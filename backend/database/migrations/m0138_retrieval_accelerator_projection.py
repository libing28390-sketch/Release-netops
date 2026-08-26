"""Additive retrieval accelerator projection for the current V1 tables.

The canonical DB-016 tables remain release-gated.  This migration gives the
existing ingestion/retrieval path nullable, versioned columns for PostgreSQL
FTS, pg_trgm and pgvector shadow reads without removing or changing V1 fields.
"""

from __future__ import annotations

from database.postgres_extensions import ensure_required_extensions

VERSION = 138
NAME = "retrieval_accelerator_projection"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]) for row in rows}
    rows = cursor.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _ensure_columns(cursor, table: str, definitions: dict[str, str], use_pg: bool) -> None:
    existing = _columns(cursor, table, use_pg)
    if not existing:
        return
    for name, definition in definitions.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    if use_pg:
        # PostgreSQL is the production authority for RET-008..010.  Fail
        # closed (with the shared actionable error) instead of silently
        # creating a text-only shadow path when the required extensions are
        # unavailable.  m0104 normally installs these first; the explicit
        # guard also protects databases upgraded from an incomplete history.
        ensure_required_extensions(
            cursor,
            use_pg=True,
            names=("vector", "pg_trgm"),
            create_missing=True,
        )
    _ensure_columns(
        cursor,
        "ai_document",
        {
            "fts_text": "TEXT",
            "retrieval_index_version": "TEXT DEFAULT 'retrieval-v1'",
        },
        use_pg,
    )
    _ensure_columns(
        cursor,
        "ai_document_chunk",
        {
            "search_text": "TEXT",
            "retrieval_index_version": "TEXT DEFAULT 'retrieval-v1'",
            "embedding_vector": "vector(1536)" if use_pg else "TEXT",
        },
        use_pg,
    )
    cursor.execute(
        "UPDATE ai_document SET fts_text = COALESCE(name, '') || ' ' || COALESCE(normalized_content, '') "
        "WHERE fts_text IS NULL"
    )
    cursor.execute(
        "UPDATE ai_document_chunk SET search_text = COALESCE(section, '') || ' ' || COALESCE(content, '') "
        "WHERE search_text IS NULL"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_doc_retrieval_version ON ai_document(tenant_id, status, retrieval_index_version)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_chunk_retrieval_version ON ai_document_chunk(document_id, retrieval_index_version)")
    if use_pg:
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_ai_chunk_search_fts "
            "ON ai_document_chunk USING GIN (to_tsvector('simple', COALESCE(search_text, '')))"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_ai_chunk_search_trgm "
            "ON ai_document_chunk USING GIN (search_text gin_trgm_ops)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_ai_chunk_embedding_vector_hnsw "
            "ON ai_document_chunk USING hnsw (embedding_vector vector_cosine_ops)"
        )
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_chunk_search_text ON ai_document_chunk(search_text)")


def downgrade(cursor, use_pg: bool) -> None:
    # The projection is additive and intentionally retained for rollback.  The
    # runtime feature flag can disable all accelerator stages safely.
    return None
