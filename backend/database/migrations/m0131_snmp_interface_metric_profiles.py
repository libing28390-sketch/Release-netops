"""Add model-scoped interface OID overrides and durable counter baselines."""

from __future__ import annotations


VERSION = 131
NAME = "snmp_interface_metric_profiles"


def _ensure_column(cursor, table: str, column: str, definition: str, use_pg: bool) -> None:
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
    return



def upgrade(cursor, use_pg: bool) -> None:
    # Existing installations already have the profile table from m0123.
    # These additive columns are intentionally nullable only where the legacy
    # test timestamp was nullable; JSON/status columns remain deterministic.
    for column, definition in (
        ('interface_config_json', "TEXT NOT NULL DEFAULT '{}'"),
        ('interface_verification_status', "TEXT NOT NULL DEFAULT 'unverified'"),
        ('interface_last_test_at', 'TEXT'),
        ('interface_last_test_device_id', "TEXT NOT NULL DEFAULT ''"),
        ('interface_last_test_message', "TEXT NOT NULL DEFAULT ''"),
    ):
        _ensure_column(cursor, 'snmp_metric_profiles', column, definition, use_pg)

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS snmp_interface_counter_samples (
            device_id TEXT NOT NULL,
            profile_id TEXT NOT NULL,
            config_hash TEXT NOT NULL DEFAULT '',
            values_json TEXT NOT NULL DEFAULT '{}',
            sampled_at TEXT NOT NULL,
            device_uptime_cs BIGINT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (device_id, profile_id),
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_snmp_interface_counter_samples_ts "
        "ON snmp_interface_counter_samples(sampled_at)"
    )


def downgrade(cursor, use_pg: bool) -> None:
    # The application only relies on additive, forward-compatible changes;
    # dropping columns would be destructive.  Keep downgrade intentionally
    # empty and let a deployment rollback restore the prior schema snapshot.
    return None
