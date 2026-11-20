from __future__ import annotations

from services import interface_collection_service, ip_locator_service
from services.operational_data_service import _resolve_categories
from services.scheduler_service import _select_nsot_scope_device_ids


def test_layer2_template_filters_arp_and_route_command_categories():
    device = {
        "id": "access-sw-1",
        "role": "Access Switch",
        "platform": "h3c_comware",
        "collection_policy_json": '{"template":"layer2_switch","collectors":{}}',
    }

    categories = _resolve_categories(
        ["neighbors", "arp", "mac_table", "vlan", "routing_table", "bgp"],
        device_info=device,
    )

    assert categories == ["neighbors", "mac_table", "vlan"]


def test_interface_status_sweep_selects_devices_allowed_by_template():
    devices = [
        {
            "id": "access-sw-1",
            "hostname": "access-sw-1",
            "role": "Access Switch",
            "status": "online",
            "collection_policy_json": '{"template":"layer2_switch","collectors":{}}',
        },
        {
            "id": "custom-disabled-1",
            "hostname": "custom-disabled-1",
            "role": "switch",
            "status": "online",
            "collection_policy_json": '{"template":"custom","collectors":{"interface_status":false,"vlan":false}}',
        },
        {
            "id": "vlan-only-1",
            "hostname": "vlan-only-1",
            "role": "switch",
            "status": "online",
            "collection_policy_json": '{"template":"custom","collectors":{"interface_status":false,"vlan":true}}',
        },
    ]

    selected = interface_collection_service._select_interface_collection_devices(devices)

    assert sorted(selected) == ["access-sw-1", "vlan-only-1"]


def test_prefix_projection_skips_devices_with_explicitly_disabled_template():
    rows = [
        {
            "device_id": "access-sw-1",
            "role": "Access Switch",
            "platform": "h3c_comware",
            "collection_policy_json": '{"template":"layer2_switch","collectors":{}}',
        },
        {
            "device_id": "no-prefix-1",
            "role": "switch",
            "platform": "cisco_ios",
            "collection_policy_json": '{"template":"custom","collectors":{"prefix_projection":false}}',
        },
    ]

    selected = ip_locator_service._filter_prefix_projection_devices(rows)

    assert [row["device_id"] for row in selected] == ["access-sw-1"]


def test_nsot_scheduled_scope_filters_online_devices_for_bulk_modes():
    online_devices = [
        {"id": "access-1", "status": "online", "site": "WH-DC-02", "role": "Access Switch", "device_category": "Network", "platform": "h3c_comware", "ip_address": "192.0.2.11"},
        {"id": "gateway-1", "status": "online", "site": "WH-DC-02", "role": "Router", "device_category": "Network", "platform": "huawei_vrp", "ip_address": "192.0.2.1"},
        {"id": "access-2", "status": "online", "site": "HQ", "role": "Access Switch", "device_category": "Network", "platform": "h3c_comware", "ip_address": "192.0.2.12"},
        {"id": "server-1", "status": "online", "site": "HQ", "role": "Server", "device_category": "Server", "platform": "linux", "ip_address": "192.0.2.50"},
        {"id": "legacy-site-switch", "status": "online", "site": "", "site_id": "site-legacy-1", "role": "Access Switch", "device_category": "Network", "platform": "h3c_comware", "ip_address": "192.0.2.13"},
    ]

    assert _select_nsot_scope_device_ids({"device_scope": "all"}, online_devices) == [
        "access-1", "access-2", "gateway-1", "legacy-site-switch", "server-1",
    ]
    assert _select_nsot_scope_device_ids(
        {"device_scope": "site", "device_filter": "WH-DC-02"}, online_devices
    ) == ["access-1", "gateway-1"]
    assert _select_nsot_scope_device_ids(
        {"device_scope": "role", "device_filter": "Access Switch"}, online_devices
    ) == ["access-1", "access-2", "legacy-site-switch"]
    assert _select_nsot_scope_device_ids(
        {"device_scope": "composite", "device_filter": '{"site":"WH-DC-02","platform":"h3c_comware"}'},
        online_devices,
    ) == ["access-1"]
    assert _select_nsot_scope_device_ids(
        {"device_scope": "composite", "device_filter": '{"category":"Network"}'}, online_devices
    ) == ["access-1", "access-2", "gateway-1", "legacy-site-switch"]
    assert _select_nsot_scope_device_ids(
        {"device_scope": "composite", "device_filter": '{"category":"Server"}'}, online_devices
    ) == ["server-1"]
    assert _select_nsot_scope_device_ids(
        {"device_scope": "composite", "device_filter": '{"site":"site-legacy-1"}'}, online_devices
    ) == ["legacy-site-switch"]
    assert _select_nsot_scope_device_ids(
        {"device_scope": "composite", "device_filter": "not-json"}, online_devices
    ) == []
    assert _select_nsot_scope_device_ids(
        {"device_scope": "composite", "device_filter": "{}"}, online_devices
    ) == []
    assert _select_nsot_scope_device_ids(
        {"device_scope": "composite", "device_filter": '{"unknown":"value"}'}, online_devices
    ) == []
    assert _select_nsot_scope_device_ids(
        {"device_scope": "ip", "device_filter": "192.0.2.1,192.0.2.12"}, online_devices
    ) == ["access-2", "gateway-1"]
    assert _select_nsot_scope_device_ids(
        {"device_scope": "ids", "device_filter": "gateway-1,offline-device"}, online_devices
    ) == ["gateway-1"]
    assert _select_nsot_scope_device_ids(
        {"device_scope": "tag", "device_filter": "{}"}, online_devices, {"gateway-1", "offline-device"}
    ) == ["gateway-1"]
    assert _select_nsot_scope_device_ids(
        {"device_scope": "site", "device_filter": "NO-SITE"}, online_devices
    ) == []


def test_scoped_endpoint_projection_keeps_only_selected_device_owners():
    endpoints = [
        {"ip": "192.0.2.11", "device_id": "access-1"},
        {"ip": "192.0.2.12", "device_id": "access-2"},
    ]

    selected = ip_locator_service._filter_endpoints_for_device_scope(endpoints, {"access-1"})

    assert selected == [{"ip": "192.0.2.11", "device_id": "access-1"}]
    assert ip_locator_service._filter_endpoints_for_device_scope(endpoints, None) == endpoints
