from __future__ import annotations

import asyncio

from ai.providers import openai_compatible as provider_module
from ai.providers.openai_compatible import OpenAICompatibleProvider


def test_deepseek_stream_uses_provider_reported_usage(monkeypatch) -> None:
    captured: dict = {}

    class FakeResponse:
        status_code = 200

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"hello"}}],"usage":null}'
            yield 'data: {"choices":[],"usage":{"prompt_tokens":21,"completion_tokens":4,"total_tokens":25}}'
            yield "data: [DONE]"

    class FakeStreamContext:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *_args):
            return False

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def stream(self, method, url, *, headers, json):
            captured.update({"method": method, "url": url, "headers": headers, "payload": json})
            return FakeStreamContext()

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", FakeClient)
    provider = OpenAICompatibleProvider({
        "id": "provider-deepseek",
        "name": "DeepSeek",
        "provider_type": "deepseek",
        "base_url": "https://api.deepseek.com",
    }, api_key="test-key")
    usage: dict[str, int] = {}

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in provider.chat_stream(
                [{"role": "user", "content": "hi"}],
                model="deepseek-chat",
                usage_sink=usage,
            )
        ]

    assert asyncio.run(collect()) == ["hello"]
    assert usage == {"input_tokens": 21, "output_tokens": 4, "cached_tokens": 0}
    assert captured["payload"]["stream_options"] == {"include_usage": True}
    assert captured["payload"]["stream"] is True
