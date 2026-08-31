import json
from backend.tests.pg_test_utils import postgresql_test_driver
from ai.services import rag_retriever as rag_retriever_module


def test_v2_retrieval_excludes_parent_context_chunks(monkeypatch):
    connection = postgresql_test_driver.connect()
    connection.executescript(
        """
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY,
            name TEXT,
            vendor TEXT,
            platform TEXT,
            tenant_id TEXT,
            status TEXT,
            acl_json TEXT,
            source_trust_level TEXT
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY,
            document_id TEXT,
            content TEXT,
            embedding TEXT,
            metadata_json TEXT,
            section TEXT,
            created_at TEXT,
            is_retrieval_candidate INTEGER,
            chunk_role TEXT,
            parent_chunk_id TEXT
        );
        INSERT INTO ai_document VALUES ('doc-1', 'OSPF guide', 'H3C', 'h3c_comware', 'tenant-default', 'active', '{}', 'official');
        """
    )
    connection.executemany(
        "INSERT INTO ai_document_chunk VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("parent", "doc-1", "OSPF parent context", json.dumps([1.0, 0.0]), "{}", "OSPF", "2026-01-01", 0, "parent", None),
            ("child", "doc-1", "display ospf peer", json.dumps([1.0, 0.0]), "{}", "OSPF", "2026-01-02", 1, "child", "parent"),
        ],
    )
    monkeypatch.setattr(rag_retriever_module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(rag_retriever_module.embedding_provider, "embed_text", lambda text: [1.0, 0.0])

    results = rag_retriever_module.RAGRetriever().retrieve("display ospf peer", top_k=5)

    assert [result["chunk_id"] for result in results] == ["child"]
    assert results[0]["chunk_role"] == "child"
    assert results[0]["parent_chunk_id"] == "parent"
