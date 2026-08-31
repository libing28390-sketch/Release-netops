"""Validate Knowledge Engine EVAL-004 version-state coverage offline."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-query-dataset-v1.yaml"
COVERAGE_PATH = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-version-coverage-v1.yaml"
MANIFEST_PATH = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-version-coverage-v1.manifest.json"
EXPECTED_CLASSES = {"specified", "unspecified", "conflict", "unknown"}
EXPECTED_VENDORS = {"Huawei", "Cisco"}
EXPECTED_INTENTS = {"vlan", "interface", "ospf", "ssh", "ntp", "route"}
SENSITIVE_MARKERS = ("sk-", "api_key", "apikey", "password", "secret", "bearer ", "authorization:")


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path.name} must contain a mapping"
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_parent_cases(cases: list[dict[str, Any]], spec: dict[str, Any]) -> None:
    assert len(cases) == int(spec["case_count"]) == 12
    expected_relation = str(spec["expected_version_relation"])
    expected_outcome = str(spec["expected_outcome"])
    expected_citation = bool(spec["citation_required"])
    for case in cases:
        assert case.get("expected_version_relation") == expected_relation
        assert case.get("expected_outcome") == expected_outcome
        assert bool(case.get("citation_required")) is expected_citation
        rendered = json.dumps(case, ensure_ascii=False).lower()
        assert not any(marker in rendered for marker in SENSITIVE_MARKERS)
        if expected_relation == "exact":
            assert case.get("software_release")
            assert case.get("gold_document_ids")
        elif expected_relation == "unspecified":
            assert case.get("software_release") is None
            assert case.get("gold_document_ids")
        elif expected_relation == "conflict":
            assert case.get("software_release") is not None
            assert not case.get("gold_document_ids")


def validate_versions() -> dict[str, Any]:
    dataset = _load(DATASET_PATH)
    coverage = _load(COVERAGE_PATH)
    assert coverage.get("schema_version") == 1
    assert coverage.get("status") == "frozen"
    assert coverage.get("parent_dataset_id") == dataset.get("dataset_id")
    assert coverage.get("source_policy", {}).get("database") == "none"
    assert coverage.get("source_policy", {}).get("sqlite") == "not_used"
    classes = coverage.get("classes") or []
    assert {str(item.get("class_id")) for item in classes} == EXPECTED_CLASSES
    assert len(classes) == 4
    parent_cases = dataset.get("cases") or []
    parent_ids = {str(case.get("id")) for case in parent_cases}
    class_counts: Counter[str] = Counter()
    unknown_vendor_intent: Counter[str] = Counter()
    unknown_ids: set[str] = set()

    for spec in classes:
        class_id = str(spec["class_id"])
        if class_id != "unknown":
            assert spec.get("source") == "parent_dataset"
            query_type = str(spec["parent_query_type"])
            matching = [case for case in parent_cases if case.get("query_type") == query_type]
            _assert_parent_cases(matching, spec)
            class_counts[class_id] = len(matching)
            continue

        assert spec.get("source") == "eval_fixture"
        unknown_cases = spec.get("cases") or []
        assert len(unknown_cases) == int(spec["case_count"]) == 12
        for case in unknown_cases:
            case_id = str(case.get("id"))
            assert case_id and case_id not in parent_ids and case_id not in unknown_ids
            unknown_ids.add(case_id)
            vendor = str(case.get("vendor"))
            intent = str(case.get("intent"))
            assert vendor in EXPECTED_VENDORS and intent in EXPECTED_INTENTS
            requested = str(case.get("requested_version") or "")
            supported = {str(item) for item in case.get("supported_versions") or []}
            assert requested and requested not in supported
            assert str(case.get("expected_version_relation", "unknown")) == "unknown"
            assert str(case.get("expected_outcome", "no_match")) == "no_match"
            assert case.get("gold_document_ids", []) == []
            assert case.get("citation_required", False) is False
            query = str(case.get("query", ""))
            assert requested.lower() in query.lower()
            assert "version" in query.lower()
            assert not any(marker in json.dumps(case, ensure_ascii=False).lower() for marker in SENSITIVE_MARKERS)
            unknown_vendor_intent[f"{vendor}:{intent}"] += 1
        class_counts[class_id] = len(unknown_cases)

    assert set(class_counts.values()) == {12}
    assert len(unknown_vendor_intent) == 12
    assert set(unknown_vendor_intent.values()) == {1}
    return {
        "status": "PASS",
        "coverage_id": coverage["coverage_id"],
        "parent_dataset_id": dataset["dataset_id"],
        "class_counts": dict(sorted(class_counts.items())),
        "unknown_vendor_intent_counts": dict(sorted(unknown_vendor_intent.items())),
        "unknown_case_ids": sorted(unknown_ids),
        "dataset_sha256": _sha256(DATASET_PATH),
        "coverage_sha256": _sha256(COVERAGE_PATH),
        "database": "none",
        "sqlite": "not_used",
        "external_network": "not_used",
        "secrets": False,
    }


def main() -> None:
    report = validate_versions()
    MANIFEST_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
