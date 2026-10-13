"""Provider adapter registry used by the LLM Gateway.

Adapters are deliberately transport-only.  They receive already protected
messages from the Security Gateway and are selected by provider type, so a new
provider cannot silently add a direct egress path.
"""

from __future__ import annotations

from typing import Any, Type

from ai.providers.base import BaseLLMProvider
from ai.providers.deepseek import DeepSeekProvider
from ai.providers.openai_compatible import OpenAICompatibleProvider


class AzureOpenAIProvider(OpenAICompatibleProvider):
    """Azure endpoint using the OpenAI-compatible chat contract."""

    def _get_endpoint(self) -> str:
        base = (self.base_url or "").rstrip("/")
        if "/chat/completions" in base:
            return base
        # Azure deployments are represented by the model code; callers may
        # also provide a fully-qualified deployment endpoint.
        if "/openai/deployments/" in base:
            return f"{base}/chat/completions"
        return f"{base}/openai/deployments/{{model}}/chat/completions"

    def _get_headers(self, request_id=None):
        headers = super()._get_headers(request_id)
        if self.api_key:
            headers.pop("Authorization", None)
            headers["api-key"] = self.api_key
        return headers

    async def chat(self, messages, *, model: str, **kwargs: Any):
        original = self.base_url
        if original and "/openai/deployments/" not in original:
            self.base_url = original.rstrip("/") + f"/openai/deployments/{model}"
        try:
            return await super().chat(messages, model=model, **kwargs)
        finally:
            self.base_url = original


class OllamaProvider(OpenAICompatibleProvider):
    """Ollama's local OpenAI-compatible endpoint (``/v1``)."""

    def _get_endpoint(self) -> str:
        base = (self.base_url or "http://127.0.0.1:11434/v1").rstrip("/")
        return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


ADAPTER_REGISTRY: dict[str, Type[BaseLLMProvider]] = {
    "deepseek": DeepSeekProvider,
    "openai": OpenAICompatibleProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "qwen": OpenAICompatibleProvider,
    "azure_openai": AzureOpenAIProvider,
    "ollama": OllamaProvider,
    "local": OpenAICompatibleProvider,
}


def register_provider_adapter(provider_type: str, adapter: Type[BaseLLMProvider]) -> None:
    key = str(provider_type or "").strip().lower().replace("-", "_")
    if not key or not issubclass(adapter, BaseLLMProvider):
        raise ValueError("provider adapter must be a BaseLLMProvider subclass")
    ADAPTER_REGISTRY[key] = adapter


def provider_adapter(provider_type: str) -> Type[BaseLLMProvider]:
    key = str(provider_type or "").strip().lower().replace("-", "_")
    adapter = ADAPTER_REGISTRY.get(key)
    if adapter is None:
        raise ValueError(f"No provider adapter registered for {key or 'empty'}")
    return adapter
