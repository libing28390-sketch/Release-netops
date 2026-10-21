"""Add display metadata and recipient targets to SMTP notification profiles."""

from __future__ import annotations


VERSION = 256
NAME = "email_notification_profiles"


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    """Extend the m0245 SMTP table without rewriting existing credentials."""
    cursor.execute(
        """
        ALTER TABLE notification_smtp_configs
        ADD COLUMN IF NOT EXISTS display_name TEXT NOT NULL DEFAULT '',
        ADD COLUMN IF NOT EXISTS recipient_targets_json JSONB NOT NULL DEFAULT '[]'::jsonb
        """
    )
    cursor.execute(
        """
        UPDATE notification_smtp_configs
           SET display_name = CASE
               WHEN COALESCE(NULLIF(BTRIM(display_name), ''), '') = ''
               THEN CASE
                   WHEN LOWER(COALESCE(NULLIF(BTRIM(name), ''), '')) = 'primary'
                   THEN '默认邮件通道'
                   ELSE COALESCE(NULLIF(BTRIM(name), ''), 'SMTP')
               END
               ELSE display_name
           END,
               recipient_targets_json = CASE
                   WHEN recipient_targets_json IS NULL
                     OR jsonb_typeof(recipient_targets_json) <> 'array'
                   THEN '[]'::jsonb
                   ELSE recipient_targets_json
               END
         WHERE COALESCE(NULLIF(BTRIM(display_name), ''), '') = ''
            OR recipient_targets_json IS NULL
            OR jsonb_typeof(recipient_targets_json) <> 'array'
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Preserve profile metadata and recipient configuration during rollback.
    return None


__all__ = ["VERSION", "NAME", "upgrade"]
