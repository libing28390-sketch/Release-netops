"""Add isolated IPAM discovery evidence and explicit scope assertions."""

from __future__ import annotations


VERSION = 301
NAME = "ipam_discovery_evidence"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("IPAM discovery evidence requires PostgreSQL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_discovery_snapshots (
            id TEXT PRIMARY KEY,
            collector TEXT NOT NULL,
            device_id TEXT NOT NULL,
            source_device_name TEXT NOT NULL DEFAULT '',
            tenant_id TEXT,
            site_id TEXT,
            vrf_id TEXT,
            vrf_context_status TEXT NOT NULL DEFAULT 'unknown',
            scope_status TEXT NOT NULL DEFAULT 'scope_pending',
            source_run_id TEXT NOT NULL DEFAULT '',
            source_version TEXT NOT NULL,
            source_status TEXT NOT NULL DEFAULT 'unknown',
            coverage_status TEXT NOT NULL DEFAULT 'unavailable',
            coverage_complete SMALLINT NOT NULL DEFAULT 0,
            coverage_reason TEXT NOT NULL DEFAULT '',
            entry_count INTEGER NOT NULL DEFAULT 0,
            observed_at TEXT,
            projected_at TEXT NOT NULL,
            UNIQUE (collector, device_id, source_version)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_discovery_observations (
            id TEXT PRIMARY KEY,
            snapshot_id TEXT NOT NULL REFERENCES ipam_discovery_snapshots(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL,
            source_device_id TEXT NOT NULL,
            source_device_name TEXT NOT NULL DEFAULT '',
            tenant_id TEXT,
            site_id TEXT,
            vrf_id TEXT,
            vrf_context_status TEXT NOT NULL DEFAULT 'unknown',
            scope_status TEXT NOT NULL DEFAULT 'scope_pending',
            ip TEXT,
            mac TEXT,
            interface_name TEXT NOT NULL DEFAULT '',
            vlan TEXT NOT NULL DEFAULT '',
            source_identity_key TEXT NOT NULL,
            source_observed_at TEXT,
            timestamp_status TEXT NOT NULL DEFAULT 'unknown',
            projected_at TEXT NOT NULL,
            UNIQUE (snapshot_id, source_identity_key)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ipam_discovery_scope_assertions (
            id TEXT PRIMARY KEY,
            observation_id TEXT NOT NULL,
            source_identity_key TEXT NOT NULL,
            subnet_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            site_id TEXT NOT NULL,
            vrf_id TEXT NOT NULL DEFAULT '',
            subnet_prefix TEXT NOT NULL DEFAULT '',
            prior_scope_status TEXT NOT NULL DEFAULT 'scope_pending',
            prior_tenant_id TEXT,
            prior_site_id TEXT,
            prior_vrf_id TEXT,
            asserted_by TEXT NOT NULL DEFAULT '',
            asserted_at TEXT NOT NULL,
            confirmation TEXT NOT NULL DEFAULT 'confirmed_scope'
        )
        """
    )
    # The development service may have already applied the first draft of
    # this migration while hot reload was enabled. Keep the migration
    # repeatable when that database sees the final additive evidence fields.
    cursor.execute(
        "ALTER TABLE ipam_discovery_snapshots ADD COLUMN IF NOT EXISTS source_device_name TEXT NOT NULL DEFAULT ''"
    )
    cursor.execute(
        "ALTER TABLE ipam_discovery_snapshots ADD COLUMN IF NOT EXISTS vrf_context_status TEXT NOT NULL DEFAULT 'unknown'"
    )
    cursor.execute(
        "ALTER TABLE ipam_discovery_observations ADD COLUMN IF NOT EXISTS source_device_name TEXT NOT NULL DEFAULT ''"
    )
    cursor.execute(
        "ALTER TABLE ipam_discovery_observations ADD COLUMN IF NOT EXISTS vrf_context_status TEXT NOT NULL DEFAULT 'unknown'"
    )
    cursor.execute(
        "ALTER TABLE ipam_discovery_scope_assertions ADD COLUMN IF NOT EXISTS source_identity_key TEXT NOT NULL DEFAULT ''"
    )
    cursor.execute(
        """UPDATE ipam_discovery_scope_assertions a
              SET source_identity_key = o.source_identity_key
             FROM ipam_discovery_observations o
            WHERE a.source_identity_key = '' AND o.id = a.observation_id"""
    )
    cursor.execute(
        "ALTER TABLE ipam_discovery_scope_assertions ALTER COLUMN observation_id DROP NOT NULL"
    )
    cursor.execute(
        """DO $$ DECLARE fk RECORD; BEGIN
             FOR fk IN
                 SELECT conname FROM pg_constraint
                  WHERE conrelid = 'ipam_discovery_scope_assertions'::regclass
                    AND contype = 'f'
             LOOP
                 EXECUTE format('ALTER TABLE ipam_discovery_scope_assertions DROP CONSTRAINT %I', fk.conname);
             END LOOP;
           END $$"""
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ipam_discovery_snapshots_device_time "
        "ON ipam_discovery_snapshots(device_id, projected_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ipam_discovery_snapshots_coverage "
        "ON ipam_discovery_snapshots(coverage_complete, tenant_id, site_id, vrf_id, observed_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ipam_discovery_observations_source "
        "ON ipam_discovery_observations(source_device_id, source_type, source_observed_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ipam_discovery_observations_scope_ip "
        "ON ipam_discovery_observations(tenant_id, site_id, vrf_id, ip, source_observed_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ipam_discovery_observations_source_identity "
        "ON ipam_discovery_observations(source_identity_key, source_observed_at DESC)"
    )
    cursor.execute("DROP INDEX IF EXISTS ix_ipam_discovery_scope_assertions_latest")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ipam_discovery_scope_assertions_latest "
        "ON ipam_discovery_scope_assertions(source_identity_key, asserted_at DESC)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Evidence is retained through application rollback so previously recorded
    # manual registrations can still be explained and audited.
    return None
