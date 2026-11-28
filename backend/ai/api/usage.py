"""
FastAPI Router for AI Audit Logs & Token Usage Statistics
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from database.core import get_db_connection
from ai.security.permissions import require_ai_permission
from ai.services.metrics import ai_metrics
from ai.services.job_observability import snapshot as job_observability_snapshot
from ai.services.database_observability import snapshot as database_observability_snapshot
from core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["AI Audit & Usage"])


def _load_provider_model_names(conn: Any) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """Load provider_id -> display name and model_id -> (name, model_code) maps."""
    provider_names: dict[str, str] = {}
    model_names: dict[str, tuple[str, str]] = {}
    conn.execute("SAVEPOINT ai_usage_provider_names")
    try:
        for row in conn.execute("SELECT id, name, provider_type FROM ai_provider").fetchall():
            pid = str(row[0] or "").strip()
            if pid:
                provider_names[pid] = str(row[1] or row[2] or pid).strip()
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT ai_usage_provider_names")
        logger.debug("Provider display names unavailable: %s", type(exc).__name__)
    finally:
        conn.execute("RELEASE SAVEPOINT ai_usage_provider_names")
    conn.execute("SAVEPOINT ai_usage_model_names")
    try:
        for row in conn.execute("SELECT id, name, model_code, display_name FROM ai_model").fetchall():
            mid = str(row[0] or "").strip()
            if mid:
                display = str(row[3] or row[1] or row[2] or mid).strip()
                code = str(row[2] or row[1] or mid).strip()
                model_names[mid] = (display, code)
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT ai_usage_model_names")
        logger.debug("Model display names unavailable: %s", type(exc).__name__)
    finally:
        conn.execute("RELEASE SAVEPOINT ai_usage_model_names")
    return provider_names, model_names


def _is_internal_hex_id(value: str, prefix: str) -> bool:
    if value.startswith(prefix):
        tail = value[len(prefix):]
        if len(tail) >= 8 and all(ch in "0123456789abcdefABCDEF" for ch in tail):
            return True
    return len(value) == 36 and value.count("-") == 4


def _resolve_provider_display(provider_id: Optional[str], provider_names: dict[str, str]) -> str:
    pid = str(provider_id or "").strip()
    if not pid:
        return "未知供应商"
    if pid in provider_names:
        return provider_names[pid]
    return "历史供应商 (已删除)" if _is_internal_hex_id(pid, "prov_") else pid


def _resolve_model_display(model_id: Optional[str], model_names: dict[str, tuple[str, str]]) -> tuple[str, str]:
    mid = str(model_id or "").strip()
    if not mid:
        return ("未知模型", "")
    if mid in model_names:
        return model_names[mid]
    if _is_internal_hex_id(mid, "model_"):
        return ("历史模型 (已删除)", "")
    return (mid, mid)


@router.get("/audit", response_model=List[Dict[str, Any]])
def list_ai_audit_logs(
    limit: int = Query(50, ge=1, le=500),
    scene: Optional[str] = None,
    user=Depends(require_ai_permission("ai.usage.view"))
):
    """List AI Request Audit Logs.

    Request logs cover every user, so they need ``ai.usage.view``
    (Administrator by default) rather than the broader ``ai.audit.view``.
    """
    with get_db_connection() as conn:
        provider_names, model_names = _load_provider_model_names(conn)
        cursor = conn.cursor()
        query = """
            SELECT id, request_id, user_id, scene, provider_id, model_id, prompt_id,
                   input_tokens, output_tokens, latency_ms, status, error_code, error_message, created_at
            FROM ai_request_log
        """
        params = []
        if scene:
            query += " WHERE scene = ?"
            params.append(scene)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        result = []
        for r in rows:
            m_name, m_code = _resolve_model_display(r[5], model_names)
            p_name = _resolve_provider_display(r[4], provider_names)
            result.append({
                "id": r[0],
                "request_id": r[1],
                "user_id": r[2],
                "scene": r[3],
                "provider_id": r[4],
                "provider_name": p_name,
                "model_id": r[5],
                "model_name": m_name,
                "model_code": m_code,
                "prompt_id": r[6],
                "input_tokens": r[7],
                "output_tokens": r[8],
                "latency_ms": r[9],
                "status": r[10],
                "error_code": r[11],
                "error_message": r[12],
                "created_at": r[13],
            })
        return result


@router.get("/usage/summary", response_model=Dict[str, Any])
def get_usage_summary(user=Depends(require_ai_permission("ai.usage.view"))):
    """Get overall Token Usage & Request Aggregations."""
    with get_db_connection() as conn:
        provider_names, model_names = _load_provider_model_names(conn)
        cursor = conn.cursor()
        
        # Overall totals
        cursor.execute(
            """
            SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens), AVG(latency_ms)
            FROM ai_request_log
            """
        )
        row = cursor.fetchone()
        total_requests = row[0] or 0
        total_input_tokens = row[1] or 0
        total_output_tokens = row[2] or 0
        avg_latency_ms = float(row[3] or 0.0)

        # Requests by scene
        cursor.execute(
            """
            SELECT scene, COUNT(*) FROM ai_request_log GROUP BY scene
            """
        )
        scene_breakdown = {r[0]: r[1] for r in cursor.fetchall()}

        estimated_cost = 0.0
        daily_estimated_cost = 0.0
        today_key = datetime.now(timezone.utc).date().isoformat()
        provider_breakdown: dict[str, dict[str, Any]] = {}
        try:
            try:
                cursor.execute(
                    "SELECT provider_id, model_id, SUM(requests), SUM(input_tokens), SUM(output_tokens), "
                    "SUM(estimated_cost), "
                    "COALESCE(SUM(avg_latency * requests) / NULLIF(SUM(requests), 0), 0), "
                    "SUM(success_count), SUM(error_count) "
                    "FROM ai_usage_daily GROUP BY provider_id, model_id ORDER BY SUM(estimated_cost) DESC"
                )
                usage_rows = cursor.fetchall()
            except Exception:
                # Older installations may not have the additive success/error
                # counters yet; keep the cost/latency view readable there.
                conn.rollback()
                cursor.execute(
                    "SELECT provider_id, model_id, SUM(requests), SUM(input_tokens), SUM(output_tokens), "
                    "SUM(estimated_cost), "
                    "COALESCE(SUM(avg_latency * requests) / NULLIF(SUM(requests), 0), 0) "
                    "FROM ai_usage_daily GROUP BY provider_id, model_id ORDER BY SUM(estimated_cost) DESC"
                )
                usage_rows = [(*item, None, None) for item in cursor.fetchall()]
            for item in usage_rows:
                cost = float(item[5] or 0)
                requests = int(item[2] or 0)
                success_count = int(item[7] or 0)
                error_count = int(item[8] or 0)
                if item[7] is None and item[8] is None:
                    success_count = requests
                estimated_cost += cost
                p_name = _resolve_provider_display(item[0], provider_names)
                m_name, m_code = _resolve_model_display(item[1], model_names)
                provider_breakdown[f"{item[0]}:{item[1]}"] = {
                    "provider_id": item[0],
                    "provider_name": p_name,
                    "model_id": item[1],
                    "model_name": m_name,
                    "model_code": m_code,
                    "requests": requests, "success": success_count, "errors": error_count,
                    "error_rate": round(error_count / requests, 4) if requests else 0,
                    "input_tokens": int(item[3] or 0),
                    "output_tokens": int(item[4] or 0), "estimated_cost_usd": round(cost, 6),
                    "avg_latency_ms": round(float(item[6] or 0), 2),
                }
            daily_row = cursor.execute(
                "SELECT COALESCE(SUM(estimated_cost), 0) FROM ai_usage_daily WHERE date = ?",
                (today_key,),
            ).fetchone()
            daily_estimated_cost = float((daily_row or [0])[0] or 0)
        except Exception as exc:
            # Totals above are still valid; only the cost/provider breakdown is missing.
            logger.warning("AI usage cost/provider breakdown unavailable; returning totals only code=AI_USAGE_BREAKDOWN_FAILED error=%s", type(exc).__name__)
        budget = float(getattr(settings, "AI_DAILY_BUDGET_USD", 0) or 0)

        return {
            "total_requests": total_requests,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            "avg_latency_ms": round(avg_latency_ms, 2),
            "scene_breakdown": scene_breakdown,
            "estimated_cost_usd": round(estimated_cost, 6),
            "daily_estimated_cost_usd": round(daily_estimated_cost, 6),
            "budget_usd": budget,
            "budget_percent": round((daily_estimated_cost / budget) * 100, 2) if budget > 0 else 0,
            "budget_alert": bool(budget > 0 and daily_estimated_cost >= budget * 0.8),
            "provider_breakdown": provider_breakdown,
        }


@router.get("/metrics", response_model=Dict[str, Any])
def get_ai_metrics(user=Depends(require_ai_permission("ai.usage.view"))):
    """Return low-cardinality provider/tool/agent metrics without payloads."""
    metrics = ai_metrics.snapshot()
    metrics["jobs"]["observability"] = job_observability_snapshot()
    metrics["database"] = database_observability_snapshot()
    return metrics
