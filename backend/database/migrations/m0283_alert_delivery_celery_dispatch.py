"""Add broker publication leases and dispatch fencing to alert deliveries."""

from __future__ import annotations


VERSION = 283
NAME = "alert_delivery_celery_dispatch"


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    cursor.execute(
        "ALTER TABLE alert_delivery_outbox "
        "DROP CONSTRAINT IF EXISTS alert_delivery_outbox_channel_check"
    )
    cursor.execute(
        "ALTER TABLE alert_delivery_outbox "
        "ADD CONSTRAINT alert_delivery_outbox_channel_check "
        "CHECK (channel IN ('workspace', 'feishu', 'dingtalk', 'wechat', 'email', 'global_webhook', 'grafana_feishu'))"
    )
    cursor.execute(
        """
        ALTER TABLE alert_delivery_outbox
            ADD COLUMN IF NOT EXISTS dispatch_generation BIGINT NOT NULL DEFAULT 1,
            ADD COLUMN IF NOT EXISTS published_generation BIGINT NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'normal',
            ADD COLUMN IF NOT EXISTS publish_attempts INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS publish_redrive_count INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS publish_available_at TIMESTAMPTZ NOT NULL DEFAULT '1970-01-01 00:00:00+00'::timestamptz,
            ADD COLUMN IF NOT EXISTS publish_lease_owner TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS publish_lease_until TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS publish_last_error TEXT NOT NULL DEFAULT ''
        """
    )
    cursor.execute(
        """
        ALTER TABLE alert_delivery_outbox
            ALTER COLUMN publish_available_at SET DEFAULT clock_timestamp()
        """
    )
    cursor.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE conname = 'alert_delivery_outbox_priority_check'
            ) THEN
                ALTER TABLE alert_delivery_outbox
                    ADD CONSTRAINT alert_delivery_outbox_priority_check
                    CHECK (priority IN ('critical', 'normal'));
            END IF;
        END $$
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_alert_delivery_outbox_publish_ready
            ON alert_delivery_outbox (publish_available_at, available_at, created_at, id)
         WHERE status = 'pending'
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_alert_delivery_outbox_expired_lease
            ON alert_delivery_outbox (lease_until, id)
         WHERE status = 'processing'
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep dispatch history and pending messages intact for safe rollback.
    return None


__all__ = ["VERSION", "NAME", "upgrade"]
