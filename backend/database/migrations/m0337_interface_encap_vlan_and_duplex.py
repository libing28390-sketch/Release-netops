"""Add subinterface real 802.1Q encap_vlan_id and duplex columns to interface tables.

Allows subinterfaces such as ``GigabitEthernet0/0/1.999`` terminating
``dot1q termination vid 100`` to store their authoritative ``encap_vlan_id``
(100) rather than mis-inferring VLAN 999 from the subinterface suffix.
"""

from __future__ import annotations

VERSION = 337
NAME = "interface_encap_vlan_and_duplex"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        return
    cursor.execute("ALTER TABLE interfaces ADD COLUMN IF NOT EXISTS encap_vlan_id INTEGER")
    cursor.execute("ALTER TABLE interfaces ADD COLUMN IF NOT EXISTS duplex TEXT DEFAULT ''")
    cursor.execute(
        "ALTER TABLE cmdb_device_interface_observations ADD COLUMN IF NOT EXISTS encap_vlan_id INTEGER"
    )
    cursor.execute(
        "ALTER TABLE cmdb_device_interface_observations ADD COLUMN IF NOT EXISTS duplex TEXT DEFAULT ''"
    )


def downgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        return
    cursor.execute("ALTER TABLE cmdb_device_interface_observations DROP COLUMN IF EXISTS duplex")
    cursor.execute("ALTER TABLE cmdb_device_interface_observations DROP COLUMN IF EXISTS encap_vlan_id")
    cursor.execute("ALTER TABLE interfaces DROP COLUMN IF EXISTS duplex")
    cursor.execute("ALTER TABLE interfaces DROP COLUMN IF EXISTS encap_vlan_id")
