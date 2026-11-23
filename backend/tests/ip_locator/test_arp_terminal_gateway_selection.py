"""ARP sweep sources are derived from who owns each endpoint Prefix gateway.

Endpoint Prefixes (IPv4 /28 or larger, IPv6 /124 or larger, not typed
loopback/transit/p2p/wan) get exactly one ARP source: the device holding the
Prefix gateway IP, else the lowest-addressed SVI owner, else the lowest
routed-interface owner. Loopback interfaces and point-to-point Prefixes never
pull a device into the sweep; device role is not consulted.
"""

from __future__ import annotations

from services import ip_locator_service


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _Connection:
    def __init__(self, rows):
        self.rows = rows
        self.closed = False

    def execute(self, _sql, _params=()):
        return _Result(self.rows)

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def _row(
    prefix_id,
    prefix,
    address,
    device_id,
    interface_name,
    *,
    gateway="",
    network_type="",
    interface_id=None,
    current_interface_observation=True,
    observed_interface_name=None,
    observed_ip=None,
):
    return {
        "prefix_id": prefix_id,
        "prefix": prefix,
        "network_type": network_type,
        "gateway": gateway,
        "address": address,
        "device_id": device_id,
        "interface_name": interface_name,
        "interface_id": interface_id if interface_id is not None else f"{device_id}:{interface_name}",
        "current_interface_observation": current_interface_observation,
        "observed_interface_name": observed_interface_name if observed_interface_name is not None else interface_name,
        "observed_ip": observed_ip if observed_ip is not None else address,
    }


def _select(monkeypatch, rows):
    connection = _Connection(rows)
    monkeypatch.delenv("ARP_AUTO_TERMINAL_GATEWAYS", raising=False)
    monkeypatch.setattr(ip_locator_service, "get_db_connection", lambda: connection)
    from services import ipam_service

    observations = [
        {
            "device_id": row["device_id"],
            "interface_name": row["observed_interface_name"],
            "normalized_interface_name": ip_locator_service.normalize_interface_name(
                row["observed_interface_name"]
            ),
            "ip_address": row["observed_ip"],
        }
        for row in rows
        if row["current_interface_observation"]
    ]
    monkeypatch.setattr(ipam_service, "_current_cmdb_interface_ip_observations", lambda _conn: observations)
    selected = ip_locator_service._load_terminal_gateway_device_ids()
    assert connection.closed is True
    return selected


def test_gateway_ip_owner_wins_over_lower_addressed_svi(monkeypatch) -> None:
    selected = _select(monkeypatch, [
        _row("p10", "10.1.10.0/24", "10.1.10.1", "dev-svi", "Vlan10", gateway="10.1.10.254"),
        _row("p10", "10.1.10.0/24", "10.1.10.254", "dev-gw", "GE1/0/1", gateway="10.1.10.254/24"),
    ])

    assert selected == {"dev-gw": "10.1.10.0/24"}


def test_without_gateway_svi_owner_beats_routed_port_then_lowest_address(monkeypatch) -> None:
    selected = _select(monkeypatch, [
        _row("p20", "10.1.20.0/24", "10.1.20.1", "dev-routed", "GE1/0/2"),
        _row("p20", "10.1.20.0/24", "10.1.20.3", "dev-svi-b", "Vlan-interface20"),
        _row("p20", "10.1.20.0/24", "10.1.20.2", "dev-svi-a", "Vlanif20"),
    ])

    assert selected == {"dev-svi-a": "10.1.20.0/24"}


def test_unbound_or_unverified_address_records_are_not_arp_gateway_evidence(monkeypatch) -> None:
    selected = _select(monkeypatch, [
        _row("p40", "10.1.40.0/24", "10.1.40.1", "empty-if", "", interface_id=""),
        _row(
            "p40", "10.1.40.0/24", "10.1.40.2", "manual-only", "GE1/0/1",
            interface_id="", current_interface_observation=False,
        ),
        _row(
            "p40", "10.1.40.0/24", "10.1.40.3", "stale-ip", "Vlan40",
            observed_ip="10.1.99.3",
        ),
        _row(
            "p40", "10.1.40.0/24", "10.1.40.4", "not-l3", "Vlan40",
            current_interface_observation=False,
        ),
    ])

    assert selected == {}


def test_address_outside_registered_prefix_is_not_gateway_evidence(monkeypatch) -> None:
    selected = _select(monkeypatch, [
        _row("p50", "10.1.50.0/24", "10.1.51.1", "wrong-prefix", "Vlan50"),
    ])

    assert selected == {}


def test_point_to_point_loopback_and_infrastructure_prefixes_are_excluded(monkeypatch) -> None:
    selected = _select(monkeypatch, [
        _row("p30", "10.254.12.0/30", "10.254.12.1", "core-1", "FGE1/0/53"),
        _row("p29", "10.254.100.0/29", "10.254.100.4", "core-1", "Vlan100"),
        _row("p32", "10.254.0.1/32", "10.254.0.1", "core-1", "Loop0"),
        _row("pt", "10.9.0.0/24", "10.9.0.1", "core-2", "GE1/0/9", network_type="transit"),
        _row("pl", "10.8.0.0/24", "10.8.0.1", "core-3", "LoopBack1"),
        _row("p6p2p", "2001:db8::/127", "2001:db8::", "core-4", "GE1/0/10"),
    ])

    assert selected == {}


def test_boundary_prefixes_and_ipv6_endpoint_prefix_are_included(monkeypatch) -> None:
    selected = _select(monkeypatch, [
        _row("p28", "10.2.0.0/28", "10.2.0.1", "edge-28", "Vlan2"),
        _row("p6", "2001:db8:1::/64", "2001:db8:1::1", "edge-v6", "Vlan6"),
    ])

    assert selected == {"edge-28": "10.2.0.0/28", "edge-v6": "2001:db8:1::/64"}


def test_one_device_owning_several_endpoint_prefixes_is_listed_once(monkeypatch) -> None:
    selected = _select(monkeypatch, [
        _row("p5", "172.16.5.0/24", "172.16.5.1", "s6850-5", "Vlan7"),
        _row("p6", "172.16.6.0/24", "172.16.6.1", "s6850-5", "Vlan8"),
    ])

    assert list(selected) == ["s6850-5"]
    assert selected["s6850-5"] in {"172.16.5.0/24", "172.16.6.0/24"}


def test_terminal_gateway_rule_can_be_disabled_without_touching_the_database(monkeypatch) -> None:
    monkeypatch.setenv("ARP_AUTO_TERMINAL_GATEWAYS", "0")

    def _fail():
        raise AssertionError("database must not be opened when the rule is disabled")

    monkeypatch.setattr(ip_locator_service, "get_db_connection", _fail)

    assert ip_locator_service._load_terminal_gateway_device_ids() == {}


def test_terminal_gateway_rule_degrades_to_empty_when_database_is_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("ARP_AUTO_TERMINAL_GATEWAYS", raising=False)

    def _unavailable():
        raise RuntimeError("database offline")

    monkeypatch.setattr(ip_locator_service, "get_db_connection", _unavailable)

    assert ip_locator_service._load_terminal_gateway_device_ids() == {}


def test_arp_sweep_adds_endpoint_gateway_owners_but_honours_explicit_opt_out(monkeypatch) -> None:
    devices = [
        {"id": "access-1", "role": "access"},
        {"id": "core-gw", "role": "core", "hostname": "AC_11"},
        {"id": "core-plain", "role": "core"},
        {"id": "fw-opt-out", "role": "firewall",
         "collection_policy_json": '{"collectors":{"arp":false}}'},
    ]
    monkeypatch.setattr(ip_locator_service, "_load_eligible_devices", lambda **_kwargs: devices)
    monkeypatch.setattr(ip_locator_service, "_load_prefix_gateway_device_ids", lambda: set())
    monkeypatch.setattr(
        ip_locator_service,
        "_load_terminal_gateway_device_ids",
        lambda: {"core-gw": "192.168.56.0/24", "fw-opt-out": "192.168.56.0/24"},
    )
    monkeypatch.setattr(ip_locator_service, "_load_arp_collection_state", lambda: {})
    monkeypatch.setattr(
        ip_locator_service,
        "reserve_collector_sweep_batch",
        lambda *_args, **_kwargs: {"start_cursor": 0, "selected_count": 10},
    )

    selected, total, skipped = ip_locator_service._load_arp_sweep_devices("run-terminal-gw")

    assert [device["id"] for device in selected] == ["access-1", "core-gw"]
    assert total == 2
    assert skipped == 0
