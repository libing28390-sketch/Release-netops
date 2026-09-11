"""Pure contract tests for the bounded CLI-only locator trace engine."""

from __future__ import annotations

import ipaddress

from services.ip_locator_trace_service import (
    DIRECT_PROTOCOLS,
    TraceLimits,
    _best_routes,
    _is_direct,
    _parse_target_route_output,
    _route_command,
    trace_ip,
)


def test_best_routes_keeps_longest_prefix_and_direct_route_first():
    rows = [
        {
            "destination": "192.168.0.0/16",
            "next_hop": "10.0.0.2",
            "protocol": "ospf",
            "interface": "Gi1/0/1",
        },
        {
            "destination": "192.168.10.0/24",
            "next_hop": "directly connected",
            "protocol": "connected",
            "interface": "Vlanif10",
        },
        {
            "destination": "192.168.10.0/24",
            "next_hop": "10.0.0.3",
            "protocol": "ospf",
            "interface": "Gi1/0/2",
        },
    ]

    selected = _best_routes(rows, "192.168.10.100")

    assert len(selected) == 2
    assert selected[0]["protocol"] == "connected"
    assert selected[0]["prefix_length"] == 24
    assert _is_direct(selected[0])
    assert ipaddress.ip_address("192.168.10.100") in ipaddress.ip_network(selected[0]["destination"])


def test_route_commands_are_vendor_specific_and_read_only():
    assert _route_command({"platform": "cisco_ios"}, "192.0.2.10", "default") == "show ip route 192.0.2.10"
    assert _route_command({"platform": "huawei_vrp"}, "192.0.2.10", "corp") == "display ip routing-table vpn-instance corp 192.0.2.10"
    assert _route_command({"platform": "h3c_comware"}, "192.0.2.10", "default") == "display ip routing-table 192.0.2.10"
    assert _route_command({"platform": "juniper_junos"}, "192.0.2.10", "default") == "show route 192.0.2.10"


def test_target_route_parser_recovers_cisco_direct_and_next_hop_records():
    output = """
Routing entry for 192.168.10.0/24
  Known via \"connected\"
  * directly connected, via Vlan10
Routing entry for 192.168.20.0/24
  * 10.0.0.2, via GigabitEthernet1/0/1
"""

    rows = _parse_target_route_output(output, {"id": "core-1", "platform": "cisco_ios"}, "192.168.10.100", "default")

    assert rows
    assert any(_is_direct(row) for row in rows)
    assert any(row["interface"] == "gi1/0/1" for row in rows)


def test_trace_limits_are_bounded_by_default():
    limits = TraceLimits()

    assert limits.max_l3_hops == 16
    assert limits.max_l2_hops == 16
    assert limits.max_devices == 32
    assert DIRECT_PROTOCOLS >= {"direct", "connected", "directly connected"}


def test_trace_follows_core_to_direct_then_arp_mac_and_terminal(monkeypatch):
    devices = [
        {"id": "core", "hostname": "CORE", "ip_address": "192.0.2.1", "platform": "cisco_ios", "role": "core"},
        {"id": "agg", "hostname": "AGG", "ip_address": "192.0.2.2", "platform": "cisco_ios", "role": "aggregation"},
        {"id": "access", "hostname": "ACCESS", "ip_address": "192.0.2.3", "platform": "cisco_ios", "role": "access"},
    ]
    route_outputs = {
        "core": "Routing entry for 192.168.10.0/24\n  * 10.0.0.2, via GigabitEthernet1/0/1",
        "agg": "Routing entry for 192.168.10.0/24\n  * 10.0.0.3, via GigabitEthernet1/0/2",
        "access": "Routing entry for 192.168.10.0/24\n  * directly connected, via Vlan10",
    }

    class _Conn:
        def close(self):
            return None

    monkeypatch.setattr("services.ip_locator_trace_service._load_devices", lambda **_: devices)
    monkeypatch.setattr("services.ip_locator_trace_service._cached_route_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr("services.ip_locator_trace_service._cache_for_scope", lambda scope: (None, ""))
    monkeypatch.setattr("services.ip_locator_trace_service._run_cli_with_device_lease", lambda device, operation, callback, owner_id: callback())
    monkeypatch.setattr("services.ip_locator_trace_service._persist_observation", lambda **kwargs: None)
    monkeypatch.setattr("services.ip_locator_trace_service.get_db_connection", lambda: _Conn())
    monkeypatch.setattr("services.ip_locator_trace_service._find_next_hop_device", lambda conn, next_hop, current: {"id": "agg" if next_hop == "10.0.0.2" else "access"})
    monkeypatch.setattr("services.ip_locator_trace_service.legacy", type(
        "Legacy",
        (),
        {
            "parse_routing_table": staticmethod(lambda output, platform: []),
            "normalize_interface_name": staticmethod(lambda value: str(value or "").lower()),
            "_send_command": staticmethod(lambda device, command, force_refresh=False: route_outputs[device["id"]]),
            "_targeted_arp_query": staticmethod(lambda device, target_ip, vrf=None, force_refresh=False: (
                {"mac": "001122334455", "interface": "Vlan10", "vlan": "10", "source_device_id": "access", "source_device": "ACCESS"}
                if device["id"] == "access" else None
            )),
            "_targeted_mac_query": staticmethod(lambda device, mac, force_refresh=False: [
                {"mac": mac, "port": "GigabitEthernet1/0/10", "vlan": "10", "type": "dynamic"}
            ]),
            "_load_trace_port_identity": staticmethod(lambda conn, device_id, port: {}),
            "_trace_identity_confirms_access_terminal": staticmethod(lambda identity: True),
            "_collect_lldp_from_device": staticmethod(lambda device: []),
            "_normalize_mac": staticmethod(lambda value: str(value).replace(".", "").replace("-", "").replace(":", "").lower()),
            "_format_mac": staticmethod(lambda value: value),
        },
    ))
    monkeypatch.setattr("services.ip_locator_trace_service._topology_neighbors", lambda conn, device_id, port: [])
    monkeypatch.setattr("services.ip_locator_trace_service._lldp_neighbors", lambda device, port: [])

    result = trace_ip("192.168.10.100", start_device_id="core", force_refresh=True)

    assert result["status"] == "completed"
    assert result["conclusion"] == "managed_access_confirmed"
    assert [hop["device_id"] for hop in result["l3_paths"]] == ["core", "agg", "access"]
    assert result["arp_evidence"][0]["device_id"] == "access"
    assert result["location"]["device_id"] == "access"
    assert result["location"]["port"] == "GigabitEthernet1/0/10"
