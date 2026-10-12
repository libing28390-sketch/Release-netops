"""Add durable storage for monitoring alert notification deliveries."""

from __future__ import annotations


VERSION = 241
NAME = "monitoring_notification_outbox"


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Existing probe targets belong to the system/default tenant until an
    # operator or tenant-aware API explicitly moves them.
    cursor.execute(
        "ALTER TABLE outbound_probe_targets ADD COLUMN IF NOT EXISTS "
        "tenant_id TEXT NOT NULL DEFAULT 'tenant-default'"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_outbound_probe_targets_tenant_id "
        "ON outbound_probe_targets (tenant_id)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_delivery_outbox (
            id TEXT PRIMARY KEY,
            delivery_key TEXT NOT NULL UNIQUE,
            channel TEXT NOT NULL CHECK (channel IN ('workspace', 'global_webhook')),
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'processing', 'succeeded', 'failed')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            max_attempts INTEGER NOT NULL DEFAULT 8 CHECK (max_attempts > 0),
            available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            lease_owner TEXT NOT NULL DEFAULT '',
            lease_until TIMESTAMPTZ,
            last_error TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            completed_at TIMESTAMPTZ
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_delivery_outbox_claim "
        "ON alert_delivery_outbox (available_at, created_at, id) "
        "WHERE status IN ('pending', 'processing')"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_delivery_outbox_status_created "
        "ON alert_delivery_outbox (status, created_at DESC)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Retain delivery history and pending notifications during rollback.
    return None
