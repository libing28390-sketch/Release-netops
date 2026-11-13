"""Append verified optical metrics to built-in SNMP catalog variants.

The catalog source is authoritative for new built-in metrics, but existing
variant JSON may contain operator edits.  This migration therefore merges only
missing walk/source/metric entries and never replaces an existing value.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from services.monitoring_oid_catalog import iter_builtin_catalog


VERSION = 254
NAME = "append_optical_oid_metrics"


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


def _append_unique(config: dict[str, Any], key: str, additions: Any) -> bool:
    values = config.get(key)
    if not isinstance(values, list):
        values = []
    existing = {str(value) for value in values}
    changed = False
    for value in additions or []:
        if value is None or str(value) in existing:
            continue
        values.append(value)
        existing.add(str(value))
        changed = True
    if changed:
        config[key] = values
    return changed


def _append_metrics(config: dict[str, Any], additions: Any) -> bool:
    metrics = config.get("metrics")
    if not isinstance(metrics, list):
        metrics = []
    existing_names = {
        str(metric.get("name") or "")
        for metric in metrics
        if isinstance(metric, dict) and metric.get("name")
    }
    existing_oids = {
        str(metric.get("oid") or "")
        for metric in metrics
        if isinstance(metric, dict) and metric.get("oid")
    }
    changed = False
    for metric in additions or []:
        if not isinstance(metric, dict):
            continue
        name = str(metric.get("name") or "")
        oid = str(metric.get("oid") or "")
        if not name or not oid or name in existing_names or oid in existing_oids:
            continue
        metrics.append(dict(metric))
        existing_names.add(name)
        existing_oids.add(oid)
        changed = True
    if changed:
        config["metrics"] = metrics
    return changed


def _merge_config(existing: dict[str, Any], builtin: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    merged = dict(existing)
    changed = False
    for key in ("walk", "get", "mib_sources", "source_urls"):
        changed = _append_unique(merged, key, builtin.get(key)) or changed
    changed = _append_metrics(merged, builtin.get("metrics")) or changed
    return merged, changed


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    now = _now()
    for item in iter_builtin_catalog():
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
        merged, changed = _merge_config(existing, variant.get("oid_config") or {})
        if not changed:
            continue
        oid_json = _json(merged)
        generator_hash = hashlib.sha256(oid_json.encode("utf-8")).hexdigest()
        mib_hash = hashlib.sha256(_json(merged.get("mib_sources") or []).encode("utf-8")).hexdigest()
        cursor.execute(
            """
            UPDATE snmp_module_variants
               SET oid_config_json = ?, generator_config_hash = ?, mib_hash = ?, updated_at = ?
             WHERE id = ?
            """,
            (oid_json, generator_hash, mib_hash, now, variant_id),
        )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # The migration is append-only.  Removing metrics could delete operator
    # edits or leave compiled configurations referring to removed definitions.
    return None
