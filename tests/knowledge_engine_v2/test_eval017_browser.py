"""EVAL-017 frontend/browser key-path gate with PostgreSQL authority."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_eval017_browser_check.py"
SPEC = importlib.util.spec_from_file_location("eval017_browser", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_eval017_contract_covers_all_browser_surfaces_and_safe_states() -> None:
    report = MODULE.validate_browser_coverage()
    assert report["status"] == "PASS"
    assert report["task_id"] == "EVAL-017"
    assert report["database"] == "postgresql"
    assert report["sqlite"] == "not_used"
    assert report["frontend_test_database"] == "none"
    assert set(report["browser_surfaces"]) == {"copilot", "providers", "models_and_routes", "knowledge_management", "security_gateway"}
    assert set(report["required_states"]) == {"loading", "success", "empty", "error", "permission_boundary", "narrow_layout"}


def test_eval017_frontend_and_postgresql_v1_gate_pass() -> None:
    report = MODULE.run_gate()
    assert report["status"] == "PASS"
    assert report["frontend_tests"]["status"] == "PASS"
    assert report["frontend_tests"]["database"] == "none"
    assert report["frontend_tests"]["sqlite"] == "not_used"
    assert report["frontend_tests"]["tests_passed"] >= 45
    assert report["v1_postgresql"]["database"] == "postgresql"
    assert report["v1_postgresql"]["metrics"]["retrieval_accuracy"] == 1.0
    assert report["v1_postgresql"]["metrics"]["citation_accuracy"] == 1.0
    assert report["v1_postgresql"]["rollback"] == "transaction_rollback"
    assert report["live_browser_status"] == "USER_VERIFY_PENDING"
    assert report["rollback_or_cleanup"] is True
