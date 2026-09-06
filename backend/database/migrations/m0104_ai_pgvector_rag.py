"""Migration m0104: Enable pgvector extension (if PostgreSQL) and add vector index helpers."""

from __future__ import annotations

from database.postgres_extensions import ensure_required_extensions

VERSION = 104
NAME = "ai_pgvector_rag"


def upgrade(cursor, use_pg: bool) -> None:
    ensure_required_extensions(cursor, names=("vector", "pg_trgm"), create_missing=True)
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_doc_chunk_docid ON ai_document_chunk(document_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_agent_run_status ON ai_agent_run(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ai_agent_step_runid ON ai_agent_step(run_id)")
