"""Record whether message token usage came from the provider or an estimate."""

from __future__ import annotations

VERSION = 169
NAME = "ai_message_token_source"


def upgrade(cursor, use_pg: bool) -> None:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        ("ai_messages",),
    ).fetchall()
    columns = {str(row[0]) for row in rows}
    if columns and "token_source" not in columns:
        cursor.execute("ALTER TABLE ai_messages ADD COLUMN token_source TEXT")
    cursor.execute(
        "UPDATE ai_messages SET token_source = 'local_zero' "
        "WHERE execution_mode IN ('local_knowledge', 'local_operation') "
        "AND input_tokens = 0 AND output_tokens = 0 AND token_source IS NULL"
    )


def downgrade(cursor, use_pg: bool) -> None:
    return None
