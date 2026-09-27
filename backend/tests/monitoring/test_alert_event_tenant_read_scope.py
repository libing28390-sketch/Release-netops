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


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _insert_alert(conn, *, alert_id: str, device_id: str, title: str, dedupe_key: str) -> None:
    conn.execute(
        """
        INSERT INTO alert_events (
            id, dedupe_key, source, severity, title, message, device_id,
            interface_name, created_at, resolved_at, workflow_status, note, updated_at
        ) VALUES (?, ?, 'monitoring', 'critical', ?, 'test alert', ?, '', CURRENT_TIMESTAMP, NULL, 'open', '', CURRENT_TIMESTAMP)
        """,
        (alert_id, dedupe_key, title, device_id),
    )


def test_alert_list_summary_and_details_are_scoped_to_authenticated_tenant(isolated_db, monkeypatch):
    tenant_a = _id("tenant-alert-a")
    tenant_b = _id("tenant-alert-b")
    device_a = _id("device-alert-a")
    device_b = _id("device-alert-b")
    alert_a = _id("alert-a")
    alert_b = _id("alert-b")
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO tenants (id, name) VALUES (?, ?)", (tenant_a, tenant_a))
        conn.execute("INSERT INTO tenants (id, name) VALUES (?, ?)", (tenant_b, tenant_b))
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, site, tenant_id) VALUES (?, ?, ?, ?, ?)",
            (device_a, "tenant-a-edge", "192.0.2.10", "Tenant A Site", tenant_a),
        )
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, site, tenant_id) VALUES (?, ?, ?, ?, ?)",
            (device_b, "tenant-b-edge", "192.0.2.11", "Tenant B Site", tenant_b),
        )
        _insert_alert(conn, alert_id=alert_a, device_id=device_a, title="Tenant A CPU", dedupe_key="shared-dedupe")
        _insert_alert(conn, alert_id=alert_b, device_id=device_b, title="Tenant B CPU", dedupe_key="shared-dedupe")
        conn.execute(
            """
            INSERT INTO alert_events (
                id, dedupe_key, source, severity, title, message, device_id,
                interface_name, created_at, resolved_at, workflow_status, note, updated_at
            ) VALUES (?, 'system-event', 'monitoring', 'critical', 'Unscoped system event', 'system', NULL, '', CURRENT_TIMESTAMP, NULL, 'open', '', CURRENT_TIMESTAMP)
            """,
            (_id("alert-global"),),
        )
        conn.commit()
    finally:
        conn.close()

    tenant_user = {
        "user_id": _id("viewer-a"),
        "username": "tenant-a-viewer",
        "role": "Viewer",
        "tenant_id": tenant_a,
    }
    monkeypatch.setattr(users, "validate_session_token", lambda _token: tenant_user)
    headers = {"Authorization": "Bearer tenant-a-viewer-token"}

    listing = _request("GET", "/api/alerts?status=all", headers=headers)
    assert listing.status_code == 200, listing.text
    data = listing.json()
    assert data["total"] == 1
    assert [item["id"] for item in data["items"]] == [alert_a]
    assert data["filters"]["sites"] == ["Tenant A Site"]
    assert data["status_counts"]["all"] == 1

    summary = _request("GET", "/api/alerts/summary", headers=headers)
    assert summary.status_code == 200, summary.text
    assert summary.json()["open_count"] == 1
    assert summary.json()["critical_open"] == 1

    visible_detail = _request("GET", f"/api/alerts/{alert_a}", headers=headers)
    hidden_detail = _request("GET", f"/api/alerts/{alert_b}", headers=headers)
    assert visible_detail.status_code == 200, visible_detail.text
    assert hidden_detail.status_code == 404


def test_tenant_operator_cannot_acknowledge_another_tenants_alert(isolated_db, monkeypatch):
    tenant_a = _id("tenant-ack-a")
    tenant_b = _id("tenant-ack-b")
    device_b = _id("device-ack-b")
    alert_b = _id("alert-ack-b")
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO tenants (id, name) VALUES (?, ?)", (tenant_a, tenant_a))
        conn.execute("INSERT INTO tenants (id, name) VALUES (?, ?)", (tenant_b, tenant_b))
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, tenant_id) VALUES (?, ?, ?, ?)",
            (device_b, "tenant-b-edge", "192.0.2.21", tenant_b),
        )
        _insert_alert(conn, alert_id=alert_b, device_id=device_b, title="Tenant B alert", dedupe_key="tenant-b-alert")
        conn.commit()
    finally:
        conn.close()

    actor = {
        "user_id": _id("operator-a"),
        "username": "tenant-a-operator",
        "role": "Operator",
        "tenant_id": tenant_a,
    }
    monkeypatch.setattr(users, "validate_session_token", lambda _token: actor)
    response = _request(
        "POST",
        f"/api/alerts/{alert_b}/ack",
        headers={"Authorization": "Bearer tenant-a-operator-token"},
        json={"actor_username": "forged-admin"},
    )
    assert response.status_code == 404, response.text

    conn = get_db_connection()
    try:
        row = conn.execute("SELECT workflow_status, ack_by FROM alert_events WHERE id = ?", (alert_b,)).fetchone()
        assert row["workflow_status"] == "open"
        assert row["ack_by"] is None
    finally:
        conn.close()
