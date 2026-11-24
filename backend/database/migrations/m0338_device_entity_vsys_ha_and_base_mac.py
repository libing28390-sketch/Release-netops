"""Add logical virtual-system (vsys_id), HA cluster/role, and base_mac to devices.

Enables composite entity identity ``chassis_sn:vsys_id`` for multi-VSYS
firewalls / VDC switches, HA Active/Standby prioritization in gateway
selection, and fast chassis-MAC recognition during Proxy ARP / L2 tracing.
"""

from __future__ import annotations

VERSION = 338
NAME = "device_entity_vsys_ha_and_base_mac"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        return
    cursor.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS vsys_id TEXT NOT NULL DEFAULT 'default'")
    cursor.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS ha_cluster_id TEXT DEFAULT ''")
    cursor.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS ha_role TEXT NOT NULL DEFAULT 'STANDALONE'")
    cursor.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS base_mac TEXT DEFAULT ''")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_devices_ha_cluster ON devices(ha_cluster_id)")


def downgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        return
    cursor.execute("DROP INDEX IF EXISTS idx_devices_ha_cluster")
    cursor.execute("ALTER TABLE devices DROP COLUMN IF EXISTS base_mac")
    cursor.execute("ALTER TABLE devices DROP COLUMN IF EXISTS ha_role")
    cursor.execute("ALTER TABLE devices DROP COLUMN IF EXISTS ha_cluster_id")
    cursor.execute("ALTER TABLE devices DROP COLUMN IF EXISTS vsys_id")
