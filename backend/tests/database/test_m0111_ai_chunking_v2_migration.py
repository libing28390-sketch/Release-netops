from backend.tests import pg_catalog_assertions as pg_catalog
from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations import m0111_ai_chunking_v2


def test_chunking_v2_migration_is_idempotent_on_postgresql():
    conn = postgresql_test_driver.connect()
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

    m0111_ai_chunking_v2.upgrade(conn.cursor(), use_pg=True)
    m0111_ai_chunking_v2.upgrade(conn.cursor(), use_pg=True)
    columns = pg_catalog.table_columns(conn, "ai_document_chunk")

    assert {"parent_chunk_id", "chunk_role", "chunk_type", "embedding_content", "token_count", "content_hash"}.issubset(columns)
    indexes = pg_catalog.index_names(conn, "ai_document_chunk")
    assert "ix_ai_doc_chunk_parent" in indexes
