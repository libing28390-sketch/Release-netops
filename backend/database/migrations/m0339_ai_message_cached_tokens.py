"""Persist provider cache accounting through the PostgreSQL migration lifecycle."""
VERSION = 339
NAME = "ai_message_cached_tokens"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        return
    cursor.execute("ALTER TABLE ai_messages ADD COLUMN IF NOT EXISTS cached_tokens INTEGER")
