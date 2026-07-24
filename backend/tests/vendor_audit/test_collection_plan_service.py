from __future__ import annotations

from services.collection_plan_service import resolve_collection_plan, should_collect, validate_policy


def _device(role: str, **extra):
    return {"id": role, "hostname": role, "platform": "cisco_ios", "role": role, **extra}


def test_router_skips_l2_collectors_by_default():
    device = _device("router")
    assert should_collect(device, "arp") is True
    assert should_collect(device, "lldp") is True
    assert should_collect(device, "routes") is True
    assert should_collect(device, "mac_table") is False
    assert should_collect(device, "vlan") is False
    assert should_collect(device, "endpoint_location") is False


def test_access_switch_skips_routing_collectors_by_default():
    device = _device("access")
    assert should_collect(device, "mac_table") is True
    assert should_collect(device, "vlan") is True
    assert should_collect(device, "lldp") is True
    assert should_collect(device, "arp") is False
    assert should_collect(device, "routes") is False
    assert should_collect(device, "bgp") is False


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
    assert normalized == {"collectors": {"mac_table": False}, "ignored_keys": ["future_collector"]}

    try:
        validate_policy({"collectors": {"mac_table": "sometimes"}})
    except ValueError as exc:
        assert "mac_table" in str(exc)
    else:
        raise AssertionError("invalid collector policy should fail validation")
