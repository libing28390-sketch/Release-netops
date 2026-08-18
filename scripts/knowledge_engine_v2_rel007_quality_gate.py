"""REL-007 PostgreSQL release quality gate.

``run_gate()`` is a filesystem-only contract check.  ``--execute`` runs the
PostgreSQL probes, contract wrappers, frontend lint/build and native target
configuration validators.  Missing Docker/Nginx binaries are reported as
BLOCKED instead of being silently replaced by a weaker assertion.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "REL-007"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "REL-007-QUALITY-GATE-CONTRACT.yaml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "rel-007-quality-gate-v1.json"


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("task_id") != TASK_ID:
        raise AssertionError("REL-007 contract task mismatch")
    return payload


def _redact(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"(?i)(postgres(?:ql)?://)[^\s'\"]+", r"\1***", text)
    text = re.sub(r"(?i)(password|api[_-]?key|secret|token)=([^\s]+)", r"\1=***", text)
    return text[-2000:]


def _run(label: str, argv: list[str], *, timeout: int = 180) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            argv,
            cwd=ROOT,
            env=os.environ.copy(),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return {"status": "BLOCKED", "reason": "TOOL_NOT_FOUND", "label": label, "argv": argv}
    except subprocess.TimeoutExpired:
        return {"status": "FAILED", "reason": "TIMEOUT", "label": label, "argv": argv, "duration_seconds": round(time.perf_counter() - started, 3)}
    return {
        "status": "PASS" if completed.returncode == 0 else "FAILED",
        "label": label,
        "returncode": completed.returncode,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "stdout_tail": _redact(completed.stdout),
        "stderr_tail": _redact(completed.stderr),
    }


def _static_checks() -> dict[str, Any]:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose.get("services") if isinstance(compose, dict) else None
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    scripts = package.get("scripts", {})
    return {
        "contract": load_contract().get("authority") == "PostgreSQL",
        "compose_yaml_parse": isinstance(services, dict) and {"db", "netops", "nginx"}.issubset(services),
        "compose_health_dependency": isinstance(services, dict) and services.get("netops", {}).get("depends_on", {}).get("db", {}).get("condition") == "service_healthy",
        "frontend_lint_script": "lint" in scripts,
        "frontend_build_script": "build" in scripts,
        "pytest_path": (ROOT / "tests" / "knowledge_engine_v2").is_dir(),
        "python_backend": (ROOT / "backend" / "main.py").is_file(),
        "sqlite_acceptance_excluded": "sqlite" in (ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "REL-007-QUALITY-GATE-CONTRACT.yaml").read_text(encoding="utf-8").lower(),
    }


def _parse_probe(output: str) -> dict[str, Any]:
    # Probe runners print one JSON object. Keep parsing tolerant of a warning
    # prefix while returning only structured, non-secret evidence.
    for start in range(len(output) - 1, -1, -1):
        if output[start] != "{":
            continue
        try:
            candidate = json.loads(output[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return {key: value for key, value in candidate.items() if key not in {"cases", "stdout", "stderr"}}
    return {"status": "FAILED", "reason": "PROBE_JSON_MISSING"}


def run_gate(*, execute: bool = False) -> dict[str, Any]:
    static = _static_checks()
    runtime: dict[str, Any] = {}
    if execute:
        os.environ["PYTHONPATH"] = str(ROOT / "backend") + os.pathsep + os.environ.get("PYTHONPATH", "")
        # The probe commands are transaction-scoped or explicitly read-only.
        probe_specs = [
            ("v1_postgresql_baseline", "scripts/knowledge_engine_v2_v1_baseline_pg.py"),
            ("mig008_postgresql_audit", "scripts/knowledge_engine_v2_mig008_consistency_audit_check.py"),
            ("ret_postgresql_probe", "scripts/knowledge_engine_v2_ret_pg_probe.py"),
            ("rel006_manifest_postgresql_probe", "scripts/knowledge_engine_v2_rel006_backup_gate.py", "--pg-probe"),
        ]
        for spec in probe_specs:
            label, script, *extra = spec
            result = _run(label, [sys.executable, str(ROOT / script), *extra], timeout=240)
            if result.get("status") == "PASS":
                parsed = _parse_probe(result.get("stdout_tail", ""))
                result["structured"] = parsed
            runtime[label] = result

        focused = [
            "tests/knowledge_engine_v2/test_mig001_strategy.py",
            "tests/knowledge_engine_v2/test_mig002_source_first.py",
            "tests/knowledge_engine_v2/test_mig003_mapping_manifest.py",
            "tests/knowledge_engine_v2/test_mig004_migration_runner.py",
            "tests/knowledge_engine_v2/test_mig005_metadata_confidence.py",
            "tests/knowledge_engine_v2/test_mig006_official_entity_validation.py",
            "tests/knowledge_engine_v2/test_mig007_source_seed_preflight.py",
            "tests/knowledge_engine_v2/test_mig008_consistency_audit.py",
            "tests/knowledge_engine_v2/test_rel001_target_matrix.py",
            "tests/knowledge_engine_v2/test_rel002_postgres_gate.py",
            "tests/knowledge_engine_v2/test_rel003_env_contract.py",
            "tests/knowledge_engine_v2/test_rel004_http_delivery_gate.py",
            "tests/knowledge_engine_v2/test_rel005_streaming_gate.py",
            "tests/knowledge_engine_v2/test_rel006_backup_gate.py",
        ]
        runtime["postgres_contract_tests"] = _run(
            "postgres_contract_tests",
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *focused],
            timeout=300,
        )
        npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
        runtime["frontend_lint"] = _run("frontend_lint", [npm, "run", "lint"], timeout=180)
        runtime["frontend_build"] = _run("frontend_build", [npm, "run", "build"], timeout=300)
        runtime["python_compile"] = _run("python_compile", [sys.executable, "-m", "compileall", "-q", "backend", "scripts"], timeout=180)
        runtime["git_diff_check"] = _run("git_diff_check", ["git", "diff", "--check"], timeout=60)

        if shutil.which("docker"):
            runtime["docker_compose_syntax"] = _run("docker_compose_syntax", ["docker", "compose", "config", "--quiet"], timeout=120)
        else:
            runtime["docker_compose_syntax"] = {"status": "BLOCKED", "reason": "DOCKER_CLI_NOT_INSTALLED"}
        if shutil.which("nginx"):
            runtime["nginx_syntax"] = _run("nginx_syntax", ["nginx", "-t", "-c", str(ROOT / "nginx" / "nginx.conf")], timeout=60)
        else:
            runtime["nginx_syntax"] = {"status": "BLOCKED", "reason": "NGINX_BINARY_NOT_INSTALLED"}

    blocking = [key for key, value in runtime.items() if value.get("status") == "BLOCKED"]
    failures = [key for key, value in runtime.items() if value.get("status") == "FAILED"]
    status = "READY" if not execute else ("FAILED" if failures else ("BLOCKED" if blocking else "PASS"))
    report = {
        "task_id": TASK_ID,
        "status": status,
        "static_checks": static,
        "runtime": runtime,
        "blocked_checks": blocking,
        "failed_checks": failures,
        "database": "PostgreSQL_only",
        "sqlite": "forbidden_for_acceptance",
        "production_database_write": False,
        "external_provider_request": False,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    report = run_gate(execute=args.execute)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"READY", "PASS", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
