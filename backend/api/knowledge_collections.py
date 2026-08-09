"""CAT-018 custom Collection API kept separate from the official catalog."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from core.rbac import require_permission
from database import get_db_connection
from services.audit_service import log_audit_event
from services.catalog_collection_service import (
    CatalogCollectionError,
    archive_custom_collection,
    collection_boundary,
    create_custom_collection,
    list_custom_collections,
    update_custom_collection,
)


router = APIRouter(prefix="/knowledge-v2/collections", tags=["knowledge-v2-custom-collections"])
logger = logging.getLogger(__name__)


class CustomCollectionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=3, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)
    acl: dict[str, list[str]] = Field(default_factory=dict)
    catalog_model_refs: list[str] = Field(default_factory=list, max_length=500)


class CustomCollectionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1024)
    acl: dict[str, list[str]] | None = None
    catalog_model_refs: list[str] | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, max_length=32)
    expected_updated_at: str = Field(default="", max_length=64)


class CustomCollectionArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: str = Field(default="", max_length=64)
    confirm: bool = False


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except CatalogCollectionError as exc:
        detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.details is not None:
            detail["details"] = exc.details
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Knowledge custom collection operation failed")
        raise HTTPException(status_code=500, detail={"code": "COLLECTION_ERROR", "message": "Custom collection operation failed"}) from exc


def _audit_collection_operation(user: dict[str, Any], operation: str, details: dict[str, Any]) -> str:
    """Write a redacted audit event before the in-memory state is committed."""
    conn = get_db_connection()
    try:
        event_id = log_audit_event(
            event_type=f"catalog_collection_{operation}",
            category="knowledge_catalog",
            severity="info",
            status="success",
            summary=f"Knowledge custom collection {operation}",
            actor_id=str(user.get("id") or user.get("user_id") or user.get("username") or "system"),
            actor_username=str(user.get("username") or user.get("id") or "system"),
            actor_role=str(user.get("role") or "system"),
            target_type="knowledge_custom_collection",
            target_id=str(details.get("collection_id") or ""),
            details=details,
            conn=conn,
        )
        conn.commit()
        return event_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/boundary")
def api_collection_boundary(user=require_permission("knowledge_collection", "read")):
    return {"success": True, "data": collection_boundary(), "message": ""}


@router.get("")
@router.get("/")
def api_list_custom_collections(
    status: str = Query(default="all", max_length=32),
    user=require_permission("knowledge_collection", "read"),
):
    return {"success": True, "data": _call(list_custom_collections, user, status=status), "message": ""}


@router.post("")
@router.post("/")
def api_create_custom_collection(
    payload: CustomCollectionCreateRequest = Body(...),
    user=require_permission("knowledge_collection", "create"),
):
    return {
        "success": True,
        "data": _call(
            create_custom_collection,
            user,
            payload.model_dump(),
            audit_writer=lambda operation, details: _audit_collection_operation(user, operation, details),
        ),
        "message": "Custom collection created",
    }


@router.patch("/{collection_id}")
def api_update_custom_collection(
    collection_id: str = Path(..., min_length=1, max_length=256),
    payload: CustomCollectionUpdateRequest = Body(...),
    user=require_permission("knowledge_collection", "update"),
):
    data = payload.model_dump(exclude_none=True)
    expected_updated_at = data.pop("expected_updated_at", "")
    return {
        "success": True,
        "data": _call(
            update_custom_collection,
            user,
            collection_id,
            data,
            expected_updated_at=expected_updated_at,
            audit_writer=lambda operation, details: _audit_collection_operation(user, operation, details),
        ),
        "message": "Custom collection updated",
    }


@router.post("/{collection_id}/archive")
def api_archive_custom_collection(
    collection_id: str = Path(..., min_length=1, max_length=256),
    payload: CustomCollectionArchiveRequest = Body(...),
    user=require_permission("knowledge_collection", "archive"),
):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail={"code": "COLLECTION_CONFIRM_REQUIRED", "message": "confirm must be true to archive a collection"})
    return {
        "success": True,
        "data": _call(
            archive_custom_collection,
            user,
            collection_id,
            expected_updated_at=payload.expected_updated_at,
            audit_writer=lambda operation, details: _audit_collection_operation(user, operation, details),
        ),
        "message": "Custom collection archived",
    }

