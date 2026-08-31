"""Add tenant-scoped operational alerts for official-source collection.

ING-023 must not reuse the legacy ``alert_events`` table: that table predates
Knowledge Engine tenant boundaries and has no tenant key.  This additive
projection stores only stable host/code facts, never URLs, response bodies or
headers.  A row is updated in place so one tenant/host/code has one bounded
open/closed lifecycle and repeated refreshes remain idempotent.
"""

from __future__ import annotations


VERSION = 149
NAME = "knowledge_v2_site_anomaly_alerts"


def _json_type(use_pg: bool) -> tuple[str, str]:
    return "JSONB", "'{}'::jsonb"
    return "TEXT", "'{}'"


def upgrade(cursor, use_pg: bool) -> None:
    json_type, json_default = _json_type(use_pg)
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS kb_site_anomaly_alert (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            host TEXT NOT NULL,
            alert_code TEXT NOT NULL,
            severity TEXT NOT NULL CHECK (severity IN ('warning','major','critical')),
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
            failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            resolved_at TEXT,
            source_ids_json {json_type} NOT NULL DEFAULT {json_default},
            details_json {json_type} NOT NULL DEFAULT {json_default},
            UNIQUE (tenant_id, host, alert_code)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_kb_site_anomaly_alert_tenant_status "
        "ON kb_site_anomaly_alert(tenant_id, status, last_seen_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_kb_site_anomaly_alert_tenant_host "
        "ON kb_site_anomaly_alert(tenant_id, host, last_seen_at DESC)"
    )


def downgrade(cursor, use_pg: bool) -> None:
    # Operational evidence is retained on rollback; removing it would make
    # an incident unauditable.  A future retention migration may archive rows.
    return None

