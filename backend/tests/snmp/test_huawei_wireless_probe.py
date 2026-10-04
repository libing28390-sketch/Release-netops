from __future__ import annotations

import asyncio

from services import snmp_hardware_inventory_service as inventory
from services import snmp_hardware_probe_service as probe
from services.monitoring_compiler import render_exporter_modules
from services.monitoring_oid_catalog import BUILTIN_OID_CATALOG


def _walk_from(mapping):
    async def walk(_ip, _community, oid, _port, _version):
        return list(mapping.get(oid, []))

    return walk


def test_huawei_vrp_wireless_maps_ap_radio_vap_and_ssid_rows_by_mac_indexes(monkeypatch):
    ap_suffix = "0.17.34.51.68.85"
    radio_suffix = f"{ap_suffix}.1"
    vap_suffix = f"{radio_suffix}.7"
    ssid_suffix = "4.99.111.114.112"
    values = {
        probe._VRP_WLAN_AP_SERIAL_OID: [(ap_suffix, "SN-HW-001")],
        probe._VRP_WLAN_AP_TYPE_OID: [(ap_suffix, "AirEngine-6761")],
        probe._VRP_WLAN_AP_NAME_OID: [(ap_suffix, "AP-East-01")],
        probe._VRP_WLAN_AP_MEMORY_USAGE_OID: [(ap_suffix, "62")],
        probe._VRP_WLAN_AP_CPU_USAGE_OID: [(ap_suffix, "31")],
        probe._VRP_WLAN_RADIO_TYPE_OID: [(radio_suffix, "50")],  # a + ac + ax
        probe._VRP_WLAN_RADIO_CHANNEL_OID: [(radio_suffix, "36")],
        probe._VRP_WLAN_RADIO_MAC_OID: [(radio_suffix, "AA:BB:CC:DD:EE:FF")],
        probe._VRP_WLAN_RADIO_UTILIZATION_OID: [(radio_suffix, "48")],
        probe._VRP_WLAN_RADIO_INTERFERENCE_OID: [(radio_suffix, "12")],
        probe._VRP_WLAN_RADIO_EIRP_OID: [(radio_suffix, "18")],
        probe._VRP_WLAN_VAP_CLIENTS_OID: [(vap_suffix, "3")],
        probe._VRP_WLAN_SSID_CLIENTS_2G_OID: [(ssid_suffix, "5")],
        probe._VRP_WLAN_SSID_CLIENTS_5G_OID: [(ssid_suffix, "2")],
    }

    async def get_values(_ip, _community, oids, _port, _version):
        assert oids == {probe._VRP_WLAN_AP_COUNT_OID}
        return {probe._VRP_WLAN_AP_COUNT_OID: "1"}

    monkeypatch.setattr(probe, "_get_many", get_values)
    result = asyncio.run(probe._probe_vrp_wireless_adapter(
        "192.0.2.1", "public", 161,
        rule={"id": "huawei-wireless-fixture", "source_commit": "fixture"},
        version="2c", walk_func=_walk_from(values),
    ))

    sensors = result["sensors"]
    radio_sensors = [sensor for sensor in sensors if sensor["component_class"] == "wireless_radio"]
    assert {sensor["metadata"]["wireless_sensor_class"] for sensor in radio_sensors} == {
        "radio-type", "channel", "utilization", "interference", "tx-power",
    }
    assert len({sensor["source_id"] for sensor in radio_sensors}) == 5
    for sensor in radio_sensors:
        assert sensor["index"] == [0, 17, 34, 51, 68, 85, 1]
        assert sensor["index_labels"]["ap_mac"] == "00:11:22:33:44:55"
        assert sensor["index_labels"]["ap_name"] == "AP-East-01"
        assert sensor["index_labels"]["ap_serial"] == "SN-HW-001"
        assert sensor["index_labels"]["ap_model"] == "AirEngine-6761"
        assert sensor["index_labels"]["radio_id"] == "1"
        assert sensor["index_labels"]["radio_mac"] == "aa:bb:cc:dd:ee:ff"
        assert sensor["metadata"]["poll_plan"]["kind"] == "direct"
        assert sensor["metadata"]["poll_plan"]["index"] == radio_suffix
    radio_type = next(sensor for sensor in radio_sensors if sensor["metadata"]["wireless_sensor_class"] == "radio-type")
    assert radio_type["index_labels"]["radio_mode"] == "dot11a_ac_ax"

    vap_sensor = next(sensor for sensor in sensors if sensor["component_class"] == "wireless_bss")
    assert vap_sensor["metadata"]["wireless_sensor_class"] == "clients"
    assert vap_sensor["index"] == [0, 17, 34, 51, 68, 85, 1, 7]
    assert vap_sensor["index_labels"]["wlan_id"] == "7"
    assert vap_sensor["value"] == 3
    assert vap_sensor["metadata"]["poll_plan"]["index"] == vap_suffix

    ap_sensors = [sensor for sensor in sensors if sensor["component_class"] in {"processor", "memory_pool"}]
    assert {sensor["component_class"] for sensor in ap_sensors} == {"processor", "memory_pool"}
    assert all(sensor["index_labels"]["ap_model"] == "AirEngine-6761" for sensor in ap_sensors)
    ssid_sensors = [sensor for sensor in sensors if sensor["component_class"] == "wireless_ssid"]
    assert len(ssid_sensors) == 2
    assert {sensor["index_labels"]["radio_band"] for sensor in ssid_sensors} == {"2.4GHz", "5GHz"}
    assert {sensor["index_labels"]["ssid"] for sensor in ssid_sensors} == {"corp"}
    assert len({sensor["source_id"] for sensor in ssid_sensors}) == 2

    categories = {item["component_class"]: item for item in result["category_results"]}
    assert categories["wireless_radio"]["coverage_complete"] is True
    assert categories["wireless_bss"]["coverage_complete"] is True
    assert categories["wireless_ssid"]["coverage_complete"] is True

    metrics = inventory.render_hardware_metrics(
        [
            {
                **sensor,
                "last_value": sensor.get("value"),
                "last_raw_value": sensor.get("raw_value"),
                "last_quality": sensor.get("quality"),
            }
            for sensor in sensors
        ],
        {"asset_id": "asset-huawei"},
    )
    assert 'radio_mac="aa:bb:cc:dd:ee:ff"' in metrics
    assert 'radio_mode="dot11a_ac_ax"' in metrics
    assert 'wlan_id="7"' in metrics
    assert 'sensor_class="utilization"' in metrics
    assert 'sensor_class="clients"' in metrics


def test_huawei_wireless_catalog_uses_official_radio_vap_oids_and_mac_index_types():
    module = next(item for item in BUILTIN_OID_CATALOG if item["module_key"] == "huawei_wireless")
    config = module["variant"]["oid_config"]
    assert "HUAWEI-WLAN-AP-RADIO-MIB" in config["mib_sources"]
    expected_walks = {
        probe._VRP_WLAN_RADIO_TYPE_OID,
        probe._VRP_WLAN_RADIO_CHANNEL_OID,
        probe._VRP_WLAN_RADIO_MAC_OID,
        probe._VRP_WLAN_RADIO_UTILIZATION_OID,
        probe._VRP_WLAN_RADIO_INTERFERENCE_OID,
        probe._VRP_WLAN_RADIO_EIRP_OID,
        probe._VRP_WLAN_VAP_CLIENTS_OID,
        probe._VRP_WLAN_AP_SERIAL_OID,
        probe._VRP_WLAN_AP_TYPE_OID,
    }
    assert expected_walks <= set(config["walk"])
    assert all(not oid.endswith(".0") for oid in config["walk"])
    assert all(oid.endswith(".0") for oid in config["get"])

    metrics = {metric["name"]: metric for metric in config["metrics"]}
    assert metrics["hwWlanRadioMac"]["oid"] == probe._VRP_WLAN_RADIO_MAC_OID
    assert metrics["hwWlanRadioActualEIRP"]["unit"] == "dBm"
    assert metrics["hwWlanVapStaOnlineCnt"]["indexes"] == [
        {"labelname": "ap_mac", "type": "PhysAddress48"},
        {"labelname": "radio_index", "type": "gauge"},
        {"labelname": "wlan_id", "type": "gauge"},
    ]
    assert metrics["hwWlanSsid2gStaCnt"]["indexes"] == [
        {"labelname": "ssid", "type": "DisplayString"},
    ]

    module = next(item for item in BUILTIN_OID_CATALOG if item["module_key"] == "huawei_wireless")
    variant = dict(module["variant"])
    variant["module_id"] = module["id"]
    rendered = render_exporter_modules(
        [{"variant_key": variant["variant_key"], "enabled": True}],
        modules=[{key: value for key, value in module.items() if key != "variant"}],
        variants=[variant],
    )
    rendered_metrics = {metric["name"]: metric for metric in rendered[variant["variant_key"]]["metrics"]}
    assert rendered_metrics["hwWlanRadioChUtilizationRate"]["indexes"] == metrics[
        "hwWlanRadioChUtilizationRate"
    ]["indexes"]


def test_huawei_wireless_index_decoders_reject_length_prefixed_and_truncated_mac_indexes():
    assert probe._vrp_fixed_mac_index("0.17.34.51.68.85") == "00:11:22:33:44:55"
    assert probe._vrp_fixed_mac_index("6.0.17.34.51.68.85") is None
    assert probe._vrp_mac_table_index("0.17.34.51.68.85.1", 1) == (
        "00:11:22:33:44:55", [1],
    )
    assert probe._vrp_mac_table_index("0.17.34.51.68.85.1", 2) is None


def test_huawei_invalid_radio_utilization_and_disabled_eirp_are_not_reported_as_real_values(monkeypatch):
    ap_suffix = "0.17.34.51.68.85"
    radio_suffix = f"{ap_suffix}.1"
    values = {
        probe._VRP_WLAN_AP_NAME_OID: [(ap_suffix, "AP-01")],
        probe._VRP_WLAN_RADIO_TYPE_OID: [(radio_suffix, "2")],
        probe._VRP_WLAN_RADIO_CHANNEL_OID: [(radio_suffix, "6")],
        probe._VRP_WLAN_RADIO_MAC_OID: [(radio_suffix, "AA:BB:CC:DD:EE:FF")],
        probe._VRP_WLAN_RADIO_UTILIZATION_OID: [(radio_suffix, "255")],
        probe._VRP_WLAN_RADIO_INTERFERENCE_OID: [(radio_suffix, "8")],
        probe._VRP_WLAN_RADIO_EIRP_OID: [(radio_suffix, "255")],
    }

    async def get_values(_ip, _community, _oids, _port, _version):
        return {probe._VRP_WLAN_AP_COUNT_OID: "1"}

    monkeypatch.setattr(probe, "_get_many", get_values)
    result = asyncio.run(probe._probe_vrp_wireless_adapter(
        "192.0.2.1", "public", 161,
        rule={"id": "huawei-invalid-radio-fixture"}, version="2c",
        walk_func=_walk_from(values),
    ))

    radio_sensors = [sensor for sensor in result["sensors"] if sensor["component_class"] == "wireless_radio"]
    reported_classes = {sensor["metadata"]["wireless_sensor_class"] for sensor in radio_sensors}
    assert "utilization" not in reported_classes
    assert "tx-power" not in reported_classes
    assert {"radio-type", "channel", "interference"} <= reported_classes
    radio_category = next(item for item in result["category_results"] if item["component_class"] == "wireless_radio")
    assert radio_category["status"] == "partial"
    assert radio_category["coverage_complete"] is False
