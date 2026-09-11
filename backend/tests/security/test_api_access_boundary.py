from __future__ import annotations

import asyncio

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException, WebSocket
from fastapi.testclient import TestClient

from api import notifications, pam
from core.api_security import enforce_api_access
from core.rbac import require_admin, require_role
from database import get_db_connection


@pytest.mark.parametrize('method,path', [
    ('GET', '/api/audit/events'), ('GET', '/api/capacity/overview'),
    ('GET', '/api/reports/dashboard'), ('GET', '/api/scripts'),
    ('DELETE', '/api/devices/security-probe'), ('PUT', '/api/devices/security-probe'),
    ('POST', '/api/configs/run-now'), ('POST', '/api/compliance/run'),
    ('POST', '/api/vars'), ('POST', '/api/notifications/read'),
])
def test_real_application_rejects_anonymous_legacy_routes(isolated_db, method, path):
    from main import app
    # Do not enter the TestClient lifespan: no scheduler, devices or startup jobs.
    response = TestClient(app).request(method, path, json={})
    assert response.status_code == 401, response.text


@pytest.mark.parametrize('role,method,expected', [
    ('Viewer', 'GET', 200), ('Viewer', 'POST', 403), ('Viewer', 'PUT', 403),
    ('Operator', 'POST', 200), ('Operator', 'DELETE', 403),
    ('Administrator', 'DELETE', 200),
])
def test_fallback_method_policy(monkeypatch, role, method, expected):
    from api import users
    monkeypatch.setattr(users, 'validate_session_token', lambda _: {'username': 'tester', 'role': role})
    app = FastAPI(dependencies=[Depends(enforce_api_access)])
    router = APIRouter()

    @router.api_route('/legacy', methods=['GET', 'POST', 'PUT', 'DELETE'])
    def legacy():
        return {'ok': True}

    app.include_router(router, prefix='/api')
    assert TestClient(app).request(method, '/api/legacy', headers={'Authorization': 'Bearer synthetic'}).status_code == expected


def test_explicit_read_only_post_and_self_service_are_preserved(monkeypatch):
    from api import users
    monkeypatch.setattr(users, 'validate_session_token', lambda _: {'username': 'tester', 'role': 'Viewer'})
    app = FastAPI(dependencies=[Depends(enforce_api_access)])

    @app.post('/api/read-analysis')
    def analyze(user=require_role('Viewer')):
        return {'ok': True}

    @app.put('/api/users/{user_id}')
    def profile(user_id: str):
        return {'ok': True}

    client = TestClient(app)
    for method, path in [('POST', '/api/read-analysis'), ('PUT', '/api/users/self')]:
        assert client.request(method, path, headers={'Authorization': 'Bearer synthetic'}).status_code == 200
        assert client.request(method, path).status_code == 401


def test_public_exception_is_exact_and_admin_shortcut_checks_permissions(monkeypatch):
    from api import users
    monkeypatch.setattr(users, 'validate_session_token', lambda _: {'username': 'tester', 'role': 'Viewer'})
    app = FastAPI(dependencies=[Depends(enforce_api_access)])

    @app.post('/api/login')
    def login():
        return {'ok': True}

    @app.post('/api/login-extra')
    def extra():
        pytest.fail('Prefix bypassed route authorization')

    @app.get('/api/admin-only')
    def admin(user=Depends(require_admin)):
        pytest.fail('Administrator shortcut did not enforce its role')

    client = TestClient(app)
    assert client.post('/api/login').status_code == 200
    assert client.post('/api/login-extra').status_code == 401
    assert client.get('/api/admin-only', headers={'Authorization': 'Bearer synthetic'}).status_code == 403


def test_notification_state_cannot_be_written_for_another_user():
    with pytest.raises(HTTPException) as error:
        notifications.mark_notifications_read({'user_id': 'victim', 'notification_ids': ['x']}, {'user_id': 'attacker'})
    assert error.value.status_code == 403


def test_legacy_pam_approval_uses_authenticated_actor_and_rejects_self_approval(make_user):
    requester = make_user('security_requester', role='Administrator')
    reviewer = make_user('security_reviewer', role='Administrator')
    with get_db_connection() as conn:
        conn.execute("INSERT INTO physical_assets (id, asset_type, hostname, management_ip, created_at, updated_at) VALUES ('approval-asset', 'server', 'approval-host', '192.0.2.20', '2026-09-11', '2026-09-11')")
        conn.commit()
    result = pam.create_access_request(pam.AccessRequestIn(asset_id='approval-asset', access_level='admin', requester_username='forged-requester'), requester)
    request_id = result['request_id']
    with pytest.raises(HTTPException) as error:
        pam.approve_access_request(request_id, pam.AccessReviewIn(reviewer_username='forged-reviewer'), requester)
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        pam.approve_access_request(request_id, pam.AccessReviewIn(), dict(requester, username='renamed-requester'))
    assert error.value.status_code == 403
    pam.approve_access_request(request_id, pam.AccessReviewIn(reviewer_username='forged-reviewer'), reviewer)
    with get_db_connection() as conn:
        row = conn.execute('SELECT requester_username, reviewer_username FROM pam_access_requests WHERE id = ?', (request_id,)).fetchone()
        assert row['requester_username'] == requester['username']
        assert row['reviewer_username'] == reviewer['username']


def test_legacy_pam_approval_requires_reviewer_permission(monkeypatch):
    from api import users
    monkeypatch.setattr(users, 'validate_session_token', lambda _: {'username': 'tester', 'role': 'Operator'})
    app = FastAPI()
    app.include_router(pam.router, prefix='/api')
    response = TestClient(app).post('/api/pam/access-requests/unknown/approve', json={}, headers={'Authorization': 'Bearer synthetic'})
    assert response.status_code == 403


def test_http_boundary_preserves_websocket_handshake_dependencies():
    app = FastAPI(dependencies=[Depends(enforce_api_access)])
    router = APIRouter()
    checked = []

    async def authenticate_socket(websocket: WebSocket):
        checked.append(websocket.query_params.get('token'))

    @router.websocket('/socket', dependencies=[Depends(authenticate_socket)])
    async def socket(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text('authenticated-handshake-reached')
        await websocket.close()

    app.include_router(router, prefix='/api')
    with TestClient(app).websocket_connect('/api/socket?token=synthetic') as connection:
        assert connection.receive_text() == 'authenticated-handshake-reached'
    assert checked == ['synthetic']
