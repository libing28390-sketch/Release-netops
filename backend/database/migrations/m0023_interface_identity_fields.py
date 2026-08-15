"""Align the persisted interface schema with the canonical Interface model."""

VERSION = 23
NAME = "interface_identity_fields"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]) for row in rows}
    return {str(row[1]) for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}


def upgrade(cursor, use_pg: bool) -> None:
    """Add missing interface identity/display fields without touching data."""
    additions = {
        "name_raw": "TEXT DEFAULT ''",
        "name_display": "TEXT DEFAULT ''",
        "primary_ip": "TEXT DEFAULT ''",
        "ip_address": "TEXT DEFAULT ''",
        "ip_prefix_length": "INTEGER",
        "ip_version": "INTEGER",
        "is_l3": "INTEGER DEFAULT 0",
        "last_change": "TEXT",
        "last_seen": "TEXT",
        "lag_id": "TEXT DEFAULT ''",
        "vlan_mode": "TEXT DEFAULT 'access'",
    }
    columns = _columns(cursor, "interfaces", use_pg)
    for name, definition in additions.items():
        if name not in columns:
            cursor.execute(f"ALTER TABLE interfaces ADD COLUMN {name} {definition}")

    # Existing rows created by the legacy collector have interface_name only.
    # Backfill identity/display fields so topology and graph queries can use
    # one stable representation immediately after the migration.
    cursor.execute(
        "UPDATE interfaces SET name_raw = interface_name "
        "WHERE COALESCE(name_raw, '') = ''"
    )
    cursor.execute(
        "UPDATE interfaces SET name_display = interface_name "
        "WHERE COALESCE(name_display, '') = ''"
    )
