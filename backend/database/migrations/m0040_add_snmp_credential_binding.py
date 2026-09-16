"""Add an independent SNMP credential binding for assets and devices."""

from __future__ import annotations


VERSION = 40
NAME = "add_snmp_credential_binding"


def upgrade(cursor, use_pg: bool) -> None:
    columns = {row[0] for row in cursor.execute("SELECT * FROM devices LIMIT 0").description}
    if "snmp_credential_id" not in columns:
        cursor.execute("ALTER TABLE devices ADD COLUMN snmp_credential_id TEXT DEFAULT ''")

    columns = {row[0] for row in cursor.execute("SELECT * FROM physical_assets LIMIT 0").description}
    if "snmp_credential_id" not in columns:
        cursor.execute("ALTER TABLE physical_assets ADD COLUMN snmp_credential_id TEXT DEFAULT ''")
