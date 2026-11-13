"""Add first-class RAG metadata and reindex job state.

This project uses the lightweight migration runner in ``database.migrations``
instead of Alembic.  The migration is additive, idempotent, and keeps the
source documents intact; only indexed metadata/chunks are rebuilt by the
separate reindex service.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

VERSION = 113
NAME = "rag_metadata_v2"


DOCUMENT_COLUMNS = {
    "document_id": "TEXT",
    "document_category": "TEXT",
    "product_family": "TEXT",
    "product_series": "TEXT",
    "product_model": "TEXT",
    "os_family": "TEXT",
    "os_generation": "TEXT",
    "software_train": "TEXT",
    "software_release": "TEXT",
    "cli_platform": "TEXT",
    "feature_domain": "TEXT",
    "feature": "TEXT",
    "subfeature": "TEXT",
    "risk_level": "TEXT",
    "verification_level": "TEXT",
    # Source metadata uses ordered labels such as P0/P1 as well as numeric
    # priorities; TEXT preserves both forms without coercion loss.
    "rag_priority": "TEXT",
    "metadata_parse_status": "TEXT DEFAULT 'missing'",
    "metadata_parse_error": "TEXT",
    "original_content": "TEXT",
    "exclude_from_rag": "INTEGER NOT NULL DEFAULT 0",
    "embedding_model": "TEXT",
    "embedding_dimensions": "INTEGER",
    "embedding_version": "TEXT",
}
CHUNK_COLUMNS = {
    "document_category": "TEXT",
    "vendor": "TEXT",
    "product_series": "TEXT",
    "product_model": "TEXT",
    "software_train": "TEXT",
    "software_release": "TEXT",
    "cli_platform": "TEXT",
    "feature_domain": "TEXT",
    "feature": "TEXT",
    "subfeature": "TEXT",
    "risk_level": "TEXT",
    "verification_level": "TEXT",
    "rag_priority": "TEXT",
    "chunk_index": "INTEGER",
    "embedding_model": "TEXT",
    "embedding_dimensions": "INTEGER",
    "embedding_version": "TEXT",
}


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    schema_clause = "table_schema = current_schema() AND " if use_pg else ""
    cursor.execute(
        f"SELECT column_name FROM information_schema.columns WHERE {schema_clause}table_name = ?",
        (table,),
    )
    return {str(row[0]) for row in cursor.fetchall()}



def _add_columns(cursor, table: str, definitions: dict[str, str], use_pg: bool) -> None:
    existing = _columns(cursor, table, use_pg)
    for name, definition in definitions.items():
        if name in existing:
            continue
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _normalise_existing_json(cursor) -> None:
    """Keep the JSONB conversion safe for legacy rows with malformed text."""
    cursor.execute("SELECT id, metadata_json FROM ai_document WHERE metadata_json IS NOT NULL")
    for row in cursor.fetchall():
        raw = row[1]
        if isinstance(raw, (dict, list)):
            continue
        try:
            json.loads(str(raw))
        except (TypeError, ValueError):
            # The original document is untouched; only the derived audit blob
            # is repaired so the typed JSON column can be created.
            cursor.execute("UPDATE ai_document SET metadata_json = ? WHERE id = ?", ("{}", row[0]))


def upgrade(cursor, use_pg: bool) -> None:
    _add_columns(cursor, "ai_document", DOCUMENT_COLUMNS, use_pg)
    _add_columns(cursor, "ai_document_chunk", CHUNK_COLUMNS, use_pg)

    _normalise_existing_json(cursor)
    # The baseline declared a TEXT default.  PostgreSQL validates a
    # column's default while changing its type, so clear it first and add
    # a typed JSONB default after the conversion.
    cursor.execute("ALTER TABLE ai_document ALTER COLUMN metadata_json DROP DEFAULT")
    cursor.execute(
        "ALTER TABLE ai_document ALTER COLUMN metadata_json TYPE JSONB "
        "USING COALESCE(NULLIF(metadata_json, ''), '{}')::jsonb"
    )
    cursor.execute("ALTER TABLE ai_document ALTER COLUMN metadata_json SET DEFAULT '{}'::jsonb")
    cursor.execute("ALTER TABLE ai_document_chunk ALTER COLUMN metadata_json DROP DEFAULT")
    cursor.execute(
        "ALTER TABLE ai_document_chunk ALTER COLUMN metadata_json TYPE JSONB "
        "USING COALESCE(NULLIF(metadata_json, ''), '{}')::jsonb"
    )
    cursor.execute("ALTER TABLE ai_document_chunk ALTER COLUMN metadata_json SET DEFAULT '{}'::jsonb")

    indexes = (
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_document_document_id "
        "ON ai_document(document_id) WHERE document_id IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_ai_document_vendor ON ai_document(vendor)",
        "CREATE INDEX IF NOT EXISTS ix_ai_document_category ON ai_document(document_category)",
        "CREATE INDEX IF NOT EXISTS ix_ai_document_cli_platform ON ai_document(cli_platform)",
        "CREATE INDEX IF NOT EXISTS ix_ai_document_train ON ai_document(software_train)",
        "CREATE INDEX IF NOT EXISTS ix_ai_document_feature ON ai_document(feature)",
        "CREATE INDEX IF NOT EXISTS ix_ai_document_status ON ai_document(status)",
        "CREATE INDEX IF NOT EXISTS ix_ai_document_chunk_document ON ai_document_chunk(document_id, chunk_index)",
    )
    for statement in indexes:
        cursor.execute(statement)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_document_metadata_gin "
        "ON ai_document USING GIN (metadata_json)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_document_chunk_metadata_gin "
        "ON ai_document_chunk USING GIN (metadata_json)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_knowledge_reindex_job (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            scope_json TEXT NOT NULL DEFAULT '{}',
            dry_run INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'queued',
            total INTEGER NOT NULL DEFAULT 0,
            parsed INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            updated INTEGER NOT NULL DEFAULT 0,
            rechunked INTEGER NOT NULL DEFAULT 0,
            embedding_success INTEGER NOT NULL DEFAULT 0,
            embedding_failed INTEGER NOT NULL DEFAULT 0,
            error_log_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_knowledge_reindex_job_status "
        "ON ai_knowledge_reindex_job(tenant_id, status, created_at)"
    )


def downgrade(cursor, use_pg: bool) -> None:
    """Reverse the additive schema change without touching document rows."""
    cursor.execute("DROP INDEX IF EXISTS ux_ai_document_document_id")
    for name in (
        "ix_ai_document_vendor", "ix_ai_document_category", "ix_ai_document_cli_platform",
        "ix_ai_document_train", "ix_ai_document_feature", "ix_ai_document_status",
        "ix_ai_document_chunk_document", "ix_ai_document_metadata_gin",
        "ix_ai_document_chunk_metadata_gin", "ix_ai_document_metadata_text",
        "ix_ai_knowledge_reindex_job_status",
    ):
        cursor.execute(f"DROP INDEX IF EXISTS {name}")
    cursor.execute("DROP TABLE IF EXISTS ai_knowledge_reindex_job")
    cursor.execute(
        "ALTER TABLE ai_document ALTER COLUMN metadata_json TYPE TEXT USING metadata_json::text"
    )
    cursor.execute(
        "ALTER TABLE ai_document_chunk ALTER COLUMN metadata_json TYPE TEXT USING metadata_json::text"
    )
    # PostgreSQL and modern SQLite support DROP COLUMN.  Best-effort is used
    # for old SQLite runtimes where the baseline schema remains usable.
    for table, names in (("ai_document", DOCUMENT_COLUMNS), ("ai_document_chunk", CHUNK_COLUMNS)):
        for name in names:
            try:
                cursor.execute(f"ALTER TABLE {table} DROP COLUMN {name}")
            except Exception:
                continue
