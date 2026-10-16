"""Persist packet-loss and packet-delay variation for ICMP probe samples."""

from __future__ import annotations


VERSION = 258
NAME = "outbound_probe_icmp_quality"


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg  # Runtime and migration acceptance use PostgreSQL only.
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        ("outbound_probe_results",),
    ).fetchall()
    columns = {str(row[0]).lower() for row in rows}
    for name in ("packet_loss_percent", "rtt_jitter_ms"):
        if name not in columns:
            cursor.execute(f"ALTER TABLE outbound_probe_results ADD COLUMN {name} REAL")


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Preserve historical measurements during application rollback.
    return None


__all__ = ["VERSION", "NAME", "upgrade"]
