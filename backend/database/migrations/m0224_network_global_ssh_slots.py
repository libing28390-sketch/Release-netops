"""Add PostgreSQL lease slots for deployment-wide managed SSH access."""

from __future__ import annotations


VERSION = 224
NAME = "network_global_ssh_slots"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("network_global_ssh_slots requires PostgreSQL")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS network_global_access_slots (
            purpose TEXT NOT NULL DEFAULT 'network_ssh',
            slot_id INTEGER NOT NULL CHECK (slot_id >= 0),
            lease_owner TEXT NOT NULL DEFAULT '',
            lease_token TEXT NOT NULL DEFAULT '',
            lease_until TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (purpose, slot_id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_network_global_access_lease "
        "ON network_global_access_slots(purpose, lease_until)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Preserve active lease state when rolling back application code.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
