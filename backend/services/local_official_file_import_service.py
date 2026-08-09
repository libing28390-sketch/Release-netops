"""ING-004 local official-file import with mandatory provenance proof.

This service accepts bytes supplied by the API boundary, never a caller
controlled filesystem path.  It validates the filename/type/magic and official
source evidence, then records a hash-only source-version manifest through the
CAT-003 registry.  Parsing and publication remain later ING phases.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from core.rbac import authorize_resource
from services.audit_service import log_audit_event
from services.ingestion_pipeline_service import (
    IngestionPipelineError,
    classify_ingestion_error,
    ingestion_pipeline,
)
from services.official_url_import_service import _ensure_source, _find_source
from services.source_registry_service import (
    SourceRegistryError,
    list_source_versions,
    record_source_version,
    validate_official_url_input,
)


_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_OFFICIAL_SOURCE_KINDS = {
    "official_url",
    "product_page",
    "configuration_guide",
    "command_reference",
    "release_note",
    "product_support",
}
_VERSION_KEYS = {"primary", "compatibility"}
_MAX_FILE_BYTES = 20_000_000
_ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".json": "application/json",
    ".xml": "application/xml",
}
_TEXT_EXTENSIONS = set(_ALLOWED_EXTENSIONS) - {".pdf"}
_TEXT_MIME_ALIASES = {"text/plain", "text/html", "text/markdown", "application/json", "application/xml"}


class LocalOfficialFileImportError(ValueError):
    """Stable, safe error for local official-file import requests."""

    def __init__(self, code: str, message: str, *, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _text(value: Any, *, field: str, maximum: int, required: bool = False) -> str:
    text = str(value or "").strip()
    if (required and not text) or len(text) > maximum or _CONTROL_RE.search(text):
        raise LocalOfficialFileImportError("IMPORT_INPUT_INVALID", f"{field} is invalid")
    return text


def _actor(user: dict[str, Any]) -> str:
    return _text(user.get("id") or user.get("user_id") or user.get("username") or "system", field="actor", maximum=256, required=True)


def _tenant(user: dict[str, Any]) -> str:
    return _text(user.get("tenant_id") or "tenant-default", field="tenant_id", maximum=128, required=True)


def _version_scope(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("version_scope")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LocalOfficialFileImportError("IMPORT_VERSION_SCOPE_INVALID", "version_scope must be valid JSON") from exc
    if not isinstance(raw, dict) or set(raw) - _VERSION_KEYS:
        raise LocalOfficialFileImportError("IMPORT_VERSION_SCOPE_INVALID", "version_scope must contain only primary and compatibility")
    return {
        "primary": _text(raw.get("primary"), field="version_scope.primary", maximum=128, required=True),
        "compatibility": _text(raw.get("compatibility"), field="version_scope.compatibility", maximum=128, required=True),
    }


def _official_metadata(payload: dict[str, Any], *, actor: str, captured_at: str) -> dict[str, Any]:
    vendor = _text(payload.get("vendor"), field="vendor", maximum=128, required=True)
    family = _text(payload.get("product_family"), field="product_family", maximum=256, required=True)
    scope = _version_scope(payload)
    terms = _text(payload.get("terms_review_status"), field="terms_review_status", maximum=32, required=True).lower()
    if terms not in {"approved", "waived", "not_required"}:
        raise LocalOfficialFileImportError("IMPORT_TERMS_REVIEW_REQUIRED", "terms_review_status must be approved, waived, or not_required", status_code=403)
    reviewer = _text(payload.get("reviewer") or actor, field="reviewer", maximum=256, required=True)
    reviewed_at = _text(payload.get("reviewed_at") or captured_at, field="reviewed_at", maximum=128, required=True)
    return {
        "vendor": vendor,
        "product_family": family,
        "version_scope": scope,
        "terms_review_status": terms,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "ingestion": {"boundary": "ING-004_local_official_file", "actor": actor},
    }


def _file_bytes(content: Any) -> bytes:
    if isinstance(content, bytes):
        data = content
    elif isinstance(content, (bytearray, memoryview)):
        data = bytes(content)
    else:
        raise LocalOfficialFileImportError("LOCAL_FILE_CONTENT_INVALID", "Local file bytes are required")
    if not data:
        raise LocalOfficialFileImportError("LOCAL_FILE_EMPTY", "Local official file cannot be empty")
    if len(data) > _MAX_FILE_BYTES:
        raise LocalOfficialFileImportError("LOCAL_FILE_TOO_LARGE", "Local official file exceeds the 20 MB limit", status_code=413)
    return data


def _filename_and_type(filename: Any, content_type: Any, data: bytes) -> tuple[str, str]:
    name = _text(filename, field="filename", maximum=255, required=True)
    if name in {".", ".."} or "/" in name or "\\" in name or name.endswith("."):
        raise LocalOfficialFileImportError("LOCAL_FILE_NAME_INVALID", "filename must be a single safe basename")
    dot = name.rfind(".")
    extension = name[dot:].lower() if dot > 0 else ""
    expected = _ALLOWED_EXTENSIONS.get(extension)
    if not expected:
        raise LocalOfficialFileImportError("LOCAL_FILE_TYPE_FORBIDDEN", "Only reviewed PDF, HTML, Markdown, TXT, JSON or XML files are accepted")
    declared = str(content_type or "").split(";", 1)[0].strip().lower()
    if declared and declared not in {"application/octet-stream", "binary/octet-stream"}:
        compatible = declared == expected or (expected == "text/markdown" and declared in _TEXT_MIME_ALIASES) or (expected in {"text/html", "text/plain"} and declared in _TEXT_MIME_ALIASES)
        if not compatible:
            raise LocalOfficialFileImportError("LOCAL_FILE_CONTENT_TYPE_MISMATCH", "Declared content type does not match the reviewed file type")
    if extension == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise LocalOfficialFileImportError("LOCAL_FILE_MAGIC_MISMATCH", "PDF magic bytes are missing")
    else:
        if b"\x00" in data[:4096]:
            raise LocalOfficialFileImportError("LOCAL_FILE_BINARY_FORBIDDEN", "Text file contains binary control bytes")
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise LocalOfficialFileImportError("LOCAL_FILE_ENCODING_INVALID", "Text file must be valid UTF-8") from exc
    return name, expected


def _audit_local(event_type: str, *, user: dict[str, Any], source: dict[str, Any], details: dict[str, Any], request_id: str = "") -> None:
    conn = None
    try:
        from database import get_db_connection

        conn = get_db_connection()
        log_audit_event(
            event_type=event_type,
            category="knowledge_source",
            severity="info" if event_type.endswith("started") or event_type.endswith("completed") else "warning",
            status="success" if event_type.endswith("completed") else "open",
            summary=f"Knowledge source {event_type.replace('_', ' ')}",
            actor_id=_actor(user),
            actor_username=str(user.get("username") or _actor(user)),
            actor_role=str(user.get("role") or "system"),
            target_type="kb_source_registry",
            target_id=str(source.get("id") or ""),
            target_name=str(source.get("name") or source.get("canonical_url") or ""),
            request_id=request_id,
            details=details,
            conn=conn,
        )
        conn.commit()
    finally:
        if conn is not None:
            conn.close()


def _error_result(job, error: BaseException, *, source: dict[str, Any] | None, request_id: str) -> dict[str, Any]:
    detail = classify_ingestion_error(error, phase=job.phase, attempt_no=job.attempt_no, correlation_id=request_id)
    job.fail(detail, actor="official-file-importer", request_id=request_id)
    return {
        "success": False,
        "job": job.to_dict(),
        "source": copy.deepcopy(source) if source else None,
        "version": None,
        "provenance": None,
        "error": detail.to_dict(),
        "continuation_required": False,
    }


def import_local_official_file(
    user: dict[str, Any],
    payload: dict[str, Any],
    *,
    content: bytes | bytearray | memoryview | None = None,
    filename: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    """Import exactly one local official file and persist its provenance proof."""
    if not isinstance(payload, dict):
        raise LocalOfficialFileImportError("IMPORT_INPUT_INVALID", "Import payload must be an object")
    actor = _actor(user)
    tenant_id = _tenant(user)
    if not authorize_resource(user, "knowledge_source", "create", tenant_id=tenant_id):
        raise LocalOfficialFileImportError("SOURCE_PERMISSION_DENIED", "Insufficient permission for local official-file import", status_code=403)
    captured_at = _now()
    data = _file_bytes(content if content is not None else payload.get("file_bytes", payload.get("content")))
    safe_filename, detected_type = _filename_and_type(filename if filename is not None else payload.get("filename"), content_type if content_type is not None else payload.get("content_type"), data)
    raw_url = _text(payload.get("source_url") or payload.get("official_url") or payload.get("url"), field="source_url", maximum=4096, required=True)
    source_kind = _text(payload.get("source_kind") or "product_page", field="source_kind", maximum=64, required=True).lower()
    if source_kind not in _OFFICIAL_SOURCE_KINDS:
        raise LocalOfficialFileImportError("IMPORT_SOURCE_KIND_INVALID", "source_kind is not an official source kind")
    metadata = _official_metadata(payload, actor=actor, captured_at=captured_at)
    try:
        preflight = validate_official_url_input(raw_url, source_kind=source_kind, metadata=metadata)
    except SourceRegistryError as exc:
        raise LocalOfficialFileImportError(exc.code, exc.message, status_code=exc.status_code, details=exc.details) from exc
    canonical_url = preflight["canonical_url"]
    content_hash = hashlib.sha256(data).hexdigest()
    evidence_url = _text(payload.get("evidence_url") or canonical_url, field="evidence_url", maximum=4096, required=True)
    if evidence_url != canonical_url:
        raise LocalOfficialFileImportError("PROVENANCE_EVIDENCE_URL_MISMATCH", "evidence_url must equal the reviewed official source URL", status_code=403)
    provenance = {
        "proof_type": "official_source_url_plus_local_content_hash",
        "source_url": canonical_url,
        "evidence_url": canonical_url,
        "filename": safe_filename,
        "content_type": detected_type,
        "content_hash": content_hash,
        "byte_size": len(data),
        "captured_at": captured_at,
        "captured_by": actor,
        "vendor": metadata["vendor"],
        "product_family": metadata["product_family"],
        "version_scope": copy.deepcopy(metadata["version_scope"]),
        "terms_review_status": metadata["terms_review_status"],
        "reviewer": metadata["reviewer"],
        "reviewed_at": metadata["reviewed_at"],
    }
    explicit_key = _text(payload.get("idempotency_key") or "", field="idempotency_key", maximum=256)
    # Keep the default idempotency scope bound to both the reviewed source and
    # the uploaded bytes.  The same bytes from a second official URL are a
    # distinct provenance candidate for the later ING-014 merge policy.
    key = explicit_key or f"official-file:{hashlib.sha256(f'{canonical_url}:{content_hash}'.encode('utf-8')).hexdigest()}"
    try:
        max_retries = int(payload.get("max_retries", 1))
    except (TypeError, ValueError) as exc:
        raise LocalOfficialFileImportError("IMPORT_RETRY_INVALID", "max_retries must be an integer") from exc
    if not 0 <= max_retries <= 5:
        raise LocalOfficialFileImportError("IMPORT_RETRY_INVALID", "max_retries must be between 0 and 5")
    scope = {"canonical_url": canonical_url, "source_kind": source_kind, "content_hash": content_hash, "version_scope": metadata["version_scope"]}
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
        raise LocalOfficialFileImportError(exc.code, exc.message, status_code=exc.status_code, details=exc.details) from exc
    request_id = _text(payload.get("request_id") or "", field="request_id", maximum=256)
    if job.execution_state in {"succeeded", "cancelled", "failed"} or job.phase == "fetched":
        replay_source = _find_source(user, canonical_url)
        replay_versions = list_source_versions(replay_source["id"], user) if replay_source else []
        replay_version = next((item for item in replay_versions if str(item.get("content_hash") or "") == content_hash), replay_versions[0] if replay_versions else None)
        return {
            "success": job.execution_state not in {"failed", "cancelled"},
            "job": job.to_dict(),
            "source": replay_source,
            "version": replay_version,
            "provenance": (replay_version or {}).get("metadata", {}).get("provenance") if replay_version else provenance,
            "replayed": True,
            "continuation_required": job.phase == "fetched" and job.execution_state == "running",
        }
    worker_id = f"official-file-importer:{job.id}"
    source: dict[str, Any] | None = None
    try:
        job.claim(worker_id, request_id=request_id)
        job.advance_phase("scoped", actor=worker_id, request_id=request_id)
        source, _created = _ensure_source(
            user,
            canonical_url=canonical_url,
            source_kind=source_kind,
            source_metadata=metadata,
            name=_text(payload.get("name") or safe_filename, field="name", maximum=256),
            description=_text(payload.get("description") or "Local official file import source", field="description", maximum=4_000),
        )
        _audit_local(
            "local_file_import_started",
            user=user,
            source=source,
            request_id=request_id,
            details={"filename": safe_filename, "content_type": detected_type, "byte_size": len(data), "content_hash": content_hash},
        )
        version = record_source_version(
            source["id"],
            {
                "content": data,
                "fetched_at": captured_at,
                "parser_name": "local-file-boundary",
                "parser_version": "1.0.0",
                "fetch_url": canonical_url,
                "response_content_type": detected_type,
                "raw_content_ref": f"local_upload_sha256:{content_hash}",
                "raw_content_storage": "hash_only_memory_boundary",
                "verification_method": "ing004_official_provenance_v1",
                "metadata": {"provenance": provenance},
                "status": "fetched",
            },
            user,
        )
        job.advance_phase("fetched", actor=worker_id, request_id=request_id, evidence={"source_id": source["id"], "source_version_id": version.get("id"), "content_hash": content_hash})
        job.update_progress(total_count=1, processed_count=0, actor=worker_id, request_id=request_id)
        _audit_local(
            "local_file_import_completed",
            user=user,
            source=source,
            request_id=request_id,
            details={"source_version_id": version.get("id"), "filename": safe_filename, "content_type": detected_type, "byte_size": len(data), "content_hash": content_hash},
        )
        return {
            "success": True,
            "job": job.to_dict(),
            "source": source,
            "version": version,
            "provenance": provenance,
            "replayed": False,
            "continuation_required": True,
        }
    except (SourceRegistryError, IngestionPipelineError) as exc:
        if source:
            _audit_local("local_file_import_failed", user=user, source=source, request_id=request_id, details={"code": getattr(exc, "code", "IMPORT_FAILED")})
        return _error_result(job, exc, source=source, request_id=request_id)
    except Exception as exc:
        if source:
            _audit_local("local_file_import_failed", user=user, source=source, request_id=request_id, details={"code": "IMPORT_FAILED"})
        return _error_result(job, exc, source=source, request_id=request_id)


__all__ = ["LocalOfficialFileImportError", "import_local_official_file"]
