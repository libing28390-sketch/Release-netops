"""
FastAPI Router for AI Configuration Generation, Risk Check, and Change Approval Governance
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ai.security.permissions import require_ai_permission
from ai.security.rate_limit import ai_rate_limiter
from ai.services.config_generation import config_generation_service
from ai.services.change_governance import change_governance_service
from core.config import settings

router = APIRouter(prefix="/governance", tags=["AI Change Governance"])

# A generated plan can be turned into a change-order draft for this long.
PLAN_TOKEN_TTL_SECONDS = 30 * 60


class GenerateConfigRequest(BaseModel):
    intent: str = Field(..., description="Configuration change intent description")
    vendor: str = Field("Huawei", description="Device vendor")
    platform: str = Field("huawei_vrp", description="Device platform")


class CreateDraftRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    device_id: str = Field(..., min_length=1, max_length=128)
    commands: List[str] = Field(..., max_length=500)
    verification_commands: List[str] = Field(default_factory=list, max_length=200)
    rollback_commands: List[str] = Field(default_factory=list, max_length=500)
    # Issued by /generate-config. Binds the draft to commands the server
    # generated and safety-checked for this user.
    plan_token: str = Field(..., min_length=16, max_length=4096)
    risk_acknowledged: bool = False


def _user_identity(user: Dict[str, Any]) -> tuple[str, str, str]:
    username = str(user.get("username") or "").strip()
    user_id = str(user.get("user_id") or user.get("id") or username).strip()
    tenant_id = str(user.get("tenant_id") or "").strip()
    return username, user_id, tenant_id


def _plan_digest(commands: List[str], verification: List[str], rollback: List[str]) -> str:
    body = json.dumps(
        {"commands": list(commands or []), "verification": list(verification or []), "rollback": list(rollback or [])},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _sign(raw: bytes) -> str:
    key = hashlib.sha256(("nexora-ai-plan-token:" + str(settings.SECRET_KEY or "")).encode("utf-8")).digest()
    return hmac.new(key, raw, hashlib.sha256).hexdigest()


def issue_plan_token(*, user_id: str, tenant_id: str, commands: List[str], verification: List[str], rollback: List[str], has_warnings: bool) -> str:
    claims = {
        "u": user_id,
        "t": tenant_id,
        "d": _plan_digest(commands, verification, rollback),
        "w": bool(has_warnings),
        "e": int(time.time()) + PLAN_TOKEN_TTL_SECONDS,
    }
    raw = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") + "." + _sign(raw)


def verify_plan_token(token: str, *, user_id: str, tenant_id: str, commands: List[str], verification: List[str], rollback: List[str]) -> Dict[str, Any]:
    """Return the token claims, or raise HTTPException(403)."""

    def deny(code: str) -> HTTPException:
        return HTTPException(status_code=403, detail={"code": code, "message": "请先通过“生成配置”生成方案，再提交工单草稿。"})

    try:
        encoded, signature = str(token).rsplit(".", 1)
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        claims = json.loads(raw)
    except (ValueError, TypeError):
        raise deny("AI_PLAN_TOKEN_INVALID") from None
    if not hmac.compare_digest(_sign(raw), signature):
        raise deny("AI_PLAN_TOKEN_INVALID")
    if int(claims.get("e") or 0) < int(time.time()):
        raise deny("AI_PLAN_TOKEN_EXPIRED")
    if claims.get("u") != user_id or claims.get("t") != tenant_id:
        raise deny("AI_PLAN_TOKEN_INVALID")
    if claims.get("d") != _plan_digest(commands, verification, rollback):
        # The submitted commands differ from what the server generated.
        raise deny("AI_PLAN_TOKEN_MISMATCH")
    return claims


@router.post("/generate-config")
async def generate_config(req: GenerateConfigRequest, user=Depends(require_ai_permission("ai.use"))):
    """Generate vendor-aware configuration commands with safety inspection."""
    username, user_id, tenant_id = _user_identity(user)
    roles = [str(user.get("role"))] if user.get("role") else []
    allowed, _ = await ai_rate_limiter.is_allowed_async(username or user_id or "user", "change_plan")
    if not allowed:
        raise HTTPException(status_code=429, detail="Daily rate limit exceeded for configuration generation.")
    result = await config_generation_service.generate_config(
        intent=req.intent,
        vendor=req.vendor,
        platform=req.platform,
        user_id=username or "user",
        tenant_id=tenant_id or "tenant-default",
        roles=roles,
    )
    if isinstance(result, dict) and result.get("commands"):
        result["plan_token"] = issue_plan_token(
            user_id=user_id,
            tenant_id=tenant_id,
            commands=list(result.get("commands") or []),
            verification=list(result.get("verification_commands") or []),
            rollback=list(result.get("rollback_commands") or []),
            has_warnings=bool(result.get("safety_warnings")),
        )
    return result


@router.post("/create-draft")
def create_change_draft(req: CreateDraftRequest, user=Depends(require_ai_permission("ai.use"))):
    """Submit a server-generated configuration plan as a Change Order draft.

    Only commands produced by /generate-config for the same user are
    accepted (``plan_token``); a plan with safety warnings needs an explicit
    risk acknowledgement.  The draft then follows the normal ITSM review and
    approval workflow.
    """
    username, user_id, tenant_id = _user_identity(user)
    if not username or not user_id:
        raise HTTPException(status_code=401, detail="Authenticated user identity is required")
    claims = verify_plan_token(
        req.plan_token,
        user_id=user_id,
        tenant_id=tenant_id,
        commands=req.commands,
        verification=req.verification_commands,
        rollback=req.rollback_commands,
    )
    if claims.get("w") and not req.risk_acknowledged:
        raise HTTPException(
            status_code=409,
            detail={"code": "AI_PLAN_RISK_NOT_ACKNOWLEDGED", "message": "该方案包含高危命令告警，请确认风险后再提交。"},
        )
    return change_governance_service.create_change_draft(
        title=req.title,
        device_id=req.device_id,
        commands=req.commands,
        verification_commands=req.verification_commands,
        rollback_commands=req.rollback_commands,
        created_by=username,
        requester_id=user_id,
        tenant_id=tenant_id,
    )


@router.post("/approve/{change_id}", status_code=410)
def approve_change(change_id: str, user=Depends(require_ai_permission("ai.view"))):
    """Retired: AI drafts are approved through the standard change workflow.

    This shortcut used to move a draft straight to ``approved`` with the
    Provider-management permission, skipping initial review, final review,
    the change window and the approval snapshot.  AI-generated drafts now go
    through ``POST /api/change-orders/{id}/transition`` like every other
    change order.
    """
    raise HTTPException(
        status_code=410,
        detail={
            "code": "AI_APPROVAL_USE_CHANGE_WORKFLOW",
            "message": "AI 生成的变更草稿请在“ITSM 变更工单”中按初审、终审流程审批。",
            "change_id": change_id,
        },
    )
