"""Register every built-in vendor/wireless OID catalog entry in the baseline plan."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from services.monitoring_oid_catalog import iter_builtin_catalog
from database.migrations.m0233_vendor_snmp_oid_catalog import upgrade as _ensure_catalog_rows


VERSION = 243
NAME = "expand_catalog_collection_plan"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row_value(row, key: str, index: int = 0):
    return row.get(key) if hasattr(row, "get") else row[index]


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Older installations may already have this plan (or may have received
    # plan entries from a development snapshot) while their database stopped
    # before the corresponding built-in module/variant rows were registered.
    # Re-run the idempotent catalog seeding first so every plan reference is
    # backed by a real module and variant before the compiler sees it.  This
    # is intentionally limited to built-in catalog rows; custom rows and
    # operator edits remain untouched by m0233's conflict-safe seed logic.
    _ensure_catalog_rows(cursor, use_pg)
    row = cursor.execute(
        "SELECT config_json FROM monitoring_collection_plans WHERE id = ?",
        ("plan-generic-ifmib",),
    ).fetchone()
    if not row:
        return
    raw = _row_value(row, "config_json")
    try:
        config = json.loads(raw or "{}") if isinstance(raw, str) else dict(raw or {})
    except (TypeError, ValueError):
        config = {}
    entries = config.get("modules")
    if not isinstance(entries, list):
        entries = []
    existing = {
        str(item.get("variant") or item.get("variant_key") or "")
        for item in entries
        if isinstance(item, dict)
    }
    changed = False
    for item in iter_builtin_catalog():
        module = item
        variant = item.get("variant") or {}
        feature_domain = str(module.get("feature_domain") or "").casefold()
        variant_key = str(variant.get("variant_key") or "")
        if feature_domain not in {"hardware", "wireless"} or not variant_key or variant_key in existing:
            continue
        vendor = str(module.get("vendor") or "").strip()
        supported_platforms = list(variant.get("supported_platforms") or [])
        entry = {
            "module": str(module.get("module_key") or ""),
            "variant": variant_key,
            "vendor": [vendor] if vendor else [],
            "platform": supported_platforms,
            "interval": "60s" if feature_domain == "hardware" else "120s",
            "scrape_timeout": "20s",
            "enabled": True,
        }
        entries.append(entry)
        existing.add(variant_key)
        changed = True
    if changed:
        cursor.execute(
            "UPDATE monitoring_collection_plans SET config_json = ?, updated_at = ? WHERE id = ?",
            (_json({**config, "modules": entries}), _now(), "plan-generic-ifmib"),
        )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # The catalog plan is additive and may contain operator edits; leave entries
    # in place on downgrade so a previous binary does not silently lose them.
    return None
