from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "knowledge_engine_v2_rel010_runbook_gate",
    ROOT / "scripts" / "knowledge_engine_v2_rel010_runbook_gate.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_rel010_static_runbook_gate_is_postgres_only_and_side_effect_free() -> None:
    contract = MODULE.load_contract()
    assert contract["authority"] == "PostgreSQL"
    report = MODULE.run_gate(pg_probe=False)
    assert report["status"] == "PASS"
    assert all(report["checks"].values())
    assert report["production_database_write"] is False
    assert report["reindex_executed_by_gate"] is False
    assert report["external_provider_request"] is False
    assert report["network_device_write"] is False
    assert report["sqlite"] == "forbidden_for_acceptance"
