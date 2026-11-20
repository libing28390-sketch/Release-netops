"""Add NetBox-aligned IPAM native objects: VLAN Groups, Route Targets, RIRs, Aggregates, and ASNs."""

from __future__ import annotations


VERSION = 329
NAME = "ipam_native_models"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("IPAM native models require PostgreSQL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_vlan_groups (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL DEFAULT '',
            scope_type TEXT NOT NULL DEFAULT ''
                CHECK (scope_type IN ('', 'site')),
            scope_id TEXT NOT NULL DEFAULT '',
            min_vid INTEGER NOT NULL DEFAULT 1 CHECK (min_vid BETWEEN 1 AND 4094),
            max_vid INTEGER NOT NULL DEFAULT 4094 CHECK (max_vid BETWEEN 1 AND 4094 AND max_vid >= min_vid),
            description TEXT NOT NULL DEFAULT '',
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ipam_vlan_groups_tenant_name
            ON ipam_vlan_groups (tenant_id, lower(name))
        """
    )
    cursor.execute(
        """
        ALTER TABLE vlans
            ADD COLUMN IF NOT EXISTS vlan_group_id TEXT REFERENCES ipam_vlan_groups(id) ON DELETE SET NULL
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_vlans_group_vid
            ON vlans (vlan_group_id, vlan_id)
         WHERE vlan_group_id IS NOT NULL
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_route_targets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ipam_route_targets_tenant_name
            ON ipam_route_targets (tenant_id, lower(name))
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_vrf_route_targets (
            vrf_id TEXT NOT NULL REFERENCES vrfs(id) ON DELETE CASCADE,
            route_target_id TEXT NOT NULL REFERENCES ipam_route_targets(id) ON DELETE CASCADE,
            direction TEXT NOT NULL CHECK (direction IN ('import', 'export')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (vrf_id, route_target_id, direction)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_rirs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL DEFAULT '',
            is_private BOOLEAN NOT NULL DEFAULT FALSE,
            description TEXT NOT NULL DEFAULT '',
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ipam_rirs_tenant_name
            ON ipam_rirs (tenant_id, lower(name))
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_aggregates (
            id TEXT PRIMARY KEY,
            prefix TEXT NOT NULL,
            prefix_cidr CIDR NOT NULL,
            ip_version SMALLINT NOT NULL CHECK (ip_version IN (4, 6)),
            rir_id TEXT NOT NULL REFERENCES ipam_rirs(id) ON DELETE RESTRICT,
            date_added TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ipam_aggregates_tenant_cidr
            ON ipam_aggregates (tenant_id, prefix_cidr)
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_asns (
            id TEXT PRIMARY KEY,
            asn BIGINT NOT NULL CHECK (asn BETWEEN 1 AND 4294967295),
            rir_id TEXT NOT NULL REFERENCES ipam_rirs(id) ON DELETE RESTRICT,
            site_id TEXT REFERENCES sites(id) ON DELETE SET NULL,
            description TEXT NOT NULL DEFAULT '',
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ipam_asns_tenant_asn
            ON ipam_asns (tenant_id, asn)
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    return None
