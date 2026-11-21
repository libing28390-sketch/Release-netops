from __future__ import annotations

import pytest

from services.ipam_fhrp_parser import parse_cisco_fhrp_output, parse_fhrp_output, parse_h3c_vrrp_output


HSRP_HEADER_WITH_P = (
    "Interface Grp Prio P State Active addr Standby addr Group addr"
)
HSRP_HEADER_WITHOUT_P = "Interface Grp Prio State Active addr Standby addr Group addr"
HSRP_DOCUMENTED_HEADER = "Interface Grp Pri P State Active Standby Virtual IP"
VRRP_HEADER = "Interface Grp A-F Pri Time Own Pre State Master addr Group addr"
H3C_IPV4_VERBOSE = """IPv4 Virtual Router Information:
  Running Mode : Standard
  Total number of virtual routers : 1
  Interface Vlan-interface20
    VRID : 7                       Adver Timer : 100
    Admin Status : Up              State : Master
    Config Pri : 120               Running Pri : 120
    Preempt Mode : Yes             Delay Time : 0
    Auth Type : None
    Virtual IP : 192.0.2.70
                 192.0.2.71
    Virtual MAC : 0000-5e00-0107
    Master IP : 192.0.2.1
"""
H3C_IPV6_VERBOSE = """IPv6 Virtual Router Information:
  Running Mode : Standard
  Total number of virtual routers : 1
  Interface Vlan-interface200
    VRID : 9                       Adver Timer : 100
    Admin Status : Up              State : Backup
    Config Pri : 110               Running Pri : 105
    Preempt Mode : Yes             Delay Time : 0
    Auth Type : None
    Virtual IP : 2001:db8::90
    Member IP List : 2001:db8::2 (Master)
    Master IP : 2001:db8::2
"""


def test_hsrp_parses_optional_p_column_and_keeps_repeated_group_ids_separate() -> None:
    output = f"""
{HSRP_HEADER_WITH_P}
GigabitEthernet1/0/1.100 10 120 P Active local 192.0.2.2 192.0.2.1
GigabitEthernet1/0/2.100 10 100 - Standby 192.0.2.1 local 192.0.2.1
"""

    result = parse_cisco_fhrp_output("show standby brief", output, platform="cisco_ios")

    assert result["status"] == "complete"
    assert result["observations"] == [
        {
            "protocol": "hsrp",
            "group_id": 10,
            "address_family": 4,
            "interface_name": "GigabitEthernet1/0/1.100",
            "priority": 120,
            "state": "active",
            "master_address": None,
            "virtual_ip": "192.0.2.1",
            "virtual_mac": None,
        },
        {
            "protocol": "hsrp",
            "group_id": 10,
            "address_family": 4,
            "interface_name": "GigabitEthernet1/0/2.100",
            "priority": 100,
            "state": "standby",
            "master_address": "192.0.2.1",
            "virtual_ip": "192.0.2.1",
            "virtual_mac": None,
        },
    ]


def test_hsrp_accepts_header_without_p_and_normalizes_ipv6_addresses() -> None:
    output = f"""
{HSRP_HEADER_WITHOUT_P}
Vlan200 3 110 Active local FE80:0:0:0:0:0:0:2 fe80::1
"""

    result = parse_cisco_fhrp_output("show standby brief", output, platform="cisco_iosxe")

    assert result["status"] == "complete"
    assert result["observations"] == [
        {
            "protocol": "hsrp",
            "group_id": 3,
            "address_family": 6,
            "interface_name": "Vlan200",
            "priority": 110,
            "state": "active",
            "master_address": None,
            "virtual_ip": "fe80::1",
            "virtual_mac": None,
        }
    ]


def test_hsrp_accepts_official_short_column_labels() -> None:
    output = f"""
{HSRP_DOCUMENTED_HEADER}
Et1/0 6 120 P Active local FE80::A8BB:CCFF:FE00:3401 FE80::5:73FF:FEA0:6
"""

    result = parse_cisco_fhrp_output("show standby brief", output, platform="cisco_ios")

    assert result["status"] == "complete"
    assert result["observations"][0]["address_family"] == 6
    assert result["observations"][0]["virtual_ip"] == "fe80::5:73ff:fea0:6"


def test_vrrp_parses_ipv4_and_ipv6_rows_without_merging_group_ids() -> None:
    output = f"""
{VRRP_HEADER}
Vlan20 7 IPv4 120 0 Y Y Master local 192.0.2.20
Vlan200 7 IPv6 110 1 N Y Backup 2001:0DB8:0:0::2 2001:db8::20
"""

    result = parse_cisco_fhrp_output("show vrrp brief", output, platform="cisco_xe")

    assert result["status"] == "complete"
    assert result["observations"] == [
        {
            "protocol": "vrrp",
            "group_id": 7,
            "address_family": 4,
            "interface_name": "Vlan20",
            "priority": 120,
            "state": "master",
            "master_address": None,
            "virtual_ip": "192.0.2.20",
            "virtual_mac": None,
        },
        {
            "protocol": "vrrp",
            "group_id": 7,
            "address_family": 6,
            "interface_name": "Vlan200",
            "priority": 110,
            "state": "backup",
            "master_address": "2001:db8::2",
            "virtual_ip": "2001:db8::20",
            "virtual_mac": None,
        },
    ]


def test_h3c_vrrp_parses_verbose_ipv4_and_multiple_virtual_ips() -> None:
    result = parse_h3c_vrrp_output(
        "display vrrp verbose", H3C_IPV4_VERBOSE, platform="h3c_comware"
    )

    assert result["status"] == "complete"
    assert [
        (item["group_id"], item["interface_name"], item["priority"], item["virtual_ip"], item["virtual_mac"])
        for item in result["observations"]
    ] == [
        (7, "Vlan-interface20", 120, "192.0.2.70", "0000-5e00-0107"),
        (7, "Vlan-interface20", 120, "192.0.2.71", "0000-5e00-0107"),
    ]
    assert result["observations"][0]["master_address"] == "192.0.2.1"
    assert all(item["address_family"] == 4 and item["state"] == "master" for item in result["observations"])


def test_h3c_vrrp_parses_verbose_ipv6_and_running_priority() -> None:
    result = parse_fhrp_output(
        "display vrrp ipv6 verbose", H3C_IPV6_VERBOSE, platform="h3c_comware"
    )

    assert result["status"] == "complete"
    assert result["observations"] == [
        {
            "protocol": "vrrp",
            "group_id": 9,
            "address_family": 6,
            "interface_name": "Vlan-interface200",
            "priority": 105,
            "state": "backup",
            "master_address": "2001:db8::2",
            "virtual_ip": "2001:db8::90",
            "virtual_mac": None,
        }
    ]


@pytest.mark.parametrize(
    ("command", "output"),
    [
        (
            "display vrrp verbose",
            "IPv4 Virtual Router Information:\nTotal number of virtual routers : 0\n",
        ),
        (
            "display vrrp ipv6 verbose",
            "IPv6 Virtual Router Information:\nTotal number of virtual routers : 0\n",
        ),
    ],
)
def test_h3c_explicit_zero_router_count_is_complete_empty(command: str, output: str) -> None:
    result = parse_h3c_vrrp_output(command, output, platform="h3c_comware")

    assert result == {"status": "complete", "observations": []}


@pytest.mark.parametrize(
    ("command", "output"),
    [
        ("display vrrp verbose", "VRRP4 is not configured.\n"),
        ("display vrrp ipv6 verbose", "VRRP6 is not configured.\n"),
    ],
)
def test_h3c_family_specific_not_configured_output_is_verified_empty(
    command: str, output: str
) -> None:
    result = parse_h3c_vrrp_output(command, output, platform="h3c_comware")

    assert result == {"status": "complete", "observations": []}


@pytest.mark.parametrize(
    ("command", "output", "expected_status", "expected_observations"),
    [
        ("display vrrp verbose", "IPv4 Virtual Router Information:\n", "partial", 0),
        (
            "display vrrp verbose",
            "IPv4 Virtual Router Information:\nTotal number of virtual routers : 2\n"
            "Interface Vlan-interface20\nVRID : 7\nState : Master\n",
            "partial",
            1,
        ),
        (
            "display vrrp verbose",
            "% Unrecognized command found at '^' position.\n",
            "unsupported",
            0,
        ),
    ],
)
def test_h3c_missing_count_mismatch_or_rejected_command_is_not_empty(
    command: str, output: str, expected_status: str, expected_observations: int
) -> None:
    result = parse_h3c_vrrp_output(command, output, platform="h3c_comware")

    assert result["status"] == expected_status
    assert len(result["observations"]) == expected_observations


def test_h3c_vrrp_parser_rejects_cisco_family_and_wrong_address_family() -> None:
    assert parse_h3c_vrrp_output(
        "show vrrp brief", H3C_IPV4_VERBOSE, platform="h3c_comware"
    ) == {"status": "unsupported", "observations": []}
    assert parse_h3c_vrrp_output(
        "display vrrp ipv6 verbose", H3C_IPV4_VERBOSE, platform="h3c_comware"
    )["status"] == "partial"


@pytest.mark.parametrize(
    ("command", "header", "platform"),
    [
        ("show standby brief", HSRP_HEADER_WITH_P, "cisco_ios"),
        ("show vrrp brief", VRRP_HEADER, "cisco_ios"),
    ],
)
def test_header_only_output_is_a_complete_empty_result(
    command: str, header: str, platform: str
) -> None:
    result = parse_cisco_fhrp_output(command, f"{header}\n", platform=platform)

    assert result == {"status": "complete", "observations": []}


def test_explicit_no_groups_message_is_a_complete_empty_result() -> None:
    result = parse_cisco_fhrp_output(
        "show standby brief", "No HSRP groups configured.\n", platform="cisco_ios"
    )

    assert result == {"status": "complete", "observations": []}


@pytest.mark.parametrize(
    "output",
    [
        "",
        "Interface Group Priority State Master addr Virtual IP\n",
        f"{HSRP_HEADER_WITH_P}\nGigabitEthernet1/0/1 10 100 P Active local 192.0.2.2\n",
    ],
)
def test_invalid_or_truncated_hsrp_output_is_partial(output: str) -> None:
    result = parse_cisco_fhrp_output("show standby brief", output, platform="cisco_ios")

    assert result["status"] == "partial"
    assert result["observations"] == []


def test_page_marker_makes_result_partial_without_discarding_complete_rows() -> None:
    output = (
        f"{HSRP_HEADER_WITH_P}\n"
        "GigabitEthernet1/0/1 10 100 P Active local 192.0.2.2 192.0.2.1\n"
        "--More--"
    )

    result = parse_cisco_fhrp_output("show standby brief", output, platform="cisco_ios")

    assert result["status"] == "partial"
    assert [item["interface_name"] for item in result["observations"]] == [
        "GigabitEthernet1/0/1"
    ]


def test_garbled_preamble_keeps_valid_rows_but_marks_result_partial() -> None:
    output = (
        "unexpected CLI fragment\n"
        f"{HSRP_HEADER_WITH_P}\n"
        "GigabitEthernet1/0/1 10 100 P Active local 192.0.2.2 192.0.2.1\n"
    )

    result = parse_cisco_fhrp_output("show standby brief", output, platform="cisco_ios")

    assert result["status"] == "partial"
    assert [item["interface_name"] for item in result["observations"]] == [
        "GigabitEthernet1/0/1"
    ]


def test_malformed_vrrp_row_makes_result_partial_but_keeps_valid_evidence() -> None:
    output = f"""
{VRRP_HEADER}
Vlan20 7 IPv4 120 0 Y Y Master local 192.0.2.20
Vlan21 8 IPv4 high 0 Y Y Backup 192.0.2.2 192.0.2.21
"""

    result = parse_cisco_fhrp_output("show vrrp brief", output, platform="cisco_ios")

    assert result["status"] == "partial"
    assert [item["interface_name"] for item in result["observations"]] == ["Vlan20"]


@pytest.mark.parametrize(
    ("command", "platform"),
    [
        ("show standby brief", "cisco_nxos"),
        ("show vrrp brief", "huawei_vrp"),
        ("show standby", "cisco_ios"),
        ("show running-config", "cisco_ios"),
        ("show standby brief", "unknown"),
    ],
)
def test_unknown_platform_or_command_is_unsupported(command: str, platform: str) -> None:
    result = parse_cisco_fhrp_output(command, HSRP_HEADER_WITH_P, platform=platform)

    assert result == {"status": "unsupported", "observations": []}


def test_device_command_rejection_is_unsupported() -> None:
    result = parse_cisco_fhrp_output(
        "show vrrp brief", "% Invalid input detected at '^' marker.\n", platform="cisco_ios"
    )

    assert result == {"status": "unsupported", "observations": []}
