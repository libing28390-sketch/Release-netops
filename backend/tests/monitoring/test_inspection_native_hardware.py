from __future__ import annotations

import asyncio

from services import inspection_service
from services import librenms_diagnostic_service


def _native_row(value: float, freshness: str = "fresh") -> dict:
    return {
        "sensor_current": value,
        "value_status": "available",
        "freshness": freshness,
    }


def test_inspection_hardware_values_come_from_fresh_librenms_rows(monkeypatch) -> None:
    async def fake_diagnostic(_device):
        return {
            "processor_sensors": [_native_row(25), _native_row(74)],
            "memory_pools": [_native_row(61)],
            "hardware_sensors": [
                {"sensor_class": "temperature", **_native_row(42)},
                {"sensor_class": "temperature", **_native_row(35, "stale")},
            ],
        }

    async def fake_interfaces(*_args, **_kwargs):
        return [{"name": "GigabitEthernet1/0/1", "status": "up"}]

    monkeypatch.setattr(librenms_diagnostic_service, "diagnose_librenms_hardware", fake_diagnostic)
    monkeypatch.setattr(inspection_service, "resolve_metric_profiles", lambda _device: {"interface": {}})
    monkeypatch.setattr(inspection_service, "collect_interface_data", fake_interfaces)

    metrics, interfaces = inspection_service._collect_snmp_for_inspection(
        {"id": "device-1", "ip_address": "192.0.2.1", "tenant_id": "tenant-1"}
    )

    assert metrics == {"cpu_usage": 74, "memory_usage": 61, "temp": 42}
    assert interfaces == [{"name": "GigabitEthernet1/0/1", "status": "up"}]


def test_inspection_does_not_use_native_hardware_rows_without_fresh_sample_time(monkeypatch) -> None:
    async def fake_diagnostic(_device):
        return {
            "processor_sensors": [_native_row(74, "unknown")],
            "memory_pools": [_native_row(61, "stale")],
            "hardware_sensors": [
                {"sensor_class": "temperature", **_native_row(42, "unknown")},
            ],
        }

    async def fake_interfaces(*_args, **_kwargs):
        return []

    monkeypatch.setattr(librenms_diagnostic_service, "diagnose_librenms_hardware", fake_diagnostic)
    monkeypatch.setattr(inspection_service, "resolve_metric_profiles", lambda _device: {"interface": {}})
    monkeypatch.setattr(inspection_service, "collect_interface_data", fake_interfaces)

    metrics, interfaces = inspection_service._collect_snmp_for_inspection(
        {"id": "device-1", "ip_address": "192.0.2.1", "tenant_id": "tenant-1"}
    )

    assert metrics == {}
    assert interfaces == []
