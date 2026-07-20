"""Add lifecycle timestamps to CMDB sites."""

VERSION = 19
NAME = "site_timestamps"


def upgrade(cursor, use_pg: bool) -> None:
    definitions = {
        "created_at": "TEXT DEFAULT ''",
        "updated_at": "TEXT DEFAULT ''",
    }
    if use_pg:
        for column, definition in definitions.items():
            cursor.execute(f"ALTER TABLE sites ADD COLUMN IF NOT EXISTS {column} {definition}")
    else:
        columns = {row[1] for row in cursor.execute("PRAGMA table_info(sites)").fetchall()}
        for column, definition in definitions.items():
            if column not in columns:
                cursor.execute(f"ALTER TABLE sites ADD COLUMN {column} {definition}")

    # Existing installations did not retain site creation time. Populate a
    # stable migration timestamp so the UI never renders an empty column.
    if use_pg:
        # The baseline stores these lifecycle values as TEXT on PostgreSQL too.
        # Keep the migration compatible with that legacy contract.
        cursor.execute(
            "UPDATE sites SET created_at = COALESCE(NULLIF(created_at, ''), CURRENT_TIMESTAMP::text)"
        )
        cursor.execute(
            "UPDATE sites SET updated_at = COALESCE(NULLIF(updated_at, ''), created_at, CURRENT_TIMESTAMP::text)"
        )
    else:
        cursor.execute("UPDATE sites SET created_at = COALESCE(NULLIF(created_at, ''), CURRENT_TIMESTAMP)")
        cursor.execute("UPDATE sites SET updated_at = COALESCE(NULLIF(updated_at, ''), created_at, CURRENT_TIMESTAMP)")
