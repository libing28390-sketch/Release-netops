"""Track the freshness and provenance of automatically discovered VLANs."""

from __future__ import annotations


VERSION = 44
NAME = "vlan_discovery_metadata"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    schema_clause = "table_schema = current_schema() AND " if use_pg else ""
    cursor.execute(
        f"SELECT column_name FROM information_schema.columns WHERE {schema_clause}table_name = %s",
        (table,),
    )
    return {row[0] for row in cursor.fetchall()}



def upgrade(cursor, use_pg: bool) -> None:
    existing = _columns(cursor, "vlans", use_pg)
    for name, definition in [
        ("discovery_source", "TEXT DEFAULT 'manual'"),
        ("first_discovered_at", "TEXT"),
        ("last_discovered_at", "TEXT"),
        ("discovery_run_id", "TEXT DEFAULT ''"),
    ]:
        if name not in existing:
            cursor.execute(f"ALTER TABLE vlans ADD COLUMN {name} {definition}")

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_vlans_discovery_freshness "
        "ON vlans(last_discovered_at, discovery_source)"
    )
