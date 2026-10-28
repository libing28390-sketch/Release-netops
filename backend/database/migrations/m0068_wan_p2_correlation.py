"""Add probe bindings, correlation evidence, baselines and recommendations."""

from __future__ import annotations


VERSION = 68
NAME = "wan_p2_correlation"


def upgrade(cursor, use_pg: bool) -> None:
    time_type = "TIMESTAMPTZ"
    json_type = "JSONB"
    json_default = "'{}'::jsonb"
    cursor.execute(
        f"""CREATE TABLE IF NOT EXISTS wan_probe_bindings (
            id TEXT PRIMARY KEY, link_id TEXT NOT NULL, target_id TEXT NOT NULL,
            route_mode TEXT NOT NULL DEFAULT 'default', source_ip TEXT DEFAULT '', priority INTEGER NOT NULL DEFAULT 100,
            enabled BOOLEAN NOT NULL DEFAULT TRUE, created_by TEXT DEFAULT '', created_at {time_type} NOT NULL,
            updated_at {time_type} NOT NULL, UNIQUE (link_id, target_id)
        )"""
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_probe_bindings_target ON wan_probe_bindings(target_id, enabled)")
    cursor.execute(
        f"""CREATE TABLE IF NOT EXISTS wan_correlation_events (
            id TEXT PRIMARY KEY, correlation_group TEXT NOT NULL, root_cause_code TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info', status TEXT NOT NULL DEFAULT 'open', confidence NUMERIC(5,3),
            title TEXT NOT NULL, summary TEXT DEFAULT '', scope_json {json_type} NOT NULL DEFAULT {json_default},
            rule_version TEXT NOT NULL DEFAULT 'wan-correlation-v1', starts_at {time_type} NOT NULL,
            last_seen_at {time_type} NOT NULL, resolved_at {time_type}, created_at {time_type} NOT NULL,
            updated_at {time_type} NOT NULL
        )"""
    )
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_wan_active_correlation ON wan_correlation_events(correlation_group, root_cause_code) WHERE status IN ('open', 'acknowledged')")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_correlation_time ON wan_correlation_events(status, starts_at DESC)")
    cursor.execute(
        f"""CREATE TABLE IF NOT EXISTS wan_correlation_evidence (
            id TEXT PRIMARY KEY, event_id TEXT NOT NULL, source_type TEXT NOT NULL, source_id TEXT DEFAULT '',
            observed_at {time_type} NOT NULL, metric TEXT DEFAULT '', metric_value NUMERIC,
            details_json {json_type} NOT NULL DEFAULT {json_default}, created_at {time_type} NOT NULL
        )"""
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_correlation_evidence_event ON wan_correlation_evidence(event_id, observed_at)")
    cursor.execute(
        f"""CREATE TABLE IF NOT EXISTS wan_baselines (
            id TEXT PRIMARY KEY, link_id TEXT NOT NULL, direction TEXT NOT NULL DEFAULT 'download',
            weekday INTEGER NOT NULL, hour INTEGER NOT NULL, sample_count INTEGER NOT NULL DEFAULT 0,
            median_bps BIGINT, p95_bps BIGINT, stddev_bps NUMERIC, median_util_pct NUMERIC(7,3),
            p95_util_pct NUMERIC(7,3), window_days INTEGER NOT NULL DEFAULT 30,
            status TEXT NOT NULL DEFAULT 'ready', calculated_at {time_type} NOT NULL,
            UNIQUE (link_id, direction, weekday, hour, window_days)
        )"""
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_baselines_link_time ON wan_baselines(link_id, weekday, hour)")
    cursor.execute(
        f"""CREATE TABLE IF NOT EXISTS wan_capacity_recommendations (
            id TEXT PRIMARY KEY, link_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'observing',
            recommendation TEXT NOT NULL, confidence NUMERIC(5,3), evidence_json {json_type} NOT NULL DEFAULT {json_default},
            period_start {time_type} NOT NULL, period_end {time_type} NOT NULL,
            reviewed_by TEXT DEFAULT '', reviewed_at {time_type}, created_at {time_type} NOT NULL, updated_at {time_type} NOT NULL
        )"""
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_capacity_link_period ON wan_capacity_recommendations(link_id, period_end DESC)")
