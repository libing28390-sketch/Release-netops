"""HTTP contract for the V1 document lifecycle boundary."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from core.rbac import require_permission
from services.document_lifecycle_service import DocumentLifecycleError, get_document_lifecycle, rollback_document_version, transition_document_lifecycle
from services.document_version_service import DocumentVersionError, compare_document_versions, list_document_versions


router = APIRouter(prefix="/knowledge/documents", tags=["knowledge-document-lifecycle"])


class DocumentLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_status: str = Field(..., min_length=1, max_length=32)
    document_version_id: str | None = Field(default=None, max_length=256)
    replacement_version_id: str | None = Field(default=None, max_length=256)
    expected_status: str | None = Field(default=None, max_length=32)
    expected_updated_at: str | None = Field(default=None, max_length=128)
    request_id: str | None = Field(default=None, max_length=256)
    reason: str = Field(default="", max_length=2_000)


class DocumentVersionActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = Field(default=False)
    replacement_version_id: str | None = Field(default=None, max_length=256)
    request_id: str | None = Field(default=None, max_length=256)
    reason: str = Field(default="", max_length=2_000)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (DocumentLifecycleError, DocumentVersionError) as exc:
        detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.details is not None:
            detail["details"] = exc.details
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc


@router.get("/{document_id}/lifecycle")
def api_get_document_lifecycle(
    document_id: str = Path(..., min_length=1, max_length=256),
    user=require_permission("knowledge_source", "read"),
):
    return {"success": True, "data": _call(get_document_lifecycle, document_id, user), "message": ""}


@router.post("/{document_id}/lifecycle")
def api_transition_document_lifecycle(
    document_id: str = Path(..., min_length=1, max_length=256),
    payload: DocumentLifecycleRequest = Body(...),
    user=require_permission("knowledge_source", "update"),
):
    return {
        "success": True,
        "data": _call(
            transition_document_lifecycle,
            document_id,
            payload.target_status,
            user,
            document_version_id=payload.document_version_id,
            replacement_version_id=payload.replacement_version_id,
            expected_status=payload.expected_status,
            expected_updated_at=payload.expected_updated_at,
            request_id=payload.request_id,
            reason=payload.reason,
        ),
        "message": "Document lifecycle transition recorded",
    }


@router.get("/{document_id}/versions")
def api_list_document_versions(
    document_id: str = Path(..., min_length=1, max_length=256),
    user=require_permission("knowledge_source", "read"),
):
    return {"success": True, "data": _call(list_document_versions, document_id, user), "message": ""}


@router.get("/{document_id}/versions/compare")
def api_compare_document_versions(
    document_id: str = Path(..., min_length=1, max_length=256),
    left_version_id: str = Query(..., min_length=1, max_length=256),
    right_version_id: str = Query(..., min_length=1, max_length=256),
    user=require_permission("knowledge_source", "read"),
):
    return {"success": True, "data": _call(compare_document_versions, document_id, left_version_id, right_version_id, user), "message": ""}


def _require_confirmation(payload: DocumentVersionActionRequest) -> None:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail={"code": "DOCUMENT_VERSION_CONFIRMATION_REQUIRED", "message": "请明确确认版本操作"})


@router.post("/{document_id}/versions/{version_id}/publish")
def api_publish_document_version(
    document_id: str = Path(..., min_length=1, max_length=256),
    version_id: str = Path(..., min_length=1, max_length=256),
    payload: DocumentVersionActionRequest = Body(...),
    user=require_permission("knowledge_source", "update"),
):
    _require_confirmation(payload)
    return {"success": True, "data": _call(
        transition_document_lifecycle,
        document_id,
        "published",
        user,
        document_version_id=version_id,
        request_id=payload.request_id,
        reason=payload.reason or "published by knowledge administrator",
    ), "message": "Document version published"}


@router.post("/{document_id}/versions/{version_id}/supersede")
def api_supersede_document_version(
    document_id: str = Path(..., min_length=1, max_length=256),
    version_id: str = Path(..., min_length=1, max_length=256),
    payload: DocumentVersionActionRequest = Body(...),
    user=require_permission("knowledge_source", "update"),
):
    _require_confirmation(payload)
    if not payload.replacement_version_id:
        raise HTTPException(status_code=400, detail={"code": "DOCUMENT_REPLACEMENT_REQUIRED", "message": "replacement_version_id is required"})
    return {"success": True, "data": _call(
        transition_document_lifecycle,
        document_id,
        "superseded",
        user,
        document_version_id=version_id,
        replacement_version_id=payload.replacement_version_id,
        request_id=payload.request_id,
        reason=payload.reason or "superseded by knowledge administrator",
    ), "message": "Document version superseded"}


@router.post("/{document_id}/versions/{version_id}/rollback")
def api_rollback_document_version(
    document_id: str = Path(..., min_length=1, max_length=256),
    version_id: str = Path(..., min_length=1, max_length=256),
    payload: DocumentVersionActionRequest = Body(...),
    user=require_permission("knowledge_source", "update"),
):
    _require_confirmation(payload)
    return {"success": True, "data": _call(
        rollback_document_version,
        document_id,
        version_id,
        user,
        request_id=payload.request_id,
        reason=payload.reason or "rollback by knowledge administrator",
    ), "message": "Document version rolled back"}


__all__ = ["DocumentLifecycleRequest", "DocumentVersionActionRequest", "router"]
