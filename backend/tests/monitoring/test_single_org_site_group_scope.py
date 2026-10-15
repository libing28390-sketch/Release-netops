from __future__ import annotations

import asyncio
import uuid

import httpx

from api import users
from database import get_db_connection
from main import app
from services.collection_status_service import record_collection_result
from services.monitoring_incident_service import sync_incidents


def _request(method: str, path: str, *, token: str, **kwargs) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(
                method,
                path,
                headers={"Authorization": f"Bearer {token}"},
                **kwargs,
            )

    return asyncio.run(run())


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _insert_alert(conn, *, alert_id: str, device_id: str) -> None:
    conn.execute(
        """
        INSERT INTO alert_events (
            id, dedupe_key, source, severity, title, message, device_id,
            interface_name, created_at, resolved_at, workflow_status, note, updated_at
        ) VALUES (?, ?, 'monitoring', 'major', ?, 'scope regression', ?, '',
                  CURRENT_TIMESTAMP, NULL, 'open', '', CURRENT_TIMESTAMP)
        """,
        (alert_id, f"scope:{alert_id}", f"Alert {device_id}", device_id),
    )


def test_monitoring_and_alert_routes_apply_site_and_device_group_scope(
    isolated_db,
    make_user,
    monkeypatch,
):
    user_row = make_user("single-org-monitor-scope", role="Operator", tenant_id="tenant-default")
    user_id = user_row["user_id"]
    token = "single-org-monitor-scope-token"
    actor = {
        **user_row,
        "id": user_id,
        "scope_mode": "restricted",
        # The devices intentionally carry legacy tenant IDs. In one-organization
        # mode, site and group grants remain the boundary.
    }
    monkeypatch.setattr(users, "validate_session_token", lambda _token: actor)

    site_a, site_b, site_c = (_id("site") for _ in range(3))
    device_group = "scope-group-a"
    devices = {
        "group": _id("device-group"),
        "site": _id("device-site"),
        "hidden": _id("device-hidden"),
    }
    alerts = {key: _id(f"alert-{key}") for key in devices}
    conn = get_db_connection()
    try:
        conn.execute("UPDATE users SET scope_mode = 'restricted' WHERE id = ?", (user_id,))
        for site_id in (site_a, site_b, site_c):
            conn.execute(
                "INSERT INTO sites (id, site_code, site_name, status) VALUES (?, ?, ?, 'active')",
                (site_id, site_id, site_id),
            )
        conn.executemany(
            """INSERT INTO user_resource_scopes
               (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
               VALUES (?, ?, 'asset', ?, ?, '["view", "update"]', CURRENT_TIMESTAMP)""",
            [
                (_id("scope-group"), user_id, "device_group", device_group),
                (_id("scope-site"), user_id, "site", site_c),
            ],
        )
        for device_id, site_id, group_id, tenant_id in (
            (devices["group"], site_a, device_group, "legacy-tenant-a"),
            (devices["site"], site_c, "scope-group-other", "legacy-tenant-b"),
            (devices["hidden"], site_b, "scope-group-hidden", "legacy-tenant-c"),
        ):
            conn.execute(
                """INSERT INTO devices
                   (id, hostname, ip_address, platform, status, role, site, site_id,
                    device_group_id, tenant_id, device_category)
                   VALUES (?, ?, ?, 'h3c_comware', 'online', 'access', ?, ?, ?, ?, 'network_device')""",
                (
                    device_id,
                    f"edge-{device_id}",
                    "192.0.2.10",
                    site_id,
                    site_id,
                    group_id,
                    tenant_id,
                ),
            )
            _insert_alert(conn, alert_id=alerts[next(key for key, value in devices.items() if value == device_id)], device_id=device_id)
        conn.commit()
    finally:
        conn.close()


    for key, device_id in devices.items():
        record_collection_result(device_id, "reachability", status="success")

    conn = get_db_connection()
    try:
        sync_incidents(conn, return_incidents=False)
    finally:
        conn.close()


    headers_token = token
    device_list = _request("GET", "/api/monitoring/network-devices?status=all", token=headers_token)
    assert device_list.status_code == 200, device_list.text
    assert {item["id"] for item in device_list.json()["items"]} == {devices["group"], devices["site"]}

    collection_status = _request("GET", "/api/monitoring/collection-status", token=headers_token)
    assert collection_status.status_code == 200, collection_status.text
    assert {item["device_id"] for item in collection_status.json()["items"]} == {
        devices["group"],
        devices["site"],
    }
    assert collection_status.json()["summary"]["total"] == 2

    health = _request("GET", "/api/monitoring/health-devices", token=headers_token)
    assert health.status_code == 200, health.text
    assert {item["id"] for item in health.json()["items"]} == {devices["group"], devices["site"]}

    report = _request("GET", "/api/monitoring/reports/data?report_type=devices", token=headers_token)
    assert report.status_code == 200, report.text
    assert {item["id"] for item in report.json()["items"]} == {devices["group"], devices["site"]}
    outbound_report = _request("GET", "/api/monitoring/reports/data?report_type=outbound", token=headers_token)
    assert outbound_report.status_code == 200, outbound_report.text
    assert outbound_report.json()["items"] == []

    visible_trend = _request(
        "GET",
        f"/api/monitoring/device/{devices['group']}/trend?provider=native",
        token=headers_token,
    )
    hidden_trend = _request(
        "GET",
        f"/api/monitoring/device/{devices['hidden']}/trend?provider=native",
        token=headers_token,
    )
    assert visible_trend.status_code == 200, visible_trend.text
    assert hidden_trend.status_code == 404

    denied_diagnostics = _request(
        "POST",
        f"/api/monitoring/device/{devices['hidden']}/diagnostics",
        token=headers_token,
    )
    assert denied_diagnostics.status_code == 404

    incidents = _request("GET", "/api/monitoring/incidents?status=all&page_size=100", token=headers_token)
    assert incidents.status_code == 200, incidents.text
    assert {
        item["primary_device_id"] for item in incidents.json()["items"]
    } == {devices["group"], devices["site"]}

    alerts_list = _request("GET", "/api/alerts?status=all", token=headers_token)
    assert alerts_list.status_code == 200, alerts_list.text
    assert {item["id"] for item in alerts_list.json()["items"]} == {alerts["group"], alerts["site"]}
    assert alerts_list.json()["total"] == 2
    assert alerts_list.json()["status_counts"]["all"] == 2

    summary = _request("GET", "/api/alerts/summary", token=headers_token)
    assert summary.status_code == 200, summary.text
    assert summary.json()["open_count"] == 2

    hidden_detail = _request("GET", f"/api/alerts/{alerts['hidden']}", token=headers_token)
    assert hidden_detail.status_code == 404
    denied_batch_assign = _request(
        "POST",
        "/api/alerts/batch-assign",
        token=headers_token,
        json={"alert_ids": [alerts["hidden"]], "assignee": "scope-operator"},
    )
    assert denied_batch_assign.status_code == 404

    scope_catalog = _request(
        "GET",
        "/api/alerts/rules/scope-catalog?search=edge-device-",
        token=headers_token,
    )
    assert scope_catalog.status_code == 200, scope_catalog.text
    assert {item["id"] for item in scope_catalog.json()["devices"]} == {
        devices["group"],
        devices["site"],
    }

    conn = get_db_connection()
    try:
        hidden_alert = conn.execute(
            "SELECT assignee FROM alert_events WHERE id = ?",
            (alerts["hidden"],),
        ).fetchone()
        assert hidden_alert["assignee"] is None
    finally:
        conn.close()


def test_notification_writes_use_default_tenant_and_recipients_cross_legacy_tenants(
    isolated_db,
    make_user,
):
    from api.alerts import _notification_tenant_id, _validated_recipient_targets

    tenant_a_user = make_user("notification-tenant-a", role="Administrator", tenant_id="legacy-a")
    tenant_b_user = make_user("notification-tenant-b", role="Viewer", tenant_id="legacy-b")
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE users SET group_name = 'shared-noc' WHERE id IN (?, ?)",
            (tenant_a_user["user_id"], tenant_b_user["user_id"]),
        )
        targets = _validated_recipient_targets(
            conn,
            "tenant-default",
            [
                {"kind": "user", "user_id": tenant_b_user["user_id"]},
                {"kind": "group", "group_name": "shared-noc"},
            ],
            allow_empty=False,
        )
        conn.commit()
    finally:
        conn.close()

    assert _notification_tenant_id({"tenant_id": "legacy-b"}) == "tenant-default"
    assert targets == [
        {"kind": "user", "user_id": tenant_b_user["user_id"]},
        {"kind": "group", "group_name": "shared-noc"},
    ]
