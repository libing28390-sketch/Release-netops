"""Storage helpers shared by configuration backup, diff, and search code."""

from __future__ import annotations

import gzip
import io
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import PROJECT_ROOT, settings
from database import get_db_connection
from services.storage_service import (
    StorageError,
    StorageNotFound,
    StorageObject,
    StorageService,
    build_storage_service,
    normalize_object_key,
)


LEGACY_BACKUP_ROOT = os.path.join(PROJECT_ROOT, "backup")
CONFIG_CONTENT_TYPE = "application/octet-stream"
logger = logging.getLogger(__name__)


def _legacy_root() -> str:
    # The compatibility API historically exposed ``api.configs.BACKUP_ROOT``
    # and tests/installations may override it.  New providers never use this
    # path; legacy reads retain that override without introducing a provider
    # fallback.
    try:
        from api import configs as configs_api

        return str(getattr(configs_api, "BACKUP_ROOT", LEGACY_BACKUP_ROOT))
    except Exception:
        return LEGACY_BACKUP_ROOT


def _fernet():
    from core.crypto import _get_fernet

    return _get_fernet()


def serialize_config_content(content: str) -> bytes:
    """Compress and encrypt a local-provider config snapshot."""

    compressed = gzip.compress(str(content or "").encode("utf-8"))
    return b"ENCRYPTED:" + _fernet().encrypt(compressed)


def serialize_s3_config_content(content: str) -> bytes:
    """Return a new S3-backed config snapshot as readable UTF-8 bytes.

    Historical S3 objects may still be gzip-compressed; ``deserialize_config_bytes``
    intentionally keeps accepting that representation.
    """

    return str(content or "").encode("utf-8")


def deserialize_config_bytes(data: bytes) -> str:
    payload = bytes(data or b"")
    if payload.startswith(b"ENCRYPTED:"):
        payload = _fernet().decrypt(payload[len(b"ENCRYPTED:") :])
    if payload[:2] == b"\x1f\x8b":
        payload = gzip.decompress(payload)
    return payload.decode("utf-8", errors="replace")


def legacy_path(file_path: str) -> str:
    normalized = str(file_path or "").replace("/", os.sep).replace("\\", os.sep)
    root = os.path.abspath(_legacy_root())
    absolute = os.path.abspath(os.path.join(root, normalized))
    if os.path.commonpath((root, absolute)) != root:
        raise ValueError("Legacy config path escapes the backup root")
    return absolute


def read_legacy_bytes(file_path: str) -> bytes:
    absolute = legacy_path(file_path)
    try:
        with open(absolute, "rb") as handle:
            return handle.read()
    except FileNotFoundError:
        return b""


def read_legacy_content(file_path: str) -> str:
    data = read_legacy_bytes(file_path)
    if not data:
        return ""
    try:
        return deserialize_config_bytes(data)
    except Exception:
        return ""


def delete_legacy_file(file_path: str) -> None:
    absolute = legacy_path(file_path)
    if os.path.exists(absolute):
        os.remove(absolute)
    parent = os.path.dirname(absolute)
    root = os.path.abspath(_legacy_root())
    while parent != root:
        try:
            os.rmdir(parent)
        except OSError:
            break
        parent = os.path.dirname(parent)


def object_key_for_snapshot(
    snapshot_id: str,
    timestamp: datetime,
    config_type: str = "running",
    *,
    vendor: str = "",
    hostname: str = "",
    trigger: str = "",
    encrypted: bool = True,
) -> str:
    extension = ".cfg.enc" if encrypted else ".cfg"

    def segment(value: object, fallback: str) -> str:
        safe = re.sub(r"[^\w.-]+", "_", str(value or "").strip(), flags=re.UNICODE).strip("._-")
        return safe[:128] or fallback

    vendor_segment = segment(vendor, "Unknown")
    hostname_segment = segment(hostname, "device")
    trigger_segment = segment(trigger, "manual")
    snapshot_segment = segment(snapshot_id, "snapshot")
    if str(config_type or "running").strip().lower() == "startup":
        snapshot_segment = f"{snapshot_segment}_startup"
    return normalize_object_key(
        f"{timestamp:%Y/%m/%d}/{vendor_segment}/"
        f"{hostname_segment}_{timestamp:%H%M%S}_{trigger_segment}_{snapshot_segment}{extension}"
    )


def config_spool_path(
    snapshot_id: str,
    config_type: str = "running",
    *,
    encrypted: bool = True,
) -> Path:
    suffix = "_startup" if str(config_type or "running") == "startup" else ""
    extension = ".cfg.enc" if encrypted else ".cfg"
    directory = Path(settings.STORAGE_SPOOL_ROOT).expanduser().resolve() / "config"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{str(snapshot_id)}{suffix}{extension}"


def write_config_spool(
    snapshot_id: str,
    content: str,
    config_type: str = "running",
    *,
    encrypted: bool = True,
) -> Path:
    destination = config_spool_path(snapshot_id, config_type, encrypted=encrypted)
    temporary = destination.with_name(f".{destination.name}.uploading")
    payload = serialize_config_content(content) if encrypted else serialize_s3_config_content(content)
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return destination


def provider_for_row(row: Any) -> StorageService:
    def value(name: str, default: Any = ""):
        if isinstance(row, dict):
            return row.get(name, default)
        try:
            return row[name]
        except (KeyError, IndexError, TypeError):
            return default

    backend_name = str(value("storage_backend") or "").strip().lower()
    bucket = value("storage_bucket") or ""
    provider_id = str(value("storage_config_id") or "").strip()
    if provider_id:
        return build_storage_service(storage_config_id=provider_id, bucket=str(bucket or ""))
    # Rows created before provider profiles existed retain their environment
    # S3 credentials and endpoint.  The explicit backend/bucket also keeps
    # legacy local rows readable.
    return build_storage_service(
        backend_name=backend_name or None,
        bucket=str(bucket or "") or None,
    )


def read_snapshot_content(row: Any, *, strict_storage_errors: bool = False) -> str:
    """Read a new object-backed snapshot or an explicitly legacy row.

    Internal analytics callers may keep the historical empty-string behavior.
    User-facing content/download endpoints can request strict mode so storage
    failures remain distinguishable from empty or missing config content.
    """

    def value(name: str, default: Any = ""):
        if isinstance(row, dict):
            return row.get(name, default)
        try:
            return row[name]
        except (KeyError, IndexError, TypeError):
            return default

    object_key = str(value("object_key") or "").strip()
    storage_status = str(value("storage_status", "LEGACY") or "LEGACY").strip().upper()
    if object_key and storage_status in {"READY", "UPLOADING", "PENDING"}:
        try:
            service = provider_for_row(row)
            stream = service.get_stream(object_key)
            try:
                return deserialize_config_bytes(stream.read())
            finally:
                stream.close()
        except StorageError as exc:
            # A READY object is authoritative.  Do not silently read a stale
            # local mirror when the configured provider reports an error. Log
            # the sanitized storage error so an operator can distinguish a
            # missing object from an unavailable or misconfigured bucket.
            logger.warning(
                "[Storage] Config snapshot %s object read failed: %s",
                str(value("id") or "unknown"),
                str(exc),
            )
            if strict_storage_errors:
                raise
            return ""
        except (OSError, ValueError) as exc:
            logger.warning(
                "[Storage] Config snapshot %s object read failed: %s",
                str(value("id") or "unknown"),
                type(exc).__name__,
            )
            return ""
    return read_legacy_content(str(value("file_path") or ""))


def put_snapshot_content(
    *,
    snapshot_id: str,
    timestamp: datetime,
    content: str,
    config_type: str = "running",
    vendor: str = "",
    hostname: str = "",
    trigger: str = "",
    service: StorageService | None = None,
) -> StorageObject:
    storage = service or build_storage_service(purpose="config_backup")
    encrypted = storage.name != "s3"
    key = object_key_for_snapshot(
        snapshot_id,
        timestamp,
        config_type,
        vendor=vendor,
        hostname=hostname,
        trigger=trigger,
        encrypted=encrypted,
    )
    payload = serialize_config_content(content) if encrypted else serialize_s3_config_content(content)
    return storage.put_stream(key, io.BytesIO(payload), CONFIG_CONTENT_TYPE)


def put_legacy_snapshot(
    *,
    snapshot_id: str,
    file_path: str,
    service: StorageService | None = None,
) -> StorageObject:
    """Upload an existing encrypted legacy file without decrypting it."""

    payload = read_legacy_bytes(file_path)
    if not payload:
        raise StorageNotFound(file_path)
    storage = service or build_storage_service(purpose="config_backup")
    key = normalize_object_key(f"legacy/{snapshot_id}.cfg.enc")
    return storage.put_stream(key, io.BytesIO(payload), CONFIG_CONTENT_TYPE)


def delete_snapshot_object(row: Any) -> None:
    def value(name: str, default: Any = ""):
        if isinstance(row, dict):
            return row.get(name, default)
        try:
            return row[name]
        except (KeyError, IndexError, TypeError):
            return default

    object_key = str(value("object_key") or "").strip()
    storage_status = str(value("storage_status", "LEGACY") or "LEGACY").strip().upper()
    if object_key and storage_status in {"READY", "UPLOADING", "PENDING", "ERROR"}:
        provider_for_row(row).delete(object_key)
        return
    file_path = str(value("file_path") or "")
    if file_path:
        delete_legacy_file(file_path)


def retry_pending_config_snapshots(limit: int = 50) -> dict[str, int]:
    """Retry explicitly spooled configuration objects; never changes provider."""

    conn = get_db_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM config_snapshots
               WHERE storage_status = 'ERROR' AND storage_spool_path <> ''
               ORDER BY timestamp ASC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    finally:
        conn.close()
    result = {"attempted": 0, "succeeded": 0, "failed": 0}
    for row in rows:
        result["attempted"] += 1
        spool = Path(str(row["storage_spool_path"] or ""))
        if not spool.is_file():
            result["failed"] += 1
            continue
        try:
            provider_id = str(row["storage_config_id"] or "").strip()
            if provider_id:
                # A usage can override the profile's default bucket.  Failed
                # rows keep the effective bucket, so retries must stay bound
                # to that bucket along with the provider and full object key.
                service = build_storage_service(
                    storage_config_id=provider_id,
                    bucket=str(row["storage_bucket"] or "").strip() or None,
                )
            else:
                # Rows created before provider IDs existed remain bound to the
                # deployment environment (and their recorded bucket), even if
                # the database default has changed since the failed upload.
                service = build_storage_service(
                    backend_name=str(row["storage_backend"] or "").strip().lower() or None,
                    bucket=str(row["storage_bucket"] or "").strip() or None,
                )
            key = str(row["object_key"] or object_key_for_snapshot(
                row["id"],
                datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00")),
                row["config_type"] or "running",
                vendor=row["vendor"] or "",
                hostname=row["hostname"] or "",
                trigger=row["trigger"] or "",
                encrypted=service.name != "s3",
            ))
            with spool.open("rb") as handle:
                stored = service.put_stream(key, handle, CONFIG_CONTENT_TYPE)
            conn = get_db_connection()
            try:
                conn.execute(
                    """UPDATE config_snapshots
                       SET storage_backend=?, storage_config_id=?, storage_bucket=?, object_key=?, object_version_id=?,
                           object_size=?, object_sha256=?, content_type=?, storage_status='READY',
                           storage_error='', storage_spool_path='', storage_updated_at=?
                       WHERE id=?""",
                    (
                        stored.backend, getattr(stored, "storage_config_id", None), stored.bucket or "", stored.object_key, stored.version_id or "",
                        stored.size, stored.sha256 or "", stored.content_type or CONFIG_CONTENT_TYPE,
                        datetime.now().astimezone().isoformat(), row["id"],
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            try:
                spool.unlink()
            except FileNotFoundError:
                pass
            result["succeeded"] += 1
        except Exception:
            result["failed"] += 1
    return result


__all__ = [
    "CONFIG_CONTENT_TYPE",
    "LEGACY_BACKUP_ROOT",
    "delete_legacy_file",
    "delete_snapshot_object",
    "deserialize_config_bytes",
    "legacy_path",
    "object_key_for_snapshot",
    "put_legacy_snapshot",
    "put_snapshot_content",
    "read_legacy_bytes",
    "read_legacy_content",
    "read_snapshot_content",
    "config_spool_path",
    "retry_pending_config_snapshots",
    "serialize_config_content",
    "serialize_s3_config_content",
    "write_config_spool",
]
