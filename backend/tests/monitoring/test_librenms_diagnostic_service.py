from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from services import librenms_diagnostic_service as diagnostics
from services import snmp_hardware_poller_service as poller
from services.librenms_source_policy import PINNED_LIBRENMS_COMMIT


class _Connection:
    closed = False

    def close(self) -> None:
        self.closed = True


def _sensor(**overrides: Any) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    sensor = {
        "sensor_key": "cpu-0",
        "source_type": "librenms_rule",
        "source_id": "cisco_ios",
        "component_class": "processor",
        "measurement_type": "cpu_usage_percent",
        "index": [0],
        "index_labels": {},
        "data_origin": "legacy_snmp",
        "rule_version": PINNED_LIBRENMS_COMMIT,
        "metadata": {
            "collection_version": poller.DISCOVERY_VERSION,
            "source_path": "resources/definitions/os_discovery/ciscosb.yaml",
            "source_commit": PINNED_LIBRENMS_COMMIT,
            "poll_interval_seconds": 300,
        },
        "enabled": True,
        "lifecycle_status": "active",
        "discovery_status": "present",
        "presence_status": "present",
        "oid": "1.3.6.1.4.1.9.9.109.1.1.1.1.6",
        "sensor_name": "CPU 0",
        "unit": "percent",
        "last_value": 35.5,
        "last_raw_value": "35.5",
        "last_quality": "good",
        "last_success": now - timedelta(seconds=10),
        "last_sample_at": now - timedelta(seconds=10),
        "thresholds": {"warning": 80},
        "states": {},
    }
    sensor.update(overrides)
    return sensor


def test_diagnostic_exposes_current_rule_inventory_provenance_and_lifecycle(monkeypatch) -> None:
    from services import snmp_hardware_inventory_service as inventory

    connection = _Connection()
    sample_time = datetime.now(timezone.utc) - timedelta(seconds=10)
    current_sensor = _sensor(last_success=sample_time, last_sample_at=sample_time)
    retired_sensor = _sensor(
        sensor_key="cpu-retired",
        enabled=False,
        lifecycle_status="retired",
        discovery_status="missing",
        presence_status="missing",
        last_value=10,
        last_quality="good",
    )
    external_sensor = _sensor(
        sensor_key="external-cpu",
        source_type="librenms_native",
        data_origin="librenms_native",
    )
    old_collection_sensor = _sensor(
        sensor_key="old-cpu",
        source_type="standard_mib",
        metadata={
            "collection_version": "old-collector",
            "source_path": "resources/definitions/os_discovery/ciscosb.yaml",
            "source_commit": PINNED_LIBRENMS_COMMIT,
            "poll_interval_seconds": 300,
        },
    )
    untrusted_current_sensor = _sensor(
        sensor_key="untrusted-cpu",
        metadata={
            "collection_version": poller.DISCOVERY_VERSION,
            "source_path": "resources/definitions/os_discovery/not-verified.yaml",
            "source_commit": PINNED_LIBRENMS_COMMIT,
            "poll_interval_seconds": 300,
        },
    )
    monkeypatch.setattr(diagnostics, "get_db_connection", lambda: connection)
    monkeypatch.setattr(inventory, "list_hardware_sensors", lambda *_args, **_kwargs: [
        current_sensor, retired_sensor, external_sensor, old_collection_sensor, untrusted_current_sensor,
    ])
    monkeypatch.setattr(inventory, "list_hardware_capabilities", lambda *_args: [
        {
            "source_type": "librenms_rule",
            "component_class": "processor",
            "discovery_version": poller.DISCOVERY_VERSION,
            "last_status": "success",
            "coverage_complete": True,
            "active_sensor_count": 1,
            "last_discovered_count": 1,
            "rule_version": PINNED_LIBRENMS_COMMIT,
            "artifact_version": "resources/definitions/os_discovery/ciscosb.yaml",
        },
        {
            "source_type": "librenms_rule",
            "component_class": "temperature",
            "discovery_version": "old-collector",
            "last_status": "failed",
        },
        {
            "source_type": "librenms_native",
            "component_class": "temperature",
            "discovery_version": poller.DISCOVERY_VERSION,
            "last_status": "failed",
        },
        {
            "source_type": "h3c_wireless",
            "component_class": "wireless_radio",
            "discovery_version": poller.DISCOVERY_VERSION,
            "last_status": "success",
        },
    ])
    monkeypatch.setattr(poller, "hardware_sample_interval_seconds", lambda: 75)
    monkeypatch.setattr(
        poller,
        "hardware_stale_after_seconds",
        lambda sensor: 900 if (sensor or {}).get("metadata", {}).get("poll_interval_seconds") == 300 else 225,
        raising=False,
    )

    result = asyncio.run(diagnostics.diagnose_librenms_hardware({
        "id": "device-1", "hostname": "edge-01", "ip_address": "192.0.2.10",
    }))

    assert result["source"] == "nexora_snmp"
    assert result["state"] == "available"
    assert result["sensor_count"] == 2
    assert result["active_sensor_count"] == 1
    assert len(result["capabilities"]) == 1
    assert result["collection"]["poll_interval_seconds"] == 75
    assert result["collection"]["stale_after_seconds"] == 900
    assert result["collection"]["sync_status"] == "not_applicable"
    by_id = {row["sensor_id"]: row for row in result["processor_sensors"]}
    current = by_id["cpu-0"]
    assert current["source"] == "librenms_rule"
    assert current["source_id"] == "cisco_ios"
    assert current["source_path"] == "resources/definitions/os_discovery/ciscosb.yaml"
    assert current["source_commit"] == PINNED_LIBRENMS_COMMIT
    assert current["rule_version"] == PINNED_LIBRENMS_COMMIT
    assert current["quality"] == "good"
    assert current["poll_interval_seconds"] == 75
    assert current["registered_poll_interval_seconds"] == 300
    assert current["enabled"] is True
    assert current["lifecycle_status"] == "active"
    assert current["sensor_current"] == 35.5
    assert by_id["cpu-retired"]["enabled"] is False
    assert by_id["cpu-retired"]["lifecycle_status"] == "retired"
    assert not any(row["source_type"] == "librenms_native" for row in result["processor_sensors"])
    assert connection.closed is True


def test_diagnostic_waits_for_current_local_rule_inventory_without_instance_fallback(monkeypatch) -> None:
    from services import snmp_hardware_inventory_service as inventory

    connection = _Connection()
    monkeypatch.setattr(diagnostics, "get_db_connection", lambda: connection)
    monkeypatch.setattr(inventory, "list_hardware_sensors", lambda *_args, **_kwargs: [
        _sensor(metadata={
            "collection_version": "old-collector",
            "source_path": "resources/definitions/os_discovery/ciscosb.yaml",
            "source_commit": PINNED_LIBRENMS_COMMIT,
            "poll_interval_seconds": 300,
        }),
    ])
    monkeypatch.setattr(inventory, "list_hardware_capabilities", lambda *_args: [])

    def fail_external_dependency(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("local diagnostics must not access external bindings or credentials")

    monkeypatch.setattr(diagnostics, "decrypt_credential", fail_external_dependency, raising=False)
    monkeypatch.setattr(diagnostics, "_binding_for_device", fail_external_dependency, raising=False)

    result = asyncio.run(diagnostics.diagnose_librenms_hardware({
        "id": "device-v3", "hostname": "edge-v3", "ip_address": "192.0.2.30",
    }))

    assert result["source"] == "nexora_snmp"
    assert result["state"] == "pending"
    assert "不触发即时采集" in result["message"]
    assert result["hardware_sensors"] == []
    assert result["processor_sensors"] == []
    assert result["collection"]["engine_status"] == "local"
    assert connection.closed is True


def test_diagnostic_returns_local_unavailable_state_when_inventory_read_fails(monkeypatch) -> None:
    from services import snmp_hardware_inventory_service as inventory

    monkeypatch.setattr(diagnostics, "get_db_connection", lambda: _Connection())
    monkeypatch.setattr(
        inventory,
        "list_hardware_sensors",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database down")),
    )
    monkeypatch.setattr(diagnostics.logger, "warning", lambda *_args, **_kwargs: None)

    result = asyncio.run(diagnostics.diagnose_librenms_hardware({"id": "device-1"}))

    assert result["source"] == "nexora_snmp"
    assert result["state"] == "unavailable"
    assert result["collection"]["engine_status"] == "error"
    assert result["binding"] is None
