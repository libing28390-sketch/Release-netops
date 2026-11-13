"""Repair built-in H3C wireless summary OIDs while preserving local catalog edits."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


VERSION = 269
NAME = "correct_h3c_wireless_oid_bindings"

_WRONG_SCALAR_OIDS = {
    "1.3.6.1.4.1.25506.2.75.1.1.1",
    "1.3.6.1.4.1.25506.2.75.1.1.1.0",
    "1.3.6.1.4.1.25506.2.75.1.1.2",
    "1.3.6.1.4.1.25506.2.75.1.1.2.0",
    "1.3.6.1.4.1.25506.2.75.1.1.3",
    "1.3.6.1.4.1.25506.2.75.1.1.3.0",
}
_CANONICAL_METRICS = {
    "hh3cDot11CurrOnlineAPNum": (
        "1.3.6.1.4.1.25506.2.75.1.1.2.21",
        "Current AP count connected to the H3C wireless controller (HH3C-DOT11-AC-MIB::hh3cDot11TotalAPconnected).",
    ),
    "hh3cDot11CurrAssocUserNum": (
        "1.3.6.1.4.1.25506.2.75.1.1.3.6",
        "Current associated wireless station count on the H3C wireless controller (HH3C-DOT11-AC-MIB::hh3cDot11StationCurAssocSum).",
    ),
}
_WRONG_TOTAL_AP_OID = "1.3.6.1.4.1.25506.2.75.1.1.3"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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


def _repair_config(config: dict[str, Any], builtin: dict[str, Any]) -> bool:
    changed = False
    for key in ("mib_sources", "source_urls"):
        values = config.get(key)
        if not isinstance(values, list):
            values = []
        existing = {str(value) for value in values}
        for value in builtin.get(key) or []:
            if str(value) not in existing:
                values.append(value)
                existing.add(str(value))
                changed = True
        if values:
            config[key] = values

    get_values = config.get("get")
    if not isinstance(get_values, list):
        get_values = []
    filtered_get = [value for value in get_values if str(value) not in _WRONG_SCALAR_OIDS]
    if filtered_get != get_values:
        config["get"] = filtered_get
        changed = True
    for value in builtin.get("get") or []:
        if value not in config.get("get", []):
            config.setdefault("get", []).append(value)
            changed = True

    metrics = config.get("metrics")
    if not isinstance(metrics, list):
        metrics = []
    repaired_metrics = []
    for metric_value in metrics:
        if not isinstance(metric_value, dict):
            repaired_metrics.append(metric_value)
            continue
        metric = dict(metric_value)
        name = str(metric.get("name") or "")
        oid = str(metric.get("oid") or "")
        if name == "hh3cDot11TotalAPNum" and oid == _WRONG_TOTAL_AP_OID:
            changed = True
            continue
        canonical = _CANONICAL_METRICS.get(name)
        if canonical and oid in _WRONG_SCALAR_OIDS:
            metric["oid"] = canonical[0]
            metric["help"] = canonical[1]
            changed = True
        repaired_metrics.append(metric)

    for builtin_metric in builtin.get("metrics") or []:
        if not isinstance(builtin_metric, dict):
            continue
        name = str(builtin_metric.get("name") or "")
        if not name or any(
            isinstance(existing, dict) and str(existing.get("name") or "") == name
            for existing in repaired_metrics
        ):
            continue
        repaired_metrics.append(dict(builtin_metric))
        changed = True
    if repaired_metrics != metrics:
        config["metrics"] = repaired_metrics
        changed = True
    return changed


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    from services.monitoring_oid_catalog import iter_builtin_catalog

    now = _now()
    for item in iter_builtin_catalog():
        if str(item.get("module_key") or "") != "h3c_wireless":
            continue
        variant = item.get("variant") or {}
        variant_id = str(variant.get("id") or "")
        if not variant_id:
            continue
        row = cursor.execute(
            """
            SELECT v.oid_config_json
              FROM snmp_module_variants v
              JOIN snmp_modules m ON m.id = v.module_id
             WHERE v.id = ? AND m.built_in = 1
            """,
            (variant_id,),
        ).fetchone()
        if not row:
            continue
        existing = _load_config(_row_value(row, "oid_config_json"))
        changed = _repair_config(existing, variant.get("oid_config") or {})
        if not changed:
            continue
        serialized = _json(existing)
        generator_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        mib_hash = hashlib.sha256(_json(existing.get("mib_sources") or []).encode("utf-8")).hexdigest()
        cursor.execute(
            """
            UPDATE snmp_module_variants
               SET oid_config_json = ?, generator_config_hash = ?, mib_hash = ?, updated_at = ?
             WHERE id = ?
            """,
            (serialized, generator_hash, mib_hash, now, variant_id),
        )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Restoring the invalid scalar bindings would reintroduce empty H3C metrics.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
