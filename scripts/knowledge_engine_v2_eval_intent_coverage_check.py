"""Validate EVAL-002 vendor and network-intent coverage offline."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-query-dataset-v1.yaml"
COVERAGE_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-intent-coverage-v1.yaml"
MANIFEST_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-intent-coverage-v1.manifest.json"
EXPECTED_VENDORS = {"Huawei", "Cisco"}
EXPECTED_INTENTS = {"vlan", "interface", "ospf", "ssh", "ntp", "route"}
EXPECTED_QUERY_TYPES = {
    "exact",
    "alias",
    "prefix",
    "typo",
    "wrong_vendor",
    "product_conflict",
    "version_exact",
    "version_conflict",
    "no_match",
}
SENSITIVE_MARKERS = ("sk-", "api_key", "apikey", "password", "secret", "bearer ", "authorization:")


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path.name} must contain a mapping"
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_coverage() -> dict[str, Any]:
    dataset = _load(DATASET_PATH)
    coverage = _load(COVERAGE_PATH)
    assert coverage.get("schema_version") == 1
    assert coverage.get("status") == "frozen"
    assert coverage.get("parent_dataset_id") == dataset.get("dataset_id")
    assert coverage.get("source_policy", {}).get("database") == "none"
    assert coverage.get("source_policy", {}).get("sqlite") == "not_used"
    assert coverage.get("source_policy", {}).get("external_network") == "forbidden"
    required_types = set(coverage.get("required_query_types") or [])
    assert required_types == EXPECTED_QUERY_TYPES

    cases = dataset.get("cases") or []
    tracks = coverage.get("tracks") or []
    assert len(tracks) == 12
    track_keys = [(str(item.get("vendor")), str(item.get("intent"))) for item in tracks]
    assert len(set(track_keys)) == 12
    assert set(track_keys) == {(vendor, intent) for vendor in EXPECTED_VENDORS for intent in EXPECTED_INTENTS}

    track_counts: Counter[str] = Counter()
    vendor_counts: Counter[str] = Counter()
    intent_counts: Counter[str] = Counter()
    example_count = 0
    for track in tracks:
        vendor = str(track.get("vendor"))
        intent = str(track.get("intent"))
        assert vendor in EXPECTED_VENDORS
        assert intent in EXPECTED_INTENTS
        rendered = json.dumps(track, ensure_ascii=False).lower()
        assert not any(marker in rendered for marker in SENSITIVE_MARKERS)

        examples = [str(item).strip() for item in track.get("query_examples") or []]
        canonical_terms = [str(item).strip().lower() for item in track.get("canonical_terms") or []]
        assert len(examples) >= 3
        assert len(canonical_terms) >= 3
        joined_examples = " | ".join(examples).lower()
        assert vendor.lower() in joined_examples
        assert str(track.get("product_series")).lower() in joined_examples or str(track.get("product_model")).lower() in joined_examples
        assert all(term in joined_examples for term in canonical_terms)
        assert all(any(term in example.lower() for term in canonical_terms) for example in examples)
        example_count += len(examples)

        matching = [case for case in cases if case.get("vendor") == vendor and case.get("intent") == intent]
        assert len(matching) == 9
        types = {str(case.get("query_type")) for case in matching}
        assert types == required_types
        exact = next(case for case in matching if case.get("query_type") == "exact")
        assert track.get("gold_document_id") in (exact.get("gold_document_ids") or [])
        for field in ("platform", "product_family", "product_series", "product_model", "os_family", "software_train"):
            assert exact.get(field) == track.get(field), f"{vendor}:{intent} field mismatch: {field}"

        key = f"{vendor}:{intent}"
        track_counts[key] = len(matching)
        vendor_counts[vendor] += 1
        intent_counts[intent] += 1

    assert set(track_counts.values()) == {9}
    assert set(vendor_counts.values()) == {6}
    assert set(intent_counts.values()) == {2}
    return {
        "status": "PASS",
        "coverage_id": coverage["coverage_id"],
        "parent_dataset_id": dataset["dataset_id"],
        "track_count": len(tracks),
        "query_example_count": example_count,
        "track_case_counts": dict(sorted(track_counts.items())),
        "vendor_track_counts": dict(sorted(vendor_counts.items())),
        "intent_track_counts": dict(sorted(intent_counts.items())),
        "dataset_sha256": _sha256(DATASET_PATH),
        "coverage_sha256": _sha256(COVERAGE_PATH),
        "database": "none",
        "sqlite": "not_used",
        "external_network": "not_used",
        "secrets": False,
    }


def main() -> None:
    report = validate_coverage()
    MANIFEST_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
