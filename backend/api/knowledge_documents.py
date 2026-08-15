"""HTTP contract for the ING-015 V2 document lifecycle boundary."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field

from core.rbac import require_permission
from services.document_lifecycle_service import DocumentLifecycleError, get_document_lifecycle, transition_document_lifecycle


router = APIRouter(prefix="/knowledge-v2/documents", tags=["knowledge-v2-document-lifecycle"])


class DocumentLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_status: str = Field(..., min_length=1, max_length=32)
    document_version_id: str | None = Field(default=None, max_length=256)
    replacement_version_id: str | None = Field(default=None, max_length=256)
    expected_status: str | None = Field(default=None, max_length=32)
    expected_updated_at: str | None = Field(default=None, max_length=128)
    request_id: str | None = Field(default=None, max_length=256)
    reason: str = Field(default="", max_length=2_000)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DocumentLifecycleError as exc:
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


__all__ = ["DocumentLifecycleRequest", "router"]

