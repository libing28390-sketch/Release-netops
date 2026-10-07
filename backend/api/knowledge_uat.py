"""Browser UAT-001 case review and sign-off API."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from core.rbac import authorize_resource, require_permission
from services.knowledge_uat_service import (
    CAMPAIGN_ID,
    KnowledgeUATError,
    list_uat_case_history,
    list_uat_cases,
    sign_uat_case,
)


router = APIRouter(prefix="/knowledge/uat", tags=["knowledge-browser-uat"])


class UATSignoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "partial", "rejected"]
    comment: str = Field(default="", max_length=4000)
    evidence_ref: str = Field(default="", max_length=1024)


def _tenant(user: dict) -> str:
    return str(user.get("tenant_id") or "tenant-default")[:128]


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KnowledgeUATError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    except Exception as exc:  # pragma: no cover - defensive API boundary
        raise HTTPException(status_code=500, detail={"code": "UAT_API_ERROR", "message": "UAT operation failed"}) from exc


@router.get("")
@router.get("/")
def api_list_uat_cases(
    campaign_id: str = Query(default=CAMPAIGN_ID, min_length=1, max_length=128),
    suite: str = Query(default="", max_length=32),
    vendor: str = Query(default="", max_length=64),
    status: str = Query(default="all", max_length=32),
    search: str = Query(default="", max_length=256),
    user=require_permission("knowledge_uat", "read"),
):
    data = _call(
        list_uat_cases,
        tenant_id=_tenant(user),
        campaign_id=campaign_id,
        suite=suite,
        vendor=vendor,
        status=status,
        search=search,
    )
    data["can_sign"] = authorize_resource(user, "knowledge_uat", "sign", tenant_id=_tenant(user))
    data["current_reviewer"] = {
        "id": str(user.get("id") or user.get("user_id") or user.get("username") or ""),
        "name": str(user.get("display_name") or user.get("username") or ""),
    }
    return {"success": True, "data": data, "message": ""}


@router.post("/{campaign_id}/cases/{case_id}/signoff")
def api_sign_uat_case(
    campaign_id: str = Path(..., min_length=1, max_length=128),
    case_id: str = Path(..., min_length=1, max_length=128),
    payload: UATSignoffRequest = Body(...),
    user=require_permission("knowledge_uat", "sign"),
):
    data = _call(
        sign_uat_case,
        case_id,
        tenant_id=_tenant(user),
        campaign_id=campaign_id,
        user=user,
        decision=payload.decision,
        comment=payload.comment,
        evidence_ref=payload.evidence_ref,
    )
    return {"success": True, "data": data, "message": "UAT case sign-off saved"}


@router.get("/{campaign_id}/cases/{case_id}/history")
def api_list_uat_case_history(
    campaign_id: str = Path(..., min_length=1, max_length=128),
    case_id: str = Path(..., min_length=1, max_length=128),
    user=require_permission("knowledge_uat", "read"),
):
    data = _call(
        list_uat_case_history,
        case_id,
        tenant_id=_tenant(user),
        campaign_id=campaign_id,
    )
    return {"success": True, "data": data, "message": ""}


__all__ = ["router", "UATSignoffRequest"]
