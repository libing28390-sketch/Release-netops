"""
Main AI Center Router assembling all sub-routers
"""

from __future__ import annotations

from fastapi import APIRouter
from ai.api.providers import router as providers_router
from ai.api.models import router as models_router
from ai.api.prompts import router as prompts_router
from ai.api.analyze import router as analyze_router
from ai.api.usage import router as usage_router
from ai.api.assistant import router as assistant_router
from ai.api.agents import router as agents_router
from ai.api.governance import router as governance_router
from ai.api.security import router as security_router
from ai.api.diagnostics import router as diagnostics_router

ai_router = APIRouter(prefix="/ai", tags=["Nexora AI Center"])

ai_router.include_router(providers_router)
ai_router.include_router(models_router)
ai_router.include_router(prompts_router)
ai_router.include_router(analyze_router)
ai_router.include_router(usage_router)
ai_router.include_router(assistant_router)
ai_router.include_router(agents_router)
ai_router.include_router(governance_router)
ai_router.include_router(security_router)
ai_router.include_router(diagnostics_router)
