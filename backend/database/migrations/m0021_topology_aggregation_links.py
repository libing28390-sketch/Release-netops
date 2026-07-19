"""Add first-class fields for logical aggregation links in topology."""

VERSION = 21
NAME = "topology_aggregation_links"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]) for row in rows}
    return {str(row[1]) for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}


def upgrade(cursor, use_pg: bool) -> None:
    columns = _columns(cursor, "topology_links", use_pg)
    additions = {
        "link_kind": "TEXT NOT NULL DEFAULT 'physical'",
        "source_aggregation_name": "TEXT NOT NULL DEFAULT ''",
        "target_aggregation_name": "TEXT NOT NULL DEFAULT ''",
        "aggregation_protocol": "TEXT NOT NULL DEFAULT ''",
        "member_count": "INTEGER NOT NULL DEFAULT 0",
        "active_member_count": "INTEGER NOT NULL DEFAULT 0",
        "aggregation_bandwidth_mbps": "REAL NOT NULL DEFAULT 0",
        "members_json": "TEXT NOT NULL DEFAULT '[]'",
    }
    for name, definition in additions.items():
        if name not in columns:
            cursor.execute(f"ALTER TABLE topology_links ADD COLUMN {name} {definition}")

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_topology_links_kind ON topology_links(link_kind)"
    )

    interface_columns = _columns(cursor, "interfaces", use_pg)
    if 'aggregation_protocol' not in interface_columns:
        cursor.execute("ALTER TABLE interfaces ADD COLUMN aggregation_protocol TEXT NOT NULL DEFAULT ''")
