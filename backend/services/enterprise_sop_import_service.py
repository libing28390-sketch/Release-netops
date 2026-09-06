"""ING-005 enterprise SOP local-file import.

Enterprise SOPs are a separate trust/domain boundary from official vendor
knowledge.  The caller supplies bytes and descriptive ownership metadata; the
service creates a server-owned internal source URI, forces INTERNAL
classification, and records a hash-only immutable Source Version manifest.
There is no external URL and no network request in this flow.
"""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timezone
from typing import Any

from core.rbac import authorize_resource
from services.audit_service import log_audit_event
from services.ingestion_pipeline_service import (
    IngestionPipelineError,
    classify_ingestion_error,
    ingestion_pipeline,
)
from services.local_official_file_import_service import LocalOfficialFileImportError, _file_bytes, _filename_and_type
from services.knowledge_v1_source_service import (
    SourceRegistryError,
    create_source,
    disable_source,
    enable_source,
    list_source_versions,
    record_source_version,
    validate_source,
)


class EnterpriseSopImportError(ValueError):
    """Stable, redacted error for enterprise SOP imports."""

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
    if (required and not text) or len(text) > maximum or any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise EnterpriseSopImportError("IMPORT_INPUT_INVALID", f"{field} is invalid")
    return text


def _actor(user: dict[str, Any]) -> str:
    return _text(user.get("id") or user.get("user_id") or user.get("username") or "system", field="actor", maximum=256, required=True)


def _tenant(user: dict[str, Any]) -> str:
    return _text(user.get("tenant_id") or "tenant-default", field="tenant_id", maximum=128, required=True)


def _audit(event_type: str, *, user: dict[str, Any], source: dict[str, Any], details: dict[str, Any], request_id: str = "") -> None:
    from database import get_db_connection

    conn = get_db_connection()
    try:
        log_audit_event(
            event_type=event_type,
            category="knowledge_source",
            severity="info" if event_type.endswith("started") or event_type.endswith("completed") else "warning",
            status="success" if event_type.endswith("completed") else "open",
            summary=f"Knowledge source {event_type.replace('_', ' ')}",
            actor_id=_actor(user),
            actor_username=str(user.get("username") or _actor(user)),
            actor_role=str(user.get("role") or "system"),
        target_type="knowledge_source",
            target_id=str(source.get("id") or ""),
            target_name=str(source.get("name") or source.get("canonical_url") or ""),
            request_id=request_id,
            details=details,
            conn=conn,
        )
        conn.commit()
    finally:
        conn.close()


def _find_source(canonical_url: str, tenant_id: str) -> dict[str, Any] | None:
    from services.knowledge_v1_source_service import list_sources

    user = {"id": "system", "username": "system", "role": "Administrator", "tenant_id": tenant_id}
    return next((item for item in list_sources(user, status="all", tenant_id=tenant_id) if str(item.get("canonical_url") or "") == canonical_url), None)


def _ensure_source(user: dict[str, Any], *, canonical_url: str, metadata: dict[str, Any], title: str, description: str) -> dict[str, Any]:
    tenant_id = _tenant(user)
    source = _find_source(canonical_url, tenant_id)
    if source is None:
        source = create_source(
            {
                "source_type": "enterprise",
                "source_kind": "enterprise",
                "canonical_url": canonical_url,
                "allowed_host": "internal.nexora.local",
                "name": title,
                "description": description,
                "trust_level": "internal",
                "metadata": metadata,
            },
            user,
        )
    if str(source.get("status") or "") in {"archived", "deleted", "purged", "quarantined"}:
        raise SourceRegistryError("SOURCE_NOT_COLLECTABLE", "The enterprise SOP source is not collectable in its current lifecycle state", status_code=409)
    if str(source.get("status") or "") != "active" or not bool(source.get("fetch_enabled")) or str(source.get("validation_status") or "") != "valid":
        validation = validate_source(source["id"], user)
        if not validation.get("valid"):
            raise SourceRegistryError("SOURCE_VALIDATION_FAILED", "The enterprise SOP source failed the source registry gate", status_code=403, details=validation)
        source = enable_source(source["id"], user)
    return source


def _error_result(job, error: BaseException, *, source: dict[str, Any] | None, request_id: str) -> dict[str, Any]:
    detail = classify_ingestion_error(error, phase=job.phase, attempt_no=job.attempt_no, correlation_id=request_id)
    job.fail(detail, actor="enterprise-sop-importer", request_id=request_id)
    return {
        "success": False,
        "job": job.to_dict(),
        "source": copy.deepcopy(source) if source else None,
        "version": None,
        "provenance": None,
        "classification": "INTERNAL",
        "error": detail.to_dict(),
        "continuation_required": False,
    }


def import_enterprise_sop_file(
    user: dict[str, Any],
    payload: dict[str, Any],
    *,
    content: bytes | bytearray | memoryview | None = None,
    filename: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    """Import one tenant-owned SOP and force its classification to INTERNAL."""
    if not isinstance(payload, dict):
        raise EnterpriseSopImportError("IMPORT_INPUT_INVALID", "Import payload must be an object")
    actor = _actor(user)
    tenant_id = _tenant(user)
    if not authorize_resource(user, "knowledge_source", "create", tenant_id=tenant_id):
        raise EnterpriseSopImportError("SOURCE_PERMISSION_DENIED", "Insufficient permission for enterprise SOP import", status_code=403)
    if payload.get("source_url") or payload.get("official_url") or payload.get("url"):
        raise EnterpriseSopImportError("SOP_EXTERNAL_SOURCE_FORBIDDEN", "Enterprise SOP import cannot accept an external source URL", status_code=403)
    classification = str(payload.get("classification") or "INTERNAL").strip().upper()
    if classification != "INTERNAL":
        raise EnterpriseSopImportError("SOP_CLASSIFICATION_FORBIDDEN", "Enterprise SOP imports are forced to INTERNAL classification", status_code=403)
    try:
        data = _file_bytes(content if content is not None else payload.get("file_bytes", payload.get("content")))
    except LocalOfficialFileImportError as exc:
        raise EnterpriseSopImportError(exc.code, exc.message, status_code=exc.status_code, details=exc.details) from exc
    try:
        safe_filename, detected_type = _filename_and_type(filename if filename is not None else payload.get("filename"), content_type if content_type is not None else payload.get("content_type"), data)
    except ValueError as exc:
        if hasattr(exc, "code"):
            raise EnterpriseSopImportError(exc.code, exc.message, status_code=getattr(exc, "status_code", 400), details=getattr(exc, "details", None)) from exc
        raise
    title = _text(payload.get("title") or payload.get("name") or safe_filename, field="title", maximum=256, required=True)
    description = _text(payload.get("description") or "Enterprise SOP local import", field="description", maximum=4_000)
    owner = _text(payload.get("owner") or actor, field="owner", maximum=256, required=True)
    department = _text(payload.get("department") or "network-operations", field="department", maximum=256, required=True)
    captured_at = _now()
    content_hash = hashlib.sha256(data).hexdigest()
    tenant_key = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:24]
    canonical_url = f"https://internal.nexora.local/tenant/{tenant_key}/enterprise-sop/{content_hash}"
    provenance = {
        "proof_type": "tenant_owned_local_file_hash",
        "source_url": canonical_url,
        "filename": safe_filename,
        "content_type": detected_type,
        "content_hash": content_hash,
        "byte_size": len(data),
        "captured_at": captured_at,
        "captured_by": actor,
        "owner": owner,
        "department": department,
        "classification": "INTERNAL",
    }
    metadata = {
        "knowledge_domain": "enterprise",
        "document_kind": "enterprise_sop",
        "classification": "INTERNAL",
        "trust_level": "internal",
        "owner": owner,
        "department": department,
        "source_authority": "tenant_owned",
        "provenance": provenance,
        "ingestion": {"boundary": "ING-005_enterprise_sop", "actor": actor},
    }
    explicit_key = _text(payload.get("idempotency_key") or "", field="idempotency_key", maximum=256)
    key = explicit_key or f"enterprise-sop:{hashlib.sha256(f'{canonical_url}:{content_hash}'.encode('utf-8')).hexdigest()}"
    try:
        max_retries = int(payload.get("max_retries", 1))
    except (TypeError, ValueError) as exc:
        raise EnterpriseSopImportError("IMPORT_RETRY_INVALID", "max_retries must be an integer") from exc
    if not 0 <= max_retries <= 5:
        raise EnterpriseSopImportError("IMPORT_RETRY_INVALID", "max_retries must be between 0 and 5")
    scope = {"canonical_url": canonical_url, "source_kind": "enterprise", "content_hash": content_hash, "classification": "INTERNAL"}
    try:
        job = ingestion_pipeline.create_job(tenant_id=tenant_id, job_kind="document_import", idempotency_key=key, scope=scope, max_retries=max_retries, actor=actor)
    except IngestionPipelineError as exc:
        raise EnterpriseSopImportError(exc.code, exc.message, status_code=exc.status_code, details=exc.details) from exc
    request_id = _text(payload.get("request_id") or "", field="request_id", maximum=256)
    if job.execution_state in {"succeeded", "cancelled", "failed"} or job.phase == "fetched":
        replay_source = _find_source(canonical_url, tenant_id)
        versions = list_source_versions(replay_source["id"], user) if replay_source else []
        replay_version = next((item for item in versions if str(item.get("content_hash") or "") == content_hash), versions[0] if versions else None)
        return {
            "success": job.execution_state not in {"failed", "cancelled"},
            "job": job.to_dict(),
            "source": replay_source,
            "version": replay_version,
            "provenance": (replay_version or {}).get("metadata", {}).get("provenance") if replay_version else provenance,
            "classification": "INTERNAL",
            "replayed": True,
            "continuation_required": job.phase == "fetched" and job.execution_state == "running",
        }
    worker_id = f"enterprise-sop-importer:{job.id}"
    source: dict[str, Any] | None = None
    try:
        job.claim(worker_id, request_id=request_id)
        job.advance_phase("scoped", actor=worker_id, request_id=request_id)
        source = _ensure_source(user, canonical_url=canonical_url, metadata=metadata, title=title, description=description)
        _audit("enterprise_sop_import_started", user=user, source=source, request_id=request_id, details={"filename": safe_filename, "content_type": detected_type, "byte_size": len(data), "content_hash": content_hash, "classification": "INTERNAL"})
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
                "verification_method": "ing005_enterprise_internal_v1",
                "metadata": metadata,
                "status": "fetched",
            },
            user,
        )
        # Enterprise SOPs are local-only.  Keep the immutable version readable
        # but disable the registry row before returning so a generic source
        # fetch route cannot turn the synthetic URI into an egress attempt.
        source = disable_source(source["id"], user, reason="enterprise_sop_local_only")
        job.advance_phase("fetched", actor=worker_id, request_id=request_id, evidence={"source_id": source["id"], "source_version_id": version.get("id"), "content_hash": content_hash, "classification": "INTERNAL"})
        job.update_progress(total_count=1, processed_count=0, actor=worker_id, request_id=request_id)
        _audit("enterprise_sop_import_completed", user=user, source=source, request_id=request_id, details={"source_version_id": version.get("id"), "content_hash": content_hash, "byte_size": len(data), "classification": "INTERNAL"})
        return {
            "success": True,
            "job": job.to_dict(),
            "source": source,
            "version": version,
            "provenance": provenance,
            "classification": "INTERNAL",
            "replayed": False,
            "continuation_required": True,
        }
    except (SourceRegistryError, IngestionPipelineError) as exc:
        if source:
            _audit("enterprise_sop_import_failed", user=user, source=source, request_id=request_id, details={"code": getattr(exc, "code", "IMPORT_FAILED"), "classification": "INTERNAL"})
        return _error_result(job, exc, source=source, request_id=request_id)
    except Exception as exc:
        if source:
            _audit("enterprise_sop_import_failed", user=user, source=source, request_id=request_id, details={"code": "IMPORT_FAILED", "classification": "INTERNAL"})
        return _error_result(job, exc, source=source, request_id=request_id)


__all__ = ["EnterpriseSopImportError", "import_enterprise_sop_file"]
