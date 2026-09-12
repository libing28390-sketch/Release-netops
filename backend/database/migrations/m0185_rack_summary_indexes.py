"""Add bounded-list indexes used by the paged rack summary read model."""

VERSION = 185
NAME = "rack_summary_indexes"


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_racks_summary_scope "
        "ON racks(site_id, floor, room, row, status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_rack_devices_rack_asset "
        "ON rack_devices(rack_id, asset_id)"
    )


def downgrade(cursor, use_pg: bool) -> None:
    del use_pg
    cursor.execute("DROP INDEX IF EXISTS idx_rack_devices_rack_asset")
    cursor.execute("DROP INDEX IF EXISTS idx_racks_summary_scope")
