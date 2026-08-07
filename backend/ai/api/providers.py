"""
FastAPI Router for AI Providers Management & Connection Testing
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from database.core import get_db_connection
from ai.security.crypto import encrypt_api_key, mask_api_key, decrypt_api_key
from ai.security.permissions import require_ai_permission
from ai.schemas.provider import (
    AIProviderCreate,
    AIProviderResponse,
    AIProviderTestResponse,
    AIProviderUpdate,
)
from ai.providers.deepseek import DeepSeekProvider
from ai.providers.openai_compatible import OpenAICompatibleProvider

router = APIRouter(prefix="/providers", tags=["AI Providers"])


@router.get("", response_model=List[AIProviderResponse])
def list_providers(user=Depends(require_ai_permission("ai.provider.manage"))):
    """List all AI Providers."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, name, provider_type, base_url, api_key_masked, timeout,
                   max_retries, proxy_url, enabled, created_by, created_at, updated_at
            FROM ai_provider ORDER BY created_at DESC
            """
        )
        rows = cursor.fetchall()
        result = []
        for r in rows:
            result.append(
                AIProviderResponse(
                    id=r[0], name=r[1], provider_type=r[2], base_url=r[3],
                    api_key_masked=r[4], timeout=r[5], max_retries=r[6],
                    proxy_url=r[7], enabled=bool(r[8]), created_by=r[9],
                    created_at=r[10], updated_at=r[11]
                )
            )
        return result


@router.post("", response_model=AIProviderResponse, status_code=status.HTTP_201_CREATED)
def create_provider(payload: AIProviderCreate, user=Depends(require_ai_permission("ai.provider.manage"))):
    """Create a new AI Provider with AES-256-GCM encrypted API key."""
    now_iso = datetime.now(timezone.utc).isoformat()
    p_id = f"prov_{uuid.uuid4().hex[:12]}"
    
    enc_key = encrypt_api_key(payload.api_key) if payload.api_key else None
    masked_key = mask_api_key(payload.api_key) if payload.api_key else None
    
    username = user.get("username", "admin")
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO ai_provider (
                id, name, provider_type, base_url, api_key_encrypted, api_key_masked,
                timeout, max_retries, proxy_url, enabled, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p_id, payload.name, payload.provider_type, payload.base_url, enc_key, masked_key,
                payload.timeout, payload.max_retries, payload.proxy_url, int(payload.enabled),
                username, now_iso, now_iso
            )
        )
        
        # Auto-provision initial models for this provider
        models_to_create = []
        p_type = payload.provider_type.lower()
        
        if payload.default_model_code:
            models_to_create.append({
                "code": payload.default_model_code,
                "name": f"{payload.name} ({payload.default_model_code})",
                "type": "chat"
            })
        elif p_type == "deepseek":
            models_to_create.extend([
                {"code": "deepseek-chat", "name": "DeepSeek Chat", "type": "chat"},
                {"code": "deepseek-reasoner", "name": "DeepSeek Reasoner (R1)", "type": "chat", "thinking": True}
            ])
        elif p_type in ("openai", "qwen"):
            default_code = "gpt-4o" if p_type == "openai" else "qwen-max"
            models_to_create.append({"code": default_code, "name": f"{payload.name} {default_code}", "type": "chat"})
        else:
            models_to_create.append({"code": "default-model", "name": f"{payload.name} Default Model", "type": "chat"})

        # Check if default model already exists in DB
        cursor.execute("SELECT COUNT(*) FROM ai_model WHERE is_default = 1 AND enabled = 1")
        has_default = (cursor.fetchone() or [0])[0] > 0
        
        first_model_id = None
        for idx, m in enumerate(models_to_create):
            m_id = f"model_{uuid.uuid4().hex[:12]}"
            if not first_model_id:
                first_model_id = m_id
            is_def_flag = 1 if (not has_default and idx == 0) else 0
            cursor.execute(
                """
                INSERT INTO ai_model (
                    id, provider_id, name, model_code, model_type, thinking_supported,
                    tool_call_supported, json_supported, context_length, max_output_tokens,
                    default_temperature, default_max_tokens, enabled, is_default, priority,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, 1, 128000, 4096, 0.7, 2048, 1, ?, 10, ?, ?)
                """,
                (
                    m_id, p_id, m["name"], m["code"], m["type"],
                    1 if m.get("thinking") else 0, is_def_flag, now_iso, now_iso
                )
            )

        # Seed scene routes if missing
        if first_model_id:
            scenes = ["chat", "agent", "config_diff", "alarm_analysis", "command_explain"]
            for s in scenes:
                cursor.execute("SELECT id FROM ai_model_route WHERE scene = ?", (s,))
                if not cursor.fetchone():
                    r_id = f"route_{uuid.uuid4().hex[:12]}"
                    cursor.execute(
                        "INSERT INTO ai_model_route (id, scene, model_id, enabled, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
                        (r_id, s, first_model_id, now_iso, now_iso)
                    )

        conn.commit()

    return AIProviderResponse(
        id=p_id, name=payload.name, provider_type=payload.provider_type, base_url=payload.base_url,
        api_key_masked=masked_key, timeout=payload.timeout, max_retries=payload.max_retries,
        proxy_url=payload.proxy_url, enabled=payload.enabled, created_by=username,
        created_at=now_iso, updated_at=now_iso
    )


@router.put("/{provider_id}", response_model=AIProviderResponse)
def update_provider(provider_id: str, payload: AIProviderUpdate, user=Depends(require_ai_permission("ai.provider.manage"))):
    """Update an existing AI Provider."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, api_key_encrypted, api_key_masked FROM ai_provider WHERE id = ?", (provider_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found.")
        
        enc_key = row[1]
        masked_key = row[2]
        if payload.api_key is not None:
            enc_key = encrypt_api_key(payload.api_key) if payload.api_key else None
            masked_key = mask_api_key(payload.api_key) if payload.api_key else None

        fields = []
        params = []
        if payload.name is not None: fields.append("name = ?"); params.append(payload.name)
        if payload.provider_type is not None: fields.append("provider_type = ?"); params.append(payload.provider_type)
        if payload.base_url is not None: fields.append("base_url = ?"); params.append(payload.base_url)
        if payload.api_key is not None: fields.extend(["api_key_encrypted = ?", "api_key_masked = ?"]); params.extend([enc_key, masked_key])
        if payload.timeout is not None: fields.append("timeout = ?"); params.append(payload.timeout)
        if payload.max_retries is not None: fields.append("max_retries = ?"); params.append(payload.max_retries)
        if payload.proxy_url is not None: fields.append("proxy_url = ?"); params.append(payload.proxy_url)
        if payload.enabled is not None: fields.append("enabled = ?"); params.append(int(payload.enabled))

        fields.append("updated_at = ?")
        params.append(now_iso)
        params.append(provider_id)

        query = f"UPDATE ai_provider SET {', '.join(fields)} WHERE id = ?"
        cursor.execute(query, tuple(params))
        conn.commit()

        cursor.execute(
            "SELECT id, name, provider_type, base_url, api_key_masked, timeout, max_retries, proxy_url, enabled, created_by, created_at, updated_at FROM ai_provider WHERE id = ?",
            (provider_id,)
        )
        r = cursor.fetchone()
        return AIProviderResponse(
            id=r[0], name=r[1], provider_type=r[2], base_url=r[3],
            api_key_masked=r[4], timeout=r[5], max_retries=r[6],
            proxy_url=r[7], enabled=bool(r[8]), created_by=r[9],
            created_at=r[10], updated_at=r[11]
        )


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(provider_id: str, user=Depends(require_ai_permission("ai.provider.manage"))):
    """Delete an AI Provider."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ai_provider WHERE id = ?", (provider_id,))
        conn.commit()
    return None


@router.post("/{provider_id}/test", response_model=AIProviderTestResponse)
async def test_provider_connection(provider_id: str, user=Depends(require_ai_permission("ai.provider.manage"))):
    """Test API connection to an AI Provider."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, provider_type, base_url, api_key_encrypted, timeout, max_retries, proxy_url FROM ai_provider WHERE id = ?",
            (provider_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found.")
        
        p_data = {
            "id": row[0],
            "name": row[1],
            "provider_type": row[2],
            "base_url": row[3],
            "timeout": row[5],
            "max_retries": row[6],
            "proxy_url": row[7],
        }
        plain_key = decrypt_api_key(row[4])
        
        p_type = p_data["provider_type"].lower()
        if p_type == "deepseek":
            provider_inst = DeepSeekProvider(p_data, api_key=plain_key)
        else:
            provider_inst = OpenAICompatibleProvider(p_data, api_key=plain_key)
        
        res = await provider_inst.test_connection()
        return AIProviderTestResponse(
            success=res["success"],
            latency_ms=res["latency_ms"],
            message=res["message"],
            model_tested=res.get("model_tested"),
            sample_response=res.get("sample_response"),
            error_code=res.get("error_code")
        )
