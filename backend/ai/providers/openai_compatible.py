"""
OpenAI-Compatible LLM Provider Implementation
"""

from __future__ import annotations

import time
import httpx
from typing import Any, Dict, List, Optional
from ai.providers.base import BaseLLMProvider
from ai.gateway.exceptions import (
    AIAuthFailedException,
    AIInvalidResponseException,
    AINetworkException,
    AIRateLimitException,
    AIProviderTimeoutException,
)


class OpenAICompatibleProvider(BaseLLMProvider):
    """Universal OpenAI-compatible API Provider (supports OpenAI, Qwen, Ollama, vLLM, DeepSeek, etc.)."""

    def _get_endpoint(self) -> str:
        base = (self.base_url or "https://api.openai.com/v1").rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

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
    ) -> Dict[str, Any]:
        url = self._get_endpoint()
        headers = self._get_headers()
        
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format:
            payload["response_format"] = response_format
        if tools:
            payload["tools"] = tools

        timeout_sec = float(self.timeout)
        
        try:
            async with httpx.AsyncClient(timeout=timeout_sec, proxy=self.proxy_url) as client:
                resp = await client.post(url, headers=headers, json=payload)
                
                if resp.status_code == 401:
                    raise AIAuthFailedException(f"Authentication failed for provider '{self.name}': HTTP 401")
                elif resp.status_code == 429:
                    raise AIRateLimitException(f"Rate limit exceeded for provider '{self.name}': HTTP 429")
                elif resp.status_code >= 400:
                    raise AINetworkException(f"Provider '{self.name}' returned HTTP {resp.status_code}: {resp.text[:200]}")
                
                data = resp.json()
                choices = data.get("choices", [])
                if not choices:
                    raise AIInvalidResponseException(f"No choices returned from provider '{self.name}'")
                
                first_choice = choices[0]
                message = first_choice.get("message", {})
                content = message.get("content", "") or ""
                tool_calls = message.get("tool_calls")
                
                usage = data.get("usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)
                
                return {
                    "content": content,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "tool_calls": tool_calls,
                    "raw": data
                }
        except httpx.TimeoutException as exc:
            raise AIProviderTimeoutException(f"Request to provider '{self.name}' timed out ({self.timeout}s)") from exc
        except (AIAuthFailedException, AIRateLimitException, AINetworkException, AIInvalidResponseException, AIProviderTimeoutException):
            raise
        except Exception as exc:
            raise AINetworkException(f"Network error calling provider '{self.name}': {str(exc)}") from exc

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        *,
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ):
        url = self._get_endpoint()
        headers = self._get_headers()
        
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        timeout_sec = float(self.timeout)
        
        try:
            async with httpx.AsyncClient(timeout=timeout_sec, proxy=self.proxy_url) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        raise AINetworkException(f"Provider '{self.name}' returned HTTP {response.status_code}: {body.decode('utf-8', errors='ignore')[:200]}")
                    
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk_json = json.loads(data_str)
                            choices = chunk_json.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content_piece = delta.get("content")
                                if content_piece:
                                    yield content_piece
                        except Exception:
                            continue
        except Exception as exc:
            logger.error(f"Streaming error for '{self.name}': {exc}")
            raise AINetworkException(f"Streaming error calling provider '{self.name}': {str(exc)}") from exc

    async def test_connection(self, test_model: Optional[str] = None) -> Dict[str, Any]:
        start_time = time.perf_counter()
        target_model = test_model or "gpt-3.5-turbo"
        test_messages = [{"role": "user", "content": "你好！请用一句话简短回答：你是什么 AI 模型？"}]
        try:
            res = await self.chat(test_messages, model=target_model, max_tokens=60)
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            answer = (res.get("content") or "").strip()
            return {
                "success": True,
                "latency_ms": latency_ms,
                "message": f"成功连通供应商 '{self.name}'",
                "model_tested": target_model,
                "sample_response": answer[:150]
            }
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return {
                "success": False,
                "latency_ms": latency_ms,
                "message": str(exc),
                "model_tested": target_model,
                "error_code": getattr(exc, "code", "UNKNOWN_ERROR")
            }
