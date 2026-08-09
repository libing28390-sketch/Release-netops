import sqlite3

from database.migrations import m0113_rag_metadata_v2


def _baseline():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY,
            metadata_json TEXT DEFAULT '{}',
            vendor TEXT,
            platform TEXT,
            status TEXT,
            tenant_id TEXT,
            normalized_content TEXT
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY,
            document_id TEXT,
            metadata_json TEXT DEFAULT '{}',
            content TEXT,
            embedding TEXT
        );
        INSERT INTO ai_document (id, metadata_json) VALUES ('doc-1', '{}');
        """
    )
    return conn


def test_upgrade_and_downgrade_are_additive_and_reversible():
    conn = _baseline()
    cursor = conn.cursor()
    m0113_rag_metadata_v2.upgrade(cursor, use_pg=False)
    conn.commit()
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(ai_document)").fetchall()}
    assert {"document_id", "document_category", "cli_platform", "metadata_parse_status", "embedding_model"} <= columns
    assert cursor.execute("SELECT COUNT(*) FROM ai_document").fetchone()[0] == 1
    assert cursor.execute("SELECT COUNT(*) FROM ai_knowledge_reindex_job").fetchone()[0] == 0

    m0113_rag_metadata_v2.downgrade(cursor, use_pg=False)
    conn.commit()
    columns_after = {row[1] for row in cursor.execute("PRAGMA table_info(ai_document)").fetchall()}
    assert "document_id" not in columns_after
    assert cursor.execute("SELECT COUNT(*) FROM ai_document").fetchone()[0] == 1

