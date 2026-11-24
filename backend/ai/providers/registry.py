"""Provider adapter registry used by the LLM Gateway.

Adapters are deliberately transport-only.  They receive already protected
messages from the Security Gateway and are selected by provider type, so a new
provider cannot silently add a direct egress path.
"""

from __future__ import annotations

from typing import Any, Optional, Type
from urllib.parse import urlsplit, urlunsplit

from ai.providers.anthropic import AnthropicProvider
from ai.providers.base import BaseLLMProvider
from ai.providers.deepseek import DeepSeekProvider
from ai.providers.openai_compatible import OpenAICompatibleProvider


class AzureOpenAIProvider(OpenAICompatibleProvider):
    """Azure endpoint using the OpenAI-compatible chat contract."""

    def _get_endpoint(self, model: Optional[str] = None) -> str:
        base = (self.base_url or "").rstrip("/")
        parsed = urlsplit(base)
        path = parsed.path.rstrip("/")
        if path.endswith("/chat/completions"):
            return urlunsplit(parsed._replace(path=path))
        if path.endswith("/openai/v1"):
            # Azure OpenAI v1 uses a resource-level OpenAI-compatible root;
            # deployment selection is carried in the model field.
            return urlunsplit(parsed._replace(path=f"{path}/chat/completions"))
        # Azure deployments are represented by the model code; callers may
        # also provide a fully-qualified deployment endpoint.
        if "/openai/deployments/" in path:
            return f"{base}/chat/completions"
        deployment = str(model or "").strip() or "{model}"
        return f"{base}/openai/deployments/{deployment}/chat/completions"

    def _get_headers(self, request_id=None):
        headers = super()._get_headers(request_id)
        if self.api_key:
            headers.pop("Authorization", None)
            headers["api-key"] = self.api_key
        return headers


class OllamaProvider(OpenAICompatibleProvider):
    """Ollama's local OpenAI-compatible endpoint (``/v1``)."""

    def _get_endpoint(self, model: Optional[str] = None) -> str:
        del model
        base = (self.base_url or "http://127.0.0.1:11434/v1").rstrip("/")
        return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


ADAPTER_REGISTRY: dict[str, Type[BaseLLMProvider]] = {
    "deepseek": DeepSeekProvider,
    "anthropic": AnthropicProvider,
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
