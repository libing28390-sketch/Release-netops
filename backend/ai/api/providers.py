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
from ai.security.gateway import deployment_endpoint_allowed, endpoint_host
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
from services.audit_service import log_audit_event

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/providers", tags=["AI Providers"])


# ── audit and key storage helpers (review item M16 / M14) ────────────────

_AUDITED_FIELDS = (
    "name", "provider_type", "base_url", "timeout", "max_retries", "enabled",
    "data_region", "allowed_data_classification", "no_training_confirmed",
    "retention_days", "data_processing_agreement_ref", "agreement_reviewed_at",
)


def _proxy_summary(proxy_url: str | None) -> str | None:
    """Proxy URLs can carry credentials (user:pass@host); keep scheme://host:port."""
    if not proxy_url:
        return None
    parsed = urlparse(str(proxy_url))
    host = parsed.hostname or ""
    return f"{parsed.scheme}://{host}{':' + str(parsed.port) if parsed.port else ''}" if host else "(set)"


def _provider_snapshot(conn, provider_id: str) -> dict | None:
    row = conn.execute(
        "SELECT name, provider_type, base_url, timeout, max_retries, enabled, data_region, "
        "allowed_data_classification, no_training_confirmed, retention_days, data_processing_agreement_ref, "
        "agreement_reviewed_at, proxy_url, api_key_masked, approved_endpoint_patterns_json, tags_json "
        "FROM ai_provider WHERE id = ?",
        (provider_id,),
    ).fetchone()
    if not row:
        return None
    snapshot = {field: row[index] for index, field in enumerate(_AUDITED_FIELDS)}
    snapshot["enabled"] = bool(snapshot["enabled"])
    snapshot["no_training_confirmed"] = bool(snapshot["no_training_confirmed"])
    snapshot["proxy"] = _proxy_summary(row[12])
    # Whether a key is stored, never the key or its mask.
    snapshot["key_configured"] = bool(row[13])
    snapshot["approved_endpoint_patterns"] = row[14] if isinstance(row[14], list) else str(row[14] or "[]")[:1000]
    snapshot["tags"] = row[15] if isinstance(row[15], (list, dict)) else str(row[15] or "[]")[:500]
    return snapshot


def _audit_provider(user, *, event_type: str, provider_id: str, summary: str, severity: str = "medium",
                    before: dict | None = None, after: dict | None = None, details: dict | None = None, conn=None) -> None:
    # The audit row shares the caller's transaction.  On PostgreSQL a failed
    # statement aborts the whole transaction, so isolate it in a savepoint:
    # a failed audit write must not roll back the provider change itself.
    savepoint = f"ai_provider_audit_{uuid.uuid4().hex[:8]}"
    if conn is not None:
        conn.execute(f"SAVEPOINT {savepoint}")
    try:
        log_audit_event(
            event_type=event_type,
            category="ai_provider",
            severity=severity,
            status="success",
            summary=summary,
            actor_id=str(user.get("user_id") or user.get("id") or "") or None,
            actor_username=str(user.get("username") or "") or None,
            actor_role=str(user.get("role") or "") or None,
            target_type="ai_provider",
            target_id=provider_id,
            target_name=str((after or before or {}).get("name") or "") or None,
            before=before,
            after=after,
            details=details,
            conn=conn,
        )
    except Exception:
        # The change is persisted by the caller; audit I/O must not undo it.
        if conn is not None:
            try:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            except Exception:  # connection itself is gone; the caller's commit reports it
                logger.debug("AI provider audit savepoint rollback failed code=AI_AUDIT_SAVEPOINT_FAILED")
        logger.warning("AI provider audit write failed event=%s code=AI_AUDIT_WRITE_FAILED", event_type)
        return
    if conn is not None:
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")


def _changed_fields(before: dict | None, after: dict | None) -> list[str]:
    before, after = before or {}, after or {}
    return sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))


def _history_retention_days() -> int:
    try:
        return max(1, int(getattr(settings, "AI_PROVIDER_KEY_HISTORY_RETENTION_DAYS", 30) or 30))
    except (TypeError, ValueError):
        return 30


def _purge_key_history(conn, provider_id: str | None = None) -> int:
    """Drop ciphertexts of retired keys after the retention window.

    The rotation rows (version, mask, who, when) stay for the audit trail;
    only the encrypted secret is removed.  Invalidated keys never keep it.
    """
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(days=_history_retention_days())).isoformat()
    scope_sql, scope_params = (" AND provider_id = ?", [provider_id]) if provider_id else ("", [])
    cursor = conn.execute(
        "UPDATE ai_provider_key_rotation SET api_key_encrypted = NULL "
        "WHERE api_key_encrypted IS NOT NULL AND ("
        "status = 'invalidated' OR (status = 'retired' AND COALESCE(retired_at, created_at) < ?))" + scope_sql,
        (cutoff, *scope_params),
    )
    return int(getattr(cursor, "rowcount", 0) or 0)


def _store_new_key(conn, provider_id: str, api_key: str, *, actor: str, reason: str, now_iso: str) -> tuple[str, str, int]:
    """The single path that writes a provider key: versioned, audited, encrypted."""
    encrypted = encrypt_api_key(api_key, provider_id=provider_id)
    masked = mask_api_key(api_key)
    version = int((conn.execute(
        "SELECT COALESCE(MAX(key_version), 0) FROM ai_provider_key_rotation WHERE provider_id = ?", (provider_id,)
    ).fetchone() or [0])[0]) + 1
    conn.execute(
        "UPDATE ai_provider_key_rotation SET status = 'retired', retired_at = ? WHERE provider_id = ? AND status = 'active'",
        (now_iso, provider_id),
    )
    conn.execute(
        "INSERT INTO ai_provider_key_rotation (id, provider_id, key_version, status, api_key_encrypted, api_key_masked, created_by, created_at) "
        "VALUES (?, ?, ?, 'active', ?, ?, ?, ?)",
        (f"key_{uuid.uuid4().hex[:12]}", provider_id, version, encrypted, masked, actor, now_iso),
    )
    conn.execute(
        "INSERT INTO ai_provider_key_audit (id, provider_id, key_version, action, actor_id, reason_code, created_at) "
        "VALUES (?, ?, ?, 'rotate', ?, ?, ?)",
        (f"keyaudit_{uuid.uuid4().hex[:12]}", provider_id, version, actor, reason[:80], now_iso),
    )
    _purge_key_history(conn, provider_id)
    return encrypted, masked, version


def _require_key_storage() -> None:
    try:
        require_configured_master_key()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Provider key storage is unavailable until the master key is configured") from exc


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


def _validate_deployment_endpoint(provider_type: str | None, base_url: str | None) -> None:
    """Cloud endpoints must also match the deployment-level host allowlist."""
    if not base_url or str(provider_type or "").lower() in {"local", "ollama"}:
        return
    if not deployment_endpoint_allowed(base_url):
        raise HTTPException(
            status_code=400,
            detail="Provider endpoint host is not in the deployment allowlist (AI_PROVIDER_ENDPOINT_ALLOWLIST)",
        )


def _normalize_provider_type(value) -> str:
    return str(value or "").strip().lower().replace("-", "_")


ALLOWLIST_EXCEEDS_DEPLOYMENT_CODE = "AI_PROVIDER_ALLOWLIST_EXCEEDS_DEPLOYMENT"
_FNMATCH_SPECIALS = ("*", "?", "[")


def _deployment_host_patterns() -> list[str]:
    """Host patterns of ``AI_PROVIDER_ENDPOINT_ALLOWLIST``.

    Parsed exactly like ``deployment_endpoint_allowed`` so the ceiling checked
    here is the one enforced at request time (host names, ``*`` allowed; a
    full URL entry is reduced to its host).
    """
    raw = str(getattr(settings, "AI_PROVIDER_ENDPOINT_ALLOWLIST", "") or "")
    patterns: list[str] = []
    for item in raw.split(","):
        item = item.strip().lower()
        if not item:
            continue
        if "://" in item:
            item = endpoint_host(item)
        if item:
            patterns.append(item)
    return patterns


def _pattern_host(pattern: str) -> str | None:
    """Host part of an allowlist URL pattern with its wildcards kept.

    ``None`` when the host cannot be isolated unambiguously (no scheme,
    userinfo, backslashes): such a pattern is never treated as covered.
    """
    _scheme, sep, rest = str(pattern).partition("://")
    if not sep:
        return None
    # ``?`` is an fnmatch wildcard, so it is kept in the host part (and makes
    # the host a wildcard) rather than read as the start of a query string.
    netloc = re.split(r"[/#]", rest, maxsplit=1)[0]
    if not netloc or "@" in netloc or "\\" in netloc:
        return None
    if netloc.startswith("["):
        end = netloc.find("]")
        return netloc[1:end].lower() if end > 1 else None
    return netloc.rsplit(":", 1)[0].lower() if ":" in netloc else netloc.lower()


def _pattern_within_deployment(pattern: str, base_url: str, deployment: list[str]) -> bool:
    if not deployment:
        # No deployment ceiling: the Provider may only name its own endpoint,
        # exactly and without wildcards.
        return not any(ch in pattern for ch in _FNMATCH_SPECIALS) and pattern == str(base_url).strip().rstrip("/")
    host = _pattern_host(pattern)
    if not host:
        return False
    for allowed in deployment:
        if host == allowed:
            return True
        # A wildcard host is only accepted when it is literally a deployment
        # entry; anything else (``*``, ``*.com`` ...) could be wider.
        if not any(ch in host for ch in _FNMATCH_SPECIALS) and fnmatchcase(host, allowed):
            return True
    return False


def _require_within_deployment_allowlist(base_url: str, patterns: list[str]) -> None:
    """Provider allowlists may only narrow the deployment-level allowlist."""
    deployment = _deployment_host_patterns()
    rejected = [pattern for pattern in patterns if not _pattern_within_deployment(pattern, base_url, deployment)]
    if not rejected:
        return
    if deployment:
        message = (
            "外发白名单超出了部署级白名单的范围：" + "、".join(rejected[:5])
            + "。这里只能在部署级白名单范围内收窄；如需放行新的地址，"
            "请先由服务器管理员在服务器配置 AI_PROVIDER_ENDPOINT_ALLOWLIST 中添加。"
        )
    else:
        message = (
            "服务器未配置部署级白名单（AI_PROVIDER_ENDPOINT_ALLOWLIST），外发白名单只能填写当前 Base URL 本身，"
            "不能使用通配或其他地址：" + "、".join(rejected[:5])
            + "。如需放行更多地址，请先在服务器配置 AI_PROVIDER_ENDPOINT_ALLOWLIST 中添加。"
        )
    raise HTTPException(
        status_code=400,
        detail={
            "code": ALLOWLIST_EXCEEDS_DEPLOYMENT_CODE,
            "message": message,
            "details": {"rejected_patterns": rejected[:32], "deployment_allowlist_configured": bool(deployment)},
        },
    )


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
    _require_within_deployment_allowlist(str(base_url), normalized)
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
    _validate_deployment_endpoint(payload.provider_type, payload.base_url)
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
        _require_key_storage()
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
                p_id, payload.name, payload.provider_type, payload.base_url, None, None,
                payload.timeout, payload.max_retries, payload.proxy_url, int(payload.enabled),
                username, now_iso, now_iso, json.dumps(payload.tags, ensure_ascii=False), payload.data_region,
                payload.allowed_data_classification, int(payload.no_training_confirmed), payload.retention_days,
                payload.data_processing_agreement_ref, payload.agreement_reviewed_at,
                json.dumps(approved_endpoint_patterns, ensure_ascii=False)
            )
        )
        
        key_version = None
        if payload.api_key:
            enc_key, masked_key, key_version = _store_new_key(
                conn, p_id, payload.api_key, actor=username, reason="provider_created", now_iso=now_iso,
            )
            conn.execute(
                "UPDATE ai_provider SET api_key_encrypted = ?, api_key_masked = ?, adapter_key_version = ? WHERE id = ?",
                (enc_key, masked_key, key_version, p_id),
            )

        # Only the model the administrator named is created.  Guessing model
        # codes per provider type (gpt-4o, qwen-max, llama3.1, ...) created
        # rows -- and scene routes -- for models the account may not have.
        if payload.default_model_code:
            code = payload.default_model_code
            m_id = f"model_{uuid.uuid4().hex[:12]}"
            has_default = (cursor.execute("SELECT COUNT(*) FROM ai_model WHERE is_default = 1 AND enabled = 1").fetchone() or [0])[0] > 0
            cursor.execute(
                """
                INSERT INTO ai_model (
                    id, provider_id, name, model_code, model_type, thinking_supported,
                    tool_call_supported, json_supported, context_length, max_output_tokens,
                    default_temperature, default_max_tokens, enabled, is_default, priority,
                    created_at, updated_at, stream_supported, display_name
                ) VALUES (?, ?, ?, ?, 'chat', 0, 1, 1, 131072, 16384, 0.7, 4096, 1, ?, 10, ?, ?, 1, ?)
                """,
                (m_id, p_id, f"{payload.name} ({code})", code, 0 if has_default else 1, now_iso, now_iso, f"{payload.name} ({code})"),
            )
            # Routes only where a scene has none yet, and only to the model
            # the administrator named.
            for scene in ("chat", "agent", "config_diff", "alarm_analysis", "command_explain"):
                if not cursor.execute("SELECT id FROM ai_model_route WHERE scene = ?", (scene,)).fetchone():
                    cursor.execute(
                        "INSERT INTO ai_model_route (id, scene, model_id, enabled, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
                        (f"route_{uuid.uuid4().hex[:12]}", scene, m_id, now_iso, now_iso),
                    )

        _audit_provider(
            user, event_type="ai_provider.created", provider_id=p_id,
            summary=f"AI Provider created: {payload.name}",
            after=_provider_snapshot(conn, p_id),
            details={"default_model_code": payload.default_model_code, "key_version": key_version},
            conn=conn,
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
        cursor.execute("SELECT id, api_key_encrypted, api_key_masked, provider_type, base_url, approved_endpoint_patterns_json FROM ai_provider WHERE id = ?", (provider_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found.")
        
        next_type = payload.provider_type or row[3]
        next_url = payload.base_url if payload.base_url is not None else row[4]
        _validate_provider_endpoint(next_type, next_url)
        _validate_deployment_endpoint(next_type, next_url)
        if next_type == "deepseek" and next_url and next_url.rstrip('/') not in {'https://api.deepseek.com', 'https://api.deepseek.com/v1'}:
            raise HTTPException(status_code=400, detail='DeepSeek provider must use the official HTTPS endpoint')
        approved_endpoint_patterns = None
        if payload.approved_endpoint_patterns is not None:
            approved_endpoint_patterns = _validate_endpoint_allowlist(
                next_type,
                next_url,
                payload.approved_endpoint_patterns,
            )
        elif payload.base_url is not None and str(next_type).lower() not in {"local", "ollama"} and next_url:
            raw_existing = row[5] if len(row) > 5 else None
            if isinstance(raw_existing, (list, tuple)):
                existing_patterns = [str(item).strip().rstrip("/") for item in raw_existing if str(item).strip()]
            else:
                try:
                    parsed_existing = json.loads(str(raw_existing or "[]"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed_existing = []
                existing_patterns = [str(item).strip().rstrip("/") for item in (parsed_existing if isinstance(parsed_existing, list) else []) if str(item).strip()]
            normalized_next = str(next_url).strip().rstrip("/")
            if not any(fnmatchcase(normalized_next, pattern) for pattern in existing_patterns):
                approved_endpoint_patterns = _validate_endpoint_allowlist(
                    next_type,
                    next_url,
                    [normalized_next],
                )
        if payload.name is not None and cursor.execute("SELECT id FROM ai_provider WHERE name = ? AND id <> ?", (payload.name, provider_id)).fetchone():
            raise HTTPException(status_code=409, detail="Provider name already exists")
        enc_key = row[1]
        masked_key = row[2]
        # A stored key never follows a Provider to another host or adapter:
        # otherwise the same permission could redirect it to any HTTPS
        # endpoint.  On an endpoint change the caller supplies a new key, or
        # the Provider is left without one.
        endpoint_changed = (
            (payload.base_url is not None and endpoint_host(next_url) != endpoint_host(row[4]))
            or (payload.provider_type is not None and _normalize_provider_type(next_type) != _normalize_provider_type(row[3]))
        )
        key_cleared = endpoint_changed and not payload.api_key and bool(row[1])
        if key_cleared:
            enc_key = None
            masked_key = None
        before = _provider_snapshot(conn, provider_id)
        actor = user.get("username", "admin")
        new_key_version = None
        if payload.api_key:
            # Same versioned, audited path as rotate-key; the edit form is
            # only a convenience for supplying the replacement key.
            _require_key_storage()
            enc_key, masked_key, new_key_version = _store_new_key(
                conn, provider_id, payload.api_key, actor=actor,
                reason="endpoint_changed_key_replaced" if endpoint_changed else "provider_updated", now_iso=now_iso,
            )
        elif payload.api_key is not None and row[1]:
            # An empty string clears the key: treat as an invalidation.
            enc_key, masked_key = None, None
            conn.execute(
                "UPDATE ai_provider_key_rotation SET status = 'invalidated', invalidated_at = ?, api_key_encrypted = NULL "
                "WHERE provider_id = ? AND status = 'active'",
                (now_iso, provider_id),
            )
            conn.execute(
                "INSERT INTO ai_provider_key_audit (id, provider_id, key_version, action, actor_id, reason_code, created_at) "
                "VALUES (?, ?, NULL, 'invalidate', ?, 'cleared_in_edit', ?)",
                (f"keyaudit_{uuid.uuid4().hex[:12]}", provider_id, actor, now_iso),
            )

        fields = []
        params = []
        if payload.name is not None: fields.append("name = ?"); params.append(payload.name)
        if payload.provider_type is not None: fields.append("provider_type = ?"); params.append(payload.provider_type)
        if payload.base_url is not None: fields.append("base_url = ?"); params.append(payload.base_url)
        key_changed = payload.api_key is not None or key_cleared
        if key_changed: fields.extend(["api_key_encrypted = ?", "api_key_masked = ?"]); params.extend([enc_key, masked_key])
        if new_key_version is not None: fields.append("adapter_key_version = ?"); params.append(new_key_version)
        if key_changed or endpoint_changed:
            fields.extend(["health_status = 'unknown'", "last_health_check_at = NULL", "last_success_at = NULL", "last_error_code = NULL", "last_error_at = NULL"])
        if payload.timeout is not None: fields.append("timeout = ?"); params.append(payload.timeout)
        if payload.max_retries is not None: fields.append("max_retries = ?"); params.append(payload.max_retries)
        if payload.proxy_url is not None: fields.append("proxy_url = ?"); params.append(payload.proxy_url)
        if payload.enabled is not None: fields.append("enabled = ?"); params.append(int(payload.enabled))
        if payload.tags is not None: fields.append("tags_json = ?"); params.append(json.dumps(payload.tags, ensure_ascii=False))
        if payload.data_region is not None: fields.append("data_region = ?"); params.append(payload.data_region)
        if payload.allowed_data_classification is not None: fields.append("allowed_data_classification = ?"); params.append(payload.allowed_data_classification)
        if payload.no_training_confirmed is not None: fields.append("no_training_confirmed = ?"); params.append(int(payload.no_training_confirmed))
        # An explicit null clears the value (the edit form sends null for an
        # emptied field); an omitted field is left unchanged.
        if payload.retention_days is not None or "retention_days" in payload.model_fields_set:
            fields.append("retention_days = ?"); params.append(payload.retention_days)
        if payload.data_processing_agreement_ref is not None: fields.append("data_processing_agreement_ref = ?"); params.append(payload.data_processing_agreement_ref)
        if payload.agreement_reviewed_at is not None or "agreement_reviewed_at" in payload.model_fields_set:
            fields.append("agreement_reviewed_at = ?"); params.append(payload.agreement_reviewed_at or None)
        if approved_endpoint_patterns is not None:
            fields.append("approved_endpoint_patterns_json = ?")
            params.append(json.dumps(approved_endpoint_patterns or [], ensure_ascii=False))

        fields.append("updated_at = ?")
        params.append(now_iso)
        params.append(provider_id)

        query = f"UPDATE ai_provider SET {', '.join(fields)} WHERE id = ?"
        cursor.execute(query, tuple(params))
        if endpoint_changed and row[1]:
            if key_cleared:
                cursor.execute(
                    "UPDATE ai_provider_key_rotation SET status = 'invalidated', invalidated_at = ?, api_key_encrypted = NULL "
                    "WHERE provider_id = ? AND status = 'active'",
                    (now_iso, provider_id),
                )
            cursor.execute(
                "INSERT INTO ai_provider_key_audit (id, provider_id, key_version, action, actor_id, reason_code, created_at) VALUES (?, ?, ?, 'invalidate', ?, ?, ?)",
                (
                    f"keyaudit_{uuid.uuid4().hex[:12]}",
                    provider_id,
                    None,
                    user.get("username", "admin"),
                    "endpoint_changed" if key_cleared else "endpoint_changed_key_replaced",
                    now_iso,
                ),
            )
        after = _provider_snapshot(conn, provider_id)
        changed = _changed_fields(before, after)
        # The snapshot only records *whether* a key is stored, so replacing a
        # key with another one looks unchanged.  A new key version is always
        # an audited change.
        if new_key_version is not None and "key_configured" not in changed:
            changed = sorted([*changed, "key_version"])
        if changed:
            toggled = changed == ["enabled"]
            _audit_provider(
                user,
                event_type=("ai_provider.enabled" if after and after.get("enabled") else "ai_provider.disabled") if toggled else "ai_provider.updated",
                provider_id=provider_id,
                summary=f"AI Provider {'enabled' if after and after.get('enabled') else 'disabled'}: {(after or {}).get('name')}" if toggled
                else f"AI Provider updated: {(after or {}).get('name')} ({', '.join(changed)})",
                severity="high" if {"base_url", "provider_type", "key_configured", "key_version", "allowed_data_classification", "data_region", "approved_endpoint_patterns"} & set(changed) else "medium",
                before=before, after=after,
                details={"changed_fields": changed, "endpoint_changed": bool(endpoint_changed), "key_version": new_key_version},
                conn=conn,
            )
        conn.commit()
        if key_changed or endpoint_changed:
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
        before = _provider_snapshot(conn, provider_id)
        cursor.execute("DELETE FROM ai_provider WHERE id = ?", (provider_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Provider not found")
        _audit_provider(
            user, event_type="ai_provider.deleted", provider_id=provider_id, severity="high",
            summary=f"AI Provider deleted: {(before or {}).get('name')}", before=before, conn=conn,
        )
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
    _require_key_storage()
    with get_db_connection() as conn:
        row = conn.execute("SELECT id, name FROM ai_provider WHERE id = ?", (provider_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Provider not found")
        encrypted, masked, version = _store_new_key(
            conn, provider_id, api_key, actor=user.get("username", "admin"), reason="manual_rotation", now_iso=now_iso,
        )
        conn.execute("UPDATE ai_provider SET api_key_encrypted = ?, api_key_masked = ?, adapter_key_version = ?, health_status = 'unknown', disabled_reason = NULL, updated_at = ? WHERE id = ?", (encrypted, masked, version, now_iso, provider_id))
        _audit_provider(
            user, event_type="ai_provider.key_rotated", provider_id=provider_id, severity="high",
            summary=f"AI Provider key rotated: {row[1]} (v{version})", details={"key_version": version}, conn=conn,
        )
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
        conn.execute("UPDATE ai_provider_key_rotation SET status = 'invalidated', invalidated_at = ?, api_key_encrypted = NULL WHERE provider_id = ? AND status = 'active'", (now_iso, provider_id))
        conn.execute("UPDATE ai_provider SET api_key_encrypted = NULL, api_key_masked = NULL, health_status = 'disabled', disabled_reason = ?, last_error_code = 'AI_KEY_INVALIDATED', updated_at = ? WHERE id = ?", (reason, now_iso, provider_id))
        conn.execute("INSERT INTO ai_provider_key_audit (id, provider_id, key_version, action, actor_id, reason_code, created_at) VALUES (?, ?, ?, 'invalidate', ?, ?, ?)", (f"keyaudit_{uuid.uuid4().hex[:12]}", provider_id, version, user.get("username", "admin"), reason, now_iso))
        _audit_provider(
            user, event_type="ai_provider.key_invalidated", provider_id=provider_id, severity="high",
            summary=f"AI Provider key invalidated ({reason})", details={"key_version": version, "reason": reason}, conn=conn,
        )
        conn.commit()
        return _row_to_provider(conn.execute(_PROVIDER_SELECT + " WHERE id = ?", (provider_id,)).fetchone())


@router.get("/{provider_id}/key-history")
def provider_key_history(provider_id: str, user=Depends(require_ai_permission("ai.provider.manage"))):
    """Key versions and key audit trail; never returns key material."""
    with get_db_connection() as conn:
        if not conn.execute("SELECT id FROM ai_provider WHERE id = ?", (provider_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Provider not found")
        versions = conn.execute(
            "SELECT key_version, status, api_key_masked, created_by, created_at, retired_at, invalidated_at, "
            "api_key_encrypted IS NOT NULL FROM ai_provider_key_rotation WHERE provider_id = ? ORDER BY key_version DESC LIMIT 50",
            (provider_id,),
        ).fetchall()
        audit = conn.execute(
            "SELECT key_version, action, actor_id, reason_code, created_at FROM ai_provider_key_audit "
            "WHERE provider_id = ? ORDER BY created_at DESC LIMIT 100",
            (provider_id,),
        ).fetchall()
    return {
        "provider_id": provider_id,
        "retention_days": _history_retention_days(),
        "versions": [
            {
                "key_version": row[0], "status": row[1], "api_key_masked": row[2], "created_by": row[3],
                "created_at": row[4], "retired_at": row[5], "invalidated_at": row[6], "ciphertext_retained": bool(row[7]),
            }
            for row in versions
        ],
        "audit": [
            {"key_version": row[0], "action": row[1], "actor": row[2], "reason_code": row[3], "created_at": row[4]}
            for row in audit
        ],
    }


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
            "SELECT id, model_code, model_type FROM ai_model WHERE provider_id = ? AND enabled = 1 ORDER BY is_default DESC, priority DESC LIMIT 1",
            (provider_id,),
        ).fetchone()
    if not model_row:
        raise HTTPException(status_code=400, detail="Provider has no enabled V4 model")
    started = datetime.now(timezone.utc)
    if str(model_row[2] or "").lower() == "embedding":
        from ai.services.model_health import check_model_health

        probe = await check_model_health(
            model_row[0],
            user_id=str(user.get("username") or "provider-test"),
            tenant_id=str(user.get("tenant_id") or "tenant-default"),
        )
        now_ts = datetime.now(timezone.utc).isoformat()
        with get_db_connection() as conn:
            if probe.get("success"):
                conn.execute(
                    "UPDATE ai_provider SET health_status = 'healthy', last_health_check_at = ?, last_success_at = ?, last_error_code = NULL, updated_at = ? WHERE id = ?",
                    (now_ts, now_ts, now_ts, provider_id),
                )
            else:
                conn.execute(
                    "UPDATE ai_provider SET health_status = 'unhealthy', last_health_check_at = ?, last_error_code = ?, updated_at = ? WHERE id = ?",
                    (now_ts, str(probe.get("error_code") or "AI_EMBEDDING_PROBE_FAILED"), now_ts, provider_id),
                )
            conn.commit()
        return AIProviderTestResponse(
            success=bool(probe.get("success")),
            latency_ms=int(probe.get("latency_ms") or 0),
            message=str(probe.get("message") or ("embedding connection succeeded" if probe.get("success") else "embedding probe failed")),
            model_tested=model_row[1],
            error_code=probe.get("error_code"),
        )
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
