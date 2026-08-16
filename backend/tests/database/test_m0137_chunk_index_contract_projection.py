import sqlite3

from database.migrations import m0137_chunk_index_contract_projection


def test_chk008_projection_is_idempotent_and_preserves_v1_columns():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE ai_document (id TEXT PRIMARY KEY, content TEXT);
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY,
            document_id TEXT,
            content TEXT,
            embedding TEXT,
            page INTEGER
        );
        """
    )

    cursor = conn.cursor()
    m0137_chunk_index_contract_projection.upgrade(cursor, use_pg=False)
    m0137_chunk_index_contract_projection.upgrade(cursor, use_pg=False)

    document_columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_document)").fetchall()}
    chunk_columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_document_chunk)").fetchall()}
    assert "content" in document_columns
    assert "embedding" in chunk_columns
    assert "page" in chunk_columns
    assert {
        "parser_version",
        "chunker_version",
        "document_version",
        "index_version",
        "embedding_mode",
        "embedding_contract_version",
    } <= document_columns
    assert {
        "structure_types_json",
        "chunker_version",
        "neighbor_chunk_ids_json",
        "parser_version",
        "document_version",
        "index_version",
        "embedding_mode",
        "embedding_contract_version",
    } <= chunk_columns
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(ai_document_chunk)").fetchall()}
    assert "ix_ai_doc_chunk_neighbor_projection" in indexes
