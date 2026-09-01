from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "docs" / "knowledge-engine" / "eval" / "ai-dialog-remediation-v1.yaml"
BASELINE = ROOT / "docs" / "knowledge-engine" / "eval" / "ai-dialog-remediation-v1-baseline.json"


def test_dialog_eval_dataset_has_required_operational_and_security_coverage():
    data = yaml.safe_load(DATASET.read_text(encoding="utf-8"))
    cases = data["cases"]
    assert len(cases) >= 20
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["scenario"] for case in cases} >= {
        "asset", "alarm", "knowledge", "diagnostic", "configuration", "execution", "casual_chat", "security",
    }
    assert {case["input_variant"] for case in cases} >= {
        "canonical", "alias", "typo", "bilingual", "missing_context", "injection", "sensitive", "dangerous",
    }
    assert any(case["expected_outcome"] == "blocked" for case in cases)
    assert any(case.get("risk_level") == "R3" and case.get("expected_execution") is False for case in cases)

    matrix = {item["provider_type"]: item for item in data["provider_matrix"]}
    assert {"deepseek", "qwen", "ollama"} <= matrix.keys()
    assert matrix["deepseek"]["live_case_ids"]


def test_dialog_baseline_is_explicit_about_measured_values_and_gaps():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert baseline["dataset_id"] == "nexora-ai-dialog-remediation-v1-20260901"
    assert baseline["database"] == "postgresql"
    assert baseline["quality_metrics"]["high_risk_unconfirmed_execution_rate"]["value"] == 0.0
    assert baseline["quality_metrics"]["sensitive_credential_egress_pass_rate"]["value"] == 1.0
    assert baseline["provider_matrix"]["deepseek"]["allowed_data_classification"] == "INTERNAL"
    assert baseline["provider_matrix"]["qwen"]["configured"] is False
    assert baseline["provider_matrix"]["ollama"]["configured"] is False
    assert baseline["gaps"]
