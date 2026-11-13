"""Index short-lived shared CLI results and bounded task retention."""

from __future__ import annotations


VERSION = 223
NAME = "locator_query_task_retention"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("locator_query_task_retention requires PostgreSQL")
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_locator_tasks_terminal_retention
            ON locator_query_tasks(completed_at)
         WHERE status IN ('succeeded', 'failed', 'cancelled', 'expired')
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    cursor.execute("DROP INDEX IF EXISTS ix_locator_tasks_terminal_retention")


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
