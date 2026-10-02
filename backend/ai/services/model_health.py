"""Model-level health probes and short-window SLA statistics.

Health probes deliberately use the normal LLM gateway so security policy,
provider limits, circuit breakers and request auditing remain identical to
production traffic.  Probe history is operational metadata only; the prompt
and provider response are never persisted here.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from ai.gateway.exceptions import AIException
from ai.gateway.llm_gateway import llm_gateway
from core.config import settings
from database.core import get_db_connection

logger = logging.getLogger(__name__)

MODEL_HEALTH_SCENE = "model_health_probe"
MODEL_HEALTH_WINDOW_HOURS = 24
MODEL_HEALTH_MESSAGE = "Reply with one short word: ok"


def classify_health_bucket(check_count: int, success_count: int) -> str:
    """Classify one status-page bucket without treating missing data as healthy."""
    checks = max(0, int(check_count or 0))
    successes = max(0, min(checks, int(success_count or 0)))
    if checks == 0:
        return "unknown"
    if successes == checks:
        return "healthy"
    availability = (successes / checks) * 100
    return "degraded" if availability >= 95 else "unhealthy"


def build_health_timeline(
    daily_rows: dict[str, tuple[int, int, Optional[float]]],
    *,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    """Expand daily aggregates into a finite status-page timeline."""
    timeline: list[dict[str, Any]] = []
    cursor = start_date
    while cursor <= end_date:
        bucket_date = cursor.isoformat()
        check_count, success_count, avg_latency = daily_rows.get(bucket_date, (0, 0, None))
        check_count = max(0, int(check_count or 0))
        success_count = max(0, min(check_count, int(success_count or 0)))
        timeline.append(
            {
                "bucket_date": bucket_date,
                "status": classify_health_bucket(check_count, success_count),
                "check_count": check_count,
                "success_count": success_count,
                "failure_count": max(0, check_count - success_count),
                "availability_percent": round((success_count / check_count) * 100, 2) if check_count else None,
                "avg_latency_ms": int(round(float(avg_latency))) if avg_latency is not None else None,
            }
        )
        cursor += timedelta(days=1)
    return timeline


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error_code(exc: BaseException) -> str:
    """Return a bounded, stable error code without persisting provider text."""
    value = getattr(exc, "code", None) or "AI_MODEL_HEALTH_CHECK_FAILED"
    return str(value).strip()[:120] or "AI_MODEL_HEALTH_CHECK_FAILED"


def _sla_from_row(row: Any) -> dict[str, Any]:
    check_count = int(row[0] or 0) if row else 0
    success_count = int(row[1] or 0) if row else 0
    failure_count = max(0, check_count - success_count)
    avg_latency = row[2] if row and row[2] is not None else None
    return {
        "window_hours": MODEL_HEALTH_WINDOW_HOURS,
        "check_count": check_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "availability_percent": round((success_count / check_count) * 100, 2) if check_count else None,
        "avg_latency_ms": int(round(float(avg_latency))) if avg_latency is not None else None,
    }


def get_model_sla(conn: Any, model_id: str) -> dict[str, Any]:
    window_start = (datetime.now(timezone.utc) - timedelta(hours=MODEL_HEALTH_WINDOW_HOURS)).isoformat()
    row = conn.execute(
        """
        SELECT COUNT(*),
               SUM(CASE WHEN status = 'healthy' THEN 1 ELSE 0 END),
               AVG(CASE WHEN status = 'healthy' THEN latency_ms END)
        FROM ai_model_health_check
        WHERE model_id = ? AND checked_at >= ?
        """,
        (model_id, window_start),
    ).fetchone()
    return _sla_from_row(row)


def _record_model_health(
    model_id: str,
    *,
    status: str,
    checked_at: str,
    latency_ms: int,
    error_code: Optional[str],
) -> dict[str, Any]:
    with get_db_connection() as conn:
        if status == "healthy":
            conn.execute(
                """
                UPDATE ai_model
                SET health_status = ?, last_health_check_at = ?, last_latency_ms = ?,
                    last_success_at = ?, last_error_code = NULL
                WHERE id = ?
                """,
                (status, checked_at, latency_ms, checked_at, model_id),
            )
        else:
            conn.execute(
                """
                UPDATE ai_model
                SET health_status = ?, last_health_check_at = ?, last_latency_ms = ?,
                    last_error_code = ?
                WHERE id = ?
                """,
                (status, checked_at, latency_ms, error_code, model_id),
            )
        conn.execute(
            """
            INSERT INTO ai_model_health_check
                (id, model_id, checked_at, status, latency_ms, error_code)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (f"mhc_{uuid.uuid4().hex[:16]}", model_id, checked_at, status, latency_ms, error_code),
        )
        conn.commit()
        return get_model_sla(conn, model_id)


def _non_probe_result(
    model: Any,
    *,
    status: str,
    error_code: Optional[str],
    message: str,
) -> dict[str, Any]:
    return {
        "model_id": model[0],
        "model_name": model[1],
        "model_code": model[2],
        "success": False,
        "health_status": status,
        "latency_ms": 0,
        "last_health_check_at": None,
        "error_code": error_code,
        "message": message,
        "sla": {
            "window_hours": MODEL_HEALTH_WINDOW_HOURS,
            "check_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "availability_percent": None,
            "avg_latency_ms": None,
        },
    }


async def check_model_health(
    model_id: str,
    *,
    user_id: str = "system:model-health-monitor",
    tenant_id: str = "tenant-default",
    roles: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Run one safe health probe for an enabled chat-capable model."""
    with get_db_connection() as conn:
        model = conn.execute(
            """
            SELECT m.id, m.name, m.model_code, m.model_type, m.enabled,
                   COALESCE(p.enabled, 0), m.last_health_check_at, m.health_status
            FROM ai_model m
            LEFT JOIN ai_provider p ON p.id = m.provider_id
            WHERE m.id = ?
            """,
            (model_id,),
        ).fetchone()

    if not model:
        return {
            "model_id": model_id,
            "model_name": None,
            "model_code": None,
            "success": False,
            "health_status": "unknown",
            "latency_ms": 0,
            "last_health_check_at": None,
            "error_code": "AI_MODEL_NOT_FOUND",
            "message": "model was not found",
            "sla": {
                "window_hours": MODEL_HEALTH_WINDOW_HOURS,
                "check_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "availability_percent": None,
                "avg_latency_ms": None,
            },
        }
    if not model[4]:
        return _non_probe_result(model, status="disabled", error_code="AI_MODEL_DISABLED", message="model is disabled")
    if not model[5]:
        return _non_probe_result(model, status="disabled", error_code="AI_PROVIDER_DISABLED", message="provider is disabled")
    if str(model[3] or "chat").lower() not in {"chat", "reasoning"}:
        return _non_probe_result(
            model,
            status="not_supported",
            error_code="AI_MODEL_HEALTH_UNSUPPORTED_TYPE",
            message="health probes support chat and reasoning models only",
        )

    # Keep manual retries bounded as well as scheduled probes.  This mirrors
    # the provider-level health backoff and prevents a double-click/retry loop
    # from becoming an avoidable token spend.
    last_check = model[6]
    if last_check:
        try:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(str(last_check).replace("Z", "+00:00"))).total_seconds()
            backoff = max(0, int(getattr(settings, "AI_HEALTH_BACKOFF_SECONDS", 30)))
            if elapsed < backoff:
                with get_db_connection() as conn:
                    sla = get_model_sla(conn, model_id)
                return {
                    "model_id": model[0],
                    "model_name": model[1],
                    "model_code": model[2],
                    "success": False,
                    "health_status": model[7] or "unknown",
                    "latency_ms": 0,
                    "last_health_check_at": last_check,
                    "error_code": "AI_HEALTH_BACKOFF",
                    "message": "health probe backoff is active",
                    "sla": sla,
                }
        except (TypeError, ValueError):
            pass

    started = time.perf_counter()
    try:
        await llm_gateway.chat(
            scene=MODEL_HEALTH_SCENE,
            model_id=model[0],
            messages=[{"role": "user", "content": MODEL_HEALTH_MESSAGE}],
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles or ["admin", "system"],
            max_tokens=max(16, int(getattr(settings, "AI_MODEL_HEALTH_MAX_TOKENS", 64))),
            data_classification="PUBLIC",
            selection_source="model_health_monitor",
        )
        status = "healthy"
        error_code = None
        success = True
        message = "model health check succeeded through security gateway"
    except AIException as exc:
        status = "unhealthy"
        error_code = _error_code(exc)
        success = False
        message = "model health check blocked or failed"
    except Exception:
        status = "unhealthy"
        error_code = "AI_MODEL_HEALTH_CHECK_FAILED"
        success = False
        message = "model health check blocked or failed"
        logger.exception("Unexpected model health probe failure model_id=%s", model_id)

    latency_ms = max(0, int((time.perf_counter() - started) * 1000))
    checked_at = utc_now_iso()
    sla = _record_model_health(
        model_id,
        status=status,
        checked_at=checked_at,
        latency_ms=latency_ms,
        error_code=error_code,
    )
    return {
        "model_id": model[0],
        "model_name": model[1],
        "model_code": model[2],
        "success": success,
        "health_status": status,
        "latency_ms": latency_ms,
        "last_health_check_at": checked_at,
        "error_code": error_code,
        "message": message,
        "sla": sla,
    }


def cleanup_model_health_history() -> None:
    retention_days = max(1, int(getattr(settings, "AI_MODEL_HEALTH_RETENTION_DAYS", 30)))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    with get_db_connection() as conn:
        conn.execute("DELETE FROM ai_model_health_check WHERE checked_at < ?", (cutoff,))
        conn.commit()


async def run_scheduled_model_health_checks() -> dict[str, int]:
    """Probe all enabled chat/reasoning models with bounded concurrency."""
    if not bool(getattr(settings, "AI_MODEL_HEALTH_MONITOR_ENABLED", True)):
        return {"checked": 0, "healthy": 0, "unhealthy": 0, "skipped": 0}
    if not (bool(getattr(settings, "AI_ENABLED", False)) or bool(getattr(settings, "EXTERNAL_AI_ENABLED", False))):
        logger.debug("AI model health monitor skipped because external AI is disabled")
        return {"checked": 0, "healthy": 0, "unhealthy": 0, "skipped": 0}

    with get_db_connection() as conn:
        models = conn.execute(
            """
            SELECT m.id
            FROM ai_model m
            JOIN ai_provider p ON p.id = m.provider_id
            WHERE m.enabled = 1 AND p.enabled = 1
              AND LOWER(COALESCE(m.model_type, 'chat')) IN ('chat', 'reasoning')
            ORDER BY m.priority DESC, m.created_at DESC
            """
        ).fetchall()

    semaphore = asyncio.Semaphore(max(1, int(getattr(settings, "AI_MODEL_HEALTH_MAX_CONCURRENCY", 2))))

    async def probe(row: Any) -> dict[str, Any]:
        async with semaphore:
            return await check_model_health(str(row[0]))

    results = await asyncio.gather(*(probe(row) for row in models), return_exceptions=True)
    healthy = sum(1 for result in results if isinstance(result, dict) and result.get("success"))
    unhealthy = sum(1 for result in results if isinstance(result, dict) and not result.get("success"))
    unexpected = sum(1 for result in results if isinstance(result, BaseException))
    if unexpected:
        logger.error("AI model health monitor had %s unexpected probe failures", unexpected)
    cleanup_model_health_history()
    if models:
        logger.info(
            "AI model health monitor completed checked=%s healthy=%s unhealthy=%s",
            len(models), healthy, unhealthy + unexpected,
        )
    return {"checked": len(models), "healthy": healthy, "unhealthy": unhealthy + unexpected, "skipped": 0}
