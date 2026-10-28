"""Add transactional revision counters for CMDB read projections."""

from __future__ import annotations


VERSION = 298
NAME = "cmdb_cache_versions"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("CMDB cache revisions require PostgreSQL")

    cursor.execute(
        """CREATE TABLE IF NOT EXISTS cmdb_read_versions (
               domain TEXT NOT NULL,
               scope_key TEXT NOT NULL DEFAULT '',
               revision BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0),
               updated_at TEXT NOT NULL,
               PRIMARY KEY (domain, scope_key)
           )"""
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_cmdb_read_versions_updated_at "
        "ON cmdb_read_versions(updated_at)"
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS cmdb_collection_snapshots (
               device_id TEXT NOT NULL,
               domain TEXT NOT NULL,
               attempt_generation BIGINT NOT NULL DEFAULT 0 CHECK (attempt_generation >= 0),
               successful_generation BIGINT NOT NULL DEFAULT 0 CHECK (successful_generation >= 0),
               attempt_status TEXT NOT NULL DEFAULT 'never',
               run_id TEXT NOT NULL DEFAULT '',
               last_attempt_at TEXT,
               last_success_at TEXT,
               observed_at TEXT,
               transport TEXT NOT NULL DEFAULT '',
               record_count INTEGER NOT NULL DEFAULT 0 CHECK (record_count >= 0),
               failure_code TEXT NOT NULL DEFAULT '',
               metadata_json TEXT NOT NULL DEFAULT '{}',
               PRIMARY KEY (device_id, domain)
           )"""
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_cmdb_collection_snapshots_status "
        "ON cmdb_collection_snapshots(domain, attempt_status, last_attempt_at)"
    )
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS cmdb_device_vlan_observations (
               device_id TEXT NOT NULL,
               vlan_id INTEGER NOT NULL CHECK (vlan_id BETWEEN 1 AND 4094),
               site_id TEXT NOT NULL DEFAULT '',
               vlan_name TEXT NOT NULL DEFAULT '',
               vlan_status TEXT NOT NULL DEFAULT '',
               generation BIGINT NOT NULL DEFAULT 0 CHECK (generation >= 0),
               observed_at TEXT,
               run_id TEXT NOT NULL DEFAULT '',
               PRIMARY KEY (device_id, vlan_id)
           )"""
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_cmdb_device_vlan_observations_site_vlan "
        "ON cmdb_device_vlan_observations(site_id, vlan_id, device_id)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Cache counters contain no source facts; keeping the table lets an
    # application rollback safely without making a newer schema destructive.
    return None
