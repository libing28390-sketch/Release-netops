"""HTTP API for the Knowledge Engine V2 Source Registry (CAT-003)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from core.rbac import require_permission
from services.source_registry_service import (
    SourceRegistryError,
    collect_source,
    create_source,
    delete_source,
    disable_source,
    enable_source,
    get_source,
    list_source_versions,
    list_source_refresh_observations,
    get_source_refresh_status,
    list_sources,
    record_source_version,
    update_source,
    validate_source,
)
from api.knowledge_v2_response import (
    REFRESH_OBSERVATION_SUMMARY_FIELDS,
    SOURCE_SUMMARY_FIELDS,
    SOURCE_VERSION_SUMMARY_FIELDS,
    attach_pagination,
    paginate_items,
    project_summary,
)


router = APIRouter(prefix="/knowledge-v2/sources", tags=["knowledge-v2-source-registry"])
logger = logging.getLogger(__name__)


class _SourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRegistryCreateRequest(_SourceRequest):
    source_type: str = Field(..., min_length=1, max_length=64)
    source_kind: str | None = Field(default=None, min_length=1, max_length=64)
    canonical_url: str = Field(..., min_length=8, max_length=4096)
    allowed_host: str | None = Field(default=None, min_length=1, max_length=255)
    name: str = Field(default="", max_length=256)
    description: str = Field(default="", max_length=4000)
    trust_level: str | None = Field(default=None, max_length=32)
    collection_policy: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceRegistryUpdateRequest(_SourceRequest):
    canonical_url: str | None = Field(default=None, min_length=8, max_length=4096)
    name: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=4000)
    trust_level: str | None = Field(default=None, max_length=32)
    collection_policy: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    expected_updated_at: str | None = Field(default=None, max_length=128)


class SourceVersionCreateRequest(_SourceRequest):
    content_hash: str | None = Field(default=None, min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    content: str | None = Field(default=None, max_length=100_000_000)
    byte_size: int | None = Field(default=None, ge=0, le=100_000_000)
    fetched_at: str | None = Field(default=None, max_length=128)
    parser_name: str = Field(..., min_length=1, max_length=128)
    parser_version: str = Field(..., min_length=1, max_length=64)
    source_etag: str = Field(default="", max_length=512)
    source_last_modified: str = Field(default="", max_length=256)
    fetch_url: str | None = Field(default=None, max_length=4096)
    response_content_type: str = Field(default="", max_length=256)
    http_status: int | None = Field(default=None, ge=100, le=599)
    raw_content_ref: str = Field(default="", max_length=2048)
    raw_content_storage: str = Field(default="", max_length=128)
    verification_method: str = Field(default="", max_length=128)
    error_code: str = Field(default="", max_length=128)
    error: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="fetched", max_length=32)


class SourceLifecycleRequest(_SourceRequest):
    reason: str = Field(default="", max_length=2000)


class SourceFetchRequest(_SourceRequest):
    method: str = Field(default="GET", pattern=r"^(?i:get|head)$")


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except SourceRegistryError as exc:
        detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.details is not None:
            detail["details"] = exc.details
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Knowledge source registry operation failed")
        raise HTTPException(status_code=500, detail={"code": "SOURCE_REGISTRY_ERROR", "message": "Source registry operation failed"}) from exc


@router.get("")
@router.get("/")
def api_list_sources(
    status: str = Query(default="all", max_length=32),
    tenant_id: str | None = Query(default=None, max_length=128),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: str = Query(default="updated_at", max_length=64),
    sort_order: str = Query(default="desc", pattern="^(?i:asc|desc)$"),
    user=require_permission("knowledge_source", "read"),
):
    rows = [
        project_summary(row, fields=SOURCE_SUMMARY_FIELDS)
        for row in _call(list_sources, user, status=status, tenant_id=tenant_id)
    ]
    items, meta = paginate_items(
        rows, page=page, page_size=page_size, sort_by=sort_by, sort_order=sort_order,
        allowed_sort_fields={"updated_at", "created_at", "name", "status", "source_type", "trust_level"},
    )
    return attach_pagination({"success": True, "data": items, "message": ""}, meta, filters={"status": status, "tenant_id": tenant_id})


@router.post("")
@router.post("/")
def api_create_source(payload: SourceRegistryCreateRequest, user=require_permission("knowledge_source", "create")):
    return {"success": True, "data": _call(create_source, payload.model_dump(exclude_none=True), user), "message": "Source registry record created"}


@router.get("/{source_id}")
def api_get_source(
    source_id: str = Path(..., min_length=1, max_length=128),
    user=require_permission("knowledge_source", "read"),
):
    return {"success": True, "data": _call(get_source, source_id, user), "message": ""}


@router.patch("/{source_id}")
@router.put("/{source_id}")
def api_update_source(
    source_id: str = Path(..., min_length=1, max_length=128),
    payload: SourceRegistryUpdateRequest = Body(...),
    user=require_permission("knowledge_source", "update"),
):
    return {"success": True, "data": _call(update_source, source_id, payload.model_dump(exclude_unset=True), user), "message": "Source registry record updated"}


@router.post("/{source_id}/validate")
def api_validate_source(
    source_id: str = Path(..., min_length=1, max_length=128),
    user=require_permission("knowledge_source", "read"),
):
    return {"success": True, "data": _call(validate_source, source_id, user), "message": "Source validation completed"}


@router.post("/{source_id}/enable")
def api_enable_source(
    source_id: str = Path(..., min_length=1, max_length=128),
    user=require_permission("knowledge_source", "update"),
):
    return {"success": True, "data": _call(enable_source, source_id, user), "message": "Source enabled"}


@router.post("/{source_id}/disable")
def api_disable_source(
    source_id: str = Path(..., min_length=1, max_length=128),
    payload: SourceLifecycleRequest | None = Body(default=None),
    user=require_permission("knowledge_source", "update"),
):
    return {"success": True, "data": _call(disable_source, source_id, user, reason=(payload.reason if payload else "")), "message": "Source disabled"}


@router.delete("/{source_id}")
def api_delete_source(
    source_id: str = Path(..., min_length=1, max_length=128),
    payload: SourceLifecycleRequest | None = Body(default=None),
    user=require_permission("knowledge_source", "delete"),
):
    return {"success": True, "data": _call(delete_source, source_id, user, reason=(payload.reason if payload else "")), "message": "Source archived as deleted"}


@router.get("/{source_id}/versions")
def api_list_source_versions(
    source_id: str = Path(..., min_length=1, max_length=128),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: str = Query(default="fetched_at", max_length=64),
    sort_order: str = Query(default="desc", pattern="^(?i:asc|desc)$"),
    user=require_permission("knowledge_source", "read"),
):
    rows = [
        project_summary(row, fields=SOURCE_VERSION_SUMMARY_FIELDS)
        for row in _call(list_source_versions, source_id, user)
    ]
    items, meta = paginate_items(
        rows, page=page, page_size=page_size, sort_by=sort_by, sort_order=sort_order,
        allowed_sort_fields={"fetched_at", "created_at", "status", "byte_size", "id"},
    )
    return attach_pagination({"success": True, "data": items, "message": ""}, meta)


@router.get("/{source_id}/refresh-observations")
def api_list_source_refresh_observations(
    source_id: str = Path(..., min_length=1, max_length=128),
    limit: int = Query(default=50, ge=1, le=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_by: str = Query(default="checked_at", max_length=64),
    sort_order: str = Query(default="desc", pattern="^(?i:asc|desc)$"),
    user=require_permission("knowledge_source", "read"),
):
    # FastAPI resolves ``Query`` to an int for HTTP callers.  Keeping a plain
    # default here also makes this route safe to invoke directly in internal
    # contract tests and avoids leaking framework sentinel values to services.
    if not isinstance(limit, int):
        limit = 50
    if not isinstance(page, int):
        page = 1
    if not isinstance(page_size, int):
        page_size = 50
    if not isinstance(sort_by, str):
        sort_by = "checked_at"
    if not isinstance(sort_order, str):
        sort_order = "desc"
    rows = [
        project_summary(row, fields=REFRESH_OBSERVATION_SUMMARY_FIELDS)
        for row in _call(list_source_refresh_observations, source_id, user, limit=limit)
    ]
    items, meta = paginate_items(
        rows, page=page, page_size=min(page_size, limit), sort_by=sort_by, sort_order=sort_order,
        allowed_sort_fields={"checked_at", "created_at", "outcome", "detection_type", "http_status"},
    )
    return attach_pagination({"success": True, "data": items, "message": ""}, meta)


@router.get("/{source_id}/refresh-status")
def api_get_source_refresh_status(
    source_id: str = Path(..., min_length=1, max_length=128),
    user=require_permission("knowledge_source", "read"),
):
    return {"success": True, "data": _call(get_source_refresh_status, source_id, user), "message": ""}


@router.post("/{source_id}/versions")
def api_record_source_version(
    source_id: str = Path(..., min_length=1, max_length=128),
    payload: SourceVersionCreateRequest = Body(...),
    user=require_permission("knowledge_source", "create"),
):
    data = payload.model_dump(exclude_none=True)
    return {"success": True, "data": _call(record_source_version, source_id, data, user), "message": "Source version recorded"}


@router.post("/{source_id}/fetch")
def api_collect_source(
    source_id: str = Path(..., min_length=1, max_length=128),
    payload: SourceFetchRequest | None = Body(default=None),
    user=require_permission("knowledge_source", "create"),
):
    data = (payload or SourceFetchRequest()).model_dump(exclude_none=True)
    return {"success": True, "data": _call(collect_source, source_id, data, user), "message": "Source collection completed"}
