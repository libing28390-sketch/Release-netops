from __future__ import annotations

from datetime import datetime, timezone

import pytest

from database import get_db_connection
from database.migrations.m0315_ipam_unknown_context_keys import VERSION, upgrade
from database.migrations import discover_migrations


def test_m0315_retains_unknown_raw_context_keys_idempotently(isolated_db):
    assert VERSION in {int(module.VERSION) for module in discover_migrations()}
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO devices (id, hostname, ip_address, platform, status)
               VALUES ('unknown-context-device', 'unknown-context-device',
                       '192.0.2.15', 'cisco_ios', 'online')"""
        )
        upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        observed_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO ipam_endpoint_collection_states (
                   device_id, observation_source, context_source, context_type,
                   local_context_key, latest_status, last_attempt_at
               ) VALUES (
                   'unknown-context-device', 'arp', 'cli', 'unknown', 'default',
                   'scope_unknown', ?
               )""",
            (observed_at,),
        )
        conn.execute(
            """INSERT INTO cmdb_device_interface_address_observations (
                   device_id, normalized_interface_name, interface_name,
                   context_source, context_type, local_context_key,
                   local_context_name, ip_address, ip_prefix_length,
                   generation, observed_at, run_id, metadata_json
               ) VALUES (
                   'unknown-context-device', 'vlan10', 'Vlan10', 'cli',
                   'unknown', 'default', 'default', '198.51.100.15'::inet,
                   24, 1, ?, 'run-1', '{}'::jsonb
               )""",
            (observed_at,),
        )
        conn.execute(
            """INSERT INTO ipam_current_endpoint_observations (
                   source_device_id, observation_source, context_source,
                   context_type, local_context_key, local_context_name,
                   ip_address, mac_address, generation, observed_at
               ) VALUES (
                   'unknown-context-device', 'arp', 'cli', 'unknown',
                   'global', 'global', '198.51.100.15'::inet,
                   '001122334455', 1, ?
               )""",
            (observed_at,),
        )
        conn.commit()

        assert conn.execute(
            """SELECT COUNT(*) FROM ipam_endpoint_collection_states
                WHERE device_id = 'unknown-context-device'
                  AND context_type = 'unknown' AND local_context_key = 'default'"""
        ).fetchone()[0] == 1
        assert conn.execute(
            """SELECT COUNT(*) FROM cmdb_device_interface_address_observations
                WHERE device_id = 'unknown-context-device'
                  AND context_type = 'unknown' AND local_context_key = 'default'"""
        ).fetchone()[0] == 1
        assert conn.execute(
            """SELECT COUNT(*) FROM ipam_current_endpoint_observations
                WHERE source_device_id = 'unknown-context-device'
                  AND context_type = 'unknown' AND local_context_key = 'global'"""
        ).fetchone()[0] == 1

def test_m0315_unknown_raw_key_catalog_failure_rolls_back_and_retry_is_idempotent(
    isolated_db,
):
    del isolated_db
    old_checks = {
        "cmdb_device_interface_address_observations": "cmdb_interface_address_context_key_chk",
        "ipam_current_endpoint_observations": "ck_ipam_current_endpoint_context_key",
        "ipam_endpoint_collection_states": "ck_ipam_endpoint_state_context_key",
    }
    old_definition = """CHECK (
        (context_type = 'unknown' AND local_context_key = '')
        OR (context_type IN ('vrf', 'global') AND btrim(local_context_key) <> '')
    )"""
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO devices (id, hostname, ip_address, platform, status)
               VALUES ('m0315-unknown-rollback-device', 'm0315-unknown-rollback-device',
                       '192.0.2.31', 'cisco_ios', 'online')"""
        )
        for table_name, constraint_name in old_checks.items():
            conn.execute(
                f"ALTER TABLE {table_name} DROP CONSTRAINT IF EXISTS {constraint_name}"
            )
            conn.execute(
                f"ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} {old_definition}"
            )
        conn.commit()

    def fail_after_m0315_constraints(cursor, use_pg: bool) -> None:
        upgrade(cursor, use_pg)
        raise RuntimeError("synthetic m0315 failure after check replacement")

    with get_db_connection() as conn:
        with pytest.raises(RuntimeError, match="synthetic m0315 failure after check replacement"):
            fail_after_m0315_constraints(conn.cursor(), use_pg=True)
        conn.rollback()
        old_definitions = {
            table_name: conn.execute(
                """SELECT pg_get_constraintdef(oid, true)
                     FROM pg_constraint
                    WHERE conrelid = ?::regclass AND conname = ?""",
                (table_name, constraint_name),
            ).fetchone()[0]
            for table_name, constraint_name in old_checks.items()
        }
        assert all("local_context_key = ''" in definition for definition in old_definitions.values())

        upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        first_definitions = {
            table_name: conn.execute(
                """SELECT pg_get_constraintdef(oid, true)
                     FROM pg_constraint
                    WHERE conrelid = ?::regclass AND conname = ?""",
                (table_name, constraint_name),
            ).fetchone()[0]
            for table_name, constraint_name in old_checks.items()
        }
        upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        second_definitions = {
            table_name: conn.execute(
                """SELECT pg_get_constraintdef(oid, true)
                     FROM pg_constraint
                    WHERE conrelid = ?::regclass AND conname = ?""",
                (table_name, constraint_name),
            ).fetchone()[0]
            for table_name, constraint_name in old_checks.items()
        }
        assert first_definitions == second_definitions
        assert all("context_type = 'unknown'" in definition for definition in first_definitions.values())

        observed_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO ipam_endpoint_collection_states (
                   device_id, observation_source, context_source, context_type,
                   local_context_key, latest_status, last_attempt_at
               ) VALUES (
                   'm0315-unknown-rollback-device', 'arp', 'cli', 'unknown',
                   'raw-blue-key', 'scope_unknown', ?
               )""",
            (observed_at,),
        )
        conn.execute(
            """INSERT INTO cmdb_device_interface_address_observations (
                   device_id, normalized_interface_name, interface_name,
                   context_source, context_type, local_context_key,
                   local_context_name, ip_address, ip_prefix_length,
                   generation, observed_at, run_id, metadata_json
               ) VALUES (
                   'm0315-unknown-rollback-device', 'vlan31', 'Vlan31', 'cli',
                   'unknown', 'raw-blue-key', 'Blue', '198.51.100.31'::inet,
                   24, 1, ?, 'm0315-run', '{}'::jsonb
               )""",
            (observed_at,),
        )
        conn.execute(
            """INSERT INTO ipam_current_endpoint_observations (
                   source_device_id, observation_source, context_source,
                   context_type, local_context_key, local_context_name,
                   ip_address, mac_address, generation, observed_at
               ) VALUES (
                   'm0315-unknown-rollback-device', 'arp', 'cli', 'unknown',
                   'raw-blue-key', 'Blue', '198.51.100.31'::inet,
                   '001122334455', 1, ?
               )""",
            (observed_at,),
        )
        conn.commit()
        for table_name, device_column in (
            ("ipam_endpoint_collection_states", "device_id"),
            ("cmdb_device_interface_address_observations", "device_id"),
            ("ipam_current_endpoint_observations", "source_device_id"),
        ):
            assert conn.execute(
                f"""SELECT COUNT(*) FROM {table_name}
                      WHERE {device_column} = 'm0315-unknown-rollback-device'
                        AND context_type = 'unknown'
                        AND local_context_key = 'raw-blue-key'"""
            ).fetchone()[0] == 1
