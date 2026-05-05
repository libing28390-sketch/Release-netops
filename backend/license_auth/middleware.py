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


class LicenseMiddleware:
    """
    Stable ASGI middleware for license enforcement.
    Avoids BaseHTTPMiddleware deadlocks on Windows/Proactor.
    """
    def __init__(self, app):
        self.app = app
        self.EXEMPT_PATHS = _EXEMPT_PREFIXES

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
            
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        # 1. Always allow exempt paths (Fast-path, no logging)
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return await self.app(scope, receive, send)

        # 2. Allow non-API paths (static files)
        if not path.startswith("/api/"):
            return await self.app(scope, receive, send)

        logger.info(f"[LicenseMiddleware] CHECK: {method} {path}")

        # 3. Validate license
        verifier = get_license_verifier()
        lic_status = verifier.validate()

        if lic_status.valid:
            # logger.debug(f"[LicenseMiddleware] VALID: {path}")
            return await self.app(scope, receive, send)

        # 4. Invalid - logic for expiry vs hard block
        error_msg = lic_status.error or "License invalid"
        is_expired = "expired" in error_msg.lower()

        # Allow GET for expired (read-only)
        if is_expired and method in _READONLY_METHODS:
            return await self.app(scope, receive, send)

        # Otherwise block
        logger.warning(f"[License] BLOCKED: {path} - {error_msg}")
        response = JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "detail": f"License Error: {error_msg}",
                "code": "LICENSE_EXPIRED" if is_expired else "LICENSE_INVALID",
                "machine_id": get_machine_id()
            }
        )
        return await response(scope, receive, send)


# ── Route-level Dependencies ─────────────────────────────────────────

def require_license(request: Request):
    """
    FastAPI Dependency: ensures a valid license for critical endpoints.
    
    Usage:
        @router.post("/api/tasks/run", dependencies=[Depends(require_license)])
        async def run_task(...):
    """
    verifier = get_license_verifier()
    lic_status = verifier.validate()

    if not lic_status.valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "A valid license is required for this operation",
                "license_error": lic_status.error,
                "code": "LICENSE_REQUIRED",
            },
        )


def require_feature(feature_name: str):
    """
    FastAPI Dependency factory: checks for a specific licensed feature.
    
    Usage:
        @router.post("/api/rbac/roles", dependencies=[Depends(require_feature("rbac"))])
        async def create_role(...):
    
    If the feature is not in the license, raises 403.
    """
    def _dependency(request: Request):
        verifier = get_license_verifier()
        lic_status = verifier.validate()

        if not lic_status.valid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": "A valid license is required",
                    "license_error": lic_status.error,
                    "code": "LICENSE_REQUIRED",
                },
            )

        if feature_name not in lic_status.features:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": f"Feature '{feature_name}' is not included in your license. "
                               f"Please upgrade to access this functionality.",
                    "code": "FEATURE_NOT_LICENSED",
                    "feature": feature_name,
                    "licensed_features": lic_status.features,
                },
            )

    return _dependency
