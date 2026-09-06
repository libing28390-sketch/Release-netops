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
from fnmatch import fnmatchcase
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from database.core import get_db_connection
from ai.security.crypto import decrypt_api_key
from ai.security.gateway import AISecurityGateway, SecurityBlocked, ai_security_gateway
from ai.security.output import StreamingOutputResolver
from ai.security.tokenization import opaque_user_id
from ai.security.sanitizer import sanitize_log_text
from ai.security.security_service import create_security_incident, record_security_event
from ai.gateway.exceptions import (
    AIException,
    AIBudgetExceededException,
    AIAuthFailedException,
    AICircuitOpenException,
    AIInvalidRequestException,
    AIModelNotFoundException,
    AINetworkException,
    AIOutputTruncatedException,
    AIProviderUnsupportedException,
    AIQuotaExceededException,
    AISecurityBlockedException,
)
from ai.gateway.router import model_router
from ai.gateway.limits import ai_limits
from core.config import settings
from core.context import request_id_var, resolve_request_id
from ai.providers.base import BaseLLMProvider
from ai.providers.registry import provider_adapter
from ai.services.metrics import ai_metrics

logger = logging.getLogger(__name__)


def _resolve_approved_endpoint_patterns(raw_patterns: Any, base_url: Any, provider_type: Any) -> list[str]:
    """Normalize the persisted endpoint allowlist with a legacy-safe fallback.

    Older Provider rows may have been created before the endpoint allowlist
    column existed, or may have been written after the one-time backfill ran.
    A configured Base URL is already the operator-selected destination, so an
    empty allowlist can safely fall back to that exact URL.  This never creates
    a wildcard and does not apply to local providers, which do not use the
    cloud egress allowlist.
    """

    if isinstance(raw_patterns, list):
        candidates = raw_patterns
    else:
        try:
            parsed = json.loads(raw_patterns or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = []
        candidates = parsed if isinstance(parsed, list) else []

    patterns = [
        str(item).strip().rstrip("/")
        for item in candidates
        if item is not None and str(item).strip()
    ]
    if patterns:
        return patterns

    normalized_type = str(provider_type or "").lower().replace("-", "_")
    normalized_base_url = str(base_url or "").strip().rstrip("/")
    parsed_base_url = urlparse(normalized_base_url)
    if (
        normalized_type not in {"local", "ollama"}
        and parsed_base_url.scheme.lower() == "https"
        and parsed_base_url.hostname
    ):
        return [normalized_base_url]
    return []


class LLMGateway:
    """Unified LLM Gateway service."""

    def __init__(self, security_gateway: AISecurityGateway | None = None):
        self.security_gateway = security_gateway or ai_security_gateway

    def _generate_request_id(self, request_id: Optional[str] = None) -> str:
        """Reuse the API correlation id, or create one for direct callers."""

        return resolve_request_id(request_id or request_id_var.get("-"), prefix="ai_req")

    def _get_provider_instance(self, provider_id: str) -> BaseLLMProvider:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT id, name, provider_type, base_url, api_key_encrypted, timeout, max_retries, proxy_url, enabled, approved_endpoint_patterns_json "
                    "FROM ai_provider WHERE id = ?",
                    (provider_id,)
                )
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, name, provider_type, base_url, api_key_encrypted, timeout, max_retries, proxy_url, enabled, '[]' "
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

            provider_type = str(p_data["provider_type"] or "").lower().replace("-", "_")
            raw_patterns = row[9] if len(row) > 9 else "[]"
            endpoint_patterns = _resolve_approved_endpoint_patterns(
                raw_patterns,
                p_data.get("base_url"),
                provider_type,
            )
            if provider_type not in {"local", "ollama"}:
                base_url = str(p_data.get("base_url") or "").rstrip("/")
                if not endpoint_patterns or not any(fnmatchcase(base_url, pattern) for pattern in endpoint_patterns):
                    raise AIProviderUnsupportedException("Provider endpoint is not covered by the approved egress allowlist")
            
            plain_api_key = decrypt_api_key(row[4])
            
            try:
                adapter = provider_adapter(str(p_data["provider_type"] or ""))
            except ValueError as exc:
                raise AIProviderUnsupportedException() from exc
            return adapter(p_data, api_key=plain_api_key)

    def _get_model_details(self, model_id_or_code: str) -> Dict[str, Any]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT m.id, m.provider_id, m.model_code, m.default_temperature, m.default_max_tokens, "
                    "m.enabled, p.provider_type, m.model_type, m.thinking_supported, m.tool_call_supported, "
                    "m.json_supported, m.stream_supported, p.allowed_data_classification, p.data_region, "
                    "p.no_training_confirmed, p.retention_days, p.data_processing_agreement_ref, "
                    "p.agreement_reviewed_at, p.approved_endpoint_patterns_json, "
                    "m.context_length, m.max_output_tokens, m.cost_input_per_1k, m.cost_output_per_1k "
                    "FROM ai_model m LEFT JOIN ai_provider p ON p.id = m.provider_id "
                    "WHERE (m.id = ? OR m.model_code = ?) AND m.enabled = 1 AND COALESCE(p.enabled, 0) = 1",
                    (model_id_or_code, model_id_or_code)
                )
            except Exception:
                # Legacy installations are allowed to read the old shape, but
                # production PostgreSQL runs m0139 and uses the extended row.
                # PostgreSQL marks the transaction failed after an undefined
                # column error, so clear that state before the compatibility
                # query rather than masking the original fallback path.
                try:
                    conn.rollback()
                except Exception:
                    pass
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT m.id, m.provider_id, m.model_code, m.default_temperature, m.default_max_tokens, "
                    "m.enabled, p.provider_type, m.model_type, m.thinking_supported, m.tool_call_supported, "
                    "m.json_supported, 1, COALESCE(p.allowed_data_classification, 'CONFIDENTIAL'), 'unknown', "
                    "0, NULL, NULL, NULL, '[]', 32768, 4096, 0, 0 "
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
                    "model_type": row[7] or "chat",
                    "thinking_supported": bool(row[8]),
                    "tool_call_supported": bool(row[9]),
                    "json_supported": bool(row[10]),
                    "stream_supported": bool(row[11] if row[11] is not None else True),
                    "allowed_data_classification": row[12] or "PUBLIC",
                    "data_region": row[13] or "unknown",
                    "no_training_confirmed": bool(row[14]),
                    "retention_days": int(row[15]) if row[15] is not None else None,
                    "data_processing_agreement_ref": row[16],
                    "agreement_reviewed_at": row[17],
                    "approved_endpoint_patterns": row[18],
                    "context_length": int(row[19] or 32768),
                    "max_output_tokens": int(row[20] or 4096),
                    "cost_input_per_1k": float(row[21] or 0),
                    "cost_output_per_1k": float(row[22] or 0),
                }
            
            # If not found by ID or code, try any active default model
            try:
                cursor.execute(
                    "SELECT m.id, m.provider_id, m.model_code, m.default_temperature, m.default_max_tokens, "
                    "p.provider_type, m.model_type, m.thinking_supported, m.tool_call_supported, m.json_supported, m.stream_supported, "
                    "p.allowed_data_classification, p.data_region, p.no_training_confirmed, p.retention_days, "
                    "p.data_processing_agreement_ref, p.agreement_reviewed_at, p.approved_endpoint_patterns_json, "
                    "m.context_length, m.max_output_tokens, m.cost_input_per_1k, m.cost_output_per_1k "
                    "FROM ai_model m LEFT JOIN ai_provider p ON p.id = m.provider_id "
                    "WHERE m.enabled = 1 AND COALESCE(p.enabled, 0) = 1 ORDER BY m.is_default DESC, m.priority DESC LIMIT 1"
                )
            except Exception:
                cursor.execute(
                    "SELECT m.id, m.provider_id, m.model_code, m.default_temperature, m.default_max_tokens, "
                    "p.provider_type, m.model_type, m.thinking_supported, m.tool_call_supported, m.json_supported, 1, 'PUBLIC', 'unknown', "
                    "0, NULL, NULL, NULL, '[]', 32768, 4096, 0, 0 "
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
                    "model_type": def_row[6] or "chat",
                    "thinking_supported": bool(def_row[7]),
                    "tool_call_supported": bool(def_row[8]),
                    "json_supported": bool(def_row[9]),
                    "stream_supported": bool(def_row[10] if def_row[10] is not None else True),
                    "allowed_data_classification": def_row[11] or "PUBLIC",
                    "data_region": def_row[12] or "unknown",
                    "no_training_confirmed": bool(def_row[13]),
                    "retention_days": int(def_row[14]) if def_row[14] is not None else None,
                    "data_processing_agreement_ref": def_row[15],
                    "agreement_reviewed_at": def_row[16],
                    "approved_endpoint_patterns": def_row[17],
                    "context_length": int(def_row[18] or 32768),
                    "max_output_tokens": int(def_row[19] or 4096),
                    "cost_input_per_1k": float(def_row[20] or 0),
                    "cost_output_per_1k": float(def_row[21] or 0),
                }
        
        raise AIModelNotFoundException("No active AI model configured in database.")

    def _authorize_model(self, model_info: Dict[str, Any], *, tenant_id: str, user_id: Optional[str], roles: Optional[List[str]]) -> None:
        """Enforce model visibility without leaking ACL or provider details."""
        try:
            with get_db_connection() as conn:
                rows = conn.execute(
                    "SELECT subject_type, subject_id, allow_access FROM ai_model_acl WHERE model_id = ? AND tenant_id = ?",
                    (model_info["id"], tenant_id),
                ).fetchall()
        except Exception:
            # V1 installations before m0139 have no ACL table; preserve their
            # existing visibility behavior until the migration is applied.
            rows = []
        if not rows:
            return
        subjects = {("user", str(user_id or "")), ("tenant", str(tenant_id))}
        subjects.update(("role", str(role)) for role in (roles or []))
        matching = [row for row in rows if (str(row[0]), str(row[1])) in subjects]
        if not matching or not any(bool(row[2]) for row in matching):
            raise AIModelNotFoundException("Requested AI model is not available for this user")

    def _get_user_default_model(self, *, tenant_id: str, user_id: Optional[str], roles: Optional[List[str]]) -> Optional[str]:
        if not user_id:
            return None
        try:
            opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id="model-preference")
            with get_db_connection() as conn:
                row = conn.execute("SELECT p.model_id FROM ai_user_model_preference p JOIN ai_model m ON m.id = p.model_id JOIN ai_provider v ON v.id = m.provider_id WHERE p.tenant_id = ? AND p.user_id_opaque = ? AND p.enabled = 1 AND m.enabled = 1 AND v.enabled = 1", (tenant_id, opaque)).fetchone()
            return str(row[0]) if row else None
        except Exception:
            return None

    @staticmethod
    def _apply_model_capabilities(model_info: Dict[str, Any], *, tools, response_format, thinking, reasoning_effort):
        if model_info.get("model_type") in {"embedding", "rerank"}:
            raise AIModelNotFoundException("Selected model is not a chat-capable model")
        return (
            tools if model_info.get("tool_call_supported", True) else None,
            response_format if model_info.get("json_supported", True) else None,
            bool(thinking and model_info.get("thinking_supported", False)),
            reasoning_effort if model_info.get("thinking_supported", False) else None,
        )

    @staticmethod
    def _classification_rank(value: str | None) -> int:
        return {"PUBLIC": 1, "INTERNAL": 2, "CONFIDENTIAL": 3, "SECRET": 4}.get(str(value or "PUBLIC").upper(), 0)

    @staticmethod
    def _is_local_provider(model_info: Dict[str, Any]) -> bool:
        return str(model_info.get("provider_type") or "").lower().replace("-", "_") in {"local", "ollama"}

    def _fallback_is_compatible(
        self,
        primary: Dict[str, Any],
        fallback: Dict[str, Any],
        *,
        data_classification: str | None = None,
    ) -> bool:
        """A fallback may not downgrade the data classification boundary."""
        if fallback.get("model_type") in {"embedding", "rerank"}:
            return False
        if not fallback.get("stream_supported", True) and primary.get("stream_required"):
            return False
        requested_rank = self._classification_rank(data_classification)
        if requested_rank >= self._classification_rank("CONFIDENTIAL") and not self._is_local_provider(fallback):
            return False
        return self._classification_rank(fallback.get("allowed_data_classification")) >= max(
            self._classification_rank(primary.get("allowed_data_classification")), requested_rank
        )

    def _budget_exceeded(self, *, provider_id: str, model_id: str) -> bool:
        budget = float(getattr(settings, "AI_DAILY_BUDGET_USD", 0) or 0)
        if budget <= 0:
            return False
        today = datetime.now(timezone.utc).date().isoformat()
        try:
            with get_db_connection() as conn:
                row = conn.execute(
                    "SELECT COALESCE(SUM(estimated_cost), 0) FROM ai_usage_daily WHERE date = ? AND provider_id = ? AND model_id = ?",
                    (today, provider_id, model_id),
                ).fetchone()
            return float(row[0] or 0) >= budget if row else False
        except Exception:
            # Budget enforcement must fail closed only when a budget is
            # explicitly configured; an unavailable legacy usage table is not
            # allowed to block an otherwise healthy V1 deployment by default.
            return bool(budget > 0 and getattr(settings, "AI_BUDGET_FAIL_CLOSED", False))

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
        ai_metrics.provider_finished(
            provider_id,
            model_id,
            status=status,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error_code=error_code,
        )
        try:
            now = datetime.now(timezone.utc).isoformat()
            with get_db_connection() as health_conn:
                if provider_id:
                    health_conn.execute(
                        "UPDATE ai_provider SET health_status = ?, last_success_at = CASE WHEN ? = 'healthy' THEN ? ELSE last_success_at END, last_error_code = CASE WHEN ? = 'healthy' THEN NULL ELSE ? END, last_health_check_at = ?, last_error_at = CASE WHEN ? = 'healthy' THEN last_error_at ELSE ? END WHERE id = ?",
                        ("healthy" if status == "success" else "unhealthy", status, now, status, error_code, now, status, now, provider_id),
                    )
                if model_id:
                    health_conn.execute("UPDATE ai_model SET health_status = ?, last_latency_ms = ?, last_success_at = CASE WHEN ? = 'healthy' THEN ? ELSE last_success_at END, last_error_code = CASE WHEN ? = 'healthy' THEN NULL ELSE ? END WHERE id = ?", ("healthy" if status == "success" else "unhealthy", max(0, int(latency_ms or 0)), status, now, status, error_code, model_id))
                health_conn.commit()
        except Exception:
            logger.debug("Failed to update provider/model health code=AI_HEALTH_WRITE_FAILED")
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
        except Exception:
            logger.warning("Failed to save AI request audit log code=AI_REQUEST_AUDIT_WRITE_FAILED")
        # Keep the durable daily cost/usage read model separate from the
        # request audit row.  It contains counters only; never prompt text or
        # provider response bodies.
        if provider_id and model_id:
            try:
                now_iso = datetime.now(timezone.utc).isoformat()
                date_key = datetime.now(timezone.utc).date().isoformat()
                with get_db_connection() as usage_conn:
                    price = usage_conn.execute(
                        "SELECT cost_input_per_1k, cost_output_per_1k FROM ai_model WHERE id = ?",
                        (model_id,),
                    ).fetchone()
                    input_rate = float(price[0] or 0) if price else 0.0
                    output_rate = float(price[1] or 0) if price else 0.0
                    cost = (max(0, int(input_tokens or 0)) / 1000.0) * input_rate + (max(0, int(output_tokens or 0)) / 1000.0) * output_rate
                    ai_metrics.provider_cost(provider_id, model_id, cost)
                    row = usage_conn.execute(
                        "SELECT id, requests, input_tokens, output_tokens, estimated_cost, success_count, error_count, avg_latency FROM ai_usage_daily WHERE date = ? AND provider_id = ? AND model_id = ? AND scene = ?",
                        (date_key, provider_id, model_id, scene),
                    ).fetchone()
                    if row:
                        requests = int(row[1] or 0) + 1
                        successes = int(row[5] or 0) + (1 if status == "success" else 0)
                        errors = int(row[6] or 0) + (0 if status == "success" else 1)
                        usage_conn.execute(
                            "UPDATE ai_usage_daily SET requests = ?, input_tokens = ?, output_tokens = ?, estimated_cost = ?, success_count = ?, error_count = ?, avg_latency = ?, created_at = ? WHERE id = ?",
                            (requests, int(row[2] or 0) + max(0, int(input_tokens or 0)), int(row[3] or 0) + max(0, int(output_tokens or 0)), float(row[4] or 0) + cost, successes, errors, (float(row[7] or 0) * (requests - 1) + max(0, int(latency_ms or 0))) / requests, now_iso, row[0]),
                        )
                    else:
                        usage_conn.execute(
                            "INSERT INTO ai_usage_daily (id, date, provider_id, model_id, scene, requests, input_tokens, output_tokens, estimated_cost, success_count, error_count, avg_latency, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (f"usage_{uuid.uuid4().hex[:16]}", date_key, provider_id, model_id, scene, 1, max(0, int(input_tokens or 0)), max(0, int(output_tokens or 0)), cost, 1 if status == "success" else 0, 0 if status == "success" else 1, max(0, int(latency_ms or 0)), now_iso),
                        )
                    usage_conn.commit()
            except Exception:
                logger.debug("Failed to update AI daily usage counters code=AI_USAGE_WRITE_FAILED")

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
            logger.debug("Failed to save AI security audit metadata code=AI_SECURITY_AUDIT_WRITE_FAILED")
        try:
            level = str(max_data_level or "L1").upper()
            classification = {"L0": "PUBLIC", "L1": "INTERNAL", "L2": "CONFIDENTIAL", "L3": "SECRET", "L4": "SECRET"}.get(level, "INTERNAL")
            record_security_event(
                request_id=request_id,
                tenant_id=tenant_id,
                policy_version=self.security_gateway.policy.policy_version,
                classification=classification,
                data_region="unknown",
                decision=decision if decision in {"ALLOW", "MINIMIZE", "TOKENIZE", "BLOCK"} else "BLOCK",
                disposition="blocked" if status == "blocked" else ("sent" if status in {"success", "completed"} else "prepared"),
                finding_categories=finding_categories or (),
                provider_id=provider_type,
                model_id=model_code,
                payload_bytes=payload_bytes,
                error_code=error_code,
            )
            if status == "blocked" or decision == "BLOCK":
                create_security_incident(
                    tenant_id=tenant_id,
                    incident_type="policy_violation",
                    severity="high",
                    category="gateway",
                    task_id=task_id,
                    request_id=request_id,
                    evidence={
                        "request_id": request_id,
                        "provider_id": provider_type,
                        "model_id": model_code,
                        "classification": classification,
                        "decision": decision,
                        "error_code": error_code,
                        "finding_categories": finding_categories or (),
                    },
                )
        except Exception:
            logger.debug("Failed to save extended security event code=AI_SECURITY_EVENT_WRITE_FAILED")

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
        roles: Optional[List[str]] = None,
        selection_source: Optional[str] = None,
        task_id: Optional[str] = None,
        thinking: bool = False,
        reasoning_effort: Optional[str] = None,
        sanitize_inputs: bool = True,
        workspace_id: Optional[str] = None,
        site_id: Optional[str] = None,
        department: Optional[str] = None,
        document_scope: Optional[str] = None,
        request_id: Optional[str] = None,
        data_classification: Optional[str] = None,
        route_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        request_id = self._generate_request_id(request_id)
        start_time = time.perf_counter()
        ai_metrics.request_started(scene)

        # Check the egress gate before consulting model/provider configuration.
        # A disabled or killed gateway must fail closed even when the database
        # has no active model, and must not reveal provider configuration.
        if self.security_gateway.policy.kill_switch or not self.security_gateway.policy.external_ai_enabled:
            blocked = AISecurityBlockedException("AI request blocked by security policy")
            blocked.request_id = request_id
            if route_meta is not None:
                route_meta.update({"request_id": request_id, "status": "blocked", "security_result": "blocked", "security": {"decision": "block", "result_code": "AI_SECURITY_BLOCKED"}, "latency_ms": 0, "input_tokens": 0, "output_tokens": 0})
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
        requested_model_id = model_id
        route_reason = selection_source or ("message_explicit_model" if model_id else "scene_route_or_system_default")
        target_model_id = model_id
        fallback_model_id = None
        if not target_model_id:
            user_default = self._get_user_default_model(tenant_id=tenant_id or "tenant-default", user_id=user_id, roles=roles)
            if user_default:
                target_model_id = user_default
                route_reason = "user_default_model"
            else:
                target_model_id, fallback_model_id, route_reason = model_router.resolve_route_with_reason(scene)

        target_info = self._get_model_details(target_model_id)
        self._authorize_model(target_info, tenant_id=tenant_id or "tenant-default", user_id=user_id, roles=roles)
        if route_meta is not None:
            route_meta.update({
                "requested_model_id": requested_model_id,
                "model_id": target_info.get("id"),
                "provider_id": target_info.get("provider_id"),
                "route_reason": route_reason,
                "fallback_used": False,
                "external_egress": False,
                "request_id": request_id,
            })
        tools, response_format, thinking, reasoning_effort = self._apply_model_capabilities(
            target_info, tools=tools, response_format=response_format, thinking=thinking, reasoning_effort=reasoning_effort
        )
        fallback_info: Dict[str, Any] | None = None
        if fallback_model_id:
            try:
                fallback_info = self._get_model_details(fallback_model_id)
                self._authorize_model(fallback_info, tenant_id=tenant_id or "tenant-default", user_id=user_id, roles=roles)
                allowed_types = {item.lower() for item in self.security_gateway.policy.allowed_provider_types}
                if str(fallback_info.get("provider_type") or "").lower() not in allowed_types:
                    # A route fallback is still an external egress. Never let
                    # it bypass the same provider allowlist as the primary.
                    fallback_model_id = None
                elif not self._fallback_is_compatible(
                    target_info,
                    fallback_info,
                    data_classification=data_classification,
                ):
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
                provider_id=target_info.get("provider_id"),
                model_id=target_info.get("id"),
                data_classification=data_classification,
                data_region=target_info.get("data_region"),
                provider_allowed_classification=target_info.get("allowed_data_classification"),
                provider_no_training_confirmed=bool(target_info.get("no_training_confirmed")),
                provider_retention_days=target_info.get("retention_days"),
                provider_data_processing_agreement_ref=target_info.get("data_processing_agreement_ref"),
                workspace_id=workspace_id,
                site_id=site_id,
                department=department,
                document_scope=document_scope,
                user_role=(roles or [None])[0],
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
                error_code=getattr(exc, "reason_code", "AI_SECURITY_BLOCKED"),
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
                error_code=getattr(exc, "reason_code", "AI_SECURITY_BLOCKED"),
            )
            blocked = AISecurityBlockedException(
                "AI request blocked by security policy",
                code=getattr(exc, "reason_code", "AI_SECURITY_BLOCKED"),
            )
            blocked.request_id = request_id
            raise blocked from exc

        # `protect` derives a classification when the caller did not provide
        # one explicitly.  Re-check the already-loaded fallback against that
        # effective classification before any provider attempt; otherwise a
        # route fallback could reuse a sanitized payload but still violate the
        # local-only CONFIDENTIAL/SECRET or assured-INTERNAL boundary.
        effective_classification = str(
            (secure_payload.metadata or {}).get("classification") or data_classification or "PUBLIC"
        )
        if fallback_model_id and fallback_info and not self._fallback_is_compatible(
            target_info,
            fallback_info,
            data_classification=effective_classification,
        ):
            fallback_model_id = None

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
            self._authorize_model(model_info, tenant_id=tenant, user_id=user_id, roles=roles)
            if self._budget_exceeded(provider_id=model_info["provider_id"], model_id=model_info["id"]):
                raise AIBudgetExceededException()
            provider_inst = self._get_provider_instance(model_info["provider_id"])
            call_tools, call_response_format, call_thinking, call_reasoning = self._apply_model_capabilities(
                model_info,
                tools=processed_tools,
                response_format=secure_payload.provider_options.get("response_format"),
                thinking=bool(secure_payload.provider_options.get("thinking")),
                reasoning_effort=secure_payload.provider_options.get("reasoning_effort"),
            )
            
            used_temp = temperature if temperature is not None else model_info["default_temperature"]
            used_tokens = max_tokens if max_tokens is not None else model_info["default_max_tokens"]
            
            # Retry loop with exponential backoff
            try:
                # Provider configuration is operator-controlled data; keep a
                # malformed or excessive retry budget from becoming an
                # unbounded outage amplifier.
                max_retries = max(0, min(int(provider_inst.max_retries or 0), 3))
            except (TypeError, ValueError):
                max_retries = 0
            last_err = None
            
            for attempt in range(max_retries + 1):
                try:
                    async with ai_limits.slot(provider_id=model_info["provider_id"], tenant_id=tenant, user_id=user_id):
                        if route_meta is not None:
                            # Model selection and security preparation are not
                            # egress. Set this only immediately before the
                            # provider adapter call so a circuit-open decision
                            # remains distinguishable from an attempted call.
                            route_meta.update({
                                "external_egress": True,
                                "status": "provider_attempted",
                                "model_id": model_info.get("id"),
                                "provider_id": model_info.get("provider_id"),
                            })
                        res = await provider_inst.chat(
                            processed_messages,
                            model=model_info["model_code"],
                            temperature=used_temp,
                            max_tokens=used_tokens,
                            tools=call_tools,
                            response_format=call_response_format,
                            thinking=call_thinking,
                            reasoning_effort=call_reasoning,
                            user_id=provider_user_id,
                            request_id=request_id,
                        )
                    ai_limits.record_success(model_info["provider_id"])
                    res["provider_id"] = model_info["provider_id"]
                    res["model_id"] = model_info["id"]
                    return res
                except AIException as exc:
                    last_err = exc
                    if isinstance(exc, (AICircuitOpenException, AIQuotaExceededException, AIBudgetExceededException)):
                        break
                    # Deterministic configuration/request failures must be
                    # surfaced immediately. Retrying a bad API key or an
                    # invalid model only turns a useful code into a circuit
                    # breaker result and needlessly delays the operator.
                    if isinstance(exc, (AIAuthFailedException, AIInvalidRequestException, AIModelNotFoundException, AIOutputTruncatedException)):
                        break
                    ai_limits.record_failure(model_info["provider_id"])
                    if attempt < max_retries:
                        await asyncio.sleep(0.5 * (2 ** attempt))
                except Exception as exc:
                    # Provider exceptions may contain response bodies or input
                    # fragments. Keep them out of the persisted/public error.
                    last_err = AINetworkException("Unexpected provider error")
                    ai_limits.record_failure(model_info["provider_id"])
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
            result["requested_model_id"] = requested_model_id
            result["route_reason"] = route_reason
            result["fallback_used"] = False
            result["token_source"] = "provider_reported" if int(result.get("input_tokens") or 0) > 0 else None
            if route_meta is not None:
                route_meta.update({
                    "model_id": result.get("model_id"),
                    "provider_id": result.get("provider_id"),
                    "status": "success",
                    "security_result": str(secure_payload.action.value),
                    "latency_ms": latency_ms,
                    "input_tokens": max(0, int(result.get("input_tokens") or 0)),
                    "output_tokens": max(0, int(result.get("output_tokens") or 0)),
                    "token_source": result.get("token_source"),
                })
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
            logger.warning("Primary AI model failed for scene=%s code=%s", sanitize_log_text(scene, limit=64), sanitize_log_text(getattr(primary_exc, "code", "AI_INTERNAL_ERROR"), limit=64))

            if isinstance(primary_exc, AISecurityBlockedException):
                primary_exc.request_id = request_id
                raise primary_exc
            
            # If fallback model is configured, attempt fallback
            if fallback_model_id and fallback_model_id != target_model_id:
                ai_metrics.fallback_event(
                    scene,
                    target_info.get("provider_id"),
                    fallback_model_id,
                    status="started",
                )
                try:
                    logger.info("Attempting fallback AI model for scene=%s", sanitize_log_text(scene, limit=64))
                    result = await _attempt_call(fallback_model_id)
                    ai_metrics.fallback_event(
                        scene,
                        target_info.get("provider_id"),
                        fallback_model_id,
                        status="success",
                    )
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
                    result["requested_model_id"] = requested_model_id
                    result["route_reason"] = "scene_route_fallback"
                    result["fallback_used"] = True
                    result["token_source"] = "provider_reported" if int(result.get("input_tokens") or 0) > 0 else None
                    if route_meta is not None:
                        route_meta.update({
                            "model_id": result.get("model_id"),
                            "provider_id": result.get("provider_id"),
                            "route_reason": "scene_route_fallback",
                            "fallback_used": True,
                            "status": "success",
                            "security_result": str(secure_payload.action.value),
                            "latency_ms": latency_ms,
                            "input_tokens": max(0, int(result.get("input_tokens") or 0)),
                            "output_tokens": max(0, int(result.get("output_tokens") or 0)),
                            "token_source": result.get("token_source"),
                        })
                    if result.get("content"):
                        result["content"] = self.security_gateway.resolve_output(
                            result["content"], tenant_id=tenant, task_id=task
                        )
                    result.pop("reasoning_content", None)
                    result.pop("raw", None)
                    return result
                except Exception as fallback_exc:
                    ai_metrics.fallback_event(
                        scene,
                        target_info.get("provider_id"),
                        fallback_model_id,
                        status="error",
                    )
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
                provider_id=target_info.get("provider_id"),
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

            if route_meta is not None:
                route_meta.update({
                    "status": "error",
                    "security_result": str(secure_payload.action.value),
                    "latency_ms": latency_ms,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "error_code": str(err_code)[:64],
                })
            
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
        roles: Optional[List[str]] = None,
        selection_source: Optional[str] = None,
        route_meta: Optional[Dict[str, Any]] = None,
        workspace_id: Optional[str] = None,
        site_id: Optional[str] = None,
        department: Optional[str] = None,
        document_scope: Optional[str] = None,
        request_id: Optional[str] = None,
        data_classification: Optional[str] = None,
    ):
        request_id = self._generate_request_id(request_id)
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

        requested_model_id = model_id
        fallback_model_id = None
        route_reason = selection_source or ("message_explicit_model" if model_id else "scene_route_or_system_default")
        target_model_id = model_id
        if not target_model_id:
            tenant_for_pref = tenant_id or "tenant-default"
            user_default = self._get_user_default_model(tenant_id=tenant_for_pref, user_id=user_id, roles=roles)
            if user_default:
                target_model_id = user_default
                route_reason = "user_default_model"
            else:
                primary_id, fallback_model_id, route_reason = model_router.resolve_route_with_reason(scene)
                target_model_id = primary_id

        model_info = self._get_model_details(target_model_id)
        self._authorize_model(model_info, tenant_id=tenant_id or "tenant-default", user_id=user_id, roles=roles)
        fallback_info: Dict[str, Any] | None = None
        if fallback_model_id:
            try:
                fallback_info = self._get_model_details(fallback_model_id)
                self._authorize_model(fallback_info, tenant_id=tenant_id or "tenant-default", user_id=user_id, roles=roles)
                allowed_types = {item.lower() for item in self.security_gateway.policy.allowed_provider_types}
                if str(fallback_info.get("provider_type") or "").lower() not in allowed_types:
                    fallback_model_id = None
                elif not self._fallback_is_compatible(
                    model_info,
                    fallback_info,
                    data_classification=data_classification,
                ):
                    fallback_model_id = None
            except AIException:
                fallback_model_id = None

        if route_meta is not None:
            route_meta.update({"requested_model_id": requested_model_id, "model_id": model_info.get("id"), "provider_id": model_info.get("provider_id"), "route_reason": route_reason, "fallback_used": False, "external_egress": False, "request_id": request_id})

        tools, response_format, thinking, reasoning_effort = self._apply_model_capabilities(
            model_info, tools=tools, response_format=response_format, thinking=thinking, reasoning_effort=reasoning_effort
        )
        
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
                provider_id=model_info.get("provider_id"),
                model_id=model_info.get("id"),
                data_classification=data_classification,
                data_region=model_info.get("data_region"),
                provider_allowed_classification=model_info.get("allowed_data_classification"),
                provider_no_training_confirmed=bool(model_info.get("no_training_confirmed")),
                provider_retention_days=model_info.get("retention_days"),
                provider_data_processing_agreement_ref=model_info.get("data_processing_agreement_ref"),
                workspace_id=workspace_id,
                site_id=site_id,
                department=department,
                document_scope=document_scope,
                user_role=(roles or [None])[0],
            )
        except SecurityBlocked as exc:
            blocked = AISecurityBlockedException(
                "AI request blocked by security policy",
                code=getattr(exc, "reason_code", "AI_SECURITY_BLOCKED"),
            )
            blocked.request_id = request_id
            if route_meta is not None:
                route_meta.update({"status": "blocked", "security_result": "blocked", "security": {"decision": "block", "result_code": getattr(exc, "reason_code", "AI_SECURITY_BLOCKED")}, "latency_ms": int((time.perf_counter() - start_time) * 1000), "input_tokens": 0, "output_tokens": 0})
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
                error_code=getattr(exc, "reason_code", "AI_SECURITY_BLOCKED"),
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
                error_code=getattr(exc, "reason_code", "AI_SECURITY_BLOCKED"),
            )
            raise blocked from exc

        effective_classification = str(
            (secure_payload.metadata or {}).get("classification") or data_classification or "PUBLIC"
        )
        if fallback_model_id and fallback_info and not self._fallback_is_compatible(
            model_info,
            fallback_info,
            data_classification=effective_classification,
        ):
            fallback_model_id = None

        processed_messages = secure_payload.messages
        full_content = []
        stream_resolver = StreamingOutputResolver(
            tenant_id=tenant,
            task_id=task,
            vault=self.security_gateway.vault,
        )
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
        if route_meta is not None:
            route_meta.update({"status": "prepared", "security_result": str(secure_payload.action.value), "security": {"decision": str(secure_payload.action.value), "result_code": "AI_SECURITY_PREPARED"}})

        stream_usage_by_model: Dict[str, Dict[str, int]] = {}

        async def _stream_candidate(candidate_info: Dict[str, Any]):
            if self._budget_exceeded(provider_id=candidate_info["provider_id"], model_id=candidate_info["id"]):
                raise AIBudgetExceededException()
            provider_inst = self._get_provider_instance(candidate_info["provider_id"])
            call_tools, call_response_format, call_thinking, call_reasoning = self._apply_model_capabilities(
                candidate_info,
                tools=secure_payload.tools,
                response_format=secure_payload.provider_options.get("response_format"),
                thinking=bool(secure_payload.provider_options.get("thinking")),
                reasoning_effort=secure_payload.provider_options.get("reasoning_effort"),
            )
            try:
                max_retries = max(0, min(int(provider_inst.max_retries or 0), 3))
            except (TypeError, ValueError):
                max_retries = 0

            for attempt in range(max_retries + 1):
                emitted = False
                try:
                    async with ai_limits.slot(provider_id=candidate_info["provider_id"], tenant_id=tenant, user_id=user_id):
                        if route_meta is not None:
                            # This flag means a provider adapter call actually
                            # started; model selection and security preparation
                            # alone are not external egress.
                            route_meta.update({
                                "external_egress": True,
                                "model_id": candidate_info.get("id"),
                                "provider_id": candidate_info.get("provider_id"),
                            })
                        if hasattr(provider_inst, "chat_stream"):
                            usage_sink: Dict[str, int] = {}
                            stream_usage_by_model[str(candidate_info["id"])] = usage_sink
                            async for chunk in provider_inst.chat_stream(
                                processed_messages,
                                model=candidate_info["model_code"],
                                temperature=used_temp,
                                max_tokens=used_tokens,
                                tools=call_tools,
                                response_format=call_response_format,
                                thinking=call_thinking,
                                reasoning_effort=call_reasoning,
                                user_id=secure_payload.user_id,
                                request_id=request_id,
                                usage_sink=usage_sink,
                            ):
                                emitted = True
                                yield chunk
                        else:
                            result = await provider_inst.chat(
                                processed_messages,
                                model=candidate_info["model_code"],
                                temperature=used_temp,
                                max_tokens=used_tokens,
                                tools=call_tools,
                                response_format=call_response_format,
                                thinking=call_thinking,
                                reasoning_effort=call_reasoning,
                                user_id=secure_payload.user_id,
                                request_id=request_id,
                            )
                            if result.get("content"):
                                emitted = True
                                yield str(result["content"])
                    ai_limits.record_success(candidate_info["provider_id"])
                    return
                except AIException as exc:
                    if isinstance(exc, (AICircuitOpenException, AIQuotaExceededException, AIBudgetExceededException)):
                        raise
                    if isinstance(exc, (AIAuthFailedException, AIInvalidRequestException, AIModelNotFoundException, AIOutputTruncatedException)):
                        raise
                    ai_limits.record_failure(candidate_info["provider_id"])
                    if attempt < max_retries and not emitted:
                        await asyncio.sleep(0.5 * (2 ** attempt))
                        continue
                    raise
                except Exception as exc:
                    ai_limits.record_failure(candidate_info["provider_id"])
                    if attempt < max_retries and not emitted:
                        await asyncio.sleep(0.5 * (2 ** attempt))
                        continue
                    raise AINetworkException("Unexpected streaming provider error") from exc

        try:
            async for chunk in _stream_candidate(model_info):
                full_content.append(chunk)
                resolved_chunk = stream_resolver.push(chunk)
                if resolved_chunk:
                    yield resolved_chunk
            resolved_tail = stream_resolver.flush()
            if resolved_tail:
                yield resolved_tail

            latency_ms = int((time.perf_counter() - start_time) * 1000)
            combined_txt = "".join(full_content)
            provider_usage = stream_usage_by_model.get(str(model_info["id"])) or {}
            provider_reported = int(provider_usage.get("input_tokens") or 0) > 0
            out_tok = max(0, int(provider_usage.get("output_tokens") or 0)) if provider_reported else max(1, len(combined_txt) // 3)
            in_tok = max(0, int(provider_usage.get("input_tokens") or 0)) if provider_reported else max(1, sum(len(m.get("content", "")) for m in messages) // 3)

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
            if route_meta is not None:
                route_meta.update({"model_id": model_info["id"], "provider_id": model_info["provider_id"], "fallback_used": False, "status": "success", "security_result": str(secure_payload.action.value), "latency_ms": latency_ms, "input_tokens": in_tok, "output_tokens": out_tok, "token_source": "provider_reported" if provider_reported else "estimated"})
        except Exception as exc:
            if fallback_model_id and not full_content:
                ai_metrics.fallback_event(
                    scene,
                    model_info.get("provider_id"),
                    fallback_model_id,
                    status="started",
                )
                try:
                    fallback_info = self._get_model_details(fallback_model_id)
                    self._authorize_model(fallback_info, tenant_id=tenant, user_id=user_id, roles=roles)
                    if not self._fallback_is_compatible(model_info, fallback_info):
                        raise AIModelNotFoundException("Fallback model is not compatible with the selected data policy")
                    fallback_resolver = StreamingOutputResolver(
                        tenant_id=tenant,
                        task_id=task,
                        vault=self.security_gateway.vault,
                    )
                    async for chunk in _stream_candidate(fallback_info):
                        full_content.append(chunk)
                        resolved_chunk = fallback_resolver.push(chunk)
                        if resolved_chunk:
                            yield resolved_chunk
                    resolved_tail = fallback_resolver.flush()
                    if resolved_tail:
                        yield resolved_tail
                    ai_metrics.fallback_event(
                        scene,
                        model_info.get("provider_id"),
                        fallback_model_id,
                        status="success",
                    )
                    latency_ms = int((time.perf_counter() - start_time) * 1000)
                    fallback_usage = stream_usage_by_model.get(str(fallback_info["id"])) or {}
                    fallback_provider_reported = int(fallback_usage.get("input_tokens") or 0) > 0
                    fallback_input_tokens = max(0, int(fallback_usage.get("input_tokens") or 0)) if fallback_provider_reported else max(1, sum(len(m.get("content", "")) for m in messages) // 3)
                    fallback_output_tokens = max(0, int(fallback_usage.get("output_tokens") or 0)) if fallback_provider_reported else max(1, len("".join(full_content)) // 3)
                    if route_meta is not None:
                        route_meta.update({"model_id": fallback_info["id"], "provider_id": fallback_info["provider_id"], "route_reason": "scene_route_fallback", "fallback_used": True, "status": "success", "security_result": str(secure_payload.action.value), "latency_ms": latency_ms, "input_tokens": fallback_input_tokens, "output_tokens": fallback_output_tokens, "token_source": "provider_reported" if fallback_provider_reported else "estimated"})
                    self._log_request(request_id=request_id, user_id=secure_payload.user_id, scene=scene, provider_id=fallback_info["provider_id"], model_id=fallback_info["id"], prompt_id=None, prompt_version=None, input_tokens=fallback_input_tokens, output_tokens=fallback_output_tokens, latency_ms=latency_ms, status="success")
                    return
                except Exception as fallback_exc:
                    ai_metrics.fallback_event(
                        scene,
                        model_info.get("provider_id"),
                        fallback_model_id,
                        status="error",
                    )
                    logger.warning("LLM stream fallback failed code=%s", sanitize_log_text(getattr(fallback_exc, "code", "AI_INTERNAL_ERROR"), limit=64))
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
            if route_meta is not None:
                route_meta.update({"status": "error", "security_result": str(secure_payload.action.value), "latency_ms": latency_ms, "input_tokens": 0, "output_tokens": 0})
            raise exc


llm_gateway = LLMGateway()
