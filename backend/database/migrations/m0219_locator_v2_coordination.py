"""Add the PostgreSQL coordination model for the V2 IP locator.

The V2 locator deliberately has its own durable model.  The legacy collector
queue is keyed by ``(collector, device_id)`` and cannot represent a shared
query subscribed by several runs, scoped evidence, or a per-device lease.  A
locator task is therefore deduplicated by a caller-built ``query_key`` and
connected to one or more runs through ``locator_run_tasks``.

This migration is PostgreSQL-only.  Locator evidence uses JSONB and
``timestamptz`` so that the service can keep structured records and compare
freshness in UTC without introducing a SQLite production path.
"""

from __future__ import annotations


VERSION = 219
NAME = "locator_v2_coordination"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("locator_v2_coordination requires PostgreSQL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS locator_runs (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            deployment_id TEXT NOT NULL DEFAULT '',
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            scope_hash TEXT NOT NULL DEFAULT '',
            network_domain_id TEXT NOT NULL DEFAULT '',
            site_id TEXT NOT NULL DEFAULT '',
            vrf_name TEXT NOT NULL DEFAULT 'default',
            target_ip TEXT NOT NULL CHECK (BTRIM(target_ip) <> ''),
            start_device_id TEXT NOT NULL DEFAULT '',
            mode TEXT NOT NULL DEFAULT 'normal'
                CHECK (mode IN ('normal', 'force_refresh')),
            force_refresh BOOLEAN NOT NULL DEFAULT FALSE,
            authorization_scope_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN (
                    'queued', 'running', 'completed', 'partial', 'failed',
                    'cancelled', 'needs_context'
                )),
            deadline_at TIMESTAMPTZ NOT NULL,
            result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            stats_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            error_code TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            version BIGINT NOT NULL DEFAULT 1 CHECK (version > 0),
            cancel_requested_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    # ``locator_runs`` was introduced in this migration, but the additive
    # guard also makes a partially applied development database safe to retry.
    cursor.execute(
        "ALTER TABLE locator_runs ADD COLUMN IF NOT EXISTS "
        "deployment_id TEXT NOT NULL DEFAULT ''"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS locator_query_tasks (
            id TEXT PRIMARY KEY,
            query_key TEXT NOT NULL,
            deployment_id TEXT NOT NULL DEFAULT '',
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            scope_hash TEXT NOT NULL DEFAULT '',
            network_domain_id TEXT NOT NULL DEFAULT '',
            site_id TEXT NOT NULL DEFAULT '',
            vrf_name TEXT NOT NULL DEFAULT 'default',
            start_device_id TEXT NOT NULL DEFAULT '',
            operation TEXT NOT NULL
                CHECK (operation IN (
                    'route', 'arp', 'mac', 'topology', 'interface', 'neighbor'
                )),
            device_id TEXT,
            target_ip TEXT NOT NULL DEFAULT '',
            target_mac TEXT NOT NULL DEFAULT '',
            bridge_domain TEXT NOT NULL DEFAULT '',
            vlan_id INTEGER,
            target_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            authorization_scope_hash TEXT NOT NULL DEFAULT '',
            action_version TEXT NOT NULL DEFAULT '',
            parser_version TEXT NOT NULL DEFAULT '',
            priority INTEGER NOT NULL DEFAULT 100 CHECK (priority >= 0),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN (
                    'pending', 'running', 'succeeded', 'failed',
                    'cancelled', 'expired'
                )),
            available_at TIMESTAMPTZ NOT NULL,
            deadline_at TIMESTAMPTZ NOT NULL,
            lease_owner TEXT NOT NULL DEFAULT '',
            lease_token TEXT NOT NULL DEFAULT '',
            lease_until TIMESTAMPTZ,
            attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
            max_attempts INTEGER NOT NULL DEFAULT 2 CHECK (max_attempts > 0),
            generation BIGINT NOT NULL DEFAULT 0 CHECK (generation >= 0),
            payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            error_code TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            cancel_requested_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL,
            UNIQUE (query_key),
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE SET NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS locator_run_tasks (
            run_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            relation_role TEXT NOT NULL DEFAULT 'required',
            required BOOLEAN NOT NULL DEFAULT TRUE,
            status TEXT NOT NULL DEFAULT 'subscribed'
                CHECK (status IN (
                    'subscribed', 'detached', 'fulfilled', 'failed'
                )),
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (run_id, task_id),
            FOREIGN KEY (run_id) REFERENCES locator_runs(id) ON DELETE CASCADE,
            FOREIGN KEY (task_id) REFERENCES locator_query_tasks(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS locator_observations (
            id TEXT PRIMARY KEY,
            observation_key TEXT NOT NULL UNIQUE,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            scope_hash TEXT NOT NULL DEFAULT '',
            network_domain_id TEXT NOT NULL DEFAULT '',
            site_id TEXT NOT NULL DEFAULT '',
            vrf_name TEXT NOT NULL DEFAULT 'default',
            device_id TEXT NOT NULL,
            observation_kind TEXT NOT NULL
                CHECK (observation_kind IN (
                    'route', 'arp', 'mac', 'interface', 'neighbor',
                    'topology', 'path'
                )),
            target_ip TEXT NOT NULL DEFAULT '',
            target_mac TEXT NOT NULL DEFAULT '',
            bridge_domain TEXT NOT NULL DEFAULT '',
            vlan_id INTEGER,
            records_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            coverage TEXT NOT NULL DEFAULT 'targeted'
                CHECK (coverage IN ('targeted', 'full', 'partial', 'failed')),
            source TEXT NOT NULL DEFAULT 'ssh_cli',
            collected_at TIMESTAMPTZ NOT NULL,
            fresh_until TIMESTAMPTZ NOT NULL,
            retain_until TIMESTAMPTZ NOT NULL,
            generation BIGINT NOT NULL DEFAULT 0 CHECK (generation >= 0),
            action_version TEXT NOT NULL DEFAULT '',
            parser_version TEXT NOT NULL DEFAULT '',
            schema_version TEXT NOT NULL DEFAULT 'locator-v2',
            query_task_id TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            CHECK (fresh_until >= collected_at),
            CHECK (retain_until >= fresh_until),
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE,
            FOREIGN KEY (query_task_id) REFERENCES locator_query_tasks(id) ON DELETE SET NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS network_device_access_slots (
            canonical_device_id TEXT NOT NULL,
            purpose TEXT NOT NULL DEFAULT 'ip_locator',
            slot_id INTEGER NOT NULL DEFAULT 0 CHECK (slot_id >= 0),
            lease_owner TEXT NOT NULL DEFAULT '',
            lease_token TEXT NOT NULL DEFAULT '',
            task_id TEXT,
            lease_until TIMESTAMPTZ,
            connection_state TEXT NOT NULL DEFAULT 'idle'
                CHECK (connection_state IN ('idle', 'leased', 'draining')),
            last_acquired_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (canonical_device_id, purpose, slot_id),
            FOREIGN KEY (canonical_device_id) REFERENCES devices(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS locator_history (
            id TEXT PRIMARY KEY,
            run_id TEXT,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            scope_hash TEXT NOT NULL DEFAULT '',
            network_domain_id TEXT NOT NULL DEFAULT '',
            site_id TEXT NOT NULL DEFAULT '',
            vrf_name TEXT NOT NULL DEFAULT 'default',
            target_ip TEXT NOT NULL DEFAULT '',
            outcome TEXT NOT NULL DEFAULT '',
            result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            source TEXT NOT NULL DEFAULT 'ssh_cli',
            generated_at TIMESTAMPTZ NOT NULL,
            fresh_until TIMESTAMPTZ NOT NULL,
            retain_until TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            FOREIGN KEY (run_id) REFERENCES locator_runs(id) ON DELETE SET NULL,
            CHECK (retain_until >= generated_at)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS locator_invalidation_outbox (
            id TEXT PRIMARY KEY,
            event_key TEXT NOT NULL UNIQUE,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            scope_hash TEXT NOT NULL DEFAULT '',
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            generation BIGINT NOT NULL DEFAULT 0 CHECK (generation >= 0),
            payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'processing', 'processed', 'failed')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            available_at TIMESTAMPTZ NOT NULL,
            lease_owner TEXT NOT NULL DEFAULT '',
            lease_token TEXT NOT NULL DEFAULT '',
            lease_until TIMESTAMPTZ,
            last_error TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL,
            processed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_locator_runs_owner_status "
        "ON locator_runs(owner_id, status, created_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_locator_runs_scope_target "
        "ON locator_runs(tenant_id, scope_hash, target_ip, created_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_locator_tasks_claim "
        "ON locator_query_tasks(status, available_at, priority, id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_locator_tasks_lease "
        "ON locator_query_tasks(status, lease_until)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_locator_tasks_device "
        "ON locator_query_tasks(device_id, operation, status, available_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_locator_run_tasks_task "
        "ON locator_run_tasks(task_id, status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_locator_observations_lookup "
        "ON locator_observations(tenant_id, scope_hash, observation_kind, "
        "device_id, vrf_name, target_ip, target_mac)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_locator_observations_freshness "
        "ON locator_observations(fresh_until, retain_until)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_device_access_slots_lease "
        "ON network_device_access_slots(canonical_device_id, purpose, lease_until)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_locator_history_target "
        "ON locator_history(tenant_id, scope_hash, target_ip, generated_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_locator_history_retention "
        "ON locator_history(retain_until)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_locator_outbox_claim "
        "ON locator_invalidation_outbox(status, available_at, created_at)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Application rollback keeps the additive evidence and queue tables so an
    # older binary cannot silently discard locator history or active leases.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
