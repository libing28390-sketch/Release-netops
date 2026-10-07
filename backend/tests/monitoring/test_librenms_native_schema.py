from __future__ import annotations

import pytest
from psycopg2.errors import CheckViolation, ForeignKeyViolation, RestrictViolation, UniqueViolation

import database
from database.migrations import discover_migrations
from database.migrations.m0277_librenms_native_bindings import upgrade
from database.migrations.m0278_librenms_native_inventory_projection import upgrade as upgrade_projection
from database.migrations.m0278_librenms_native_inventory_projection import downgrade as downgrade_projection
from backend.tests import pg_catalog_assertions as pg_catalog


def _reset_and_apply(conn) -> None:
    """Recreate just this migration's tables inside the isolated test DB."""
    conn.execute("DROP TABLE IF EXISTS librenms_device_bindings")
    conn.execute("DROP TABLE IF EXISTS librenms_instances")
    upgrade(conn.cursor(), use_pg=True)
    upgrade_projection(conn.cursor(), use_pg=True)
    conn.commit()


def _insert_instance(conn, instance_id: str, *, token_credential_id: str | None = None) -> None:
    conn.execute(
        """INSERT INTO librenms_instances
           (id, display_name, base_url, token_credential_id)
           VALUES (?, ?, ?, ?)""",
        (instance_id, f"LibreNMS {instance_id}", "https://librenms.internal", token_credential_id),
    )


def _insert_device(conn, device_id: str) -> None:
    asset_id = f"asset-{device_id}"
    conn.execute(
        "INSERT INTO physical_assets (id, created_at, updated_at) VALUES (?, ?, ?)",
        (asset_id, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO devices (id, hostname, asset_id, tenant_id) VALUES (?, ?, ?, ?)",
        (device_id, f"device-{device_id}", asset_id, "tenant-1"),
    )


def _insert_binding(
    conn,
    binding_id: str,
    *,
    device_id: str,
    instance_id: str,
    tenant_id: str = "tenant-1",
    asset_id: str | None = None,
    librenms_device_id: str | None = None,
) -> None:
    if asset_id is None:
        asset_id = conn.execute("SELECT asset_id FROM devices WHERE id = ?", (device_id,)).fetchone()[0]
    conn.execute(
        """INSERT INTO librenms_device_bindings
           (id, tenant_id, asset_id, device_id, instance_id, librenms_device_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (binding_id, tenant_id, asset_id, device_id, instance_id, librenms_device_id),
    )


def test_native_binding_migration_is_registered_idempotent_and_has_expected_shape(isolated_db):
    conn = database.get_db_connection()
    try:
        _reset_and_apply(conn)

        registered = discover_migrations()
        assert registered[-2].VERSION == 277
        assert registered[-2].NAME == "librenms_native_bindings"
        assert registered[-1].VERSION == 278
        assert registered[-1].NAME == "librenms_native_inventory_projection"

        instance_columns = pg_catalog.table_columns(conn, "librenms_instances")
        binding_columns = pg_catalog.table_columns(conn, "librenms_device_bindings")
        assert {
            "id", "display_name", "base_url", "token_credential_id", "engine_version",
            "engine_commit", "enabled", "health_state", "health_checked_at",
            "health_error_code", "health_error_text", "created_at", "updated_at",
        }.issubset(instance_columns)
        assert {
            "id", "tenant_id", "asset_id", "device_id", "instance_id",
            "librenms_device_id", "librenms_hostname", "collector_id", "poller_group",
            "desired_state", "sync_status", "last_sync_at", "last_discovery_at",
            "last_poll_at", "last_error_code", "last_error_text", "created_at", "updated_at",
        }.issubset(binding_columns)

        column_types = {
            (str(row[0]), str(row[1]))
            for row in conn.execute(
                """SELECT table_name, data_type
                   FROM information_schema.columns
                   WHERE table_schema = current_schema()
                     AND table_name IN ('librenms_instances', 'librenms_device_bindings')
                     AND column_name IN ('enabled', 'health_checked_at', 'last_poll_at')"""
            ).fetchall()
        }
        assert ("librenms_instances", "boolean") in column_types
        assert ("librenms_instances", "timestamp with time zone") in column_types
        assert ("librenms_device_bindings", "timestamp with time zone") in column_types

        instance_indexes = pg_catalog.index_names(conn, "librenms_instances")
        binding_indexes = pg_catalog.index_names(conn, "librenms_device_bindings")
        assert "idx_librenms_instances_enabled_health" in instance_indexes
        assert {
            "uq_librenms_bindings_device",
            "uq_librenms_bindings_native_device",
            "idx_librenms_bindings_tenant_asset_device",
            "idx_librenms_bindings_device",
            "idx_librenms_bindings_instance_sync_state",
            "idx_librenms_bindings_poller_group",
        }.issubset(binding_indexes)
        native_index = conn.execute(
            """SELECT indexdef FROM pg_indexes
               WHERE schemaname = current_schema()
                 AND indexname = 'uq_librenms_bindings_native_device'"""
        ).fetchone()[0]
        assert "UNIQUE INDEX" in str(native_index).upper()
        assert "WHERE (librenms_device_id IS NOT NULL)" in str(native_index)

        constraints = {
            str(row[0]): str(row[1])
            for row in conn.execute(
                """SELECT constraint_row.conname,
                          pg_get_constraintdef(constraint_row.oid)
                   FROM pg_constraint AS constraint_row
                   JOIN pg_class AS local_table ON local_table.oid = constraint_row.conrelid
                   JOIN pg_namespace AS namespace ON namespace.oid = local_table.relnamespace
                   WHERE namespace.nspname = current_schema()
                     AND local_table.relname IN ('librenms_instances', 'librenms_device_bindings')"""
            ).fetchall()
        }
        assert "FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE" in constraints.values()
        assert "FOREIGN KEY (asset_id) REFERENCES physical_assets(id) ON DELETE CASCADE" in constraints.values()
        assert "FOREIGN KEY (instance_id) REFERENCES librenms_instances(id) ON DELETE RESTRICT" in constraints.values()
        assert "FOREIGN KEY (token_credential_id) REFERENCES credentials(id) ON DELETE SET NULL" in constraints.values()

        upgrade_projection(conn.cursor(), use_pg=True)
        upgrade_projection(conn.cursor(), use_pg=True)
        conn.commit()
        sensor_columns = pg_catalog.table_columns(conn, "snmp_hardware_sensors")
        assert {
            "data_origin", "native_instance_id", "native_device_id", "native_entity_id",
            "last_sample_at",
        }.issubset(sensor_columns)
        sensor_indexes = pg_catalog.index_names(conn, "snmp_hardware_sensors")
        assert "uq_snmp_hw_native_entity_measurement" in sensor_indexes
        assert "idx_snmp_hw_sensors_native_poll" in sensor_indexes
    finally:
        conn.close()


def test_native_projection_downgrade_refuses_to_drop_native_rows(isolated_db):
    conn = database.get_db_connection()
    device_id = "native-downgrade-device"
    try:
        _insert_device(conn, device_id)
        conn.execute(
            """INSERT INTO snmp_hardware_sensors (
                   sensor_id, tenant_id, asset_id, device_id, sensor_key,
                   source_type, source_id, component_class, measurement_type,
                   oid, data_origin, native_instance_id, native_device_id,
                   native_entity_id, first_seen, last_seen, last_sample_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP,
                         CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (
                "native-downgrade-sensor",
                "tenant-1",
                f"asset-{device_id}",
                device_id,
                "librenms:lnms-1:17:processor:3:cpu_usage_percent",
                "librenms_native",
                "processor:3",
                "processor",
                "cpu_usage_percent",
                "",
                "librenms_native",
                "lnms-1",
                "17",
                "processor:3",
            ),
        )
        conn.commit()

        with pytest.raises(RuntimeError, match="native or null-OID hardware rows exist"):
            downgrade_projection(conn.cursor(), use_pg=True)

        assert "native_entity_id" in pg_catalog.table_columns(conn, "snmp_hardware_sensors")
    finally:
        conn.close()


def test_native_bindings_enforce_identity_state_and_deletion_contracts(isolated_db):
    conn = database.get_db_connection()
    try:
        _reset_and_apply(conn)
        conn.execute("INSERT INTO credentials (id) VALUES (?)", ("lnms-token-1",))
        _insert_instance(conn, "lnms-1", token_credential_id="lnms-token-1")
        _insert_instance(conn, "lnms-2")
        _insert_device(conn, "device-1")
        _insert_device(conn, "device-2")
        _insert_device(conn, "device-3")
        _insert_device(conn, "device-4")
        _insert_binding(
            conn,
            "binding-1",
            device_id="device-1",
            instance_id="lnms-1",
            librenms_device_id="native-42",
        )
        _insert_binding(conn, "binding-2", device_id="device-2", instance_id="lnms-1")
        # A native ID is scoped to one LibreNMS instance, and an unsynced
        # binding with NULL remote ID does not collide with another NULL.
        _insert_binding(
            conn,
            "binding-3",
            device_id="device-3",
            instance_id="lnms-2",
            librenms_device_id="native-42",
        )
        conn.commit()

        with pytest.raises(UniqueViolation):
            _insert_binding(conn, "duplicate-device", device_id="device-1", instance_id="lnms-1")
        conn.rollback()

        with pytest.raises(UniqueViolation):
            _insert_binding(
                conn,
                "duplicate-native-id",
                device_id="device-3",
                instance_id="lnms-1",
                librenms_device_id="native-42",
            )
        conn.rollback()

        with pytest.raises(CheckViolation):
            conn.execute(
                "UPDATE librenms_device_bindings SET desired_state = 'running' WHERE id = ?",
                ("binding-1",),
            )
        conn.rollback()
        with pytest.raises(CheckViolation):
            conn.execute(
                "UPDATE librenms_device_bindings SET sync_status = 'unknown' WHERE id = ?",
                ("binding-1",),
            )
        conn.rollback()
        with pytest.raises(CheckViolation):
            conn.execute(
                "UPDATE librenms_instances SET health_state = 'degraded' WHERE id = ?",
                ("lnms-1",),
            )
        conn.rollback()

        with pytest.raises(ForeignKeyViolation):
            _insert_binding(
                conn, "orphan-device", device_id="missing-device", instance_id="lnms-1",
                asset_id="asset-device-1",
            )
        conn.rollback()
        with pytest.raises(ForeignKeyViolation):
            _insert_binding(conn, "orphan-instance", device_id="device-4", instance_id="missing-instance")
        conn.rollback()

        # Removing the credential record clears only the reference; removing a
        # device cascades its Nexora binding. Instance removal is restricted
        # until bindings have been explicitly detached.
        conn.execute("DELETE FROM credentials WHERE id = ?", ("lnms-token-1",))
        assert conn.execute(
            "SELECT token_credential_id FROM librenms_instances WHERE id = ?", ("lnms-1",)
        ).fetchone()[0] is None
        conn.execute("DELETE FROM devices WHERE id = ?", ("device-1",))
        assert conn.execute(
            "SELECT 1 FROM librenms_device_bindings WHERE id = ?", ("binding-1",)
        ).fetchone() is None
        with pytest.raises(RestrictViolation):
            conn.execute("DELETE FROM librenms_instances WHERE id = ?", ("lnms-1",))
        conn.rollback()
    finally:
        conn.close()
