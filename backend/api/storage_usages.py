"""Administrator API for per-purpose storage routing."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.rbac import require_role
from database import get_db_connection
from services.audit_service import log_audit_event
from services.storage_service import (
    StorageError,
    USAGE_PURPOSES,
    _service_for_profile,
    effective_storage_provider,
    get_storage_provider_config,
    list_storage_usage_bindings,
    normalize_relative_prefix,
    resolve_storage_usage,
)


router = APIRouter(prefix="/storage/usages", tags=["Storage usage routing"])


class StorageUsageUpdate(BaseModel):
    provider_mode: str = Field(default="default")
    provider_id: str | None = None
    bucket_override: str | None = Field(default=None, max_length=255)
    key_prefix: str = Field(default="", max_length=512)


def _bucket(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,253}[A-Za-z0-9]", text):
        raise HTTPException(status_code=422, detail="bucket_override is invalid")
    return text


_USAGE_LABELS = {
    "config_backup": "Config backups",
    "pam_recording": "PAM recordings",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@router.get("")
def list_usages(_user=require_role("Administrator")):
    try:
        bindings = list_storage_usage_bindings()
        items = []
        for binding in bindings:
            resolved_binding, profile = resolve_storage_usage(binding.purpose)
            items.append({
                "purpose": binding.purpose,
                "label": _USAGE_LABELS.get(binding.purpose, binding.purpose),
                "provider_mode": binding.provider_mode,
                "provider_id": binding.provider_id,
                "bucket_override": binding.bucket_override,
                "key_prefix": binding.key_prefix,
                "effective_provider_id": profile.id or ("environment" if profile.source == "environment" else None),
                "effective_provider_name": profile.name,
                "effective_source": profile.source,
                "effective_bucket": resolved_binding.bucket_override or profile.bucket,
                "effective_endpoint_url": profile.endpoint_url,
            })
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Storage usage configuration is unavailable") from exc
    return {"items": items}


@router.put("/{purpose}")
def update_usage(purpose: str, payload: StorageUsageUpdate, user=require_role("Administrator")):
    purpose = str(purpose or "").strip()
    if purpose not in USAGE_PURPOSES:
        raise HTTPException(status_code=404, detail="Unsupported storage usage purpose")
    mode = str(payload.provider_mode or "").strip().lower()
    if mode not in {"default", "environment", "profile"}:
        raise HTTPException(status_code=422, detail="provider_mode must be default, environment, or profile")
    provider_id = str(payload.provider_id or "").strip() or None
    if mode == "profile":
        if not provider_id or provider_id == "environment":
            raise HTTPException(status_code=422, detail="provider_id is required for profile mode")
        try:
            from services.storage_service import get_storage_provider_config
            get_storage_provider_config(provider_id)
        except StorageError as exc:
            raise HTTPException(status_code=422, detail="Storage provider not found or unavailable") from exc
    else:
        provider_id = None
    bucket_override = _bucket(payload.bucket_override)
    try:
        key_prefix = normalize_relative_prefix(payload.key_prefix)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="key_prefix must be a safe relative prefix") from exc
    conn = get_db_connection()
    try:
        conn.execute(
            """UPDATE storage_usage_bindings
               SET provider_mode=?, provider_id=?, bucket_override=?, key_prefix=?, updated_at=?
               WHERE purpose=?""",
            (mode, provider_id, bucket_override, key_prefix, _now(), purpose),
        )
        if conn.execute("SELECT 1 FROM storage_usage_bindings WHERE purpose = ?", (purpose,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Storage usage purpose not found")
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        if "foreign key" in str(exc).lower() or "violates" in str(exc).lower():
            raise HTTPException(status_code=409, detail="Storage provider is not available") from exc
        raise HTTPException(status_code=400, detail="Storage usage configuration could not be saved") from exc
    finally:
        conn.close()
    try:
        binding, profile = resolve_storage_usage(purpose)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Storage usage configuration is unavailable") from exc
    try:
        log_audit_event(
            event_type="STORAGE_USAGE_UPDATE",
            category="system_configuration",
            severity="medium",
            status="success",
            summary=f"Updated storage usage route {purpose}",
            actor_id=str(user.get("id") or user.get("user_id") or "") or None,
            actor_username=str(user.get("username") or "admin"),
            actor_role=str(user.get("role") or "Administrator"),
            target_type="storage_usage",
            target_id=purpose,
            target_name=purpose,
            details={
                "provider_mode": binding.provider_mode,
                "provider_id": binding.provider_id,
                "bucket_override": binding.bucket_override,
                "key_prefix": binding.key_prefix,
            },
        )
    except Exception:
        pass
    return {
        "purpose": binding.purpose,
        "label": _USAGE_LABELS.get(binding.purpose, binding.purpose),
        "provider_mode": binding.provider_mode,
        "provider_id": binding.provider_id,
        "bucket_override": binding.bucket_override,
        "key_prefix": binding.key_prefix,
        "effective_provider_id": profile.id or ("environment" if profile.source == "environment" else None),
        "effective_provider_name": profile.name,
        "effective_source": profile.source,
        "effective_bucket": binding.bucket_override or profile.bucket,
        "effective_endpoint_url": profile.endpoint_url,
    }


@router.post("/{purpose}/test")
def test_usage(purpose: str, payload: StorageUsageUpdate, _user=require_role("Administrator")):
    """Test an unsaved usage route draft without changing the binding."""

    purpose = str(purpose or "").strip()
    if purpose not in USAGE_PURPOSES:
        raise HTTPException(status_code=404, detail="Unsupported storage usage purpose")
    mode = str(payload.provider_mode or "").strip().lower()
    if mode not in {"default", "environment", "profile"}:
        raise HTTPException(status_code=422, detail="provider_mode must be default, environment, or profile")
    provider_id = str(payload.provider_id or "").strip() or None
    if mode == "profile":
        if not provider_id or provider_id == "environment":
            raise HTTPException(status_code=422, detail="provider_id is required for profile mode")
    else:
        provider_id = None
    bucket_override = _bucket(payload.bucket_override)
    try:
        key_prefix = normalize_relative_prefix(payload.key_prefix)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="key_prefix must be a safe relative prefix") from exc

    try:
        if mode == "profile":
            profile = get_storage_provider_config(provider_id)
        elif mode == "environment":
            profile = get_storage_provider_config("environment")
        else:
            profile = effective_storage_provider()
        service = _service_for_profile(
            profile,
            bucket=bucket_override,
            key_prefix=key_prefix,
            purpose=purpose,
        )
        ok, message = service.health_check()
        return {
            "ok": bool(ok),
            "success": bool(ok),
            "message": message if ok else "Storage usage health check failed",
        }
    except Exception:
        return {
            "ok": False,
            "success": False,
            "message": "Storage usage health check failed",
        }


__all__ = ["router"]
