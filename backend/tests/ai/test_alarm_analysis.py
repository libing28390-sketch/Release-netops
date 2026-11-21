from __future__ import annotations

import asyncio
import json

from ai.services import assistant as assistant_module
from ai.services.assistant import AIAssistantService


def _payload(event: str) -> dict:
    data_line = next(line for line in event.splitlines() if line.startswith("data:"))
    return json.loads(data_line.split(":", 1)[1].strip())


def test_non_stream_alarm_search_stays_on_local_aggregate(monkeypatch):
    async def fake_parse_intent(message, user_id=None):
        return {"intent": "alarm_search", "filters": {}}

    async def fake_alert_analysis(message, filters, tenant_id=None):
        return {
            "matched_count": 2,
            "summary": "alert aggregate",
            "analysis": {"alerts": {"active_count": 1, "recent_24h_count": 2}},
            "citations": [{"citation_id": "alert-1"}],
        }

    async def forbidden_provider(*args, **kwargs):
        raise AssertionError("alarm search must not reach a provider")

    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", fake_parse_intent)
    monkeypatch.setattr(assistant_module.natural_query_service, "execute_alert_analysis", fake_alert_analysis)
    monkeypatch.setattr(assistant_module.llm_gateway, "chat", forbidden_provider)

    result = asyncio.run(
        AIAssistantService().chat("当前未恢复告警数量", tenant_id="tenant-a")
    )

    assert result["answer"] == "alert aggregate"
    assert result["intent"] == "alarm_search"
    assert result["execution_mode"] == "local_operation"
    assert result["external_egress"] is False
    assert result["input_tokens"] == 0
    assert result["output_tokens"] == 0


def test_stream_alarm_search_emits_local_terminal_contract(monkeypatch):
    async def fake_parse_intent(message, user_id=None):
        return {"intent": "alarm_search", "filters": {}}

    async def fake_alert_analysis(message, filters, tenant_id=None):
        return {
            "matched_count": 0,
            "summary": "empty alert aggregate",
            "analysis": {"alerts": {"active_count": 0, "recent_24h_count": 0}},
            "citations": [],
        }

    async def forbidden_provider(*args, **kwargs):
        raise AssertionError("alarm stream must not reach a provider")

    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", fake_parse_intent)
    monkeypatch.setattr(assistant_module.natural_query_service, "execute_alert_analysis", fake_alert_analysis)
    monkeypatch.setattr(assistant_module.llm_gateway, "chat_stream", forbidden_provider)

    async def collect():
        return [event async for event in AIAssistantService().chat_stream("当前告警数量")]

    events = asyncio.run(collect())
    payloads = [_payload(event) for event in events]
    assert any(payload.get("intent") == "alarm_search" for payload in payloads)
    assert any(payload.get("content") == "empty alert aggregate" for payload in payloads)
    done = next(payload for payload in payloads if payload.get("status") == "completed" and "duration_ms" in payload)
    assert done["execution_mode"] == "local_operation"
    assert done["external_egress"] is False
