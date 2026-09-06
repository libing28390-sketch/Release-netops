"""Add maintenance, link-group, alert workflow and reporting tables."""

from __future__ import annotations


VERSION = 67
NAME = "wan_p1_operations"


def upgrade(cursor, use_pg: bool) -> None:
    time_type = "TIMESTAMPTZ"
    json_type = "JSONB"
    json_default = "'{}'::jsonb"
    cursor.execute(
        f"""CREATE TABLE IF NOT EXISTS wan_maintenance_windows (
            id TEXT PRIMARY KEY, site_id TEXT DEFAULT '', link_id TEXT DEFAULT '',
            name TEXT NOT NULL, starts_at {time_type} NOT NULL, ends_at {time_type} NOT NULL,
            timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai', reason TEXT DEFAULT '',
            enabled BOOLEAN NOT NULL DEFAULT TRUE, created_by TEXT DEFAULT '', created_at {time_type} NOT NULL,
            updated_at {time_type} NOT NULL
        )"""
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_maintenance_window ON wan_maintenance_windows(starts_at, ends_at, enabled)")
    cursor.execute(
        f"""CREATE TABLE IF NOT EXISTS wan_link_groups (
            id TEXT PRIMARY KEY, group_name TEXT NOT NULL UNIQUE, mode TEXT NOT NULL DEFAULT 'primary_backup',
            site_id TEXT DEFAULT '', provider TEXT DEFAULT '', enabled BOOLEAN NOT NULL DEFAULT TRUE,
            created_at {time_type} NOT NULL, updated_at {time_type} NOT NULL
        )"""
    )
    cursor.execute(
        f"""CREATE TABLE IF NOT EXISTS wan_link_group_members (
            group_id TEXT NOT NULL, link_id TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'primary',
            priority INTEGER NOT NULL DEFAULT 100, weight INTEGER NOT NULL DEFAULT 1,
            created_at {time_type} NOT NULL, updated_at {time_type} NOT NULL,
            PRIMARY KEY (group_id, link_id)
        )"""
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_group_members_link ON wan_link_group_members(link_id)")
    cursor.execute(
        f"""CREATE TABLE IF NOT EXISTS wan_alert_event_audit (
            id TEXT PRIMARY KEY, event_id TEXT NOT NULL, action TEXT NOT NULL,
            actor_id TEXT DEFAULT '', actor_name TEXT DEFAULT '', before_json {json_type} NOT NULL DEFAULT {json_default},
            after_json {json_type} NOT NULL DEFAULT {json_default}, created_at {time_type} NOT NULL
        )"""
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_alert_audit_event ON wan_alert_event_audit(event_id, created_at DESC)")
    cursor.execute(
        f"""CREATE TABLE IF NOT EXISTS wan_report_runs (
            id TEXT PRIMARY KEY, report_type TEXT NOT NULL, period_start {time_type} NOT NULL,
            period_end {time_type} NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
            scope_json {json_type} NOT NULL DEFAULT {json_default}, result_json {json_type} NOT NULL DEFAULT {json_default},
            generated_by TEXT DEFAULT '', created_at {time_type} NOT NULL, completed_at {time_type}
        )"""
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_reports_period ON wan_report_runs(report_type, period_end DESC)")
