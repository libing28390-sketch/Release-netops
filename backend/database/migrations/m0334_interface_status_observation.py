"""Track a timestamp and source for the stored interface state pair.

``interfaces.last_seen`` is refreshed by VLAN and address-snapshot collectors,
so it cannot certify when ``admin_status`` and ``oper_status`` were observed.
These nullable/empty fields are populated only by a collector that reads both
state values in the same batch. Existing rows are intentionally not backfilled.
"""

from __future__ import annotations

VERSION = 334
NAME = "interface_status_observation"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        return
    cursor.execute("ALTER TABLE interfaces ADD COLUMN IF NOT EXISTS status_observed_at TEXT")
    cursor.execute(
        "ALTER TABLE interfaces ADD COLUMN IF NOT EXISTS status_observation_source TEXT NOT NULL DEFAULT ''"
    )


def downgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        return
    cursor.execute("ALTER TABLE interfaces DROP COLUMN IF EXISTS status_observation_source")
    cursor.execute("ALTER TABLE interfaces DROP COLUMN IF EXISTS status_observed_at")
