"""Repair the run deployment scope on databases that applied m0219 early."""

from __future__ import annotations


VERSION = 220
NAME = "locator_run_deployment_scope"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("locator_run_deployment_scope requires PostgreSQL")
    cursor.execute(
        "ALTER TABLE locator_runs ADD COLUMN IF NOT EXISTS "
        "deployment_id TEXT NOT NULL DEFAULT ''"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep deployment scope during application rollback; it is part of the
    # query-key boundary and dropping it could merge otherwise distinct runs.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
