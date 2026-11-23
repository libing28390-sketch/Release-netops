"""
LLM Gateway - Unified LLM Dispatcher with Model Routing, Sanitizer, Retry, Fallback, and Request Audit Logging
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from database.core import get_db_connection
from ai.security.crypto import ProviderKeyDecryptError, decrypt_api_key, reencrypt_if_needed
from ai.security.gateway import AISecurityGateway, SecurityBlocked, ai_security_gateway, deployment_endpoint_allowed
from ai.security.output import StreamingOutputResolver
from ai.security.tokenization import opaque_user_id
from ai.security.sanitizer import sanitize_log_text
from ai.security.security_service import create_security_incident, record_security_event
from ai.gateway.exceptions import (
    AIKeyDecryptException,
    AIException,
    AIBudgetExceededException,
    AIAuthFailedException,
    AIContextTooLargeException,
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
from ai.gateway.token_estimate import estimate_message_tokens, estimate_tokens
from ai.gateway.limits import ai_limits
from core.config import settings
from core.context import request_id_var, resolve_request_id
from ai.providers.base import BaseLLMProvider
from ai.providers.registry import provider_adapter
from ai.services.metrics import ai_metrics

logger = logging.getLogger(__name__)

# Blocks caused by the request content are security incidents.  Blocks caused
# by configuration (external AI off, kill switch, provider/region not allowed)
# are expected and are recorded as events only, so they cannot flood the
# incident queue with one "high" incident per request.
_INCIDENT_ERROR_CODES = frozenset({
    "AI_SECURITY_SENSITIVE_DATA",
    "AI_SECURITY_DLP_FAILED",
    "AI_SECURITY_UNSAFE_TOOL",
    "AI_SECURITY_CLASSIFICATION_DENIED",
})


def _estimate_tokens(text: str) -> int:
    """Kept for callers/tests; see ai.gateway.token_estimate."""
    return estimate_tokens(text)


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


@dataclass
class _PreparedRequest:
    """Result of :meth:`LLMGateway._prepare_request` (review item L4).

    Everything ``chat`` and ``chat_stream`` need before the first provider
    attempt: the resolved route, the authorized primary model, a fallback that
    already passed ACL / egress / classification checks (or ``None``), and the
    security-gateway payload that is the only thing allowed to leave.
    """

    request_id: str
    tenant: str
    task: str
    requested_model_id: Optional[str]
    target_model_id: Optional[str]
    route_reason: str
    target_info: Dict[str, Any]
    fallback_model_id: Optional[str]
    fallback_info: Optional[Dict[str, Any]]
    effective_classification: str
    messages: List[Dict[str, Any]]
    secure_payload: Any


class LLMGateway:
    """Unified LLM Gateway service."""

    def __init__(self, security_gateway: AISecurityGateway | None = None):
        self.security_gateway = security_gateway or ai_security_gateway

    @staticmethod
    def _fit_context(
        messages: List[Dict[str, Any]],
        models: List[Optional[Dict[str, Any]]],
        max_tokens: Optional[int],
    ) -> List[Dict[str, Any]]:
        """Keep a request inside the context window of every candidate model.

        System messages, messages marked ``_pin`` (e.g. an Agent's original
        question) and the newest message are always kept; older history is
        dropped from the oldest end.  The private ``_pin`` marker is always
        removed before the messages leave the gateway.  If the kept messages
        alone are too large, the request fails with AI_CONTEXT_TOO_LARGE
        instead of being sent to a provider that would reject it.
        """
        cleaned: List[Dict[str, Any]] = []
        pinned: set[int] = set()
        for index, message in enumerate(messages or []):
            if isinstance(message, dict) and "_pin" in message:
                if message.get("_pin"):
                    pinned.add(index)
                message = {key: value for key, value in message.items() if key != "_pin"}
            cleaned.append(message)

        windows: List[int] = []
        for info in models:
            if not info:
                continue
            try:
                context_length = int(info.get("context_length") or 131072)
                output_cap = int(info.get("max_output_tokens") or 16384)
                requested = int(max_tokens if max_tokens is not None else (info.get("default_max_tokens") or 4096))
            except (TypeError, ValueError):
                continue
            reserve = max(256, min(requested, output_cap))
            windows.append(int(context_length * 0.95) - reserve)
        if not windows or not cleaned:
            return cleaned
        budget = max(512, min(windows))
        costs = [estimate_message_tokens(item) for item in cleaned]
        if sum(costs) <= budget:
            return cleaned

        keep = {index for index, item in enumerate(cleaned) if isinstance(item, dict) and item.get("role") == "system"}
        keep |= pinned
        keep.add(len(cleaned) - 1)
        used = sum(costs[index] for index in keep)
        if used > budget:
            raise AIContextTooLargeException()
        for index in range(len(cleaned) - 2, -1, -1):
            if index in keep:
                continue
            if used + costs[index] > budget:
                break  # keep a contiguous recent tail
            keep.add(index)
            used += costs[index]
        trimmed = [item for index, item in enumerate(cleaned) if index in keep]
        logger.info("AI context trimmed to fit the model window dropped_messages=%s", len(cleaned) - len(trimmed))
        return trimmed

    @staticmethod
    def _retry_delay(attempt: int, max_retries: int, exc: BaseException | None) -> float | None:
        """Backoff before the next attempt, or None when no retry should happen.

        Exponential backoff with jitter (so parallel requests do not retry in
        lock-step), capped at 8s.  A provider ``Retry-After`` is honoured; if
        it asks for longer than AI_RETRY_AFTER_MAX_SECONDS the request fails
        now instead of holding the caller.
        """
        if attempt >= max_retries:
            return None
        delay = min(8.0, 0.5 * (2 ** attempt)) * random.uniform(0.5, 1.5)
        retry_after = getattr(exc, "retry_after", None)
        if retry_after:
            try:
                cap = float(getattr(settings, "AI_RETRY_AFTER_MAX_SECONDS", 10.0))
            except (TypeError, ValueError):
                cap = 10.0
            if float(retry_after) > cap:
                return None
            delay = max(delay, float(retry_after))
        return delay

    @staticmethod
    async def _db(fn, *args, **kwargs):
        """Run a blocking helper (PostgreSQL, policy refresh) off the event loop.

        Every helper wrapped here does synchronous psycopg2 I/O.  Running it
        in a worker thread keeps one slow query from stalling every other
        request and SSE stream served by this worker.
        """
        return await asyncio.to_thread(fn, *args, **kwargs)

    def _current_policy(self):
        """Policy after deployment flags and cross-worker refresh."""
        getter = getattr(self.security_gateway, "effective_policy", None)
        return getter() if callable(getter) else self.security_gateway.policy

    def _assert_egress(self, model_info: Dict[str, Any], *, tenant_id: str) -> None:
        """Re-check kill switches, provider allowlist and region for one model.

        Runs for every candidate (primary and fallback) right before the
        provider request, so a fallback or a policy change made mid-request
        cannot bypass the egress policy.
        """
        checker = getattr(self.security_gateway, "assert_egress_allowed", None)
        if not callable(checker):
            return
        try:
            checker(
                provider_type=model_info.get("provider_type") or "",
                provider_id=model_info.get("provider_id"),
                data_region=model_info.get("data_region"),
                tenant_id=tenant_id,
            )
        except SecurityBlocked as exc:
            raise AISecurityBlockedException(
                "AI request blocked by security policy",
                code=getattr(exc, "reason_code", "AI_SECURITY_BLOCKED"),
            ) from exc

    def _generate_request_id(self, request_id: Optional[str] = None) -> str:
        """Reuse the API correlation id, or create one for direct callers."""

        return resolve_request_id(request_id or request_id_var.get("-"), prefix="ai_req")

    def _get_provider_instance(self, provider_id: str) -> BaseLLMProvider:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # approved_endpoint_patterns_json exists since m0165/m0166; the
            # pre-m0139 compatibility query was removed (review L2).
            cursor.execute(
                "SELECT id, name, provider_type, base_url, api_key_encrypted, timeout, max_retries, proxy_url, enabled, approved_endpoint_patterns_json "
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
                if not deployment_endpoint_allowed(base_url):
                    raise AIProviderUnsupportedException("Provider endpoint host is not in the deployment allowlist")

            try:
                plain_api_key = decrypt_api_key(row[4], provider_id=str(row[0]))
            except ProviderKeyDecryptError as exc:
                logger.error("AI provider key unusable provider=%s reason=%s code=AI_KEY_DECRYPT_FAILED", row[0], exc.reason)
                raise AIKeyDecryptException() from exc
            if row[4] and plain_api_key:
                # Upgrade legacy / old-master-key ciphertexts on first use;
                # optimistic so a concurrent rotation is never overwritten.
                try:
                    upgraded, changed = reencrypt_if_needed(row[4], provider_id=str(row[0]))
                    if changed:
                        conn.execute(
                            "UPDATE ai_provider SET api_key_encrypted = ? WHERE id = ? AND api_key_encrypted = ?",
                            (upgraded, row[0], row[4]),
                        )
                        conn.commit()
                except Exception:
                    logger.warning("AI provider key re-encryption skipped provider=%s code=AI_KEY_REENCRYPT_FAILED", row[0])

            try:
                adapter = provider_adapter(str(p_data["provider_type"] or ""))
            except ValueError as exc:
                raise AIProviderUnsupportedException() from exc
            return adapter(p_data, api_key=plain_api_key)

    def _get_model_details(self, model_id_or_code: str) -> Dict[str, Any]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # All columns exist since m0139/m0165/m0217; the legacy-shape
            # compatibility query was removed (review L2).
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
                    "context_length": int(row[19] or 131072),
                    "max_output_tokens": int(row[20] or 16384),
                    "cost_input_per_1k": float(row[21] or 0),
                    "cost_output_per_1k": float(row[22] or 0),
                }

            if str(model_id_or_code or "").strip():
                # ADR-011: a requested, routed or fallback model that is
                # missing, disabled or on a disabled Provider is an error.  It
                # is never silently replaced by another (possibly different
                # Provider's) model.
                raise AIModelNotFoundException("Requested AI model is not available")

            # Nothing was requested and no route applies: use the system default.
            cursor.execute(
                "SELECT m.id, m.provider_id, m.model_code, m.default_temperature, m.default_max_tokens, "
                "p.provider_type, m.model_type, m.thinking_supported, m.tool_call_supported, m.json_supported, m.stream_supported, "
                "p.allowed_data_classification, p.data_region, p.no_training_confirmed, p.retention_days, "
                "p.data_processing_agreement_ref, p.agreement_reviewed_at, p.approved_endpoint_patterns_json, "
                "m.context_length, m.max_output_tokens, m.cost_input_per_1k, m.cost_output_per_1k "
                "FROM ai_model m LEFT JOIN ai_provider p ON p.id = m.provider_id "
                "WHERE m.enabled = 1 AND COALESCE(p.enabled, 0) = 1 ORDER BY m.is_default DESC, m.priority DESC LIMIT 1"
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
                    "context_length": int(def_row[18] or 131072),
                    "max_output_tokens": int(def_row[19] or 16384),
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
            # The ACL table exists on every supported schema (m0139+).  If it
            # cannot be read, deny rather than silently granting access.
            logger.warning("AI model ACL lookup failed code=AI_MODEL_ACL_UNAVAILABLE")
            raise AIModelNotFoundException("Requested AI model is not available for this user")
        if not rows:
            # No ACL rows: the model is visible to everyone (current default).
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
            # A preference is optional: fall back to scene/system routing.
            logger.warning("AI user model preference lookup failed code=AI_MODEL_PREFERENCE_UNAVAILABLE")
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
        del provider_id, model_id
        budget = float(getattr(settings, "AI_DAILY_BUDGET_USD", 0) or 0)
        if budget <= 0:
            return False
        today = datetime.now(timezone.utc).date().isoformat()
        try:
            with get_db_connection() as conn:
                row = conn.execute(
                    "SELECT COALESCE(SUM(estimated_cost), 0) FROM ai_usage_daily WHERE date = ?",
                    (today,),
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
            # Local policy blocks and client disconnects say nothing about
            # upstream provider/model health and must never flip a healthy
            # model to unhealthy.
            _non_health_statuses = {"client_aborted", "blocked", "security_blocked", "policy_blocked", "cancelled"}
            if status not in _non_health_statuses:
                now = datetime.now(timezone.utc).isoformat()
                health = "healthy" if status == "success" else "unhealthy"
                with get_db_connection() as health_conn:
                    if provider_id:
                        health_conn.execute(
                            "UPDATE ai_provider SET health_status = ?, last_success_at = CASE WHEN ? = 'healthy' THEN ? ELSE last_success_at END, last_error_code = CASE WHEN ? = 'healthy' THEN NULL ELSE ? END, last_health_check_at = ?, last_error_at = CASE WHEN ? = 'healthy' THEN last_error_at ELSE ? END WHERE id = ?",
                            (health, health, now, health, error_code, now, health, now, provider_id),
                        )
                    if model_id:
                        health_conn.execute(
                            "UPDATE ai_model SET health_status = ?, last_latency_ms = ?, last_health_check_at = ?, last_success_at = CASE WHEN ? = 'healthy' THEN ? ELSE last_success_at END, last_error_code = CASE WHEN ? = 'healthy' THEN NULL ELSE ? END WHERE id = ?",
                            (health, max(0, int(latency_ms or 0)), now, health, now, health, error_code, model_id),
                        )
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
                    in_tok_val = max(0, int(input_tokens or 0))
                    out_tok_val = max(0, int(output_tokens or 0))
                    latency_val = max(0, int(latency_ms or 0))
                    success_inc = 1 if status == "success" else 0
                    error_inc = 0 if status in {"success", "client_aborted"} else 1
                    usage_conn.execute(
                        """
                        INSERT INTO ai_usage_daily (
                            id, date, provider_id, model_id, scene,
                            requests, input_tokens, output_tokens, estimated_cost,
                            success_count, error_count, avg_latency, created_at
                        ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (date, provider_id, model_id, scene) DO UPDATE SET
                            requests = ai_usage_daily.requests + 1,
                            input_tokens = ai_usage_daily.input_tokens + EXCLUDED.input_tokens,
                            output_tokens = ai_usage_daily.output_tokens + EXCLUDED.output_tokens,
                            estimated_cost = ai_usage_daily.estimated_cost + EXCLUDED.estimated_cost,
                            success_count = ai_usage_daily.success_count + EXCLUDED.success_count,
                            error_count = ai_usage_daily.error_count + EXCLUDED.error_count,
                            avg_latency = ((ai_usage_daily.avg_latency * ai_usage_daily.requests) + EXCLUDED.avg_latency) / (ai_usage_daily.requests + 1),
                            created_at = EXCLUDED.created_at
                        """,
                        (
                            f"usage_{uuid.uuid4().hex[:16]}",
                            date_key,
                            provider_id,
                            model_id,
                            scene,
                            in_tok_val,
                            out_tok_val,
                            cost,
                            success_inc,
                            error_inc,
                            latency_val,
                            now_iso,
                        ),
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
            if (status == "blocked" or decision == "BLOCK") and str(error_code or "") in _INCIDENT_ERROR_CODES:
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

    async def _prepare_request(
        self,
        *,
        scene: str,
        messages: List[Dict[str, Any]],
        request_id: str,
        start_time: float,
        model_id: Optional[str],
        max_tokens: Optional[int],
        tools: Optional[List[Dict[str, Any]]],
        response_format: Optional[Dict[str, Any]],
        thinking: bool,
        reasoning_effort: Optional[str],
        prompt_id: Optional[str],
        prompt_version: Optional[int],
        user_id: Optional[str],
        tenant_id: Optional[str],
        roles: Optional[List[str]],
        selection_source: Optional[str],
        task_id: Optional[str],
        workspace_id: Optional[str],
        site_id: Optional[str],
        department: Optional[str],
        document_scope: Optional[str],
        data_classification: Optional[str],
        route_meta: Optional[Dict[str, Any]],
    ) -> _PreparedRequest:
        """Preparation shared by :meth:`chat` and :meth:`chat_stream` (review L4).

        Policy gate -> route -> model details + ACL -> capability trimming ->
        fallback pre-check -> context fit -> security ``protect`` -> fallback
        re-check against the effective classification -> "prepared" audit.

        Both entry points used to carry their own ~150-line copy of this and
        had drifted apart (the stream path skipped the security audit on a
        kill-switch block and did not fill ``route_meta`` on it).  Sending,
        retries and streaming stay in the callers.
        """
        tenant = tenant_id or "tenant-default"
        task = task_id or request_id

        # Check the egress gate before consulting model/provider configuration.
        # A disabled or killed gateway must fail closed even when the database
        # has no active model, and must not reveal provider configuration.
        current_policy = await self._db(self._current_policy)
        if current_policy.kill_switch or not current_policy.external_ai_enabled:
            blocked = AISecurityBlockedException("AI request blocked by security policy")
            blocked.request_id = request_id
            if route_meta is not None:
                route_meta.update({"request_id": request_id, "status": "blocked", "security_result": "blocked", "security": {"decision": "block", "result_code": "AI_SECURITY_BLOCKED"}, "latency_ms": 0, "input_tokens": 0, "output_tokens": 0})
            await self._db(self._log_request,
                request_id=request_id,
                user_id=opaque_user_id(user_id, tenant_id=tenant, task_id=task),
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
            await self._db(self._log_security_audit,
                request_id=request_id,
                tenant_id=tenant,
                task_id=task,
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
            scene_model_id, scene_fallback_id, scene_reason, scene_classification = await self._db(model_router.resolve_route_policy, scene)
            if scene_reason == "scene_route" and scene_model_id:
                target_model_id = scene_model_id
                fallback_model_id = scene_fallback_id
                route_reason = "scene_route"
                if data_classification is None and scene_classification:
                    data_classification = scene_classification
            else:
                user_default = await self._db(self._get_user_default_model, tenant_id=tenant, user_id=user_id, roles=roles)
                if user_default:
                    target_model_id = user_default
                    route_reason = "user_default_model"
                else:
                    target_model_id, fallback_model_id, route_reason = scene_model_id, scene_fallback_id, scene_reason

        target_info = await self._db(self._get_model_details, target_model_id)
        await self._db(self._authorize_model, target_info, tenant_id=tenant, user_id=user_id, roles=roles)
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
                fallback_info = await self._db(self._get_model_details, fallback_model_id)
                await self._db(self._authorize_model, fallback_info, tenant_id=tenant, user_id=user_id, roles=roles)
                # A route fallback is still an external egress: it must pass
                # the same kill switches, provider allowlist and data-region
                # policy as the primary model.
                await self._db(self._assert_egress, fallback_info, tenant_id=tenant)
                if not self._fallback_is_compatible(
                    target_info,
                    fallback_info,
                    data_classification=data_classification,
                ):
                    fallback_model_id = None
            except AIException:
                fallback_model_id = None
        fitted = self._fit_context(messages, [target_info, fallback_info if fallback_model_id else None], max_tokens)
        try:
            secure_payload = self.security_gateway.protect(
                fitted,
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
                scene=scene,
            )
        except SecurityBlocked as exc:
            reason_code = getattr(exc, "reason_code", "AI_SECURITY_BLOCKED")
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            if route_meta is not None:
                route_meta.update({"status": "blocked", "security_result": "blocked", "security": {"decision": "block", "result_code": reason_code}, "latency_ms": latency_ms, "input_tokens": 0, "output_tokens": 0})
            await self._db(self._log_request,
                request_id=request_id,
                user_id=opaque_user_id(user_id, tenant_id=tenant, task_id=task),
                scene=scene,
                provider_id=target_info.get("provider_id"),
                model_id=target_info.get("id"),
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
                status="blocked",
                error_code=reason_code,
                error_message="policy_block",
            )
            await self._db(self._log_security_audit,
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
                error_code=reason_code,
            )
            blocked = AISecurityBlockedException(
                "AI request blocked by security policy",
                code=reason_code,
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

        await self._db(self._log_security_audit,
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
        return _PreparedRequest(
            request_id=request_id,
            tenant=tenant,
            task=task,
            requested_model_id=requested_model_id,
            target_model_id=target_model_id,
            route_reason=route_reason,
            target_info=target_info,
            fallback_model_id=fallback_model_id,
            fallback_info=fallback_info if fallback_model_id else None,
            effective_classification=effective_classification,
            messages=fitted,
            secure_payload=secure_payload,
        )

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

        prepared = await self._prepare_request(
            scene=scene,
            messages=messages,
            request_id=request_id,
            start_time=start_time,
            model_id=model_id,
            max_tokens=max_tokens,
            tools=tools,
            response_format=response_format,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
            selection_source=selection_source,
            task_id=task_id,
            workspace_id=workspace_id,
            site_id=site_id,
            department=department,
            document_scope=document_scope,
            data_classification=data_classification,
            route_meta=route_meta,
        )
        requested_model_id = prepared.requested_model_id
        route_reason = prepared.route_reason
        target_model_id = prepared.target_model_id
        target_info = prepared.target_info
        fallback_model_id = prepared.fallback_model_id
        tenant = prepared.tenant
        task = prepared.task
        secure_payload = prepared.secure_payload
        processed_messages = secure_payload.messages
        processed_tools = secure_payload.tools
        provider_user_id = secure_payload.user_id

        # Helper to execute call on candidate model
        async def _attempt_call(m_id: str) -> Dict[str, Any]:
            model_info = await self._db(self._get_model_details, m_id)
            await self._db(self._authorize_model, model_info, tenant_id=tenant, user_id=user_id, roles=roles)
            await self._db(self._assert_egress, model_info, tenant_id=tenant)
            if await self._db(self._budget_exceeded, provider_id=model_info["provider_id"], model_id=model_info["id"]):
                raise AIBudgetExceededException()
            provider_inst = await self._db(self._get_provider_instance, model_info["provider_id"])
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
            circuit_provider = model_info["provider_id"]
            # One circuit check per request; retries below reuse it.
            is_probe = ai_limits.acquire_circuit(circuit_provider)
            try:
                for attempt in range(max_retries + 1):
                    try:
                        async with ai_limits.slot(provider_id=model_info["provider_id"], tenant_id=tenant, user_id=user_id, check_circuit=False):
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
                        delay = self._retry_delay(attempt, max_retries, exc)
                        if delay is None:
                            # One failed request counts once, not once per retry.
                            ai_limits.record_failure(circuit_provider)
                            break
                        await asyncio.sleep(delay)
                    except Exception:
                        # Provider exceptions may contain response bodies or input
                        # fragments. Keep them out of the persisted/public error.
                        last_err = AINetworkException("Unexpected provider error")
                        delay = self._retry_delay(attempt, max_retries, None)
                        if delay is None:
                            ai_limits.record_failure(circuit_provider)
                            break
                        await asyncio.sleep(delay)
            finally:
                if is_probe:
                    # No-op when record_success/record_failure already resolved it.
                    ai_limits.release_probe(circuit_provider)

            raise last_err

        # Execute primary attempt
        try:
            result = await _attempt_call(target_model_id)
            latency_ms = int((time.perf_counter() - start_time) * 1000)

            # Audit log success
            await self._db(self._log_request,
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

                    await self._db(self._log_request,
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

            await self._db(self._log_request,
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

    async def chat_stream(self, scene: str, messages: List[Dict[str, str]], **kwargs: Any):
        """Stream a completion through the gateway (see ``_chat_stream_impl``).

        Also accounts for client disconnects: when the consumer stops reading
        (browser closed, SSE aborted, task cancelled) the request is still
        recorded as ``client_aborted`` with the tokens already produced, so
        usage and cost are not under-reported.
        """
        tracker: Dict[str, Any] = {}
        emitted: List[str] = []
        try:
            async for chunk in self._chat_stream_impl(scene, messages, _abort_tracker=tracker, **kwargs):
                emitted.append(chunk)
                yield chunk
        except (asyncio.CancelledError, GeneratorExit):
            self._record_client_abort(scene=scene, messages=messages, output="".join(emitted), tracker=tracker)
            raise

    def _record_client_abort(self, *, scene: str, messages: List[Dict[str, Any]], output: str, tracker: Dict[str, Any]) -> None:
        """Persist an aborted stream without awaiting.

        Runs from a cancelled task, where any await may be cancelled again,
        so the write is handed to a worker thread and not awaited.
        """
        try:
            usage = tracker.get("usage") or {}
            provider_id = tracker.get("provider_id")
            reported_in = int(usage.get("input_tokens") or 0)
            reported_out = int(usage.get("output_tokens") or 0)
            if provider_id:
                input_tokens = reported_in or _estimate_tokens("".join(str(m.get("content", "")) for m in messages))
                output_tokens = reported_out or _estimate_tokens(output)
            else:
                # Aborted before any provider call: nothing was sent or billed.
                input_tokens = output_tokens = 0
            started = tracker.get("start_time") or time.perf_counter()
            record = dict(
                request_id=str(tracker.get("request_id") or "-"),
                user_id=tracker.get("user_id"),
                scene=scene,
                provider_id=provider_id,
                model_id=tracker.get("model_id") if provider_id else None,
                prompt_id=tracker.get("prompt_id"),
                prompt_version=tracker.get("prompt_version"),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=int((time.perf_counter() - started) * 1000),
                status="client_aborted",
                error_code="AI_CLIENT_ABORTED",
                error_message="client_disconnected",
            )

            def _write() -> None:
                try:
                    self._log_request(**record)
                except Exception:
                    logger.warning("Failed to record aborted AI stream code=AI_ABORT_AUDIT_WRITE_FAILED")

            try:
                asyncio.get_running_loop().run_in_executor(None, _write)
            except RuntimeError:
                _write()
        except Exception:
            logger.warning("Failed to record aborted AI stream code=AI_ABORT_AUDIT_WRITE_FAILED")

    async def _chat_stream_impl(
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
        prompt_id: Optional[str] = None,
        prompt_version: Optional[int] = None,
        _abort_tracker: Optional[Dict[str, Any]] = None,
    ):
        request_id = self._generate_request_id(request_id)
        start_time = time.perf_counter()
        ai_metrics.request_started(scene)
        tracker = _abort_tracker if _abort_tracker is not None else {}
        tracker.update({
            "request_id": request_id,
            "start_time": start_time,
            "user_id": opaque_user_id(user_id, tenant_id=tenant_id or "tenant-default", task_id=task_id or request_id),
            "prompt_id": prompt_id,
            "prompt_version": prompt_version,
        })

        prepared = await self._prepare_request(
            scene=scene,
            messages=messages,
            request_id=request_id,
            start_time=start_time,
            model_id=model_id,
            max_tokens=max_tokens,
            tools=tools,
            response_format=response_format,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
            selection_source=selection_source,
            task_id=task_id,
            workspace_id=workspace_id,
            site_id=site_id,
            department=department,
            document_scope=document_scope,
            data_classification=data_classification,
            route_meta=route_meta,
        )
        model_info = prepared.target_info
        fallback_model_id = prepared.fallback_model_id
        tenant = prepared.tenant
        task = prepared.task
        secure_payload = prepared.secure_payload
        effective_classification = prepared.effective_classification
        # Fitted (pre-protect) messages: used for token estimates below.
        messages = prepared.messages

        used_temp = temperature if temperature is not None else model_info.get("default_temperature", 0.7)
        used_tokens = max_tokens if max_tokens is not None else model_info.get("default_max_tokens", 4096)
        # A caller may ask for a long answer; never exceed what the model
        # accepts (an over-limit max_tokens is an invalid request upstream).
        try:
            model_output_cap = int(model_info.get("max_output_tokens") or 0)
        except (TypeError, ValueError):
            model_output_cap = 0
        if model_output_cap > 0 and used_tokens:
            used_tokens = min(int(used_tokens), model_output_cap)

        processed_messages = secure_payload.messages
        full_content = []
        stream_resolver = StreamingOutputResolver(
            tenant_id=tenant,
            task_id=task,
            vault=self.security_gateway.vault,
        )
        if route_meta is not None:
            route_meta.update({"status": "prepared", "security_result": str(secure_payload.action.value), "security": {"decision": str(secure_payload.action.value), "result_code": "AI_SECURITY_PREPARED"}})

        stream_usage_by_model: Dict[str, Dict[str, int]] = {}

        async def _stream_candidate(candidate_info: Dict[str, Any]):
            tracker.update({"model_id": candidate_info.get("id"), "provider_id": None, "usage": None})
            await self._db(self._assert_egress, candidate_info, tenant_id=tenant)
            if await self._db(self._budget_exceeded, provider_id=candidate_info["provider_id"], model_id=candidate_info["id"]):
                raise AIBudgetExceededException()
            provider_inst = await self._db(self._get_provider_instance, candidate_info["provider_id"])
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

            circuit_provider = candidate_info["provider_id"]
            is_probe = ai_limits.acquire_circuit(circuit_provider)
            try:
                for attempt in range(max_retries + 1):
                    emitted = False
                    try:
                        async with ai_limits.slot(provider_id=candidate_info["provider_id"], tenant_id=tenant, user_id=user_id, check_circuit=False):
                            tracker["provider_id"] = candidate_info.get("provider_id")
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
                                tracker["usage"] = usage_sink
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
                        delay = None if emitted else self._retry_delay(attempt, max_retries, exc)
                        if delay is None:
                            ai_limits.record_failure(circuit_provider)
                            raise
                        await asyncio.sleep(delay)
                        continue
                    except Exception as exc:
                        delay = None if emitted else self._retry_delay(attempt, max_retries, None)
                        if delay is None:
                            ai_limits.record_failure(circuit_provider)
                            raise AINetworkException("Unexpected streaming provider error") from exc
                        await asyncio.sleep(delay)
                        continue
            finally:
                if is_probe:
                    ai_limits.release_probe(circuit_provider)

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
            out_tok = max(0, int(provider_usage.get("output_tokens") or 0)) if provider_reported else max(1, _estimate_tokens(combined_txt))
            in_tok = max(0, int(provider_usage.get("input_tokens") or 0)) if provider_reported else max(1, _estimate_tokens("".join(str(m.get("content", "")) for m in messages)))

            await self._db(self._log_request,
                request_id=request_id,
                user_id=secure_payload.user_id,
                scene=scene,
                provider_id=model_info["provider_id"],
                model_id=model_info["id"],
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                input_tokens=in_tok,
                output_tokens=out_tok,
                latency_ms=latency_ms,
                status="success"
            )
            cached_tok = max(0, int(provider_usage.get("cached_tokens") or 0)) if provider_reported else 0
            if route_meta is not None:
                route_meta.update({"model_id": model_info["id"], "provider_id": model_info["provider_id"], "fallback_used": False, "status": "success", "security_result": str(secure_payload.action.value), "latency_ms": latency_ms, "input_tokens": in_tok, "output_tokens": out_tok, "cached_tokens": cached_tok, "token_source": "provider_reported" if provider_reported else "estimated"})
        except Exception as exc:
            if isinstance(exc, AIOutputTruncatedException) and full_content:
                # The model hit its output limit after streaming part of the
                # answer.  Deliver the text held back by the resolver and
                # tell the caller the answer is incomplete; it is not a
                # provider failure.
                truncated_tail = stream_resolver.flush()
                if truncated_tail:
                    yield truncated_tail
                provider_usage = stream_usage_by_model.get(str(model_info["id"])) or {}
                truncated_input = max(0, int(provider_usage.get("input_tokens") or 0))
                truncated_output = max(0, int(provider_usage.get("output_tokens") or 0)) or max(1, _estimate_tokens("".join(full_content)))
                truncated_latency = int((time.perf_counter() - start_time) * 1000)
                if route_meta is not None:
                    route_meta.update({
                        "model_id": model_info["id"],
                        "provider_id": model_info["provider_id"],
                        "finish_reason": "length",
                        "latency_ms": truncated_latency,
                        "input_tokens": truncated_input,
                        "output_tokens": truncated_output,
                        "token_source": "provider_reported" if int(provider_usage.get("input_tokens") or 0) > 0 else "estimated",
                    })
                # Record it as a completed call (usage counted, provider stays
                # healthy), not as STREAM_ERROR with zero tokens; the caller
                # still receives the exception and reports finish_reason=length.
                await self._db(
                    self._log_request,
                    request_id=request_id,
                    user_id=secure_payload.user_id,
                    scene=scene,
                    provider_id=model_info.get("provider_id"),
                    model_id=model_info.get("id"),
                    prompt_id=prompt_id,
                    prompt_version=prompt_version,
                    input_tokens=truncated_input,
                    output_tokens=truncated_output,
                    latency_ms=truncated_latency,
                    status="success",
                    error_code="AI_OUTPUT_TRUNCATED",
                )
                if route_meta is not None:
                    route_meta.update({"status": "success", "security_result": str(secure_payload.action.value)})
                raise exc
            if fallback_model_id and not full_content and not isinstance(exc, AISecurityBlockedException):
                ai_metrics.fallback_event(
                    scene,
                    model_info.get("provider_id"),
                    fallback_model_id,
                    status="started",
                )
                try:
                    fallback_info = await self._db(self._get_model_details, fallback_model_id)
                    await self._db(self._authorize_model, fallback_info, tenant_id=tenant, user_id=user_id, roles=roles)
                    if not self._fallback_is_compatible(model_info, fallback_info, data_classification=effective_classification):
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
                    fallback_input_tokens = max(0, int(fallback_usage.get("input_tokens") or 0)) if fallback_provider_reported else max(1, _estimate_tokens("".join(str(m.get("content", "")) for m in messages)))
                    fallback_output_tokens = max(0, int(fallback_usage.get("output_tokens") or 0)) if fallback_provider_reported else max(1, _estimate_tokens("".join(full_content)))
                    if route_meta is not None:
                        route_meta.update({"model_id": fallback_info["id"], "provider_id": fallback_info["provider_id"], "route_reason": "scene_route_fallback", "fallback_used": True, "status": "success", "security_result": str(secure_payload.action.value), "latency_ms": latency_ms, "input_tokens": fallback_input_tokens, "output_tokens": fallback_output_tokens, "token_source": "provider_reported" if fallback_provider_reported else "estimated"})
                    await self._db(self._log_request, request_id=request_id, user_id=secure_payload.user_id, scene=scene, provider_id=fallback_info["provider_id"], model_id=fallback_info["id"], prompt_id=prompt_id, prompt_version=prompt_version, input_tokens=fallback_input_tokens, output_tokens=fallback_output_tokens, latency_ms=latency_ms, status="success")
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
            await self._db(self._log_request,
                request_id=request_id,
                user_id=secure_payload.user_id,
                scene=scene,
                provider_id=model_info.get("provider_id"),
                model_id=model_info.get("id"),
                prompt_id=prompt_id,
                prompt_version=prompt_version,
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
