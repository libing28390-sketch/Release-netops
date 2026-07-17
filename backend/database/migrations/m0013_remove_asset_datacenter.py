"""Remove the retired free-text physical asset datacenter column."""

VERSION = 13
NAME = "remove_asset_datacenter"


def upgrade(cursor, use_pg: bool) -> None:
    if use_pg:
        cursor.execute("ALTER TABLE physical_assets DROP COLUMN IF EXISTS datacenter")
        return

    columns = {row[1] for row in cursor.execute("PRAGMA table_info(physical_assets)").fetchall()}
    if "datacenter" in columns:
        cursor.execute("ALTER TABLE physical_assets DROP COLUMN datacenter")
