"""ING-002 single official URL import API."""

from __future__ import annotations

import logging
import json
import copy
from typing import Any

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from core.rbac import require_permission
from services.enterprise_sop_import_service import EnterpriseSopImportError, import_enterprise_sop_file
from services.local_official_file_import_service import LocalOfficialFileImportError, import_local_official_file
from services.official_url_import_service import OfficialUrlImportError, import_single_official_url
from services.ingestion_pipeline_service import IngestionPipelineError, ingestion_pipeline


router = APIRouter(prefix="/knowledge-v2/ingestion", tags=["knowledge-v2-ingestion"])
logger = logging.getLogger(__name__)


class OfficialUrlImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., min_length=8, max_length=4096)
    source_kind: str = Field(default="product_page", min_length=1, max_length=64)
    vendor: str = Field(..., min_length=1, max_length=128)
    product_family: str = Field(..., min_length=1, max_length=256)
    version_scope: dict[str, str] = Field(...)
    terms_review_status: str = Field(..., min_length=1, max_length=32)
    reviewer: str = Field(default="", max_length=256)
    reviewed_at: str = Field(default="", max_length=128)
    name: str = Field(default="", max_length=256)
    description: str = Field(default="", max_length=4000)
    idempotency_key: str = Field(default="", max_length=256)
    request_id: str = Field(default="", max_length=256)
    max_retries: int = Field(default=1, ge=0, le=5)


class IngestionJobCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=1024)
    request_id: str = Field(default="", max_length=256)


class IngestionJobRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default="", max_length=256)


def _job_actor(user: dict[str, Any]) -> str:
    return str(user.get("id") or user.get("user_id") or user.get("username") or "system").strip() or "system"


def _job_tenant(user: dict[str, Any]) -> str:
    return str(user.get("tenant_id") or "tenant-default").strip() or "tenant-default"


def _call_job_control(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except IngestionPipelineError as exc:
        detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.details is not None:
            detail["details"] = exc.details
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Knowledge V2 ingestion job operation failed")
        raise HTTPException(status_code=500, detail={"code": "INGESTION_JOB_ERROR", "message": "Ingestion job operation failed"}) from exc


def _public_job_snapshot(job: Any) -> dict[str, Any]:
    if hasattr(job, "to_public_dict"):
        return job.to_public_dict()
    result = copy.deepcopy(job if isinstance(job, dict) else {})
    result["lease_held"] = bool(result.get("lease_owner"))
    result["lease_owner"] = ""
    result.pop("fencing_token", None)
    for event in result.get("audit_events", []):
        if isinstance(event, dict):
            event.pop("fencing_token", None)
            event.pop("lease_owner", None)
    return result


def _public_import_result(result: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(result)
    if isinstance(value.get("job"), dict):
        value["job"] = _public_job_snapshot(value["job"])
    return value


@router.get("/jobs")
def api_list_ingestion_jobs(
    execution_state: str = Query(default="", max_length=32),
    user=require_permission("knowledge_import", "read"),
):
    """Return tenant-scoped progress snapshots; counters remain server-owned."""
    rows = ingestion_pipeline.list_jobs(tenant_id=_job_tenant(user), execution_state=execution_state)
    return {"success": True, "data": [_public_job_snapshot(row) for row in rows], "count": len(rows)}


@router.get("/jobs/{job_id}")
def api_get_ingestion_job(
    job_id: str,
    user=require_permission("knowledge_import", "read"),
):
    job = ingestion_pipeline.get_job(job_id, tenant_id=_job_tenant(user))
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "The ingestion job was not found"})
    return {"success": True, "data": _public_job_snapshot(job)}


@router.get("/jobs/{job_id}/errors")
def api_get_ingestion_job_errors(
    job_id: str,
    user=require_permission("knowledge_import", "read"),
):
    job = ingestion_pipeline.get_job(job_id, tenant_id=_job_tenant(user))
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "The ingestion job was not found"})
    snapshot = _public_job_snapshot(job)
    return {
        "success": True,
        "data": {
            "job_id": job.id,
            "phase": job.phase,
            "execution_state": job.execution_state,
            "last_error_code": job.last_error_code,
            "last_error_at": snapshot.get("last_error_at"),
            "error_count": job.error_count,
            "errors": snapshot.get("errors", []),
        },
    }


@router.post("/jobs/{job_id}/cancel")
def api_cancel_ingestion_job(
    job_id: str,
    payload: IngestionJobCancelRequest | None = Body(default=None),
    user=require_permission("knowledge_import", "cancel"),
):
    body = payload or IngestionJobCancelRequest()
    job = _call_job_control(
        ingestion_pipeline.request_cancel,
        job_id,
        tenant_id=_job_tenant(user),
        actor=_job_actor(user),
        reason=body.reason,
        request_id=body.request_id,
    )
    return {"success": True, "data": _public_job_snapshot(job), "message": "Ingestion cancellation accepted"}


@router.post("/jobs/{job_id}/retry")
def api_retry_ingestion_job(
    job_id: str,
    payload: IngestionJobRetryRequest | None = Body(default=None),
    user=require_permission("knowledge_import", "retry"),
):
    body = payload or IngestionJobRetryRequest()
    job = _call_job_control(
        ingestion_pipeline.retry_job,
        job_id,
        tenant_id=_job_tenant(user),
        actor=_job_actor(user),
        request_id=body.request_id,
    )
    return {"success": True, "data": _public_job_snapshot(job), "message": "Ingestion retry accepted"}


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except OfficialUrlImportError as exc:
        detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.details is not None:
            detail["details"] = exc.details
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Official URL import operation failed")
        raise HTTPException(status_code=500, detail={"code": "INGESTION_IMPORT_ERROR", "message": "Official URL import operation failed"}) from exc


@router.post("/official-url")
def api_import_official_url(
    response: Response,
    payload: OfficialUrlImportRequest = Body(...),
    user=require_permission("knowledge_source", "create"),
):
    result = _public_import_result(_call(import_single_official_url, user, payload.model_dump(exclude_none=True)))
    status = 202 if result.get("success") and result.get("continuation_required") else (200 if result.get("success") else 502)
    response.status_code = status
    # Keep the job error in the response body for retry/observability instead
    # of converting a bounded source failure into an opaque server exception.
    return {"success": bool(result.get("success")), "data": result, "message": "Official URL import accepted" if status == 202 else "Official URL import failed"}


async def _read_local_file(file: UploadFile) -> bytes:
    """Read one upload with a hard 20 MB ceiling before service validation."""
    limit = 20_000_000
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(min(1024 * 1024, limit + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise LocalOfficialFileImportError("LOCAL_FILE_TOO_LARGE", "Local official file exceeds the 20 MB limit", status_code=413)
        chunks.append(chunk)
    if not chunks:
        raise LocalOfficialFileImportError("LOCAL_FILE_EMPTY", "Local official file cannot be empty")
    return b"".join(chunks)


def _call_local(*args, **kwargs):
    try:
        return import_local_official_file(*args, **kwargs)
    except LocalOfficialFileImportError as exc:
        detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.details is not None:
            detail["details"] = exc.details
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Local official file import operation failed")
        raise HTTPException(status_code=500, detail={"code": "INGESTION_LOCAL_FILE_ERROR", "message": "Local official file import operation failed"}) from exc


def _call_sop(*args, **kwargs):
    try:
        return import_enterprise_sop_file(*args, **kwargs)
    except EnterpriseSopImportError as exc:
        detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.details is not None:
            detail["details"] = exc.details
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Enterprise SOP import operation failed")
        raise HTTPException(status_code=500, detail={"code": "INGESTION_SOP_ERROR", "message": "Enterprise SOP import operation failed"}) from exc


@router.post("/official-file")
async def api_import_official_file(
    response: Response,
    file: UploadFile = File(...),
    source_url: str = Form(...),
    vendor: str = Form(...),
    product_family: str = Form(...),
    version_scope_primary: str = Form(""),
    version_scope_compatibility: str = Form(""),
    terms_review_status: str = Form(...),
    source_kind: str = Form("product_page"),
    reviewer: str = Form(""),
    reviewed_at: str = Form(""),
    evidence_url: str = Form(""),
    name: str = Form(""),
    description: str = Form(""),
    idempotency_key: str = Form(""),
    request_id: str = Form(""),
    max_retries: int = Form(1),
    version_scope: str = Form(""),
    user=require_permission("knowledge_source", "create"),
):
    """Import one local official file; the multipart body is never returned."""
    content = await _read_local_file(file)
    scope: dict[str, str]
    if version_scope.strip():
        try:
            parsed_scope = json.loads(version_scope)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail={"code": "IMPORT_VERSION_SCOPE_INVALID", "message": "version_scope must be valid JSON"}) from exc
        scope = parsed_scope if isinstance(parsed_scope, dict) else {}
    else:
        scope = {"primary": version_scope_primary, "compatibility": version_scope_compatibility}
    result = _public_import_result(_call_local(
        user,
        {
            "source_url": source_url,
            "source_kind": source_kind,
            "vendor": vendor,
            "product_family": product_family,
            "version_scope": scope,
            "terms_review_status": terms_review_status,
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "evidence_url": evidence_url,
            "name": name,
            "description": description,
            "idempotency_key": idempotency_key,
            "request_id": request_id,
            "max_retries": max_retries,
        },
        content=content,
        filename=file.filename or "",
        content_type=file.content_type or "",
    ))
    status = 202 if result.get("success") and result.get("continuation_required") else (200 if result.get("success") else 502)
    response.status_code = status
    return {"success": bool(result.get("success")), "data": result, "message": "Official file import accepted" if status == 202 else "Official file import failed"}


@router.post("/enterprise-sop")
async def api_import_enterprise_sop(
    response: Response,
    file: UploadFile = File(...),
    title: str = Form(""),
    owner: str = Form(""),
    department: str = Form(""),
    classification: str = Form("INTERNAL"),
    description: str = Form(""),
    idempotency_key: str = Form(""),
    request_id: str = Form(""),
    max_retries: int = Form(1),
    user=require_permission("knowledge_source", "create"),
):
    """Import one tenant-owned SOP; classification is server-forced INTERNAL."""
    content = await _read_local_file(file)
    result = _public_import_result(_call_sop(
        user,
        {
            "title": title,
            "owner": owner,
            "department": department,
            "classification": classification,
            "description": description,
            "idempotency_key": idempotency_key,
            "request_id": request_id,
            "max_retries": max_retries,
        },
        content=content,
        filename=file.filename or "",
        content_type=file.content_type or "",
    ))
    status = 202 if result.get("success") and result.get("continuation_required") else (200 if result.get("success") else 502)
    response.status_code = status
    return {"success": bool(result.get("success")), "data": result, "message": "Enterprise SOP import accepted" if status == 202 else "Enterprise SOP import failed"}
