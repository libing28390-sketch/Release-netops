"""Allow the metadata schema's P0/P1 rag priority labels."""

from __future__ import annotations

VERSION = 114
NAME = "rag_priority_text"


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        "ALTER TABLE ai_document ALTER COLUMN rag_priority TYPE TEXT USING rag_priority::text"
    )
    cursor.execute(
        "ALTER TABLE ai_document_chunk ALTER COLUMN rag_priority TYPE TEXT USING rag_priority::text"
    )


def downgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        "ALTER TABLE ai_document ALTER COLUMN rag_priority TYPE INTEGER "
        "USING CASE WHEN rag_priority ~ '^[0-9]+$' THEN rag_priority::integer ELSE NULL END"
    )
    cursor.execute(
        "ALTER TABLE ai_document_chunk ALTER COLUMN rag_priority TYPE INTEGER "
        "USING CASE WHEN rag_priority ~ '^[0-9]+$' THEN rag_priority::integer ELSE NULL END"
    )

