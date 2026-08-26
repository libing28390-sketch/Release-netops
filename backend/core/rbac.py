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

RESOURCE_ACTION_CATALOG = {
    'platform': {'view', 'create', 'update', 'delete', 'edit_draft', 'submit', 'approve', 'publish', 'rollback', 'bind_device'},
    'knowledge_source': {'read', 'view', 'create', 'update', 'delete', 'validate', 'enable', 'disable'},
    # Import jobs are a separate control-plane resource.  Keeping these
    # actions distinct from source CRUD prevents a source editor from silently
    # cancelling or replaying a tenant's ingestion work.
    'knowledge_import': {'read', 'view', 'create', 'manage', 'cancel', 'retry'},
    'knowledge_catalog': {'read', 'view', 'resolve', 'review', 'import', 'rollback'},
    'knowledge_collection': {'read', 'view', 'create', 'update', 'archive'},
    'command': {'view', 'edit_draft', 'test', 'execute'},
    'pam': {'view', 'request_approval', 'approve', 'create_change', 'intervene'},
    'textfsm': {'view', 'create', 'edit_draft', 'delete', 'test', 'submit', 'approve', 'publish', 'rollback', 'deprecate'},
    'sample_output': {'upload', 'view', 'delete'},
    'playbook': {'view', 'create', 'edit_draft', 'test', 'submit', 'approve', 'publish', 'execute', 'schedule', 'rollback'},
}

# Named role profiles are persisted on users by migration m0093. The legacy
# Administrator/Operator/Viewer role remains as the coarse HTTP role so old
# sessions and installations continue to work while resource actions use the
# narrower profile when one is assigned.
RECOMMENDED_ROLE_PROFILES = {
    'Platform Viewer': {
        'platform': {'view'}, 'knowledge_source': {'read', 'view'}, 'knowledge_import': {'read', 'view'}, 'knowledge_catalog': {'read', 'view', 'resolve'}, 'knowledge_collection': {'read', 'view'}, 'command': {'view'}, 'textfsm': {'view'},
        'sample_output': {'view'}, 'playbook': {'view'},
    },
    'Template Developer': {
        'platform': {'view'}, 'command': {'view', 'test'},
        'textfsm': {'view', 'create', 'edit_draft', 'delete', 'test', 'submit'},
        'sample_output': {'upload', 'view', 'delete'}, 'playbook': {'view'},
    },
    'Platform Maintainer': {
        'platform': {'view', 'create', 'update', 'delete', 'edit_draft', 'submit', 'bind_device'},
        'knowledge_source': {'read', 'view', 'create', 'update', 'delete', 'validate', 'enable', 'disable'},
        'knowledge_import': {'read', 'view', 'create', 'manage', 'cancel', 'retry'},
        'knowledge_catalog': {'read', 'view', 'resolve', 'review', 'import', 'rollback'},
        'knowledge_collection': {'read', 'view', 'create', 'update', 'archive'},
        'command': {'view', 'edit_draft', 'test'}, 'textfsm': {'view'},
        'sample_output': {'view'}, 'playbook': {'view'},
    },
    'Playbook Author': {
        'platform': {'view'}, 'command': {'view', 'test'}, 'textfsm': {'view'},
        'sample_output': {'view'},
        'playbook': {'view', 'create', 'edit_draft', 'test', 'submit'},
    },
    'Release Manager': {
        'platform': {'view', 'approve', 'publish', 'rollback'},
        'command': {'view'}, 'textfsm': {'view', 'approve', 'publish', 'rollback', 'deprecate'},
        'pam': {'view', 'approve'},
        'sample_output': {'view'},
        'playbook': {'view', 'approve', 'publish', 'rollback'},
    },
    'Scheduler Administrator': {
        'platform': {'view'}, 'command': {'view'}, 'textfsm': {'view'},
        'sample_output': {'view'}, 'playbook': {'view', 'schedule'},
    },
    'Automation Operator': {
        'platform': {'view'}, 'command': {'view', 'execute'}, 'textfsm': {'view'},
        'pam': {'view', 'request_approval', 'create_change', 'intervene'},
        'sample_output': {'view'}, 'playbook': {'view', 'execute'},
    },
    'System Administrator': {'*': {'*'}},
}


RESOURCE_ACTIONS = {
    'Administrator': {'*'},
    # Operator is the author/executor role.  Approval, publication and
    # rollback stay Administrator-only until a dedicated tenant role/profile
    # model is introduced; otherwise the old broad set defeats separation of
    # duties even when individual routes use resource permissions.
    'Operator': {
        'read', 'view', 'create', 'update', 'edit_draft', 'submit',
        'bind_device', 'test', 'execute', 'upload', 'delete', 'manage', 'cancel', 'retry',
        'request_approval', 'create_change', 'intervene', 'archive',
        'reserve', 'allocate', 'release', 'export',
    },
    'Viewer': {'read', 'view'},
}


def permission_catalog() -> dict[str, list[str]]:
    """Return the stable resource/action vocabulary for UI and API clients."""
    return {resource: sorted(actions) for resource, actions in RESOURCE_ACTION_CATALOG.items()}


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


def _profile_for_user(user: dict) -> str:
    profile = str(user.get('role_profile') or '').strip()
    if profile in RECOMMENDED_ROLE_PROFILES:
        return profile
    user_id = str(user.get('id') or user.get('user_id') or '').strip()
    if not user_id:
        return ''
    try:
        from database import get_db_connection
        conn = get_db_connection()
        try:
            row = conn.execute('SELECT role_profile FROM users WHERE id = ?', (user_id,)).fetchone()
        finally:
            conn.close()
        profile = str(row[0] or '').strip() if row else ''
        return profile if profile in RECOMMENDED_ROLE_PROFILES else ''
    except Exception:
        logger.debug('Role profile lookup unavailable', exc_info=True)
        return ''


def _action_allowed(user: dict, resource_type: str, action: str) -> bool:
    profile = _profile_for_user(user)
    if profile:
        permissions = RECOMMENDED_ROLE_PROFILES[profile]
        allowed = permissions.get(resource_type, set()) | permissions.get('*', set())
        return '*' in allowed or action in allowed
    allowed = RESOURCE_ACTIONS.get(user.get('role', ''), set())
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
    if not _action_allowed(user, resource_type, action):
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
