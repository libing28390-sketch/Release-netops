"""REL-003 static configuration and secret-safety gate."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "REL-003"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "REL-003-ENV-CONTRACT.yaml"
ENV_EXAMPLE = ROOT / ".env.example"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "rel-003-env-contract-v1.json"

REQUIRED_KEYS = {
    "AI_ENABLED", "EXTERNAL_AI_ENABLED", "AI_KILL_SWITCH", "AI_SECURITY_VAULT_TTL_SECONDS",
    "AI_MAX_PAYLOAD_BYTES", "AI_PROVIDER_ALLOWLIST", "AI_DEBUG_PAYLOAD", "AI_OUTBOUND_PROXY_URL",
    "AI_PROVIDER_MAX_CONCURRENCY", "AI_TENANT_MAX_CONCURRENCY", "AI_USER_MAX_CONCURRENCY",
    "AI_CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS", "AI_CIRCUIT_FAILURE_THRESHOLD",
    "AI_CIRCUIT_COOLDOWN_SECONDS", "AI_HEALTH_BACKOFF_SECONDS", "AI_DAILY_BUDGET_USD",
    "AI_EMBEDDING_MODE", "AI_EMBEDDING_DIMENSIONS", "AI_RETRIEVAL_CACHE_ENABLED",
    "AI_RETRIEVAL_TRGM_THRESHOLD", "KNOWLEDGE_V2_ENABLED", "KNOWLEDGE_V2_SHADOW_READ",
    "KNOWLEDGE_V2_ROLLOUT_PERCENT", "KNOWLEDGE_V2_WRITE_ENABLED", "NETWORK_WRITE_ENABLED",
    "PRODUCTION_CREDENTIALS_ALLOWED", "AI_GATEWAY_MODE", "DATA_CLASSIFICATION",
    "DEVICE_CREDENTIAL_SOURCE", "KB_V2_SECRET_NAMESPACE",
}
ZERO_KEYS = {
    "AI_ENABLED", "EXTERNAL_AI_ENABLED", "AI_KILL_SWITCH", "AI_DEBUG_PAYLOAD",
    "AI_RETRIEVAL_CACHE_ENABLED", "KNOWLEDGE_V2_ENABLED", "KNOWLEDGE_V2_SHADOW_READ",
    "KNOWLEDGE_V2_ROLLOUT_PERCENT", "KNOWLEDGE_V2_WRITE_ENABLED", "NETWORK_WRITE_ENABLED",
    "PRODUCTION_CREDENTIALS_ALLOWED",
}
FORBIDDEN_KEY_NAMES = {"OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "API_KEY", "PROVIDER_API_KEY", "VAULT_TOKEN"}
SECRET_PATTERNS = re.compile(r"(?:sk_live_|sk-proj-|Bearer\s+|gho_|github_pat_|AKIA[0-9A-Z]{16})", re.IGNORECASE)
ASSIGNMENT_SECRET_PATTERN = re.compile(r"(?:=|:\s*)[\"']?" + SECRET_PATTERNS.pattern, re.IGNORECASE)
PLACEHOLDER_PATTERNS = re.compile(r"(?:replace-with|change-me|test-only|placeholder|example|your-|<.+?>)", re.IGNORECASE)


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("task_id") != TASK_ID:
        raise AssertionError("REL-003 contract task mismatch")
    return payload


def _parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _tracked_secret_scan() -> dict[str, Any]:
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=False, check=True,
        ).stdout.decode("utf-8", "replace").split("\0")
    except Exception as exc:
        return {"status": "BLOCKED", "error_type": type(exc).__name__, "files_scanned": 0, "matches": []}
    matches: list[str] = []
    scanned = 0
    for name in tracked:
        path_name = Path(name).as_posix()
        config_like = (
            path_name.startswith(".github/workflows/")
            or path_name in {"docker-compose.yml", "docker-compose.prod.yml"}
            or path_name.endswith((".env", ".env.local"))
        )
        if not name or name == ".env.example" or not config_like or name.endswith((".png", ".jpg", ".jpeg", ".svg", ".lock")):
            continue
        path = ROOT / name
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        if any(ASSIGNMENT_SECRET_PATTERN.search(line) for line in text.splitlines() if not line.lstrip().startswith("#")):
            matches.append(name)
    return {"status": "PASS" if not matches else "BLOCKED", "files_scanned": scanned, "matches": matches}


def run_gate() -> dict[str, Any]:
    load_contract()
    values = _parse_env(ENV_EXAMPLE.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_KEYS - values.keys())
    zero_violations = sorted(key for key in ZERO_KEYS if values.get(key, "").lower() not in {"0", "false", "no", "off"})
    forbidden_keys = sorted(key for key in values if key in FORBIDDEN_KEY_NAMES or key.endswith("_API_KEY"))
    suspicious_values = sorted(key for key, value in values.items() if SECRET_PATTERNS.search(value))
    placeholder_failures = sorted(
        key for key in ("POSTGRES_PASSWORD", "SECRET_KEY", "CREDENTIAL_ENCRYPTION_KEY")
        if key not in values or not PLACEHOLDER_PATTERNS.search(values[key])
    )
    allowlist = {item.strip() for item in values.get("AI_PROVIDER_ALLOWLIST", "").split(",") if item.strip()}
    expected_allowlist = {"deepseek", "openai", "openai_compatible", "azure_openai", "ollama", "local", "qwen"}
    code_checks = {
        "settings_provider_security": "AI_PROVIDER_ALLOWLIST" in (ROOT / "backend" / "core" / "config.py").read_text(encoding="utf-8"),
        "embedding_env_consumed": "AI_EMBEDDING_MODE" in (ROOT / "backend" / "ai" / "providers" / "embedding.py").read_text(encoding="utf-8"),
        "retrieval_flags_consumed": "AI_RETRIEVAL_CACHE_ENABLED" in (ROOT / "backend" / "ai" / "services" / "rag_retriever.py").read_text(encoding="utf-8"),
    }
    tracked_scan = _tracked_secret_scan()
    checks = {
        "required_keys": not missing,
        "safe_disabled_defaults": not zero_violations,
        "provider_allowlist": expected_allowlist.issubset(allowlist),
        "forbidden_key_names_absent": not forbidden_keys,
        "suspicious_values_absent": not suspicious_values,
        "placeholder_secrets": not placeholder_failures,
        "tracked_secret_scan": tracked_scan["status"] == "PASS",
        **code_checks,
    }
    status = "PASS" if all(checks.values()) else "BLOCKED"
    report = {
        "task_id": TASK_ID,
        "status": status,
        "reason_codes": sorted(
            (["ENV_REQUIRED_KEY_MISSING"] if missing else [])
            + (["ENV_UNSAFE_DEFAULT"] if zero_violations else [])
            + (["ENV_FORBIDDEN_SECRET_KEY"] if forbidden_keys else [])
            + (["ENV_SUSPICIOUS_SECRET_VALUE"] if suspicious_values else [])
            + (["ENV_PLACEHOLDER_MISSING"] if placeholder_failures else [])
            + (["TRACKED_SECRET_DETECTED"] if tracked_scan["status"] != "PASS" else [])
        ),
        "checks": checks,
        "details": {
            "missing_keys": missing,
            "zero_violations": zero_violations,
            "forbidden_keys": forbidden_keys,
            "suspicious_values": suspicious_values,
            "placeholder_failures": placeholder_failures,
            "tracked_secret_scan": tracked_scan,
            "database": "none",
            "production_database_write": False,
            "sqlite": "forbidden_for_acceptance",
        },
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(run_gate(), ensure_ascii=False, indent=2))
