"""REL-001 static release-target impact matrix.

This gate is deliberately filesystem-only.  It does not start a service,
connect to PostgreSQL, call a Provider, build a container, or mutate release
artifacts.  Runtime/startup verification belongs to target-specific release
gates; this task proves that all four target paths are wired to the same
PostgreSQL/V1-safe contract before packaging.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "REL-001"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "REL-001-TARGET-MATRIX-CONTRACT.yaml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "rel-001-target-matrix-v1.json"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(_read(CONTRACT_PATH))
    if not isinstance(payload, dict) or payload.get("task_id") != TASK_ID:
        raise AssertionError("REL-001 contract task mismatch")
    if payload.get("authority") != "PostgreSQL" or payload.get("sqlite") != "forbidden_for_acceptance":
        raise AssertionError("REL-001 must be PostgreSQL-only")
    if payload.get("production_database_write") is not False:
        raise AssertionError("REL-001 is read-only")
    return payload


def _exists(relative: str) -> bool:
    return (ROOT / relative).exists()


def _required(relative_paths: list[str]) -> dict[str, bool]:
    return {path: _exists(path) for path in relative_paths}


def _placeholder_scan() -> dict[str, Any]:
    text = _read(ROOT / ".env.example")
    forbidden = re.compile(r"(?i)(sk-[a-z0-9]{16,}|bearer\s+[a-z0-9._-]{12,}|-----begin\s+[^\n]+private key-----)")
    matches = forbidden.findall(text)
    return {"status": "PASS" if not matches else "FAIL", "matches": len(matches)}


def build_matrix() -> dict[str, Any]:
    package = json.loads(_read(ROOT / "package.json"))
    scripts = package.get("scripts") or {}
    dockerfile = _read(ROOT / "Dockerfile")
    compose = _read(ROOT / "docker-compose.yml")
    workflow_dir = ROOT / ".github" / "workflows"
    workflows = sorted(path.name for path in workflow_dir.glob("*.yml"))

    windows_files = _required(["start.bat", "NetOps.exe", "desktop/launcher.py", "backend/main.py", ".env.example"])
    ubuntu_files = _required(["deploy-ubuntu.sh", "backend/main.py", ".env.example", "nginx/nginx.conf"])
    compose_files = _required(["Dockerfile", "docker-compose.yml", "nginx/Dockerfile", "nginx/nginx.conf", ".env.example"])
    ci_files = _required([".github/workflows/backend-pytest-check.yml", ".github/workflows/frontend-build-check.yml", ".github/workflows/knowledge-engine-v2-eval.yml", ".github/workflows/release.yml"])

    python_match = re.search(r"^FROM\s+python:(\d+\.\d+)", dockerfile, flags=re.MULTILINE)
    python_runtime = python_match.group(1) if python_match else None
    compose_postgres = bool(re.search(r"^\s*db:\s*$", compose, flags=re.MULTILINE) and "postgresql://" in compose)
    ci_text = "\n".join(_read(workflow_dir / name) for name in workflows)
    ci_postgres = "DATABASE_URL: postgresql://" in ci_text and "postgres:" in ci_text
    ci_v2_off = all(value in ci_text for value in ('KNOWLEDGE_V2_ENABLED: "false"', 'KNOWLEDGE_V2_SHADOW_READ: "false"', 'KNOWLEDGE_V2_ROLLOUT_PERCENT: "0"'))
    v1_rollback = _exists("docs/knowledge-engine-v2/architecture/MIG-013-FAST-ROLLBACK-CONTRACT.yaml") or _exists("docs/knowledge-engine-v2/evidence/MIG-013.md")
    target_checks = {
        "windows_desktop": {"files": windows_files, "entrypoint": "start.bat -> NetOps.exe or desktop/launcher.py", "status": all(windows_files.values())},
        "ubuntu_native": {"files": ubuntu_files, "entrypoint": "deploy-ubuntu.sh", "status": all(ubuntu_files.values())},
        "docker_compose": {"files": compose_files, "entrypoint": "docker compose up (db -> netops -> nginx)", "postgres_service": compose_postgres, "python_runtime": python_runtime, "status": all(compose_files.values()) and compose_postgres and python_runtime is not None and tuple(map(int, python_runtime.split("."))) >= (3, 11)},
        "ci": {"files": ci_files, "entrypoint": "GitHub Actions backend/frontend/eval/release workflows", "workflow_files": workflows, "postgres_service": ci_postgres, "v2_defaults_off": ci_v2_off, "status": all(ci_files.values()) and ci_postgres and ci_v2_off},
    }
    placeholders = _placeholder_scan()
    all_targets = all(item["status"] for item in target_checks.values())
    return {
        "status": "PASS" if all_targets and placeholders["status"] == "PASS" and v1_rollback else "FAIL",
        "task_id": TASK_ID,
        "authority": "PostgreSQL",
        "sqlite": "forbidden",
        "targets": target_checks,
        "package_start_scripts": {key: bool(scripts.get(key)) for key in ("start:win", "start:linux", "build", "lint")},
        "docker_runtime": python_runtime,
        "placeholder_scan": placeholders,
        "v1_default_and_rollback_contract": v1_rollback,
        "production_database_write": False,
        "external_calls": False,
        "report_redacted": True,
        "contract_sha256": _sha256(_read(CONTRACT_PATH)),
    }


def run_gate() -> dict[str, Any]:
    started = time.perf_counter()
    contract = load_contract()
    report = build_matrix()
    report["duration_seconds"] = round(time.perf_counter() - started, 3)
    report["contract_layers"] = sorted(contract)
    return report


def main() -> int:
    try:
        report = run_gate()
    except Exception as exc:
        report = {"status": "ERROR", "task_id": TASK_ID, "error_type": type(exc).__name__}
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
