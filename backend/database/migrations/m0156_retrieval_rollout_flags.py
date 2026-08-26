"""Persist tenant-scoped retrieval rollout state for the V1/V2 cutover."""

from __future__ import annotations


VERSION = 156
NAME = "retrieval_rollout_flags"


def upgrade(cursor, use_pg: bool) -> None:
    """Create the PostgreSQL-only rollout-state projection idempotently."""

    if not use_pg:
        return

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_retrieval_rollout_flag (
            tenant_id TEXT PRIMARY KEY,
            mode TEXT NOT NULL DEFAULT 'off'
                CHECK (mode IN ('off', 'shadow', 'v2')),
            rollout_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
            changed_by TEXT,
            changed_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ai_retrieval_rollout_mode
        ON ai_retrieval_rollout_flag(mode, changed_at)
        """
    )
