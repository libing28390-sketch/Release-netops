"""Track native LibreNMS identity and sample time in hardware projections."""

from __future__ import annotations


VERSION = 278
NAME = "librenms_native_inventory_projection"


def upgrade(cursor, use_pg: bool) -> None:
    """Extend the existing metric inventory without changing its old rows."""
    if not use_pg:
        raise RuntimeError("librenms_native_inventory_projection requires PostgreSQL")

    cursor.execute(
        "ALTER TABLE snmp_hardware_sensors "
        "ADD COLUMN IF NOT EXISTS data_origin TEXT NOT NULL DEFAULT 'legacy_snmp'"
    )
    cursor.execute(
        "ALTER TABLE snmp_hardware_sensors "
        "ADD COLUMN IF NOT EXISTS native_instance_id TEXT"
    )
    cursor.execute(
        "ALTER TABLE snmp_hardware_sensors "
        "ADD COLUMN IF NOT EXISTS native_device_id TEXT"
    )
    cursor.execute(
        "ALTER TABLE snmp_hardware_sensors "
        "ADD COLUMN IF NOT EXISTS native_entity_id TEXT"
    )
    cursor.execute(
        "ALTER TABLE snmp_hardware_sensors "
        "ADD COLUMN IF NOT EXISTS last_sample_at TIMESTAMPTZ"
    )
    cursor.execute(
        "UPDATE snmp_hardware_sensors "
        "SET last_sample_at = last_success "
        "WHERE last_sample_at IS NULL AND last_success IS NOT NULL"
    )
    # LibreNMS processor and memory-pool API rows need not expose a SNMP OID.
    # Their native identities are stored separately and are never fabricated as OIDs.
    cursor.execute("ALTER TABLE snmp_hardware_sensors ALTER COLUMN oid DROP NOT NULL")
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_snmp_hw_native_entity_measurement
            ON snmp_hardware_sensors(
                native_instance_id, native_device_id, native_entity_id,
                component_class, measurement_type, series_variant
            )
            WHERE data_origin = 'librenms_native'
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_snmp_hw_sensors_native_poll
            ON snmp_hardware_sensors(device_id, data_origin, last_sample_at DESC)
        """
    )


def downgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("librenms_native_inventory_projection requires PostgreSQL")
    cursor.execute(
        "SELECT COUNT(*) FROM snmp_hardware_sensors "
        "WHERE data_origin = 'librenms_native' OR oid IS NULL"
    )
    non_reversible_rows = int((cursor.fetchone() or (0,))[0] or 0)
    if non_reversible_rows:
        raise RuntimeError(
            "Cannot downgrade librenms_native_inventory_projection while native or null-OID hardware rows exist"
        )
    cursor.execute("DROP INDEX IF EXISTS idx_snmp_hw_sensors_native_poll")
    cursor.execute("DROP INDEX IF EXISTS uq_snmp_hw_native_entity_measurement")
    cursor.execute("ALTER TABLE snmp_hardware_sensors ALTER COLUMN oid SET NOT NULL")
    cursor.execute("ALTER TABLE snmp_hardware_sensors DROP COLUMN IF EXISTS last_sample_at")
    cursor.execute("ALTER TABLE snmp_hardware_sensors DROP COLUMN IF EXISTS native_entity_id")
    cursor.execute("ALTER TABLE snmp_hardware_sensors DROP COLUMN IF EXISTS native_device_id")
    cursor.execute("ALTER TABLE snmp_hardware_sensors DROP COLUMN IF EXISTS native_instance_id")
    cursor.execute("ALTER TABLE snmp_hardware_sensors DROP COLUMN IF EXISTS data_origin")


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
