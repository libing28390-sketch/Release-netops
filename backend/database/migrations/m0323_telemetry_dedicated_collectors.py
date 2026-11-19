"""Give Telemetry its own collector registry and capacity pool."""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 323
NAME = "telemetry_dedicated_collectors"


_UTC_NOW_SQL = "(to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'))"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Dedicated Telemetry collector registry requires PostgreSQL")

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS telemetry_collectors (
            id TEXT PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            collector_type TEXT NOT NULL DEFAULT 'LOCAL'
                CHECK (collector_type IN ('LOCAL', 'REMOTE')),
            status TEXT NOT NULL DEFAULT 'UNKNOWN',
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            management_address TEXT NOT NULL DEFAULT '',
            device_limit INTEGER NOT NULL DEFAULT 50 CHECK (device_limit > 0),
            series_limit INTEGER NOT NULL DEFAULT 25000 CHECK (series_limit > 0),
            samples_per_second_limit DOUBLE PRECISION NOT NULL DEFAULT 5000
                CHECK (samples_per_second_limit > 0),
            message_bytes_limit BIGINT NOT NULL DEFAULT 4194304 CHECK (message_bytes_limit > 0),
            queue_bytes_limit BIGINT NOT NULL DEFAULT 17179869184 CHECK (queue_bytes_limit > 0),
            receiver_config_bytes_limit BIGINT NOT NULL DEFAULT 8388608 CHECK (receiver_config_bytes_limit > 0),
            created_at TEXT NOT NULL DEFAULT {_UTC_NOW_SQL},
            updated_at TEXT NOT NULL DEFAULT {_UTC_NOW_SQL}
        )
        """
    )
    now = _now()
    cursor.execute(
        """INSERT INTO telemetry_collectors (
               id, code, name, collector_type, status, enabled,
               device_limit, series_limit, samples_per_second_limit,
               message_bytes_limit, queue_bytes_limit, receiver_config_bytes_limit,
               created_at, updated_at
           ) VALUES (?, ?, ?, 'LOCAL', 'UNKNOWN', TRUE, 50, 25000, 5000, 4194304, 17179869184, 8388608, ?, ?)
           ON CONFLICT DO NOTHING""",
        ("telemetry-collector-local", "telemetry-local", "Telemetry local receiver", now, now),
    )

    # m0321 originally referenced the generic SNMP/monitoring collector table.
    # Replace those foreign keys with the independent Telemetry registry.
    cursor.execute(
        "ALTER TABLE telemetry_device_configs "
        "DROP CONSTRAINT IF EXISTS telemetry_device_configs_collector_id_fkey"
    )
    cursor.execute(
        "UPDATE telemetry_device_configs SET collector_id = ?",
        ("telemetry-collector-local",),
    )
    cursor.execute(
        "ALTER TABLE telemetry_device_configs "
        "DROP CONSTRAINT IF EXISTS fk_telemetry_device_configs_telemetry_collector"
    )
    cursor.execute(
        """ALTER TABLE telemetry_device_configs
           ADD CONSTRAINT fk_telemetry_device_configs_telemetry_collector
           FOREIGN KEY (collector_id) REFERENCES telemetry_collectors(id) ON DELETE RESTRICT"""
    )
    cursor.execute(
        "ALTER TABLE telemetry_config_jobs "
        "DROP CONSTRAINT IF EXISTS telemetry_config_jobs_collector_id_fkey"
    )
    cursor.execute(
        "UPDATE telemetry_config_jobs SET collector_id = ?",
        ("telemetry-collector-local",),
    )
    cursor.execute(
        "ALTER TABLE telemetry_config_jobs "
        "DROP CONSTRAINT IF EXISTS fk_telemetry_config_jobs_telemetry_collector"
    )
    cursor.execute(
        """ALTER TABLE telemetry_config_jobs
           ADD CONSTRAINT fk_telemetry_config_jobs_telemetry_collector
           FOREIGN KEY (collector_id) REFERENCES telemetry_collectors(id) ON DELETE RESTRICT"""
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Collector identity and configuration history are retained across rollback.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
