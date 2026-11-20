from __future__ import annotations

import uuid
from datetime import datetime, timezone

from services import rack_service


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def test_layout_read_model_exposes_explicit_occupancy_and_non_u_quality(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        rack = rack_service.create_rack(
            conn,
            name=_id("layout-rack"),
            site_id="site-default",
            total_u=42,
            power_capacity_watts=5000,
            rack_code=_id("layout-code"),
        )
        standard_type = rack_service.create_device_type(
            conn,
            model=_id("switch"),
            vendor="RackVision",
            u_height=2,
            device_role="switch",
            default_mount_kind="u_mount",
        )
        zero_u_type = rack_service.create_device_type(
            conn,
            model=_id("pdu"),
            vendor="RackVision",
            u_height=0,
            device_role="pdu",
            default_mount_kind="zero_u",
        )
        asset_id = _id("asset")
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        conn.execute(
            """INSERT INTO physical_assets (
                   id, asset_type, asset_tag, serial_number, hostname,
                   created_at, updated_at
               ) VALUES (?, 'network_device', ?, ?, ?, ?, ?)""",
            (asset_id, "AT-001", "SN-001", "edge-01", now, now),
        )
        conn.execute(
            """INSERT INTO devices (
                   id, asset_id, hostname, sn, status, site_id
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (_id("network"), asset_id, "edge-01", "SN-001", "online", "site-default"),
        )
        conn.commit()
        rack_service.create_rack_device(
            conn,
            name="standard-device",
            rack_id=rack["id"],
            device_type_id=standard_type["id"],
            start_u=10,
            height_u=2,
            position="front",
            mount_kind="u_mount",
            asset_id=asset_id,
        )
        rack_service.create_rack_device(
            conn,
            name="vertical-pdu",
            rack_id=rack["id"],
            device_type_id=zero_u_type["id"],
            start_u=None,
            height_u=None,
            position="rear",
            mount_kind="zero_u",
        )

        layout = rack_service.get_rack_layout(conn, rack["id"])
        assert layout["placements"] == layout["devices"]
        assert layout["occupancy"]["front"] == [10, 11]
        assert layout["occupancy"]["rear"] == []
        assert layout["occupancy"]["used_u"] == 2
        assert layout["data_quality"]["non_u_device_count"] == 1
        assert layout["data_quality"]["invalid_device_count"] == 0
        assert layout["meta"]["schema_version"] == "rack-layout-v1"
        assert layout["meta"]["layout_revision"] >= 1
        standard = next(item for item in layout["devices"] if item["name"] == "standard-device")
        assert standard["asset_id"] == asset_id
        assert standard["physical_asset_tag"] == "AT-001"
        assert standard["physical_serial_number"] == "SN-001"
        assert standard["network_device_id"]
        assert standard["network_hostname"] == "edge-01"
        assert standard["network_sn"] == "SN-001"
    finally:
        conn.close()
