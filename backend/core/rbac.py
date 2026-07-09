"""
RBAC (Role-Based Access Control) middleware and dependencies.

Roles:
  - Administrator: Full access to all endpoints
  - Operator: Can execute commands, manage devices, run playbooks
  - Viewer: Read-only access to all data

Usage in API routes:
  from core.rbac import require_role
  @router.post("/devices")
  def create_device(user=Depends(require_role("Operator"))):
      ...
"""

import logging
from fastapi import Request, HTTPException, Depends

logger = logging.getLogger(__name__)

# Role hierarchy: higher includes all lower permissions
ROLE_HIERARCHY = {
    'Administrator': 3,
    'Operator': 2,
    'Viewer': 1,
}

# Map HTTP methods to minimum required role
METHOD_ROLE_MAP = {
    'GET': 'Viewer',
    'HEAD': 'Viewer',
    'OPTIONS': 'Viewer',
    'POST': 'Operator',
    'PUT': 'Operator',
    'DELETE': 'Administrator',
}

# Endpoints that require Administrator regardless of method
ADMIN_ONLY_PATHS = {
    '/api/users',
}


def _get_current_user(request: Request) -> dict | None:
    """Extract session user from Authorization header."""
    from api.users import validate_session_token
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '') if auth.startswith('Bearer ') else ''
    logger.info(f"[RBAC Debug] Request path: {request.url.path}, auth header present: {bool(auth)}, token length: {len(token)}")
    if not token:
        logger.warning(f"[RBAC Debug] No token extracted from Authorization header for path: {request.url.path}")
        return None
    user = validate_session_token(token)
    logger.info(f"[RBAC Debug] User validation result for path {request.url.path}: {user.get('username') if user else 'None'}")
    return user


def require_role(minimum_role: str):
    """FastAPI dependency that enforces a minimum role level."""
    def dependency(request: Request):
        user = _get_current_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required")
        user_level = ROLE_HIERARCHY.get(user.get('role', ''), 0)
        required_level = ROLE_HIERARCHY.get(minimum_role, 99)
        if user_level < required_level:
            logger.warning(
                f"RBAC denied: user={user.get('username')} role={user.get('role')} "
                f"needs={minimum_role} path={request.url.path}"
            )
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return Depends(dependency)


def require_admin(request: Request):
    """Shorthand dependency for Administrator-only endpoints."""
    return require_role("Administrator")


def require_operator(request: Request):
    """Shorthand dependency for Operator+ endpoints."""
    return require_role("Operator")
