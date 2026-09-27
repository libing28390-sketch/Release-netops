from __future__ import annotations

import uuid
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app
from database import get_db_connection

client = TestClient(app)


def test_receive_grafana_alert_webhook_firing_and_resolved(monkeypatch):
    configured_webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/configured-test-token"
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", configured_webhook)
    firing_payload = {
        "receiver": "Nexora-Webhook",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
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
        "commonLabels": {
            "alertname": "DeviceHighCPU",
            "severity": "critical",
        },
    }

    with patch("api.alerts.send_feishu", return_value=(True, "ok")) as mock_feishu, \
         patch("api.alerts.dispatch_to_all_users", return_value=[{"platform": "feishu", "success": True}]) as mock_dispatch:
        
        resp = client.post(
            "/api/alerts/webhook/grafana?feishu_url=https://127.0.0.1/attacker-controlled",
            json=firing_payload,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["received_count"] == 1
        assert data["processed"][0]["status"] == "active"
        assert mock_feishu.called
        assert mock_feishu.call_args.args[0] == configured_webhook

        # Verify insertion into alert_events table
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM alert_events WHERE dedupe_key LIKE 'grafana:DeviceHighCPU:%' AND resolved_at IS NULL",
            ).fetchone()
            assert row is not None
            assert row["severity"] == "critical"
            assert row["title"] == "Core Switch CPU over 90%"
        finally:
            conn.close()

    # Now test resolved status
    resolved_payload = {
        "receiver": "Nexora-Webhook",
        "status": "resolved",
        "alerts": [
            {
                "status": "resolved",
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

    with patch("api.alerts.send_feishu", return_value=(True, "ok")), \
         patch("api.alerts.dispatch_to_all_users", return_value=[]):
        resp2 = client.post("/api/alerts/webhook/grafana", json=resolved_payload)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["status"] == "ok"
        assert data2["processed"][0]["status"] == "resolved"

        # Verify alert_events has been marked resolved
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM alert_events WHERE dedupe_key LIKE 'grafana:DeviceHighCPU:%' AND resolved_at IS NOT NULL",
            ).fetchone()
            assert row is not None
            assert row["workflow_status"] == "resolved"
        finally:
            conn.close()
