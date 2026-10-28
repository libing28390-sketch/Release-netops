"""Repair SNMPv3 credential columns missing from some recorded m0232 upgrades.

Some development databases recorded migration 232 before its credential-field
extension was present.  Their migration history therefore reports the current
version while the ``credentials`` table still has only the legacy SNMP fields.
This additive repair is safe for both those databases and installations where
the columns already exist.
"""

from __future__ import annotations


VERSION = 240
NAME = "repair_credential_snmpv3_columns"


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    existing_columns = {
        row[0]
        for row in cursor.execute("SELECT * FROM credentials LIMIT 0").description
    }
    missing_columns = (
        ("snmp_security_level", "TEXT NOT NULL DEFAULT 'authPriv'"),
        ("snmp_auth_protocol", "TEXT NOT NULL DEFAULT 'SHA'"),
        ("snmp_auth_password", "TEXT NOT NULL DEFAULT ''"),
        ("snmp_priv_protocol", "TEXT NOT NULL DEFAULT 'AES'"),
        ("snmp_priv_password", "TEXT NOT NULL DEFAULT ''"),
        ("snmp_context_name", "TEXT NOT NULL DEFAULT ''"),
    )
    for column, definition in missing_columns:
        if column not in existing_columns:
            cursor.execute(f"ALTER TABLE credentials ADD COLUMN {column} {definition}")


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # The repair is intentionally non-destructive.  Removing credential
    # columns would destroy data written by newer application versions.
    return None
