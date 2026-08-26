"""EVAL-006 quality-metric gate; no database fixture is used."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).parents[2] / "scripts" / "knowledge_engine_v2_eval_quality_metrics_check.py"
_SPEC = importlib.util.spec_from_file_location("eval006_quality_metrics_check", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_eval006_defines_quality_and_provenance_metrics() -> None:
    report = _MODULE.validate_quality_metrics()
    assert report["status"] == "PASS"
    assert report["metrics"] == [
        "product_match",
        "os_match",
        "version_match",
        "wrong_vendor_rate",
        "official_source_rate",
        "citation_accuracy",
    ]
    assert report["report"]["case_count"] == 3
    assert report["database"] == "none"
    assert report["sqlite"] == "not_used"
    assert report["external_network"] == "not_used"
    assert report["secrets"] is False
