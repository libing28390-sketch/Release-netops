"""Administrative controls for the VictoriaMetrics disk safety threshold."""

from __future__ import annotations

import logging
import json
import os
import re
import secrets
import stat
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.rbac import require_role


router = APIRouter(prefix="/monitoring", tags=["Monitoring storage"])
logger = logging.getLogger(__name__)

_DEFAULT_MIN_FREE_BYTES = 10 * 1024**3
_MIN_FREE_BYTES = 512 * 1024**2
_MAX_FREE_BYTES = 16 * 1024**4
_RUNTIME_CONFIG_NAME = "min-free-disk-space-bytes"
_RUNTIME_ACTIVE_NAME = "active-min-free-disk-space-bytes"
_RUNTIME_STATE_NAME = "runtime-state"
_RUNTIME_ERROR_NAME = "runtime-error-code"
_RUNTIME_RESTARTED_NAME = "last-restart-at"
_RUNTIME_ENV_SYNC_REQUEST_NAME = "env-sync-request"
_RUNTIME_ENV_SYNC_TRIGGER_NAME = "env-sync-trigger"
_RUNTIME_ENV_SYNC_STATUS_NAME = "env-sync-status"
_RUNTIME_ENV_SYNC_READY_NAME = "env-sync-ready"
_INTEGER_PATTERN = re.compile(r"^[0-9]{1,20}$")
_REQUEST_ID_PATTERN = re.compile(r"^[a-f0-9]{24}$")
_ENV_SYNC_REQUEST_TTL_SECONDS = 10.0
_ENV_SYNC_TIMEOUT_SECONDS = 15.0


class StorageProtectionUpdate(BaseModel):
    min_free_disk_space_bytes: int = Field(ge=_MIN_FREE_BYTES, le=_MAX_FREE_BYTES)


def _runtime_directory() -> Path | None:
    configured = os.environ.get("MONITORING_VM_RUNTIME_DIR", "").strip()
    return Path(configured) if configured else None


def _read_bounded_integer(path: Path | None) -> int | None:
    if path is None:
        return None
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (FileNotFoundError, OSError, UnicodeError):
        return None
    if not lines:
        return None
    raw = lines[0].strip()
    if not _INTEGER_PATTERN.fullmatch(raw):
        return None
    value = int(raw)
    return value if _MIN_FREE_BYTES <= value <= _MAX_FREE_BYTES else None


def _read_text(path: Path | None, default: str = "") -> str:
    if path is None:
        return default
    try:
        return path.read_text(encoding="ascii").strip()[:128]
    except (FileNotFoundError, OSError, UnicodeError):
        return default


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="ascii"))
    except (FileNotFoundError, OSError, UnicodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _request_id(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (FileNotFoundError, OSError, UnicodeError):
        return None
    if len(lines) < 2 or not _REQUEST_ID_PATTERN.fullmatch(lines[1]):
        return None
    return lines[1]


def _settings_payload(directory: Path | None) -> dict[str, Any]:
    fallback = _DEFAULT_MIN_FREE_BYTES
    raw_fallback = os.environ.get("VM_MIN_FREE_DISK_SPACE_BYTES", "").strip()
    if _INTEGER_PATTERN.fullmatch(raw_fallback):
        parsed_fallback = int(raw_fallback)
        if _MIN_FREE_BYTES <= parsed_fallback <= _MAX_FREE_BYTES:
            fallback = parsed_fallback

    requested = _read_bounded_integer(directory / _RUNTIME_CONFIG_NAME if directory else None) or fallback
    active = _read_bounded_integer(directory / _RUNTIME_ACTIVE_NAME if directory else None)
    state = _read_text(directory / _RUNTIME_STATE_NAME if directory else None, "STARTING" if directory else "UNMANAGED")
    error_code = _read_text(directory / _RUNTIME_ERROR_NAME if directory else None)
    restarted_at = _read_text(directory / _RUNTIME_RESTARTED_NAME if directory else None)
    current_request_id = _request_id(directory / _RUNTIME_CONFIG_NAME if directory else None)
    pending_request_id = _request_id(directory / _RUNTIME_ENV_SYNC_REQUEST_NAME if directory else None)
    sync_ready = _read_text(directory / _RUNTIME_ENV_SYNC_READY_NAME if directory else None) == "READY"
    sync_status = _read_json(directory / _RUNTIME_ENV_SYNC_STATUS_NAME if directory else None)
    status_request_id = str(sync_status.get("request_id") or "")
    sync_request_id = current_request_id
    sync_state = "UNAVAILABLE"
    sync_error_code = None
    if sync_ready:
        if pending_request_id and pending_request_id != current_request_id:
            sync_request_id = pending_request_id
        if sync_request_id is None:
            sync_state = "SYNCED"
        elif status_request_id == sync_request_id:
            candidate_state = str(sync_status.get("state") or "PENDING").upper()
            sync_state = candidate_state if candidate_state in {"SYNCED", "FAILED"} else "PENDING"
            if sync_state == "FAILED":
                candidate_error = str(sync_status.get("error_code") or "")
                sync_error_code = candidate_error if re.fullmatch(r"[A-Z0-9_]{1,64}", candidate_error) else "UNKNOWN"
        else:
            sync_state = "PENDING"
    return {
        "managed": directory is not None,
        "min_free_disk_space_bytes": requested,
        "active_min_free_disk_space_bytes": active,
        "runtime_state": state,
        "runtime_error_code": error_code or None,
        "last_restart_at": restarted_at or None,
        "env_sync_ready": sync_ready,
        "env_sync_state": sync_state,
        "env_sync_request_id": sync_request_id,
        "env_sync_error_code": sync_error_code,
    }


@router.get("/storage-protection")
def get_storage_protection(_user=require_role("Viewer")):
    return _settings_payload(_runtime_directory())


@router.put("/storage-protection")
def update_storage_protection(body: StorageProtectionUpdate, user=require_role("Administrator")):
    directory = _runtime_directory()
    if directory is None:
        raise HTTPException(
            status_code=503,
            detail="VictoriaMetrics runtime configuration is unavailable in this deployment",
        )

    if _read_text(directory / _RUNTIME_ENV_SYNC_READY_NAME) != "READY":
        raise HTTPException(
            status_code=503,
            detail="Host .env synchronization is not installed; run the Docker-host installer before changing this setting.",
        )

    temporary_path: Path | None = None
    request_id = secrets.token_hex(12)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="ascii",
            dir=directory,
            prefix=f".{_RUNTIME_CONFIG_NAME}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            expires_at = time.time() + _ENV_SYNC_REQUEST_TTL_SECONDS
            temporary.write(f"{body.min_free_disk_space_bytes}\n{request_id}\n{expires_at:.6f}\n")
        os.replace(temporary_path, directory / _RUNTIME_ENV_SYNC_REQUEST_NAME)

        trigger_path = directory / _RUNTIME_ENV_SYNC_TRIGGER_NAME
        trigger_flags = os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        trigger_fd = os.open(trigger_path, trigger_flags)
        if not stat.S_ISREG(os.fstat(trigger_fd).st_mode):
            os.close(trigger_fd)
            raise OSError("host sync trigger is unavailable")
        with os.fdopen(trigger_fd, "w", encoding="ascii") as trigger:
            trigger.write(f"{request_id}\n")
            trigger.flush()
            os.fsync(trigger.fileno())
    except OSError as exc:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            request_path = directory / _RUNTIME_ENV_SYNC_REQUEST_NAME
            if _request_id(request_path) == request_id:
                request_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(
            status_code=503,
            detail="The host .env synchronization request could not be submitted",
        ) from exc

    deadline = time.monotonic() + _ENV_SYNC_TIMEOUT_SECONDS
    sync_status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        sync_status = _read_json(directory / _RUNTIME_ENV_SYNC_STATUS_NAME)
        if sync_status.get("request_id") == request_id:
            if sync_status.get("state") == "SYNCED":
                break
            if sync_status.get("state") == "FAILED":
                error_code = str(sync_status.get("error_code") or "UNKNOWN")
                if not re.fullmatch(r"[A-Z0-9_]{1,64}", error_code):
                    error_code = "UNKNOWN"
                raise HTTPException(
                    status_code=503,
                    detail=f"Host .env synchronization failed ({error_code}); the runtime threshold was not applied.",
                )
        time.sleep(0.2)
    else:
        raise HTTPException(
            status_code=503,
            detail="Host .env synchronization did not complete; the runtime threshold was not applied.",
        )

    if _request_id(directory / _RUNTIME_CONFIG_NAME) != request_id:
        raise HTTPException(
            status_code=503,
            detail="The host updated .env but could not confirm the runtime configuration commit.",
        )

    logger.info(
        "VictoriaMetrics disk protection update requested by user=%s threshold_bytes=%s",
        user.get("username", "unknown"),
        body.min_free_disk_space_bytes,
    )
    payload = _settings_payload(directory)
    payload["runtime_state"] = "RESTART_REQUESTED"
    payload["runtime_error_code"] = None
    payload["request_id"] = request_id
    return payload
