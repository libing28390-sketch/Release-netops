"""Administrator API for database-backed S3 provider profiles."""

from __future__ import annotations

import re
import uuid
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.crypto import encrypt_credential
from core.rbac import require_role
from database import get_db_connection
from services.audit_service import log_audit_event
from services.storage_service import (
    StorageError,
    StorageProviderConfig,
    _service_for_profile,
    effective_storage_provider,
    get_storage_provider_config,
    list_storage_provider_configs,
)


router = APIRouter(prefix="/storage/providers", tags=["Storage providers"])
logger = logging.getLogger(__name__)


class StorageProviderPayload(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    backend: str = Field(default="s3")
    endpoint_url: str = Field(min_length=1, max_length=2048)
    bucket: str = Field(min_length=1, max_length=255)
    region: str = Field(default="us-east-1", max_length=128)
    access_key_id: str = Field(default="", max_length=512)
    secret_access_key: str = Field(default="", max_length=4096)
    force_path_style: bool = True
    verify_tls: bool = True
    is_default: bool = False
    notes: str = Field(default="", max_length=2000)


class StorageProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    backend: str | None = None
    endpoint_url: str | None = Field(default=None, max_length=2048)
    bucket: str | None = Field(default=None, max_length=255)
    region: str | None = Field(default=None, max_length=128)
    access_key_id: str | None = Field(default=None, max_length=512)
    secret_access_key: str | None = Field(default=None, max_length=4096)
    force_path_style: bool | None = None
    verify_tls: bool | None = None
    is_default: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class StorageProviderTestPayload(BaseModel):
    backend: str = "s3"
    endpoint_url: str = Field(min_length=1, max_length=2048)
    bucket: str = Field(min_length=1, max_length=255)
    region: str = Field(default="us-east-1", max_length=128)
    access_key_id: str = Field(default="", max_length=512)
    secret_access_key: str = Field(default="", max_length=4096)
    force_path_style: bool = True
    verify_tls: bool = True


def _validate_profile_values(payload: dict) -> None:
    if "name" in payload and not str(payload.get("name") or "").strip():
        raise HTTPException(status_code=422, detail="name is required")
    if str(payload.get("backend") or "s3").strip().lower() != "s3":
        raise HTTPException(status_code=422, detail="Only the s3 backend is supported")
    endpoint = str(payload.get("endpoint_url") or "").strip()
    parsed = urlparse(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or any(char.isspace() for char in endpoint)
    ):
        raise HTTPException(status_code=422, detail="endpoint_url must be an HTTP(S) URL without credentials")
    bucket = str(payload.get("bucket") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,253}[A-Za-z0-9]", bucket):
        raise HTTPException(status_code=422, detail="bucket is invalid")
    if not str(payload.get("region") or "").strip():
        raise HTTPException(status_code=422, detail="region is required")


def _mask_access_key(value: str) -> str:
    value = str(value or "")
    if len(value) <= 8:
        return "••••••••" if value else ""
    return f"{value[:4]}••••{value[-4:]}"


def _item(profile: StorageProviderConfig) -> dict:
    return {
        "id": profile.id or ("environment" if profile.source == "environment" else None),
        "name": profile.name,
        "backend": profile.backend,
        "endpoint_url": profile.endpoint_url,
        "bucket": profile.bucket,
        "region": profile.region,
        "force_path_style": profile.force_path_style,
        "verify_tls": profile.verify_tls,
        "is_default": profile.is_default,
        "notes": profile.notes,
        "source": profile.source,
        "access_key_id_masked": _mask_access_key(profile.access_key_id),
        "has_access_key": bool(profile.access_key_id),
        "has_secret_key": bool(profile.secret_access_key),
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _audit(event_type: str, *, user: dict, provider_id: str, provider_name: str, summary: str, details: dict | None = None) -> None:
    try:
        log_audit_event(
            event_type=event_type,
            category="system_configuration",
            severity="medium",
            status="success",
            summary=summary,
            actor_id=str(user.get("id") or user.get("user_id") or "") or None,
            actor_username=str(user.get("username") or "admin"),
            actor_role=str(user.get("role") or "Administrator"),
            target_type="storage_provider",
            target_id=provider_id,
            target_name=provider_name,
            details=details or {},
        )
    except Exception:
        # A logging outage must not turn a completed provider mutation into a
        # failed response, and this warning contains no provider credentials.
        logger.warning("Storage provider audit event could not be persisted: %s", event_type)


def _set_default(conn, provider_id: str | None) -> None:
    conn.execute("UPDATE storage_provider_configs SET is_default = FALSE, updated_at = ?", (_now(),))
    if provider_id:
        conn.execute(
            "UPDATE storage_provider_configs SET is_default = TRUE, updated_at = ? WHERE id = ?",
            (_now(), provider_id),
        )


@router.get("")
def list_providers(_user=require_role("Administrator")):
    try:
        profiles = list_storage_provider_configs()
        effective = effective_storage_provider()
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Storage provider configuration is unavailable") from exc
    return {
        "items": [_item(profile) for profile in profiles],
        "effective_default_id": effective.id or ("environment" if effective.source == "environment" else None),
        "default_source": effective.source,
    }


@router.post("", status_code=201)
def create_provider(payload: StorageProviderPayload, user=require_role("Administrator")):
    values = payload.model_dump()
    _validate_profile_values(values)
    if not values["access_key_id"].strip() or not values["secret_access_key"].strip():
        raise HTTPException(status_code=422, detail="S3 credentials are required")
    provider_id = str(uuid.uuid4())
    now = _now()
    conn = get_db_connection()
    try:
        if values["is_default"]:
            _set_default(conn, None)
        conn.execute(
            """INSERT INTO storage_provider_configs
               (id, name, backend, endpoint_url, bucket, region,
                access_key_id_encrypted, secret_access_key_encrypted,
                force_path_style, verify_tls, is_default, notes, created_at, updated_at)
               VALUES (?, ?, 's3', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                provider_id, values["name"].strip(), values["endpoint_url"].strip(),
                values["bucket"].strip(), values["region"].strip() or "us-east-1",
                encrypt_credential(values["access_key_id"].strip()),
                encrypt_credential(values["secret_access_key"].strip()),
                values["force_path_style"], values["verify_tls"], values["is_default"],
                values["notes"].strip(), now, now,
            ),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise HTTPException(status_code=409, detail="Storage provider name or default already exists") from exc
        raise HTTPException(status_code=400, detail="Storage provider could not be saved") from exc
    finally:
        conn.close()
    try:
        profile = get_storage_provider_config(provider_id)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Storage provider configuration is unavailable") from exc
    _audit(
        "STORAGE_PROVIDER_CREATE",
        user=user,
        provider_id=provider_id,
        provider_name=profile.name,
        summary=f"Created storage provider {profile.name}",
        details={"is_default": bool(profile.is_default)},
    )
    if profile.is_default:
        _audit(
            "STORAGE_PROVIDER_DEFAULT_CHANGE",
            user=user,
            provider_id=provider_id,
            provider_name=profile.name,
            summary=f"Set storage provider {profile.name} as default",
            details={"is_default": True},
        )
    return _item(profile)


@router.put("/{provider_id}")
def update_provider(provider_id: str, payload: StorageProviderUpdate, user=require_role("Administrator")):
    try:
        current = get_storage_provider_config(provider_id)
    except StorageError as exc:
        status = 404 if "not found" in str(exc).lower() else 503
        detail = "Storage provider not found" if status == 404 else "Storage provider configuration is unavailable"
        raise HTTPException(status_code=status, detail=detail) from exc
    updates = payload.model_dump(exclude_unset=True)
    merged = {
        "name": updates.get("name", current.name),
        "backend": updates.get("backend", current.backend),
        "endpoint_url": updates.get("endpoint_url", current.endpoint_url),
        "bucket": updates.get("bucket", current.bucket),
        "region": updates.get("region", current.region),
        "force_path_style": updates.get("force_path_style", current.force_path_style),
        "verify_tls": updates.get("verify_tls", current.verify_tls),
        "is_default": updates.get("is_default", current.is_default),
        "notes": updates.get("notes", current.notes),
    }
    _validate_profile_values(merged)
    access_key = str(updates.get("access_key_id") or "").strip() or current.access_key_id
    secret_key = str(updates.get("secret_access_key") or "").strip() or current.secret_access_key
    if not access_key or not secret_key:
        raise HTTPException(status_code=422, detail="S3 credentials are required")
    conn = get_db_connection()
    try:
        if not conn.execute("SELECT 1 FROM storage_provider_configs WHERE id = ?", (provider_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Storage provider not found")
        referenced = any(
            conn.execute(
                f"SELECT 1 FROM {table} WHERE storage_config_id = ? LIMIT 1", (provider_id,)
            ).fetchone()
            for table in ("config_snapshots", "pam_sessions")
        )
        connection_fields_changed = any(
            (
                field == "endpoint_url" and str(updates[field]).strip() != current.endpoint_url
            )
            or (
                field == "bucket" and str(updates[field]).strip() != current.bucket
            )
            or (
                field == "region" and str(updates[field]).strip() != current.region
            )
            or (field == "backend" and str(updates[field]).strip().lower() != current.backend)
            or (field == "force_path_style" and bool(updates[field]) != current.force_path_style)
            or (field == "verify_tls" and bool(updates[field]) != current.verify_tls)
            or (field == "access_key_id" and str(updates[field]).strip() != current.access_key_id)
            or (field == "secret_access_key" and str(updates[field]).strip() != current.secret_access_key)
            for field in updates
            if field in {"endpoint_url", "bucket", "region", "backend", "force_path_style", "verify_tls", "access_key_id", "secret_access_key"}
            and updates[field] is not None
            and not (field in {"access_key_id", "secret_access_key"} and not str(updates[field] or "").strip())
        )
        if referenced and connection_fields_changed:
            raise HTTPException(
                status_code=409,
                detail="Referenced objects are bound to this provider; create a new profile before changing connection settings",
            )
        was_default = current.is_default
        if merged["is_default"]:
            _set_default(conn, None)
        conn.execute(
            """UPDATE storage_provider_configs
               SET name=?, endpoint_url=?, bucket=?, region=?,
                   access_key_id_encrypted=?, secret_access_key_encrypted=?,
                   force_path_style=?, verify_tls=?, is_default=?, notes=?, updated_at=?
               WHERE id=?""",
            (
                merged["name"].strip(), merged["endpoint_url"].strip(), merged["bucket"].strip(),
                merged["region"].strip() or "us-east-1", encrypt_credential(access_key),
                encrypt_credential(secret_key), merged["force_path_style"], merged["verify_tls"],
                merged["is_default"], str(merged["notes"] or "").strip(), _now(), provider_id,
            ),
        )
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise HTTPException(status_code=409, detail="Storage provider name or default already exists") from exc
        raise HTTPException(status_code=400, detail="Storage provider could not be updated") from exc
    finally:
        conn.close()
    try:
        profile = get_storage_provider_config(provider_id)
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Storage provider configuration is unavailable") from exc
    _audit(
        "STORAGE_PROVIDER_UPDATE",
        user=user,
        provider_id=provider_id,
        provider_name=profile.name,
        summary=f"Updated storage provider {profile.name}",
        details={"is_default": bool(profile.is_default)},
    )
    if was_default != profile.is_default:
        _audit(
            "STORAGE_PROVIDER_DEFAULT_CHANGE",
            user=user,
            provider_id=provider_id,
            provider_name=profile.name,
            summary=(f"Set storage provider {profile.name} as default" if profile.is_default else f"Cleared default storage provider {profile.name}"),
            details={"is_default": bool(profile.is_default)},
        )
    return _item(profile)


@router.delete("/{provider_id}")
def delete_provider(provider_id: str, user=require_role("Administrator")):
    if provider_id == "environment":
        raise HTTPException(status_code=400, detail="The environment profile cannot be deleted")
    conn = get_db_connection()
    try:
        for table in ("config_snapshots", "pam_sessions"):
            row = conn.execute(
                f"SELECT 1 FROM {table} WHERE storage_config_id = ? LIMIT 1", (provider_id,)
            ).fetchone()
            if row:
                raise HTTPException(status_code=409, detail="Storage provider is referenced by stored objects")
        if conn.execute(
            "SELECT 1 FROM storage_usage_bindings WHERE provider_mode = 'profile' AND provider_id = ? LIMIT 1",
            (provider_id,),
        ).fetchone():
            raise HTTPException(status_code=409, detail="Storage provider is referenced by a usage binding")
        row = conn.execute("SELECT name, is_default FROM storage_provider_configs WHERE id = ?", (provider_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Storage provider not found")
        conn.execute("DELETE FROM storage_provider_configs WHERE id = ?", (provider_id,))
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        if "foreign key" in str(exc).lower() or "violates" in str(exc).lower():
            raise HTTPException(status_code=409, detail="Storage provider is referenced by stored objects") from exc
        raise HTTPException(status_code=400, detail="Storage provider could not be deleted") from exc
    finally:
        conn.close()
    _audit(
        "STORAGE_PROVIDER_DELETE",
        user=user,
        provider_id=provider_id,
        provider_name=str(row["name"] if "name" in row.keys() else provider_id),
        summary=f"Deleted storage provider {str(row['name'] if 'name' in row.keys() else provider_id)}",
        details={"was_default": bool(row["is_default"])},
    )
    if row["is_default"]:
        _audit(
            "STORAGE_PROVIDER_DEFAULT_CHANGE",
            user=user,
            provider_id=provider_id,
            provider_name=str(row["name"] if "name" in row.keys() else provider_id),
            summary="Cleared default storage provider",
            details={"is_default": False},
        )
    return {"ok": True}


def _test_profile(profile: StorageProviderConfig) -> dict:
    try:
        ok, message = _service_for_profile(profile).health_check()
        return {
            "ok": bool(ok),
            "success": bool(ok),
            "message": message,
        }
    except Exception as exc:
        return {"ok": False, "success": False, "message": f"Storage provider test failed: {type(exc).__name__}"}


@router.post("/test")
def test_provider(payload: StorageProviderTestPayload, _user=require_role("Administrator")):
    values = payload.model_dump()
    _validate_profile_values(values)
    if not values["access_key_id"].strip() or not values["secret_access_key"].strip():
        raise HTTPException(status_code=422, detail="S3 credentials are required")
    profile = StorageProviderConfig(
        id=None, name="Unsaved profile", backend="s3", endpoint_url=values["endpoint_url"],
        bucket=values["bucket"], region=values["region"], access_key_id=values["access_key_id"],
        secret_access_key=values["secret_access_key"], force_path_style=values["force_path_style"],
        verify_tls=values["verify_tls"],
    )
    return _test_profile(profile)


@router.post("/{provider_id}/test")
def test_saved_provider(provider_id: str, _user=require_role("Administrator")):
    if provider_id == "environment":
        try:
            # The virtual Environment row always represents the deployment
            # environment.  It must not resolve through the database default.
            profile = get_storage_provider_config("environment")
        except StorageError as exc:
            raise HTTPException(status_code=503, detail="Storage provider configuration is unavailable") from exc
    else:
        try:
            profile = get_storage_provider_config(provider_id)
        except StorageError as exc:
            status = 404 if "not found" in str(exc).lower() else 503
            detail = "Storage provider not found" if status == 404 else "Storage provider configuration is unavailable"
            raise HTTPException(status_code=status, detail=detail) from exc
    return _test_profile(profile)


__all__ = ["router"]
