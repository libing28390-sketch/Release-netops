"""Add versioned service requests, SLA clocks, and ticket notification outbox."""

from __future__ import annotations


VERSION = 293
NAME = "service_requests_sla"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Service requests and ticket SLA require PostgreSQL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_work_calendars (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            name TEXT NOT NULL,
            current_version INTEGER NOT NULL DEFAULT 0,
            created_by_id TEXT NOT NULL DEFAULT '',
            created_by_username TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, name)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_work_calendar_versions (
            id TEXT PRIMARY KEY,
            calendar_id TEXT NOT NULL REFERENCES ticket_work_calendars(id) ON DELETE RESTRICT,
            version INTEGER NOT NULL,
            timezone TEXT NOT NULL,
            schedule_json JSONB NOT NULL,
            holidays_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_by_id TEXT NOT NULL DEFAULT '',
            created_by_username TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (calendar_id, version)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_sla_policies (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            name TEXT NOT NULL,
            current_version INTEGER NOT NULL DEFAULT 0,
            created_by_id TEXT NOT NULL DEFAULT '',
            created_by_username TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, name)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_sla_policy_versions (
            id TEXT PRIMARY KEY,
            policy_id TEXT NOT NULL REFERENCES ticket_sla_policies(id) ON DELETE RESTRICT,
            version INTEGER NOT NULL,
            source_type TEXT NOT NULL CHECK (source_type IN ('incident', 'service_request')),
            priority TEXT NOT NULL CHECK (priority IN ('P1', 'P2', 'P3', 'P4')),
            response_target_minutes INTEGER,
            restore_target_minutes INTEGER,
            fulfillment_target_minutes INTEGER,
            warning_before_minutes INTEGER,
            calendar_version_id TEXT NOT NULL REFERENCES ticket_work_calendar_versions(id) ON DELETE RESTRICT,
            created_by_id TEXT NOT NULL DEFAULT '',
            created_by_username TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (
                COALESCE(response_target_minutes, 0) > 0
                OR COALESCE(restore_target_minutes, 0) > 0
                OR COALESCE(fulfillment_target_minutes, 0) > 0
            ),
            CHECK (response_target_minutes IS NULL OR response_target_minutes > 0),
            CHECK (restore_target_minutes IS NULL OR restore_target_minutes > 0),
            CHECK (fulfillment_target_minutes IS NULL OR fulfillment_target_minutes > 0),
            CHECK (warning_before_minutes IS NULL OR warning_before_minutes > 0),
            CHECK (
                (source_type = 'incident' AND fulfillment_target_minutes IS NULL)
                OR (source_type = 'service_request' AND restore_target_minutes IS NULL)
            ),
            UNIQUE (policy_id, version)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_sla_policy_assignments (
            tenant_id TEXT NOT NULL,
            source_type TEXT NOT NULL CHECK (source_type IN ('incident', 'service_request')),
            priority TEXT NOT NULL CHECK (priority IN ('P1', 'P2', 'P3', 'P4')),
            policy_version_id TEXT NOT NULL REFERENCES ticket_sla_policy_versions(id) ON DELETE RESTRICT,
            updated_by_id TEXT NOT NULL DEFAULT '',
            updated_by_username TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_id, source_type, priority)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS service_catalog_items (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            item_key TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            current_version INTEGER NOT NULL DEFAULT 0,
            active BOOLEAN NOT NULL DEFAULT FALSE,
            created_by_id TEXT NOT NULL DEFAULT '',
            created_by_username TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, item_key)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS service_catalog_versions (
            id TEXT PRIMARY KEY,
            catalog_item_id TEXT NOT NULL REFERENCES service_catalog_items(id) ON DELETE RESTRICT,
            version INTEGER NOT NULL,
            request_schema_json JSONB NOT NULL DEFAULT '{"fields": []}'::jsonb,
            requires_approval BOOLEAN NOT NULL DEFAULT FALSE,
            assignment_group_id TEXT REFERENCES ticket_assignment_groups(id) ON DELETE RESTRICT,
            approval_group_id TEXT REFERENCES ticket_assignment_groups(id) ON DELETE RESTRICT,
            fulfillment_instructions TEXT NOT NULL DEFAULT '',
            acceptance_criteria TEXT NOT NULL DEFAULT '',
            sla_policy_version_id TEXT REFERENCES ticket_sla_policy_versions(id) ON DELETE RESTRICT,
            published_by_id TEXT NOT NULL DEFAULT '',
            published_by_username TEXT NOT NULL DEFAULT '',
            published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (catalog_item_id, version),
            CHECK (NOT requires_approval OR approval_group_id IS NOT NULL)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_service_catalog_active ON service_catalog_items(tenant_id, active, name)"
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS service_requests (
            id TEXT PRIMARY KEY,
            request_number TEXT NOT NULL UNIQUE,
            catalog_item_id TEXT NOT NULL REFERENCES service_catalog_items(id) ON DELETE RESTRICT,
            catalog_version_id TEXT NOT NULL REFERENCES service_catalog_versions(id) ON DELETE RESTRICT,
            tenant_id TEXT NOT NULL,
            title TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'P3' CHECK (priority IN ('P1', 'P2', 'P3', 'P4')),
            status TEXT NOT NULL DEFAULT 'submitted'
                CHECK (status IN ('submitted', 'pending_approval', 'accepted', 'in_progress', 'waiting_external', 'pending_confirmation', 'completed', 'rejected', 'cancelled')),
            requester_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            requester_username TEXT NOT NULL DEFAULT '',
            assignment_group_id TEXT REFERENCES ticket_assignment_groups(id) ON DELETE RESTRICT,
            assignee_id TEXT REFERENCES users(id) ON DELETE RESTRICT,
            assignee_username TEXT NOT NULL DEFAULT '',
            approval_group_id TEXT REFERENCES ticket_assignment_groups(id) ON DELETE RESTRICT,
            details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            catalog_snapshot_json JSONB NOT NULL,
            delivery_summary TEXT NOT NULL DEFAULT '',
            delivery_evidence_json JSONB NOT NULL DEFAULT 'null'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_service_requests_queue ON service_requests(tenant_id, status, updated_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_service_requests_requester ON service_requests(requester_id, status, updated_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_service_requests_group ON service_requests(assignment_group_id, status, updated_at DESC)")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS service_request_events (
            id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL REFERENCES service_requests(id) ON DELETE RESTRICT,
            event_type TEXT NOT NULL,
            actor_id TEXT NOT NULL DEFAULT '',
            actor_username TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            evidence_json JSONB NOT NULL DEFAULT 'null'::jsonb,
            details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_service_request_events_request ON service_request_events(request_id, created_at, id)")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_sla_clocks (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL CHECK (source_type IN ('incident', 'service_request')),
            incident_ticket_id TEXT REFERENCES incident_tickets(id) ON DELETE RESTRICT,
            service_request_id TEXT REFERENCES service_requests(id) ON DELETE RESTRICT,
            kind TEXT NOT NULL CHECK (kind IN ('response', 'restore', 'fulfillment')),
            policy_version_id TEXT NOT NULL REFERENCES ticket_sla_policy_versions(id) ON DELETE RESTRICT,
            tenant_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'paused', 'met', 'breached', 'stopped')),
            started_at TIMESTAMPTZ NOT NULL,
            running_since TIMESTAMPTZ,
            deadline_at TIMESTAMPTZ NOT NULL,
            remaining_work_seconds BIGINT NOT NULL CHECK (remaining_work_seconds >= 0),
            completed_at TIMESTAMPTZ,
            warning_sent_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (
                (source_type = 'incident' AND incident_ticket_id IS NOT NULL AND service_request_id IS NULL AND kind IN ('response', 'restore'))
                OR (source_type = 'service_request' AND service_request_id IS NOT NULL AND incident_ticket_id IS NULL AND kind IN ('response', 'fulfillment'))
            ),
            UNIQUE (incident_ticket_id, kind),
            UNIQUE (service_request_id, kind)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ticket_sla_due ON ticket_sla_clocks(status, deadline_at) WHERE status = 'running'")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ticket_sla_incident ON ticket_sla_clocks(incident_ticket_id, kind)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ticket_sla_service_request ON ticket_sla_clocks(service_request_id, kind)")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_sla_events (
            id TEXT PRIMARY KEY,
            clock_id TEXT NOT NULL REFERENCES ticket_sla_clocks(id) ON DELETE RESTRICT,
            event_type TEXT NOT NULL,
            actor_id TEXT NOT NULL DEFAULT '',
            actor_username TEXT NOT NULL DEFAULT '',
            details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_ticket_sla_events_clock ON ticket_sla_events(clock_id, created_at, id)")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_notification_outbox (
            id TEXT PRIMARY KEY,
            event_key TEXT NOT NULL,
            source_type TEXT NOT NULL CHECK (source_type IN ('incident', 'service_request')),
            incident_ticket_id TEXT REFERENCES incident_tickets(id) ON DELETE RESTRICT,
            service_request_id TEXT REFERENCES service_requests(id) ON DELETE RESTRICT,
            tenant_id TEXT NOT NULL,
            recipient_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            payload_json JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sending', 'sent', 'failed', 'suppressed')),
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            lease_owner TEXT NOT NULL DEFAULT '',
            lease_until TIMESTAMPTZ,
            last_error TEXT NOT NULL DEFAULT '',
            sent_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (
                (source_type = 'incident' AND incident_ticket_id IS NOT NULL AND service_request_id IS NULL)
                OR (source_type = 'service_request' AND service_request_id IS NOT NULL AND incident_ticket_id IS NULL)
            ),
            UNIQUE (event_key, recipient_user_id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ticket_notification_ready ON ticket_notification_outbox(status, available_at, created_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ticket_notification_source ON ticket_notification_outbox(source_type, incident_ticket_id, service_request_id, created_at DESC)"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_notification_attempts (
            id TEXT PRIMARY KEY,
            outbox_id TEXT NOT NULL REFERENCES ticket_notification_outbox(id) ON DELETE RESTRICT,
            attempt_no INTEGER NOT NULL CHECK (attempt_no > 0),
            phase TEXT NOT NULL CHECK (phase IN ('started', 'sent', 'failed', 'suppressed')),
            worker_id TEXT NOT NULL DEFAULT '',
            error_code TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (outbox_id, attempt_no, phase)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ticket_notification_attempts_outbox ON ticket_notification_attempts(outbox_id, attempt_no, created_at)"
    )

    cursor.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_itsm_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'ITSM event ledgers are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    cursor.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_itsm_published_version_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'published ITSM versions are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table_name, trigger_name in (
        ("service_request_events", "trg_service_request_events_append_only"),
        ("ticket_sla_events", "trg_ticket_sla_events_append_only"),
        ("ticket_notification_attempts", "trg_ticket_notification_attempts_append_only"),
    ):
        cursor.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}")
        cursor.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION prevent_itsm_event_mutation()
            """
        )
    for table_name, trigger_name in (
        ("service_catalog_versions", "trg_service_catalog_versions_immutable"),
        ("ticket_work_calendar_versions", "trg_ticket_work_calendar_versions_immutable"),
        ("ticket_sla_policy_versions", "trg_ticket_sla_policy_versions_immutable"),
    ):
        cursor.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}")
        cursor.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION prevent_itsm_published_version_mutation()
            """
        )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Service requests and SLA histories are durable business records.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
