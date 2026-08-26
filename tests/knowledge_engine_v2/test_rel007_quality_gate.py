from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "knowledge_engine_v2_rel007_quality_gate",
    ROOT / "scripts" / "knowledge_engine_v2_rel007_quality_gate.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_rel007_static_quality_contract_is_ready_and_postgresql_only() -> None:
    report = MODULE.run_gate(execute=False)
    assert report["status"] == "READY"
    assert all(report["static_checks"].values())
    assert report["database"] == "PostgreSQL_only"
    assert report["sqlite"] == "forbidden_for_acceptance"
    assert report["production_database_write"] is False

