"""Persist S3 storage profiles and bind stored objects to their provider."""

from __future__ import annotations


VERSION = 248
NAME = "storage_provider_configs"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Storage provider persistence requires PostgreSQL")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS storage_provider_configs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            backend TEXT NOT NULL DEFAULT 's3',
            endpoint_url TEXT NOT NULL,
            bucket TEXT NOT NULL,
            region TEXT NOT NULL DEFAULT 'us-east-1',
            access_key_id_encrypted TEXT NOT NULL DEFAULT '',
            secret_access_key_encrypted TEXT NOT NULL DEFAULT '',
            force_path_style BOOLEAN NOT NULL DEFAULT TRUE,
            verify_tls BOOLEAN NOT NULL DEFAULT TRUE,
            is_default BOOLEAN NOT NULL DEFAULT FALSE,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CONSTRAINT storage_provider_configs_backend_chk CHECK (backend = 's3'),
            CONSTRAINT storage_provider_configs_endpoint_chk CHECK (BTRIM(endpoint_url) <> ''),
            CONSTRAINT storage_provider_configs_bucket_chk CHECK (BTRIM(bucket) <> '')
        )
        """
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_storage_provider_configs_default "
        "ON storage_provider_configs(is_default) WHERE is_default"
    )
    cursor.execute(
        "ALTER TABLE config_snapshots ADD COLUMN IF NOT EXISTS storage_config_id TEXT"
    )
    cursor.execute(
        "ALTER TABLE pam_sessions ADD COLUMN IF NOT EXISTS storage_config_id TEXT"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_snapshots_storage_config "
        "ON config_snapshots(storage_config_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_pam_sessions_storage_config "
        "ON pam_sessions(storage_config_id)"
    )
    cursor.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'config_snapshots_storage_config_id_fkey'
            ) THEN
                ALTER TABLE config_snapshots
                ADD CONSTRAINT config_snapshots_storage_config_id_fkey
                FOREIGN KEY (storage_config_id)
                REFERENCES storage_provider_configs(id)
                ON DELETE RESTRICT;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'pam_sessions_storage_config_id_fkey'
            ) THEN
                ALTER TABLE pam_sessions
                ADD CONSTRAINT pam_sessions_storage_config_id_fkey
                FOREIGN KEY (storage_config_id)
                REFERENCES storage_provider_configs(id)
                ON DELETE RESTRICT;
            END IF;
        END $$
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Provider IDs are retained so existing objects remain readable on rollback.
    return None


__all__ = ["VERSION", "NAME", "upgrade"]
