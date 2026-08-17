"""EVAL-009 reproducible offline evaluation command gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).parents[2] / "scripts" / "knowledge_engine_v2_eval_offline.py"
_SPEC = importlib.util.spec_from_file_location("eval009_offline_evaluation", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_eval009_offline_report_is_machine_readable_and_repeatable() -> None:
    first = _MODULE.run_offline_evaluation()
    second = _MODULE.run_offline_evaluation()
    assert first == second
    assert first["status"] == "PASS"
    assert first["component_count"] == 8
    assert [item["task_id"] for item in first["components"]] == [f"EVAL-{index:03d}" for index in range(1, 9)]
    assert all(item["status"] == "PASS" for item in first["components"])
    assert first["database"] == "none"
    assert first["sqlite"] == "not_used"
    assert first["external_network"] == "not_used"
    assert first["production_write"] is False
    assert first["reproducibility"]["generated_at"] is None
    assert first["reproducibility"]["random_seed"] is None
    assert len(first["report_sha256"]) == 64
