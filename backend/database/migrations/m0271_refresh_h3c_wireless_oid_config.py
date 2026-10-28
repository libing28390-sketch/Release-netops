"""Add verified H3C wireless OIDs to the persisted built-in variant."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


VERSION = 271
NAME = "refresh_h3c_wireless_oid_config"


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


def _merge_builtin(config: dict[str, Any], builtin: dict[str, Any]) -> bool:
    changed = False
    for key in ("mib_sources", "source_urls", "get", "walk"):
        existing = config.get(key) if isinstance(config.get(key), list) else []
        merged = list(existing)
        for value in builtin.get(key) or []:
            if value not in merged:
                merged.append(value)
                changed = True
        if merged != existing:
            config[key] = merged

    metrics = config.get("metrics") if isinstance(config.get("metrics"), list) else []
    merged_metrics = list(metrics)
    existing_by_name = {
        str(value.get("name") or value.get("source_name") or ""): value
        for value in merged_metrics
        if isinstance(value, dict)
    }
    for builtin_metric in builtin.get("metrics") or []:
        if not isinstance(builtin_metric, dict):
            continue
        name = str(builtin_metric.get("name") or builtin_metric.get("source_name") or "")
        existing = existing_by_name.get(name)
        if existing is None:
            merged_metric = dict(builtin_metric)
            merged_metrics.append(merged_metric)
            existing_by_name[name] = merged_metric
            changed = True
            continue
        if (
            name in {"hh3cDot11CurrOnlineAPNum", "hh3cDot11CurrAssocUserNum"}
            and str(existing.get("oid") or "") == str(builtin_metric.get("oid") or "")
            and "HH3C-DOT11-AC-MIB::" in str(existing.get("help") or "")
        ):
            existing["help"] = builtin_metric.get("help", existing.get("help"))
            changed = True
    if merged_metrics != metrics:
        config["metrics"] = merged_metrics
        changed = True

    schema_version = str(builtin.get("schema_version") or "1")
    if str(config.get("schema_version") or "") != schema_version:
        config["schema_version"] = schema_version
        changed = True
    return changed


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    from services.monitoring_oid_catalog import iter_builtin_catalog

    item = next(
        (value for value in iter_builtin_catalog() if str(value.get("module_key") or "") == "h3c_wireless"),
        None,
    )
    if not item:
        return
    variant = item.get("variant") or {}
    variant_id = str(variant.get("id") or "")
    builtin = variant.get("oid_config") or {}
    if not variant_id or not isinstance(builtin, dict):
        return
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
        return

    config = _load_config(_row_value(row, "oid_config_json"))
    if not _merge_builtin(config, builtin):
        return
    serialized = _json(config)
    generator_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    mib_hash = hashlib.sha256(_json(config.get("mib_sources") or []).encode("utf-8")).hexdigest()
    cursor.execute(
        """
        UPDATE snmp_module_variants
           SET oid_config_json = ?, generator_config_hash = ?, mib_hash = ?, updated_at = ?
         WHERE id = ?
        """,
        (serialized, generator_hash, mib_hash, _now(), variant_id),
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Removing the newly verified OIDs from the persisted catalog is not safe.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
