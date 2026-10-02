"""EVAL-002 Knowledge Engine coverage gate; no database dependency."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).parents[2] / "scripts" / "knowledge_eval_intent_coverage_check.py"
_SPEC = importlib.util.spec_from_file_location("eval002_intent_coverage_check", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_eval002_covers_both_vendors_and_all_six_intents() -> None:
    report = _MODULE.validate_coverage()
    assert report["status"] == "PASS"
    assert report["track_count"] == 12
    assert report["query_example_count"] == 36
    assert set(report["track_case_counts"].values()) == {9}
    assert report["vendor_track_counts"] == {"Cisco": 6, "Huawei": 6}
    assert report["intent_track_counts"] == {"interface": 2, "ntp": 2, "ospf": 2, "route": 2, "ssh": 2, "vlan": 2}
    assert report["database"] == "none"
    assert report["sqlite"] == "not_used"
    assert report["external_network"] == "not_used"
    assert report["secrets"] is False
