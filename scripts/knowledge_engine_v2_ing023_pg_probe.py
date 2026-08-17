"""PostgreSQL-only ING-023 migration and alert transaction probe.

The probe intentionally refuses SQLite. All DDL and alert writes run on one
configured PostgreSQL connection and are rolled back before exit.
"""

from __future__ import annotations

import json
import sys

import database
import database.core as database_core
from database.migrations.m0149_knowledge_v2_site_anomaly_alerts import upgrade
from services.official_seed_batch_service import _record_site_alerts, list_site_anomaly_alerts


class _SameConnection:
    """Adapter for service code that commits/closes its own connection."""

    def __init__(self, connection):
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


def main() -> int:
    if not database_core._USE_PG:
        print(json.dumps({"status": "BLOCKED", "reason": "DATABASE_URL is not PostgreSQL"}))
        return 2
    connection = database.get_db_connection()
    original_get_connection = database.get_db_connection
    try:
        upgrade(connection.cursor(), use_pg=True)
        upgrade(connection.cursor(), use_pg=True)
        jsonb_type = connection.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'kb_site_anomaly_alert' AND column_name = 'details_json'"
        ).fetchone()[0]
        if jsonb_type != "jsonb":
            raise AssertionError(f"details_json is {jsonb_type!r}, expected jsonb")

        database.get_db_connection = lambda: _SameConnection(connection)
        user = {"id": "ing023-pg", "username": "ing023-pg", "tenant_id": "tenant-ing023-pg"}
        alert = {
            "host": "www.cisco.com",
            "alert_code": "OUTBOUND_HTTP_5XX",
            "severity": "warning",
            "title": "Official source site anomaly",
            "observed_count": 2,
            "source_ids": ["source-1"],
        }
        _record_site_alerts(user, batch_id="pg-probe-1", alerts=[alert])
        alert["observed_count"] = 1
        _record_site_alerts(user, batch_id="pg-probe-2", alerts=[alert])
        row = connection.execute(
            "SELECT tenant_id, host, alert_code, status, failure_count FROM kb_site_anomaly_alert "
            "WHERE tenant_id = ? AND host = ? AND alert_code = ?",
            ("tenant-ing023-pg", "www.cisco.com", "OUTBOUND_HTTP_5XX"),
        ).fetchone()
        if tuple(row) != ("tenant-ing023-pg", "www.cisco.com", "OUTBOUND_HTTP_5XX", "open", 3):
            raise AssertionError(f"unexpected alert row: {tuple(row)!r}")
        _record_site_alerts(
            {"id": "ing023-pg-other", "username": "ing023-pg-other", "tenant_id": "tenant-ing023-pg-other"},
            batch_id="pg-probe-other",
            alerts=[alert],
        )
        tenant_rows = connection.execute(
            "SELECT COUNT(*) FROM kb_site_anomaly_alert WHERE host = ? AND alert_code = ?",
            ("www.cisco.com", "OUTBOUND_HTTP_5XX"),
        ).fetchone()[0]
        if int(tenant_rows) != 2:
            raise AssertionError(f"tenant isolation key was not respected: {tenant_rows!r}")
        listed = list_site_anomaly_alerts(user, status="open", limit=10)
        if len(listed) != 1 or listed[0]["host"] != "www.cisco.com":
            raise AssertionError(f"tenant-bounded alert read model failed: {listed!r}")
        connection.rollback()
        print(json.dumps({"status": "PASS", "database": "PostgreSQL", "jsonb": True, "tenant_scope": True, "rollback": True}))
        return 0
    finally:
        database.get_db_connection = original_get_connection
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
