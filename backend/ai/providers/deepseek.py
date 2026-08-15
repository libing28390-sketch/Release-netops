"""
DeepSeek LLM Provider Implementation
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional
from ai.gateway.exceptions import AIModelNotFoundException
from ai.providers.openai_compatible import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek Provider implementation using DeepSeek's OpenAI-compatible API."""

    SUPPORTED_MODELS = frozenset({"deepseek-v4-flash", "deepseek-v4-pro"})

    def __init__(self, provider_data: Dict[str, Any], api_key: Optional[str] = None):
        configured = (provider_data.get("base_url") or "").rstrip("/")
        if configured and configured not in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}:
            raise ValueError("DeepSeek provider base_url must be https://api.deepseek.com")
        provider_data["base_url"] = "https://api.deepseek.com"
        super().__init__(provider_data, api_key=api_key)

    @classmethod
    def _validate_model(cls, model: str) -> None:
        if str(model).lower() not in cls.SUPPORTED_MODELS:
            raise AIModelNotFoundException("DeepSeek V4 model is required")

    async def chat(self, messages: List[Dict[str, str]], *, model: str, **kwargs: Any) -> Dict[str, Any]:
        self._validate_model(model)
        return await super().chat(messages, model=model, **kwargs)

    async def chat_stream(self, messages: List[Dict[str, str]], *, model: str, **kwargs: Any) -> AsyncIterator[str]:
        self._validate_model(model)
        async for chunk in super().chat_stream(messages, model=model, **kwargs):
            yield chunk

    async def test_connection(self, test_model: Optional[str] = None) -> Dict[str, Any]:
        target_model = test_model or "deepseek-v4-flash"
        return await super().test_connection(test_model=target_model)
