"""Storage helpers shared by configuration backup, diff, and search code."""

from __future__ import annotations

import gzip
import io
import os
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
    compressed = gzip.compress(str(content or "").encode("utf-8"))
    return b"ENCRYPTED:" + _fernet().encrypt(compressed)


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


def object_key_for_snapshot(snapshot_id: str, timestamp: datetime, config_type: str = "running") -> str:
    suffix = "_startup" if str(config_type or "running") == "startup" else ""
    return normalize_object_key(
        f"config/{timestamp:%Y/%m}/{snapshot_id}{suffix}.cfg.enc"
    )


def config_spool_path(snapshot_id: str, config_type: str = "running") -> Path:
    suffix = "_startup" if str(config_type or "running") == "startup" else ""
    directory = Path(settings.STORAGE_SPOOL_ROOT).expanduser().resolve() / "config"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{str(snapshot_id)}{suffix}.cfg.enc"


def write_config_spool(snapshot_id: str, content: str, config_type: str = "running") -> Path:
    destination = config_spool_path(snapshot_id, config_type)
    temporary = destination.with_name(f".{destination.name}.uploading")
    payload = serialize_config_content(content)
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
    if not backend_name:
        backend_name = "local"
    bucket = value("storage_bucket") or ""
    return build_storage_service(backend_name=backend_name, bucket=str(bucket or ""))


def read_snapshot_content(row: Any) -> str:
    """Read a new object-backed snapshot or an explicitly legacy row."""

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
        except (StorageError, OSError, ValueError):
            # A READY object is authoritative.  Do not silently read a stale
            # local mirror when the configured provider reports an error.
            return ""
    return read_legacy_content(str(value("file_path") or ""))


def put_snapshot_content(
    *,
    snapshot_id: str,
    timestamp: datetime,
    content: str,
    config_type: str = "running",
    service: StorageService | None = None,
) -> StorageObject:
    storage = service or build_storage_service()
    key = object_key_for_snapshot(snapshot_id, timestamp, config_type)
    payload = serialize_config_content(content)
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
    storage = service or build_storage_service()
    key = normalize_object_key(f"config/legacy/{snapshot_id}.cfg.enc")
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
            service = build_storage_service()
            key = str(row["object_key"] or object_key_for_snapshot(
                row["id"], datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00")), row["config_type"] or "running"
            ))
            with spool.open("rb") as handle:
                stored = service.put_stream(key, handle, CONFIG_CONTENT_TYPE)
            conn = get_db_connection()
            try:
                conn.execute(
                    """UPDATE config_snapshots
                       SET storage_backend=?, storage_bucket=?, object_key=?, object_version_id=?,
                           object_size=?, object_sha256=?, content_type=?, storage_status='READY',
                           storage_error='', storage_spool_path='', storage_updated_at=?
                       WHERE id=?""",
                    (
                        stored.backend, stored.bucket or "", stored.object_key, stored.version_id or "",
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
    "write_config_spool",
]
