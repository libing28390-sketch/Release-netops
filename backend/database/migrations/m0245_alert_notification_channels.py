"""Add per-rule notification channels, SMTP settings, and delivery audit data."""

from __future__ import annotations


VERSION = 245
NAME = "alert_notification_channels"


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    cursor.execute(
        """
        ALTER TABLE alert_rules
        ADD COLUMN IF NOT EXISTS notification_channels_json JSONB
        NOT NULL DEFAULT '["workspace"]'::jsonb
        """
    )
    cursor.execute(
        """
        UPDATE alert_rules
           SET notification_channels_json = '["workspace"]'::jsonb
         WHERE notification_channels_json IS NULL
            OR jsonb_typeof(notification_channels_json) <> 'array'
            OR jsonb_array_length(notification_channels_json) = 0
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_smtp_configs (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            name TEXT NOT NULL DEFAULT 'primary',
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            host TEXT NOT NULL DEFAULT '',
            port INTEGER NOT NULL DEFAULT 587,
            security TEXT NOT NULL DEFAULT 'starttls'
                CHECK (security IN ('ssl', 'starttls', 'none')),
            username TEXT NOT NULL DEFAULT '',
            password_ciphertext TEXT NOT NULL DEFAULT '',
            from_address TEXT NOT NULL DEFAULT '',
            from_name TEXT NOT NULL DEFAULT 'Nexora',
            reply_to TEXT NOT NULL DEFAULT '',
            connect_timeout_seconds INTEGER NOT NULL DEFAULT 10,
            send_timeout_seconds INTEGER NOT NULL DEFAULT 20,
            rate_limit_per_minute INTEGER NOT NULL DEFAULT 60,
            created_by TEXT NOT NULL DEFAULT 'system',
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            updated_by TEXT NOT NULL DEFAULT 'system',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            UNIQUE (tenant_id, name)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_smtp_configs_tenant "
        "ON notification_smtp_configs(tenant_id, enabled)"
    )

    cursor.execute(
        """
        ALTER TABLE alert_delivery_outbox
        ADD COLUMN IF NOT EXISTS alert_id TEXT,
        ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
        ADD COLUMN IF NOT EXISTS event_kind TEXT NOT NULL DEFAULT 'active',
        ADD COLUMN IF NOT EXISTS destination_key TEXT NOT NULL DEFAULT ''
        """
    )
    cursor.execute(
        "ALTER TABLE alert_delivery_outbox "
        "DROP CONSTRAINT IF EXISTS alert_delivery_outbox_channel_check"
    )
    cursor.execute(
        "ALTER TABLE alert_delivery_outbox "
        "ADD CONSTRAINT alert_delivery_outbox_channel_check "
        "CHECK (channel IN ('workspace', 'feishu', 'dingtalk', 'wechat', 'email', 'global_webhook'))"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_delivery_outbox_alert "
        "ON alert_delivery_outbox(alert_id, created_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_delivery_outbox_tenant "
        "ON alert_delivery_outbox(tenant_id, status, created_at DESC)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_delivery_attempts (
            id TEXT PRIMARY KEY,
            delivery_id TEXT NOT NULL,
            alert_id TEXT,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            channel TEXT NOT NULL,
            event_kind TEXT NOT NULL DEFAULT 'active',
            attempt_no INTEGER NOT NULL DEFAULT 1 CHECK (attempt_no > 0),
            status TEXT NOT NULL DEFAULT 'sending'
                CHECK (status IN ('queued', 'sending', 'retrying', 'succeeded', 'failed', 'skipped')),
            error_code TEXT NOT NULL DEFAULT '',
            error_summary TEXT NOT NULL DEFAULT '',
            provider_class TEXT NOT NULL DEFAULT '',
            recipient_count INTEGER NOT NULL DEFAULT 0,
            started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            finished_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_delivery_attempts_alert "
        "ON alert_delivery_attempts(alert_id, created_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_delivery_attempts_delivery "
        "ON alert_delivery_attempts(delivery_id, attempt_no DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_delivery_attempts_status "
        "ON alert_delivery_attempts(status, created_at DESC)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Preserve notification configuration and audit history during rollback.
    return None


__all__ = ["VERSION", "NAME", "upgrade"]
