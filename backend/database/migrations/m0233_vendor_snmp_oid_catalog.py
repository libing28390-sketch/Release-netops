"""Add the vendor OID catalog and make it part of the single baseline plan.

The migration is additive and idempotent.  Existing custom modules/variants
are never overwritten; only empty OID configurations on the two built-in
generic variants are backfilled.  H3C, Huawei and Cisco entries are seeded as
additional modules in the existing ``plan-generic-ifmib`` plan and selected by
vendor at compile time, so the database does not grow one plan per vendor.
"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone

from services.monitoring_oid_catalog import iter_builtin_catalog


VERSION = 233
NAME = "vendor_snmp_oid_catalog"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _columns(cursor, table: str) -> set[str]:
    return {str(item[0]) for item in cursor.execute(f"SELECT * FROM {table} LIMIT 0").description}


def _seed_metric_definitions(cursor, catalog: list[dict], now: str) -> None:
    """Expose catalog metric names to the provider/query catalogue.

    The exporter still owns the raw OID mapping.  These rows make the
    supported metric vocabulary discoverable to the dashboard/query layer and
    intentionally contain no credentials or device-specific values.
    """

    seen: set[str] = set()
    for item in catalog:
        variant = item.get("variant") or {}
        config = variant.get("oid_config") or {}
        for metric in config.get("metrics") or []:
            if not isinstance(metric, dict):
                continue
            metric_key = str(metric.get("name") or "").strip()
            if not metric_key or metric_key in seen:
                continue
            seen.add(metric_key)
            metric_type = str(metric.get("type") or "gauge").lower()
            semantic = str(metric.get("help") or metric_key)
            unit = "percent" if any(token in metric_key.lower() for token in ("usage", "status", "speed")) else ""
            cursor.execute(
                """
                INSERT INTO monitoring_metric_definitions
                  (id, metric_key, semantic, unit, query, metric_type, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT (id) DO NOTHING
                """,
                (f"metric-{metric_key}", metric_key, semantic, unit, metric_key, metric_type, now, now),
            )


def _merge_baseline_plan(cursor, catalog: list[dict]) -> None:
    row = cursor.execute(
        "SELECT config_json FROM monitoring_collection_plans WHERE id = ?",
        ("plan-generic-ifmib",),
    ).fetchone()
    if not row:
        return
    raw = row[0] if not hasattr(row, "get") else row.get("config_json")
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
    defaults = {
        "generic_ifmib_interface_std": {
            "module": "generic_ifmib_interface",
            "variant": "generic_ifmib_interface_std",
            "interval": "60s",
            "scrape_timeout": "20s",
            "enabled": True,
        },
        "generic_system_std": {
            "module": "generic_system",
            "variant": "generic_system_std",
            "interval": "900s",
            "scrape_timeout": "30s",
            "enabled": True,
        },
        "h3c_common_std": {
            "module": "h3c_common",
            "variant": "h3c_common_std",
            "vendor": ["h3c", "hpe", "hp", "comware"],
            "interval": "60s",
            "scrape_timeout": "20s",
            "enabled": True,
        },
        "huawei_common_std": {
            "module": "huawei_common",
            "variant": "huawei_common_std",
            "vendor": ["huawei", "vrp"],
            "interval": "60s",
            "scrape_timeout": "20s",
            "enabled": True,
        },
        "cisco_common_std": {
            "module": "cisco_common",
            "variant": "cisco_common_std",
            "vendor": ["cisco", "ios", "iosxe", "nxos", "asa"],
            "interval": "60s",
            "scrape_timeout": "20s",
            "enabled": True,
        },
    }
    changed = False
    for variant_key, entry in defaults.items():
        if variant_key not in existing:
            entries.append(entry)
            changed = True
    if changed:
        config["modules"] = entries
        cursor.execute(
            "UPDATE monitoring_collection_plans SET config_json = ?, updated_at = ? WHERE id = ?",
            (_json(config), _now(), "plan-generic-ifmib"),
        )


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    columns = _columns(cursor, "snmp_module_variants")
    if "oid_config_json" not in columns:
        cursor.execute("ALTER TABLE snmp_module_variants ADD COLUMN oid_config_json TEXT NOT NULL DEFAULT '{}'")
    now = _now()
    catalog = iter_builtin_catalog()

    for item in catalog:
        cursor.execute(
            """
            INSERT INTO snmp_modules
              (id, module_key, display_name, vendor, cli_platform, feature_domain,
               description, metric_group, walk_fingerprint, enabled, built_in, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (
                item["id"], item["module_key"], item["display_name"], item.get("vendor", ""),
                item.get("cli_platform", ""), item.get("feature_domain", ""), item.get("description", ""),
                item.get("metric_group", ""), item.get("walk_fingerprint", ""), now, now,
            ),
        )
        variant = item["variant"]
        oid_config = _json(variant.get("oid_config") or {})
        generator_hash = hashlib.sha256(oid_config.encode("utf-8")).hexdigest()
        mib_hash = hashlib.sha256(_json((variant.get("oid_config") or {}).get("mib_sources") or []).encode("utf-8")).hexdigest()
        cursor.execute(
            """
            INSERT INTO snmp_module_variants
              (id, module_id, variant_key, display_name, max_repetitions, retries,
               request_timeout_ms, scrape_timeout_ms, supported_models, supported_version_scope,
               verified_models, verified_versions, mib_bundle_id, generator_version,
               status, enabled, oid_config_json, generator_config_hash, mib_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (
                variant["id"], item["id"], variant["variant_key"], variant["display_name"],
                int(variant.get("max_repetitions", 25)), int(variant.get("retries", 2)),
                int(variant.get("request_timeout_ms", 3000)), int(variant.get("scrape_timeout_ms", 20000)),
                _json(variant.get("supported_models") or []), _json(variant.get("supported_version_scope") or []),
                _json(variant.get("verified_models") or []), _json(variant.get("verified_versions") or []),
                str(variant.get("mib_bundle_id") or ""), str(variant.get("generator_version") or ""),
                str(variant.get("status") or "DRAFT").upper(), int(bool(variant.get("enabled", True))),
                oid_config, generator_hash, mib_hash, now, now,
            ),
        )
        # m0232 created the generic variants before the OID catalog existed.
        # Backfill only empty values so a later operator edit remains intact.
        cursor.execute(
            """
            UPDATE snmp_module_variants
               SET oid_config_json = ?, updated_at = ?
             WHERE id = ? AND (oid_config_json IS NULL OR oid_config_json IN ('', '{}', '[]'))
            """,
            (oid_config, now, variant["id"]),
        )
        cursor.execute(
            """
            UPDATE snmp_module_variants
               SET generator_config_hash = ?, mib_hash = ?
             WHERE id = ? AND (generator_config_hash IS NULL OR generator_config_hash = '')
            """,
            (generator_hash, mib_hash, variant["id"]),
        )

    _merge_baseline_plan(cursor, catalog)
    _seed_metric_definitions(cursor, catalog, now)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    columns = _columns(cursor, "snmp_module_variants")
    if "oid_config_json" in columns:
        cursor.execute("ALTER TABLE snmp_module_variants DROP COLUMN oid_config_json")
