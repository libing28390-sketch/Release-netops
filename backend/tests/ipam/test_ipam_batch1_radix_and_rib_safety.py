"""Batch 1 tests: Iron Rule #2 RIB safety, multi-domain ip_inventory, down-gateway filtering, and Exact_IP_Map + Per_VRF_Radix_Tree."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from core.interface_utils import normalize_interface_name
from database import get_db_connection
from services import ip_locator_service, prefix_discovery_service, snmp_service
from services.cmdb_snapshot_service import begin_snapshot_attempt, complete_snapshot
from services.interface_collection_service import _upsert_snmp_ip_inventory
from services.ip_locator_trace_service import trace_ip
from services.ipam_address_space_service import create_address_space
from services.ipam_radix_index_service import (
    build_ipam_radix_index,
    invalidate_ipam_radix_index,
)
from services.ipam_service import create_subnet, get_prefix_gateway_candidates


def _seed_site_and_device(conn, *, site_id: str, device_id: str, hostname: str, mgmt_ip: str, role: str = "aggregation") -> None:
    conn.execute(
        """INSERT INTO sites (id, site_code, site_name, tenant_id)
           VALUES (?, ?, ?, 'tenant-default')
           ON CONFLICT (id) DO NOTHING""",
        (site_id, site_id.upper(), site_id.upper()),
    )
    conn.execute(
        """INSERT INTO devices (id, hostname, ip_address, status, role, vendor, platform, tenant_id, site_id, site)
           VALUES (?, ?, ?, 'online', ?, 'huawei', 'huawei_vrp', 'tenant-default', ?, ?)
           ON CONFLICT (id) DO NOTHING""",
        (device_id, hostname, mgmt_ip, role, site_id, site_id),
    )


def _publish_cmdb_interfaces(conn, device_id: str, rows: list[dict]) -> None:
    attempt = begin_snapshot_attempt(device_id, "interface_inventory")
    observed_at = "2026-11-24T08:00:00+00:00"
    for row in rows:
        if_name = row["interface_name"]
        norm = normalize_interface_name(if_name).strip().lower()
        conn.execute(
            """INSERT INTO cmdb_device_interface_observations (
                   device_id, normalized_interface_name, interface_name, description,
                   admin_status, oper_status, ip_address, ip_prefix_length,
                   interface_type, generation, observed_at, run_id, metadata_json
               ) VALUES (?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, '{}')""",
            (
                device_id,
                norm,
                if_name,
                row.get("admin_status", "up"),
                row.get("oper_status", "up"),
                row["ip_address"],
                row["prefix_length"],
                row.get("interface_type", "physical"),
                attempt["generation"],
                observed_at,
                attempt["run_id"],
            ),
        )
        conn.execute(
            """INSERT INTO cmdb_device_interface_address_observations (
                   device_id, normalized_interface_name, interface_name,
                   context_source, context_type, local_context_key, local_context_name,
                   ip_address, ip_prefix_length, generation, observed_at, run_id, metadata_json
               ) VALUES (?, ?, ?, 'cli', ?, ?, ?, ?::inet, ?, ?, ?::timestamptz, ?, '{}'::jsonb)""",
            (
                device_id,
                norm,
                if_name,
                row.get("context_type", "global"),
                row.get("local_context_key", "--"),
                row.get("local_context_key", "--"),
                row["ip_address"],
                row["prefix_length"],
                attempt["generation"],
                observed_at,
                attempt["run_id"],
            ),
        )
    assert complete_snapshot(
        conn,
        attempt,
        observed_at=observed_at,
        record_count=len(rows),
        transport="cli",
    )


def test_full_rib_collection_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("IP_LOCATOR_ALLOW_FULL_RIB_COLLECTION", raising=False)
    res = ip_locator_service.run_route_collector()
    assert res["status"] == "disabled_by_policy"
    assert res["reason"] == "full_rib_collection_retired"
    assert res["routes_collected"] == 0

    with pytest.raises(RuntimeError, match="Iron Rule #2"):
        asyncio.run(snmp_service.collect_ip_forward_table("10.0.0.1", "public"))


def test_prefix_discovery_never_requests_routing_arp_or_mac_tables(isolated_db) -> None:
    del isolated_db
    captured_categories: list[list[str] | None] = []

    def fake_collect(device_info, categories=None, **_kwargs):
        captured_categories.append(list(categories) if categories is not None else None)
        return {"status": "success", "device": device_info, "categories": []}

    with patch.object(prefix_discovery_service, "collect_read_only_evidence", side_effect=fake_collect):
        prefix_discovery_service.discover_prefixes_for_device(
            {"id": "dev-no-snapshot", "hostname": "R1", "ip_address": "10.0.0.1", "platform": "huawei_vrp"}
        )

    assert len(captured_categories) == 1
    assert captured_categories[0] is not None
    assert "routing_table" not in captured_categories[0]
    assert "arp" not in captured_categories[0]
    assert "mac_table" not in captured_categories[0]
    assert "interfaces" in captured_categories[0]


def test_ip_inventory_supports_overlapping_ips_across_devices_and_vrfs(isolated_db) -> None:
    del isolated_db
    with get_db_connection() as conn:
        _seed_site_and_device(conn, site_id="site-a", device_id="dev-vrf-a", hostname="SW-A", mgmt_ip="10.254.0.1")
        _seed_site_and_device(conn, site_id="site-b", device_id="dev-vrf-b", hostname="SW-B", mgmt_ip="10.254.0.2")
        conn.commit()

    count_a = _upsert_snmp_ip_inventory(
        "dev-vrf-a",
        [{"ip_address": "192.168.1.1", "prefix_length": 24, "interface": "Vlanif10", "vrf_name": "VRF_OA"}],
    )
    count_b = _upsert_snmp_ip_inventory(
        "dev-vrf-b",
        [{"ip_address": "192.168.1.1", "prefix_length": 24, "interface": "Vlanif10", "vrf_name": "VRF_PROD"}],
    )
    assert count_a == 1
    assert count_b == 1

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT device_id, vrf_name, ip FROM ip_inventory WHERE ip = '192.168.1.1' ORDER BY device_id"
        ).fetchall()
    assert [(r["device_id"], r["vrf_name"], r["ip"]) for r in rows] == [
        ("dev-vrf-a", "VRF_OA", "192.168.1.1"),
        ("dev-vrf-b", "VRF_PROD", "192.168.1.1"),
    ]


def test_get_prefix_gateway_candidates_excludes_shutdown_interface(isolated_db) -> None:
    del isolated_db
    space = create_address_space(name="Global Space", kind="global", vrf_id=None, security_tenant_id="tenant-default")
    with get_db_connection() as conn:
        _seed_site_and_device(conn, site_id="site-cutover", device_id="old-core", hostname="OLD-CORE", mgmt_ip="10.254.1.1", role="core")
        _seed_site_and_device(conn, site_id="site-cutover", device_id="new-core", hostname="NEW-CORE", mgmt_ip="10.254.1.2", role="core")
        for dev_id in ("old-core", "new-core"):
            conn.execute(
                """INSERT INTO ipam_device_routing_contexts (
                       id, device_id, context_source, context_type, local_context_key,
                       local_context_name, address_space_id, status, revision,
                       created_at, updated_at
                   ) VALUES (?, ?, 'cli', 'global', '--', '--', ?, 'active', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (f"ctx-{dev_id}", dev_id, space["id"]),
            )
        conn.commit()
        _publish_cmdb_interfaces(
            conn,
            "old-core",
            [{"interface_name": "Vlanif55", "ip_address": "192.168.55.1", "prefix_length": 24, "interface_type": "svi", "admin_status": "down", "oper_status": "down"}],
        )
        _publish_cmdb_interfaces(
            conn,
            "new-core",
            [{"interface_name": "Vlanif55", "ip_address": "192.168.55.1", "prefix_length": 24, "interface_type": "svi", "admin_status": "up", "oper_status": "up"}],
        )
        conn.commit()

    create_subnet(prefix="192.168.55.0/24", tenant_id="tenant-default", site_id="site-cutover", address_space_id=space["id"])
    res = get_prefix_gateway_candidates(
        prefix="192.168.55.0/24",
        site_id="site-cutover",
        tenant_id="tenant-default",
        gateway_ip="192.168.55.1",
        address_space_id=space["id"],
    )
    assert res["status"] == "matched"
    assert res["selected"]["device_id"] == "new-core"
    assert len(res["endpoints"]) == 1


def test_radix_index_exact_match_p2p_peer_vrf_isolation_and_master_priority(isolated_db) -> None:
    del isolated_db
    invalidate_ipam_radix_index()
    with get_db_connection() as conn:
        _seed_site_and_device(conn, site_id="site-dc", device_id="agg-master", hostname="AGG-MASTER", mgmt_ip="10.254.10.1")
        _seed_site_and_device(conn, site_id="site-dc", device_id="agg-backup", hostname="AGG-BACKUP", mgmt_ip="10.254.10.2")
        _seed_site_and_device(conn, site_id="site-dc", device_id="old-down", hostname="OLD-DOWN", mgmt_ip="10.254.10.9")
        conn.commit()

        _publish_cmdb_interfaces(
            conn,
            "agg-master",
            [
                {"interface_name": "LoopBack0", "ip_address": "10.0.0.1", "prefix_length": 32, "interface_type": "loopback"},
                {"interface_name": "10GE1/0/1", "ip_address": "10.255.12.1", "prefix_length": 30, "interface_type": "physical"},
                {"interface_name": "Vlanif100", "ip_address": "192.168.100.252", "prefix_length": 24, "interface_type": "svi", "context_type": "vrf", "local_context_key": "VRF_PROD"},
            ],
        )
        _publish_cmdb_interfaces(
            conn,
            "agg-backup",
            [
                {"interface_name": "10GE1/0/48", "ip_address": "10.255.12.2", "prefix_length": 30, "interface_type": "physical", "admin_status": "up", "oper_status": "down"},
                {"interface_name": "Vlanif100", "ip_address": "192.168.100.253", "prefix_length": 24, "interface_type": "svi", "context_type": "vrf", "local_context_key": "VRF_PROD"},
            ],
        )
        _publish_cmdb_interfaces(
            conn,
            "old-down",
            [
                {"interface_name": "Vlanif100", "ip_address": "192.168.100.1", "prefix_length": 24, "interface_type": "svi", "context_type": "vrf", "local_context_key": "VRF_PROD", "admin_status": "down", "oper_status": "down"},
            ],
        )
        # Seed FHRP Master/Backup observations
        conn.execute(
            """INSERT INTO ipam_current_fhrp_observations (
                   device_id, protocol, group_id, address_family,
                   interface_name, normalized_interface_name, priority, state,
                   virtual_ip, virtual_ip_key, virtual_mac,
                   generation, observed_at, run_id, metadata_json
               ) VALUES
               ('agg-master', 'vrrp', 100, 4, 'Vlanif100', 'vlanif100', 120, 'master', '192.168.100.254'::inet, '192.168.100.254', '00:00:5e:00:01:64', 1, CURRENT_TIMESTAMP, 'run-1', '{}'::jsonb),
               ('agg-backup', 'vrrp', 100, 4, 'Vlanif100', 'vlanif100', 100, 'backup', '192.168.100.254'::inet, '192.168.100.254', '00:00:5e:00:01:64', 1, CURRENT_TIMESTAMP, 'run-1', '{}'::jsonb)"""
        )
        conn.commit()

        idx = build_ipam_radix_index(conn)

        # 1. Exact_IP_Map retains DOWN P2P interface and resolves its /30 peer
        down_hits = idx.lookup_exact("10.255.12.2")
        assert len(down_hits) == 1
        assert down_hits[0].device_id == "agg-backup"
        assert down_hits[0].is_down is True
        peer = idx.find_p2p_peer(down_hits[0])
        assert peer is not None
        assert peer.device_id == "agg-master"
        assert peer.ip == "10.255.12.1"

        # 2. Per_VRF_Radix_Tree excludes old-down and sorts MASTER before BACKUP
        cidr, gws = idx.lookup_connected_gateways("192.168.100.88", vrf="VRF_PROD")
        assert cidr == "192.168.100.0/24"
        assert [g.device_id for g in gws] == ["agg-master", "agg-backup"]
        assert gws[0].vip_role == "MASTER"
        assert gws[1].vip_role == "BACKUP"

        # 3. VRF isolation: default VRF must NOT match VRF_PROD subnet
        cidr_default, gws_default = idx.lookup_connected_gateways("192.168.100.88", vrf="default")
        assert cidr_default == ""
        assert gws_default == []

    # 4. End-to-end trace_ip hits Loopback /32 and DOWN /30 in O(1) with ZERO SSH calls
    with patch("services.ip_locator_trace_service._run_cli_with_device_lease", side_effect=AssertionError("SSH must not be called")):
        lo_res = trace_ip("10.0.0.1", tenant_id="tenant-default", authorized_device_ids=["agg-master", "agg-backup"])
        assert lo_res["found"] is True
        assert lo_res["conclusion"] == "device_interface"
        assert lo_res["location"]["device_id"] == "agg-master"
        assert lo_res["location"]["ip_classification"] == "LOOPBACK"

        p2p_res = trace_ip("10.255.12.2", tenant_id="tenant-default", authorized_device_ids=["agg-master", "agg-backup"])
        assert p2p_res["found"] is True
        assert p2p_res["conclusion"] == "device_interface"
        assert p2p_res["location"]["is_down"] is True
        assert p2p_res["location"]["peer_relationship"]["peer_device_id"] == "agg-master"
        assert p2p_res["location"]["peer_relationship"]["peer_ip"] == "10.255.12.1"
