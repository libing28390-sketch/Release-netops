"""Remove derived topology ranks and relation rank-exclusion flags."""

from __future__ import annotations


VERSION = 261
NAME = "remove_topology_rank_fields"

_COLUMNS = (
    ("topology_nodes", "rank", "DOUBLE PRECISION"),
    ("topology_edges", "rank_excluded", "INTEGER NOT NULL DEFAULT 0"),
    ("topology_relations", "rank_excluded", "INTEGER NOT NULL DEFAULT 0"),
)


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Topology rank removal requires PostgreSQL")
    for table, column, _definition in _COLUMNS:
        cursor.execute(f"ALTER TABLE IF EXISTS {table} DROP COLUMN IF EXISTS {column}")


def downgrade(cursor, use_pg: bool) -> None:
    """Restore the legacy columns with defaults; removed derived values cannot be recovered."""
    if not use_pg:
        raise RuntimeError("Topology rank restoration requires PostgreSQL")
    for table, column, definition in _COLUMNS:
        cursor.execute(
            f"ALTER TABLE IF EXISTS {table} ADD COLUMN IF NOT EXISTS {column} {definition}"
        )


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
