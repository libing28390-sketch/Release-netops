"""Add an auditable timeline for monitoring incidents."""

from __future__ import annotations


VERSION = 62
NAME = "monitoring_incident_timeline"


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monitoring_incident_timeline (
            id TEXT PRIMARY KEY,
            incident_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL DEFAULT '',
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (incident_id) REFERENCES monitoring_incidents(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_monitoring_incident_timeline_incident "
        "ON monitoring_incident_timeline(incident_id, created_at)"
    )
