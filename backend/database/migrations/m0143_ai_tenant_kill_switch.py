"""Tenant-scoped AI Security Gateway kill switch."""

from __future__ import annotations

VERSION = 143
NAME = "ai_tenant_kill_switch"


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_tenant_security_controls (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL UNIQUE,
            kill_switch INTEGER NOT NULL DEFAULT 0,
            reason TEXT,
            changed_by TEXT,
            changed_at TEXT NOT NULL
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_tenant_security_controls ON ai_tenant_security_controls(tenant_id, kill_switch)")


def downgrade(cursor, use_pg: bool) -> None:
    return None
