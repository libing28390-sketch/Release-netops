"""Add an optional SNMP target address to credential-center records."""

from __future__ import annotations


VERSION = 39
NAME = "add_snmp_server_to_credentials"


def upgrade(cursor, use_pg: bool) -> None:
    columns = {row[0] for row in cursor.execute("SELECT * FROM credentials LIMIT 0").description}
    if "snmp_server" not in columns:
        cursor.execute("ALTER TABLE credentials ADD COLUMN snmp_server TEXT DEFAULT ''")
