"""Add the PostgreSQL-native time-series and rollup model for WAN P1."""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 66
NAME = "wan_p1_time_series"


def upgrade(cursor, use_pg: bool) -> None:
    time_type = "TIMESTAMPTZ"
    json_type = "JSONB"
    json_default = "'{}'::jsonb"

    cursor.execute(
        """CREATE TABLE IF NOT EXISTS wan_link_samples_1m_partitioned (
            id TEXT NOT NULL, link_id TEXT NOT NULL, sampled_at TIMESTAMPTZ NOT NULL,
            in_octets NUMERIC(20,0), out_octets NUMERIC(20,0), download_bps BIGINT,
            upload_bps BIGINT, download_util_pct NUMERIC(7,3), upload_util_pct NUMERIC(7,3),
            in_error_delta BIGINT, out_error_delta BIGINT, in_discard_delta BIGINT,
            out_discard_delta BIGINT, admin_status TEXT, oper_status TEXT,
            collection_status TEXT NOT NULL, quality_flags JSONB NOT NULL DEFAULT '{}',
            collection_latency_ms INTEGER, created_at TIMESTAMPTZ NOT NULL,
            in_octets_hc NUMERIC(20,0), out_octets_hc NUMERIC(20,0), in_octets_32 BIGINT,
            out_octets_32 BIGINT, counter_width INTEGER, counter_source TEXT,
            counter_quality TEXT, device_uptime_cs BIGINT,
            PRIMARY KEY (link_id, sampled_at)
        ) PARTITION BY RANGE (sampled_at)"""
    )
    now = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for offset in range(-1, 4):
        month_index = now.year * 12 + now.month - 1 + offset
        year, month0 = divmod(month_index, 12)
        month = month0 + 1
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        next_month = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.utc)
        name = f"wan_link_samples_1m_{year}{month:02d}"
        cursor.execute(
            f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF wan_link_samples_1m_partitioned "
            f"FOR VALUES FROM ('{start.isoformat()}') TO ('{next_month.isoformat()}')",
        )
    cursor.execute(
        """INSERT INTO wan_link_samples_1m_partitioned (
            id, link_id, sampled_at, in_octets, out_octets, download_bps, upload_bps,
            download_util_pct, upload_util_pct, in_error_delta, out_error_delta,
            in_discard_delta, out_discard_delta, admin_status, oper_status, collection_status,
            quality_flags, collection_latency_ms, created_at, in_octets_hc, out_octets_hc,
            in_octets_32, out_octets_32, counter_width, counter_source, counter_quality, device_uptime_cs
        ) SELECT id, link_id, sampled_at, in_octets, out_octets, download_bps, upload_bps,
            download_util_pct, upload_util_pct, in_error_delta, out_error_delta,
            in_discard_delta, out_discard_delta, admin_status, oper_status, collection_status,
            quality_flags, collection_latency_ms, created_at, in_octets_hc, out_octets_hc,
            in_octets_32, out_octets_32, counter_width, counter_source, counter_quality, device_uptime_cs
        FROM wan_link_samples_1m
        WHERE sampled_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
        ON CONFLICT (link_id, sampled_at) DO NOTHING"""
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_samples_1m_part_link_time ON wan_link_samples_1m_partitioned(link_id, sampled_at DESC)")

    for table in ("wan_link_samples_5m", "wan_link_samples_1h", "wan_link_samples_daily"):
        cursor.execute(
            f"""CREATE TABLE IF NOT EXISTS {table} (
                link_id TEXT NOT NULL, bucket_start {time_type} NOT NULL,
                sample_count INTEGER NOT NULL DEFAULT 0, coverage_pct NUMERIC(6,2),
                avg_download_bps BIGINT, avg_upload_bps BIGINT,
                max_download_bps BIGINT, max_upload_bps BIGINT,
                p95_download_bps BIGINT, p95_upload_bps BIGINT,
                avg_download_util_pct NUMERIC(7,3), avg_upload_util_pct NUMERIC(7,3),
                max_download_util_pct NUMERIC(7,3), max_upload_util_pct NUMERIC(7,3),
                in_error_total BIGINT, out_error_total BIGINT,
                in_discard_total BIGINT, out_discard_total BIGINT,
                quality_flags {json_type} NOT NULL DEFAULT {json_default},
                updated_at {time_type} NOT NULL,
                PRIMARY KEY (link_id, bucket_start)
            )"""
        )
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_time ON {table}(bucket_start DESC)")
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_link_time ON {table}(link_id, bucket_start DESC)")

    cursor.execute(
        f"""CREATE TABLE IF NOT EXISTS wan_retention_policies (
            id TEXT PRIMARY KEY, raw_days INTEGER NOT NULL DEFAULT 30,
            five_min_days INTEGER NOT NULL DEFAULT 180, hourly_days INTEGER NOT NULL DEFAULT 730,
            daily_days INTEGER NOT NULL DEFAULT 3650, alert_days INTEGER NOT NULL DEFAULT 1095,
            enabled BOOLEAN NOT NULL DEFAULT TRUE, updated_at {time_type} NOT NULL
        )"""
    )
    cursor.execute(
        "INSERT INTO wan_retention_policies (id, updated_at) VALUES ('default', ?) ON CONFLICT(id) DO NOTHING",
        (datetime.now(timezone.utc).replace(microsecond=0).isoformat(),),
    )
