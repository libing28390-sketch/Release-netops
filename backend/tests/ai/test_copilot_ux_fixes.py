"""Copilot conversation fixes found in the 2026-11-22 walkthrough.

1. IP/MAC questions without the words "IP" or "定位" fell through to the
   cloud intent parser, which the security gateway must refuse
   (AI_SECURITY_CLASSIFICATION_DENIED) -> "service temporarily unavailable".
2. Answers that hit the model's output limit were silently cut off.
3. "Execute <destructive command>" got a "which platform?" clarification.
4. Disabled web search still showed a failed "web lookup" step.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from ai.services import assistant as assistant_module
from ai.services import intent_parser as intent_module
from ai.services.intent_parser import (
    IntentType,
    _classification_denied_local_intent,
    _deterministic_identifier_intent,
)


def _events(message: str, **kwargs) -> list[str]:
    async def collect():
        return [
            event async for event in assistant_module.ai_assistant_service._chat_stream_impl(
                message, history=[], tenant_id="tenant-default", user_id="admin", roles=[], context={}, **kwargs
            )
        ]

    return asyncio.run(collect())


def _payloads(events: list[str], name: str) -> list[dict]:
    result = []
    for event in events:
        lines = event.strip().splitlines()
        if not any(line == f"event: {name}" for line in lines):
            continue
        data = "".join(line[len("data: "):] for line in lines if line.startswith("data: "))
        try:
            result.append(json.loads(data))
        except ValueError:
            continue
    return result


def _answer_text(events: list[str]) -> str:
    return "".join(str(item.get("content") or "") for item in _payloads(events, "token"))


# ── 1. IP / MAC questions ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "10.10.20.15 接在哪台交换机哪个端口？",
        "10.10.20.15 在哪",
        "which switch is 10.10.20.15 connected to",
        "帮我定位 IP 10.10.20.15",
    ],
)
def test_location_questions_about_an_ip_are_answered_locally(query):
    decision = _deterministic_identifier_intent(query)
    assert decision is not None and decision.intent == IntentType.IP_LOCATION
    assert decision.filters == {"ip": "10.10.20.15"}


def test_mac_location_question_without_the_word_mac():
    decision = _deterministic_identifier_intent("00:11:22:33:44:55 接在哪个端口")
    assert decision is not None and decision.intent == IntentType.MAC_LOCATION


def test_classification_denied_with_an_address_falls_back_to_local_lookup():
    decision = _classification_denied_local_intent("10.1.1.9 最近怎么样", "AI_SECURITY_CLASSIFICATION_DENIED")
    assert decision is not None and decision.intent == IntentType.IP_LOCATION
    assert _classification_denied_local_intent("10.1.1.9 最近怎么样", "AI_PROVIDER_TIMEOUT") is None
    assert _classification_denied_local_intent("没有地址的问题", "AI_SECURITY_CLASSIFICATION_DENIED") is None


def test_parse_intent_uses_the_local_fallback_instead_of_a_failure(monkeypatch):
    class Denied(Exception):
        code = "AI_SECURITY_CLASSIFICATION_DENIED"

    async def denied(*_args, **_kwargs):
        raise Denied()

    parser = intent_module.intent_parser
    monkeypatch.setattr(parser, "_chat_intent", denied)
    monkeypatch.setattr(intent_module, "is_alert_aggregation_query", lambda _q: False)
    monkeypatch.setattr(intent_module, "is_asset_analysis_query", lambda _q: False)
    monkeypatch.setattr(parser, "is_knowledge_query", lambda _q: False)
    monkeypatch.setattr(type(parser), "_deterministic_high_risk_decision", classmethod(lambda cls, _q: None))

    result = asyncio.run(parser.parse_intent("10.1.1.9 最近怎么样"))
    assert result["intent"] == "ip_location"
    assert not result.get("parse_failure")


# ── 2. truncated answers ──────────────────────────────────────────────────


def test_truncated_stream_keeps_the_text_and_reports_finish_reason(monkeypatch):
    # This contract mocks the intent-parser/legacy synthesis path explicitly.
    monkeypatch.setattr(assistant_module.settings, "AI_COPILOT_AGENTIC_CHAT_ENABLED", False)
    from ai.gateway.exceptions import AIOutputTruncatedException

    captured: list[dict] = []

    async def fake_intent(*_args, **_kwargs):
        return {"intent": "general_qa", "filters": {}}

    async def fake_stream(*_args, **kwargs):
        captured.append(kwargs)
        yield "第一部分"
        yield "第二部分"
        raise AIOutputTruncatedException()

    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", fake_intent)
    monkeypatch.setattr(assistant_module.llm_gateway, "chat_stream", fake_stream)
    monkeypatch.setattr(assistant_module.settings, "AI_COPILOT_MAX_OUTPUT_TOKENS", 8192, raising=False)

    events = _events("hello")
    assert captured and captured[-1]["max_tokens"] == 8192
    assert "第一部分第二部分" in _answer_text(events)
    done = _payloads(events, "done")
    assert done and done[-1].get("finish_reason") == "length"
    progress = _payloads(events, "progress")
    assert not any("模型服务未返回内容" in str(item.get("detail") or "") for item in progress)
    assert any("输出长度上限" in str(item.get("detail") or "") for item in progress)


def test_complete_stream_has_no_finish_reason(monkeypatch):
    # This contract mocks the intent-parser/legacy synthesis path explicitly.
    monkeypatch.setattr(assistant_module.settings, "AI_COPILOT_AGENTIC_CHAT_ENABLED", False)
    async def fake_intent(*_args, **_kwargs):
        return {"intent": "general_qa", "filters": {}}

    async def fake_stream(*_args, **_kwargs):
        yield "完整回答"

    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", fake_intent)
    monkeypatch.setattr(assistant_module.llm_gateway, "chat_stream", fake_stream)
    done = _payloads(_events("hello"), "done")
    assert done and "finish_reason" not in done[-1]


# ── 3. execution requests ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message, commands",
    [
        ("直接在核心交换机上执行 undo ospf 1 并保存", ["undo ospf 1", "save"]),
        ("帮我执行 shutdown", ["shutdown"]),
        ("在 S5700 上下发 undo vlan 10，然后保存", ["undo vlan 10", "save"]),
    ],
)
def test_execution_requests_are_recognized(message, commands):
    assert assistant_module._explicit_device_execution_request(message) == commands


@pytest.mark.parametrize(
    "message",
    [
        "undo ospf 1 是什么意思",
        "执行 undo ospf 1 会有什么影响",
        "帮我写一个执行 undo ospf 1 的变更方案",
        "帮我执行 display version",
        "OSPF 邻居卡在 ExStart 怎么排查",
    ],
)
def test_questions_about_commands_are_not_blocked(message):
    assert assistant_module._explicit_device_execution_request(message) is None


def test_execution_request_is_answered_locally_without_any_model_call(monkeypatch):
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("no model call for an execution request")
        yield  # pragma: no cover

    async def forbidden_intent(*_args, **_kwargs):
        raise AssertionError("no intent parsing for an execution request")

    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", forbidden_intent)
    monkeypatch.setattr(assistant_module.llm_gateway, "chat_stream", forbidden)
    events = _events("直接在核心交换机上执行 undo ospf 1 并保存")
    text = _answer_text(events)
    assert "不会在设备上执行命令" in text
    assert "undo ospf 1" in text and "OSPF" in text
    assert "/ai/governance" in text
    done = _payloads(events, "done")
    assert done and done[-1]["execution_mode"] == "local_security_block"
    assert done[-1]["external_egress"] is False


# ── 4. disabled web search / identity ─────────────────────────────────────


def test_web_lookup_is_off_when_web_search_is_disabled(monkeypatch):
    monkeypatch.setattr(assistant_module.settings, "AI_WEB_SEARCH_ENABLED", False)
    monkeypatch.setattr(assistant_module.settings, "AI_ENABLED", True)
    monkeypatch.setattr(assistant_module.settings, "EXTERNAL_AI_ENABLED", True)
    assert assistant_module.AIAssistantService._web_lookup_allowed(tenant_id="tenant-default") is False


def test_network_prompt_describes_nexora_and_disabled_web_search(monkeypatch):
    monkeypatch.setattr(assistant_module.settings, "AI_WEB_SEARCH_ENABLED", False)
    prompt = assistant_module._build_system_prompt()
    assert "network operations copilot" in prompt
    assert "never execute commands on devices" in prompt
    assert "web search is disabled" in prompt
    monkeypatch.setattr(assistant_module.settings, "AI_WEB_SEARCH_ENABLED", True)
    assert "web search is disabled" not in assistant_module._build_system_prompt()
