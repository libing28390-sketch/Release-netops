from datetime import datetime, timedelta, timezone

import pytest

from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations.m0061_monitoring_incidents import upgrade
from database.migrations.m0062_monitoring_incident_timeline import upgrade as upgrade_timeline
from services import monitoring_incident_service
from services.monitoring_incident_service import (
    get_incident_impact,
    get_incident,
    incident_group_key,
    list_incidents,
    recommend_incident_playbooks,
    run_scheduled_incident_projection_sync,
    sync_incidents,
    update_incident_status,
    assign_incident,
)


def _connection() -> postgresql_test_driver.Connection:
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
    conn.execute(
        """
        CREATE TABLE devices (
            id TEXT PRIMARY KEY,
            hostname TEXT,
            ip_address TEXT,
            site TEXT,
            site_id TEXT,
            platform TEXT,
            vendor TEXT,
            role TEXT,
            tenant_id TEXT DEFAULT 'tenant-default'
        )
        """
    )
    conn.execute("CREATE TABLE sites (id TEXT PRIMARY KEY, site_name TEXT NOT NULL)")
    conn.execute(
        """
        CREATE TABLE alert_events (
            id TEXT PRIMARY KEY,
            dedupe_key TEXT NOT NULL,
            source TEXT NOT NULL,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            device_id TEXT,
            interface_name TEXT,
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            workflow_status TEXT NOT NULL DEFAULT 'open',
            assignee TEXT,
            ack_by TEXT,
            ack_at TEXT,
            note TEXT DEFAULT '',
            updated_at TEXT
        )
        """
    )
    upgrade(conn, use_pg=True)
    upgrade_timeline(conn, use_pg=True)
    conn.execute(
        """
        CREATE TABLE topology_links (
            id TEXT PRIMARY KEY,
            source_device_id TEXT,
            target_device_id TEXT,
            source_hostname TEXT,
            target_hostname TEXT,
            source_port TEXT,
            target_port TEXT,
            status TEXT,
            confidence REAL,
            discovery_source TEXT,
            updated_at TEXT
        )
        """
    )
    conn.execute("INSERT INTO sites VALUES (?, ?)", ("site-wh", "华北数据中心"))
    conn.execute(
        "INSERT INTO devices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("d-1", "edge-1", "192.0.2.1", "site-wh", "site-wh", "cisco_ios", "Cisco", "access", "tenant-default"),
    )
    return conn


def test_connectivity_alerts_from_one_device_share_an_incident_group() -> None:
    assert incident_group_key({"device_id": "d-1", "dedupe_key": "snmp_unreachable:d-1"}) == "device:d-1:reachability"
    assert incident_group_key({"device_id": "d-1", "dedupe_key": "interface_down:d-1:Gi1/0/1"}) != "device:d-1:reachability"


def test_incident_reads_are_read_only_by_default(monkeypatch) -> None:
    conn = _connection()
    try:
        def fail_sync(*_args, **_kwargs):
            raise AssertionError("GET path attempted to synchronize the incident projection")

        monkeypatch.setattr(monitoring_incident_service, "sync_incidents", fail_sync)
        assert list_incidents(conn)["total"] == 0
        assert get_incident(conn, "missing-incident") is None
        assert get_incident_impact(conn, "missing-incident") is None
    finally:
        conn.close()


def test_scheduled_sync_preserves_operator_state_and_tenant_scope(monkeypatch) -> None:
    conn = _connection()
    try:
        conn.execute(
            "INSERT INTO devices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("d-2", "edge-2", "192.0.2.2", "site-wh", "site-wh", "cisco_ios", "Cisco", "access", "tenant-b"),
        )
        conn.execute(
            """
            INSERT INTO alert_events
                (id, dedupe_key, source, severity, title, message, device_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("a-tenant-a-1", "ping_unreachable:d-1", "network_monitor", "major", "Ping failed", "Ping timeout", "d-1", "2026-08-01T01:00:00+00:00"),
        )
        sync_incidents(conn, return_incidents=False)
        incident = list_incidents(conn, tenant_id="tenant-default")["items"][0]
        update_incident_status(conn, incident["id"], "acknowledged", "operator-a")
        assign_incident(conn, incident["id"], "operator-a")

        conn.execute(
            """
            INSERT INTO alert_events
                (id, dedupe_key, source, severity, title, message, device_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("a-tenant-a-2", "snmp_unreachable:d-1", "network_monitor", "critical", "SNMP failed", "No SNMP response", "d-1", "2026-08-01T01:01:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO alert_events
                (id, dedupe_key, source, severity, title, message, device_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("a-tenant-b-1", "ping_unreachable:d-2", "network_monitor", "warning", "Ping failed", "Ping timeout", "d-2", "2026-08-01T01:00:00+00:00"),
        )

        class BorrowedConnection:
            def __getattr__(self, name):
                return getattr(conn, name)

            def close(self):
                return None

        monkeypatch.setattr(monitoring_incident_service, "get_db_connection", BorrowedConnection)
        run_scheduled_incident_projection_sync()

        tenant_a = list_incidents(conn, tenant_id="tenant-default")
        tenant_b = list_incidents(conn, tenant_id="tenant-b")
        assert tenant_a["total"] == 1
        assert tenant_b["total"] == 1
        refreshed = tenant_a["items"][0]
        assert refreshed["id"] == incident["id"]
        assert refreshed["status"] == "acknowledged"
        assert refreshed["assigned_to"] == "operator-a"
        assert refreshed["impact_alert_count"] == 2
        assert tenant_b["items"][0]["primary_device_id"] == "d-2"
    finally:
        conn.close()


def test_sync_incidents_links_related_alerts_and_preserves_timeline() -> None:
    conn = _connection()
    try:
        conn.executemany(
            """
            INSERT INTO alert_events
                (id, dedupe_key, source, severity, title, message, device_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("a-1", "ping_unreachable:d-1", "network_monitor", "major", "Ping failed", "Ping timeout", "d-1", "2026-08-01T01:00:00+00:00"),
                ("a-2", "snmp_unreachable:d-1", "network_monitor", "critical", "SNMP failed", "No SNMP response", "d-1", "2026-08-01T01:01:00+00:00"),
                ("a-3", "interface_down:d-1:Gi1/0/1", "network_monitor", "warning", "Interface down", "Gi1/0/1 down", "d-1", "2026-08-01T01:02:00+00:00"),
            ],
        )
        page = list_incidents(conn, status="active", page=1, page_size=20, sync=True)
        assert page["total"] == 2
        reachability = next(item for item in page["items"] if item["impact_alert_count"] == 2)
        assert reachability["severity"] == "critical"

        detail = get_incident(conn, reachability["id"], sync=False)
        assert detail is not None
        assert len(detail["alerts"]) == 2
        assert len(detail["timeline"]) == 3
        assert detail["site"] == "华北数据中心"
        assert detail["timeline"][0]["event_type"] == "incident_opened"
    finally:
        conn.close()


def test_sync_incidents_bulk_noop_is_stable_and_root_recovers_after_alert_resolution() -> None:
    conn = _connection()
    try:
        first_seen = datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc)
        alerts = [
            (
                f"a-{index:03d}",
                f"probe_failed:d-1:{index}",
                "network_monitor",
                "warning",
                f"Probe offline {index}",
                "Connectivity probe failed",
                "d-1",
                (first_seen + timedelta(seconds=index)).isoformat(),
            )
            for index in range(520)
        ]
        conn.executemany(
            """
            INSERT INTO alert_events
                (id, dedupe_key, source, severity, title, message, device_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            alerts,
        )

        executed_statements: list[tuple[str, tuple[object, ...]]] = []
        original_execute = conn.execute

        def record_execute(statement: str, parameters=None):
            executed_statements.append((statement, tuple(parameters or ())))
            return original_execute(statement, parameters)

        conn.execute = record_execute

        assert sync_incidents(conn, return_incidents=False) is None
        association_batches = [
            parameters
            for statement, parameters in executed_statements
            if "INSERT INTO monitoring_incident_alerts" in statement
        ]
        assert sorted(len(parameters) // 4 for parameters in association_batches) == [20, 500]
        assert all(len(parameters) % 4 == 0 for parameters in association_batches)
        opened_events = conn.execute(
            "SELECT COUNT(*) FROM monitoring_incident_timeline WHERE event_type = 'incident_opened'"
        ).fetchone()[0]
        assert opened_events == 1

        incident = conn.execute(
            "SELECT id, root_cause_alert_id, updated_at, xmin::text AS tuple_version "
            "FROM monitoring_incidents"
        ).fetchone()
        assert incident["root_cause_alert_id"] == "a-000"
        stable_incident_state = (incident["updated_at"], incident["tuple_version"])
        stable_link_state = [
            (row["alert_id"], row["is_root"], row["tuple_version"])
            for row in conn.execute(
                "SELECT alert_id, is_root, xmin::text AS tuple_version "
                "FROM monitoring_incident_alerts WHERE incident_id = ? ORDER BY alert_id",
                (incident["id"],),
            ).fetchall()
        ]
        assert len(stable_link_state) == 520
        assert sum(row[1] for row in stable_link_state) == 1

        list_query_count = sum("COUNT(ia.alert_id)" in statement for statement, _ in executed_statements)
        page = list_incidents(conn, status="active", page_size=100)
        assert page["total"] == 1
        assert sum("COUNT(ia.alert_id)" in statement for statement, _ in executed_statements) == list_query_count + 1
        list_query_count = sum("COUNT(ia.alert_id)" in statement for statement, _ in executed_statements)
        detail = get_incident(conn, incident["id"])
        assert detail is not None
        assert len(detail["alerts"]) == 520
        assert sum("COUNT(ia.alert_id)" in statement for statement, _ in executed_statements) == list_query_count

        unchanged_incident = conn.execute(
            "SELECT updated_at, xmin::text AS tuple_version FROM monitoring_incidents WHERE id = ?",
            (incident["id"],),
        ).fetchone()
        unchanged_link_state = [
            (row["alert_id"], row["is_root"], row["tuple_version"])
            for row in conn.execute(
                "SELECT alert_id, is_root, xmin::text AS tuple_version "
                "FROM monitoring_incident_alerts WHERE incident_id = ? ORDER BY alert_id",
                (incident["id"],),
            ).fetchall()
        ]
        assert (unchanged_incident["updated_at"], unchanged_incident["tuple_version"]) == stable_incident_state
        assert unchanged_link_state == stable_link_state

        critical_alert_id = "a-critical"
        conn.execute(
            """
            INSERT INTO alert_events
                (id, dedupe_key, source, severity, title, message, device_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                critical_alert_id,
                "probe_failed:d-1:critical",
                "network_monitor",
                "critical",
                "Critical probe offline",
                "Connectivity probe failed",
                "d-1",
                (first_seen + timedelta(seconds=30)).isoformat(),
            ),
        )
        sync_incidents(conn, return_incidents=False)
        changed_incident = conn.execute(
            "SELECT root_cause_alert_id, xmin::text AS tuple_version "
            "FROM monitoring_incidents WHERE id = ?",
            (incident["id"],),
        ).fetchone()
        assert changed_incident["root_cause_alert_id"] == critical_alert_id
        assert changed_incident["tuple_version"] != stable_incident_state[1]
        root_flags = {
            row["alert_id"]: row["is_root"]
            for row in conn.execute(
                "SELECT alert_id, is_root FROM monitoring_incident_alerts WHERE incident_id = ? "
                "AND alert_id IN (?, ?) ORDER BY alert_id",
                (incident["id"], "a-000", critical_alert_id),
            ).fetchall()
        }
        assert root_flags == {"a-000": 0, critical_alert_id: 1}

        resolved_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE alert_events SET resolved_at = ?, updated_at = ? WHERE id = ?",
            (resolved_at, resolved_at, critical_alert_id),
        )
        sync_incidents(conn, return_incidents=False)
        recovered_incident = conn.execute(
            "SELECT root_cause_alert_id, severity FROM monitoring_incidents WHERE id = ?",
            (incident["id"],),
        ).fetchone()
        assert recovered_incident["root_cause_alert_id"] == "a-000"
        assert recovered_incident["severity"] == "warning"
        recovered_root_flags = {
            row["alert_id"]: row["is_root"]
            for row in conn.execute(
                "SELECT alert_id, is_root FROM monitoring_incident_alerts WHERE incident_id = ? "
                "AND alert_id IN (?, ?) ORDER BY alert_id",
                (incident["id"], "a-000", critical_alert_id),
            ).fetchall()
        }
        assert recovered_root_flags == {"a-000": 1, critical_alert_id: 0}
    finally:
        conn.close()


@pytest.mark.parametrize("group_count", [500, 1000, 5000])
def test_sync_incidents_batches_unique_group_projection_and_open_timeline(group_count: int) -> None:
    conn = _connection()
    try:
        first_seen = datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc)
        conn.executemany(
            """
            INSERT INTO alert_events
                (id, dedupe_key, source, severity, title, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    f"batch-alert-{index:05d}",
                    f"metric-alert:{index:05d}",
                    "network_monitor",
                    "warning",
                    f"Metric alert {index}",
                    "Synthetic isolated integration fixture",
                    (first_seen + timedelta(seconds=index)).isoformat(),
                )
                for index in range(group_count)
            ],
        )

        executed_statements: list[tuple[str, tuple[object, ...]]] = []
        original_execute = conn.execute

        def record_execute(statement: str, parameters=None):
            executed_statements.append((statement, tuple(parameters or ())))
            return original_execute(statement, parameters)

        conn.execute = record_execute
        expected_batches = (group_count + 499) // 500

        assert sync_incidents(conn, return_incidents=False) is None
        upsert_batches = [
            parameters
            for statement, parameters in executed_statements
            if "INSERT INTO monitoring_incidents" in statement
        ]
        timeline_batches = [
            parameters
            for statement, parameters in executed_statements
            if "INSERT INTO monitoring_incident_timeline" in statement
        ]
        assert len(upsert_batches) == expected_batches
        assert sorted(len(parameters) // 14 for parameters in upsert_batches) == sorted(
            [500] * (group_count // 500)
            + ([group_count % 500] if group_count % 500 else [])
        )
        assert len(timeline_batches) == expected_batches
        assert sorted(len(parameters) // 7 for parameters in timeline_batches) == sorted(
            [500] * (group_count // 500)
            + ([group_count % 500] if group_count % 500 else [])
        )
        assert conn.execute("SELECT COUNT(*) FROM monitoring_incidents").fetchone()[0] == group_count
        assert conn.execute(
            "SELECT COUNT(*) FROM monitoring_incident_timeline WHERE event_type = 'incident_opened'"
        ).fetchone()[0] == group_count

        assert sync_incidents(conn, return_incidents=False) is None
        assert sum(
            "INSERT INTO monitoring_incident_timeline" in statement
            for statement, _parameters in executed_statements
        ) == expected_batches
        assert conn.execute(
            "SELECT COUNT(*) FROM monitoring_incident_timeline WHERE event_type = 'incident_opened'"
        ).fetchone()[0] == group_count
    finally:
        conn.close()


def test_resolving_incident_resolves_only_its_related_alerts() -> None:
    conn = _connection()
    try:
        conn.execute(
            """
            INSERT INTO alert_events
                (id, dedupe_key, source, severity, title, message, device_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("a-1", "ping_unreachable:d-1", "network_monitor", "critical", "Device offline", "offline", "d-1", "2026-08-01T01:00:00+00:00"),
        )
        incident = list_incidents(conn, status="active", sync=True)["items"][0]
        updated = update_incident_status(conn, incident["id"], "resolved", "operator")
        assert updated is not None
        assert updated["status"] == "resolved"
        alert = conn.execute("SELECT resolved_at, workflow_status FROM alert_events WHERE id = 'a-1'").fetchone()
        assert alert["resolved_at"]
        assert alert["workflow_status"] == "resolved"
        assert list_incidents(conn, status="active")["total"] == 0
        timeline = conn.execute("SELECT event_type, actor FROM monitoring_incident_timeline ORDER BY created_at").fetchall()
        assert [row[0] for row in timeline][-1] == "incident_resolved"
    finally:
        conn.close()


def test_incident_impact_uses_topology_links_for_affected_devices() -> None:
    conn = _connection()
    try:
        conn.execute(
            """
            INSERT INTO alert_events
                (id, dedupe_key, source, severity, title, message, device_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("a-1", "ping_unreachable:d-1", "network_monitor", "critical", "Device offline", "offline", "d-1", "2026-08-01T01:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO devices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("d-2", "core-2", "192.0.2.2", "site-wh", "site-wh", "cisco_ios", "Cisco", "core", "tenant-default"),
        )
        conn.execute(
            "INSERT INTO topology_links VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("link-1", "d-1", "d-2", "edge-1", "core-2", "Gi1/0/1", "Gi1/0/1", "up", 0.98, "lldp", "2026-08-01T01:00:00+00:00"),
        )
        incident = list_incidents(conn, status="active", sync=True)["items"][0]
        impact = get_incident_impact(conn, incident["id"], sync=False)
        assert impact is not None
        assert impact["summary"]["affected_devices"] == 1
        assert impact["summary"]["topology_nodes"] == 2
        assert impact["summary"]["related_links"] == 1
        assert {node["impact_scope"] for node in impact["nodes"]} == {"affected", "neighbor"}
    finally:
        conn.close()


def test_playbook_recommendations_are_platform_bound_and_read_only(monkeypatch) -> None:
    conn = _connection()
    try:
        conn.execute(
            """
            INSERT INTO alert_events
                (id, dedupe_key, source, severity, title, message, device_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("a-1", "snmp_unreachable:d-1", "network_monitor", "critical", "SNMP failed", "No SNMP response", "d-1", "2026-08-01T01:00:00+00:00"),
        )
        incident = list_incidents(conn, status="active", sync=True)["items"][0]
        import api.playbooks.scenarios as scenario_module
        monkeypatch.setattr(
            scenario_module,
            "_all_scenarios",
            lambda: [{
                "id": "safe-check",
                "name": "Safe check",
                "name_zh": "安全检查",
                "risk": "low",
                "platform_phases": {"cisco_ios": {"pre_check": ["show version"], "execute": [], "post_check": [], "rollback": []}},
            }],
        )
        result = recommend_incident_playbooks(conn, incident["id"])
        assert result is not None
        assert result["device"]["platform"] == "cisco_ios"
        assert result["items"][0]["scenario_id"] == "safe-check"
        assert result["items"][0]["read_only"] is True
        assert result["items"][0]["execution_allowed"] is False
        assert result["policy"]["automatic_execution"] is False
    finally:
        conn.close()
