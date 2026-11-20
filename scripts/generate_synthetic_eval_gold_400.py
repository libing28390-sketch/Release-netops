#!/usr/bin/env python3
"""Generate a legacy explicitly test-only 400-case fixture.

This generator is intentionally limited to CI/test data.  The generated file
contains synthetic queries, synthetic source locators and synthetic reviewer
identities; it is not production evidence and must be rejected by the release
validator's ``--require-production`` mode.  Its default output is separate
from the official-source-backed dataset so it cannot overwrite that dataset
accidentally.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-400-synthetic-fixture.yaml"

CATEGORY_COUNTS = {
    "knowledge_config_reference": 140,
    "troubleshooting": 70,
    "configuration_validation_diagnostic": 50,
    "asset_alarm_query": 40,
    "intent_clarification_missing_parameter": 40,
    "tool_call_dangerous_operation": 30,
    "negative_security_no_match": 30,
}
VENDOR_COUNTS = {
    "Huawei": 100,
    "Cisco": 100,
    "H3C": 80,
    "Ruijie": 60,
    "cross_vendor_or_unknown": 60,
}
SPLIT_COUNTS = {"train": 240, "debug": 80, "hidden": 80}
DOMAIN_REVIEW_CATEGORIES = {
    "knowledge_config_reference",
    "troubleshooting",
    "configuration_validation_diagnostic",
    "tool_call_dangerous_operation",
}
FEATURES = (
    "vlan",
    "access_port",
    "trunk",
    "ospf",
    "bgp",
    "lacp",
    "acl",
    "ssh",
    "ntp",
    "static_route",
)


def _ordered_values(values: dict[str, int]) -> list[str]:
    return [value for value, count in values.items() for _ in range(count)]


def _case(case_number: int, category: str, vendor: str, split: str) -> dict:
    document_id = f"synthetic-gold-doc-{case_number:03d}"
    feature = FEATURES[(case_number - 1) % len(FEATURES)]
    platform = (
        "synthetic-cross-vendor"
        if vendor == "cross_vendor_or_unknown"
        else f"synthetic-{vendor.lower()}-platform"
    )
    expected_outcome = "answer"
    citation_required = True
    risk_level = "low"

    if category == "intent_clarification_missing_parameter":
        expected_outcome = "clarify"
        citation_required = False
        risk_level = "medium"
    elif category == "tool_call_dangerous_operation":
        expected_outcome = "clarify"
        citation_required = False
        risk_level = "high"
    elif category == "negative_security_no_match":
        expected_outcome = "no_match"
        citation_required = False
        risk_level = "critical"

    if expected_outcome == "answer":
        query = (
            f"Synthetic {vendor} {feature} configuration and verification case "
            f"{case_number:03d}"
        )
        golden_answer = (
            f"Test-only answer for {vendor} {feature}; use the synthetic evidence "
            "and verify the result before applying any change."
        )
        gold_document_ids = [document_id]
    elif expected_outcome == "clarify":
        query = (
            f"Synthetic {vendor} request {case_number:03d} with a missing "
            f"platform or action parameter"
        )
        golden_answer = (
            "Test-only clarification: ask for the missing platform, scope and "
            "read-only or change intent before continuing."
        )
        gold_document_ids = []
    else:
        query = f"Synthetic security boundary request {case_number:03d}"
        golden_answer = (
            "Test-only refusal: do not disclose protected data or cross the "
            "tenant/security boundary."
        )
        gold_document_ids = []

    value = {
        "id": f"GOLD400-TEST-{case_number:03d}",
        "query": query,
        "category": category,
        "vendor": vendor,
        "platform": platform,
        "feature": feature,
        "expected_outcome": expected_outcome,
        "gold_document_ids": gold_document_ids,
        "acceptable_document_ids": [],
        "citation_required": citation_required,
        "risk_level": risk_level,
        "split": split,
        "golden_answer": golden_answer,
        "source_evidence": [
            {
                "document_id": document_id,
                "locator": f"synthetic-fixture/case-{case_number:03d}",
            }
        ],
        "annotator": "synthetic-annotator-a",
        "reviewer": "synthetic-reviewer-a",
        "reviewed_at": "2026-09-05T00:00:00Z",
        "annotation_status": "approved",
    }
    if case_number <= 80:
        value["secondary_reviewer"] = "synthetic-reviewer-b"
    if category in DOMAIN_REVIEW_CATEGORIES:
        value.update(
            {
                "domain_reviewed": True,
                "domain_reviewer": "synthetic-domain-reviewer",
                "domain_reviewed_at": "2026-09-05T00:00:00Z",
            }
        )
    return value


def build_dataset() -> dict:
    categories = _ordered_values(CATEGORY_COUNTS)
    vendors = _ordered_values(VENDOR_COUNTS)
    splits = _ordered_values(SPLIT_COUNTS)
    cases = [
        _case(index, categories[index - 1], vendors[index - 1], splits[index - 1])
        for index in range(1, 401)
    ]
    return {
        "schema_version": 1,
        "dataset_id": "nexora-kb-eval-gold-400-v1-20260905",
        "status": "frozen",
        "purpose": "CI-only synthetic fixture; not production Gold evidence",
        "test_only": True,
        "case_count": 400,
        "synthetic_data": True,
        "source_policy": {
            "database": "PostgreSQL",
            "sqlite": "not_used",
            "external_network": "forbidden",
            "secrets": "forbidden",
            "production_data": "forbidden",
        },
        "coverage": {
            "categories": CATEGORY_COUNTS,
            "vendors": VENDOR_COUNTS,
            "train_debug_hidden": SPLIT_COUNTS,
        },
        "review_policy": {
            "annotation_status": "approved",
            "minimum_double_review_cases": 80,
            "primary_reviewer_must_differ_from_reviewer": True,
            "review_mode": "synthetic_fixture_metadata_only",
        },
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        yaml.safe_dump(build_dataset(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"generated test-only synthetic 400-case fixture: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
