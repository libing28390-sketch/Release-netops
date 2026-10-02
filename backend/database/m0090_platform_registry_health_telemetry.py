"""Persist structured platform-action outcomes for P2 health and failure closure."""

from __future__ import annotations


VERSION = 90
NAME = "platform_registry_health_telemetry"


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_action_runs (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            device_id TEXT NOT NULL,
            platform_profile_id TEXT,
            platform_release_id TEXT,
            action_code TEXT NOT NULL,
            parser_template_version_id TEXT,
            status TEXT NOT NULL DEFAULT 'FAILED',
            failure_stage TEXT,
            error_code TEXT,
            record_count INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            output_bytes INTEGER NOT NULL DEFAULT 0,
            raw_output TEXT NOT NULL DEFAULT '{}',
            raw_output_encrypted TEXT,
            raw_output_expires_at TEXT,
            created_at TEXT NOT NULL,
            CHECK (status IN ('SUCCESS', 'FAILED')),
            CHECK (record_count >= 0),
            CHECK (duration_ms >= 0),
            CHECK (output_bytes >= 0)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_platform_action_runs_profile_time "
        "ON platform_action_runs(platform_profile_id, created_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_platform_action_runs_release_time "
        "ON platform_action_runs(platform_release_id, created_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_platform_action_runs_failure_time "
        "ON platform_action_runs(status, error_code, created_at DESC)"
    )
