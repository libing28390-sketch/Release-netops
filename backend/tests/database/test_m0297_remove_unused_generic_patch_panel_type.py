from __future__ import annotations

import uuid

from database import get_db_connection
from database.migrations.m0297_remove_unused_generic_patch_panel_type import upgrade
from services import rack_service


def _generic_patch_panel(conn):
    row = conn.execute(
        "SELECT id FROM device_types WHERE vendor = ? AND model = ?",
        ("Generic", "Patch Panel 24P"),
    ).fetchone()
    if row:
        return str(row["id"])
    return str(
        rack_service.create_device_type(
            conn,
            model="Patch Panel 24P",
            vendor="Generic",
            device_role="patch_panel",
            description="24-port Cat6 patch panel",
        )["id"]
    )


def test_unused_generic_patch_panel_type_is_removed_idempotently(isolated_db):
    conn = get_db_connection()
    try:
        device_type_id = _generic_patch_panel(conn)

        upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        assert conn.execute(
            "SELECT 1 FROM device_types WHERE id = ?", (device_type_id,)
        ).fetchone() is None
    finally:
        conn.close()


def test_generic_patch_panel_type_in_use_by_rack_is_kept(isolated_db):
    conn = get_db_connection()
    try:
        device_type_id = _generic_patch_panel(conn)
        rack = rack_service.create_rack(
            conn,
            name=f"m0297-rack-{uuid.uuid4().hex[:8]}",
            site_id="site-default",
            rack_code=f"m0297-code-{uuid.uuid4().hex[:8]}",
            total_u=10,
        )
        placement = rack_service.create_rack_device(
            conn,
            name="referenced generic patch panel",
            rack_id=rack["id"],
            device_type_id=device_type_id,
            start_u=1,
        )

        upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        assert conn.execute(
            "SELECT 1 FROM device_types WHERE id = ?", (device_type_id,)
        ).fetchone()
        assert conn.execute(
            "SELECT 1 FROM rack_devices WHERE id = ?", (placement["id"],)
        ).fetchone()
    finally:
        conn.close()
