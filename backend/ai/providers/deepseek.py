"""
DeepSeek LLM Provider Implementation
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from ai.providers.openai_compatible import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek Provider implementation using DeepSeek's OpenAI-compatible API."""

    def __init__(self, provider_data: Dict[str, Any], api_key: Optional[str] = None):
        if not provider_data.get("base_url"):
            provider_data["base_url"] = "https://api.deepseek.com"
        super().__init__(provider_data, api_key=api_key)

    async def test_connection(self, test_model: Optional[str] = None) -> Dict[str, Any]:
        target_model = test_model or "deepseek-chat"
        return await super().test_connection(test_model=target_model)
