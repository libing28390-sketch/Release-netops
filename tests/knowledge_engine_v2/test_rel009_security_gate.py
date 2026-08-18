from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "knowledge_engine_v2_rel009_security_gate",
    ROOT / "scripts" / "knowledge_engine_v2_rel009_security_gate.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_rel009_static_security_contract_passes_without_emitting_secrets() -> None:
    report = MODULE.run_gate(include_runtime=False)
    assert report["status"] == "READY"
    assert all(report["static_checks"].values())
    assert report["database"] == "PostgreSQL_only"
    assert report["sqlite"] == "forbidden_for_acceptance"
    assert report["secret_values_emitted"] is False

