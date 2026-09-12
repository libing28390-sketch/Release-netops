"""Add the canonical province/state field to CMDB sites."""

VERSION = 17
NAME = "site_state_province"


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute("ALTER TABLE sites ADD COLUMN IF NOT EXISTS state_province TEXT DEFAULT ''")
    return
