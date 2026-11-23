"""
DeepSeek LLM Provider Implementation
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional
from ai.gateway.exceptions import AIModelNotFoundException
from ai.providers.openai_compatible import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek Provider implementation using DeepSeek's OpenAI-compatible API."""

    def __init__(self, provider_data: Dict[str, Any], api_key: Optional[str] = None):
        configured = (provider_data.get("base_url") or "").rstrip("/")
        if configured and configured not in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}:
            raise ValueError("DeepSeek provider base_url must be https://api.deepseek.com")
        provider_data["base_url"] = "https://api.deepseek.com"
        super().__init__(provider_data, api_key=api_key)

    @classmethod
    def _validate_model(cls, model: str) -> None:
        # Any DeepSeek model code (deepseek-chat, deepseek-reasoner,
        # deepseek-v4-*, ...).  The former SUPPORTED_MODELS allowlist was
        # redundant: every entry already matched this prefix (review L1).
        m = str(model or "").strip().lower()
        if not m.startswith("deepseek-"):
            raise AIModelNotFoundException("DeepSeek model is required (e.g. deepseek-chat, deepseek-reasoner)")

    async def chat(self, messages: List[Dict[str, str]], *, model: str, **kwargs: Any) -> Dict[str, Any]:
        self._validate_model(model)
        return await super().chat(messages, model=model, **kwargs)

    async def chat_stream(self, messages: List[Dict[str, str]], *, model: str, **kwargs: Any) -> AsyncIterator[str]:
        self._validate_model(model)
        async for chunk in super().chat_stream(messages, model=model, **kwargs):
            yield chunk

    async def test_connection(self, test_model: Optional[str] = None) -> Dict[str, Any]:
        # No hard-coded default model (review L5): the API layer tests the
        # provider's configured model.  Without one the base class returns
        # AI_TEST_MODEL_REQUIRED; a non-DeepSeek code is reported, not raised.
        target_model = str(test_model or "").strip()
        if target_model:
            try:
                self._validate_model(target_model)
            except AIModelNotFoundException as exc:
                return {"success": False, "latency_ms": 0, "message": "not a DeepSeek model code", "model_tested": target_model, "error_code": getattr(exc, "code", "AI_MODEL_NOT_FOUND")}
        return await super().test_connection(test_model=target_model or None)
