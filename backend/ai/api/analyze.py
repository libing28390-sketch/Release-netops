"""
FastAPI Router for AI Analysis Endpoints (Command Explain, Config Explain, Diff Analysis, Alarm Analysis)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from ai.security.permissions import require_ai_permission
from ai.security.rate_limit import ai_rate_limiter
from ai.schemas.analysis import (
    AlarmAnalysisRequest,
    AlarmAnalysisResponse,
    CommandAnalysisRequest,
    CommandAnalysisResponse,
    ConfigAnalysisRequest,
    ConfigAnalysisResponse,
    DiffAnalysisRequest,
    DiffAnalysisResponse,
)
from ai.services.alarm_analysis import alarm_analysis_service
from ai.services.command_analysis import command_analysis_service
from ai.services.config_analysis import config_analysis_service
from ai.services.diff_analysis import diff_analysis_service

router = APIRouter(prefix="/analyze", tags=["AI Operational Analysis"])


@router.post("/command", response_model=CommandAnalysisResponse)
async def analyze_command(
    req: CommandAnalysisRequest,
    user=Depends(require_ai_permission("ai.command_explain"))
):
    """AI Command Explanation Endpoint."""
    user_id = user.get("username", "user")
    allowed, _ = ai_rate_limiter.is_allowed(user_id, "command_explain")
    if not allowed:
        raise HTTPException(status_code=429, detail="Daily rate limit exceeded for command analysis.")
    return await command_analysis_service.analyze(req, user_id=user_id)


@router.post("/config", response_model=ConfigAnalysisResponse)
async def analyze_config(
    req: ConfigAnalysisRequest,
    user=Depends(require_ai_permission("ai.config_analyze"))
):
    """AI Configuration Analysis Endpoint."""
    user_id = user.get("username", "user")
    allowed, _ = ai_rate_limiter.is_allowed(user_id, "config_explain")
    if not allowed:
        raise HTTPException(status_code=429, detail="Daily rate limit exceeded for config analysis.")
    return await config_analysis_service.analyze(req, user_id=user_id)


@router.post("/diff", response_model=DiffAnalysisResponse)
async def analyze_diff(
    req: DiffAnalysisRequest,
    user=Depends(require_ai_permission("ai.diff_analyze"))
):
    """AI Config Diff Analysis Endpoint (Consumes raw diff from Nexora Diff Engine)."""
    user_id = user.get("username", "user")
    allowed, _ = ai_rate_limiter.is_allowed(user_id, "config_diff")
    if not allowed:
        raise HTTPException(status_code=429, detail="Daily rate limit exceeded for diff analysis.")
    return await diff_analysis_service.analyze(req, user_id=user_id)


@router.post("/alarm", response_model=AlarmAnalysisResponse)
async def analyze_alarm(
    req: AlarmAnalysisRequest,
    user=Depends(require_ai_permission("ai.alarm_analyze"))
):
    """AI Alarm & Incident Correlation Analysis Endpoint."""
    user_id = user.get("username", "user")
    allowed, _ = ai_rate_limiter.is_allowed(user_id, "alarm_analysis")
    if not allowed:
        raise HTTPException(status_code=429, detail="Daily rate limit exceeded for alarm analysis.")
    return await alarm_analysis_service.analyze(req, user_id=user_id)
