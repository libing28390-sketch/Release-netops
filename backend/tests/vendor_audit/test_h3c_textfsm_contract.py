from pathlib import Path

from core.textfsm import (
    _find_template,
    list_templates,
    resolve_textfsm_platform,
    smart_parse_cli,
)
from services.operational_data_service import resolve_textfsm_template_for_command


FIXTURES = Path(__file__).parents[1] / "fixtures" / "cli" / "h3c"


def test_comware_v7_bgp_paths_keep_the_shared_prefix_and_wrapped_as_path():
    output = (
        "   Network          NextHop          MED     LocPrf   PrefVal Path/Ogn\n"
        "* > 192.0.2.0/24     198.51.100.1     0                0       i\n"
        "  e                 198.51.100.2     0                0       64512\n"
        "  64513 64514 i\n"
        "* e 203.0.113.0/24   198.51.100.3     0       100      0       64515i\n"
        "VPN instance: isolated\n"
        "   Network          NextHop          MED     LocPrf   PrefVal Path/Ogn\n"
        "  e                 198.51.100.4     0                0       64516i\n"
    )
    parsed = smart_parse_cli(
        output, "display bgp routing-table ipv4 unicast vpn-instance LAB",
        platform="h3c_comware_v7",
    )

    assert parsed["template"] == "h3c_comware_v7_display_bgp_routing_table_ipv4.textfsm"
    first, alternate, third = parsed["data"]
    assert first["FLAGS"] == "* >"
    assert alternate["NETWORK"] == first["NETWORK"] == "192.0.2.0/24"
    assert alternate["FLAGS"] == "e"
    assert alternate["AS_PATH"] == "64512 64513 64514 i"
    assert third["NETWORK"] == "203.0.113.0/24"
    assert not third["PATH_CONTINUATION"]


def test_comware_v7_interface_details_do_not_use_bandwidth_as_link_speed():
    output = (
        "GigabitEthernet1/0/7\nCurrent state: UP\nLine protocol state: UP\n"
        "Description: Lab uplink\n"
        "IP packet frame type: Ethernet II, hardware address: 0000-0000-0007\n"
        "Bandwidth: 123456 kbps\n1000Mbps-speed mode, full-duplex mode\n"
        "GigabitEthernet1/0/8\nCurrent state: DOWN\n"
        "Bandwidth: 1000000 kbps\nUnknown-speed mode, unknown-duplex mode\n"
    )
    parsed = smart_parse_cli(output, "display interface", platform="h3c_comware_v7")

    assert parsed["template"] == "h3c_comware_v7_display_interface.textfsm"
    first, second = parsed["data"]
    assert first["SPEED"] == "1000Mbps"
    assert first["DESCRIPTION"] == "Lab uplink"
    assert first["PROTOCOL"] == "UP"
    assert second["INTERFACE"] == "GigabitEthernet1/0/8"
    assert not second["SPEED"]
    assert not second["MAC_ADDRESS"]


def test_all_h3c_parser_inputs_resolve_to_one_public_comware_family():
    for platform in ("h3c", "comware", "h3c_comware", "h3c_comware_v3", "h3c_comware_v5", "h3c_comware_v7", "h3c_comware_v9"):
        assert resolve_textfsm_platform(platform) == "h3c_comware"
    # hp_comware is a Netmiko implementation name, not a TextFSM platform
    # alias in the Nexora catalog.
    assert resolve_textfsm_platform("hp_comware") != "h3c_comware"


def test_h3c_template_lookup_uses_the_canonical_h3c_filename():
    template = _find_template("h3c_comware", "display interface brief")
    assert template is not None
    assert template.name == "h3c_comware_v7_display_interface_brief.textfsm"


def test_comware_memory_lookup_keeps_its_command_separate_from_huawei_memory_usage():
    comware = _find_template("h3c_comware_v7", "display memory")
    abbreviated_comware = _find_template("h3c_comware_v7", "dis mem")
    huawei = _find_template("huawei_vrp8", "display memory")

    assert comware is not None
    assert comware.name == "h3c_comware_v7_display_memory.textfsm"
    assert abbreviated_comware == comware
    assert huawei is not None
    assert huawei.name == "huawei_vrp_display_memory_usage.textfsm"


def test_comware_bgp_route_lookup_accepts_the_optional_unicast_keyword():
    template = _find_template(
        "h3c_comware_v7", "display bgp routing-table ipv4 unicast"
    )
    vrf_template = _find_template(
        "h3c_comware_v7",
        "display bgp routing-table ipv4 unicast vpn-instance VRF_A",
    )
    output = (
        FIXTURES
        / "h3c_comware"
        / "display_bgp_routing_table_ipv4"
        / "comware_v7_router_b.txt"
    ).read_text(encoding="utf-8")
    parsed = smart_parse_cli(
        output,
        "display bgp routing-table ipv4 unicast",
        platform="h3c_comware_v7",
    )

    assert template is not None
    assert vrf_template == template
    assert template.name == "h3c_comware_v7_display_bgp_routing_table_ipv4.textfsm"
    assert parsed["success"] is True
    assert parsed["template"] == template.name
    assert parsed["data"][0]["NETWORK"] == "8.1.1.0/24"


def test_comware_v7_release_actions_resolve_through_explicit_command_aliases():
    device = {
        "platform": "h3c_comware",
        "vendor": "H3C",
        "profile_platform_code": "h3c_comware_v7",
        "profile_parser_platform": "h3c_comware",
        "profile_connection_driver": "hp_comware",
    }
    cases = (
        ("get_arp_table_vrf", "display arp vpn-instance {{vrf}}", "h3c_comware_v7_display_arp_all.textfsm"),
        ("get_bgp_neighbors_vrf", "display bgp peer ipv4 vpn-instance {{vrf}}", "h3c_comware_v7_display_bgp_peer_ipv4_unicast.textfsm"),
        ("get_bgp_routes", "display bgp routing-table ipv4 unicast", "h3c_comware_v7_display_bgp_routing_table_ipv4.textfsm"),
        ("get_bgp_routes_vrf", "display bgp routing-table ipv4 unicast vpn-instance {{vrf}}", "h3c_comware_v7_display_bgp_routing_table_ipv4.textfsm"),
        ("get_mac_table_vrf", "display mac-address vpn-instance {{vrf}}", "h3c_comware_v7_display_mac_address.textfsm"),
        ("get_route_table_vrf", "display ip routing-table vpn-instance {{vrf}}", "h3c_comware_v7_display_ip_routing_table.textfsm"),
    )

    for action_code, command, filename in cases:
        match = resolve_textfsm_template_for_command(
            device,
            command,
            action_code=action_code,
            templates_catalog=list_templates(vendor_filter="h3c"),
        )
        assert match is not None, (action_code, command)
        assert match["textfsm_template"] == filename


def test_comware_vrf_alias_resolution_does_not_cross_profile_version():
    unknown_version = {
        "platform": "h3c_comware",
        "vendor": "H3C",
        "profile_platform_code": "h3c_comware_unknown",
        "profile_parser_platform": "h3c_comware",
        "profile_connection_driver": "hp_comware",
    }

    match = resolve_textfsm_template_for_command(
        unknown_version,
        "display ip routing-table vpn-instance {{vrf}}",
        action_code="get_route_table_vrf",
        templates_catalog=list_templates(vendor_filter="h3c"),
    )

    assert match is None


def test_comware_vrf_route_lookup_uses_the_platform_route_table_template():
    template = _find_template(
        "h3c_comware_v7", "display ip routing-table vpn-instance VRF_A"
    )
    unknown_profile_template = _find_template(
        "h3c_comware_unknown", "display ip routing-table vpn-instance VRF_A"
    )

    assert template is not None
    assert template.name == "h3c_comware_v7_display_ip_routing_table.textfsm"
    assert unknown_profile_template is None


def test_comware_v7_vrf_bgp_peer_commands_use_the_ipv4_peer_template():
    specific_vrf = _find_template(
        "h3c_comware_v7", "display bgp peer ipv4 vpn-instance VRF_A"
    )
    all_vrfs = _find_template(
        "h3c_comware_v7", "display bgp peer ipv4 vpn-instance-all"
    )

    assert specific_vrf is not None
    assert specific_vrf.name == "h3c_comware_v7_display_bgp_peer_ipv4_unicast.textfsm"
    assert all_vrfs == specific_vrf


def test_internal_h3c_profile_selectors_route_to_explicit_grammar_variants():
    v3_template = _find_template("h3c_comware_v3", "display cpu-usage")
    v5_template = _find_template("hp_comware", "display cpu-usage")
    v9_template = _find_template("h3c_comware9", "display interface brief")

    assert v3_template is not None
    assert v3_template.name == "h3c_comware_v3_display_cpu_usage.textfsm"
    assert v5_template is not None
    assert v5_template.name == "h3c_comware_v5_display_cpu_usage.textfsm"
    assert v9_template is not None
    assert v9_template.name == "h3c_comware_v9_display_interface_brief.textfsm"


def test_h3c_v5_stp_action_resolves_to_its_official_sample_template():
    for profile_code in ("hp_comware", "h3c_comware_v5"):
        match = resolve_textfsm_template_for_command(
            {
                "platform": "h3c_comware",
                "vendor": "H3C",
                "profile_platform_code": profile_code,
                "profile_parser_platform": "h3c_comware_v5",
                "profile_connection_driver": "hp_comware",
            },
            "display stp brief",
            action_code="get_stp",
            templates_catalog=list_templates(vendor_filter="h3c"),
        )

        assert match is not None
        assert match["textfsm_template"] == "h3c_comware_v5_display_stp_brief.textfsm"


def test_h3c_comware_v9_fixture_uses_an_explicit_v9_template_without_losing_records():
    output = (
        FIXTURES
        / "h3c_comware_v9"
        / "display_interface_brief"
        / "comware_v9_cr16000.txt"
    ).read_text(encoding="utf-8")

    result = smart_parse_cli(output, "display interface brief", platform="h3c_comware_v9")

    assert result["success"] is True
    assert result["template"] == "h3c_comware_v9_display_interface_brief.textfsm"
    assert {item["INTERFACE"] for item in result["data"]} == {
        "InLoop0",
        "MGE0/0/0",
        "NULL0",
        "REG0",
        "GE1/0/1",
    }


def test_h3c_v7_isis_fixture_satisfies_the_published_action_field_contract():
    from services.platform_registry_service import _normalize_records

    output = (
        FIXTURES
        / "h3c_comware"
        / "display_isis_peer"
        / "comware_v7_s6850.txt"
    ).read_text(encoding="utf-8")
    parsed = smart_parse_cli(output, "display isis peer", platform="h3c_comware_v7")

    assert parsed["success"] is True
    assert parsed["template"] == "h3c_comware_v7_display_isis_peer.textfsm"
    assert len(parsed["data"]) == 2

    records = _normalize_records(
        parsed["data"],
        max_records=1000,
        expected_fields={"neighbor", "state", "interface", "system_id", "level"},
    )
    assert records[0]["neighbor"] == "0000.0000.0001"
    assert records[0]["system_id"] == "0000.0000.0001"
    assert records[0]["level"] == "L1(L1L2)"
    assert records[1]["level"] == "L2(L1L2)"


def test_h3c_v9_isis_fixture_matches_both_quick_ops_profiles():
    from services.platform_registry_service import PROFILE_ACTION_COMMANDS, _normalize_records

    output = (FIXTURES / "h3c_comware" / "display_isis_peer" / "comware_v9_sr6602_i.txt").read_text(
        encoding="utf-8"
    )
    catalog = list_templates(vendor_filter="h3c")
    action_code = "get_isis_neighbors"
    for profile in ("h3c_comware_v9", "h3c_comware9"):
        device = {
            "vendor": "H3C",
            "platform": "h3c_comware",
            "profile_platform_code": profile,
            "profile_parser_platform": "h3c_comware",
            "profile_connection_driver": "hp_comware",
        }
        command = PROFILE_ACTION_COMMANDS[profile][action_code]
        match = resolve_textfsm_template_for_command(
            device, command, action_code=action_code, templates_catalog=catalog
        )
        assert match is not None
        assert match["textfsm_template"] == "h3c_comware_v9_display_isis_peer.textfsm"

    parsed = smart_parse_cli(output, "display isis peer", platform="h3c_comware_v9")
    assert parsed["success"] is True
    records = _normalize_records(
        parsed["data"],
        max_records=1000,
        expected_fields={"neighbor", "state", "interface", "system_id", "level"},
    )
    assert len(records) == 1
    assert records[0]["neighbor"] == records[0]["system_id"] == "0000.0000.0001"
    assert records[0]["state"].lower() == "up"
    assert records[0]["interface"] == "XGE0/0/6"
    assert records[0]["level"] == "L1(L1L2)"


def test_h3c_v7_clock_and_memory_fixtures_satisfy_the_published_action_fields():
    from services.platform_registry_service import _normalize_records

    clock_output = (
        FIXTURES
        / "h3c_comware"
        / "display_clock"
        / "comware_v7_s6850.txt"
    ).read_text(encoding="utf-8")
    clock = smart_parse_cli(clock_output, "display clock", platform="h3c_comware_v7")
    clock_records = _normalize_records(
        clock["data"], max_records=8, expected_fields={"clock", "timezone"}
    )

    memory_output = (
        FIXTURES
        / "h3c_comware"
        / "display_memory"
        / "comware_v7_s6850.txt"
    ).read_text(encoding="utf-8")
    memory = smart_parse_cli(memory_output, "display memory", platform="h3c_comware_v7")
    memory_records = _normalize_records(
        memory["data"], max_records=32, expected_fields={"usage", "total"}
    )

    assert clock["success"] is True
    assert clock_records[0]["clock"] == "15:11:00.211 Z5 Fri 03/16/2015"
    assert clock_records[0]["timezone"] == "Z5"
    assert memory["success"] is True
    assert memory_records[0]["total"] == "7900.82 MB"
    assert memory_records[0]["usage"] == "20.2%"


def test_h3c_v7_vrf_bgp_fixture_satisfies_the_published_action_fields():
    from services.platform_registry_service import _normalize_records

    output = (
        FIXTURES
        / "h3c_comware"
        / "display_bgp_peer_ipv4"
        / "comware_v7_s6850_vrf_all.txt"
    ).read_text(encoding="utf-8")
    parsed = smart_parse_cli(
        output,
        "display bgp peer ipv4 vpn-instance-all",
        platform="h3c_comware_v7",
    )

    records = _normalize_records(
        parsed["data"],
        max_records=1000,
        expected_fields={"neighbor", "asn", "state", "vrf_name"},
    )
    assert parsed["success"] is True
    assert len(records) == 4
    assert [record["vrf_name"] for record in records] == ["1", "1", "2", "2"]
    assert records[0]["neighbor"] == "111.1.1.1"
    assert records[0]["asn"] == "100"
    assert records[0]["state"] == "Connect"


def test_textfsm_catalog_exposes_one_public_h3c_family_with_explicit_variants():
    h3c = list_templates(platform_filter="h3c_comware", search="bgp", exact_platform=True)

    assert h3c and all(item["platform"] == "h3c_comware" for item in h3c)
    # V3 intentionally reuses the verified V5 grammar until a real V3 output
    # fixture is available; it is not represented by a fabricated V3 file.
    assert {item.get("template_variant") for item in h3c} >= {"v5", "v7", "v9"}


def test_textfsm_catalog_supports_vendor_family_and_version_filters():
    v7 = list_templates(
        vendor_filter="h3c",
        platform_family_filter="h3c_comware",
        version_filter="v7",
    )

    assert v7
    assert all(item["vendor"] == "h3c" for item in v7)
    assert all(item["platform_family"] == "h3c_comware" for item in v7)
    assert all(item["version"] == "v7" for item in v7)
    assert all(item["filename"].startswith("h3c_comware_v7_") for item in v7)
