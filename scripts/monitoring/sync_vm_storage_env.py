#!/usr/bin/env python3
"""Synchronize the VictoriaMetrics runtime threshold into the host .env.

This helper is installed as a root-owned, network-isolated systemd oneshot.
It accepts only a bounded integer request from the shared runtime volume and
updates one whitelisted .env key. The NetOps web container never mounts the
host .env file or receives Docker socket access.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # Local Windows checks do not exercise host-side locking.
    fcntl = None  # type: ignore[assignment]


ENV_KEY = b"VM_MIN_FREE_DISK_SPACE_BYTES"
MIN_FREE_BYTES = 512 * 1024**2
MAX_FREE_BYTES = 16 * 1024**4
RUNTIME_CONFIG_NAME = "min-free-disk-space-bytes"
REQUEST_NAME = "env-sync-request"
TRIGGER_NAME = "env-sync-trigger"
STATUS_NAME = "env-sync-status"
READY_NAME = "env-sync-ready"
REQUEST_ID_PATTERN = re.compile(r"^[a-f0-9]{24}$")
VALUE_PATTERN = re.compile(r"^[0-9]{1,20}$")
ENV_ASSIGNMENT_PATTERN = re.compile(
    rb"^([ \t]*(?:export[ \t]+)?VM_MIN_FREE_DISK_SPACE_BYTES[ \t]*=[ \t]*)(.*)$"
)


class SyncFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _read_request(path: Path) -> tuple[int, str]:
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (FileNotFoundError, OSError, UnicodeError) as exc:
        raise SyncFailure("REQUEST_UNAVAILABLE") from exc
    if len(lines) < 2 or not VALUE_PATTERN.fullmatch(lines[0]) or not REQUEST_ID_PATTERN.fullmatch(lines[1]):
        raise SyncFailure("REQUEST_INVALID")
    value = int(lines[0])
    if value < MIN_FREE_BYTES or value > MAX_FREE_BYTES:
        raise SyncFailure("REQUEST_INVALID")
    return value, lines[1]


def _read_request_expiry(path: Path) -> float:
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (FileNotFoundError, OSError, UnicodeError) as exc:
        raise SyncFailure("REQUEST_UNAVAILABLE") from exc
    if len(lines) < 3 or not re.fullmatch(r"[0-9]{10,12}(?:\.[0-9]{1,6})?", lines[2]):
        raise SyncFailure("REQUEST_INVALID")
    return float(lines[2])


def _split_line_ending(line: bytes) -> tuple[bytes, bytes]:
    if line.endswith(b"\r\n"):
        return line[:-2], b"\r\n"
    if line.endswith(b"\n"):
        return line[:-1], b"\n"
    if line.endswith(b"\r"):
        return line[:-1], b"\r"
    return line, b""


def _replace_value_preserving_comment(body: bytes, value: bytes) -> bytes:
    comment_at = body.find(b"#")
    if comment_at < 0:
        return value
    comment = body[comment_at:]
    if comment_at > 0 and body[comment_at - 1 : comment_at] not in (b" ", b"\t"):
        return value + b" " + comment
    return value + body[comment_at - 1 : comment_at] + comment


def update_env_bytes(contents: bytes, value: int) -> tuple[bytes, bool]:
    """Replace all exact assignments, preserving unrelated bytes and line endings."""
    replacement = str(value).encode("ascii")
    lines = contents.splitlines(keepends=True)
    updated: list[bytes] = []
    matches = 0
    for line in lines:
        body, ending = _split_line_ending(line)
        candidate = body[3:] if body.startswith(b"\xef\xbb\xbf") else body
        prefix = body[: len(body) - len(candidate)]
        match = ENV_ASSIGNMENT_PATTERN.match(candidate)
        if match is None:
            updated.append(line)
            continue
        current_value = match.group(2)
        new_body = prefix + match.group(1) + _replace_value_preserving_comment(current_value, replacement)
        updated.append(new_body + ending)
        matches += 1

    if matches == 0:
        newline = b"\r\n" if b"\r\n" in contents else b"\n"
        if contents and not contents.endswith((b"\n", b"\r")):
            updated.append(newline)
        updated.append(ENV_KEY + b"=" + replacement + newline)
        return b"".join(updated), True

    result = b"".join(updated)
    return result, result != contents


def _write_atomic(path: Path, contents: bytes, *, mode: int, uid: int, gid: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            if os.name == "posix":
                os.fsync(stream.fileno())
                os.fchmod(stream.fileno(), mode)
                os.fchown(stream.fileno(), uid, gid)
            else:  # pragma: no cover - host helper is Linux-only
                os.chmod(temporary, mode)
        os.replace(temporary, path)
        if os.name == "posix":
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _backup_env(env_file: Path, original: bytes, env_stat: os.stat_result, request_id: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = env_file.with_name(f"{env_file.name}.backup.vm-threshold.{stamp}.{request_id}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(backup, flags, 0o600)
    try:
        if os.name == "posix":
            os.fchown(descriptor, env_stat.st_uid, env_stat.st_gid)
            os.fchmod(descriptor, 0o600)
        else:  # pragma: no cover - host helper is Linux-only
            os.chmod(backup, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    return backup


def _write_status(runtime_dir: Path, request_id: str, state: str, error_code: str | None = None) -> None:
    directory_stat = runtime_dir.stat()
    payload = {
        "request_id": request_id,
        "state": state,
        "error_code": error_code,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _write_atomic(
        runtime_dir / STATUS_NAME,
        (json.dumps(payload, separators=(",", ":")) + "\n").encode("ascii"),
        mode=0o664,
        uid=directory_stat.st_uid,
        gid=directory_stat.st_gid,
    )


def _write_runtime_config(runtime_dir: Path, value: int, request_id: str) -> None:
    directory_stat = runtime_dir.stat()
    _write_atomic(
        runtime_dir / RUNTIME_CONFIG_NAME,
        f"{value}\n{request_id}\n".encode("ascii"),
        mode=0o664,
        uid=directory_stat.st_uid,
        gid=directory_stat.st_gid,
    )


def sync_request(
    env_file: Path,
    runtime_dir: Path,
    value: int,
    request_id: str,
    *,
    expires_at: float | None = None,
) -> dict[str, Any]:
    if value < MIN_FREE_BYTES or value > MAX_FREE_BYTES or not REQUEST_ID_PATTERN.fullmatch(request_id):
        raise SyncFailure("REQUEST_INVALID")
    if expires_at is not None and time.time() > expires_at:
        raise SyncFailure("REQUEST_EXPIRED")
    if env_file.is_symlink():
        raise SyncFailure("ENV_FILE_UNSUPPORTED")
    try:
        env_stat = env_file.stat(follow_symlinks=False)
        if not stat.S_ISREG(env_stat.st_mode):
            raise SyncFailure("ENV_FILE_UNSUPPORTED")
        original = env_file.read_bytes()
    except SyncFailure:
        raise
    except (FileNotFoundError, OSError) as exc:
        raise SyncFailure("ENV_FILE_UNAVAILABLE") from exc

    updated, changed = update_env_bytes(original, value)
    backup: Path | None = None
    if changed:
        try:
            backup = _backup_env(env_file, original, env_stat, request_id)
            _write_atomic(
                env_file,
                updated,
                mode=stat.S_IMODE(env_stat.st_mode),
                uid=env_stat.st_uid,
                gid=env_stat.st_gid,
            )
        except OSError as exc:
            raise SyncFailure("ENV_UPDATE_FAILED") from exc

    try:
        if expires_at is not None and time.time() > expires_at:
            raise SyncFailure("REQUEST_EXPIRED")
        _write_runtime_config(runtime_dir, value, request_id)
    except (OSError, SyncFailure) as exc:
        if changed:
            try:
                _write_atomic(
                    env_file,
                    original,
                    mode=stat.S_IMODE(env_stat.st_mode),
                    uid=env_stat.st_uid,
                    gid=env_stat.st_gid,
                )
            except OSError as rollback_exc:
                raise SyncFailure("ENV_ROLLBACK_FAILED") from rollback_exc
        if isinstance(exc, SyncFailure):
            raise
        raise SyncFailure("RUNTIME_COMMIT_FAILED") from exc

    return {
        "request_id": request_id,
        "state": "SYNCED",
        "error_code": None,
        "backup_name": backup.name if backup else None,
        "changed": changed,
    }


def _load_settings() -> tuple[Path, Path]:
    settings_path = Path(os.environ.get("NEXORA_VM_ENV_SYNC_SETTINGS", ""))
    if not settings_path.is_absolute():
        raise SyncFailure("SETTINGS_UNAVAILABLE")
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        env_file = Path(settings["env_file"])
        runtime_dir = Path(settings["runtime_dir"])
    except (FileNotFoundError, OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise SyncFailure("SETTINGS_UNAVAILABLE") from exc
    if not env_file.is_absolute() or not runtime_dir.is_absolute():
        raise SyncFailure("SETTINGS_UNAVAILABLE")
    return env_file, runtime_dir


def _read_status(runtime_dir: Path) -> dict[str, Any]:
    try:
        return json.loads((runtime_dir / STATUS_NAME).read_text(encoding="ascii"))
    except (FileNotFoundError, OSError, UnicodeError, ValueError):
        return {}


def _run_once(env_file: Path, runtime_dir: Path, *, reconcile: bool) -> int:
    runtime_stat = runtime_dir.stat()
    lock_path = runtime_dir / "env-sync.lock"
    lock_flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    lock_descriptor = os.open(lock_path, lock_flags, 0o664)
    lock_stat = os.fstat(lock_descriptor)
    if not stat.S_ISREG(lock_stat.st_mode):
        os.close(lock_descriptor)
        raise SyncFailure("LOCK_UNAVAILABLE")
    if os.name == "posix":
        os.fchown(lock_descriptor, runtime_stat.st_uid, runtime_stat.st_gid)
        os.fchmod(lock_descriptor, 0o664)

    with os.fdopen(lock_descriptor, "r+b") as lock_stream:
        if fcntl is not None:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        if reconcile:
            try:
                value, request_id = _read_request(runtime_dir / RUNTIME_CONFIG_NAME)
            except SyncFailure as exc:
                if exc.code == "REQUEST_UNAVAILABLE":
                    return 0
                raise
        else:
            value, request_id = _read_request(runtime_dir / REQUEST_NAME)
            expires_at = _read_request_expiry(runtime_dir / REQUEST_NAME)
            if time.time() > expires_at:
                _write_status(runtime_dir, request_id, "FAILED", "REQUEST_EXPIRED")
                print("Nexora VM environment sync failed: REQUEST_EXPIRED")
                return 1
        if reconcile:
            expires_at = None

        current_status = _read_status(runtime_dir)
        if current_status.get("request_id") == request_id and current_status.get("state") == "SYNCED":
            if not reconcile:
                (runtime_dir / REQUEST_NAME).unlink(missing_ok=True)
            return 0

        try:
            result = sync_request(env_file, runtime_dir, value, request_id, expires_at=expires_at)
        except SyncFailure as exc:
            _write_status(runtime_dir, request_id, "FAILED", exc.code)
            print(f"Nexora VM environment sync failed: {exc.code}")
            return 1

        _write_status(runtime_dir, request_id, "SYNCED")
        if not reconcile:
            (runtime_dir / REQUEST_NAME).unlink(missing_ok=True)
        print(
            "Nexora VM environment sync complete: "
            f"changed={str(result['changed']).lower()} backup={result['backup_name'] or 'none'}"
        )
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reconcile", action="store_true", help="sync the existing runtime value into .env")
    args = parser.parse_args()
    try:
        env_file, runtime_dir = _load_settings()
        return _run_once(env_file, runtime_dir, reconcile=args.reconcile)
    except SyncFailure as exc:
        print(f"Nexora VM environment sync failed: {exc.code}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
