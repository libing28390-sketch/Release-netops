"""Contract tests for the PostgreSQL-only EVAL-020 security gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_eval020_security_check.py"
SPEC = importlib.util.spec_from_file_location("eval020_security", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_eval020_contract_is_postgresql_only_and_secret_safe() -> None:
    contract = (ROOT / "docs/knowledge-engine-v2/architecture/EVAL-020-SECURITY-GATE-CONTRACT.yaml").read_text(encoding="utf-8")
    assert MODULE.TASK_ID == "EVAL-020"
    assert "database_under_test: PostgreSQL_only" in contract
    assert "sqlite: forbidden" in contract
    assert "production_database_write_false" in contract
    assert "PRIVATE KEY" in MODULE._SECRET_LITERAL_RE.pattern


def test_eval020_permission_inventory_protects_every_ai_route() -> None:
    result = MODULE.permission_check()
    assert result["status"] == "PASS"
    assert result["route_count"] >= 60
    assert result["coverage_percent"] == 100.0
    assert result["missing_permission_routes"] == []


def test_eval020_static_error_and_logging_contracts_are_clean() -> None:
    assert MODULE.logging_check()["status"] == "PASS"
    errors = MODULE.error_contract_check()
    assert errors["status"] == "PASS"
    assert errors["stable_error_schema"] is True


def test_eval020_validator_rejects_literal_secret_without_exposing_values() -> None:
    result = MODULE._validator_probe()
    assert result["safe_config_pass"] is True
    assert result["literal_secret_rejected"] is True
    assert result["validator_outputs_not_collected"] is True
