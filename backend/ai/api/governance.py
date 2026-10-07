"""
FastAPI Router for AI Configuration Generation, Risk Check, and Change Approval Governance
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from ai.security.permissions import require_ai_permission
from ai.services.config_generation import config_generation_service
from ai.services.change_governance import change_governance_service

router = APIRouter(prefix="/governance", tags=["AI Change Governance"])


class GenerateConfigRequest(BaseModel):
    intent: str = Field(..., description="Configuration change intent description")
    vendor: str = Field("Huawei", description="Device vendor")
    platform: str = Field("huawei_vrp", description="Device platform")


class CreateDraftRequest(BaseModel):
    title: str
    device_id: str
    commands: List[str]
    verification_commands: List[str] = []
    rollback_commands: List[str] = []


@router.post("/generate-config")
async def generate_config(req: GenerateConfigRequest, user=Depends(require_ai_permission("ai.use"))):
    """Generate vendor-aware configuration commands with safety inspection."""
    user_id = user.get("username", "user")
    return await config_generation_service.generate_config(
        intent=req.intent,
        vendor=req.vendor,
        platform=req.platform,
        user_id=user_id
    )


@router.post("/create-draft")
def create_change_draft(req: CreateDraftRequest, user=Depends(require_ai_permission("ai.use"))):
    """Submit AI Generated Configuration as Change Order Draft."""
    username = user.get("username", "ai_agent")
    return change_governance_service.create_change_draft(
        title=req.title,
        device_id=req.device_id,
        commands=req.commands,
        verification_commands=req.verification_commands,
        rollback_commands=req.rollback_commands,
        created_by=username
    )


@router.post("/approve/{change_id}")
def approve_change(change_id: str, user=Depends(require_ai_permission("ai.provider.manage"))):
    """Human approval gate for AI generated Change Order."""
    username = user.get("username", "admin")
    return change_governance_service.approve_change(change_id, approver=username)
