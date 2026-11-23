"""OpenAI-compatible provider with a constrained, non-redirecting egress."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import weakref
from contextlib import asynccontextmanager
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
from core.config import settings
from core.context import resolve_request_id

logger = logging.getLogger(__name__)


# ── Shared HTTP clients ────────────────────────────────────────────────────
# One long-lived AsyncClient per event loop and (proxy, timeout) keeps TLS
# connections alive between calls instead of a new handshake per request.
# API keys are sent per request in headers, so a client is never bound to a
# Provider's credentials.  Clients are per event loop because an httpx pool
# cannot be shared across loops.
_SHARED_CLIENTS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[tuple, Any]]" = weakref.WeakKeyDictionary()


@asynccontextmanager
async def _borrowed(client: Any):
    """Use a shared client inside ``async with`` without closing it."""
    yield client


async def aclose_shared_clients() -> None:
    """Close this loop's shared provider clients (called on app shutdown)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    clients = _SHARED_CLIENTS.pop(loop, {})
    for client in clients.values():
        try:
            await client.aclose()
        except Exception:
            logger.debug("AI provider client close failed")


def _retry_after_seconds(headers: Any) -> float | None:
    """Parse a numeric Retry-After header (seconds); HTTP dates are ignored."""
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:
        return None
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return max(0.0, value) if math.isfinite(value) else None


def _rate_limited(response: Any) -> AIRateLimitException:
    exc = AIRateLimitException("AI provider rate limit exceeded")
    exc.retry_after = _retry_after_seconds(getattr(response, "headers", None) or {})
    return exc


class OpenAICompatibleProvider(BaseLLMProvider):
    """Universal OpenAI-compatible provider.

    The gateway supplies already-protected messages. This class is transport
    only: it never logs request bodies and never follows provider redirects.
    """

    def _get_endpoint(self, model: Optional[str] = None) -> str:
        del model
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

    def _shared_client(self) -> Any:
        loop = asyncio.get_running_loop()
        clients = _SHARED_CLIENTS.get(loop)
        if clients is None:
            clients = {}
            _SHARED_CLIENTS[loop] = clients
        factory = httpx.AsyncClient
        try:
            timeout = max(1.0, float(self.timeout or 30))
        except (TypeError, ValueError):
            timeout = 30.0
        key = (id(factory), str(self.proxy_url or ""), timeout)
        client = clients.get(key)
        if client is None or getattr(client, "is_closed", False):
            try:
                max_connections = max(1, int(getattr(settings, "AI_HTTP_MAX_CONNECTIONS", 50)))
            except (TypeError, ValueError):
                max_connections = 50
            client = factory(
                # connect/pool are short; read/write keep the Provider timeout.
                timeout=httpx.Timeout(timeout, connect=min(10.0, timeout), pool=min(10.0, timeout)),
                limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=min(20, max_connections)),
                proxy=self.proxy_url or None,
                follow_redirects=False,
            )
            clients[key] = client
        return client

    @staticmethod
    def _stream_max_seconds() -> float:
        try:
            return max(1.0, float(getattr(settings, "AI_STREAM_MAX_SECONDS", 300.0)))
        except (TypeError, ValueError):
            return 300.0

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
        url = self._get_endpoint(model)
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
            async with _borrowed(self._shared_client()) as client:
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
                    raise _rate_limited(response)
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
                # finish_reason=length: the model stopped at max_tokens.  The
                # partial answer is still a valid response -- return it with
                # an explicit marker instead of discarding it (review L5).
                # Callers that need a complete answer check ``truncated``.
                truncated = first_choice.get("finish_reason") == "length"
                message = first_choice.get("message") or {}
                if not isinstance(message, dict):
                    raise AIInvalidResponseException("AI provider message is invalid")
                usage = data.get("usage") or {}
                if not isinstance(usage, dict):
                    usage = {}
                details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
                cached_tok = max(
                    0,
                    int(
                        usage.get("prompt_cache_hit_tokens")
                        or details.get("cached_tokens")
                        or usage.get("cache_read_input_tokens")
                        or usage.get("cached_tokens")
                        or 0
                    ),
                )
                return {
                    "content": message.get("content") or "",
                    "reasoning_content": message.get("reasoning_content") or message.get("reasoning") or "",
                    "input_tokens": int(usage.get("prompt_tokens") or 0),
                    "output_tokens": int(usage.get("completion_tokens") or 0),
                    "cached_tokens": cached_tok,
                    "tool_calls": message.get("tool_calls"),
                    "finish_reason": first_choice.get("finish_reason"),
                    "truncated": truncated,
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
        url = self._get_endpoint(model)
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
            async with _borrowed(self._shared_client()) as client:
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
                        raise _rate_limited(response)
                    if response.status_code >= 400:
                        await response.aread()
                        raise AINetworkException(f"AI provider returned HTTP {response.status_code}")
                    # Total stream duration is capped: a provider that keeps
                    # trickling tokens cannot hold the request open forever.
                    # (Each read is also bounded by the Provider timeout.)
                    deadline = time.monotonic() + self._stream_max_seconds()
                    async for line in response.aiter_lines():
                        if time.monotonic() > deadline:
                            raise AIProviderTimeoutException("AI provider stream exceeded the maximum duration")
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
                            details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
                            usage_sink.update({
                                "input_tokens": max(0, int(usage.get("prompt_tokens") or 0)),
                                "output_tokens": max(0, int(usage.get("completion_tokens") or 0)),
                                "cached_tokens": max(
                                    0,
                                    int(
                                        usage.get("prompt_cache_hit_tokens")
                                        or details.get("cached_tokens")
                                        or usage.get("cache_read_input_tokens")
                                        or usage.get("cached_tokens")
                                        or 0
                                    ),
                                ),
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
        target_model = str(test_model or "").strip()
        if not target_model:
            # A generic OpenAI-compatible endpoint has no model name we could
            # safely guess (the former default was a DeepSeek model).  The
            # caller passes the provider's configured model.
            return {
                "success": False,
                "latency_ms": 0,
                "message": "a model code is required to test this provider",
                "model_tested": None,
                "error_code": "AI_TEST_MODEL_REQUIRED",
            }
        test_messages = [{"role": "user", "content": "Reply with one short word: ok"}]
        try:
            # Keep the probe short while leaving enough room for providers
            # that may emit a small amount of reasoning/metadata before the
            # requested answer.  Too small a budget is reported as a
            # truncated response even when the endpoint is healthy.
            result = await self.chat(test_messages, model=target_model, max_tokens=64)
            if result.get("truncated"):
                # A probe that ran out of output budget is not a healthy reply.
                return {
                    "success": False,
                    "latency_ms": int((time.perf_counter() - start_time) * 1000),
                    "message": "provider reply was truncated",
                    "model_tested": target_model,
                    "error_code": "AI_OUTPUT_TRUNCATED",
                }
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
