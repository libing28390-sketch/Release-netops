from __future__ import annotations

from fastapi.testclient import TestClient

from database import get_db_connection
from main import app


client = TestClient(app)


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
