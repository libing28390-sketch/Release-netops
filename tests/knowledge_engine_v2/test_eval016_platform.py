"""EVAL-016 PostgreSQL-authority platform fixture gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_eval016_platform_check.py"
SPEC = importlib.util.spec_from_file_location("eval016_platform", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_eval016_contract_covers_three_vendor_mappings_and_read_only_boundary() -> None:
    report = MODULE.validate_platform_coverage()
    assert report["status"] == "PASS"
    assert report["task_id"] == "EVAL-016"
    assert report["database"] == "postgresql"
    assert report["sqlite"] == "not_used"
    assert report["fixture_database"] == "none"
    assert all(report["coverage"].values())


def test_eval016_fixture_matrix_and_postgresql_v1_authority_pass() -> None:
    report = MODULE.run_postgresql_platform_matrix()
    assert report["status"] == "PASS"
    assert report["database"] == "postgresql"
    assert report["sqlite"] == "not_used"
    assert report["fixture_tests"]["passed"] == 123
    assert report["v1_postgresql"]["rollback"] == "transaction_rollback"
    for key in ("huawei", "cisco", "h3c", "read_only_commands", "unknown_boundary"):
        assert report[key]["status"] == "PASS"
    assert report["rollback_or_cleanup"] is True
