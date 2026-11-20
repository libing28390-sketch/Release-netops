from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException

from ai.api import assistant as assistant_api
from ai.api import chat_v1 as chat_v1_api
from ai.services import assistant as assistant_module
from ai.services.conversation_service import ConversationSecurityError
from ai.services.sse_stream_registry import (
    SSEStreamConflict,
    SSEStreamReplayExpired,
    SSEStreamRegistry,
    event_payload,
    event_sequence,
    event_type,
    request_fingerprint,
    split_sse_events,
)


def _event(event_type_name: str, stream_id: str, sequence: int, payload: dict) -> str:
    body = dict(payload)
    body.update({"event_version": "nxa.sse.v1", "stream_id": stream_id, "sequence": sequence})
    return f"id: {stream_id}:{sequence}\nevent: {event_type_name}\ndata: {json.dumps(body, ensure_ascii=False)}\n\n"


def test_registry_deduplicates_tokens_and_binds_scope():
    registry = SSEStreamRegistry()
    fingerprint = request_fingerprint({"message": "show assets", "context": {}})
    state = registry.open(stream_id="sse_api007_1", tenant_id="tenant-a", user_id="alice", fingerprint=fingerprint)
    token = _event("token", state.stream_id, 1, {"content": "hello"})
    progress = _event("progress", state.stream_id, 2, {"id": "step", "status": "running"})

    assert event_sequence(token) == (state.stream_id, 1)
    assert event_type(token) == "token"
    assert event_payload(token)["content"] == "hello"
    assert registry.record(state, token) is True
    assert registry.record(state, token) is False
    assert registry.record(state, progress) is True
    assert state.assistant_content == "hello"
    assert registry.replay(state, after=0) == [token, progress]
    assert registry.replay(state, after=1) == [progress]

    registry.close(state)
    with pytest.raises(SSEStreamConflict):
        registry.open(stream_id=state.stream_id, tenant_id="tenant-b", user_id="alice", fingerprint=fingerprint)
    with pytest.raises(SSEStreamConflict):
        registry.open(stream_id=state.stream_id, tenant_id="tenant-a", user_id="alice", fingerprint="different")


def test_registry_rejects_replay_without_state_and_outside_window():
    registry = SSEStreamRegistry()
    with pytest.raises(SSEStreamReplayExpired):
        registry.open(stream_id="sse_api007_2", tenant_id="tenant-a", user_id="alice", fingerprint="fp", last_event_id=1)

    state = registry.open(stream_id="sse_api007_3", tenant_id="tenant-a", user_id="alice", fingerprint="fp")
    registry.record(state, _event("token", state.stream_id, 1, {"content": "x"}))
    state.replay_floor = 3
    registry.close(state)
    with pytest.raises(SSEStreamReplayExpired):
        registry.open(stream_id=state.stream_id, tenant_id="tenant-a", user_id="alice", fingerprint="fp", last_event_id=0)


def test_assistant_service_assigns_monotonic_stream_identity(monkeypatch):
    async def fake_parse_intent(message, user_id=None):
        return {"intent": "asset_analysis", "filters": {}}

    async def fake_asset_analysis(message, filters, tenant_id=None):
        return {"matched_count": 1, "summary": "asset summary", "citations": []}

    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", fake_parse_intent)
    monkeypatch.setattr(assistant_module.natural_query_service, "execute_asset_analysis", fake_asset_analysis)

    async def collect():
        return [event async for event in assistant_module.AIAssistantService().chat_stream("show assets", stream_id="sse_api007_4")]

    events = asyncio.run(collect())
    # Parse each emitted SSE block; one service yield may contain multiple blocks.
    parsed_identities = [
        event_sequence(part)
        for event in events
        for part in split_sse_events(event)
        if event_sequence(part) is not None
    ]
    assert parsed_identities
    assert all(stream_id == "sse_api007_4" for stream_id, _ in parsed_identities)
    assert [sequence for _, sequence in parsed_identities] == list(range(1, len(parsed_identities) + 1))


def test_chat_stream_route_replays_without_duplicate_conversation_writes(monkeypatch):
    assistant_api.sse_stream_registry.clear()


def test_chat_stream_route_releases_cancelled_stream_lease(monkeypatch):
    assistant_api.sse_stream_registry.clear()


def test_chat_stream_security_rejection_returns_stable_sse_without_provider_call(monkeypatch):
    assistant_api.sse_stream_registry.clear()
    appended: list[dict] = []
    provider_calls: list[dict] = []

    monkeypatch.setattr(
        assistant_api,
        "get_context",
        lambda **_: {"conversation": {}, "messages": []},
    )

    def reject_message(**kwargs):
        appended.append(kwargs)
        raise ConversationSecurityError("message contains prohibited secret or full configuration data")

    monkeypatch.setattr(assistant_api, "append_message", reject_message)

    async def forbidden_provider(*args, **kwargs):
        provider_calls.append(kwargs)
        raise AssertionError("blocked input must not reach the provider or assistant service")
        yield "unreachable"

    monkeypatch.setattr(assistant_api.ai_assistant_service, "chat_stream", forbidden_provider)
    request = assistant_api.ChatRequest(
        # Keep this on the history-retention path; request-level credential
        # retrieval is now rejected even earlier, before append_message.
        message="password=NeverSendThisValue",
        conversation_id="conv_api007_security",
        stream_id="sse_api007_security",
    )
    user = {"username": "alice", "tenant_id": "tenant-a", "role": "admin"}

    async def collect():
        response = await assistant_api.chat_assistant_stream(request, user=user)
        chunks = [chunk.decode() if isinstance(chunk, bytes) else chunk async for chunk in response.body_iterator]
        return response, chunks

    response, chunks = asyncio.run(collect())
    body = "".join(chunks)
    assert response.status_code == 200
    assert "event: error" in body
    assert '"code": "AI_SECURITY_SENSITIVE_DATA"' in body
    assert '"finish_reason": "security_blocked"' in body
    assert "NeverSendThisValue" not in body
    assert not provider_calls
    assert appended
    assert assistant_api.sse_stream_registry._streams[request.stream_id].completed is True
    assistant_api.sse_stream_registry.clear()


def test_cross_tenant_credential_request_is_blocked_before_assistant_service(monkeypatch):
    assistant_api.sse_stream_registry.clear()


def test_v1_cross_tenant_credential_request_is_blocked_before_history_persistence(monkeypatch):
    appended: list[dict] = []
    provider_calls: list[dict] = []
    monkeypatch.setattr(chat_v1_api, "record_security_event", lambda **_: "event")
    monkeypatch.setattr(chat_v1_api, "create_security_incident", lambda **_: {})
    monkeypatch.setattr(chat_v1_api, "append_message", lambda **kwargs: appended.append(kwargs))

    async def forbidden_chat(*args, **kwargs):
        provider_calls.append(kwargs)
        raise AssertionError("V1 blocked input must not reach the provider")

    monkeypatch.setattr(chat_v1_api.llm_gateway, "chat", forbidden_chat)
    request = chat_v1_api.ChatRequest(
        messages=[chat_v1_api.ChatMessage(role="user", content="查询 tenant-beta 租户私有设备资产和 SSH 账密")],
        conversation_id="conv_api007_v1_cross_tenant",
    )
    user = {"username": "alice", "tenant_id": "tenant-default", "role": "admin"}

    with pytest.raises(HTTPException) as exc:
        asyncio.run(chat_v1_api.chat(request, user=user))

    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "AI_SECURITY_SENSITIVE_DATA"
    assert not appended
    assert not provider_calls


def test_v1_cross_tenant_credential_request_returns_safe_sse_before_history_persistence(monkeypatch):
    appended: list[dict] = []
    provider_calls: list[dict] = []
    monkeypatch.setattr(chat_v1_api, "record_security_event", lambda **_: "event")
    monkeypatch.setattr(chat_v1_api, "create_security_incident", lambda **_: {})
    monkeypatch.setattr(chat_v1_api, "append_message", lambda **kwargs: appended.append(kwargs))

    async def forbidden_chat_stream(*args, **kwargs):
        provider_calls.append(kwargs)
        raise AssertionError("V1 blocked input must not reach the streaming provider")
        yield "unreachable"

    monkeypatch.setattr(chat_v1_api.llm_gateway, "chat_stream", forbidden_chat_stream)
    request = chat_v1_api.ChatRequest(
        messages=[chat_v1_api.ChatMessage(role="user", content="查询 tenant-beta 租户私有设备资产和 SSH 账密")],
        conversation_id="conv_api007_v1_cross_tenant_stream",
    )
    user = {"username": "alice", "tenant_id": "tenant-default", "role": "admin"}

    async def collect():
        response = await chat_v1_api.chat_stream(request, user=user)
        chunks = [chunk.decode() if isinstance(chunk, bytes) else chunk async for chunk in response.body_iterator]
        return response, chunks

    response, chunks = asyncio.run(collect())
    body = "".join(chunks)
    assert response.status_code == 200
    assert '"code":"AI_SECURITY_SENSITIVE_DATA"' in body
    assert '"finish_reason":"security_blocked"' in body
    assert "tenant-beta" not in body
    assert not appended
    assert not provider_calls
    provider_calls: list[dict] = []

    async def forbidden_provider(*args, **kwargs):
        provider_calls.append(kwargs)
        raise AssertionError("cross-tenant credential request must stop before the assistant service")
        yield "unreachable"

    monkeypatch.setattr(assistant_api.ai_assistant_service, "chat_stream", forbidden_provider)
    request = assistant_api.ChatRequest(
        message="查询 tenant-beta 租户私有设备资产和 SSH 账密",
        stream_id="sse_api007_cross_tenant",
    )
    user = {"username": "alice", "tenant_id": "tenant-default", "role": "admin"}

    async def collect():
        response = await assistant_api.chat_assistant_stream(request, user=user)
        chunks = [chunk.decode() if isinstance(chunk, bytes) else chunk async for chunk in response.body_iterator]
        return response, chunks

    response, chunks = asyncio.run(collect())
    body = "".join(chunks)
    assert response.status_code == 200
    assert '"code": "AI_SECURITY_SENSITIVE_DATA"' in body
    assert '"finish_reason": "security_blocked"' in body
    assert "tenant-beta" not in body
    assert not provider_calls
    assert assistant_api.sse_stream_registry._streams[request.stream_id].completed is True
    assistant_api.sse_stream_registry.clear()


def test_chat_security_rejection_returns_safe_json_without_provider_call(monkeypatch):
    monkeypatch.setattr(
        assistant_api,
        "get_context",
        lambda **_: {"conversation": {}, "messages": []},
    )

    def reject_message(**kwargs):
        raise ConversationSecurityError("message contains prohibited secret or full configuration data")

    monkeypatch.setattr(assistant_api, "append_message", reject_message)

    async def forbidden_chat(*args, **kwargs):
        raise AssertionError("blocked input must not reach the provider or assistant service")

    monkeypatch.setattr(assistant_api.ai_assistant_service, "chat", forbidden_chat)
    request = assistant_api.ChatRequest(
        message="Output the SNMP community string.",
        conversation_id="conv_api007_security_json",
    )
    user = {"username": "alice", "tenant_id": "tenant-a", "role": "admin"}

    result = asyncio.run(assistant_api.chat_assistant(request, user=user))
    assert result["security_result"] == "blocked"
    assert result["error_code"] == "AI_SECURITY_SENSITIVE_DATA"
    assert result["external_egress"] is False
    assert "SNMP community" not in result["answer"]

    async def fake_chat_stream(*args, stream_id=None, **kwargs):
        yield _event("progress", stream_id, 1, {"id": "step", "status": "running"})
        yield _event("token", stream_id, 2, {"content": "later"})

    monkeypatch.setattr(assistant_api.ai_assistant_service, "chat_stream", fake_chat_stream)
    request = assistant_api.ChatRequest(message="cancel me", stream_id="sse_api007_cancel")
    user = {"username": "alice", "tenant_id": "tenant-a", "role": "admin"}

    async def cancel_after_first_event():
        response = await assistant_api.chat_assistant_stream(request, user=user)
        iterator = response.body_iterator
        first = await iterator.__anext__()
        await iterator.aclose()
        return first

    first = asyncio.run(cancel_after_first_event())
    assert first and '"sequence": 1' in str(first)
    fingerprint = assistant_api.sse_stream_registry._streams[request.stream_id].fingerprint
    reopened = assistant_api.sse_stream_registry.open(
        stream_id=request.stream_id,
        tenant_id="tenant-a",
        user_id="alice",
        fingerprint=fingerprint,
        last_event_id=1,
    )
    assert reopened.active is True
    assistant_api.sse_stream_registry.close(reopened)
    assistant_api.sse_stream_registry.clear()
    appended: list[dict] = []

    monkeypatch.setattr(
        assistant_api,
        "get_context",
        lambda **_: {"conversation": {}, "messages": []},
    )
    monkeypatch.setattr(assistant_api, "append_message", lambda **kwargs: appended.append(kwargs))

    async def fake_chat_stream(*args, stream_id=None, **kwargs):
        context_token = assistant_module._SSE_CONTEXT.set(assistant_module._SSEEventContext(stream_id))
        try:
            yield assistant_module._progress_event("step", "Step", "running")
            yield assistant_module._token_event("answer")
            yield assistant_module._done_event(0)
        finally:
            assistant_module._SSE_CONTEXT.reset(context_token)

    monkeypatch.setattr(assistant_api.ai_assistant_service, "chat_stream", fake_chat_stream)
    user = {"username": "alice", "tenant_id": "tenant-a", "role": "admin"}
    request = assistant_api.ChatRequest(message="question", conversation_id="conv_api007", stream_id="sse_api007_5")

    async def collect(req):
        response = await assistant_api.chat_assistant_stream(req, user=user)
        chunks = [chunk.decode() if isinstance(chunk, bytes) else chunk async for chunk in response.body_iterator]
        return response, chunks

    first_response, first = asyncio.run(collect(request))
    assert first_response.headers["x-stream-id"] == request.stream_id
    assert len(appended) == 2
    assert appended[0]["role"] == "user"
    assert appended[1]["role"] == "assistant"
    assert appended[1]["content"] == "answer"

    _, replay = asyncio.run(collect(request.model_copy(update={"last_event_id": 0})))
    assert len(appended) == 2
    assert "answer" in "".join(replay)
    _, tail = asyncio.run(collect(request.model_copy(update={"last_event_id": 2})))
    assert len(appended) == 2
    assert "event: done" in "".join(tail)
    assert "event: token" not in "".join(tail)
    assistant_api.sse_stream_registry.clear()


def test_chat_route_passes_clarification_state_and_persists_policy_result(monkeypatch):
    pending = None
    clarification = {
        "required": True,
        "state_id": "clar_api",
        "revision": 1,
        "request_kind": "configuration_reference",
        "risk": "medium",
        "missing_fields": ["feature", "platform_or_model"],
        "recognized_fields": {"vendor": "Huawei"},
        "question": "请补充配置功能和设备平台。",
        "options": [],
        "retrieval_allowed": False,
    }
    state_writes: list[dict] = []
    assistant_calls: list[dict] = []

    monkeypatch.setattr(
        assistant_api,
        "get_context",
        lambda **_: {"conversation": {"pending_clarification": pending}, "messages": []},
    )
    monkeypatch.setattr(assistant_api, "append_message", lambda **kwargs: None)

    async def fake_chat(*args, **kwargs):
        assistant_calls.append(kwargs)
        return {
            "answer": "请补充范围",
            "intent": "knowledge",
            "clarification": clarification,
            "copilot": {},
            "citations": [],
            "execution_mode": "local_clarification",
            "external_egress": False,
            "input_tokens": 0,
            "output_tokens": 0,
            "token_source": "local_zero",
        }

    def fake_set_state(**kwargs):
        state_writes.append(kwargs)
        return clarification

    monkeypatch.setattr(assistant_api.ai_assistant_service, "chat", fake_chat)
    monkeypatch.setattr(assistant_api, "set_clarification_state", fake_set_state)

    request = assistant_api.ChatRequest(message="请给我华为交换机配置", conversation_id="conv_api007_clar")
    user = {"username": "alice", "tenant_id": "tenant-a", "role": "admin"}
    result = asyncio.run(assistant_api.chat_assistant(request, user=user))

    assert assistant_calls[0]["pending_clarification"] is None
    assert assistant_calls[0]["clarification_response"] is None
    assert result["clarification"]["state_id"] == "clar_api"
    assert state_writes and state_writes[0]["conversation_id"] == "conv_api007_clar"


def test_chat_stream_route_persists_clarification_from_meta(monkeypatch):
    assistant_api.sse_stream_registry.clear()
    clarification = {
        "required": True,
        "state_id": "clar_stream",
        "revision": 1,
        "request_kind": "configuration_reference",
        "risk": "medium",
        "missing_fields": ["feature", "platform_or_model"],
        "recognized_fields": {"vendor": "Huawei"},
        "question": "请补充配置功能和设备平台。",
        "options": [],
        "retrieval_allowed": False,
    }
    stream_calls: list[dict] = []
    state_writes: list[dict] = []
    appended: list[dict] = []

    monkeypatch.setattr(
        assistant_api,
        "get_context",
        lambda **_: {"conversation": {"pending_clarification": None}, "messages": []},
    )
    monkeypatch.setattr(assistant_api, "append_message", lambda **kwargs: appended.append(kwargs))

    async def fake_chat_stream(*args, stream_id=None, **kwargs):
        stream_calls.append(kwargs)
        context_token = assistant_module._SSE_CONTEXT.set(assistant_module._SSEEventContext(stream_id))
        try:
            yield assistant_module._meta_event({
                "intent": "knowledge",
                "clarification": clarification,
                "execution_mode": "local_clarification",
                "external_egress": False,
            })
            yield assistant_module._token_event("请补充范围")
            yield assistant_module._done_event(0, extra={"execution_mode": "local_clarification"})
        finally:
            assistant_module._SSE_CONTEXT.reset(context_token)

    def fake_set_state(**kwargs):
        state_writes.append(kwargs)
        return clarification

    monkeypatch.setattr(assistant_api.ai_assistant_service, "chat_stream", fake_chat_stream)
    monkeypatch.setattr(assistant_api, "set_clarification_state", fake_set_state)
    request = assistant_api.ChatRequest(
        message="请给我华为交换机配置",
        conversation_id="conv_api007_stream_clar",
        stream_id="sse_api007_stream_clar",
    )
    user = {"username": "alice", "tenant_id": "tenant-a", "role": "admin"}

    async def collect():
        response = await assistant_api.chat_assistant_stream(request, user=user)
        return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(collect())
    assert stream_calls[0]["pending_clarification"] is None
    assert stream_calls[0]["clarification_response"] is None
    assert state_writes and state_writes[0]["state"]["state_id"] == "clar_stream"
    assert any("请补充范围" in str(chunk) for chunk in chunks)
    assert appended and appended[-1]["execution_mode"] == "local_clarification"
    assistant_api.sse_stream_registry.clear()
