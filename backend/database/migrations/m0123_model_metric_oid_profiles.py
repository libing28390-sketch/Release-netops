"""Add vendor/model-scoped SNMP CPU and memory OID profiles."""

from __future__ import annotations


VERSION = 123
NAME = "model_metric_oid_profiles"


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS snmp_metric_profiles (
            id TEXT PRIMARY KEY,
            vendor_key TEXT NOT NULL,
            vendor_name TEXT NOT NULL DEFAULT '',
            model_key TEXT NOT NULL,
            model_name TEXT NOT NULL DEFAULT '',
            cpu_oid TEXT NOT NULL DEFAULT '',
            memory_oid TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL DEFAULT '',
            UNIQUE (vendor_key, model_key)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_snmp_metric_profiles_model "
        "ON snmp_metric_profiles(vendor_key, model_key)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep operator-defined OID mappings during downgrade so a rollback cannot
    # silently remove the telemetry configuration.
    return None
