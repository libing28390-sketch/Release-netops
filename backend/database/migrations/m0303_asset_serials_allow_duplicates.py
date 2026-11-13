"""Allow HCL and real devices to reuse the same reported serial number."""

from __future__ import annotations


VERSION = 303
NAME = "asset_serials_allow_duplicates"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Asset serial identity migration requires PostgreSQL")
    cursor.execute("DROP INDEX IF EXISTS uq_physical_assets_serial_number_ci")


def downgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Asset serial identity migration requires PostgreSQL")
    cursor.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_physical_assets_serial_number_ci
             ON physical_assets (LOWER(TRIM(serial_number)))
          WHERE TRIM(COALESCE(serial_number, '')) <> ''"""
    )
