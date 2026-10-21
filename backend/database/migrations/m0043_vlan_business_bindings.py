"""Add the manual business-ownership layer for VLANs.

Network facts remain in ``vlans``, ``interfaces`` and the ARP/MAC tables.
This table stores only the human-confirmed business meaning of a VLAN scope.
"""

from __future__ import annotations


VERSION = 43
NAME = "vlan_business_bindings"


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS vlan_business_bindings (
            id TEXT PRIMARY KEY,
            site_id TEXT NOT NULL DEFAULT '',
            vrf_id TEXT NOT NULL DEFAULT '',
            vlan_id INTEGER NOT NULL,
            business_system TEXT NOT NULL,
            department TEXT NOT NULL DEFAULT '',
            owner TEXT NOT NULL DEFAULT '',
            business_level TEXT NOT NULL DEFAULT 'P3',
            status TEXT NOT NULL DEFAULT 'active',
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_vlan_business_scope
        ON vlan_business_bindings(site_id, vrf_id, vlan_id, business_system)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_vlan_business_lookup
        ON vlan_business_bindings(site_id, vrf_id, vlan_id, status)
        """
    )
