import json
from backend.tests.pg_test_utils import postgresql_test_driver
from ai.services import rag_retriever as module
from ai.services.rag_retriever import RAGRetriever, RetrievalRequest


def test_metadata_hard_filter_and_document_dedup(monkeypatch):
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
            is_retrieval_candidate INTEGER, chunk_role TEXT, parent_chunk_id TEXT
        );
        """
    )
    docs = [
        ("d1", "Huawei V600 OSPF", "Huawei", "huawei_yunshan_v600", "huawei.yunshan.v600", "command", "V600", "huawei_yunshan_v600", "routing", "ospf"),
        ("d2", "Huawei V300 OSPF", "Huawei", "huawei_yunshan_v300", "huawei.yunshan.v300", "command", "V300", "huawei_yunshan_v300", "routing", "ospf"),
    ]
    for row in docs:
        d_id, name, vendor, platform, semantic_id, category, train, cli, domain, feature = row
        connection.execute(
            "INSERT INTO ai_document VALUES (?, ?, ?, ?, 'tenant-default', 'active', '{}', 'official', ?, ?, NULL, NULL, ?, ?, ?, ?, 0, '{}')",
            (d_id, name, vendor, platform, semantic_id, category, train, cli, domain, feature),
        )
    connection.executemany(
        "INSERT INTO ai_document_chunk VALUES (?, ?, ?, ?, '{}', 'OSPF', ?, 1, 'child', NULL)",
        [("c1", "d1", "display ospf peer", json.dumps([1.0, 0.0]), "2026-01-01"), ("c2", "d1", "OSPF verification", json.dumps([1.0, 0.0]), "2026-01-02"), ("c3", "d2", "display ospf peer", json.dumps([1.0, 0.0]), "2026-01-03")],
    )
    monkeypatch.setattr(module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(module.embedding_provider, "embed_text", lambda text: [1.0, 0.0])

    request = RetrievalRequest(
        query="display ospf peer",
        top_k=5,
        vendor="Huawei",
        document_category="command",
        feature_domain="routing",
        feature="ospf",
        cli_platform="huawei_yunshan_v300",
    )
    result = RAGRetriever().search(request, min_relevance=0.0)
    assert [item["document_id"] for item in result["results"]] == ["huawei.yunshan.v300"]
    assert result["debug"]["candidate_count"] == 1
    assert result["debug"]["dedup_document_count"] == 1


def test_cosine_does_not_give_orthogonal_vectors_false_relevance():
    assert RAGRetriever._cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert RAGRetriever._cosine([1.0, 0.0], [1.0, 0.0]) == 1.0


def test_exact_command_ranking_expands_sibling_configuration_context(monkeypatch):
    connection = postgresql_test_driver.connect()
    connection.executescript(
        """
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY, name TEXT, vendor TEXT, platform TEXT,
            tenant_id TEXT, status TEXT, acl_json TEXT, source_trust_level TEXT,
            document_id TEXT, document_category TEXT, cli_platform TEXT,
            exclude_from_rag INTEGER DEFAULT 0, metadata_json JSONB
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY, document_id TEXT, content TEXT, embedding TEXT,
            metadata_json JSONB, section TEXT, created_at TEXT,
            is_retrieval_candidate INTEGER, chunk_role TEXT, parent_chunk_id TEXT,
            ordinal INTEGER, embedding_model TEXT
        );
        INSERT INTO ai_document VALUES (
            'vlan-doc', 'huawei.vrp5.v200.vlan_access.configuration', 'Huawei',
            'huawei_vrp5_v200', 'tenant-default', 'active', '{}', 'official',
            'huawei.vrp5.v200.vlan_access.configuration', 'configuration',
            'huawei_vrp5_v200', 0, '{"feature":"vlan","keywords":["VLAN access"]}'
        );
        """
    )
    connection.executemany(
        "INSERT INTO ai_document_chunk VALUES (?, 'vlan-doc', ?, ?, ?, ?, '2026-01-01', 1, 'child', NULL, ?, NULL)",
        [
            ("semantics", "Platform Configuration Semantics", json.dumps([1.0, 0.0]), '{"feature":"vlan"}', "Platform Semantics", 2),
            ("skeleton", "system-view\nvlan <VLAN_ID>\ninterface <INTERFACE>", json.dumps([0.0, 1.0]), '{"feature":"vlan"}', "配置骨架", 1),
        ],
    )
    monkeypatch.setattr(module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(module.embedding_provider, "embed_text", lambda text: [1.0, 0.0])

    result = RAGRetriever().search(
        RetrievalRequest(query="VLAN access config", document_category="configuration", top_k=1),
        min_relevance=0.0,
    )
    assert len(result["results"]) == 1
    assert "system-view" in result["results"][0]["content"]
    assert "Platform Configuration Semantics" in result["results"][0]["content"]
    assert result["results"][0]["context_chunk_count"] == 2


def test_all_metadata_eligible_chunks_are_scored_before_top_k(monkeypatch):
    connection = postgresql_test_driver.connect()
    connection.executescript(
        """
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY, name TEXT, vendor TEXT, platform TEXT,
            tenant_id TEXT, status TEXT, acl_json TEXT, source_trust_level TEXT,
            document_id TEXT, document_category TEXT, exclude_from_rag INTEGER DEFAULT 0
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY, document_id TEXT, content TEXT, embedding TEXT,
            metadata_json JSONB, section TEXT, created_at TEXT,
            is_retrieval_candidate INTEGER, chunk_role TEXT, parent_chunk_id TEXT
        );
        """
    )
    for index in range(125):
        doc_id = f"doc-{index:03d}"
        connection.execute(
            "INSERT INTO ai_document VALUES (?, ?, 'Huawei', NULL, 'tenant-default', 'active', '{}', 'official', ?, 'command', 0)",
            (doc_id, doc_id, doc_id),
        )
        connection.execute(
            "INSERT INTO ai_document_chunk VALUES (?, ?, ?, ?, '{}', 'General', '2026-01-01', 1, 'child', NULL)",
            (f"chunk-{index:03d}", doc_id, f"term-{index}", json.dumps([1.0, 0.0])),
        )
    monkeypatch.setattr(module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(module.embedding_provider, "embed_text", lambda text: [1.0, 0.0])

    result = RAGRetriever().search(RetrievalRequest(query="term-124", top_k=1), min_relevance=0.0)
    assert result["debug"]["candidate_count"] == 125
    assert result["debug"]["vector_top_n"] == 125
    assert result["results"][0]["document_id"] == "doc-124"


def test_official_broad_document_requires_chunk_feature_evidence(monkeypatch):
    connection = postgresql_test_driver.connect()
    connection.executescript(
        """
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY, name TEXT, source TEXT, vendor TEXT, platform TEXT,
            tenant_id TEXT, status TEXT, acl_json TEXT, source_trust_level TEXT,
            knowledge_source_type TEXT, document_id TEXT, document_category TEXT,
            cli_platform TEXT, feature_domain TEXT, feature TEXT,
            exclude_from_rag INTEGER DEFAULT 0, metadata_json JSONB
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY, document_id TEXT, content TEXT, embedding TEXT,
            metadata_json JSONB, section TEXT, created_at TEXT,
            is_retrieval_candidate INTEGER, chunk_role TEXT, parent_chunk_id TEXT,
            ordinal INTEGER
        );
        """
    )
    connection.execute(
        """
        INSERT INTO ai_document
            (id, name, source, vendor, platform, tenant_id, status, acl_json,
             source_trust_level, knowledge_source_type, document_id,
             document_category, cli_platform, feature_domain, feature,
             exclude_from_rag, metadata_json)
        VALUES
            ('bad', 'Catalyst System Management Command Reference',
             'https://www.cisco.com/c/en/system_management_commands.html',
             'Cisco', 'cisco_iosxe', 'tenant-default', 'active', '{}', 'official',
             'official_url', 'bad-semantic-id', 'command', 'cisco_iosxe',
             'switching', 'vlan', 0, '{}'),
            ('good', 'Cisco VLAN Access Commands',
             'https://www.cisco.com/c/en/vlan_access_commands.html',
             'Cisco', 'cisco_iosxe', 'tenant-default', 'active', '{}', 'official',
             'official_url', 'good-semantic-id', 'command', 'cisco_iosxe',
             'switching', 'vlan', 0, '{}')
        """
    )
    connection.executemany(
        """
        INSERT INTO ai_document_chunk
            (id, document_id, content, embedding, metadata_json, section,
             created_at, is_retrieval_candidate, chunk_role, parent_chunk_id,
             ordinal)
        VALUES (?, ?, ?, ?, ?, ?, '2026-09-01', 1, 'child', NULL, ?)
        """,
        [
            (
                "bad-chunk",
                "bad",
                "show license tech support\nSmartAgentIndividualRUMEncrypt: 2",
                json.dumps([1.0, 0.0]),
                json.dumps({
                    "feature": "vlan",
                    "source_kind": "command_reference",
                    "source_type": "official_url",
                    "title": "Catalyst System Management Command Reference",
                    "canonical_url": "https://www.cisco.com/c/en/system_management_commands.html",
                }),
                "show flow monitor FLOW-MONITOR-1",
                1,
            ),
            (
                "good-chunk",
                "good",
                "show vlan brief\nswitchport mode access",
                json.dumps([1.0, 0.0]),
                json.dumps({
                    "feature": "vlan",
                    "feature_source": "title_or_url",
                    "source_kind": "command_reference",
                    "source_type": "official_url",
                    "title": "Cisco VLAN Access Commands",
                    "canonical_url": "https://www.cisco.com/c/en/vlan_access_commands.html",
                }),
                "VLAN access commands",
                1,
            ),
        ],
    )
    monkeypatch.setattr(module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(module.embedding_provider, "embed_text", lambda text: [1.0, 0.0])

    result = RAGRetriever().search(
        RetrievalRequest(
            query="VLAN / Access / Trunk",
            top_k=5,
            vendor="Cisco",
            document_category="command",
            feature_domain="switching",
            feature="vlan",
            cli_platform="cisco_iosxe",
        ),
        min_relevance=0.0,
    )

    assert [item["storage_document_id"] for item in result["results"]] == ["good"]
    assert result["debug"]["candidate_count"] == 2
    assert result["debug"]["feature_scope_filtered"] == 1
    assert not RAGRetriever._feature_scope_is_eligible(
        "vlan",
        {
            "feature": "vlan",
            "feature_source": "title_or_url",
            "source_kind": "command_reference",
            "source_type": "official_url",
        },
        content="show license tech support",
        section="System management",
        document_name="Cisco VLAN commands",
    )
    assert RAGRetriever._feature_scope_is_eligible(
        "vlan",
        {
            "feature": "vlan",
            "feature_source": "explicit",
            "source_kind": "command_reference",
            "source_type": "official_url",
        },
        content="show license tech support",
        section="System management",
    )
