import importlib
import json
from backend.tests.pg_test_utils import postgresql_test_driver
import pytest


knowledge_service_module = importlib.import_module("ai.services.knowledge_service")
assistant_module = importlib.import_module("ai.api.assistant")


def _connection():
    connection = postgresql_test_driver.connect()
    connection.row_factory = postgresql_test_driver.Row
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
            product_family TEXT,
            product_series TEXT,
            product_model TEXT,
            os_family TEXT,
            software_release TEXT,
            feature_domain TEXT,
            document_category TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY,
            document_id TEXT,
            content TEXT,
            page INTEGER DEFAULT 1,
            section TEXT DEFAULT '',
            created_at TEXT DEFAULT ''
        );
        INSERT INTO ai_document (
            id, knowledge_base_id, name, source, vendor, platform, status,
            knowledge_source_type, tenant_id, acl_json, source_trust_level,
            metadata_json, product_family, product_series, product_model,
            os_family, software_release, feature_domain, document_category,
            created_at, updated_at
        ) VALUES
          ('doc-huawei', 'kb-a', 'Huawei OSPF', 'upload', 'Huawei', 'huawei_vrp', 'active', 'official_vendor', 'tenant-a', '{}', 'official', '{"knowledge_directory_path":"01_product/huawei"}', 'CloudEngine', 'CE6800', 'CE6885', 'VRP', 'V800R022', 'ospf', '01_product', '2026-08-17', '2026-08-17'),
          ('doc-cisco', 'kb-a', 'Cisco VLAN', 'upload', 'Cisco', 'cisco_ios_xe', 'active', 'internal_sop', 'tenant-a', '{}', 'internal', '{"knowledge_directory_path":"01_product/cisco"}', 'Catalyst', 'C9300', 'C9300-24P', 'IOS XE', '17.9', 'vlan', '02_commands', '2026-08-16', '2026-08-16'),
          ('doc-other-tenant', 'kb-a', 'Huawei Other Tenant', 'upload', 'Huawei', 'huawei_vrp', 'active', 'official_vendor', 'tenant-b', '{}', 'official', '{"knowledge_directory_path":"01_product/huawei"}', 'CloudEngine', 'CE6800', 'CE6885', 'VRP', 'V800R022', 'ospf', '01_product', '2026-08-15', '2026-08-15');
        INSERT INTO ai_document_chunk (id, document_id, content) VALUES ('chunk-huawei', 'doc-huawei', 'ospf evidence');
        INSERT INTO ai_document_chunk (id, document_id, content) VALUES ('chunk-cisco', 'doc-cisco', 'vlan evidence');
        """
    )
    return connection


def test_semantic_filters_are_server_side_and_tenant_scoped(monkeypatch):
    connection = _connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)

    result = knowledge_service_module.KnowledgeService().list_documents(
        tenant_id="tenant-a",
        vendor="Huawei",
        product_family="CloudEngine",
        product_model="CE6885",
        os_family="VRP",
        software_release="V800R022",
        feature_domain="ospf",
        document_category="01_product",
    )

    assert result["total"] == 1
    assert result["items"][0]["id"] == "doc-huawei"
    assert "kb_import" not in json.dumps(result, ensure_ascii=False)


def test_directory_category_alias_is_normalized_to_semantic_category(monkeypatch):
    connection = _connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)

    result = knowledge_service_module.KnowledgeService().list_documents(
        tenant_id="tenant-a",
        document_category="01_product",
    )

    assert result["total"] == 1
    assert result["items"][0]["document_category"] == "01_product"


def test_product_hierarchy_facets_are_bounded_and_tenant_scoped(monkeypatch):
    connection = _connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)

    facets = knowledge_service_module.KnowledgeService().list_document_facets(
        tenant_id="tenant-a",
        directory_path="01_product/huawei",
    )

    assert facets["vendors"] == [{"value": "Huawei", "count": 1}]
    assert facets["families"] == [{"value": "CloudEngine", "count": 1}]
    assert facets["series"] == [{"value": "CE6800", "count": 1}]
    assert "kb_import" not in json.dumps(facets, ensure_ascii=False)


def test_official_and_enterprise_scopes_are_server_side(monkeypatch):
    connection = _connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)
    service = knowledge_service_module.KnowledgeService()

    official = service.list_documents(tenant_id="tenant-a", knowledge_scope="official")
    enterprise = service.list_documents(tenant_id="tenant-a", knowledge_scope="enterprise")

    assert [item["id"] for item in official["items"]] == ["doc-huawei"]
    assert [item["id"] for item in enterprise["items"]] == ["doc-cisco"]


def test_official_scope_includes_governed_config_templates(monkeypatch):
    connection = _connection()
    connection.execute(
        """
        INSERT INTO ai_document (
            id, knowledge_base_id, name, source, vendor, platform, status,
            knowledge_source_type, tenant_id, acl_json, source_trust_level,
            metadata_json, product_family, product_series, product_model,
            os_family, software_release, feature_domain, document_category,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "doc-template", "kb-a", "Huawei VLAN template", "official", "Huawei", "huawei_vrp",
            "active", "official_template", "tenant-a", "{}", "official", "{}", "CloudEngine",
            "S5731", "S5731-H", "VRP", "V800R022", "vlan", "configuration", "2026-08-18", "2026-08-18",
        ),
    )
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)
    result = knowledge_service_module.KnowledgeService().list_documents(tenant_id="tenant-a", knowledge_scope="official")
    assert {item["id"] for item in result["items"]} == {"doc-huawei", "doc-template"}


def test_detail_contract_loads_body_source_and_explicit_version_history(monkeypatch):
    connection = _connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)

    detail = knowledge_service_module.KnowledgeService().get_document_detail("doc-huawei", tenant_id="tenant-a")

    assert detail is not None
    assert detail["raw_source"]["source"] == "upload"
    assert detail["source_version_history"] == []
    assert detail["chunks"][0]["content"] == "ospf evidence"


def test_unknown_semantic_column_fails_closed_without_sql_injection(monkeypatch):
    connection = _connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)

    result = knowledge_service_module.KnowledgeService().list_documents(
        tenant_id="tenant-a",
        product_model="' OR 1=1 --",
    )

    assert result["total"] == 0
    assert result["items"] == []


def test_document_contract_rejects_unknown_request_fields():
    with pytest.raises(Exception):
        assistant_module.KnowledgeDocumentCreateRequest(
            content="# safe",
            unexpected_raw_content="secret",
        )


def test_document_contract_clamps_chunk_size_and_requires_content():
    request = assistant_module.KnowledgeDocumentCreateRequest(content="# safe", chunk_size=512)
    assert request.chunk_size == 512
    with pytest.raises(Exception):
        assistant_module.KnowledgeDocumentCreateRequest(content="")
