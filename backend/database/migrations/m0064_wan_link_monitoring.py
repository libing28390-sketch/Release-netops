"""Add the P0 internet egress link monitoring model.

The project uses text identifiers for inventory objects, so the WAN model keeps
those identifiers while using PostgreSQL-native numeric/time/json types when
running against PostgreSQL.  The migration is intentionally additive and
idempotent for both supported database engines.
"""

from __future__ import annotations


VERSION = 64
NAME = "wan_link_monitoring_p0"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]).lower() for row in rows}



def _ensure_column(cursor, table: str, name: str, definition: str, use_pg: bool) -> None:
    if name not in _columns(cursor, table, use_pg):
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    time_type = "TIMESTAMPTZ"
    json_type = "JSONB"
    json_default = "'{}'::jsonb"

    _ensure_column(cursor, "interfaces", "if_index", "INTEGER", use_pg)

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS wan_links (
            id TEXT PRIMARY KEY,
            link_name TEXT NOT NULL,
            site_id TEXT DEFAULT '',
            site_name TEXT DEFAULT '',
            device_id TEXT NOT NULL,
            interface_id TEXT NOT NULL,
            interface_name TEXT NOT NULL,
            if_index INTEGER NOT NULL,
            provider TEXT DEFAULT '',
            circuit_number TEXT DEFAULT '',
            public_ip TEXT DEFAULT '',
            link_type TEXT NOT NULL DEFAULT 'Internet',
            link_role TEXT NOT NULL DEFAULT 'primary',
            direction_mode TEXT NOT NULL DEFAULT 'normal',
            contracted_download_bps BIGINT NOT NULL,
            contracted_upload_bps BIGINT NOT NULL,
            collection_interval_sec INTEGER NOT NULL DEFAULT 60,
            timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            maintenance_window TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at {time_type} NOT NULL,
            updated_at {time_type} NOT NULL
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_links_device ON wan_links(device_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_links_site ON wan_links(site_id, enabled)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_wan_links_interface ON wan_links(device_id, interface_id)")

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS wan_link_samples_1m (
            id TEXT PRIMARY KEY,
            link_id TEXT NOT NULL,
            sampled_at {time_type} NOT NULL,
            in_octets NUMERIC(20,0),
            out_octets NUMERIC(20,0),
            download_bps BIGINT,
            upload_bps BIGINT,
            download_util_pct NUMERIC(7,3),
            upload_util_pct NUMERIC(7,3),
            in_error_delta BIGINT,
            out_error_delta BIGINT,
            in_discard_delta BIGINT,
            out_discard_delta BIGINT,
            admin_status TEXT DEFAULT 'unknown',
            oper_status TEXT DEFAULT 'unknown',
            collection_status TEXT NOT NULL DEFAULT 'success',
            quality_flags {json_type} NOT NULL DEFAULT {json_default},
            collection_latency_ms INTEGER,
            created_at {time_type} NOT NULL,
            CONSTRAINT uq_wan_sample_link_time UNIQUE (link_id, sampled_at)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_samples_link_time ON wan_link_samples_1m(link_id, sampled_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_samples_time ON wan_link_samples_1m(sampled_at DESC)")

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS wan_link_current_status (
            link_id TEXT PRIMARY KEY,
            sampled_at {time_type},
            download_bps BIGINT,
            upload_bps BIGINT,
            download_util_pct NUMERIC(7,3),
            upload_util_pct NUMERIC(7,3),
            admin_status TEXT DEFAULT 'unknown',
            oper_status TEXT DEFAULT 'unknown',
            collection_status TEXT DEFAULT 'unknown',
            health_status TEXT NOT NULL DEFAULT 'unknown',
            active_alert_count INTEGER NOT NULL DEFAULT 0,
            last_success_at {time_type},
            consecutive_down_count INTEGER NOT NULL DEFAULT 0,
            updated_at {time_type} NOT NULL
        )
        """
    )

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS wan_alert_rules (
            id TEXT PRIMARY KEY,
            link_id TEXT NOT NULL,
            metric TEXT NOT NULL,
            severity TEXT NOT NULL,
            threshold_value NUMERIC(12,3),
            duration_sec INTEGER NOT NULL,
            recovery_threshold NUMERIC(12,3),
            recovery_duration_sec INTEGER NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at {time_type} NOT NULL,
            updated_at {time_type} NOT NULL,
            CONSTRAINT uq_wan_rule_link_metric UNIQUE (link_id, metric)
        )
        """
    )

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS wan_alert_events (
            id TEXT PRIMARY KEY,
            event_key TEXT NOT NULL UNIQUE,
            link_id TEXT NOT NULL,
            metric TEXT NOT NULL,
            severity TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'firing',
            title TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            metric_value NUMERIC(16,3),
            threshold_value NUMERIC(16,3),
            started_at {time_type} NOT NULL,
            last_seen_at {time_type} NOT NULL,
            recovered_at {time_type},
            details {json_type} NOT NULL DEFAULT {json_default},
            created_at {time_type} NOT NULL
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_events_status_time ON wan_alert_events(status, started_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_events_link_time ON wan_alert_events(link_id, started_at DESC)")
