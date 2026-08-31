import json
from backend.tests.pg_test_utils import postgresql_test_driver
from ai.services import knowledge_service as knowledge_service_module


def _connection() -> postgresql_test_driver.Connection:
    connection = postgresql_test_driver.connect()
    connection.executescript(
        """
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY,
            knowledge_base_id TEXT,
            name TEXT,
            source TEXT,
            vendor TEXT,
            platform TEXT,
            status TEXT,
            knowledge_source_type TEXT,
            tenant_id TEXT,
            acl_json TEXT,
            source_trust_level TEXT,
            metadata_json TEXT,
            normalized_content TEXT,
            content_hash TEXT,
            chunking_version TEXT,
            ingestion_status TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY,
            document_id TEXT,
            content TEXT,
            embedding TEXT,
            metadata_json TEXT,
            page INTEGER,
            section TEXT,
            created_at TEXT,
            parent_chunk_id TEXT,
            chunk_role TEXT,
            chunk_type TEXT,
            ordinal INTEGER,
            raw_content TEXT,
            embedding_content TEXT,
            heading_path_json TEXT,
            token_count INTEGER,
            content_hash TEXT,
            source_locator_json TEXT,
            chunking_version TEXT,
            is_retrieval_candidate INTEGER,
            oversize_reason TEXT
        );
        """
    )
    return connection


def test_add_document_persists_v2_parent_child_metadata(monkeypatch):
    connection = _connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(knowledge_service_module.embedding_provider, "dimensions", 2)
    monkeypatch.setattr(knowledge_service_module.embedding_provider, "embed_text", lambda text: [0.1, 0.2])

    service = knowledge_service_module.KnowledgeService()
    result = service.add_document_and_chunk(
        knowledge_base_id="kb-1",
        name="OSPF troubleshooting",
        content=(
            "# OSPF\n\n## Neighbor stuck in ExStart\n\n"
            "### Symptoms\nThe neighbor remains in ExStart.\n\n"
            "### Causes\nMTU mismatch.\n\n"
            "### Verification\n```h3c\ndisplay ospf peer\n```"
        ),
        vendor="H3C",
        platform="h3c_comware",
        metadata={"verified_version": "Comware 7"},
    )

    assert result["chunking_version"] == "v2"
    assert result["chunk_count"] >= 3
    rows = connection.execute(
        "SELECT chunk_role, chunk_type, parent_chunk_id, raw_content, embedding_content, heading_path_json "
        "FROM ai_document_chunk ORDER BY ordinal"
    ).fetchall()
    assert any(row[0] == "parent" for row in rows)
    children = [row for row in rows if row[0] == "child"]
    assert children
    assert all(row[2] for row in children)
    assert all("vendor: H3C" in row[4] for row in children)
    assert all(json.loads(row[5]) for row in rows)
