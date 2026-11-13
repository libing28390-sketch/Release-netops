"""Disable the old SNMP Exporter wireless variants superseded by rule adapters."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


VERSION = 280
NAME = "retire_legacy_wireless_oid_variants"

_RETIRED_VARIANTS = frozenset({
    "huawei_wireless_std",
    "h3c_wireless_std",
    "ruijie_wireless_std",
    "cisco_wireless_std",
    "aruba_wireless_std",
    "ruckus_wireless_std",
})
_DISABLED_REASON = "superseded by the Python wireless adapter synchronized to the pinned LibreNMS sources"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_value(row: Any, key: str, index: int = 0) -> Any:
    return row.get(key) if hasattr(row, "get") else row[index]


def _load_config(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            value = json.loads(raw or "{}")
        except (TypeError, ValueError):
            value = {}
    else:
        value = raw
    return dict(value) if isinstance(value, dict) else {}


def _disable_plan_entries(cursor: Any, now: str) -> None:
    rows = cursor.execute(
        "SELECT id, config_json FROM monitoring_collection_plans"
    ).fetchall()
    for row in rows:
        plan_id = str(_row_value(row, "id") or "")
        config = _load_config(_row_value(row, "config_json"))
        changed = False
        for key in ("modules", "assignments"):
            entries = config.get(key)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                variant_key = str(entry.get("variant") or entry.get("variant_key") or "")
                if variant_key not in _RETIRED_VARIANTS:
                    continue
                if entry.get("enabled", True) is not False:
                    entry["enabled"] = False
                    changed = True
                if entry.get("disabled_reason") != _DISABLED_REASON:
                    entry["disabled_reason"] = _DISABLED_REASON
                    changed = True
        if changed and plan_id:
            cursor.execute(
                "UPDATE monitoring_collection_plans SET config_json = ?, updated_at = ? WHERE id = ?",
                (
                    json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    now,
                    plan_id,
                ),
            )


def upgrade(cursor, use_pg: bool) -> None:
    """Stop compiling duplicate vendor OID wireless rules without deleting their history."""
    del use_pg  # The migration uses SQL and JSON text supported by PostgreSQL.
    now = _now()
    variant_placeholders = ", ".join("?" for _ in _RETIRED_VARIANTS)

    _disable_plan_entries(cursor, now)

    cursor.execute(
        f"""
        UPDATE monitoring_collection_assignments
           SET enabled = 0, updated_at = ?
         WHERE module_variant_id IN (
             SELECT v.id
               FROM snmp_module_variants v
               JOIN snmp_modules m ON m.id = v.module_id
              WHERE m.built_in = 1 AND v.variant_key IN ({variant_placeholders})
         )
        """,
        (now, *_RETIRED_VARIANTS),
    )
    cursor.execute(
        f"""
        UPDATE snmp_module_variants
           SET enabled = 0, status = 'DRAFT', updated_at = ?
         WHERE module_id IN (
             SELECT id FROM snmp_modules WHERE built_in = 1
         )
           AND variant_key IN ({variant_placeholders})
        """,
        (now, *_RETIRED_VARIANTS),
    )
    cursor.execute(
        """
        UPDATE snmp_modules
           SET enabled = 0, updated_at = ?
         WHERE built_in = 1 AND module_key IN (
             'huawei_wireless', 'h3c_wireless', 'ruijie_wireless',
             'cisco_wireless', 'aruba_wireless', 'ruckus_wireless'
         )
        """,
        (now,),
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep the legacy OID variants disabled so rollback cannot silently
    # reintroduce duplicate collection alongside the LibreNMS adapters.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
