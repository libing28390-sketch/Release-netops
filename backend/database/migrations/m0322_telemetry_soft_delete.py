"""Add soft-delete metadata to Telemetry subscriptions."""

from __future__ import annotations


VERSION = 322
NAME = "telemetry_soft_delete"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Telemetry soft-delete metadata requires PostgreSQL")

    cursor.execute(
        "ALTER TABLE telemetry_subscriptions "
        "ADD COLUMN IF NOT EXISTS deleted_at TEXT"
    )
    # Keep names unique among live subscriptions while allowing an operator to
    # recreate a subscription after its previous row has been soft-deleted.
    cursor.execute(
        "ALTER TABLE telemetry_subscriptions "
        "DROP CONSTRAINT IF EXISTS uq_telemetry_subscriptions_config_name"
    )
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_telemetry_subscriptions_config_name_active "
        "ON telemetry_subscriptions(config_id, name) WHERE deleted_at IS NULL"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Retain deletion timestamps across application rollback.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
