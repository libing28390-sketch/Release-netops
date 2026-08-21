import asyncio

import pytest

from ai.gateway.exceptions import AINetworkException
from ai.providers.deepseek import DeepSeekProvider
from ai.providers.openai_compatible import OpenAICompatibleProvider


def test_deepseek_uses_only_v4_models_and_official_endpoint():
    provider = DeepSeekProvider({"id": "p1", "name": "DeepSeek", "provider_type": "deepseek"}, api_key="secret")
    assert provider.base_url == "https://api.deepseek.com"
    assert provider._get_endpoint().endswith("/v1/chat/completions")
    assert provider.test_connection.__func__ is DeepSeekProvider.test_connection
    # Valid models
    provider._validate_model("deepseek-chat")
    provider._validate_model("deepseek-reasoner")
    provider._validate_model("deepseek-v4-flash")
    provider._validate_model("deepseek-v4-pro")


def test_deepseek_rejects_unsupported_model():
    with pytest.raises(Exception):
        DeepSeekProvider._validate_model("gpt-4o")
    with pytest.raises(Exception):
        DeepSeekProvider._validate_model("claude-3-5-sonnet")


def test_deepseek_rejects_custom_endpoint():
    with pytest.raises(ValueError):
        DeepSeekProvider({"base_url": "https://evil.example.invalid"})


def test_provider_rejects_http_except_loopback():
    provider = OpenAICompatibleProvider({"base_url": "http://example.invalid"})
    with pytest.raises(AINetworkException):
        provider._validate_endpoint(provider._get_endpoint())


class _Response:
    status_code = 200

    def json(self):
        return {"id": "req_1", "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


class _Client:
    last_json = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, *, headers, json):
        _Client.last_json = json
        return _Response()


def test_openai_compatible_payload_carries_v1_contract(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    provider = OpenAICompatibleProvider({"base_url": "https://provider.example", "provider_type": "deepseek"}, api_key="secret")
    result = asyncio.run(provider.chat(
        [{"role": "user", "content": "hello"}],
        model="deepseek-v4-pro",
        tools=[{"type": "function", "function": {"name": "read_only"}}],
        thinking=True,
        reasoning_effort="high",
        user_id="nxa_user_opaque",
    ))
    assert result["finish_reason"] == "stop"
    assert _Client.last_json["model"] == "deepseek-v4-pro"
    assert _Client.last_json["thinking"] == {"type": "enabled"}
    assert _Client.last_json["reasoning_effort"] == "high"
    assert _Client.last_json["user"] == "nxa_user_opaque"
