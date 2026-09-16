"""Default-deny HTTP boundary for legacy routes missing explicit RBAC."""
from fastapi import HTTPException, Request
from starlette.requests import HTTPConnection

from core.rbac import require_role


# Exact registered route templates, never caller-controlled path prefixes.
# Agent callbacks authenticate their own one-time/callback capabilities.
PUBLIC_ROUTES = {
    ('GET', '/api/health'), ('HEAD', '/api/health'), ('GET', '/api/health/live'),
    ('GET', '/api/system/info'), ('GET', '/api/system/download-assistant'),
    ('GET', '/api/system/download-terminal-agent'), ('GET', '/api/system/exchange-token'),
    ('GET', '/api/captcha/generate'), ('POST', '/api/login'),
    ('POST', '/api/mfa/verify'),
    ('POST', '/api/forgot-password/send-code'), ('POST', '/api/forgot-password/verify-code'),
    ('POST', '/api/forgot-password/verify-mfa'), ('POST', '/api/forgot-password/reset'),
    ('POST', '/api/forgot-password/mfa-reset'),
    ('POST', '/api/pam/web-sessions/exchange'),
    ('POST', '/api/pam/web-sessions/{session_id}/status'),
    ('POST', '/api/pam/web-sessions/{session_id}/recording'),
}

SELF_SERVICE_ROUTES = {
    ('PUT', '/api/users/{user_id}'), ('POST', '/api/users/{user_id}/notify-test'),
    ('POST', '/api/mfa/setup'), ('POST', '/api/mfa/enable'), ('POST', '/api/mfa/disable'),
    ('POST', '/api/notifications/read'),
}


def _has_explicit_authorization(dependant) -> bool:
    for child in getattr(dependant, 'dependencies', ()):
        if getattr(child.call, '__module__', '') in {'core.rbac', 'ai.security.permissions'}:
            return True
        if _has_explicit_authorization(child):
            return True
    return False


def enforce_api_access(request: HTTPConnection):
    # Application dependencies also run for WebSockets. Their endpoints own
    # token validation; accepting HTTPConnection preserves that handshake.
    if request.scope['type'] != 'http':
        return
    # Newer FastAPI keeps the original, unprefixed APIRoute in "route" and
    # the included router's full path/dependency tree in its effective context.
    # Use that context when present, while retaining older FastAPI support.
    route = request.scope.get('fastapi', {}).get('effective_route_context') or request.scope.get('route')
    path = getattr(route, 'path', request.url.path)
    if not request.url.path.startswith('/api/'):
        return
    method = request.scope['method']
    key = (method, path)
    if key in PUBLIC_ROUTES:
        return
    # Existing role/profile dependencies remain authoritative, including
    # read-only POST analyses and narrowly scoped release-manager actions.
    if _has_explicit_authorization(getattr(route, 'dependant', None)):
        return
    role = 'Viewer' if key in SELF_SERVICE_ROUTES else {
        'GET': 'Viewer', 'HEAD': 'Viewer', 'POST': 'Operator',
        'PUT': 'Operator', 'PATCH': 'Operator', 'DELETE': 'Administrator',
    }.get(method)
    if role is None:
        raise HTTPException(status_code=403, detail='HTTP method is not authorized')
    return require_role(role).dependency(request)
