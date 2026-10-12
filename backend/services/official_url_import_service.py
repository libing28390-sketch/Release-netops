"""ING-002 single official URL import task.

This adapter composes the CAT-003 source registry, CAT-004 safe outbound
fetcher, ING-001 control-plane state machine, and the additive ING-013
Document Version boundary.  It fetches exactly one reviewed URL and records
immutable source/document-version facts.  Parsing, chunking, embedding, and
publication remain explicit continuation phases owned by later ING tasks.
"""

from __future__ import annotations

import copy
import hashlib
import re
from typing import Any
from urllib.parse import urlsplit

from services.ingestion_pipeline_service import (
    IngestionPipelineError,
    classify_ingestion_error,
    ingestion_pipeline,
)
from services.ingestion_idempotency_service import build_url_idempotency_key
from services.document_version_service import DocumentVersionError, record_document_version
from services.document_content_cleaning import parse_and_clean_document
from services.official_document_publisher import publish_official_document
from services.knowledge_v1_source_service import (
    SourceRegistryError,
    collect_source,
    create_source,
    enable_source,
    list_sources,
    list_source_versions,
    validate_official_url_input,
    validate_source,
)


_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_OFFICIAL_SOURCE_KINDS = {"official_url", "product_page", "configuration_guide", "command_reference", "release_note", "troubleshooting_guide", "product_support"}
_VERSION_KEYS = {"primary", "compatibility"}


class OfficialUrlImportError(ValueError):
    """Stable input/service error for one-URL import requests."""

    def __init__(self, code: str, message: str, *, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def _text(value: Any, *, field: str, maximum: int, required: bool = False) -> str:
    text = str(value or "").strip()
    if (required and not text) or len(text) > maximum or _CONTROL_RE.search(text):
        raise OfficialUrlImportError("IMPORT_INPUT_INVALID", f"{field} is invalid")
    return text


def _tenant(user: dict[str, Any]) -> str:
    tenant = _text(user.get("tenant_id") or "tenant-default", field="tenant_id", maximum=128, required=True)
    return tenant


def _metadata(payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
    vendor = _text(payload.get("vendor"), field="vendor", maximum=128, required=True)
    family = _text(payload.get("product_family"), field="product_family", maximum=256, required=True)
    raw_scope = payload.get("version_scope")
    if not isinstance(raw_scope, dict) or set(raw_scope) - _VERSION_KEYS:
        raise OfficialUrlImportError("IMPORT_VERSION_SCOPE_INVALID", "version_scope must contain only primary and compatibility")
    version_scope = {
        "primary": _text(raw_scope.get("primary"), field="version_scope.primary", maximum=128, required=True),
        "compatibility": _text(raw_scope.get("compatibility"), field="version_scope.compatibility", maximum=128, required=True),
    }
    terms = _text(payload.get("terms_review_status"), field="terms_review_status", maximum=32, required=True).lower()
    if terms not in {"approved", "waived", "not_required"}:
        raise OfficialUrlImportError("IMPORT_TERMS_REVIEW_REQUIRED", "terms_review_status must be approved, waived, or not_required", status_code=403)
    return {
        "vendor": vendor,
        "product_family": family,
        "version_scope": version_scope,
        "terms_review_status": terms,
        "reviewer": _text(payload.get("reviewer") or actor, field="reviewer", maximum=256, required=True),
        "reviewed_at": _text(payload.get("reviewed_at") or "", field="reviewed_at", maximum=128),
        "product_series": _text(payload.get("product_series"), field="product_series", maximum=256),
        "product_model": _text(payload.get("product_model"), field="product_model", maximum=256),
        "platform_code": _text(payload.get("platform_code"), field="platform_code", maximum=128),
        "os_family": _text(payload.get("os_family"), field="os_family", maximum=128),
        "os_generation": _text(payload.get("os_generation"), field="os_generation", maximum=128),
        # A reviewed source may carry an explicit feature scope.  Keep it
        # optional: broad vendor command references must remain unscoped
        # unless the reviewer has supplied a real feature binding.
        "feature": _text(payload.get("feature"), field="feature", maximum=128),
        "feature_domain": _text(payload.get("feature_domain"), field="feature_domain", maximum=128),
        "document_category": _text(payload.get("document_category"), field="document_category", maximum=64),
        "ingestion": {"boundary": "ING-002_single_official_url", "actor": actor},
    }


def _error_result(job, error: BaseException, *, source: dict[str, Any] | None = None, request_id: str = "") -> dict[str, Any]:
    detail = classify_ingestion_error(error, phase=job.phase, attempt_no=job.attempt_no, correlation_id=request_id)
    job.fail(detail, actor="official-url-importer", request_id=request_id)
    return {
        "success": False,
        "job": job.to_dict(),
        "source": copy.deepcopy(source) if source else None,
        "error": detail.to_dict(),
        "continuation_required": False,
    }


def _find_source(user: dict[str, Any], canonical_url: str) -> dict[str, Any] | None:
    tenant = _tenant(user)
    for row in list_sources(user, status="all", tenant_id=tenant):
        if str(row.get("canonical_url") or "") == canonical_url:
            return row
    return None


def _ensure_source(
    user: dict[str, Any],
    *,
    canonical_url: str,
    source_kind: str,
    source_metadata: dict[str, Any],
    name: str,
    description: str,
) -> tuple[dict[str, Any], bool]:
    existing = _find_source(user, canonical_url)
    created = False
    if existing is None:
        source_type = "official_vendor" if source_kind == "official_url" else "official_product"
        try:
            existing = create_source(
                {
                    "source_type": source_type,
                    "source_kind": source_kind,
                    "canonical_url": canonical_url,
                    "allowed_host": urlsplit(canonical_url).hostname,
                    "name": name,
                    "description": description,
                    "trust_level": "official",
                    "metadata": source_metadata,
                },
                user,
            )
            created = True
        except SourceRegistryError as exc:
            if exc.code != "SOURCE_URL_CONFLICT":
                raise
            existing = _find_source(user, canonical_url)
            if existing is None:
                raise
    status = str(existing.get("status") or "")
    if status in {"archived", "deleted", "purged", "quarantined"}:
        raise SourceRegistryError("SOURCE_NOT_COLLECTABLE", "The official source is not collectable in its current lifecycle state", status_code=409)
    if status != "active" or not bool(existing.get("fetch_enabled")) or str(existing.get("validation_status") or "") != "valid":
        validation = validate_source(existing["id"], user)
        if not validation.get("valid"):
            raise SourceRegistryError("SOURCE_VALIDATION_FAILED", "The official source failed the source registry gate", status_code=403, details=validation)
        existing = enable_source(existing["id"], user)
    return existing, created


def import_single_official_url(
    user: dict[str, Any],
    payload: dict[str, Any],
    *,
    transport: Any = None,
    resolver: Any = None,
    client_factory: Any = None,
    operational_policy: bool = False,
    backoff_base_seconds: float = 0.0,
    sleeper: Any = None,
) -> dict[str, Any]:
    """Create or replay one URL import and persist its source-version manifest.

    ``transport``, ``resolver`` and ``client_factory`` are test-only injection
    points; the HTTP API never exposes them.
    """
    if not isinstance(payload, dict):
        raise OfficialUrlImportError("IMPORT_INPUT_INVALID", "Import payload must be an object")
    actor = _text(user.get("id") or user.get("username") or "system", field="actor", maximum=256, required=True)
    tenant_id = _tenant(user)
    raw_url = payload.get("url") or payload.get("canonical_url")
    raw_url = _text(raw_url, field="url", maximum=4096, required=True)
    source_kind = _text(payload.get("source_kind") or "product_page", field="source_kind", maximum=64, required=True).lower()
    if source_kind not in _OFFICIAL_SOURCE_KINDS:
        raise OfficialUrlImportError("IMPORT_SOURCE_KIND_INVALID", "source_kind is not an official source kind")
    source_metadata = _metadata(payload, actor=actor)
    publish_requested = bool(payload.get("publish_to_knowledge_base"))
    try:
        preflight = validate_official_url_input(raw_url, source_kind=source_kind, metadata=source_metadata)
    except SourceRegistryError as exc:
        raise OfficialUrlImportError(exc.code, exc.message, status_code=exc.status_code, details=exc.details) from exc
    if not preflight.get("valid"):
        raise OfficialUrlImportError(
            "OFFICIAL_URL_NOT_ALLOWLISTED",
            "The official URL is outside the approved source allowlist",
            status_code=403,
            details={
                "host": preflight.get("host"),
                "path": preflight.get("path"),
                "source_kind": preflight.get("source_kind"),
                "reasons": preflight.get("reasons") or [],
            },
        )
    canonical_url = preflight["canonical_url"]
    explicit_key = _text(payload.get("idempotency_key") or "", field="idempotency_key", maximum=256)
    key = explicit_key or build_url_idempotency_key(canonical_url)
    max_retries_raw = payload.get("max_retries", 1)
    try:
        max_retries = int(max_retries_raw)
    except (TypeError, ValueError) as exc:
        raise OfficialUrlImportError("IMPORT_RETRY_INVALID", "max_retries must be an integer") from exc
    if not 0 <= max_retries <= 5:
        raise OfficialUrlImportError("IMPORT_RETRY_INVALID", "max_retries must be between 0 and 5")
    scope = {"canonical_url": canonical_url, "source_kind": source_kind, "version_scope": source_metadata["version_scope"]}
    try:
        job = ingestion_pipeline.create_job(
            tenant_id=tenant_id,
            job_kind="document_import",
            idempotency_key=key,
            scope=scope,
            max_retries=max_retries,
            actor=actor,
        )
    except IngestionPipelineError as exc:
        raise OfficialUrlImportError(exc.code, exc.message, status_code=exc.status_code, details=exc.details) from exc
    if job.execution_state in {"succeeded", "cancelled", "failed"} or job.phase == "fetched":
        replay_source = _find_source(user, canonical_url)
        replay_versions = list_source_versions(replay_source["id"], user) if replay_source else []
        replay_version = replay_versions[0] if replay_versions else None
        replay_document = None
        if replay_source and replay_version:
            try:
                replay_document = record_document_version(replay_source, replay_version, user)
            except DocumentVersionError:
                # A legacy job may predate the V2 shadow tables.  Do not turn
                # a safe source-job replay into a destructive retry.
                replay_document = None
        return {
            "success": job.execution_state not in {"failed", "cancelled"},
            "job": job.to_dict(),
            "source": replay_source,
            "version": replay_version,
            "document": (replay_document or {}).get("document"),
            "document_version": (replay_document or {}).get("document_version"),
            "document_version_decision": (replay_document or {}).get("decision"),
            "source_observation": (replay_document or {}).get("source_observation"),
            "merged": bool((replay_document or {}).get("merged")),
            "fetch": None,
            "replayed": True,
            "idempotency": (replay_version or {}).get("idempotency") or {"decision": "replay_same_url_same_content", "replayed": True},
            "continuation_required": job.phase == "fetched" and job.execution_state == "running",
        }
    worker_id = f"official-url-importer:{job.id}"
    request_id = _text(payload.get("request_id") or "", field="request_id", maximum=256)
    try:
        job.claim(worker_id, request_id=request_id)
        job.advance_phase("scoped", actor=worker_id, request_id=request_id)
        source_name = _text(payload.get("name") or f"Official URL {urlsplit(canonical_url).hostname}", field="name", maximum=256)
        description = _text(payload.get("description") or "Single official URL import source", field="description", maximum=4_000)
        source, _created = _ensure_source(
            user,
            canonical_url=canonical_url,
            source_kind=source_kind,
            source_metadata=source_metadata,
            name=source_name,
            description=description,
        )
        captured: dict[str, Any] = {}

        def _capture(body: bytes, response_content_type: str) -> None:
            captured["content"] = body
            captured["content_type"] = response_content_type

        result = collect_source(
            source["id"],
            {"method": "GET"},
            user,
            transport=transport,
            resolver=resolver,
            client_factory=client_factory,
            operational_policy=operational_policy,
            backoff_base_seconds=backoff_base_seconds,
            sleeper=sleeper,
            content_sink=_capture if publish_requested else None,
        )
        version = result.get("version") or {}
        cleaned = None
        raw_content = captured.get("content") if publish_requested else None
        if publish_requested:
            if not isinstance(raw_content, bytes) or not raw_content:
                raise OfficialUrlImportError("PUBLISH_CONTENT_EMPTY", "Official source content is empty")
            cleaned = parse_and_clean_document(
                raw_content,
                # MIME/magic detection owns the format; leaving the filename
                # empty avoids declaring HTML for a text/PDF response.
                filename="",
                content_type=str(captured.get("content_type") or version.get("response_content_type") or ""),
            )
            if not str(cleaned.text or "").strip():
                raise OfficialUrlImportError("PUBLISH_CONTENT_EMPTY", "Official source has no searchable text")
        raw_for_document = None
        if isinstance(raw_content, bytes):
            raw_hash = hashlib.sha256(raw_content).hexdigest()
            if raw_hash == str(version.get("content_hash") or "") and len(raw_content) == int(version.get("byte_size") or 0):
                try:
                    raw_content.decode("utf-8")
                    raw_for_document = raw_content
                except UnicodeDecodeError:
                    # PDF/binary sources retain the immutable source reference
                    # in V2; the searchable normalized text is still indexed
                    # by the local projection below.
                    raw_for_document = None
        document_result = record_document_version(
            source,
            version,
            user,
            metadata={"source_kind": source_kind, **source_metadata},
            original_content=raw_for_document,
            normalized_content=cleaned.text if cleaned is not None else None,
            collection_id=payload.get("collection_id") or payload.get("knowledge_base_id"),
            document_kind=(
                "command_reference"
                if source_kind == "command_reference"
                else ("troubleshooting" if source_kind == "troubleshooting_guide" else "official_manual")
            ),
        )
        job.advance_phase(
            "fetched",
            actor=worker_id,
            request_id=request_id,
            evidence={
                "source_id": source["id"],
                "source_version_id": version.get("id"),
                "document_id": (document_result.get("document") or {}).get("id"),
                "document_version_id": (document_result.get("document_version") or {}).get("id"),
            },
        )
        if publish_requested:
            publication = publish_official_document(
                user=user,
                source=source,
                source_version=version,
                raw_content=raw_content,
                content_type=str(captured.get("content_type") or version.get("response_content_type") or ""),
                source_kind=source_kind,
                payload=payload,
                cleaned=cleaned,
            )
            job.advance_phase("parsed", actor=worker_id, request_id=request_id, evidence={"parser": publication.get("parser_name"), "parser_version": publication.get("parser_version")})
            job.advance_phase("normalized", actor=worker_id, request_id=request_id, evidence={"cleaner": publication.get("cleaner_name"), "cleaner_version": publication.get("cleaner_version")})
            job.advance_phase("classified", actor=worker_id, request_id=request_id, evidence={"document_category": (payload.get("document_category") or source_kind), "official_only": True})
            job.advance_phase("chunked", actor=worker_id, request_id=request_id, evidence={"chunk_count": int(publication.get("chunk_count") or 0)})
            job.advance_phase("embedded", actor=worker_id, request_id=request_id, evidence={"embedding": "knowledge_service"})
            job.advance_phase("indexed", actor=worker_id, request_id=request_id, evidence={"projection": "ai_document/ai_document_chunk"})
            job.advance_phase("validated", actor=worker_id, request_id=request_id, evidence={"content_hash": publication.get("content_hash")})
            job.advance_phase("committed", actor=worker_id, request_id=request_id, evidence={"document_id": publication.get("document_id")})
            job.update_progress(total_count=1, processed_count=1, parsed_count=1, succeeded_count=1, actor=worker_id, request_id=request_id)
            job.advance_phase("completed", actor=worker_id, request_id=request_id, evidence={"published": True})
            job.transition_execution_state("succeeded", actor=worker_id, request_id=request_id)
        else:
            # The source manifest is complete, but parser/chunk/index phases
            # remain an explicit continuation for the legacy API contract.
            publication = None
            job.update_progress(total_count=1, processed_count=0, actor=worker_id, request_id=request_id)
        replayed = bool(
            version.get("deduplicated")
            or version.get("idempotency", {}).get("replayed")
            or document_result.get("replayed")
        )
        return {
            "success": True,
            "job": job.to_dict(),
            "source": source,
            "fetch": result.get("fetch"),
            "policy": result.get("policy") or {},
            "version": version,
            "document": document_result.get("document"),
            "document_version": document_result.get("document_version"),
            "document_version_decision": document_result.get("decision"),
            "source_observation": document_result.get("source_observation"),
            "merged": bool(document_result.get("merged")),
            "idempotency": version.get("idempotency") or {"decision": "new_version", "replayed": replayed},
            "replayed": replayed,
            "publication": publication,
            "published": bool(publication),
            "continuation_required": False if publish_requested else not replayed,
        }
    except (SourceRegistryError, IngestionPipelineError) as exc:
        source = locals().get("source")
        return _error_result(job, exc, source=source, request_id=request_id)
    except Exception as exc:
        source = locals().get("source")
        return _error_result(job, exc, source=source, request_id=request_id)


__all__ = ["OfficialUrlImportError", "import_single_official_url"]
