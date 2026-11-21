#!/usr/bin/env python3
"""Compare P4 review-sheet facts with current PostgreSQL IPAM ledgers.

This command is read-only. It reads formal Prefix/address-space/ledger tables
and current site labels, never historical discovery observations, and does not
infer or write target address-space decisions.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAPPING = REPO_ROOT / "docs/plans/ipam_p4_mapping_review_20261110.csv"
DEFAULT_DUPLICATES = REPO_ROOT / "docs/plans/ipam_p4_duplicate_review_20261110.csv"
sys.path.insert(0, str(REPO_ROOT / "backend"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _value(value) -> str:
    return "" if value is None else str(value).strip()


def _ids(value: str) -> set[str]:
    return {item.strip() for item in str(value or "").split("|") if item.strip()}


def _manual_override(value) -> str:
    return "1" if value is True or str(value or "").strip().lower() in {"1", "true", "t", "yes"} else "0"


def _read_current_state() -> dict:
    from database import get_db_connection

    conn = get_db_connection()
    try:
        conn.execute("BEGIN READ ONLY")
        prefixes = [
            dict(row)
            for row in conn.execute(
                """SELECT p.id, p.prefix, p.name, p.tenant_id, p.site_id,
                          site.site_name AS physical_site, p.network_type,
                          p.source_type, p.manual_override, p.vlan_id, p.gateway,
                          p.vrf_id, p.address_space_id
                     FROM prefixes p
                     LEFT JOIN sites site ON site.id = p.site_id
                    ORDER BY p.id"""
            ).fetchall()
        ]
        spaces = [
            dict(row)
            for row in conn.execute(
                "SELECT id, kind, vrf_id FROM ipam_address_spaces ORDER BY id"
            ).fetchall()
        ]
        active_context_mappings = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM ipam_device_routing_contexts WHERE status = 'active'"
            ).fetchone()["count"]
        )
        ledger_counts = {
            table: int(conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
            for table in ("ip_addresses", "ipam_pools", "ipam_vips", "ipam_dhcp_leases")
        }
        return {
            "prefixes": prefixes,
            "spaces": spaces,
            "active_context_mappings": active_context_mappings,
            "ledger_counts": ledger_counts,
        }
    finally:
        conn.rollback()
        conn.close()


def validate(mapping_path: Path, duplicate_path: Path) -> tuple[list[str], dict]:
    mapping_rows = _read_csv(mapping_path)
    duplicate_rows = _read_csv(duplicate_path)
    state = _read_current_state()
    prefixes = state["prefixes"]
    db_by_id = {str(row["id"]): row for row in prefixes}
    sheet_by_id = {str(row.get("prefix_id") or "").strip(): row for row in mapping_rows}
    mismatches: list[str] = []

    if len(sheet_by_id) != len(mapping_rows):
        mismatches.append("P4 mapping sheet contains empty or duplicate Prefix IDs")
    if set(sheet_by_id) != set(db_by_id):
        mismatches.append(
            "P4 mapping Prefix IDs differ from current database: "
            f"sheet_only={len(set(sheet_by_id) - set(db_by_id))}, "
            f"database_only={len(set(db_by_id) - set(sheet_by_id))}"
        )

    by_cidr: dict[str, list[dict]] = defaultdict(list)
    for prefix in prefixes:
        by_cidr[str(prefix["prefix"])].append(prefix)
    expected_duplicate_groups = {
        cidr: rows for cidr, rows in by_cidr.items() if len(rows) > 1
    }

    for prefix_id in sorted(set(sheet_by_id) & set(db_by_id)):
        row = sheet_by_id[prefix_id]
        current = db_by_id[prefix_id]
        facts = {
            "prefix_cidr": current.get("prefix"),
            "physical_site": current.get("physical_site"),
            "network_type": current.get("network_type"),
            "prefix_name": current.get("name"),
            "source_type": current.get("source_type"),
            "manual_override": _manual_override(current.get("manual_override")),
            "vlan_id": current.get("vlan_id"),
            "gateway": current.get("gateway"),
            "current_vrf_id": current.get("vrf_id"),
            "current_address_space_id": current.get("address_space_id"),
        }
        for field, actual in facts.items():
            if _value(row.get(field)) != _value(actual):
                mismatches.append(f"{prefix_id}:{field}")

    duplicate_by_cidr = {
        str(row.get("prefix_cidr") or "").strip(): row for row in duplicate_rows
    }
    if len(duplicate_by_cidr) != len(duplicate_rows):
        mismatches.append("P4 duplicate review contains empty or duplicate CIDRs")

    if set(duplicate_by_cidr) != set(expected_duplicate_groups):
        mismatches.append(
            "P4 duplicate CIDR groups differ from current database: "
            f"sheet_only={len(set(duplicate_by_cidr) - set(expected_duplicate_groups))}, "
            f"database_only={len(set(expected_duplicate_groups) - set(duplicate_by_cidr))}"
        )

    for cidr in sorted(set(duplicate_by_cidr) & set(expected_duplicate_groups)):
        group = duplicate_by_cidr[cidr]
        members = expected_duplicate_groups[cidr]
        member_ids = {str(row["id"]) for row in members}
        mapped_ids = {str(row["id"]) for row in members if row.get("address_space_id")}
        unmapped_ids = member_ids - mapped_ids
        space_ids = {str(row["address_space_id"]) for row in members if row.get("address_space_id")}
        site_names = {str(row["physical_site"]) for row in members if row.get("physical_site")}
        network_types = {str(row["network_type"]) for row in members if row.get("network_type")}
        facts = {
            "record_count": str(len(members)),
            "prefix_ids": member_ids,
            "mapped_prefix_ids": mapped_ids,
            "unmapped_prefix_ids": unmapped_ids,
            "existing_address_space_ids": space_ids,
            "physical_sites": site_names,
            "network_types": network_types,
        }
        for field, actual in facts.items():
            if field in {"record_count"}:
                matches = _value(group.get(field)) == actual
            else:
                matches = _ids(group.get(field) or "") == actual
            if not matches:
                mismatches.append(f"{cidr}:{field}")

    mapped_count = sum(bool(row.get("address_space_id")) for row in prefixes)
    address_space_kinds = dict(Counter(str(row["kind"]) for row in state["spaces"]))
    summary = {
        "prefixes": len(prefixes),
        "mapped_prefixes": mapped_count,
        "unmapped_prefixes": len(prefixes) - mapped_count,
        "duplicate_cidr_groups": len(expected_duplicate_groups),
        "duplicate_rows": sum(len(rows) for rows in expected_duplicate_groups.values()),
        "address_spaces": len(state["spaces"]),
        "address_space_kinds": address_space_kinds,
        "active_context_mappings": state["active_context_mappings"],
        "formal_ledgers": state["ledger_counts"],
        "mapping_sheet_rows": len(mapping_rows),
        "duplicate_sheet_rows": len(duplicate_rows),
        "fact_mismatches": mismatches,
        "historical_observation_tables_queried": False,
        "transaction_read_only": True,
        "target_scope_inferred": False,
    }
    return mismatches, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument("--duplicates", type=Path, default=DEFAULT_DUPLICATES)
    args = parser.parse_args()
    try:
        mismatches, summary = validate(args.mapping, args.duplicates)
    except Exception as exc:
        print(f"P4 live-fact validation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
