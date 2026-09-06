"""
FastAPI Router for AI Providers Management & Connection Testing
"""

from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fnmatch import fnmatchcase
from urllib.parse import urlparse
from database.core import get_db_connection
from ai.security.crypto import encrypt_api_key, mask_api_key, require_configured_master_key
from ai.security.permissions import require_ai_permission
from ai.schemas.provider import (
    AIProviderCreate,
    AIProviderPageResponse,
    AIProviderResponse,
    AIProviderTestResponse,
    AIProviderUpdate,
    SUPPORTED_PROVIDER_TYPES,
)
from api.knowledge_contracts import ProviderKeyInvalidationRequest, ProviderKeyRotationRequest
from ai.gateway.exceptions import AIException
from ai.gateway.llm_gateway import llm_gateway
from ai.gateway.limits import ai_limits
from core.config import settings

router = APIRouter(prefix="/providers", tags=["AI Providers"])


def _validate_provider_endpoint(provider_type: str, base_url: str | None) -> None:
    if not base_url:
        if provider_type not in {"ollama", "local"}:
            raise HTTPException(status_code=400, detail="base_url is required for this provider type")
        return
    parsed = urlparse(base_url.rstrip("/"))
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and provider_type in {"ollama", "local"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return
    raise HTTPException(status_code=400, detail="Provider base_url must use HTTPS; HTTP is allowed only for local Ollama endpoints")


def _validate_endpoint_allowlist(
    provider_type: str,
    base_url: str | None,
    patterns: list[str] | None,
) -> list[str]:
    """Validate and normalize the application-level egress endpoint allowlist."""

    normalized = [str(item).strip().rstrip("/") for item in (patterns or []) if str(item).strip()]
    if not base_url or str(provider_type).lower() in {"local", "ollama"}:
        return normalized
    if not normalized:
        # Existing deployments are backfilled by m0166; a new provider with a
        # configured HTTPS endpoint gets that exact endpoint as its initial
        # approved destination instead of an implicit wildcard.
        normalized = [str(base_url).rstrip("/")]
    parsed_base = urlparse(str(base_url).rstrip("/"))
    if parsed_base.scheme != "https" or not parsed_base.hostname:
        raise HTTPException(status_code=400, detail="Cloud provider endpoint allowlist requires an HTTPS URL")
    for pattern in normalized:
        parsed_pattern = urlparse(pattern.replace("*", "allowlist-wildcard"))
        if parsed_pattern.scheme != "https" or not parsed_pattern.hostname:
            raise HTTPException(status_code=400, detail="approved_endpoint_patterns must contain HTTPS URL patterns")
    if not any(fnmatchcase(str(base_url).rstrip("/"), pattern) for pattern in normalized):
        raise HTTPException(status_code=400, detail="base_url is not covered by approved_endpoint_patterns")
    return normalized


def _row_to_provider(row) -> AIProviderResponse:
    # PostgreSQL TEXT/JSON adapters can return a JSON string, a decoded list,
    # or legacy `{}` from m0139's original default.  The public contract is
    # always list[str]; malformed/object values fail closed to an empty list so
    # one legacy row cannot take down the whole Provider page.
    raw_tags = row[12] if len(row) > 12 else None
    if isinstance(raw_tags, list):
        decoded_tags = raw_tags
    elif isinstance(raw_tags, tuple):
        decoded_tags = list(raw_tags)
    elif raw_tags:
        try:
            parsed_tags = json.loads(str(raw_tags))
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed_tags = []
        decoded_tags = parsed_tags if isinstance(parsed_tags, list) else []
    else:
        decoded_tags = []
    tags = [tag.strip() for tag in decoded_tags if isinstance(tag, str) and tag.strip()]
    raw_patterns = row[23] if len(row) > 23 else None
    if isinstance(raw_patterns, (list, tuple)):
        decoded_patterns = list(raw_patterns)
    else:
        try:
            parsed_patterns = json.loads(str(raw_patterns or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed_patterns = []
        decoded_patterns = parsed_patterns if isinstance(parsed_patterns, list) else []
    return AIProviderResponse(
        id=row[0], name=row[1], provider_type=row[2], base_url=row[3], api_key_masked=row[4],
        timeout=row[5], max_retries=row[6], proxy_url=row[7], enabled=bool(row[8]), created_by=row[9],
        created_at=row[10], updated_at=row[11], health_status=row[13] or "unknown", last_health_check_at=row[14],
        last_success_at=row[15], last_error_code=row[16], tags=tags, data_region=row[17] or "unknown",
        allowed_data_classification=row[18] or "PUBLIC",
        no_training_confirmed=bool(row[19]) if len(row) > 19 else False,
        retention_days=(int(row[20]) if len(row) > 20 and row[20] is not None else None),
        data_processing_agreement_ref=(row[21] if len(row) > 21 else None),
        agreement_reviewed_at=(row[22] if len(row) > 22 else None),
        approved_endpoint_patterns=[item for item in decoded_patterns if isinstance(item, str) and item.strip()],
    )


_PROVIDER_SELECT = """SELECT id, name, provider_type, base_url, api_key_masked, timeout,
       max_retries, proxy_url, enabled, created_by, created_at, updated_at,
       tags_json, health_status, last_health_check_at, last_success_at,
       last_error_code, data_region, allowed_data_classification,
       no_training_confirmed, retention_days, data_processing_agreement_ref,
       agreement_reviewed_at, approved_endpoint_patterns_json
       FROM ai_provider"""


def _provider_filter_sql(
    search: str,
    data_region: str,
    health_status: str,
    enabled: bool | None,
    provider_type: str,
    tag: str,
) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if search.strip():
        needle = f"%{search.strip().lower()}%"
        clauses.append(
            "(LOWER(name) LIKE ? OR LOWER(provider_type) LIKE ? OR LOWER(COALESCE(base_url, '')) LIKE ? "
            "OR LOWER(COALESCE(data_region, '')) LIKE ? OR LOWER(COALESCE(health_status, '')) LIKE ? "
            "OR LOWER(COALESCE(tags_json, '')) LIKE ?)"
        )
        params.extend([needle] * 6)
    if data_region.strip():
        clauses.append("LOWER(COALESCE(data_region, 'unknown')) = ?")
        params.append(data_region.strip().lower())
    if health_status.strip():
        clauses.append("LOWER(COALESCE(health_status, 'unknown')) = ?")
        params.append(health_status.strip().lower())
    if enabled is not None:
        clauses.append("enabled = ?")
        params.append(int(enabled))
    if provider_type.strip():
        clauses.append("LOWER(provider_type) = ?")
        params.append(provider_type.strip().lower())
    if tag.strip():
        clauses.append("LOWER(COALESCE(tags_json, '')) LIKE ?")
        # tags_json is a bounded JSON string column for legacy compatibility.
        # Match a quoted JSON token so a filter for `prod` cannot accidentally
        # return a provider tagged `production`.
        params.append(f"%{json.dumps(tag.strip().lower())}%")
    return (f"WHERE {' AND '.join(clauses)}" if clauses else ""), params


def _provider_page_facets(cursor) -> dict[str, list[str]]:
    facets: dict[str, list[str]] = {}
    for key, expression in (
        ("data_regions", "COALESCE(data_region, 'unknown')"),
        ("health_statuses", "COALESCE(health_status, 'unknown')"),
        ("provider_types", "provider_type"),
    ):
        rows = cursor.execute(
            f"SELECT DISTINCT {expression} FROM ai_provider WHERE {expression} IS NOT NULL ORDER BY 1"
        ).fetchall()
        facets[key] = [str(row[0]) for row in rows if row[0] is not None]
    tags: set[str] = set()
    for row in cursor.execute("SELECT tags_json FROM ai_provider WHERE tags_json IS NOT NULL").fetchall():
        raw = row[0]
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = []
        if isinstance(parsed, list):
            tags.update(str(item).strip() for item in parsed if str(item).strip())
    facets["tags"] = sorted(tags, key=str.casefold)
    return facets


@router.get("")
def list_providers(
    search: str = Query(default="", max_length=256),
    data_region: str = Query(default="", max_length=64),
    health_status: str = Query(default="", max_length=32),
    enabled: bool | None = Query(default=None),
    provider_type: str = Query(default="", max_length=64),
    tag: str = Query(default="", max_length=64),
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user=Depends(require_ai_permission("ai.provider.manage")),
):
    """List providers with a paged/filterable contract for the registry UI.

    Calls without query parameters retain the legacy array response consumed
    by Model Management and Copilot's provider picker.
    """
    del user
    with get_db_connection() as conn:
        cursor = conn.cursor()
        where_sql, params = _provider_filter_sql(search, data_region, health_status, enabled, provider_type, tag)
        is_paged = page is not None or bool(search.strip() or data_region.strip() or health_status.strip() or provider_type.strip() or tag.strip() or enabled is not None)
        if not is_paged:
            try:
                rows = cursor.execute(_PROVIDER_SELECT + " ORDER BY created_at DESC, id DESC").fetchall()
            except Exception:
                rows = cursor.execute("SELECT id, name, provider_type, base_url, api_key_masked, timeout, max_retries, proxy_url, enabled, created_by, created_at, updated_at, NULL, 'unknown', NULL, NULL, NULL, 'unknown', 'PUBLIC', 0, NULL, NULL, NULL, '[]' FROM ai_provider ORDER BY created_at DESC, id DESC").fetchall()
            return [_row_to_provider(row) for row in rows]

        total_row = cursor.execute(f"SELECT COUNT(*) FROM ai_provider {where_sql}", tuple(params)).fetchone()
        total = int(total_row[0] if total_row else 0)
        total_pages = max(1, math.ceil(total / page_size))
        effective_page = min(page or 1, total_pages)
        rows = cursor.execute(
            _PROVIDER_SELECT + f" {where_sql} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            tuple([*params, page_size, (effective_page - 1) * page_size]),
        ).fetchall()
        return AIProviderPageResponse(
            items=[_row_to_provider(row) for row in rows],
            total=total,
            page=effective_page,
            page_size=page_size,
            total_pages=total_pages,
            facets=_provider_page_facets(cursor),
        )


@router.post("", response_model=AIProviderResponse, status_code=status.HTTP_201_CREATED)
def create_provider(payload: AIProviderCreate, user=Depends(require_ai_permission("ai.provider.manage"))):
    """Create a new AI Provider with AES-256-GCM encrypted API key."""
    _validate_provider_endpoint(payload.provider_type, payload.base_url)
    if payload.provider_type == "deepseek" and payload.base_url and payload.base_url.rstrip('/') not in {
        'https://api.deepseek.com', 'https://api.deepseek.com/v1',
    }:
        raise HTTPException(status_code=400, detail='DeepSeek provider must use the official HTTPS endpoint')
    approved_endpoint_patterns = _validate_endpoint_allowlist(
        payload.provider_type,
        payload.base_url,
        payload.approved_endpoint_patterns,
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    p_id = f"prov_{uuid.uuid4().hex[:12]}"
    
    if payload.api_key:
        try:
            require_configured_master_key()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Provider key storage is unavailable until the master key is configured") from exc
    enc_key = encrypt_api_key(payload.api_key) if payload.api_key else None
    masked_key = mask_api_key(payload.api_key) if payload.api_key else None
    
    username = user.get("username", "admin")
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if cursor.execute("SELECT id FROM ai_provider WHERE name = ?", (payload.name,)).fetchone():
            raise HTTPException(status_code=409, detail="Provider name already exists")
        cursor.execute(
            """
            INSERT INTO ai_provider (
                id, name, provider_type, base_url, api_key_encrypted, api_key_masked,
                timeout, max_retries, proxy_url, enabled, created_by, created_at, updated_at,
                tags_json, health_status, data_region, allowed_data_classification,
                no_training_confirmed, retention_days, data_processing_agreement_ref,
                agreement_reviewed_at, approved_endpoint_patterns_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unknown', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                p_id, payload.name, payload.provider_type, payload.base_url, enc_key, masked_key,
                payload.timeout, payload.max_retries, payload.proxy_url, int(payload.enabled),
                username, now_iso, now_iso, json.dumps(payload.tags, ensure_ascii=False), payload.data_region,
                payload.allowed_data_classification, int(payload.no_training_confirmed), payload.retention_days,
                payload.data_processing_agreement_ref, payload.agreement_reviewed_at,
                json.dumps(approved_endpoint_patterns, ensure_ascii=False)
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
                {"code": "deepseek-v4-flash", "name": "DeepSeek V4 Flash", "type": "chat"},
                {"code": "deepseek-v4-pro", "name": "DeepSeek V4 Pro", "type": "chat", "thinking": True}
            ])
        elif p_type in ("openai", "qwen", "azure_openai"):
            default_code = "gpt-4o" if p_type in {"openai", "azure_openai"} else "qwen-max"
            models_to_create.append({"code": default_code, "name": f"{payload.name} {default_code}", "type": "chat"})
        elif p_type in ("ollama", "local"):
            models_to_create.append({"code": "llama3.1", "name": f"{payload.name} llama3.1", "type": "chat"})
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
                    created_at, updated_at, stream_supported, display_name
                ) VALUES (?, ?, ?, ?, ?, ?, 1, 1, 128000, 4096, 0.7, 2048, 1, ?, 10, ?, ?, 1, ?)
                """,
                (
                    m_id, p_id, m["name"], m["code"], m["type"],
                    1 if m.get("thinking") else 0, is_def_flag, now_iso, now_iso, m["name"]
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
        created_at=now_iso, updated_at=now_iso, tags=payload.tags, data_region=payload.data_region,
        allowed_data_classification=payload.allowed_data_classification,
        no_training_confirmed=payload.no_training_confirmed,
        retention_days=payload.retention_days,
        data_processing_agreement_ref=payload.data_processing_agreement_ref,
        agreement_reviewed_at=payload.agreement_reviewed_at,
        approved_endpoint_patterns=approved_endpoint_patterns,
    )


@router.put("/{provider_id}", response_model=AIProviderResponse)
def update_provider(provider_id: str, payload: AIProviderUpdate, user=Depends(require_ai_permission("ai.provider.manage"))):
    """Update an existing AI Provider."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, api_key_encrypted, api_key_masked, provider_type, base_url FROM ai_provider WHERE id = ?", (provider_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found.")
        
        next_type = payload.provider_type or row[3]
        next_url = payload.base_url if payload.base_url is not None else row[4]
        _validate_provider_endpoint(next_type, next_url)
        if next_type == "deepseek" and next_url and next_url.rstrip('/') not in {'https://api.deepseek.com', 'https://api.deepseek.com/v1'}:
            raise HTTPException(status_code=400, detail='DeepSeek provider must use the official HTTPS endpoint')
        approved_endpoint_patterns = None
        if payload.approved_endpoint_patterns is not None:
            approved_endpoint_patterns = _validate_endpoint_allowlist(
                next_type,
                next_url,
                payload.approved_endpoint_patterns,
            )
        if payload.name is not None and cursor.execute("SELECT id FROM ai_provider WHERE name = ? AND id <> ?", (payload.name, provider_id)).fetchone():
            raise HTTPException(status_code=409, detail="Provider name already exists")
        enc_key = row[1]
        masked_key = row[2]
        if payload.api_key is not None:
            if payload.api_key:
                try:
                    require_configured_master_key()
                except RuntimeError as exc:
                    raise HTTPException(status_code=503, detail="Provider key storage is unavailable until the master key is configured") from exc
            enc_key = encrypt_api_key(payload.api_key) if payload.api_key else None
            masked_key = mask_api_key(payload.api_key) if payload.api_key else None

        fields = []
        params = []
        if payload.name is not None: fields.append("name = ?"); params.append(payload.name)
        if payload.provider_type is not None: fields.append("provider_type = ?"); params.append(payload.provider_type)
        if payload.base_url is not None: fields.append("base_url = ?"); params.append(payload.base_url)
        if payload.api_key is not None: fields.extend(["api_key_encrypted = ?", "api_key_masked = ?"]); params.extend([enc_key, masked_key])
        if payload.api_key is not None:
            fields.extend(["health_status = 'unknown'", "last_health_check_at = NULL", "last_success_at = NULL", "last_error_code = NULL", "last_error_at = NULL"])
        if payload.timeout is not None: fields.append("timeout = ?"); params.append(payload.timeout)
        if payload.max_retries is not None: fields.append("max_retries = ?"); params.append(payload.max_retries)
        if payload.proxy_url is not None: fields.append("proxy_url = ?"); params.append(payload.proxy_url)
        if payload.enabled is not None: fields.append("enabled = ?"); params.append(int(payload.enabled))
        if payload.tags is not None: fields.append("tags_json = ?"); params.append(json.dumps(payload.tags, ensure_ascii=False))
        if payload.data_region is not None: fields.append("data_region = ?"); params.append(payload.data_region)
        if payload.allowed_data_classification is not None: fields.append("allowed_data_classification = ?"); params.append(payload.allowed_data_classification)
        if payload.no_training_confirmed is not None: fields.append("no_training_confirmed = ?"); params.append(int(payload.no_training_confirmed))
        if payload.retention_days is not None: fields.append("retention_days = ?"); params.append(payload.retention_days)
        if payload.data_processing_agreement_ref is not None: fields.append("data_processing_agreement_ref = ?"); params.append(payload.data_processing_agreement_ref)
        if payload.agreement_reviewed_at is not None: fields.append("agreement_reviewed_at = ?"); params.append(payload.agreement_reviewed_at)
        if payload.approved_endpoint_patterns is not None:
            fields.append("approved_endpoint_patterns_json = ?")
            params.append(json.dumps(approved_endpoint_patterns or [], ensure_ascii=False))

        fields.append("updated_at = ?")
        params.append(now_iso)
        params.append(provider_id)

        query = f"UPDATE ai_provider SET {', '.join(fields)} WHERE id = ?"
        cursor.execute(query, tuple(params))
        conn.commit()
        if payload.api_key is not None:
            ai_limits.reset_provider(provider_id)

        cursor.execute(_PROVIDER_SELECT + " WHERE id = ?", (provider_id,))
        r = cursor.fetchone()
        return _row_to_provider(r)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(provider_id: str, user=Depends(require_ai_permission("ai.provider.manage"))):
    """Delete an AI Provider."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        refs = cursor.execute("SELECT COUNT(*) FROM ai_model WHERE provider_id = ?", (provider_id,)).fetchone()[0]
        if refs:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "AI_PROVIDER_HAS_MODELS",
                    "message": "该 Provider 仍关联模型，暂时不能删除。请先处理关联模型；如果只是暂时不用，可以直接停用 Provider。",
                    "details": {
                        "model_count": int(refs),
                        "next_action": "disable_provider_or_remove_models",
                    },
                },
            )
        cursor.execute("DELETE FROM ai_provider WHERE id = ?", (provider_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Provider not found")
        conn.commit()
    return None


@router.get("/{provider_id}/delete-preview")
def provider_delete_preview(provider_id: str, user=Depends(require_ai_permission("ai.provider.manage"))):
    with get_db_connection() as conn:
        provider = conn.execute("SELECT id, name, enabled FROM ai_provider WHERE id = ?", (provider_id,)).fetchone()
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        models = conn.execute("SELECT id, name, enabled FROM ai_model WHERE provider_id = ? ORDER BY priority DESC", (provider_id,)).fetchall()
        routes = conn.execute("SELECT scene, model_id, fallback_model_id FROM ai_model_route WHERE model_id IN (SELECT id FROM ai_model WHERE provider_id = ?) OR fallback_model_id IN (SELECT id FROM ai_model WHERE provider_id = ?)", (provider_id, provider_id)).fetchall()
    return {
        "provider_id": provider[0], "provider_name": provider[1], "enabled": bool(provider[2]),
        "model_count": len(models), "models": [{"id": row[0], "name": row[1], "enabled": bool(row[2])} for row in models],
        "route_count": len(routes), "routes": [{"scene": row[0], "model_id": row[1], "fallback_model_id": row[2]} for row in routes],
        "can_delete": not models and not routes,
    }


@router.post("/{provider_id}/rotate-key", response_model=AIProviderResponse)
def rotate_provider_key(provider_id: str, payload: ProviderKeyRotationRequest, user=Depends(require_ai_permission("ai.provider.manage"))):
    """Rotate a provider key without returning plaintext or retiring history."""
    api_key = payload.api_key
    if not api_key or len(api_key) > 4096 or re.search(r"[\r\n]", api_key):
        raise HTTPException(status_code=400, detail="A valid API key is required")
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        require_configured_master_key()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Provider key storage is unavailable until the master key is configured") from exc
    encrypted = encrypt_api_key(api_key)
    with get_db_connection() as conn:
        row = conn.execute("SELECT id FROM ai_provider WHERE id = ?", (provider_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Provider not found")
        version = int((conn.execute("SELECT COALESCE(MAX(key_version), 0) FROM ai_provider_key_rotation WHERE provider_id = ?", (provider_id,)).fetchone() or [0])[0]) + 1
        masked = mask_api_key(api_key)
        conn.execute("UPDATE ai_provider SET api_key_encrypted = ?, api_key_masked = ?, adapter_key_version = ?, health_status = 'unknown', disabled_reason = NULL, updated_at = ? WHERE id = ?", (encrypted, masked, version, now_iso, provider_id))
        conn.execute("UPDATE ai_provider_key_rotation SET status = 'retired', retired_at = ? WHERE provider_id = ? AND status = 'active'", (now_iso, provider_id))
        conn.execute("INSERT INTO ai_provider_key_rotation (id, provider_id, key_version, status, api_key_encrypted, api_key_masked, created_by, created_at) VALUES (?, ?, ?, 'active', ?, ?, ?, ?)", (f"key_{uuid.uuid4().hex[:12]}", provider_id, version, encrypted, masked, user.get("username", "admin"), now_iso))
        conn.execute("INSERT INTO ai_provider_key_audit (id, provider_id, key_version, action, actor_id, reason_code, created_at) VALUES (?, ?, ?, 'rotate', ?, ?, ?)", (f"keyaudit_{uuid.uuid4().hex[:12]}", provider_id, version, user.get("username", "admin"), "manual_rotation", now_iso))
        conn.commit()
        ai_limits.reset_provider(provider_id)
        return _row_to_provider(conn.execute(_PROVIDER_SELECT + " WHERE id = ?", (provider_id,)).fetchone())


@router.post("/{provider_id}/invalidate-key", response_model=AIProviderResponse)
def invalidate_provider_key(provider_id: str, payload: ProviderKeyInvalidationRequest | None = None, user=Depends(require_ai_permission("ai.provider.manage"))):
    """Immediately revoke the active provider key and retain an audit row."""
    now_iso = datetime.now(timezone.utc).isoformat()
    reason = (payload.reason if payload else "manual_invalidation")[:80]
    with get_db_connection() as conn:
        row = conn.execute("SELECT id FROM ai_provider WHERE id = ?", (provider_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Provider not found")
        active = conn.execute("SELECT key_version FROM ai_provider_key_rotation WHERE provider_id = ? AND status = 'active' ORDER BY key_version DESC LIMIT 1", (provider_id,)).fetchone()
        version = int(active[0]) if active else None
        conn.execute("UPDATE ai_provider_key_rotation SET status = 'invalidated', invalidated_at = ? WHERE provider_id = ? AND status = 'active'", (now_iso, provider_id))
        conn.execute("UPDATE ai_provider SET api_key_encrypted = NULL, api_key_masked = NULL, health_status = 'disabled', disabled_reason = ?, last_error_code = 'AI_KEY_INVALIDATED', updated_at = ? WHERE id = ?", (reason, now_iso, provider_id))
        conn.execute("INSERT INTO ai_provider_key_audit (id, provider_id, key_version, action, actor_id, reason_code, created_at) VALUES (?, ?, ?, 'invalidate', ?, ?, ?)", (f"keyaudit_{uuid.uuid4().hex[:12]}", provider_id, version, user.get("username", "admin"), reason, now_iso))
        conn.commit()
        return _row_to_provider(conn.execute(_PROVIDER_SELECT + " WHERE id = ?", (provider_id,)).fetchone())


@router.get("/{provider_id}/health")
def provider_health(provider_id: str, user=Depends(require_ai_permission("ai.view"))):
    with get_db_connection() as conn:
        row = conn.execute("SELECT id, name, health_status, last_health_check_at, last_success_at, last_error_code, last_error_at FROM ai_provider WHERE id = ?", (provider_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")
    return {"provider_id": row[0], "provider_name": row[1], "health_status": row[2] or "unknown", "last_health_check_at": row[3], "last_success_at": row[4], "last_error_code": row[5], "last_error_at": row[6]}


@router.post("/{provider_id}/test", response_model=AIProviderTestResponse)
async def test_provider_connection(provider_id: str, user=Depends(require_ai_permission("ai.provider.manage"))):
    """Test through the same security gateway as production traffic.

    A Provider object must never expose a direct test path that can bypass the
    egress policy. The probe contains only a public, non-enterprise prompt.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, provider_type, enabled, last_health_check_at, health_status FROM ai_provider WHERE id = ?",
            (provider_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found.")
        if not row[3]:
            return AIProviderTestResponse(success=False, latency_ms=0, message="provider is disabled", error_code="AI_PROVIDER_DISABLED", provider_id=provider_id, route_reason="explicit_provider_health_probe")
        last_check = row[4]
        if last_check:
            try:
                elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(str(last_check).replace("Z", "+00:00"))).total_seconds()
                backoff = max(0, int(getattr(settings, "AI_HEALTH_BACKOFF_SECONDS", 30)))
                if elapsed < backoff:
                    return AIProviderTestResponse(success=False, latency_ms=0, message="health probe backoff is active", model_tested=None, error_code="AI_HEALTH_BACKOFF", provider_id=provider_id, route_reason="explicit_provider_health_probe")
            except (TypeError, ValueError):
                pass
        
        model_row = cursor.execute(
            "SELECT id, model_code FROM ai_model WHERE provider_id = ? AND enabled = 1 ORDER BY is_default DESC, priority DESC LIMIT 1",
            (provider_id,),
        ).fetchone()
    if not model_row:
        raise HTTPException(status_code=400, detail="Provider has no enabled V4 model")
    started = datetime.now(timezone.utc)
    try:
        result = await llm_gateway.chat(
            scene="provider_test",
            model_id=model_row[0],
            messages=[{"role": "user", "content": "Reply with one short word: ok"}],
            user_id=str(user.get("username") or "provider-test"),
            tenant_id=str(user.get("tenant_id") or "tenant-default"),
            # A short probe still needs enough output budget for providers
            # that spend tokens on structured/reasoning metadata.  A budget
            # of 16 can produce HTTP 200 + finish_reason=length, which is a
            # valid transport response but not a successful health probe.
            max_tokens=64,
            # The probe is a fixed, business-data-free public message.  Mark
            # it explicitly so a Provider limited to PUBLIC does not get
            # rejected merely because the generic classifier maps text with
            # no findings to L1_GENERAL/INTERNAL.
            data_classification="PUBLIC",
        )
        with get_db_connection() as conn:
            now_success = datetime.now(timezone.utc).isoformat()
            conn.execute("UPDATE ai_provider SET health_status = 'healthy', last_health_check_at = ?, last_success_at = ?, last_error_code = NULL, updated_at = ? WHERE id = ?", (now_success, now_success, now_success, provider_id))
            conn.commit()
        return AIProviderTestResponse(
            success=True,
            latency_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
            message="provider connection succeeded through security gateway",
            model_tested=model_row[1],
            sample_response=str(result.get("content") or "")[:150],
            provider_id=provider_id,
            route_reason="explicit_provider_health_probe",
        )
    except AIException as exc:
        with get_db_connection() as conn:
            conn.execute("UPDATE ai_provider SET health_status = 'unhealthy', last_health_check_at = ?, last_error_code = ?, last_error_at = ?, updated_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), exc.code, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), provider_id))
            conn.commit()
        return AIProviderTestResponse(
            success=False,
            latency_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
            message="provider connection test blocked or failed",
            model_tested=model_row[1],
            error_code=exc.code,
            provider_id=provider_id,
            route_reason="explicit_provider_health_probe",
        )
