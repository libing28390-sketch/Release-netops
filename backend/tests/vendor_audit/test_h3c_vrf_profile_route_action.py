from __future__ import annotations

from services import ip_locator_service
from services.operational_data_service import parse_device_cli_output


H3C_VRF_LIST_OUTPUT_WITH_PROMPTS = """\
[S6850_1]
Total VPN-Instances configured : 2
VPN-Instance Name               RD                     Create time
VRF_A                           100:1                  2026/11/10 20:14:33
VRF_B                           200:1                  2026/11/10 20:14:33
[S6850_1]
"""


H3C_VRF_ROUTE_OUTPUT = """\
[S6850_1]display ip routing-table vpn-instance VRF_A
Destinations : 8        Routes : 8

Destination/Mask   Proto   Pre Cost        NextHop         Interface
0.0.0.0/32         Direct  0   0           127.0.0.1       InLoop0
127.0.0.0/8        Direct  0   0           127.0.0.1       InLoop0
127.0.0.0/32       Direct  0   0           127.0.0.1       InLoop0
127.0.0.1/32       Direct  0   0           127.0.0.1       InLoop0
127.255.255.255/32 Direct  0   0           127.0.0.1       InLoop0
224.0.0.0/4        Direct  0   0           0.0.0.0         NULL0
224.0.0.0/24       Direct  0   0           0.0.0.0         NULL0
255.255.255.255/32 Direct  0   0           127.0.0.1       InLoop0
[S6850_1]
"""


H3C_V7_CONTEXT = {
    "raw_platform": "h3c_comware",
    "public_platform": "h3c_comware",
    "profile_platform_code": "h3c_comware",
    "parser_platform": "h3c_comware_v7",
    "parser_family": "h3c_comware",
}


def _fake_vrf_command(monkeypatch, output: str) -> list[str]:
    commands: list[str] = []

    def send_command(_device: dict, command: str, **_kwargs) -> str:
        commands.append(command)
        assert command == "display ip vpn-instance"
        return output

    monkeypatch.setattr(ip_locator_service, "_send_command", send_command)
    return commands


def test_profile_backed_h3c_discovers_live_vrfs_and_ignores_prompt_header(monkeypatch):
    commands = _fake_vrf_command(monkeypatch, H3C_VRF_LIST_OUTPUT_WITH_PROMPTS)
    device = {
        "id": "fixture-s6850-1",
        "hostname": "S6850_1",
        "platform": "h3c_comware",
        "platform_profile_id": "fixture-h3c-comware-v7-profile",
    }

    assert ip_locator_service._collect_device_vrfs(device) == [
        "default",
        "VRF_A",
        "VRF_B",
    ]
    assert commands == ["display ip vpn-instance"]


def test_h3c_vrf_discovery_does_not_return_prompt_as_a_vrf(monkeypatch):
    _fake_vrf_command(monkeypatch, H3C_VRF_LIST_OUTPUT_WITH_PROMPTS)
    device = {
        "id": "fixture-s6850-1-unbound",
        "hostname": "S6850_1",
        "platform": "h3c_comware",
    }

    assert ip_locator_service._collect_device_vrfs(device) == [
        "default",
        "VRF_A",
        "VRF_B",
    ]


def test_profile_route_candidates_merge_live_known_and_configured_contexts(monkeypatch):
    commands = _fake_vrf_command(monkeypatch, H3C_VRF_LIST_OUTPUT_WITH_PROMPTS)
    device = {
        "id": "fixture-s6850-1",
        "hostname": "S6850_1",
        "platform": "h3c_comware",
        "platform_profile_id": "fixture-h3c-comware-v7-profile",
        "vrf_name": "MGMT",
    }

    assert ip_locator_service._route_collection_vrf_candidates(
        device,
        {"VRF_A", "vrf_a", "KNOWN_ONLY"},
    ) == ["default", "KNOWN_ONLY", "MGMT", "VRF_A", "VRF_B"]
    assert commands == ["display ip vpn-instance"]


def test_h3c_profile_vrf_route_action_records_normalize_for_route_cache():
    parsed = parse_device_cli_output(
        {
            "id": "fixture-s6850-1",
            "hostname": "S6850_1",
            "platform": "h3c_comware",
            "platform_profile_id": "fixture-h3c-comware-v7-profile",
        },
        "display ip routing-table vpn-instance VRF_A",
        H3C_VRF_ROUTE_OUTPUT,
        context=H3C_V7_CONTEXT,
    )

    assert parsed["parse_status"] == "matched", parsed
    assert len(parsed["records"]) == 8
    assert all(
        record.get("network") and record.get("prefix_length") is not None
        and record.get("nexthop_ip") and record.get("nexthop_if")
        for record in parsed["records"]
    )

    normalized = ip_locator_service._normalize_profile_route_records(
        "fixture-s6850-1", "VRF_A", parsed["records"]
    )

    assert len(normalized) == 8
    first_route = normalized[0]
    assert first_route["device_id"] == "fixture-s6850-1"
    assert first_route["vrf_name"] == "VRF_A"
    assert first_route["prefix"] == "0.0.0.0"
    assert first_route["mask"] == "32"
    assert first_route["next_hop"] == "127.0.0.1"
    assert first_route["interface"] == "InLoop0"
    assert first_route["protocol"]
    assert first_route["metric"] == 0
    assert isinstance(first_route["metric"], int)
    assert first_route["preference"] == 0


def test_incomplete_profile_route_batch_does_not_replace_a_cached_scope():
    normalized = ip_locator_service._normalize_profile_route_records(
        "fixture-s6850-1",
        "VRF_A",
        [
            {
                "network": "192.168.10.0",
                "prefix_length": "24",
                "nexthop_ip": "192.168.10.1",
                "nexthop_if": "Vlan-interface10",
                "protocol": "Direct",
            },
            {
                "network": "192.168.11.0",
                "prefix_length": "24",
                "nexthop_ip": "192.168.10.1",
                "nexthop_if": "",
                "protocol": "Direct",
            },
        ],
    )

    assert normalized == []
