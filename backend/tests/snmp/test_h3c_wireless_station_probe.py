from __future__ import annotations

import asyncio

from services import snmp_hardware_inventory_service as inventory
from services import snmp_hardware_probe_service as probe
from services.monitoring_oid_catalog import BUILTIN_OID_CATALOG


def _walk_from(mapping, calls=None):
    async def walk(_ip, _community, oid, _port, _version):
        if calls is not None:
            calls.append(oid)
        return list(mapping.get(oid, []))

    return walk


def test_h3c_station_associate_table_maps_fixed_mac_index_and_requested_columns(monkeypatch):
    suffix = "0.17.34.51.68.85"
    station_mac = "00:11:22:33:44:55"
    station_values = {
        probe._H3C_DOT11_STATION_IP_OID: "192.0.2.50",
        probe._H3C_DOT11_STATION_USERNAME_OID: "operator-fixture",
        probe._H3C_DOT11_STATION_TX_RATE_SET_OID: "6(B), 12(B), 24(B)",
        probe._H3C_DOT11_STATION_SSID_OID: "corp-fixture",
    }
    rows = {oid: [(suffix, value)] for oid, value in station_values.items()}
    ap_id = "AP-01"
    ap_suffix = ".".join(str(value) for value in (len(ap_id), *ap_id.encode("ascii")))
    rows[f"{probe._H3C_DOT11_AP_OBJECT_TABLE}.8"] = [(ap_suffix, ap_id)]
    rows[probe._H3C_DOT11_STATION_AP_ID_OID] = [(suffix, ap_id)]
    rows[probe._H3C_DOT11_STATION_RADIO_ID_OID] = [(suffix, "1")]
    rows[probe._H3C_DOT11_STATION_WLAN_ID_OID] = [(suffix, "2")]
    rows[probe._H3C_DOT11_STATION_VLAN_OID] = [(suffix, "200")]
    calls: list[str] = []

    async def no_scalars(*_args):
        return {}

    monkeypatch.setattr(probe, "_get_many", no_scalars)
    result = asyncio.run(probe._probe_h3c_comware_wireless(
        "192.0.2.1", "public", 161,
        rule={"id": "h3c-wireless-test", "source_commit": "fixture"},
        version="2c", walk_func=_walk_from(rows, calls),
    ))

    station_sensors = [
        sensor for sensor in result["sensors"]
        if sensor["component_class"] == "wireless_station"
    ]
    assert {sensor["series_variant"] for sensor in station_sensors} == {
        "station_ip", "username", "tx_rate_set", "ssid",
    }
    assert {sensor["oid"] for sensor in station_sensors} == set(station_values)
    by_attribute = {sensor["series_variant"]: sensor for sensor in station_sensors}
    expected_values = {
        "station_ip": station_values[probe._H3C_DOT11_STATION_IP_OID],
        "username": station_values[probe._H3C_DOT11_STATION_USERNAME_OID],
        "tx_rate_set": station_values[probe._H3C_DOT11_STATION_TX_RATE_SET_OID],
        "ssid": station_values[probe._H3C_DOT11_STATION_SSID_OID],
    }
    for attribute, expected in expected_values.items():
        sensor = by_attribute[attribute]
        assert sensor["index"] == [0, 17, 34, 51, 68, 85]
        assert sensor["index_labels"]["ap_name"] == ap_id
        assert sensor["index_labels"]["radio_id"] == "1"
        assert sensor["index_labels"]["wlan_id"] == "2"
        assert sensor["index_labels"]["vlan_id"] == "200"
        assert sensor["raw_value"] == expected
        assert sensor["value"] is None
        assert sensor["quality"] == "good"
        assert sensor["metadata"]["station_mac"] == station_mac
        assert sensor["metadata"]["station_attributes"] == {attribute: expected}
        assert "username" not in sensor["index_labels"]

    current_station_sensors = [
        {
            **sensor,
            "tenant_id": "tenant-fixture",
            "asset_id": "asset-fixture",
            "device_id": "device-fixture",
            "last_quality": "good",
            "last_value": sensor["value"],
            "last_raw_value": sensor["raw_value"],
            "last_success": "2026-10-06T12:00:00Z",
            "discovery_status": "present",
            "lifecycle_status": "active",
            "enabled": True,
        }
        for sensor in station_sensors
    ]
    metrics_text = inventory.render_hardware_metrics(
        current_station_sensors,
        {
            "device_id": "device-fixture", "tenant_id": "tenant-fixture",
            "asset_id": "asset-fixture", "hostname": "wlc-fixture",
            "site_name": "site-fixture", "vendor": "h3c", "platform": "comware",
            "role": "wireless_controller",
        },
    )
    station_metric_lines = [
        line for line in metrics_text.splitlines()
        if line.startswith("nexora_wireless_station_info{")
    ]
    assert len(station_metric_lines) == 1
    station_metric = station_metric_lines[0]
    assert station_metric.endswith(" 1")
    for label in (
        'tenant_id="tenant-fixture"', 'asset_id="asset-fixture"',
        'device_id="device-fixture"', 'hostname="wlc-fixture"',
        'site_name="site-fixture"', 'vendor="h3c"', 'platform="comware"',
        'role="wireless_controller"', f'station_mac="{station_mac}"',
        'station_ip="192.0.2.50"', 'ap_name="AP-01"', 'ssid="corp-fixture"',
        'radio_id="1"', 'wlan_id="2"', 'vlan_id="200"',
    ):
        assert label in station_metric
    assert "operator-fixture" not in metrics_text
    assert "username=" not in metrics_text
    assert "tx_rate_set=" not in metrics_text

    stale_metrics_text = inventory.render_hardware_metrics(
        [{**sensor, "last_quality": "stale"} for sensor in current_station_sensors],
        {"device_id": "device-fixture"},
    )
    assert "nexora_wireless_station_info{" not in stale_metrics_text

    category = next(
        item for item in result["category_results"]
        if item["component_class"] == "wireless_station"
    )
    assert category["status"] == "success"
    assert category["coverage_complete"] is True
    assert set(station_values) <= set(calls)


def test_h3c_station_catalog_registers_station_mib_and_table_walk_without_scalar_suffix():
    module = next(item for item in BUILTIN_OID_CATALOG if item["module_key"] == "h3c_wireless")
    config = module["variant"]["oid_config"]
    assert "HH3C-DOT11-STATION-MIB" in config["mib_sources"]
    assert "https://www.h3c.com/en/d_202604/2834085_294551_0.htm" in config["source_urls"]
    assert "https://www.h3c.com/en/d_202606/2850312_294551_0.htm" in config["source_urls"]
    assert probe._H3C_DOT11_STATION_TABLE in config["walk"]
    assert probe._H3C_DOT11_STATION_AP_RELATION_TABLE in config["walk"]
    assert not any(oid.endswith(".0") for oid in config["walk"])
    assert all(oid.endswith(".0") for oid in config["get"])
    catalog_metrics = {metric["name"]: metric for metric in config["metrics"]}
    for metric_name in (
        "hh3cDot11StationVlanId", "hh3cDot11CurrAPID",
        "hh3cDot11CurrRadioID", "hh3cDot11CurrWlanID",
    ):
        assert catalog_metrics[metric_name]["indexes"][0]["labelname"] == "station_mac"


def test_h3c_station_metric_keeps_empty_ap_name_when_relation_is_missing(monkeypatch):
    suffix = "0.17.34.51.68.85"
    rows = {
        probe._H3C_DOT11_STATION_IP_OID: [(suffix, "192.0.2.50")],
        probe._H3C_DOT11_STATION_SSID_OID: [(suffix, "corp-fixture")],
    }

    async def no_scalars(*_args):
        return {}

    monkeypatch.setattr(probe, "_get_many", no_scalars)
    result = asyncio.run(probe._probe_h3c_comware_wireless(
        "192.0.2.1", "public", 161,
        rule={"id": "h3c-wireless-test", "source_commit": "fixture"},
        version="2c", walk_func=_walk_from(rows),
    ))
    station_sensors = [
        {
            **sensor,
            "last_quality": "good",
            "last_raw_value": sensor["raw_value"],
            "last_success": "2026-10-06T12:00:00Z",
            "discovery_status": "present",
            "lifecycle_status": "active",
            "enabled": True,
        }
        for sensor in result["sensors"]
        if sensor["component_class"] == "wireless_station"
    ]
    metrics_text = inventory.render_hardware_metrics(
        station_sensors, {"device_id": "device-fixture"},
    )
    station_metric = next(
        line for line in metrics_text.splitlines()
        if line.startswith("nexora_wireless_station_info{")
    )
    assert 'ap_name=""' in station_metric
    assert 'radio_id=""' in station_metric
    assert 'wlan_id=""' in station_metric
    assert 'vlan_id=""' in station_metric


def test_h3c_radio_table_collects_documented_type_status_ssid_and_signal_columns(monkeypatch):
    ap_id = "AP-01"
    ap_octets = [len(ap_id), *ap_id.encode("ascii")]
    ap_suffix = ".".join(str(value) for value in ap_octets)
    radio_suffix = f"{ap_suffix}.1"
    ap_name_oid = f"{probe._H3C_DOT11_AP_OBJECT_TABLE}.8"
    radio_values = {
        10: "30",
        30: "3",
        31: "1",
        32: "corp-main, guest",
        33: "-62",
        34: "-48",
        35: "-79",
        26: "45",
    }
    rows = {ap_name_oid: [(ap_suffix, ap_id)]}
    for column, value in radio_values.items():
        rows[f"{probe._H3C_DOT11_AP_RADIO_TABLE}.{column}"] = [(radio_suffix, value)]

    async def no_scalars(*_args):
        return {}

    monkeypatch.setattr(probe, "_get_many", no_scalars)
    result = asyncio.run(probe._probe_h3c_comware_wireless(
        "192.0.2.1", "public", 161,
        rule={"id": "h3c-wireless-test", "source_commit": "fixture"},
        version="2c", walk_func=_walk_from(rows),
    ))

    radio_sensors = {
        sensor["series_variant"]: sensor
        for sensor in result["sensors"]
        if sensor["component_class"] == "wireless_radio"
    }
    expected = {
        "radio_resource_usage": (10, "30", 30.0),
        "channel_utilization": (26, "45", 45.0),
        "radio_type_code": (30, "3", 3.0),
        "radio_oper_code": (31, "1", 1.0),
        "signal_strength_average_raw": (33, "-62", -62.0),
        "signal_strength_max_raw": (34, "-48", -48.0),
        "signal_strength_min_raw": (35, "-79", -79.0),
    }
    for variant, (column, raw_value, value) in expected.items():
        sensor = radio_sensors[variant]
        assert sensor["oid"] == f"{probe._H3C_DOT11_AP_RADIO_TABLE}.{column}"
        assert sensor["index"] == [*ap_octets, 1]
        assert sensor["raw_value"] == raw_value
        assert sensor["value"] == value
        assert sensor["quality"] == "good"
        assert sensor["index_labels"]["ap_name"] == ap_id

    bound_ssids = radio_sensors["bound_ssids_raw"]
    assert bound_ssids["oid"] == f"{probe._H3C_DOT11_AP_RADIO_TABLE}.32"
    assert bound_ssids["measurement_type"] == "wireless_radio_attribute"
    assert bound_ssids["raw_value"] == radio_values[32]
    assert bound_ssids["value"] is None
    assert bound_ssids["quality"] == "good"
    assert bound_ssids["index_labels"]["ap_name"] == ap_id

    assert radio_sensors["radio_resource_usage"]["metadata"]["wireless_sensor_class"] == "radio-resource-usage"
    assert radio_sensors["channel_utilization"]["metadata"]["wireless_sensor_class"] == "utilization"
    radio_metrics = inventory.render_hardware_metrics(
        [
            {
                **radio_sensors[variant],
                "last_value": radio_sensors[variant]["value"],
                "last_raw_value": radio_sensors[variant]["raw_value"],
                "last_quality": radio_sensors[variant]["quality"],
            }
            for variant in ("radio_resource_usage", "channel_utilization")
        ],
        {"device_id": "device-fixture"},
    )
    assert 'sensor_class="radio-resource-usage"' in radio_metrics
    assert radio_metrics.count('sensor_class="utilization"') == 1


def test_h3c_radio_text_attributes_poll_as_inventory_values(monkeypatch):
    import database

    class Connection:
        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    recorded = []
    monkeypatch.setattr(database, "get_db_connection", lambda: Connection())
    monkeypatch.setattr(
        inventory,
        "record_sensor_samples_batch",
        lambda _conn, samples: recorded.extend(
            (sample["device_id"], sample["sensor_key"], sample["value"],
             sample["raw_value"], sample["quality"])
            for sample in samples
        ),
    )
    suffix = "5.65.80.45.48.49.1"
    oid = f"{probe._H3C_DOT11_AP_RADIO_TABLE}.32"
    value = "corp-main, guest"
    sensor = {
        "device_id": "device-fixture",
        "sensor_key": "radio-ssid-fixture",
        "measurement_type": "wireless_radio_attribute",
        "oid": oid,
        "index": [5, 65, 80, 45, 48, 49, 1],
        "metadata": {"poll_plan": {"kind": "direct", "oid": oid, "index": suffix}},
    }

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.1", "public", 161, "2c", [sensor],
        walk_func=_walk_from({oid: [(suffix, value)]}),
    ))

    assert result == {"good": 1, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    assert recorded == [("device-fixture", "radio-ssid-fixture", None, value, "good")]


def test_h3c_station_mac_index_requires_exactly_six_octets():
    assert probe._h3c_dot11_mac_index("0.17.34.51.68.85") == (
        "00:11:22:33:44:55", [0, 17, 34, 51, 68, 85],
    )
    assert probe._h3c_dot11_mac_index("0.17.34.51.68.85.102") is None
    assert probe._h3c_dot11_mac_index("0.17.34.51.68.999") is None


def test_h3c_station_text_attributes_poll_as_inventory_values(monkeypatch):
    import database

    class Connection:
        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    recorded = []
    monkeypatch.setattr(database, "get_db_connection", lambda: Connection())
    monkeypatch.setattr(
        inventory,
        "record_sensor_samples_batch",
        lambda _conn, samples: recorded.extend(
            (sample["device_id"], sample["sensor_key"], sample["value"],
             sample["raw_value"], sample["quality"])
            for sample in samples
        ),
    )
    suffix = "0.17.34.51.68.85"
    username = "operator-fixture"
    sensor = {
        "device_id": "device-fixture",
        "sensor_key": "station-username-fixture",
        "measurement_type": "wireless_station_attribute",
        "oid": probe._H3C_DOT11_STATION_USERNAME_OID,
        "index": [0, 17, 34, 51, 68, 85],
        "metadata": {"poll_plan": {
            "kind": "direct",
            "oid": probe._H3C_DOT11_STATION_USERNAME_OID,
            "index": suffix,
        }},
    }

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.1", "public", 161, "2c", [sensor],
        walk_func=_walk_from({probe._H3C_DOT11_STATION_USERNAME_OID: [(suffix, username)]}),
    ))

    assert result == {"good": 1, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    assert recorded == [(
        "device-fixture", "station-username-fixture", None, username, "good",
    )]
