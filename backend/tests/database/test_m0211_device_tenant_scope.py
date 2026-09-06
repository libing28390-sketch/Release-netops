from __future__ import annotations

import database
from database.migrations import m0211_device_tenant_scope as migration


def test_device_tenant_migration_backfills_and_sets_default(isolated_db):
    conn = database.get_db_connection()
    legacy_ids = ("legacy-device-empty", "legacy-device-null")
    defaulted_id = "defaulted-device"
    try:
        conn.execute(
            "INSERT INTO devices (id, hostname, tenant_id) VALUES (?, ?, ?)",
            (legacy_ids[0], "legacy-empty", ""),
        )
        conn.execute(
            "INSERT INTO devices (id, hostname, tenant_id) VALUES (?, ?, ?)",
            (legacy_ids[1], "legacy-null", None),
        )
        conn.commit()

        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        rows = conn.execute(
            "SELECT id, tenant_id FROM devices WHERE id IN (?, ?) ORDER BY id",
            legacy_ids,
        ).fetchall()
        assert [dict(row) for row in rows] == [
            {"id": "legacy-device-empty", "tenant_id": "tenant-default"},
            {"id": "legacy-device-null", "tenant_id": "tenant-default"},
        ]

        # The PostgreSQL default protects direct/legacy writers that omit the
        # column after the migration has been applied.
        conn.execute(
            "INSERT INTO devices (id, hostname) VALUES (?, ?)",
            (defaulted_id, "defaulted"),
        )
        conn.commit()
        assert conn.execute(
            "SELECT tenant_id FROM devices WHERE id = ?",
            (defaulted_id,),
        ).fetchone()[0] == "tenant-default"

        # A second run must remain safe and must not alter the repaired values.
        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        assert conn.execute(
            "SELECT COUNT(*) FROM devices "
            "WHERE id IN (?, ?) AND tenant_id = 'tenant-default'",
            legacy_ids,
        ).fetchone()[0] == 2
    finally:
        conn.close()

