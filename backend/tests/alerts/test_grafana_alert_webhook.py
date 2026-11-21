from __future__ import annotations

from fastapi.testclient import TestClient

from api import alerts as alerts_api
from database import get_db_connection
from main import app


client = TestClient(app)


class _RecordingConnection:
    def __init__(self, connection):
        self.connection = connection
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql, params=()):
        self.execute_calls.append((sql, tuple(params or ())))
        return self.connection.execute(sql, params)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


def test_grafana_webhook_persists_lifecycle_and_queues_each_notification_once(isolated_db, monkeypatch):
    configured_webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/configured-test-token"
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", configured_webhook)
    fingerprint = "grafana-alert-atomic-test"
    firing_payload = {
        "receiver": "Nexora-Webhook",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "fingerprint": fingerprint,
                "labels": {
                    "alertname": "DeviceHighCPU",
                    "hostname": "SW-CORE-TEST-01",
                    "instance": "192.168.100.1:9161",
                    "severity": "critical",
                },
                "annotations": {
                    "summary": "Core Switch CPU over 90%",
                    "description": "Device SW-CORE-TEST-01 CPU usage reached 92.5%",
                },
                "startsAt": "2026-09-19T03:50:00Z",
                "generatorURL": "http://localhost:3000/grafana/d/01",
            }
        ],
    }

    resp = client.post(
        "/api/alerts/webhook/grafana?feishu_url=https://127.0.0.1/attacker-controlled",
        json=firing_payload,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["received_count"] == 1
    assert data["processed"][0]["status"] == "active"
    assert data["processed"][0]["queued_channels"] == ["workspace", "grafana_feishu"]
    dedupe_key = data["processed"][0]["dedupe_key"]
    alert_id = data["processed"][0]["alert_id"]

    # A repeated firing updates the current projection but does not fan out
    # another notification for the same Grafana fingerprint.
    repeated_payload = {
        **firing_payload,
        "alerts": [
            {
                **firing_payload["alerts"][0],
                "annotations": {
                    "summary": "Core Switch CPU still over 90%",
                    "description": "The same alert remains active",
                },
            }
        ],
    }
    repeated = client.post("/api/alerts/webhook/grafana", json=repeated_payload)
    assert repeated.status_code == 200
    assert repeated.json()["processed"][0]["queued_channels"] == []

    connection = get_db_connection()
    try:
        rows = connection.execute(
            "SELECT id, severity, title, resolved_at FROM alert_events WHERE dedupe_key = ?",
            (dedupe_key,),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["id"] == alert_id
        assert rows[0]["severity"] == "critical"
        assert rows[0]["title"] == "Core Switch CPU still over 90%"
        assert rows[0]["resolved_at"] is None
        active_deliveries = connection.execute(
            "SELECT channel, payload FROM alert_delivery_outbox WHERE delivery_key LIKE ? ORDER BY channel",
            (f"{alert_id}:%:active",),
        ).fetchall()
        assert {row["channel"] for row in active_deliveries} == {"workspace", "grafana_feishu"}
        assert configured_webhook not in str([row["payload"] for row in active_deliveries])
        assert "attacker-controlled" not in str([row["payload"] for row in active_deliveries])
        opened = connection.execute(
            "SELECT COUNT(*) FROM alert_activity WHERE alert_id = ? AND event_type = 'OPENED'",
            (alert_id,),
        ).fetchone()[0]
        assert opened == 1
    finally:
        connection.close()
    resolved_payload = {
        "receiver": "Nexora-Webhook",
        "status": "resolved",
        "alerts": [
            {
                "status": "resolved",
                "fingerprint": fingerprint,
                "labels": {
                    "alertname": "DeviceHighCPU",
                    "hostname": "SW-CORE-TEST-01",
                    "instance": "192.168.100.1:9161",
                    "severity": "critical",
                },
                "annotations": {
                    "summary": "Core Switch CPU over 90%",
                    "description": "Device SW-CORE-TEST-01 CPU usage normalized",
                },
                "startsAt": "2026-09-19T03:50:00Z",
                "endsAt": "2026-09-19T03:55:00Z",
            }
        ],
    }
    resolved = client.post("/api/alerts/webhook/grafana", json=resolved_payload)
    assert resolved.status_code == 200
    assert resolved.json()["processed"][0]["status"] == "resolved"
    assert resolved.json()["processed"][0]["queued_channels"] == ["workspace", "grafana_feishu"]

    connection = get_db_connection()
    try:
        row = connection.execute(
            "SELECT workflow_status, resolved_at FROM alert_events WHERE dedupe_key = ?",
            (dedupe_key,),
        ).fetchone()
        assert row is not None
        assert row["workflow_status"] == "resolved"
        assert row["resolved_at"] is not None
        deliveries = connection.execute(
            "SELECT channel, payload FROM alert_delivery_outbox WHERE delivery_key LIKE ? ORDER BY delivery_key",
            (f"{alert_id}:%",),
        ).fetchall()
        assert len(deliveries) == 4
        assert {row["channel"] for row in deliveries} == {"workspace", "grafana_feishu"}
        resolved_events = connection.execute(
            "SELECT COUNT(*) FROM alert_activity WHERE alert_id = ? AND event_type = 'RESOLVED'",
            (alert_id,),
        ).fetchone()[0]
        assert resolved_events == 1
    finally:
        connection.close()


def test_grafana_webhook_batches_500_and_1000_alerts_with_bounded_sql(isolated_db, monkeypatch):
    monkeypatch.delenv("FEISHU_WEBHOOK_URL", raising=False)
    recording_connections: list[_RecordingConnection] = []
    original_get_connection = alerts_api.get_db_connection

    def tracked_get_connection():
        connection = _RecordingConnection(original_get_connection())
        recording_connections.append(connection)
        return connection

    monkeypatch.setattr(alerts_api, "get_db_connection", tracked_get_connection)
    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "fingerprint": f"storm-test-{index}",
                "labels": {"alertname": "StormTest", "severity": "warning"},
                "annotations": {"summary": f"synthetic alert {index}"},
            }
            for index in range(500)
        ],
    }

    response = client.post("/api/alerts/webhook/grafana", json=payload)

    assert response.status_code == 200
    assert response.json()["received_count"] == 500
    assert len(recording_connections) == 1
    sql_calls = [sql.lower() for sql, _params in recording_connections[0].execute_calls]
    assert sum("where dedupe_key in" in sql for sql in sql_calls) == 1
    assert sum("insert into alert_events" in sql for sql in sql_calls) == 1
    assert sum("insert into alert_delivery_outbox" in sql for sql in sql_calls) == 1
    assert sum("insert into alert_activity" in sql for sql in sql_calls) == 2
    assert not any("from devices" in sql for sql in sql_calls)
    assert len(sql_calls) == 5

    second_response = client.post("/api/alerts/webhook/grafana", json={
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "fingerprint": f"storm-test-second-{index}",
                "labels": {"alertname": "StormTest", "severity": "warning"},
                "annotations": {"summary": f"synthetic alert {index}"},
            }
            for index in range(1000)
        ],
    })

    assert second_response.status_code == 200
    assert second_response.json()["received_count"] == 1000
    assert len(recording_connections) == 2
    second_sql_calls = [sql.lower() for sql, _params in recording_connections[1].execute_calls]
    assert sum("where dedupe_key in" in sql for sql in second_sql_calls) == 2
    assert sum("insert into alert_events" in sql for sql in second_sql_calls) == 2
    assert sum("insert into alert_delivery_outbox" in sql for sql in second_sql_calls) == 2
    assert sum("insert into alert_activity" in sql for sql in second_sql_calls) == 4
    assert not any("from devices" in sql for sql in second_sql_calls)
    assert len(second_sql_calls) == 10

    connection = get_db_connection()
    try:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM alert_events WHERE source = 'grafana_alert'"
        ).fetchone()["count"] == 1500
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM alert_delivery_outbox WHERE channel = 'workspace'"
        ).fetchone()["count"] == 1500
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM alert_activity WHERE event_type = 'OPENED' "
            "AND alert_id IN (SELECT id FROM alert_events WHERE source = 'grafana_alert')"
        ).fetchone()["count"] == 1500
    finally:
        connection.close()


def test_grafana_webhook_preserves_ordered_duplicate_lifecycle_in_one_batch(isolated_db, monkeypatch):
    monkeypatch.delenv("FEISHU_WEBHOOK_URL", raising=False)
    fingerprint = "same-payload-lifecycle"
    base = {
        "fingerprint": fingerprint,
        "labels": {"alertname": "LifecycleTest", "severity": "critical"},
        "annotations": {"summary": "same fingerprint lifecycle"},
        "startsAt": "2026-10-12T08:00:00Z",
    }

    response = client.post("/api/alerts/webhook/grafana", json={
        "alerts": [
            {**base, "status": "firing"},
            {**base, "status": "resolved"},
            {**base, "status": "firing"},
        ],
    })

    assert response.status_code == 200
    processed = response.json()["processed"]
    assert processed[0]["alert_id"] == processed[1]["alert_id"]
    assert processed[2]["alert_id"] != processed[0]["alert_id"]
    dedupe_key = processed[0]["dedupe_key"]
    connection = get_db_connection()
    try:
        events = connection.execute(
            "SELECT id, resolved_at, workflow_status FROM alert_events WHERE dedupe_key = ?",
            (dedupe_key,),
        ).fetchall()
        assert len(events) == 2
        assert sum(row["resolved_at"] is not None for row in events) == 1
        assert sum(row["resolved_at"] is None for row in events) == 1
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM alert_activity WHERE alert_id IN (?, ?) "
            "AND event_type IN ('OPENED', 'RESOLVED')",
            (processed[0]["alert_id"], processed[2]["alert_id"]),
        ).fetchone()["count"] == 3
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM alert_delivery_outbox WHERE alert_id IN (?, ?)",
            (processed[0]["alert_id"], processed[2]["alert_id"]),
        ).fetchone()["count"] == 3
    finally:
        connection.close()
