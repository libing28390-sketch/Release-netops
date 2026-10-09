from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_m0280_disables_legacy_wireless_exporter_rules_and_keeps_records(isolated_db) -> None:
    database = isolated_db["module"]
    migration = importlib.import_module(
        "database.migrations.m0280_retire_legacy_wireless_oid_variants"
    )
    connection = database.get_db_connection()
    now = datetime.now(timezone.utc).isoformat()
    variant_key = "huawei_wireless_std"
    try:
        variant = connection.execute(
            """
            SELECT v.id, v.module_id
              FROM snmp_module_variants v
             WHERE v.variant_key = ?
            """,
            (variant_key,),
        ).fetchone()
        assert variant is not None
        variant_id, module_id = variant[0], variant[1]

        plan = connection.execute(
            "SELECT config_json FROM monitoring_collection_plans WHERE id = ?",
            ("plan-generic-ifmib",),
        ).fetchone()
        assert plan is not None
        config = json.loads(plan[0])
        modules = config.get("modules") or []
        modules.append({"module": "huawei_wireless", "variant": variant_key, "enabled": True})
        modules.append({"module": "generic_ifmib_interface", "variant": "generic_ifmib_interface_std", "enabled": True})
        config["modules"] = modules
        connection.execute(
            "UPDATE monitoring_collection_plans SET config_json = ? WHERE id = ?",
            (_json(config), "plan-generic-ifmib"),
        )
        connection.execute(
            "UPDATE snmp_modules SET enabled = 1 WHERE id = ?",
            (module_id,),
        )
        connection.execute(
            "UPDATE snmp_module_variants SET enabled = 1, status = 'PUBLISHED' WHERE id = ?",
            (variant_id,),
        )
        connection.execute(
            """
            INSERT INTO monitoring_collection_assignments (
                id, asset_id, collector_id, module_variant_id, credential_id,
                auth_alias, interval_seconds, scrape_timeout_seconds, enabled,
                source_type, source_plan_id, assignment_hash, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-wireless-assignment", "asset-test", "collector-local", variant_id,
                "", "", 120, 20, 1, "PLAN", "plan-generic-ifmib", "hash-test", now, now,
            ),
        )
        connection.commit()

        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()

        stored_module = connection.execute(
            "SELECT enabled FROM snmp_modules WHERE id = ?", (module_id,),
        ).fetchone()
        stored_variant = connection.execute(
            "SELECT enabled, status, oid_config_json FROM snmp_module_variants WHERE id = ?",
            (variant_id,),
        ).fetchone()
        assignment = connection.execute(
            "SELECT enabled FROM monitoring_collection_assignments WHERE id = ?",
            ("legacy-wireless-assignment",),
        ).fetchone()
        assert stored_module[0] in (0, False)
        assert stored_variant[0] in (0, False)
        assert stored_variant[1] == "DRAFT"
        assert json.loads(stored_variant[2])["metrics"]
        assert assignment[0] in (0, False)

        upgraded_plan = connection.execute(
            "SELECT config_json FROM monitoring_collection_plans WHERE id = ?",
            ("plan-generic-ifmib",),
        ).fetchone()
        upgraded_entries = json.loads(upgraded_plan[0])["modules"]
        disabled_wireless = next(item for item in upgraded_entries if item.get("variant") == variant_key)
        generic = next(item for item in upgraded_entries if item.get("variant") == "generic_ifmib_interface_std")
        assert disabled_wireless["enabled"] is False
        assert "LibreNMS" in disabled_wireless["disabled_reason"]
        assert generic["enabled"] is True

        snapshot = upgraded_plan[0]
        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        repeated = connection.execute(
            "SELECT config_json FROM monitoring_collection_plans WHERE id = ?",
            ("plan-generic-ifmib",),
        ).fetchone()
        assert repeated[0] == snapshot
    finally:
        connection.rollback()
        connection.close()
