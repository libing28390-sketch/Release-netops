"""
FastAPI Router for AI Models & Model Scene Routes
"""

from __future__ import annotations

import uuid
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

router = APIRouter(prefix="/models", tags=["AI Models & Routes"])


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
                   created_at, updated_at
            FROM ai_model ORDER BY priority DESC, created_at DESC
            """
        )
        rows = cursor.fetchall()
        result = []
        for r in rows:
            result.append(
                AIModelResponse(
                    id=r[0], provider_id=r[1], name=r[2], model_code=r[3],
                    model_type=r[4], thinking_supported=bool(r[5]),
                    tool_call_supported=bool(r[6]), json_supported=bool(r[7]),
                    context_length=r[8], max_output_tokens=r[9],
                    default_temperature=r[10], default_max_tokens=r[11],
                    enabled=bool(r[12]), is_default=bool(r[13]), priority=r[14],
                    created_at=r[15], updated_at=r[16]
                )
            )
        return result


@router.post("", response_model=AIModelResponse, status_code=status.HTTP_201_CREATED)
def create_model(payload: AIModelCreate, user=Depends(require_ai_permission("ai.model.manage"))):
    """Create a new AI Model."""
    now_iso = datetime.now(timezone.utc).isoformat()
    m_id = f"model_{uuid.uuid4().hex[:12]}"
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        provider_row = cursor.execute(
            "SELECT provider_type FROM ai_provider WHERE id = ?",
            (payload.provider_id,),
        ).fetchone()
        if not provider_row or str(provider_row[0] or '').lower() != 'deepseek':
            raise HTTPException(status_code=400, detail='Only DeepSeek V1 providers may own AI models')
        if payload.is_default:
            cursor.execute("UPDATE ai_model SET is_default = 0")
            
        cursor.execute(
            """
            INSERT INTO ai_model (
                id, provider_id, name, model_code, model_type, thinking_supported,
                tool_call_supported, json_supported, context_length, max_output_tokens,
                default_temperature, default_max_tokens, enabled, is_default, priority,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                m_id, payload.provider_id, payload.name, payload.model_code, payload.model_type,
                int(payload.thinking_supported), int(payload.tool_call_supported),
                int(payload.json_supported), payload.context_length, payload.max_output_tokens,
                payload.default_temperature, payload.default_max_tokens, int(payload.enabled),
                int(payload.is_default), payload.priority, now_iso, now_iso
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


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(model_id: str, user=Depends(require_ai_permission("ai.model.manage"))):
    """Delete an AI Model."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ai_model WHERE id = ?", (model_id,))
        conn.commit()
    return None


# --- AI Scene Routes CRUD ---
@router.get("/routes", response_model=List[AIModelRouteResponse])
def list_routes(user=Depends(require_ai_permission("ai.view"))):
    """List all AI Scene Routes."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, scene, model_id, fallback_model_id, enabled, created_at, updated_at FROM ai_model_route")
        rows = cursor.fetchall()
        return [
            AIModelRouteResponse(
                id=r[0], scene=r[1], model_id=r[2], fallback_model_id=r[3],
                enabled=bool(r[4]), created_at=r[5], updated_at=r[6]
            ) for r in rows
        ]


@router.post("/routes", response_model=AIModelRouteResponse)
def upsert_route(payload: AIModelRouteCreate, user=Depends(require_ai_permission("ai.model.manage"))):
    """Upsert Scene Model Route."""
    now_iso = datetime.now(timezone.utc).isoformat()
    r_id = f"route_{uuid.uuid4().hex[:12]}"
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM ai_model_route WHERE scene = ?", (payload.scene,))
        row = cursor.fetchone()
        if row:
            cursor.execute(
                """
                UPDATE ai_model_route SET model_id = ?, fallback_model_id = ?, enabled = ?, updated_at = ?
                WHERE scene = ?
                """,
                (payload.model_id, payload.fallback_model_id, int(payload.enabled), now_iso, payload.scene)
            )
            r_id = row[0]
        else:
            cursor.execute(
                """
                INSERT INTO ai_model_route (id, scene, model_id, fallback_model_id, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (r_id, payload.scene, payload.model_id, payload.fallback_model_id, int(payload.enabled), now_iso, now_iso)
            )
        conn.commit()

    return AIModelRouteResponse(
        id=r_id, scene=payload.scene, model_id=payload.model_id,
        fallback_model_id=payload.fallback_model_id, enabled=payload.enabled,
        created_at=now_iso, updated_at=now_iso
    )
