"""Audit the 50-anchor annotations without claiming human review.

This check is intentionally separate from the runtime evaluator.  It compares
Gold IDs with the checked-in official-template migration seeds, records an
explicit acceptable-document set, and emits the human-review fields still
needed before the frozen benchmark can be treated as production evidence.
It never treats a same-vendor document as a substitute for a missing Gold ID.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
DATASET_PATH = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-anchors-50.yaml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-anchors-50-review.json"
MIGRATIONS_PATH = ROOT / "backend" / "database" / "migrations"

REQUIRED_REVIEW_FIELDS = ("reviewer", "reviewed_at", "annotation_status")
_ID_RE = re.compile(r"[\"']id[\"']\s*:\s*[\"']([^\"']+)[\"']")
_OFFICIAL_LITERAL_RE = re.compile(r"(?<![A-Za-z0-9])official-[a-z0-9]+(?:-[a-z0-9]+)+")


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a mapping")
    return value


def _known_projected_document_ids() -> set[str]:
    """Collect projected IDs from checked-in migration seed literals.

    This is source evidence only; it is deliberately not described as a live
    PostgreSQL lookup.  A later isolated-PostgreSQL run must still confirm the
    resulting ``ai_document`` rows.
    """

    known: set[str] = set()
    for path in sorted(MIGRATIONS_PATH.glob("m*.py")):
        source = path.read_text(encoding="utf-8", errors="replace")
        for match in _ID_RE.finditer(source):
            template_id = match.group(1).strip()
            if template_id.startswith("official-"):
                known.add(f"official-template-{template_id}")
        # Older seed migrations keep template IDs in tuples passed to the
        # INSERT/UPDATE helper rather than in an ``{"id": ...}`` mapping.
        # Capture only the stable official-ID namespace; URLs and free-form
        # prose are intentionally not treated as document identities.
        for match in _OFFICIAL_LITERAL_RE.finditer(source):
            known.add(f"official-template-{match.group(0)}")
    return known


def _known_postgresql_document_ids() -> tuple[set[str], str, str | None]:
    """Read official document identities from the configured PostgreSQL DB.

    The query intentionally selects only ``document_id`` and never reads
    normalized/original content.  A failed read is reported as a validation
    state rather than being silently replaced with migration-source evidence.
    """

    try:
        from database import _USE_PG
        from database.core import get_db_connection

        if not _USE_PG:
            return set(), "postgresql_required", "configured database is not PostgreSQL"
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT document_id
                FROM ai_document
                WHERE tenant_id = ?
                  AND source_trust_level = 'official'
                  AND knowledge_source_type IN ('official_template', 'official_url')
                  AND COALESCE(exclude_from_rag, 0) = 0
                """,
                ("tenant-default",),
            ).fetchall()
        ids = {str(row[0]).strip() for row in rows if row and str(row[0]).strip()}
        return ids, "read_only_postgresql", None
    except Exception:
        # Do not expose connection strings, SQL details, or provider errors in
        # a durable review artifact.
        return set(), "postgresql_unavailable", "read-only PostgreSQL lookup failed"


def _known_postgresql_document_metadata() -> tuple[dict[str, dict[str, Any]], str, str | None]:
    """Read only the structured metadata needed for annotation consistency.

    The review audit must be able to say that a Gold ID exists without
    silently accepting a document whose vendor/platform/explicit feature is
    incompatible with the case.  Never select document bodies, chunks,
    prompts, answers, or source URLs here.
    """

    try:
        from database import _USE_PG
        from database.core import get_db_connection

        if not _USE_PG:
            return {}, "postgresql_required", "configured database is not PostgreSQL"
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT document_id, vendor, cli_platform, feature
                FROM ai_document
                WHERE tenant_id = ?
                  AND source_trust_level = 'official'
                  AND knowledge_source_type IN ('official_template', 'official_url')
                  AND COALESCE(exclude_from_rag, 0) = 0
                """,
                ("tenant-default",),
            ).fetchall()
        metadata = {
            str(row[0]).strip(): {
                "vendor": str(row[1]).strip() if row[1] is not None else None,
                "cli_platform": str(row[2]).strip() if row[2] is not None else None,
                "feature": str(row[3]).strip() if row[3] is not None else None,
            }
            for row in rows
            if row and str(row[0]).strip()
        }
        return metadata, "read_only_postgresql", None
    except Exception:
        # Do not expose connection strings, SQL details, or provider errors in
        # a durable review artifact.
        return {}, "postgresql_unavailable", "read-only PostgreSQL metadata lookup failed"


def _infer_feature(case: dict[str, Any]) -> tuple[str | None, str]:
    explicit = str(case.get("feature") or "").strip()
    if explicit:
        return explicit, "case_annotation"

    intent = str(case.get("intent") or "").strip().lower()
    query = str(case.get("query") or "").strip().lower()
    query_features = (
        # Port-security queries often mention a MAC address/count.  Match the
        # specific security phrase before the generic ARP/MAC diagnostic
        # markers so the review worksheet cannot suggest an unrelated Gold
        # feature.
        ("port-security", "port_security"),
        ("port security", "port_security"),
        ("端口安全", "port_security"),
        ("lldp", "lldp"),
        ("arp", "arp"),
        ("mac", "arp"),
        ("ospf", "ospf"),
        ("bgp", "bgp"),
        ("vlan", "vlan"),
        ("trunk", "trunk"),
        ("lacp", "lacp"),
        ("aggregateport", "lacp"),
        ("ntp", "ntp"),
        ("ssh", "ssh"),
        ("acl", "acl"),
        ("access-list", "acl"),
        # HSRP and VRRP are distinct first-hop redundancy protocols.  Keep
        # the review worksheet aligned with the runtime taxonomy instead of
        # suggesting a cross-protocol Gold annotation.
        ("hsrp", "hsrp"),
        ("vrrp", "vrrp"),
        ("vxlan", "vxlan"),
        ("evpn", "evpn"),
        ("route", "static_route"),
        ("路由", "static_route"),
        ("eth-trunk", "lacp"),
        ("聚合", "lacp"),
    )
    for marker, feature in query_features:
        if marker in query:
            return feature, "query_inference"
    if intent in {"vlan", "interface", "ospf", "ssh", "ntp", "route", "bgp", "lag", "acl", "bfd", "vxlan", "hsrp"}:
        return intent, "intent_inference"
    return None, "not_applicable_or_unresolved"


def _review_record(
    case: dict[str, Any],
    known_ids: set[str],
    known_metadata: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    case_id = str(case.get("id") or "UNKNOWN")
    expected_outcome = str(case.get("expected_outcome") or "").strip().lower()
    vendor = case.get("vendor")
    vendor = str(vendor).strip() if vendor else None
    platform = case.get("platform")
    platform = str(platform).strip() if platform else None
    gold_ids = [str(item).strip() for item in (case.get("gold_document_ids") or []) if str(item).strip()]
    acceptable_ids = [
        str(item).strip()
        for item in (case.get("acceptable_document_ids") or gold_ids)
        if str(item).strip()
    ]
    feature, feature_source = _infer_feature(case)
    unresolved_ids = sorted(set(acceptable_ids) - known_ids)
    missing_fields = [
        field for field in REQUIRED_REVIEW_FIELDS
        if not str(case.get(field) or "").strip()
    ]
    if expected_outcome in {"clarify", "no_match"} or bool(case.get("high_risk")):
        gold_policy = "not_required_guard_case"
    elif acceptable_ids:
        gold_policy = "required_acceptable_set"
    else:
        gold_policy = "missing_required_acceptable_set"

    missing_annotation_fields: list[str] = []
    if expected_outcome == "answer" and gold_policy != "not_required_guard_case":
        # The reviewer must record the feature explicitly.  Query/intent
        # inference is useful diagnostic context, but it is not an annotation
        # that can authorize feature-pollution or metadata consistency gates.
        for field in ("vendor", "platform", "feature"):
            if not str(case.get(field) or "").strip():
                missing_annotation_fields.append(field)

    metadata_validation: dict[str, Any] = {
        "status": "not_run",
        "mismatch_document_ids": [],
        "insufficient_document_ids": [],
        "checked_fields": [],
    }
    if known_metadata is not None and gold_policy != "not_required_guard_case":
        from ai.services.knowledge_metadata import (
            canonical_cli_platform,
            canonical_feature,
            canonical_vendor,
        )

        expected_vendor = canonical_vendor(vendor) if vendor else ""
        expected_platform = canonical_cli_platform(platform) if platform else ""
        expected_feature = canonical_feature(case.get("feature")) if case.get("feature") else ""
        expected_fields = {
            "vendor": expected_vendor,
            "cli_platform": expected_platform,
            "feature": expected_feature,
        }
        checked_fields = [key for key, value in expected_fields.items() if value]
        metadata_validation["checked_fields"] = checked_fields
        mismatch_ids: list[str] = []
        insufficient_ids: list[str] = []
        for document_id in acceptable_ids:
            document = known_metadata.get(document_id)
            if not document:
                continue
            missing_metadata_fields = [
                key for key in checked_fields
                if not str(document.get(key) or "").strip()
            ]
            if missing_metadata_fields:
                insufficient_ids.append(document_id)
                continue
            mismatched = [
                key for key in checked_fields
                if (
                    canonical_vendor(document.get(key)) if key == "vendor"
                    else canonical_cli_platform(document.get(key)) if key == "cli_platform"
                    else canonical_feature(document.get(key))
                ) != expected_fields[key]
            ]
            if mismatched:
                mismatch_ids.append(document_id)
        if acceptable_ids and not any(document_id in known_metadata for document_id in acceptable_ids):
            metadata_validation["status"] = "not_available"
        elif mismatch_ids and not (set(acceptable_ids) - set(mismatch_ids)):
            metadata_validation["status"] = "mismatch"
        elif insufficient_ids and not (set(acceptable_ids) - set(insufficient_ids)):
            metadata_validation["status"] = "insufficient"
        else:
            metadata_validation["status"] = "pass"
        metadata_validation["mismatch_document_ids"] = sorted(mismatch_ids)
        metadata_validation["insufficient_document_ids"] = sorted(insufficient_ids)

    return {
        "id": case_id,
        "expected_outcome": expected_outcome,
        "vendor": vendor,
        "platform": platform,
        "feature": feature,
        "feature_source": feature_source,
        "gold_document_ids": gold_ids,
        "acceptable_document_ids": acceptable_ids,
        "gold_policy": gold_policy,
        "missing_annotation_fields": missing_annotation_fields,
        "gold_id_source_status": "source_evidence_found" if not unresolved_ids else "unresolved_source_evidence",
        "unresolved_gold_document_ids": unresolved_ids,
        "reviewer": case.get("reviewer"),
        "reviewed_at": case.get("reviewed_at"),
        "annotation_status": case.get("annotation_status") or "pending_human_review",
        "missing_review_fields": missing_fields,
        "metadata_validation": metadata_validation,
    }


def validate_anchor_review(
    dataset: dict[str, Any] | None = None,
    *,
    known_ids: set[str] | None = None,
    known_metadata: Mapping[str, Mapping[str, Any]] | None = None,
    database_validation: str = "not_run_source_scan_only",
    database_error: str | None = None,
) -> dict[str, Any]:
    dataset = dataset or _load(DATASET_PATH)
    cases = dataset.get("cases") or []
    if not isinstance(cases, list) or not cases:
        raise ValueError("anchor dataset must contain a non-empty cases list")

    resolved_ids = known_ids if known_ids is not None else _known_projected_document_ids()
    records = [_review_record(case, resolved_ids, known_metadata) for case in cases]
    missing_review_cases = [record["id"] for record in records if record["missing_review_fields"]]
    unresolved_gold = {
        value
        for record in records
        for value in record["unresolved_gold_document_ids"]
    }
    missing_gold_cases = [
        record["id"]
        for record in records
        if record["gold_policy"] == "missing_required_acceptable_set"
    ]
    missing_annotation_field_cases = [
        record["id"] for record in records if record["missing_annotation_fields"]
    ]
    missing_feature_annotation_cases = [
        record["id"]
        for record in records
        if "feature" in record["missing_annotation_fields"]
    ]
    inferred_feature_cases = [
        record["id"] for record in records
        if record["feature_source"] != "case_annotation"
        and record["expected_outcome"] == "answer"
        and record["gold_policy"] != "not_required_guard_case"
    ]
    # An acceptable set is conjunctive at review time: every listed candidate
    # must carry compatible metadata before a reviewer can approve it.  Do not
    # hide a bad candidate merely because another candidate in the set passes.
    metadata_mismatch_cases = [
        record["id"]
        for record in records
        if record["metadata_validation"].get("mismatch_document_ids")
    ]
    metadata_insufficient_cases = [
        record["id"]
        for record in records
        if (
            record["metadata_validation"].get("status") in {"insufficient", "not_available"}
            or record["metadata_validation"].get("insufficient_document_ids")
        )
        and record["gold_policy"] != "not_required_guard_case"
    ]

    review_status = "PASS" if not missing_review_cases else "PENDING_HUMAN_REVIEW"
    gold_status = "PASS" if not (
        unresolved_gold
        or missing_gold_cases
        or missing_annotation_field_cases
        or metadata_mismatch_cases
        or metadata_insufficient_cases
    ) else "FAIL"
    overall_status = "PASS" if review_status == "PASS" and gold_status == "PASS" else "FAIL"

    report = {
        "schema_version": 1,
        "dataset_id": dataset.get("dataset_id"),
        "status": overall_status,
        "review_status": review_status,
        "gold_status": gold_status,
        "database_validation": database_validation,
        "database_error": database_error,
        "human_review_required": True,
        "case_count": len(records),
        "vendor_counts": dict(sorted(Counter(str(record["vendor"] or "unknown") for record in records).items())),
        "missing_review_field_cases": missing_review_cases,
        "missing_gold_cases": missing_gold_cases,
        "missing_annotation_field_cases": missing_annotation_field_cases,
        "missing_feature_annotation_cases": missing_feature_annotation_cases,
        "unresolved_gold_document_ids": sorted(unresolved_gold),
        "inferred_feature_cases": inferred_feature_cases,
        "metadata_mismatch_cases": metadata_mismatch_cases,
        "metadata_insufficient_cases": metadata_insufficient_cases,
        "known_projected_document_id_count": len(resolved_ids),
        "records": records,
    }
    return report


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        action="store_true",
        help="perform a read-only official-document identity lookup in PostgreSQL",
    )
    args = parser.parse_args()
    if args.database:
        database_metadata, validation, database_error = _known_postgresql_document_metadata()
        report = validate_anchor_review(
            known_ids=set(database_metadata),
            known_metadata=database_metadata,
            database_validation=validation,
            database_error=database_error,
        )
        report["source_scan_known_projected_document_id_count"] = len(_known_projected_document_ids())
    else:
        report = validate_anchor_review()
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "50-anchor review audit: "
        f"status={report['status']} "
        f"review={report['review_status']} "
        f"gold={report['gold_status']} "
        f"cases={report['case_count']} "
        f"missing_review={len(report['missing_review_field_cases'])} "
        f"unresolved_gold={len(report['unresolved_gold_document_ids'])}"
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
