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
    from services import snmp_metric_profile_service, snmp_service

    profile_calls = []
    transport_calls = []

    async def fake_diagnostic(_device):
        return {
            "processor_sensors": [_native_row(25), _native_row(74)],
            "memory_pools": [{"sensor_type": "memory_usage_percent", **_native_row(61)}],
            "hardware_sensors": [
                {"sensor_class": "temperature", **_native_row(42)},
                {"sensor_class": "temperature", **_native_row(35, "stale")},
            ],
        }

    async def fake_interfaces(*args, **kwargs):
        transport_calls.append((args, kwargs))
        return [{"name": "GigabitEthernet1/0/1", "status": "up"}]

    def fake_profile_resolver(device):
        profile_calls.append(device)
        return {"interface": {"in_octets_oid": "1.3.6.1.4.1.55555.10"}}

    monkeypatch.setattr(librenms_diagnostic_service, "diagnose_librenms_hardware", fake_diagnostic)
    monkeypatch.setattr(snmp_metric_profile_service, "resolve_metric_profiles", fake_profile_resolver)
    monkeypatch.setattr(snmp_service, "collect_interface_data", fake_interfaces)
    monkeypatch.setattr(inspection_service, "resolve_metric_profiles", fake_profile_resolver, raising=False)
    monkeypatch.setattr(inspection_service, "collect_interface_data", fake_interfaces, raising=False)

    metrics, interfaces = inspection_service._collect_snmp_for_inspection(
        {
            "id": "device-1", "ip_address": "192.0.2.1", "tenant_id": "tenant-1",
            "snmp_metric_profile_id": "custom-profile",
            "snmp_metric_profile": {"interface": {"in_octets_oid": "1.3.6.1.4.1.55555.10"}},
        }
    )

    assert metrics == {"cpu_usage": 74, "memory_usage": 61, "temp": 42}
    assert interfaces == []
    assert profile_calls == []
    assert transport_calls == []


def test_inspection_does_not_use_native_hardware_rows_without_fresh_sample_time(monkeypatch) -> None:
    async def fake_diagnostic(_device):
        return {
            "processor_sensors": [_native_row(74, "unknown")],
            "memory_pools": [_native_row(61, "stale")],
            "hardware_sensors": [
                {"sensor_class": "temperature", **_native_row(42, "unknown")},
            ],
        }

    monkeypatch.setattr(librenms_diagnostic_service, "diagnose_librenms_hardware", fake_diagnostic)

    metrics, interfaces = inspection_service._collect_snmp_for_inspection(
        {"id": "device-1", "ip_address": "192.0.2.1", "tenant_id": "tenant-1"}
    )

    assert metrics == {}
    assert interfaces == []


def test_interface_down_inspection_without_librenms_rows_is_no_data() -> None:
    value, error = inspection_service._extract_snmp_item_value(
        {"check_key": "interface_down"}, {}, [],
    )

    assert value is None
    assert "IF-MIB" in error
