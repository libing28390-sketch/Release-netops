import sqlite3

from database.migrations.m0061_monitoring_incidents import upgrade
from database.migrations.m0062_monitoring_incident_timeline import upgrade as upgrade_timeline
from services.monitoring_incident_service import (
    get_incident_impact,
    get_incident,
    incident_group_key,
    list_incidents,
    recommend_incident_playbooks,
    sync_incidents,
    update_incident_status,
)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE devices (
            id TEXT PRIMARY KEY,
            hostname TEXT,
            ip_address TEXT,
            site TEXT,
            site_id TEXT,
            platform TEXT,
            vendor TEXT
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
    upgrade(conn, use_pg=False)
    upgrade_timeline(conn, use_pg=False)
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
    conn.execute("INSERT INTO devices VALUES (?, ?, ?, ?, ?, ?, ?)", ("d-1", "edge-1", "192.0.2.1", "site-wh", "site-wh", "cisco_ios", "Cisco"))
    return conn


def test_connectivity_alerts_from_one_device_share_an_incident_group() -> None:
    assert incident_group_key({"device_id": "d-1", "dedupe_key": "snmp_unreachable:d-1"}) == "device:d-1:reachability"
    assert incident_group_key({"device_id": "d-1", "dedupe_key": "interface_down:d-1:Gi1/0/1"}) != "device:d-1:reachability"


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
        page = list_incidents(conn, status="active", page=1, page_size=20)
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
        incident = list_incidents(conn, status="active")["items"][0]
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
        conn.execute("INSERT INTO devices VALUES (?, ?, ?, ?, ?, ?, ?)", ("d-2", "core-2", "192.0.2.2", "site-wh", "site-wh", "cisco_ios", "Cisco"))
        conn.execute(
            "INSERT INTO topology_links VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("link-1", "d-1", "d-2", "edge-1", "core-2", "Gi1/0/1", "Gi1/0/1", "up", 0.98, "lldp", "2026-08-01T01:00:00+00:00"),
        )
        incident = list_incidents(conn, status="active")["items"][0]
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
        incident = list_incidents(conn, status="active")["items"][0]
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
