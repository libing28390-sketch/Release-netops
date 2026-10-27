from __future__ import annotations

import asyncio
import uuid

import httpx

from api import users
from database import get_db_connection
from main import app


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def _unique_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def test_user_create_ignores_foreign_payload_tenant_and_uses_default_tenant(
    isolated_db,
    make_user,
    monkeypatch,
):
    actor = make_user("tenant-admin", role="Administrator")
    actor_tenant = _unique_id("tenant-a")
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO tenants (id, name, description) VALUES (?, ?, ?)",
            (actor_tenant, actor_tenant, "user-tenant-assignment test"),
        )
        conn.execute(
            "UPDATE users SET tenant_id = ? WHERE id = ?",
            (actor_tenant, actor["user_id"]),
        )
        conn.commit()
    finally:
        conn.close()

    actor_session = {
        "id": actor["user_id"],
        "user_id": actor["user_id"],
        "username": actor["username"],
        "role": "Administrator",
        "tenant_id": actor_tenant,
    }
    monkeypatch.setattr(users, "validate_session_token", lambda _token: actor_session)

    async def fake_hash(_password: str) -> str:
        return "test-only-hash"

    monkeypatch.setattr(users, "_hash_password", fake_hash)
    monkeypatch.setattr(users, "log_audit_event", lambda **_event: None)
    foreign_tenant_username = f"foreign-tenant-{uuid.uuid4().hex[:10]}"
    response = _request(
        "POST",
        "/api/users",
        headers={"Authorization": "Bearer tenant-admin-token"},
        json={
            "username": foreign_tenant_username,
            "password": "Strong-Test!257",
            "role": "Viewer",
            "display_name": "Tenant User",
            "phone": "+1 555 010 1234",
            "email": "tenant-user@example.test",
            "tenant_id": "tenant-attacker-controlled",
        },
    )

    assert response.status_code == 200, response.text
    conn = get_db_connection()
    try:
        created_with_foreign_tenant = conn.execute(
            "SELECT tenant_id FROM users WHERE username = ?",
            (foreign_tenant_username,),
        ).fetchone()
        assert created_with_foreign_tenant["tenant_id"] == "tenant-default"
    finally:
        conn.close()

    username = f"created-{uuid.uuid4().hex[:10]}"
    defaulted = _request(
        "POST",
        "/api/users",
        headers={"Authorization": "Bearer tenant-admin-token"},
        json={
            "username": username,
            "password": "Strong-Test!257",
            "role": "Viewer",
            "display_name": "Tenant User",
            "phone": "+1 555 010 1234",
            "email": "tenant-user@example.test",
        },
    )
    assert defaulted.status_code == 200, defaulted.text
    conn = get_db_connection()
    try:
        created = conn.execute(
            "SELECT id, role, role_profile, scope_mode, tenant_id FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        assert created["tenant_id"] == "tenant-default"
        asset_scope = conn.execute(
            "SELECT scope_type, scope_id, actions_json FROM user_resource_scopes "
            "WHERE user_id = ? AND resource_type = 'asset'",
            (created["id"],),
        ).fetchone()
        assert asset_scope
        assert asset_scope["scope_type"] == "tenant"
        assert asset_scope["scope_id"] == "tenant-default"
        assert asset_scope["actions_json"] == '["view"]'
    finally:
        conn.close()

    from core.rbac import authorize_resource

    requester = dict(created)
    requester["user_id"] = requester["id"]
    assert authorize_resource(
        requester,
        "asset",
        "view",
        tenant_id="tenant-default",
    )


def test_global_admin_assigns_default_tenant_and_unauthenticated_request_is_rejected(
    isolated_db,
    monkeypatch,
):
    tenantless_actor = {
        "id": _unique_id("tenantless-admin"),
        "user_id": _unique_id("tenantless-admin-user"),
        "username": "tenantless-admin",
        "role": "Administrator",
        "tenant_id": "",
    }
    monkeypatch.setattr(users, "validate_session_token", lambda _token: tenantless_actor)
    async def fake_hash(_password: str) -> str:
        return "test-only-hash"

    monkeypatch.setattr(users, "_hash_password", fake_hash)
    monkeypatch.setattr(users, "log_audit_event", lambda **_event: None)
    blocked_username = f"blocked-{uuid.uuid4().hex[:10]}"
    response = _request(
        "POST",
        "/api/users",
        headers={"Authorization": "Bearer tenantless-admin-token"},
        json={
            "username": blocked_username,
            "password": "Strong-Test!257",
            "role": "Viewer",
            "display_name": "Blocked User",
            "phone": "+1 555 010 1234",
            "email": "blocked@example.test",
            "tenant_id": "tenant-default",
        },
    )
    assert response.status_code == 200, response.text
    conn = get_db_connection()
    try:
        created = conn.execute(
            "SELECT tenant_id FROM users WHERE username = ?",
            (blocked_username,),
        ).fetchone()
        assert created["tenant_id"] == "tenant-default"
    finally:
        conn.close()

    monkeypatch.setattr(users, "validate_session_token", lambda _token: None)
    unauthenticated = _request(
        "POST",
        "/api/users",
        json={
            "username": f"anonymous-{uuid.uuid4().hex[:10]}",
            "password": "Strong-Test!257",
            "role": "Viewer",
            "display_name": "Anonymous User",
            "phone": "+1 555 010 1234",
            "email": "anonymous@example.test",
        },
    )
    assert unauthenticated.status_code == 401, unauthenticated.text


def test_change_order_assignment_options_are_minimal_and_tenant_scoped(
    isolated_db,
    make_user,
    monkeypatch,
):
    requester = make_user('assignment-options-requester', role='Viewer')
    initial = make_user(
        'assignment-options-initial', role='Administrator',
        change_groups=['initial_reviewer'],
    )
    final = make_user(
        'assignment-options-final', role='Administrator',
        change_groups=['final_approver'],
    )
    foreign = make_user(
        'assignment-options-foreign', role='Administrator',
        change_groups=['initial_reviewer', 'final_approver'],
    )
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE users SET role_profile='Change Requester', scope_mode='restricted' WHERE id = ?",
            (requester['user_id'],),
        )
        conn.execute(
            "UPDATE users SET tenant_id = ? WHERE id = ?",
            ('tenant-other', foreign['user_id']),
        )
        conn.execute(
            """INSERT INTO user_resource_scopes
               (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
               VALUES (?, ?, 'change_order', 'tenant', 'tenant-default', '[\"create\",\"update\",\"view\"]', '2026-10-26T00:00:00Z')""",
            ('assignment-options-requester-scope', requester['user_id']),
        )
        conn.commit()
    finally:
        conn.close()

    requester_session = {
        'id': requester['user_id'],
        'user_id': requester['user_id'],
        'username': requester['username'],
        'role': 'Viewer',
        'role_profile': 'Change Requester',
        'tenant_id': 'tenant-default',
        'scope_mode': 'restricted',
    }
    monkeypatch.setattr(users, 'validate_session_token', lambda _token: requester_session)
    response = _request(
        'GET',
        '/api/change-orders/assignment-options',
        headers={'Authorization': 'Bearer assignment-options-token'},
    )

    assert response.status_code == 200, response.text
    options = response.json()['data']
    usernames = {item['username'] for item in options}
    assert {requester['username'], initial['username'], final['username']} <= usernames
    from core.tenant_policy import TENANT_ISOLATION_ENABLED

    if TENANT_ISOLATION_ENABLED:
        assert foreign['username'] not in usernames
    else:
        assert foreign['username'] in usernames
    assert all({'email', 'phone', 'last_login'}.isdisjoint(item) for item in options)
    initial_option = next(item for item in options if item['id'] == initial['user_id'])
    final_option = next(item for item in options if item['id'] == final['user_id'])
    assert 'initial_reviewer' in initial_option['change_groups']
    assert 'final_approver' in final_option['change_groups']
