"""Persist safe, tenant-scoped platform-identification conflict work items."""

from __future__ import annotations


VERSION = 91
NAME = "platform_identification_conflicts"


def upgrade(cursor, use_pg: bool) -> None:
    json_type = "JSONB" if use_pg else "TEXT"
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS platform_identification_conflicts (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            device_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            conflict_fingerprint TEXT NOT NULL,
            platform_candidates_json {json_type} NOT NULL DEFAULT '[]',
            observation_commands_json {json_type} NOT NULL DEFAULT '[]',
            resolved_profile_id TEXT,
            resolved_by TEXT,
            resolution_reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            resolved_at TEXT,
            CHECK (status IN ('OPEN', 'RESOLVED', 'IGNORED'))
        )
        """
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_identification_conflict_open "
        "ON platform_identification_conflicts(device_id, conflict_fingerprint, status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_platform_identification_conflicts_scope "
        "ON platform_identification_conflicts(tenant_id, status, updated_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_platform_identification_conflicts_device "
        "ON platform_identification_conflicts(device_id, status, updated_at)"
    )
