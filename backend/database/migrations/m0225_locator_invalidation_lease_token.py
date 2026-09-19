"""Add fencing token support to the locator invalidation outbox."""

from __future__ import annotations


VERSION = 225
NAME = "locator_invalidation_lease_token"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("locator_invalidation_lease_token requires PostgreSQL")
    cursor.execute(
        """
        ALTER TABLE locator_invalidation_outbox
        ADD COLUMN IF NOT EXISTS lease_token TEXT NOT NULL DEFAULT ''
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Preserve lease fencing metadata during an application rollback.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
