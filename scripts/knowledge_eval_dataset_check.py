"""Validate the frozen Knowledge Engine EVAL-001 query dataset offline."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-query-dataset-v1.yaml"
MANIFEST_PATH = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-query-dataset-v1.manifest.json"
EXPECTED_TYPES = {"exact", "alias", "prefix", "ambiguous", "typo", "wrong_vendor", "product_conflict", "version_exact", "version_conflict", "no_match"}
EXPECTED_INTENTS = {"vlan", "interface", "ospf", "ssh", "ntp", "route"}
EXPECTED_VENDORS = {"Huawei", "Cisco"}
SENSITIVE_MARKERS = ("sk-", "api_key", "apikey", "password", "secret", "bearer ", "authorization:")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_dataset() -> dict[str, Any]:
    raw = DATASET_PATH.read_bytes()
    fixture = yaml.safe_load(raw.decode("utf-8"))
    assert fixture.get("schema_version") == 1
    assert fixture.get("status") == "frozen"
    cases = fixture.get("cases") or []
    assert fixture.get("case_count") == len(cases) == 120
    ids = [str(case.get("id") or "") for case in cases]
    assert len(set(ids)) == len(ids) and all(item.startswith("EVAL-Q") for item in ids)
    assert {str(case.get("intent")) for case in cases} == EXPECTED_INTENTS
    assert {str(case.get("query_type")) for case in cases} == EXPECTED_TYPES

    type_counts = Counter(str(case.get("query_type")) for case in cases)
    intent_counts = Counter(str(case.get("intent")) for case in cases)
    vendor_intent_counts: defaultdict[tuple[str, str], int] = defaultdict(int)
    ambiguous_intent_counts: Counter[str] = Counter()
    for case in cases:
        query = str(case.get("query") or "")
        rendered = json.dumps(case, ensure_ascii=False).lower()
        assert query and len(query) <= 500
        assert not any(marker in rendered for marker in SENSITIVE_MARKERS)
        query_type = str(case.get("query_type"))
        outcome = str(case.get("expected_outcome"))
        gold = case.get("gold_document_ids") or []
        assert outcome in {"answer", "clarify", "no_match"}
        if outcome == "answer":
            assert gold and case.get("citation_required") is True
        if outcome == "clarify":
            assert len(gold) >= 2 and case.get("citation_required") is False
        if outcome == "no_match":
            assert not gold and case.get("citation_required") is False
        if query_type == "version_exact":
            assert case.get("expected_version_relation") == "exact" and case.get("software_release")
        if query_type == "version_conflict":
            assert case.get("expected_version_relation") == "conflict" and outcome == "no_match"
        if query_type == "ambiguous":
            assert case.get("expected_vendor") is None and outcome == "clarify"
            ambiguous_intent_counts[str(case.get("intent"))] += 1
            target_vendors: set[str] = set()
        else:
            expected_vendor = case.get("expected_vendor")
            assert expected_vendor in EXPECTED_VENDORS
            target_vendors = {str(expected_vendor)}
        for vendor in target_vendors:
            vendor_intent_counts[(vendor, str(case.get("intent")))] += 1

    assert set(type_counts.values()) == {12}
    assert set(intent_counts.values()) == {20}
    assert set(vendor_intent_counts.values()) == {9}
    assert set(ambiguous_intent_counts.values()) == {2}
    assert all(str(case.get("expected_version_relation")) in {"exact", "unspecified", "conflict"} for case in cases)
    return {
        "status": "PASS",
        "dataset_id": fixture["dataset_id"],
        "case_count": len(cases),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "query_type_counts": dict(sorted(type_counts.items())),
        "intent_counts": dict(sorted(intent_counts.items())),
        "vendor_intent_counts": {f"{vendor}:{intent}": count for (vendor, intent), count in sorted(vendor_intent_counts.items())},
        "ambiguous_intent_counts": dict(sorted(ambiguous_intent_counts.items())),
        "database": "none",
        "sqlite": "not_used",
        "secrets": False,
    }


def main() -> None:
    report = validate_dataset()
    MANIFEST_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
