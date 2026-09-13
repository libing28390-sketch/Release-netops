from __future__ import annotations

import json

import pytest

from services.collection_plan_service import (
    COLLECTORS,
    collection_templates,
    explicit_collector_override,
    resolve_collection_plan,
    should_collect,
    validate_policy,
)


def _device(role: str, **extra):
    return {"id": role, "hostname": role, "platform": "cisco_ios", "role": role, **extra}


def test_l3_network_device_collects_route_table_by_default():
    device = _device("router")
    assert should_collect(device, "reachability") is True
    assert should_collect(device, "health_metrics") is True
    assert should_collect(device, "interface_status") is True
    assert should_collect(device, "interface_ip") is True
    assert should_collect(device, "prefix_projection") is True
    assert should_collect(device, "arp") is True
    assert should_collect(device, "lldp") is False
    assert should_collect(device, "routes") is True
    assert should_collect(device, "bgp") is True
    assert should_collect(device, "mac_table") is False
    assert should_collect(device, "vlan") is False
    assert should_collect(device, "endpoint_location") is False


def test_access_switch_also_uses_basic_inventory_only_by_default():
    device = _device("access")
    assert should_collect(device, "interface_status") is True
    assert should_collect(device, "interface_ip") is True
    assert should_collect(device, "mac_table") is False
    assert should_collect(device, "vlan") is False
    assert should_collect(device, "lldp") is False
    assert should_collect(device, "arp") is False
    assert should_collect(device, "routes") is False
    assert should_collect(device, "bgp") is False


def test_server_does_not_collect_route_table_by_default():
    device = _device("server", platform="linux")
    assert should_collect(device, "routes") is False
    assert should_collect(device, "bgp") is False
    assert should_collect(device, "interface_ip") is False
    assert should_collect(device, "prefix_projection") is False


def test_firewall_collects_route_table_but_not_bgp_by_default():
    device = _device("firewall", platform="h3c_comware")
    assert should_collect(device, "routes") is True
    assert should_collect(device, "arp") is True
    assert should_collect(device, "bgp") is False


def test_l3_device_can_explicitly_disable_bgp_discovery():
    device = _device(
        "distribution",
        collection_policy_json='{"collectors":{"bgp":false}}',
    )
    assert should_collect(device, "routes") is True
    assert should_collect(device, "bgp") is False


def test_access_switch_can_explicitly_enable_arp():
    device = _device(
        "access",
        collection_policy_json='{"collectors":{"arp":true}}',
    )
    assert should_collect(device, "arp") is True


def test_explicit_device_policy_overrides_role_defaults():
    device = _device(
        "router",
        collection_policy_json='{"collectors":{"mac_table":"enabled","vlan":true,"lldp":false}}',
    )
    plan = resolve_collection_plan(device)
    assert plan["overrides"] == {"mac_table": True, "vlan": True, "lldp": False}
    assert plan["effective"]["mac_table"] is True
    assert plan["effective"]["vlan"] is True
    assert plan["effective"]["lldp"] is False


def test_policy_validation_rejects_invalid_values_and_reports_unknown_keys():
    normalized = validate_policy({"collectors": {"mac_table": "disabled", "future_collector": True}})
    assert normalized == {
        "template": None,
        "collectors": {"mac_table": False},
        "ignored_keys": ["future_collector"],
    }

    try:
        validate_policy({"collectors": {"mac_table": "sometimes"}})
    except ValueError as exc:
        assert "mac_table" in str(exc)
    else:
        raise AssertionError("invalid collector policy should fail validation")


@pytest.mark.parametrize(
    ("template", "expected_enabled", "expected_disabled"),
    [
        (
            "role_default",
            {
                "reachability",
                "health_metrics",
                "interface_status",
                "interface_ip",
                "arp",
                "routes",
                "bgp",
                "prefix_projection",
            },
            {"lldp", "mac_table", "vlan", "ospf", "endpoint_location"},
        ),
        (
            "basic",
            {"reachability", "health_metrics", "interface_status", "interface_ip", "prefix_projection"},
            {"lldp", "arp", "mac_table", "vlan", "routes", "bgp", "endpoint_location"},
        ),
        (
            "layer2_switch",
            {
                "reachability",
                "health_metrics",
                "interface_status",
                "interface_ip",
                "lldp",
                "mac_table",
                "vlan",
                "endpoint_location",
                "prefix_projection",
            },
            {"arp", "routes", "bgp", "ospf", "eigrp", "isis", "rip", "bfd"},
        ),
        (
            "layer3_gateway",
            {
                "reachability",
                "health_metrics",
                "interface_status",
                "interface_ip",
                "lldp",
                "arp",
                "routes",
                "prefix_projection",
            },
            {"mac_table", "vlan", "bgp", "ospf", "eigrp", "isis", "rip", "bfd"},
        ),
        (
            "firewall",
            {
                "reachability",
                "health_metrics",
                "interface_status",
                "interface_ip",
                "lldp",
                "arp",
                "routes",
                "prefix_projection",
            },
            {"mac_table", "vlan", "bgp", "ospf", "endpoint_location"},
        ),
        (
            "wireless",
            {"reachability", "health_metrics", "interface_status", "interface_ip", "lldp", "prefix_projection"},
            {"arp", "mac_table", "vlan", "routes", "bgp", "endpoint_location"},
        ),
        (
            "custom",
            {
                "reachability",
                "health_metrics",
                "interface_status",
                "interface_ip",
                "arp",
                "routes",
                "bgp",
                "prefix_projection",
            },
            {"lldp", "mac_table", "vlan", "ospf", "endpoint_location"},
        ),
    ],
)
def test_each_template_resolves_complete_expected_collector_matrix(
    template: str, expected_enabled: set[str], expected_disabled: set[str]
):
    device = _device(
        "router",
        collection_policy_json=json.dumps({"template": template, "collectors": {}}),
    )
    plan = resolve_collection_plan(device)

    assert plan["template_id"] == template
    assert set(plan["defaults"]) == set(COLLECTORS)
    assert all(plan["effective"][collector] is True for collector in expected_enabled)
    assert all(plan["effective"][collector] is False for collector in expected_disabled)
    assert plan["template_name_zh"]
    assert plan["template_name_en"]


@pytest.mark.parametrize(
    ("role", "canonical"),
    [
        ("Core Switch", "core"),
        ("Aggregation Switch", "distribution"),
        ("Access Switch", "access"),
        ("Wireless AC", "wlc"),
        ("Wireless AP", "ap"),
        ("Load Balancer", "load-balancer"),
        ("L3 Switch", "l3switch"),
    ],
)
def test_role_aliases_are_canonicalized_without_using_role_as_platform(role: str, canonical: str):
    plan = resolve_collection_plan(_device(role, platform="h3c_comware"))

    assert plan["role"] == canonical
    assert plan["platform"] == "h3c_comware"


def test_template_defaults_then_explicit_overrides_are_applied():
    device = _device(
        "Access Switch",
        collection_policy_json=(
            '{"template":"layer2_switch","collectors":'
            '{"mac_table":false,"arp":true,"routes":true}}'
        ),
    )

    plan = resolve_collection_plan(device)

    assert plan["template_id"] == "layer2_switch"
    assert plan["defaults"]["mac_table"] is True
    assert plan["overrides"] == {"mac_table": False, "arp": True, "routes": True}
    assert plan["effective"]["mac_table"] is False
    assert plan["effective"]["arp"] is True
    assert plan["effective"]["routes"] is True


def test_template_protocol_defaults_are_not_explicit_denials():
    template_only = _device(
        "router",
        collection_policy_json='{"template":"layer2_switch","collectors":{}}',
    )
    explicit_deny = _device(
        "router",
        collection_policy_json='{"template":"layer2_switch","collectors":{"ospf":false}}',
    )

    assert should_collect(template_only, "ospf") is False
    assert explicit_collector_override(template_only, "ospf") is None
    assert explicit_collector_override(explicit_deny, "ospf") is False


def test_role_default_arp_matches_l3_role_and_svi_candidate_rules():
    assert should_collect(_device("router"), "arp") is True
    assert should_collect(_device("access"), "arp") is False
    assert should_collect(_device("access", _has_svi=True), "arp") is True
    assert should_collect(
        _device("access", _has_svi=True, collection_policy_json='{"collectors":{"arp":false}}'),
        "arp",
    ) is False


def test_old_policy_formats_resolve_as_role_default():
    role_default = resolve_collection_plan(_device("router", collection_policy_json="{}"))
    legacy_collectors = resolve_collection_plan(
        _device("router", collection_policy_json='{"collectors":{"lldp":true}}')
    )

    assert role_default["template_id"] == "role_default"
    assert legacy_collectors["template_id"] == "role_default"
    assert legacy_collectors["effective"]["routes"] is True
    assert legacy_collectors["effective"]["lldp"] is True
    assert legacy_collectors["overrides"] == {"lldp": True}


def test_validate_policy_rejects_unknown_template_and_exposes_template_catalog():
    with pytest.raises(ValueError, match="unknown collection template"):
        validate_policy({"template": "magic", "collectors": {}})

    assert {entry["id"] for entry in collection_templates()} == {
        "role_default",
        "basic",
        "layer2_switch",
        "layer3_gateway",
        "firewall",
        "wireless",
        "custom",
    }
