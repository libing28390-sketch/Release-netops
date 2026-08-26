"""MIG-004 dry-run/resume/idempotency/rollback and PostgreSQL tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_mig004_migration_runner_check.py"
SPEC = importlib.util.spec_from_file_location("mig004_runner", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _manifest() -> dict:
    return MODULE.load_manifest(ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-003-migration-manifest-v1.json")


class _Writer:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str, str], dict] = {}
        self.pending: dict[tuple[str, str, str, str], dict] = {}
        self.begin_calls = 0
        self.rollback_calls = 0

    def begin_batch(self, _number: int) -> None:
        self.begin_calls += 1
        self.pending = {}

    def exists_same(self, key: tuple[str, str, str, str]) -> bool:
        return key in self.rows

    def upsert(self, entry: dict) -> None:
        key = (entry["tenant_id_hash"], entry["legacy_id"], entry["v2_document_id"], entry["v2_document_version_id"])
        self.pending[key] = entry

    def commit_batch(self) -> None:
        self.rows.update(self.pending)
        self.pending = {}

    def rollback_batch(self) -> None:
        self.rollback_calls += 1
        self.pending = {}


def test_mig004_contract_and_dry_run_are_redacted_and_complete(tmp_path: Path) -> None:
    contract = MODULE.load_contract()
    assert contract["task_id"] == "MIG-004"
    assert contract["authority"] == "PostgreSQL"
    manifest = _manifest()
    result = MODULE.MigrationRunner(manifest, tmp_path / "checkpoint.json", batch_size=7).run(mode="dry-run")
    assert result["status"] == "PASS"
    assert result["next_offset"] == len(manifest["entries"])
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "dry_run_complete"
    assert checkpoint["manifest_sha256"] == manifest["manifest_sha256"]
    assert "original_content" not in json.dumps(checkpoint)


def test_mig004_failure_preserves_cursor_and_resume_is_idempotent(tmp_path: Path) -> None:
    manifest = _manifest()
    checkpoint = tmp_path / "checkpoint.json"
    writer = _Writer()
    runner = MODULE.MigrationRunner(manifest, checkpoint, batch_size=10)
    with pytest.raises(MODULE.MigrationRunnerError, match="MIG004_INJECTED_BATCH_FAILURE"):
        runner.run(mode="apply", writer=writer, fail_after_batch=1)
    failed = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert failed["status"] == "retry_wait"
    assert failed["next_offset"] == 0
    assert failed["committed_batches"] == 0
    assert not writer.rows
    assert writer.rollback_calls == 1
    resumed = runner.run(mode="apply", writer=writer)
    assert resumed["status"] == "PASS"
    assert len(writer.rows) == len(manifest["entries"])
    again = runner.run(mode="apply", writer=writer)
    assert again["status"] == "PASS"
    assert again["counts"]["skipped_idempotent"] == len(manifest["entries"])


def test_mig004_conflicting_checkpoint_fails_closed(tmp_path: Path) -> None:
    manifest = _manifest()
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps({"checkpoint_version": MODULE.CHECKPOINT_VERSION, "task_id": "MIG-004", "manifest_sha256": "0" * 64, "batch_size": 5}), encoding="utf-8")
    with pytest.raises(MODULE.MigrationRunnerError, match="MIG004_CHECKPOINT_BINDING_MISMATCH"):
        MODULE.MigrationRunner(manifest, path, batch_size=5).run(mode="dry-run")


def test_mig004_postgresql_temp_batch_rollback_probe() -> None:
    result = MODULE.postgres_temp_transaction_probe()
    assert result["database"] == "PostgreSQL"
    assert result["temporary_transaction_only"] is True
    assert result["batch_rollback"] is True
    assert result["after_rollback"] == 0
    assert result["production_database_write"] is False
    assert result["sqlite"] == "forbidden"
