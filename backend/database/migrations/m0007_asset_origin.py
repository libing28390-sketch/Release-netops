VERSION = 7
NAME = "asset_origin"


def _column_exists(cursor, use_pg: bool) -> bool:
    if use_pg:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
            ("physical_assets", "asset_origin"),
        )
        return cursor.fetchone() is not None
    cursor.execute("PRAGMA table_info(physical_assets)")
    return any(row[1] == "asset_origin" for row in cursor.fetchall())


def upgrade(cursor, use_pg: bool) -> None:
    if not _column_exists(cursor, use_pg):
        cursor.execute("ALTER TABLE physical_assets ADD COLUMN asset_origin TEXT DEFAULT 'new'")
        cursor.execute("UPDATE physical_assets SET asset_origin = 'legacy'")
