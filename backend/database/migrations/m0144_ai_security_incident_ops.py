"""Indexes for tenant-scoped AI security incident response."""

from __future__ import annotations

VERSION = 144
NAME = "ai_security_incident_ops"


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_security_incidents_tenant_status_created "
        "ON ai_security_incidents(tenant_id, status, created_at)"
    )


def downgrade(cursor, use_pg: bool) -> None:
    return None
