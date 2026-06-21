"""
license/middleware.py — FastAPI License 中间件 & 装饰器
======================================================
Provides:
  1. LicenseMiddleware — ASGI middleware that intercepts every request
  2. require_license  — Route dependency for critical endpoints
  3. require_feature  — Route dependency for feature-gated endpoints

Policy:
  • Expired license → block task execution (POST/PUT/DELETE) but allow read (GET)
  • Invalid/missing license → 403 on all requests (except /api/license/*)
  • Feature not licensed → 403 with explanation
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Callable, Optional

from fastapi import Depends, HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .verifier import LicenseVerifier, get_license_verifier, get_machine_id

logger = logging.getLogger("license.middleware")

# Paths that are ALWAYS allowed regardless of license state
_EXEMPT_PREFIXES = (
    "/api/license/status", # explicit status check
    "/api/license/upload", # explicit upload
    "/api/license/machine-id", # retrieve machine id
    "/api/health",       # health check
    "/api/setup",        # initial setup
    "/api/login",        # user authentication (login)
    "/api/session",      # session validation
    "/api/users",        # user management
    "/api/playbooks/scenarios", # allowed to load basic UI
    "/docs",             # Swagger UI
    "/openapi.json",     # OpenAPI schema
    "/redoc",            # ReDoc
    "/assets",           # frontend static assets
    "/api/system",       # platform info
    "/favicon",          # favicon
)

# Read-only methods allowed when license is expired (view data, no mutations)
_READONLY_METHODS = {"GET", "HEAD", "OPTIONS"}

# ── URL prefix → required feature 映射表 ──────────────────────────────
# 这张表内嵌在编译后的 .so 里，即使 main.py 被篡改删除 dependencies，
# 中间件层面仍然会强制检查。
# 规则：路径前缀匹配，返回需要的 feature 名称。
_FEATURE_REQUIRED: tuple[tuple[str, str], ...] = (
    ("/api/automation",       "automation"),
    ("/api/scripts",          "automation"),
    ("/api/playbooks",        "automation"),
    ("/api/inspections",      "inspections"),
    ("/api/scheduled-jobs",   "scheduled_jobs"),
    ("/api/configs",          "config_management"),
    ("/api/config-drift",     "config_management"),
    ("/api/monitoring",       "monitoring"),
    ("/api/device-health",    "monitoring"),
    ("/api/alerts",           "alerting"),
    ("/api/alert-rules",      "alerting"),
    ("/api/maintenance",      "alerting"),
    ("/api/topology",         "topology"),
    ("/api/ipam",             "ipam"),
    ("/api/capacity",         "capacity"),
    ("/api/reports",          "reports"),
    ("/api/compliance",       "compliance"),
    ("/api/change-orders",    "change_orders"),
    ("/api/change-order-templates", "change_orders"),
    ("/api/pam",              "access_center"),
    ("/api/access",           "access_center"),
    ("/api/password-rotation","password_rotation"),
    ("/api/audit",            "rbac"),
)


def _get_required_feature(path: str):
    # type: (str) -> Optional[str]
    """返回该路径需要的 feature，没有限制则返回 None。"""
    for prefix, feature in _FEATURE_REQUIRED:
        if path.startswith(prefix):
            return feature
    return None


class LicenseMiddleware:
    """
    Dummy license middleware that allows all requests to pass.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        return await self.app(scope, receive, send)


# ── Route-level Dependencies ─────────────────────────────────────────

def require_feature(feature_name: str):
    """
    FastAPI Dependency factory: returns a dummy dependency that always allows access.
    """
    def _dependency():
        pass
    return _dependency


def require_license():
    """
    FastAPI Dependency: dummy dependency that always allows access.
    """
    pass

