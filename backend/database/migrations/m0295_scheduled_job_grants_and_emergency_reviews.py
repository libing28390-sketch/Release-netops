"""Add bounded scheduled-job authorization grants and emergency review facts."""

from __future__ import annotations


VERSION = 295
NAME = "scheduled_job_grants_and_emergency_reviews"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Scheduled-job grants and emergency reviews require PostgreSQL")

    cursor.execute(
        "ALTER TABLE scheduled_jobs "
        "ADD COLUMN IF NOT EXISTS current_authorization_grant_id TEXT NOT NULL DEFAULT ''"
    )
    cursor.execute(
        "ALTER TABLE scheduled_jobs ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduled_job_authorization_grants (
            grant_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            version INTEGER NOT NULL CHECK (version > 0),
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'revoked', 'expired', 'exhausted', 'superseded')),
            owner_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            template_version TEXT NOT NULL DEFAULT '',
            manifest_hash TEXT NOT NULL,
            grant_json JSONB NOT NULL,
            valid_until TIMESTAMPTZ NOT NULL,
            max_runs INTEGER NOT NULL CHECK (max_runs BETWEEN 1 AND 10000),
            used_runs INTEGER NOT NULL DEFAULT 0 CHECK (used_runs >= 0),
            max_targets INTEGER NOT NULL CHECK (max_targets BETWEEN 1 AND 10000),
            ticket_source_type TEXT NOT NULL
                CHECK (ticket_source_type IN ('incident', 'service_request')),
            ticket_id TEXT NOT NULL,
            ticket_number TEXT NOT NULL DEFAULT '',
            ticket_title TEXT NOT NULL DEFAULT '',
            change_order_id TEXT NOT NULL DEFAULT '',
            change_order_number TEXT NOT NULL DEFAULT '',
            created_by_id TEXT NOT NULL,
            approved_by_id TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            revoked_at TIMESTAMPTZ,
            UNIQUE (job_id, version)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_scheduled_job_grants_job_version "
        "ON scheduled_job_authorization_grants(job_id, version DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_scheduled_job_grants_status_expiry "
        "ON scheduled_job_authorization_grants(status, valid_until)"
    )
    cursor.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_scheduled_job_grant_snapshot_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'scheduled_job_authorization_grants are immutable audit records';
            END IF;
            IF ROW(
                NEW.grant_id, NEW.job_id, NEW.version, NEW.owner_id, NEW.tenant_id,
                NEW.template_version, NEW.manifest_hash, NEW.grant_json, NEW.valid_until,
                NEW.max_runs, NEW.max_targets, NEW.ticket_source_type, NEW.ticket_id,
                NEW.ticket_number, NEW.ticket_title, NEW.change_order_id,
                NEW.change_order_number, NEW.created_by_id, NEW.approved_by_id, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.grant_id, OLD.job_id, OLD.version, OLD.owner_id, OLD.tenant_id,
                OLD.template_version, OLD.manifest_hash, OLD.grant_json, OLD.valid_until,
                OLD.max_runs, OLD.max_targets, OLD.ticket_source_type, OLD.ticket_id,
                OLD.ticket_number, OLD.ticket_title, OLD.change_order_id,
                OLD.change_order_number, OLD.created_by_id, OLD.approved_by_id, OLD.created_at
            ) THEN
                RAISE EXCEPTION 'scheduled_job_authorization_grants snapshot fields are immutable';
            END IF;
            IF NEW.used_runs < OLD.used_runs OR NEW.used_runs > NEW.max_runs THEN
                RAISE EXCEPTION 'scheduled job grant usage must be monotonic and within quota';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status
               AND NOT (OLD.status = 'active' AND NEW.status IN ('revoked', 'expired', 'exhausted', 'superseded')) THEN
                RAISE EXCEPTION 'scheduled job grant status cannot be reopened or moved backwards';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    cursor.execute(
        "DROP TRIGGER IF EXISTS trg_scheduled_job_grant_snapshot_immutable "
        "ON scheduled_job_authorization_grants"
    )
    cursor.execute(
        """
        CREATE TRIGGER trg_scheduled_job_grant_snapshot_immutable
        BEFORE UPDATE OR DELETE ON scheduled_job_authorization_grants
        FOR EACH ROW EXECUTE FUNCTION prevent_scheduled_job_grant_snapshot_mutation()
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduled_job_runs (
            run_id TEXT PRIMARY KEY,
            run_key TEXT NOT NULL UNIQUE,
            job_id TEXT NOT NULL,
            job_name TEXT NOT NULL DEFAULT '',
            job_type TEXT NOT NULL DEFAULT '',
            action_type TEXT NOT NULL DEFAULT '',
            trigger_type TEXT NOT NULL CHECK (trigger_type IN ('cron', 'once')),
            scheduled_for TIMESTAMPTZ NOT NULL,
            grant_id TEXT REFERENCES scheduled_job_authorization_grants(grant_id) ON DELETE RESTRICT,
            grant_version INTEGER NOT NULL DEFAULT 0,
            snapshot_hash TEXT NOT NULL DEFAULT '',
            ticket_source_type TEXT NOT NULL DEFAULT '',
            ticket_id TEXT NOT NULL DEFAULT '',
            ticket_number TEXT NOT NULL DEFAULT '',
            ticket_title TEXT NOT NULL DEFAULT '',
            change_order_id TEXT NOT NULL DEFAULT '',
            change_order_number TEXT NOT NULL DEFAULT '',
            owner_id TEXT NOT NULL DEFAULT '',
            tenant_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'partial_failure', 'unknown', 'denied', 'skipped')),
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            target_count INTEGER NOT NULL DEFAULT 0 CHECK (target_count >= 0),
            success_count INTEGER NOT NULL DEFAULT 0 CHECK (success_count >= 0),
            failed_count INTEGER NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
            error_code TEXT NOT NULL DEFAULT '',
            error_summary TEXT NOT NULL DEFAULT '',
            execution_id TEXT NOT NULL DEFAULT '',
            resolved_from_status TEXT NOT NULL DEFAULT '',
            resolved_outcome TEXT NOT NULL DEFAULT '',
            resolved_by_id TEXT NOT NULL DEFAULT '',
            resolved_by_username TEXT NOT NULL DEFAULT '',
            resolved_at TIMESTAMPTZ,
            resolution_note TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_scheduled_job_runs_job_schedule "
        "ON scheduled_job_runs(job_id, scheduled_for DESC, run_id DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_scheduled_job_runs_status_started "
        "ON scheduled_job_runs(status, started_at)"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_scheduled_job_run_one_running_per_job "
        "ON scheduled_job_runs(job_id) WHERE status = 'running'"
    )
    cursor.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_scheduled_job_run_snapshot_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'scheduled_job_runs are immutable audit records';
            END IF;
            IF ROW(
                NEW.run_id, NEW.run_key, NEW.job_id, NEW.job_name, NEW.job_type,
                NEW.action_type, NEW.trigger_type, NEW.scheduled_for, NEW.grant_id,
                NEW.grant_version, NEW.snapshot_hash, NEW.ticket_source_type,
                NEW.ticket_id, NEW.ticket_number, NEW.ticket_title,
                NEW.change_order_id, NEW.change_order_number, NEW.owner_id,
                NEW.tenant_id, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.run_id, OLD.run_key, OLD.job_id, OLD.job_name, OLD.job_type,
                OLD.action_type, OLD.trigger_type, OLD.scheduled_for, OLD.grant_id,
                OLD.grant_version, OLD.snapshot_hash, OLD.ticket_source_type,
                OLD.ticket_id, OLD.ticket_number, OLD.ticket_title,
                OLD.change_order_id, OLD.change_order_number, OLD.owner_id,
                OLD.tenant_id, OLD.created_at
            ) THEN
                RAISE EXCEPTION 'scheduled job run snapshot fields are immutable';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
                (OLD.status = 'running' AND NEW.status IN ('succeeded', 'failed', 'partial_failure', 'unknown', 'denied', 'skipped'))
                OR (OLD.status = 'unknown' AND NEW.status IN ('succeeded', 'failed', 'partial_failure'))
            ) THEN
                RAISE EXCEPTION 'scheduled job run status transition is invalid';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    cursor.execute(
        "DROP TRIGGER IF EXISTS trg_scheduled_job_run_snapshot_immutable ON scheduled_job_runs"
    )
    cursor.execute(
        """
        CREATE TRIGGER trg_scheduled_job_run_snapshot_immutable
        BEFORE UPDATE OR DELETE ON scheduled_job_runs
        FOR EACH ROW EXECUTE FUNCTION prevent_scheduled_job_run_snapshot_mutation()
        """
    )

    # Pre-grant user jobs cannot inherit the new bounded authorization model.
    # Retain their configuration and history for explicit reauthorization.
    cursor.execute(
        """
        UPDATE scheduled_jobs
           SET enabled = 0,
               status = 'reauthorization_required'
         WHERE COALESCE(authorization_mode, 'legacy') <> 'system'
           AND COALESCE(current_authorization_grant_id, '') = ''
        """
    )

    for name, declaration in (
        ("emergency_reason", "TEXT NOT NULL DEFAULT ''"),
        ("emergency_review_owner_id", "TEXT NOT NULL DEFAULT ''"),
        ("emergency_review_due_at", "TIMESTAMPTZ"),
        ("emergency_review_status", "TEXT NOT NULL DEFAULT ''"),
        ("emergency_reviewed_by_id", "TEXT NOT NULL DEFAULT ''"),
        ("emergency_reviewed_by", "TEXT NOT NULL DEFAULT ''"),
        ("emergency_reviewed_at", "TIMESTAMPTZ"),
        ("emergency_review_note", "TEXT NOT NULL DEFAULT ''"),
    ):
        cursor.execute(f"ALTER TABLE change_orders ADD COLUMN IF NOT EXISTS {name} {declaration}")

    cursor.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE conname = 'ck_change_orders_emergency_review_status'
            ) THEN
                ALTER TABLE change_orders
                    ADD CONSTRAINT ck_change_orders_emergency_review_status
                    CHECK (emergency_review_status IN ('', 'pending', 'accepted', 'follow_up_required'));
            END IF;
        END;
        $$
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Run ledgers, grant history, and emergency review facts are audit records.
    # Keep them in place on application rollback.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
