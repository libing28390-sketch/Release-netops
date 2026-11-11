"""Add explicit address-space links for VIPs and DHCP lease observations."""

from __future__ import annotations


VERSION = 310
NAME = "ipam_vip_lease_scopes"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("IPAM VIP and lease scope relationships require PostgreSQL")

    cursor.execute("ALTER TABLE ipam_vips ADD COLUMN IF NOT EXISTS address_inet INET")
    cursor.execute("ALTER TABLE ipam_vips ADD COLUMN IF NOT EXISTS prefix_id TEXT")
    cursor.execute("ALTER TABLE ipam_vips ADD COLUMN IF NOT EXISTS address_space_id TEXT")
    cursor.execute("ALTER TABLE ipam_dhcp_leases ADD COLUMN IF NOT EXISTS address_space_id TEXT")
    cursor.execute("ALTER TABLE ipam_dhcp_leases ADD COLUMN IF NOT EXISTS pool_id TEXT")
    cursor.execute("ALTER TABLE ipam_dhcp_leases ADD COLUMN IF NOT EXISTS external_id TEXT")
    cursor.execute(
        "ALTER TABLE ipam_dhcp_leases ADD COLUMN IF NOT EXISTS "
        "scope_status TEXT NOT NULL DEFAULT 'scope_unknown'"
    )

    # Existing rows are deliberately left unmapped. Their address alone does
    # not establish a routing domain, tenant, Prefix, or external DHCP Pool.
    cursor.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_ipam_vips_prefix'
            ) THEN
                ALTER TABLE ipam_vips
                    ADD CONSTRAINT fk_ipam_vips_prefix
                    FOREIGN KEY (prefix_id) REFERENCES prefixes(id) ON DELETE RESTRICT;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_ipam_vips_address_space'
            ) THEN
                ALTER TABLE ipam_vips
                    ADD CONSTRAINT fk_ipam_vips_address_space
                    FOREIGN KEY (address_space_id)
                    REFERENCES ipam_address_spaces(id) ON DELETE RESTRICT;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_ipam_vips_scope_pair'
            ) THEN
                ALTER TABLE ipam_vips
                    ADD CONSTRAINT ck_ipam_vips_scope_pair CHECK (
                        (prefix_id IS NULL AND address_space_id IS NULL AND address_inet IS NULL)
                        OR (prefix_id IS NOT NULL AND address_space_id IS NOT NULL AND address_inet IS NOT NULL)
                    );
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_ipam_lease_address_space'
            ) THEN
                ALTER TABLE ipam_dhcp_leases
                    ADD CONSTRAINT fk_ipam_lease_address_space
                    FOREIGN KEY (address_space_id)
                    REFERENCES ipam_address_spaces(id) ON DELETE RESTRICT;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_ipam_lease_pool'
            ) THEN
                ALTER TABLE ipam_dhcp_leases
                    ADD CONSTRAINT fk_ipam_lease_pool
                    FOREIGN KEY (pool_id) REFERENCES ipam_pools(id) ON DELETE RESTRICT;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_ipam_lease_scope_status'
            ) THEN
                ALTER TABLE ipam_dhcp_leases
                    ADD CONSTRAINT ck_ipam_lease_scope_status CHECK (
                        scope_status IN ('scope_unknown', 'scope_resolved')
                    );
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_ipam_lease_scope_link'
            ) THEN
                ALTER TABLE ipam_dhcp_leases
                    ADD CONSTRAINT ck_ipam_lease_scope_link CHECK (
                        (pool_id IS NULL AND address_space_id IS NULL AND scope_status = 'scope_unknown')
                        OR (pool_id IS NOT NULL AND address_space_id IS NOT NULL AND scope_status = 'scope_resolved')
                    );
            END IF;
        END $$
        """
    )

    cursor.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_ipam_vips_space_host_active
             ON ipam_vips(address_space_id, address_inet)
             WHERE address_space_id IS NOT NULL
               AND address_inet IS NOT NULL
               AND COALESCE(status, 'active') NOT IN ('released', 'deprecated', 'disabled')"""
    )
    cursor.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_ipam_dhcp_external_identity
             ON ipam_dhcp_leases(
                 COALESCE(tenant_id, 'tenant-default'),
                 lower(btrim(COALESCE(dhcp_server, ''))),
                 btrim(external_id)
             )
             WHERE external_id IS NOT NULL AND btrim(external_id) <> ''"""
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ipam_vips_space_status "
        "ON ipam_vips(address_space_id, status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ipam_leases_scope_pool_state "
        "ON ipam_dhcp_leases(address_space_id, pool_id, lease_state)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Scope fields preserve user decisions and must not be removed on rollback.
    return None
