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

from .verifier import LicenseVerifier, get_license_verifier

logger = logging.getLogger("license.middleware")

# Paths that are ALWAYS allowed regardless of license state
_EXEMPT_PREFIXES = (
    "/api/license",      # license management endpoints themselves
    "/api/health",       # health check
    "/api/setup",        # initial setup
    "/api/login",        # user authentication (login)
    "/api/session",      # session validation
    "/api/users",        # user management
    "/docs",             # Swagger UI
    "/openapi.json",     # OpenAPI schema
    "/redoc",            # ReDoc
    "/assets",           # frontend static assets
    "/favicon",          # favicon
)

# Read-only methods allowed when license is expired (view data, no mutations)
_READONLY_METHODS = {"GET", "HEAD", "OPTIONS"}


class LicenseMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware for license enforcement on every HTTP request.
    
    Behavior:
      • Exempt paths pass through unconditionally.
      • Valid license → pass through, inject X-License-Warning header if expiring.
      • Expired license → allow GET (read-only), block POST/PUT/DELETE with 403.
      • Invalid/missing → block with 403.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Always allow exempt paths
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return await call_next(request)

        # Also allow if path is serving static frontend files (no /api prefix)
        if not path.startswith("/api/"):
            return await call_next(request)

        # Validate license
        verifier = get_license_verifier()
        lic_status = verifier.validate()

        if lic_status.valid:
            # License is valid — pass through
            response = await call_next(request)

            # Inject warning header if license is expiring soon
            if lic_status.warnings:
                clean_warnings = "; ".join(lic_status.warnings).replace("\u2014", "-")
                clean_warnings = clean_warnings.encode("latin-1", "replace").decode("latin-1")
                response.headers["X-License-Warning"] = clean_warnings
                if lic_status.days_remaining is not None:
                    response.headers["X-License-Days-Remaining"] = str(lic_status.days_remaining)

            return response

        # License is invalid
        error_msg = lic_status.error or "License validation failed"

        # Check if it's an expiry case (softer policy: allow reads)
        if "expired" in error_msg.lower():
            if request.method in _READONLY_METHODS:
                # Allow read-only access with warning
                response = await call_next(request)
                response.headers["X-License-Expired"] = "true"
                clean_error = error_msg.replace("\u2014", "-").encode("latin-1", "replace").decode("latin-1")
                response.headers["X-License-Error"] = clean_error
                return response
            else:
                logger.warning(
                    f"[License] Blocked write request {request.method} {path} — license expired"
                )
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "detail": "License has expired. Read-only access is available. "
                                  "Please renew your license to resume full operations.",
                        "license_error": error_msg,
                        "code": "LICENSE_EXPIRED",
                    },
                )

        # Hard block: invalid, corrupted, missing, tampered
        logger.warning(f"[License] Blocked request {request.method} {path} — {error_msg}")
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "detail": "License validation failed. Please provide a valid license.",
                "license_error": error_msg,
                "code": "LICENSE_INVALID",
            },
        )


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
