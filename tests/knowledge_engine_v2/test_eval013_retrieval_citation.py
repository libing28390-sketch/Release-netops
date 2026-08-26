"""EVAL-013 PostgreSQL-only retrieval and citation gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_eval013_retrieval_citation_check.py"
SPEC = importlib.util.spec_from_file_location("eval013_retrieval_citation", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_eval013_contract_is_postgresql_only_and_covers_all_boundaries() -> None:
    report = MODULE.validate_retrieval_citation_coverage()
    assert report["status"] == "PASS"
    assert report["task_id"] == "EVAL-013"
    assert report["database"] == "postgresql"
    assert report["sqlite"] == "not_used"
    assert all(report["coverage"].values())
    assert report["production_write"] is False


def test_eval013_postgresql_retrieval_and_baseline_probes_pass_and_roll_back() -> None:
    report = MODULE.run_postgresql_retrieval_probes()
    assert report["status"] == "PASS"
    assert report["database"] == "postgresql"
    assert report["sqlite"] == "not_used"
    assert report["rollback_or_cleanup"] is True
    assert report["no_match"]["status"] == "PASS"
    assert report["ambiguous"]["status"] == "PASS"
    assert report["version_conflict"]["status"] == "PASS"
