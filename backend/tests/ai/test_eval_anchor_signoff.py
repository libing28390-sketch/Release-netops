"""Tests for the explicit 50-anchor signoff promotion step."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "knowledge_eval_anchor_signoff.py"
SPEC = importlib.util.spec_from_file_location("knowledge_eval_anchor_signoff", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_signoff_promotes_candidate_without_changing_annotations() -> None:
    candidate_path = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-anchors-50-source-reviewed-v2.yaml"
    candidate = yaml.safe_load(candidate_path.read_text(encoding="utf-8"))
    original_ids = {
        case["id"]: list(case.get("acceptable_document_ids") or case.get("gold_document_ids") or [])
        for case in candidate["cases"]
    }

    signed = MODULE.create_signed_dataset(
        candidate,
        reviewer="reviewer-test",
        reviewed_at="2026-09-05T00:00:00+08:00",
        dataset_id="nexora-kb-eval-anchors-50-test-signed",
    )

    assert candidate["status"] == "candidate"
    assert signed["status"] == "frozen"
    assert signed["review_status"] == "approved"
    assert signed["source_review_status"] == "approved"
    assert signed["reviewer"] == "reviewer-test"
    assert signed["reviewed_at"] == "2026-09-05T00:00:00+08:00"
    assert len(signed["cases"]) == 50
    assert all(case.get("reviewer") == "reviewer-test" for case in signed["cases"])
    assert all(case.get("annotation_status") == "approved" for case in signed["cases"])

    for case in signed["cases"]:
        case_id = case["id"]
        assert list(case.get("acceptable_document_ids") or case.get("gold_document_ids") or []) == original_ids[case_id]
        source_review = case.get("source_review")
        if isinstance(source_review, dict):
            assert source_review["status"] == "source_verified_human_approved"
            assert source_review["reviewer"] == "reviewer-test"
            assert source_review["annotation_status"] == "approved"
