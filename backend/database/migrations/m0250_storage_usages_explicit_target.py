"""Replace dynamic default routes with their current explicit storage target."""

from __future__ import annotations


VERSION = 250
NAME = "storage_usages_explicit_target"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Storage usage routing requires PostgreSQL")
    cursor.execute(
        """
        UPDATE storage_usage_bindings
        SET provider_mode = 'environment', provider_id = NULL,
            updated_at = CURRENT_TIMESTAMP::TEXT
        WHERE provider_mode = 'default'
          AND NOT EXISTS (
              SELECT 1 FROM storage_provider_configs WHERE is_default = TRUE
          )
        """
    )
    cursor.execute(
        """
        UPDATE storage_usage_bindings
        SET provider_mode = 'profile',
            provider_id = (
                SELECT id FROM storage_provider_configs
                WHERE is_default = TRUE LIMIT 1
            ),
            updated_at = CURRENT_TIMESTAMP::TEXT
        WHERE provider_mode = 'default'
          AND EXISTS (
              SELECT 1 FROM storage_provider_configs WHERE is_default = TRUE
          )
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    return None


__all__ = ["VERSION", "NAME", "upgrade"]
