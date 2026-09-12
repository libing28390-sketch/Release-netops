"""Read-only evidence adapter shared by prefix discovery and CMDB jobs.

The adapter deliberately delegates command selection and TextFSM parsing to
``operational_data_service``.  It adds only a stable batch envelope and
category status so downstream discovery does not depend on vendor field names.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.neighbor_collection_contract import classify_lldp_status
from services.operational_data_service import collect_operational_data


READ_ONLY_EVIDENCE_CATEGORIES = (
    "interfaces",
    "interface_description",
    "vlan",
    "routing_table",
    "neighbors",
    "arp",
    "mac_table",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def collect_read_only_evidence(
    device_info: dict[str, Any],
    *,
    categories: list[str] | None = None,
    auth_role: str = "auto",
) -> dict[str, Any]:
    requested = [str(item).strip().lower() for item in (categories or READ_ONLY_EVIDENCE_CATEGORIES)]
    invalid = [item for item in requested if item not in READ_ONLY_EVIDENCE_CATEGORIES]
    if invalid:
        raise ValueError(f"Unsupported read-only evidence categories: {', '.join(sorted(set(invalid)))}")

    payload = collect_operational_data(device_info, categories=requested, auth_role=auth_role)
    categories_out: list[dict[str, Any]] = []
    for category in payload.get("categories") or []:
        item = dict(category)
        if item.get("key") == "neighbors":
            raw_outputs = item.get("raw_outputs") or []
            raw_text = "\n".join(str(output.get("output") or "") for output in raw_outputs if isinstance(output, dict))
            if not item.get("success"):
                item["collection_status"] = classify_lldp_status(raw_output=raw_text, error=ValueError(item.get("error") or "command failed"))
            else:
                item["collection_status"] = classify_lldp_status(
                    raw_output=raw_text,
                    parsed_count=int(item.get("count") or 0),
                )
        else:
            item["collection_status"] = "success" if item.get("success") and item.get("parse_status") == "matched" else (
                "command_failed" if not item.get("success") else "parse_failed"
            )
        categories_out.append(item)

    successful = sum(1 for item in categories_out if item.get("collection_status") == "success")
    return {
        "source": "automation_playbook_textfsm",
        "contract_version": "read-only-evidence-v1",
        "device": payload.get("device") or {
            "id": device_info.get("id"),
            "hostname": device_info.get("hostname"),
            "platform": device_info.get("platform"),
        },
        "collected_at": payload.get("collected_at") or _now(),
        "status": "success" if successful == len(categories_out) else "partial",
        "categories": categories_out,
        "summary": {
            "requested_categories": requested,
            "successful_categories": successful,
            "total_categories": len(categories_out),
            "total_records": sum(int(item.get("count") or 0) for item in categories_out),
        },
    }
