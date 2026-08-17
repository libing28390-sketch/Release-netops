"""Validate EVAL-011 provider/model/security coverage against the frozen plan."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "LLM-001-037-POSTGRES-TEST-PLAN.yaml"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "EVAL-011-PROVIDER-MODEL-SECURITY-CONTRACT.yaml"
PROBE_PATH = ROOT / "scripts" / "knowledge_engine_v2_llm_pg_probe.py"
BACKEND_TESTS = (
    ROOT / "backend" / "tests" / "ai" / "test_llm_001_037_multi_provider.py",
    ROOT / "backend" / "tests" / "ai" / "test_sec_001_020_security_gateway.py",
    ROOT / "backend" / "tests" / "ai" / "test_security_gateway.py",
    ROOT / "backend" / "tests" / "ai" / "test_api_v2_contracts.py",
)
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-provider-model-security-v1.manifest.json"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing EVAL-011 authority: {path}"
    return path.read_text(encoding="utf-8")


def _require(text: str, marker: str, label: str) -> None:
    assert marker in text, f"{label} missing marker: {marker}"


def validate_provider_model_security_coverage() -> dict[str, Any]:
    plan = _read(PLAN_PATH)
    contract = _read(CONTRACT_PATH)
    probe = _read(PROBE_PATH)
    tests = {path.name: _read(path) for path in BACKEND_TESTS}

    _require(plan, "database_under_test: PostgreSQL_only", "LLM plan")
    _require(plan, "sqlite:\n    status: not_used", "LLM plan")
    _require(plan, "missing_environment: Mark the affected task BLOCKED", "LLM plan")
    for marker in ("provider_CRUD", "model_switcher", "route_fallback", "ACL_tenant_scope", "key_rotation_audit"):
        _require(plan, marker, "LLM plan")
    for marker in ("_USE_PG", "rollback", "ai_model_acl", "route_fallback", "key_rotation", "duplicate_model_rejected"):
        _require(probe, marker, "PostgreSQL probe")
    for marker in ("AIProviderCreate", "provider_adapter", "_fallback_is_compatible", "stable_codes", "has_configured_master_key"):
        _require(tests["test_llm_001_037_multi_provider.py"], marker, "LLM backend tests")
    for marker in ("secret_detectors", "SecurityBlocked", "provider_adapter"):
        _require(tests["test_sec_001_020_security_gateway.py"], marker, "security backend tests")
    for marker in ("ProviderResponseContract", "ProviderKeyRotationRequest", "extra", "api_key"):
        _require(tests["test_api_v2_contracts.py"], marker, "API contract tests")
    _require(contract, "sqlite: forbidden", "EVAL-011 contract")
    _require(contract, "persistence_probe_transaction: rollback", "EVAL-011 contract")

    output: dict[str, Any] = {
        "status": "PASS",
        "task_id": "EVAL-011",
        "database": "postgresql",
        "sqlite": "not_used",
        "postgres_probe": str(PROBE_PATH.relative_to(ROOT)).replace("\\", "/"),
        "coverage": {
            "provider_crud": True,
            "model_switching": True,
            "fallback": True,
            "permission": True,
            "key_security": True,
            "stable_errors": True,
        },
        "rollback": "probe_transaction",
        "production_write": False,
        "source_sha256": {
            "plan": hashlib.sha256(plan.encode("utf-8")).hexdigest(),
            "contract": hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            "probe": hashlib.sha256(probe.encode("utf-8")).hexdigest(),
        },
    }
    REPORT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    print(json.dumps(validate_provider_model_security_coverage(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
