"""Link service requests to existing change orders without bypassing approval."""

from __future__ import annotations


VERSION = 294
NAME = "service_request_change_order_links"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Service request/change order links require PostgreSQL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS service_request_change_order_links (
            id TEXT PRIMARY KEY,
            service_request_id TEXT NOT NULL REFERENCES service_requests(id) ON DELETE RESTRICT,
            change_order_id TEXT NOT NULL REFERENCES change_orders(id) ON DELETE RESTRICT,
            linked_by_id TEXT NOT NULL DEFAULT '',
            linked_by_username TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (service_request_id, change_order_id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_service_request_change_order_links_change_order ON service_request_change_order_links(change_order_id)"
    )
    cursor.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_service_request_change_order_link_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'service request change-order links are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    cursor.execute(
        "DROP TRIGGER IF EXISTS trg_service_request_change_order_links_append_only ON service_request_change_order_links"
    )
    cursor.execute(
        """
        CREATE TRIGGER trg_service_request_change_order_links_append_only
        BEFORE UPDATE OR DELETE ON service_request_change_order_links
        FOR EACH ROW EXECUTE FUNCTION prevent_service_request_change_order_link_mutation()
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Link history is audit data and stays in place on application rollback.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
