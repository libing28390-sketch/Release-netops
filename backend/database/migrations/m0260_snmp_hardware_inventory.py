"""Persist per-measurement SNMP hardware inventory and discovery lifecycle."""

from __future__ import annotations


VERSION = 260
NAME = "snmp_hardware_inventory"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("SNMP hardware inventory requires PostgreSQL JSONB semantics")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS snmp_hardware_discovery_runs (
            attempt_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            tenant_id TEXT,
            asset_id TEXT,
            source_type TEXT NOT NULL,
            component_class TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('success', 'partial', 'failed', 'unsupported', 'not_found')
            ),
            coverage_complete BOOLEAN NOT NULL DEFAULT FALSE,
            discovered_count INTEGER NOT NULL DEFAULT 0 CHECK (discovered_count >= 0),
            rule_version TEXT NOT NULL DEFAULT '',
            discovery_version TEXT NOT NULL DEFAULT '',
            artifact_version TEXT NOT NULL DEFAULT '',
            reason_code TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            started_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
            UNIQUE (run_id, device_id, source_type, component_class)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_snmp_hw_discovery_runs_device_time
            ON snmp_hardware_discovery_runs(device_id, started_at DESC)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_snmp_hw_discovery_runs_scope_time
            ON snmp_hardware_discovery_runs(device_id, source_type, component_class, started_at DESC)
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS snmp_hardware_sensors (
            sensor_id TEXT PRIMARY KEY,
            tenant_id TEXT,
            asset_id TEXT,
            device_id TEXT NOT NULL,
            sensor_key TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL DEFAULT '',
            component_class TEXT NOT NULL,
            measurement_type TEXT NOT NULL,
            series_variant TEXT NOT NULL DEFAULT '',
            index_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            index_labels_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            oid TEXT NOT NULL DEFAULT '',
            unit TEXT NOT NULL DEFAULT '',
            scale DOUBLE PRECISION NOT NULL DEFAULT 1,
            value_offset DOUBLE PRECISION NOT NULL DEFAULT 0,
            states_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            thresholds_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            sensor_name TEXT NOT NULL DEFAULT '',
            entity_name TEXT NOT NULL DEFAULT '',
            group_name TEXT NOT NULL DEFAULT '',
            rule_version TEXT NOT NULL DEFAULT '',
            discovery_status TEXT NOT NULL DEFAULT 'present'
                CHECK (discovery_status IN ('present', 'not_present')),
            lifecycle_status TEXT NOT NULL DEFAULT 'active'
                CHECK (lifecycle_status IN ('active', 'pending_retirement', 'retired')),
            missing_success_count INTEGER NOT NULL DEFAULT 0 CHECK (missing_success_count >= 0),
            last_missing_run_id TEXT NOT NULL DEFAULT '',
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            last_value DOUBLE PRECISION,
            last_raw_value TEXT,
            last_quality TEXT NOT NULL DEFAULT 'missing'
                CHECK (last_quality IN ('good', 'missing', 'invalid', 'stale', 'unsupported_mapping')),
            first_seen TIMESTAMPTZ NOT NULL,
            last_seen TIMESTAMPTZ NOT NULL,
            last_success TIMESTAMPTZ,
            last_run_id TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
            UNIQUE (device_id, sensor_key),
            UNIQUE (device_id, source_type, component_class, measurement_type, index_json, series_variant)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_snmp_hw_sensors_device_class_state
            ON snmp_hardware_sensors(device_id, component_class, lifecycle_status, enabled)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_snmp_hw_sensors_scope_state
            ON snmp_hardware_sensors(device_id, source_type, component_class, lifecycle_status)
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS snmp_hardware_capabilities (
            device_id TEXT NOT NULL,
            tenant_id TEXT,
            asset_id TEXT,
            source_type TEXT NOT NULL,
            component_class TEXT NOT NULL,
            last_status TEXT NOT NULL
                CHECK (last_status IN ('success', 'partial', 'failed', 'unsupported', 'not_found')),
            coverage_complete BOOLEAN NOT NULL DEFAULT FALSE,
            active_sensor_count INTEGER NOT NULL DEFAULT 0 CHECK (active_sensor_count >= 0),
            last_discovered_count INTEGER NOT NULL DEFAULT 0 CHECK (last_discovered_count >= 0),
            rule_version TEXT NOT NULL DEFAULT '',
            discovery_version TEXT NOT NULL DEFAULT '',
            artifact_version TEXT NOT NULL DEFAULT '',
            last_run_id TEXT NOT NULL DEFAULT '',
            last_attempt_at TIMESTAMPTZ NOT NULL,
            last_success_at TIMESTAMPTZ,
            reason_code TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (device_id, source_type, component_class),
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_snmp_hw_capabilities_device_status
            ON snmp_hardware_capabilities(device_id, last_status, component_class)
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    cursor.execute("DROP TABLE IF EXISTS snmp_hardware_capabilities")
    cursor.execute("DROP TABLE IF EXISTS snmp_hardware_sensors")
    cursor.execute("DROP TABLE IF EXISTS snmp_hardware_discovery_runs")


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
