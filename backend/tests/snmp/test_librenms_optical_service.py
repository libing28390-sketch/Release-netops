from __future__ import annotations

import pytest

from services import snmp_librenms_optical_service as optical


def test_optical_records_project_librenms_sensors_by_port_and_lane():
    sensors = [
        {
            "quality": "good",
            "measurement_type": "optical_power_dbm",
            "value": -12.3456,
            "sensor_name": "",
            "entity_name": "XGigabitEthernet0/0/1",
            "group_name": "Optical Rx power",
            "index": [7, 2],
            "index_labels": {"if_index": 7},
            "metadata": {"raw_definition": {"descr": "Rx lane 2 power"}},
        },
        {
            "quality": "good",
            "measurement_type": "optical_power_dbm",
            "value": -3.25,
            "sensor_name": "",
            "entity_name": "XGigabitEthernet0/0/1",
            "group_name": "Optical Tx power",
            "index": [7, 2],
            "index_labels": {"if_index": 7},
            "metadata": {"raw_definition": {"descr": "Tx lane 2 power"}},
        },
        {
            "quality": "good",
            "measurement_type": "current_amperes",
            "value": 0.0045,
            "sensor_name": "",
            "entity_name": "XGigabitEthernet0/0/1",
            "group_name": "Optical transceiver",
            "index": [7, 2],
            "index_labels": {"if_index": 7},
            "metadata": {"raw_definition": {"descr": "TX bias current"}},
        },
        {
            "quality": "good",
            "measurement_type": "optical_power_dbm",
            "value": -8,
            "sensor_name": "",
            "entity_name": "XGigabitEthernet0/0/1",
            "group_name": "Optical Rx power",
            "index": [7, 3],
            "index_labels": {"if_index": 7},
            "metadata": {"raw_definition": {"descr": "Rx lane 3 power"}},
        },
        {
            "quality": "good",
            "measurement_type": "optical_power_dbm",
            "value": -99,
            "quality": "bad",
            "sensor_name": "",
            "entity_name": "XGigabitEthernet0/0/1",
            "group_name": "Optical Rx power",
            "index": [7, 2],
            "index_labels": {"if_index": 7},
            "metadata": {"raw_definition": {"descr": "Rx lane 2 power"}},
        },
    ]

    records = optical._optical_records(sensors, "Aruba", "2026-09-29T00:00:00+00:00")

    assert len(records) == 2
    lane_two = next(record for record in records if record.get("laneIndex") == 2)
    assert lane_two["interface"] == "XGigabitEthernet0/0/1"
    assert lane_two["ifIndex"] == 7
    assert lane_two["rx_power_dbm"] == pytest.approx(-12.346)
    assert lane_two["tx_power_dbm"] == pytest.approx(-3.25)
    assert lane_two["bias_ma"] == pytest.approx(4.5)
    assert lane_two["source"] == "snmp"
    assert lane_two["vendor"] == "Aruba"


def test_optical_projection_does_not_confuse_entity_index_with_ifindex():
    records = optical._optical_records([{
        "quality": "good",
        "source_type": "librenms",
        "measurement_type": "optical_power_dbm",
        "value": -12.3,
        "entity_name": "XGigabitEthernet0/0/1",
        "group_name": "transceiver",
        "index": [68632782],
        "index_labels": {"ent_physical_index": "68632782"},
        "metadata": {
            "ent_physical_index": "68632782",
            "ent_physical_index_measured": "ports",
            "raw_definition": {"descr": "Rx power"},
        },
    }], "Huawei", "2026-09-29T00:00:00+00:00")

    assert len(records) == 1
    assert records[0]["entityIndex"] == 68632782
    assert "ifIndex" not in records[0]
    assert records[0]["interface"] == "XGigabitEthernet0/0/1"


def test_collect_librenms_optical_uses_local_probe_and_reports_credentials(monkeypatch):
    probe_calls = []

    monkeypatch.setattr(
        "services.vault_service.resolve_collector_credentials",
        lambda device: {
            "snmp": {
                "configured": True,
                "server": device["ip_address"],
                "community": "test-community",
                "port": 161,
                "version": "2c",
            }
        },
    )

    async def fake_probe(server, community, port, version, device):
        probe_calls.append((server, community, port, version, device))
        return {
            "identity": {
                "status": "identified",
                "vendor": "Aruba",
                "librenms_os_key": "arubaos-cx",
                "librenms_rule_id": "rule-1",
            },
            "librenms_rule": {
                "os_key": "arubaos-cx",
                "compatibility": {"hardware_level": "supported"},
                "hardware_definitions": {
                    "sensors": [{"source_class": "dbm", "group": "Optical Rx power"}],
                },
            },
            "hardware_sensors": [{
                "quality": "good",
                "measurement_type": "optical_power_dbm",
                "value": -10.5,
                "sensor_name": "",
                "entity_name": "1/1/1",
                "group_name": "Optical Rx power",
                "index": [7, 1],
                "index_labels": {"if_index": 7},
                "metadata": {"raw_definition": {"descr": "Rx lane 1 power"}},
            }],
        }

    monkeypatch.setattr(optical, "_probe_local_hardware", fake_probe)
    device = {"vendor": "Aruba", "platform": "aruba_aoscx", "ip_address": "192.0.2.10"}

    result = optical.collect_librenms_optical(device)

    assert result["success"] is True
    assert result["adapter"]["mode"] == "librenms"
    assert result["adapter"]["os_key"] == "arubaos-cx"
    assert result["records"][0]["rx_power_dbm"] == pytest.approx(-10.5)
    assert probe_calls == [("192.0.2.10", "test-community", 161, "2c", device)]

    monkeypatch.setattr(
        "services.vault_service.resolve_collector_credentials",
        lambda _device: {"snmp": {"configured": False}},
    )
    missing = optical.collect_librenms_optical(device)
    assert missing["success"] is False
    assert missing["error_code"] == "SNMP_CREDENTIALS_MISSING"
    assert missing["records"] == []
