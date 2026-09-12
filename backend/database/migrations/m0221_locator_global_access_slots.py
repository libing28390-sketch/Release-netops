"""Add PostgreSQL leases for the deployment-wide locator CLI budget."""

from __future__ import annotations


VERSION = 221
NAME = "locator_global_access_slots"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("locator_global_access_slots requires PostgreSQL")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS locator_global_access_slots (
            purpose TEXT NOT NULL DEFAULT 'ip_locator',
            slot_id INTEGER NOT NULL CHECK (slot_id >= 0),
            lease_owner TEXT NOT NULL DEFAULT '',
            lease_token TEXT NOT NULL DEFAULT '',
            run_id TEXT NOT NULL DEFAULT '',
            lease_until TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (purpose, slot_id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_locator_global_access_lease "
        "ON locator_global_access_slots(purpose, lease_until)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep active lease metadata during an application rollback.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
