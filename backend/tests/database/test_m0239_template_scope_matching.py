from __future__ import annotations

import json

import database
from database.migrations import m0239_template_scope_matching as migration


def test_m0239_adds_scope_columns_and_refreshes_builtin_platforms(isolated_db):
    connection = database.get_db_connection()
    try:
        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()

        profile_columns = {item[0] for item in connection.execute("SELECT * FROM snmp_metric_profiles LIMIT 0").description}
        assert {
            "platform_key", "platform_scope_json", "model_pattern",
            "software_version_scope_json", "min_version", "max_version",
            "excluded_versions_json", "scope_priority",
        } <= profile_columns
        variant_columns = {item[0] for item in connection.execute("SELECT * FROM snmp_module_variants LIMIT 0").description}
        assert "supported_platforms" in variant_columns
        row = connection.execute(
            "SELECT supported_platforms FROM snmp_module_variants WHERE variant_key = ?",
            ("h3c_common_std",),
        ).fetchone()
        assert json.loads(row[0]) == ["h3c_comware_v5", "h3c_comware_v7", "h3c_comware_v9"]
    finally:
        connection.close()

