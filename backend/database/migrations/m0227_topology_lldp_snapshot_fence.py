"""Persist per-device LLDP snapshot completeness and collection fencing state."""

from __future__ import annotations


VERSION = 227
NAME = "topology_lldp_snapshot_fence"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("topology_lldp_snapshot_fence requires PostgreSQL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS topology_device_lldp_snapshots (
            device_id TEXT PRIMARY KEY
                REFERENCES devices (id) ON DELETE CASCADE,
            generation BIGINT NOT NULL DEFAULT 0 CHECK (generation >= 0),
            state TEXT NOT NULL DEFAULT 'unknown'
                CHECK (state IN ('unknown', 'collecting', 'complete', 'failed')),
            snapshot_complete BOOLEAN NOT NULL DEFAULT FALSE,
            observation_count INTEGER NOT NULL DEFAULT 0
                CHECK (observation_count >= 0),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            action_version TEXT NOT NULL DEFAULT '',
            parser_version TEXT NOT NULL DEFAULT '',
            schema_version TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL
        )
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep snapshot rows and their generation fence during application rollback.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
