from __future__ import annotations

import database
from database.migrations import m0232_monitoring_v1_control_plane as migration
from services.credential_service import create_credential


def test_m0232_monitoring_v1_schema_and_seed_are_idempotent(isolated_db):
    connection = database.get_db_connection()
    try:
        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name LIKE 'monitoring_%'"
            ).fetchall()
        }
        assert {
            "monitoring_collectors",
            "monitoring_collection_plans",
            "monitoring_collection_assignments",
            "monitoring_config_versions",
            "monitoring_target_snapshots",
            "monitoring_metric_definitions",
            "monitoring_shadow_comparisons",
        } <= tables
        assert connection.execute("SELECT code FROM monitoring_collectors WHERE id = 'collector-local'").fetchone()[0] == "collector-local"
        assert connection.execute("SELECT variant_key FROM snmp_module_variants WHERE id = 'variant-generic-if-mib-std'").fetchone()[0] == "generic_ifmib_interface_std"
        plan = connection.execute("SELECT config_json FROM monitoring_collection_plans WHERE id = 'plan-generic-ifmib'").fetchone()[0]
        assert "generic_ifmib_interface_std" in str(plan)
        credential_columns = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'credentials'"
            ).fetchall()
        }
        assert {"snmp_security_level", "snmp_auth_password", "snmp_priv_password"} <= credential_columns
        credential = create_credential(
            connection,
            credential_name="p0-v3",
            credential_type="snmpv3",
            username="monitor",
            snmp_security_level="authPriv",
            snmp_auth_password="auth-secret",
            snmp_priv_password="priv-secret",
        )
        assert credential["credential_type"] == "snmpv3"
        assert credential["has_snmp_auth_password"] is True
        assert credential["has_snmp_priv_password"] is True
        raw = connection.execute("SELECT snmp_auth_password, snmp_priv_password FROM credentials WHERE id = ?", (credential["id"],)).fetchone()
        assert raw[0] != "auth-secret" and raw[1] != "priv-secret"
    finally:
        connection.close()
