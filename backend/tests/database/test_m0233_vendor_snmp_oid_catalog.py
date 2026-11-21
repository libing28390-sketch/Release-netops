from __future__ import annotations

import json

import database
from database.migrations import m0233_vendor_snmp_oid_catalog as migration


def test_m0233_seeds_vendor_oid_catalog_and_merges_baseline_plan(isolated_db):
    connection = database.get_db_connection()
    try:
        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()

        columns = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'snmp_module_variants'"
            ).fetchall()
        }
        assert "oid_config_json" in columns
        modules = {
            row[0]
            for row in connection.execute(
                "SELECT module_key FROM snmp_modules WHERE module_key IN (?, ?, ?)",
                ("h3c_common", "huawei_common", "cisco_common"),
            ).fetchall()
        }
        assert modules == {"h3c_common", "huawei_common", "cisco_common"}
        rows = connection.execute(
            "SELECT variant_key, oid_config_json, generator_config_hash, mib_hash FROM snmp_module_variants "
            "WHERE variant_key IN (?, ?, ?)",
            ("h3c_common_std", "huawei_common_std", "cisco_common_std"),
        ).fetchall()
        assert len(rows) == 3
        for row in rows:
            config = json.loads(row[1])
            assert config["walk"] and config["metrics"]
            assert row[2] and row[3]
        plan = json.loads(
            connection.execute(
                "SELECT config_json FROM monitoring_collection_plans WHERE id = ?",
                ("plan-generic-ifmib",),
            ).fetchone()[0]
        )
        plan_variants = {item.get("variant") for item in plan["modules"]}
        assert {"generic_ifmib_interface_std", "generic_system_std", "h3c_common_std", "huawei_common_std", "cisco_common_std"} <= plan_variants
    finally:
        connection.close()
