"""Build reviewed official knowledge documents from the governed YAML catalog.

The command is deliberately dry-run by default.  ``--apply`` is required for
network access and PostgreSQL writes, and the caller must provide both an
explicit source selection and terms-review evidence.  The script delegates
URL validation, robots/SSRF checks, source registration, parsing, cleaning,
chunking, embeddings, deduplication, and publication to the existing service
boundaries.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CATALOG = ROOT / "docs" / "knowledge-engine" / "governance" / "official-document-source-catalog.yaml"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


SUPPORTED_SOURCE_KINDS = {
    "official_url",
    "product_page",
    "configuration_guide",
    "command_reference",
    "troubleshooting_guide",
    "release_note",
    "product_support",
}
COLLECTABLE_STATUSES = {
    "candidate_registry_review",
    "candidate_allowlist_review",
    "candidate_taxonomy_and_registry_review",
    "candidate_taxonomy_and_allowlist_review",
}
CATEGORY_BY_KIND = {
    "configuration_guide": "configuration",
    "command_reference": "command",
    "troubleshooting_guide": "troubleshooting",
    "release_note": "troubleshooting",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_catalog(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict) or not isinstance(value.get("vendors"), list):
        raise ValueError("catalog must contain a vendors list")
    return value


def _flatten_sources(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for vendor in catalog["vendors"]:
        if not isinstance(vendor, dict):
            raise ValueError("each vendor entry must be an object")
        vendor_name = str(vendor.get("vendor") or "").strip()
        if not vendor_name:
            raise ValueError("vendor name is required")
        for source in vendor.get("sources") or []:
            if not isinstance(source, dict):
                raise ValueError(f"source entry for {vendor_name} must be an object")
            row = dict(source)
            row["vendor_record"] = vendor
            row["vendor"] = vendor_name
            rows.append(row)
    return rows


def _selection(args: argparse.Namespace, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requested_ids = {str(item).strip() for item in args.source_id if str(item).strip()}
    requested_vendors = {str(item).strip().casefold() for item in args.vendor if str(item).strip()}
    if not requested_ids and not requested_vendors:
        raise ValueError("an explicit --source-id or --vendor selector is required")
    known_ids = {str(row.get("source_id") or "") for row in rows}
    unknown_ids = sorted(requested_ids - known_ids)
    if unknown_ids:
        raise ValueError("unknown source_id: " + ", ".join(unknown_ids))

    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in rows:
        source_id = str(row.get("source_id") or "")
        vendor = str(row.get("vendor") or "")
        if requested_ids and source_id not in requested_ids and vendor.casefold() not in requested_vendors:
            continue
        if not requested_ids and vendor.casefold() not in requested_vendors:
            continue
        if args.priority and str(row.get("priority") or "") != args.priority:
            continue
        status = str(row.get("collection_status") or "")
        if status == "discovery_only":
            skipped.append({"source_id": source_id, "reason": "discovery_only"})
            continue
        if status == "active_valid_existing":
            skipped.append({"source_id": source_id, "reason": "already_active_valid_in_pg"})
            continue
        if status not in COLLECTABLE_STATUSES:
            skipped.append({"source_id": source_id, "reason": f"status_not_collectable:{status}"})
            continue
        kind = str(row.get("desired_document_type") or row.get("source_type") or "").strip().lower()
        if kind not in SUPPORTED_SOURCE_KINDS:
            skipped.append({"source_id": source_id, "reason": f"source_kind_not_supported:{kind}"})
            continue
        if not bool(row.get("direct_ingestion") is False):
            skipped.append({"source_id": source_id, "reason": "catalog_direct_ingestion_flag_not_false"})
            continue
        selected.append(row)
    return selected, skipped


def _version_scope(row: dict[str, Any]) -> dict[str, str]:
    vendor = row["vendor_record"]
    row_scope = row.get("registry_version_scope") or {}
    vendor_scope = vendor.get("registry_version_scope") or {}
    raw = str(row.get("version_scope") or "").strip()
    primary = str(row_scope.get("primary") or vendor_scope.get("primary") or "").strip() if raw == "document-defined" else str(row_scope.get("primary") or raw).strip()
    compatibility = str(row_scope.get("compatibility") or vendor_scope.get("compatibility") or "").strip()
    if not primary or not compatibility:
        raise ValueError(f"version scope is incomplete for {row.get('source_id')}")
    return {"primary": primary, "compatibility": compatibility}


def _payload(row: dict[str, Any], *, catalog_id: str, reviewer: str, terms_status: str, reviewed_at: str, tenant_id: str) -> dict[str, Any]:
    vendor = row["vendor_record"]
    kind = str(row.get("desired_document_type") or row.get("source_type") or "").strip().lower()
    product_family = str(vendor.get("registry_product_family") or row.get("product_scope") or "").strip()
    if not product_family:
        raise ValueError(f"registry product family is incomplete for {row.get('source_id')}")
    payload = {
        "url": str(row.get("canonical_url") or "").strip(),
        "source_kind": kind,
        "vendor": str(row.get("vendor") or "").strip(),
        "product_family": product_family,
        "version_scope": _version_scope(row),
        "terms_review_status": terms_status,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "name": str(row.get("title") or row.get("source_id") or "Official document").strip(),
        "description": f"Official {kind} imported from governed catalog source {row.get('source_id')}",
        "product_series": str(row.get("product_scope") or product_family).strip(),
        "platform_code": str(row.get("platform_code") or vendor.get("registry_platform_code") or "").strip(),
        "os_family": str(row.get("os_family") or vendor.get("registry_os_family") or "").strip(),
        "document_category": CATEGORY_BY_KIND.get(kind, "hardware"),
        "idempotency_key": f"official-catalog:{catalog_id}:{row.get('source_id')}",
        "request_id": f"official-catalog:{row.get('source_id')}",
        "max_retries": 1,
        "publish_to_knowledge_base": True,
        "tenant_id": tenant_id,
    }
    if not payload["url"].startswith("https://"):
        raise ValueError(f"source URL is not HTTPS for {row.get('source_id')}")
    return payload


def _preview(selected: list[dict[str, Any]], skipped: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "mode": "dry-run",
        "selected_count": len(selected),
        "skipped_count": len(skipped),
        "selected": [
            {
                "source_id": row.get("source_id"),
                "vendor": row.get("vendor"),
                "url": row.get("canonical_url"),
                "source_kind": row.get("desired_document_type") or row.get("source_type"),
                "collection_status": row.get("collection_status"),
            }
            for row in selected
        ],
        "skipped": skipped,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--source-id", action="append", default=[])
    parser.add_argument("--vendor", action="append", default=[])
    parser.add_argument("--priority", choices=("P0", "P1", "P2"), default="")
    parser.add_argument("--tenant-id", default="tenant-default")
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--terms-review-status", choices=("approved", "waived", "not_required"), default="")
    parser.add_argument("--reviewed-at", default="")
    parser.add_argument("--rate-limit-per-minute", type=int, default=6)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--backoff-base-seconds", type=float, default=0.25)
    parser.add_argument("--apply", action="store_true", help="Fetch selected official URLs and publish to PostgreSQL")
    args = parser.parse_args(argv)

    try:
        catalog = _load_catalog(args.catalog)
        rows = _flatten_sources(catalog)
        selected, skipped = _selection(args, rows)
        if not selected:
            raise ValueError("selection contains no collectable candidate sources")
        if not args.apply:
            print(json.dumps(_preview(selected, skipped), ensure_ascii=False, indent=2))
            return 0
        if not args.reviewer:
            raise ValueError("--reviewer is required with --apply")
        if not args.terms_review_status:
            raise ValueError("--terms-review-status is required with --apply")
        reviewed_at = args.reviewed_at or _now()
        from services.official_seed_batch_service import collect_official_seed_batch

        user = {
            "id": args.reviewer,
            "username": args.reviewer,
            "role": "Administrator",
            "tenant_id": args.tenant_id,
        }
        items = [
            _payload(
                row,
                catalog_id=str(catalog.get("catalog_id") or "official-catalog"),
                reviewer=args.reviewer,
                terms_status=args.terms_review_status,
                reviewed_at=reviewed_at,
                tenant_id=args.tenant_id,
            )
            for row in selected
        ]
        result = collect_official_seed_batch(
            user,
            items,
            rate_limit_per_minute=args.rate_limit_per_minute,
            concurrency=args.concurrency,
            backoff_base_seconds=args.backoff_base_seconds,
            request_id=f"official-catalog-build:{args.reviewer}",
        )
        result["skipped"] = skipped
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if int(result.get("failed_count") or 0) == 0 else 2
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)[:500]}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
