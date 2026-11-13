"""Use one global storage provider for all storage-backed purposes."""

from __future__ import annotations


VERSION = 251
NAME = "storage_single_default"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Storage usage bindings require PostgreSQL")
    cursor.execute(
        """
        UPDATE storage_usage_bindings
        SET provider_mode = 'default',
            provider_id = NULL,
            bucket_override = NULL,
            updated_at = CURRENT_TIMESTAMP::TEXT
        WHERE provider_mode <> 'default'
           OR provider_id IS NOT NULL
           OR bucket_override IS NOT NULL
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    return None


__all__ = ["VERSION", "NAME", "upgrade"]
