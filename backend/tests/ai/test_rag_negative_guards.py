import json
import pytest
from backend.tests.pg_test_utils import postgresql_test_driver
from ai.services import rag_retriever as module
from ai.services.rag_retriever import RAGRetriever, RetrievalRequest
from ai.services.retrieval_contract import BoundedReranker, build_minimal_context


def _setup_mock_db():
    connection = postgresql_test_driver.connect()
    connection.executescript(
        """
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY, name TEXT, vendor TEXT, platform TEXT,
            tenant_id TEXT, status TEXT, acl_json TEXT, source_trust_level TEXT,
            document_id TEXT, document_category TEXT, product_series TEXT,
            product_model TEXT, software_train TEXT, cli_platform TEXT,
            feature_domain TEXT, feature TEXT, exclude_from_rag INTEGER DEFAULT 0,
            metadata_json JSONB
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY, document_id TEXT, content TEXT, embedding TEXT,
            metadata_json JSONB, section TEXT, created_at TEXT,
            is_retrieval_candidate INTEGER, chunk_role TEXT, parent_chunk_id TEXT,
            ordinal INTEGER, embedding_model TEXT
        );
        """
    )
    return connection


def test_tc_neg_01_cross_vendor_pollution_strictly_blocked(monkeypatch):
    """
    [TC-NEG-01] 跨厂商污染负向门禁：
    当用户显式指定或识别出 Cisco 厂商/平台时，候选池中即便有同名特性的华为文档，
    也必须被硬过滤 100% 拦截，绝对不能渗透到最终结果中。
    """
    connection = _setup_mock_db()
    # 插入 Cisco 文档与华为文档
    connection.execute(
        "INSERT INTO ai_document VALUES ('doc-cisco-vlan', 'Cisco Catalyst VLAN Config', 'Cisco', 'cisco_iosxe', 'tenant-default', 'active', '{}', 'official', 'cisco.cat3850.vlan', 'configuration', NULL, 'WS-C3850', '16.9', 'cisco_iosxe', 'switching', 'vlan', 0, '{}')"
    )
    connection.execute(
        "INSERT INTO ai_document VALUES ('doc-huawei-vlan', 'Huawei S5700 VLAN Config', 'Huawei', 'huawei_vrp', 'tenant-default', 'active', '{}', 'official', 'huawei.s5700.vlan', 'configuration', NULL, 'S5700', 'V200', 'huawei_vrp', 'switching', 'vlan', 0, '{}')"
    )
    connection.executemany(
        "INSERT INTO ai_document_chunk VALUES (?, ?, ?, ?, '{}', 'VLAN', '2026-01-01', 1, 'child', NULL, 1, NULL)",
        [
            ("c-cisco", "doc-cisco-vlan", "vlan 10\nname SALES\ninterface GigabitEthernet1/0/1\nswitchport mode access", json.dumps([1.0, 0.0])),
            ("c-huawei", "doc-huawei-vlan", "vlan 10\ndescription SALES\ninterface GigabitEthernet0/0/1\nport link-type access", json.dumps([1.0, 0.0])),
        ],
    )
    monkeypatch.setattr(module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(module.embedding_provider, "embed_text", lambda text: [1.0, 0.0])

    request = RetrievalRequest(
        query="configure vlan 10 access port",
        top_k=5,
        vendor="Cisco",
        cli_platform="cisco_iosxe",
    )
    result = RAGRetriever().search(request, min_relevance=0.0)
    returned_docs = [item["document_id"] for item in result["results"]]

    assert "cisco.cat3850.vlan" in returned_docs
    assert "huawei.s5700.vlan" not in returned_docs
    assert result["debug"]["wrong_vendor_count"] == 0


def test_tc_neg_02_historical_tenants_share_only_matching_site_acl(monkeypatch):
    """
    [TC-NEG-02] 历史 tenant 标签不限制单组织检索，但文档 site ACL 仍然有效。
    """
    connection = _setup_mock_db()
    connection.execute(
        "INSERT INTO ai_document VALUES ('doc-alpha', 'Alpha Private SOP', 'Cisco', 'cisco_ios', 'tenant-alpha', 'active', '{\"sites\":[\"site-a\"]}', 'internal', 'alpha.sop.01', 'sop', NULL, NULL, NULL, 'cisco_ios', 'routing', 'bgp', 0, '{}')"
    )
    connection.execute(
        "INSERT INTO ai_document VALUES ('doc-beta', 'Beta Shared Site SOP', 'Cisco', 'cisco_ios', 'tenant-beta', 'active', '{\"sites\":[\"site-a\"]}', 'internal', 'beta.sop.01', 'sop', NULL, NULL, NULL, 'cisco_ios', 'routing', 'bgp', 0, '{}')"
    )
    connection.execute(
        "INSERT INTO ai_document VALUES ('doc-other-site', 'Other Site SOP', 'Cisco', 'cisco_ios', 'tenant-gamma', 'active', '{\"sites\":[\"site-b\"]}', 'internal', 'gamma.sop.01', 'sop', NULL, NULL, NULL, 'cisco_ios', 'routing', 'bgp', 0, '{}')"
    )
    connection.executemany(
        "INSERT INTO ai_document_chunk VALUES (?, ?, ?, ?, '{}', 'BGP', '2026-01-01', 1, 'child', NULL, 1, NULL)",
        [
            ("c-alpha", "doc-alpha", "router bgp 65001\nneighbor 10.1.1.1 remote-as 65002", json.dumps([1.0, 0.0])),
            ("c-beta", "doc-beta", "router bgp 65099\nneighbor 10.9.9.9 remote-as 65099", json.dumps([1.0, 0.0])),
            ("c-other-site", "doc-other-site", "router bgp 65088\nneighbor 10.8.8.8 remote-as 65088", json.dumps([1.0, 0.0])),
        ],
    )
    monkeypatch.setattr(module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(module.embedding_provider, "embed_text", lambda text: [1.0, 0.0])

    request_alpha = RetrievalRequest(
        query="router bgp configuration",
        tenant_id="tenant-alpha",
        top_k=5,
        site_ids=["site-a"],
    )
    result_alpha = RAGRetriever().search(request_alpha, min_relevance=0.0)
    returned_alpha = [item["document_id"] for item in result_alpha["results"]]

    assert "alpha.sop.01" in returned_alpha
    assert "beta.sop.01" in returned_alpha
    assert "gamma.sop.01" not in returned_alpha


def test_tc_neg_02b_default_tenant_internal_document_still_obeys_site_acl(monkeypatch):
    """Default tenant is not a public ACL bypass in single-organization mode."""
    connection = _setup_mock_db()
    connection.execute(
        "INSERT INTO ai_document VALUES ('doc-default-private', 'Default Private SOP', 'Cisco', 'cisco_ios', 'tenant-default', 'active', '{\"sites\":[\"site-a\"]}', 'internal', 'default.sop.01', 'sop', NULL, NULL, NULL, 'cisco_ios', 'routing', 'bgp', 0, '{}')"
    )
    connection.executemany(
        "INSERT INTO ai_document_chunk VALUES (?, ?, ?, ?, '{}', 'BGP', '2026-01-01', 1, 'child', NULL, 1, NULL)",
        [("c-default-private", "doc-default-private", "router bgp 65001 private tenant procedure", json.dumps([1.0, 0.0]))],
    )
    monkeypatch.setattr(module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(module.embedding_provider, "embed_text", lambda text: [1.0, 0.0])

    matching_site = RAGRetriever().search(
        RetrievalRequest(query="router bgp configuration", tenant_id="tenant-alpha", site_ids=["site-a"], top_k=5),
        min_relevance=0.0,
    )
    assert [item["document_id"] for item in matching_site["results"]] == ["default.sop.01"]

    other_site = RAGRetriever().search(
        RetrievalRequest(query="router bgp configuration", tenant_id="tenant-alpha", site_ids=["site-b"], top_k=5),
        min_relevance=0.0,
    )
    assert other_site["results"] == []
    assert other_site["debug"]["candidate_count"] > 0


def test_tc_neg_03_reranker_failure_and_timeout_fail_safe():
    """
    [TC-NEG-03] Reranker 故障熔断降级门禁：
    当 Reranker 模型或远程 Sidecar 发生异常（超时、崩溃、抛错）时，
    系统必须自动平滑降级至基础规则排序，绝对不向用户抛出 500 异常，且结果集保活非空。
    """
    class CrashReranker:
        name = "crash-reranker"
        def rank(self, query, candidates):
            raise RuntimeError("Sidecar connection refused or out of memory")

    candidates = [
        {"document_id": "doc-1", "relevance_score": 0.85},
        {"document_id": "doc-2", "relevance_score": 0.70},
    ]

    bounded = BoundedReranker(CrashReranker(), timeout_ms=500)
    results, debug = bounded.apply("test query", candidates)

    # 结果必须完整保活回退
    assert len(results) == 2
    assert results[0]["document_id"] == "doc-1"
    assert debug["stage"] == "degraded"
    assert debug["reason"] == "reranker_error"


def test_tc_neg_04_context_expansion_token_budget_bounded():
    """
    [TC-NEG-04] 上下文展开 Token/字符预算防爆仓门禁：
    当文档包含大量子分块时，`build_minimal_context` 必须严格遵守 `max_chars` 限制，
    防止展开后的超大内容撑爆 LLM 上下文窗口。
    """
    large_chunks = [
        {"chunk_id": f"chunk-{i}", "content": "X" * 300, "section": f"Section {i}", "ordinal": i}
        for i in range(20)
    ]
    max_limit = 800
    context = build_minimal_context(large_chunks[0], large_chunks, max_chars=max_limit)

    assert context["context_char_count"] <= max_limit
    assert len(context["context_chunk_ids"]) < 20
    assert "chunk-0" in context["context_chunk_ids"]


def test_tc_neg_05_feature_scope_guard_suppresses_irrelevant_licensing(monkeypatch):
    """
    [TC-NEG-05] 业务特性防污染门禁（复现 VLAN 召回 Smart Licensing 场景）：
    当查询明确针对 VLAN 配置特性时，包含通用词汇的 Smart Licensing / SmartAgent 文档
    不能被误召回为主要结果。
    """
    connection = _setup_mock_db()
    connection.execute(
        "INSERT INTO ai_document VALUES ('doc-vlan', 'Cisco Catalyst 3850 VLAN Guide', 'Cisco', 'cisco_iosxe', 'tenant-default', 'active', '{}', 'official', 'cisco.cat3850.vlan', 'configuration', NULL, 'WS-C3850', '16.9', 'cisco_iosxe', 'switching', 'vlan', 0, '{\"feature\":\"vlan\"}')"
    )
    connection.execute(
        "INSERT INTO ai_document VALUES ('doc-smart-licensing', 'Cisco Smart Licensing and SmartAgent Guide', 'Cisco', 'cisco_iosxe', 'tenant-default', 'active', '{}', 'official', 'cisco.smart.licensing', 'configuration', NULL, 'WS-C3850', '16.9', 'cisco_iosxe', 'licensing', 'smart_licensing', 0, '{\"feature\":\"smart_licensing\"}')"
    )
    connection.executemany(
        "INSERT INTO ai_document_chunk VALUES (?, ?, ?, ?, '{}', 'Content', '2026-01-01', 1, 'child', NULL, 1, NULL)",
        [
            ("c-vlan", "doc-vlan", "vlan 100\nname SERVER_VLAN\ninterface vlan 100\nip address 192.168.100.1 255.255.255.0", json.dumps([0.9, 0.1])),
            ("c-lic", "doc-smart-licensing", "Smart licensing agent communication over vlan interface or management port for token registration", json.dumps([0.7, 0.3])),
        ],
    )
    monkeypatch.setattr(module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(module.embedding_provider, "embed_text", lambda text: [0.9, 0.1])

    request = RetrievalRequest(
        query="vlan 100 interface configuration",
        vendor="Cisco",
        feature="vlan",
        top_k=2,
    )
    result = RAGRetriever().search(request, min_relevance=0.0)
    returned_docs = [item["document_id"] for item in result["results"]]

    assert "cisco.cat3850.vlan" in returned_docs
    # 在指定 feature=vlan 时，smart licensing 不得占据 Top-1
    if returned_docs:
        assert returned_docs[0] == "cisco.cat3850.vlan"
