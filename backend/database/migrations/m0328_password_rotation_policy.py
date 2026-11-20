"""Persist password rotation policy and notification deduplication log."""

from __future__ import annotations


VERSION = 328
NAME = "password_rotation_policy"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Password rotation policy requires PostgreSQL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS password_rotation_policy (
            id TEXT PRIMARY KEY,
            auto_rotate_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            interval_days INTEGER NOT NULL DEFAULT 90 CHECK (interval_days BETWEEN 1 AND 3650),
            notify_days INTEGER NOT NULL DEFAULT 14 CHECK (notify_days BETWEEN 1 AND 365),
            schedule_hour INTEGER NOT NULL DEFAULT 2 CHECK (schedule_hour BETWEEN 0 AND 23),
            schedule_minute INTEGER NOT NULL DEFAULT 0 CHECK (schedule_minute BETWEEN 0 AND 59),
            included_roles_json TEXT NOT NULL DEFAULT '["admin"]',
            updated_by TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS password_rotation_notification_log (
            dedup_key TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            role TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN ('expiring', 'expired', 'failed')),
            message TEXT NOT NULL DEFAULT '',
            notified_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    return None
