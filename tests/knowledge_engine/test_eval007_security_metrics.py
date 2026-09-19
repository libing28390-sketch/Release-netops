"""EVAL-007 Knowledge Engine security metric gate; no database fixture is used."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).parents[2] / "scripts" / "knowledge_eval_security_metrics_check.py"
_SPEC = importlib.util.spec_from_file_location("eval007_security_metrics_check", _SCRIPT)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_eval007_security_metrics_are_fail_closed() -> None:
    report = _MODULE.validate_security_metrics()
    assert report["status"] == "PASS"
    assert report["report"]["secret_leakage_rate"] == 0.5
    assert report["report"]["prompt_injection_block_rate"] == 1.0
    assert report["report"]["authorization_violation_rate"] == 0.5
    assert report["report"]["outbound_policy_compliance_rate"] == 2 / 3
    assert report["database"] == "none"
    assert report["sqlite"] == "not_used"
    assert report["external_network"] == "not_used"
    assert report["secrets"] is False
