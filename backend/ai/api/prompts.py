"""
FastAPI Router for Prompt Center & Prompt Version Management
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from database.core import get_db_connection
from ai.security.permissions import require_ai_permission
from ai.schemas.prompt import (
    AIPromptCreate,
    AIPromptResponse,
    AIPromptUpdate,
    AIPromptVersionResponse,
)

router = APIRouter(prefix="/prompts", tags=["AI Prompt Center"])


@router.get("", response_model=List[AIPromptResponse])
def list_prompts(user=Depends(require_ai_permission("ai.view"))):
    """List all Prompts."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, code, name, scene, vendor, platform, system_prompt, user_prompt_template,
                   output_schema, temperature, max_tokens, version, enabled, created_by, created_at, updated_at
            FROM ai_prompt ORDER BY created_at DESC
            """
        )
        rows = cursor.fetchall()
        return [
            AIPromptResponse(
                id=r[0], code=r[1], name=r[2], scene=r[3], vendor=r[4], platform=r[5],
                system_prompt=r[6], user_prompt_template=r[7], output_schema=r[8],
                temperature=r[9], max_tokens=r[10], version=r[11], enabled=bool(r[12]),
                created_by=r[13], created_at=r[14], updated_at=r[15]
            ) for r in rows
        ]


@router.post("", response_model=AIPromptResponse, status_code=status.HTTP_201_CREATED)
def create_prompt(payload: AIPromptCreate, user=Depends(require_ai_permission("ai.prompt.manage"))):
    """Create a new Prompt template and create initial version 1."""
    now_iso = datetime.now(timezone.utc).isoformat()
    p_id = f"prompt_{uuid.uuid4().hex[:12]}"
    username = user.get("username", "admin")
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM ai_prompt WHERE code = ?", (payload.code,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail=f"Prompt code '{payload.code}' already exists.")
            
        cursor.execute(
            """
            INSERT INTO ai_prompt (
                id, code, name, scene, vendor, platform, system_prompt, user_prompt_template,
                output_schema, temperature, max_tokens, version, enabled, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                p_id, payload.code, payload.name, payload.scene, payload.vendor, payload.platform,
                payload.system_prompt, payload.user_prompt_template, payload.output_schema,
                payload.temperature, payload.max_tokens, int(payload.enabled), username, now_iso, now_iso
            )
        )
        
        # Save version 1
        v_id = f"pv_{uuid.uuid4().hex[:12]}"
        cursor.execute(
            """
            INSERT INTO ai_prompt_version (
                id, prompt_id, version, system_prompt, user_prompt_template,
                output_schema, temperature, max_tokens, created_by, created_at
            ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                v_id, p_id, payload.system_prompt, payload.user_prompt_template,
                payload.output_schema, payload.temperature, payload.max_tokens, username, now_iso
            )
        )
        conn.commit()

    return AIPromptResponse(
        id=p_id, code=payload.code, name=payload.name, scene=payload.scene, vendor=payload.vendor,
        platform=payload.platform, system_prompt=payload.system_prompt,
        user_prompt_template=payload.user_prompt_template, output_schema=payload.output_schema,
        temperature=payload.temperature, max_tokens=payload.max_tokens, version=1,
        enabled=payload.enabled, created_by=username, created_at=now_iso, updated_at=now_iso
    )


@router.get("/{prompt_id}/versions", response_model=List[AIPromptVersionResponse])
def list_prompt_versions(prompt_id: str, user=Depends(require_ai_permission("ai.view"))):
    """List version history for a prompt."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, prompt_id, version, system_prompt, user_prompt_template, output_schema,
                   temperature, max_tokens, created_by, created_at
            FROM ai_prompt_version WHERE prompt_id = ? ORDER BY version DESC
            """,
            (prompt_id,)
        )
        rows = cursor.fetchall()
        return [
            AIPromptVersionResponse(
                id=r[0], prompt_id=r[1], version=r[2], system_prompt=r[3],
                user_prompt_template=r[4], output_schema=r[5], temperature=r[6],
                max_tokens=r[7], created_by=r[8], created_at=r[9]
            ) for r in rows
        ]
