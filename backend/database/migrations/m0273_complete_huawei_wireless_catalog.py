"""Add the verified Huawei AP Radio and VAP wireless polling catalog."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


VERSION = 273
NAME = "complete_huawei_wireless_catalog"


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
    repaired = [dict(value) if isinstance(value, dict) else value for value in metrics]
    positions = {
        str(value.get("name") or ""): index
        for index, value in enumerate(repaired)
        if isinstance(value, dict) and value.get("name")
    }
    for expected in builtin.get("metrics") or []:
        if not isinstance(expected, dict):
            continue
        name = str(expected.get("name") or "")
        index = positions.get(name)
        if index is None:
            positions[name] = len(repaired)
            repaired.append(dict(expected))
            changed = True
            continue
        current = repaired[index]
        if not isinstance(current, dict):
            continue
        if str(current.get("oid") or "") != str(expected.get("oid") or ""):
            # A locally redirected metric is a deliberate customization.
            continue
        # Correct the built-in table index encoding while retaining operator
        # edits to other metric metadata such as help and units.
        if current.get("indexes") != expected.get("indexes"):
            current["indexes"] = expected.get("indexes", [])
            changed = True
    if repaired != metrics:
        config["metrics"] = repaired
        changed = True

    schema_version = str(builtin.get("schema_version") or "1")
    if str(config.get("schema_version") or "") != schema_version:
        config["schema_version"] = schema_version
        changed = True
    return changed


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    from services.monitoring_oid_catalog import iter_builtin_catalog

    item = next(
        (value for value in iter_builtin_catalog() if str(value.get("module_key") or "") == "huawei_wireless"),
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
    cursor.execute(
        """
        UPDATE snmp_module_variants
           SET oid_config_json = ?, generator_config_hash = ?, mib_hash = ?, updated_at = ?
         WHERE id = ?
        """,
        (
            serialized,
            hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            hashlib.sha256(_json(config.get("mib_sources") or []).encode("utf-8")).hexdigest(),
            _now(),
            variant_id,
        ),
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Removing supported wireless table coverage from an editable built-in
    # variant would also remove operator changes, so the migration is additive.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
