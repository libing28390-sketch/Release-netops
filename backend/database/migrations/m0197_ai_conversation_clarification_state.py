"""Persist bounded Copilot clarification state for multi-turn configuration help."""

from __future__ import annotations


VERSION = 197
NAME = "ai_conversation_clarification_state"


def _columns(cursor, table: str) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]).lower() for row in rows}


def upgrade(cursor, use_pg: bool) -> None:
    """Add nullable-by-behaviour state storage without rewriting conversations."""

    existing = _columns(cursor, "ai_conversations")
    if not existing:
        return

    state_type = "JSONB" if use_pg else "TEXT"
    state_default = "'{}'::jsonb" if use_pg else "'{}'"
    definitions = {
        "clarification_state_json": f"{state_type} NOT NULL DEFAULT {state_default}",
        "clarification_state_version": "INTEGER NOT NULL DEFAULT 0",
        "clarification_updated_at": "TEXT",
    }
    for name, definition in definitions.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE ai_conversations ADD COLUMN {name} {definition}")


def downgrade(cursor, use_pg: bool) -> None:
    # Conversation state is intentionally retained during release rollback so
    # a running UI cannot lose its pending clarification after a restart.
    del cursor, use_pg
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
