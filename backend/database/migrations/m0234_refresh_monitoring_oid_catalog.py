"""Refresh the built-in OID catalog after the initial monitoring migration.

This small follow-up also repairs older development databases whose baseline
plan was seeded with only the interface module.  Built-in Variant rows are
system-owned, so their catalog payload is refreshed from the versioned source;
custom Variants remain untouched.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from services.monitoring_oid_catalog import iter_builtin_catalog
from database.migrations.m0233_vendor_snmp_oid_catalog import _merge_baseline_plan, _seed_metric_definitions


VERSION = 234
NAME = "refresh_monitoring_oid_catalog"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _columns(cursor, table: str) -> set[str]:
    return {str(item[0]) for item in cursor.execute(f"SELECT * FROM {table} LIMIT 0").description}


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    if "oid_config_json" not in _columns(cursor, "snmp_module_variants"):
        cursor.execute("ALTER TABLE snmp_module_variants ADD COLUMN oid_config_json TEXT NOT NULL DEFAULT '{}'")
    now = _now()
    catalog = iter_builtin_catalog()
    for item in catalog:
        cursor.execute(
            """
            UPDATE snmp_modules
               SET display_name = ?, vendor = ?, cli_platform = ?, feature_domain = ?,
                   description = ?, metric_group = ?, walk_fingerprint = ?, updated_at = ?
             WHERE id = ? AND built_in = 1
            """,
            (
                item["display_name"], item.get("vendor", ""), item.get("cli_platform", ""),
                item.get("feature_domain", ""), item.get("description", ""), item.get("metric_group", ""),
                item.get("walk_fingerprint", ""), now, item["id"],
            ),
        )
        variant = item["variant"]
        oid_config = _json(variant.get("oid_config") or {})
        generator_hash = hashlib.sha256(oid_config.encode("utf-8")).hexdigest()
        mib_hash = hashlib.sha256(_json((variant.get("oid_config") or {}).get("mib_sources") or []).encode("utf-8")).hexdigest()
        cursor.execute(
            """
            UPDATE snmp_module_variants
               SET oid_config_json = ?, generator_config_hash = ?, mib_hash = ?,
                   mib_bundle_id = ?, generator_version = ?, updated_at = ?
             WHERE id = ?
            """,
            (
                oid_config,
                generator_hash,
                mib_hash,
                str(variant.get("mib_bundle_id") or ""),
                str(variant.get("generator_version") or ""),
                now,
                variant["id"],
            ),
        )
        cursor.execute(
            "UPDATE snmp_module_variants SET display_name = ?, updated_at = ? WHERE id = ?",
            (variant["display_name"], now, variant["id"]),
        )
    cursor.execute(
        "UPDATE monitoring_collection_plans SET name = ?, description = ?, updated_at = ? WHERE id = ?",
        ("SNMP 基线采集计划", "IF-MIB、系统和厂商常用硬件指标的统一 SNMP 基线。", now, "plan-generic-ifmib"),
    )
    cursor.execute(
        "UPDATE monitoring_collectors SET name = ?, updated_at = ? WHERE id = ?",
        ("本地采集器", now, "collector-local"),
    )
    _merge_baseline_plan(cursor, catalog)
    _seed_metric_definitions(cursor, catalog, now)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # The initial m0233 migration owns the column; leave it in place so a
    # rollback of this refresh does not remove a schema element still in use.
    return None
