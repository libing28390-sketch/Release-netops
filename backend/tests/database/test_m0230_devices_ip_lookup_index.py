from __future__ import annotations

import database
from database.migrations import m0230_devices_ip_lookup_index as migration


def test_devices_ip_lookup_index_migration_is_idempotent(isolated_db):
    connection = database.get_db_connection()
    try:
        connection.execute("DROP INDEX IF EXISTS idx_devices_ip_address")
        connection.commit()

        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()

        row = connection.execute(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = current_schema() AND tablename = 'devices' "
            "AND indexname = 'idx_devices_ip_address'"
        ).fetchone()
        assert row is not None
        assert "(ip_address)" in str(row[0])
    finally:
        connection.close()
