"""Add lifecycle timestamps to CMDB sites."""

VERSION = 19
NAME = "site_timestamps"


def upgrade(cursor, use_pg: bool) -> None:
    definitions = {
        "created_at": "TEXT DEFAULT ''",
        "updated_at": "TEXT DEFAULT ''",
    }
    for column, definition in definitions.items():
        cursor.execute(f"ALTER TABLE sites ADD COLUMN IF NOT EXISTS {column} {definition}")

    # Existing installations did not retain site creation time. Populate a
    # stable migration timestamp so the UI never renders an empty column.
    cursor.execute(
        "UPDATE sites SET created_at = COALESCE(NULLIF(created_at, ''), CURRENT_TIMESTAMP::text)"
    )
    cursor.execute(
        "UPDATE sites SET updated_at = COALESCE(NULLIF(updated_at, ''), created_at, CURRENT_TIMESTAMP::text)"
    )
