"""Enforce non-empty asset identity fields as case-insensitive unique values."""

VERSION = 14
NAME = "asset_identity_uniqueness"


def upgrade(cursor, use_pg: bool) -> None:
    # Empty values remain allowed for legacy/incomplete inventory rows, but a
    # populated hostname, asset tag, serial number, or management IP may only
    # belong to one physical asset.
    for field in ("hostname", "asset_tag", "serial_number", "management_ip"):
        cursor.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS uq_physical_assets_{field}_ci "
            f"ON physical_assets (LOWER(TRIM({field}))) "
            f"WHERE TRIM(COALESCE({field}, '')) <> ''"
        )
