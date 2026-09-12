"""Remove the retired free-text physical asset datacenter column."""

VERSION = 13
NAME = "remove_asset_datacenter"


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute("ALTER TABLE physical_assets DROP COLUMN IF EXISTS datacenter")
    return
