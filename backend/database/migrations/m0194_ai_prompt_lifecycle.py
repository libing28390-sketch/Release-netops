"""Add immutable prompt lifecycle metadata used by the Prompt Center."""

from __future__ import annotations


VERSION = 194
NAME = "ai_prompt_lifecycle"


def _columns(cursor, table: str) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]).lower() for row in rows}


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    if not _columns(cursor, "ai_prompt_version"):
        raise RuntimeError("ai_prompt_lifecycle requires ai_prompt_version")

    existing = _columns(cursor, "ai_prompt_version")
    definitions = {
        "change_reason": "TEXT NOT NULL DEFAULT ''",
        "change_type": "TEXT NOT NULL DEFAULT 'update'",
        "restored_from_version": "INTEGER",
    }
    for name, definition in definitions.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE ai_prompt_version ADD COLUMN {name} {definition}")

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_prompt_version_lifecycle "
        "ON ai_prompt_version(prompt_id, change_type, version)"
    )


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
