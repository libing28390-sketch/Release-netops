import importlib
import sqlite3


knowledge_service_module = importlib.import_module("ai.services.knowledge_service")


def _knowledge_connection():
    connection = sqlite3.connect(":memory:")
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
            created_at TEXT
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY,
            document_id TEXT,
            content TEXT
        );
        INSERT INTO ai_document VALUES
          ('doc-1', 'kb-1', 'Huawei OSPF', 'upload', 'Huawei', 'huawei_vrp', 'active', 'internal_sop', 'tenant-a', '{}', 'internal', '2026-08-03T00:00:00Z'),
          ('doc-2', 'kb-1', 'Cisco BGP', 'upload', 'Cisco', 'ios_xe', 'active', 'official_vendor', 'tenant-a', '{}', 'official', '2026-08-02T00:00:00Z'),
          ('doc-3', 'kb-1', 'Shared VLAN Standard', 'upload', 'all', 'all', 'active', 'internal_standard', 'tenant-default', '{}', 'internal', '2026-08-01T00:00:00Z'),
          ('doc-4', 'kb-1', 'Hidden Old Document', 'upload', 'Huawei', 'huawei_vrp', 'archived', 'internal_sop', 'tenant-a', '{}', 'internal', '2026-08-04T00:00:00Z');
        INSERT INTO ai_document_chunk VALUES
          ('chunk-1', 'doc-1', 'ospf'),
          ('chunk-2', 'doc-1', 'neighbor'),
          ('chunk-3', 'doc-2', 'bgp');
        """
    )
    return connection


def test_list_documents_filters_and_paginates_without_loading_all_rows(monkeypatch):
    connection = _knowledge_connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)

    result = knowledge_service_module.KnowledgeService().list_documents(
        knowledge_source_type="internal_sop",
        tenant_id="tenant-a",
        search="huawei",
        page=1,
        page_size=1,
    )

    assert result["total"] == 1
    assert result["page"] == 1
    assert result["page_size"] == 1
    assert result["total_pages"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["id"] == "doc-1"
    assert result["items"][0]["chunk_count"] == 2


def test_list_documents_includes_default_tenant_and_clamps_page(monkeypatch):
    connection = _knowledge_connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)

    result = knowledge_service_module.KnowledgeService().list_documents(
        tenant_id="tenant-a",
        page=99,
        page_size=2,
    )

    assert result["total"] == 3
    assert result["page"] == 2
    assert result["total_pages"] == 2
    assert [item["id"] for item in result["items"]] == ["doc-3"]
