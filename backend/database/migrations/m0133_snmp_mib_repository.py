"""Add SNMP MIB repository and OID symbol nodes table."""

from __future__ import annotations


VERSION = 133
NAME = "snmp_mib_repository"


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS snmp_mibs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            vendor TEXT NOT NULL DEFAULT 'General',
            filename TEXT NOT NULL,
            file_size INTEGER NOT NULL DEFAULT 0,
            node_count INTEGER NOT NULL DEFAULT 0,
            source_type TEXT NOT NULL DEFAULT 'user_upload',
            description TEXT NOT NULL DEFAULT '',
            content_text TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_snmp_mibs_vendor ON snmp_mibs(vendor)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS snmp_mib_nodes (
            id TEXT PRIMARY KEY,
            mib_id TEXT NOT NULL,
            node_name TEXT NOT NULL,
            oid TEXT NOT NULL,
            parent_oid TEXT NOT NULL DEFAULT '',
            syntax_type TEXT NOT NULL DEFAULT '',
            access_type TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'current',
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (mib_id) REFERENCES snmp_mibs(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_snmp_mib_nodes_oid ON snmp_mib_nodes(oid)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_snmp_mib_nodes_name ON snmp_mib_nodes(node_name)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_snmp_mib_nodes_mib ON snmp_mib_nodes(mib_id)"
    )


def downgrade(cursor, use_pg: bool) -> None:
    return None
