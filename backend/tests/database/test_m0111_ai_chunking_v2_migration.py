import sqlite3

from database.migrations import m0111_ai_chunking_v2


def test_chunking_v2_migration_is_idempotent_on_sqlite():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY,
            content_hash TEXT
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY,
            document_id TEXT,
            content TEXT,
            embedding TEXT
        );
        """
    )

    m0111_ai_chunking_v2.upgrade(conn.cursor(), use_pg=False)
    m0111_ai_chunking_v2.upgrade(conn.cursor(), use_pg=False)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_document_chunk)").fetchall()}

    assert {"parent_chunk_id", "chunk_role", "chunk_type", "embedding_content", "token_count", "content_hash"}.issubset(columns)
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(ai_document_chunk)").fetchall()}
    assert "ix_ai_doc_chunk_parent" in indexes
