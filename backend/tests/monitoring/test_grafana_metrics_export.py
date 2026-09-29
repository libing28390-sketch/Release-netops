from datetime import datetime, timedelta, timezone

import database
from api import grafana_metrics
from services.snmp_hardware_inventory_service import upsert_discovery_run


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _MetricsConnection:
    def __init__(self, *, outbound_available=True):
        self.outbound_available = outbound_available
        self.closed = False

    def execute(self, sql, params=()):
        if sql.strip() == "SELECT 1":
            return _Result([(1,)])
        if "FROM outbound_probe_samples" in sql:
            if not self.outbound_available:
                raise RuntimeError("table missing")
            return _Result([{
                "sample_count": 10,
                "success_count": 9,
                "avg_latency_ms": 18.5,
                "max_latency_ms": 40.0,
            }])
        if "FROM outbound_probe_results" in sql:
            return _Result([{
                "probe_type": "ICMP_PING",
                "sample_count": 2,
                "success_count": 1,
                "timeout_count": 1,
                "latency_avg_ms": 5.0,
                "latency_max_ms": 5.0,
                "packet_loss_percent_avg": 20.0,
                "rtt_jitter_avg_ms": 1.5,
            }])
        if "FROM wan_link_current_status" in sql:
            return _Result([{"status": "healthy", "link_count": 2}])
        if "FROM wan_link_samples_1m" in sql:
            return _Result([{
                "sample_count": 60,
                "collected_count": 59,
                "admin_up_count": 59,
                "oper_up_count": 58,
                "avg_download_bps": 1000,
                "avg_upload_bps": 500,
                "errors_total": 1,
                "discards_total": 2,
            }])
        if "SUM(duplicate_count - 1)" in sql:
            return _Result([(1,)])
        if "SELECT created_at\n              FROM alert_events" in sql:
            return _Result([{"created_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()}])
        if "SELECT created_at, ack_at" in sql:
            now = datetime.now(timezone.utc)
            return _Result([{
                "created_at": (now - timedelta(seconds=60)).isoformat(),
                "ack_at": (now - timedelta(seconds=20)).isoformat(),
            }])
        if "SELECT created_at, resolved_at" in sql:
            now = datetime.now(timezone.utc)
            return _Result([{
                "created_at": (now - timedelta(seconds=300)).isoformat(),
                "resolved_at": (now - timedelta(seconds=100)).isoformat(),
            }])
        if "FROM alert_events" in sql and "GROUP BY 1" in sql:
            return _Result([
                {"severity": "critical", "event_count": 2},
                {"severity": "major", "event_count": 1},
            ])
        if "COUNT(*) FROM alert_events" in sql:
            return _Result([(3,)])
        if "FROM alert_delivery_attempts" in sql:
            if "SELECT COUNT(*)" in sql:
                return _Result([(1,)])
            return _Result([{"channel": "email", "status": "failed", "item_count": 2}])
        if "FROM alert_delivery_outbox" in sql:
            return _Result([{"status": "pending", "item_count": 1}])
        raise AssertionError(f"Unexpected metrics query: {sql}")

    def rollback(self):
        return None

    def close(self):
        self.closed = True


def test_metrics_export_contains_only_aggregate_allowlisted_labels(monkeypatch):
    connection = _MetricsConnection()
    monkeypatch.setattr(grafana_metrics, "get_db_connection", lambda: connection)

    response = grafana_metrics.grafana_metrics()
    body = response.body.decode("utf-8")

    assert response.media_type.startswith("text/plain")
    assert "nexora_monitoring_database_available 1" in body
    assert 'nexora_outbound_probe_availability_ratio{window="1h"} 0.9' in body
    assert 'nexora_outbound_probe_samples{window="24h"} 10' in body
    assert 'nexora_outbound_probe_success_ratio_by_type{window="24h",probe_type="icmp_ping"} 0.5' in body
    assert 'nexora_outbound_probe_icmp_packet_loss_ratio{window="24h"} 0.2' in body
    assert 'nexora_outbound_probe_icmp_jitter_avg_ms{window="24h"} 1.5' in body
    assert 'nexora_wan_interface_oper_up_ratio{window="24h"} 0.983051' in body
    assert "nexora_alert_mtta_seconds_24h 40" in body
    assert "nexora_alert_mtta_p95_seconds_24h 40" in body
    assert "nexora_alert_mttr_seconds_24h 200" in body
    assert "nexora_alert_mttr_p95_seconds_24h 200" in body
    assert "nexora_alert_duplicate_open_events 1" in body
    assert "nexora_alert_retried_deliveries_24h 1" in body
    assert 'nexora_alert_open_events{severity="major"} 1' in body
    assert 'nexora_alert_delivery_attempts_24h{channel="email",status="failed"} 2' in body
    assert "tenant_id" not in body
    assert "hostname" not in body
    assert "recipient" not in body
    assert "resolved_ip" not in body
    assert connection.closed is True


def test_metrics_export_omits_unavailable_optional_source_instead_of_zero(monkeypatch):
    connection = _MetricsConnection(outbound_available=False)
    monkeypatch.setattr(grafana_metrics, "get_db_connection", lambda: connection)

    body = grafana_metrics.grafana_metrics().body.decode("utf-8")

    assert "nexora_monitoring_database_available 1" in body
    assert "# TYPE nexora_outbound_probe_samples gauge" not in body
    assert "# TYPE nexora_outbound_probe_availability_ratio gauge" not in body
    assert "nexora_alert_events_created_24h" in body


def test_metrics_export_runs_aggregate_queries_on_postgres(monkeypatch, isolated_db):
    connection = database.get_db_connection()
    cursor = connection.cursor()
    recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    cursor.execute(
        """
        INSERT INTO outbound_probe_samples
            (id, timestamp, success_count, total_targets, success_rate, avg_latency_ms)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("grafana-metrics-sample-1", recent, 2, 3, 2 / 3, 50.0),
    )
    cursor.execute(
        """
        INSERT INTO outbound_probe_samples
            (id, timestamp, success_count, total_targets, success_rate, avg_latency_ms)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("grafana-metrics-sample-2", recent, 1, 3, 1 / 3, 100.0),
    )
    cursor.execute(
        """
        INSERT INTO alert_events
            (id, dedupe_key, source, severity, title, message, created_at, workflow_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "grafana-metrics-alert-1",
            "grafana-metrics-dedupe-1",
            "test",
            "major",
            "Metrics contract test",
            "Synthetic isolated test row",
            recent,
            "open",
        ),
    )
    cursor.execute(
        """
        INSERT INTO alert_delivery_attempts
            (id, delivery_id, channel, status, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("grafana-metrics-attempt-1", "grafana-metrics-delivery-1", "email", "succeeded", recent),
    )
    cursor.execute(
        """
        INSERT INTO alert_delivery_outbox (id, delivery_key, channel, status)
        VALUES (?, ?, ?, ?)
        """,
        ("grafana-metrics-outbox-1", "grafana-metrics-delivery-2", "workspace", "pending"),
    )
    connection.commit()
    connection.close()
    monkeypatch.setattr(grafana_metrics, "get_db_connection", database.get_db_connection)

    body = grafana_metrics.grafana_metrics().body.decode("utf-8")

    assert 'nexora_outbound_probe_samples{window="24h"} 6' in body
    assert 'nexora_outbound_probe_availability_ratio{window="24h"} 0.5' in body
    assert 'nexora_outbound_probe_latency_avg_ms{window="24h"} 66.666667' in body
    assert 'nexora_outbound_probe_latency_max_ms{window="24h"} 100' in body
    assert 'nexora_alert_open_events{severity="major"} 1' in body
    assert 'nexora_alert_delivery_attempts_24h{channel="email",status="succeeded"} 1' in body
    assert 'nexora_alert_outbox_items{status="pending"} 1' in body


def test_metrics_export_includes_normalized_hardware_and_capability_without_addresses(monkeypatch, isolated_db):
    from database.migrations.m0260_snmp_hardware_inventory import upgrade

    conn = database.get_db_connection()
    upgrade(conn.cursor(), use_pg=True)
    conn.execute(
        """
        INSERT INTO devices (id, hostname, tenant_id, asset_id, platform, vendor, role)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO NOTHING
        """,
        ("grafana-hardware-device", "router-hw-01", "tenant-hw", "asset-hw-01", "example_os", "Example", "switch"),
    )
    sampled_at = datetime.now(timezone.utc)
    outcome = upsert_discovery_run(
        conn,
        "grafana-hardware-device",
        "grafana-hardware-run-1",
        "rules-abc123",
        [{
            "source_type": "standard_mib",
            "source_id": "HOST-RESOURCES-MIB::hrProcessorLoad",
            "component_class": "processor",
            "measurement_type": "cpu_usage_percent",
            "index": [1],
            "oid": "1.3.6.1.2.1.25.3.3.1.2",
            "unit": "percent",
            "sensor_name": "CPU 1",
            "group_name": "processor",
            "value": 26.5,
            "raw_value": "26.5",
            "quality": "good",
            "sample_at": sampled_at,
            "metadata": {"window": "unknown"},
        }],
        [{
            "source_type": "standard_mib",
            "component_class": "processor",
            "status": "success",
            "coverage_complete": True,
        }],
        sampled_at,
        discovery_version="nexora.hardware.discovery.v1",
        artifact_version="nexora.hardware.direct-poll.v1",
    )
    assert outcome["results"][0]["active_sensor_count"] == 1
    conn.commit()
    conn.close()
    monkeypatch.setattr(grafana_metrics, "get_db_connection", database.get_db_connection)

    body = grafana_metrics.grafana_hardware_metrics().body.decode("utf-8")

    assert 'nexora_hw_cpu_usage_percent{asset_id="asset-hw-01",component_class="processor",device_id="grafana-hardware-device"' in body
    assert 'hostname="router-hw-01"' in body
    assert 'window="unknown"' in body
    assert 'nexora_hw_sensor_quality{' in body and 'quality="good"' in body
    assert 'nexora_hw_capability_status{' in body and 'status="success"' in body
    assert 'nexora_hw_capability_active_sensor_count{' in body and '} 1' in body
    assert 'nexora_hw_capability_last_discovered_count{' in body and '} 1' in body
    assert 'artifact_version="nexora.hardware.direct-poll.v1"' in body
    assert 'nexora_hw_capability_info{' in body
    assert 'nexora_hw_capability_last_success_timestamp_seconds{' in body
    assert 'nexora_hw_sensor_render_errors 0' in body
    assert "192.0.2." not in body
    assert 'ip_address=' not in body

    aggregate_body = grafana_metrics.grafana_metrics().body.decode("utf-8")
    assert "nexora_hw_" not in aggregate_body
