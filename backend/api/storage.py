"""Read-only storage provider status for the operations UI."""

from __future__ import annotations

import re
import posixpath
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from core.rbac import require_role
from database import get_db_connection
from services.storage_service import (
    StorageError,
    StorageNotFound,
    _service_for_profile,
    build_storage_service,
    effective_storage_provider,
    get_storage_provider_config,
    normalize_object_key,
    resolve_storage_usage,
)
from services.config_snapshot_storage import deserialize_config_bytes


router = APIRouter(prefix="/storage", tags=["Storage"])


def _count(conn, table: str, where: str, params: tuple[Any, ...] = ()) -> int:
    try:
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE {where}", params).fetchone()
        return int(row["count"] if row and "count" in row.keys() else row[0] if row else 0)
    except Exception:
        return 0


def _storage_counts(conn) -> dict[str, int]:
    ready = pending = error = legacy = spool = 0
    for table in ("config_snapshots", "pam_sessions"):
        ready += _count(conn, table, "COALESCE(storage_status, 'LEGACY') = 'READY'")
        pending += _count(conn, table, "COALESCE(storage_status, 'LEGACY') IN ('PENDING', 'UPLOADING')")
        error += _count(conn, table, "COALESCE(storage_status, 'LEGACY') = 'ERROR'")
        legacy += _count(conn, table, "COALESCE(storage_status, 'LEGACY') = 'LEGACY'")
    spool += _count(conn, "config_snapshots", "COALESCE(storage_spool_path, '') <> ''")
    spool += _count(conn, "pam_sessions", "COALESCE(recording_spool_path, '') <> ''")
    return {"ready": ready, "pending": pending, "error": error, "legacy": legacy, "spool": spool}


def _recent_errors(conn, limit: int = 5) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for table, kind in (("config_snapshots", "config"), ("pam_sessions", "pam")):
        try:
            rows = conn.execute(
                f"""SELECT id, storage_error, storage_updated_at
                    FROM {table}
                    WHERE COALESCE(storage_status, 'LEGACY') = 'ERROR'
                    ORDER BY storage_updated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            errors.extend(
                {
                    "kind": kind,
                    "id": str(row["id"] or ""),
                    "message": str(row["storage_error"] or "Storage upload failed"),
                    "updated_at": str(row["storage_updated_at"] or ""),
                }
                for row in rows
            )
        except Exception:
            continue
    return sorted(errors, key=lambda item: item.get("updated_at", ""), reverse=True)[:limit]


@router.get("/status")
def get_storage_status(user=require_role("Viewer")):
    """Return sanitized provider health and object lifecycle counts."""

    purpose = "config_backup"
    profile = None
    storage_service = None
    backend = "unknown"
    endpoint = ""
    bucket = ""
    configuration_source = "unavailable"
    effective_default_id = None
    health_ok = False
    health_message = "Storage provider is not configured"
    try:
        _binding, profile = resolve_storage_usage(purpose)
        storage_service = build_storage_service(purpose=purpose)
        backend = storage_service.name
        endpoint = profile.endpoint_url if backend == "s3" else ""
        bucket = storage_service.bucket if backend == "s3" else ""
        configuration_source = profile.source
        effective_default_id = profile.id or ("environment" if profile.source == "environment" else None)
        health_ok, health_message = storage_service.health_check()
    except StorageError:
        health_message = "Storage usage configuration is unavailable"
    except Exception as exc:
        health_message = f"Storage check failed: {type(exc).__name__}"

    conn = get_db_connection()
    try:
        counts = _storage_counts(conn)
        recent_errors = _recent_errors(conn)
    finally:
        conn.close()

    degraded = not health_ok or counts["pending"] > 0 or counts["error"] > 0
    return {
        "backend": backend,
        "provider": "S3-compatible" if backend == "s3" else "Local filesystem",
        "endpoint": endpoint,
        "bucket": bucket,
        "status": "degraded" if degraded else "ready",
        "health_ok": health_ok,
        "health_message": health_message,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
        "recent_errors": recent_errors,
        "configuration_source": configuration_source,
        "effective_default_id": effective_default_id,
        "purpose": purpose,
    }


@router.get("/objects")
def list_storage_objects(
    provider_id: str | None = Query(default=None, max_length=128),
    prefix: str = Query(default="", max_length=512),
    delimiter: str = Query(default="/", max_length=1),
    continuation_token: str | None = Query(default=None, max_length=4096),
    page_size: int = Query(default=100, ge=1, le=1000),
    _user=require_role("Administrator"),
):
    """List one page of S3 object paths for an administrator-selected profile."""

    if "\x00" in prefix:
        raise HTTPException(status_code=422, detail="prefix is invalid")
    if delimiter not in {"", "/"}:
        raise HTTPException(status_code=422, detail="delimiter must be '/' or empty")
    try:
        profile = get_storage_provider_config(provider_id) if provider_id else effective_storage_provider()
        if profile.backend.strip().lower() != "s3":
            raise HTTPException(status_code=400, detail="Selected storage provider is not S3")
        service = _service_for_profile(profile)
        page = service.list_objects_page(
            prefix=prefix,
            delimiter=delimiter,
            continuation_token=continuation_token,
            max_keys=page_size,
        )
    except HTTPException:
        raise
    except StorageError as exc:
        message = str(exc)
        detail = "Storage provider could not be listed; verify its configuration and credentials."
        known_safe_errors = {
            "S3 endpoint is not configured": "The S3 endpoint is not configured.",
            "S3 bucket is not configured": "The S3 bucket is not configured.",
            "Storage provider credentials are not configured": "Storage credentials are not configured.",
            "Storage provider credentials could not be decrypted": "Storage credentials could not be decrypted; verify the server encryption key.",
            "Storage provider configuration was not found": "The selected storage profile was not found.",
        }
        if message in known_safe_errors:
            detail = known_safe_errors[message]
        else:
            match = re.fullmatch(
                r"S3 listing failed: ([A-Za-z0-9_.-]{1,64}(?: \(HTTP [1-5][0-9]{2}\))?|HTTP [1-5][0-9]{2}|[A-Za-z]+Error)",
                message,
            )
            if match:
                detail = f"S3 listing failed ({match.group(1)}); check endpoint connectivity, bucket access, and ListBucket permission."
        raise HTTPException(
            status_code=503,
            detail=detail,
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="S3 object listing is unavailable") from exc

    bucket = str(service.bucket or profile.bucket or "")
    return {
        "provider_id": profile.id or "environment",
        "provider_name": profile.name,
        "endpoint_url": profile.endpoint_url,
        "bucket": bucket,
        "items": [
            {
                "object_key": item.object_key,
                "s3_uri": f"s3://{bucket}/{item.object_key}",
                "size": item.size,
                "last_modified": item.last_modified,
            }
            for item in page.items
        ],
        "folders": list(page.common_prefixes),
        "next_continuation_token": page.next_continuation_token,
        "is_truncated": page.is_truncated,
    }


def _config_object_key(object_key: str) -> str:
    """Validate that a browser request targets a configuration snapshot object."""

    try:
        normalized = normalize_object_key(object_key)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="object_key is invalid") from exc
    basename = posixpath.basename(normalized)
    if not re.fullmatch(r".+\.cfg(?:\.(?:gz|enc))?", basename, flags=re.IGNORECASE):
        raise HTTPException(status_code=422, detail="Only configuration snapshot objects can be read")
    return normalized


def _config_download_filename(object_key: str) -> str:
    basename = posixpath.basename(object_key)
    basename = re.sub(r"\.(?:gz|enc)$", "", basename, flags=re.IGNORECASE)
    basename = re.sub(r"[^A-Za-z0-9._-]+", "_", basename).strip("._-") or "config_snapshot"
    if not basename.lower().endswith(".cfg"):
        basename = f"{basename}.cfg"
    if len(basename) > 180:
        basename = f"{basename[:176].rstrip('._-')}.cfg"
    return basename


@router.get("/objects/content")
def get_storage_object_content(
    provider_id: str | None = Query(default=None, max_length=128),
    object_key: str = Query(..., min_length=1, max_length=1024),
    download: bool = Query(default=False),
    _user=require_role("Administrator"),
):
    """Read a configuration snapshot object as text for the storage browser."""

    normalized_key = _config_object_key(object_key)
    try:
        profile = get_storage_provider_config(provider_id) if provider_id else effective_storage_provider()
        if profile.backend.strip().lower() != "s3":
            raise HTTPException(status_code=400, detail="Selected storage provider is not S3")
        service = _service_for_profile(profile)
        stream = service.get_stream(normalized_key)
        try:
            payload = stream.read()
        finally:
            stream.close()
    except HTTPException:
        raise
    except StorageNotFound as exc:
        raise HTTPException(status_code=404, detail="Configuration object not found") from exc
    except StorageError as exc:
        raise HTTPException(status_code=503, detail="Configuration object is unavailable") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Configuration object is unavailable") from exc

    try:
        content = deserialize_config_bytes(payload)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Configuration object content is invalid") from exc

    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if download:
        headers["Content-Disposition"] = (
            f'attachment; filename="{_config_download_filename(normalized_key)}"'
        )
    return Response(content=content, media_type="text/plain", headers=headers)


__all__ = ["router"]
