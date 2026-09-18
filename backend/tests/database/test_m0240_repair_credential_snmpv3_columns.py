from __future__ import annotations

import database
from database.migrations import m0240_repair_credential_snmpv3_columns as migration


_SNMPV3_COLUMNS = {
    "snmp_security_level",
    "snmp_auth_protocol",
    "snmp_auth_password",
    "snmp_priv_protocol",
    "snmp_priv_password",
    "snmp_context_name",
}


def _credential_columns(connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'credentials'"
        ).fetchall()
    }


def test_m0240_repairs_recorded_m0232_without_touching_existing_rows(isolated_db):
    connection = database.get_db_connection()
    try:
        for column in sorted(_SNMPV3_COLUMNS):
            connection.execute(f"ALTER TABLE credentials DROP COLUMN IF EXISTS {column}")
        connection.commit()

        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        assert _SNMPV3_COLUMNS <= _credential_columns(connection)

        migration.upgrade(connection.cursor(), use_pg=True)
        connection.commit()
        assert _SNMPV3_COLUMNS <= _credential_columns(connection)
    finally:
        connection.close()
