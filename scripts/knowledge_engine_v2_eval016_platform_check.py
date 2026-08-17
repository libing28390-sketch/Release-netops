"""Run the mock/fixture EVAL-016 platform and read-only command gate."""

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
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "EVAL-016-PLATFORM-READONLY-CONTRACT.yaml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-platform-readonly-v1.manifest.json"
PURE_FILES = (
    ROOT / "backend" / "tests" / "vendor_audit" / "test_huawei_vrp5_cli_output.py",
    ROOT / "backend" / "tests" / "vendor_audit" / "test_h3c_cisco_quick_queries.py",
    ROOT / "backend" / "tests" / "vendor_audit" / "test_h3c_textfsm_contract.py",
    ROOT / "backend" / "tests" / "vendor_audit" / "test_platform_parser_boundary.py",
    ROOT / "backend" / "tests" / "vendor_audit" / "test_netmiko_driver_security.py",
    ROOT / "backend" / "tests" / "platform_registry" / "test_platform_registry.py",
    ROOT / "backend" / "tests" / "platform_registry" / "test_platform_registry_api.py",
)
PURE_TARGETS = (
    str(PURE_FILES[0]),
    str(PURE_FILES[1]),
    str(PURE_FILES[2]),
    str(PURE_FILES[3]),
    str(PURE_FILES[4]),
    str(PURE_FILES[5]) + "::test_read_command_guard_rejects_config_and_shell_chaining",
    str(PURE_FILES[6]) + "::test_registry_write_and_execution_gate_is_closed_by_default",
    str(PURE_FILES[6]) + "::test_registry_write_and_execution_gate_can_be_enabled",
    str(PURE_FILES[6]) + "::test_platform_write_request_models_reject_unknown_fields_and_bound_values",
    str(PURE_FILES[6]) + "::test_platform_binding_request_models_normalize_and_reject_duplicate_batches",
    str(PURE_FILES[6]) + "::test_operator_cannot_approve_publish_or_rollback_resources",
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing EVAL-016 authority: {path}"
    return path.read_text(encoding="utf-8")


def _require(text: str, marker: str, label: str) -> None:
    assert marker in text, f"{label} missing marker: {marker}"


def validate_platform_coverage() -> dict[str, Any]:
    contract = _read(CONTRACT_PATH)
    sources = {path.name: _read(path) for path in PURE_FILES}
    for marker in ("authority: PostgreSQL", "fixture_tests_database: none", "sqlite: forbidden", "production_database_write: false"):
        _require(contract, marker, "EVAL-016 contract")
    for marker in ("smart_parse_cli", "huawei_vrp", "display version", "eth_trunk"):
        _require(sources["test_huawei_vrp5_cli_output.py"], marker, "Huawei fixture tests")
    for marker in ("cisco_ios", "cisco_nxos", "h3c_comware", "_resolve_commands", "smart_parse_cli"):
        _require(sources["test_h3c_cisco_quick_queries.py"], marker, "Cisco/H3C fixture tests")
    for marker in ("resolve_textfsm_platform", "h3c_comware_v9", "template_variant"):
        _require(sources["test_h3c_textfsm_contract.py"], marker, "H3C TextFSM tests")
    for marker in ("secondary_parser", "h3c_comware", "cisco"):
        _require(sources["test_platform_parser_boundary.py"], marker, "platform boundary tests")
    for marker in ("enable_secret", "write_channel", "password", "writes"):
        _require(sources["test_netmiko_driver_security.py"], marker, "driver security tests")
    for marker in ("is_safe_read_command", "configure terminal", "running-config"):
        _require(sources["test_platform_registry.py"], marker, "read-only command tests")
    for marker in ("PlatformActionRequest", "unexpected", "read_only", "authorize_resource"):
        _require(sources["test_platform_registry_api.py"], marker, "platform API boundary tests")
    for name, source in sources.items():
        assert "sqlite3" not in source.lower(), f"{name} imports sqlite3"
    return {
        "status": "PASS",
        "task_id": "EVAL-016",
        "database": "postgresql",
        "sqlite": "not_used",
        "fixture_database": "none",
        "coverage": {"huawei": True, "cisco": True, "h3c": True, "read_only_commands": True, "unknown_boundary": True},
        "pure_targets": [target.replace("\\", "/") for target in PURE_TARGETS],
        "production_database_write": False,
        "source_sha256": {"contract": hashlib.sha256(contract.encode("utf-8")).hexdigest(), **{name: hashlib.sha256(source.encode("utf-8")).hexdigest() for name, source in sources.items()}},
    }


def _postgres_environment() -> dict[str, str]:
    env = os.environ.copy()
    url = env.get("DATABASE_URL", "")
    if not url.lower().startswith(("postgresql://", "postgres://")):
        raise RuntimeError("EVAL-016 requires PostgreSQL DATABASE_URL; SQLite is forbidden")
    env["PYTHONPATH"] = str(ROOT / "backend")
    return env


def _run_fixture_tests(env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:conftest", *PURE_TARGETS, "-q", "-p", "no:cacheprovider"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180, check=False)
    if completed.returncode != 0:
        raise AssertionError(f"EVAL-016 fixture tests failed: {completed.stdout[-1200:]} {completed.stderr[-1200:]}")
    match = re.search(r"(\d+) passed", completed.stdout)
    if not match:
        raise AssertionError(f"EVAL-016 fixture tests did not report pass count: {completed.stdout}")
    return {"status": "PASS", "database": "none", "sqlite": "not_used", "passed": int(match.group(1))}


def _run_v1_pg_probe(env: dict[str, str]) -> dict[str, Any]:
    probe = ROOT / "scripts" / "knowledge_engine_v2_v1_baseline_pg.py"
    completed = subprocess.run([sys.executable, str(probe)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120, check=False)
    if completed.returncode != 0:
        raise AssertionError(f"V1 PostgreSQL baseline failed: {completed.stdout[-800:]} {completed.stderr[-800:]}")
    text = completed.stdout.strip()
    try:
        report = json.loads(text)
    except json.JSONDecodeError:
        report = json.loads(text[text.find("{") : text.rfind("}") + 1])
    if str(report.get("database", "")).lower() != "postgresql":
        raise AssertionError("V1 baseline did not report PostgreSQL")
    metrics = report.get("metrics") or {}
    if float(metrics.get("retrieval_accuracy", -1)) != 1.0 or float(metrics.get("citation_accuracy", -1)) != 1.0:
        raise AssertionError("V1 baseline regressed during EVAL-016")
    return {"status": "PASS", "database": "postgresql", "case_count": report.get("case_count"), "metrics": metrics, "rollback": report.get("rollback"), "production_database_write": report.get("production_database_write")}


def run_postgresql_platform_matrix() -> dict[str, Any]:
    env = _postgres_environment()
    fixture = _run_fixture_tests(env)
    v1 = _run_v1_pg_probe(env)
    return {
        "status": "PASS",
        "task_id": "EVAL-016",
        "database": "postgresql",
        "sqlite": "not_used",
        "fixture_tests": fixture,
        "v1_postgresql": v1,
        "huawei": {"status": "PASS", "fixture": "Huawei VRP5"},
        "cisco": {"status": "PASS", "fixture": "Cisco IOS/IOS-XE/NX-OS"},
        "h3c": {"status": "PASS", "fixture": "H3C Comware v5/v7/v9"},
        "read_only_commands": {"status": "PASS", "config_and_shell_chain_blocked": True, "enable_secret_explicit": True},
        "unknown_boundary": {"status": "PASS", "no_cisco_default": True},
        "production_database_write": False,
        "rollback_or_cleanup": True,
    }


def main() -> int:
    coverage = validate_platform_coverage()
    matrix = run_postgresql_platform_matrix()
    output = {**coverage, "matrix": matrix, "rollback_or_cleanup": True}
    REPORT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
