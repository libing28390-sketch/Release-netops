import asyncio

import pytest

from ai.gateway.exceptions import (
    AINetworkException,
    AIInvalidResponseException,
)
from ai.providers.deepseek import DeepSeekProvider
from ai.providers.openai_compatible import OpenAICompatibleProvider
from ai.providers.registry import AzureOpenAIProvider


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


@pytest.mark.parametrize(
    ("base_url", "expected_endpoint"),
    [
        ("https://generativelanguage.googleapis.com/v1beta/openai", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"),
        ("https://api.fireworks.ai/inference/v1", "https://api.fireworks.ai/inference/v1/chat/completions"),
        ("https://openrouter.ai/api/v1", "https://openrouter.ai/api/v1/chat/completions"),
        ("https://qianfan.baidubce.com/v2", "https://qianfan.baidubce.com/v2/chat/completions"),
        ("https://ark.cn-beijing.volces.com/api/v3", "https://ark.cn-beijing.volces.com/api/v3/chat/completions"),
        ("https://open.bigmodel.cn/api/paas/v4", "https://open.bigmodel.cn/api/paas/v4/chat/completions"),
        ("https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1", "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1/chat/completions"),
        (
            "https://aiplatform.googleapis.com/v1/projects/ProjectABC/locations/us-central1/endpoints/openapi",
            "https://aiplatform.googleapis.com/v1/projects/ProjectABC/locations/us-central1/endpoints/openapi/chat/completions",
        ),
        (
            "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/ProjectABC/locations/us-central1/endpoints/812345",
            "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/ProjectABC/locations/us-central1/endpoints/812345/chat/completions",
        ),
        ("https://provider.example/v1/chat/completions/?tenant=West", "https://provider.example/v1/chat/completions?tenant=West"),
        ("https://provider.example/v1", "https://provider.example/v1/chat/completions"),
        ("https://provider.example", "https://provider.example/v1/chat/completions"),
        ("https://API.Example.com/ProxyCase", "https://API.Example.com/ProxyCase/v1/chat/completions"),
        ("https://provider.example/proxy?tenant=West", "https://provider.example/proxy/v1/chat/completions?tenant=West"),
    ],
)
def test_openai_compatible_endpoint_respects_prefixed_api_roots(base_url, expected_endpoint):
    provider = OpenAICompatibleProvider({"base_url": base_url})

    assert provider._get_endpoint() == expected_endpoint


@pytest.mark.parametrize(
    "base_url",
    [
        "https://provider.example/v1/chat/completions",
        "https://provider.example/proxy/chat/completions?tenant=West",
    ],
)
def test_openai_compatible_complete_endpoint_is_passed_through(base_url):
    provider = OpenAICompatibleProvider({"base_url": base_url})

    assert provider._get_endpoint() == base_url


def test_azure_openai_v1_endpoint_uses_native_api_key_header():
    azure = AzureOpenAIProvider(
        {
            "id": "p1",
            "name": "Azure",
            "provider_type": "azure_openai",
            "base_url": "https://my-res.openai.azure.com/openai/v1/",
        },
        api_key="test-key",
    )

    assert azure._get_endpoint("gpt-4o") == "https://my-res.openai.azure.com/openai/v1/chat/completions"
    headers = azure._get_headers()
    assert headers["api-key"] == "test-key"
    assert "Authorization" not in headers


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


def test_openai_compatible_health_probe_has_room_for_short_provider_metadata(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    provider = OpenAICompatibleProvider({"base_url": "https://provider.example", "provider_type": "openai"})

    result = asyncio.run(provider.test_connection(test_model="model-1"))

    assert result["success"] is True
    assert _Client.last_json["max_tokens"] == 64


@pytest.mark.parametrize(
    ("payload", "expected_exception"),
    [
        (ValueError("not-json"), AIInvalidResponseException),
        ({"choices": "not-a-list"}, AIInvalidResponseException),
    ],
)
def test_openai_compatible_provider_maps_invalid_and_truncated_responses(monkeypatch, payload, expected_exception):
    class Response:
        status_code = 200

        def json(self):
            if isinstance(payload, Exception):
                raise payload
            return payload

    class Client(_Client):
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def post(self, url, *, headers, json):
            return Response()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    provider = OpenAICompatibleProvider({"base_url": "https://provider.example", "provider_type": "openai"})
    with pytest.raises(expected_exception) as exc_info:
        asyncio.run(provider.chat([{"role": "user", "content": "hello"}], model="model-1"))
    assert exc_info.value.code == "AI_INVALID_RESPONSE"
    assert "provider.example" not in str(exc_info.value)


def test_openai_compatible_provider_maps_server_error_without_body(monkeypatch):
    import httpx

    class ErrorResponse:
        status_code = 503

    class ErrorClient(_Client):
        async def post(self, url, *, headers, json):
            return ErrorResponse()

    monkeypatch.setattr(httpx, "AsyncClient", ErrorClient)
    provider = OpenAICompatibleProvider({"base_url": "https://provider.example", "provider_type": "openai"})
    with pytest.raises(AINetworkException) as exc_info:
        asyncio.run(provider.chat([{"role": "user", "content": "hello"}], model="model-1"))
    assert exc_info.value.code == "AI_NETWORK_ERROR"
    assert "provider.example" not in str(exc_info.value)


class _LengthClient(_Client):
    async def post(self, url, *, headers, json):
        _Client.last_json = json

        class Response:
            status_code = 200

            def json(self_inner):
                return {"choices": [{"message": {"content": "partial answer"}, "finish_reason": "length"}], "usage": {"completion_tokens": 64}}

        return Response()


def test_non_stream_length_returns_the_partial_content(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _LengthClient)
    provider = OpenAICompatibleProvider({"base_url": "https://provider.example", "provider_type": "openai"})
    result = asyncio.run(provider.chat([{"role": "user", "content": "hello"}], model="model-1"))
    assert result["content"] == "partial answer"
    assert result["finish_reason"] == "length" and result["truncated"] is True


def test_complete_reply_is_not_marked_truncated(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    provider = OpenAICompatibleProvider({"base_url": "https://provider.example", "provider_type": "openai"})
    result = asyncio.run(provider.chat([{"role": "user", "content": "hello"}], model="model-1"))
    assert result["truncated"] is False


def test_health_probe_requires_a_model_for_generic_providers():
    provider = OpenAICompatibleProvider({"base_url": "https://provider.example", "provider_type": "openai"})
    result = asyncio.run(provider.test_connection())
    assert result["success"] is False and result["error_code"] == "AI_TEST_MODEL_REQUIRED"


def test_truncated_health_probe_is_not_a_success(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _LengthClient)
    provider = OpenAICompatibleProvider({"base_url": "https://provider.example", "provider_type": "openai"})
    result = asyncio.run(provider.test_connection(test_model="model-1"))
    assert result["success"] is False and result["error_code"] == "AI_OUTPUT_TRUNCATED"
