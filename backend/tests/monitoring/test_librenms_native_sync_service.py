from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from services import librenms_native_sync_service as sync_service
from services.librenms_runtime_client import LibreNMSAPIError


def _snapshot() -> SimpleNamespace:
    return SimpleNamespace(
        device={
            "device_id": "17",
            "poller_interval": 300,
            "last_discovered": "2026-10-07T09:50:00Z",
            "last_polled": "2026-10-07T10:00:00Z",
        },
        sensors=[
            {
                "sensor_id": 1,
                "sensor_class": "temperature",
                "sensor_type": "chassis",
                "sensor_descr": "Chassis temperature",
                "sensor_current": "41.5",
                "sensor_limit_warn": "70",
                "sensor_oid": "1.3.6.1.4.1.9.1.1",
            },
            {
                "sensor_id": 2,
                "sensor_class": "vendor_gauge",
                "sensor_descr": "Vendor gauge",
                "sensor_current": "7.25",
                "lastupdate": "2026-10-07T09:59:00Z",
                "unit": "widgets",
            },
        ],
        wireless_sensors=[{
            "sensor_id": 7,
            "sensor_class": "clients",
            "sensor_type": "wireless-ap",
            "sensor_index": "ap-1",
            "sensor_descr": "AP clients",
            "sensor_current": "12",
            "lastupdate": "2026-10-07T09:59:30Z",
            "access_point_id": 23,
        }],
        transceivers=[{
            "port_id": 44, "ifName": "Ten1/0/1", "vendor": "Optics Co",
            "serial": "S-1", "part_number": "P-1",
        }],
        processor_sensors=[{
            "processor_id": 3,
            "processor_usage": "37.25",
            "processor_descr": "CPU 1",
            "processor_index": 1,
            "processor_type": "hr-device",
            "processor_perc_warn": "90",
            "lastupdate": "2026-10-07T09:58:00Z",
        }],
        memory_pools=[{
            "mempool_id": 4,
            "mempool_perc": "62",
            "mempool_descr": "System Memory",
            "mempool_class": "system",
            "mempool_used": 620,
            "mempool_free": 380,
            "mempool_total": 1000,
            "lastupdate": "2026-10-07T09:57:00Z",
        }],
        health_graphs={"processor": [{"sensor_id": 99, "desc": "Graph only"}]},
    )


def test_snapshot_conversion_preserves_native_identity_and_sample_time() -> None:
    converted = sync_service.snapshot_to_inventory_records(
        _snapshot(),
        device_id="device-1",
        instance_id="instance-1",
        native_device_id="17",
    )

    sensors = {sensor["native_entity_id"]: sensor for sensor in converted["sensors"]}
    temperature = sensors["sensor:1"]
    assert temperature["source_type"] == "librenms_native"
    assert temperature["data_origin"] == "librenms_native"
    assert temperature["component_class"] == "temperature"
    assert temperature["measurement_type"] == "temperature_celsius"
    assert temperature["unit"] == "celsius"
    assert temperature["value"] is None
    assert temperature["raw_value"] is None
    assert temperature["quality"] == "missing"
    assert temperature["sample_at"] is None
    assert "sensor_current" not in temperature["metadata"]
    assert temperature["thresholds"] == {"limit_warn": "70"}
    assert temperature["index"] == {
        "instance_id": "instance-1",
        "native_device_id": "17",
        "row_kind": "sensor",
        "row_id": "1",
    }

    processor = sensors["processor:3"]
    assert processor["measurement_type"] == "cpu_usage_percent"
    assert processor["unit"] == "%"
    assert processor["value"] == 37.25
    assert processor["metadata"]["poll_interval_seconds"] == 300
    assert processor["sample_at"] == datetime(2026, 10, 7, 9, 58, tzinfo=timezone.utc)
    cpu_sample = next(sample for sample in converted["sample_rows"] if sample["value"] == 37.25)
    assert cpu_sample["sensor_key"] == sync_service.build_sensor_key(
        "librenms_native", "processor", "cpu_usage_percent", processor["index"], "unknown",
    )

    memory = sensors["memory_pool:4"]
    assert memory["measurement_type"] == "memory_usage_percent"
    assert memory["value"] == 62
    assert memory["unit"] == "%"
    assert memory["metadata"]["poll_interval_seconds"] == 300
    assert not {"memory_used_bytes", "memory_total_bytes"} & {
        sensor["measurement_type"] for sensor in converted["sensors"]
    }
    assert not {"mempool_used", "mempool_free", "mempool_total"} & set(memory["metadata"])

    vendor = sensors["sensor:2"]
    assert vendor["measurement_type"] == "sensor_value"
    assert vendor["unit"] == "widgets"
    assert vendor["value"] == 7.25
    assert len(converted["sample_rows"]) == 4
    assert all(sample["observed_at"] is not None for sample in converted["sample_rows"])
    assert "sensor:99" not in sensors  # Health graph descriptions are not readings.

    wireless = sensors["wireless_sensor:7"]
    assert wireless["measurement_type"] == "wireless_sensor_value"
    assert wireless["metadata"]["wireless_sensor_class"] == "clients"
    assert wireless["metadata"]["poll_interval_seconds"] == 300
    assert wireless["metadata"]["access_point_id"] == 23

    transceiver = sensors["transceiver:44"]
    assert transceiver["value"] is None
    assert transceiver["quality"] == "missing"
    assert transceiver["sample_at"] is None
    assert transceiver["metadata"]["serial"] == "S-1"


def test_snapshot_conversion_uses_latest_duplicate_native_row_time() -> None:
    snapshot = SimpleNamespace(
        device={"device_id": "17"},
        sensors=[
            {
                "sensor_id": 8, "sensor_class": "voltage", "sensor_descr": "PSU",
                "sensor_current": "12", "lastupdate": "2026-10-07T09:00:00Z",
            },
            {
                "sensor_id": 8, "sensor_class": "voltage", "sensor_descr": "PSU",
                "sensor_current": "13", "lastupdate": "2026-10-07T09:05:00Z",
            },
        ],
    )
    converted = sync_service.snapshot_to_inventory_records(
        snapshot, device_id="device-1", instance_id="instance-1", native_device_id="17",
    )

    assert len(converted["sensors"]) == 1
    assert converted["sensors"][0]["value"] == 13
    assert converted["sample_rows"][0]["value"] == 13
    assert converted["sample_rows"][0]["observed_at"] == datetime(
        2026, 10, 7, 9, 5, tzinfo=timezone.utc,
    )


def test_coverage_marks_missing_identity_partial_and_empty_known_scope_complete() -> None:
    snapshot = SimpleNamespace(
        device={"device_id": "17"},
        sensors=[{
            "sensor_class": "temperature", "sensor_descr": "No stable id", "sensor_current": 22,
        }],
    )
    converted = sync_service.snapshot_to_inventory_records(
        snapshot,
        device_id="device-1",
        instance_id="instance-2",
        native_device_id="17",
        existing_component_classes=("fan",),
    )

    results = {item["component_class"]: item for item in converted["category_results"]}
    assert results["temperature"]["status"] == "partial"
    assert results["temperature"]["coverage_complete"] is False
    assert results["fan"]["status"] == "not_found"
    assert results["fan"]["coverage_complete"] is True


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


class _Connection:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state
        self.closed = False
        self.committed = False
        self.rolled_back = False

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        if "FROM librenms_device_bindings AS b" in sql and "desired_state = 'enabled'" in sql:
            assert params == ("device-1",)
            return _Rows([self.state["binding"]] if self.state.get("enabled_binding", True) else [])
        if "SELECT EXISTS" in sql and "snmp_hardware_sensors" in sql:
            assert params == ("device-1", "instance-1", "17")
            return _Rows([{"has_sample": self.state.get("has_sample", False)}])
        if "SELECT DISTINCT component_class" in sql:
            return _Rows([{"component_class": item} for item in self.state.get("classes", [])])
        if "FOR UPDATE OF b, i" in sql:
            assert params == ("binding-1",)
            if not self.state.get("enabled_binding", True):
                return _Rows([])
            return _Rows([{
                "id": "binding-1", "desired_state": "enabled", "instance_enabled": True,
            }])
        if "UPDATE librenms_device_bindings" in sql:
            self.state["binding_updates"].append((sql, params))
            return SimpleNamespace(rowcount=1)
        raise AssertionError(f"unexpected SQL: {sql}")

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def _binding(**overrides: Any) -> dict[str, Any]:
    binding = {
        "binding_id": "binding-1",
        "tenant_id": "tenant-1",
        "asset_id": "asset-1",
        "device_id": "device-1",
        "instance_id": "instance-1",
        "librenms_device_id": "17",
        "sync_status": "synced",
        "last_sync_at": None,
        "last_discovery_at": None,
        "last_poll_at": None,
        "base_url": "https://librenms.example",
        "instance_enabled": True,
        "engine_version": "26.9",
        "engine_commit": "abc123",
        "token_credential_id": "credential-1",
        "credential_type": "api_token",
        "encrypted_password": "encrypted-placeholder",
    }
    binding.update(overrides)
    return binding


def _install_fakes(
    monkeypatch,
    *,
    binding: dict[str, Any] | None = None,
    has_sample: bool = False,
    classes: list[str] | None = None,
    snapshot: Any | None = None,
    device_error: Exception | None = None,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "binding": binding or _binding(),
        "enabled_binding": True,
        "has_sample": has_sample,
        "classes": classes or [],
        "binding_updates": [],
        "connections": [],
        "snapshot_calls": 0,
        "device_calls": 0,
        "upsert_calls": [],
        "batch_calls": [],
    }

    def connection_factory() -> _Connection:
        connection = _Connection(state)
        state["connections"].append(connection)
        return connection

    monkeypatch.setattr(sync_service, "get_db_connection", connection_factory)
    monkeypatch.setattr(sync_service, "decrypt_credential", lambda _: "unit-test-token")
    monkeypatch.setattr(
        sync_service,
        "upsert_discovery_run",
        lambda *args, **kwargs: state["upsert_calls"].append((args, kwargs)) or {"run_id": "run-1"},
    )
    monkeypatch.setattr(
        sync_service,
        "record_sensor_samples_batch",
        lambda _conn, samples: state["batch_calls"].append(list(samples)) or len(samples),
    )

    class _Client:
        def __init__(self, base_url: str, token: str) -> None:
            assert base_url == "https://librenms.example"
            assert token == "unit-test-token"

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get_device(self, native_device_id: str) -> dict[str, Any]:
            state["device_calls"] += 1
            assert native_device_id == "17"
            if device_error:
                raise device_error
            return {"device_id": "17", "last_polled": "2026-10-07T10:00:00Z"}

        async def read_device_snapshot(self, native_device_id: str) -> Any:
            state["snapshot_calls"] += 1
            assert native_device_id == "17"
            return snapshot or _snapshot()

    monkeypatch.setattr(sync_service, "LibreNMSRuntimeClient", _Client)
    return state


def test_sync_persists_native_snapshot_and_keeps_request_and_sample_times_separate(monkeypatch) -> None:
    state = _install_fakes(monkeypatch, snapshot=_snapshot())

    result = asyncio.run(sync_service.sync_bound_device_hardware("device-1"))

    assert result["status"] == "synced"
    assert result["sensor_count"] == 6
    assert result["sample_count"] == 4
    assert state["device_calls"] == 1
    assert state["snapshot_calls"] == 1
    assert len(state["upsert_calls"]) == 1
    _, upsert_kwargs = state["upsert_calls"][0]
    assert upsert_kwargs["sensors"][0]["sample_at"] is None
    batch = state["batch_calls"][0]
    assert len(batch) == 4
    assert all(sample["observed_at"] != upsert_kwargs["observed_at"] for sample in batch)
    assert "unit-test-token" not in repr(result)
    assert any(connection.committed for connection in state["connections"])


def test_sync_skips_full_snapshot_when_native_poll_is_unchanged_and_inventory_has_samples(monkeypatch) -> None:
    state = _install_fakes(
        monkeypatch,
        binding=_binding(last_poll_at="2026-10-07T10:00:00Z"),
        has_sample=True,
    )

    result = asyncio.run(sync_service.sync_bound_device_hardware("device-1"))

    assert result["status"] == "unchanged"
    assert result["native_last_polled"] == "2026-10-07T10:00:00+00:00"
    assert state["device_calls"] == 1
    assert state["snapshot_calls"] == 0
    assert state["upsert_calls"] == []
    assert state["batch_calls"] == []
    assert any(connection.committed for connection in state["connections"])


def test_sync_failure_stores_only_sanitized_error_code(monkeypatch) -> None:
    state = _install_fakes(
        monkeypatch,
        device_error=LibreNMSAPIError("timeout"),
    )

    result = asyncio.run(sync_service.sync_bound_device_hardware("device-1"))

    assert result == {
        "status": "failed", "error_code": "timeout", "sensor_count": 0, "sample_count": 0,
    }
    failure_update = next(
        params for sql, params in state["binding_updates"] if "sync_status = 'failed'" in sql
    )
    assert failure_update[1] == "timeout"
    assert "unit-test-token" not in repr(result)


def test_sync_reads_full_snapshot_when_native_poll_is_known_but_inventory_has_no_samples(monkeypatch) -> None:
    state = _install_fakes(
        monkeypatch,
        binding=_binding(last_poll_at="2026-10-07T10:00:00Z"),
        has_sample=False,
    )

    result = asyncio.run(sync_service.sync_bound_device_hardware("device-1"))

    assert result["status"] == "synced"
    assert state["snapshot_calls"] == 1
