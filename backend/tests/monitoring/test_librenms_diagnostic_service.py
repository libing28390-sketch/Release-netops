from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import database
from services import librenms_diagnostic_service as diagnostics


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _Connection:
    def __init__(self, binding: dict[str, Any]) -> None:
        self.binding = binding
        self.closed = False

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _Rows:
        assert "librenms_device_bindings" in sql
        assert params == ("device-1",)
        return _Rows([self.binding])

    def close(self) -> None:
        self.closed = True


def _binding() -> dict[str, Any]:
    return {
        "binding_id": "binding-1",
        "tenant_id": "tenant-1",
        "asset_id": "asset-1",
        "device_id": "device-1",
        "instance_id": "instance-1",
        "librenms_device_id": "17",
        "librenms_hostname": "edge-01",
        "collector_id": "collector-1",
        "poller_group": "default",
        "desired_state": "enabled",
        "sync_status": "synced",
        "last_sync_at": None,
        "last_discovery_at": None,
        "last_poll_at": None,
        "last_error_code": None,
        "instance_name": "LibreNMS primary",
        "base_url": "http://librenms",
        "instance_enabled": True,
        "engine_version": "26.9",
        "engine_commit": "abc123",
        "instance_health_state": "healthy",
        "token_credential_id": "credential-1",
        "credential_type": "api_token",
        "encrypted_password": "ciphertext",
    }


def _install_client(monkeypatch, snapshot: SimpleNamespace, binding: dict[str, Any] | None = None) -> _Connection:
    connection = _Connection(binding or _binding())
    monkeypatch.setattr(diagnostics, "get_db_connection", lambda: connection)
    monkeypatch.setattr(diagnostics, "decrypt_credential", lambda _value: "unit-test-token")

    class FakeClient:
        def __init__(self, base_url: str, token: str) -> None:
            assert base_url == "http://librenms"
            assert token == "unit-test-token"

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def read_device_snapshot(self, native_device_id: str) -> SimpleNamespace:
            assert native_device_id == "17"
            return snapshot

        async def get_system_info(self) -> dict[str, str]:
            return {"local_ver": "26.9", "local_sha": "abc123"}

    monkeypatch.setattr(diagnostics, "LibreNMSRuntimeClient", FakeClient)
    return connection


def _snapshot(*, processor: dict[str, Any], memory_pool: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        device={
            "device_id": "17", "hostname": "edge-01", "os": "comware",
            "poller_interval": 60, "last_polled": "2026-10-07 10:00:00",
        },
        sensors=[{
            "device_id": 17, "sensor_class": "temperature", "sensor_current": "41.5",
            "sensor_descr": "Chassis", "lastupdate": "2026-10-07T10:00:00Z",
        }],
        wireless_sensors=[],
        transceivers=[],
        processor_sensors=[processor],
        memory_pools=[memory_pool],
        health_graphs={
            "processor": [{"sensor_id": 3, "desc": "Processor"}],
            "mempool": [{"sensor_id": 4, "desc": "Memory"}],
            "storage": [],
        },
    )


def test_diagnostic_exposes_librenms_processor_and_mempool_samples_with_native_times(monkeypatch) -> None:
    processor_time = datetime.now(timezone.utc) - timedelta(seconds=45)
    memory_time = datetime.now(timezone.utc) - timedelta(seconds=300)
    snapshot = _snapshot(
        processor={
            "processor_id": 3, "device_id": 17, "processor_usage": "37.25",
            "processor_descr": "CPU 1", "processor_type": "hr-device", "processor_index": "1",
            "lastupdate": processor_time.isoformat(),
        },
        memory_pool={
            "mempool_id": 4, "device_id": 17, "mempool_perc": "62",
            "mempool_descr": "System Memory", "mempool_class": "system",
            "mempool_used": 630, "mempool_free": 370, "mempool_total": 1000,
            "mempool_precision": 1024, "lastupdate": memory_time.isoformat(),
        },
    )
    connection = _install_client(monkeypatch, snapshot)

    result = asyncio.run(diagnostics.diagnose_librenms_hardware({
        "id": "device-1", "asset_id": "asset-1", "tenant_id": "tenant-1",
        "hostname": "edge-01", "ip_address": "192.0.2.10",
    }))

    assert result["source"] == "librenms_native"
    assert result["state"] == "available"
    assert result["processor_sensors"] == [{
        "processor_id": 3, "device_id": 17, "processor_usage": "37.25",
        "processor_type": "hr-device", "processor_index": "1", "processor_descr": "CPU 1",
        "sensor_id": 3, "sensor_descr": "CPU 1", "sensor_class": "processor",
        "sensor_current": 37.25, "unit": None, "lastupdate": processor_time.isoformat(),
        "data_origin": "librenms_native", "value_status": "available", "freshness": "fresh",
        "sample_age_seconds": 45.0, "observed_at": processor_time.isoformat(),
    }]
    memory = result["memory_pools"][0]
    assert memory["sensor_id"] == 4
    assert memory["sensor_descr"] == "System Memory"
    assert memory["sensor_class"] == "mempool"
    assert memory["sensor_current"] == 62.0
    assert memory["mempool_used"] == 630
    assert memory["mempool_total"] == 1000
    assert memory["mempool_precision"] == 1024
    assert memory["unit"] is None
    assert memory["freshness"] == "stale"
    assert memory["observed_at"] == memory_time.isoformat()
    assert result["health_graphs"] == [
        {"health_type": "processor", "desc": "Processor"},
        {"health_type": "mempool", "desc": "Memory"},
    ]
    assert {item["key"] for item in result["metric_summary"]} >= {"processor", "mempool", "temperature"}
    assert result["generated_at"] != processor_time.isoformat()
    assert "observed_at" not in result["collection"]
    assert connection.closed is True


def test_processor_and_mempool_without_sample_timestamps_remain_freshness_unknown(monkeypatch) -> None:
    snapshot = _snapshot(
        processor={
            "processor_id": 3, "processor_usage": "8", "processor_descr": "CPU",
        },
        memory_pool={
            "mempool_id": 4, "mempool_perc": "50", "mempool_descr": "Memory",
            "mempool_total": 2048, "mempool_precision": 1024,
        },
    )
    _install_client(monkeypatch, snapshot)

    result = asyncio.run(diagnostics.diagnose_librenms_hardware({
        "id": "device-1", "asset_id": "asset-1", "tenant_id": "tenant-1",
    }))

    processor = result["processor_sensors"][0]
    memory = result["memory_pools"][0]
    assert processor["sensor_current"] == 8
    assert processor["lastupdate"] is None
    assert processor["observed_at"] is None
    assert processor["sample_age_seconds"] is None
    assert processor["freshness"] == "unknown"
    assert memory["sensor_current"] == 50
    assert memory["mempool_total"] == 2048
    assert memory["mempool_precision"] == 1024
    assert memory["observed_at"] is None
    assert memory["freshness"] == "unknown"
    assert result["metric_summary"][-2]["status"] == "unknown"
    assert result["metric_summary"][-1]["status"] == "unknown"


def test_native_snapshot_remains_readable_while_projection_sync_is_pending(monkeypatch) -> None:
    snapshot = _snapshot(
        processor={"processor_id": 3, "processor_usage": "8", "processor_descr": "CPU"},
        memory_pool={"mempool_id": 4, "mempool_perc": "50", "mempool_descr": "Memory"},
    )
    pending_binding = _binding()
    pending_binding["sync_status"] = "pending"
    _install_client(monkeypatch, snapshot, pending_binding)

    result = asyncio.run(diagnostics.diagnose_librenms_hardware({
        "id": "device-1", "asset_id": "asset-1", "tenant_id": "tenant-1",
    }))

    assert result["state"] == "available"
    assert result["collection"]["sync_status"] == "pending"
    assert result["processor_sensors"][0]["sensor_current"] == 8
    assert result["memory_pools"][0]["sensor_current"] == 50


def test_binding_lookup_uses_canonical_default_tenant_when_device_row_is_unscoped(isolated_db, monkeypatch) -> None:
    conn = database.get_db_connection()
    try:
        conn.execute(
            """INSERT INTO physical_assets (id, asset_type, created_at, updated_at)
               VALUES ('asset-unscoped', 'network_device', '2026-01-01', '2026-01-01')"""
        )
        conn.execute(
            """INSERT INTO devices (id, hostname, asset_id, tenant_id)
               VALUES ('device-unscoped', 'edge-unscoped', 'asset-unscoped', NULL)"""
        )
        conn.execute(
            """INSERT INTO librenms_instances (id, display_name, base_url, enabled, health_state)
               VALUES ('instance-unscoped', 'LibreNMS', 'https://librenms.example', TRUE, 'healthy')"""
        )
        conn.execute(
            """INSERT INTO librenms_device_bindings
               (id, tenant_id, asset_id, device_id, instance_id, librenms_device_id, sync_status)
               VALUES ('binding-unscoped', 'tenant-default', 'asset-unscoped', 'device-unscoped',
                       'instance-unscoped', '17', 'pending')"""
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(diagnostics, "get_db_connection", database.get_db_connection)

    binding = diagnostics._binding_for_device({
        "id": "device-unscoped", "asset_id": "asset-unscoped", "tenant_id": "",
    })

    assert binding is not None
    assert binding["binding_id"] == "binding-unscoped"
    assert binding["tenant_id"] == "tenant-default"
