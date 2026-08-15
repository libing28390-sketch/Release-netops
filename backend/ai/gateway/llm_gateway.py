"""
LLM Gateway - Unified LLM Dispatcher with Model Routing, Sanitizer, Retry, Fallback, and Request Audit Logging
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database.core import get_db_connection
from ai.security.crypto import decrypt_api_key
from ai.security.gateway import AISecurityGateway, SecurityBlocked, ai_security_gateway
from ai.security.tokenization import opaque_user_id
from ai.gateway.exceptions import (
    AIException,
    AIModelNotFoundException,
    AINetworkException,
    AISecurityBlockedException,
)
from ai.gateway.router import model_router
from ai.providers.base import BaseLLMProvider
from ai.providers.deepseek import DeepSeekProvider
from ai.providers.openai_compatible import OpenAICompatibleProvider
from ai.services.metrics import ai_metrics

logger = logging.getLogger(__name__)


class LLMGateway:
    """Unified LLM Gateway service."""

    def __init__(self, security_gateway: AISecurityGateway | None = None):
        self.security_gateway = security_gateway or ai_security_gateway

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
                "SELECT m.id, m.provider_id, m.model_code, m.default_temperature, m.default_max_tokens, "
                "m.enabled, p.provider_type "
                "FROM ai_model m LEFT JOIN ai_provider p ON p.id = m.provider_id "
                "WHERE (m.id = ? OR m.model_code = ?) AND m.enabled = 1",
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
                    "provider_type": row[6] or "",
                }
            
            # If not found by ID or code, try any active default model
            cursor.execute(
                "SELECT m.id, m.provider_id, m.model_code, m.default_temperature, m.default_max_tokens, "
                "p.provider_type "
                "FROM ai_model m LEFT JOIN ai_provider p ON p.id = m.provider_id "
                "WHERE m.enabled = 1 ORDER BY m.is_default DESC, m.priority DESC LIMIT 1"
            )
            def_row = cursor.fetchone()
            if def_row:
                return {
                    "id": def_row[0],
                    "provider_id": def_row[1],
                    "model_code": def_row[2],
                    "default_temperature": def_row[3],
                    "default_max_tokens": def_row[4],
                    "provider_type": def_row[5] or "",
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
        ai_metrics.request_finished(scene, status=status, latency_ms=latency_ms)
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

    def _log_security_audit(
        self,
        *,
        request_id: str,
        tenant_id: str,
        task_id: str,
        scene: str,
        provider_type: str | None,
        model_code: str | None,
        decision: str,
        max_data_level: str | None = None,
        finding_categories: list[str] | None = None,
        payload_bytes: int = 0,
        status: str,
        error_code: str | None = None,
    ) -> None:
        """Persist metadata-only egress evidence; never persist body content."""
        try:
            with get_db_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO ai_outbound_audits
                        (id, request_id, tenant_id, task_id, scene, provider_type,
                         model_code, decision, max_data_level,
                         finding_categories_json, payload_bytes, status, error_code, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"out_{uuid.uuid4().hex[:16]}", request_id, tenant_id, task_id,
                        scene, provider_type, model_code, decision, max_data_level,
                        json.dumps(sorted(set(finding_categories or [])), ensure_ascii=False),
                        max(0, int(payload_bytes or 0)), status, error_code,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                conn.commit()
        except Exception:
            # The request log remains useful on installations before m0105;
            # an audit-table failure must never open the external egress path.
            logger.debug("Failed to save AI security audit metadata", exc_info=True)

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
        tenant_id: Optional[str] = None,
        task_id: Optional[str] = None,
        thinking: bool = False,
        reasoning_effort: Optional[str] = None,
        sanitize_inputs: bool = True,
    ) -> Dict[str, Any]:
        request_id = self._generate_request_id()
        start_time = time.perf_counter()
        ai_metrics.request_started(scene)

        # Check the egress gate before consulting model/provider configuration.
        # A disabled or killed gateway must fail closed even when the database
        # has no active model, and must not reveal provider configuration.
        if self.security_gateway.policy.kill_switch or not self.security_gateway.policy.external_ai_enabled:
            blocked = AISecurityBlockedException("AI request blocked by security policy")
            blocked.request_id = request_id
            self._log_request(
                request_id=request_id,
                user_id=opaque_user_id(user_id, tenant_id=tenant_id or "tenant-default", task_id=task_id or request_id),
                scene=scene,
                provider_id=None,
                model_id=model_id,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                status="blocked",
                error_code="AI_SECURITY_BLOCKED",
                error_message="policy_block",
            )
            self._log_security_audit(
                request_id=request_id,
                tenant_id=tenant_id or "tenant-default",
                task_id=task_id or request_id,
                scene=scene,
                provider_type=None,
                model_code=model_id,
                decision="BLOCK",
                status="blocked",
                error_code="AI_SECURITY_BLOCKED",
            )
            raise blocked

        # Resolve the target before constructing an outbound body.  The
        # security gateway is the only component allowed to transform model
        # input; `sanitize_inputs=False` is retained for API compatibility but
        # can no longer bypass policy.
        target_model_id = model_id
        fallback_model_id = None
        if not target_model_id:
            target_model_id, fallback_model_id = model_router.resolve_route(scene)

        target_info = self._get_model_details(target_model_id)
        if fallback_model_id:
            try:
                fallback_info = self._get_model_details(fallback_model_id)
                allowed_types = {item.lower() for item in self.security_gateway.policy.allowed_provider_types}
                if str(fallback_info.get("provider_type") or "").lower() not in allowed_types:
                    # A route fallback is still an external egress. Never let
                    # it bypass the same provider allowlist as the primary.
                    fallback_model_id = None
            except AIException:
                fallback_model_id = None
        tenant = tenant_id or "tenant-default"
        task = task_id or request_id
        try:
            secure_payload = self.security_gateway.protect(
                messages,
                tenant_id=tenant,
                task_id=task,
                user_id=user_id,
                tools=tools,
                provider_options={
                    "response_format": response_format,
                    "thinking": thinking,
                    "reasoning_effort": reasoning_effort,
                },
                provider_type=target_info.get("provider_type") or "deepseek",
            )
        except SecurityBlocked as exc:
            self._log_request(
                request_id=request_id,
                user_id=opaque_user_id(user_id, tenant_id=tenant, task_id=task),
                scene=scene,
                provider_id=target_info.get("provider_id"),
                model_id=target_info.get("id"),
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                input_tokens=0,
                output_tokens=0,
                latency_ms=int((time.perf_counter() - start_time) * 1000),
                status="blocked",
                error_code="AI_SECURITY_BLOCKED",
                error_message="policy_block",
            )
            self._log_security_audit(
                request_id=request_id,
                tenant_id=tenant,
                task_id=task,
                scene=scene,
                provider_type=target_info.get("provider_type"),
                model_code=target_info.get("model_code"),
                decision="BLOCK",
                max_data_level=(f"L{max(int(item.level) for item in exc.findings)}" if exc.findings else None),
                finding_categories=[item.category for item in exc.findings],
                status="blocked",
                error_code="AI_SECURITY_BLOCKED",
            )
            blocked = AISecurityBlockedException("AI request blocked by security policy")
            blocked.request_id = request_id
            raise blocked from exc

        processed_messages = secure_payload.messages
        processed_tools = secure_payload.tools
        provider_user_id = secure_payload.user_id
        self._log_security_audit(
            request_id=request_id,
            tenant_id=tenant,
            task_id=task,
            scene=scene,
            provider_type=target_info.get("provider_type"),
            model_code=target_info.get("model_code"),
            decision=secure_payload.action.value,
            max_data_level=f"L{int(secure_payload.level)}",
            finding_categories=[item.category for item in secure_payload.findings],
            payload_bytes=len(secure_payload.as_provider_json().encode("utf-8")),
            status="prepared",
        )

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
                        tools=processed_tools,
                        response_format=secure_payload.provider_options.get("response_format"),
                        thinking=bool(secure_payload.provider_options.get("thinking")),
                        reasoning_effort=secure_payload.provider_options.get("reasoning_effort"),
                        user_id=provider_user_id,
                    )
                    res["provider_id"] = model_info["provider_id"]
                    res["model_id"] = model_info["id"]
                    return res
                except AIException as exc:
                    last_err = exc
                    if attempt < max_retries:
                        await asyncio.sleep(0.5 * (2 ** attempt))
                except Exception as exc:
                    # Provider exceptions may contain response bodies or input
                    # fragments. Keep them out of the persisted/public error.
                    last_err = AINetworkException("Unexpected provider error")
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
                user_id=provider_user_id,
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
            if result.get("content"):
                result["content"] = self.security_gateway.resolve_output(
                    result["content"], tenant_id=tenant, task_id=task
                )
            # Chain-of-thought is retained by the provider/audit layer only;
            # never expose it through the general chat response contract.
            result.pop("reasoning_content", None)
            result.pop("raw", None)
            return result
            
        except Exception as primary_exc:
            logger.warning("Primary AI model failed for scene=%s code=%s", scene, getattr(primary_exc, "code", "AI_INTERNAL_ERROR"))

            if isinstance(primary_exc, AISecurityBlockedException):
                primary_exc.request_id = request_id
                raise primary_exc
            
            # If fallback model is configured, attempt fallback
            if fallback_model_id and fallback_model_id != target_model_id:
                try:
                    logger.info("Attempting fallback AI model for scene=%s", scene)
                    result = await _attempt_call(fallback_model_id)
                    latency_ms = int((time.perf_counter() - start_time) * 1000)
                    
                    self._log_request(
                        request_id=request_id,
                        user_id=provider_user_id,
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
                    if result.get("content"):
                        result["content"] = self.security_gateway.resolve_output(
                            result["content"], tenant_id=tenant, task_id=task
                        )
                    result.pop("reasoning_content", None)
                    result.pop("raw", None)
                    return result
                except Exception as fallback_exc:
                    primary_exc = fallback_exc

            # Log error
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            err_code = getattr(primary_exc, "code", "AI_INTERNAL_ERROR")
            # Persist only a stable code. Provider response bodies can contain
            # secrets or prompt data and are never suitable for an audit row.
            err_msg = "provider_request_failed"
            
            self._log_request(
                request_id=request_id,
                user_id=provider_user_id,
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
        tenant_id: Optional[str] = None,
        task_id: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        response_format: Optional[Dict[str, Any]] = None,
        thinking: bool = False,
        reasoning_effort: Optional[str] = None,
    ):
        request_id = self._generate_request_id()
        start_time = time.perf_counter()
        ai_metrics.request_started(scene)

        if self.security_gateway.policy.kill_switch or not self.security_gateway.policy.external_ai_enabled:
            blocked = AISecurityBlockedException("AI request blocked by security policy")
            blocked.request_id = request_id
            self._log_request(
                request_id=request_id,
                user_id=opaque_user_id(user_id, tenant_id=tenant_id or "tenant-default", task_id=task_id or request_id),
                scene=scene,
                provider_id=None,
                model_id=model_id,
                prompt_id=None,
                prompt_version=None,
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                status="blocked",
                error_code="AI_SECURITY_BLOCKED",
                error_message="policy_block",
            )
            raise blocked

        target_model_id = model_id
        if not target_model_id:
            primary_id, _ = model_router.resolve_route(scene)
            target_model_id = primary_id

        model_info = self._get_model_details(target_model_id)
        
        used_temp = temperature if temperature is not None else model_info.get("default_temperature", 0.7)
        used_tokens = max_tokens if max_tokens is not None else model_info.get("default_max_tokens", 2048)

        tenant = tenant_id or "tenant-default"
        task = task_id or request_id
        try:
            secure_payload = self.security_gateway.protect(
                messages,
                tenant_id=tenant,
                task_id=task,
                user_id=user_id,
                tools=tools,
                provider_options={
                    "response_format": response_format,
                    "thinking": thinking,
                    "reasoning_effort": reasoning_effort,
                },
                provider_type=model_info.get("provider_type") or "deepseek",
            )
        except SecurityBlocked as exc:
            blocked = AISecurityBlockedException("AI request blocked by security policy")
            blocked.request_id = request_id
            self._log_request(
                request_id=request_id,
                user_id=opaque_user_id(user_id, tenant_id=tenant, task_id=task),
                scene=scene,
                provider_id=model_info.get("provider_id"),
                model_id=model_info.get("id"),
                prompt_id=None,
                prompt_version=None,
                input_tokens=0,
                output_tokens=0,
                latency_ms=int((time.perf_counter() - start_time) * 1000),
                status="blocked",
                error_code="AI_SECURITY_BLOCKED",
                error_message="policy_block",
            )
            self._log_security_audit(
                request_id=request_id,
                tenant_id=tenant,
                task_id=task,
                scene=scene,
                provider_type=model_info.get("provider_type"),
                model_code=model_info.get("model_code"),
                decision="BLOCK",
                max_data_level=(f"L{max(int(item.level) for item in exc.findings)}" if exc.findings else None),
                finding_categories=[item.category for item in exc.findings],
                status="blocked",
                error_code="AI_SECURITY_BLOCKED",
            )
            raise blocked from exc

        processed_messages = secure_payload.messages
        full_content = []
        self._log_security_audit(
            request_id=request_id,
            tenant_id=tenant,
            task_id=task,
            scene=scene,
            provider_type=model_info.get("provider_type"),
            model_code=model_info.get("model_code"),
            decision=secure_payload.action.value,
            max_data_level=f"L{int(secure_payload.level)}",
            finding_categories=[item.category for item in secure_payload.findings],
            payload_bytes=len(secure_payload.as_provider_json().encode("utf-8")),
            status="prepared",
        )

        try:
            provider_inst = self._get_provider_instance(model_info["provider_id"])
            if hasattr(provider_inst, "chat_stream"):
                async for chunk in provider_inst.chat_stream(
                    processed_messages,
                    model=model_info["model_code"],
                    temperature=used_temp,
                    max_tokens=used_tokens,
                    tools=secure_payload.tools,
                    response_format=secure_payload.provider_options.get("response_format"),
                    thinking=bool(secure_payload.provider_options.get("thinking")),
                    reasoning_effort=secure_payload.provider_options.get("reasoning_effort"),
                    user_id=secure_payload.user_id,
                ):
                    full_content.append(chunk)
                    yield self.security_gateway.resolve_output(chunk, tenant_id=tenant, task_id=task)
            else:
                res = await provider_inst.chat(
                    processed_messages,
                    model=model_info["model_code"],
                    temperature=used_temp,
                    max_tokens=used_tokens,
                    tools=secure_payload.tools,
                    response_format=secure_payload.provider_options.get("response_format"),
                    thinking=bool(secure_payload.provider_options.get("thinking")),
                    reasoning_effort=secure_payload.provider_options.get("reasoning_effort"),
                    user_id=secure_payload.user_id,
                )
                txt = res.get("content", "")
                full_content.append(txt)
                yield self.security_gateway.resolve_output(txt, tenant_id=tenant, task_id=task)

            latency_ms = int((time.perf_counter() - start_time) * 1000)
            combined_txt = "".join(full_content)
            out_tok = max(1, len(combined_txt) // 3)
            in_tok = max(1, sum(len(m.get("content", "")) for m in messages) // 3)

            self._log_request(
                request_id=request_id,
                user_id=secure_payload.user_id,
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
                user_id=secure_payload.user_id,
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
                error_message="stream_request_failed"
            )
            raise exc


llm_gateway = LLMGateway()
