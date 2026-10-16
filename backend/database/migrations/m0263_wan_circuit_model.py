"""Add tenant-scoped WAN circuit endpoints and contract history.

The existing ``wan_links`` row remains the root business object.  This
migration only adds circuit metadata around it so existing collectors,
samples, alert rules, and group memberships keep their link id unchanged.
"""

from __future__ import annotations


VERSION = 263
NAME = "wan_circuit_model"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("WAN circuit model requires PostgreSQL")

    cursor.execute(
        "ALTER TABLE wan_links ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'tenant-default'"
    )
    cursor.execute(
        "ALTER TABLE wan_links ADD COLUMN IF NOT EXISTS configuration_version INTEGER NOT NULL DEFAULT 1"
    )

    # The device is the trusted ownership source for legacy single-ended
    # links.  A site is also checked below when both identities are present.
    cursor.execute(
        """
        UPDATE wan_links l
           SET tenant_id = COALESCE(
               NULLIF(d.tenant_id, ''),
               NULLIF((SELECT s.tenant_id FROM sites s WHERE s.id = NULLIF(l.site_id, '')), ''),
               'tenant-default'
           )
          FROM devices d
         WHERE d.id = l.device_id
        """
    )
    cursor.execute(
        """
        SELECT l.id
          FROM wan_links l
          JOIN devices d ON d.id = l.device_id
          LEFT JOIN sites s ON s.id = NULLIF(l.site_id, '')
         WHERE COALESCE(NULLIF(d.tenant_id, ''), 'tenant-default')
               <> COALESCE(NULLIF(s.tenant_id, ''), COALESCE(NULLIF(d.tenant_id, ''), 'tenant-default'))
         LIMIT 1
        """
    )
    mismatch = cursor.fetchone()
    if mismatch is not None:
        raise RuntimeError(f"WAN link tenant mismatch for legacy link {mismatch[0]}")

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_wan_links_tenant_site ON wan_links(tenant_id, site_id, updated_at DESC)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS wan_link_endpoints (
            id TEXT PRIMARY KEY,
            link_id TEXT NOT NULL,
            side TEXT NOT NULL,
            endpoint_type TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            site_id TEXT NOT NULL DEFAULT '',
            device_id TEXT,
            interface_id TEXT,
            if_index INTEGER,
            site_name TEXT NOT NULL DEFAULT '',
            endpoint_name TEXT NOT NULL DEFAULT '',
            counter_orientation TEXT NOT NULL DEFAULT 'normal',
            measurement_scope TEXT NOT NULL DEFAULT 'shared_interface',
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_wan_link_endpoint_side UNIQUE (link_id, side),
            CONSTRAINT ck_wan_link_endpoint_side CHECK (side IN ('A', 'Z')),
            CONSTRAINT ck_wan_link_endpoint_type CHECK (endpoint_type IN ('managed', 'unmanaged')),
            CONSTRAINT ck_wan_link_endpoint_orientation CHECK (counter_orientation IN ('normal', 'reversed')),
            CONSTRAINT ck_wan_link_endpoint_scope CHECK (measurement_scope IN ('dedicated', 'shared_interface')),
            CONSTRAINT ck_wan_link_endpoint_managed_identity CHECK (
                endpoint_type = 'unmanaged'
                OR (device_id IS NOT NULL AND interface_id IS NOT NULL AND if_index IS NOT NULL)
            )
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_wan_link_endpoints_tenant_site ON wan_link_endpoints(tenant_id, site_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_wan_link_endpoints_link ON wan_link_endpoints(link_id, side)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS wan_link_contract_history (
            id TEXT PRIMARY KEY,
            link_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            configuration_version INTEGER NOT NULL,
            contracted_download_bps BIGINT NOT NULL,
            contracted_upload_bps BIGINT NOT NULL,
            provider TEXT NOT NULL DEFAULT '',
            circuit_number TEXT NOT NULL DEFAULT '',
            effective_at TIMESTAMPTZ NOT NULL,
            changed_by TEXT NOT NULL DEFAULT '',
            snapshot JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_wan_link_contract_history_link ON wan_link_contract_history(link_id, configuration_version DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_wan_link_contract_history_tenant ON wan_link_contract_history(tenant_id, effective_at DESC)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS wan_link_sla_policies (
            link_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            policy_version INTEGER NOT NULL DEFAULT 1,
            policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_by TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS wan_link_sla_policy_history (
            id TEXT PRIMARY KEY,
            link_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            policy_version INTEGER NOT NULL,
            policy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            changed_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_wan_link_sla_policy_history_link ON wan_link_sla_policy_history(link_id, policy_version DESC)"
    )


def downgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("WAN circuit model requires PostgreSQL")
    # Preserve operational and contract history data during rollback.  The
    # forward migration is additive and can safely be reapplied.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
