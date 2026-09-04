#!/usr/bin/env python3
"""Validate the human-reviewed 400-case Knowledge Engine Gold Dataset.

This is a completeness and safety gate, not an annotation generator.  The
repository intentionally contains the contract but no fabricated 400-case
dataset; the command returns ``NOT_READY`` until a real reviewed file is
provided.  It never connects to a database or writes production data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-400.yaml"
DEFAULT_CONTRACT = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-400-contract-v1.yaml"
DEFAULT_OUTPUT = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-400-check.json"
_DATASET_ID_RE = re.compile(r"^nexora-kb-eval-gold-400-v[0-9]+-[0-9]{8}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,256}$")
_SECRET_RE = re.compile(
    r"(?i)(?:-----begin [a-z0-9 ]*private key-----|postgres(?:ql)?://|"
    r"(?:api[_ -]?key|access[_ -]?token|password|passwd|secret)\s*[:=]\s*[^\s,;]+|"
    r"(?:snmp(?:-agent|-server)?\s+community)\s+(?:read|write|cipher|simple)?\s*[^\s]+|"
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,})"
)
_CUSTOMER_KEY_RE = re.compile(r"(?i)(?:customer[_ -]?(?:id|name)|account[_ -]?id|tenant[_ -]?id|"
                               r"user(?:name|_id)|email|phone(?:_number)?)")


class GoldDatasetValidationError(ValueError):
    pass


def _load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _case_has_customer_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _CUSTOMER_KEY_RE.search(str(key)) or _case_has_customer_key(item):
                return True
    elif isinstance(value, list):
        return any(_case_has_customer_key(item) for item in value)
    return False


def _source_evidence_valid(value: Any) -> bool:
    entries = _list(value)
    if not entries:
        return False
    for entry in entries:
        if not isinstance(entry, Mapping):
            return False
        if not _text(entry.get("document_id")) or not _text(entry.get("locator")):
            return False
        if not _SAFE_ID_RE.fullmatch(_text(entry.get("document_id"))):
            return False
    return True


def validate_dataset(dataset_path: Path = DEFAULT_DATASET, contract_path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    errors: list[str] = []
    dataset: Any = None
    contract: Any = None
    try:
        contract = _load(contract_path)
        dataset = _load(dataset_path)
    except FileNotFoundError:
        return {
            "status": "NOT_READY",
            "dataset_path": str(dataset_path.relative_to(ROOT)) if dataset_path.is_relative_to(ROOT) else str(dataset_path),
            "required_case_count": 400,
            "case_count": 0,
            "errors": ["human-reviewed 400-case dataset is not present"],
            "database": "PostgreSQL",
            "sqlite": "not_used",
            "external_network": "forbidden",
            "secrets": False,
        }
    if not isinstance(contract, Mapping):
        errors.append("contract must be a mapping")
    if not isinstance(dataset, Mapping):
        errors.append("dataset must be a mapping")
        dataset = {}

    cases = _list(dataset.get("cases"))
    required_fields = list(((contract.get("dataset") or {}).get("required_case_fields") or [])) if isinstance(contract, Mapping) else []
    expected_categories = dict(((contract.get("dataset") or {}).get("categories") or {})) if isinstance(contract, Mapping) else {}
    expected_splits = dict(((contract.get("dataset") or {}).get("splits") or {})) if isinstance(contract, Mapping) else {}
    expected_vendors = dict(((contract.get("dataset") or {}).get("vendors") or {})) if isinstance(contract, Mapping) else {}
    expected_outcomes = set(((contract.get("dataset") or {}).get("expected_outcomes") or [])) if isinstance(contract, Mapping) else set()
    expected_risk_levels = set(((contract.get("dataset") or {}).get("risk_levels") or [])) if isinstance(contract, Mapping) else set()
    domain_categories = set(((contract.get("review_policy") or {}).get("domain_review_required_for") or [])) if isinstance(contract, Mapping) else set()

    if dataset.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not _DATASET_ID_RE.fullmatch(_text(dataset.get("dataset_id"))):
        errors.append("dataset_id must match nexora-kb-eval-gold-400-vN-YYYYMMDD")
    if dataset.get("status") != "frozen":
        errors.append("status must be frozen")
    if dataset.get("case_count") != 400 or len(cases) != 400:
        errors.append(f"case_count must be 400 (declared={dataset.get('case_count')!r}, actual={len(cases)})")
    if dataset.get("synthetic_data") is not True:
        errors.append("synthetic_data must be true")
    source_policy = dataset.get("source_policy") if isinstance(dataset.get("source_policy"), Mapping) else {}
    for key, expected in {"database": "PostgreSQL", "sqlite": "not_used", "external_network": "forbidden", "secrets": "forbidden", "production_data": "forbidden"}.items():
        if source_policy.get(key) != expected:
            errors.append(f"source_policy.{key} must be {expected}")
    coverage = dataset.get("coverage") if isinstance(dataset.get("coverage"), Mapping) else {}
    review_policy = dataset.get("review_policy") if isinstance(dataset.get("review_policy"), Mapping) else {}
    if coverage.get("train_debug_hidden") != {"train": 240, "debug": 80, "hidden": 80}:
        errors.append("coverage.train_debug_hidden must be 240/80/80")

    ids: set[str] = set()
    category_counts: Counter[str] = Counter()
    vendor_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    double_review_count = 0
    for index, case in enumerate(cases, start=1):
        prefix = f"case[{index}]"
        if not isinstance(case, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        missing = [field for field in required_fields if field not in case]
        errors.extend(f"{prefix} missing {field}" for field in missing)
        case_id = _text(case.get("id"))
        if not case_id or case_id in ids:
            errors.append(f"{prefix} id is missing or duplicated")
        ids.add(case_id)
        query = _text(case.get("query"))
        if not query or len(query) > 2000:
            errors.append(f"{prefix} query is empty or too long")
        category = _text(case.get("category"))
        category_counts[category] += 1
        if category not in expected_categories:
            errors.append(f"{prefix} category is not in the contract")
        vendor = _text(case.get("vendor")) or "cross_vendor_or_unknown"
        vendor_counts[vendor] += 1
        if vendor not in expected_vendors:
            errors.append(f"{prefix} vendor is not in the contract")
        split = _text(case.get("split"))
        split_counts[split] += 1
        if split not in expected_splits:
            errors.append(f"{prefix} split is not in the contract")
        outcome = _text(case.get("expected_outcome"))
        if outcome not in (expected_outcomes or {"answer", "clarify", "no_match"}):
            errors.append(f"{prefix} expected_outcome is invalid")
        risk_level = _text(case.get("risk_level"))
        if risk_level not in (expected_risk_levels or {"low", "medium", "high", "critical"}):
            errors.append(f"{prefix} risk_level is invalid")
        gold = _list(case.get("gold_document_ids"))
        acceptable = _list(case.get("acceptable_document_ids"))
        if outcome == "answer" and not (gold or acceptable):
            errors.append(f"{prefix} answer requires Gold or acceptable document IDs")
        if outcome == "no_match" and (gold or acceptable):
            errors.append(f"{prefix} no_match cannot carry Gold or acceptable document IDs")
        for field_name in ("gold_document_ids", "acceptable_document_ids"):
            for doc_id in _list(case.get(field_name)):
                if not _SAFE_ID_RE.fullmatch(_text(doc_id)):
                    errors.append(f"{prefix} {field_name} contains an invalid document ID")
        if not isinstance(case.get("citation_required"), bool):
            errors.append(f"{prefix} citation_required must be boolean")
        if not _text(case.get("golden_answer")) or len(_text(case.get("golden_answer"))) > 20_000:
            errors.append(f"{prefix} golden_answer is empty or too long")
        if not _source_evidence_valid(case.get("source_evidence")):
            errors.append(f"{prefix} source_evidence is incomplete")
        annotator = _text(case.get("annotator"))
        reviewer = _text(case.get("reviewer"))
        if not annotator or not reviewer or annotator == reviewer:
            errors.append(f"{prefix} annotator/reviewer must be present and different")
        if not _text(case.get("reviewed_at")) or _text(case.get("annotation_status")) != "approved":
            errors.append(f"{prefix} is not human-approved")
        if _text(case.get("secondary_reviewer")):
            double_review_count += 1
            if _text(case.get("secondary_reviewer")) in {annotator, reviewer}:
                errors.append(f"{prefix} secondary reviewer must be independent")
        if category in domain_categories and (case.get("domain_reviewed") is not True or not _text(case.get("domain_reviewer")) or not _text(case.get("domain_reviewed_at"))):
            errors.append(f"{prefix} requires domain review evidence")
        if _case_has_customer_key(case):
            errors.append(f"{prefix} contains a prohibited customer/user/tenant identifier field")
        if _SECRET_RE.search(json.dumps(case, ensure_ascii=False, default=str)):
            errors.append(f"{prefix} contains a secret-like value")

    for category, expected in expected_categories.items():
        if category_counts[category] != int(expected):
            errors.append(f"category {category} count must be {expected}, got {category_counts[category]}")
    for split, expected in expected_splits.items():
        if split_counts[split] != int(expected):
            errors.append(f"split {split} count must be {expected}, got {split_counts[split]}")
    for vendor, bounds in expected_vendors.items():
        lower = int((bounds or {}).get("min", 0))
        upper = int((bounds or {}).get("max", 0))
        if not lower <= vendor_counts[vendor] <= upper:
            errors.append(f"vendor {vendor} count must be between {lower} and {upper}, got {vendor_counts[vendor]}")
    if double_review_count < int(review_policy.get("minimum_double_review_cases", 80) or 80):
        errors.append("at least 20% of cases require an independent secondary review")

    rendered = json.dumps(dataset, ensure_ascii=False, sort_keys=True, default=str)
    report = {
        "status": "PASS" if not errors else "FAIL",
        "dataset_id": _text(dataset.get("dataset_id")),
        "case_count": len(cases),
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "category_counts": dict(sorted(category_counts.items())),
        "vendor_counts": dict(sorted(vendor_counts.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "double_review_count": double_review_count,
        "errors": errors[:200],
        "error_count": len(errors),
        "database": "PostgreSQL",
        "sqlite": "not_used",
        "external_network": "forbidden",
        "secrets": bool(_SECRET_RE.search(rendered)),
        "customer_identifiers": _case_has_customer_key(dataset),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    report = validate_dataset(args.dataset, args.contract)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2 if report["status"] == "NOT_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
