"""MIG-004 migration-runner gate.

This runner deliberately stops at the manifest/dry-run boundary while the
MIG-002 source and hash reconciliation is unresolved.  Its execution engine
still implements the production-safe primitives needed by the later apply
wave: bounded batches, a manifest-bound checkpoint, idempotent writes, and
rollback of only the failed batch.  The live database probe uses a temporary
PostgreSQL table and rolls the transaction back; no persistent table is
modified and SQLite is never accepted.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "MIG-004"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "MIG-004-MIGRATION-RUNNER-CONTRACT.yaml"
MANIFEST_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-003-migration-manifest-v1.json"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-004-migration-runner-v1.json"
CHECKPOINT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-004-checkpoint-v1.json"
CHECKPOINT_VERSION = "nexora-knowledge-engine-v2-migration-checkpoint/v1"
FORBIDDEN_ENTRY_FIELDS = {"original_content", "normalized_content", "metadata_json", "acl_json", "secret", "database_url"}


class MigrationRunnerError(RuntimeError):
    """Stable, redacted runner error."""


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("task_id") != TASK_ID:
        raise AssertionError("MIG-004 contract task mismatch")
    if payload.get("authority") != "PostgreSQL" or payload.get("sqlite") != "forbidden_for_acceptance":
        raise AssertionError("MIG-004 PostgreSQL-only authority is missing")
    if payload.get("production_database_write") is not False:
        raise AssertionError("MIG-004 production writes must remain disabled at this gate")
    execution = payload.get("execution") or {}
    if execution.get("default_mode") != "dry_run" or execution.get("idempotency_key") is None:
        raise AssertionError("MIG-004 runner contract is incomplete")
    return payload


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    body.pop("generated_at", None)
    return hashlib.sha256(_canonical_json(body)).hexdigest()


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("manifest_version") != "nexora-knowledge-engine-v2-migration-manifest/v1":
        raise MigrationRunnerError("MIG004_MANIFEST_VERSION_INVALID")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise MigrationRunnerError("MIG004_MANIFEST_ENTRIES_INVALID")
    expected = str(manifest.get("manifest_sha256") or "")
    if len(expected) != 64 or _manifest_digest(manifest) != expected:
        raise MigrationRunnerError("MIG004_MANIFEST_DIGEST_MISMATCH")
    for entry in entries:
        if not isinstance(entry, dict):
            raise MigrationRunnerError("MIG004_MANIFEST_ENTRY_INVALID")
        if FORBIDDEN_ENTRY_FIELDS.intersection(entry):
            raise MigrationRunnerError("MIG004_MANIFEST_RAW_FIELD_PRESENT")
    return manifest


def _checkpoint_payload(
    *, manifest_sha256: str, batch_size: int, next_offset: int, committed_batches: int,
    status: str, counts: Mapping[str, int], last_error_code: str = "",
) -> dict[str, Any]:
    return {
        "checkpoint_version": CHECKPOINT_VERSION,
        "task_id": TASK_ID,
        "manifest_sha256": manifest_sha256,
        "batch_size": batch_size,
        "next_offset": next_offset,
        "committed_batches": committed_batches,
        "status": status,
        "counts": {key: int(value) for key, value in counts.items()},
        "last_error_code": last_error_code,
        "redaction": {"raw_content": "omitted", "metadata": "omitted", "acl": "omitted", "secrets": "omitted"},
    }


def write_checkpoint(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically persist only manifest-bound cursor/counts and stable errors."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(dict(payload), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def read_checkpoint(path: Path, manifest_sha256: str, batch_size: int) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("checkpoint_version") != CHECKPOINT_VERSION or payload.get("task_id") != TASK_ID:
        raise MigrationRunnerError("MIG004_CHECKPOINT_VERSION_INVALID")
    if payload.get("manifest_sha256") != manifest_sha256 or int(payload.get("batch_size", 0)) != batch_size:
        raise MigrationRunnerError("MIG004_CHECKPOINT_BINDING_MISMATCH")
    if any(key in payload for key in FORBIDDEN_ENTRY_FIELDS):
        raise MigrationRunnerError("MIG004_CHECKPOINT_RAW_FIELD_PRESENT")
    return payload


class MigrationRunner:
    """Bounded, resumable runner with injectable transactional writer."""

    def __init__(self, manifest: Mapping[str, Any], checkpoint_path: Path, *, batch_size: int = 25) -> None:
        if batch_size <= 0 or batch_size > 1000:
            raise ValueError("batch_size must be between 1 and 1000")
        self.manifest = manifest
        self.entries = list(manifest.get("entries") or [])
        self.manifest_sha256 = str(manifest.get("manifest_sha256") or "")
        self.checkpoint_path = checkpoint_path
        self.batch_size = batch_size
        self._validate_entries()

    def _validate_entries(self) -> None:
        seen_old: set[tuple[str, str]] = set()
        seen_v2: set[str] = set()
        for entry in self.entries:
            old_key = (str(entry.get("tenant_id_hash") or ""), str(entry.get("legacy_id") or ""))
            v2_id = str(entry.get("v2_document_id") or "")
            if not old_key[0] or not old_key[1] or not v2_id:
                raise MigrationRunnerError("MIG004_MAPPING_KEY_MISSING")
            if old_key in seen_old:
                raise MigrationRunnerError("MIG004_DUPLICATE_LEGACY_KEY")
            if v2_id in seen_v2:
                raise MigrationRunnerError("MIG004_V2_MAPPING_COLLISION")
            seen_old.add(old_key)
            seen_v2.add(v2_id)

    def run(
        self,
        *, mode: str = "dry-run",
        writer: Any | None = None,
        fail_after_batch: int | None = None,
        on_batch: Callable[[int, list[dict[str, Any]]], None] | None = None,
    ) -> dict[str, Any]:
        if mode not in {"dry-run", "apply"}:
            raise ValueError("mode must be dry-run or apply")
        if mode == "apply" and writer is None:
            raise MigrationRunnerError("MIG004_APPROVED_TARGET_REQUIRED")
        checkpoint = read_checkpoint(self.checkpoint_path, self.manifest_sha256, self.batch_size)
        counts = {"planned": len(self.entries), "processed": 0, "inserted": 0, "skipped_idempotent": 0, "failed": 0}
        start = 0
        committed_batches = 0
        if checkpoint:
            start = int(checkpoint.get("next_offset", 0))
            committed_batches = int(checkpoint.get("committed_batches", 0))
            for key in counts:
                counts[key] = int((checkpoint.get("counts") or {}).get(key, counts[key] if key == "planned" else 0))
            if start >= len(self.entries):
                # A completed checkpoint is an idempotent replay, not a
                # reason to silently assume that the target still exists.
                # Verify the target adapter when applying; any missing row is
                # a fail-closed checkpoint/target inconsistency.
                if mode == "apply":
                    missing = 0
                    for entry in self.entries:
                        key = (entry["tenant_id_hash"], entry["legacy_id"], entry["v2_document_id"], entry["v2_document_version_id"])
                        if writer is None or not writer.exists_same(key):
                            missing += 1
                    if missing:
                        raise MigrationRunnerError("MIG004_CHECKPOINT_TARGET_MISSING")
                    counts["skipped_idempotent"] = len(self.entries)
                return {
                    "status": "PASS",
                    "mode": mode,
                    "checkpoint": str(self.checkpoint_path),
                    "counts": counts,
                    "next_offset": len(self.entries),
                    "committed_batches": committed_batches,
                    "idempotent_noop": True,
                }
        batch_number = committed_batches
        while start < len(self.entries):
            batch = self.entries[start : start + self.batch_size]
            batch_number += 1
            if mode == "dry-run":
                counts["processed"] += len(batch)
                write_checkpoint(
                    self.checkpoint_path,
                    _checkpoint_payload(
                        manifest_sha256=self.manifest_sha256, batch_size=self.batch_size,
                        next_offset=start + len(batch), committed_batches=batch_number,
                        status="dry_run_progress", counts=counts,
                    ),
                )
            else:
                writer.begin_batch(batch_number)
                try:
                    for entry in batch:
                        key = (entry["tenant_id_hash"], entry["legacy_id"], entry["v2_document_id"], entry["v2_document_version_id"])
                        if writer.exists_same(key):
                            counts["skipped_idempotent"] += 1
                        else:
                            writer.upsert(entry)
                            counts["inserted"] += 1
                        counts["processed"] += 1
                    if fail_after_batch is not None and batch_number == fail_after_batch:
                        raise MigrationRunnerError("MIG004_INJECTED_BATCH_FAILURE")
                    writer.commit_batch()
                except Exception as exc:
                    writer.rollback_batch()
                    counts["failed"] += 1
                    write_checkpoint(
                        self.checkpoint_path,
                        _checkpoint_payload(
                            manifest_sha256=self.manifest_sha256, batch_size=self.batch_size,
                            next_offset=start, committed_batches=batch_number - 1,
                            status="retry_wait", counts=counts,
                            last_error_code=exc.args[0] if isinstance(exc, MigrationRunnerError) else "MIG004_BATCH_FAILED",
                        ),
                    )
                    raise
                write_checkpoint(
                    self.checkpoint_path,
                    _checkpoint_payload(
                        manifest_sha256=self.manifest_sha256, batch_size=self.batch_size,
                        next_offset=start + len(batch), committed_batches=batch_number,
                        status="apply_progress", counts=counts,
                    ),
                )
            if on_batch:
                on_batch(batch_number, batch)
            start += len(batch)
        final_status = "dry_run_complete" if mode == "dry-run" else "apply_complete"
        write_checkpoint(
            self.checkpoint_path,
            _checkpoint_payload(
                manifest_sha256=self.manifest_sha256, batch_size=self.batch_size,
                next_offset=len(self.entries), committed_batches=batch_number,
                status=final_status, counts=counts,
            ),
        )
        return {"status": "PASS", "mode": mode, "checkpoint": str(self.checkpoint_path), "counts": counts, "next_offset": len(self.entries), "committed_batches": batch_number}


def postgres_temp_transaction_probe() -> dict[str, Any]:
    from database import core

    if not core._USE_PG:
        raise RuntimeError("MIG-004 requires PostgreSQL; SQLite is forbidden")
    conn = core.get_db_connection()
    try:
        conn.execute("BEGIN")
        conn.execute("CREATE TEMP TABLE mig004_batch_probe (id TEXT PRIMARY KEY) ON COMMIT DROP")
        conn.execute("SAVEPOINT mig004_batch")
        conn.execute("INSERT INTO mig004_batch_probe (id) VALUES (?)", ("probe",))
        before_rollback = int(conn.execute("SELECT COUNT(*) FROM mig004_batch_probe").fetchone()[0])
        conn.execute("ROLLBACK TO SAVEPOINT mig004_batch")
        after_rollback = int(conn.execute("SELECT COUNT(*) FROM mig004_batch_probe").fetchone()[0])
        conn.execute("RELEASE SAVEPOINT mig004_batch")
        conn.rollback()
    finally:
        conn.close()
    return {
        "database": "PostgreSQL",
        "temporary_transaction_only": True,
        "before_rollback": before_rollback,
        "after_rollback": after_rollback,
        "batch_rollback": before_rollback == 1 and after_rollback == 0,
        "production_database_write": False,
        "sqlite": "forbidden",
    }


def run_gate() -> dict[str, Any]:
    started = time.perf_counter()
    contract = load_contract()
    manifest = load_manifest()
    checkpoint_path = CHECKPOINT_PATH
    runner = MigrationRunner(manifest, checkpoint_path, batch_size=25)
    dry_run = runner.run(mode="dry-run")
    pg_probe = postgres_temp_transaction_probe()
    counts = dry_run["counts"]
    status = "PASS" if dry_run["status"] == "PASS" and dry_run["next_offset"] == len(runner.entries) and pg_probe["batch_rollback"] else "FAIL"
    return {
        "status": status,
        "task_id": TASK_ID,
        "authority": "PostgreSQL",
        "sqlite": "forbidden",
        "duration_seconds": round(time.perf_counter() - started, 3),
        "manifest_sha256": runner.manifest_sha256,
        "manifest_entries": len(runner.entries),
        "dry_run": {"status": dry_run["status"], "next_offset": dry_run["next_offset"], "committed_batches": dry_run["committed_batches"], "counts": counts},
        "checkpoint": {"path": str(checkpoint_path), "status": "redacted_manifest_bound"},
        "postgres_probe": pg_probe,
        "production_database_write": False,
        "apply_guard": "approved_target_and_reconciled_manifest_required",
        "rollback": "failed_batch_only_and_previous_checkpoint_preserved",
        "report_redacted": True,
        "contract_sha256": hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest(),
        "contract_layers": sorted(contract),
    }


def main() -> int:
    try:
        report = run_gate()
    except Exception as exc:
        report = {"status": "ERROR", "task_id": TASK_ID, "error_type": type(exc).__name__}
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 1
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
