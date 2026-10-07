"""EVAL-004 Knowledge Engine version-state gate; no database fixture is used."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).parents[2] / "scripts" / "knowledge_eval_version_coverage_check.py"
_SPEC = importlib.util.spec_from_file_location("eval004_version_coverage_check", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_eval004_covers_four_version_states() -> None:
    report = _MODULE.validate_versions()
    assert report["status"] == "PASS"
    assert report["class_counts"] == {"conflict": 12, "specified": 12, "unknown": 12, "unspecified": 12}
    assert len(report["unknown_case_ids"]) == 12
    assert set(report["unknown_vendor_intent_counts"].values()) == {1}
    assert report["database"] == "none"
    assert report["sqlite"] == "not_used"
    assert report["external_network"] == "not_used"
    assert report["secrets"] is False
