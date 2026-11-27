"""First-party Anthropic Messages API adapter.

The LLM gateway passes already-protected canonical messages into this class.
This module only translates that contract to and from the Messages API; it
does not implement an alternate egress path or log request/response bodies.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional

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
from ai.providers.openai_compatible import OpenAICompatibleProvider, _borrowed, _rate_limited
from core.context import resolve_request_id

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
_ANTHROPIC_VERSION = "2026-10-21"


def _string_content(value: Any, *, field: str = "message content") -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    raise AIInvalidRequestException(f"Anthropic requires {field} to be a string")


def _tool_definition(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Translate the gateway's OpenAI function-tool shape to Anthropic."""
    function = tool.get("function") if isinstance(tool, dict) else None
    if not isinstance(function, dict):
        # Accept Anthropic-native definitions for internal gateway callers.
        function = tool if isinstance(tool, dict) else {}
    name = str(function.get("name") or "").strip()
    if not name:
        raise AIInvalidRequestException("Anthropic tool definition is missing a name")
    schema = function.get("parameters", function.get("input_schema"))
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise AIInvalidRequestException("Anthropic tool input schema must be an object schema")
    translated: Dict[str, Any] = {"name": name, "input_schema": schema}
    description = function.get("description")
    if description:
        translated["description"] = str(description)
    return translated


def _parse_function_arguments(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = json.loads(value or "{}")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AIInvalidRequestException("Prior assistant tool arguments are invalid JSON") from exc
    else:
        raise AIInvalidRequestException("Prior assistant tool arguments must be an object")
    if not isinstance(parsed, dict):
        raise AIInvalidRequestException("Prior assistant tool arguments must be a JSON object")
    return parsed


def _messages_for_anthropic(messages: List[Dict[str, Any]]) -> tuple[str, List[Dict[str, Any]]]:
    """Split system prompts and convert canonical tool history to Messages."""
    system_parts: List[str] = []
    converted: List[Dict[str, Any]] = []
    for message in messages or []:
        if not isinstance(message, dict):
            raise AIInvalidRequestException("Anthropic messages must be objects")
        role = str(message.get("role") or "").strip().lower()
        content = _string_content(message.get("content"))
        if role == "system":
            if content:
                system_parts.append(content)
            continue
        if role == "tool":
            tool_use_id = str(message.get("tool_call_id") or "").strip()
            if not tool_use_id:
                raise AIInvalidRequestException("Tool result is missing its tool_call_id")
            result_block = {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": content,
            }
            if message.get("is_error"):
                result_block["is_error"] = True
            if converted and converted[-1]["role"] == "user" and isinstance(converted[-1]["content"], list):
                # Anthropic expects parallel results together in one user
                # message after the assistant tool_use message.
                converted[-1]["content"].append(result_block)
            else:
                converted.append({"role": "user", "content": [result_block]})
            continue
        if role not in {"user", "assistant"}:
            raise AIInvalidRequestException("Anthropic supports only system, user, assistant, and tool messages")

        blocks: List[Dict[str, Any]] = []
        if content:
            blocks.append({"type": "text", "text": content})
        if role == "assistant":
            tool_calls = message.get("tool_calls") or []
            if not isinstance(tool_calls, list):
                raise AIInvalidRequestException("Prior assistant tool_calls must be a list")
            for call in tool_calls:
                if not isinstance(call, dict):
                    raise AIInvalidRequestException("Prior assistant tool call is invalid")
                function = call.get("function") if isinstance(call.get("function"), dict) else {}
                call_id = str(call.get("id") or "").strip()
                name = str(function.get("name") or "").strip()
                if not call_id or not name:
                    raise AIInvalidRequestException("Prior assistant tool call is missing its id or name")
                blocks.append({
                    "type": "tool_use",
                    "id": call_id,
                    "name": name,
                    "input": _parse_function_arguments(function.get("arguments", {})),
                })
        if not blocks:
            # Empty assistant turns are not useful and Anthropic rejects empty
            # content; an empty user turn is rejected for the same reason.
            raise AIInvalidRequestException("Anthropic messages cannot have empty content")
        item: Dict[str, Any] = {"role": role, "content": blocks}
        converted.append(item)
    if not converted:
        raise AIInvalidRequestException("Anthropic requires at least one user or assistant message")
    return "\n\n".join(system_parts), converted


def _response_format_config(response_format: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not response_format:
        return None
    if not isinstance(response_format, dict):
        raise AIInvalidRequestException("Response format must be an object")
    format_type = str(response_format.get("type") or "").strip().lower()
    if format_type == "json_object":
        # Messages structured output needs a complete schema. A root object
        # with no properties would constrain Claude to return only {}, so the
        # generic JSON-object mode stays prompt-guided and supports arbitrary
        # keys without pretending to enforce an unknown schema.
        return None
    elif format_type in {"json_schema", "json_schema_object"}:
        schema = response_format.get("json_schema") or response_format.get("schema")
        if isinstance(schema, dict) and isinstance(schema.get("schema"), dict):
            schema = schema["schema"]
        if not isinstance(schema, dict):
            raise AIInvalidRequestException("JSON schema response format requires a schema object")
    else:
        raise AIInvalidRequestException("Unsupported Anthropic response format")
    return {"type": "json_schema", "schema": schema}


def _finish_reason(stop_reason: Any) -> str | None:
    return {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "model_context_window_exceeded": "length",
        "tool_use": "tool_calls",
        "pause_turn": "stop",
        "refusal": "content_filter",
    }.get(str(stop_reason or ""), None)


def _usage_int(value: Any, field: str) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError) as exc:
        raise AIInvalidResponseException(f"Anthropic response {field} is invalid") from exc


def _tool_calls(content_blocks: Any) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    if not isinstance(content_blocks, list):
        return calls
    for block in content_blocks:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        arguments = block.get("input")
        if not isinstance(arguments, dict):
            raise AIInvalidResponseException("Anthropic tool input is invalid")
        calls.append({
            "id": str(block.get("id") or ""),
            "type": "function",
            "function": {
                "name": str(block.get("name") or ""),
                "arguments": json.dumps(arguments, ensure_ascii=False, separators=(",", ":")),
            },
        })
    return calls


def _normalize_response(data: Dict[str, Any], *, request_id: Optional[str] = None) -> Dict[str, Any]:
    blocks = data.get("content")
    if not isinstance(blocks, list):
        raise AIInvalidResponseException("Anthropic response content is invalid")
    text_parts: List[str] = []
    reasoning_parts: List[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text" and isinstance(block.get("text"), str):
            text_parts.append(block["text"])
        elif block_type == "thinking" and isinstance(block.get("thinking"), str):
            reasoning_parts.append(block["thinking"])
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    stop_reason = data.get("stop_reason")
    return {
        "content": "".join(text_parts),
        "reasoning_content": "".join(reasoning_parts),
        "input_tokens": _usage_int(usage.get("input_tokens"), "input_tokens"),
        "output_tokens": _usage_int(usage.get("output_tokens"), "output_tokens"),
        "cached_tokens": _usage_int(usage.get("cache_read_input_tokens"), "cache_read_input_tokens"),
        "tool_calls": _tool_calls(blocks),
        "finish_reason": _finish_reason(stop_reason),
        "truncated": stop_reason in {"max_tokens", "model_context_window_exceeded"},
        "provider_request_id": data.get("id") or request_id,
        "raw": data,
    }


class AnthropicProvider(OpenAICompatibleProvider):
    """Anthropic's native Messages API with gateway-compatible results."""

    def _get_endpoint(self, model: Optional[str] = None) -> str:
        del model
        base = str(self.base_url or _DEFAULT_BASE_URL).rstrip("/")
        if base.endswith("/v1/messages"):
            return base
        if base.endswith("/v1"):
            return f"{base}/messages"
        return f"{base}/v1/messages"

    def _get_headers(self, request_id: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": _ANTHROPIC_VERSION,
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        if request_id:
            headers["X-Request-ID"] = resolve_request_id(request_id, prefix="req")
        return headers

    def _build_payload(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: str,
        temperature: Optional[float],
        max_tokens: Optional[int],
        tools: Optional[List[Dict[str, Any]]],
        response_format: Optional[Dict[str, Any]],
        thinking: bool,
        reasoning_effort: Optional[str],
        user_id: Optional[str],
        stream: bool,
    ) -> Dict[str, Any]:
        system, api_messages = _messages_for_anthropic(messages)
        if max_tokens is None:
            raise AIInvalidRequestException("Anthropic requests require max_tokens")
        if int(max_tokens) <= 0:
            raise AIInvalidRequestException("Anthropic max_tokens must be positive")
        payload: Dict[str, Any] = {
            "model": model,
            "max_tokens": int(max_tokens),
            "messages": api_messages,
        }
        if system:
            payload["system"] = system
        if response_format and str(response_format.get("type") or "").strip().lower() == "json_object":
            json_instruction = (
                "Return exactly one valid JSON object as the response, with no Markdown fences or text outside the JSON object."
            )
            payload["system"] = f"{system}\n\n{json_instruction}" if system else json_instruction
        # Anthropic has removed sampling parameters in its current API
        # version. In older API versions, Claude 4.7+ also rejects any
        # non-default temperature, so this adapter intentionally ignores the
        # generic gateway value.
        if tools:
            payload["tools"] = [_tool_definition(tool) for tool in tools]
        output_format = _response_format_config(response_format)
        if output_format:
            payload["output_config"] = {"format": output_format}
        if reasoning_effort:
            effort = str(reasoning_effort).strip().lower()
            if effort not in {"low", "medium", "high", "xhigh", "max"}:
                raise AIInvalidRequestException("Unsupported Anthropic reasoning effort")
            payload.setdefault("output_config", {})["effort"] = effort
        if thinking:
            # Let current models allocate their thinking budget adaptively;
            # a fixed budget is model-specific and must stay below max_tokens.
            payload["thinking"] = {"type": "adaptive"}
        if user_id:
            payload["metadata"] = {"user_id": str(user_id)}
        if stream:
            payload["stream"] = True
        return payload

    @staticmethod
    def _raise_for_status(response: Any) -> None:
        status_code = int(response.status_code)
        if 300 <= status_code < 400:
            raise AINetworkException("Anthropic provider redirect refused")
        if status_code in {401, 403}:
            raise AIAuthFailedException("Anthropic provider authorization failed")
        if status_code == 404:
            raise AIModelNotFoundException("Anthropic model or endpoint was not found")
        if status_code in {400, 422}:
            raise AIInvalidRequestException("Anthropic rejected the request parameters")
        if status_code in {408, 504}:
            raise AIProviderTimeoutException("Anthropic provider request timed out")
        if status_code == 429:
            raise _rate_limited(response)
        if status_code >= 400:
            raise AINetworkException(f"Anthropic provider returned HTTP {status_code}")

    async def chat(
        self,
        messages: List[Dict[str, Any]],
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
        payload = self._build_payload(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            response_format=response_format,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            user_id=user_id,
            stream=stream,
        )
        endpoint = self._get_endpoint(model)
        self._validate_endpoint(endpoint)
        try:
            async with _borrowed(self._shared_client()) as client:
                response = await client.post(endpoint, headers=self._get_headers(request_id), json=payload)
                self._raise_for_status(response)
                try:
                    data = response.json()
                except (TypeError, ValueError) as exc:
                    raise AIInvalidResponseException("Anthropic returned invalid JSON") from exc
                if not isinstance(data, dict) or data.get("type") not in {None, "message"}:
                    raise AIInvalidResponseException("Anthropic response is invalid")
                result = _normalize_response(data, request_id=getattr(response, "headers", {}).get("request-id"))
                result["truncated"] = bool(result["truncated"])
                return result
        except httpx.TimeoutException as exc:
            raise AIProviderTimeoutException("Anthropic provider request timed out") from exc
        except (
            AIAuthFailedException,
            AIInvalidRequestException,
            AIModelNotFoundException,
            AIRateLimitException,
            AINetworkException,
            AIInvalidResponseException,
            AIOutputTruncatedException,
            AIProviderTimeoutException,
        ):
            raise
        except Exception as exc:
            raise AINetworkException("Network error calling Anthropic") from exc

    async def test_connection(self, test_model: Optional[str] = None) -> Dict[str, Any]:
        """Probe Messages API through this adapter's native chat path."""
        target_model = str(test_model or "").strip()
        if not target_model:
            return {
                "success": False,
                "latency_ms": 0,
                "message": "a model code is required to test this provider",
                "model_tested": None,
                "error_code": "AI_TEST_MODEL_REQUIRED",
            }
        started = time.perf_counter()
        try:
            result = await self.chat(
                [{"role": "user", "content": "Reply with one short word: ok"}],
                model=target_model,
                max_tokens=64,
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            if result.get("truncated"):
                return {
                    "success": False,
                    "latency_ms": latency_ms,
                    "message": "provider reply was truncated",
                    "model_tested": target_model,
                    "error_code": "AI_OUTPUT_TRUNCATED",
                }
            return {
                "success": True,
                "latency_ms": latency_ms,
                "message": "Anthropic Messages API connection succeeded",
                "model_tested": target_model,
                "sample_response": str(result.get("content") or "")[:150],
            }
        except Exception as exc:
            return {
                "success": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "message": "Anthropic Messages API connection failed",
                "model_tested": target_model,
                "error_code": getattr(exc, "code", "UNKNOWN_ERROR"),
            }

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
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
        payload = self._build_payload(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            response_format=response_format,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            user_id=user_id,
            stream=True,
        )
        endpoint = self._get_endpoint(model)
        self._validate_endpoint(endpoint)
        try:
            async with _borrowed(self._shared_client()) as client:
                async with client.stream("POST", endpoint, headers=self._get_headers(request_id), json=payload) as response:
                    self._raise_for_status(response)
                    deadline = time.monotonic() + self._stream_max_seconds()
                    saw_message_start = False
                    stop_reason: Optional[str] = None
                    event_count = 0
                    async for line in response.aiter_lines():
                        if time.monotonic() > deadline:
                            raise AIProviderTimeoutException("Anthropic stream exceeded the maximum duration")
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        text = line[5:].strip()
                        if text == "[DONE]":
                            break
                        try:
                            event = json.loads(text)
                        except (TypeError, ValueError) as exc:
                            raise AIInvalidResponseException("Anthropic stream returned invalid JSON") from exc
                        if not isinstance(event, dict):
                            raise AIInvalidResponseException("Anthropic stream event is invalid")
                        event_count += 1
                        event_type = event.get("type")
                        if event_type == "message_start":
                            saw_message_start = True
                            message = event.get("message") if isinstance(event.get("message"), dict) else {}
                            usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
                            if usage_sink is not None:
                                usage_sink.update({
                                    "input_tokens": _usage_int(usage.get("input_tokens"), "input_tokens"),
                                    "output_tokens": _usage_int(usage.get("output_tokens"), "output_tokens"),
                                    "cached_tokens": _usage_int(usage.get("cache_read_input_tokens"), "cache_read_input_tokens"),
                                })
                        elif event_type == "content_block_start":
                            block = event.get("content_block") if isinstance(event.get("content_block"), dict) else {}
                            initial_text = block.get("text")
                            if block.get("type") == "text" and isinstance(initial_text, str) and initial_text:
                                yield initial_text
                        elif event_type == "content_block_delta":
                            delta = event.get("delta") if isinstance(event.get("delta"), dict) else {}
                            if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                                yield delta["text"]
                            # Thinking and tool-input deltas are intentionally
                            # withheld from the public string-only stream API.
                        elif event_type == "message_delta":
                            delta = event.get("delta") if isinstance(event.get("delta"), dict) else {}
                            stop_reason = delta.get("stop_reason") or stop_reason
                            usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
                            if usage_sink is not None and usage:
                                usage_sink.update({
                                    "output_tokens": _usage_int(usage.get("output_tokens") or usage_sink.get("output_tokens"), "output_tokens"),
                                    "input_tokens": _usage_int(usage.get("input_tokens") or usage_sink.get("input_tokens"), "input_tokens"),
                                    "cached_tokens": _usage_int(usage.get("cache_read_input_tokens") or usage_sink.get("cached_tokens"), "cache_read_input_tokens"),
                                })
                        elif event_type == "error":
                            raise AINetworkException("Anthropic stream returned an error event")
                        elif event_type in {"ping", "content_block_stop", "message_stop"}:
                            continue
                        else:
                            # Ignore future, non-content event kinds while
                            # preserving strict JSON/schema checks above.
                            continue
                    if not saw_message_start or event_count == 0:
                        raise AIInvalidResponseException("Anthropic stream ended without a message")
                    if stop_reason in {"max_tokens", "model_context_window_exceeded"}:
                        raise AIOutputTruncatedException()
                    if usage_sink is not None:
                        usage_sink["finish_reason"] = _finish_reason(stop_reason) or "stop"
                        if stop_reason == "tool_use":
                            usage_sink["tool_use"] = 1
        except (
            AIAuthFailedException,
            AIInvalidRequestException,
            AIModelNotFoundException,
            AIRateLimitException,
            AINetworkException,
            AIInvalidResponseException,
            AIOutputTruncatedException,
            AIProviderTimeoutException,
        ):
            raise
        except httpx.TimeoutException as exc:
            raise AIProviderTimeoutException("Anthropic stream timed out") from exc
        except Exception as exc:
            logger.error("Anthropic stream failed provider=%s error=%s", self.name, type(exc).__name__)
            raise AINetworkException("Streaming error calling Anthropic") from exc
