"""EVAL-014 PostgreSQL-only migration and recovery gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_eval014_migration_check.py"
SPEC = importlib.util.spec_from_file_location("eval014_migration", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_eval014_contract_is_postgresql_only_and_covers_migration_matrix() -> None:
    report = MODULE.validate_migration_coverage()
    assert report["status"] == "PASS"
    assert report["task_id"] == "EVAL-014"
    assert report["database"] == "postgresql"
    assert report["sqlite"] == "not_used"
    assert all(report["coverage"].values())
    assert report["production_database_write"] is False


def test_eval014_real_postgresql_fresh_repeat_backfill_constraints_and_recovery_pass() -> None:
    report = MODULE.run_postgresql_migration_matrix()
    assert report["status"] == "PASS"
    assert report["database"] == "postgresql"
    assert report["sqlite"] == "not_used"
    assert report["temporary_database_dropped"] is True
    assert report["fresh_install"]["pending_after_second"] == []
    assert report["repeated_execution"]["second_applied"] == 0
    assert report["backfill"]["idempotent"] is True
    assert report["constraints"]["all_rejected"] is True
    assert report["rollback"]["status"] == "PASS"
    assert report["recovery"]["corrected_retry_applied"] == 2
    assert report["recovery"]["history_drift_fail_closed"] is True
