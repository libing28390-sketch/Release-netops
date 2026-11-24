"""Batch 4 tests: VSYS/HA entity schema & Active>Standby Radix priority, VXLAN VTEP leaf lookup, DNAT/SLB VIP real-server penetration, and 5D holographic panorama."""

from __future__ import annotations

import json

from database import get_db_connection
from services.ipam_panorama_service import (
    get_device_holographic_panorama,
    penetrate_vip_real_servers,
    resolve_vxlan_vtep_leaf,
)
from services.ipam_radix_index_service import build_ipam_radix_index


def test_ha_active_standby_priority_vxlan_vtep_dnat_and_5d_panorama(isolated_db) -> None:
    del isolated_db
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO devices (
                   id, hostname, ip_address, status, role, vendor, platform,
                   tenant_id, site_id, site, vsys_id, ha_cluster_id, ha_role, base_mac
               ) VALUES
               ('fw-active', 'FW-ACTIVE', '10.254.20.1', 'online', 'firewall', 'fortinet', 'fortinet', 'tenant-default', 'site-dc', 'site-dc', 'vsys_prod', 'ha-fw-01', 'ACTIVE', 'AABBCC112233'),
               ('fw-standby', 'FW-STANDBY', '10.254.20.2', 'online', 'firewall', 'fortinet', 'fortinet', 'tenant-default', 'site-dc', 'site-dc', 'vsys_prod', 'ha-fw-01', 'STANDBY', 'AABBCC112244'),
               ('leaf-17', 'DC-LEAF-17', '10.254.20.17', 'online', 'access', 'huawei', 'huawei_vrp', 'tenant-default', 'site-dc', 'site-dc', 'default', '', 'STANDALONE', '4C1FCC000017')"""
        )
        conn.execute(
            """INSERT INTO interfaces (
                   id, device_id, interface_name, interface_type, primary_ip, ip_address,
                   ip_prefix_length, admin_status, oper_status, speed, duplex, encap_vlan_id, description
               ) VALUES
               ('if-fw-a', 'fw-active', 'port1.100', 'sub_interface', '172.16.100.1', '172.16.100.1', 24, 'up', 'up', 10000000000, 'full', 100, 'Prod Gateway'),
               ('if-fw-b', 'fw-standby', 'port1.100', 'sub_interface', '172.16.100.1', '172.16.100.1', 24, 'up', 'up', 10000000000, 'full', 100, 'Prod Gateway'),
               ('if-leaf-vtep', 'leaf-17', 'LoopBack1', 'loopback', '10.254.255.17', '10.254.255.17', 32, 'up', 'up', 0, '', NULL, 'VXLAN VTEP')"""
        )
        conn.execute(
            """INSERT INTO ipam_vips (
                   id, address, vip_type, device_id, real_servers, tenant_id, status, created_at, updated_at
               ) VALUES (
                   'vip-slb-1', '172.16.200.80', 'f5', 'fw-active', ?, 'tenant-default', 'active', '2026-11-24T08:00:00Z', '2026-11-24T08:00:00Z'
               )""",
            (json.dumps([{"ip": "10.10.50.11", "port": 8443, "status": "up"}, {"ip": "10.10.50.12", "port": 8443, "status": "up"}]),),
        )
        conn.execute(
            """INSERT INTO topology_links (
                   id, source_device_id, source_hostname, source_port, source_port_normalized,
                   target_device_id, target_hostname, target_port, target_port_normalized,
                   status, discovery_source, confidence, last_seen, updated_at
               ) VALUES (
                   'lnk-fw-leaf', 'fw-active', 'FW-ACTIVE', 'port1.100', 'port1.100',
                   'leaf-17', 'DC-LEAF-17', '10GE1/0/48', '10ge1/0/48',
                   'up', 'lldp_snmp', 0.9, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
               )"""
        )
        conn.commit()

        # 1. HA ACTIVE sorts ahead of HA STANDBY in Radix Tree
        idx = build_ipam_radix_index(conn)
        cidr, gws = idx.lookup_connected_gateways("172.16.100.55")
        assert cidr == "172.16.100.0/24"
        assert [g.device_id for g in gws] == ["fw-active", "fw-standby"]

        # 2. EVPN VXLAN VTEP Loopback IP resolves to remote Leaf-17
        leaf = resolve_vxlan_vtep_leaf(conn, "10.254.255.17")
        assert leaf is not None
        assert leaf["device_id"] == "leaf-17"
        assert leaf["vtep_interface"] == "LoopBack1"

        # 3. DNAT / F5 VIP penetration returns backend Real Server IPs
        reals = penetrate_vip_real_servers(conn, "172.16.200.80", tenant_id="tenant-default")
        assert [r["real_ip"] for r in reals] == ["10.10.50.11", "10.10.50.12"]

        # 4. 5-Dimension Holographic Panorama
        pano = get_device_holographic_panorama("fw-active", highlight_port="port1.100", conn=conn)
        assert pano is not None
        assert pano["asset_identity"]["vsys_id"] == "vsys_prod"
        assert pano["asset_identity"]["ha_role"] == "ACTIVE"
        assert pano["asset_identity"]["base_mac"] == "AABBCC112233"
        assert pano["target_port_diagnostics"]["encap_vlan_id"] == 100
        assert pano["target_port_diagnostics"]["duplex"] == "full"
        assert len(pano["l3_interfaces"]) == 1
        assert len(pano["topology_neighbors"]) == 1
        assert pano["topology_neighbors"][0]["peer_device_id"] == "leaf-17"
