"""Smoke-check Knowledge Engine EVAL-006 product/OS/version/source metrics."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from ai.services.evaluation_metrics import (
    citation_accuracy,
    evaluate_quality_cases,
    official_source_rate,
    os_match_accuracy,
    product_match_accuracy,
    version_match_accuracy,
    wrong_vendor_rate,
)


MODULE_PATH = ROOT / "backend" / "ai" / "services" / "evaluation_metrics.py"
REPORT_PATH = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-quality-metrics-v1.manifest.json"


def _close(actual: float, expected: float) -> None:
    assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9), (actual, expected)


def _cases() -> list[dict[str, object]]:
    return [
        {
            "expected": {
                "product": "CE6885-48YS8CQ",
                "os": "VRP",
                "vendor": "Huawei",
                "version_relation": "exact",
                "version": "V300R023C10",
            },
            "predicted": {
                "product": "CE6885/48YS8CQ",
                "os": "vrp",
                "vendor": "huawei",
                "version_relation": "exact",
                "version": "v300r023c10",
            },
            "expected_outcome": "answer",
            "gold_ids": ["doc-huawei-vlan"],
            "citations": [{"document_id": "doc-huawei-vlan", "official": True}],
            "expected_vendor": "Huawei",
            "predicted_vendor": "huawei",
        },
        {
            "expected": {"product": None, "os": None, "vendor": None, "version_relation": "unspecified"},
            "predicted": {"product": None, "os": None, "vendor": None, "version_relation": "unspecified", "version": None},
            "expected_outcome": "clarify",
            "gold_ids": ["doc-huawei-vlan", "doc-cisco-vlan"],
            "citations": [],
            "expected_vendor": None,
            "predicted_vendor": None,
        },
        {
            "expected": {"product": "C9300-48P", "os": "IOS XE", "vendor": "Cisco", "version_relation": "conflict"},
            "predicted": {"product": "CE6885-48YS8CQ", "os": "VRP", "vendor": "Huawei", "version_relation": "conflict"},
            "expected_outcome": "no_match",
            "gold_ids": [],
            "citations": [{"document_id": "doc-huawei-vlan", "official": False}],
            "expected_vendor": "Cisco",
            "predicted_vendor": "Huawei",
        },
    ]


def validate_quality_metrics() -> dict[str, object]:
    cases = _cases()
    _close(product_match_accuracy(cases), 2 / 3)
    _close(os_match_accuracy(cases), 2 / 3)
    _close(version_match_accuracy(cases), 1.0)
    _close(wrong_vendor_rate(cases), 1 / 3)
    _close(official_source_rate(cases), 2 / 3)
    _close(citation_accuracy(cases), 2 / 3)
    report = evaluate_quality_cases(cases)
    assert report["case_count"] == 3
    for key, expected in {
        "product_match": 2 / 3,
        "os_match": 2 / 3,
        "version_match": 1.0,
        "wrong_vendor_rate": 1 / 3,
        "official_source_rate": 2 / 3,
        "citation_accuracy": 2 / 3,
    }.items():
        _close(float(report[key]), expected)
    output = {
        "status": "PASS",
        "metrics": ["product_match", "os_match", "version_match", "wrong_vendor_rate", "official_source_rate", "citation_accuracy"],
        "report": report,
        "database": "none",
        "sqlite": "not_used",
        "external_network": "not_used",
        "secrets": False,
        "module_sha256": hashlib.sha256(MODULE_PATH.read_bytes()).hexdigest(),
    }
    REPORT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> None:
    print(json.dumps(validate_quality_metrics(), ensure_ascii=False))


if __name__ == "__main__":
    main()
