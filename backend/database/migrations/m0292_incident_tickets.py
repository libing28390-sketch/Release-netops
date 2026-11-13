"""Persist incident response tickets, assignment groups, events and links."""

from __future__ import annotations


VERSION = 292
NAME = "incident_tickets"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Incident tickets require PostgreSQL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_assignment_groups (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_by_id TEXT NOT NULL DEFAULT '',
            created_by_username TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ticket_assignment_groups_tenant_name "
        "ON ticket_assignment_groups (tenant_id, lower(name))"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS ticket_assignment_group_members (
            id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL REFERENCES ticket_assignment_groups(id) ON DELETE CASCADE,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            username TEXT NOT NULL DEFAULT '',
            added_by_id TEXT NOT NULL DEFAULT '',
            added_by_username TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (group_id, user_id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_ticket_assignment_group_members_user "
        "ON ticket_assignment_group_members(user_id, group_id)"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS incident_tickets (
            id TEXT PRIMARY KEY,
            ticket_number TEXT NOT NULL,
            source_incident_id TEXT NOT NULL UNIQUE
                REFERENCES monitoring_incidents(id) ON DELETE RESTRICT,
            tenant_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            severity TEXT NOT NULL DEFAULT 'warning',
            priority TEXT NOT NULL DEFAULT 'P3',
            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'in_progress', 'pending_confirmation', 'closed', 'cancelled', 'merged')),
            primary_device_id TEXT,
            site_id TEXT NOT NULL DEFAULT '',
            device_group_id TEXT NOT NULL DEFAULT '',
            assigned_group_id TEXT REFERENCES ticket_assignment_groups(id) ON DELETE SET NULL,
            assignee_id TEXT REFERENCES users(id) ON DELETE RESTRICT,
            assignee_username TEXT NOT NULL DEFAULT '',
            created_by_id TEXT NOT NULL DEFAULT '',
            created_by_username TEXT NOT NULL DEFAULT '',
            merged_into_id TEXT REFERENCES incident_tickets(id) ON DELETE RESTRICT,
            source_status TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            closed_at TIMESTAMPTZ
        )
        """
    )
    cursor.execute("ALTER TABLE incident_tickets ADD COLUMN IF NOT EXISTS ticket_number TEXT")
    cursor.execute("ALTER TABLE incident_tickets ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'P3'")
    cursor.execute(
        """
        UPDATE incident_tickets
           SET ticket_number = 'INC-' || TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYYMMDD') || '-' || UPPER(SUBSTRING(REPLACE(id, '-', ''), 1, 8))
         WHERE ticket_number IS NULL OR BTRIM(ticket_number) = ''
        """
    )
    cursor.execute("ALTER TABLE incident_tickets ALTER COLUMN ticket_number SET NOT NULL")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_incident_tickets_ticket_number ON incident_tickets(ticket_number)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_incident_tickets_queue "
        "ON incident_tickets(status, updated_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_incident_tickets_assignee "
        "ON incident_tickets(assignee_id, status, updated_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_incident_tickets_group "
        "ON incident_tickets(assigned_group_id, status, updated_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_incident_tickets_tenant "
        "ON incident_tickets(tenant_id, status, updated_at DESC)"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS incident_ticket_events (
            id TEXT PRIMARY KEY,
            ticket_id TEXT NOT NULL REFERENCES incident_tickets(id) ON DELETE RESTRICT,
            event_type TEXT NOT NULL,
            actor_id TEXT NOT NULL DEFAULT '',
            actor_username TEXT NOT NULL DEFAULT '',
            details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            source_status TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_incident_ticket_events_ticket "
        "ON incident_ticket_events(ticket_id, created_at, id)"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS incident_ticket_links (
            id TEXT PRIMARY KEY,
            ticket_id TEXT NOT NULL REFERENCES incident_tickets(id) ON DELETE RESTRICT,
            change_order_id TEXT NOT NULL REFERENCES change_orders(id) ON DELETE RESTRICT,
            linked_by_id TEXT NOT NULL DEFAULT '',
            linked_by_username TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (ticket_id, change_order_id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_incident_ticket_links_change_order "
        "ON incident_ticket_links(change_order_id)"
    )
    cursor.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_incident_ticket_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'incident_ticket_events is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    cursor.execute(
        "DROP TRIGGER IF EXISTS trg_incident_ticket_events_append_only ON incident_ticket_events"
    )
    cursor.execute(
        """
        CREATE TRIGGER trg_incident_ticket_events_append_only
        BEFORE UPDATE OR DELETE ON incident_ticket_events
        FOR EACH ROW EXECUTE FUNCTION prevent_incident_ticket_event_mutation()
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Ticket and assignment facts are durable audit records; downgrade is a no-op.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
