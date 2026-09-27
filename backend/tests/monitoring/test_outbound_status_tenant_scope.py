from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from api import monitoring
from database import get_db_connection
from services import outbound_probe_service


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def test_outbound_status_only_returns_authenticated_tenant_targets_and_samples(isolated_db):
    tenant_a = _id("tenant-outbound-a")
    tenant_b = _id("tenant-outbound-b")
    target_a = _id("outbound-target-a")
    target_b = _id("outbound-target-b")
    run_id = _id("outbound-run")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    checked_at = (now + timedelta(seconds=1)).isoformat()
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO tenants (id, name) VALUES (?, ?)", (tenant_a, tenant_a))
        conn.execute("INSERT INTO tenants (id, name) VALUES (?, ?)", (tenant_b, tenant_b))
        node = conn.execute(
            "SELECT id FROM outbound_probe_nodes WHERE node_name = 'platform-server' AND enabled IS TRUE LIMIT 1"
        ).fetchone()
        assert node is not None
        node_id = node['id']
        conn.execute(
            """
            INSERT INTO outbound_probe_targets (
                id, target_name, host, port, probe_type, is_active, created_at,
                group_name, url, expected_status_code, expected_keyword, timeout_ms,
                enabled, updated_at, tenant_id
            ) VALUES (?, ?, ?, 443, 'HTTPS_GET', TRUE, ?, 'business', '', 200, '', 2000, TRUE, ?, ?)
            """,
            (target_a, _id("tenant-a-target"), checked_at, checked_at, tenant_a),
        )
        conn.execute(
            """
            INSERT INTO outbound_probe_targets (
                id, target_name, host, port, probe_type, is_active, created_at,
                group_name, url, expected_status_code, expected_keyword, timeout_ms,
                enabled, updated_at, tenant_id
            ) VALUES (?, ?, ?, 443, 'HTTPS_GET', TRUE, ?, 'business', '', 200, '', 2000, TRUE, ?, ?)
            """,
            (target_b, _id("tenant-b-target"), checked_at, checked_at, tenant_b),
        )
        conn.execute(
            """
            INSERT INTO outbound_probe_runs (
                id, node_id, started_at, finished_at, status, raw_status, status_reason,
                success_count, total_targets, availability_percent, average_latency_ms,
                public_ip, public_ip_changed, consecutive_failure_count,
                consecutive_recovery_count, group_status_json, created_at
            ) VALUES (?, ?, ?, ?, 'degraded', 'degraded', 'foreign tenant target failed',
                      1, 2, 50, 42, '203.0.113.20', FALSE, 1, 0, '{"business":{}}', ?)
            """,
            (run_id, node_id, now.isoformat(), checked_at, checked_at),
        )
        conn.execute(
            """
            INSERT INTO outbound_probe_results (
                id, run_id, target_id, target_name, group_name, probe_type, sampled_at,
                success, latency_ms, packet_loss_percent, rtt_jitter_ms, error_type,
                error_message, resolved_ip, http_status, dns_answers_json
            ) VALUES (?, ?, ?, 'Tenant A service', 'business', 'HTTPS_GET', ?, TRUE, 42, NULL, NULL, NULL, NULL, '192.0.2.10', 200, '[]')
            """,
            (_id("outbound-result-a"), run_id, target_a, checked_at),
        )
        conn.execute(
            """
            INSERT INTO outbound_probe_results (
                id, run_id, target_id, target_name, group_name, probe_type, sampled_at,
                success, latency_ms, packet_loss_percent, rtt_jitter_ms, error_type,
                error_message, resolved_ip, http_status, dns_answers_json
            ) VALUES (?, ?, ?, 'Tenant B service', 'business', 'HTTPS_GET', ?, FALSE, NULL, NULL, NULL, 'CONNECT_TIMEOUT', 'private endpoint failed', '192.0.2.11', NULL, '[]')
            """,
            (_id("outbound-result-b"), run_id, target_b, checked_at),
        )
        conn.commit()
    finally:
        conn.close()

    response = outbound_probe_service.get_outbound_status(history_hours=24, tenant_id=tenant_a)

    assert [item['id'] for item in response['targets']] == [target_a]
    assert response['current'] is not None
    assert response['current']['targets'][0]['target_id'] == target_a
    assert response['current']['status'] == outbound_probe_service.STATUS_HEALTHY
    assert response['current']['success_count'] == 1
    assert response['current']['total_count'] == 1
    assert response['current']['groups']['business']['total_count'] == 1
    assert response['current']['public_ip'] == ''
    assert response['current']['egress_ip'] is None
    assert all(point['total_targets'] == 1 for point in response['history'])


def test_outbound_status_route_passes_the_authenticated_tenant(monkeypatch):
    captured = {}

    def fake_get_outbound_status(*, history_hours, tenant_id):
        captured.update(history_hours=history_hours, tenant_id=tenant_id)
        return {"current": None, "history": [], "targets": []}

    monkeypatch.setattr(outbound_probe_service, "get_outbound_status", fake_get_outbound_status)
    user = {"role": "Viewer", "tenant_id": "tenant-route-a"}

    response = monitoring.get_monitoring_outbound_status(history_hours=12, user=user)

    assert response == {"current": None, "history": [], "targets": []}
    assert captured == {"history_hours": 12, "tenant_id": "tenant-route-a"}
