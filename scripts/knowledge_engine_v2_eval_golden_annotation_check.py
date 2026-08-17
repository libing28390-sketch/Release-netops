"""Validate EVAL-008 reviewed Golden Answer and citation annotations."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-query-dataset-v1.yaml"
ANNOTATION_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-golden-annotations-v1.yaml"
MANIFEST_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-golden-annotations-v1.manifest.json"
EXPECTED_VENDORS = {"Huawei", "Cisco"}
EXPECTED_INTENTS = {"vlan", "interface", "ospf", "ssh", "ntp", "route"}
SENSITIVE_MARKERS = ("sk-", "api_key", "apikey", "password", "secret", "bearer ", "authorization:")


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path.name} must contain a mapping"
    return value


def validate_annotations() -> dict[str, Any]:
    dataset = _load(DATASET_PATH)
    annotations = _load(ANNOTATION_PATH)
    assert annotations.get("schema_version") == 1
    assert annotations.get("status") == "frozen"
    assert annotations.get("workflow_version") == 1
    assert annotations.get("parent_dataset_id") == dataset.get("dataset_id")
    assert annotations.get("source_policy", {}).get("database") == "none"
    assert annotations.get("source_policy", {}).get("sqlite") == "not_used"
    assert annotations.get("workflow", {}).get("stages") == ["draft", "peer_review", "adjudication", "frozen"]
    assert annotations.get("workflow", {}).get("primary_annotator_must_differ_from_reviewer") is True
    rules = annotations.get("label_rules") or {}
    assert set(rules) == {"answer", "clarify", "no_match"}
    records = annotations.get("annotations") or []
    assert len(records) == 12
    assert len({str(record.get("annotation_id")) for record in records}) == len(records)

    parent_by_id = {str(case.get("id")): case for case in dataset.get("cases") or []}
    vendor_intent_counts: Counter[str] = Counter()
    citation_count = 0
    for record in records:
        case_id = str(record.get("case_id"))
        parent = parent_by_id.get(case_id)
        assert parent is not None
        assert parent.get("query_type") == "exact"
        assert parent.get("expected_outcome") == "answer"
        assert record.get("status") == "frozen"
        assert str(record.get("annotator")) and str(record.get("reviewer"))
        assert record.get("annotator") != record.get("reviewer")
        assert record.get("vendor") in EXPECTED_VENDORS
        assert record.get("vendor") == parent.get("vendor")
        assert record.get("intent") in EXPECTED_INTENTS
        assert record.get("intent") == parent.get("intent")
        golden_answer = str(record.get("golden_answer") or "").strip()
        assert golden_answer and len(golden_answer) <= 1000
        applicability = record.get("applicability") or {}
        for field in ("vendor", "product_model", "os_family", "software_train"):
            assert applicability.get(field) == parent.get(field), f"{case_id} applicability mismatch: {field}"
        assert applicability.get("release_relation") == parent.get("expected_version_relation")
        assert applicability.get("release") == parent.get("software_release")
        citations = record.get("citations") or []
        assert citations
        gold_ids = set(str(item) for item in parent.get("gold_document_ids") or [])
        for citation in citations:
            assert isinstance(citation, dict)
            assert str(citation.get("document_id")) in gold_ids
            assert str(citation.get("source_version")) == str(parent.get("software_train"))
            assert str(citation.get("locator") or "").startswith("fixture/")
            assert citation.get("claim_ids")
            assert citation.get("official") is True
            citation_count += 1
        rendered = json.dumps(record, ensure_ascii=False).lower()
        assert not any(marker in rendered for marker in SENSITIVE_MARKERS)
        vendor_intent_counts[f"{record['vendor']}:{record['intent']}"] += 1

    assert len(vendor_intent_counts) == 12
    assert set(vendor_intent_counts.values()) == {1}
    report = {
        "status": "PASS",
        "annotation_set_id": annotations["annotation_set_id"],
        "parent_dataset_id": dataset["dataset_id"],
        "annotation_count": len(records),
        "citation_count": citation_count,
        "vendor_intent_counts": dict(sorted(vendor_intent_counts.items())),
        "review_status_counts": dict(Counter(str(record.get("status")) for record in records)),
        "dataset_sha256": hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest(),
        "annotation_sha256": hashlib.sha256(ANNOTATION_PATH.read_bytes()).hexdigest(),
        "database": "none",
        "sqlite": "not_used",
        "external_network": "not_used",
        "secrets": False,
    }
    MANIFEST_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    print(json.dumps(validate_annotations(), ensure_ascii=False))


if __name__ == "__main__":
    main()
