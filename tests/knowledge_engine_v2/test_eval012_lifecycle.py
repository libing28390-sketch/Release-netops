"""EVAL-012 PostgreSQL-only lifecycle gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[2]
_SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_eval012_lifecycle_check.py"
_SPEC = importlib.util.spec_from_file_location("eval012_lifecycle", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_eval012_lifecycle_contract_is_postgresql_only() -> None:
    report = _MODULE.validate_lifecycle_contract()
    assert report["status"] == "PASS"
    assert report["task_id"] == "EVAL-012"
    assert report["database"] == "postgresql"
    assert report["sqlite"] == "not_used"
    assert report["probe_count"] == 5
    assert report["probes"] == ["source", "document", "version", "chunk", "reindex"]
    assert report["production_write"] is False


def test_eval012_postgresql_lifecycle_probes_pass_and_cleanup() -> None:
    report = _MODULE.run_postgresql_lifecycle_probes()
    assert report["status"] == "PASS"
    assert report["database"] == "postgresql"
    assert report["sqlite"] == "not_used"
    assert report["probe_count"] == 5
    assert report["rollback_or_cleanup"] is True
    assert all(isinstance(item, dict) for item in report["probes"].values())
