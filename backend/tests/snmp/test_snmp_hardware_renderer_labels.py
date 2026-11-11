import re

from services.snmp_hardware_inventory_service import render_hardware_metrics


DEVICE_LABELS = {
    "tenant_id": "tenant-canonical",
    "asset_id": "asset-canonical",
    "device_id": "device-canonical",
    "hostname": "ac-01",
    "site_name": "North DC",
    "vendor": "Huawei",
    "platform": "huawei_vrp",
    "role": "wireless_controller",
}

WIRELESS_INDEX_LABELS = {
    "ap_id": "ap-01",
    "ap_name": "AP-01",
    "ap_model": "WA6320-HCL",
    "ap_ip": "192.0.2.10",
    "ap_mac": "00:11:22:33:44:55",
    "ap_serial": "SERIAL-01",
    "radio_id": "radio-0",
    "radio_index": "18",
    "radio_ifindex": "10018",
    "radio_mac": "00:11:22:33:44:66",
    "radio_mode": "11ax",
    "wlan_id": "wlan-7",
    "ssid": "Nexora-Guest",
    "ssid_index": "7",
    "radio_band": "5GHz",
    "bssid": "00:11:22:33:44:77",
    "vlan_id": "207",
    "ent_physical_index": "19",
    # Sensor-supplied identity-like labels must never replace device labels.
    "tenant_id": "index-shadow-tenant",
    "asset_id": "index-shadow-asset",
    "device_id": "index-shadow-device",
    "hostname": "index-shadow-host",
    "vendor": "index-shadow-vendor",
    "role": "index-shadow-role",
}


def _labels(line: str) -> set[str]:
    label_text = line.split("{", 1)[1].rsplit("} ", 1)[0]
    return set(re.findall(r'(?:^|,)([a-zA-Z_][a-zA-Z0-9_]*)="', label_text))


def _simulated_vm_label_count(line: str) -> int:
    labels = _labels(line)
    scrape_and_system_labels = {"__name__", "job", "instance"}
    assert labels.isdisjoint(scrape_and_system_labels)
    return len(labels | scrape_and_system_labels)


def _full_sensor(*, component_class: str, measurement_type: str, sensor_key: str) -> dict:
    return {
        "tenant_id": "sensor-shadow-tenant",
        "asset_id": "sensor-shadow-asset",
        "device_id": "sensor-shadow-device",
        "hostname": "sensor-shadow-host",
        "vendor": "sensor-shadow-vendor",
        "role": "sensor-shadow-role",
        "sensor_key": sensor_key,
        "data_origin": "librenms_native",
        "native_instance_id": "instance-01",
        "native_device_id": "native-device-01",
        "native_entity_id": "native-entity-01",
        "source_type": "librenms_rule",
        "source_id": "wireless-rule-01",
        "component_class": component_class,
        "measurement_type": measurement_type,
        "series_variant": "5m",
        "sensor_name": "Radio utilization",
        "entity_name": "AP-01 radio",
        "group_name": "wireless",
        "rule_version": "rules-v4",
        "discovery_status": "success",
        "lifecycle_status": "active",
        "unit": "percent",
        "index": {"ap": 1, "radio": 0, "wlan": 7},
        "index_labels": dict(WIRELESS_INDEX_LABELS),
        "metadata": {
            "window": "5m",
            "ent_physical_index_measured": "index_shadow_type",
            "wireless_sensor_class": "utilization",
            "tenant_id": "metadata-shadow-tenant",
            "asset_id": "metadata-shadow-asset",
            "device_id": "metadata-shadow-device",
            "hostname": "metadata-shadow-host",
            "vendor": "metadata-shadow-vendor",
            "role": "metadata-shadow-role",
            "sensor_key": "metadata-shadow-sensor",
        },
        "states": {"1": "active"},
        "last_quality": "good",
        "last_value": 42.5,
        "last_raw_value": "1",
        "last_success": "2026-11-10T10:00:00+00:00",
        "enabled": True,
        "last_sample_at": None,
    }


def test_renderer_stays_within_victoriametrics_cap_with_full_wireless_metadata() -> None:
    radio_value = _full_sensor(
        component_class="wireless_radio",
        measurement_type="wireless_sensor_value",
        sensor_key="radio-utilization",
    )
    ap_state = _full_sensor(
        component_class="wireless_access_point",
        measurement_type="component_state",
        sensor_key="ap-state",
    )
    ap_state["states"] = [{"value": 1, "descr": "disconnected", "generic": 3}]
    ap_state["last_raw_value"] = "1"
    ap_state["index_labels"]["raw_index_extra"] = "ignored"
    hardware_state = _full_sensor(
        component_class="fan_state",
        measurement_type="component_state",
        sensor_key="fan-state",
    )
    hardware_state["index_labels"] = {"ent_physical_index": "9", "sensor_index": "2"}
    hardware_state["metadata"] = {
        "window": "15m",
        "ent_physical_index_measured": "entPhysicalIndex",
    }

    exposition = render_hardware_metrics(
        [radio_value, ap_state, hardware_state], DEVICE_LABELS,
    )
    metric_lines = [line for line in exposition.splitlines() if not line.startswith("#")]
    ap_state_line = next(
        line for line in metric_lines if line.startswith("nexora_hw_component_state{")
    )
    nonwireless_info_line = next(
        line for line in metric_lines
        if line.startswith("nexora_hw_sensor_info{") and 'sensor_key="fan-state"' in line
    )

    assert metric_lines
    assert max(_simulated_vm_label_count(line) for line in metric_lines) <= 30
    assert len(_labels(nonwireless_info_line)) == 27
    assert any(line.startswith("nexora_hw_sensor_quality{") for line in metric_lines)
    assert any(line.startswith("nexora_hw_sensor_last_success_timestamp_seconds{") for line in metric_lines)
    assert {"ap_id", "ap_name", "ap_model", "ap_ip", "ap_mac", "raw_state", "state_description"} <= _labels(ap_state_line)


def test_renderer_keeps_dashboard_wireless_labels_and_authoritative_identity() -> None:
    sensor = _full_sensor(
        component_class="wireless_radio",
        measurement_type="wireless_sensor_value",
        sensor_key="radio-utilization",
    )

    exposition = render_hardware_metrics([sensor], DEVICE_LABELS)
    radio_line = next(
        line for line in exposition.splitlines()
        if line.startswith("nexora_wireless_sensor_value{")
    )
    info_line = next(
        line for line in exposition.splitlines()
        if line.startswith("nexora_hw_sensor_info{")
    )

    radio_labels = _labels(radio_line)
    assert {
        "tenant_id", "asset_id", "device_id", "hostname", "site_name", "vendor", "platform", "role",
        "sensor_key", "source_type", "component_class", "measurement_type", "window", "sensor_class", "unit",
        "ap_id", "ap_mac", "ap_name", "ap_ip", "ap_model", "radio_id", "ssid", "wlan_id",
    } <= radio_labels
    assert {"ap_serial", "radio_index", "radio_ifindex", "radio_mac", "radio_mode", "ssid_index", "radio_band", "bssid", "vlan_id"}.isdisjoint(radio_labels)
    assert "ent_physical_index" not in radio_labels
    assert "measured_entity_type" not in radio_labels
    assert len(radio_labels) == 27
    assert "rule_version" not in radio_labels

    for expected in (
        'tenant_id="tenant-canonical"',
        'asset_id="asset-canonical"',
        'device_id="device-canonical"',
        'hostname="ac-01"',
        'vendor="Huawei"',
        'ap_name="AP-01"',
    ):
        assert expected in radio_line
        assert expected in info_line
    for shadow in (
        "sensor-shadow-tenant", "index-shadow-tenant", "metadata-shadow-tenant",
        "sensor-shadow-asset", "index-shadow-asset", "metadata-shadow-asset",
        "sensor-shadow-device", "index-shadow-device", "metadata-shadow-device",
        "metadata-shadow-host", "metadata-shadow-vendor", "metadata-shadow-role",
    ):
        assert shadow not in radio_line
        assert shadow not in info_line

    info_labels = _labels(info_line)
    assert {"sensor_name", "group", "index", "source_id", "rule_version"} <= info_labels
    assert {"ap_id", "ap_name", "ap_model", "ap_ip", "ap_mac"} <= info_labels
    assert len(info_labels) <= 30 - 3
