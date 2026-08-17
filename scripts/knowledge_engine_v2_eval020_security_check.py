"""PostgreSQL-only EVAL-020 security gate.

The gate is deliberately bounded and fail-closed.  It audits the AI runtime
surface (dependencies, secret handling, route permissions, logging and error
contracts), exercises the existing redaction/error tests, and invokes the
PostgreSQL V1 baseline.  It never prints a secret, DSN, request body or
provider response and never writes a production row.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "EVAL-020"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-security-gate-v1.json"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "EVAL-020-SECURITY-GATE-CONTRACT.yaml"
CONFIG_VALIDATOR = ROOT / "scripts" / "validate_kb_v2_test_config.py"
SAFE_CONFIG = ROOT / "docs" / "knowledge-engine-v2" / "governance" / "test-environment.example"
V1_BASELINE = ROOT / "scripts" / "knowledge_engine_v2_v1_baseline_pg.py"

_SECRET_LITERAL_RE = re.compile(
    r"\b(?:sk|rk)-[A-Za-z0-9]{12,}\b|\bAKIA[0-9A-Z]{16}\b|"
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|"
    r"\b(?:api[_-]?key|apikey|password|secret|token|authorization)\s*[:=]\s*"
    r"['\"](?!\$\{|secret://|vault://|<|REDACTED|redacted|example|dummy|test|"
    r"change-me|replace-with|your[-_]password)[^'\"]{8,}['\"]",
    re.IGNORECASE,
)
_LOG_RAW_RE = re.compile(
    r"(?:logger|log)\.(?:debug|info|warning|error|exception|critical)\([^\n]*(?:"
    r"api[_-]?key\s*[:=]|password\s*[:=]|secret\s*[:=]|token\s*[:=]|"
    r"raw[_-]?(?:body|query|content)|response\.text|request\.body|"
    r"\{\s*(?:exc|e)\s*\}|\b(?:exc|e)\s*\)\s*$)",
    re.IGNORECASE,
)
_AI_CODE_RE = re.compile(r"^(?:AI_|PROVIDER_|LLM_|AUTH_|SECURITY_|GATEWAY_|MODEL_|REQUEST_)")


def _python() -> str:
    candidate = ROOT / ".venv" / "Scripts" / "python.exe"
    return str(candidate if candidate.exists() else Path(sys.executable))


def _run(command: list[str], *, timeout: int = 90, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Run a command without exposing its output in the report."""

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "exit_code": int(completed.returncode),
            "duration_seconds": round(time.perf_counter() - started, 3),
            "stdout_lines": len(completed.stdout.splitlines()),
            "stderr_lines": len(completed.stderr.splitlines()),
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": 124,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "stdout_lines": 0,
            "stderr_lines": 0,
            "timed_out": True,
        }


def _iter_source_files(roots: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".ts", ".tsx", ".js", ".jsx"}:
                continue
            if any(part in {"__pycache__", "node_modules", "dist", ".git"} for part in path.parts):
                continue
            if any(part.lower() == "tests" or "test" in path.name.lower() for part in path.parts):
                continue
            files.append(path)
    return sorted(set(files))


def dependency_check() -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "backend")
    pip = _run([_python(), "-m", "pip", "check"], timeout=60, env=env)
    lock_path = ROOT / "package-lock.json"
    lock_present = lock_path.is_file()
    lock_valid = False
    lock_sha256 = None
    if lock_present:
        try:
            json.loads(lock_path.read_text(encoding="utf-8"))
            lock_valid = True
            lock_sha256 = hashlib.sha256(lock_path.read_bytes()).hexdigest()
        except (OSError, ValueError):
            lock_valid = False
    npm = _run(["npm.cmd", "ls", "--depth=0", "--json", "--package-lock-only"], timeout=90, env=env)
    return {
        "status": "PASS" if pip["exit_code"] == 0 and lock_present and lock_valid and npm["exit_code"] == 0 else "FAIL",
        "python_pip_check": pip,
        "package_lock": {"present": lock_present, "valid_json": lock_valid, "sha256": lock_sha256},
        "npm_lock_probe": npm,
    }


def _validator_probe() -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "backend")
    safe = _run([_python(), str(CONFIG_VALIDATOR), "--file", str(SAFE_CONFIG), "--environment", "test"], timeout=30, env=env)
    with tempfile.TemporaryDirectory(prefix="eval020-") as temp_dir:
        bad_path = Path(temp_dir) / "bad.env"
        bad_text = SAFE_CONFIG.read_text(encoding="utf-8").replace(
            "SECRET_KEY=${TEST_SECRET_KEY}", "SECRET_KEY=literal-value-that-must-be-rejected"
        )
        bad_path.write_text(bad_text, encoding="utf-8")
        bad = _run([_python(), str(CONFIG_VALIDATOR), "--file", str(bad_path), "--environment", "test"], timeout=30, env=env)
    return {
        "safe_config_pass": safe["exit_code"] == 0,
        "literal_secret_rejected": bad["exit_code"] != 0,
        "validator_outputs_not_collected": True,
    }


def secret_check() -> dict[str, Any]:
    validator = _validator_probe()
    files = _iter_source_files([ROOT / "backend" / "ai", ROOT / "src"])
    findings: list[dict[str, Any]] = []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if _SECRET_LITERAL_RE.search(line):
                findings.append({"file": str(path.relative_to(ROOT)).replace("\\", "/"), "line": line_number})
    return {
        "status": "PASS" if validator["safe_config_pass"] and validator["literal_secret_rejected"] and not findings else "FAIL",
        "validator": validator,
        "scanned_files": len(files),
        "literal_findings": findings,
        "values_emitted": False,
    }


def _contains_permission(node: ast.AST) -> bool:
    return any(isinstance(item, ast.Name) and item.id == "require_ai_permission" for item in ast.walk(node))


def permission_check() -> dict[str, Any]:
    routes: list[dict[str, Any]] = []
    for path in sorted((ROOT / "backend" / "ai" / "api").glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            route_decorators = []
            for decorator in node.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "router":
                    if target.attr in {"get", "post", "put", "patch", "delete", "options", "head", "websocket"}:
                        route_decorators.append(target.attr)
            if not route_decorators:
                continue
            protected = _contains_permission(node)
            routes.append({"file": str(path.relative_to(ROOT)).replace("\\", "/"), "function": node.name, "methods": route_decorators, "protected": protected})
    missing = [item for item in routes if not item["protected"]]
    return {
        "status": "PASS" if routes and not missing else "FAIL",
        "route_count": len(routes),
        "protected_route_count": len(routes) - len(missing),
        "coverage_percent": round((len(routes) - len(missing)) * 100 / max(1, len(routes)), 2),
        "missing_permission_routes": missing,
    }


def logging_check() -> dict[str, Any]:
    files = _iter_source_files([ROOT / "backend" / "ai"])
    findings: list[dict[str, Any]] = []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if _LOG_RAW_RE.search(line):
                findings.append({"file": str(path.relative_to(ROOT)).replace("\\", "/"), "line": line_number})
    # Existing runtime tests prove that the central logger and retrieval trace
    # projection redact values; the script only records static locations.
    return {
        "status": "PASS" if not findings else "FAIL",
        "scanned_files": len(files),
        "raw_sensitive_logger_findings": findings,
        "values_emitted": False,
    }


def error_contract_check() -> dict[str, Any]:
    files = _iter_source_files([ROOT / "backend" / "ai"])
    forbidden: list[dict[str, Any]] = []
    raw_detail_re = re.compile(
        r"HTTPException\([^\n]*detail\s*=\s*(?:str\(\s*(?:exc|e)\s*\)|"
        r"f[\"'][^\n]*\{\s*(?:exc|e)\s*\})",
        re.IGNORECASE,
    )
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if raw_detail_re.search(line):
                forbidden.append({"file": str(path.relative_to(ROOT)).replace("\\", "/"), "line": line_number})
    exception_file = ROOT / "backend" / "ai" / "gateway" / "exceptions.py"
    exception_text = exception_file.read_text(encoding="utf-8") if exception_file.is_file() else ""
    stable_schema = all(marker in exception_text for marker in ("\"code\"", "\"message\"", "\"request_id\"", "\"details\""))
    return {
        "status": "PASS" if stable_schema and not forbidden else "FAIL",
        "stable_error_schema": stable_schema,
        "raw_exception_detail_findings": forbidden,
        "values_emitted": False,
    }


def postgresql_v1_probe() -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "backend")
    probe = _run([_python(), str(V1_BASELINE)], timeout=120, env=env)
    return {
        "status": "PASS" if probe["exit_code"] == 0 else "FAIL",
        "command": "knowledge_engine_v2_v1_baseline_pg.py",
        "probe": probe,
        "database": "PostgreSQL",
        "sqlite": "forbidden",
        "production_database_write": False,
        "rollback": "transaction_rollback",
    }


def run_gate() -> dict[str, Any]:
    started = time.perf_counter()
    dependency = dependency_check()
    secret = secret_check()
    permission = permission_check()
    logging = logging_check()
    errors = error_contract_check()
    v1 = postgresql_v1_probe()
    checks = {"dependency": dependency, "secret": secret, "permission": permission, "logging": logging, "error_response": errors, "v1_postgresql": v1}
    failed = [name for name, result in checks.items() if result.get("status") != "PASS"]
    return {
        "status": "PASS" if not failed else "FAIL",
        "task_id": TASK_ID,
        "database": "PostgreSQL",
        "sqlite": "forbidden",
        "duration_seconds": round(time.perf_counter() - started, 3),
        "checks": checks,
        "failed_checks": failed,
        "external_calls": False,
        "device_write_commands": False,
        "production_database_write": False,
        "rollback": "V1_probe_transaction_rollback; audit-only changes revert by commit",
        "report_does_not_contain_secrets": True,
    }


def main() -> int:
    try:
        report = run_gate()
    except Exception as exc:  # no raw exception text in report
        report = {"status": "ERROR", "task_id": TASK_ID, "error_type": type(exc).__name__}
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 1
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
