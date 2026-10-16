"""Add first-class platform/model/software-version scope metadata.

The original SNMP metric profile table was keyed only by vendor and model and
the Monitoring V1 variant table kept model/version fields as descriptive JSON.
This migration keeps existing rows valid while adding the scope dimensions
used by the resolver and compiler.  All columns are additive and nullable in
practice through safe defaults so older fixtures can continue to run.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from services.monitoring_oid_catalog import iter_builtin_catalog


VERSION = 239
NAME = "template_scope_matching"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _columns(cursor, table: str) -> set[str]:
    return {str(item[0]) for item in cursor.execute(f"SELECT * FROM {table} LIMIT 0").description}


def _add_columns(cursor, table: str, definitions: dict[str, str]) -> None:
    existing = _columns(cursor, table)
    for column, definition in definitions.items():
        if column not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _refresh_builtin_variant_platforms(cursor, now: str) -> None:
    """Backfill platform scope for built-ins without touching custom rows."""

    columns = _columns(cursor, "snmp_module_variants")
    if "supported_platforms" not in columns:
        return
    for item in iter_builtin_catalog():
        variant = item.get("variant") or {}
        platforms = list(variant.get("supported_platforms") or [])
        cursor.execute(
            """
            UPDATE snmp_module_variants
               SET supported_platforms = ?, updated_at = ?
             WHERE id = ?
               AND EXISTS (SELECT 1 FROM snmp_modules m WHERE m.id = snmp_module_variants.module_id AND m.built_in = 1)
            """,
            (_json(platforms), now, str(variant.get("id") or "")),
        )


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    _add_columns(
        cursor,
        "snmp_metric_profiles",
        {
            "platform_key": "TEXT NOT NULL DEFAULT ''",
            "platform_scope_json": "TEXT NOT NULL DEFAULT '[]'",
            "model_pattern": "TEXT NOT NULL DEFAULT ''",
            "software_version_scope_json": "TEXT NOT NULL DEFAULT '[]'",
            "min_version": "TEXT NOT NULL DEFAULT ''",
            "max_version": "TEXT NOT NULL DEFAULT ''",
            "excluded_versions_json": "TEXT NOT NULL DEFAULT '[]'",
            "scope_priority": "INTEGER NOT NULL DEFAULT 0",
        },
    )
    _add_columns(
        cursor,
        "snmp_module_variants",
        {
            "supported_platforms": "TEXT NOT NULL DEFAULT '[]'",
        },
    )

    cursor.execute(
        """
        UPDATE snmp_metric_profiles
           SET model_pattern = model_name
         WHERE COALESCE(TRIM(model_pattern), '') = ''
           AND COALESCE(TRIM(model_name), '') <> ''
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_snmp_metric_profiles_scope "
        "ON snmp_metric_profiles(vendor_key, platform_key, model_key, scope_priority)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_snmp_module_variants_scope "
        "ON snmp_module_variants(module_id, status, enabled)"
    )
    _refresh_builtin_variant_platforms(cursor, _now())


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Scope columns are intentionally retained.  Removing them would make an
    # older binary silently select the wrong OID template after a downgrade.
    return None

