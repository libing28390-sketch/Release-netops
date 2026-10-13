"""Add LLDP-only topology snapshot fields and normalize run scope metadata."""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 31
NAME = "lldp_collection_contract"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table,),
    )
    return {row[0] for row in cursor.fetchall()}



def _ensure_columns(cursor, table: str, definitions: list[tuple[str, str]], use_pg: bool) -> None:
    existing = _columns(cursor, table, use_pg)
    for name, definition in definitions:
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    _ensure_columns(
        cursor,
        "topology_observations",
        [
            ("first_seen_at", "TEXT"),
            ("last_seen_at", "TEXT"),
            ("miss_count", "INTEGER DEFAULT 0"),
            ("is_active", "INTEGER DEFAULT 1"),
        ],
        use_pg,
    )
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor.execute(
        """
        UPDATE topology_observations
        SET first_seen_at = COALESCE(first_seen_at, collected_at, ?),
            last_seen_at = COALESCE(last_seen_at, collected_at, ?),
            miss_count = COALESCE(miss_count, 0),
            is_active = CASE
                WHEN is_active IS NULL THEN CASE WHEN COALESCE(status, 'active') = 'active' THEN 1 ELSE 0 END
                ELSE is_active
            END
        """,
        (now, now),
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_topology_observations_active ON topology_observations(source_device_id, is_active, last_seen_at)")
    cursor.execute("UPDATE topology_discovery_runs SET protocol_scope = 'lldp' WHERE protocol_scope = 'lldp_cdp'")
