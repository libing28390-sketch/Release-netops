"""Run the PostgreSQL-only EVAL-015 input/failure matrix."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "EVAL-015-INPUT-FAILURE-CONTRACT.yaml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-input-failure-v1.manifest.json"
PROBES: tuple[tuple[str, Path], ...] = (
    ("provider_acl", ROOT / "scripts" / "knowledge_engine_v2_llm_pg_probe.py"),
    ("reindex_dependency", ROOT / "scripts" / "knowledge_engine_v2_chk013_pg_probe.py"),
    ("duplicate_content", ROOT / "scripts" / "knowledge_engine_v2_ing024_pg_probe.py"),
    ("v1_empty", ROOT / "scripts" / "knowledge_engine_v2_v1_baseline_pg.py"),
)
PURE_TESTS = (
    ROOT / "backend" / "tests" / "ai" / "test_api_v2_contracts.py",
    ROOT / "backend" / "tests" / "ai" / "test_sec_001_020_security_gateway.py",
    ROOT / "backend" / "tests" / "ai" / "test_security_gateway.py",
    ROOT / "backend" / "tests" / "ai" / "test_ingestion_pipeline_state_machine.py",
    ROOT / "backend" / "tests" / "ai" / "test_ingestion_idempotency.py",
    ROOT / "backend" / "tests" / "ai" / "test_ing006_document_parser_adapters.py",
    ROOT / "backend" / "tests" / "ai" / "test_ing008_document_security_scan.py",
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing EVAL-015 authority: {path}"
    return path.read_text(encoding="utf-8")


def _require(text: str, marker: str, label: str) -> None:
    assert marker in text, f"{label} missing marker: {marker}"


def validate_input_failure_coverage() -> dict[str, Any]:
    contract = _read(CONTRACT_PATH)
    pure_sources = {path.name: _read(path) for path in PURE_TESTS}
    probe_sources = {path.name: _read(path) for _, path in PROBES}
    for marker in ("authority: PostgreSQL", "sqlite: forbidden", "persistence_probe_transaction: rollback", "production_database_write: false"):
        _require(contract, marker, "EVAL-015 contract")
    for marker in ("ProviderResponseContract", "extra", "api_key", "unknown"):
        _require(pure_sources["test_api_v2_contracts.py"], marker, "API contract tests")
    for marker in ("unknown_provider", "prompt_injection", "write_tool", "sensitive_dump"):
        _require(pure_sources["test_sec_001_020_security_gateway.py"], marker, "security gateway tests")
    for marker in ("fail_closed", "credentials_are_blocked", "write_tool_is_blocked"):
        _require(pure_sources["test_security_gateway.py"], marker, "security tests")
    for marker in ("retry_budget", "lease_fencing", "failed_terminal_state", "tenant_scope"):
        _require(pure_sources["test_ingestion_pipeline_state_machine.py"], marker, "ingestion state tests")
    for marker in ("same_hash", "changed_hash", "cross_tenant", "fail_closed"):
        _require(pure_sources["test_ingestion_idempotency.py"], marker, "ingestion idempotency tests")
    for marker in ("malformed", "empty", "mime", "network_client"):
        _require(pure_sources["test_ing006_document_parser_adapters.py"], marker, "parser tests")
    for marker in ("quarantined", "credential", "invisible", "no_network"):
        _require(pure_sources["test_ing008_document_security_scan.py"], marker, "document security tests")
    for name, source in probe_sources.items():
        assert "sqlite3" not in source.lower(), f"{name} imports sqlite3"
    return {
        "status": "PASS",
        "task_id": "EVAL-015",
        "database": "postgresql",
        "sqlite": "not_used",
        "coverage": {
            "success": True,
            "invalid_input": True,
            "permission_denial": True,
            "empty_data": True,
            "dependency_failure": True,
        },
        "postgres_probes": [str(path.relative_to(ROOT)).replace("\\", "/") for _, path in PROBES],
        "pure_contract_tests": [str(path.relative_to(ROOT)).replace("\\", "/") for path in PURE_TESTS],
        "excluded_sqlite_fixture": "backend/tests/ai/test_kui_012_document_actions.py",
        "production_database_write": False,
        "source_sha256": {
            "contract": hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            **{name: hashlib.sha256(source.encode("utf-8")).hexdigest() for name, source in probe_sources.items()},
        },
    }


def _postgres_environment() -> dict[str, str]:
    env = os.environ.copy()
    database_url = env.get("DATABASE_URL", "")
    if not database_url.lower().startswith(("postgresql://", "postgres://")):
        raise RuntimeError("EVAL-015 requires PostgreSQL DATABASE_URL; SQLite is forbidden")
    env["PYTHONPATH"] = str(ROOT / "backend")
    return env


def _parse_json(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise AssertionError("probe did not emit JSON")
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise AssertionError("probe JSON is not an object")
    return value


def _run_probe(path: Path, env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run([sys.executable, str(path)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=150, check=False)
    if completed.returncode != 0:
        raise AssertionError(f"{path.name} failed: {completed.stdout[-600:]} {completed.stderr[-600:]}")
    report = _parse_json(completed.stdout)
    database = str(report.get("database") or report.get("backend") or "").lower()
    if database not in {"postgresql", "postgres"} and report.get("postgresql") is not True:
        raise AssertionError(f"{path.name} did not report PostgreSQL")
    return report


def _run_pure_tests(env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:conftest", *(str(path) for path in PURE_TESTS), "-q", "-p", "no:cacheprovider"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(f"pure EVAL-015 tests failed: {completed.stdout[-1200:]} {completed.stderr[-1200:]}")
    match = re.search(r"(\d+) passed", completed.stdout)
    if not match:
        raise AssertionError(f"pure EVAL-015 tests did not report pass count: {completed.stdout}")
    return {"status": "PASS", "database": "none", "sqlite": "not_used", "passed": int(match.group(1))}


def run_postgresql_input_failure_matrix() -> dict[str, Any]:
    env = _postgres_environment()
    reports = {name: _run_probe(path, env) for name, path in PROBES}
    provider = reports["provider_acl"]
    reindex = reports["reindex_dependency"]
    duplicate = reports["duplicate_content"]
    baseline = reports["v1_empty"]
    if not provider.get("rollback") or not provider.get("acl_tenant_scoped") or not provider.get("route_fallback"):
        raise AssertionError("provider/ACL PostgreSQL probe did not cover permission and dependency boundaries")
    if reindex.get("status") != "PASS" or not reindex.get("provider_failure_atomic") or not reindex.get("changed_projection"):
        raise AssertionError("reindex PostgreSQL success/dependency matrix failed")
    if duplicate.get("status") != "PASS" or not duplicate.get("duplicate_same_tenant_rejected") or not duplicate.get("rollback"):
        raise AssertionError("duplicate-content PostgreSQL invalid-input matrix failed")
    cases = {str(case.get("id")): case for case in baseline.get("cases", [])}
    metrics = baseline.get("metrics") or {}
    if cases.get("Q07", {}).get("returned_ids") != []:
        raise AssertionError("empty/no-match PostgreSQL V1 case returned data")
    if float(metrics.get("retrieval_accuracy", -1)) != 1.0 or float(metrics.get("citation_accuracy", -1)) != 1.0:
        raise AssertionError("V1 success/empty baseline regressed")
    pure = _run_pure_tests(env)
    return {
        "status": "PASS",
        "task_id": "EVAL-015",
        "database": "postgresql",
        "sqlite": "not_used",
        "probes": reports,
        "pure_tests": pure,
        "success": {"status": "PASS", "changed_projection": True},
        "invalid_input": {"status": "PASS", "duplicate_same_tenant_rejected": True},
        "permission_denial": {"status": "PASS", "acl_tenant_scoped": True},
        "empty_data": {"status": "PASS", "case": "Q07", "returned_ids": []},
        "dependency_failure": {"status": "PASS", "provider_failure_atomic": True},
        "production_database_write": False,
        "rollback_or_cleanup": True,
    }


def main() -> int:
    coverage = validate_input_failure_coverage()
    matrix = run_postgresql_input_failure_matrix()
    output = {**coverage, "matrix": matrix, "rollback_or_cleanup": True}
    REPORT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
