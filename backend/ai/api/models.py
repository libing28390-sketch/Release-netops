"""
FastAPI Router for AI Models & Model Scene Routes
"""

from __future__ import annotations

import uuid
import json
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from database.core import get_db_connection
from ai.security.permissions import require_ai_permission
from ai.schemas.model import (
    AIModelCreate,
    AIModelResponse,
    AIModelRouteCreate,
    AIModelRouteResponse,
    AIModelUpdate,
)
from api.knowledge_v2_contracts import DefaultModelRequest, ModelAccessRequest
from ai.security.tokenization import opaque_user_id

router = APIRouter(prefix="/models", tags=["AI Models & Routes"])


def _model_from_row(r) -> AIModelResponse:
    return AIModelResponse(
        id=r[0], provider_id=r[1], name=r[2], model_code=r[3], model_type=r[4], thinking_supported=bool(r[5]),
        tool_call_supported=bool(r[6]), json_supported=bool(r[7]), context_length=r[8], max_output_tokens=r[9],
        default_temperature=r[10], default_max_tokens=r[11], enabled=bool(r[12]), is_default=bool(r[13]), priority=r[14],
        created_at=r[15], updated_at=r[16], stream_supported=bool(r[17] if len(r) > 17 and r[17] is not None else 1),
        display_name=(r[18] if len(r) > 18 else None), cost_input_per_1k=float(r[19] or 0) if len(r) > 19 else 0,
        cost_output_per_1k=float(r[20] or 0) if len(r) > 20 else 0,
        health_status=(r[21] if len(r) > 21 and r[21] else "unknown"),
        last_latency_ms=(int(r[22]) if len(r) > 22 and r[22] is not None else None),
        last_success_at=(r[23] if len(r) > 23 else None),
        last_error_code=(r[24] if len(r) > 24 else None),
    )


# --- AI Models CRUD ---
@router.get("", response_model=List[AIModelResponse])
def list_models(user=Depends(require_ai_permission("ai.view"))):
    """List all configured AI Models."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, provider_id, name, model_code, model_type, thinking_supported,
                   tool_call_supported, json_supported, context_length, max_output_tokens,
                   default_temperature, default_max_tokens, enabled, is_default, priority,
                   created_at, updated_at, stream_supported, display_name, cost_input_per_1k, cost_output_per_1k,
                   health_status, last_latency_ms, last_success_at, last_error_code
            FROM ai_model ORDER BY priority DESC, created_at DESC
            """
        )
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
        row = conn.execute("SELECT id, provider_id, name, model_code, model_type, thinking_supported, tool_call_supported, json_supported, context_length, max_output_tokens, default_temperature, default_max_tokens, enabled, is_default, priority, created_at, updated_at, stream_supported, display_name, cost_input_per_1k, cost_output_per_1k, health_status, last_latency_ms, last_success_at, last_error_code FROM ai_model WHERE id = ?", (model_id,)).fetchone()
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


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(model_id: str, user=Depends(require_ai_permission("ai.model.manage"))):
    """Delete an AI Model."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        refs = cursor.execute("SELECT COUNT(*) FROM ai_model_route WHERE model_id = ? OR fallback_model_id = ?", (model_id, model_id)).fetchone()[0]
        if refs:
            raise HTTPException(status_code=409, detail='Model is referenced by a scene route; update the route first')
        msg_refs = cursor.execute("SELECT COUNT(*) FROM ai_messages WHERE requested_model_id = ? OR actual_model_id = ?", (model_id, model_id)).fetchone()[0]
        if msg_refs:
            raise HTTPException(status_code=409, detail='Model has message provenance and cannot be deleted; disable it instead')
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
