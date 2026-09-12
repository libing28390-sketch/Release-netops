"""Add optional per-device CPU and memory metric OID overrides."""

from __future__ import annotations


VERSION = 122
NAME = "device_custom_metric_oids"


_COLUMNS = {
    "snmp_cpu_oid": "TEXT NOT NULL DEFAULT ''",
    "snmp_memory_oid": "TEXT NOT NULL DEFAULT ''",
}


def _table_columns(cursor, table: str, use_pg: bool) -> set[str]:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (table,),
    )
    return {str(row[0]) for row in cursor.fetchall()}



def upgrade(cursor, use_pg: bool) -> None:
    existing = _table_columns(cursor, "devices", use_pg)
    for name, definition in _COLUMNS.items():
        if name in existing:
            continue
        cursor.execute(
            f"ALTER TABLE devices ADD COLUMN IF NOT EXISTS {name} {definition}"
        )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep the columns on downgrade so an older binary can safely continue to
    # read device rows without losing an operator's metric configuration.
    return None
