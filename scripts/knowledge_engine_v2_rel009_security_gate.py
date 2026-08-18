"""REL-009 production secret, permission, path and log-safety gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "REL-009"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "REL-009-SECURITY-PATH-CONTRACT.yaml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "rel-009-security-path-v1.json"
TRACKED_CONFIG_FILES = (".env.example", "docker-compose.yml", "Dockerfile", "nginx/nginx.conf", "scripts/deploy-docker.sh", "scripts/install-daily-backup.sh")
PLACEHOLDER_RE = re.compile(r"(?i)(replace-with|change-me|your[-_]?|example|dummy|test[-_]?only|__change_me__|supersecret|postgres:postgres)")
REAL_KEY_RE = re.compile(r"(?i)\b(?:sk-[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,})\b")


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("task_id") != TASK_ID:
        raise AssertionError("REL-009 contract task mismatch")
    return payload


def _env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _is_placeholder(value: str) -> bool:
    return not value.strip() or bool(PLACEHOLDER_RE.search(value))


def _hash12(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:12]


def _tracked_files() -> list[Path]:
    try:
        completed = subprocess.run(["git", "ls-files", *TRACKED_CONFIG_FILES], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        names = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    except OSError:
        names = list(TRACKED_CONFIG_FILES)
    return [ROOT / name for name in names if (ROOT / name).is_file()]


def _static_checks() -> dict[str, Any]:
    contract = load_contract()
    compose_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    nginx = (ROOT / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    logging = (ROOT / "backend" / "core" / "logging.py").read_text(encoding="utf-8")
    config = (ROOT / "backend" / "core" / "config.py").read_text(encoding="utf-8")
    configs_api = (ROOT / "backend" / "api" / "configs.py").read_text(encoding="utf-8")
    config_search = (ROOT / "backend" / "services" / "config_search_service.py").read_text(encoding="utf-8")
    tracked_text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in _tracked_files())
    parsed_compose = yaml.safe_load(compose_text)
    static_files_clean = not REAL_KEY_RE.search(tracked_text)
    known_default_absent = all(marker not in compose_text for marker in (
        "POSTGRES_PASSWORD:-postgres", "CREDENTIAL_ENCRYPTION_KEY:-change-me", "SECRET_KEY:-supersecret",
    ))
    return {
        "contract_postgresql": contract.get("authority") == "PostgreSQL",
        "compose_yaml": isinstance(parsed_compose, dict) and isinstance(parsed_compose.get("services"), dict),
        "compose_secret_defaults_absent": known_default_absent and "POSTGRES_PASSWORD:?" in compose_text and "SECRET_KEY:?" in compose_text and "CREDENTIAL_ENCRYPTION_KEY:?" in compose_text,
        "docker_non_root": "USER netops" in dockerfile and "useradd" in dockerfile,
        "runtime_dirs_declared": "/app/data/logs" in dockerfile and "/app/backup" in dockerfile,
        "network_write_disabled": "NETWORK_WRITE_ENABLED=0" in (ROOT / ".env.example").read_text(encoding="utf-8") and "PRODUCTION_CREDENTIALS_ALLOWED=0" in (ROOT / ".env.example").read_text(encoding="utf-8"),
        "log_sanitizer": all(marker in logging for marker in ("_SENSITIVE_PATTERNS", "_BEARER_PATTERN", "_PRIVATE_KEY_PATTERN", "SanitizeFilter")),
        "production_fail_closed": "validate_production_security" in config and "PRODUCTION_POSTGRES_REQUIRED" in config and "PRODUCTION_SECURITY_CONFIGURATION_INVALID" in config,
        "log_path_project_owned": '"data", "logs"' in logging and "os.path.join" in logging,
        "config_path_project_owned": "BACKUP_ROOT" in configs_api and "os.path.relpath" in configs_api,
        "path_traversal_boundary": "os.path.commonpath" in config_search or "commonpath" in configs_api,
        "public_static_excludes_sensitive_dirs": all(marker not in nginx for marker in ("/data/", "/backup/", "/logs/")),
        "backup_private_permissions": "chmod 600" in (ROOT / "scripts" / "install-daily-backup.sh").read_text(encoding="utf-8") and "chmod 600" in (ROOT / "scripts" / "deploy-docker.sh").read_text(encoding="utf-8"),
        "tracked_examples_are_placeholder_safe": not any(PLACEHOLDER_RE.search(line) is None and re.search(r"(?i)(?:PASSWORD|SECRET|TOKEN|API[_-]?KEY)\s*=\s*[^$\s]", line) for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines() if "=" in line and not line.lstrip().startswith("#")),
    }


def _runtime_checks(*, include_runtime: bool) -> dict[str, Any]:
    if not include_runtime:
        return {"status": "NOT_RUN"}
    values = _env_file(ROOT / ".env")
    required = ("SECRET_KEY", "CREDENTIAL_ENCRYPTION_KEY", "POSTGRES_PASSWORD", "DATABASE_URL")
    missing_or_placeholder = [key for key in required if _is_placeholder(values.get(key, ""))]
    db_url = values.get("DATABASE_URL", "")
    parsed = urlparse(db_url)
    postgres_ok = db_url.lower().startswith(("postgresql://", "postgres://")) and bool(parsed.hostname) and not _is_placeholder(parsed.password or "")

    log_dir = (ROOT / "data" / "logs").resolve()
    backup_dir = (ROOT / "backup").resolve()
    paths_ok = log_dir.is_relative_to(ROOT.resolve()) and backup_dir.is_relative_to(ROOT.resolve())

    sanitizer_ok = False
    sanitizer_detail = "not_imported"
    try:
        from core.logging import _sanitize_log_value
        sample = "api_key=runtime-secret Bearer abc.def password=hidden"
        sanitized = _sanitize_log_value(sample)
        sanitizer_ok = "runtime-secret" not in sanitized and "abc.def" not in sanitized and "hidden" not in sanitized
        sanitizer_detail = "PASS" if sanitizer_ok else "FAIL"
    except Exception as exc:  # pragma: no cover - environment specific
        sanitizer_detail = type(exc).__name__

    mode_checks: dict[str, Any] = {"platform": os.name}
    if os.name != "nt":
        mode_checks["log_dir_not_world_writable"] = not log_dir.exists() or not (stat.S_IMODE(log_dir.stat().st_mode) & 0o002)
        mode_checks["backup_dir_not_world_writable"] = not backup_dir.exists() or not (stat.S_IMODE(backup_dir.stat().st_mode) & 0o002)
    else:
        mode_checks["posix_mode_check"] = "not_applicable_windows_acl_required"

    status = "BLOCKED" if missing_or_placeholder or not postgres_ok else ("PASS" if paths_ok and sanitizer_ok and all(value is True or value == "not_applicable_windows_acl_required" for key, value in mode_checks.items() if key != "platform") else "FAILED")
    return {
        "status": status,
        "missing_or_placeholder_keys": missing_or_placeholder,
        "postgres_url_scheme_ok": postgres_ok,
        "paths_project_owned": paths_ok,
        "log_sanitizer": sanitizer_detail,
        "filesystem_permissions": mode_checks,
        "secret_value_hashes": {key: _hash12(values.get(key, "")) if values.get(key) else None for key in required},
    }


def run_gate(*, include_runtime: bool = False) -> dict[str, Any]:
    static = _static_checks()
    runtime = _runtime_checks(include_runtime=include_runtime)
    if not all(static.values()):
        status = "FAILED"
    elif runtime["status"] in {"BLOCKED", "FAILED"}:
        status = runtime["status"]
    else:
        status = "READY" if not include_runtime else "PASS"
    report = {
        "task_id": TASK_ID,
        "status": status,
        "static_checks": static,
        "runtime": runtime,
        "database": "PostgreSQL_only",
        "sqlite": "forbidden_for_acceptance",
        "production_database_write": False,
        "external_provider_request": False,
        "secret_values_emitted": False,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", action="store_true")
    args = parser.parse_args()
    report = run_gate(include_runtime=args.runtime)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"READY", "PASS", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
