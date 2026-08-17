"""Contract and fault-injection tests for EVAL-019."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_eval019_stability.py"
SPEC = importlib.util.spec_from_file_location("eval019_stability", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_eval019_contract_constants_are_bounded_and_postgresql_only() -> None:
    assert MODULE.TASK_ID == "EVAL-019"
    assert MODULE.IMPORT_CYCLES == 100
    assert MODULE.REINDEX_ROWS == 1000
    assert MODULE.SSE_STREAM_CYCLES == 100
    assert MODULE.PROVIDER_CYCLES == 100
    assert "SQLite is forbidden" in SCRIPT.read_text(encoding="utf-8")


def test_eval019_import_and_sse_recovery_smoke() -> None:
    imports = MODULE.run_import_soak(3)
    assert imports["completed"] == 3
    assert imports["terminal_failures"] == 0
    sse = MODULE.run_sse_soak(3)
    assert sse["emitted_events"] == 12
    assert sse["replayed_events"] == 6
    assert sse["duplicate_events"] == 0
    assert sse["out_of_order_streams"] == 0


def test_eval019_provider_fault_recovery_smoke() -> None:
    provider = asyncio.run(MODULE.run_provider_soak(3))
    assert provider["successes"] == 3
    assert provider["transient_failures_injected"] == 1
    assert provider["circuit_open_after_recovery"] is False
    assert provider["external_provider_request"] is False
