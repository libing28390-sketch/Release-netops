from __future__ import annotations

import json
from pathlib import Path

from core.textfsm import list_templates, smart_parse_cli
from services.operational_data_service import resolve_textfsm_template_for_command
from services.platform_registry_service import (
    PARAMETERIZED_ACTION_DEFINITIONS,
    _coerce_field_types,
    _normalize_records,
    get_profile_action_commands,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "cli" / "h3c" / "h3c_comware"
V5_BGP_DIR = FIXTURES / "display_bgp_vpnv4_vpn_instance_routing_table"
V7_INTERFACE_DIR = FIXTURES / "display_interface_brief"
V5_BGP_NAME = "s3610_s5510_release_5309_vpn1"
V7_INTERFACE_NAME = "wbc580_g2_comware_v7"
V5_BGP_TEMPLATE = "h3c_comware_v5_display_bgp_vpnv4_vpn_instance_routing_table.textfsm"
V7_INTERFACE_TEMPLATE = "h3c_comware_v7_display_interface_brief.textfsm"
V5_BGP_COMMAND = "display bgp vpnv4 vpn-instance vpn1 routing-table"
V7_INTERFACE_COMMAND = "display interface brief"


def _read_fixture(directory: Path, name: str) -> tuple[str, dict[str, object]]:
    output = (directory / f"{name}.txt").read_text(encoding="utf-8")
    metadata = json.loads((directory / f"{name}.meta.json").read_text(encoding="utf-8"))
    return output, metadata


def test_official_s3610_s5510_comware_v5_vpn_bgp_table_resolves_to_quick_ops_action():
    output, metadata = _read_fixture(V5_BGP_DIR, V5_BGP_NAME)
    assert metadata["source_type"] == "official_vendor_documentation"
    assert metadata["platform_version"] == "V5.20"
    assert metadata["documentation_release"] == "Release 5309-6W100"
    assert metadata["software_version"] == "unknown"
    assert metadata["command"] == V5_BGP_COMMAND

    parsed = smart_parse_cli(
        output,
        V5_BGP_COMMAND,
        platform=str(metadata["parser_platform"]),
        version=str(metadata["software_version"]),
    )
    assert parsed["success"] is True, parsed.get("message")
    assert parsed["template"] == V5_BGP_TEMPLATE
    assert len(parsed["data"]) == 5
    assert parsed["data"][0] == {
        "STATUS": "*>i",
        "PREFIX": "10.0.0.0",
        "NEXT_HOP": "1.1.1.1",
        "METRIC": "0",
        "LOCAL_PREF": "100",
        "WEIGHT": "0",
        "AS_PATH": "",
        "ORIGIN": "i",
    }
    assert parsed["data"][2] == {
        "STATUS": "*>",
        "PREFIX": "20.0.0.0",
        "NEXT_HOP": "10.1.1.1",
        "METRIC": "0",
        "LOCAL_PREF": "",
        "WEIGHT": "99",
        "AS_PATH": "200",
        "ORIGIN": "?",
    }

    action = next(
        item for item in PARAMETERIZED_ACTION_DEFINITIONS
        if item["action_code"] == "get_bgp_routes_vrf"
    )
    profile = {"platform_code": "h3c_comware_v5", "parser_platform": "h3c_comware"}
    commands = get_profile_action_commands(profile)
    expected_command = "display bgp vpnv4 vpn-instance {{vrf}} routing-table"
    assert commands["get_bgp_routes_vrf"] == expected_command
    device = {
        "platform": "h3c_comware",
        "vendor": "H3C",
        "profile_platform_code": "h3c_comware_v5",
        "profile_parser_platform": "h3c_comware",
        "profile_connection_driver": "hp_comware",
    }
    resolved = resolve_textfsm_template_for_command(
        device,
        commands["get_bgp_routes_vrf"],
        action_code="get_bgp_routes_vrf",
        templates_catalog=list_templates(vendor_filter="h3c"),
    )
    assert resolved is not None
    assert resolved["textfsm_template"] == V5_BGP_TEMPLATE
    v7_device = {
        "platform": "h3c_comware",
        "vendor": "H3C",
        "profile_platform_code": "h3c_comware_v7",
        "profile_parser_platform": "h3c_comware_v7",
        "profile_connection_driver": "hp_comware",
    }
    assert resolve_textfsm_template_for_command(
        v7_device,
        commands["get_bgp_routes_vrf"],
        action_code="get_bgp_routes_vrf",
        templates_catalog=list_templates(vendor_filter="h3c"),
    ) is None

    records = _normalize_records(
        parsed["data"],
        int(action["max_records"]),
        expected_fields=set(action["fields"])
        | set(action.get("optional_fields") or [])
        | set(action.get("field_types") or {}),
    )
    _coerce_field_types(records, {"types": action.get("field_types") or {}})
    required = set(action["fields"])
    assert all(required <= record.keys() for record in records)
    assert records[0]["prefix"] == "10.0.0.0"
    assert records[0]["next_hop"] == "1.1.1.1"
    assert records[0]["metric"] == 0
    assert records[2]["as_path"] == "200"
    assert records[2]["origin"] == "?"


def test_official_wbc580_g2_comware_v7_mixed_interface_brief_resolves_quick_ops_action():
    output, metadata = _read_fixture(V7_INTERFACE_DIR, V7_INTERFACE_NAME)
    assert metadata["source_type"] == "official_vendor_documentation"
    assert metadata["platform_version"] == "V7"
    assert metadata["software_version"] == "unknown"
    assert metadata["command"] == V7_INTERFACE_COMMAND

    parsed = smart_parse_cli(
        output,
        V7_INTERFACE_COMMAND,
        platform=str(metadata["parser_platform"]),
        version=str(metadata["software_version"]),
    )
    assert parsed["success"] is True, parsed.get("message")
    assert parsed["template"] == V7_INTERFACE_TEMPLATE
    assert len(parsed["data"]) == 12
    records = {str(record["INTERFACE"]): record for record in parsed["data"]}
    assert records["Loop0"]["PROTOCOL"] == "UP(s)"
    assert records["Vlan999"]["MAIN_IP"] == "192.168.1.42"
    assert records["BAGG1"]["SPEED"] == "auto"
    assert records["BAGG1"]["TYPE"] == "A"
    assert records["GE1/0/1"]["LINK"] == "UP"
    assert records["GE1/0/1"]["SPEED"] == "1G"
    assert records["XGE1/0/6"]["LINK"] == "DOWN"

    profile = {"platform_code": "h3c_comware", "parser_platform": "h3c_comware"}
    commands = get_profile_action_commands(profile)
    assert commands["get_interface_brief"] == V7_INTERFACE_COMMAND
    device = {
        "platform": "h3c_comware",
        "vendor": "H3C",
        "profile_platform_code": "h3c_comware",
        "profile_parser_platform": "h3c_comware_v7",
        "profile_connection_driver": "hp_comware",
    }
    resolved = resolve_textfsm_template_for_command(
        device,
        commands["get_interface_brief"],
        action_code="get_interface_brief",
        templates_catalog=list_templates(vendor_filter="h3c"),
    )
    assert resolved is not None
    assert resolved["textfsm_template"] == V7_INTERFACE_TEMPLATE
