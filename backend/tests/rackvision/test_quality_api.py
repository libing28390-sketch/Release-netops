from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import uuid

import httpx

from main import app
from services import rack_data_quality_service, rack_service
from api import users


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def test_quality_issue_list_and_resolve_api(isolated_db, monkeypatch):
    monkeypatch.setattr(
        users,
        "validate_session_token",
        lambda token: {
            "user_id": "operator-1",
            "username": "operator",
            "role": "Operator",
            "tenant_id": "tenant-default",
        },
    )
    conn = isolated_db["module"].get_db_connection()
    try:
        rack = rack_service.create_rack(
            conn,
            name=_id("quality-rack"),
            site_id="site-default",
            rack_code=_id("quality-code"),
        )
        issue = rack_data_quality_service.upsert_issue(
            conn,
            entity_type="rack",
            entity_id=rack["id"],
            issue_code="SITE_SCOPE_MISSING",
            details={"rack_id": rack["id"]},
            commit=True,
        )
    finally:
        conn.close()

    headers = {"Authorization": "Bearer operator-token"}
    listed = _request("GET", f"/api/racks/{rack['id']}/quality-issues", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["data"]["items"][0]["id"] == issue["id"]

    audited = _request(
        "POST",
        "/api/rack-data-quality/audit",
        params={"rack_id": rack["id"]},
        headers=headers,
    )
    assert audited.status_code == 200, audited.text
    assert audited.json()["data"]["racks_checked"] == 1

    resolved = _request(
        "PUT",
        f"/api/rack-data-quality/issues/{issue['id']}/resolve",
        headers=headers,
        json={"resolution_note": "site scope verified"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["data"]["status"] == "resolved"


def test_scoped_quality_audit_reports_projection_and_power_conflicts(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    try:
        rack = rack_service.create_rack(
            conn,
            name=_id("audit-rack"),
            site_id="site-default",
            rack_code=_id("audit-code"),
            power_capacity_watts=5000,
        )
        device_type = rack_service.create_device_type(
            conn,
            model=_id("audit-model"),
            vendor="RackVision",
            u_height=2,
        )
        asset_id = _id("audit-asset")
        conn.execute(
            """INSERT INTO physical_assets (
                    id, asset_type, site_id, rack_id, rack_position,
                    rack_mount_kind, rack_location_status, u_height,
                    planned_start_u, created_at, updated_at
                ) VALUES (?, 'network_device', ?, ?, 'rear', 'u_mount',
                          'confirmed', 2, 99, ?, ?)""",
            (asset_id, "site-default", rack["id"], now, now),
        )
        conn.execute(
            """INSERT INTO rack_devices (
                    id, name, rack_id, device_type_id, start_u, position,
                    mount_kind, height_u, placement_status, placement_source,
                    dimension_status, location_note, model_key, status,
                    serial_number, asset_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 10, 'front', 'u_mount', 2, 'confirmed',
                          'manual', 'unknown', '', '', 'active', '', ?, ?, ?)""",
            (
                _id("audit-placement"),
                "audit-placement",
                rack["id"],
                device_type["id"],
                asset_id,
                now,
                now,
            ),
        )
        conn.execute(
            "UPDATE racks SET power_capacity_w = 7000, power_capacity_watts = 5000 WHERE id = ?",
            (rack["id"],),
        )
        conn.commit()

        result = rack_data_quality_service.audit_all(
            conn,
            rack_ids=(rack["id"],),
            commit=True,
        )
        assert result["racks_checked"] == 1
        assert result["rack_devices_checked"] == 1
        assert result["by_code"]["POWER_FIELD_CONFLICT"] == 1
        assert result["by_code"]["LEGACY_LOCATION_CONFLICT"] == 1
        assert result["issues_detected"] == 2
    finally:
        conn.close()
