from __future__ import annotations

import json
from pathlib import Path

import pytest

import services.operational_data_service as operational_service
from core.textfsm import list_template_suggestions, smart_parse_cli
from services.operational_data_service import NTC_PLATFORM_MAP, _resolve_commands


FIXTURES = Path(__file__).parents[1] / "fixtures" / "cli"


def fixture_platform(path: Path) -> str:
    for platform in (
        "h3c_comware_v3",
        "h3c_comware_v5",
        "h3c_comware_v9",
        "h3c_comware",
        "cisco_nxos",
        "cisco_ios",
    ):
        if platform in path.parts:
            return platform
    raise AssertionError(f"No supported vendor platform in fixture path: {path}")


def load_official_fixture(*parts: str, name: str) -> tuple[str, dict]:
    directory = FIXTURES.joinpath(*parts)
    output = (directory / f"{name}.txt").read_text(encoding="utf-8")
    metadata = json.loads((directory / f"{name}.meta.json").read_text(encoding="utf-8"))
    assert metadata["source_type"] == "official_vendor_documentation"
    assert metadata["source_url"].startswith(
        ("https://www.h3c.com/", "https://wwwsg.h3c.com/", "https://www.cisco.com/")
    )
    return output, metadata


ALL_H3C_CISCO_METADATA = sorted(
    [
        *FIXTURES.joinpath("h3c").rglob("*.meta.json"),
        *FIXTURES.joinpath("cisco").rglob("*.meta.json"),
    ],
    key=lambda path: path.as_posix(),
)


@pytest.mark.parametrize(
    "metadata_path",
    ALL_H3C_CISCO_METADATA,
    ids=lambda path: path.relative_to(FIXTURES).as_posix().removesuffix(".meta.json"),
)
def test_every_official_h3c_and_cisco_fixture_has_a_working_parser(metadata_path: Path):
    output_path = metadata_path.with_name(
        f"{metadata_path.name.removesuffix('.meta.json')}.txt"
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    output = output_path.read_text(encoding="utf-8")

    assert metadata["source_type"] == "official_vendor_documentation"
    assert metadata["source_url"].startswith(
        ("https://www.h3c.com/", "https://wwwsg.h3c.com/", "https://www.cisco.com/")
    )

    result = smart_parse_cli(
        output,
        metadata["command"],
        platform=fixture_platform(metadata_path),
    )

    assert result["success"] is True
    assert result["matched_rows"] > 0
    assert result["data"]


def test_platform_catalog_keeps_h3c_and_cisco_command_families_separate():
    assert _resolve_commands("h3c_comware_v3", ["bgp", "bgp_routes"]) == {
        "bgp": ["display bgp peer"],
        "bgp_routes": ["display bgp routing-table"],
    }
    assert _resolve_commands("h3c_comware_v3", ["interface_description"]) == {
        "interface_description": ["display interface brief description"],
    }
    assert _resolve_commands("h3c_comware_v5", ["bgp", "bgp_routes"]) == {
        "bgp": ["display bgp peer"],
        "bgp_routes": ["display bgp routing-table"],
    }
    assert _resolve_commands("h3c_comware_v5", ["interface_description"]) == {
        "interface_description": ["display interface brief description"],
    }
    assert _resolve_commands("h3c_comware", ["bgp", "bgp_routes"]) == {
        "bgp": ["display bgp peer ipv4 unicast"],
        "bgp_routes": ["display bgp routing-table ipv4"],
    }
    assert _resolve_commands("h3c_comware", ["interface_description"]) == {
        "interface_description": ["display interface brief description"],
    }
    assert _resolve_commands("h3c_comware_v9", ["bgp", "bgp_routes"]) == {
        "bgp": ["display bgp peer ipv4 unicast"],
        "bgp_routes": ["display bgp routing-table ipv4"],
    }
    assert _resolve_commands("h3c_comware_v9", ["interface_description"]) == {
        "interface_description": ["display interface brief description"],
    }

    ios_expected = {
        "bgp": ["show ip bgp summary"],
        "bgp_routes": ["show ip bgp"],
        "bfd": ["show bfd neighbors details"],
        "ntp": ["show ntp status"],
        "environment": ["show environment temperature"],
        "transceiver": ["show interfaces transceiver"],
    }
    assert _resolve_commands("cisco_ios", list(ios_expected)) == ios_expected
    assert _resolve_commands("cisco_xe", list(ios_expected)) == ios_expected
    assert _resolve_commands(
        "cisco_nxos",
        ["bgp", "bgp_routes", "bfd", "ntp", "environment", "transceiver", "logs"],
    ) == {
        "bgp": ["show ip bgp summary"],
        "bgp_routes": ["show ip bgp"],
        "bfd": ["show bfd neighbors"],
        "ntp": ["show ntp peer-status"],
        "environment": ["show environment"],
        "transceiver": ["show interface transceiver"],
        "logs": ["show logging last 30"],
    }

    assert NTC_PLATFORM_MAP["cisco_xe"] == "cisco_ios"
    assert NTC_PLATFORM_MAP["h3c_comware_v3"] == "h3c_comware"
    assert NTC_PLATFORM_MAP["h3c_comware_v9"] == "h3c_comware"


def test_comware_suggestions_keep_abbreviated_query_in_the_selected_version():
    v3_suggestions = list_template_suggestions("h3c_comware_v3", "dis ver", 8)
    assert any(
        item["command"] == "display version"
        and item["filename"].startswith("h3c_comware_v5_")
        for item in v3_suggestions
    )
    assert not any(item["filename"].startswith("h3c_comware_v7_") for item in v3_suggestions)

    v7_suggestions = list_template_suggestions("h3c_comware_v7", "display ver", 8)
    assert any(
        item["command"] == "display version"
        and item["filename"].startswith("h3c_comware_v7_")
        for item in v7_suggestions
    )
    assert not any(item["filename"].startswith("h3c_comware_v5_") for item in v7_suggestions)

    v5_suggestions = list_template_suggestions("h3c_comware_v5", "dis ver", 8)
    assert any(
        item["command"] == "display version"
        and item["filename"].startswith("h3c_comware_v5_")
        for item in v5_suggestions
    )
    assert not any(item["filename"].startswith("h3c_comware_v7_") for item in v5_suggestions)


def test_h3c_bgp_unicast_and_no_suffix_use_distinct_textfsm_templates():
    output, _ = load_official_fixture(
        "h3c",
        "h3c_comware",
        "display_bgp_peer_ipv4",
        name="comware_v7_s5560",
    )
    unicast = smart_parse_cli(output, "display bgp peer ipv4 unicast", platform="h3c_comware")
    no_suffix = smart_parse_cli(output, "display bgp peer ipv4", platform="h3c_comware")

    assert unicast["template"] == "h3c_comware_v7_display_bgp_peer_ipv4_unicast.textfsm"
    # The legacy no-suffix V7 custom file was intentionally removed with the
    # old fixture set; it now falls back to the NTC parser.
    assert no_suffix["template"] == "ntc_templates_parse_output"


def test_cisco_neighbor_collection_uses_lldp_only():
    assert _resolve_commands("cisco_ios", ["neighbors"]) == {
        "neighbors": ["show lldp neighbors"],
    }
    assert _resolve_commands("cisco_nxos", ["neighbors"]) == {
        "neighbors": ["show lldp neighbors detail"],
    }


@pytest.mark.parametrize(
    ("platform", "parts", "name", "expected_template", "expected_rows"),
    [
        (
            "h3c_comware",
            ("h3c", "h3c_comware", "display_bgp_peer_ipv4"),
            "comware_v7_s5560",
            "h3c_comware_v7_display_bgp_peer_ipv4_unicast.textfsm",
            1,
        ),
        (
            "h3c_comware",
            ("h3c", "h3c_comware", "display_bgp_routing_table_ipv4"),
            "comware_v7_router_b",
            "h3c_comware_v7_display_bgp_routing_table_ipv4.textfsm",
            1,
        ),
        (
            "h3c_comware",
            ("h3c", "h3c_comware", "display_logbuffer"),
            "comware_v7_s5130",
            "h3c_comware_v7_display_logbuffer.textfsm",
            1,
        ),
        (
            "h3c_comware",
            ("h3c", "h3c_comware", "display_interface_brief"),
            "comware_v7",
            "h3c_comware_v7_display_interface_brief.textfsm",
            3,
        ),
        (
            "h3c_comware",
            ("h3c", "h3c_comware", "display_lldp_neighbor_information_list"),
            "comware_v7_s5130",
            "h3c_comware_v7_display_lldp_neighbor_information_list.textfsm",
            3,
        ),
        (
            "h3c_comware",
            ("h3c", "h3c_comware", "display_vlan_brief"),
            "comware_v7_msr",
            "h3c_comware_v7_display_vlan_brief.textfsm",
            1,
        ),
        (
            "h3c_comware_v9",
            ("h3c", "h3c_comware_v9", "display_bgp_peer_ipv4"),
            "comware_v9_cr16000",
            "h3c_comware_v9_display_bgp_peer_ipv4_unicast.textfsm",
            1,
        ),
        (
            "h3c_comware_v9",
            ("h3c", "h3c_comware_v9", "display_bgp_routing_table_ipv4"),
            "comware_v9_cr16000",
            "h3c_comware_v9_display_bgp_routing_table_ipv4.textfsm",
            2,
        ),
        (
            "h3c_comware_v9",
            ("h3c", "h3c_comware_v9", "display_interface_brief"),
            "comware_v9_cr16000",
            "h3c_comware_v9_display_interface_brief.textfsm",
            5,
        ),
        (
            "h3c_comware_v9",
            ("h3c", "h3c_comware_v9", "display_link_aggregation_verbose"),
            "comware_v9_msr5680",
            "h3c_comware_v9_display_link_aggregation_verbose.textfsm",
            3,
        ),
        (
            "h3c_comware_v9",
            ("h3c", "h3c_comware_v9", "display_vlan_brief"),
            "comware_v9_cr16000",
            "h3c_comware_v9_display_vlan_brief.textfsm",
            3,
        ),
        (
            "cisco_ios",
            ("cisco", "cisco_ios", "show_ntp_status"),
            "iosxe_17",
            "cisco_ios_show_ntp_status.textfsm",
            1,
        ),
        (
            "cisco_ios",
            ("cisco", "cisco_ios", "show_environment_temperature"),
            "iosxe_c9300",
            "cisco_ios_show_environment_temperature.textfsm",
            1,
        ),
        (
            "cisco_ios",
            ("cisco", "cisco_ios", "show_interfaces_transceiver"),
            "ios_asr",
            "cisco_ios_show_interfaces_transceiver.textfsm",
            3,
        ),
        (
            "cisco_nxos",
            ("cisco", "cisco_nxos", "show_ntp_peer_status"),
            "nexus7000",
            "cisco_nxos_show_ntp_peer_status.textfsm",
            3,
        ),
        (
            "cisco_nxos",
            ("cisco", "cisco_nxos", "show_interface_transceiver"),
            "nexus3000",
            "cisco_nxos_show_interface_transceiver.textfsm",
            1,
        ),
        (
            "cisco_nxos",
            ("cisco", "cisco_nxos", "show_logging_last_30"),
            "nexus3000",
            "cisco_nxos_show_logging_last_30.textfsm",
            3,
        ),
    ],
)
def test_official_h3c_and_cisco_outputs_parse_by_platform(
    platform: str,
    parts: tuple[str, ...],
    name: str,
    expected_template: str,
    expected_rows: int,
):
    output, metadata = load_official_fixture(*parts, name=name)
    result = smart_parse_cli(output, metadata["command"], platform=platform)

    assert result["success"] is True
    assert result["template"] == expected_template
    assert result["matched_rows"] == expected_rows
    assert len(result["data"]) == expected_rows


def test_comware9_does_not_collapse_to_comware7_before_dedicated_templates():
    output, metadata = load_official_fixture(
        "h3c", "h3c_comware_v9", "display_bgp_peer_ipv4", name="comware_v9_cr16000"
    )
    result = smart_parse_cli(output, metadata["command"], platform="h3c_comware_v9")

    assert result["template_source"] == "custom"
    assert result["data"][0]["PEER"] == "10.2.1.2"
    assert result["data"][0]["STATUS"] == "Established"


@pytest.mark.parametrize(
    ("platform", "expected_template"),
    [
        ("h3c_comware_v5", "h3c_comware_v5_display_interface_brief_description.textfsm"),
        ("h3c_comware", "h3c_comware_v7_display_interface_brief_description.textfsm"),
        ("h3c_comware_v9", "h3c_comware_v9_display_interface_brief_description.textfsm"),
    ],
)
def test_h3c_interface_description_command_prefers_dedicated_grammar_and_keeps_legacy_fallback(
    platform: str,
    expected_template: str,
):
    output, _metadata = load_official_fixture(
        "h3c", "h3c_comware", "display_interface_brief", name="comware_v7"
    )
    # Netmiko strips the command echo.  The official fixture's first line records
    # the source command and is intentionally removed for this catalog alias test.
    output_without_echo = "\n".join(output.splitlines()[1:])
    result = smart_parse_cli(
        output_without_echo,
        "display interface brief description",
        platform=platform,
    )

    assert result["success"] is True
    assert result["template"] == expected_template
    assert result["matched_rows"] == 3


def test_comware9_interface_parser_does_not_turn_headers_into_records():
    output, metadata = load_official_fixture(
        "h3c", "h3c_comware_v9", "display_interface_brief", name="comware_v9_cr16000"
    )
    result = smart_parse_cli(output, metadata["command"], platform="h3c_comware_v9")

    assert {item["INTERFACE"] for item in result["data"]} == {
        "InLoop0",
        "MGE0/0/0",
        "NULL0",
        "REG0",
        "GE1/0/1",
    }


def test_comware_vlan_parser_keeps_the_complete_vlan_name():
    output, metadata = load_official_fixture(
        "h3c", "h3c_comware_v9", "display_vlan_brief", name="comware_v9_cr16000"
    )
    result = smart_parse_cli(output, metadata["command"], platform="h3c_comware_v9")

    assert [item["VLAN_NAME"] for item in result["data"]] == [
        "VLAN 0001",
        "VLAN 0002",
        "VLAN 0003",
    ]


def test_comware9_link_aggregation_keeps_parent_context_on_every_member():
    output, metadata = load_official_fixture(
        "h3c",
        "h3c_comware_v9",
        "display_link_aggregation_verbose",
        name="comware_v9_msr5680",
    )
    result = smart_parse_cli(output, metadata["command"], platform="h3c_comware_v9")

    assert {item["AGGREGATE_INTERFACE"] for item in result["data"]} == {
        "Route-Aggregation1"
    }
    assert {item["AGGREGATION_MODE"] for item in result["data"]} == {"Dynamic"}


@pytest.mark.parametrize("platform", ["h3c_comware_v5", "h3c_comware"])
def test_comware7_real_world_transceiver_blocks_are_not_collapsed(platform):
    output = """Ten-GigabitEthernet1/0/50 transceiver information:
  Transceiver Type              : SFP-GE-LX-SM1310
  Connector Type                : LC
  Wavelength(nm)                : 1310
  Transfer Distance(km)         : 10(9um)
  Digital Diagnostic Monitoring : YES
  Vendor Name                   : H3C
Ten-GigabitEthernet1/0/51 transceiver information:
  Transceiver Type              : SFP-GE-LX-SM1310
  Connector Type                : LC
  Wavelength(nm)                : 1310
  Transfer Distance(km)         : 10(9um)
  Digital Diagnostic Monitoring : YES
  Vendor Name                   : H3C
Ten-GigabitEthernet1/0/52 transceiver information:
  Transceiver Type              : SFP-GE-LX-SM1310
  Connector Type                : LC
  Wavelength(nm)                : 1310
  Transfer Distance(km)         : 10(9um)
  Digital Diagnostic Monitoring : YES
  Vendor Name                   : H3C
"""
    result = smart_parse_cli(output, "display transceiver interface", platform=platform)

    assert result["success"] is True
    assert result["matched_rows"] == 3
    assert {item["INTERFACE"] for item in result["data"]} == {
        "Ten-GigabitEthernet1/0/50",
        "Ten-GigabitEthernet1/0/51",
        "Ten-GigabitEthernet1/0/52",
    }
    assert {item["TRANSFER_DISTANCE"] for item in result["data"]} == {"10(9um)"}


@pytest.mark.parametrize("platform", ["h3c_comware_v5", "h3c_comware"])
def test_comware7_real_world_version_is_one_complete_record(platform):
    output = """H3C Comware Software, Version 7.1.070, Alpha 7170
Copyright (c) 2004-2022 New H3C Technologies Co., Ltd. All rights reserved.
H3C S6850 uptime is 0 weeks, 0 days, 1 hour, 35 minutes
Last reboot reason: User reboot
Boot image: flash:/s6850-cmw710-boot-t7064p15.bin
Boot image version: 7.1.070, Alpha 7170
  Compiled Nov 21 2022 11:00:00
Boot image: flash:/s6850-cmw710-system-t7064p15.bin
Boot image version: 7.1.070, Alpha 7170
  Compiled Nov 21 2022 11:00:00

Slot 1:
S6850 with 2 Processors
"""
    result = smart_parse_cli(output, "display version", platform=platform)

    assert result["success"] is True
    assert result["matched_rows"] == 1
    record = result["data"][0]
    assert record["SOFTWARE_VERSION"] == "7.1.070"
    assert record["RELEASE"] == "Alpha 7170"
    assert record["DEVICE"] == "S6850"
    assert record["UPTIME"] == "0 weeks, 0 days, 1 hour, 35 minutes"
    assert record["LAST_REBOOT_REASON"] == "User reboot"


@pytest.mark.parametrize("platform", ["h3c_comware_v5", "h3c_comware"])
def test_comware7_real_world_environment_table_is_structured(platform):
    output = """System temperature information (degree centigrade):
-------------------------------------
Slot  Sensor    Temperature LowerLimit WarningLimit AlarmLimit
 0/1  Inflow  1   30           -5          66          76
 0/1  Outflow 1   33           -5          66          76
 0/1  Outflow 2   37           -5          66          76
 0/1  Hotspot 1   39           -5          66          76
 0/1  Hotspot 2   42           -5          66          76
 0/1  Hotspot 3   44           -5          66          76
"""
    result = smart_parse_cli(output, "display environment", platform=platform)

    assert result["success"] is True
    assert result["matched_rows"] == 6
    assert [item["TEMPERATURE"] for item in result["data"]] == ["30", "33", "37", "39", "42", "44"]


@pytest.mark.parametrize("platform", ["h3c_comware_v5", "h3c_comware"])
def test_comware7_real_world_power_table_is_structured(platform):
    output = """Device Info on Slot 1:
Device ID.  Status
 1          Normal
 2          Normal
"""
    result = smart_parse_cli(output, "display power", platform=platform)

    assert result["success"] is True
    assert result["matched_rows"] == 2
    assert [item["POWER_ID"] for item in result["data"]] == ["1", "2"]
    assert {item["STATUS"] for item in result["data"]} == {"Normal"}


@pytest.mark.parametrize("platform", ["h3c_comware_v5", "h3c_comware"])
def test_comware7_real_world_ntp_status_is_structured(platform):
    output = """--- H3C-SW1 ---
[display ntp-service status]
 Clock status: unsynchronized
 Clock stratum: 16
 Reference clock ID: none
 Clock jitter: 0.000000 s
 Stability: 0.000 pps
 Clock precision: 2^-18
 Root delay: 0.00000 ms
 Root dispersion: 0.50354 ms
 Reference time: 00000000.00000000  Thu, Feb  7 2036  6:28:16.000
 System poll interval: 8 s
"""
    result = smart_parse_cli(output, "display ntp-service status", platform=platform)

    assert result["success"] is True
    assert result["matched_rows"] == 1
    record = result["data"][0]
    assert record["CLOCK_STATUS"] == "unsynchronized"
    assert record["CLOCK_STRATUM"] == "16"
    assert record["REFERENCE_CLOCK_ID"] == "none"
    assert record["POLL_INTERVAL"] == "8"


@pytest.mark.parametrize("platform", ["h3c_comware"])
def test_comware7_real_world_bfd_down_session_is_structured(platform):
    output = """--- S6850_1 ---
[display bfd session]
 Total sessions: 1     Up sessions: 0     Init mode: Active

 IPv4 session working in control packet mode:

 LD/RD            SourceAddr      DestAddr        State  Holdtime    Interface
 32833/0          10.254.12.1     10.254.12.2     Down      /        Vlan112
"""
    result = smart_parse_cli(output, "display bfd session", platform=platform)

    assert result["success"] is True
    assert result["matched_rows"] == 1
    record = result["data"][0]
    assert record["LOCAL_DISCRIMINATOR"] == "32833"
    assert record["REMOTE_DISCRIMINATOR"] == "0"
    assert record["SOURCE_IP"] == "10.254.12.1"
    assert record["DESTINATION_IP"] == "10.254.12.2"
    assert record["STATUS"] == "Down"
    assert record["HOLDTIME"] == "/"
    assert record["INTERFACE"] == "Vlan112"


@pytest.mark.parametrize(
    ("platform", "category_fixtures", "expected_commands"),
    [
        (
            "h3c_comware",
            {
                "arp": ("h3c", "h3c_comware", "display_arp_all", "comware_v7_s5130"),
                "bfd": ("h3c", "h3c_comware", "display_bfd_session", "comware_v7_s5130"),
                "bgp": ("h3c", "h3c_comware", "display_bgp_peer_ipv4", "comware_v7_s5560"),
                "bgp_routes": (
                    "h3c",
                    "h3c_comware",
                    "display_bgp_routing_table_ipv4",
                    "comware_v7_router_b",
                ),
                "environment": ("h3c", "h3c_comware", "display_environment", "comware_v7_s5130"),
                "fan": ("h3c", "h3c_comware", "display_fan", "comware_v7_s5130"),
                "interfaces": ("h3c", "h3c_comware", "display_interface_brief", "comware_v7"),
                "neighbors": (
                    "h3c",
                    "h3c_comware",
                    "display_lldp_neighbor_information_list",
                    "comware_v7_s5130",
                ),
                "logs": ("h3c", "h3c_comware", "display_logbuffer", "comware_v7_s5130"),
                "ospf": ("h3c", "h3c_comware", "display_ospf_peer", "comware_v7_s5130"),
                "power": ("h3c", "h3c_comware", "display_power", "comware_v7_s5130"),
                "stack": ("h3c", "h3c_comware", "display_irf", "comware_v7_s5130"),
                "version": ("h3c", "h3c_comware", "display_version", "comware_v7_wx2880x"),
                "vlan": ("h3c", "h3c_comware", "display_vlan_brief", "comware_v7_msr"),
            },
            {
                "arp": ["display arp all"],
                "bfd": ["display bfd session"],
                "bgp": ["display bgp peer ipv4 unicast"],
                "bgp_routes": ["display bgp routing-table ipv4"],
                "environment": ["display environment"],
                "fan": ["display fan"],
                "interfaces": ["display interface brief"],
                "neighbors": ["display lldp neighbor-information list"],
                "logs": ["display logbuffer"],
                "ospf": ["display ospf peer"],
                "power": ["display power"],
                "stack": ["display irf"],
                "version": ["display version"],
                "vlan": ["display vlan brief"],
            },
        ),
        (
            "h3c_comware_v9",
            {
                "bgp": ("h3c", "h3c_comware_v9", "display_bgp_peer_ipv4", "comware_v9_cr16000"),
                "bgp_routes": (
                    "h3c",
                    "h3c_comware_v9",
                    "display_bgp_routing_table_ipv4",
                    "comware_v9_cr16000",
                ),
                "eth_trunk": (
                    "h3c",
                    "h3c_comware_v9",
                    "display_link_aggregation_verbose",
                    "comware_v9_msr5680",
                ),
                "interfaces": (
                    "h3c",
                    "h3c_comware_v9",
                    "display_interface_brief",
                    "comware_v9_cr16000",
                ),
                "vlan": (
                    "h3c",
                    "h3c_comware_v9",
                    "display_vlan_brief",
                    "comware_v9_cr16000",
                ),
            },
            {
                "bgp": ["display bgp peer ipv4 unicast"],
                "bgp_routes": ["display bgp routing-table ipv4"],
                "eth_trunk": ["display link-aggregation verbose"],
                "interfaces": ["display interface brief"],
                "vlan": ["display vlan brief"],
            },
        ),
        (
            "cisco_xe",
            {
                "ntp": ("cisco", "cisco_ios", "show_ntp_status", "iosxe_17"),
                "environment": (
                    "cisco",
                    "cisco_ios",
                    "show_environment_temperature",
                    "iosxe_c9300",
                ),
                "transceiver": (
                    "cisco",
                    "cisco_ios",
                    "show_interfaces_transceiver",
                    "ios_asr",
                ),
            },
            {
                "ntp": ["show ntp status"],
                "environment": ["show environment temperature"],
                "transceiver": ["show interfaces transceiver"],
            },
        ),
        (
            "cisco_nxos",
            {
                "ntp": ("cisco", "cisco_nxos", "show_ntp_peer_status", "nexus7000"),
                "transceiver": (
                    "cisco",
                    "cisco_nxos",
                    "show_interface_transceiver",
                    "nexus3000",
                ),
                "logs": (
                    "cisco",
                    "cisco_nxos",
                    "show_logging_last_30",
                    "nexus3000",
                ),
            },
            {
                "ntp": ["show ntp peer-status"],
                "transceiver": ["show interface transceiver"],
                "logs": ["show logging last 30"],
            },
        ),
    ],
)
def test_quick_collection_uses_platform_command_and_parses_official_output(
    monkeypatch,
    platform: str,
    category_fixtures: dict[str, tuple[str, str, str, str]],
    expected_commands: dict[str, list[str]],
):
    outputs: dict[str, str] = {}
    for category, fixture in category_fixtures.items():
        output, metadata = load_official_fixture(*fixture[:3], name=fixture[3])
        # Official samples sometimes use a shorter command spelling than the
        # platform catalog's explicit address-family command. The recorded
        # output remains valid evidence for every catalog command under test.
        assert metadata["command"]
        for command in expected_commands[category]:
            outputs[command] = output

    class FakeConnection:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def send_command(self, command, **_kwargs):
            return outputs[command]

    monkeypatch.setattr(operational_service, "_build_connection_params", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(operational_service, "ConnectHandler", FakeConnection)

    result = operational_service.collect_operational_data(
        {
            "id": f"{platform}-test",
            "hostname": "official-fixture",
            "ip_address": "192.0.2.10",
            "vendor": "H3C" if "comware" in platform else "Cisco",
            "platform": platform,
            "version": "7.1.070" if platform == "h3c_comware" else "",
            "role": "distribution",
            "collection_policy_json": '{"collectors":{"interface_status":true,"lldp":true,"arp":true,"mac_table":true,"vlan":true,"routes":true,"bgp":true,"ospf":true,"eigrp":true,"isis":true,"rip":true,"bfd":true}}',
        },
        categories=list(category_fixtures),
    )

    categories = {item["key"]: item for item in result["categories"]}
    for category, commands in expected_commands.items():
        assert categories[category]["commands"] == commands
        assert categories[category]["parse_status"] == "matched"
        assert categories[category]["count"] > 0

    if "h3c_comware" == platform:
        assert categories["interfaces"]["parser"] == (
            "textfsm:h3c_comware_v7_display_interface_brief.textfsm"
        )
        assert categories["interfaces"]["template"] == (
            "h3c_comware_v7_display_interface_brief.textfsm"
        )
        assert categories["interfaces"]["parser_platform"] == "h3c_comware_v7"
