"""Run the PostgreSQL-only Source/Document/Version/Chunk/Reindex probes."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "EVAL-012-LIFECYCLE-TEST-CONTRACT.yaml"
PLAN_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-022-REINDEX-BATCH-LEASE-CONTRACT.yaml"
REINDEX_SERVICE_PATH = ROOT / "backend" / "ai" / "services" / "knowledge_reindex_service.py"
PROBES: tuple[tuple[str, str], ...] = (
    ("source", "scripts/knowledge_engine_v2_kui015_pg_probe.py"),
    ("document", "scripts/knowledge_engine_v2_kui012_pg_probe.py"),
    ("version", "scripts/knowledge_engine_v2_kui014_pg_probe.py"),
    ("chunk", "scripts/knowledge_engine_v2_chk015_pg_probe.py"),
    ("reindex", "scripts/knowledge_engine_v2_chk013_pg_probe.py"),
)
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-lifecycle-v1.manifest.json"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing EVAL-012 authority: {path}"
    return path.read_text(encoding="utf-8")


def validate_lifecycle_contract() -> dict[str, Any]:
    contract = _read(CONTRACT_PATH)
    plan = _read(PLAN_PATH)
    reindex_service = _read(REINDEX_SERVICE_PATH)
    for marker in ("authority: PostgreSQL", "sqlite: forbidden", "transaction_or_cleanup: required", "production_write: false"):
        assert marker in contract, marker
    for marker in ("_select_document_batch", "_ReindexLease", "checkpointed", "retry_wait", "MAX_BATCH_SIZE"):
        assert marker in reindex_service, marker
    assert "V1" in plan
    for _, relative in PROBES:
        assert (ROOT / relative).is_file(), relative
    return {
        "status": "PASS",
        "task_id": "EVAL-012",
        "database": "postgresql",
        "sqlite": "not_used",
        "probe_count": len(PROBES),
        "probes": [name for name, _ in PROBES],
        "production_write": False,
        "source_sha256": {
            "contract": hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            "reindex_contract": hashlib.sha256(plan.encode("utf-8")).hexdigest(),
            "reindex_service": hashlib.sha256(reindex_service.encode("utf-8")).hexdigest(),
        },
    }


def _postgres_environment() -> dict[str, str]:
    env = os.environ.copy()
    database_url = env.get("DATABASE_URL", "")
    if not database_url.lower().startswith(("postgresql://", "postgres://")):
        raise RuntimeError("EVAL-012 requires a PostgreSQL DATABASE_URL; SQLite is forbidden")
    env["PYTHONPATH"] = str(ROOT / "backend")
    return env


def run_postgresql_lifecycle_probes() -> dict[str, Any]:
    env = _postgres_environment()
    results: dict[str, Any] = {}
    for name, relative in PROBES:
        completed = subprocess.run(
            [sys.executable, str(ROOT / relative)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if completed.returncode != 0:
            raise AssertionError(f"{name} PostgreSQL probe failed (exit {completed.returncode})")
        try:
            report = json.loads(completed.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError) as exc:
            raise AssertionError(f"{name} probe did not emit JSON") from exc
        database = str(report.get("database", "")).lower()
        if database not in {"postgresql", "postgres"} and report.get("postgresql") is not True:
            raise AssertionError(f"{name} probe did not report PostgreSQL")
        results[name] = report
    return {
        "status": "PASS",
        "task_id": "EVAL-012",
        "database": "postgresql",
        "sqlite": "not_used",
        "probe_count": len(results),
        "probes": results,
        "production_write": False,
        "rollback_or_cleanup": True,
    }


def main() -> int:
    contract_report = validate_lifecycle_contract()
    probe_report = run_postgresql_lifecycle_probes()
    output = {**contract_report, "probe_results": probe_report["probes"], "rollback_or_cleanup": True}
    REPORT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
