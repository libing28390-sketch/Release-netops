"""Normalize built-in Monitoring V1 labels to Chinese for the operator UI."""

from __future__ import annotations

from datetime import datetime, timezone

from services.monitoring_oid_catalog import iter_builtin_catalog


VERSION = 235
NAME = "monitoring_chinese_labels"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    now = _now()
    for item in iter_builtin_catalog():
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


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    return None
