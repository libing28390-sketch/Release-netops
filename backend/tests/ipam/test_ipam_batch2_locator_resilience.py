"""Batch 2 tests: next-hop CMDB lookup, LAG member expansion, /32 Loopback Direct route, wakeup ping, historical fallback, and smart terminal classification."""

from __future__ import annotations

import json

from core.interface_utils import normalize_interface_name
from database import get_db_connection
from services.cmdb_snapshot_service import begin_snapshot_attempt, complete_snapshot
from services.ip_locator_trace_service import (
    _count_edge_port_active_macs,
    _expand_lag_member_ports,
    _find_next_hop_device_candidates,
    _gateway_ping_command,
    _is_fit_ap_neighbor,
    _is_hypervisor_mac,
    _is_hypervisor_neighbor,
    _lldp_neighbors,
    _lookup_historical_last_seen,
    _topology_neighbors,
)


def _seed_device(conn, *, device_id: str, hostname: str, mgmt_ip: str, role: str = "aggregation") -> None:
    conn.execute(
        """INSERT INTO devices (id, hostname, ip_address, status, role, vendor, platform, tenant_id, site_id, site)
           VALUES (?, ?, ?, 'online', ?, 'huawei', 'huawei_vrp', 'tenant-default', 'site-b2', 'site-b2')
           ON CONFLICT (id) DO NOTHING""",
        (device_id, hostname, mgmt_ip, role),
    )


def test_find_next_hop_resolves_cmdb_multi_address_and_interfaces(isolated_db) -> None:
    del isolated_db
    with get_db_connection() as conn:
        _seed_device(conn, device_id="nh-cmdb", hostname="NH-CMDB", mgmt_ip="10.254.2.1")
        _seed_device(conn, device_id="nh-intf", hostname="NH-INTF", mgmt_ip="10.254.2.2")
        conn.execute(
            """INSERT INTO interfaces (id, device_id, interface_name, interface_type, primary_ip, ip_address, ip_prefix_length)
               VALUES ('if-nh-2', 'nh-intf', '10GE1/0/2', 'physical', '10.255.99.2', '10.255.99.2', 30)"""
        )
        conn.commit()

        attempt = begin_snapshot_attempt("nh-cmdb", "interface_inventory")
        observed_at = "2026-11-24T09:00:00+00:00"
        conn.execute(
            """INSERT INTO cmdb_device_interface_observations (
                   device_id, normalized_interface_name, interface_name, description,
                   admin_status, oper_status, ip_address, ip_prefix_length,
                   interface_type, generation, observed_at, run_id, metadata_json
               ) VALUES ('nh-cmdb', '10ge1/0/1', '10GE1/0/1', '', 'up', 'up', '10.255.99.1', 30, 'physical', ?, ?, ?, '{}')""",
            (attempt["generation"], observed_at, attempt["run_id"]),
        )
        conn.execute(
            """INSERT INTO cmdb_device_interface_address_observations (
                   device_id, normalized_interface_name, interface_name,
                   context_source, context_type, local_context_key, local_context_name,
                   ip_address, ip_prefix_length, generation, observed_at, run_id, metadata_json
               ) VALUES ('nh-cmdb', '10ge1/0/1', '10GE1/0/1', 'cli', 'global', '--', '--', '10.255.99.1'::inet, 30, ?, ?::timestamptz, ?, '{}'::jsonb)""",
            (attempt["generation"], observed_at, attempt["run_id"]),
        )
        assert complete_snapshot(conn, attempt, observed_at=observed_at, record_count=1, transport="cli")
        conn.commit()

        eligible = {
            "nh-cmdb": {"id": "nh-cmdb", "hostname": "NH-CMDB", "ip_address": "10.254.2.1"},
            "nh-intf": {"id": "nh-intf", "hostname": "NH-INTF", "ip_address": "10.254.2.2"},
        }
        res_cmdb = _find_next_hop_device_candidates(conn, "10.255.99.1", eligible)
        assert [d["id"] for d in res_cmdb] == ["nh-cmdb"]

        res_intf = _find_next_hop_device_candidates(conn, "10.255.99.2", eligible)
        assert [d["id"] for d in res_intf] == ["nh-intf"]


def test_lag_member_expansion_fixes_topology_and_live_lldp_matching(isolated_db) -> None:
    del isolated_db
    with get_db_connection() as conn:
        _seed_device(conn, device_id="agg-lag", hostname="AGG-LAG", mgmt_ip="10.254.3.1")
        _seed_device(conn, device_id="acc-lag", hostname="ACC-LAG", mgmt_ip="10.254.3.2", role="access")
        conn.execute(
            """INSERT INTO interfaces (id, device_id, interface_name, interface_type)
               VALUES ('if-lag-10', 'agg-lag', 'Eth-Trunk10', 'port_channel')"""
        )
        conn.execute(
            """INSERT INTO interfaces (id, device_id, interface_name, interface_type, parent_interface_id, channel_group)
               VALUES
               ('if-m1', 'agg-lag', 'GigabitEthernet1/0/1', 'physical', 'if-lag-10', 10),
               ('if-m2', 'agg-lag', 'GigabitEthernet1/0/2', 'physical', 'if-lag-10', 10)"""
        )
        # Topology link stored ONLY on physical member port without source_aggregation_name
        conn.execute(
            """INSERT INTO topology_links (
                   id, source_device_id, source_port, source_port_normalized,
                   target_device_id, target_port, target_port_normalized,
                   status, discovery_source, confidence, last_seen, updated_at
               ) VALUES (
                   'lnk-lag-1', 'agg-lag', 'GigabitEthernet1/0/1', ?,
                   'acc-lag', 'GigabitEthernet1/0/48', ?,
                   'up', 'lldp_snmp', 0.95, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
               )""",
            (
                normalize_interface_name("GigabitEthernet1/0/1").lower(),
                normalize_interface_name("GigabitEthernet1/0/48").lower(),
            ),
        )
        conn.commit()

        expanded = _expand_lag_member_ports(conn, "agg-lag", "Eth-Trunk10")
        assert normalize_interface_name("GigabitEthernet1/0/1").lower() in expanded
        assert normalize_interface_name("GigabitEthernet1/0/2").lower() in expanded

        neighbors = _topology_neighbors(conn, "agg-lag", "Eth-Trunk10")
        assert len(neighbors) == 1
        assert neighbors[0]["neighbor_id"] == "acc-lag"

        # Live LLDP matching on physical member port when tracing Eth-Trunk10
        lldp_records = [
            {"local_interface": "GigabitEthernet1/0/2", "neighbor": "ACC-LAG", "neighbor_port": "Gi1/0/47"},
        ]
        matched_lldp = _lldp_neighbors(
            {"id": "agg-lag", "hostname": "AGG-LAG"},
            "Eth-Trunk10",
            records=lldp_records,
            member_ports=expanded,
        )
        assert len(matched_lldp) == 1
        assert matched_lldp[0]["neighbor_name"] == "ACC-LAG"


def test_gateway_ping_commands_historical_fallback_and_smart_terminal_helpers(isolated_db) -> None:
    del isolated_db
    assert _gateway_ping_command({"platform": "huawei_vrp"}, "192.168.1.5", "VRF_OA") == "ping -vpn-instance VRF_OA -c 2 -t 1000 192.168.1.5"
    assert _gateway_ping_command({"platform": "cisco_iosxe"}, "192.168.1.5", "VRF_OA") == "ping vrf VRF_OA 192.168.1.5 repeat 2 timeout 1"
    assert _gateway_ping_command({"platform": "juniper_junos"}, "192.168.1.5", "default") == "ping count 2 wait 1 192.168.1.5"

    assert _is_hypervisor_mac("00:50:56:ab:cd:ef") is True
    assert _is_hypervisor_mac("52:54:00:11:22:33") is True
    assert _is_hypervisor_mac("4c:1f:cc:11:22:33") is False
    assert _is_fit_ap_neighbor({"neighbor_name": "3F-East-AP06"}) is True
    assert _is_hypervisor_neighbor({"neighbor_name": "prod-esxi-08.corp.local"}) is True

    with get_db_connection() as conn:
        _seed_device(conn, device_id="acc-edge", hostname="ACC-EDGE", mgmt_ip="10.254.4.1", role="access")
        conn.execute(
            """INSERT INTO mac_table (id, device_id, mac_address, interface_name, vlan_id, last_updated)
               VALUES
               ('mac-1', 'acc-edge', '00:11:22:33:44:01', 'GigabitEthernet1/0/12', 55, CURRENT_TIMESTAMP),
               ('mac-2', 'acc-edge', '00:11:22:33:44:02', 'GigabitEthernet1/0/12', 55, CURRENT_TIMESTAMP),
               ('mac-3', 'acc-edge', '00:11:22:33:44:03', 'GigabitEthernet1/0/12', 55, CURRENT_TIMESTAMP)"""
        )
        conn.execute(
            """INSERT INTO network_endpoints (id, ip, mac, switch_id, switch_port, vlan, first_seen, last_seen)
               VALUES ('ep-1', '192.168.55.88', '00:11:22:33:44:01', 'acc-edge', 'GigabitEthernet1/0/12', '55', '2026-11-23T08:00:00+08:00', '2026-11-23T18:30:00+08:00')"""
        )
        conn.commit()

        assert _count_edge_port_active_macs(conn, "acc-edge", "GigabitEthernet1/0/12") == 3
        scope = {"tenant_id": "tenant-default", "authorized_device_ids": ["acc-edge"]}
        # Legacy endpoints lack the scoped discovery evidence required by the locator.
        assert _lookup_historical_last_seen(conn, "192.168.55.88", **scope) is None
        conn.execute(
            """INSERT INTO ipam_discovery_snapshots (
                   id, collector, device_id, source_device_name, tenant_id, site_id,
                   vrf_context_status, scope_status, source_run_id, source_version,
                   source_status, coverage_status, coverage_complete, coverage_reason,
                   entry_count, observed_at, projected_at
               ) VALUES ('hist-snap', 'arp', 'acc-edge', 'ACC-EDGE', 'tenant-default', 'site-b2',
                         'unknown', 'scope_pending', '', 'hist-v1', 'success', 'unavailable', 0,
                         'test_positive_only', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        )
        conn.execute(
            """INSERT INTO ipam_discovery_observations (
                   id, snapshot_id, source_type, source_device_id, source_device_name,
                   tenant_id, site_id, vrf_context_status, scope_status,
                   ip, mac, interface_name, vlan, source_identity_key,
                   source_observed_at, timestamp_status, projected_at
               ) VALUES ('hist-obs', 'hist-snap', 'arp', 'acc-edge', 'ACC-EDGE',
                         'tenant-default', 'site-b2', 'unknown', 'scope_pending',
                         '192.168.55.88', '00:11:22:33:44:01', 'GigabitEthernet1/0/12', '55',
                         'hist-key', CURRENT_TIMESTAMP, 'valid', CURRENT_TIMESTAMP)"""
        )
        conn.commit()
        assert _lookup_historical_last_seen(conn, "192.168.55.88", tenant_id="other", authorized_device_ids=["acc-edge"]) is None
        assert _lookup_historical_last_seen(conn, "192.168.55.88", tenant_id="tenant-default", authorized_device_ids=[]) is None
        hist = _lookup_historical_last_seen(conn, "192.168.55.88", **scope)
        assert hist is not None
        assert hist["status"] == "offline_historical_snapshot"
        assert hist["device_id"] == "acc-edge"
        assert hist["port"] == "GigabitEthernet1/0/12"
