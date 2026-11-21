from __future__ import annotations

import uuid

from api import assets
from database import get_db_connection
from database.migrations.m0218_device_telemetry_delete_cascade import upgrade


_TELEMETRY_TABLES = (
    "device_telemetry_samples",
    "device_telemetry_hourly",
)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _replace_with_no_action_constraints(conn) -> None:
    for table_name in _TELEMETRY_TABLES:
        conn.execute(
            f'ALTER TABLE "{table_name}" '
            f'DROP CONSTRAINT IF EXISTS "{table_name}_device_id_fkey"'
        )
        conn.execute(
            f'ALTER TABLE "{table_name}" '
            f'ADD CONSTRAINT "legacy_{table_name}_device_fk" '
            'FOREIGN KEY (device_id) REFERENCES devices(id)'
        )
    conn.commit()


def _delete_rules(conn) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT tc.table_name, rc.delete_rule
          FROM information_schema.table_constraints tc
          JOIN information_schema.referential_constraints rc
            ON tc.constraint_schema = rc.constraint_schema
           AND tc.constraint_name = rc.constraint_name
         WHERE tc.table_schema = current_schema()
           AND tc.table_name IN (?, ?)
           AND tc.constraint_type = 'FOREIGN KEY'
           AND tc.constraint_name LIKE '%device_id_fkey'
        """,
        _TELEMETRY_TABLES,
    ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def test_m0218_replaces_legacy_foreign_keys_idempotently(isolated_db) -> None:
    conn = get_db_connection()
    try:
        _replace_with_no_action_constraints(conn)

        upgrade(conn.cursor(), use_pg=True)
        upgrade(conn.cursor(), use_pg=True)

        assert _delete_rules(conn) == {
            "device_telemetry_samples": "CASCADE",
            "device_telemetry_hourly": "CASCADE",
        }
    finally:
        conn.close()


def test_device_telemetry_rows_follow_device_delete(isolated_db) -> None:
    conn = get_db_connection()
    device_id = _id("telemetry-device")
    try:
        conn.execute(
            "INSERT INTO devices (id, hostname) VALUES (?, ?)",
            (device_id, "telemetry-delete-test"),
        )
        conn.execute(
            """INSERT INTO device_telemetry_samples
                (ts, device_id, cpu_util, mem_avail, cpu_load, disk_util)
                VALUES (?, ?, ?, ?, ?, ?)""",
            ("2026-01-01T00:00:00+00:00", device_id, 1, 1, 1, 1),
        )
        conn.execute(
            "INSERT INTO device_telemetry_hourly (ts_hour, device_id) VALUES (?, ?)",
            ("2026-01-01T00:00:00+00:00", device_id),
        )
        conn.commit()

        conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))
        conn.commit()

        for table_name in _TELEMETRY_TABLES:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table_name} WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            assert row[0] == 0
    finally:
        conn.close()


def test_asset_delete_cleans_telemetry_on_legacy_no_action_installation(isolated_db) -> None:
    user = {
        "id": _id("telemetry-admin"),
        "user_id": _id("telemetry-admin-user"),
        "username": "telemetry-delete-admin",
        "role": "Administrator",
        "tenant_id": "tenant-default",
    }
    created = assets.create_asset(
        assets.AssetCreate(
            asset_type="server",
            asset_tag=_id("telemetry-asset"),
            hostname="telemetry-delete-asset",
            management_ip="192.0.2.220",
        ),
        _user=user,
    )
    device_id = created["device_id"]

    conn = get_db_connection()
    try:
        _replace_with_no_action_constraints(conn)
        conn.execute(
            """INSERT INTO device_telemetry_samples
                (ts, device_id, cpu_util, mem_avail, cpu_load, disk_util)
                VALUES (?, ?, ?, ?, ?, ?)""",
            ("2026-01-01T00:00:00+00:00", device_id, 1, 1, 1, 1),
        )
        conn.execute(
            "INSERT INTO device_telemetry_hourly (ts_hour, device_id) VALUES (?, ?)",
            ("2026-01-01T00:00:00+00:00", device_id),
        )
        conn.commit()
    finally:
        conn.close()

    result = assets.delete_asset(created["id"], _user=user)
    assert result == {"ok": True}

    conn = get_db_connection()
    try:
        for table_name in ("physical_assets", "devices", *_TELEMETRY_TABLES):
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table_name} "
                f"WHERE {'id' if table_name in ('physical_assets', 'devices') else 'device_id'} = ?",
                (created["id"] if table_name == "physical_assets" else device_id,),
            ).fetchone()
            assert row[0] == 0, table_name
    finally:
        conn.close()
