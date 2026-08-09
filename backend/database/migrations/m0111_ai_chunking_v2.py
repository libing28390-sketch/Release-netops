"""Add additive metadata needed by the V2 knowledge chunking pipeline.

The migration deliberately keeps the existing ``content`` and JSON embedding
columns.  V2 can be written alongside the old representation and read back by
older API clients while the new retrieval path is evaluated in shadow mode.
"""

from __future__ import annotations

VERSION = 111
NAME = "ai_chunking_v2"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    try:
        if use_pg:
            rows = cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = ?",
                (table,),
            ).fetchall()
            return {str(row[0]) for row in rows}
        rows = cursor.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(row[1]) for row in rows}
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
    _ensure_columns(
        cursor,
        "ai_document",
        {
            "normalized_content": "TEXT",
            "content_hash": "TEXT",
            "chunking_version": "TEXT DEFAULT 'v1'",
            "ingestion_status": "TEXT DEFAULT 'ready'",
        },
        use_pg,
    )
    _ensure_columns(
        cursor,
        "ai_document_chunk",
        {
            "parent_chunk_id": "TEXT",
            "chunk_role": "TEXT DEFAULT 'standalone'",
            "chunk_type": "TEXT DEFAULT 'concept'",
            "ordinal": "INTEGER DEFAULT 0",
            "raw_content": "TEXT",
            "embedding_content": "TEXT",
            "heading_path_json": "TEXT DEFAULT '[]'",
            "token_count": "INTEGER DEFAULT 0",
            "content_hash": "TEXT",
            "source_locator_json": "TEXT DEFAULT '{}'",
            "chunking_version": "TEXT DEFAULT 'v2'",
            "is_retrieval_candidate": "INTEGER DEFAULT 1",
            "oversize_reason": "TEXT",
        },
        use_pg,
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_doc_chunk_parent "
        "ON ai_document_chunk(document_id, parent_chunk_id, ordinal)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_doc_chunk_type "
        "ON ai_document_chunk(document_id, chunk_role, chunk_type, is_retrieval_candidate)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_document_content_hash "
        "ON ai_document(content_hash)"
    )
