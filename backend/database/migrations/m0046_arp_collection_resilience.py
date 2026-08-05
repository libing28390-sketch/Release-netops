"""Add retry and circuit-breaker state for device collectors."""

from __future__ import annotations


VERSION = 46
NAME = "arp_collection_resilience"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table,),
        )
        return {row[0] for row in cursor.fetchall()}
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def upgrade(cursor, use_pg: bool) -> None:
    existing = _columns(cursor, "device_collection_status", use_pg)
    for name, definition in [
        ("next_retry_at", "TEXT"),
        ("failure_class", "TEXT DEFAULT ''"),
        ("circuit_state", "TEXT DEFAULT 'closed'"),
        ("last_failure_at", "TEXT"),
    ]:
        if name not in existing:
            cursor.execute(
                f"ALTER TABLE device_collection_status ADD COLUMN {name} {definition}"
            )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_collection_status_retry "
        "ON device_collection_status(collector, circuit_state, next_retry_at)"
    )
