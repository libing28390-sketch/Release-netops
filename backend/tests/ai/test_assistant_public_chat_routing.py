from __future__ import annotations

import asyncio

import pytest

from ai.services import assistant as assistant_module


def test_general_chat_uses_public_classification_and_skips_broad_rag(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict] = []

    async def fake_intent(*args, **kwargs):
        return {"intent": "general_qa", "filters": {}}

    async def fake_stream(*args, **kwargs):
        captured.append(kwargs)
        yield "hello"

    def forbidden_rag(*args, **kwargs):
        raise AssertionError("general chat must not call the broad RAG retriever")

    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", fake_intent)
    monkeypatch.setattr(assistant_module.llm_gateway, "chat_stream", fake_stream)
    monkeypatch.setattr(assistant_module.rag_retriever, "retrieve", forbidden_rag)

    async def collect_events():
        events = []
        async for event in assistant_module.ai_assistant_service._chat_stream_impl(
            "hello", history=[], tenant_id="tenant-default", user_id="admin", roles=[], context={}
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())

    assert captured
    assert captured[-1]["data_classification"] == "PUBLIC"
    assert any("hello" in event for event in events)
