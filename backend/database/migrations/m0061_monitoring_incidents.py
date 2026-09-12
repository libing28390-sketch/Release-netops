"""Create the first durable monitoring Incident read model.

Incidents relate multiple active alert events while preserving the original
alert rows as the audit-friendly source timeline.  The migration is additive
and uses only SQL understood by the project's PostgreSQL adapter and SQLite
compatibility path.
"""

from __future__ import annotations


VERSION = 61
NAME = "monitoring_incidents"


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monitoring_incidents (
            id TEXT PRIMARY KEY,
            incident_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            severity TEXT NOT NULL DEFAULT 'warning',
            status TEXT NOT NULL DEFAULT 'open',
            source TEXT NOT NULL DEFAULT 'alert_events',
            root_cause_alert_id TEXT,
            primary_device_id TEXT,
            site TEXT DEFAULT '',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            impact_device_count INTEGER NOT NULL DEFAULT 0,
            impact_alert_count INTEGER NOT NULL DEFAULT 0,
            acknowledged_by TEXT,
            acknowledged_at TEXT,
            assigned_to TEXT,
            resolved_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS monitoring_incident_alerts (
            incident_id TEXT NOT NULL,
            alert_id TEXT NOT NULL,
            linked_at TEXT NOT NULL,
            is_root INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (incident_id, alert_id),
            FOREIGN KEY (incident_id) REFERENCES monitoring_incidents(id) ON DELETE CASCADE,
            FOREIGN KEY (alert_id) REFERENCES alert_events(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_incidents_status ON monitoring_incidents(status, updated_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_incidents_site ON monitoring_incidents(site, status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_incident_alerts_alert ON monitoring_incident_alerts(alert_id)")
