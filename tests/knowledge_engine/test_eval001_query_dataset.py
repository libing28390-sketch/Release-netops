"""EVAL-001 frozen Knowledge Engine dataset gate; no database fixture is involved."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).parents[2] / "scripts" / "knowledge_eval_dataset_check.py"
_SPEC = importlib.util.spec_from_file_location("eval001_dataset_check", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_eval001_frozen_dataset_has_120_balanced_cases() -> None:
    report = _MODULE.validate_dataset()
    assert report["status"] == "PASS"
    assert report["database"] == "none"
    assert report["sqlite"] == "not_used"
    assert report["case_count"] == 120
    assert set(report["query_type_counts"].values()) == {12}
    assert set(report["intent_counts"].values()) == {20}
    assert set(report["vendor_intent_counts"].values()) == {9}
    assert set(report["ambiguous_intent_counts"].values()) == {2}
    assert report["secrets"] is False
