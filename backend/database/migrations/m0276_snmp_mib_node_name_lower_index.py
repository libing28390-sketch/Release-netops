"""Index normalized SNMP MIB node names for case-insensitive lookup."""

from __future__ import annotations


VERSION = 276
NAME = "snmp_mib_node_name_lower_index"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("snmp_mib_node_name_lower_index requires PostgreSQL")
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_snmp_mib_nodes_name_lower
            ON snmp_mib_nodes (LOWER(node_name))
        """
    )


def downgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("snmp_mib_node_name_lower_index requires PostgreSQL")
    cursor.execute("DROP INDEX IF EXISTS idx_snmp_mib_nodes_name_lower")
