"""Semantic vector column for bge-m3 (RAG refactor phase 3).

Adds nullable columns only -- on PostgreSQL that is a catalog change and does
not rewrite ``ai_document_chunk`` (DB-017: expand nullable -> backfill ->
validate -> index).  The vectors are filled by
``scripts/rag_index_maintenance.py backfill`` and by the ingestion path when
``AI_SEMANTIC_EMBEDDING_PROVIDER=sidecar``; the HNSW index is built by
``scripts/rag_index_maintenance.py build-index`` with CREATE INDEX
CONCURRENTLY, because a migration runs inside a transaction and a plain
CREATE INDEX would block writes on a large table.

Columns
-------
embedding_v2               halfvec(1024) (vector(1024) when pgvector < 0.7)
embedding_v2_model         e.g. ``bge-m3``
embedding_v2_version       e.g. ``bge-m3-int8-v1``; vectors from different
                           versions are never compared with each other
embedding_v2_content_hash  sha256 of the text that was embedded, so a chunk
                           whose text changed is detected as stale
embedding_v2_at            ISO timestamp of the embedding

The legacy ``embedding_vector vector(1536)`` column is left untouched until
the cleanup phase.
"""

from __future__ import annotations

import re

VERSION = 331
NAME = "rag_semantic_embedding_v2"

SEMANTIC_DIMENSIONS = 1024


def _pgvector_version(cursor) -> tuple[int, ...]:
    row = cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
    return tuple(int(part) for part in re.findall(r"\d+", str((row or [""])[0] or "")))[:3]


def vector_type(version: tuple[int, ...]) -> str:
    """halfvec halves storage and index size; it needs pgvector >= 0.7."""
    return f"halfvec({SEMANTIC_DIMENSIONS})" if version >= (0, 7) else f"vector({SEMANTIC_DIMENSIONS})"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        return
    from database.postgres_extensions import ensure_required_extensions

    ensure_required_extensions(cursor, names=("vector",), create_missing=True)
    column_type = vector_type(_pgvector_version(cursor))
    for statement in (
        f"ALTER TABLE ai_document_chunk ADD COLUMN IF NOT EXISTS embedding_v2 {column_type}",
        "ALTER TABLE ai_document_chunk ADD COLUMN IF NOT EXISTS embedding_v2_model TEXT",
        "ALTER TABLE ai_document_chunk ADD COLUMN IF NOT EXISTS embedding_v2_version TEXT",
        "ALTER TABLE ai_document_chunk ADD COLUMN IF NOT EXISTS embedding_v2_content_hash TEXT",
        "ALTER TABLE ai_document_chunk ADD COLUMN IF NOT EXISTS embedding_v2_at TEXT",
    ):
        cursor.execute(statement)


def downgrade(cursor, use_pg: bool) -> None:
    # Additive; kept for rollback.  AI_SEMANTIC_EMBEDDING_PROVIDER=none stops
    # writes and the retriever does not read the column unless configured.
    return None
