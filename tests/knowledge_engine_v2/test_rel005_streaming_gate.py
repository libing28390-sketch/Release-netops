from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "knowledge_engine_v2_rel005_streaming_gate",
    ROOT / "scripts" / "knowledge_engine_v2_rel005_streaming_gate.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_rel005_no_buffer_delivery_contract_pass() -> None:
    contract = MODULE.load_contract()
    assert contract["authority"] == "Nginx_Docker_Desktop"
    report = MODULE.run_gate()
    assert report["status"] == "PASS"
    assert all(report["checks"].values())
    assert report["production_database_write"] is False
    assert report["sqlite"] == "forbidden_for_acceptance"
