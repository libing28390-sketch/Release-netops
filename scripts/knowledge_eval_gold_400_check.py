#!/usr/bin/env python3
"""Validate the official-source-backed 400-case Knowledge Engine dataset.

This is a completeness, provenance, and safety gate, not an answer generator.
The dataset policy does not require human review: every answer case must carry
an HTTPS source URL on an allow-listed vendor domain.  The command never
connects to a database or writes production data.
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
from urllib.parse import urlsplit

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
OFFICIAL_HOSTS = {
    "Huawei": {"support.huawei.com", "info.support.huawei.com"},
    "Cisco": {"www.cisco.com"},
    "H3C": {"www.h3c.com"},
    "Ruijie": {"www.ruijie.com.cn"},
}
OFFICIAL_SOURCE_TYPES = {"official_vendor_documentation", "official_url_backed_local_summary"}
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


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


def _source_evidence_valid(
    value: Any,
    vendor: str,
    official_manifest_sources: Mapping[str, tuple[str, set[str]]] | None = None,
) -> bool:
    entries = _list(value)
    if not entries:
        return False
    allowed_hosts = set().union(*(OFFICIAL_HOSTS.values())) if vendor == "cross_vendor_or_unknown" else OFFICIAL_HOSTS.get(vendor, set())
    for entry in entries:
        if not isinstance(entry, Mapping):
            return False
        if not _text(entry.get("document_id")) or not _text(entry.get("locator")):
            return False
        if not _SAFE_ID_RE.fullmatch(_text(entry.get("document_id"))):
            return False
        source_url = _text(entry.get("url") or entry.get("source_url"))
        parsed = urlsplit(source_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.casefold() not in allowed_hosts:
            return False
        if parsed.username or parsed.password:
            return False
        source_type = _text(entry.get("source_type"))
        if source_type and source_type not in OFFICIAL_SOURCE_TYPES:
            return False
        if official_manifest_sources is not None:
            manifest_source = official_manifest_sources.get(_text(entry.get("document_id")))
            if manifest_source is None:
                return False
            manifest_vendor, manifest_urls = manifest_source
            if vendor != "cross_vendor_or_unknown" and manifest_vendor != vendor:
                return False
            if source_url not in manifest_urls:
                return False
    return True


def _load_official_manifest_sources(
    collection: Mapping[str, Any],
    errors: list[str],
) -> dict[str, tuple[str, set[str]]]:
    """Load the source manifest and return document ID -> vendor/URL mappings."""
    raw_path = _text(collection.get("source_manifest"))
    if not raw_path:
        errors.append("collection.source_manifest must identify the official source manifest")
        return {}
    manifest_path = Path(raw_path)
    resolved_path = (manifest_path if manifest_path.is_absolute() else ROOT / manifest_path).resolve()
    try:
        resolved_path.relative_to(ROOT.resolve())
    except ValueError:
        errors.append("collection.source_manifest must stay inside the repository")
        return {}
    if not resolved_path.is_file():
        errors.append("collection.source_manifest file is not present")
        return {}

    expected_sha256 = _text(collection.get("source_manifest_sha256"))
    if not _SHA256_RE.fullmatch(expected_sha256):
        errors.append("collection.source_manifest_sha256 must be a 64-character SHA-256")
    else:
        actual_sha256 = hashlib.sha256(resolved_path.read_bytes()).hexdigest()
        if actual_sha256.casefold() != expected_sha256.casefold():
            errors.append("collection.source_manifest_sha256 does not match the manifest")

    try:
        payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.append("collection.source_manifest is not valid JSON")
        return {}
    documents = payload.get("documents") if isinstance(payload, Mapping) else None
    if not isinstance(documents, list):
        errors.append("collection.source_manifest must contain a documents list")
        return {}

    sources: dict[str, tuple[str, set[str]]] = {}
    for document in documents:
        if not isinstance(document, Mapping):
            continue
        document_id = _text(document.get("document_id"))
        vendor = _text(document.get("vendor"))
        urls = {
            _text(url)
            for url in _list(document.get("source_urls"))
            if _text(url)
        }
        if not document_id or not vendor or not urls:
            continue
        if document_id in sources:
            errors.append(f"collection.source_manifest contains duplicate document_id: {document_id}")
            continue
        sources[document_id] = (vendor, urls)
    return sources


def validate_dataset(
    dataset_path: Path = DEFAULT_DATASET,
    contract_path: Path = DEFAULT_CONTRACT,
    *,
    require_production: bool = False,
) -> dict[str, Any]:
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
            "errors": ["official-source-backed 400-case dataset is not present"],
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
    contract_review_policy = (
        contract.get("review_policy") if isinstance(contract, Mapping) and isinstance(contract.get("review_policy"), Mapping) else {}
    )
    if contract_review_policy.get("human_review_required") is not False:
        errors.append("contract.review_policy.human_review_required must be false for the automated 400-case dataset")
    if int(contract_review_policy.get("minimum_double_review_cases", 0) or 0) != 0:
        errors.append("contract.review_policy.minimum_double_review_cases must be 0 for the automated 400-case dataset")
    if contract_review_policy.get("review_mode") != "official_source_provenance_automated":
        errors.append("contract.review_policy.review_mode must be official_source_provenance_automated")

    review_policy = dataset.get("review_policy") if isinstance(dataset.get("review_policy"), Mapping) else {}
    human_review_required = review_policy.get("human_review_required")
    if not isinstance(human_review_required, bool):
        human_review_required = True
    if human_review_required is not False:
        errors.append("dataset.review_policy.human_review_required must be false; human review is not a 400-case gate")
    if int(review_policy.get("minimum_double_review_cases", 0) or 0) != 0:
        errors.append("dataset.review_policy.minimum_double_review_cases must be 0; double review is not a 400-case gate")
    if review_policy.get("review_mode") != "official_source_provenance_automated":
        errors.append("dataset.review_policy.review_mode must be official_source_provenance_automated")

    if dataset.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if not _DATASET_ID_RE.fullmatch(_text(dataset.get("dataset_id"))):
        errors.append("dataset_id must match nexora-kb-eval-gold-400-vN-YYYYMMDD")
    if dataset.get("status") != "frozen":
        errors.append("status must be frozen")
    if not isinstance(dataset.get("test_only"), bool):
        errors.append("test_only must be boolean")
    if not isinstance(dataset.get("synthetic_data"), bool):
        errors.append("synthetic_data must be boolean")
    if require_production and dataset.get("test_only") is True:
        errors.append("test-only dataset cannot satisfy the production gate")
    if require_production and dataset.get("synthetic_data") is True:
        errors.append("synthetic dataset cannot satisfy the production gate")
    if require_production and dataset.get("production_eligible") is not True:
        errors.append("production_eligible must be true for the production gate")
    if dataset.get("case_count") != 400 or len(cases) != 400:
        errors.append(f"case_count must be 400 (declared={dataset.get('case_count')!r}, actual={len(cases)})")
    source_policy = dataset.get("source_policy") if isinstance(dataset.get("source_policy"), Mapping) else {}
    for key, expected in {
        "database": "PostgreSQL",
        "sqlite": "not_used",
        "external_network": "forbidden",
        "secrets": "forbidden",
        "production_data": "forbidden",
        "official_sources": "required",
        "source_collection": "official_url_backed_local_summary",
    }.items():
        if source_policy.get(key) != expected:
            errors.append(f"source_policy.{key} must be {expected}")
    collection = dataset.get("collection") if isinstance(dataset.get("collection"), Mapping) else {}
    if not collection:
        errors.append("collection must identify the official source manifest")
    if collection.get("mode") != "official_url_backed_local_summary":
        errors.append("collection.mode must be official_url_backed_local_summary")
    collection_review_required = collection.get("human_review_required") if collection else None
    if collection_review_required is not False:
        errors.append("collection.human_review_required must be false; provenance is checked automatically")
    official_manifest_sources = _load_official_manifest_sources(collection, errors) if collection else {}
    coverage = dataset.get("coverage") if isinstance(dataset.get("coverage"), Mapping) else {}
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
        source_evidence = case.get("source_evidence")
        if outcome == "answer":
            if not _source_evidence_valid(source_evidence, vendor, official_manifest_sources):
                errors.append(f"{prefix} answer source_evidence must match an official manifest document and HTTPS URL")
        elif source_evidence and not _source_evidence_valid(source_evidence, vendor, official_manifest_sources):
            errors.append(f"{prefix} source_evidence is incomplete or not official")
        annotator = _text(case.get("annotator"))
        reviewer = _text(case.get("reviewer"))
        if human_review_required:
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
    minimum_double_review_cases = int(review_policy.get("minimum_double_review_cases", 0) or 0)
    if human_review_required and double_review_count < minimum_double_review_cases:
        errors.append(f"at least {minimum_double_review_cases} cases require an independent secondary review")

    rendered = json.dumps(dataset, ensure_ascii=False, sort_keys=True, default=str)
    report = {
        "status": "PASS" if not errors else "FAIL",
        "dataset_id": _text(dataset.get("dataset_id")),
        "test_only": dataset.get("test_only") is True,
        "synthetic_data": dataset.get("synthetic_data") is True,
        "production_eligible": dataset.get("production_eligible") is True,
        "production_gate": require_production,
        "case_count": len(cases),
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "category_counts": dict(sorted(category_counts.items())),
        "vendor_counts": dict(sorted(vendor_counts.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "double_review_count": double_review_count,
        "human_review_required": human_review_required,
        "official_source_evidence_case_count": sum(
            1
            for case in cases
            if isinstance(case, Mapping)
            and _text(case.get("expected_outcome")) == "answer"
            and _source_evidence_valid(
                case.get("source_evidence"),
                _text(case.get("vendor")) or "cross_vendor_or_unknown",
                official_manifest_sources,
            )
        ),
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
    parser.add_argument(
        "--require-production",
        action="store_true",
        help="require a non-test, non-synthetic, production-eligible official-source dataset",
    )
    args = parser.parse_args(argv)
    report = validate_dataset(
        args.dataset,
        args.contract,
        require_production=args.require_production,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2 if report["status"] == "NOT_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
