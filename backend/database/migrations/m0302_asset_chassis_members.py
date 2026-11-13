"""Store fixed-index chassis serial observations for physical assets."""

from __future__ import annotations


VERSION = 302
NAME = "asset_chassis_members"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Asset chassis members require PostgreSQL")

    cursor.execute(
        "ALTER TABLE physical_assets "
        "ADD COLUMN IF NOT EXISTS serial_number_source TEXT NOT NULL DEFAULT ''"
    )
    cursor.execute(
        "ALTER TABLE physical_assets "
        "ADD COLUMN IF NOT EXISTS chassis_observed_at TIMESTAMPTZ"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS asset_chassis_members (
            asset_id TEXT NOT NULL REFERENCES physical_assets(id) ON DELETE CASCADE,
            entity_index INTEGER NOT NULL CHECK (entity_index BETWEEN 1 AND 3),
            serial_number TEXT NOT NULL DEFAULT '',
            entity_name TEXT NOT NULL DEFAULT '',
            entity_description TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            collected_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (asset_id, entity_index)
        )
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep collected identity evidence if application code is rolled back.
    return None
