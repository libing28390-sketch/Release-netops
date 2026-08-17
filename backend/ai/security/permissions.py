"""
AI Platform Role-Based Access Control (RBAC) & Permission Helpers
"""

from __future__ import annotations

from typing import Dict, Set
from fastapi import Depends, HTTPException, Request, status
from core.rbac import _get_current_user

AI_PERMISSION_CODES = {
    "ai.view": "View AI Center & Analysis Dashboards",
    "ai.use": "Use Basic AI Features",
    "ai.command_explain": "Execute AI Command Explanation",
    "ai.config_analyze": "Execute AI Configuration Analysis",
    "ai.diff_analyze": "Execute AI Config Diff Analysis",
    "ai.alarm_analyze": "Execute AI Alarm Analysis",
    "ai.assistant": "Use AI Assistant / Chat",
    "ai.provider.manage": "Manage AI Providers & API Keys",
    "ai.model.manage": "Manage AI Models & Model Routes",
    "ai.prompt.manage": "Manage AI Prompt Center & Templates",
    "ai.knowledge.manage": "Manage AI Knowledge Base & RAG Documents",
    "ai.audit.view": "View AI Audit Logs & Usage Dashboards",
    "ai.agent.use": "Run read-only AI agents",
    "ai.security.manage": "Manage AI Security Gateway policy",
    "ai.security.events": "View and export AI Security events",
    "ai.security.incident": "Respond to AI Security incidents",
    "ai.copilot.feedback": "Submit Copilot feedback",
    "ai.diagnostics.run": "Run read-only network diagnostics",
}

# Role permissions mapping
ROLE_AI_PERMISSIONS: Dict[str, Set[str]] = {
    "Administrator": set(AI_PERMISSION_CODES.keys()),
    "Operator": {
        "ai.view", "ai.use", "ai.command_explain", "ai.config_analyze",
        "ai.diff_analyze", "ai.alarm_analyze", "ai.assistant", "ai.audit.view",
        "ai.agent.use", "ai.copilot.feedback", "ai.diagnostics.run",
    },
    "Viewer": {
        "ai.view", "ai.command_explain", "ai.config_analyze",
        "ai.diff_analyze", "ai.alarm_analyze"
    }
}


def get_current_user(request: Request) -> dict:
    """Extract authenticated user or fallback to admin context for dev/internal calls."""
    user = _get_current_user(request)
    if not user:
        return {"username": "admin", "role": "Administrator", "permissions": list(AI_PERMISSION_CODES.keys())}
    return user


def require_ai_permission(permission_code: str):
    """FastAPI Dependency for enforcing specific AI permission codes."""
    async def dependency(request: Request, user: dict = Depends(get_current_user)):
        role = user.get("role", "Viewer")
        allowed_perms = ROLE_AI_PERMISSIONS.get(role, set())
        
        # If user has custom permissions array in dict
        user_perms = user.get("permissions")
        if isinstance(user_perms, list) and permission_code in user_perms:
            return user
            
        if role == "Administrator" or permission_code in allowed_perms:
            return user

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"AI permission denied. Required permission: '{permission_code}' (role '{role}')"
        )
    return dependency
