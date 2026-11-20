import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


_SOURCE_REVIEW_PATH = ROOT / "scripts" / "knowledge_eval_anchor_source_review.py"
_SPEC = importlib.util.spec_from_file_location("knowledge_eval_anchor_source_review", _SOURCE_REVIEW_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
build_candidate = _MODULE.build_candidate


def test_source_review_candidate_completes_automatic_work_without_impersonating_human_signoff():
    dataset_path = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-anchors-50.yaml"
    dataset = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))

    candidate, report = build_candidate(dataset)

    assert report["status"] == "SOURCE_REVIEW_COMPLETE_PENDING_HUMAN_SIGNOFF"
    assert report["changed_case_count"] == 11
    assert report["source_review_case_count"] == 42
    assert report["proposed_feature_annotation_count"] == 42
    assert report["feature_adjudication_required_case_ids"] == []
    assert report["machine_feature_scope_case_ids"] == [
        "ANCHOR-003",
        "ANCHOR-004",
        "ANCHOR-029",
        "ANCHOR-049",
    ]
    assert candidate["human_review_required"] is True
    assert candidate["status"] == "candidate"
    assert candidate["source_review_status"] == "complete_pending_human_signoff"
    assert all(
        "reviewer" not in case
        and "reviewed_at" not in case
        and case.get("annotation_status") != "approved"
        for case in candidate["cases"]
    )

    cases = {case["id"]: case for case in candidate["cases"]}
    assert sum("acceptable_document_ids" in case for case in candidate["cases"]) == 42
    assert cases["ANCHOR-001"]["acceptable_document_ids"] == [
        "official-template-official-huawei-vlan-basic",
        "official-template-official-huawei-vlanif",
    ]
    assert cases["ANCHOR-016"]["feature"] == "bfd"
    assert cases["ANCHOR-019"]["feature"] == "system_monitoring"
    assert cases["ANCHOR-030"]["feature"] == "interface"
    assert cases["ANCHOR-003"]["feature"] == "interface"
    assert cases["ANCHOR-003"]["feature_scope"] == ["interface", "access_port", "trunk"]
    assert cases["ANCHOR-003"]["acceptable_document_ids"] == [
        "official-template-official-huawei-ce6885-interface-status-diagnostic",
        "official-template-official-huawei-access-port",
        "official-template-official-huawei-trunk-port",
    ]
    assert cases["ANCHOR-003"]["source_review"]["status"] == "source_verified_pending_human_signoff"
