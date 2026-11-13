"""Backfill legacy WAN endpoints and retain immutable endpoint versions."""

from __future__ import annotations


VERSION = 265
NAME = "wan_endpoint_history"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("WAN endpoint history requires PostgreSQL")

    cursor.execute(
        "ALTER TABLE wan_link_endpoints ADD COLUMN IF NOT EXISTS binding_version INTEGER NOT NULL DEFAULT 1"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS wan_link_endpoint_history (
            id TEXT PRIMARY KEY,
            link_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            side TEXT NOT NULL CHECK (side IN ('A', 'Z')),
            endpoint_version INTEGER NOT NULL,
            endpoint_type TEXT NOT NULL CHECK (endpoint_type IN ('managed', 'unmanaged')),
            site_id TEXT NOT NULL DEFAULT '',
            device_id TEXT,
            interface_id TEXT,
            if_index INTEGER,
            site_name TEXT NOT NULL DEFAULT '',
            endpoint_name TEXT NOT NULL DEFAULT '',
            counter_orientation TEXT NOT NULL DEFAULT 'normal',
            measurement_scope TEXT NOT NULL DEFAULT 'shared_interface',
            valid_from TIMESTAMPTZ NOT NULL,
            valid_to TIMESTAMPTZ,
            changed_by TEXT NOT NULL DEFAULT '',
            snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT uq_wan_endpoint_history_version UNIQUE (link_id, side, endpoint_version),
            CONSTRAINT ck_wan_endpoint_history_validity CHECK (valid_to IS NULL OR valid_to >= valid_from)
        )
        """
    )

    # Legacy links retain their wan_links identity.  A-side is backfilled only
    # when its current CMDB interface has a valid owner and ifIndex; ambiguous
    # mappings stay incomplete for an operator to repair.  The Z-side is
    # explicitly unmanaged and does not inherit the A-site as a false fact.
    cursor.execute(
        """
        INSERT INTO wan_link_endpoints (
            id, link_id, side, endpoint_type, tenant_id, site_id, device_id,
            interface_id, if_index, site_name, endpoint_name,
            counter_orientation, measurement_scope, created_at, updated_at,
            binding_version
        )
        SELECT 'wan-endpoint-legacy-a-' || l.id, l.id, 'A', 'managed', l.tenant_id,
               COALESCE(NULLIF(d.site_id, ''), NULLIF(l.site_id, ''), ''),
               d.id, i.id, i.if_index,
               COALESCE(NULLIF(l.site_name, ''), ''),
               COALESCE(NULLIF(i.interface_name, ''), NULLIF(l.interface_name, ''), ''),
               CASE WHEN l.direction_mode = 'reversed' THEN 'reversed' ELSE 'normal' END,
               'shared_interface', COALESCE(NULLIF(l.created_at::text, '')::timestamptz, clock_timestamp()),
               clock_timestamp(), 1
          FROM wan_links l
          JOIN devices d ON d.id = l.device_id
          JOIN interfaces i ON i.id = l.interface_id AND i.device_id = d.id
         WHERE i.if_index IS NOT NULL
           AND COALESCE(NULLIF(d.tenant_id, ''), 'tenant-default') = COALESCE(NULLIF(l.tenant_id, ''), 'tenant-default')
           AND (NULLIF(l.site_id, '') IS NULL OR NULLIF(d.site_id, '') IS NULL OR l.site_id = d.site_id)
           AND NOT EXISTS (
               SELECT 1 FROM wan_link_endpoints e WHERE e.link_id = l.id AND e.side = 'A'
           )
        ON CONFLICT (link_id, side) DO NOTHING
        """
    )
    cursor.execute(
        """
        INSERT INTO wan_link_endpoints (
            id, link_id, side, endpoint_type, tenant_id, site_id, device_id,
            interface_id, if_index, site_name, endpoint_name,
            counter_orientation, measurement_scope, created_at, updated_at,
            binding_version
        )
        SELECT 'wan-endpoint-legacy-z-' || l.id, l.id, 'Z', 'unmanaged', l.tenant_id,
               '', NULL, NULL, NULL, '', '', 'normal', 'dedicated',
               COALESCE(NULLIF(l.created_at::text, '')::timestamptz, clock_timestamp()),
               clock_timestamp(), 1
          FROM wan_links l
         WHERE NOT EXISTS (
               SELECT 1 FROM wan_link_endpoints e WHERE e.link_id = l.id AND e.side = 'Z'
         )
        ON CONFLICT (link_id, side) DO NOTHING
        """
    )

    cursor.execute(
        """
        INSERT INTO wan_link_endpoint_history (
            id, link_id, tenant_id, side, endpoint_version, endpoint_type,
            site_id, device_id, interface_id, if_index, site_name, endpoint_name,
            counter_orientation, measurement_scope, valid_from, valid_to,
            changed_by, snapshot
        )
        SELECT 'wan-endpoint-history-' || md5(e.id || ':1'), e.link_id, e.tenant_id,
               e.side, e.binding_version, e.endpoint_type, e.site_id, e.device_id,
               e.interface_id, e.if_index, e.site_name, e.endpoint_name,
               e.counter_orientation, e.measurement_scope, e.created_at, NULL, '',
               to_jsonb(e)
          FROM wan_link_endpoints e
        ON CONFLICT (link_id, side, endpoint_version) DO NOTHING
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_wan_endpoint_history_tenant_link_time "
        "ON wan_link_endpoint_history (tenant_id, link_id, valid_from DESC)"
    )
    # The old WAN model did not record whether the selected physical port was
    # exclusive to one provider circuit. Treat migrated counters as aggregate
    # evidence until an operator explicitly confirms a dedicated A endpoint.
    cursor.execute(
        """
        UPDATE wan_link_current_status c
           SET download_util_pct = NULL,
               upload_util_pct = NULL,
               health_status = CASE WHEN c.oper_status = 'down' THEN 'unavailable' ELSE 'unknown' END,
               active_alert_count = (
                   SELECT COUNT(*) FROM wan_alert_events e
                    WHERE e.link_id = c.link_id AND e.status IN ('firing', 'acknowledged')
               ),
               updated_at = clock_timestamp()
          FROM wan_link_endpoints a
         WHERE a.link_id = c.link_id AND a.side = 'A'
           AND a.measurement_scope = 'shared_interface'
           AND (
               c.download_util_pct IS NOT NULL
               OR c.upload_util_pct IS NOT NULL
               OR c.health_status IS DISTINCT FROM CASE WHEN c.oper_status = 'down' THEN 'unavailable' ELSE 'unknown' END
               OR c.active_alert_count IS DISTINCT FROM (
                   SELECT COUNT(*) FROM wan_alert_events e
                    WHERE e.link_id = c.link_id AND e.status IN ('firing', 'acknowledged')
               )
           )
        """
    )
    cursor.execute(
        """
        UPDATE wan_alert_events e
           SET status = 'resolved',
               recovered_at = COALESCE(e.recovered_at, clock_timestamp()),
               last_seen_at = clock_timestamp(),
               details = COALESCE(e.details, '{}'::jsonb) || '{"resolution_reason":"measurement_scope_shared_interface"}'::jsonb,
               updated_at = clock_timestamp()
          FROM wan_link_endpoints a
         WHERE a.link_id = e.link_id AND a.side = 'A'
           AND a.measurement_scope = 'shared_interface'
           AND e.metric LIKE 'util_%'
           AND e.status IN ('firing', 'acknowledged')
        """
    )
    cursor.execute(
        """
        UPDATE wan_link_current_status c
           SET active_alert_count = (
               SELECT COUNT(*) FROM wan_alert_events e
                WHERE e.link_id = c.link_id AND e.status IN ('firing', 'acknowledged')
           ),
               updated_at = clock_timestamp()
          FROM wan_link_endpoints a
         WHERE a.link_id = c.link_id AND a.side = 'A'
           AND a.measurement_scope = 'shared_interface'
           AND c.active_alert_count IS DISTINCT FROM (
               SELECT COUNT(*) FROM wan_alert_events e
                WHERE e.link_id = c.link_id AND e.status IN ('firing', 'acknowledged')
           )
        """
    )


def downgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("WAN endpoint history requires PostgreSQL")
    # Keep endpoint audit history when rolling back application code.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
