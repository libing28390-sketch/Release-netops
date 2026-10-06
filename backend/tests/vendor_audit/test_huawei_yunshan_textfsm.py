"""Synthetic YunShan captures following Huawei's documented CLI shapes.

These are sanitized grammar fixtures, not evidence of a live device test.
The combined VRP Software/YunShan banner is documented in Huawei's S16700
V600R025C00 LLDP command reference (EDOC1100515417).
"""
from pathlib import Path

import pytest

from core import textfsm as textfsm_core
from drivers.netmiko_driver import NetmikoDriver
from drivers.scrapli_driver import ScrapliDriver
from engine.drivers.netmiko_driver import NetmikoDriver as EngineNetmikoDriver


TEMPLATES = Path(__file__).resolve().parents[3] / "data" / "textfsm_templates"
SAMPLES = [
    ("display version", """Huawei YunShan OS
Version 1.24.0.1 (S5700 V600R024C00SPC100)
Copyright (C) Huawei Technologies Co., Ltd.
HUAWEI S5755-H48T4Y2CZ uptime is 3 days, 2 hours, 1 minute
Patch Version: V600R024HP0010
MPU(Master) 0 : uptime is 3 days, 2 hours, 0 minutes
Memory Size : 4096 M bytes
""", [{"MODEL": "S5755-H48T4Y2CZ", "VERSION": "1.24.0.1", "PATCH_VERSION": "V600R024HP0010"}]),
    ("display version", """<LAB-CE> display version
Huawei Versatile Routing Platform Software
YunShan OS, Version 1.25.1.1 (CE6800 V300R025C10SPC500)
Copyright (C) Huawei Technologies Co., Ltd.
HUAWEI CE6863H-48S6CQ uptime is 1 day, 4 hours, 20 minutes
MPU(Master) 1 : uptime is 1 day, 4 hours, 19 minutes
StartupTime 2026/01/01 00:00:00
""", [{"MODEL": "CE6863H-48S6CQ", "PRODUCT_VERSION": "CE6800 V300R025C10SPC500"}]),
    ("display interface brief", """PHY: Physical
*down: administratively down
Interface PHY Protocol InUti OutUti inErrors outErrors
GE1/0/1 up up 0.01% 1.20% 0 2
10GE1/0/2 down down -- -- 0 0
""", [{"INTERFACE": "GE1/0/1", "PHY": "up"}, {"INTERFACE": "10GE1/0/2", "PHY": "down"}]),
    ("display interface brief", """Interface PHY Protocol InUti OutUti inErrors outErrors
400GE 1/0/1 up up 45.50% 0.00% 7 0
Eth-Trunk10 up up 0% 0% 0 0
25GE1/0/3 *down down -- -- 0 0
""", [{"INTERFACE": "400GE 1/0/1"}, {"INTERFACE": "Eth-Trunk10"}, {"INTERFACE": "25GE1/0/3", "PHY": "*down"}]),
    ("display ip interface brief", """*down: administratively down
The number of interface that is UP in Physical is 2
Interface IP Address/Mask Physical Protocol VPN
Vlanif10 192.0.2.1/24 up up --
MEth0/0/0 unassigned down down --
""", [{"INTERFACE": "Vlanif10", "IP_ADDRESS": "192.0.2.1", "PREFIX_LENGTH": "24"}, {"INTERFACE": "MEth0/0/0", "IP_ADDRESS": "unassigned"}]),
    ("display ip interface brief", """Interface IP Address/Mask Physical Protocol
LoopBack0 198.51.100.1/32 up up(s)
10GE 1/0/1 203.0.113.1/30 *down down
""", [{"INTERFACE": "LoopBack0", "PROTOCOL": "up(s)", "PREFIX_LENGTH": "32"}, {"INTERFACE": "10GE 1/0/1", "PHY": "*down", "PREFIX_LENGTH": "30"}]),
    ("display lldp neighbor brief", """Local Interface Exptime(s) Neighbor Interface Neighbor Device
10GE1/0/1 103 10GE1/0/2 lab-core
400GE 1/0/3 96 400GE 1/0/4 lab-spine
""", [{"INTERFACE": "10GE1/0/1", "NEIGHBOR_NAME": "lab-core"}, {"INTERFACE": "400GE 1/0/3", "NEIGHBOR_INTERFACE": "400GE 1/0/4"}]),
    ("display lldp neighbor brief", """Local Intf Neighbor Dev Neighbor Intf Exptime(s)
25GE1/0/1 lab-leaf 25GE1/0/2 110
Eth-Trunk1 lab-stack Eth-Trunk2 92
""", [{"INTERFACE": "25GE1/0/1", "EXPIRED_TIME": "110"}, {"INTERFACE": "Eth-Trunk1", "NEIGHBOR_NAME": "lab-stack"}]),
    ("display arp", """IP ADDRESS MAC ADDRESS EXPIRE(M) TYPE INTERFACE VPN-INSTANCE
VLAN/CEVLAN PVC
192.0.2.10 0200-0000-0010 18 D-0 10GE1/0/1 --
                  10/-
192.0.2.1 0200-0000-0001 - I Vlanif10 --
Total:2 Dynamic:1 Static:0 Interface:1
""", [{"IP_ADDRESS": "192.0.2.10", "INTERFACE": "10GE1/0/1", "VLAN": "10"}, {"IP_ADDRESS": "192.0.2.1", "INTERFACE": "Vlanif10"}]),
    ("display arp", """IP ADDRESS MAC ADDRESS EXPIRE(M) TYPE INTERFACE VPN-INSTANCE
198.51.100.2 0200-0000-0002 8 D-0 100GE 1/0/1 blue
198.51.100.3 0200-0000-0003 - S Eth-Trunk20 blue
--------------------------------------------
Total:2 Dynamic:1 Static:1 Interface:0
""", [{"IP_ADDRESS": "198.51.100.2", "VPN_INSTANCE": "blue"}, {"IP_ADDRESS": "198.51.100.3", "INTERFACE": "Eth-Trunk20"}]),
    ("display mac-address", """MAC Address VLAN/VSI/BD Learned-From Type
0200-0000-0001 10 10GE1/0/1 dynamic
0200-0000-0002 20 Eth-Trunk10 static
Total items displayed = 2
""", [{"MAC_ADDRESS": "0200-0000-0001", "INTERFACE": "10GE1/0/1"}, {"MAC_ADDRESS": "0200-0000-0002", "VLAN": "20"}]),
    ("display mac-address", """MAC Address VLAN/VSI/BD PEVLAN CEVLAN Port Type LSP/LSR-ID
0200-0000-0003 30 - - 100GE 1/0/1 dynamic -
0200-0000-0004 40 - - 25GE1/0/4 static -
""", [{"MAC_ADDRESS": "0200-0000-0003", "INTERFACE": "100GE 1/0/1"}, {"MAC_ADDRESS": "0200-0000-0004", "VLAN": "40"}]),
]


@pytest.mark.parametrize("command,output,expected", SAMPLES)
def test_yunshan_templates_parse_two_shapes_per_command(command, output, expected):
    result = textfsm_core.smart_parse_cli(output, command, platform="huawei_yunshan")
    assert result["success"], result
    assert result["template"].startswith("huawei_yunshan_")
    assert len(result["data"]) == len(expected)
    for row, fields in zip(result["data"], expected, strict=True):
        for field, value in fields.items():
            assert row[field] == value


@pytest.mark.parametrize("alias", [
    "huawei_yunshan", "YunShan OS", "yunshan", "yunshanos", "huawei_yunshan_os",
    "yunshan_os", "Huawei YunShan OS", "华为云杉", "华为 YunShan OS（云杉）", "华为 YunShan OS (云杉)",
])
def test_parser_and_driver_aliases_keep_a_distinct_parser_family(alias):
    assert textfsm_core.resolve_textfsm_platform(alias) == "huawei_yunshan"
    assert textfsm_core._template_platform_candidates(alias) == ["huawei_yunshan"]
    device = {"vendor": "Huawei", "platform": alias, "ip_address": "192.0.2.1"}
    assert NetmikoDriver(device).device_type == "huawei"
    assert EngineNetmikoDriver(device).device_type == "huawei"
    assert ScrapliDriver(device).platform_type == "huawei_vrp"


def test_catalog_filter_and_namespace_are_independent_of_vrp():
    items = textfsm_core.list_templates(platform_family_filter="huawei_yunshan", vendor_filter="huawei", version_filter="common")
    assert len(items) == 6
    assert all(item["platform"] == item["platform_family"] == "huawei_yunshan" for item in items)
    assert {item["command"] for item in items} == {command for command, _, _ in SAMPLES}
    assert textfsm_core.resolve_textfsm_template_namespace("huawei_yunshan", version="common") == "huawei_yunshan"
    assert textfsm_core._find_template("huawei_yunshan", "display cpu-usage") is None
    assert textfsm_core._find_template("huawei_vrp8", "display version").name != "huawei_yunshan_display_version.textfsm"


def test_vrp_output_cannot_be_accepted_as_yunshan_version():
    output = """Huawei Versatile Routing Platform Software
VRP (R) software, Version 8.180 (S5700 V200R019C10)
HUAWEI S5700 Router uptime is 1 day, 1 hour, 1 minute
"""
    assert not textfsm_core.smart_parse_cli(output, "display version", platform="huawei_yunshan")["success"]


def test_missing_namespace_does_not_select_legacy_vrp_grammar(tmp_path, monkeypatch):
    (tmp_path / "huawei_vrp_display_version.textfsm").write_text("legacy", encoding="utf-8")
    monkeypatch.setattr(textfsm_core, "_CUSTOM_TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(textfsm_core, "_get_packaged_templates_dir", lambda: None)
    monkeypatch.setattr(textfsm_core, "_get_builtin_templates_dir", lambda: None)
    assert textfsm_core._find_template("huawei_yunshan", "display version") is None


def test_every_yunshan_template_has_a_matching_action_association():
    associations = {
        "display_version": "get_version", "display_interface_brief": "get_interface_brief",
        "display_ip_interface_brief": "get_ip_interfaces", "display_lldp_neighbor_brief": "get_lldp_neighbors",
        "display_arp": "get_arp_table", "display_mac_address": "get_mac_table",
    }
    for command, action in associations.items():
        content = (TEMPLATES / f"huawei_yunshan_{command}.textfsm").read_text(encoding="utf-8")
        assert textfsm_core.template_action_code(content) == action


@pytest.mark.parametrize("command,output,_expected", SAMPLES[::2])
def test_yunshan_records_satisfy_registered_consumer_field_names(command, output, _expected):
    from services.operational_data_service import parse_device_cli_output
    from services.platform_registry_service import (
        PLATFORM_ACTION_COMMANDS, _normalize_records, iter_action_definitions,
    )

    action = next(code for code, cli in PLATFORM_ACTION_COMMANDS['huawei_yunshan'].items() if cli == command)
    required = set(next(item['fields'] for item in iter_action_definitions() if item['action_code'] == action))
    result = parse_device_cli_output({
        'vendor': 'Huawei', 'platform': 'huawei_yunshan',
        'profile_platform_code': 'huawei_yunshan', 'profile_parser_platform': 'huawei_yunshan',
        'profile_connection_driver': 'huawei_vrp',
    }, command, output)
    assert result['parse_status'] == 'matched', result
    assert result['parser_platform'] == 'huawei_yunshan'
    records = _normalize_records(result['records'], 100, expected_fields=required)
    assert records
    assert all(required.issubset(record) for record in records)
