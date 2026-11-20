"""Smoke-check Knowledge Engine EVAL-005 metrics with deterministic cases."""

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
    entity_resolution_accuracy,
    evaluate_retrieval_cases,
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


MODULE_PATH = ROOT / "backend" / "ai" / "services" / "evaluation_metrics.py"
REPORT_PATH = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-metrics-v1.manifest.json"


def _close(actual: float, expected: float) -> None:
    assert math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9), (actual, expected)


def validate_metrics() -> dict[str, object]:
    positive = {"ranked_ids": ["d3", "d1", "d2"], "gold_ids": ["d1", "d2"]}
    no_match_correct = {"ranked_ids": [], "gold_ids": []}
    no_match_guess = {"ranked_ids": ["d9"], "gold_ids": []}

    _close(recall_at_k(**positive, k=1), 0.0)
    _close(recall_at_k(**positive, k=3), 1.0)
    _close(recall_at_k(**no_match_correct, k=3), 1.0)
    _close(recall_at_k(**no_match_guess, k=3), 0.0)
    _close(precision_at_k(**positive, k=3), 2 / 3)
    _close(precision_at_k(**no_match_correct, k=3), 1.0)
    _close(precision_at_k(**no_match_guess, k=3), 0.0)
    _close(mean_reciprocal_rank(**positive), 0.5)
    _close(mean_reciprocal_rank(**no_match_correct), 1.0)
    _close(mean_reciprocal_rank(**no_match_guess), 0.0)
    _close(ndcg_at_k(**positive, k=3), (1 / math.log2(3) + 1 / math.log2(4)) / (1 + 1 / math.log2(3)))
    _close(ndcg_at_k(**no_match_correct, k=3), 1.0)
    _close(ndcg_at_k(**no_match_guess, k=3), 0.0)

    retrieval_report = evaluate_retrieval_cases([positive, no_match_correct, no_match_guess], ks=(1, 3))
    assert retrieval_report["case_count"] == 3
    assert retrieval_report["recall_at_k"] == {"1": 0.333333, "3": 0.666667}
    assert retrieval_report["precision_at_k"] == {"1": 0.333333, "3": 0.555556}
    assert retrieval_report["mrr"] == 0.5
    assert retrieval_report["ndcg_at_k"]["1"] == 0.333333

    resolution_report = entity_resolution_accuracy(
        [
            {
                "expected": {"vendor": "Huawei", "product_model": "CE6885-48YS8CQ"},
                "predicted": {"vendor": "huawei", "product_model": "CE6885/48YS8CQ"},
            },
            {
                "expected": {"vendor": "Cisco", "product_model": "C9300-48P"},
                "predicted": {"vendor": "Cisco", "product_model": "C9300-48P", "platform": "iosxe"},
            },
            {"expected": {}, "predicted": {}},
        ]
    )
    _close(resolution_report, 2 / 3)
    report = {
        "status": "PASS",
        "metrics": ["recall_at_k", "precision_at_k", "mrr", "ndcg_at_k", "entity_resolution_accuracy"],
        "retrieval_case_count": retrieval_report["case_count"],
        "entity_resolution_case_count": 3,
        "retrieval_report": retrieval_report,
        "entity_resolution_accuracy": round(resolution_report, 6),
        "database": "none",
        "sqlite": "not_used",
        "external_network": "not_used",
        "secrets": False,
        "module_sha256": hashlib.sha256(MODULE_PATH.read_bytes()).hexdigest(),
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    print(json.dumps(validate_metrics(), ensure_ascii=False))


if __name__ == "__main__":
    main()
