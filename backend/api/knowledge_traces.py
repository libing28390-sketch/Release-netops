"""KUI-017 administrator retrieval trace viewer API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Query

from core.rbac import require_permission
from core.tenant_policy import tenant_scope_for_user, tenant_scope_is_enabled
from ai.services.retrieval_trace_store import get_retrieval_trace, list_retrieval_traces


router = APIRouter(prefix="/knowledge/retrieval-traces", tags=["knowledge-retrieval-traces"])


def _tenant(user: dict) -> str | None:
    tenant_id = tenant_scope_for_user(user)
    if tenant_id is not None:
        return tenant_id[:128]
    return "tenant-default" if tenant_scope_is_enabled() else None


@router.get("")
@router.get("/")
def api_list_retrieval_traces(
    limit: int = Query(default=50, ge=1, le=200),
    status: str = Query(default="all", max_length=32),
    user=require_permission("knowledge_source", "read"),
):
    return {
        "success": True,
        "data": {
            "items": list_retrieval_traces(tenant_id=_tenant(user), limit=limit, status=status),
            "limit": limit,
            "status": status,
            "redacted": True,
        },
        "message": "",
    }


@router.get("/{trace_id}")
def api_get_retrieval_trace(
    trace_id: str = Path(..., min_length=3, max_length=64),
    user=require_permission("knowledge_source", "read"),
):
    item = get_retrieval_trace(tenant_id=_tenant(user), trace_id=trace_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "RETRIEVAL_TRACE_NOT_FOUND", "message": "Retrieval trace not found"})
    return {"success": True, "data": item, "message": ""}
