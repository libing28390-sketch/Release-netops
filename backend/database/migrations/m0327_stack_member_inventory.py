"""Add persistent stack member inventory table separated from SNMP chassis observations."""

from __future__ import annotations


VERSION = 327
NAME = "stack_member_inventory"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Stack member inventory requires PostgreSQL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS asset_stack_members (
            id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL REFERENCES physical_assets(id) ON DELETE CASCADE,
            member_number INTEGER NOT NULL CHECK (member_number >= 1),
            physical_asset_tag TEXT NOT NULL DEFAULT '',
            serial_number TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            rack_id TEXT REFERENCES racks(id) ON DELETE SET NULL,
            rack_name TEXT NOT NULL DEFAULT '',
            u_start INTEGER,
            u_height INTEGER NOT NULL DEFAULT 1 CHECK (u_height >= 1),
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'replaced', 'retired')),
            entity_index INTEGER,
            last_reconciled_at TIMESTAMPTZ,
            reconciliation_status TEXT NOT NULL DEFAULT 'unverified'
                CHECK (reconciliation_status IN ('unverified', 'matched', 'missing_in_snmp', 'sn_mismatch')),
            replaced_by_id TEXT REFERENCES asset_stack_members(id) ON DELETE SET NULL,
            retired_at TIMESTAMPTZ,
            notes TEXT NOT NULL DEFAULT '',
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_stack_members_active_slot
            ON asset_stack_members (asset_id, member_number)
         WHERE status = 'active'
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_stack_members_active_tag
            ON asset_stack_members (tenant_id, lower(physical_asset_tag))
         WHERE status = 'active' AND btrim(physical_asset_tag) <> ''
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_stack_members_active_sn
            ON asset_stack_members (tenant_id, lower(serial_number))
         WHERE status = 'active' AND btrim(serial_number) <> ''
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_asset_stack_members_asset
            ON asset_stack_members (asset_id, status, member_number)
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    return None
