from __future__ import annotations

import json

from services import background_monitor_service, outbound_probe_service


def test_sync_lldp_neighbor_alerts_passes_source_tenant_to_rule_resolution(monkeypatch):
    captured = {}
    links = [
        {
            "id": "link-1",
            "link_key": "edge-core",
            "source_device_id": "edge-1",
            "source_hostname": "edge-1",
            "source_port": "Gi1/0/1",
            "target_device_id": "core-1",
            "target_hostname": "core-1",
            "target_port": "Gi1/0/1",
            "source_status": "online",
            "target_status": "online",
            "status": "stale",
            "source_tenant_id": "tenant-acme",
        },
    ]

    def fake_db_quick(sql, params=(), fetch=False, fetchall=False):
        captured["sql"] = sql
        assert fetchall is True
        return links

    def fake_resolve(metric_type, *, device_row=None, ip_address="", interface_name=None):
        captured["resolve"] = (metric_type, device_row, ip_address, interface_name)
        return {"severity": "critical"}

    monkeypatch.setattr(background_monitor_service, "_db_quick", fake_db_quick)
    monkeypatch.setattr(background_monitor_service, "resolve_alert_rule", fake_resolve)
    monkeypatch.setattr(background_monitor_service, "set_alert_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(background_monitor_service, "open_alerts", {})

    background_monitor_service.sync_lldp_neighbor_alerts()

    assert "s.tenant_id AS source_tenant_id" in captured["sql"]
    metric_type, device_row, ip_address, interface_name = captured["resolve"]
    assert metric_type == "lldp_neighbor_lost"
    assert device_row["tenant_id"] == "tenant-acme"
    assert device_row["id"] == "edge-1"
    assert ip_address == ""
    assert interface_name == "Gi1/0/1->Gi1/0/1"


class _HistoryCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._row


class _HistoryConnection:
    def __init__(self, target_row, result_rows):
        self.target_row = target_row
        self.result_rows = result_rows
        self.queries = []

    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        if "FROM outbound_probe_targets" in sql:
            return _HistoryCursor(self.target_row)
        if "FROM outbound_probe_results" in sql:
            return _HistoryCursor(self.result_rows)
        raise AssertionError(f"unexpected query: {sql}")

    def close(self):
        pass


def test_outbound_target_history_projects_icmp_quality_values(monkeypatch):
    target_row = {
        "id": "target-1",
        "target_name": "public probe",
        "host": "203.0.113.8",
        "port": 443,
        "probe_type": "ICMP_PING",
        "group_name": "business",
        "url": None,
        "expected_status_code": None,
        "expected_keyword": None,
        "timeout_ms": 2000,
        "enabled": 1,
        "is_active": 1,
        "created_at": "2026-09-27T00:00:00Z",
        "updated_at": "2026-09-27T00:00:00Z",
    }
    result_row = {
        "id": "result-1",
        "run_id": "run-1",
        "target_id": "target-1",
        "target_name": "public probe",
        "group_name": "business",
        "probe_type": "ICMP_PING",
        "sampled_at": "2026-09-27T01:00:00Z",
        "success": 1,
        "latency_ms": 11,
        "packet_loss_percent": 20,
        "rtt_jitter_ms": 2.5,
        "error_type": None,
        "error_message": None,
        "resolved_ip": "203.0.113.8",
        "http_status": None,
        "dns_answers_json": json.dumps([]),
        "run_status": "completed",
        "public_ip": "198.51.100.10",
    }
    connection = _HistoryConnection(target_row, [result_row])
    monkeypatch.setattr(outbound_probe_service, "get_db_connection", lambda: connection)

    history = outbound_probe_service.get_outbound_target_history(
        target_id="target-1",
        start_time="2026-09-27T00:00:00+00:00",
        end_time="2026-09-27T02:00:00+00:00",
    )

    assert history is not None
    assert "result.packet_loss_percent" in connection.queries[1][0]
    assert "result.rtt_jitter_ms" in connection.queries[1][0]
    sample = history["history"][0]
    assert sample["packet_loss_percent"] == 20.0
    assert sample["rtt_jitter_ms"] == 2.5
    assert history["latest"]["packet_loss_percent"] == 20.0
    assert history["latest"]["rtt_jitter_ms"] == 2.5

    recent_history = outbound_probe_service.get_outbound_target_history(
        target_id="target-1",
        history_hours=1,
    )
    assert recent_history is not None
    assert "result.packet_loss_percent" in connection.queries[3][0]
    assert "result.rtt_jitter_ms" in connection.queries[3][0]
