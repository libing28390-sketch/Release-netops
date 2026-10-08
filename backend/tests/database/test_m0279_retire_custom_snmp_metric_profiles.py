from __future__ import annotations

import importlib

import pytest


def test_retired_profile_migration_clears_all_custom_oid_bindings(isolated_db) -> None:
    database = isolated_db["module"]
    migration = importlib.import_module(
        "database.migrations.m0279_retire_custom_snmp_metric_profiles"
    )
    connection = database.get_db_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "CREATE TEMP TABLE devices (snmp_metric_profile_id TEXT)"
        )
        cursor.execute("CREATE TEMP TABLE snmp_metric_profiles (id INTEGER)")
        cursor.execute(
            "INSERT INTO devices (snmp_metric_profile_id) VALUES "
            "('profile-a'), (' profile-b '), ('  '), (NULL)"
        )
        cursor.execute("INSERT INTO snmp_metric_profiles (id) VALUES (1), (2)")

        migration.upgrade(cursor, use_pg=True)

        cursor.execute(
            "SELECT snmp_metric_profile_id FROM devices "
            "ORDER BY snmp_metric_profile_id NULLS LAST"
        )
        assert [row[0] for row in cursor.fetchall()] == ["", "", "  ", None]
        cursor.execute("SELECT COUNT(*) FROM snmp_metric_profiles")
        assert cursor.fetchone()[0] == 0

        # The migration is safe if the upgrade is replayed.
        migration.upgrade(cursor, use_pg=True)
        cursor.execute("SELECT COUNT(*) FROM snmp_metric_profiles")
        assert cursor.fetchone()[0] == 0
    finally:
        connection.rollback()
        cursor.close()
        connection.close()


def test_retired_profile_migration_is_irreversible() -> None:
    migration = importlib.import_module(
        "database.migrations.m0279_retire_custom_snmp_metric_profiles"
    )
    with pytest.raises(RuntimeError, match="cannot be restored"):
        migration.downgrade(object(), use_pg=True)
