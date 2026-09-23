"""Read-only storage provider status for the operations UI."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from core.config import settings
from core.rbac import require_role
from database import get_db_connection
from services.storage_service import StorageError, build_storage_service


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

    backend = str(settings.STORAGE_BACKEND or "local").strip().lower()
    endpoint = settings.S3_ENDPOINT_URL if backend == "s3" else ""
    bucket = settings.S3_BUCKET if backend == "s3" else ""
    health_ok = False
    health_message = "Storage provider is not configured"
    try:
        health_ok, health_message = build_storage_service().health_check()
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
        "configuration_source": "environment",
    }


__all__ = ["router"]
