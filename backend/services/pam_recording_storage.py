"""PAM recording spool, finalization, retry, and retention helpers."""

from __future__ import annotations

import logging
import os
import shutil
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import settings
from database import get_db_connection
from services.storage_service import (
    StorageError,
    StorageNotFound,
    StorageService,
    build_storage_service,
    normalize_object_key,
)


logger = logging.getLogger(__name__)

# Upload failures from the current thread, so the scheduled retry can tell a
# provider outage (DNS/connect/timeout) from a per-recording failure.
_upload_failure = threading.local()

# Retry circuit breaker. When the object store cannot be reached at all, every
# queued recording fails the same way: retrying 50 of them each minute only
# burns ~85 s of DNS/connect timeouts and a scheduler thread. After a
# connectivity failure the job stops the batch and waits with exponential
# backoff (2 min, doubling, capped at 30 min) before probing again.
_RETRY_BACKOFF_BASE_SECONDS = 120.0
_RETRY_BACKOFF_MAX_SECONDS = 1800.0
_retry_breaker_lock = threading.Lock()
_retry_breaker = {"open_until": 0.0, "delay": 0.0, "reason": ""}

_CONNECTIVITY_ERROR_NAMES = {
    "EndpointConnectionError",
    "ConnectTimeoutError",
    "ReadTimeoutError",
    "ConnectionClosedError",
    "ProxyConnectionError",
    "SSLError",
    "NewConnectionError",
    "MaxRetryError",
    "gaierror",
    "ConnectionError",
    "ConnectionRefusedError",
    "TimeoutError",
}


def _is_connectivity_failure(exc: BaseException | None) -> bool:
    """True when the provider itself is unreachable (not a bad recording)."""
    seen = 0
    while exc is not None and seen < 8:
        if isinstance(exc, (socket.gaierror, ConnectionError, TimeoutError)):
            return True
        if type(exc).__name__ in _CONNECTIVITY_ERROR_NAMES:
            return True
        message = str(exc)
        if any(name in message for name in _CONNECTIVITY_ERROR_NAMES):
            return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False


def _remember_upload_failure(exc: BaseException | None) -> None:
    _upload_failure.exc = exc


RECORDING_CONTENT_TYPES = {
    ".cast": "application/octet-stream",
    ".gif": "image/gif",
    ".apng": "image/apng",
    ".mp4": "video/mp4",
    ".zip": "application/zip",
    ".guac": "application/octet-stream",
}


def recording_content_type(suffix: str) -> str:
    return RECORDING_CONTENT_TYPES.get(str(suffix or "").lower(), "application/octet-stream")


def _safe_id(session_id: str) -> str:
    safe = "".join(char for char in str(session_id or "") if char.isalnum() or char in {"-", "_"})[:100]
    if not safe:
        raise ValueError("Invalid PAM session id")
    return safe


def recording_spool_path(session_id: str, suffix: str = ".cast") -> Path:
    safe = _safe_id(session_id)
    normalized_suffix = str(suffix or ".cast").lower()
    if not normalized_suffix.startswith(".") or normalized_suffix not in RECORDING_CONTENT_TYPES:
        raise ValueError("Unsupported PAM recording suffix")
    directory = Path(settings.STORAGE_SPOOL_ROOT).expanduser().resolve() / "pam"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{safe}{normalized_suffix}"


def recording_object_key(session_id: str, created_at: object, suffix: str) -> str:
    safe = _safe_id(session_id)
    try:
        parsed = datetime.fromisoformat(str(created_at or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        parsed = datetime.now(timezone.utc)
    return normalize_object_key(f"{parsed:%Y/%m}/{safe}{str(suffix).lower()}")


def _row_value(row: Any, name: str, default: Any = "") -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(name, default)
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return default


def _is_stable_guac_file(path: Path) -> bool:
    """Require a closed, non-empty, stable native Guacamole recording."""
    if path.is_symlink() or not path.is_file():
        return False
    previous: tuple[int, int] | None = None
    stable = 0
    for _ in range(3):
        try:
            stat = path.stat()
        except OSError:
            return False
        current = (int(stat.st_size), int(stat.st_mtime_ns))
        if stat.st_size <= 0:
            return False
        if current == previous:
            stable += 1
        else:
            stable = 0
        previous = current
        if stable >= 1:
            return True
        time.sleep(0.2)
    return False


def _mark_storage_error(
    session_id: str,
    message: str,
    *,
    service: StorageService | None = None,
    object_key: str | None = None,
) -> None:
    conn = get_db_connection()
    try:
        if service is not None:
            conn.execute(
                """UPDATE pam_sessions
                   SET storage_backend = ?, storage_config_id = ?, storage_bucket = ?, object_key = ?,
                       storage_status = 'ERROR', storage_error = ?, storage_updated_at = ?
                   WHERE id = ?""",
                (
                    service.name,
                    service.storage_config_id,
                    service.bucket or None,
                    object_key or None,
                    str(message or "storage error")[:2000],
                    datetime.now(timezone.utc).isoformat(),
                    session_id,
                ),
            )
        else:
            conn.execute(
                """UPDATE pam_sessions
                   SET storage_status = 'ERROR', storage_error = ?, storage_updated_at = ?
                   WHERE id = ?""",
                (str(message or "storage error")[:2000], datetime.now(timezone.utc).isoformat(), session_id),
            )
        conn.commit()
    finally:
        conn.close()


def finalize_pam_recording(
    session_id: str,
    spool_path: str | os.PathLike[str],
    *,
    content_type: str | None = None,
    legacy_path: str | None = None,
) -> bool:
    """Upload one completed spool and atomically publish its metadata.

    The spool remains available when the provider is unavailable.  The caller
    or the scheduled retry job can invoke this function again safely because
    the object key is deterministic per session and suffix.
    """

    path = Path(spool_path)
    if not path.is_file():
        _mark_storage_error(session_id, "PAM recording spool is missing")
        return False

    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM pam_sessions WHERE id = ?", (session_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return False

    suffix = path.suffix.lower() or ".cast"
    if suffix == ".guac":
        if (
            str(_row_value(row, "session_kind") or "") != "remote_desktop"
            or not bool(_row_value(row, "remote_desktop_recording_closed", False))
        ):
            return False
        if not _is_stable_guac_file(path):
            if path.exists() and path.stat().st_size <= 0:
                conn = get_db_connection()
                try:
                    conn.execute(
                        """UPDATE pam_sessions
                              SET recording_spool_path = '', recording_status = 'unavailable',
                                  storage_status = 'ERROR', storage_error = 'Completed .guac recording is empty',
                                  storage_updated_at = ?
                            WHERE id = ? AND session_kind = 'remote_desktop'""",
                        (datetime.now(timezone.utc).isoformat(), session_id),
                    )
                    conn.commit()
                finally:
                    conn.close()
            return False
    existing_key = str(_row_value(row, "object_key") or "").strip()
    existing_status = str(_row_value(row, "storage_status", "LEGACY") or "LEGACY").upper()
    provider_id = str(_row_value(row, "storage_config_id", "") or "").strip()
    service: StorageService | None = None
    try:
        if existing_key and existing_status in {"ERROR", "PENDING", "UPLOADING", "READY"}:
            backend_name = str(_row_value(row, "storage_backend", "") or "").strip().lower()
            bucket = str(_row_value(row, "storage_bucket", "") or "").strip() or None
            if provider_id:
                service = build_storage_service(storage_config_id=provider_id, bucket=bucket)
            else:
                service = build_storage_service(backend_name=backend_name or None, bucket=bucket)
            key = existing_key
            upload_key = key
        else:
            service = build_storage_service(purpose="pam_recording")
            upload_key = recording_object_key(session_id, _row_value(row, "created_at"), suffix)
            key = service.full_key(upload_key)
    except Exception as exc:
        _remember_upload_failure(exc)
        _mark_storage_error(
            session_id,
            f"{type(exc).__name__}: recording upload failed",
            service=service,
            object_key=existing_key or None,
        )
        return False
    try:
        with path.open("rb") as handle:
            stored = service.put_stream(upload_key, handle, content_type or recording_content_type(suffix))
        if stored.size != path.stat().st_size:
            raise StorageError("PAM recording size verification failed")
        conn = get_db_connection()
        try:
            conn.execute(
                """UPDATE pam_sessions
                       SET recording_spool_path = '', recording_path = ?,
                       storage_backend = ?, storage_config_id = ?, storage_bucket = ?, object_key = ?,
                       object_version_id = ?, object_size = ?, object_sha256 = ?,
                       content_type = ?, storage_status = 'READY', storage_error = '',
                       storage_updated_at = ?, recording_status = 'uploaded', updated_at = ?
                   WHERE id = ?""",
                (
                    legacy_path or '',
                    stored.backend,
                    getattr(stored, "storage_config_id", None),
                    stored.bucket or "",
                    stored.object_key,
                    stored.version_id or "",
                    stored.size,
                    stored.sha256 or "",
                    stored.content_type or content_type or recording_content_type(suffix),
                    datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                    session_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        if not legacy_path:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        return True
    except Exception as exc:
        _remember_upload_failure(exc)
        _mark_storage_error(
            session_id,
            f"{type(exc).__name__}: recording upload failed",
            service=service,
            object_key=key,
        )
        return False


def pam_recording_retry_backoff_status() -> dict[str, Any]:
    """Expose the retry circuit breaker state for diagnostics."""
    with _retry_breaker_lock:
        remaining = max(0.0, _retry_breaker["open_until"] - time.monotonic())
        return {
            "deferred": remaining > 0,
            "retry_in_seconds": int(remaining),
            "backoff_seconds": int(_retry_breaker["delay"]),
            "reason": _retry_breaker["reason"],
        }


def retry_pending_pam_recordings(limit: int = 50, *, ignore_backoff: bool = False) -> dict[str, int]:
    result = {"attempted": 0, "succeeded": 0, "failed": 0, "deferred": 0}
    if not ignore_backoff:
        with _retry_breaker_lock:
            if time.monotonic() < _retry_breaker["open_until"]:
                result["deferred"] = 1
                return result
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """SELECT id, recording_spool_path, content_type
               FROM pam_sessions
               WHERE recording_spool_path <> ''
                 AND storage_status IN ('PENDING', 'ERROR')
                 AND (session_kind <> 'remote_desktop'
                      OR (remote_desktop_protocol <> '' AND remote_desktop_recording_closed = TRUE))
               ORDER BY storage_updated_at ASC NULLS FIRST, created_at ASC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        result["attempted"] += 1
        _remember_upload_failure(None)
        if finalize_pam_recording(row["id"], row["recording_spool_path"], content_type=row["content_type"] or None):
            result["succeeded"] += 1
            with _retry_breaker_lock:
                _retry_breaker.update(open_until=0.0, delay=0.0, reason="")
            continue
        result["failed"] += 1
        failure = getattr(_upload_failure, "exc", None)
        if _is_connectivity_failure(failure):
            with _retry_breaker_lock:
                delay = min(
                    max(_retry_breaker["delay"] * 2, _RETRY_BACKOFF_BASE_SECONDS),
                    _RETRY_BACKOFF_MAX_SECONDS,
                )
                _retry_breaker.update(
                    open_until=time.monotonic() + delay,
                    delay=delay,
                    reason=type(failure).__name__,
                )
            remaining = max(0, len(rows) - result["attempted"])
            logger.warning(
                "[PAM Storage] Object storage is unreachable (%s); stopped this retry batch "
                "(%s more recordings left queued) and will retry in %ds. Check the default "
                "storage provider endpoint under Management > Storage.",
                type(failure).__name__, remaining, int(delay),
            )
            break
    return result


def delete_pam_recording(row: Any) -> None:
    """Delete a final object and/or spool for retention cleanup."""

    spool = str(_row_value(row, "recording_spool_path") or "")
    if spool:
        try:
            Path(spool).unlink()
        except FileNotFoundError:
            pass
    key = str(_row_value(row, "object_key") or "")
    status = str(_row_value(row, "storage_status", "LEGACY") or "LEGACY").upper()
    if key and status in {"READY", "ERROR", "PENDING", "UPLOADING"}:
        provider_id = str(_row_value(row, "storage_config_id", "") or "").strip()
        backend_name = str(_row_value(row, "storage_backend", "") or "").strip().lower()
        bucket = str(_row_value(row, "storage_bucket", "") or "")
        if provider_id:
            build_storage_service(storage_config_id=provider_id, bucket=bucket or None).delete(key)
        else:
            build_storage_service(backend_name=backend_name or None, bucket=bucket or None).delete(key)
    legacy_path = str(_row_value(row, "recording_path") or "")
    if legacy_path:
        try:
            Path(legacy_path).unlink()
        except FileNotFoundError:
            pass


__all__ = [
    "RECORDING_CONTENT_TYPES",
    "delete_pam_recording",
    "pam_recording_retry_backoff_status",
    "finalize_pam_recording",
    "recording_content_type",
    "recording_object_key",
    "recording_spool_path",
    "retry_pending_pam_recordings",
]
