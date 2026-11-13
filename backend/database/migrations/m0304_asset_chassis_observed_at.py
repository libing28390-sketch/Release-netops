"""Ensure chassis serial observations have a persistence watermark."""

from __future__ import annotations


VERSION = 304
NAME = "asset_chassis_observed_at"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Asset chassis observation timestamps require PostgreSQL")

    cursor.execute(
        "ALTER TABLE physical_assets "
        "ADD COLUMN IF NOT EXISTS chassis_observed_at TIMESTAMPTZ"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep the observation watermark when application code is rolled back.
    return None
