"""Add per-purpose storage routing for configuration and PAM objects."""

from __future__ import annotations


VERSION = 249
NAME = "storage_usage_bindings"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Storage usage bindings require PostgreSQL")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS storage_usage_bindings (
            purpose TEXT PRIMARY KEY,
            provider_mode TEXT NOT NULL DEFAULT 'default',
            provider_id TEXT,
            bucket_override TEXT,
            key_prefix TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            CONSTRAINT storage_usage_bindings_mode_chk
                CHECK (provider_mode IN ('default', 'environment', 'profile')),
            CONSTRAINT storage_usage_bindings_profile_chk
                CHECK (provider_mode <> 'profile' OR provider_id IS NOT NULL),
            CONSTRAINT storage_usage_bindings_prefix_chk
                CHECK (BTRIM(key_prefix) = '' OR (key_prefix NOT LIKE '/%' AND POSITION('..' IN key_prefix) = 0)),
            FOREIGN KEY (provider_id)
                REFERENCES storage_provider_configs(id)
                ON DELETE RESTRICT
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO storage_usage_bindings
            (purpose, provider_mode, provider_id, bucket_override, key_prefix, updated_at)
        VALUES
            ('config_backup', 'default', NULL, NULL, 'config', CURRENT_TIMESTAMP::TEXT),
            ('pam_recording', 'default', NULL, NULL, 'pam', CURRENT_TIMESTAMP::TEXT)
        ON CONFLICT (purpose) DO NOTHING
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_storage_usage_bindings_provider "
        "ON storage_usage_bindings(provider_id)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    return None


__all__ = ["VERSION", "NAME", "upgrade"]
