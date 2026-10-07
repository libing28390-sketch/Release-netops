from __future__ import annotations

import asyncio
import uuid

import httpx

from api import users
from database import get_db_connection
from main import app


def _request(method: str, path: str, *, token: str) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(
                method,
                path,
                headers={"Authorization": f"Bearer {token}"},
            )

    return asyncio.run(run())


def _insert_open_alert(conn, *, alert_id: str, device_id: str, title: str) -> None:
    conn.execute(
        """
        INSERT INTO alert_events (
            id, dedupe_key, source, severity, title, message, device_id,
            interface_name, created_at, resolved_at, workflow_status, note, updated_at
        ) VALUES (?, ?, 'monitoring', 'critical', ?, 'test alert', ?, '', CURRENT_TIMESTAMP, NULL, 'open', '', CURRENT_TIMESTAMP)
        """,
        (alert_id, f"dedupe-{alert_id}", title, device_id),
    )


def test_monitoring_overview_queries_execute_and_remain_tenant_scoped(isolated_db, monkeypatch):
    tenant_a = f"overview-a-{uuid.uuid4().hex[:8]}"
    tenant_b = f"overview-b-{uuid.uuid4().hex[:8]}"
    administrator_named_tenant = "administrator"
    tenants = (tenant_a, tenant_b, administrator_named_tenant)
    devices = {tenant: f"device-{tenant}-{uuid.uuid4().hex[:6]}" for tenant in tenants}
    alerts = {tenant: f"alert-{tenant}-{uuid.uuid4().hex[:6]}" for tenant in tenants}

    conn = get_db_connection()
    try:
        conn.executemany("INSERT INTO tenants (id, name) VALUES (?, ?)", [(tenant, tenant) for tenant in tenants])
        for index, tenant in enumerate(tenants, start=1):
            conn.execute(
                """
                INSERT INTO devices (id, hostname, ip_address, platform, status, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (devices[tenant], f"overview-{tenant}", f"192.0.2.{index}", "h3c_comware", "online", tenant),
            )
            _insert_open_alert(conn, alert_id=alerts[tenant], device_id=devices[tenant], title=f"{tenant} alert")
        conn.commit()
    finally:
        conn.close()

    users_by_token = {
        "overview-tenant-a": {"username": "viewer-a", "role": "Viewer", "tenant_id": tenant_a},
        "overview-tenant-b": {"username": "viewer-b", "role": "Viewer", "tenant_id": tenant_b},
        "overview-administrator-tenant": {
            "username": "tenant-viewer",
            "role": "Viewer",
            "tenant_id": administrator_named_tenant,
        },
        "overview-admin": {"username": "admin", "role": "Administrator", "tenant_id": "tenant-default"},
    }
    monkeypatch.setattr(users, "validate_session_token", lambda token: users_by_token.get(token))

    overview_a = _request("GET", "/api/monitoring/overview?force_refresh=true", token="overview-tenant-a")
    overview_b = _request("GET", "/api/monitoring/overview?force_refresh=true", token="overview-tenant-b")
    assert overview_a.status_code == 200, overview_a.text
    assert overview_b.status_code == 200, overview_b.text
    assert overview_a.json()["total_devices"] == 1
    assert overview_a.json()["open_alerts"] == 1
    assert [item["id"] for item in overview_a.json()["recent_open_alerts"]] == [alerts[tenant_a]]
    assert overview_b.json()["total_devices"] == 1
    assert [item["id"] for item in overview_b.json()["recent_open_alerts"]] == [alerts[tenant_b]]

    # A tenant named "administrator" must have a distinct cache entry from
    # the administrator's unscoped overview.
    administrator_overview = _request(
        "GET", "/api/monitoring/overview?force_refresh=true", token="overview-admin"
    )
    special_tenant_overview = _request(
        "GET", "/api/monitoring/overview?force_refresh=true", token="overview-administrator-tenant"
    )
    cached_administrator_overview = _request("GET", "/api/monitoring/overview", token="overview-admin")
    assert administrator_overview.status_code == 200, administrator_overview.text
    assert special_tenant_overview.status_code == 200, special_tenant_overview.text
    assert cached_administrator_overview.status_code == 200, cached_administrator_overview.text
    assert administrator_overview.json()["total_devices"] == len(tenants)
    assert special_tenant_overview.json()["total_devices"] == 1
    assert cached_administrator_overview.json()["total_devices"] == len(tenants)

    search_a = _request(
        "GET", f"/api/monitoring/search-devices?q={tenant_a}", token="overview-tenant-a"
    )
    assert search_a.status_code == 200, search_a.text
    assert [item["id"] for item in search_a.json()["items"]] == [devices[tenant_a]]


def test_monitoring_overview_returns_zeroes_for_an_empty_tenant(isolated_db, monkeypatch):
    tenant_id = f"overview-empty-{uuid.uuid4().hex[:8]}"
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO tenants (id, name) VALUES (?, ?)", (tenant_id, tenant_id))
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        users,
        "validate_session_token",
        lambda _token: {"username": "empty-viewer", "role": "Viewer", "tenant_id": tenant_id},
    )

    response = _request("GET", "/api/monitoring/overview?force_refresh=true", token="overview-empty")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_devices"] == 0
    assert payload["online_devices"] == 0
    assert payload["open_alerts"] == 0
    assert payload["open_alert_severity_counts"] == {"critical": 0, "major": 0, "warning": 0}
