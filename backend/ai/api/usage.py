"""
FastAPI Router for AI Audit Logs & Token Usage Statistics
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from database.core import get_db_connection
from ai.security.permissions import require_ai_permission
from ai.services.metrics import ai_metrics

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

        return {
            "total_requests": total_requests,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            "avg_latency_ms": round(avg_latency_ms, 2),
            "scene_breakdown": scene_breakdown
        }


@router.get("/metrics", response_model=Dict[str, Any])
def get_ai_metrics(user=Depends(require_ai_permission("ai.audit.view"))):
    """Return low-cardinality provider/tool/agent metrics without payloads."""
    return ai_metrics.snapshot()
