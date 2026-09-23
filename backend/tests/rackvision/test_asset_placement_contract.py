"""Asset API placement DTO contract tests."""

from __future__ import annotations

import asyncio
import uuid

import httpx

from api import assets, devices, users
from database import get_db_connection
from main import app
from services import rack_service


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def test_asset_detail_exposes_canonical_placement_without_dropping_legacy_fields(
    isolated_db,
    make_user,
    monkeypatch,
):
    conn = isolated_db["module"].get_db_connection()
    site_id = _id("placement-site")
    site_code = _id("placement-code")
    site_name = "RackVision placement site"
    conn.execute(
        """INSERT INTO sites (id, site_code, site_name, status, tenant_id)
           VALUES (?, ?, ?, 'active', ?)""",
        (site_id, site_code, site_name, "tenant-default"),
    )
    conn.commit()
    rack = rack_service.create_rack(
        conn,
        name=_id("placement-rack"),
        site_id=site_id,
        total_u=42,
        rack_code=_id("placement-code"),
    )
    device_type = rack_service.create_device_type(
        conn,
        model=_id("placement-model"),
        vendor="RackVision",
        u_height=2,
        device_role="switch",
        default_mount_kind="u_mount",
    )
    asset = assets.create_asset(
        assets.AssetCreate(
            asset_type="network_device",
            asset_tag=_id("placement-asset"),
            hostname=_id("placement-host"),
            vendor="RackVision",
            model=device_type["model"],
            site_id=site_id,
            management_ip="192.0.2.150",
        )
    )
    rack_service.create_rack_device(
        conn,
        name="canonical-placement",
        rack_id=rack["id"],
        device_type_id=device_type["id"],
        start_u=12,
        position="rear",
        mount_kind="u_mount",
        height_u=2,
        placement_status="confirmed",
        placement_source="manual",
        asset_id=asset["id"],
        commit=True,
    )
    conn.close()

    user = make_user(_id("placement-viewer"), role="Viewer")
    user_payload = {
        "user_id": user["user_id"],
        "id": user["user_id"],
        "username": user["username"],
        "role": "Viewer",
        "tenant_id": "tenant-default",
    }
    monkeypatch.setattr(users, "validate_session_token", lambda token: user_payload)

    detail = _request(
        "GET",
        f"/api/assets/{asset['id']}",
        headers={"Authorization": "Bearer placement-token"},
    )
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["rack_id"] == rack["id"]
    assert payload["planned_start_u"] == 12
    placement = payload["placement"]
    assert placement["id"]
    expected = {
        "asset_id": asset["id"],
        "rack_id": rack["id"],
        "rack_code": rack["rack_code"],
        "rack_name": rack["name"],
        "rack_site_id": site_id,
        "rack_site_code": site_code,
        "rack_site_name": site_name,
        "device_type_id": device_type["id"],
        "start_u": 12,
        "end_u": 13,
        "height_u": 2,
        "position": "rear",
        "mount_kind": "u_mount",
        "placement_status": "confirmed",
        "placement_source": "manual",
        "dimension_status": "unknown",
        "location_note": "",
        "status": "active",
        "serial_number": "",
    }
    for key, value in expected.items():
        assert placement[key] == value
    assert placement["model_key"]


def test_asset_without_canonical_placement_returns_null_placement(isolated_db):
    asset = assets.create_asset(
        assets.AssetCreate(
            asset_type="server",
            asset_tag=_id("unplaced-asset"),
            hostname=_id("unplaced-host"),
            management_ip="192.0.2.151",
        )
    )
    payload = assets.get_asset(asset["id"])
    assert payload["placement"] is None


def test_direct_device_delete_clears_rack_placement_for_reimport(isolated_db):
    """Deleting from the network-device inventory must not leave a ghost U row."""
    conn = isolated_db["module"].get_db_connection()
    site_id = _id("delete-site")
    conn.execute(
        """INSERT INTO sites (id, site_code, site_name, status, tenant_id)
           VALUES (?, ?, ?, 'active', ?)""",
        (site_id, _id("delete-code"), "Delete placement site", "tenant-default"),
    )
    conn.commit()
    rack = rack_service.create_rack(
        conn,
        name=_id("delete-rack"),
        site_id=site_id,
        total_u=42,
        rack_code=_id("delete-rack-code"),
    )
    device_type = rack_service.create_device_type(
        conn,
        model=_id("delete-model"),
        vendor="RackVision",
        u_height=1,
        device_role="switch",
    )
    first_hostname = _id("delete-host")
    first = assets.create_asset(
        assets.AssetCreate(
            asset_type="network_device",
            asset_tag=_id("delete-asset"),
            hostname=first_hostname,
            vendor="RackVision",
            model=device_type["model"],
            site_id=site_id,
            management_ip="192.0.2.181",
        )
    )
    conn.close()
    conn = get_db_connection()
    device_row = conn.execute(
        "SELECT id FROM devices WHERE asset_id = ?", (first["id"],)
    ).fetchone()
    rack_service.create_rack_device(
        conn,
        name=first_hostname,
        rack_id=rack["id"],
        device_type_id=device_type["id"],
        start_u=10,
        position="front",
        height_u=1,
        placement_status="confirmed",
        placement_source="manual",
        asset_id=first["id"],
        commit=True,
    )
    conn.close()

    devices.delete_device(device_row["id"])

    conn = get_db_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM physical_assets WHERE id = ?", (first["id"],)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM devices WHERE id = ?", (device_row["id"],)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM rack_devices WHERE asset_id = ?", (first["id"],)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM racks WHERE id = ?", (rack["id"],)).fetchone()[0] == 1
    finally:
        conn.close()

    replacement_hostname = _id("replacement-host")
    import_result = assets.import_assets(
        [assets.AssetCreate(
            asset_type="network_device",
            asset_tag=_id("replacement-asset"),
            hostname=replacement_hostname,
            vendor="RackVision",
            model=device_type["model"],
            site_id=site_id,
            rack_id=rack["id"],
            rack_position="front",
            rack_placement_status="confirmed",
            planned_start_u=10,
            u_height=1,
            management_ip="192.0.2.182",
        )],
        detailed=True,
    )
    assert import_result["created"] == 1
    replacement = {"id": import_result["results"][0]["asset_id"]}
    conn = get_db_connection()
    try:
        placement = conn.execute(
            "SELECT rack_id, start_u FROM rack_devices WHERE asset_id = ?",
            (replacement["id"],),
        ).fetchone()
        assert placement["rack_id"] == rack["id"]
        assert placement["start_u"] == 10
    finally:
        conn.close()
