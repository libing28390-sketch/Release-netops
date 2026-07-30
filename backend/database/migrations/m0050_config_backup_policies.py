"""Add persistent configuration-backup policies and policy attribution."""

from __future__ import annotations


VERSION = 50
NAME = "config_backup_policies"


def _column_exists(cursor, table: str, column: str, use_pg: bool) -> bool:
    if use_pg:
        row = cursor.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = ?
              AND column_name = ?
            """,
            (table, column),
        ).fetchone()
        return row is not None
    rows = cursor.execute(f"PRAGMA table_info({table})").fetchall()
    return any(str(row[1]) == column for row in rows)


def _ensure_column(cursor, table: str, column: str, definition: str, use_pg: bool) -> None:
    if not _column_exists(cursor, table, column, use_pg):
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_backup_policies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            cron_expr TEXT NOT NULL DEFAULT '0 2 * * *',
            timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
            priority INTEGER NOT NULL DEFAULT 100,
            scope_json TEXT NOT NULL DEFAULT '{}',
            config_types_json TEXT NOT NULL DEFAULT '["running"]',
            change_only INTEGER NOT NULL DEFAULT 1,
            retention_days INTEGER NOT NULL DEFAULT 90,
            max_versions_per_device INTEGER NOT NULL DEFAULT 30,
            concurrency INTEGER NOT NULL DEFAULT 10,
            retry_count INTEGER NOT NULL DEFAULT 1,
            timeout_seconds INTEGER NOT NULL DEFAULT 30,
            created_by TEXT NOT NULL DEFAULT '',
            updated_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_backup_policies_enabled_priority "
        "ON config_backup_policies(enabled, priority, name)"
    )

    _ensure_column(cursor, "config_backup_runs", "policy_id", "TEXT DEFAULT ''", use_pg)
    _ensure_column(cursor, "config_snapshots", "policy_id", "TEXT DEFAULT ''", use_pg)
    _ensure_column(cursor, "config_snapshots", "config_type", "TEXT DEFAULT 'running'", use_pg)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_backup_runs_policy_started "
        "ON config_backup_runs(policy_id, started_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_snapshots_policy_device_time "
        "ON config_snapshots(policy_id, device_id, timestamp DESC)"
    )
