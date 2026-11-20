from backend.tests import pg_catalog_assertions as pg_catalog
from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations.m0138_retrieval_accelerator_projection import upgrade


def _connection():
    conn = postgresql_test_driver.connect()
    conn.executescript(
        """
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY, name TEXT, normalized_content TEXT,
            tenant_id TEXT, status TEXT
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY, document_id TEXT, content TEXT, section TEXT
        );
        INSERT INTO ai_document VALUES ('d1','OSPF guide','display ospf peer','t1','active');
        INSERT INTO ai_document_chunk VALUES ('c1','d1','display ospf peer','Command');
        """
    )
    return conn


def test_m0138_postgresql_upgrade_is_additive_and_idempotent():
    conn = _connection()
    upgrade(conn.cursor(), use_pg=True)
    conn.commit()
    upgrade(conn.cursor(), use_pg=True)
    conn.commit()

    columns = pg_catalog.table_columns(conn, "ai_document_chunk")
    assert {"search_text", "embedding_vector", "retrieval_index_version"} <= columns
    assert conn.execute("SELECT search_text FROM ai_document_chunk WHERE id='c1'").fetchone()[0] == "Command display ospf peer"
    indexes = pg_catalog.index_names(conn, "ai_document_chunk")
    assert {
        "ix_ai_chunk_search_fts",
        "ix_ai_chunk_search_trgm",
        "ix_ai_chunk_embedding_vector_hnsw",
    }.issubset(indexes)
