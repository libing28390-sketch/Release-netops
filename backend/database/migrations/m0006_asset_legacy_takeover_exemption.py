VERSION = 6
NAME = "asset_legacy_takeover_exemption"


def _column_exists(cursor, table_name: str, column_name: str, use_pg: bool) -> bool:
    if use_pg:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
            (table_name, column_name),
        )
        return cursor.fetchone() is not None
    cursor.execute(f"PRAGMA table_info({table_name})")
    return any(row[1] == column_name for row in cursor.fetchall())


def upgrade(cursor, use_pg: bool) -> None:
    columns = [
        ("credential_governance_mode", "TEXT DEFAULT 'managed'"),
        ("takeover_exempt_reason", "TEXT DEFAULT ''"),
        ("takeover_exempt_at", "TEXT DEFAULT ''"),
    ]
    for column_name, definition in columns:
        if not _column_exists(cursor, "physical_assets", column_name, use_pg):
            cursor.execute(f"ALTER TABLE physical_assets ADD COLUMN {column_name} {definition}")
