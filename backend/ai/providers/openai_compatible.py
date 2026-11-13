"""OpenAI-compatible provider with a constrained, non-redirecting egress."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from ai.gateway.exceptions import (
    AIAuthFailedException,
    AIInvalidRequestException,
    AIInvalidResponseException,
    AIModelNotFoundException,
    AINetworkException,
    AIOutputTruncatedException,
    AIRateLimitException,
    AIProviderTimeoutException,
)
from ai.providers.base import BaseLLMProvider
from core.context import resolve_request_id

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(BaseLLMProvider):
    """Universal OpenAI-compatible provider.

    The gateway supplies already-protected messages. This class is transport
    only: it never logs request bodies and never follows provider redirects.
    """

    def _get_endpoint(self) -> str:
        base = (self.base_url or "https://api.openai.com/v1").rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def _validate_endpoint(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme == "https":
            return
        if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
            return
        raise AINetworkException("AI provider endpoint must use HTTPS")

    def _get_headers(self, request_id: Optional[str] = None) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if request_id:
            headers["X-Request-ID"] = resolve_request_id(request_id, prefix="req")
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
        reasoning_effort: Optional[str] = None,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        url = self._get_endpoint()
        self._validate_endpoint(url)
        payload: Dict[str, Any] = {"model": model, "messages": messages, "stream": bool(stream)}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format:
            payload["response_format"] = response_format
        if tools:
            payload["tools"] = tools
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if user_id:
            payload["user"] = user_id
        if thinking:
            # DeepSeek accepts this OpenAI-compatible extension; providers
            # that ignore unknown fields remain compatible.
            payload["thinking"] = {"type": "enabled"}

        try:
            async with httpx.AsyncClient(
                timeout=float(self.timeout),
                proxy=self.proxy_url,
                follow_redirects=False,
            ) as client:
                response = await client.post(url, headers=self._get_headers(request_id), json=payload)
                if response.status_code == 401:
                    raise AIAuthFailedException("AI provider authentication failed")
                if response.status_code == 403:
                    raise AIAuthFailedException("AI provider authorization failed")
                if response.status_code == 404:
                    raise AIModelNotFoundException("AI provider model or endpoint was not found")
                if response.status_code in {400, 422}:
                    raise AIInvalidRequestException("AI provider rejected the request parameters")
                if response.status_code in {408, 504}:
                    raise AIProviderTimeoutException("AI provider request timed out")
                if response.status_code == 429:
                    raise AIRateLimitException("AI provider rate limit exceeded")
                if 300 <= response.status_code < 400:
                    # Redirects are an egress boundary violation: do not
                    # forward Authorization to a new host.
                    raise AINetworkException("AI provider redirect refused")
                if response.status_code >= 400:
                    raise AINetworkException(f"AI provider returned HTTP {response.status_code}")
                try:
                    data = response.json()
                except (TypeError, ValueError) as exc:
                    raise AIInvalidResponseException("AI provider returned invalid JSON") from exc
                if not isinstance(data, dict):
                    raise AIInvalidResponseException("AI provider response must be an object")
                choices = data.get("choices") or []
                if not isinstance(choices, list) or not choices:
                    raise AIInvalidResponseException("AI provider returned no choices")
                first_choice = choices[0] or {}
                if not isinstance(first_choice, dict):
                    raise AIInvalidResponseException("AI provider choice is invalid")
                if first_choice.get("finish_reason") == "length":
                    raise AIOutputTruncatedException()
                message = first_choice.get("message") or {}
                if not isinstance(message, dict):
                    raise AIInvalidResponseException("AI provider message is invalid")
                usage = data.get("usage") or {}
                if not isinstance(usage, dict):
                    usage = {}
                return {
                    "content": message.get("content") or "",
                    "reasoning_content": message.get("reasoning_content") or message.get("reasoning") or "",
                    "input_tokens": int(usage.get("prompt_tokens") or 0),
                    "output_tokens": int(usage.get("completion_tokens") or 0),
                    "tool_calls": message.get("tool_calls"),
                    "finish_reason": first_choice.get("finish_reason"),
                    "provider_request_id": data.get("id"),
                    # Internal-only compatibility field. LLMGateway removes
                    # it before returning a response to an API/UI caller.
                    "raw": data,
                }
        except httpx.TimeoutException as exc:
            raise AIProviderTimeoutException("AI provider request timed out") from exc
        except (AIAuthFailedException, AIInvalidRequestException, AIModelNotFoundException, AIRateLimitException, AINetworkException, AIInvalidResponseException, AIOutputTruncatedException, AIProviderTimeoutException):
            raise
        except Exception as exc:
            raise AINetworkException("Network error calling AI provider") from exc

    async def chat_stream(
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
        usage_sink: Optional[Dict[str, int]] = None,
    ) -> AsyncIterator[str]:
        url = self._get_endpoint()
        self._validate_endpoint(url)
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if str(self.provider_type or "").lower() == "deepseek":
            # DeepSeek emits a final usage-only chunk before [DONE]. Keep the
            # mutable sink request-scoped so concurrent streams cannot mix.
            payload["stream_options"] = {"include_usage": True}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        if response_format:
            payload["response_format"] = response_format
        if thinking:
            payload["thinking"] = {"type": "enabled"}
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        if user_id:
            payload["user"] = user_id

        try:
            async with httpx.AsyncClient(
                timeout=float(self.timeout),
                proxy=self.proxy_url,
                follow_redirects=False,
            ) as client:
                async with client.stream("POST", url, headers=self._get_headers(request_id), json=payload) as response:
                    if 300 <= response.status_code < 400:
                        raise AINetworkException("AI provider redirect refused")
                    if response.status_code == 401 or response.status_code == 403:
                        raise AIAuthFailedException("AI provider authorization failed")
                    if response.status_code == 404:
                        raise AIModelNotFoundException("AI provider model or endpoint was not found")
                    if response.status_code in {400, 422}:
                        raise AIInvalidRequestException("AI provider rejected the request parameters")
                    if response.status_code in {408, 504}:
                        raise AIProviderTimeoutException("AI provider stream timed out")
                    if response.status_code == 429:
                        raise AIRateLimitException("AI provider rate limit exceeded")
                    if response.status_code >= 400:
                        await response.aread()
                        raise AINetworkException(f"AI provider returned HTTP {response.status_code}")
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_text = line[5:].strip()
                        if data_text == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_text)
                        except (TypeError, ValueError) as exc:
                            raise AIInvalidResponseException("AI provider stream returned invalid JSON") from exc
                        if not isinstance(chunk, dict):
                            raise AIInvalidResponseException("AI provider stream chunk is invalid")
                        choices = chunk.get("choices") or []
                        if not isinstance(choices, list):
                            raise AIInvalidResponseException("AI provider stream choices are invalid")
                        usage = chunk.get("usage")
                        if usage_sink is not None and isinstance(usage, dict):
                            usage_sink.update({
                                "input_tokens": max(0, int(usage.get("prompt_tokens") or 0)),
                                "output_tokens": max(0, int(usage.get("completion_tokens") or 0)),
                            })
                        if choices:
                            first_choice = choices[0]
                            if not isinstance(first_choice, dict):
                                raise AIInvalidResponseException("AI provider stream choice is invalid")
                            if first_choice.get("finish_reason") == "length":
                                raise AIOutputTruncatedException()
                            delta = first_choice.get("delta") or {}
                            if not isinstance(delta, dict):
                                raise AIInvalidResponseException("AI provider stream delta is invalid")
                            content = delta.get("content")
                            if content:
                                yield str(content)
        except (AIAuthFailedException, AIInvalidRequestException, AIModelNotFoundException, AIRateLimitException, AINetworkException, AIInvalidResponseException, AIOutputTruncatedException, AIProviderTimeoutException):
            raise
        except httpx.TimeoutException as exc:
            raise AIProviderTimeoutException("AI provider stream timed out") from exc
        except Exception as exc:
            logger.error("AI provider stream failed provider=%s error=%s", self.name, type(exc).__name__)
            raise AINetworkException("Streaming error calling AI provider") from exc

    async def test_connection(self, test_model: Optional[str] = None) -> Dict[str, Any]:
        start_time = time.perf_counter()
        target_model = test_model or "deepseek-v4-flash"
        test_messages = [{"role": "user", "content": "Reply with one short word: ok"}]
        try:
            # Keep the probe short while leaving enough room for providers
            # that may emit a small amount of reasoning/metadata before the
            # requested answer.  Too small a budget is reported as a
            # truncated response even when the endpoint is healthy.
            result = await self.chat(test_messages, model=target_model, max_tokens=64)
            return {
                "success": True,
                "latency_ms": int((time.perf_counter() - start_time) * 1000),
                "message": "provider connection succeeded",
                "model_tested": target_model,
                "sample_response": str(result.get("content") or "")[:150],
            }
        except Exception as exc:
            return {
                "success": False,
                "latency_ms": int((time.perf_counter() - start_time) * 1000),
                "message": "provider connection failed",
                "model_tested": target_model,
                "error_code": getattr(exc, "code", "UNKNOWN_ERROR"),
            }
