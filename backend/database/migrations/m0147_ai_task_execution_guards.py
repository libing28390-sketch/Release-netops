"""API-009: bounded task execution and optimistic state transitions.

The migration is additive.  Existing task rows remain readable, while new
workers can atomically claim a task, consume a step/tool budget, and finalize
it only when their execution token still owns the running lease.
"""

from __future__ import annotations


VERSION = 147
NAME = "ai_task_execution_guards"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    try:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]) for row in rows}

    except Exception:
        return set()


def _ensure_columns(cursor, table: str, definitions: dict[str, str], use_pg: bool) -> None:
    existing = _columns(cursor, table, use_pg)
    if not existing:
        return
    for name, definition in definitions.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    definitions = {
        "current_steps": "INTEGER NOT NULL DEFAULT 0",
        "current_tool_calls": "INTEGER NOT NULL DEFAULT 0",
        "execution_token": "TEXT",
        "version": "INTEGER NOT NULL DEFAULT 0",
        "updated_at": "TEXT",
        "cancel_requested_at": "TEXT",
    }
    _ensure_columns(cursor, "ai_tasks", definitions, use_pg)
    task_columns = _columns(cursor, "ai_tasks", use_pg)
    if not task_columns:
        return

    # Existing rows get a stable timestamp and bounded counters.  These
    # statements are intentionally best-effort for partially provisioned
    # legacy installations; the next startup will retry them.
    try:
        if "created_at" not in task_columns:
            raise RuntimeError("legacy task table has no created_at")
        cursor.execute(
            "UPDATE ai_tasks SET updated_at = COALESCE(NULLIF(updated_at, ''), created_at)"
        )
    except Exception:
        pass
    tool_columns = _columns(cursor, "ai_tool_calls", use_pg)
    try:
        if not {"task_id", "step_no"}.issubset(tool_columns):
            raise RuntimeError("tool call table is not provisioned")
        cursor.execute(
            """UPDATE ai_tasks t
               SET current_tool_calls = COALESCE((
                       SELECT COUNT(*) FROM ai_tool_calls c WHERE c.task_id = t.id
                   ), 0),
                   current_steps = COALESCE((
                       SELECT MAX(c.step_no) FROM ai_tool_calls c WHERE c.task_id = t.id
                   ), 0)
               WHERE COALESCE(t.current_tool_calls, 0) = 0
                 AND COALESCE(t.current_steps, 0) = 0"""
        )
    except Exception:
        pass

    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_ai_tasks_execution_scope "
        "ON ai_tasks(tenant_id, user_id_opaque, state, deadline_at, updated_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_tasks_execution_token "
        "ON ai_tasks(execution_token, state, updated_at)",
    ):
        try:
            cursor.execute(statement)
        except Exception:
            pass


def downgrade(cursor, use_pg: bool) -> None:
    # Retain execution counters and tokens as audit evidence.  Rollback is a
    # code-path disable, not destructive schema removal.
    return None
