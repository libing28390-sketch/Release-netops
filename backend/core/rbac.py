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

import json
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

RESOURCE_ACTIONS = {
    'Administrator': {'*'},
    'Operator': {'read', 'create', 'update', 'execute', 'reserve', 'allocate', 'release', 'export', 'approve_low_risk'},
    'Viewer': {'read'},
}


def _get_current_user(request: Request) -> dict | None:
    """Extract session user from Authorization header."""
    from api.users import validate_session_token
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '') if auth.startswith('Bearer ') else ''
    logger.debug("RBAC request path=%s auth_present=%s", request.url.path, bool(auth))
    if not token:
        logger.warning("No authentication token for path %s", request.url.path)
        return None
    user = validate_session_token(token)
    logger.debug("RBAC user validation path=%s user=%s", request.url.path, user.get('username') if user else 'none')
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


def _action_allowed(role: str, action: str) -> bool:
    allowed = RESOURCE_ACTIONS.get(role, set())
    return '*' in allowed or action in allowed


def authorize_resource(
    user: dict,
    resource_type: str,
    action: str,
    *,
    tenant_id: str | None = None,
    site_id: str | None = None,
    device_group_id: str | None = None,
) -> bool:
    """Evaluate resource/action and optional tenant/site/device-group scope.

    Explicit rows in ``user_resource_scopes`` narrow access. Existing users
    without scope rows retain the role-compatible behavior, while a user with
    ``tenant_id`` can never cross into another tenant.
    """
    role = user.get('role', '')
    if not _action_allowed(role, action):
        return False
    if role == 'Administrator':
        return True

    user_tenant = str(user.get('tenant_id') or '')
    if user_tenant and tenant_id and user_tenant != str(tenant_id):
        return False

    user_id = str(user.get('id') or '')
    if not user_id:
        return True
    try:
        from database import get_db_connection
        conn = get_db_connection()
        try:
            rows = conn.execute(
                """SELECT scope_type, scope_id, actions_json
                   FROM user_resource_scopes
                   WHERE user_id = ? AND resource_type IN (?, '*')""",
                (user_id, resource_type),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        logger.debug("Resource scope lookup unavailable", exc_info=True)
        rows = []
    if not rows:
        return True

    candidates = {
        'global': '',
        'tenant': str(tenant_id or ''),
        'site': str(site_id or ''),
        'device_group': str(device_group_id or ''),
    }
    for row in rows:
        scope_type = row['scope_type']
        if scope_type not in candidates:
            continue
        if scope_type != 'global' and str(row['scope_id'] or '') != candidates[scope_type]:
            continue
        try:
            actions = set(json.loads(row['actions_json'] or '[]'))
        except Exception:
            actions = set()
        if '*' in actions or action in actions:
            return True
    return False


def enforce_resource_scope(user: dict, resource_type: str, action: str, **scope) -> dict:
    if not authorize_resource(user, resource_type, action, **scope):
        logger.warning(
            "Resource authorization denied user=%s role=%s resource=%s action=%s scope=%s",
            user.get('username'), user.get('role'), resource_type, action, scope,
        )
        raise HTTPException(status_code=403, detail={
            'code': 'RESOURCE_SCOPE_DENIED',
            'message': 'Insufficient permission for this resource scope',
            'resource_type': resource_type,
            'action': action,
        })
    return user


def require_permission(resource_type: str, action: str):
    """FastAPI dependency for resource/action checks without object scope."""
    def dependency(request: Request):
        user = _get_current_user(request)
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required")
        return enforce_resource_scope(user, resource_type, action)
    return Depends(dependency)


def require_admin(request: Request):
    """Shorthand dependency for Administrator-only endpoints."""
    return require_role("Administrator")


def require_operator(request: Request):
    """Shorthand dependency for Operator+ endpoints."""
    return require_role("Operator")
