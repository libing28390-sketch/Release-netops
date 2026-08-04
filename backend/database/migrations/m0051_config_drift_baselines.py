"""Add explicit configuration baselines and drift comparison metadata."""

from __future__ import annotations


VERSION = 51
NAME = "config_drift_baselines"


def _column_exists(cursor, table: str, column: str, use_pg: bool) -> bool:
    if use_pg:
        return cursor.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = ?
              AND column_name = ?
            """,
            (table, column),
        ).fetchone() is not None
    return any(str(row[1]) == column for row in cursor.execute(f"PRAGMA table_info({table})").fetchall())


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_baselines (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            config_type TEXT NOT NULL DEFAULT 'running',
            snapshot_id TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            set_by TEXT NOT NULL DEFAULT '',
            set_at TEXT NOT NULL,
            UNIQUE(device_id, config_type)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_baselines_snapshot "
        "ON config_baselines(snapshot_id)"
    )
    if not _column_exists(cursor, "config_drift_results", "baseline_source", use_pg):
        cursor.execute(
            "ALTER TABLE config_drift_results ADD COLUMN baseline_source TEXT DEFAULT 'previous'"
        )
    if not _column_exists(cursor, "config_drift_results", "diff_mode", use_pg):
        cursor.execute(
            "ALTER TABLE config_drift_results ADD COLUMN diff_mode TEXT DEFAULT 'normalized'"
        )
