from __future__ import annotations

import pytest

from backend.tests.pg_test_utils import drop_test_database, postgresql_test_driver
from database.migrations import discover_migrations
from database.migrations.m0312_ipam_device_routing_contexts import VERSION, upgrade
from database.migrations.m0313_cmdb_interface_multi_address_observations import (
    VERSION as INTERFACE_ADDRESS_VERSION,
    upgrade as upgrade_interface_addresses,
)


def test_m0312_creates_explicit_routing_context_mappings_idempotently() -> None:
    connection = postgresql_test_driver.connect()
    target = connection._target
    try:
        connection.execute("CREATE TABLE devices (id TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE ipam_address_spaces (id TEXT PRIMARY KEY)")
        connection.commit()

        upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        upgrade(connection.cursor(), use_pg=True)
        connection.commit()

        assert VERSION in {int(module.VERSION) for module in discover_migrations()}
        columns = {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                """SELECT column_name, data_type, is_nullable
                     FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'ipam_device_routing_contexts'"""
            ).fetchall()
        }
        assert columns["address_space_id"] == ("text", "NO")
        assert columns["revision"] == ("integer", "NO")
        assert columns["last_verified_at"] == ("timestamp with time zone", "YES")

        connection.execute("INSERT INTO devices (id) VALUES (?)", ("context-device",))
        connection.execute(
            "INSERT INTO ipam_address_spaces (id) VALUES (?)", ("context-space",),
        )
        mapping_values = (
            "mapping-1", "context-device", "cli", "vrf", "PROD",
            "Production", "context-space",
        )
        connection.execute(
            """INSERT INTO ipam_device_routing_contexts
                   (id, device_id, context_source, context_type, local_context_key,
                    local_context_name, address_space_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            mapping_values,
        )
        connection.commit()

        with pytest.raises(postgresql_test_driver.IntegrityError):
            connection.execute(
                """INSERT INTO ipam_device_routing_contexts
                       (id, device_id, context_source, context_type, local_context_key,
                        local_context_name, address_space_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("mapping-duplicate", *mapping_values[1:]),
            )
        connection.rollback()
        assert connection.execute(
            "SELECT COUNT(*) FROM ipam_device_routing_contexts"
        ).fetchone()[0] == 1
    finally:
        connection.close()
        drop_test_database(target)


def test_m0313_stores_multiple_addresses_and_contexts_for_one_interface() -> None:
    connection = postgresql_test_driver.connect()
    target = connection._target
    try:
        connection.execute("CREATE TABLE devices (id TEXT PRIMARY KEY)")
        connection.execute(
            """CREATE TABLE cmdb_collection_snapshots (
                   device_id TEXT NOT NULL, domain TEXT NOT NULL,
                   successful_generation BIGINT NOT NULL,
                   PRIMARY KEY (device_id, domain)
               )"""
        )
        connection.execute(
            """CREATE TABLE cmdb_device_interface_observations (
                   device_id TEXT NOT NULL, normalized_interface_name TEXT NOT NULL,
                   interface_name TEXT NOT NULL, ip_address TEXT NOT NULL,
                   ip_prefix_length SMALLINT, generation BIGINT NOT NULL,
                   observed_at TEXT NOT NULL, run_id TEXT NOT NULL
               )"""
        )
        connection.execute(
            "INSERT INTO devices (id) VALUES (?), (?)",
            ("multi-ip-device", "stale-device"),
        )
        connection.execute(
            """INSERT INTO cmdb_collection_snapshots
                   (device_id, domain, successful_generation)
               VALUES ('multi-ip-device', 'interface_inventory', 2),
                      ('stale-device', 'interface_inventory', 2)"""
        )
        connection.execute(
            """INSERT INTO cmdb_device_interface_observations
                   (device_id, normalized_interface_name, interface_name, ip_address,
                    ip_prefix_length, generation, observed_at, run_id)
               VALUES ('multi-ip-device', 'vlan-interface1', 'Vlan-interface1',
                       '10.0.0.1', 24, 2, CURRENT_TIMESTAMP::text, 'run-current'),
                      ('stale-device', 'vlan-interface1', 'Vlan-interface1',
                       '10.0.1.1', 24, 1, CURRENT_TIMESTAMP::text, 'run-stale')"""
        )
        connection.commit()

        upgrade_interface_addresses(connection.cursor(), use_pg=True)
        connection.commit()
        upgrade_interface_addresses(connection.cursor(), use_pg=True)
        connection.commit()

        assert INTERFACE_ADDRESS_VERSION in {
            int(module.VERSION) for module in discover_migrations()
        }
        assert connection.execute(
            "SELECT COUNT(*) FROM cmdb_device_interface_address_observations"
        ).fetchone()[0] == 1
        current_row = connection.execute(
            """SELECT context_type, local_context_key, ip_address::text
                 FROM cmdb_device_interface_address_observations"""
        ).fetchone()
        assert tuple(current_row) == ("unknown", "", "10.0.0.1/32")

        address_rows = (
            ("10.0.0.1", 24, "vrf", "BLUE", "Vlan-interface1"),
            ("10.0.0.2", 32, "vrf", "BLUE", "Vlan-interface1"),
            ("10.0.0.1", 24, "vrf", "RED", "Vlan-interface1"),
        )
        for address, prefix_length, context_type, context_key, interface_name in address_rows:
            connection.execute(
                """INSERT INTO cmdb_device_interface_address_observations
                       (device_id, normalized_interface_name, interface_name,
                        context_source, context_type, local_context_key,
                        ip_address, ip_prefix_length, generation, observed_at)
                   VALUES (?, ?, ?, 'cli', ?, ?, ?::inet, ?, 1, CURRENT_TIMESTAMP)""",
                (
                    "multi-ip-device", interface_name.lower(), interface_name,
                    context_type, context_key, address, prefix_length,
                ),
            )
        connection.commit()

        assert connection.execute(
            "SELECT COUNT(*) FROM cmdb_device_interface_address_observations"
        ).fetchone()[0] == 4
        assert connection.execute(
            """SELECT COUNT(DISTINCT ip_address) FROM
                   cmdb_device_interface_address_observations
                WHERE device_id = ? AND normalized_interface_name = ?""",
            ("multi-ip-device", "vlan-interface1"),
        ).fetchone()[0] == 2
        assert connection.execute(
            """SELECT COUNT(DISTINCT local_context_key) FROM
                   cmdb_device_interface_address_observations
                WHERE device_id = ? AND normalized_interface_name = ?""",
            ("multi-ip-device", "vlan-interface1"),
        ).fetchone()[0] == 3
    finally:
        connection.close()
        drop_test_database(target)

def test_m0313_unknown_context_old_catalog_failure_rolls_back_and_retry_is_idempotent() -> None:
    connection = postgresql_test_driver.connect()
    target = connection._target
    try:
        connection.execute("CREATE TABLE devices (id TEXT PRIMARY KEY)")
        connection.execute(
            """CREATE TABLE cmdb_collection_snapshots (
                   device_id TEXT NOT NULL, domain TEXT NOT NULL,
                   successful_generation BIGINT NOT NULL,
                   PRIMARY KEY (device_id, domain)
               )"""
        )
        connection.execute(
            """CREATE TABLE cmdb_device_interface_observations (
                   device_id TEXT NOT NULL, normalized_interface_name TEXT NOT NULL,
                   interface_name TEXT NOT NULL, ip_address TEXT NOT NULL,
                   ip_prefix_length SMALLINT, generation BIGINT NOT NULL,
                   observed_at TEXT NOT NULL, run_id TEXT NOT NULL
               )"""
        )
        connection.execute(
            "INSERT INTO devices (id) VALUES (?)", ("global-m0313-device",),
        )
        connection.execute(
            """INSERT INTO cmdb_collection_snapshots
                   (device_id, domain, successful_generation)
               VALUES (?, 'interface_inventory', 2)""",
            ("global-m0313-device",),
        )
        connection.execute(
            """INSERT INTO cmdb_device_interface_observations
                   (device_id, normalized_interface_name, interface_name, ip_address,
                    ip_prefix_length, generation, observed_at, run_id)
               VALUES (?, 'vlan10', 'Vlan10', '192.0.2.10', 24, 2,
                       CURRENT_TIMESTAMP::text, 'global-current-run')""",
            ("global-m0313-device",),
        )
        connection.commit()

        def fail_after_m0313_ddl(cursor, use_pg: bool) -> None:
            upgrade_interface_addresses(cursor, use_pg)
            raise RuntimeError("synthetic m0313 failure after DDL and backfill")

        with pytest.raises(RuntimeError, match="synthetic m0313 failure after DDL and backfill"):
            fail_after_m0313_ddl(connection.cursor(), use_pg=True)
        connection.rollback()
        assert connection.execute(
            "SELECT to_regclass('cmdb_device_interface_address_observations')"
        ).fetchone()[0] is None
        assert connection.execute(
            "SELECT COUNT(*) FROM cmdb_device_interface_observations"
        ).fetchone()[0] == 1

        def catalog_snapshot() -> tuple:
            columns = tuple(
                tuple(row)
                for row in connection.execute(
                    """SELECT column_name, data_type, is_nullable, column_default
                         FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'cmdb_device_interface_address_observations'
                        ORDER BY ordinal_position"""
                ).fetchall()
            )
            constraints = tuple(
                tuple(row)
                for row in connection.execute(
                    """SELECT conname, contype, pg_get_constraintdef(oid, true)
                         FROM pg_constraint
                        WHERE conrelid = 'cmdb_device_interface_address_observations'::regclass
                        ORDER BY conname"""
                ).fetchall()
            )
            indexes = tuple(
                tuple(row)
                for row in connection.execute(
                    """SELECT indexname, indexdef FROM pg_indexes
                        WHERE schemaname = current_schema()
                          AND tablename = 'cmdb_device_interface_address_observations'
                        ORDER BY indexname"""
                ).fetchall()
            )
            return columns, constraints, indexes

        upgrade_interface_addresses(connection.cursor(), use_pg=True)
        connection.commit()
        first_catalog = catalog_snapshot()
        upgrade_interface_addresses(connection.cursor(), use_pg=True)
        connection.commit()
        second_catalog = catalog_snapshot()

        assert INTERFACE_ADDRESS_VERSION in {
            int(module.VERSION) for module in discover_migrations()
        }
        assert first_catalog == second_catalog
        assert connection.execute(
            "SELECT COUNT(*) FROM cmdb_device_interface_address_observations"
        ).fetchone()[0] == 1
        migrated = connection.execute(
            """SELECT context_type, local_context_key, host(ip_address),
                      ip_prefix_length, generation, run_id
                 FROM cmdb_device_interface_address_observations"""
        ).fetchone()
        assert tuple(migrated) == (
            "unknown", "", "192.0.2.10", 24, 2, "global-current-run",
        )
    finally:
        connection.close()
        drop_test_database(target)
