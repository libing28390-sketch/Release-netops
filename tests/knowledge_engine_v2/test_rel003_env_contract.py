from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "knowledge_engine_v2_rel003_env_contract",
    ROOT / "scripts" / "knowledge_engine_v2_rel003_env_contract.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_rel003_contract_and_env_gate_pass() -> None:
    contract = MODULE.load_contract()
    assert contract["task_id"] == "REL-003"
    report = MODULE.run_gate()
    assert report["status"] == "PASS"
    assert all(report["checks"].values())
    assert report["details"]["production_database_write"] is False
    assert report["details"]["sqlite"] == "forbidden_for_acceptance"
