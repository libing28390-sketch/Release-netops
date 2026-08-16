"""Additive CHK contract projection for the legacy V1 chunk tables.

The canonical DB-010 graph tables remain gated for the later migration/cutover.
These columns let the current ingestion path persist explicit neighbour edges,
structure and version metadata without replacing or deleting V1 fields.
"""

from __future__ import annotations


VERSION = 137
NAME = "chunk_index_contract_projection"


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
            "chunker_version": "TEXT DEFAULT 'network-structure-v2'",
            "parser_version": "TEXT DEFAULT 'markdown-network-parser-v2'",
            "document_version": "TEXT DEFAULT 'unversioned'",
            "index_version": "TEXT DEFAULT 'index-pending'",
            "embedding_mode": "TEXT DEFAULT 'local'",
            "embedding_contract_version": "TEXT DEFAULT 'embedding-v1'",
        },
        use_pg,
    )
    _ensure_columns(
        cursor,
        "ai_document_chunk",
        {
            "chunker_version": "TEXT DEFAULT 'network-structure-v2'",
            "structure_types_json": "TEXT DEFAULT '[]'",
            "neighbor_chunk_ids_json": "TEXT DEFAULT '[]'",
            "parser_version": "TEXT DEFAULT 'markdown-network-parser-v2'",
            "document_version": "TEXT DEFAULT 'unversioned'",
            "index_version": "TEXT DEFAULT 'index-pending'",
            "embedding_mode": "TEXT DEFAULT 'local'",
            "embedding_contract_version": "TEXT DEFAULT 'embedding-v1'",
        },
        use_pg,
    )
    chunk_columns = _columns(cursor, "ai_document_chunk", use_pg)
    index_columns = ["document_id"]
    if "ordinal" in chunk_columns:
        index_columns.append("ordinal")
    if "chunk_role" in chunk_columns:
        index_columns.append("chunk_role")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_doc_chunk_neighbor_projection "
        f"ON ai_document_chunk({', '.join(index_columns)})"
    )


def downgrade(cursor, use_pg: bool) -> None:
    # Additive compatibility columns are intentionally retained for rollback;
    # removing them would discard evidence written by V2 and break old clients.
    return None
