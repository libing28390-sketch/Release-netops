from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from fastapi import HTTPException

from api import monitoring_storage as storage_api


ROOT = Path(__file__).resolve().parents[3]
HELPER_PATH = ROOT / "scripts/monitoring/sync_vm_storage_env.py"
SPEC = importlib.util.spec_from_file_location("nexora_vm_storage_env_sync", HELPER_PATH)
assert SPEC and SPEC.loader
env_sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(env_sync)

FIVE_GIB = 5 * 1024**3
REQUEST_ID = "0123456789abcdef01234567"


def test_sync_updates_only_threshold_and_keeps_private_backup(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_bytes(
        b"POSTGRES_PASSWORD=do-not-change\n"
        b"VM_MIN_FREE_DISK_SPACE_BYTES=10737418240\n"
        b"AI_ENABLED=0\n"
    )
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    original = env_file.read_bytes()

    result = env_sync.sync_request(env_file, runtime_dir, FIVE_GIB, REQUEST_ID)

    assert env_file.read_bytes() == (
        b"POSTGRES_PASSWORD=do-not-change\n"
        b"VM_MIN_FREE_DISK_SPACE_BYTES=5368709120\n"
        b"AI_ENABLED=0\n"
    )
    assert result["changed"] is True
    backup = env_file.with_name(result["backup_name"])
    assert backup.read_bytes() == original
    if os.name == "posix":
        assert backup.stat().st_mode & 0o777 == 0o600
    assert (runtime_dir / env_sync.RUNTIME_CONFIG_NAME).read_bytes() == (
        b"5368709120\n0123456789abcdef01234567\n"
    )


def test_update_env_bytes_preserves_crlf_and_replaces_duplicate_keys():
    original = (
        b"POSTGRES_PASSWORD=private\r\n"
        b"VM_MIN_FREE_DISK_SPACE_BYTES = 10737418240  # first\r\n"
        b"VM_MIN_FREE_DISK_SPACE_BYTES=21474836480\r\n"
        b"AI_ENABLED=0\r\n"
    )

    updated, changed = env_sync.update_env_bytes(original, FIVE_GIB)

    assert changed is True
    assert updated == (
        b"POSTGRES_PASSWORD=private\r\n"
        b"VM_MIN_FREE_DISK_SPACE_BYTES = 5368709120 # first\r\n"
        b"VM_MIN_FREE_DISK_SPACE_BYTES=5368709120\r\n"
        b"AI_ENABLED=0\r\n"
    )
    assert b"\n" not in updated.replace(b"\r\n", b"")


def test_update_env_bytes_appends_missing_key_using_existing_newline_style():
    updated, changed = env_sync.update_env_bytes(b"POSTGRES_PASSWORD=private\r\nAI_ENABLED=0", FIVE_GIB)

    assert changed is True
    assert updated == b"POSTGRES_PASSWORD=private\r\nAI_ENABLED=0\r\nVM_MIN_FREE_DISK_SPACE_BYTES=5368709120\r\n"


def test_sync_rejects_missing_env_without_committing_runtime_value(tmp_path: Path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()

    with pytest.raises(env_sync.SyncFailure, match="ENV_FILE_UNAVAILABLE"):
        env_sync.sync_request(tmp_path / ".env-missing", runtime_dir, FIVE_GIB, REQUEST_ID)

    assert not (runtime_dir / env_sync.RUNTIME_CONFIG_NAME).exists()


def test_runtime_commit_failure_restores_env_after_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env_file = tmp_path / ".env"
    original = b"VM_MIN_FREE_DISK_SPACE_BYTES=10737418240\nOTHER=value\n"
    env_file.write_bytes(original)
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()

    def fail_commit(*_args, **_kwargs):
        raise OSError("simulated runtime-volume write failure")

    monkeypatch.setattr(env_sync, "_write_runtime_config", fail_commit)
    with pytest.raises(env_sync.SyncFailure, match="RUNTIME_COMMIT_FAILED"):
        env_sync.sync_request(env_file, runtime_dir, FIVE_GIB, REQUEST_ID)

    assert env_file.read_bytes() == original
    assert any(path.name.startswith(".env.backup.vm-threshold.") for path in tmp_path.iterdir())


def test_storage_api_waits_for_host_env_sync_before_accepting_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    env_file = tmp_path / ".env"
    env_file.write_text("VM_MIN_FREE_DISK_SPACE_BYTES=10737418240\n", encoding="ascii")
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / env_sync.READY_NAME).write_text("READY\n", encoding="ascii")
    (runtime_dir / env_sync.TRIGGER_NAME).write_text("\n", encoding="ascii")
    monkeypatch.setattr(storage_api, "_runtime_directory", lambda: runtime_dir)

    def run_host_sync(_seconds: float):
        value, request_id = env_sync._read_request(runtime_dir / env_sync.REQUEST_NAME)
        env_sync.sync_request(env_file, runtime_dir, value, request_id)
        env_sync._write_status(runtime_dir, request_id, "SYNCED")

    monkeypatch.setattr(storage_api.time, "sleep", run_host_sync)
    payload = storage_api.update_storage_protection(
        storage_api.StorageProtectionUpdate(min_free_disk_space_bytes=FIVE_GIB),
        user={"username": "admin"},
    )

    assert env_file.read_text(encoding="ascii") == "VM_MIN_FREE_DISK_SPACE_BYTES=5368709120\n"
    assert payload["runtime_state"] == "RESTART_REQUESTED"
    assert payload["env_sync_state"] == "SYNCED"
    assert payload["env_sync_request_id"] == payload["request_id"]
    assert env_sync._read_request(runtime_dir / env_sync.RUNTIME_CONFIG_NAME) == (
        FIVE_GIB,
        payload["request_id"],
    )


def test_storage_api_rejects_updates_when_host_env_sync_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    existing = b"10737418240\n0123456789abcdef01234567\n"
    (runtime_dir / env_sync.RUNTIME_CONFIG_NAME).write_bytes(existing)
    monkeypatch.setattr(storage_api, "_runtime_directory", lambda: runtime_dir)

    with pytest.raises(HTTPException) as exc_info:
        storage_api.update_storage_protection(
            storage_api.StorageProtectionUpdate(min_free_disk_space_bytes=FIVE_GIB),
            user={"username": "admin"},
        )

    assert exc_info.value.status_code == 503
    assert (runtime_dir / env_sync.RUNTIME_CONFIG_NAME).read_bytes() == existing
    assert not (runtime_dir / env_sync.REQUEST_NAME).exists()


def test_storage_api_reports_host_env_sync_failure_without_applying_runtime_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    env_file = tmp_path / ".env"
    original_env = b"VM_MIN_FREE_DISK_SPACE_BYTES=10737418240\n"
    env_file.write_bytes(original_env)
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    (runtime_dir / env_sync.READY_NAME).write_text("READY\n", encoding="ascii")
    (runtime_dir / env_sync.TRIGGER_NAME).write_text("\n", encoding="ascii")
    previous_config = b"10737418240\n0123456789abcdef01234567\n"
    (runtime_dir / env_sync.RUNTIME_CONFIG_NAME).write_bytes(previous_config)
    monkeypatch.setattr(storage_api, "_runtime_directory", lambda: runtime_dir)

    def reject_sync(_seconds: float):
        _value, request_id = env_sync._read_request(runtime_dir / env_sync.REQUEST_NAME)
        env_sync._write_status(runtime_dir, request_id, "FAILED", "ENV_FILE_UNAVAILABLE")

    monkeypatch.setattr(storage_api.time, "sleep", reject_sync)
    with pytest.raises(HTTPException) as exc_info:
        storage_api.update_storage_protection(
            storage_api.StorageProtectionUpdate(min_free_disk_space_bytes=FIVE_GIB),
            user={"username": "admin"},
        )

    assert exc_info.value.status_code == 503
    assert env_file.read_bytes() == original_env
    assert (runtime_dir / env_sync.RUNTIME_CONFIG_NAME).read_bytes() == previous_config
    settings = storage_api.get_storage_protection(_user={"username": "admin"})
    assert settings["env_sync_state"] == "FAILED"
    assert settings["env_sync_error_code"] == "ENV_FILE_UNAVAILABLE"
