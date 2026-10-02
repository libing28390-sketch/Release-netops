"""Repair AI document platforms that are incompatible with their vendors.

Knowledge uploads historically defaulted every document to ``huawei_vrp``.
Asset inventory is the source of truth for the supported vendor/platform
combinations, so this migration repairs only blank values and the known
cross-vendor Huawei default. Explicit compatible platform choices are kept.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict

VERSION = 110
NAME = "repair_ai_document_platforms"

_KNOWN_DEFAULTS = {
    "cisco": "cisco_ios",
    "huawei": "huawei_vrp",
    "h3c": "h3c_comware",
    "arista": "arista_eos",
    "juniper": "juniper_junos",
    "ruijie": "ruijie_rgos",
    "zte": "zte_zxros",
    "maipu": "maipu",
    "dptech": "dptech_conplat",
}


def _vendor_key(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if "h3c" in normalized or "comware" in normalized:
        return "h3c"
    for key in _KNOWN_DEFAULTS:
        if key in normalized:
            return key
    return normalized


def _asset_platform_defaults(cursor) -> dict[str, str]:
    options: dict[str, Counter[str]] = defaultdict(Counter)
    rows = cursor.execute(
        "SELECT vendor, platform, COUNT(*) "
        "FROM physical_assets "
        "WHERE asset_type = ? "
        "AND TRIM(COALESCE(vendor, '')) <> '' "
        "AND TRIM(COALESCE(platform, '')) <> '' "
        "GROUP BY vendor, platform",
        ("network_device",),
    ).fetchall()
    for row in rows:
        key = _vendor_key(row[0])
        platform = str(row[1] or "").strip()
        if key and platform:
            options[key][platform] += int(row[2] or 0)

    defaults = dict(_KNOWN_DEFAULTS)
    for key, counts in options.items():
        # Use the canonical default when one exists; otherwise follow the
        # platform most commonly represented by asset inventory.
        defaults[key] = defaults.get(key) or counts.most_common(1)[0][0]
    return defaults


def upgrade(cursor, use_pg: bool) -> None:
    preferred_platforms = _asset_platform_defaults(cursor)
    documents = cursor.execute(
        "SELECT id, vendor, platform FROM ai_document"
    ).fetchall()

    for row in documents:
        document_id = str(row[0])
        vendor = str(row[1] or "").strip()
        old_platform = str(row[2] or "").strip()
        key = _vendor_key(vendor)
        preferred = preferred_platforms.get(key)
        if not preferred:
            continue

        old_platform_key = old_platform.lower()
        is_blank = not old_platform_key or old_platform_key == "all"
        is_cross_vendor_huawei_default = key != "huawei" and old_platform_key == "huawei_vrp"
        if not (is_blank or is_cross_vendor_huawei_default):
            continue

        cursor.execute(
            "UPDATE ai_document SET platform = ? WHERE id = ?",
            (preferred, document_id),
        )

        chunks = cursor.execute(
            "SELECT id, metadata_json FROM ai_document_chunk WHERE document_id = ?",
            (document_id,),
        ).fetchall()
        for chunk in chunks:
            try:
                metadata = json.loads(chunk[1] or "{}")
            except (TypeError, ValueError):
                continue
            if not isinstance(metadata, dict):
                continue
            metadata["platform"] = preferred
            cursor.execute(
                "UPDATE ai_document_chunk SET metadata_json = ? WHERE id = ?",
                (json.dumps(metadata, ensure_ascii=False), chunk[0]),
            )
