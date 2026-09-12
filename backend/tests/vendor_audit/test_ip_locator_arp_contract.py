from pathlib import Path
import ipaddress
import json

import pytest

import services.ip_locator_service as ip_locator_service


DEVICE = {
    "id": "device-1",
    "hostname": "sw-01",
    "ip_address": "192.0.2.10",
}


def test_locator_normalizes_huawei_ge_and_gigabitethernet_as_the_same_port():
    assert ip_locator_service.normalize_interface_name("GE0/0/4") == "gi0/0/4"
    assert ip_locator_service.normalize_interface_name("GigabitEthernet0/0/4") == "gi0/0/4"


def test_route_selection_prefers_prefix_bound_connected_gateway_over_ospf():
    rows = [
        {
            "device_id": "lsw2",
            "destination": "10.253.20.0/24",
            "next_hop": "10.253.1.10",
            "protocol": "ospf",
            "outgoing_interface": "Vlanif23",
            "last_updated": "2026-08-05T21:21:22+00:00",
        },
        {
            "device_id": "lsw5",
            "destination": "10.253.20.0/24",
            "next_hop": "directly connected",
            "protocol": "connected",
            "outgoing_interface": "Vlanif20",
            "last_updated": "2026-08-05T21:20:00+00:00",
        },
    ]

    selected = ip_locator_service._select_best_route(
        rows,
        ipaddress.ip_address("10.253.20.10"),
        gateway_device_id="lsw5",
    )

    assert selected["device_id"] == "lsw5"
    assert selected["protocol"] == "connected"
    assert selected["outgoing_interface"] == "Vlanif20"


def test_realtime_arp_lookup_uses_capability_rules_and_never_builds_zero_workers(monkeypatch):
    devices = [
        {"id": "router-1", "role": "router", "ip_address": "192.0.2.1"},
        {"id": "access-1", "role": "access", "ip_address": "192.0.2.2"},
        {
            "id": "disabled-1",
            "role": "core",
            "ip_address": "192.0.2.3",
            "collection_policy_json": '{"collectors":{"arp":false}}',
        },
    ]
    monkeypatch.setattr(ip_locator_service, "_load_svi_evidence", lambda: {"access-1"})

    selected = ip_locator_service._load_realtime_arp_devices(devices)

    assert [device["id"] for device in selected] == ["access-1", "router-1"]
    assert all(device["_arp_policy_override"] is True for device in selected)
    assert ip_locator_service._calc_ssh_workers(0) == 1


def test_realtime_arp_hit_selection_prefers_prefix_gateway_over_completion_order():
    gateway = {"id": "gateway-1", "role": "gateway"}
    core = {"id": "core-1", "role": "core"}
    hits = [
        (core, {"mac": "001122334455"}),
        (gateway, {"mac": "00aabbccddee"}),
    ]

    selected = ip_locator_service._select_realtime_arp_hit(hits, "gateway-1")

    assert selected == (gateway, {"mac": "00aabbccddee"})


def test_route_selection_accepts_l3_roles_explicit_policy_and_interface_evidence(monkeypatch):
    devices = [
        {"id": "router-1", "role": "router"},
        {"id": "firewall-1", "role": "firewall"},
        {
            "id": "switch-explicit",
            "role": "switch",
            "collection_policy_json": '{"collectors":{"routes":true}}',
        },
        {"id": "switch-evidence", "role": "switch"},
        {
            "id": "core-disabled",
            "role": "core",
            "collection_policy_json": '{"collectors":{"routes":false}}',
        },
        {"id": "access-plain", "role": "access"},
    ]
    monkeypatch.setattr(ip_locator_service, "_load_route_l3_evidence", lambda: {"switch-evidence"})

    selected, stats = ip_locator_service._select_route_devices(devices)

    assert [device["id"] for device in selected] == [
        "firewall-1", "router-1", "switch-evidence", "switch-explicit",
    ]
    assert stats == {
        "credentialed_online": 6,
        "selected": 4,
        "role": 2,
        "explicit": 1,
        "interface_evidence": 1,
        "policy_disabled": 1,
        "policy_ignored": 0,
        "no_l3_evidence": 1,
    }


def test_nsot_route_selection_is_independent_from_inspection_plan(monkeypatch):
    devices = [
        {
            "id": "core-disabled-in-inspection",
            "role": "core",
            "collection_policy_json": '{"collectors":{"routes":false}}',
        },
        {
            "id": "access-enabled-in-inspection",
            "role": "access",
            "collection_policy_json": '{"collectors":{"routes":true}}',
        },
        {"id": "switch-with-l3-evidence", "role": "switch"},
    ]
    monkeypatch.setattr(
        ip_locator_service,
        "_load_route_l3_evidence",
        lambda: {"switch-with-l3-evidence"},
    )

    selected, stats = ip_locator_service._select_route_devices(
        devices,
        respect_collection_policy=False,
    )

    assert [device["id"] for device in selected] == [
        "core-disabled-in-inspection",
        "switch-with-l3-evidence",
    ]
    assert stats == {
        "credentialed_online": 3,
        "selected": 2,
        "role": 1,
        "explicit": 0,
        "interface_evidence": 1,
        "policy_disabled": 0,
        "policy_ignored": 2,
        "no_l3_evidence": 1,
    }


def test_unified_nsot_sync_runs_route_collection_without_inspection_policy(monkeypatch):
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(ip_locator_service, "run_arp_sweep", lambda: calls.append(("arp", None)))
    monkeypatch.setattr(
        ip_locator_service,
        "run_endpoint_collector",
        lambda **kwargs: calls.append(("endpoint", kwargs)),
    )
    monkeypatch.setattr(
        ip_locator_service,
        "run_route_collector",
        lambda **kwargs: calls.append(("routes", kwargs)),
    )
    monkeypatch.setattr(
        ip_locator_service,
        "_sync_prefixes_from_current_interfaces",
        lambda: {"devices": 0, "created": 0, "updated": 0, "failed": 0},
    )
    monkeypatch.setattr(
        "services.scheduler_service.sync_routing_neighbors_job",
        lambda: calls.append(("neighbors", None)),
    )
    monkeypatch.setattr(
        "services.scheduler_service.sync_bgp_routes_job",
        lambda: calls.append(("bgp", None)),
    )
    monkeypatch.setattr(
        "services.scheduler_service.sync_topology_and_interfaces_job",
        lambda: calls.append(("topology", None)) or {},
    )
    monkeypatch.setattr(
        "services.interface_collection_service.collect_interface_status_for_online_devices",
        lambda: calls.append(("interface_status", None)) or {},
    )

    ip_locator_service.run_unified_nsot_sync()

    assert ("routes", {"respect_collection_policy": False}) in calls


def test_eligible_device_diagnostics_explain_pre_route_exclusions(monkeypatch):
    rows = [
        {"id": "offline", "status": "offline", "platform": "cisco_ios", "has_credentials": True},
        {"id": "server", "status": "online", "platform": "linux", "has_credentials": True},
        {"id": "missing-creds", "status": "online", "platform": "cisco_ios", "has_credentials": False},
        {"id": "firewall", "status": "online", "platform": "h3c_comware", "has_credentials": True},
    ]

    class Connection:
        def execute(self, sql):
            assert "FROM devices d LEFT JOIN platform_profiles p" in sql
            return self

        def fetchall(self):
            return rows

        def close(self):
            return None

    monkeypatch.setattr(ip_locator_service, "get_db_connection", Connection)
    monkeypatch.setattr(
        ip_locator_service,
        "resolve_device_credentials",
        lambda device: {
            "normal_username": "operator" if device.get("has_credentials") else "",
            "normal_password": "credential" if device.get("has_credentials") else "",
        },
    )
    diagnostics: dict[str, int] = {}

    selected = ip_locator_service._load_eligible_devices(diagnostics=diagnostics)

    assert [device["id"] for device in selected] == ["firewall"]
    assert diagnostics == {
        "inventory_total": 4,
        "not_online": 1,
        "unsupported_platform": 1,
        "no_credentials": 1,
        "role_filtered": 0,
    }


def test_locator_context_falls_back_to_latest_interface_telemetry(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO devices (id, hostname, status, site_id, site) VALUES (?, ?, ?, ?, ?)",
        ("device-locator-switch", "LSW4", "online", "", ""),
    )
    conn.execute(
        """INSERT INTO network_endpoints
           (id, ip, mac, hostname, switch_id, switch_port, vlan, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "endpoint-locator-1", "10.253.10.10", "5489985666e2", "endpoint-1",
            "device-locator-switch", "GE0/0/4", "10", "2026-08-02T21:50:00+08:00", "2026-08-02T21:54:00+08:00",
        ),
    )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, admin_status, oper_status, switchport_mode, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            "interface-locator-1", "device-locator-switch", "GigabitEthernet0/0/4",
            "unknown", "unknown", "access", "2026-08-02T21:54:00+00:00",
        ),
    )
    conn.execute(
        """INSERT INTO interface_telemetry_raw
           (ts, device_id, interface_name, status)
           VALUES (?, ?, ?, ?)""",
        ("2026-08-02T21:55:00+00:00", "device-locator-switch", "GE0/0/4", "up"),
    )
    conn.commit()

    context = ip_locator_service._get_ip_locator_context("10.253.10.10")

    assert context["l2"]["switch_name"] == "LSW4"
    assert context["l2"]["admin_status"] == "up"
    assert context["l2"]["oper_status"] == "up"
    assert context["l2"]["mode"] == "access"
    assert context["address"]["status"] == "active"
    assert context["freshness"]["interface_last_seen"] == "2026-08-02T21:55:00+00:00"
    conn.close()


def test_v2_locator_context_skips_unqueued_live_interface_probe(isolated_db, monkeypatch):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO devices (id, hostname, status, site_id, site) VALUES (?, ?, ?, ?, ?)",
        ("device-locator-v2-context", "LSW-V2", "online", "", ""),
    )
    conn.execute(
        """INSERT INTO network_endpoints
           (id, ip, mac, hostname, switch_id, switch_port, vlan, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "endpoint-locator-v2-context", "10.253.10.11", "5489985666e3", "endpoint-v2",
            "device-locator-v2-context", "GE0/0/5", "10", "2026-08-02T21:50:00+08:00",
            "2026-08-02T21:54:00+08:00",
        ),
    )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, admin_status, oper_status, switchport_mode, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            "interface-locator-v2-context", "device-locator-v2-context", "GigabitEthernet0/0/5",
            "unknown", "unknown", "access", "2026-08-02T21:54:00+00:00",
        ),
    )
    conn.commit()
    conn.close()

    live_probes: list[tuple[str, str]] = []
    monkeypatch.setattr(
        ip_locator_service,
        "_collect_live_interface_status",
        lambda device_id, port: live_probes.append((device_id, port)) or ("up", "up"),
    )

    context = ip_locator_service._get_ip_locator_context(
        "10.253.10.11",
        allow_live_interface_status=False,
    )

    assert context["l2"]["switch_name"] == "LSW-V2"
    assert context["l2"]["vlan"] == "10"
    assert live_probes == []


def test_locator_uses_lldp_uplink_when_gateway_is_on_the_access_switch(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO devices (id, hostname, status, role) VALUES (?, ?, ?, ?)",
        ("device-access-gw", "S6850-5", "online", "access"),
    )
    conn.execute(
        "INSERT INTO devices (id, hostname, status, role) VALUES (?, ?, ?, ?)",
        ("device-distribution", "S6850-3", "online", "distribution"),
    )
    conn.execute(
        """INSERT INTO prefixes
           (id, prefix, prefix_cidr, gateway, status, gateway_device_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("prefix-locator-uplink", "172.16.5.0/24", "172.16.5.0/24", "172.16.5.1", "active", "device-access-gw"),
    )
    conn.execute(
        """INSERT INTO network_endpoints
           (id, ip, mac, hostname, switch_id, switch_port, vlan, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "endpoint-locator-uplink", "172.16.5.10", "8e4757600706", "endpoint-1",
            "device-access-gw", "GE1/0/2", "7", "2026-08-05T21:50:00+08:00", "2026-08-05T21:54:00+08:00",
        ),
    )
    conn.execute(
        """INSERT INTO topology_links
           (id, source_device_id, source_hostname, source_port,
            target_device_id, target_hostname, target_port, status, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "link-locator-uplink", "device-distribution", "S6850-3", "Ten-GigabitEthernet1/0/49",
            "device-access-gw", "S6850-5", "Ten-GigabitEthernet1/0/49", "unknown", "2026-08-05T21:55:00+00:00",
        ),
    )
    conn.commit()

    context = ip_locator_service._get_ip_locator_context("172.16.5.10")

    assert context["l3"]["gateway_device"] == "S6850-5"
    assert context["l3"]["upstream_devices"] == [{
        "device": "S6850-3",
        "device_id": "device-distribution",
        "port": "Ten-GigabitEthernet1/0/49",
        "peer_port": "Ten-GigabitEthernet1/0/49",
    }]
    conn.close()


def test_locator_topology_join_expands_lag_identity_to_parent_and_members(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO devices (id, hostname, status, role) VALUES (?, ?, ?, ?)",
        ("device-lag-core", "CORE-1", "online", "core"),
    )
    conn.execute(
        "INSERT INTO devices (id, hostname, status, role) VALUES (?, ?, ?, ?)",
        ("device-lag-access", "ACCESS-1", "online", "access"),
    )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, interface_type, switchport_mode)
           VALUES (?, ?, ?, ?, ?)""",
        ("interface-lag-parent", "device-lag-core", "Bridge-Aggregation15", "port_channel", "trunk"),
    )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, interface_type, parent_interface_id, channel_group, switchport_mode)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            "interface-lag-member", "device-lag-core", "XGE1/0/49", "physical",
            "interface-lag-parent", 15, "trunk",
        ),
    )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, interface_type, switchport_mode)
           VALUES (?, ?, ?, ?, ?)""",
        ("interface-lag-access-peer", "device-lag-access", "XGE1/0/49", "physical", "trunk"),
    )
    conn.execute(
        """INSERT INTO topology_links
           (id, source_device_id, source_interface_id, source_hostname, source_port,
            source_port_normalized, target_device_id, target_interface_id, target_hostname,
            target_port, target_port_normalized, status, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "link-lag-parent", "device-lag-core", "interface-lag-parent", "CORE-1",
            "Bridge-Aggregation15", "", "device-lag-access", "interface-lag-access-peer",
            "ACCESS-1", "XGE1/0/49", "te1/0/49", "up",
            json.dumps({
                "members": [{
                    "source": {"device_id": "device-lag-core", "name": "XGE1/0/49", "normalized": "te1/0/49"},
                    "target": {"device_id": "device-lag-access", "name": "XGE1/0/49", "normalized": "te1/0/49"},
                }]
            }),
        ),
    )
    conn.commit()

    neighbor = ip_locator_service._find_topology_trace_neighbor(
        conn, "device-lag-core", "BAGG15"
    )

    assert neighbor is not None
    assert neighbor["neighbor_id"] == "device-lag-access"
    assert neighbor["match_kind"] == "interface_id"

    member_neighbor = ip_locator_service._find_topology_trace_neighbor(
        conn, "device-lag-core", "XGE1/0/49"
    )
    assert member_neighbor is not None
    assert member_neighbor["neighbor_id"] == "device-lag-access"
    conn.close()


def test_locator_only_reuses_cached_confirmed_access_port(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO devices (id, hostname, status, role) VALUES (?, ?, ?, ?)",
        ("device-cache-validation", "CACHE-VALIDATION", "online", "access"),
    )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, interface_type, switchport_mode, access_vlan)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            "interface-cache-confirmed", "device-cache-validation", "GigabitEthernet1/0/10",
            "physical", "access", 4,
        ),
    )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, interface_type, switchport_mode)
           VALUES (?, ?, ?, ?, ?)""",
        (
            "interface-cache-unverified", "device-cache-validation", "GigabitEthernet1/0/11",
            "physical", "access",
        ),
    )
    conn.commit()
    conn.close()

    assert ip_locator_service._cached_endpoint_needs_retrace({"switch_port": "BAGG15"}) is True
    assert ip_locator_service._cached_endpoint_needs_retrace({
        "switch_id": "device-cache-validation",
        "switch_port": "GigabitEthernet1/0/10",
    }) is False
    assert ip_locator_service._cached_endpoint_needs_retrace({
        "switch_id": "device-cache-validation",
        "switch_port": "GigabitEthernet1/0/11",
    }) is True


def test_locator_does_not_report_lag_as_host_port_when_trace_is_incomplete(monkeypatch, isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO devices (id, hostname, status, role) VALUES (?, ?, ?, ?)",
        ("device-trace-core", "CORE-TRACE", "online", "core"),
    )
    conn.execute(
        "INSERT INTO devices (id, hostname, status, role) VALUES (?, ?, ?, ?)",
        ("device-trace-access", "ACCESS-TRACE", "online", "access"),
    )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, interface_type, switchport_mode)
           VALUES (?, ?, ?, ?, ?)""",
        ("interface-trace-parent", "device-trace-core", "Bridge-Aggregation15", "port_channel", "trunk"),
    )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, interface_type, parent_interface_id, channel_group, switchport_mode)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            "interface-trace-member", "device-trace-core", "XGE1/0/49", "physical",
            "interface-trace-parent", 15, "trunk",
        ),
    )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, interface_type, switchport_mode)
           VALUES (?, ?, ?, ?, ?)""",
        ("interface-trace-access-uplink", "device-trace-access", "XGE1/0/49", "physical", "trunk"),
    )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, interface_type, switchport_mode, access_vlan)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("interface-trace-host-port", "device-trace-access", "GigabitEthernet1/0/10", "physical", "access", 4),
    )
    conn.execute(
        """INSERT INTO interfaces
           (id, device_id, interface_name, interface_type, switchport_mode)
           VALUES (?, ?, ?, ?, ?)""",
        ("interface-trace-unknown-physical", "device-trace-core", "Ten-GigabitEthernet1/0/48", "physical", "access"),
    )
    conn.execute(
        """INSERT INTO topology_links
           (id, source_device_id, source_interface_id, source_hostname, source_port,
            source_port_normalized, target_device_id, target_interface_id, target_hostname,
            target_port, target_port_normalized, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "link-trace-core-access", "device-trace-core", "interface-trace-parent", "CORE-TRACE",
            "Bridge-Aggregation15", "", "device-trace-access", "interface-trace-access-uplink",
            "ACCESS-TRACE", "XGE1/0/49", "te1/0/49", "up",
        ),
    )
    conn.commit()
    conn.close()

    devices = [
        {"id": "device-trace-core", "hostname": "CORE-TRACE", "ip_address": "192.0.2.1", "role": "core"},
        {"id": "device-trace-access", "hostname": "ACCESS-TRACE", "ip_address": "192.0.2.2", "role": "access"},
    ]
    cached_endpoint_writes: list[dict] = []

    monkeypatch.setattr(ip_locator_service, "_get_ip_locator_context", lambda *_args: {})
    monkeypatch.setattr(ip_locator_service, "_get_ip_network_role", lambda *_args: None)
    monkeypatch.setattr(ip_locator_service, "_load_eligible_devices", lambda: devices)
    monkeypatch.setattr(ip_locator_service, "_load_realtime_arp_devices", lambda _devices: [devices[0]])
    monkeypatch.setattr(ip_locator_service, "_get_cached_arp", lambda _ip: None)
    monkeypatch.setattr(ip_locator_service, "_get_cached_endpoint", lambda _ip: None)
    monkeypatch.setattr(ip_locator_service, "_set_cached_arp", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ip_locator_service,
        "_set_cached_endpoint",
        lambda **kwargs: cached_endpoint_writes.append(kwargs),
    )
    monkeypatch.setattr(ip_locator_service, "_collect_lldp_from_device", lambda _device: [])

    def fake_arp(_device, _target_ip, _vrf=None, _force_refresh=False):
        return {
            "mac": "64c6d26475ae",
            "interface": "BAGG15",
            "source_device_id": "device-trace-core",
            "source_device": "CORE-TRACE",
            "vlan": "4",
        }

    def fake_mac(device, _target_mac, force_refresh=False):
        del force_refresh
        if device["id"] == "device-trace-core":
            return [{
                "mac": "64c6d26475ae", "port": "BAGG15", "vlan": "4",
                "vlan_source": "mac_table", "type": "dynamic",
            }]
        return [{
            "mac": "64c6d26475ae", "port": "GigabitEthernet1/0/10", "vlan": "4",
            "vlan_source": "mac_table", "type": "dynamic",
        }]

    monkeypatch.setattr(ip_locator_service, "_targeted_arp_query", fake_arp)
    monkeypatch.setattr(ip_locator_service, "_targeted_mac_query", fake_mac)

    traced = ip_locator_service.locate_ip("192.168.4.58", force_refresh=True)

    assert traced["found"] is True
    assert traced["trace_status"] == "terminal"
    assert traced["locations"][0]["switch_id"] == "device-trace-access"
    assert traced["locations"][0]["port"] == "GigabitEthernet1/0/10"
    assert [hop["port"] for hop in traced["trace_hops"]] == ["BAGG15", "GigabitEthernet1/0/10"]
    assert len(cached_endpoint_writes) == 1

    conn = isolated_db["module"].get_db_connection()
    conn.execute("DELETE FROM topology_links WHERE id = ?", ("link-trace-core-access",))
    conn.commit()
    conn.close()

    incomplete = ip_locator_service.locate_ip("192.168.4.58", force_refresh=True)

    assert incomplete["found"] is False
    assert incomplete["trace_status"] == "incomplete"
    assert incomplete["locations"][0]["type"] == "TRACE_INCOMPLETE"
    assert incomplete["locations"][0]["port"] == "BAGG15"
    assert "不能判定为主机接入口" in " ".join(incomplete["errors"] + [incomplete["locations"][0]["note"]])
    assert len(cached_endpoint_writes) == 1

    monkeypatch.setattr(
        ip_locator_service,
        "_targeted_mac_query",
        lambda _device, _target_mac, force_refresh=False: [{
            "mac": "64c6d26475ae", "port": "Ten-GigabitEthernet1/0/48", "vlan": "4",
            "vlan_source": "mac_table", "type": "dynamic",
        }],
    )
    unknown_physical = ip_locator_service.locate_ip("192.168.4.58", force_refresh=True)

    assert unknown_physical["found"] is False
    assert unknown_physical["trace_status"] == "incomplete"
    assert unknown_physical["locations"][0]["port"] == "Ten-GigabitEthernet1/0/48"
    assert "Access VLAN 证据" in " ".join(unknown_physical["errors"] + [unknown_physical["locations"][0]["note"]])
    assert len(cached_endpoint_writes) == 1

    monkeypatch.setattr(
        ip_locator_service,
        "_targeted_mac_query",
        lambda _device, _target_mac, force_refresh=False: [{
            "mac": "64c6d26475ae", "port": "", "vlan": "4",
            "vlan_source": "mac_table", "type": "dynamic",
        }],
    )
    no_port = ip_locator_service.locate_ip("192.168.4.58", force_refresh=True)

    assert no_port["found"] is False
    assert no_port["trace_status"] == "incomplete"
    assert no_port["trace_hops"][0]["type"] == "MAC_TABLE_NO_PORT"


def test_locator_lldp_lookup_overrides_background_plan_for_interactive_trace(monkeypatch):
    calls = {}

    def fake_collect(
        _device,
        *,
        categories,
        policy_override_categories=None,
        _connection_session=None,
        _platform_action_session=None,
    ):
        calls["categories"] = categories
        calls["policy_override_categories"] = policy_override_categories
        calls["connection_session"] = _connection_session
        calls["platform_action_session"] = _platform_action_session
        return {
            "categories": [{
                "key": "neighbors",
                "success": True,
                "records": [{
                    "local_interface": "XGE1/0/49",
                    "neighbor_name": "S6850-3",
                    "neighbor_interface": "Ten-GigabitEthernet1/0/49",
                }],
            }],
        }

    monkeypatch.setattr(ip_locator_service, "collect_operational_data", fake_collect)

    assert ip_locator_service._collect_lldp_from_device({
        "id": "device-access-gw",
        "hostname": "S6850-5",
        "platform": "hp_comware",
    }) == [{
        "local_interface": "XGE1/0/49",
        "neighbor": "S6850-3",
        "neighbor_port": "Ten-GigabitEthernet1/0/49",
        "neighbor_ip": "",
    }]
    assert calls == {
        "categories": ["neighbors"],
        "policy_override_categories": {"neighbors"},
        "connection_session": None,
        "platform_action_session": None,
    }


def test_locator_live_status_enrichment_reads_only_the_target_access_port(monkeypatch):
    monkeypatch.setattr(
        ip_locator_service,
        "_load_eligible_devices",
        lambda: [{"id": "device-locator-switch", "hostname": "LSW4", "platform": "huawei_vrp"}],
    )
    monkeypatch.setattr(
        "services.read_only_collection_adapter.collect_read_only_evidence",
        lambda *_args, **_kwargs: {
            "categories": [{
                "key": "interfaces",
                "success": True,
                "parse_status": "matched",
                "records": [{
                    "INTERFACE": "GigabitEthernet0/0/4",
                    "PHY": "up",
                    "PROTOCOL": "up",
                }],
            }],
        },
    )

    assert ip_locator_service._collect_live_interface_status(
        "device-locator-switch", "GE0/0/4"
    ) == ("up", "up")


def test_normalize_arp_record_accepts_textfsm_standard_fields():
    record = ip_locator_service._normalize_arp_record(
        {
            "IP_ADDRESS": "10.1.1.1",
            "MAC_ADDRESS": "02e0-f102-0023",
            "INTERFACE": "GE1/0/1",
        },
        DEVICE,
    )

    assert record == {
        "ip": "10.1.1.1",
        "mac": "02e0f1020023",
        "interface": "GE1/0/1",
        "source_device_id": "device-1",
        "source_device": "sw-01",
    }


def test_targeted_arp_query_uses_published_registry_action_for_bound_device(monkeypatch):
    device = {**DEVICE, "platform_profile_id": "system-profile-cisco_ios", "tenant_id": "tenant-1"}
    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: {
            "success": True,
            "records": [{
                "IP_ADDRESS": "10.1.1.1",
                "MAC_ADDRESS": "02e0-f102-0023",
                "INTERFACE": "Gi1/0/1",
            }],
        },
    )

    result = ip_locator_service._targeted_arp_query(device, "10.1.1.1")

    assert result["mac"] == "02e0f1020023"
    assert result["interface"] == "Gi1/0/1"


def test_targeted_mac_query_uses_published_registry_action_for_bound_device(monkeypatch):
    device = {
        **DEVICE,
        "platform_profile_id": "system-profile-cisco_ios",
        "tenant_id": "tenant-1",
        "collection_policy_json": '{"collectors":{"mac_table":true}}',
    }
    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: {
            "success": True,
            "records": [{
                "MAC_ADDRESS": "02e0-f102-0023",
                "VLAN_ID": "12",
                "DESTINATION_PORT": "Gi1/0/1",
            }],
        },
    )

    result = ip_locator_service._targeted_mac_query(device, "02e0f1020023")

    assert result == [{
        "mac": "02e0f1020023",
        "port": "Gi1/0/1",
        "vlan": "12",
        "vlan_source": "mac_table",
        "type": "",
        "switch_id": "device-1",
        "switch_name": "sw-01",
    }]


def test_targeted_mac_query_skips_router_without_overriding_collection_plan(monkeypatch):
    device = {
        **DEVICE,
        "role": "router",
        "platform_profile_id": "system-profile-cisco_ios",
        "tenant_id": "tenant-1",
    }
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("router MAC lookup must be skipped")

    monkeypatch.setattr("services.platform_registry_service.execute_platform_action", fail_if_called)

    assert ip_locator_service._targeted_mac_query(device, "02e0f1020023") == []


def test_targeted_mac_query_allows_explicit_router_collection_override(monkeypatch):
    device = {
        **DEVICE,
        "role": "router",
        "collection_policy_json": '{"collectors":{"mac_table":true}}',
        "platform_profile_id": "system-profile-cisco_ios",
        "tenant_id": "tenant-1",
    }
    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: {
            "success": True,
            "records": [{"MAC_ADDRESS": "02e0-f102-0023", "VLAN_ID": "12", "DESTINATION_PORT": "Gi1/0/1"}],
        },
    )

    assert ip_locator_service._targeted_mac_query(device, "02e0f1020023")[0]["vlan"] == "12"


def test_targeted_mac_query_reports_disabled_without_opening_a_session(monkeypatch):
    device = {
        **DEVICE,
        "role": "access",
        "platform": "h3c_comware",
    }

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("disabled MAC lookup must not open SSH")

    monkeypatch.setattr(ip_locator_service, "_send_command", fail_if_called)

    result = ip_locator_service._targeted_mac_query(device, "02e0f1020023")

    assert result == []
    assert result.status["status"] == "disabled"
    assert result.status["error_code"] == "MAC_TABLE_DISABLED"


def test_targeted_mac_query_reports_found_and_preserves_list_contract(monkeypatch):
    device = {
        **DEVICE,
        "role": "access",
        "platform": "h3c_comware",
        "collection_policy_json": '{"collectors":{"mac_table":true}}',
    }
    monkeypatch.setattr(
        ip_locator_service,
        "_send_command",
        lambda *_args, **_kwargs: (
            "MAC Address      VLAN ID    State            Port/Nickname            Aging\n"
            "02e0-f102-0023   12         Learned          GE1/0/1                  Y\n"
        ),
    )

    result = ip_locator_service._targeted_mac_query(device, "02e0f1020023")

    assert result == [{
        "mac": "02e0f1020023",
        "port": "GE1/0/1",
        "vlan": "12",
        "vlan_source": "mac_table",
        "type": "Learned",
        "switch_id": "device-1",
        "switch_name": "sw-01",
    }]
    assert result.status == {
        "status": "found",
        "device_id": "device-1",
        "device": "sw-01",
        "command": "display mac-address 02e0-f102-0023",
        "record_count": 1,
        "port": "GE1/0/1",
        "vlan": "12",
        "reason": "MAC 表已命中目标地址",
        "error_code": "",
    }


def test_targeted_mac_query_distinguishes_not_found_and_unsupported_output(monkeypatch):
    device = {
        **DEVICE,
        "role": "access",
        "platform": "h3c_comware",
        "collection_policy_json": '{"collectors":{"mac_table":true}}',
    }
    monkeypatch.setattr(
        ip_locator_service,
        "_send_command",
        lambda *_args, **_kwargs: "MAC Address      VLAN ID    State            Port/Nickname            Aging\n",
    )

    not_found = ip_locator_service._targeted_mac_query(device, "02e0f1020023")
    assert not_found.status["status"] == "not_found"
    assert not_found.status["error_code"] == "MAC_NOT_FOUND"

    monkeypatch.setattr(
        ip_locator_service,
        "_send_command",
        lambda *_args, **_kwargs: "% Unrecognized command\n",
    )
    unsupported = ip_locator_service._targeted_mac_query(device, "02e0f1020023")
    assert unsupported == []
    assert unsupported.status["status"] == "unsupported"
    assert unsupported.status["error_code"] == "MAC_COMMAND_UNSUPPORTED"


def test_targeted_mac_query_reports_registry_unsupported_action(monkeypatch):
    device = {
        **DEVICE,
        "role": "router",
        "platform": "h3c_comware",
        "platform_profile_id": "system-profile-h3c",
        "collection_policy_json": '{"collectors":{"mac_table":true}}',
    }
    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: {
            "success": False,
            "error_code": "UNSUPPORTED_ACTION",
            "parse_status": "unsupported_by_platform",
        },
    )

    result = ip_locator_service._targeted_mac_query(device, "02e0f1020023")

    assert result == []
    assert result.status["status"] == "unsupported"
    assert result.status["error_code"] == "UNSUPPORTED_ACTION"


def test_full_table_fallback_reports_a_mac_hit_even_when_the_port_field_is_empty(monkeypatch):
    device = {
        **DEVICE,
        "role": "access",
        "platform": "unknown_platform",
        "collection_policy_json": '{"collectors":{"mac_table":true}}',
    }
    monkeypatch.setattr(
        ip_locator_service,
        "collect_operational_data",
        lambda *_args, **_kwargs: {
            "categories": [{
                "key": "mac_table",
                "success": True,
                "commands": ["show mac table"],
                "parse_status": "matched",
                "records": [{"mac_address": "02e0-f102-0023", "vlan_id": "12", "port": ""}],
                "raw_outputs": [],
            }],
        },
    )

    result = ip_locator_service._targeted_mac_query(device, "02e0f1020023")

    assert result.status["status"] == "found"
    assert result[0]["port"] == ""


def test_targeted_mac_query_reports_query_failure_after_targeted_and_fallback_errors(monkeypatch):
    device = {
        **DEVICE,
        "role": "access",
        "platform": "h3c_comware",
        "collection_policy_json": '{"collectors":{"mac_table":true}}',
    }
    monkeypatch.setattr(
        ip_locator_service,
        "_send_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("device timeout")),
    )
    monkeypatch.setattr(ip_locator_service, "_collect_mac_from_device_for_mac", lambda *_args, **_kwargs: [])

    result = ip_locator_service._targeted_mac_query(device, "02e0f1020023")

    assert result == []
    assert result.status["status"] == "query_failed"
    assert result.status["error_code"] == "MAC_QUERY_FAILED"


def test_mac_lookup_status_keeps_an_earlier_match_when_a_downstream_hop_misses():
    result = {"mac_lookup": ip_locator_service._initial_mac_lookup_status(), "mac_lookup_attempts": []}
    ip_locator_service._update_mac_lookup_status(
        result,
        ip_locator_service._mac_lookup_status(
            {"id": "switch-1", "hostname": "SW-1"},
            "found",
            command="display mac-address 02e0-f102-0023",
            record_count=1,
            port="GE1/0/1",
            vlan="12",
        ),
    )
    ip_locator_service._update_mac_lookup_status(
        result,
        ip_locator_service._mac_lookup_status(
            {"id": "switch-2", "hostname": "SW-2"},
            "not_found",
            command="display mac-address 02e0-f102-0023",
            error_code="MAC_NOT_FOUND",
        ),
    )

    assert result["mac_lookup"]["status"] == "found"
    assert result["mac_lookup"]["port"] == "GE1/0/1"
    assert result["mac_lookup"]["last_status"] == "not_found"
    assert len(result["mac_lookup_attempts"]) == 2


def test_format_mac_uses_platform_hyphen_style():
    assert ip_locator_service._format_mac("548998106981") == "5489-9810-6981"


def test_full_mac_collection_parses_huawei_vrp_mac_table_layout(monkeypatch):
    output = """
MAC address table of slot 0:
4c1f-cc3c-7de1 20          -      -      GE0/0/4         dynamic   0/-
Total matching items on slot 0 displayed = 1
"""
    monkeypatch.setattr(ip_locator_service, "_send_command", lambda *_args: output)

    records = ip_locator_service._collect_full_mac_table_from_device({
        **DEVICE,
        "platform": "huawei_vrp",
    })

    assert records == [{
        "mac": "4c1fcc3c7de1",
        "vlan": "20",
        "port": "GE0/0/4",
        "type": "dynamic",
        "switch_id": "device-1",
        "switch_name": "sw-01",
    }]


def test_endpoint_mac_records_are_persisted_for_cmdb_and_offline_lookup(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            "INSERT INTO devices (id, hostname, status) VALUES (?, ?, ?)",
            ("device-mac-1", "sw-mac-01", "online"),
        )
        conn.commit()
    finally:
        conn.close()

    persisted = ip_locator_service._persist_mac_table_records([{
        "switch_id": "device-mac-1",
        "mac": "4c1f-cc3c-7de1",
        "vlan": "20",
        "port": "GE0/0/4",
        "type": "dynamic",
    }])

    conn = isolated_db["module"].get_db_connection()
    try:
        row = conn.execute(
            "SELECT mac_address, vlan_id, interface_name, entry_type FROM mac_table WHERE device_id = ?",
            ("device-mac-1",),
        ).fetchone()
    finally:
        conn.close()

    assert persisted == 1
    assert dict(row) == {
        "mac_address": "4c1fcc3c7de1",
        "vlan_id": 20,
        "interface_name": "GE0/0/4",
        "entry_type": "dynamic",
    }


def test_arp_output_fallback_accepts_common_cisco_and_huawei_mac_formats():
    output = """
Internet 10.1.1.2 0 aabb.ccdd.eeff ARPA GigabitEthernet1/0/2
10.1.1.3 00e0-fc41-0200  D  GE1/0/3
"""

    records = ip_locator_service._parse_arp_output_fallback(output, DEVICE)

    assert [(item["ip"], item["mac"], item["interface"]) for item in records] == [
        ("10.1.1.2", "aabbccddeeff", "GigabitEthernet1/0/2"),
        ("10.1.1.3", "00e0fc410200", "GE1/0/3"),
    ]


def test_arp_output_fallback_extracts_h3c_vid():
    records = ip_locator_service._parse_arp_output_fallback(
        "10.1.1.2 00e0-fc00-0001 12 GE1/0/2 960 D",
        DEVICE,
    )

    assert records[0]["vlan"] == "12"


def test_huawei_arp_continuation_line_is_attached_to_previous_entry():
    output = """
IP ADDRESS      MAC ADDRESS     EXPIRE(M) TYPE INTERFACE      VPN-INSTANCE
                                          VLAN
------------------------------------------------------------------------------
10.253.20.2     4c1f-ccad-6fd7            I -  Vlanif20
10.253.20.1     4c1f-cc3c-7de1  5         D-0  GE0/0/4
                                          20
10.253.20.10    5489-9810-6981  20        D-0  GE0/0/1
                                          20
------------------------------------------------------------------------------
Total:3         Dynamic:2       Static:0     Interface:1
"""

    records = ip_locator_service._parse_arp_output_fallback(output, DEVICE)

    assert {item["ip"]: item.get("vlan") for item in records} == {
        "10.253.20.2": "20",
        "10.253.20.1": "20",
        "10.253.20.10": "20",
    }


def test_full_arp_collection_uses_normalized_records_and_raw_fallback(monkeypatch):
    monkeypatch.setattr(
        ip_locator_service,
        "collect_operational_data",
        lambda *_args, **_kwargs: {
            "categories": [
                {
                    "key": "arp",
                    "success": True,
                    "commands": ["show arp"],
                    "parser": "ntc-templates",
                    "records": [
                        {
                            "IP_ADDRESS": "10.1.1.10",
                            "MAC_ADDRESS": "aabb.ccdd.0010",
                            "INTERFACE": "Gi1/0/10",
                        }
                    ],
                    "raw_outputs": [],
                }
            ]
        },
    )
    parsed = ip_locator_service._collect_full_arp_from_device(DEVICE)
    assert parsed[0]["ip"] == "10.1.1.10"
    assert parsed[0]["mac"] == "aabbccdd0010"

    fixture = Path(
        "backend/tests/fixtures/cli/h3c/h3c_comware/display_arp_all/comware_v7_s5130.txt"
    ).read_text(encoding="utf-8")
    monkeypatch.setattr(
        ip_locator_service,
        "collect_operational_data",
        lambda *_args, **_kwargs: {
            "categories": [
                {
                    "key": "arp",
                    "success": True,
                    "commands": ["display arp all"],
                    "parser": "ntc-templates",
                    "records": [],
                    "raw_outputs": [{"output": fixture}],
                }
            ]
        },
    )
    assert len(ip_locator_service._collect_full_arp_from_device(DEVICE)) == 2


def test_arp_failure_is_classified_and_backed_off():
    assert ip_locator_service._classify_arp_failure("SSH connection timed out") == "unreachable"
    assert ip_locator_service._classify_arp_failure("Authentication failed") == "auth_failed"
    assert ip_locator_service._arp_retry_delay("unreachable", 1) == 300
    assert ip_locator_service._arp_retry_delay("unreachable", 5) == 3600
    assert ip_locator_service._arp_retry_delay("auth_failed", 1) == 3600
    assert ip_locator_service._arp_retry_delay("unsupported", 1) == 86400


def test_full_arp_collection_returns_failure_metadata(monkeypatch):
    monkeypatch.setattr(
        ip_locator_service,
        "collect_operational_data",
        lambda *_args, **_kwargs: {
            "categories": [
                {
                    "key": "arp",
                    "success": False,
                    "error": "SSH connection timed out",
                    "records": [],
                    "raw_outputs": [],
                }
            ]
        },
    )

    result = ip_locator_service._collect_full_arp_result(DEVICE)
    assert result["status"] == "failed"
    assert result["failure_class"] == "unreachable"
    assert result["entries"] == []


def test_arp_sweep_reports_skipped_backoff_and_does_not_abort(monkeypatch):
    monkeypatch.setattr(
        ip_locator_service,
        "_load_arp_sweep_devices",
        lambda *_args: ([DEVICE], 3, 2),
    )
    monkeypatch.setattr(
        ip_locator_service,
        "_load_arp_collection_state",
        lambda: {"device-1": {"consecutive_failures": 0}},
    )
    monkeypatch.setattr(
        ip_locator_service,
        "_collect_full_arp_result",
        lambda *_args, **_kwargs: {
            "entries": [],
            "status": "failed",
            "failure_class": "unreachable",
            "error_message": "SSH connection timed out",
        },
    )
    monkeypatch.setattr(ip_locator_service, "record_collection_results", lambda *_args, **_kwargs: None)

    result = ip_locator_service.run_arp_sweep()
    assert result["total_eligible_devices"] == 3
    assert result["skipped_backoff_devices"] == 2
    assert result["device_results"][0]["status"] == "failed"


def test_arp_sweep_device_selection_uses_bounded_cursor_batch(monkeypatch):
    devices = [
        {"id": f"device-{index}", "role": "router", "ip_address": f"10.0.0.{index}"}
        for index in range(5)
    ]
    monkeypatch.setattr(ip_locator_service, "_load_eligible_devices", lambda: devices)
    monkeypatch.setattr(ip_locator_service, "_load_svi_evidence", lambda: set())
    monkeypatch.setattr(ip_locator_service, "_load_arp_collection_state", lambda: {})
    monkeypatch.setattr(ip_locator_service, "ARP_MAX_DEVICES_PER_SWEEP", 2)
    monkeypatch.setattr(
        ip_locator_service,
        "reserve_collector_sweep_batch",
        lambda *_args, **_kwargs: {"start_cursor": 3, "selected_count": 2},
    )

    selected, total, skipped = ip_locator_service._load_arp_sweep_devices("run-1")

    assert [item["id"] for item in selected] == ["device-3", "device-4"]
    assert all(item["_arp_policy_override"] is True for item in selected)
    assert total == 5
    assert skipped == 0


def test_arp_dispatch_queues_only_device_ids_and_policy_metadata(monkeypatch):
    device = {"id": "device-1", "_arp_policy_override": True}
    captured = {}
    monkeypatch.setattr(
        ip_locator_service,
        "_load_arp_sweep_devices",
        lambda *_args: ([device], 2, 1),
    )

    def enqueue(*_args, **kwargs):
        captured.update(kwargs)
        return 1

    monkeypatch.setattr(ip_locator_service, "enqueue_tasks", enqueue)
    result = ip_locator_service.dispatch_arp_sweep()

    assert result["queued_devices"] == 1
    assert captured["device_ids"] == ["device-1"]
    assert captured["payload_by_device"]["device-1"]["arp_policy_override"] is True


def test_targeted_arp_status_distinguishes_no_match_from_query_failure(monkeypatch):
    device = {
        "id": "arp-status-device",
        "hostname": "ARP-STATUS",
        "ip_address": "192.0.2.10",
        "platform": "cisco_ios",
    }
    monkeypatch.setattr(
        ip_locator_service,
        "_collect_arp_from_device_for_ip",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not fall back to an unbounded full table")),
    )

    monkeypatch.setattr(ip_locator_service, "_send_command", lambda *args, **kwargs: "No matching ARP entry found")
    assert ip_locator_service._targeted_arp_query_status(device, "192.0.2.99")["status"] == "not_found"

    monkeypatch.setattr(ip_locator_service, "_send_command", lambda *args, **kwargs: "% Invalid input detected")
    assert ip_locator_service._targeted_arp_query_status(device, "192.0.2.99")["status"] == "unsupported"

    def fail_query(*args, **kwargs):
        raise TimeoutError("device did not answer")

    monkeypatch.setattr(ip_locator_service, "_send_command", fail_query)
    assert ip_locator_service._targeted_arp_query_status(device, "192.0.2.99")["status"] == "query_failed"

    monkeypatch.setattr(ip_locator_service, "_send_command", lambda *args, **kwargs: "unrecognized vendor output")
    assert ip_locator_service._targeted_arp_query_status(device, "192.0.2.99")["status"] == "parse_incomplete"


def test_arp_normalizer_retains_proxy_and_entry_flags():
    record = ip_locator_service._normalize_arp_record(
        {
            "ip": "192.0.2.99",
            "mac": "0000.5e00.0107",
            "interface": "Vlan10",
            "type": "proxy",
            "flags": "P",
        },
        {"id": "gateway", "hostname": "GW"},
    )

    assert record is not None
    assert record["type"] == "proxy"
    assert record["flags"] == "P"
    assert record["is_proxy"] is True


def test_v2_mac_exact_query_does_not_trigger_a_per_target_full_table_scan(monkeypatch):
    device = {
        **DEVICE,
        "role": "access",
        "platform": "unknown_os",
        "collection_policy_json": '{"collectors":{"mac_table":true}}',
    }
    monkeypatch.setattr(ip_locator_service, "should_collect", lambda *_args: True)
    monkeypatch.setattr(
        ip_locator_service,
        "_collect_mac_from_device_for_mac",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("V2 must share one full snapshot")),
    )

    result = ip_locator_service._targeted_mac_query(
        device,
        "001122334455",
        force_refresh=True,
        allow_full_table_fallback=False,
    )

    assert result == []
    assert result.status["status"] == "unsupported"


def test_mac_full_snapshot_is_bounded_and_normalized(monkeypatch):
    device = {**DEVICE, "role": "access", "platform": "cisco_ios"}
    monkeypatch.setattr(ip_locator_service, "should_collect", lambda *_args: True)
    monkeypatch.setattr(
        "services.ip_locator_session_pool.get_active_locator_session",
        lambda _device: None,
    )
    monkeypatch.setattr(
        ip_locator_service,
        "collect_operational_data",
        lambda *_args, **_kwargs: {
            "categories": [{
                "key": "mac_table",
                "success": True,
                "parse_status": "matched",
                "records": [
                    {"mac_address": "0011.2233.4455", "port": "Gi1/0/1", "vlan": "10", "type": "dynamic"},
                    {"mac_address": "0066.7788.99aa", "port": "Gi1/0/2", "vlan": "20", "type": "dynamic"},
                ],
                "raw_outputs": [],
            }],
        },
    )

    snapshot = ip_locator_service._collect_mac_table_snapshot(device)

    assert snapshot.status["status"] == "found"
    assert snapshot.status["coverage"] == "full"
    assert [item["mac"] for item in snapshot] == ["001122334455", "0066778899aa"]


def test_arp_full_snapshot_is_normalized_and_preserves_proxy_metadata(monkeypatch):
    device = {**DEVICE, "role": "router", "platform": "cisco_ios"}
    monkeypatch.setattr(
        "services.ip_locator_session_pool.get_active_locator_session",
        lambda _device: None,
    )
    monkeypatch.setattr(
        ip_locator_service,
        "collect_operational_data",
        lambda *_args, **_kwargs: {
            "categories": [{
                "key": "arp",
                "success": True,
                "parse_status": "matched",
                "records": [{
                    "ip_address": "192.0.2.77",
                    "mac_address": "0000.5e00.0107",
                    "interface": "Vlan10",
                    "entry_type": "proxy",
                    "flags": "P",
                }],
                "raw_outputs": [],
            }],
        },
    )

    snapshot = ip_locator_service._collect_arp_snapshot(device)

    assert snapshot.status["status"] == "found"
    assert snapshot.status["coverage"] == "full"
    assert snapshot[0]["ip"] == "192.0.2.77"
    assert snapshot[0]["is_proxy"] is True


@pytest.mark.parametrize("kind", ["arp", "mac"])
def test_empty_snapshot_is_explicitly_complete_but_truncated_output_is_not(monkeypatch, kind):
    device = {**DEVICE, "role": "access", "platform": "cisco_ios"}
    if kind == "mac":
        monkeypatch.setattr(ip_locator_service, "should_collect", lambda *_args: True)
    monkeypatch.setattr(
        "services.ip_locator_session_pool.get_active_locator_session",
        lambda _device: None,
    )

    def collect(parse_status, raw_output):
        monkeypatch.setattr(
            ip_locator_service,
            "collect_operational_data",
            lambda *_args, **_kwargs: {
                "categories": [{
                    "key": "arp" if kind == "arp" else "mac_table",
                    "success": True,
                    "parse_status": parse_status,
                    "records": [],
                    "raw_outputs": [{"output": raw_output}] if raw_output else [],
                }],
            },
        )
        if kind == "arp":
            return ip_locator_service._collect_arp_snapshot(device)
        return ip_locator_service._collect_mac_table_snapshot(device)

    empty = collect("no_records", "")
    assert empty.status == {"status": "not_found", "coverage": "full"}
    truncated = collect("matched", "output truncated")
    assert truncated.status["status"] == "parse_incomplete"
    assert truncated.status.get("coverage") != "full"
