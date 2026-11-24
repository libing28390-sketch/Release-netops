"""Batch 3 tests: multi-vendor interface config block parser, Huawei/NX-OS FHRP, SNMP .4.20 mask backfill, Down-IP retention, and debounced event refresh."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from database import get_db_connection
from services import snmp_service
from services.interface_collection_service import _upsert_interfaces
from services.interface_config_parser import (
    interface_config_command_for_platform,
    parse_interface_config_blocks,
)
from services.ipam_event_refresh_service import (
    classify_network_event,
    ingest_network_change_event,
)
from services.ipam_fhrp_parser import parse_fhrp_output


def test_interface_config_parser_extracts_vrf_secondary_vip_encap_vlan_and_shutdown() -> None:
    huawei_cfg = """
#
interface GigabitEthernet0/0/1.999
 description To_Prod_App
 dot1q termination vid 100
 ip binding vpn-instance VRF_PROD
 ip address 10.100.1.1 255.255.255.0
 ip address 10.100.2.1 255.255.255.0 sub
 vrrp vrid 10 virtual-ip 10.100.1.254
#
interface Vlanif55
 description Cutover_Old_GW
 ip address 192.168.55.1 24
 shutdown
#
interface Dialer1
 ip address ppp-negotiate
#
"""
    parsed = parse_interface_config_blocks(huawei_cfg)
    by_name = {i["interface_name"]: i for i in parsed["interfaces"]}

    sub_if = by_name["GigabitEthernet0/0/1.999"]
    assert sub_if["encap_vlan_id"] == 100
    assert sub_if["vrf_name"] == "VRF_PROD"
    assert sub_if["is_admin_down"] is False
    assert len(sub_if["addresses"]) == 2
    assert sub_if["addresses"][0]["ip_address"] == "10.100.1.1"
    assert sub_if["addresses"][0]["is_secondary"] is False
    assert sub_if["addresses"][1]["ip_address"] == "10.100.2.1"
    assert sub_if["addresses"][1]["is_secondary"] is True
    assert len(parsed["vips"]) == 1
    assert parsed["vips"][0] == {
        "protocol": "vrrp",
        "group_id": 10,
        "virtual_ip": "10.100.1.254",
        "interface_name": "GigabitEthernet0/0/1.999",
        "vrf_name": "VRF_PROD",
    }

    down_if = by_name["Vlanif55"]
    assert down_if["is_admin_down"] is True
    assert down_if["addresses"][0]["ip_address"] == "192.168.55.1"
    assert down_if["addresses"][0]["prefix_length"] == 24
    assert by_name["Dialer1"]["dynamic_mode"] == "ppp-negotiate"

    assert interface_config_command_for_platform("huawei_vrp") == "display current-configuration interface"
    assert interface_config_command_for_platform("cisco_nxos") == "show running-config interface"
    assert interface_config_command_for_platform("cisco_iosxe") == "show running-config | section ^interface"


def test_huawei_vrp_and_cisco_nxos_fhrp_parsers() -> None:
    huawei_out = """
Total:2     Master:1     Backup:1     Non-active:0
VRID  State        Interface                Type     Virtual IP
----------------------------------------------------------------
Vlanif100  100  Master   10.10.10.254   Normal
Vlanif200  200  Backup   10.10.20.254   Normal
"""
    res = parse_fhrp_output("display vrrp brief", huawei_out, platform="huawei_vrp")
    assert res["status"] == "complete"
    assert len(res["observations"]) == 2
    assert res["observations"][0]["state"] == "master"
    assert res["observations"][0]["virtual_ip"] == "10.10.10.254"
    assert res["observations"][1]["state"] == "backup"

    nxos_out = """
Interface   Grp  Prio P State    Active addr      Standby addr     Group addr
Vlan10      10   110  P Active   local            10.1.10.253      10.1.10.254
"""
    nx_res = parse_fhrp_output("show hsrp brief", nxos_out, platform="cisco_nxos")
    assert nx_res["status"] == "complete"
    assert len(nx_res["observations"]) == 1
    assert nx_res["observations"][0]["protocol"] == "hsrp"
    assert nx_res["observations"][0]["state"] == "active"
    assert nx_res["observations"][0]["virtual_ip"] == "10.1.10.254"


def test_snmp_ip_address_table_backfills_missing_mask_from_legacy_ip_addr_table() -> None:
    fake_v4_columns = {
        "if_index": {"1.4.10.1.1.1": 10},
        "address_type": {"1.4.10.1.1.1": 1},
        "prefix": {"1.4.10.1.1.1": "0.0"},  # zeroDotZero bug!
        "status": {"1.4.10.1.1.1": 1},
    }
    fake_legacy = [
        {
            "if_index": 10,
            "interface": "Vlanif10",
            "ip_address": "10.1.1.1",
            "ip_version": 4,
            "prefix_length": 24,
            "address_status": "preferred",
            "address_type": 1,
            "source_mib": "ipAddrTable",
        }
    ]
    with (
        patch.object(snmp_service, "_snmp_walk_columns_complete", new=AsyncMock(return_value=fake_v4_columns)),
        patch.object(snmp_service, "collect_legacy_ip_addr_table", new=AsyncMock(return_value=fake_legacy)),
    ):
        rows = asyncio.run(
            snmp_service.collect_interface_ip_addresses("10.0.0.1", "public", {10: "Vlanif10"})
        )
    assert len(rows) == 1
    assert rows[0]["ip_address"] == "10.1.1.1"
    assert rows[0]["prefix_length"] == 24


def test_upsert_interfaces_preserves_configured_ip_on_down_interface_and_event_refresh(isolated_db) -> None:
    del isolated_db
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO devices (id, hostname, ip_address, status, role, vendor, platform, tenant_id)
               VALUES ('dev-b3', 'SW-B3', '10.254.9.1', 'online', 'core', 'huawei', 'huawei_vrp', 'tenant-default')"""
        )
        conn.execute(
            """INSERT INTO interfaces (id, device_id, interface_name, interface_type, primary_ip, ip_address, ip_prefix_length, admin_status, oper_status)
               VALUES ('if-down-1', 'dev-b3', '10GE1/0/9', 'physical', '10.255.9.1', '10.255.9.1', 30, 'up', 'down')"""
        )
        conn.commit()

    # Sync only another UP interface; 10GE1/0/9 is absent from active SNMP IP table because it is DOWN
    _upsert_interfaces(
        {"id": "dev-b3", "hostname": "SW-B3"},
        [{"interface_name": "LoopBack0", "interface_ip": "10.0.0.9", "prefix_length": 32, "admin_status": "up", "oper_status": "up"}],
    )

    with get_db_connection() as conn:
        row = conn.execute("SELECT primary_ip, ip_address, ip_prefix_length FROM interfaces WHERE id = 'if-down-1'").fetchone()
    assert row["primary_ip"] == "10.255.9.1"
    assert row["ip_address"] == "10.255.9.1"
    assert row["ip_prefix_length"] == 30

    # Verify Syslog/Trap event classification & debouncing
    assert classify_network_event(raw_message="%SYS-5-CONFIG_I: Configured from console") == "config_change"
    assert classify_network_event(raw_message="IFNET/4/LINK_STATE:GigabitEthernet1/0/1 down") == "link_state_change"
    assert classify_network_event(raw_message="lldpRemTablesChange trap received") == "lldp_change"

    first = ingest_network_change_event(device_ip="10.254.9.1", raw_message="%SYS-5-CONFIG_I: Configured")
    assert first["accepted"] is True
    assert first["debounced"] is False
    assert "invalidated_radix_index" in first["actions"]

    second = ingest_network_change_event(device_ip="10.254.9.1", raw_message="%SYS-5-CONFIG_I: Configured")
    assert second["accepted"] is True
    assert second["debounced"] is True
