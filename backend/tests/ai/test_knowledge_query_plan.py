from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ai.schemas.knowledge import KnowledgeQueryPlan, KnowledgeScope
from ai.services import assistant as assistant_module
from ai.services.assistant import AIAssistantService
from ai.services.knowledge_metadata import canonical_feature, canonical_vendor, normalize_facet_value
from ai.services.rag_policy import document_is_visible
from ai.services.rag_retriever import RAGRetriever, RetrievalRequest
from backend.tests.pg_test_utils import postgresql_test_driver


def test_query_plan_is_allowlisted_and_normalizes_shared_facets() -> None:
    plan = KnowledgeQueryPlan.from_sources(
        "华为 VLAN 配置",
        {
            "vendor": "华为",
            "protocol": "OSPF",
            "knowledgeScope": "OFFICIAL",
            "knowledge_directory_path": "kb_import/03_configuration/huawei",
            "ignored": "must not cross the plan boundary",
        },
        {"vendor": "思科", "directory_path": "stale/path"},
    )

    assert plan.vendor == "Huawei"
    assert plan.protocol == "ospf"
    assert plan.feature == "ospf"
    assert plan.knowledge_scope is KnowledgeScope.OFFICIAL
    assert plan.directory_path == "03_configuration/huawei"
    assert plan.keyword == "华为 VLAN 配置"
    assert "ignored" not in plan.model_dump()

    with pytest.raises(ValidationError):
        KnowledgeQueryPlan.model_validate(
            {"knowledge_scope": KnowledgeScope.ALL, "unknown_filter": "no"}
        )


def test_shared_facet_normalization_and_unknown_governance() -> None:
    assert canonical_vendor("新华三") == "H3C"
    assert canonical_vendor("思科系统") == "Cisco"
    assert canonical_feature("链路聚合") == "lacp"
    assert canonical_feature("packet-filter") == "acl"
    assert normalize_facet_value("UNKNOWN") == ""
    assert normalize_facet_value("华为") == "Huawei"


def test_assistant_builds_scope_and_directory_into_retrieval_request(monkeypatch: pytest.MonkeyPatch) -> None:
    resolver_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        assistant_module.product_resolver,
        "resolve_query",
        lambda *args, **kwargs: resolver_calls.append(kwargs) or assistant_module.EntityResolution(
            metadata={"vendor": "Huawei", "document_category": "configuration", "product_series": "CloudEngine 6800"}
        ),
    )

    request, _resolution = AIAssistantService.build_knowledge_request(
        "华为 VLAN 配置",
        {
            "knowledge_intent": {
                "vendor": "华为",
                "protocol": "VLAN",
                "document_scope": "official",
            }
        },
        tenant_id="tenant-a",
        user_id="operator-a",
        roles=["Operator"],
        context={"knowledge_directory_path": "03_configuration/huawei"},
    )

    assert request.vendor == "Huawei"
    assert request.feature == "vlan"
    assert request.knowledge_scope == "official"
    assert request.directory_path == "03_configuration/huawei"
    assert request.tenant_id == "tenant-a"
    assert request.roles == ["Operator"]
    assert resolver_calls[0]["tenant_id"] is None


def test_assistant_keeps_explicit_canonical_cli_platform_when_resolver_returns_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        assistant_module.product_resolver,
        "resolve_query",
        lambda *args, **kwargs: assistant_module.EntityResolution(
            metadata={
                "vendor": "Huawei",
                "cli_platform": "huawei_vrpv8",
                "document_category": "configuration",
            }
        ),
    )

    request, _resolution = AIAssistantService.build_knowledge_request(
        "华为 VRP VLAN 配置",
        {
            "knowledge_intent": {
                "vendor": "Huawei",
                "platform": "huawei_vrpv8",
                "feature": "vlan",
                "document_scope": "official",
            }
        },
    )

    assert request.cli_platform == "huawei_vrp"


def test_retrieval_ignores_legacy_tenant_scope_but_keeps_acl_in_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = postgresql_test_driver.connect()
    connection.executescript(
        """
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY,
            document_id TEXT,
            name TEXT,
            source TEXT,
            vendor TEXT,
            platform TEXT,
            tenant_id TEXT,
            status TEXT,
            acl_json JSONB,
            source_trust_level TEXT,
            knowledge_source_type TEXT,
            document_category TEXT,
            product_family TEXT,
            product_series TEXT,
            product_model TEXT,
            os_family TEXT,
            os_generation TEXT,
            software_train TEXT,
            software_release TEXT,
            cli_platform TEXT,
            feature_domain TEXT,
            feature TEXT,
            subfeature TEXT,
            metadata_json JSONB,
            exclude_from_rag INTEGER DEFAULT 0
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY,
            document_id TEXT,
            content TEXT,
            embedding JSONB,
            metadata_json JSONB,
            section TEXT
        );
        """
    )
    rows = [
        ("official", "tenant-a", "official_vendor", "{}", "03_configuration/huawei"),
        ("enterprise", "tenant-a", "internal_sop", '{"roles":["Operator"]}', "03_configuration/huawei"),
        ("other-tenant", "tenant-b", "official_vendor", "{}", "03_configuration/huawei"),
        ("admin-only", "tenant-a", "official_vendor", '{"roles":["Administrator"]}', "03_configuration/huawei"),
        ("wrong-directory", "tenant-a", "official_vendor", "{}", "01_product/huawei"),
    ]
    for doc_id, tenant_id, source_type, acl, path in rows:
        connection.execute(
            """
            INSERT INTO ai_document
              (id, document_id, name, source, vendor, platform, tenant_id, status,
               acl_json, source_trust_level, knowledge_source_type, document_category,
               product_series, cli_platform, feature, metadata_json)
            VALUES (?, ?, ?, 'local', 'Huawei', 'huawei_vrp', ?, 'active', ?,
                    'official', ?, 'configuration', 'CloudEngine 6800',
                    'huawei_vrp', 'vlan', ?)
            """,
            (
                doc_id,
                doc_id,
                doc_id,
                tenant_id,
                acl,
                source_type,
                json.dumps({"knowledge_directory_path": path}),
            ),
        )
        connection.execute(
            """
            INSERT INTO ai_document_chunk
              (id, document_id, content, embedding, metadata_json, section)
            VALUES (?, ?, ?, '[]'::jsonb, ?, 'VLAN')
            """,
            (
                f"chunk-{doc_id}",
                doc_id,
                f"vlan configuration evidence {doc_id}",
                json.dumps({"vendor": "Huawei", "feature": "vlan"}),
            ),
        )
    connection.commit()

    monkeypatch.setattr(assistant_module, "get_db_connection", lambda: connection, raising=False)
    import ai.services.rag_retriever as retriever_module

    monkeypatch.setattr(retriever_module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(retriever_module.embedding_provider, "embed_text", lambda _query: [])
    retriever = RAGRetriever()

    official = retriever.search(
        RetrievalRequest(
            query="Huawei VLAN",
            vendor="Huawei",
            product_series="CloudEngine 6800",
            document_category="configuration",
            feature="vlan",
            knowledge_scope="official",
            directory_path="03_configuration/huawei",
            tenant_id=None,
            roles=["Operator"],
        )
    )
    enterprise = retriever.search(
        RetrievalRequest(
            query="Huawei VLAN",
            vendor="Huawei",
            product_series="CloudEngine 6800",
            document_category="configuration",
            feature="vlan",
            knowledge_scope="enterprise",
            directory_path="03_configuration/huawei",
            tenant_id="tenant-a",
            roles=["Operator"],
        )
    )

    assert [item["storage_document_id"] for item in official["results"]] == ["official", "other-tenant"]
    assert [item["storage_document_id"] for item in enterprise["results"]] == ["enterprise"]
    assert "tenant_id" not in official["debug"]["metadata_filter"]
    assert document_is_visible(
        {"tenant_id": "tenant-history-a", "acl_json": '{"roles":["Operator"]}'},
        tenant_id="tenant-history-b",
        roles=["Operator"],
    ) is True
    assert document_is_visible(
        {"tenant_id": "tenant-a", "acl_json": '{"roles":["Administrator"]}'},
        tenant_id="tenant-history-b",
        roles=["Operator"],
    ) is False
    assert document_is_visible(
        {"tenant_id": "tenant-history-a", "acl_json": '{"users":["alice"]}'},
        tenant_id="tenant-history-b",
        user_id="alice",
    ) is True
    assert document_is_visible(
        {"tenant_id": "tenant-history-a", "acl_json": '{"sites":["site-a"]}'},
        tenant_id="tenant-history-b",
        site_ids=["site-a"],
    ) is True
    assert document_is_visible(
        {"tenant_id": "tenant-history-a", "acl_json": '{"sites":["site-a"]}'},
        tenant_id="tenant-history-b",
        site_ids=["site-b"],
    ) is False
    assert document_is_visible(
        {"tenant_id": "tenant-history-a", "acl_json": "not-json"},
        tenant_id="tenant-history-b",
        roles=["Administrator"],
    ) is False
    connection.close()


def test_retrieval_directory_filter_keeps_legacy_semantic_rows_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = postgresql_test_driver.connect()
    connection.executescript(
        """
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY,
            document_id TEXT,
            name TEXT,
            source TEXT,
            vendor TEXT,
            platform TEXT,
            tenant_id TEXT,
            status TEXT,
            acl_json JSONB,
            source_trust_level TEXT,
            knowledge_source_type TEXT,
            document_category TEXT,
            product_series TEXT,
            cli_platform TEXT,
            feature TEXT,
            metadata_json JSONB,
            exclude_from_rag INTEGER DEFAULT 0
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY,
            document_id TEXT,
            content TEXT,
            embedding JSONB,
            metadata_json JSONB,
            section TEXT
        );
        """
    )
    connection.execute(
        """
        INSERT INTO ai_document
          (id, document_id, name, source, vendor, platform, tenant_id, status,
           acl_json, source_trust_level, knowledge_source_type, document_category,
           product_series, cli_platform, feature, metadata_json)
        VALUES ('legacy', 'legacy', 'Legacy configuration', 'local', 'Huawei',
                'huawei_vrp', 'tenant-a', 'active', '{}', 'official',
                'official_local', 'configuration', 'CloudEngine 6800',
                'huawei_vrp', 'vlan', '{}')
        """
    )
    connection.execute(
        """
        INSERT INTO ai_document_chunk
          (id, document_id, content, embedding, metadata_json, section)
        VALUES ('chunk-legacy', 'legacy', 'Huawei VLAN configuration',
                '[]'::jsonb, '{}', 'VLAN')
        """
    )
    connection.commit()

    import ai.services.rag_retriever as retriever_module

    monkeypatch.setattr(retriever_module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(retriever_module.embedding_provider, "embed_text", lambda _query: [])

    result = RAGRetriever().search(
        RetrievalRequest(
            query="Huawei VLAN",
            vendor="Huawei",
            document_category="configuration",
            knowledge_scope="official",
            directory_path="03_configuration/huawei",
            tenant_id=None,
        )
    )

    assert [item["storage_document_id"] for item in result["results"]] == ["legacy"]
    connection.close()
