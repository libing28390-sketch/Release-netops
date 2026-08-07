"""
LLM Gateway - Unified LLM Dispatcher with Model Routing, Sanitizer, Retry, Fallback, and Request Audit Logging
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database.core import get_db_connection
from ai.security.crypto import decrypt_api_key
from ai.security.sanitizer import sanitize_data
from ai.gateway.exceptions import (
    AIException,
    AIModelNotFoundException,
    AINetworkException,
)
from ai.gateway.router import model_router
from ai.providers.base import BaseLLMProvider
from ai.providers.deepseek import DeepSeekProvider
from ai.providers.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)


class LLMGateway:
    """Unified LLM Gateway service."""

    def _generate_request_id(self) -> str:
        return f"ai_req_{uuid.uuid4().hex[:12]}"

    def _get_provider_instance(self, provider_id: str) -> BaseLLMProvider:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, provider_type, base_url, api_key_encrypted, timeout, max_retries, proxy_url, enabled "
                "FROM ai_provider WHERE id = ?",
                (provider_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise AIModelNotFoundException(f"Provider '{provider_id}' not found in database.")
            
            p_data = {
                "id": row[0],
                "name": row[1],
                "provider_type": row[2],
                "base_url": row[3],
                "timeout": row[5],
                "max_retries": row[6],
                "proxy_url": row[7],
                "enabled": row[8],
            }
            if not p_data["enabled"]:
                raise AIModelNotFoundException(f"Provider '{row[1]}' is currently disabled.")
            
            plain_api_key = decrypt_api_key(row[4])
            
            p_type = p_data["provider_type"].lower()
            if p_type == "deepseek":
                return DeepSeekProvider(p_data, api_key=plain_api_key)
            else:
                return OpenAICompatibleProvider(p_data, api_key=plain_api_key)

    def _get_model_details(self, model_id_or_code: str) -> Dict[str, Any]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, provider_id, model_code, default_temperature, default_max_tokens, enabled "
                "FROM ai_model WHERE (id = ? OR model_code = ?) AND enabled = 1",
                (model_id_or_code, model_id_or_code)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "provider_id": row[1],
                    "model_code": row[2],
                    "default_temperature": row[3],
                    "default_max_tokens": row[4],
                }
            
            # If not found by ID or code, try any active default model
            cursor.execute(
                "SELECT id, provider_id, model_code, default_temperature, default_max_tokens "
                "FROM ai_model WHERE enabled = 1 ORDER BY is_default DESC, priority DESC LIMIT 1"
            )
            def_row = cursor.fetchone()
            if def_row:
                return {
                    "id": def_row[0],
                    "provider_id": def_row[1],
                    "model_code": def_row[2],
                    "default_temperature": def_row[3],
                    "default_max_tokens": def_row[4],
                }
        
        raise AIModelNotFoundException("No active AI model configured in database.")

    def _log_request(
        self,
        request_id: str,
        user_id: Optional[str],
        scene: str,
        provider_id: Optional[str],
        model_id: Optional[str],
        prompt_id: Optional[str],
        prompt_version: Optional[int],
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        status: str,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO ai_request_log (
                        id, request_id, user_id, scene, provider_id, model_id,
                        prompt_id, prompt_version, input_tokens, output_tokens,
                        latency_ms, status, error_code, error_message, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"log_{uuid.uuid4().hex[:12]}", request_id, user_id, scene, provider_id, model_id,
                        prompt_id, prompt_version, input_tokens, output_tokens,
                        latency_ms, status, error_code, error_message, now_iso
                    )
                )
                conn.commit()
        except Exception as exc:
            logger.warning(f"Failed to save AI request audit log: {exc}")

    async def chat(
        self,
        scene: str,
        messages: List[Dict[str, str]],
        *,
        model_id: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[Dict[str, Any]] = None,
        prompt_id: Optional[str] = None,
        prompt_version: Optional[int] = None,
        user_id: Optional[str] = None,
        sanitize_inputs: bool = True,
    ) -> Dict[str, Any]:
        request_id = self._generate_request_id()
        start_time = time.perf_counter()
        
        # 1. Sanitize messages
        if sanitize_inputs:
            processed_messages = sanitize_data(messages)
        else:
            processed_messages = messages

        # 2. Resolve model & fallback model
        target_model_id = model_id
        fallback_model_id = None
        if not target_model_id:
            target_model_id, fallback_model_id = model_router.resolve_route(scene)

        # Helper to execute call on candidate model
        async def _attempt_call(m_id: str) -> Dict[str, Any]:
            model_info = self._get_model_details(m_id)
            provider_inst = self._get_provider_instance(model_info["provider_id"])
            
            used_temp = temperature if temperature is not None else model_info["default_temperature"]
            used_tokens = max_tokens if max_tokens is not None else model_info["default_max_tokens"]
            
            # Retry loop with exponential backoff
            max_retries = provider_inst.max_retries
            last_err = None
            
            for attempt in range(max_retries + 1):
                try:
                    res = await provider_inst.chat(
                        processed_messages,
                        model=model_info["model_code"],
                        temperature=used_temp,
                        max_tokens=used_tokens,
                        tools=tools,
                        response_format=response_format,
                    )
                    res["provider_id"] = model_info["provider_id"]
                    res["model_id"] = model_info["id"]
                    return res
                except AIException as exc:
                    last_err = exc
                    if attempt < max_retries:
                        await asyncio.sleep(0.5 * (2 ** attempt))
                except Exception as exc:
                    last_err = AINetworkException(f"Unexpected error: {exc}")
                    if attempt < max_retries:
                        await asyncio.sleep(0.5 * (2 ** attempt))
            
            raise last_err

        # Execute primary attempt
        try:
            result = await _attempt_call(target_model_id)
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            
            # Audit log success
            self._log_request(
                request_id=request_id,
                user_id=user_id,
                scene=scene,
                provider_id=result.get("provider_id"),
                model_id=result.get("model_id"),
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                input_tokens=result.get("input_tokens", 0),
                output_tokens=result.get("output_tokens", 0),
                latency_ms=latency_ms,
                status="success"
            )
            result["request_id"] = request_id
            return result
            
        except Exception as primary_exc:
            logger.warning(f"Primary model '{target_model_id}' failed for scene '{scene}': {primary_exc}")
            
            # If fallback model is configured, attempt fallback
            if fallback_model_id and fallback_model_id != target_model_id:
                try:
                    logger.info(f"Attempting fallback model '{fallback_model_id}' for scene '{scene}'...")
                    result = await _attempt_call(fallback_model_id)
                    latency_ms = int((time.perf_counter() - start_time) * 1000)
                    
                    self._log_request(
                        request_id=request_id,
                        user_id=user_id,
                        scene=scene,
                        provider_id=result.get("provider_id"),
                        model_id=result.get("model_id"),
                        prompt_id=prompt_id,
                        prompt_version=prompt_version,
                        input_tokens=result.get("input_tokens", 0),
                        output_tokens=result.get("output_tokens", 0),
                        latency_ms=latency_ms,
                        status="success"
                    )
                    result["request_id"] = request_id
                    return result
                except Exception as fallback_exc:
                    primary_exc = fallback_exc

            # Log error
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            err_code = getattr(primary_exc, "code", "AI_INTERNAL_ERROR")
            err_msg = str(primary_exc)
            
            self._log_request(
                request_id=request_id,
                user_id=user_id,
                scene=scene,
                provider_id=None,
                model_id=target_model_id,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
                status="error",
                error_code=err_code,
                error_message=err_msg
            )
            
            if isinstance(primary_exc, AIException):
                primary_exc.request_id = request_id
                raise primary_exc
            raise AIException(code=err_code, message=err_msg, request_id=request_id)

    async def chat_stream(
        self,
        scene: str,
        messages: List[Dict[str, str]],
        *,
        model_id: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        user_id: Optional[str] = None,
    ):
        request_id = self._generate_request_id()
        start_time = time.perf_counter()

        target_model_id = model_id
        if not target_model_id:
            primary_id, _ = model_router.resolve_route(scene)
            target_model_id = primary_id

        model_info = self._get_model_details(target_model_id)
        provider_inst = self._get_provider_instance(model_info["provider_id"])
        
        used_temp = temperature if temperature is not None else model_info.get("default_temperature", 0.7)
        used_tokens = max_tokens if max_tokens is not None else model_info.get("default_max_tokens", 2048)

        processed_messages = sanitize_data(messages)
        full_content = []

        try:
            if hasattr(provider_inst, "chat_stream"):
                async for chunk in provider_inst.chat_stream(
                    processed_messages,
                    model=model_info["model_code"],
                    temperature=used_temp,
                    max_tokens=used_tokens,
                ):
                    full_content.append(chunk)
                    yield chunk
            else:
                res = await provider_inst.chat(
                    processed_messages,
                    model=model_info["model_code"],
                    temperature=used_temp,
                    max_tokens=used_tokens,
                )
                txt = res.get("content", "")
                full_content.append(txt)
                yield txt

            latency_ms = int((time.perf_counter() - start_time) * 1000)
            combined_txt = "".join(full_content)
            out_tok = max(1, len(combined_txt) // 3)
            in_tok = max(1, sum(len(m.get("content", "")) for m in messages) // 3)

            self._log_request(
                request_id=request_id,
                user_id=user_id,
                scene=scene,
                provider_id=model_info["provider_id"],
                model_id=model_info["id"],
                prompt_id=None,
                prompt_version=None,
                input_tokens=in_tok,
                output_tokens=out_tok,
                latency_ms=latency_ms,
                status="success"
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            self._log_request(
                request_id=request_id,
                user_id=user_id,
                scene=scene,
                provider_id=model_info.get("provider_id"),
                model_id=model_info.get("id"),
                prompt_id=None,
                prompt_version=None,
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
                status="error",
                error_code="STREAM_ERROR",
                error_message=str(exc)
            )
            raise exc


llm_gateway = LLMGateway()
