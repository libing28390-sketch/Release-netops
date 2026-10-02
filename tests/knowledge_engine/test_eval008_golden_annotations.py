"""EVAL-008 Knowledge Engine answer workflow gate; no database fixture is used."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).parents[2] / "scripts" / "knowledge_eval_golden_annotation_check.py"
_SPEC = importlib.util.spec_from_file_location("eval008_golden_annotation_check", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_eval008_freezes_reviewed_golden_answers_for_all_vendor_intents() -> None:
    report = _MODULE.validate_annotations()
    assert report["status"] == "PASS"
    assert report["annotation_count"] == 12
    assert report["citation_count"] == 12
    assert set(report["vendor_intent_counts"].values()) == {1}
    assert report["review_status_counts"] == {"frozen": 12}
    assert report["database"] == "none"
    assert report["sqlite"] == "not_used"
    assert report["external_network"] == "not_used"
    assert report["secrets"] is False
