"""EVAL-003 query-type boundary gate; no database fixture is used."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).parents[2] / "scripts" / "knowledge_engine_v2_eval_query_type_coverage_check.py"
_SPEC = importlib.util.spec_from_file_location("eval003_query_type_coverage_check", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_eval003_covers_positive_and_fail_closed_query_types() -> None:
    report = _MODULE.validate_query_types()
    assert report["status"] == "PASS"
    assert report["type_counts"] == {
        "alias": 12,
        "ambiguous": 12,
        "exact": 12,
        "prefix": 12,
        "product_conflict": 12,
        "typo": 12,
        "wrong_vendor": 12,
    }
    assert report["outcome_counts"]["ambiguous"] == {"clarify": 12}
    assert report["outcome_counts"]["wrong_vendor"] == {"no_match": 12}
    assert report["outcome_counts"]["product_conflict"] == {"no_match": 12}
    assert report["database"] == "none"
    assert report["sqlite"] == "not_used"
    assert report["external_network"] == "not_used"
    assert report["secrets"] is False
