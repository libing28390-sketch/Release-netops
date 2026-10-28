"""Store CMDB CLI interface and VLAN-port observations outside shared facts."""

from __future__ import annotations


VERSION = 299
NAME = "cmdb_cli_fact_isolation"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("CMDB CLI observations require PostgreSQL")

    # Version 298 may already be tracked on installations that previously
    # applied an earlier, incomplete form of that migration. Its DDL is
    # idempotent, so reconcile those prerequisites before adding the FK below.
    from database.migrations.m0298_cmdb_cache_versions import upgrade as upgrade_cache_versions

    upgrade_cache_versions(cursor, use_pg)

    cursor.execute(
        """CREATE TABLE IF NOT EXISTS cmdb_device_interface_observations (
               device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
               normalized_interface_name TEXT NOT NULL CHECK (normalized_interface_name <> ''),
               interface_name TEXT NOT NULL,
               description TEXT NOT NULL DEFAULT '',
               admin_status TEXT NOT NULL DEFAULT 'unknown',
               oper_status TEXT NOT NULL DEFAULT 'unknown',
               ip_address TEXT NOT NULL DEFAULT '',
               ip_prefix_length SMALLINT CHECK (
                   ip_prefix_length IS NULL OR ip_prefix_length BETWEEN 0 AND 128
               ),
               interface_type TEXT NOT NULL DEFAULT 'physical',
               generation BIGINT NOT NULL CHECK (generation >= 0),
               observed_at TEXT NOT NULL,
               run_id TEXT NOT NULL DEFAULT '',
               metadata_json TEXT NOT NULL DEFAULT '{}',
               PRIMARY KEY (device_id, normalized_interface_name)
           )"""
    )

    cursor.execute(
        """CREATE TABLE IF NOT EXISTS cmdb_device_vlan_port_observations (
               device_id TEXT NOT NULL,
               vlan_id INTEGER NOT NULL CHECK (vlan_id BETWEEN 1 AND 4094),
               normalized_interface_name TEXT NOT NULL CHECK (normalized_interface_name <> ''),
               interface_name TEXT NOT NULL,
               port_mode TEXT NOT NULL DEFAULT 'unknown'
                   CHECK (port_mode IN ('access', 'trunk', 'unknown')),
               tagging TEXT NOT NULL DEFAULT 'unknown'
                   CHECK (tagging IN ('tagged', 'untagged', 'unknown')),
               generation BIGINT NOT NULL CHECK (generation >= 0),
               observed_at TEXT NOT NULL,
               run_id TEXT NOT NULL DEFAULT '',
               metadata_json TEXT NOT NULL DEFAULT '{}',
               PRIMARY KEY (device_id, vlan_id, normalized_interface_name),
               FOREIGN KEY (device_id, vlan_id)
                   REFERENCES cmdb_device_vlan_observations(device_id, vlan_id)
                   ON DELETE CASCADE
           )"""
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_cmdb_vlan_port_observations_vlan_device "
        "ON cmdb_device_vlan_port_observations(vlan_id, device_id)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # These tables contain only disposable CLI observations. Keeping them on
    # application rollback avoids destructive loss if a newer writer ran.
    return None
