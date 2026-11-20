"""Validate Knowledge Engine EVAL-003 query-type boundaries offline."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-query-dataset-v1.yaml"
COVERAGE_PATH = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-query-type-coverage-v1.yaml"
MANIFEST_PATH = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-query-type-coverage-v1.manifest.json"
EXPECTED_TYPES = {"exact", "alias", "prefix", "ambiguous", "typo", "wrong_vendor", "product_conflict"}
EXPECTED_VENDORS = {"Huawei", "Cisco"}
SENSITIVE_MARKERS = ("sk-", "api_key", "apikey", "password", "secret", "bearer ", "authorization:")


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path.name} must contain a mapping"
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_query_types() -> dict[str, Any]:
    dataset = _load(DATASET_PATH)
    coverage = _load(COVERAGE_PATH)
    assert coverage.get("schema_version") == 1
    assert coverage.get("status") == "frozen"
    assert coverage.get("parent_dataset_id") == dataset.get("dataset_id")
    assert coverage.get("source_policy", {}).get("database") == "none"
    assert coverage.get("source_policy", {}).get("sqlite") == "not_used"
    specs = coverage.get("types") or []
    assert {str(item.get("query_type")) for item in specs} == EXPECTED_TYPES
    assert len(specs) == len(EXPECTED_TYPES)

    cases = dataset.get("cases") or []
    by_type: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        query_type = str(case.get("query_type"))
        if query_type in EXPECTED_TYPES:
            by_type[query_type].append(case)

    type_counts = Counter({query_type: len(items) for query_type, items in by_type.items()})
    assert set(type_counts) == EXPECTED_TYPES
    assert set(type_counts.values()) == {12}
    outcome_counts: dict[str, dict[str, int]] = {}
    sample_ids: dict[str, list[str]] = {}

    for spec in specs:
        query_type = str(spec["query_type"])
        expected_outcome = str(spec["expected_outcome"])
        expected_citation = bool(spec["citation_required"])
        matching = by_type[query_type]
        assert len(matching) == int(spec["case_count"]) == 12
        outcomes = Counter(str(case.get("expected_outcome")) for case in matching)
        outcome_counts[query_type] = dict(sorted(outcomes.items()))
        sample_ids[query_type] = [str(case.get("id")) for case in matching[:2]]
        assert outcomes == Counter({expected_outcome: 12})

        for case in matching:
            rendered = json.dumps(case, ensure_ascii=False).lower()
            assert not any(marker in rendered for marker in SENSITIVE_MARKERS)
            gold = case.get("gold_document_ids") or []
            assert bool(case.get("citation_required")) is expected_citation
            if query_type in {"exact", "alias", "prefix", "typo"}:
                assert gold and expected_outcome == "answer"
                assert case.get("expected_vendor") in EXPECTED_VENDORS
            elif query_type == "ambiguous":
                assert case.get("vendor") is None
                assert case.get("expected_vendor") is None
                assert case.get("platform") is None
                assert case.get("product_series") is None
                assert case.get("product_model") is None
                assert len(gold) >= 2
                assert not any(vendor.lower() in str(case.get("query", "")).lower() for vendor in EXPECTED_VENDORS)
            else:
                assert not gold and expected_outcome == "no_match"
                vendor = str(case.get("vendor"))
                opposite = (EXPECTED_VENDORS - {vendor}).pop()
                query = str(case.get("query", "")).lower()
                assert vendor.lower() in query
                if query_type == "product_conflict":
                    assert str(case.get("product_series")).lower() in query
                    opposite_model = "C9300-48P" if vendor == "Huawei" else "CE6885-48YS8CQ"
                    assert opposite_model.lower() in query
                if query_type == "wrong_vendor":
                    assert opposite.lower() in query
                    assert "syntax" in query

            if query_type == "prefix":
                query = str(case.get("query", "")).lower()
                assert "ce68" in query or "c930" in query
                assert str(case.get("product_model")).lower() not in query
            if query_type == "alias":
                assert any(
                    marker in str(case.get("query", "")).lower()
                    for marker in ("access", "port status", "neighbor state", "stelnet", "time sync", "routing table")
                )
            if query_type == "typo":
                query = str(case.get("query", "")).lower()
                assert any(token in query for token in ("commmand", "interfase", "neigbor", "routng"))

    assert outcome_counts["ambiguous"] == {"clarify": 12}
    assert outcome_counts["wrong_vendor"] == {"no_match": 12}
    assert outcome_counts["product_conflict"] == {"no_match": 12}
    return {
        "status": "PASS",
        "coverage_id": coverage["coverage_id"],
        "parent_dataset_id": dataset["dataset_id"],
        "type_counts": dict(sorted(type_counts.items())),
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "sample_case_ids": dict(sorted(sample_ids.items())),
        "dataset_sha256": _sha256(DATASET_PATH),
        "coverage_sha256": _sha256(COVERAGE_PATH),
        "database": "none",
        "sqlite": "not_used",
        "external_network": "not_used",
        "secrets": False,
    }


def main() -> None:
    report = validate_query_types()
    MANIFEST_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
