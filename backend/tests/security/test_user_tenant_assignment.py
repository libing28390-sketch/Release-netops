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


def test_user_create_rejects_foreign_payload_tenant_and_inherits_actor_tenant(
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
    attacker_username = f"rejected-{uuid.uuid4().hex[:10]}"
    response = _request(
        "POST",
        "/api/users",
        headers={"Authorization": "Bearer tenant-admin-token"},
        json={
            "username": attacker_username,
            "password": "Strong-Test!257",
            "role": "Viewer",
            "display_name": "Tenant User",
            "phone": "+1 555 010 1234",
            "email": "tenant-user@example.test",
            "tenant_id": "tenant-attacker-controlled",
        },
    )

    assert response.status_code == 403, response.text
    conn = get_db_connection()
    try:
        assert conn.execute(
            "SELECT 1 FROM users WHERE username = ?",
            (attacker_username,),
        ).fetchone() is None
    finally:
        conn.close()

    username = f"created-{uuid.uuid4().hex[:10]}"
    inherited = _request(
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
    assert inherited.status_code == 200, inherited.text
    conn = get_db_connection()
    try:
        created = conn.execute(
            "SELECT tenant_id FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        assert created["tenant_id"] == actor_tenant
    finally:
        conn.close()


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
