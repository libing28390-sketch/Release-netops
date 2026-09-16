"""Add reclaimable PostgreSQL leases for durable locator run workers."""

from __future__ import annotations


VERSION = 222
NAME = "locator_run_leases"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("locator_run_leases requires PostgreSQL")
    cursor.execute(
        "ALTER TABLE locator_runs ADD COLUMN IF NOT EXISTS "
        "lease_owner TEXT NOT NULL DEFAULT ''"
    )
    cursor.execute(
        "ALTER TABLE locator_runs ADD COLUMN IF NOT EXISTS "
        "lease_token TEXT NOT NULL DEFAULT ''"
    )
    cursor.execute(
        "ALTER TABLE locator_runs ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_locator_runs_claim "
        "ON locator_runs(status, deadline_at, lease_until, created_at)"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Retain lease metadata so an application rollback does not strand or
    # reactivate in-flight runs.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
