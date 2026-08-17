from __future__ import annotations

import asyncio
import json

import pytest

from ai.services import assistant as assistant_module
from ai.services.assistant import AIAssistantService, SSE_EVENT_VERSION, _done_event, _meta_event, _progress_event, _sse_event, _token_event


def _parse_event(event: str) -> tuple[str, dict]:
    lines = event.strip().splitlines()
    name = next(line.split(":", 1)[1].strip() for line in lines if line.startswith("event:"))
    raw = next(line.split(":", 1)[1].strip() for line in lines if line.startswith("data:"))
    return name, json.loads(raw)


def test_sse_event_allowlist_and_versioned_envelope():
    name, payload = _parse_event(_sse_event("token", {"content": "hello"}))
    assert name == "token"
    assert payload == {"content": "hello", "event_version": SSE_EVENT_VERSION}
    with pytest.raises(ValueError):
        _sse_event("unknown", {})


def test_meta_emits_bounded_citation_events_with_the_same_version():
    stream = _meta_event(
        {
            "intent": "knowledge",
            "citations": [{"citation_id": "c1"}, {"citation_id": "c2"}],
        }
    )
    events = [part for part in stream.split("\n\n") if part.strip()]
    parsed = [_parse_event(f"{part}\n\n") for part in events]
    assert [name for name, _ in parsed] == ["meta", "citation", "citation"]
    assert all(payload["event_version"] == SSE_EVENT_VERSION for _, payload in parsed)
    assert parsed[1][1]["citation"]["citation_id"] == "c1"
    assert parsed[2][1]["index"] == 1


def test_all_terminal_and_progress_helpers_are_versioned():
    events = [
        _progress_event("step", "Step", "running"),
        _token_event("token"),
        _done_event(0),
    ]
    assert [_parse_event(event)[0] for event in events] == ["progress", "token", "done"]
    assert all(_parse_event(event)[1]["event_version"] == SSE_EVENT_VERSION for event in events)
    assert _parse_event(events[-1])[1]["status"] == "completed"


def test_chat_stream_covers_meta_progress_token_citation_done_and_error(monkeypatch):
    async def fake_parse_intent(message, user_id=None):
        return {"intent": "asset_analysis", "filters": {}}

    async def fake_asset_analysis(message, filters, tenant_id=None):
        return {"matched_count": 1, "summary": "asset summary", "citations": [{"citation_id": "asset-1"}]}

    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", fake_parse_intent)
    monkeypatch.setattr(assistant_module.natural_query_service, "execute_asset_analysis", fake_asset_analysis)

    async def collect_success():
        return [
            part
            for event in [event async for event in AIAssistantService().chat_stream("show assets", tenant_id="tenant-a")]
            for part in event.split("\n\n")
            if part.strip()
        ]

    success_events = asyncio.run(collect_success())
    success_parsed = [_parse_event(event) for event in success_events]
    success_names = [name for name, _ in success_parsed]
    assert {"meta", "progress", "token", "citation", "done"} <= set(success_names)
    assert all(payload["event_version"] == SSE_EVENT_VERSION for _, payload in success_parsed)

    async def failing_parse_intent(message, user_id=None):
        raise RuntimeError("internal parser detail")

    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", failing_parse_intent)

    async def collect_failure():
        return [
            part
            for event in [event async for event in AIAssistantService().chat_stream("trigger failure", tenant_id="tenant-a")]
            for part in event.split("\n\n")
            if part.strip()
        ]

    failure_parsed = [_parse_event(event) for event in asyncio.run(collect_failure())]
    failure_names = [name for name, _ in failure_parsed]
    assert "error" in failure_names and "done" in failure_names
    error_payload = next(payload for name, payload in failure_parsed if name == "error")
    assert error_payload["code"] == "ASSISTANT_CONTEXT_ERROR"
    assert error_payload["event_version"] == SSE_EVENT_VERSION
    assert "internal parser detail" not in json.dumps(error_payload)
