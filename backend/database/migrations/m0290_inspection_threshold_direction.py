"""Persist the comparison direction for inspection item thresholds."""

from __future__ import annotations


VERSION = 290
NAME = "inspection_threshold_direction"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Inspection threshold direction migration requires PostgreSQL")
    cursor.execute(
        "ALTER TABLE inspection_items "
        "ADD COLUMN IF NOT EXISTS threshold_direction TEXT"
    )
    cursor.execute(
        "UPDATE inspection_items SET threshold_direction = 'above' "
        "WHERE threshold_direction IS NULL OR BTRIM(threshold_direction) = ''"
    )
    cursor.execute(
        "ALTER TABLE inspection_items "
        "ALTER COLUMN threshold_direction SET DEFAULT 'above'"
    )
    cursor.execute(
        "ALTER TABLE inspection_items "
        "ALTER COLUMN threshold_direction SET NOT NULL"
    )
    cursor.execute(
        "UPDATE inspection_items "
        "SET threshold_direction = 'below', warning_threshold = 1, critical_threshold = NULL "
        "WHERE id = 'compliance_cisco_ios_syslog'"
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep the metadata during rollback; old consumers ignore it.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
