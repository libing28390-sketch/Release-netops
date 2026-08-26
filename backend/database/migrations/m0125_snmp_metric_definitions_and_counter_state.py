"""Add typed SNMP metric definitions and durable counter baselines.

The original model profile stored only an OID.  That is insufficient because
an SNMP value also has a semantic type (Gauge32, Counter32, Counter64, ...)
and a model-specific formula.  This migration is additive: the legacy OID
columns remain as a compatibility projection while the JSON definitions carry
the reviewed collection contract.
"""

from __future__ import annotations


VERSION = 125
NAME = "snmp_metric_definitions_and_counter_state"


def _columns(cursor, use_pg: bool) -> set[str]:
    if use_pg:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'snmp_metric_profiles'"
        )
        return {str(row[0]) for row in cursor.fetchall()}
    cursor.execute("PRAGMA table_info(snmp_metric_profiles)")
    return {str(row[1]) for row in cursor.fetchall()}


def upgrade(cursor, use_pg: bool) -> None:
    existing = _columns(cursor, use_pg)
    for name, definition in {
        "cpu_config_json": "TEXT NOT NULL DEFAULT '{}'",
        "memory_config_json": "TEXT NOT NULL DEFAULT '{}'",
    }.items():
        if name in existing:
            continue
        if use_pg:
            cursor.execute(
                f"ALTER TABLE snmp_metric_profiles ADD COLUMN IF NOT EXISTS {name} {definition}"
            )
        else:
            cursor.execute(f"ALTER TABLE snmp_metric_profiles ADD COLUMN {name} {definition}")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS snmp_metric_counter_samples (
            device_id TEXT NOT NULL,
            profile_id TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            oid TEXT NOT NULL,
            config_hash TEXT NOT NULL DEFAULT '',
            counter_bits INTEGER NOT NULL,
            values_json TEXT NOT NULL DEFAULT '{}',
            sampled_at TEXT NOT NULL,
            device_uptime_cs BIGINT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (device_id, profile_id, metric_name),
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_snmp_counter_samples_ts "
        "ON snmp_metric_counter_samples(sampled_at)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Counter baselines and definitions are operational evidence.  Keep them
    # on rollback so an older binary cannot silently destroy monitoring state.
    return None
