"""Add the PostgreSQL-only per-circuit probe and SLA evidence ledger.

The existing outbound probe tables intentionally remain target-scoped.  This
migration adds a separate ledger for circuit executions so that one target can
be bound to more than one circuit without sharing a success result between
those circuits.  Samples and SLA/quality aggregates use different tables and
carry the configuration, policy and path-evidence versions used to produce
them.
"""

from __future__ import annotations


VERSION = 264
NAME = "wan_circuit_probe_sla"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("WAN circuit probe/SLA ledger requires PostgreSQL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS wan_line_probe_samples (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            link_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            context_id TEXT NOT NULL,
            context_version TEXT NOT NULL,
            configuration_version INTEGER NOT NULL DEFAULT 1,
            policy_version INTEGER NOT NULL DEFAULT 0,
            executor_id TEXT NOT NULL DEFAULT '',
            protocol TEXT NOT NULL,
            route_mode TEXT NOT NULL DEFAULT 'default',
            source_ip TEXT NOT NULL DEFAULT '',
            path_status TEXT NOT NULL DEFAULT 'unverified'
                CHECK (path_status IN ('verified', 'unverified', 'invalid', 'unsupported')),
            evidence_version TEXT NOT NULL DEFAULT '',
            path_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
            target_name TEXT NOT NULL DEFAULT '',
            target_host TEXT NOT NULL DEFAULT '',
            scheduled_at TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            execution_status TEXT NOT NULL DEFAULT 'completed'
                CHECK (execution_status IN ('completed', 'failed', 'skipped', 'unsupported', 'internal_error')),
            success BOOLEAN,
            sla_eligible BOOLEAN NOT NULL DEFAULT FALSE,
            latency_ms NUMERIC,
            sent_count INTEGER,
            received_count INTEGER,
            packet_loss_percent NUMERIC,
            rtt_jitter_ms NUMERIC,
            error_type TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            resolved_ip TEXT NOT NULL DEFAULT '',
            result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT uq_wan_line_probe_sample_context_slot UNIQUE (context_id, scheduled_at)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_wan_line_probe_samples_tenant_link_time "
        "ON wan_line_probe_samples (tenant_id, link_id, scheduled_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_wan_line_probe_samples_context_time "
        "ON wan_line_probe_samples (context_id, scheduled_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_wan_line_probe_samples_target_time "
        "ON wan_line_probe_samples (tenant_id, target_id, scheduled_at DESC)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS wan_line_quality_slots (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            link_id TEXT NOT NULL,
            slot_start TIMESTAMPTZ NOT NULL,
            slot_end TIMESTAMPTZ NOT NULL,
            configuration_version INTEGER NOT NULL DEFAULT 1,
            policy_version INTEGER NOT NULL DEFAULT 0,
            context_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            context_versions JSONB NOT NULL DEFAULT '[]'::jsonb,
            status TEXT NOT NULL
                CHECK (status IN ('up', 'down', 'unknown')),
            reason_code TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
            sample_count INTEGER NOT NULL DEFAULT 0,
            eligible_sample_count INTEGER NOT NULL DEFAULT 0,
            sent_count INTEGER NOT NULL DEFAULT 0,
            received_count INTEGER NOT NULL DEFAULT 0,
            coverage_percent NUMERIC,
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            algorithm_version TEXT NOT NULL DEFAULT 'wan-sla-v1',
            CONSTRAINT uq_wan_line_quality_slot_version
                UNIQUE (link_id, slot_start, configuration_version, policy_version, algorithm_version)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_wan_line_quality_slots_tenant_link_time "
        "ON wan_line_quality_slots (tenant_id, link_id, slot_start DESC)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS wan_line_sla_snapshots (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            link_id TEXT NOT NULL,
            window_key TEXT NOT NULL,
            window_start TIMESTAMPTZ NOT NULL,
            window_end TIMESTAMPTZ NOT NULL,
            configuration_version INTEGER NOT NULL DEFAULT 1,
            policy_version INTEGER NOT NULL DEFAULT 0,
            algorithm_version TEXT NOT NULL DEFAULT 'wan-sla-v1',
            status TEXT NOT NULL,
            reason_code TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            observed_availability NUMERIC,
            lower_bound NUMERIC,
            upper_bound NUMERIC,
            coverage_percent NUMERIC,
            eligible_seconds BIGINT NOT NULL DEFAULT 0,
            up_seconds BIGINT NOT NULL DEFAULT 0,
            down_seconds BIGINT NOT NULL DEFAULT 0,
            unknown_seconds BIGINT NOT NULL DEFAULT 0,
            slot_count INTEGER NOT NULL DEFAULT 0,
            up_slot_count INTEGER NOT NULL DEFAULT 0,
            down_slot_count INTEGER NOT NULL DEFAULT 0,
            unknown_slot_count INTEGER NOT NULL DEFAULT 0,
            slot_stats JSONB NOT NULL DEFAULT '{}'::jsonb,
            evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
            revision INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT uq_wan_line_sla_snapshot_version UNIQUE (
                link_id, window_key, window_start, window_end,
                configuration_version, policy_version, algorithm_version
            )
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_wan_line_sla_snapshots_tenant_link_time "
        "ON wan_line_sla_snapshots (tenant_id, link_id, window_end DESC)"
    )


def downgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("WAN circuit probe/SLA ledger requires PostgreSQL")
    # The ledger is additive and contains audit evidence.  Rollback keeps it
    # intact so a code rollback cannot silently erase operational history.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
