"""Add durable cursors for bounded collector sweeps."""

from __future__ import annotations


VERSION = 47
NAME = "collector_sweep_state"


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS collector_sweep_state (
            collector TEXT PRIMARY KEY,
            cursor_position INTEGER NOT NULL DEFAULT 0,
            last_run_id TEXT DEFAULT '',
            last_started_at TEXT,
            last_completed_at TEXT,
            last_eligible INTEGER NOT NULL DEFAULT 0,
            last_selected INTEGER NOT NULL DEFAULT 0,
            last_batch_size INTEGER NOT NULL DEFAULT 0,
            last_successful INTEGER NOT NULL DEFAULT 0,
            last_failed INTEGER NOT NULL DEFAULT 0,
            last_collected INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_collector_sweep_completed "
        "ON collector_sweep_state(last_completed_at)"
    )
