import sqlite3

from database.migrations.m0138_retrieval_accelerator_projection import upgrade


def _connection():
    conn = sqlite3.connect(":memory:")
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


def test_m0138_sqlite_upgrade_is_additive_and_idempotent():
    conn = _connection()
    upgrade(conn.cursor(), use_pg=False)
    conn.commit()
    upgrade(conn.cursor(), use_pg=False)
    conn.commit()

    columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_document_chunk)")}
    assert {"search_text", "embedding_vector", "retrieval_index_version"} <= columns
    assert conn.execute("SELECT search_text FROM ai_document_chunk WHERE id='c1'").fetchone()[0] == "Command display ospf peer"
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='ix_ai_chunk_search_text'").fetchone()[0] == 1

