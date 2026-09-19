"""Add model health probe timestamps, history and SLA indexes."""

from __future__ import annotations


VERSION = 216
NAME = "ai_model_health_monitoring"


def _has_column(cursor, table: str, column: str) -> bool:
    row = cursor.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ? AND column_name = ?",
        (table, column),
    ).fetchone()
    return bool(row)


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("AI model health monitoring migration requires PostgreSQL")
    if not _has_column(cursor, "ai_model", "last_health_check_at"):
        cursor.execute("ALTER TABLE ai_model ADD COLUMN IF NOT EXISTS last_health_check_at TEXT")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_model_health_check (
            id TEXT PRIMARY KEY,
            model_id TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            status TEXT NOT NULL,
            latency_ms INTEGER NOT NULL DEFAULT 0,
            error_code TEXT,
            FOREIGN KEY (model_id) REFERENCES ai_model(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_model_health_check_model_time "
        "ON ai_model_health_check(model_id, checked_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_model_health_check_time "
        "ON ai_model_health_check(checked_at)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Retain probe history during rollback so operational evidence is not
    # silently discarded by an application downgrade.
    return None
