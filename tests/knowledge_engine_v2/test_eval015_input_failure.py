"""EVAL-015 PostgreSQL-only success/input/permission/empty/failure gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_eval015_input_failure_check.py"
SPEC = importlib.util.spec_from_file_location("eval015_input_failure", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_eval015_contract_is_postgresql_only_and_excludes_sqlite_fixture() -> None:
    report = MODULE.validate_input_failure_coverage()
    assert report["status"] == "PASS"
    assert report["task_id"] == "EVAL-015"
    assert report["database"] == "postgresql"
    assert report["sqlite"] == "not_used"
    assert all(report["coverage"].values())
    assert report["excluded_sqlite_fixture"].endswith("test_kui_012_document_actions.py")


def test_eval015_postgresql_matrix_covers_all_input_and_dependency_boundaries() -> None:
    report = MODULE.run_postgresql_input_failure_matrix()
    assert report["status"] == "PASS"
    assert report["database"] == "postgresql"
    assert report["sqlite"] == "not_used"
    assert report["pure_tests"]["passed"] == 69
    for key in ("success", "invalid_input", "permission_denial", "empty_data", "dependency_failure"):
        assert report[key]["status"] == "PASS"
    assert report["rollback_or_cleanup"] is True
