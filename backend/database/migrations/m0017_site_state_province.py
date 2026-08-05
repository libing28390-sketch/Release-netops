"""Add the canonical province/state field to CMDB sites."""

VERSION = 17
NAME = "site_state_province"


def upgrade(cursor, use_pg: bool) -> None:
    if use_pg:
        cursor.execute("ALTER TABLE sites ADD COLUMN IF NOT EXISTS state_province TEXT DEFAULT ''")
        return

    columns = {row[1] for row in cursor.execute("PRAGMA table_info(sites)").fetchall()}
    if "state_province" not in columns:
        cursor.execute("ALTER TABLE sites ADD COLUMN state_province TEXT DEFAULT ''")
