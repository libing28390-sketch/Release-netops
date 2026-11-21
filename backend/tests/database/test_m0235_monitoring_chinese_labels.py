from __future__ import annotations

import database
from database.migrations import m0235_monitoring_chinese_labels as migration


def test_m0235_normalizes_builtin_monitoring_labels(isolated_db):
    connection = database.get_db_connection()
    try:
        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        plan = connection.execute(
            "SELECT name FROM monitoring_collection_plans WHERE id = ?",
            ("plan-generic-ifmib",),
        ).fetchone()
        assert plan[0] == "SNMP 基线采集计划"
        modules = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT module_key, display_name FROM snmp_modules WHERE built_in = 1"
            ).fetchall()
        }
        assert modules["generic_ifmib_interface"] == "通用接口（IF-MIB）"
        assert modules["h3c_common"] == "华三通用设备"
    finally:
        connection.close()

