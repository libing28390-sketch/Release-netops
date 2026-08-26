"""EVAL-005 metric contract gate; no database fixture is used."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).parents[2] / "scripts" / "knowledge_engine_v2_eval_metrics_check.py"
_SPEC = importlib.util.spec_from_file_location("eval005_metrics_check", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_eval005_defines_retrieval_and_entity_resolution_metrics() -> None:
    report = _MODULE.validate_metrics()
    assert report["status"] == "PASS"
    assert report["metrics"] == ["recall_at_k", "precision_at_k", "mrr", "ndcg_at_k", "entity_resolution_accuracy"]
    assert report["retrieval_case_count"] == 3
    assert report["entity_resolution_case_count"] == 3
    assert report["entity_resolution_accuracy"] == 0.666667
    assert report["database"] == "none"
    assert report["sqlite"] == "not_used"
    assert report["external_network"] == "not_used"
    assert report["secrets"] is False
