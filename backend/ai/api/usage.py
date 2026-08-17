"""
FastAPI Router for AI Audit Logs & Token Usage Statistics
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from database.core import get_db_connection
from ai.security.permissions import require_ai_permission
from ai.services.metrics import ai_metrics
from ai.services.job_observability import snapshot as job_observability_snapshot
from ai.services.database_observability import snapshot as database_observability_snapshot
from core.config import settings

router = APIRouter(tags=["AI Audit & Usage"])


@router.get("/audit", response_model=List[Dict[str, Any]])
def list_ai_audit_logs(
    limit: int = Query(50, ge=1, le=500),
    scene: Optional[str] = None,
    user=Depends(require_ai_permission("ai.audit.view"))
):
    """List AI Request Audit Logs."""
    with get_db_connection() as conn:
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
            result.append({
                "id": r[0],
                "request_id": r[1],
                "user_id": r[2],
                "scene": r[3],
                "provider_id": r[4],
                "model_id": r[5],
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
def get_usage_summary(user=Depends(require_ai_permission("ai.audit.view"))):
    """Get overall Token Usage & Request Aggregations."""
    with get_db_connection() as conn:
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
        provider_breakdown: dict[str, dict[str, Any]] = {}
        try:
            try:
                cursor.execute("SELECT provider_id, model_id, SUM(requests), SUM(input_tokens), SUM(output_tokens), SUM(estimated_cost), AVG(avg_latency), SUM(success_count), SUM(error_count) FROM ai_usage_daily GROUP BY provider_id, model_id ORDER BY SUM(estimated_cost) DESC")
                usage_rows = cursor.fetchall()
            except Exception:
                # Older installations may not have the additive success/error
                # counters yet; keep the cost/latency view readable there.
                conn.rollback()
                cursor.execute("SELECT provider_id, model_id, SUM(requests), SUM(input_tokens), SUM(output_tokens), SUM(estimated_cost), AVG(avg_latency) FROM ai_usage_daily GROUP BY provider_id, model_id ORDER BY SUM(estimated_cost) DESC")
                usage_rows = [(*item, None, None) for item in cursor.fetchall()]
            for item in usage_rows:
                cost = float(item[5] or 0)
                requests = int(item[2] or 0)
                success_count = int(item[7] or 0)
                error_count = int(item[8] or 0)
                if item[7] is None and item[8] is None:
                    success_count = requests
                estimated_cost += cost
                provider_breakdown[f"{item[0]}:{item[1]}"] = {
                    "requests": requests, "success": success_count, "errors": error_count,
                    "error_rate": round(error_count / requests, 4) if requests else 0,
                    "input_tokens": int(item[3] or 0),
                    "output_tokens": int(item[4] or 0), "estimated_cost_usd": round(cost, 6),
                    "avg_latency_ms": round(float(item[6] or 0), 2),
                }
        except Exception:
            pass
        budget = float(getattr(settings, "AI_DAILY_BUDGET_USD", 0) or 0)

        return {
            "total_requests": total_requests,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            "avg_latency_ms": round(avg_latency_ms, 2),
            "scene_breakdown": scene_breakdown,
            "estimated_cost_usd": round(estimated_cost, 6),
            "budget_usd": budget,
            "budget_percent": round((estimated_cost / budget) * 100, 2) if budget > 0 else 0,
            "budget_alert": bool(budget > 0 and estimated_cost >= budget * 0.8),
            "provider_breakdown": provider_breakdown,
        }


@router.get("/metrics", response_model=Dict[str, Any])
def get_ai_metrics(user=Depends(require_ai_permission("ai.audit.view"))):
    """Return low-cardinality provider/tool/agent metrics without payloads."""
    metrics = ai_metrics.snapshot()
    metrics["jobs"]["observability"] = job_observability_snapshot()
    metrics["database"] = database_observability_snapshot()
    return metrics
