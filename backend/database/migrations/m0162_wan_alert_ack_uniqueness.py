"""Keep acknowledged WAN alert episodes unique while they remain active.

Migration 65 replaced the legacy global ``event_key`` uniqueness with a
PostgreSQL partial index, but the predicate only covered ``firing``.  An ACK
is an operator workflow state, not a recovery; allowing a second event after
ACK produces duplicate notifications and makes the current snapshot count
ambiguous.  This additive migration broadens the active predicate to include
both firing and acknowledged events.  SQLite receives the same partial index
for its test/local path; the service still generates an episode-specific key
for compatibility with the legacy column constraint.
"""

from __future__ import annotations


VERSION = 162
NAME = "wan_alert_ack_uniqueness"


def upgrade(cursor, use_pg: bool) -> None:
    # The old index name was used by m0065 on both engines.  Dropping it is
    # safe because the replacement is created in the same migration and the
    # transaction rolls back as one unit if creation fails.
    cursor.execute("DROP INDEX IF EXISTS uq_wan_active_event")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_wan_active_alert "
        "ON wan_alert_events(link_id, metric) "
        "WHERE status IN ('firing', 'acknowledged')"
    )


__all__ = ["VERSION", "NAME", "upgrade"]
