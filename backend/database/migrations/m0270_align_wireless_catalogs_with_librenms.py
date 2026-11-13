"""Align Huawei wireless OIDs and disable unverified Ruijie wireless defaults."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


VERSION = 270
NAME = "align_wireless_catalogs_with_librenms"

_HUAWEI_OLD_GET_OIDS = {
    "1.3.6.1.4.1.2011.6.139.13.1.2.1.0",
    "1.3.6.1.4.1.2011.6.139.13.1.2.2.0",
    "1.3.6.1.4.1.2011.6.139.13.1.2.3.0",
}
_HUAWEI_OLD_METRICS = {
    "hwWlanCurOnlineApNum": "1.3.6.1.4.1.2011.6.139.13.1.2.1",
    "hwWlanCurAssocUserNum": "1.3.6.1.4.1.2011.6.139.13.1.2.2",
    "hwWlanApTotalNum": "1.3.6.1.4.1.2011.6.139.13.1.2.3",
}
_HUAWEI_AP_COUNT = {
    "name": "hwWlanCurJointApNum",
    "oid": "1.3.6.1.4.1.2011.6.139.12.1.2.1.0",
    "type": "gauge",
    "help": "Current joined AP count discovered by LibreNMS VRP WirelessApCountDiscovery.",
    "source_name": "hwWlanCurJointApNum",
}
_HUAWEI_CLIENT_WALKS = {
    "1.3.6.1.4.1.2011.6.139.17.1.2.1.2",
    "1.3.6.1.4.1.2011.6.139.17.1.2.1.3",
}
_RUIJIE_OLD_METRICS = {
    "ruijieApcTotalApNum": "1.3.6.1.4.1.4881.1.1.10.2.75.1.1.1",
    "ruijieApcOnlineApNum": "1.3.6.1.4.1.4881.1.1.10.2.75.1.1.2",
    "ruijieApcTotalStaNum": "1.3.6.1.4.1.4881.1.1.10.2.75.1.1.3",
}
_RUIJIE_OLD_GET_OIDS = {f"{oid}.0" for oid in _RUIJIE_OLD_METRICS.values()}
_WIRELESS_VERSION_SCOPES = {
    "huawei_wireless_std": ["VRP WLAN"],
    "h3c_wireless_std": ["Comware Dot11"],
    "ruijie_wireless_std": ["RGOS WLAN"],
    "cisco_wireless_std": ["IOS-XE Wireless", "AireOS"],
    "aruba_wireless_std": ["ArubaOS"],
    "ruckus_wireless_std": ["SmartZone"],
}


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


def _repair_huawei(config: dict[str, Any], builtin: dict[str, Any]) -> bool:
    changed = False
    get_values = config.get("get") if isinstance(config.get("get"), list) else []
    filtered_get = [value for value in get_values if str(value) not in _HUAWEI_OLD_GET_OIDS]
    if filtered_get != get_values:
        config["get"] = filtered_get
        changed = True
    for oid in builtin.get("get") or []:
        if oid not in config.get("get", []):
            config.setdefault("get", []).append(oid)
            changed = True

    walk_values = config.get("walk") if isinstance(config.get("walk"), list) else []
    for oid in builtin.get("walk") or []:
        if oid not in walk_values:
            walk_values.append(oid)
            changed = True
    if walk_values:
        config["walk"] = walk_values

    metrics = config.get("metrics") if isinstance(config.get("metrics"), list) else []
    repaired: list[Any] = []
    for value in metrics:
        if not isinstance(value, dict):
            repaired.append(value)
            continue
        name = str(value.get("name") or value.get("source_name") or "")
        oid = str(value.get("oid") or "")
        if _HUAWEI_OLD_METRICS.get(name) == oid:
            changed = True
            continue
        repaired.append(dict(value))
    if not any(isinstance(value, dict) and value.get("name") == _HUAWEI_AP_COUNT["name"] for value in repaired):
        repaired.append(dict(_HUAWEI_AP_COUNT))
        changed = True
    if repaired != metrics:
        config["metrics"] = repaired
        changed = True

    for key, values in (
        ("mib_sources", builtin.get("mib_sources") or []),
        ("source_urls", builtin.get("source_urls") or []),
    ):
        existing = config.get(key) if isinstance(config.get(key), list) else []
        for value in values:
            if value not in existing:
                existing.append(value)
                changed = True
        if existing:
            config[key] = existing
    return changed


def _is_unmodified_ruijie_default(config: dict[str, Any]) -> bool:
    metrics = config.get("metrics") if isinstance(config.get("metrics"), list) else []
    observed = {
        str(value.get("name") or value.get("source_name") or ""): str(value.get("oid") or "")
        for value in metrics if isinstance(value, dict)
    }
    get_oids = {str(value) for value in config.get("get", [])} if isinstance(config.get("get"), list) else set()
    return observed == _RUIJIE_OLD_METRICS and get_oids == _RUIJIE_OLD_GET_OIDS


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    from services.monitoring_oid_catalog import iter_builtin_catalog

    now = _now()
    builtin_by_key = {
        str(item.get("module_key") or ""): item
        for item in iter_builtin_catalog()
        if str(item.get("module_key") or "") in {"huawei_wireless", "ruijie_wireless"}
    }
    rows = cursor.execute(
        """
        SELECT v.id, v.variant_key, v.oid_config_json, v.supported_version_scope,
               v.status, v.enabled, m.module_key
          FROM snmp_module_variants v
          JOIN snmp_modules m ON m.id = v.module_id
         WHERE m.built_in = 1 AND v.variant_key IN (
             'huawei_wireless_std', 'h3c_wireless_std', 'ruijie_wireless_std',
             'cisco_wireless_std', 'aruba_wireless_std', 'ruckus_wireless_std'
         )
        """
    ).fetchall()
    for row in rows:
        variant_id = str(_row_value(row, "id"))
        variant_key = str(_row_value(row, "variant_key"))
        module_key = str(_row_value(row, "module_key"))
        config = _load_config(_row_value(row, "oid_config_json"))
        changed = False
        if module_key == "huawei_wireless":
            builtin = (builtin_by_key.get(module_key) or {}).get("variant", {}).get("oid_config") or {}
            changed = _repair_huawei(config, builtin)
        elif module_key == "ruijie_wireless" and _is_unmodified_ruijie_default(config):
            config = {"schema_version": "1", "mib_sources": [], "source_urls": [], "get": [], "metrics": []}
            changed = True

        current_scope = _row_value(row, "supported_version_scope")
        if isinstance(current_scope, str):
            try:
                scope_value = json.loads(current_scope or "[]")
            except (TypeError, ValueError):
                scope_value = []
        else:
            scope_value = current_scope or []
        if scope_value == _WIRELESS_VERSION_SCOPES.get(variant_key):
            cursor.execute(
                "UPDATE snmp_module_variants SET supported_version_scope = ?, updated_at = ? WHERE id = ?",
                ("[]", now, variant_id),
            )
            changed = True

        disable_unverified_ruijie = module_key == "ruijie_wireless" and changed and not config.get("metrics")
        if not changed and not disable_unverified_ruijie:
            continue
        serialized = _json(config)
        generator_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        mib_hash = hashlib.sha256(_json(config.get("mib_sources") or []).encode("utf-8")).hexdigest()
        if disable_unverified_ruijie:
            cursor.execute(
                """
                UPDATE snmp_module_variants
                   SET oid_config_json = ?, generator_config_hash = ?, mib_hash = ?,
                       status = 'DRAFT', enabled = 0, supported_version_scope = '[]', updated_at = ?
                 WHERE id = ?
                """,
                (serialized, generator_hash, mib_hash, now, variant_id),
            )
        else:
            cursor.execute(
                """
                UPDATE snmp_module_variants
                   SET oid_config_json = ?, generator_config_hash = ?, mib_hash = ?, updated_at = ?
                 WHERE id = ?
                """,
                (serialized, generator_hash, mib_hash, now, variant_id),
            )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Re-enabling unverified defaults or restoring non-upstream Huawei OIDs is unsafe.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
