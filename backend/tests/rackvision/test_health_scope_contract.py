"""Tenant/site scope checks for device health reads."""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx

from api import users
from database import get_db_connection
from main import app


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def test_health_overview_and_detail_are_site_scoped(isolated_db, make_user, monkeypatch):
    conn = isolated_db["module"].get_db_connection()
    tenant_a = _id("health-tenant-a")
    tenant_b = _id("health-tenant-b")
    site_a = _id("health-site-a")
    site_b = _id("health-site-b")
    device_a = _id("health-device-a")
    device_b = _id("health-device-b")
    try:
        for tenant_id in (tenant_a, tenant_b):
            conn.execute(
                "INSERT INTO tenants (id, name, description) VALUES (?, ?, ?)",
                (tenant_id, tenant_id, "RackVision health scope test"),
            )
        for site_id, tenant_id in ((site_a, tenant_a), (site_b, tenant_b)):
            conn.execute(
                """INSERT INTO sites (id, site_code, site_name, status, tenant_id)
                   VALUES (?, ?, ?, 'active', ?)""",
                (site_id, site_id.upper(), site_id, tenant_id),
            )
        conn.executemany(
            """INSERT INTO devices (id, hostname, status, site_id, ip_address, platform)
               VALUES (?, ?, 'online', ?, ?, 'cisco_ios')""",
            [
                (device_a, "health-a", site_a, "192.0.2.131"),
                (device_b, "health-b", site_b, "192.0.2.132"),
            ],
        )
        user = make_user("health-scope-viewer", role="Viewer")
        conn.execute(
            "UPDATE users SET tenant_id = ? WHERE id = ?",
            (tenant_a, user["user_id"]),
        )
        conn.execute(
            """INSERT INTO user_resource_scopes (
                   id, user_id, resource_type, scope_type, scope_id,
                   actions_json, created_at
               ) VALUES (?, ?, 'asset', 'site', ?, ?, CURRENT_TIMESTAMP)""",
            (
                _id("health-scope"),
                user["user_id"],
                site_a,
                json.dumps(["view"]),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    user_payload = {
        "user_id": user["user_id"],
        "id": user["user_id"],
        "username": "health-scope-viewer",
        "role": "Viewer",
        "tenant_id": tenant_a,
    }
    monkeypatch.setattr(users, "validate_session_token", lambda token: user_payload)
    headers = {"Authorization": "Bearer health-scope-token"}

    overview = _request("GET", "/api/device-health/overview", headers=headers)
    assert overview.status_code == 200, overview.text
    assert overview.json()["data"]["total_devices"] == 1
    assert overview.json()["data"]["top_risky_devices"][0]["id"] == device_a

    visible_detail = _request("GET", f"/api/device-health/device/{device_a}", headers=headers)
    assert visible_detail.status_code == 200, visible_detail.text
    assert visible_detail.json()["device"]["hostname"] == "health-a"

    hidden_detail = _request("GET", f"/api/device-health/device/{device_b}", headers=headers)
    assert hidden_detail.status_code == 403, hidden_detail.text
    assert hidden_detail.json()["error"]["code"] == "RESOURCE_SCOPE_DENIED"

    hidden_trend = _request("GET", f"/api/device-health/device/{device_b}/trend", headers=headers)
    assert hidden_trend.status_code == 404, hidden_trend.text
