from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest
from ai.schemas.intent import IntentDecision, IntentRiskLevel, IntentType

import ai.services.intent_parser as intent_parser_module
from ai.services.intent_parser import IntentParser


def _run(parser: IntentParser, query: str) -> dict:
    return asyncio.run(parser.parse_intent(query, user_id="test-user"))


def test_intent_prompt_version_is_not_classified_as_a_network_hostname() -> None:
    from ai.security.classification import classify

    level, findings = classify({
        "messages": [{
            "role": "system",
            "content": f"Prompt version: {intent_parser_module.INTENT_PROMPT_VERSION}.",
        }],
    })

    assert level.name == "L1_GENERAL"
    assert not any(item.category == "hostname" for item in findings)


@pytest.mark.parametrize(
    ("query", "expected_intent", "expected_key", "expected_value"),
    [
        ("定位 IP 10.0.0.1", "ip_location", "ip", "10.0.0.1"),
        ("定位 MAC 00:11:22:33:44:55", "mac_location", "mac", "00:11:22:33:44:55"),
    ],
)
def test_identifier_location_uses_deterministic_local_intent(
    monkeypatch: pytest.MonkeyPatch,
    query: str,
    expected_intent: str,
    expected_key: str,
    expected_value: str,
) -> None:
    async def forbidden_chat(*args, **kwargs):
        raise AssertionError("identifier location must not call the cloud intent parser")

    monkeypatch.setattr(intent_parser_module.llm_gateway, "chat", forbidden_chat)

    result = _run(IntentParser(), query)

    assert result["intent"] == expected_intent
    assert result["filters"][expected_key] == expected_value
    assert result["parse_status"] == "deterministic"
    assert result["confidence"] == 1.0


def test_llm_intent_is_pydantic_validated_and_filter_keys_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_chat(*args, **kwargs):
        return {
            "content": (
                "```json\n"
                '{"intent":"device_search","confidence":0.88,'
                '"filters":{"device_id":"dev-01","unexpected":"drop-me"}}\n'
                "```"
            )
        }

    monkeypatch.setattr(intent_parser_module.llm_gateway, "chat", fake_chat)

    result = _run(IntentParser(), "查找 dev-01")

    assert result["intent"] == "device_search"
    assert result["filters"] == {"device_id": "dev-01"}
    assert result["confidence"] == 0.88
    assert result["parse_status"] == "llm_success"
    assert result["risk_level"] == "R0"


def test_invalid_schema_gets_one_gateway_correction_without_mutating_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[dict[str, str]]] = []
    responses = iter((
        '{"intent":"not_a_supported_intent","filters":{}}',
        '{"intent":"alarm_search","filters":{"alarm_id":"alarm-1"},"confidence":0.91}',
    ))

    async def fake_chat(*args, **kwargs):
        captured.append(deepcopy(kwargs["messages"]))
        return {"content": next(responses)}

    monkeypatch.setattr(intent_parser_module.llm_gateway, "chat", fake_chat)

    result = _run(IntentParser(), "查询 alarm-1")

    assert result["intent"] == "alarm_search"
    assert result["parse_status"] == "schema_retry_succeeded"
    assert len(captured) == 2
    assert len(captured[0]) == 2
    assert len(captured[1]) == 3
    assert "not_a_supported_intent" not in captured[1][-1]["content"]
    assert captured[0][0]["role"] == "system"


def test_schema_correction_feedback_never_echoes_sensitive_model_values(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[list[dict[str, str]]] = []
    responses = iter((
        '{"intent":"not_a_supported_intent","filters":{"keyword":"password=NeverExposeThis"}}',
        '{"intent":"general_qa","filters":{},"confidence":0.8}',
    ))

    async def fake_chat(*args, **kwargs):
        captured.append(deepcopy(kwargs["messages"]))
        return {"content": next(responses)}

    monkeypatch.setattr(intent_parser_module.llm_gateway, "chat", fake_chat)

    result = _run(IntentParser(), "解释网络抖动")

    assert result["parse_status"] == "schema_retry_succeeded"
    assert "NeverExposeThis" not in captured[1][-1]["content"]
    assert "password=NeverExposeThis" not in captured[1][-1]["content"]


def test_security_gateway_blocks_credentials_community_and_private_key_before_egress() -> None:
    from ai.security.gateway import AISecurityGateway, SecurityBlocked, SecurityPolicy
    from ai.security.tokenization import ScopedTokenVault

    gateway = AISecurityGateway(
        vault=ScopedTokenVault(ttl_seconds=120),
        policy=SecurityPolicy(external_ai_enabled=True),
    )
    samples = (
        "password=NeverSendThisValue",
        "snmp-server community NeverSendThisCommunity",
        "Authorization: Bearer eyJabc12345.payload.signature",
        "-----BEGIN RSA PRIVATE KEY-----NeverSendThisKey-----END RSA PRIVATE KEY-----",
    )
    for sample in samples:
        with pytest.raises(SecurityBlocked) as exc_info:
            gateway.protect([{"role": "user", "content": sample}])
        assert sample.split("=")[-1] not in exc_info.value.user_message


def test_schema_failure_returns_explicit_safe_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_chat(*args, **kwargs):
        return {"content": '{"intent":"bad","filters":{}}'}

    monkeypatch.setattr(intent_parser_module.llm_gateway, "chat", fake_chat)

    result = _run(IntentParser(), "帮我总结今天的网络情况")

    assert result["intent"] == "general_qa"
    assert result["parse_status"] == "schema_retry_failed"
    assert result["parse_error_code"] == "AI_INTENT_SCHEMA_INVALID"
    assert result["confidence"] == 0.0
    assert result["filters"] == {"keyword": "帮我总结今天的网络情况"}


def test_provider_failure_marks_dangerous_request_for_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    class ProviderFailure(Exception):
        code = "AI_PROVIDER_UNSUPPORTED"

    async def fake_chat(*args, **kwargs):
        raise ProviderFailure("provider unavailable")

    monkeypatch.setattr(intent_parser_module.llm_gateway, "chat", fake_chat)

    result = _run(IntentParser(), "执行 shutdown 10.0.0.1")

    assert result["intent"] == "general_qa"
    assert result["parse_status"] == "provider_error"
    assert result["parse_error_code"] == "AI_PROVIDER_UNSUPPORTED"
    assert result["risk_level"] == "R3"
    assert result["requires_confirmation"] is True
    assert result["needs_clarification"] is True
    assert result["missing_fields"] == ["confirmation"]


def test_high_risk_typed_decision_cannot_skip_confirmation() -> None:
    decision = IntentDecision(intent=IntentType.GENERAL_QA, risk_level=IntentRiskLevel.R3, confidence=0.99)

    assert decision.requires_confirmation is True
    assert decision.needs_clarification is True
    assert decision.missing_fields == ["confirmation"]


def test_structured_intent_adds_only_missing_operational_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_chat(*args, **kwargs):
        return {
            "content": (
                '{"intent":"troubleshooting","filters":{},"confidence":0.84,'
                '"risk_level":"R1"}'
            )
        }

    monkeypatch.setattr(intent_parser_module.llm_gateway, "chat", fake_chat)

    result = _run(IntentParser(), "检查交换机接口")

    assert result["intent"] == "troubleshooting"
    assert result["needs_clarification"] is True
    assert result["missing_fields"][:2] == ["device_id", "interface"]
    assert result["clarification_question"] == "请提供目标设备名称或设备 ID。"


@pytest.mark.parametrize(
    ("query", "response", "expected_missing", "expected_question"),
    [
        (
            "查询最近的告警",
            '{"intent":"alarm_search","filters":{},"confidence":0.84}',
            "device_or_time_range",
            "请提供目标设备、站点或告警时间范围。",
        ),
        (
            "排查延迟指标",
            '{"intent":"troubleshooting","filters":{"device_id":"edge-01"},"confidence":0.84}',
            "metric",
            "请说明要关注的指标，例如延迟、丢包、CPU 或接口利用率。",
        ),
        (
            "查询路由协议",
            '{"intent":"config_search","filters":{"device_id":"edge-01"},"confidence":0.84}',
            "protocol",
            "请说明要查询或排查的协议，例如 OSPF、BGP 或 VLAN。",
        ),
        (
            "执行变更动作",
            '{"intent":"config_search","filters":{"device_id":"edge-01"},"confidence":0.84,"risk_level":"R2"}',
            "action",
            "请明确希望执行的动作或命令，并说明目标范围。",
        ),
    ],
)
def test_structured_intent_exposes_specific_missing_slots(
    monkeypatch: pytest.MonkeyPatch,
    query: str,
    response: str,
    expected_missing: str,
    expected_question: str,
) -> None:
    async def fake_chat(*args, **kwargs):
        return {"content": response}

    monkeypatch.setattr(intent_parser_module.llm_gateway, "chat", fake_chat)

    result = _run(IntentParser(), query)

    assert expected_missing in result["missing_fields"]
    assert result["clarification_question"] == expected_question


def test_assistant_short_circuits_dangerous_intent_clarification(monkeypatch: pytest.MonkeyPatch) -> None:
    from ai.services.assistant import AIAssistantService

    async def fake_parse_intent(*args, **kwargs):
        return {
            "intent": "general_qa",
            "filters": {},
            "needs_clarification": True,
            "missing_fields": ["confirmation"],
            "clarification_question": "请确认目标设备和变更内容。",
            "risk_level": "R3",
            "requires_confirmation": True,
        }

    async def forbidden_chat(*args, **kwargs):
        raise AssertionError("clarification must not call the synthesis provider")

    monkeypatch.setattr(intent_parser_module.intent_parser, "parse_intent", fake_parse_intent)
    monkeypatch.setattr(intent_parser_module.llm_gateway, "chat", forbidden_chat)

    result = asyncio.run(
        AIAssistantService().chat(
            "执行 shutdown",
            user_id="test-user",
            tenant_id="tenant-default",
        )
    )

    assert result["execution_mode"] == "local_clarification"
    assert result["external_egress"] is False
    assert result["clarification"]["requires_confirmation"] is True
    assert result["answer"] == "请确认目标设备和变更内容。"


def test_generic_clarification_payload_is_persistable_and_exposes_safe_slots() -> None:
    from ai.services.assistant import AIAssistantService

    payload = AIAssistantService._intent_clarification_payload({
        "intent": "troubleshooting",
        "filters": {"device_id": "core-01", "password": "must-not-copy"},
        "needs_clarification": True,
        "missing_fields": ["interface"],
        "clarification_question": "请提供接口。",
        "risk_level": "R2",
        "requires_confirmation": False,
    })

    assert payload["request_kind"] == "intent_classification"
    assert payload["intent"] == "troubleshooting"
    assert payload["risk"] == "medium"
    assert payload["risk_level"] == "R2"
    assert payload["recognized_fields"] == {"device_id": "core-01"}
    assert payload["retrieval_allowed"] is False
    assert payload["expires_at"]


def test_generic_clarification_follow_up_fills_and_overrides_slots() -> None:
    from ai.services.assistant import AIAssistantService

    pending = {
        "required": True,
        "request_kind": "intent_classification",
        "intent": "troubleshooting",
        "risk": "medium",
        "risk_level": "R2",
        "missing_fields": ["device_id", "interface"],
        "recognized_fields": {"role": "core"},
        "state_id": "clar_generic",
        "revision": 1,
    }
    current = {
        "intent": "general_qa",
        "filters": {"role": "distribution", "interface": "GigabitEthernet1/0/1"},
        "metadata": {},
        "needs_clarification": False,
        "missing_fields": [],
    }
    result = AIAssistantService._merge_pending_clarification_intent(
        "不是核心，是汇聚交换机",
        current,
        pending,
        {"state_id": "clar_generic", "revision": 1, "values": {"device_id": "agg-01"}},
    )

    assert result["intent"] == "troubleshooting"
    assert result["filters"]["role"] == "distribution"
    assert result["filters"]["device_id"] == "agg-01"
    assert result["filters"]["interface"] == "GigabitEthernet1/0/1"
    assert result["needs_clarification"] is False
    assert result["missing_fields"] == []


def test_parser_failure_returns_local_user_facing_reason_without_synthesis_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from ai.services.assistant import AIAssistantService

    async def fake_parse(*args, **kwargs):
        return {
            "intent": "general_qa",
            "filters": {},
            "needs_clarification": False,
            "parse_failure": {
                "status": "schema_retry_failed",
                "message": "意图识别结果格式异常，未执行任何设备操作。请重新描述问题或稍后重试。",
                "error_code": "AI_INTENT_SCHEMA_INVALID",
            },
        }

    async def forbidden_chat(*args, **kwargs):
        raise AssertionError("parse failure must not call synthesis provider")

    monkeypatch.setattr(intent_parser_module.intent_parser, "parse_intent", fake_parse)
    monkeypatch.setattr(intent_parser_module.llm_gateway, "chat", forbidden_chat)

    result = asyncio.run(AIAssistantService().chat("查询设备状态", user_id="test-user", tenant_id="tenant-default"))

    assert result["execution_mode"] == "local_fallback"
    assert result["external_egress"] is False
    assert "格式异常" in result["answer"]
    assert result["intent_parse"]["error_code"] == "AI_INTENT_SCHEMA_INVALID"


def test_streaming_assistant_short_circuits_dangerous_intent_clarification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai.services.assistant import AIAssistantService

    async def fake_parse_intent(*args, **kwargs):
        return {
            "intent": "general_qa",
            "filters": {},
            "needs_clarification": True,
            "missing_fields": ["device"],
            "clarification_question": "请补充目标设备。",
            "risk_level": "R3",
            "requires_confirmation": True,
        }

    async def forbidden_chat(*args, **kwargs):
        raise AssertionError("stream clarification must not call the synthesis provider")

    monkeypatch.setattr(intent_parser_module.intent_parser, "parse_intent", fake_parse_intent)
    monkeypatch.setattr(intent_parser_module.llm_gateway, "chat", forbidden_chat)

    async def collect_events():
        events = []
        async for event in AIAssistantService()._chat_stream_impl(
            "执行 shutdown",
            user_id="test-user",
            tenant_id="tenant-default",
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())
    joined = "".join(events)

    assert "assistant.intent_clarification" in joined
    assert "请补充目标设备。" in joined
    assert '"external_egress": false' in joined
