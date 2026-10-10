"""Expand the built-in H3C and IF-MIB monitoring catalog.

The migration refreshes only the system-owned catalog rows.  Custom modules
and variants are left untouched, while the single baseline plan keeps its
existing module-selection model.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from services.monitoring_oid_catalog import iter_builtin_catalog
from database.migrations.m0233_vendor_snmp_oid_catalog import _merge_baseline_plan, _seed_metric_definitions


VERSION = 236
NAME = "expand_h3c_monitoring_oids"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
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
        oid_config = variant.get("oid_config") or {}
        oid_json = _json(oid_config)
        generator_hash = hashlib.sha256(oid_json.encode("utf-8")).hexdigest()
        mib_hash = hashlib.sha256(_json(oid_config.get("mib_sources") or []).encode("utf-8")).hexdigest()
        cursor.execute(
            """
            UPDATE snmp_module_variants
               SET display_name = ?, max_repetitions = ?, retries = ?,
                   request_timeout_ms = ?, scrape_timeout_ms = ?,
                   supported_models = ?, supported_version_scope = ?,
                   mib_bundle_id = ?, generator_version = ?, oid_config_json = ?,
                   generator_config_hash = ?, mib_hash = ?, updated_at = ?
             WHERE id = ?
            """,
            (
                variant["display_name"], int(variant.get("max_repetitions", 25)), int(variant.get("retries", 2)),
                int(variant.get("request_timeout_ms", 3000)), int(variant.get("scrape_timeout_ms", 20000)),
                _json(variant.get("supported_models") or []), _json(variant.get("supported_version_scope") or []),
                str(variant.get("mib_bundle_id") or ""), str(variant.get("generator_version") or ""), oid_json,
                generator_hash, mib_hash, now, variant["id"],
            ),
        )
    _merge_baseline_plan(cursor, catalog)
    _seed_metric_definitions(cursor, catalog, now)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Catalog refreshes are append-only; keep the expanded definitions so a
    # rollback cannot leave generated artifacts referring to missing metrics.
    return None
