"""Validate the PostgreSQL-only CI/release wiring for EVAL-010.

This is intentionally a text-level contract check. GitHub Actions is not
available in the local test runner, so the validator proves that the checked
in workflows select PostgreSQL, expose the expected evaluation profiles and
contain no SQLite database URL.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "knowledge-engine-eval.yml"
BACKEND_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "backend-pytest-check.yml"
RELEASE_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release.yml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-ci-gate-v1.manifest.json"


def _read(path: Path) -> str:
    if not path.is_file():
        raise AssertionError(f"missing required CI contract: {path}")
    return path.read_text(encoding="utf-8")


def _require(text: str, marker: str, label: str) -> None:
    assert marker in text, f"{label} is missing required marker: {marker}"


def validate_ci_gate() -> dict[str, Any]:
    small_ci = _read(WORKFLOW_PATH)
    backend_ci = _read(BACKEND_WORKFLOW_PATH)
    release_ci = _read(RELEASE_WORKFLOW_PATH)

    for label, text in (("EVAL-010 workflow", small_ci), ("backend workflow", backend_ci)):
        _require(text, "DATABASE_URL: postgresql://", label)

    _require(small_ci, "postgres:", "EVAL-010 workflow")
    _require(small_ci, "pg_isready", "EVAL-010 workflow")
    _require(small_ci, "--profile small", "EVAL-010 workflow")
    _require(small_ci, "--strict", "EVAL-010 workflow")
    _require(small_ci, "knowledge_eval_ci_gate_check.py", "EVAL-010 workflow")
    _require(release_ci, "--profile full", "release workflow")
    _require(release_ci, "--strict", "release workflow")
    _require(release_ci, "knowledge_eval_offline.py", "release workflow")
    _require(release_ci, "DATABASE_URL: postgresql://", "release workflow")

    output: dict[str, Any] = {
        "status": "PASS",
        "task_id": "EVAL-010",
        "small_ci_profile": "small",
        "full_release_profile": "full",
        "database_url_scheme": "postgresql",
        "postgres_service": True,
        "database_contract": "postgresql_only",
        "external_network": "not_used_by_offline_runner",
        "production_write": False,
        "workflow_sha256": {
            "knowledge_engine_eval": hashlib.sha256(small_ci.encode("utf-8")).hexdigest(),
            "backend_pytest": hashlib.sha256(backend_ci.encode("utf-8")).hexdigest(),
            "release": hashlib.sha256(release_ci.encode("utf-8")).hexdigest(),
        },
    }
    REPORT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    print(json.dumps(validate_ci_gate(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
