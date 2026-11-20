from __future__ import annotations

import pytest

from services import librenms_diagnostic_service, vault_service
from services import snmp_librenms_optical_service as optical


def test_native_optical_rows_preserve_librenms_fields_and_filter_non_optical_sensors():
    sensors = [
        {
            "sensor_id": "sensor-rx",
            "sensor_class": "dbm",
            "device_id": 7,
            "sensor_oid": ".1.3.6.1.4.1.1.1",
            "sensor_index": "7.1",
            "sensor_type": "dBm",
            "sensor_descr": "Rx lane 1 power",
            "group": "Transceiver",
            "sensor_current": "-12.3456",
            "lastupdate": "2026-10-07 01:02:03",
            "entPhysicalIndex": "68632782",
            "entPhysicalIndex_measured": "ports",
            "data_origin": "librenms_native",
            "value_status": "good",
            "freshness": "fresh",
            "sample_age_seconds": 3,
            "observed_at": "2026-10-07T01:02:00+00:00",
            "vendor_normalized_value": -12.346,
        },
        {
            "sensor_id": "sensor-temperature",
            "sensor_class": "temperature",
            "sensor_descr": "Transceiver temperature",
            "group": "Optical module",
            "sensor_current": "39.5",
            "data_origin": "librenms_native",
        },
        {
            "sensor_id": "sensor-cpu-temperature",
            "sensor_class": "temperature",
            "sensor_descr": "CPU temperature",
            "group": "Processor",
            "sensor_current": "51",
        },
        "invalid row",
    ]

    records = optical._native_optical_rows(sensors)

    assert [row["sensor_id"] for row in records] == ["sensor-rx", "sensor-temperature"]
    assert records[0]["sensor_current"] == "-12.3456"
    assert records[0]["data_origin"] == "librenms_native"
    assert records[0]["entPhysicalIndex"] == "68632782"
    assert "vendor_normalized_value" not in records[0]
    assert records[1]["sensor_current"] == "39.5"


def test_collect_librenms_optical_uses_only_native_diagnostic_results(monkeypatch):
    sensor = {
        "sensor_id": "sensor-rx",
        "sensor_class": "dbm",
        "sensor_descr": "Rx power",
        "group": "Transceiver",
        "sensor_current": "-10.5",
        "data_origin": "librenms_native",
    }
    native_transceiver = {"transceiver_id": "xcvr-1", "name": "Ethernet1/1"}

    async def fake_diagnostic(device):
        assert device == {"id": "device-1", "native_instance_id": "instance-1"}
        return {
            "state": "available",
            "identity": {"native_device_id": 7},
            "hardware_sensors": [sensor],
            "transceivers": [native_transceiver],
        }

    def reject_snmp_credentials(_device):
        pytest.fail("native optical reads must not resolve SNMP credentials")

    monkeypatch.setattr(librenms_diagnostic_service, "diagnose_librenms_hardware", fake_diagnostic)
    monkeypatch.setattr(vault_service, "resolve_collector_credentials", reject_snmp_credentials)

    result = optical.collect_librenms_optical(
        {"id": "device-1", "native_instance_id": "instance-1"}
    )

    assert result["success"] is True
    assert result["source"] == "librenms_native"
    assert result["adapter"]["mode"] == "librenms_native"
    assert result["adapter"]["native_state"] == "available"
    assert result["records"] == [sensor]
    assert result["transceivers"] == [native_transceiver]
    assert result["native_device_id"] == 7
