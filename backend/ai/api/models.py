"""
FastAPI Router for AI Models & Model Scene Routes
"""

from __future__ import annotations

import uuid
import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from database.core import get_db_connection
from ai.security.permissions import require_ai_permission
from ai.services.model_health import build_health_timeline, check_model_health
from ai.schemas.model import (
    AIModelCreate,
    AIModelHealthCheckResponse,
    AIModelHealthServiceResponse,
    AIModelHealthSummaryResponse,
    AIModelHealthTimelinePoint,
    AIModelResponse,
    AIModelRouteCreate,
    AIModelRouteResponse,
    AIModelUpdate,
)
from api.knowledge_contracts import DefaultModelRequest, ModelAccessRequest
from ai.security.tokenization import opaque_user_id

router = APIRouter(prefix="/models", tags=["AI Models & Routes"])


def _sla_window_start() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()


_MODEL_SELECT = """
    SELECT m.id, m.provider_id, m.name, m.model_code, m.model_type, m.thinking_supported,
           m.tool_call_supported, m.json_supported, m.context_length, m.max_output_tokens,
           m.default_temperature, m.default_max_tokens, m.enabled, m.is_default, m.priority,
           m.created_at, m.updated_at, m.stream_supported, m.display_name,
           m.cost_input_per_1k, m.cost_output_per_1k,
           m.health_status, m.last_health_check_at, m.last_latency_ms,
           m.last_success_at, m.last_error_code,
           COALESCE(h.check_count, 0), COALESCE(h.success_count, 0), h.avg_latency_ms
    FROM ai_model m
    LEFT JOIN (
        SELECT model_id,
               COUNT(*) AS check_count,
               SUM(CASE WHEN status = 'healthy' THEN 1 ELSE 0 END) AS success_count,
               AVG(CASE WHEN status = 'healthy' THEN latency_ms END) AS avg_latency_ms
        FROM ai_model_health_check
        WHERE checked_at >= ?
        GROUP BY model_id
    ) h ON h.model_id = m.id
"""


def _model_from_row(r) -> AIModelResponse:
    check_count = int(r[26] or 0) if len(r) > 26 else 0
    success_count = int(r[27] or 0) if len(r) > 27 else 0
    return AIModelResponse(
        id=r[0], provider_id=r[1], name=r[2], model_code=r[3], model_type=r[4], thinking_supported=bool(r[5]),
        tool_call_supported=bool(r[6]), json_supported=bool(r[7]), context_length=r[8], max_output_tokens=r[9],
        default_temperature=r[10], default_max_tokens=r[11], enabled=bool(r[12]), is_default=bool(r[13]), priority=r[14],
        created_at=r[15], updated_at=r[16], stream_supported=bool(r[17] if len(r) > 17 and r[17] is not None else 1),
        display_name=(r[18] if len(r) > 18 else None), cost_input_per_1k=float(r[19] or 0) if len(r) > 19 else 0,
        cost_output_per_1k=float(r[20] or 0) if len(r) > 20 else 0,
        health_status=(r[21] if len(r) > 21 and r[21] else "unknown"),
        last_health_check_at=(r[22] if len(r) > 22 else None),
        last_latency_ms=(int(r[23]) if len(r) > 23 and r[23] is not None else None),
        last_success_at=(r[24] if len(r) > 24 else None),
        last_error_code=(r[25] if len(r) > 25 else None),
        sla_check_count=check_count,
        sla_success_count=success_count,
        sla_failure_count=max(0, check_count - success_count),
        sla_availability_percent=round((success_count / check_count) * 100, 2) if check_count else None,
        sla_avg_latency_ms=(int(round(float(r[28]))) if len(r) > 28 and r[28] is not None else None),
    )


# --- AI Models CRUD ---
@router.get("", response_model=List[AIModelResponse])
def list_models(user=Depends(require_ai_permission("ai.view"))):
    """List all configured AI Models."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(_MODEL_SELECT + " ORDER BY m.priority DESC, m.created_at DESC", (_sla_window_start(),))
        rows = cursor.fetchall()
        visible = []
        tenant_id = str(user.get("tenant_id") or "tenant-default")
        user_id = str(user.get("id") or user.get("username") or "")
        roles = {str(user.get("role") or "")}
        for row in rows:
            acl_rows = cursor.execute("SELECT subject_type, subject_id, allow_access FROM ai_model_acl WHERE model_id = ? AND tenant_id = ?", (row[0], tenant_id)).fetchall()
            if not acl_rows or any(bool(a[2]) and ((a[0] == "role" and a[1] in roles) or (a[0] == "user" and a[1] == user_id) or (a[0] == "tenant" and a[1] == tenant_id)) for a in acl_rows):
                visible.append(_model_from_row(row))
        return visible


@router.post("", response_model=AIModelResponse, status_code=status.HTTP_201_CREATED)
def create_model(payload: AIModelCreate, user=Depends(require_ai_permission("ai.model.manage"))):
    """Create a new AI Model."""
    now_iso = datetime.now(timezone.utc).isoformat()
    m_id = f"model_{uuid.uuid4().hex[:12]}"
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        provider_row = cursor.execute(
            "SELECT provider_type, enabled FROM ai_provider WHERE id = ?",
            (payload.provider_id,),
        ).fetchone()
        if not provider_row:
            raise HTTPException(status_code=404, detail='Provider not found')
        if not provider_row[1]:
            raise HTTPException(status_code=409, detail='Cannot add a model to a disabled provider')
        duplicate = cursor.execute("SELECT id FROM ai_model WHERE provider_id = ? AND model_code = ?", (payload.provider_id, payload.model_code)).fetchone()
        if duplicate:
            raise HTTPException(status_code=409, detail='model_code already exists for this provider')
        if payload.is_default:
            cursor.execute("UPDATE ai_model SET is_default = 0")
            
        cursor.execute(
            """
            INSERT INTO ai_model (
                id, provider_id, name, model_code, model_type, thinking_supported,
                tool_call_supported, json_supported, context_length, max_output_tokens,
                default_temperature, default_max_tokens, enabled, is_default, priority,
                created_at, updated_at, stream_supported, display_name, cost_input_per_1k, cost_output_per_1k
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                m_id, payload.provider_id, payload.name, payload.model_code, payload.model_type,
                int(payload.thinking_supported), int(payload.tool_call_supported),
                int(payload.json_supported), payload.context_length, payload.max_output_tokens,
                payload.default_temperature, payload.default_max_tokens, int(payload.enabled),
                int(payload.is_default), payload.priority, now_iso, now_iso, int(payload.stream_supported),
                payload.display_name or payload.name, payload.cost_input_per_1k, payload.cost_output_per_1k
            )
        )
        conn.commit()

    return AIModelResponse(
        id=m_id, provider_id=payload.provider_id, name=payload.name, model_code=payload.model_code,
        model_type=payload.model_type, thinking_supported=payload.thinking_supported,
        tool_call_supported=payload.tool_call_supported, json_supported=payload.json_supported,
        context_length=payload.context_length, max_output_tokens=payload.max_output_tokens,
        default_temperature=payload.default_temperature, default_max_tokens=payload.default_max_tokens,
        enabled=payload.enabled, is_default=payload.is_default, priority=payload.priority,
        created_at=now_iso, updated_at=now_iso
    )


@router.get("/health-summary", response_model=AIModelHealthSummaryResponse)
def model_health_summary(
    window_days: int = Query(90, ge=7, le=90),
    user=Depends(require_ai_permission("ai.view")),
):
    """Return finite daily status bars for the AI model status page."""
    now = datetime.now(timezone.utc)
    start_date = (now - timedelta(days=window_days - 1)).date()
    window_start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc).isoformat()
    end_date = now.date()

    with get_db_connection() as conn:
        cursor = conn.cursor()
        model_rows = cursor.execute(
            """
            SELECT m.id, m.provider_id, p.name, m.name, m.model_code, m.model_type,
                   m.enabled, p.enabled, m.health_status, m.last_health_check_at,
                   COALESCE(h.check_count, 0), COALESCE(h.success_count, 0), h.avg_latency_ms
            FROM ai_model m
            JOIN ai_provider p ON p.id = m.provider_id
            LEFT JOIN (
                SELECT model_id,
                       COUNT(*) AS check_count,
                       SUM(CASE WHEN status = 'healthy' THEN 1 ELSE 0 END) AS success_count,
                       AVG(CASE WHEN status = 'healthy' THEN latency_ms END) AS avg_latency_ms
                FROM ai_model_health_check
                WHERE checked_at >= ?
                GROUP BY model_id
            ) h ON h.model_id = m.id
            ORDER BY m.priority DESC, m.created_at DESC
            """,
            (window_start,),
        ).fetchall()
        daily_rows = cursor.execute(
            """
            SELECT model_id, substr(checked_at, 1, 10) AS bucket_date,
                   COUNT(*) AS check_count,
                   SUM(CASE WHEN status = 'healthy' THEN 1 ELSE 0 END) AS success_count,
                   AVG(CASE WHEN status = 'healthy' THEN latency_ms END) AS avg_latency_ms
            FROM ai_model_health_check
            WHERE checked_at >= ?
            GROUP BY model_id, substr(checked_at, 1, 10)
            ORDER BY bucket_date
            """,
            (window_start,),
        ).fetchall()

        tenant_id = str(user.get("tenant_id") or "tenant-default")
        user_id = str(user.get("id") or user.get("username") or "")
        roles = {str(user.get("role") or "")}
        visible_rows = []
        for row in model_rows:
            acl_rows = cursor.execute(
                "SELECT subject_type, subject_id, allow_access FROM ai_model_acl WHERE model_id = ? AND tenant_id = ?",
                (row[0], tenant_id),
            ).fetchall()
            if not acl_rows or any(
                bool(a[2]) and (
                    (a[0] == "role" and a[1] in roles)
                    or (a[0] == "user" and a[1] == user_id)
                    or (a[0] == "tenant" and a[1] == tenant_id)
                )
                for a in acl_rows
            ):
                visible_rows.append(row)

    daily_by_model: dict[str, dict[str, tuple[int, int, Optional[float]]]] = {}
    for row in daily_rows:
        daily_by_model.setdefault(str(row[0]), {})[str(row[1])] = (int(row[2] or 0), int(row[3] or 0), row[4])

    services: list[AIModelHealthServiceResponse] = []
    monitored_service_count = 0
    checked_service_count = 0
    total_checks = 0
    total_successes = 0
    weighted_latency = 0.0
    current_statuses: list[str] = []
    for row in visible_rows:
        model_type = str(row[5] or "chat").lower()
        monitorable = bool(row[6]) and bool(row[7]) and model_type in {"chat", "reasoning"}
        if not monitorable:
            health_status = "disabled" if not row[6] or not row[7] else "not_supported"
        else:
            health_status = str(row[8] or "unknown")
            monitored_service_count += 1
            if health_status in {"healthy", "unhealthy", "degraded"}:
                current_statuses.append(health_status)

        check_count = int(row[10] or 0)
        success_count = int(row[11] or 0)
        if check_count > 0:
            checked_service_count += 1
        total_checks += check_count
        total_successes += success_count
        if row[12] is not None:
            weighted_latency += float(row[12]) * success_count

        services.append(
            AIModelHealthServiceResponse(
                model_id=str(row[0]),
                provider_id=str(row[1]),
                provider_name=str(row[2] or ""),
                model_name=str(row[3] or row[4]),
                model_code=str(row[4]),
                model_type=model_type,
                enabled=bool(row[6]) and bool(row[7]),
                health_status=health_status,
                last_health_check_at=row[9],
                window_check_count=check_count,
                window_success_count=success_count,
                window_failure_count=max(0, check_count - success_count),
                window_availability_percent=round((success_count / check_count) * 100, 2) if check_count else None,
                window_avg_latency_ms=int(round(float(row[12]))) if row[12] is not None else None,
                timeline=[AIModelHealthTimelinePoint(**point) for point in build_health_timeline(daily_by_model.get(str(row[0]), {}), start_date=start_date, end_date=end_date)],
            )
        )

    total_failures = max(0, total_checks - total_successes)
    if not monitored_service_count:
        overall_status = "unknown"
    elif "unhealthy" in current_statuses:
        overall_status = "unhealthy"
    elif "degraded" in current_statuses:
        overall_status = "degraded"
    elif "unknown" in [service.health_status for service in services if service.health_status not in {"disabled", "not_supported"}]:
        overall_status = "unknown"
    else:
        overall_status = "healthy"

    return AIModelHealthSummaryResponse(
        window_days=window_days,
        window_start=window_start,
        generated_at=now.isoformat(),
        overall_status=overall_status,
        service_count=len(services),
        monitored_service_count=monitored_service_count,
        checked_service_count=checked_service_count,
        total_check_count=total_checks,
        total_success_count=total_successes,
        total_failure_count=total_failures,
        availability_percent=round((total_successes / total_checks) * 100, 2) if total_checks else None,
        avg_latency_ms=int(round(weighted_latency / total_successes)) if total_successes else None,
        services=services,
    )


@router.post("/{model_id}/health-check", response_model=AIModelHealthCheckResponse)
async def model_health_check(model_id: str, user=Depends(require_ai_permission("ai.model.manage"))):
    """Run one model health probe through the production AI gateway."""
    user_id = str(user.get("id") or user.get("username") or "model-health-check")
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    roles = [str(user.get("role"))] if user.get("role") else ["admin"]
    result = await check_model_health(
        model_id,
        user_id=user_id,
        tenant_id=tenant_id,
        roles=roles,
    )
    sla = result.get("sla") or {}
    return AIModelHealthCheckResponse(
        model_id=str(result.get("model_id") or model_id),
        model_name=result.get("model_name"),
        model_code=result.get("model_code"),
        success=bool(result.get("success")),
        health_status=str(result.get("health_status") or "unknown"),
        latency_ms=int(result.get("latency_ms") or 0),
        last_health_check_at=result.get("last_health_check_at"),
        error_code=result.get("error_code"),
        message=str(result.get("message") or "model health check completed"),
        sla_window_hours=int(sla.get("window_hours") or 24),
        sla_check_count=int(sla.get("check_count") or 0),
        sla_success_count=int(sla.get("success_count") or 0),
        sla_failure_count=int(sla.get("failure_count") or 0),
        sla_availability_percent=sla.get("availability_percent"),
        sla_avg_latency_ms=sla.get("avg_latency_ms"),
    )


@router.put("/{model_id}", response_model=AIModelResponse)
def update_model(model_id: str, payload: AIModelUpdate, user=Depends(require_ai_permission("ai.model.manage"))):
    now_iso = datetime.now(timezone.utc).isoformat()
    updates = payload.model_dump(exclude_none=True)
    with get_db_connection() as conn:
        current = conn.execute("SELECT id FROM ai_model WHERE id = ?", (model_id,)).fetchone()
        if not current:
            raise HTTPException(status_code=404, detail='Model not found')
        if "provider_id" in updates and not conn.execute("SELECT id FROM ai_provider WHERE id = ?", (updates["provider_id"],)).fetchone():
            raise HTTPException(status_code=404, detail='Provider not found')
        if "model_code" in updates and conn.execute("SELECT id FROM ai_model WHERE provider_id = COALESCE(?, provider_id) AND model_code = ? AND id <> ?", (updates.get("provider_id"), updates["model_code"], model_id)).fetchone():
            raise HTTPException(status_code=409, detail='model_code already exists for this provider')
        if updates.get("is_default"):
            conn.execute("UPDATE ai_model SET is_default = 0 WHERE id <> ?", (model_id,))
        allowed = {"provider_id", "name", "model_code", "model_type", "thinking_supported", "tool_call_supported", "json_supported", "context_length", "max_output_tokens", "default_temperature", "default_max_tokens", "enabled", "is_default", "priority", "stream_supported", "display_name", "cost_input_per_1k", "cost_output_per_1k"}
        fields = [key for key in updates if key in allowed]
        if fields:
            conn.execute(f"UPDATE ai_model SET {', '.join(f'{key} = ?' for key in fields)}, updated_at = ? WHERE id = ?", tuple(updates[key] for key in fields) + (now_iso, model_id))
        else:
            conn.execute("UPDATE ai_model SET updated_at = ? WHERE id = ?", (now_iso, model_id))
        conn.commit()
        row = conn.execute(_MODEL_SELECT + " WHERE m.id = ?", (_sla_window_start(), model_id)).fetchone()
    return _model_from_row(row)


@router.post("/{model_id}/access")
def set_model_access(model_id: str, payload: ModelAccessRequest, user=Depends(require_ai_permission("ai.model.manage"))):
    tenant_id = str(payload.tenant_id or user.get("tenant_id") or "tenant-default")
    subject_type = payload.subject_type
    subject_id = payload.subject_id
    allow_access = payload.allow_access
    if subject_type not in {"role", "user", "tenant"}:
        raise HTTPException(status_code=400, detail='subject_type must be role, user or tenant')
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        if not conn.execute("SELECT id FROM ai_model WHERE id = ?", (model_id,)).fetchone():
            raise HTTPException(status_code=404, detail='Model not found')
        row = conn.execute("SELECT id FROM ai_model_acl WHERE model_id = ? AND tenant_id = ? AND subject_type = ? AND subject_id = ?", (model_id, tenant_id, subject_type, subject_id)).fetchone()
        if row:
            conn.execute("UPDATE ai_model_acl SET allow_access = ?, created_by = ?, created_at = ? WHERE id = ?", (int(allow_access), user.get("username", "admin"), now_iso, row[0]))
        else:
            conn.execute("INSERT INTO ai_model_acl (id, model_id, tenant_id, subject_type, subject_id, allow_access, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (f"acl_{uuid.uuid4().hex[:12]}", model_id, tenant_id, subject_type, subject_id, int(allow_access), user.get("username", "admin"), now_iso))
        conn.commit()
    return {"model_id": model_id, "tenant_id": tenant_id, "subject_type": subject_type, "subject_id": subject_id, "allow_access": allow_access}


@router.post("/preferences/default")
def set_default_model(payload: DefaultModelRequest, user=Depends(require_ai_permission("ai.assistant"))):
    model_id = payload.model_id
    if not model_id:
        raise HTTPException(status_code=400, detail="model_id is required")
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    user_id = str(user.get("id") or user.get("username") or "")
    opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id="model-preference")
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        model = conn.execute("SELECT m.id FROM ai_model m JOIN ai_provider p ON p.id = m.provider_id WHERE m.id = ? AND m.enabled = 1 AND p.enabled = 1", (model_id,)).fetchone()
        if not model:
            raise HTTPException(status_code=404, detail="Model not found or disabled")
        acl = conn.execute("SELECT subject_type, subject_id, allow_access FROM ai_model_acl WHERE model_id = ? AND tenant_id = ?", (model_id, tenant_id)).fetchall()
        if acl and not any(bool(a[2]) and ((a[0] == "role" and a[1] == str(user.get("role") or "")) or (a[0] == "user" and a[1] == user_id) or (a[0] == "tenant" and a[1] == tenant_id)) for a in acl):
            raise HTTPException(status_code=403, detail="Model is not authorized for this user")
        row = conn.execute("SELECT id FROM ai_user_model_preference WHERE tenant_id = ? AND user_id_opaque = ?", (tenant_id, opaque)).fetchone()
        if row:
            conn.execute("UPDATE ai_user_model_preference SET model_id = ?, enabled = 1, updated_at = ? WHERE id = ?", (model_id, now_iso, row[0]))
        else:
            conn.execute("INSERT INTO ai_user_model_preference (id, tenant_id, user_id_opaque, model_id, enabled, updated_at) VALUES (?, ?, ?, ?, 1, ?)", (f"pref_{uuid.uuid4().hex[:12]}", tenant_id, opaque, model_id, now_iso))
        conn.commit()
    return {"model_id": model_id, "tenant_id": tenant_id, "updated_at": now_iso}


@router.get("/{model_id}/delete-preview")
def model_delete_preview(model_id: str, user=Depends(require_ai_permission("ai.model.manage"))):
    """Return safe, non-destructive dependency information for model deletion."""
    with get_db_connection() as conn:
        model = conn.execute(
            "SELECT id, name, model_code FROM ai_model WHERE id = ?",
            (model_id,),
        ).fetchone()
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
        routes = conn.execute(
            "SELECT scene, model_id, fallback_model_id FROM ai_model_route "
            "WHERE model_id = ? OR fallback_model_id = ? ORDER BY scene",
            (model_id, model_id),
        ).fetchall()
        message_count = conn.execute(
            "SELECT COUNT(*) FROM ai_messages WHERE requested_model_id = ? OR actual_model_id = ?",
            (model_id, model_id),
        ).fetchone()[0]
    return {
        "model_id": model[0],
        "model_name": model[1],
        "model_code": model[2],
        "route_count": len(routes),
        "routes": [
            {"scene": row[0], "model_id": row[1], "fallback_model_id": row[2]}
            for row in routes
        ],
        "message_count": int(message_count),
        "can_delete": not routes and not message_count,
    }


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(model_id: str, user=Depends(require_ai_permission("ai.model.manage"))):
    """Delete an AI Model."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        refs = cursor.execute("SELECT COUNT(*) FROM ai_model_route WHERE model_id = ? OR fallback_model_id = ?", (model_id, model_id)).fetchone()[0]
        if refs:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "AI_MODEL_HAS_ROUTES",
                    "message": "该模型仍被业务场景路由使用，暂时不能删除。请先修改或移除这些路由；如果只是暂时不用，可以直接禁用模型。",
                    "details": {
                        "route_count": int(refs),
                        "next_action": "update_or_remove_model_routes",
                    },
                },
            )
        msg_refs = cursor.execute("SELECT COUNT(*) FROM ai_messages WHERE requested_model_id = ? OR actual_model_id = ?", (model_id, model_id)).fetchone()[0]
        if msg_refs:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "AI_MODEL_HAS_PROVENANCE",
                    "message": "该模型已被历史对话引用，不能物理删除。为保留历史溯源，请直接禁用模型。",
                    "details": {
                        "message_count": int(msg_refs),
                        "next_action": "disable_model",
                    },
                },
            )
        cursor.execute("DELETE FROM ai_model WHERE id = ?", (model_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail='Model not found')
        conn.commit()
    return None


# --- AI Scene Routes CRUD ---
@router.get("/routes", response_model=List[AIModelRouteResponse])
def list_routes(user=Depends(require_ai_permission("ai.view"))):
    """List all AI Scene Routes."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, scene, model_id, fallback_model_id, enabled, priority, data_classification, created_at, updated_at FROM ai_model_route ORDER BY scene, priority DESC")
        except Exception:
            cursor.execute("SELECT id, scene, model_id, fallback_model_id, enabled, 10, 'PUBLIC', created_at, updated_at FROM ai_model_route ORDER BY scene")
        rows = cursor.fetchall()
        return [
            AIModelRouteResponse(
                id=r[0], scene=r[1], model_id=r[2], fallback_model_id=r[3],
                enabled=bool(r[4]), priority=int(r[5] or 10), data_classification=r[6] or "PUBLIC", created_at=r[7], updated_at=r[8]
            ) for r in rows
        ]


@router.post("/routes", response_model=AIModelRouteResponse)
def upsert_route(payload: AIModelRouteCreate, user=Depends(require_ai_permission("ai.model.manage"))):
    """Upsert Scene Model Route."""
    now_iso = datetime.now(timezone.utc).isoformat()
    r_id = f"route_{uuid.uuid4().hex[:12]}"
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        primary = cursor.execute("SELECT id, provider_id, enabled FROM ai_model WHERE id = ?", (payload.model_id,)).fetchone()
        if not primary or not primary[2]:
            raise HTTPException(status_code=400, detail='Primary model is not enabled')
        if payload.fallback_model_id:
            fallback = cursor.execute("SELECT id, enabled FROM ai_model WHERE id = ?", (payload.fallback_model_id,)).fetchone()
            if not fallback or not fallback[1]:
                raise HTTPException(status_code=400, detail='Fallback model is not enabled')
        cursor.execute("SELECT id FROM ai_model_route WHERE scene = ?", (payload.scene,))
        row = cursor.fetchone()
        if row:
            cursor.execute(
                """
                UPDATE ai_model_route SET model_id = ?, fallback_model_id = ?, enabled = ?, priority = ?, data_classification = ?, updated_at = ?
                WHERE scene = ?
                """,
                (payload.model_id, payload.fallback_model_id, int(payload.enabled), payload.priority, payload.data_classification, now_iso, payload.scene)
            )
            r_id = row[0]
        else:
            cursor.execute(
                """
                INSERT INTO ai_model_route (id, scene, model_id, fallback_model_id, enabled, priority, data_classification, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (r_id, payload.scene, payload.model_id, payload.fallback_model_id, int(payload.enabled), payload.priority, payload.data_classification, now_iso, now_iso)
            )
        conn.commit()

    return AIModelRouteResponse(
        id=r_id, scene=payload.scene, model_id=payload.model_id,
        fallback_model_id=payload.fallback_model_id, enabled=payload.enabled,
        priority=payload.priority, data_classification=payload.data_classification,
        created_at=now_iso, updated_at=now_iso
    )
