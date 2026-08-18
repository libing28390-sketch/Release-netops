from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "knowledge_engine_v2_rel004_http_delivery_gate",
    ROOT / "scripts" / "knowledge_engine_v2_rel004_http_delivery_gate.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_rel004_static_sse_proxy_and_body_limit_contract_pass() -> None:
    contract = MODULE.load_contract()
    assert contract["authority"] == "FastAPI_and_Nginx"
    report = MODULE.run_gate()
    assert report["status"] == "PASS"
    assert all(report["checks"].values())
    assert report["production_database_write"] is False
    assert report["sqlite"] == "forbidden_for_acceptance"
