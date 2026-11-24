import asyncio
import json

import httpx
import pytest

from ai.gateway.exceptions import AIAuthFailedException, AIOutputTruncatedException
from ai.schemas.provider import SUPPORTED_PROVIDER_TYPES
from ai.security.gateway import AISecurityGateway, SecurityBlocked, SecurityPolicy
from ai.providers.anthropic import AnthropicProvider


def _provider() -> AnthropicProvider:
    return AnthropicProvider(
        {
            "id": "provider-anthropic-test",
            "name": "Anthropic test",
            "provider_type": "anthropic",
            "base_url": "https://api.anthropic.com/v1",
            "timeout": 5,
            "max_retries": 0,
        },
        api_key="sk-ant-test",
    )


def test_anthropic_messages_request_and_tool_response_are_gateway_compatible(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"request-id": "req-provider"},
            json={
                "type": "message",
                "id": "msg_123",
                "content": [
                    {"type": "text", "text": "Checking the switch."},
                    {"type": "tool_use", "id": "toolu_123", "name": "get_device", "input": {"device": "edge-1"}},
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 23, "output_tokens": 8, "cache_read_input_tokens": 4},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = _provider()
    monkeypatch.setattr(provider, "_shared_client", lambda: client)

    async def run():
        try:
            return await provider.chat(
                [
                    {"role": "system", "content": "Follow the platform policy."},
                    {"role": "user", "content": "Inspect edge-1."},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"id": "toolu_old", "type": "function", "function": {"name": "get_device", "arguments": "{\"device\":\"edge-1\"}"}}],
                    },
                    {"role": "tool", "tool_call_id": "toolu_old", "name": "get_device", "content": "Model XR-1"},
                    {"role": "tool", "tool_call_id": "toolu_old_2", "name": "get_ports", "content": "Gi1/0/1 up"},
                ],
                model="claude-3-7-sonnet-latest",
                temperature=0.4,
                max_tokens=512,
                tools=[{
                    "type": "function",
                    "function": {
                        "name": "get_device",
                        "description": "Read device inventory",
                        "parameters": {"type": "object", "properties": {"device": {"type": "string"}}},
                    },
                }],
                response_format={"type": "json_object"},
                user_id="opaque-user",
                request_id="req-test",
            )
        finally:
            await client.aclose()

    result = asyncio.run(run())
    body = seen["body"]
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-ant-test"
    assert "authorization" not in seen["headers"]
    assert seen["headers"]["anthropic-version"] == "2026-10-21"
    assert "temperature" not in body
    assert body["system"].startswith("Follow the platform policy.")
    assert body["metadata"] == {"user_id": "opaque-user"}
    assert body["tools"] == [{
        "name": "get_device",
        "description": "Read device inventory",
        "input_schema": {"type": "object", "properties": {"device": {"type": "string"}}},
    }]
    assert body["system"].endswith("Return exactly one valid JSON object as the response, with no Markdown fences or text outside the JSON object.")
    assert "output_config" not in body
    assert body["messages"][1]["content"] == [
        {"type": "tool_use", "id": "toolu_old", "name": "get_device", "input": {"device": "edge-1"}},
    ]
    assert body["messages"][2]["role"] == "user"
    assert body["messages"][2]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_old", "content": "Model XR-1"},
        {"type": "tool_result", "tool_use_id": "toolu_old_2", "content": "Gi1/0/1 up"},
    ]
    assert result["content"] == "Checking the switch."
    assert result["finish_reason"] == "tool_calls"
    assert result["tool_calls"] == [{
        "id": "toolu_123",
        "type": "function",
        "function": {"name": "get_device", "arguments": "{\"device\":\"edge-1\"}"},
    }]
    assert result["input_tokens"] == 23
    assert result["output_tokens"] == 8
    assert result["cached_tokens"] == 4
    assert result["provider_request_id"] == "msg_123"


def test_anthropic_uses_adaptive_thinking_and_omits_gateway_temperature():
    payload = _provider()._build_payload(
        [{"role": "user", "content": "Reason through the diagnosis."}],
        model="claude-opus-5-5",
        temperature=0.25,
        max_tokens=128,
        tools=None,
        response_format=None,
        thinking=True,
        reasoning_effort="high",
        user_id=None,
        stream=False,
    )
    assert payload["thinking"] == {"type": "adaptive"}
    assert payload["output_config"]["effort"] == "high"
    assert "temperature" not in payload


def test_anthropic_is_a_supported_type_without_overriding_admin_policy():
    assert "anthropic" in SUPPORTED_PROVIDER_TYPES
    assert set(SecurityPolicy().allowed_provider_types) == SUPPORTED_PROVIDER_TYPES

    gateway = AISecurityGateway(policy=SecurityPolicy(
        external_ai_enabled=True,
        allowed_provider_types=("deepseek",),
    ))
    with pytest.raises(SecurityBlocked):
        gateway.assert_egress_allowed(provider_type="anthropic")


def test_anthropic_connection_probe_uses_messages_api(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "type": "message",
            "id": "msg_probe",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 8, "output_tokens": 1},
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = _provider()
    monkeypatch.setattr(provider, "_shared_client", lambda: client)

    async def run():
        try:
            return await provider.test_connection("claude-test")
        finally:
            await client.aclose()

    result = asyncio.run(run())
    assert result["success"] is True
    assert result["model_tested"] == "claude-test"
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["body"]["max_tokens"] == 64


def test_anthropic_stream_yields_text_and_updates_usage_sink(monkeypatch):
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 12, "output_tokens": 0}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hello"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": " world"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ]
    body = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events).encode()
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body)))
    provider = _provider()
    monkeypatch.setattr(provider, "_shared_client", lambda: client)
    usage = {}

    async def run():
        try:
            return [
                chunk async for chunk in provider.chat_stream(
                    [{"role": "user", "content": "Say hello"}],
                    model="claude-3-7-sonnet-latest",
                    max_tokens=256,
                    tools=[{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}],
                    usage_sink=usage,
                )
            ]
        finally:
            await client.aclose()

    assert asyncio.run(run()) == ["hello", " world"]
    assert usage["input_tokens"] == 12
    assert usage["output_tokens"] == 5
    assert usage["finish_reason"] == "stop"


def test_anthropic_provider_maps_auth_and_truncation_errors(monkeypatch):
    auth_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"error": {"message": "not surfaced"}}))
    )
    auth_provider = _provider()
    monkeypatch.setattr(auth_provider, "_shared_client", lambda: auth_client)

    async def auth_call():
        try:
            await auth_provider.chat([{"role": "user", "content": "hello"}], model="claude-test", max_tokens=32)
        finally:
            await auth_client.aclose()

    with pytest.raises(AIAuthFailedException):
        asyncio.run(auth_call())

    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 1, "output_tokens": 0}}},
        {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}, "usage": {"output_tokens": 2}},
    ]
    stream_body = "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode()
    stream_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=stream_body))
    )
    stream_provider = _provider()
    monkeypatch.setattr(stream_provider, "_shared_client", lambda: stream_client)

    async def stream_call():
        try:
            return [
                chunk async for chunk in stream_provider.chat_stream(
                    [{"role": "user", "content": "hello"}],
                    model="claude-test",
                    max_tokens=32,
                )
            ]
        finally:
            await stream_client.aclose()

    with pytest.raises(AIOutputTruncatedException):
        asyncio.run(stream_call())
