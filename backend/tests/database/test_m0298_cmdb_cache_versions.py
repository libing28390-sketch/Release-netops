from __future__ import annotations

from database import get_db_connection
from database.migrations.m0298_cmdb_cache_versions import upgrade
from services.cmdb_version_service import bump_read_versions, read_versions


def test_cmdb_read_versions_upgrade_and_upsert_are_idempotent(isolated_db):
    connection = get_db_connection()
    try:
        upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        assert connection.execute(
            "SELECT to_regclass('cmdb_collection_snapshots') AS present"
        ).fetchone()["present"]
        assert connection.execute(
            "SELECT to_regclass('cmdb_device_vlan_observations') AS present"
        ).fetchone()["present"]
        upgrade(connection.cursor(), use_pg=True)
        connection.commit()

        assert read_versions(connection, ["vlans", "bindings"]) == {
            "bindings": 0,
            "vlans": 0,
        }
        bump_read_versions(connection, ["vlans", "bindings", "vlans"])
        connection.commit()
        assert read_versions(connection, ["vlans", "bindings"]) == {
            "bindings": 1,
            "vlans": 1,
        }

        bump_read_versions(connection, ["vlans"], scope_key="site-a")
        connection.commit()
        assert read_versions(connection, ["vlans"], scope_key="site-a") == {"vlans": 1}
        assert read_versions(connection, ["vlans"]) == {"vlans": 1}
    finally:
        connection.close()
