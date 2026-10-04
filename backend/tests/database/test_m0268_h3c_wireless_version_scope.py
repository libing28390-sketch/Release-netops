from __future__ import annotations

import json

import database
from database.migrations import m0268_fix_h3c_wireless_version_scope as migration


def test_m0268_repairs_only_the_known_bad_h3c_wireless_scope_idempotently(isolated_db):
    connection = database.get_db_connection()
    try:
        connection.execute(
            "UPDATE snmp_module_variants SET supported_version_scope = ? WHERE variant_key = ?",
            ('["Comware Dot11"]', "h3c_wireless_std"),
        )
        connection.commit()

        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()

        wireless = connection.execute(
            "SELECT supported_version_scope FROM snmp_module_variants WHERE variant_key = ?",
            ("h3c_wireless_std",),
        ).fetchone()
        assert json.loads(wireless[0]) == []

        common = connection.execute(
            "SELECT supported_version_scope FROM snmp_module_variants WHERE variant_key = ?",
            ("h3c_common_std",),
        ).fetchone()
        assert json.loads(common[0]) == ["Comware 7", "Comware 9"]
    finally:
        connection.close()
