"""
Abstract Base Class for LLM Providers
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseLLMProvider(ABC):
    """Abstract Base Class defining the unified interface for all LLM Providers."""

    def __init__(self, provider_data: Dict[str, Any], api_key: Optional[str] = None):
        self.provider_id = provider_data.get("id", "")
        self.name = provider_data.get("name", "")
        self.provider_type = provider_data.get("provider_type", "")
        self.base_url = provider_data.get("base_url")
        self.api_key = api_key
        self.timeout = provider_data.get("timeout", 30)
        self.max_retries = provider_data.get("max_retries", 3)
        self.proxy_url = provider_data.get("proxy_url")

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[Dict[str, Any]] = None,
        thinking: bool = False,
        reasoning_effort: Optional[str] = None,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute chat completion.
        
        Must return dict with keys:
          - 'content': str
          - 'input_tokens': int
          - 'output_tokens': int
          - 'tool_calls': optional list
          - 'finish_reason': optional provider finish reason
          - 'reasoning_content': optional internal-only reasoning trace
        """
        pass

    @abstractmethod
    async def test_connection(self, test_model: Optional[str] = None) -> Dict[str, Any]:
        """
        Test API connection.
        
        Must return dict with keys:
          - 'success': bool
          - 'latency_ms': int
          - 'message': str
        """
        pass
