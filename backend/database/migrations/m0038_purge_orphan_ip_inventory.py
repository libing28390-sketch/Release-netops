"""Remove legacy IP inventory rows whose device no longer exists."""

from __future__ import annotations


VERSION = 38
NAME = "purge_orphan_ip_inventory"


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        """DELETE FROM ip_inventory
           WHERE device_id IS NULL
              OR NOT EXISTS (SELECT 1 FROM devices d WHERE d.id = ip_inventory.device_id)"""
    )
