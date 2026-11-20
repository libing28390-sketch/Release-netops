from __future__ import annotations

import json
import importlib.util
from pathlib import Path

import pytest


_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "ai_live_provider_eval.py"
_SPEC = importlib.util.spec_from_file_location("ai_live_provider_eval", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
calculate_live_metrics = _MODULE.calculate_live_metrics
load_evaluation_dataset = _MODULE.load_evaluation_dataset


def test_live_provider_metrics_keep_retry_rate_unobserved_when_no_retry_occurs():
    metrics = calculate_live_metrics(
        [
            {
                "case_id": "one",
                "parse_status": "llm_success",
                "correct": True,
            },
            {
                "case_id": "two",
                "parse_status": "provider_error",
                "correct": False,
            },
        ]
    )

    assert metrics["structured_first_pass_success_rate"] == 0.5
    assert metrics["structured_correction_success_rate"] is None
    assert metrics["correction_observed_case_count"] == 0
    assert metrics["provider_intent_accuracy"] == 0.5


def test_live_provider_metrics_count_schema_correction_success():
    metrics = calculate_live_metrics(
        [
            {"case_id": "one", "parse_status": "schema_retry_succeeded", "correct": True},
            {"case_id": "two", "parse_status": "schema_retry_failed", "correct": False},
            {"case_id": "three", "parse_status": "deterministic", "correct": True},
        ]
    )

    assert metrics["provider_backed_case_count"] == 2
    assert metrics["deterministic_case_count"] == 1
    assert metrics["structured_first_pass_success_rate"] == 0.0
    assert metrics["structured_correction_success_rate"] == 0.5
    assert metrics["overall_intent_accuracy"] == 0.6667


def test_live_provider_dataset_rejects_sensitive_prompt(tmp_path):
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(
            {
                "dataset_id": "unsafe",
                "cases": [
                    {
                        "id": "unsafe-1",
                        "prompt": "Please send the password used by the service.",
                        "expected_intent": "general_qa",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsafe live-evaluation prompt"):
        load_evaluation_dataset(dataset_path)
