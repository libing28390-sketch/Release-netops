"""Persist the operational purpose of each WAN line probe sample."""

from __future__ import annotations


VERSION = 267
NAME = "wan_line_sample_purpose"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("WAN line sample purpose requires PostgreSQL")

    # Existing samples predate purpose-aware bindings.  Availability is the
    # only safe legacy classification because those rows may already feed
    # historical availability slots.
    cursor.execute(
        "ALTER TABLE wan_line_probe_samples ADD COLUMN IF NOT EXISTS purpose TEXT NOT NULL DEFAULT 'availability'"
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_wan_line_probe_samples_link_purpose_time
            ON wan_line_probe_samples(link_id, purpose, scheduled_at DESC)
        """
    )


def downgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("WAN line sample purpose requires PostgreSQL")
    # Purpose is audit data; removing it would destroy the distinction between
    # application/quality evidence and availability evidence, so rollback is
    # intentionally a no-op.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
