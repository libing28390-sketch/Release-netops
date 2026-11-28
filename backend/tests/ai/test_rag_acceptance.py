import json
from backend.tests.pg_test_utils import postgresql_test_driver
from types import SimpleNamespace

from ai.services import assistant as assistant_module
from ai.services import product_resolver as resolver_module
from ai.services import rag_retriever as retriever_module
from ai.services.assistant import AIAssistantService
from ai.services.config_clarification import clarification_policy_enabled
from ai.services.intent_parser import intent_parser


def _fixture_connection():
    conn = postgresql_test_driver.connect()
    conn.executescript(
        """
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY, name TEXT, vendor TEXT, platform TEXT,
            tenant_id TEXT, status TEXT, acl_json TEXT, source_trust_level TEXT,
            document_id TEXT, document_category TEXT, product_family TEXT,
            product_series TEXT, product_model TEXT, os_family TEXT,
            os_generation TEXT, software_train TEXT, software_release TEXT,
            cli_platform TEXT, feature_domain TEXT, feature TEXT,
            subfeature TEXT, risk_level TEXT, verification_level TEXT,
            rag_priority TEXT, exclude_from_rag INTEGER DEFAULT 0,
            metadata_json JSONB, normalized_content TEXT
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY, document_id TEXT, content TEXT, embedding TEXT,
            metadata_json JSONB, section TEXT, created_at TEXT,
            is_retrieval_candidate INTEGER, chunk_role TEXT, parent_chunk_id TEXT
        );
        """
    )
    docs = [
        ("hw-ce-series", "huawei.cloudengine-6800.product_registry.series", "hardware", "CloudEngine 6800", None, "V300", "huawei_yunshan_v300", None, None, {"document_type": "product_registry", "product_models": []}),
        ("hw-ce-model", "huawei.cloudengine-6800.ce6885.product_registry.model", "hardware", "CloudEngine 6800", "CE6885-48YS8CQ", "V300", "huawei_yunshan_v300", None, None, {"document_type": "product_registry", "product_models": ["CE6885-48YS8CQ"]}),
        ("hw-v600", "huawei.s5735-l-v2.product_registry.series", "hardware", "S5735-L-V2", None, "V600", "huawei_yunshan_v600", None, None, {"document_type": "product_registry", "product_models": []}),
        ("arp-v600", "huawei.yunshan.v600.display_arp.command", "command", None, None, "V600", "huawei_yunshan_v600", "routing", "arp", {"applicable_product_series": ["S5735-L-V2"]}),
        ("vlan-v600", "huawei.yunshan.v600.vlan_access.configuration", "configuration", None, None, "V600", "huawei_yunshan_v600", "switching", "vlan", {"applicable_product_series": ["S5735-L-V2"]}),
        ("ospf-v300", "huawei.yunshan.v300.display_ospf_peer.output.001", "cli_output", None, None, "V300", "huawei_yunshan_v300", "routing", "ospf", {}),
        ("ospf-v600", "huawei.yunshan.v600.display_ospf_peer_brief.output.001", "cli_output", None, None, "V600", "huawei_yunshan_v600", "routing", "ospf", {}),
    ]
    for index, (doc_id, name, category, series, model, train, platform, domain, feature, extra) in enumerate(docs):
        metadata = {"vendor": "Huawei", **extra}
        conn.execute(
            """INSERT INTO ai_document
            (id,name,vendor,platform,tenant_id,status,acl_json,source_trust_level,
             document_id,document_category,product_series,product_model,software_train,
             cli_platform,feature_domain,feature,exclude_from_rag,metadata_json,normalized_content)
             VALUES (?,?,?,?, 'tenant-default','active','{}','official',?,?,?,?,?,?,?,?,0,?,?)""",
            (doc_id, name, "Huawei", platform, name, category, series, model, train, platform, domain, feature, json.dumps(metadata), "content " + name),
        )
        conn.execute(
            "INSERT INTO ai_document_chunk VALUES (?,?,?,?,?,?,?,1,'standalone',NULL)",
            (
                f"chunk-{index}",
                doc_id,
                f"display ospf peer guide {name}" if feature == "ospf" else f"{feature or 'hardware'} guide {name}",
                json.dumps([1.0, 0.0]),
                json.dumps(metadata),
                "General",
                f"2026-01-{index + 1:02d}",
            ),
        )
    conn.commit()
    return conn


def test_six_acceptance_queries(monkeypatch):
    connection = _fixture_connection()
    monkeypatch.setattr(retriever_module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(resolver_module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(retriever_module.embedding_provider, "embed_text", lambda text: [1.0, 0.0])
    service = AIAssistantService()

    def run(query):
        intent = {"knowledge_intent": intent_parser.parse_knowledge_metadata(query)}
        return service.retrieve_knowledge(query, intent)

    case1 = run("Huawei CE6800 OSPF config")
    assert case1["request"].product_series == "CloudEngine 6800"
    assert case1["request"].document_category == "configuration"
    assert case1["results"] == []

    case2 = run("S5735-L-V2 V600 ARP")
    assert case2["request"].software_train == "V600"
    assert case2["request"].cli_platform == "huawei_yunshan_v600"
    assert case2["results"] and all(item["document_category"] == "command" for item in case2["results"])

    case3 = run("S5735-L-V2 VLAN config")
    assert case3["request"].document_category == "configuration"
    assert case3["request"].cli_platform == "huawei_yunshan_v600"
    assert case3["results"]

    case4 = run("display ospf peer meaning")
    assert case4["request"].cli_platform is None
    assert case4["resolution"].ambiguous is True
    assert case4["results"]
    assert case4["debug"]["clarification_required"] is False
    assert case4["debug"]["cross_platform_search"] is True
    assert {item["cli_platform"] for item in case4["results"]} == {
        "huawei_yunshan_v300",
        "huawei_yunshan_v600",
    }

    case5 = run("OSPF neighbor Down troubleshooting")
    assert case5["request"].document_category == "troubleshooting"
    assert case5["results"] == []
    assert case5["resolution"].ambiguous is True
    assert case5["debug"]["clarification_required"] is False
    assert "平台" not in service._knowledge_no_match_answer(case5)

    case6 = run("CE6800 hardware")
    assert case6["request"].document_category == "hardware"
    assert case6["request"].product_series == "CloudEngine 6800"
    assert case6["results"]

    train_only = run("Huawei V600 ARP")
    assert train_only["request"].cli_platform is None
    assert train_only["resolution"].ambiguous is True
    assert train_only["results"] == []
    assert train_only["debug"]["clarification_required"] is True


def test_tospf_configuration_alias_requires_scope_before_retrieval(monkeypatch):
    connection = _fixture_connection()
    monkeypatch.setattr(retriever_module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(resolver_module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(retriever_module.embedding_provider, "embed_text", lambda text: [1.0, 0.0])

    service = AIAssistantService()
    search_calls = 0

    def forbidden_search(*args, **kwargs):
        nonlocal search_calls
        search_calls += 1
        raise AssertionError("ambiguous configuration must not retrieve document bodies")

    monkeypatch.setattr(retriever_module.rag_retriever, "search", forbidden_search)
    query = "\u67e5\u8be2Tospf\u7684\u914d\u7f6e"
    metadata = intent_parser.parse_knowledge_metadata(query)
    result = service.retrieve_knowledge(query, {"knowledge_intent": metadata})

    assert metadata["feature"] == "ospf"
    assert result["resolution"].ambiguous is True
    assert result["debug"]["clarification_required"] is True
    assert result["debug"]["content_retrieval_skipped"] is True
    assert result["status"] == "clarification_required"
    assert result["results"] == []
    assert result["clarification"]["required"] is True
    assert result["clarification"]["missing_fields"] == ["platform_or_model"]
    assert any(item["field"] == "cli_platform" for item in result["clarification"]["options"])
    assert search_calls == 0


def test_vendor_only_configuration_request_is_local_clarification(monkeypatch):
    connection = _fixture_connection()
    monkeypatch.setattr(retriever_module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(resolver_module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(retriever_module.embedding_provider, "embed_text", lambda text: [1.0, 0.0])

    service = AIAssistantService()
    query = "请给我华为交换机配置"
    metadata = intent_parser.parse_knowledge_metadata(query)
    result = service.retrieve_knowledge(query, {"knowledge_intent": metadata})

    assert result["request"].vendor == "Huawei"
    assert result["results"] == []
    assert result["clarification"]["required"] is True
    assert set(result["clarification"]["missing_fields"]) == {"feature", "platform_or_model"}
    assert result["debug"]["content_retrieval_skipped"] is True


def test_configuration_clarification_rollout_is_deterministic(monkeypatch):
    monkeypatch.setenv("AI_CONFIG_CLARIFICATION_ENABLED", "0")
    assert clarification_policy_enabled("tenant-a") is False

    monkeypatch.setenv("AI_CONFIG_CLARIFICATION_ENABLED", "1")
    monkeypatch.setenv("AI_CONFIG_CLARIFICATION_ROLLOUT_PERCENT", "0")
    assert clarification_policy_enabled("tenant-a") is False

    monkeypatch.setenv("AI_CONFIG_CLARIFICATION_ROLLOUT_PERCENT", "100")
    assert clarification_policy_enabled("tenant-a") is True


def test_short_device_family_prefixes_are_resolved_without_using_version_as_identity(monkeypatch):
    connection = _fixture_connection()
    monkeypatch.setattr(retriever_module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(resolver_module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(retriever_module.embedding_provider, "embed_text", lambda text: [1.0, 0.0])

    service = AIAssistantService()
    metadata = intent_parser.parse_knowledge_metadata("S57 V600 VLAN config")
    result = service.retrieve_knowledge("S57 V600 VLAN config", {"knowledge_intent": metadata})

    assert metadata["product_series"] == "S57"
    assert metadata["software_train"] == "V600"
    assert result["request"].cli_platform == "huawei_yunshan_v600"
    assert result["results"]


def test_cross_platform_fallback_renders_operator_summary_instead_of_raw_kb():
    service = AIAssistantService()
    request = SimpleNamespace(document_category="configuration")
    chunks = [
        {
            "platform": "huawei_vrp5_v200",
            "document_category": "configuration",
            "content": """
## 配置OSPF基本功能 > 适用目的
配置OSPF基本功能 > 适用目的

用于配置 OSPF。

## 配置OSPF基本功能 > 风险
配置OSPF基本功能 > 风险
- risk_level: `high`

## 配置OSPF基本功能 > 配置骨架
配置OSPF基本功能 > 配置骨架
```text
system-view
ospf <PROCESS_ID> router-id <ROUTER_ID>
area <AREA_ID>
network <NETWORK> <WILDCARD_MASK>
quit
quit
```

## 配置OSPF基本功能 > 验证命令
配置OSPF基本功能 > 验证命令
- `display ospf peer`
""",
        },
        {
            "platform": "huawei_yunshan_v600",
            "document_category": "configuration",
            "content": """
## 配置OSPF基本功能 > 配置骨架
配置OSPF基本功能 > 配置骨架
```text
system-view
ospf <PROCESS_ID> router-id <ROUTER_ID>
area <AREA_ID>
network <NETWORK> <WILDCARD_MASK>
quit
quit
```

## 配置OSPF基本功能 > 验证状态
配置OSPF基本功能 > 验证状态
- verification_level: `content_verified`
""",
        },
    ]

    answer = service._knowledge_fallback_answer(chunks, request=request)

    assert "未指定唯一 CLI 平台" in answer
    assert "Huawei VRP5（V200）" in answer
    assert "Huawei YunShan（V600）" in answer
    assert "system-view" in answer
    assert "display ospf peer" in answer
    assert "risk_level" not in answer
    assert "verification_level" not in answer
    assert "适用目的" not in answer


def test_cross_platform_output_fallback_explains_peer_fields_without_metadata():
    service = AIAssistantService()
    request = SimpleNamespace(document_category="cli_output", feature="ospf")
    answer = service._knowledge_fallback_answer(
        [
            {
                "platform": "huawei_yunshan_v600",
                "document_category": "cli_output",
                "content": """
## V600 display ospf peer > Command
V600 display ospf peer > Command
```text
display ospf peer
```

## V600 display ospf peer > 输出结构锚点
V600 display ospf peer > 输出结构锚点
- `Neighbor ID`
- `State`
- `Address`
- `Interface`

## V600 display ospf peer > 特殊状态 / 格式标记
V600 display ospf peer > 特殊状态 / 格式标记
- `Full`
- `2-Way`

## V600 display ospf peer > 验证状态
V600 display ospf peer > 验证状态
- parser_ready: `false`
""",
            }
        ],
        request=request,
    )

    assert "`display ospf peer` 用于查看 OSPF 邻居" in answer
    assert "`Full` 表示邻接已建立" in answer
    assert "输出结构锚点" in answer
    assert "Neighbor ID" in answer
    assert "Full" in answer
    assert "parser_ready" not in answer
    assert "验证状态" not in answer


def test_grounded_fallback_does_not_render_unrelated_chunk_from_broad_official_doc():
    service = AIAssistantService()
    answer = service._knowledge_fallback_answer(
        [
            {
                "platform": "cisco_iosxe",
                "document_category": "command",
                "feature": "vlan",
                "source_kind": "command_reference",
                "knowledge_source_type": "official_url",
                "document_name": "Catalyst System Management Command Reference",
                "official_source": "https://www.cisco.com/c/en/system_management_commands.html",
                "section": "show flow monitor FLOW-MONITOR-1",
                "content": "show license tech support\nSmartAgentIndividualRUMEncrypt: 2",
            }
        ],
        request=SimpleNamespace(document_category="command", feature="vlan"),
    )

    assert "SmartAgentIndividualRUMEncrypt" not in answer
    assert "没有可展示的用户级命令或说明" in answer


def test_chat_stream_parses_intent_before_knowledge_retrieval(monkeypatch):
    # This contract mocks the intent-parser/legacy synthesis path explicitly.
    monkeypatch.setattr(assistant_module.settings, "AI_COPILOT_AGENTIC_CHAT_ENABLED", False)
    """Knowledge streaming must not access intent locals before parsing them."""

    llm_calls = []

    async def fake_parse_intent(message, user_id=None):
        return {"intent": "knowledge", "filters": {}, "knowledge_intent": {}}

    async def fake_chat_stream(**kwargs):
        llm_calls.append(kwargs)
        yield "ok"

    class _Resolution:
        def to_dict(self):
            return {"ambiguous": False, "metadata": {}}

    knowledge_result = {
        "request": SimpleNamespace(document_category="configuration"),
        "resolution": _Resolution(),
        "results": [],
        "debug": {},
    }
    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", fake_parse_intent)
    monkeypatch.setattr(assistant_module.llm_gateway, "chat_stream", fake_chat_stream)
    service = AIAssistantService()
    monkeypatch.setattr(service, "retrieve_knowledge", lambda *args, **kwargs: knowledge_result)

    async def collect():
        return [event async for event in service.chat_stream("Huawei CE6800 OSPF config")]

    import asyncio

    events = asyncio.run(collect())
    assert any(event.startswith("event: token") for event in events)
    assert any('"content": "ok"' in event for event in events)
    assert any('"source": "local_rag"' in event and '"status": "no_match"' in event for event in events)
    assert len(llm_calls) == 1
    outbound_text = json.dumps(llm_calls[0], ensure_ascii=False)
    assert "knowledge_status" in outbound_text
    assert "no_local_match" in outbound_text


def test_grounded_knowledge_stream_is_marked_not_external(monkeypatch):
    # This contract mocks the intent-parser/legacy synthesis path explicitly.
    monkeypatch.setattr(assistant_module.settings, "AI_COPILOT_AGENTIC_CHAT_ENABLED", False)
    async def fake_parse_intent(message, user_id=None):
        return {"intent": "knowledge", "filters": {}, "knowledge_intent": {}}

    async def unexpected_chat_stream(**kwargs):
        raise AssertionError("grounded knowledge should be rendered locally")
        yield "unreachable"

    class _Resolution:
        def to_dict(self):
            return {"ambiguous": False, "metadata": {}}

    result = {
        "request": SimpleNamespace(document_category="configuration", feature="ospf"),
        "resolution": _Resolution(),
        "results": [{
            "content": "system-view ospf 1 display ospf peer brief",
            "document_name": "Huawei OSPF",
            "section": "configuration",
            "cli_platform": "huawei_vrp",
            "document_category": "configuration",
        }],
        "debug": {"candidate_count": 1},
    }
    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", fake_parse_intent)
    monkeypatch.setattr(assistant_module.llm_gateway, "chat_stream", unexpected_chat_stream)
    service = AIAssistantService()
    monkeypatch.setattr(service, "retrieve_knowledge", lambda *args, **kwargs: result)

    import asyncio

    async def collect():
        return [event async for event in service.chat_stream("Huawei OSPF config")]

    events = asyncio.run(collect())
    assert any('"external_egress": false' in event for event in events)
    assert any("system-view" in event for event in events)


def test_grounded_knowledge_chat_uses_local_template_fallback_after_scope_repair(monkeypatch):
    # This contract mocks the intent-parser/legacy synthesis path explicitly.
    monkeypatch.setattr(assistant_module.settings, "AI_COPILOT_AGENTIC_CHAT_ENABLED", False)
    async def fake_parse_intent(message, user_id=None):
        return {"intent": "knowledge", "filters": {}, "knowledge_intent": {}}

    class _Resolution:
        def to_dict(self):
            return {"ambiguous": False, "metadata": {}}

    result = {
        "request": SimpleNamespace(
            document_category="configuration",
            vendor="Cisco",
            feature="vlan",
            cli_platform="cisco_iosxe",
        ),
        "resolution": _Resolution(),
        "results": [],
        "debug": {"candidate_count": 0},
    }
    template = {
        "content": "interface <INTERFACE>\n switchport mode access\n switchport access vlan <VLAN_ID>",
        "document_name": "Cisco VLAN Access Template",
        "source": "https://www.cisco.com/c/en/vlan_access_template.html",
        "section": "VLAN access",
        "platform": "cisco_iosxe",
        "cli_platform": "cisco_iosxe",
        "document_category": "configuration",
        "knowledge_source_type": "official_template",
        "feature": "vlan",
    }
    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", fake_parse_intent)
    monkeypatch.setattr(assistant_module, "search_official_templates", lambda request, limit=5: [template])

    async def unexpected_chat(**kwargs):
        raise AssertionError("scoped official template fallback should remain local")

    monkeypatch.setattr(assistant_module.llm_gateway, "chat", unexpected_chat)
    service = AIAssistantService()
    monkeypatch.setattr(service, "retrieve_knowledge", lambda *args, **kwargs: result)

    import asyncio

    answer = asyncio.run(service.chat("Cisco VLAN config"))

    assert answer["execution_mode"] == "local_knowledge"
    assert answer["external_egress"] is False
    assert answer["retrieval"]["source"] == "local_official_template"
    assert "switchport mode access" in answer["answer"]


def test_vendor_follow_up_inherits_feature_without_copying_previous_vendor_scope():
    current_metadata = intent_parser.parse_knowledge_metadata("那可以提供思科的吗")
    current = {
        "intent": "knowledge",
        "filters": current_metadata,
        "metadata": current_metadata,
        "knowledge_intent": current_metadata,
    }
    history = [
        {"role": "user", "content": "我想查下华为交换机的ospf配置示例"},
        {"role": "assistant", "content": "请补充设备平台。"},
        {"role": "user", "content": "Huawei VRP"},
        {"role": "assistant", "content": "已按 Huawei VRP 给出 OSPF 配置。"},
    ]

    merged = AIAssistantService._merge_history_scope_continuation(
        "那可以提供思科的吗",
        current,
        history,
    )
    scope = merged["knowledge_intent"]

    assert scope["vendor"] == "Cisco"
    assert scope["feature"] == "ospf"
    assert scope["feature_domain"] == "routing"
    assert scope["document_category"] == "configuration"
    assert scope["cli_platform"] is None
    assert scope["product_series"] is None
    assert merged["conversation_scope"]["source"] == "previous_user_knowledge_turn"


def test_vendor_follow_up_scope_reaches_chat_and_stream_retrieval(monkeypatch):
    # This contract mocks the intent-parser/legacy synthesis path explicitly.
    monkeypatch.setattr(assistant_module.settings, "AI_COPILOT_AGENTIC_CHAT_ENABLED", False)
    async def fake_parse_intent(message, user_id=None):
        metadata = intent_parser.parse_knowledge_metadata(message)
        return {
            "intent": "knowledge",
            "filters": metadata,
            "metadata": metadata,
            "knowledge_intent": metadata,
        }

    class _Resolution:
        def to_dict(self):
            return {"ambiguous": False, "metadata": {"vendor": "Cisco"}}

    retrieval_calls = []

    def fake_retrieve(message, intent_info, **kwargs):
        scope = intent_info["knowledge_intent"]
        retrieval_calls.append({
            "vendor": scope.get("vendor"),
            "feature": scope.get("feature"),
            "document_category": scope.get("document_category"),
            "cli_platform": scope.get("cli_platform"),
        })
        return {
            "request": SimpleNamespace(
                vendor=scope.get("vendor"),
                document_category=scope.get("document_category"),
                feature=scope.get("feature"),
                cli_platform=scope.get("cli_platform"),
                feature_domain=scope.get("feature_domain"),
            ),
            "resolution": _Resolution(),
            "results": [{
                "content": "router ospf 1\n network <NETWORK> area <AREA_ID>",
                "document_name": "Cisco IOS XE OSPF configuration",
                "section": "OSPF configuration",
                "source": "https://www.cisco.com/c/en/us/ospf.html",
                "platform": "cisco_iosxe",
                "cli_platform": "cisco_iosxe",
                "document_category": "configuration",
                "feature": "ospf",
            }],
            "debug": {"candidate_count": 1},
        }

    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", fake_parse_intent)
    service = AIAssistantService()
    monkeypatch.setattr(service, "retrieve_knowledge", fake_retrieve)
    history = [
        {"role": "user", "content": "我想查下华为交换机的ospf配置示例"},
        {"role": "assistant", "content": "请补充设备平台。"},
        {"role": "user", "content": "Huawei VRP"},
        {"role": "assistant", "content": "已按 Huawei VRP 给出 OSPF 配置。"},
    ]

    import asyncio

    answer = asyncio.run(service.chat("那可以提供思科的吗", history=history))

    async def collect():
        return [event async for event in service.chat_stream("那可以提供思科的吗", history=history)]

    events = asyncio.run(collect())

    assert len(retrieval_calls) == 2
    assert all(call["vendor"] == "Cisco" for call in retrieval_calls)
    assert all(call["feature"] == "ospf" for call in retrieval_calls)
    assert all(call["document_category"] == "configuration" for call in retrieval_calls)
    assert all(call["cli_platform"] is None for call in retrieval_calls)
    assert "OSPF" in answer["answer"]
    assert "router ospf 1" in answer["answer"]
    assert any("router ospf 1" in event for event in events)
    assert not any("AAA" in event or "BGP" in event or "VLAN" in event for event in events)


def test_configuration_clarification_stops_chat_and_stream_before_provider(monkeypatch):
    # This contract mocks the intent-parser/legacy synthesis path explicitly.
    monkeypatch.setattr(assistant_module.settings, "AI_COPILOT_AGENTIC_CHAT_ENABLED", False)
    async def fake_parse_intent(message, user_id=None):
        return {
            "intent": "knowledge",
            "filters": {},
            "knowledge_intent": {
                "vendor": "Huawei",
                "document_category": "configuration",
            },
        }

    class _Resolution:
        def to_dict(self):
            return {"ambiguous": True, "metadata": {"vendor": "Huawei"}}

    clarification = {
        "required": True,
        "state_id": "clar_test",
        "revision": 1,
        "request_kind": "configuration_reference",
        "risk": "medium",
        "reason_code": "MISSING_CONFIGURATION_FEATURE",
        "missing_fields": ["feature", "platform_or_model"],
        "recognized_fields": {"vendor": "Huawei"},
        "question": "请补充功能和设备平台。",
        "options": [
            {"field": "feature", "value": "vlan", "label": "VLAN"},
            {"field": "cli_platform", "value": "huawei_vrp", "label": "Huawei VRP"},
        ],
        "allow_free_text": True,
        "retrieval_allowed": False,
    }
    result = {
        "request": SimpleNamespace(document_category="configuration", vendor="Huawei", feature=None),
        "resolution": _Resolution(),
        "results": [],
        "debug": {"clarification_required": True, "content_retrieval_skipped": True},
        "clarification": clarification,
    }
    provider_calls = []

    async def unexpected_chat(**kwargs):
        provider_calls.append(kwargs)
        raise AssertionError("clarification must not invoke a provider")

    async def unexpected_chat_stream(**kwargs):
        provider_calls.append(kwargs)
        raise AssertionError("clarification must not invoke a provider")
        yield "unreachable"

    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", fake_parse_intent)
    monkeypatch.setattr(assistant_module.llm_gateway, "chat", unexpected_chat)
    monkeypatch.setattr(assistant_module.llm_gateway, "chat_stream", unexpected_chat_stream)
    service = AIAssistantService()
    monkeypatch.setattr(service, "retrieve_knowledge", lambda *args, **kwargs: result)

    import asyncio

    answer = asyncio.run(service.chat("请给我华为交换机配置"))
    assert answer["execution_mode"] == "local_clarification"
    assert answer["external_egress"] is False
    assert answer["clarification"]["required"] is True
    assert "知识库" in answer["answer"]

    async def collect():
        return [event async for event in service.chat_stream("请给我华为交换机配置")]

    events = asyncio.run(collect())
    assert any('"execution_mode": "local_clarification"' in event for event in events)
    assert any('"clarification"' in event and '"required": true' in event for event in events)
    assert any("配置范围" in event for event in events)
    assert provider_calls == []


def test_chat_no_match_uses_bounded_cloud_general_reference(monkeypatch):
    # This contract mocks the intent-parser/legacy synthesis path explicitly.
    monkeypatch.setattr(assistant_module.settings, "AI_COPILOT_AGENTIC_CHAT_ENABLED", False)
    async def fake_parse_intent(message, user_id=None):
        return {"intent": "knowledge", "filters": {}, "knowledge_intent": {}}

    llm_calls = []

    async def fake_chat(**kwargs):
        llm_calls.append(kwargs)
        return {
            "content": "云端通用参考",
            "request_id": "req-test",
            "model_id": "model-test",
            "provider_id": "deepseek",
        }

    class _Resolution:
        def to_dict(self):
            return {"ambiguous": False, "metadata": {}}

    result = {
        "request": SimpleNamespace(document_category="configuration"),
        "resolution": _Resolution(),
        "results": [],
        "debug": {"candidate_count": 0},
    }
    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", fake_parse_intent)
    monkeypatch.setattr(assistant_module.llm_gateway, "chat", fake_chat)
    service = AIAssistantService()
    monkeypatch.setattr(service, "retrieve_knowledge", lambda *args, **kwargs: result)

    import asyncio

    answer = asyncio.run(service.chat("Huawei CE6800 OSPF config"))
    assert answer["facts_retrieved"] is False
    assert answer["citations"] == []
    assert answer["answer"] == "云端通用参考"
    assert answer["answer_contract"]["grounded"] is False
    assert answer["answer_contract"]["no_match"] is True
    assert len(llm_calls) == 1
    outbound = json.dumps(llm_calls[0], ensure_ascii=False)
    assert "no_local_match" in outbound
    assert "knowledge_chunks" not in outbound
