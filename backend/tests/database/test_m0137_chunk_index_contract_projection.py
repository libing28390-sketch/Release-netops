from backend.tests import pg_catalog_assertions as pg_catalog
from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations import m0137_chunk_index_contract_projection


def test_chk008_projection_is_idempotent_and_preserves_v1_columns():
    conn = postgresql_test_driver.connect()
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
    m0137_chunk_index_contract_projection.upgrade(cursor, use_pg=True)
    m0137_chunk_index_contract_projection.upgrade(cursor, use_pg=True)

    document_columns = pg_catalog.table_columns(conn, "ai_document")
    chunk_columns = pg_catalog.table_columns(conn, "ai_document_chunk")
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
    indexes = pg_catalog.index_names(conn, "ai_document_chunk")
    assert "ix_ai_doc_chunk_neighbor_projection" in indexes
