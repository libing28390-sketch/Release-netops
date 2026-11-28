"""Pure contract tests for the bounded CLI-only locator trace engine."""

from __future__ import annotations

import ipaddress
import json
import pytest

from services import ip_locator_service as locator_service
from services import ip_locator_trace_service as trace_service
from services.ip_locator_trace_service import (
    DIRECT_PROTOCOLS,
    TraceLimits,
    _best_routes,
    _is_direct,
    _parse_target_route_output,
    _load_devices,
    _route_command,
    _route_output_status,
    _redis_write_configured,
    _is_complete_full_snapshot,
    _set_cache_source,
    _neighbor_device_candidates,
    add_legacy_compatibility,
    UnsupportedLocatorPlatform,
    trace_ip,
)


@pytest.fixture(autouse=True)
def isolate_cli_fallback(monkeypatch):
    """This suite exercises the CLI fallback; SNMP entry has its own suite."""
    monkeypatch.setattr(trace_service, "_try_snmp_endpoint", lambda *args, **kwargs: None)


def test_cache_provenance_keeps_each_device_source_and_redis_write_ack():
    result = {"cache": {"route": "miss"}}
    first_device = {"id": "device-a", "hostname": "CORE-A"}
    second_device = {"id": "device-b", "hostname": "CORE-B"}

    _set_cache_source(
        result,
        "route",
        first_device,
        "cli",
        vrf="default",
        redis_write_attempted=True,
        redis_write_ack=True,
    )
    _set_cache_source(result, "route", second_device, "redis", vrf="default")
    _set_cache_source(result, "route", first_device, "postgres", vrf="default")

    assert result["cache"]["route"] == "postgres"
    assert result["cache_provenance"] == [
        {
            "stage": "route",
            "device_id": "device-a",
            "device": "CORE-A",
            "vrf": "default",
            "variant": "target",
            "source": "postgres",
            "redis_write_attempted": True,
            "redis_write_ack": True,
        },
        {
            "stage": "route",
            "device_id": "device-b",
            "device": "CORE-B",
            "vrf": "default",
            "variant": "target",
            "source": "redis",
        },
    ]


def test_cache_provenance_records_whole_result_redis_write_ack():
    result = {"cache": {"result": "miss"}, "cache_provenance": []}

    _set_cache_source(
        result,
        "result",
        {"hostname": "whole-result"},
        "miss",
        vrf="default",
        variant="whole_result",
        redis_write_attempted=True,
        redis_write_ack=True,
    )

    assert result["cache_provenance"] == [{
        "stage": "result",
        "device_id": "",
        "device": "whole-result",
        "vrf": "default",
        "variant": "whole_result",
        "source": "miss",
        "redis_write_attempted": True,
        "redis_write_ack": True,
    }]


def test_known_access_candidate_stays_partial_when_another_route_query_fails():
    result = add_legacy_compatibility({
        "target_ip": "172.16.5.10",
        "found": True,
        "status": "partial",
        "conclusion": "path_has_unverified_branch",
        "location": {
            "device_id": "access-switch",
            "device": "S6850-5",
            "port": "GE1/0/2",
            "vlan": "7",
            "mac": "8e4757600706",
        },
        "coverage_gaps": ["route_failed:401e4856-e337-4361-9974-3d186b15f394"],
        "errors": ["AC_21 路由查询失败"],
    })

    assert result["trace_status"] == "partial"
    assert result["locations"] == [{
        "switch_id": "access-switch",
        "switch_name": "S6850-5",
        "port": "GE1/0/2",
        "vlan": "7",
        "type": "PATH_TRACED_PARTIAL",
        "is_uplink": False,
        "note": "物理接入口已确认；部分路径证据仍待核验",
    }]
    assert result["errors"] == ["AC_21 路由查询失败"]


def test_redis_write_attempt_flag_matches_cache_backend():
    class _Cache:
        def __init__(self, backend):
            self.backend = backend

    assert _redis_write_configured(_Cache("redis"), "route:key") is True
    assert _redis_write_configured(_Cache("postgres"), "route:key") is False
    assert _redis_write_configured(_Cache("redis"), "") is False


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


def test_unknown_platform_fails_closed_instead_of_using_cisco_route_syntax():
    import pytest

    with pytest.raises(UnsupportedLocatorPlatform):
        _route_command({"vendor": "Unknown", "platform": "mystery_os"}, "192.0.2.10", "default")
    with pytest.raises(UnsupportedLocatorPlatform):
        _route_command({"vendor": "", "platform": ""}, "192.0.2.10", "default")


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


def test_route_output_classification_does_not_turn_empty_or_garbled_output_into_negative():
    assert _route_output_status("No route to host") == "not_found"
    assert _route_output_status("% Invalid input detected") == "unsupported"
    assert _route_output_status("") == "query_failed"
    assert _route_output_status("unexpected vendor output") == "parse_incomplete"


@pytest.mark.parametrize(
    ("status", "records", "expected"),
    [
        ({"status": "found", "coverage": "full"}, [{"ip": "192.0.2.10"}], True),
        ({"status": "not_found", "coverage": "full"}, [], True),
        ({"status": "found", "coverage": "partial"}, [{"ip": "192.0.2.10"}], False),
        ({"status": "found", "coverage": "targeted"}, [{"ip": "192.0.2.10"}], False),
        ({"status": "found"}, [{"ip": "192.0.2.10"}], False),
        ({}, [{"ip": "192.0.2.10"}], False),
        ({"status": "not_found", "coverage": "full"}, [{"ip": "192.0.2.10"}], False),
        ({"status": "found", "coverage": "full"}, [], False),
    ],
)
def test_snapshot_reconciliation_requires_explicit_complete_coverage(status, records, expected):
    assert _is_complete_full_snapshot(status, records) is expected


def test_ipv6_is_rejected_before_any_device_lookup(monkeypatch):
    monkeypatch.setattr(
        "services.ip_locator_trace_service._load_devices",
        lambda **_: (_ for _ in ()).throw(AssertionError("IPv6 must not start an ARP trace")),
    )
    monkeypatch.setattr("services.ip_locator_trace_service._cache_for_scope", lambda _scope: (None, ""))

    result = trace_ip("2001:db8::100")

    assert result["status"] == "failed"
    assert result["conclusion"] == "unsupported_address_family"
    assert result["reason_code"] == "IPV6_NDP_UNSUPPORTED"


def test_route_candidate_truncation_is_reported_and_cannot_look_complete(monkeypatch):
    devices = [
        {"id": "core", "hostname": "CORE", "platform": "cisco_ios", "role": "core"},
    ]

    class _Conn:
        def close(self):
            return None

    monkeypatch.setattr("services.ip_locator_trace_service._load_devices", lambda **_: devices)
    monkeypatch.setattr("services.ip_locator_trace_service._cached_route_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr("services.ip_locator_trace_service._cache_for_scope", lambda _scope: (None, ""))
    monkeypatch.setattr(
        "services.ip_locator_trace_service._run_cli_with_device_lease",
        lambda _device, _operation, callback, **_kwargs: callback(),
    )
    monkeypatch.setattr("services.ip_locator_trace_service.legacy._send_command", lambda *_args, **_kwargs: "")
    monkeypatch.setattr("services.ip_locator_trace_service.get_db_connection", lambda: _Conn())
    monkeypatch.setattr(
        "services.ip_locator_trace_service._parse_target_route_output",
        lambda *_args: [
            {"destination": "192.0.2.0/24", "protocol": "ospf", "next_hop": "198.51.100.1", "interface": "Gi1/0/1"},
            {"destination": "192.0.2.0/24", "protocol": "ospf", "next_hop": "198.51.100.2", "interface": "Gi1/0/2"},
        ],
    )
    monkeypatch.setattr(
        "services.ip_locator_trace_service._find_next_hop_device_candidates",
        lambda *_args: [],
    )
    monkeypatch.setattr("services.ip_locator_trace_service._persist_observation", lambda **_kwargs: True)
    result = trace_ip(
        "192.0.2.99",
        force_refresh=True,
        limits=TraceLimits(max_candidates_per_hop=1),
    )

    assert result["status"] == "partial"
    assert any(gap.startswith("route_candidate_budget_exceeded:") for gap in result["coverage_gaps"])


def test_trace_does_not_guess_when_next_hop_ip_matches_multiple_devices(monkeypatch):
    devices = [
        {"id": "core", "hostname": "CORE", "ip_address": "192.0.2.1", "platform": "cisco_ios", "role": "core"},
        {"id": "agg-a", "hostname": "AGG-A", "ip_address": "10.0.0.2", "platform": "cisco_ios", "role": "aggregation"},
        {"id": "agg-b", "hostname": "AGG-B", "ip_address": "10.0.0.2", "platform": "cisco_ios", "role": "aggregation"},
    ]
    queried_device_ids = []

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class _Conn:
        def execute(self, query, params=()):
            if "FROM devices" in query and "TRIM(ip_address) = ?" in query:
                assert params[0] == "10.0.0.2"
                return _Rows([{"id": "agg-a"}, {"id": "agg-b"}])
            return _Rows([])

        def close(self):
            return None

    monkeypatch.setattr("services.ip_locator_trace_service._load_devices", lambda **_: devices)
    monkeypatch.setattr("services.ip_locator_trace_service._cached_route_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr("services.ip_locator_trace_service._cache_for_scope", lambda _scope: (None, ""))
    monkeypatch.setattr("services.ip_locator_trace_service.get_db_connection", lambda: _Conn())
    monkeypatch.setattr(
        "services.ip_locator_trace_service._run_cli_with_device_lease",
        lambda device, _operation, callback, **_kwargs: (
            queried_device_ids.append(device["id"]), callback()
        )[1],
    )
    monkeypatch.setattr(locator_service, "_send_command", lambda *_args, **_kwargs: "route output")
    monkeypatch.setattr(
        "services.ip_locator_trace_service._parse_target_route_output",
        lambda *_args: [{
            "destination": "192.0.2.0/24",
            "protocol": "ospf",
            "next_hop": "10.0.0.2",
            "interface": "Gi1/0/1",
            "last_updated": "2026-09-12T00:00:00+00:00",
        }],
    )
    monkeypatch.setattr("services.ip_locator_trace_service._topology_neighbors", lambda *_args: [])
    monkeypatch.setattr(
        "services.ip_locator_trace_service._load_lldp_snapshot",
        lambda *_args, **_kwargs: ([], "", "", {"status": "not_found"}),
    )
    monkeypatch.setattr("services.ip_locator_trace_service._persist_observation", lambda **_kwargs: True)

    result = trace_ip("192.0.2.10", start_device_id="core", force_refresh=True)

    assert queried_device_ids == ["core"]
    assert any(gap == "next_hop_ambiguous:10.0.0.2" for gap in result["coverage_gaps"])
    assert result["status"] != "completed"


def test_topology_neighbor_without_id_keeps_duplicate_identity_ambiguous():
    devices = {
        "agg-a": {"id": "agg-a", "hostname": "agg", "ip_address": "10.0.0.2"},
        "agg-b": {"id": "agg-b", "hostname": "agg", "ip_address": "10.0.0.2"},
    }

    class _Rows:
        def fetchall(self):
            return [{"id": "agg-a"}, {"id": "agg-b"}]

    class _Conn:
        def execute(self, query, _params=()):
            return _Rows() if "TRIM(ip_address) = ?" in query else _RowsEmpty()

    class _RowsEmpty:
        def fetchall(self):
            return []

    candidates = _neighbor_device_candidates(
        _Conn(),
        {"neighbor_name": "agg", "neighbor_ip": "10.0.0.2"},
        devices,
    )

    assert {item["id"] for item in candidates} == {"agg-a", "agg-b"}


def test_unsupported_target_filters_use_one_shared_full_snapshot_per_device(monkeypatch):
    target_ip = "192.0.2.99"
    target_mac = "001122334455"
    device = {
        "id": "gateway",
        "hostname": "GATEWAY",
        "ip_address": "192.0.2.1",
        "platform": "cisco_ios",
        "role": "core",
    }
    calls = []

    class _Conn:
        def close(self):
            return None

    class _Snapshot(list):
        def __init__(self, records, status):
            super().__init__(records)
            self.status = status

    monkeypatch.setattr("services.ip_locator_trace_service._load_devices", lambda **_: [device])
    monkeypatch.setattr("services.ip_locator_trace_service._cached_route_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr("services.ip_locator_trace_service._cache_for_scope", lambda _scope: (None, ""))
    monkeypatch.setattr("services.ip_locator_trace_service.get_db_connection", lambda: _Conn())
    monkeypatch.setattr(
        "services.ip_locator_trace_service._parse_target_route_output",
        lambda *_args: [{
            "destination": "192.0.2.0/24",
            "protocol": "connected",
            "next_hop": "direct",
            "interface": "Vlan10",
            "last_updated": "2026-09-12T00:00:00+00:00",
        }],
    )
    monkeypatch.setattr(locator_service, "_send_command", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(locator_service, "_targeted_arp_query_status", lambda *_args, **_kwargs: {
        "status": "unsupported",
        "record": None,
        "error_code": "ARP_COMMAND_UNSUPPORTED",
    })
    arp_snapshots = []
    reconciled_snapshots = []

    def collect_arp_snapshot(*_args, **_kwargs):
        arp_snapshots.append(True)
        return _Snapshot(
            [{
                "ip": target_ip,
                "mac": target_mac,
                "interface": "GigabitEthernet1/0/48",
                "vlan": "10",
                "source_device_id": "gateway",
                "source_device": "GATEWAY",
            }],
            {"status": "found", "coverage": "full"},
        )

    monkeypatch.setattr(locator_service, "_collect_arp_snapshot", collect_arp_snapshot)
    monkeypatch.setattr(
        "services.ip_locator_trace_service._reconcile_full_snapshot_absences",
        lambda **kwargs: (
            reconciled_snapshots.append((kwargs["kind"], kwargs["status"]["coverage"]))
            or {"applied": True, "revoked_count": 0}
        ),
    )
    monkeypatch.setattr(
        locator_service,
        "_targeted_mac_query",
        lambda dev, mac, force_refresh=False, allow_full_table_fallback=True:
            locator_service._mac_query_result(
                dev,
                [],
                "unsupported",
                error_code="MAC_COMMAND_UNSUPPORTED",
            ),
    )
    mac_snapshots = []

    def collect_mac_snapshot(_device):
        mac_snapshots.append(True)
        return _Snapshot(
            [{
                "mac": target_mac,
                "port": "GigabitEthernet1/0/10",
                "vlan": "10",
                "type": "dynamic",
            }],
            {"status": "found", "coverage": "full"},
        )

    monkeypatch.setattr(locator_service, "_collect_mac_table_snapshot", collect_mac_snapshot)
    monkeypatch.setattr("services.ip_locator_trace_service._run_cli_with_device_lease", lambda _device, operation, callback, **_kwargs: (calls.append(operation), callback())[1])
    monkeypatch.setattr("services.ip_locator_trace_service._persist_observation", lambda **_kwargs: True)
    monkeypatch.setattr(
        "services.ip_locator_trace_service._load_lldp_snapshot",
        lambda *_args, **_kwargs: ([], "2026-09-12T00:00:00+00:00", "", {"status": "not_found"}),
    )
    monkeypatch.setattr("services.ip_locator_trace_service._terminal_evidence", lambda *_args: {"is_terminal": False})

    result = trace_ip(target_ip, start_device_id="gateway", force_refresh=True)

    assert arp_snapshots == [True]
    assert mac_snapshots == [True]
    assert reconciled_snapshots == [("arp", "full"), ("mac", "full")]
    assert calls.count("arp") == 2
    assert calls.count("mac") == 2
    assert result["arp_evidence"][0]["mac"] == target_mac
    assert result["l2_paths"][0]["hops"][0]["port"] == "GigabitEthernet1/0/10"
    assert result["status"] == "partial"


@pytest.mark.parametrize("arp_cached", [False, True], ids=["cli-arp", "redis-arp"])
def test_trace_follows_core_to_direct_then_arp_mac_and_terminal(monkeypatch, arp_cached):
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

    class _Cache:
        def __init__(self):
            self.writes = []

        def build_key(self, kind, scope_hash, *parts):
            return ":".join((kind, scope_hash, *(str(part) for part in parts)))

        def get_json(self, key):
            if arp_cached and key.startswith("arp:"):
                return {
                    "record": {
                        "mac": "001122334455",
                        "interface": "Vlan10",
                        "vlan": "10",
                        "source_device_id": "access",
                        "source_device": "ACCESS",
                    },
                    "collected_at": "2026-09-12T08:00:00+00:00",
                    "_locator_dependency": {"scope": "global"},
                }
            return None

        def set_json(self, key, payload, **_kwargs):
            self.writes.append((key, payload))
            return True

        def is_fresh(self, kind, _collected_at):
            return bool(arp_cached and kind == "arp")

        def acquire_lock(self, _key, ttl):
            return "test-lock" if ttl else None

        def release_lock(self, _key, _token):
            return True

        def ping(self):
            return True

    cache = _Cache()
    calls = []

    monkeypatch.setattr("services.ip_locator_trace_service._load_devices", lambda **_: devices)
    monkeypatch.setattr("services.ip_locator_trace_service._cached_route_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr("services.ip_locator_trace_service._cache_for_scope", lambda _scope: (cache, "cache-scope"))
    monkeypatch.setattr(
        "services.ip_locator_trace_service._run_cli_with_device_lease",
        lambda device, operation, callback, owner_id, **kwargs: (calls.append(operation), callback())[1],
    )
    def persist_observation(**kwargs):
        kind = str(kwargs.get("kind") or "")
        device_id = str(kwargs.get("device_id") or "")
        return {
            "observation_key": f"observation:{kind}:{device_id}",
            "generation": 1,
            "observation_kind": kind,
            "device_id": device_id,
            "action_version": "action-v1",
            "parser_version": "parser-v1",
            "schema_version": "schema-v1",
        }

    monkeypatch.setattr("services.ip_locator_trace_service._persist_observation", persist_observation)
    monkeypatch.setattr("services.ip_locator_trace_service.get_db_connection", lambda: _Conn())
    monkeypatch.setattr("services.ip_locator_trace_service._find_next_hop_device_candidates", lambda _conn, next_hop, eligible: [eligible["agg" if next_hop == "10.0.0.2" else "access"]])
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
            "_load_trace_port_identity": staticmethod(lambda *_args, **_kwargs: {}),
            "_trace_identity_confirms_access_terminal": staticmethod(lambda identity: True),
            "_collect_lldp_from_device": staticmethod(lambda device: []),
            "_normalize_mac": staticmethod(lambda value: str(value).replace(".", "").replace("-", "").replace(":", "").lower()),
            "_format_mac": staticmethod(lambda value: value),
        },
    ))
    monkeypatch.setattr("services.ip_locator_trace_service._topology_neighbors", lambda conn, device_id, port: [])
    monkeypatch.setattr("services.ip_locator_trace_service._find_fresh_observation", lambda **_kwargs: None)
    monkeypatch.setattr(
        "services.ip_locator_trace_service._cached_observation_is_current",
        lambda cached, **kwargs: cached if kwargs.get("kind") == "arp" and isinstance(cached, dict) else None,
    )
    monkeypatch.setattr("services.ip_locator_trace_service._pending_fact_invalidation", lambda *_args: False)
    monkeypatch.setattr("services.ip_locator_trace_service._manifest_is_current_for_code", lambda _manifest: True)
    monkeypatch.setattr(
        "services.ip_locator_task_service.get_locator_dependency_generation",
        lambda *_args: {"generation": 12},
    )
    monkeypatch.setattr(
        "services.ip_locator_trace_service._load_lldp_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("confirmed terminal interface must not query LLDP")
        ),
    )

    result = trace_ip("192.168.10.100", start_device_id="core", force_refresh=False)

    assert result["status"] == "completed", {
        key: result.get(key)
        for key in (
            "status", "conclusion", "errors", "coverage_gaps", "l3_paths",
            "arp_evidence", "l2_paths", "terminal_candidates",
        )
    }
    assert result["conclusion"] == "managed_access_confirmed"
    assert [hop["device_id"] for hop in result["l3_paths"]] == ["core", "agg", "access"]
    arp_write = next(
        entry for entry in result["cache_provenance"]
        if entry["stage"] == "arp" and entry["device_id"] == "access" and entry["variant"] == "target"
    )
    assert arp_write["source"] == ("redis" if arp_cached else "cli")
    if arp_cached:
        assert "redis_write_attempted" not in arp_write
        assert not any(key.startswith("arp:") for key, _payload in cache.writes)
    else:
        assert arp_write.get("redis_write_attempted") is True
        assert arp_write.get("redis_write_ack") is True
    assert calls.count("arp") == (0 if arp_cached else 1)
    assert result["arp_evidence"][0]["device_id"] == "access"
    assert result["location"]["device_id"] == "access"
    assert result["location"]["port"] == "GigabitEthernet1/0/10"


def test_v2_compatibility_restores_locator_context_without_live_cli(monkeypatch):
    observed: dict[str, object] = {}

    def build_context(target_ip, result=None, *, allow_live_interface_status=True):
        observed.update({
            "target_ip": target_ip,
            "result": result,
            "allow_live_interface_status": allow_live_interface_status,
        })
        return {
            "address": {"ip": target_ip},
            "l2": {"vlan": "7", "vlan_source": "arp_table"},
            "l3": {"route_source": "BGP", "next_hop": "10.254.0.5"},
            "business": {},
            "freshness": {"collected_at": "2026-09-12T08:00:00+00:00"},
            "path": [],
        }

    monkeypatch.setattr(locator_service, "_get_ip_locator_context", build_context)
    result = {
        "target_ip": "172.16.5.10",
        "status": "completed",
        "conclusion": "managed_access_confirmed",
        "found": True,
        "location": {
            "device_id": "access-1",
            "device": "S6850-5",
            "port": "GE1/0/2",
            "vlan": "7",
            "mac": "8e4757600706",
        },
        "arp_evidence": [],
        "queried_devices": {"arp": [], "mac": [], "lldp": []},
        "cache": {"result": "miss"},
    }

    enriched = add_legacy_compatibility(result)

    assert enriched["context"]["l2"]["vlan"] == "7"
    assert enriched["context"]["l3"]["route_source"] == "BGP"
    assert observed["target_ip"] == "172.16.5.10"
    assert observed["result"]["locations"][0]["switch_name"] == "S6850-5"
    assert observed["allow_live_interface_status"] is False


def test_stale_redis_observation_is_not_added_to_dependency_manifest():
    class _StaleCache:
        def is_fresh(self, _kind, _collected_at):
            return False

    versions = {
        "action_version": "action-v1",
        "parser_version": "parser-v1",
        "schema_version": "schema-v1",
    }
    result = {
        "dependency_manifest": {
            "topology": {"key": "topology:global", "scope": "global", "generation": 1},
            "observations": [],
        }
    }
    cached = {
        "records": [{"next_hop": "192.0.2.1"}],
        "collected_at": "2026-09-12T08:00:00+00:00",
        "_locator_dependency": {
            "scope": "global",
            "topology_generation": 1,
            "observation_key": "observation-v2:stale-route",
            "generation": 3,
            **versions,
        },
    }

    validated = trace_service._cached_observation_is_current(
        cached,
        expected_versions=versions,
        result=result,
        cache=_StaleCache(),
        kind="route",
    )

    assert validated is None
    assert result["dependency_manifest"]["observations"] == []


def test_trace_ip_result_cache_uses_the_same_start_device_scope_for_read_and_write(monkeypatch):
    class _Cache:
        def __init__(self):
            self.values: dict[str, dict] = {}

        def scope_hash(self, scope):
            return json.dumps(scope, sort_keys=True, separators=(",", ":"))

        def build_key(self, kind, scope_hash, *parts):
            return json.dumps((kind, scope_hash, *parts), separators=(",", ":"))

        def get_json(self, key):
            return self.values.get(key)

        def set_json(self, key, payload, **_kwargs):
            self.values[key] = dict(payload)
            return True

        def is_fresh(self, _kind, _collected_at):
            return True

        def acquire_lock(self, _key, ttl):
            return "lock-token" if ttl else None

        def release_lock(self, _key, _token):
            return True

        def ping(self):
            return True

    cache = _Cache()
    uncached_calls: list[str] = []
    monkeypatch.setattr("services.ip_locator_cache_service.get_locator_cache", lambda: cache)
    monkeypatch.setattr(trace_service, "_manifest_is_current_for_code", lambda _manifest: True)
    monkeypatch.setattr(trace_service, "_pending_fact_invalidation", lambda *_args: False)

    def run_uncached(target_ip, **kwargs):
        uncached_calls.append(target_ip)
        tenant_id = str(kwargs.get("tenant_id") or "tenant-default")
        site_id = str(kwargs.get("site_id") or "")
        network_domain_id = str(kwargs.get("network_domain_id") or "")
        vrf = trace_service._normalise_vrf(kwargs.get("vrf") or "default")
        start_device_id = str(kwargs.get("start_device_id") or "")
        authorized_device_ids = kwargs.get("authorized_device_ids")
        scope = {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "network_domain_id": network_domain_id,
            "vrf": vrf,
            "start_device_id": start_device_id,
            "authorization_scope_hash": trace_service._authorization_scope_hash(authorized_device_ids),
        }
        scoped_cache, scope_hash = trace_service._cache_for_scope(scope)
        key = trace_service._cache_key(
            scoped_cache,
            "result",
            scope_hash,
            target_ip,
            vrf,
            start_device_id or "auto",
        )
        payload = {
            "run_id": "generated-run",
            "target_ip": target_ip,
            "status": "completed",
            "conclusion": "managed_access_confirmed",
            "found": True,
            "created_at": "2026-09-12T08:00:00+00:00",
            "evidence_collected_at": "2026-09-12T08:00:00+00:00",
            "dependency_manifest": {"observations": []},
            "cache": {"result": "miss"},
        }
        scoped_cache.set_json(key, payload, kind="result", collected_at=payload["created_at"])
        return payload

    monkeypatch.setattr(trace_service, "_trace_ip_uncached", run_uncached)
    options = {
        "tenant_id": "tenant-cache-test",
        "site_id": "site-cache-test",
        "start_device_id": "core-cache-test",
        "authorized_device_ids": ["device-cache-test"],
    }

    first = trace_ip("172.16.5.10", **options)
    second = trace_ip("172.16.5.10", **options)

    assert first["cache"]["result"] == "miss"
    assert second["cache"]["result"] == "hit"
    assert second["cache_provenance"] == [{
        "stage": "result",
        "device_id": "",
        "device": "whole-result",
        "vrf": "default",
        "variant": "whole_result",
        "source": "redis",
    }]
    assert uncached_calls == ["172.16.5.10"]


def test_lldp_snapshot_uses_shared_redis_projection_without_device_cli(monkeypatch):
    from services import ip_locator_trace_service as trace_service
    from services import topology_lldp_snapshot_service as snapshot_service

    device = {
        "id": "access-switch",
        "hostname": "ACCESS-01",
        "ip_address": "192.0.2.10",
        "platform": "cisco_ios",
        "site_id": "site-a",
        "tenant_id": "tenant-a",
    }
    collected_at = "2026-09-12T08:00:00+00:00"
    marker = {
        "device_id": "access-switch",
        "generation": 7,
        "state": "complete",
        "snapshot_complete": True,
        "observation_count": 1,
        "started_at": "2026-09-12T07:59:00+00:00",
        "completed_at": collected_at,
        "action_version": "action-v1",
        "parser_version": "parser-v1",
        "schema_version": "schema-v1",
    }
    monkeypatch.setattr(snapshot_service, "get_lldp_snapshot_marker", lambda _device_id: marker)
    monkeypatch.setattr(
        snapshot_service,
        "load_complete_lldp_snapshot",
        lambda *_args, **_kwargs: {
            "neighbors": [{
                "local_interface": "GigabitEthernet1/0/48",
                "neighbor": "DIST-01",
                "neighbor_port": "TenGigabitEthernet1/0/1",
                "neighbor_ip": "192.0.2.1",
                "neighbor_id": "distribution-switch",
                "protocol": "lldp",
                "evidence": "topology_snapshot",
            }],
            "collected_at": collected_at,
            "source": "redis",
            "marker": marker,
        },
    )
    monkeypatch.setattr(trace_service, "_pending_fact_invalidation", lambda *_args: False)
    monkeypatch.setattr(trace_service, "_find_fresh_observation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        trace_service,
        "_run_cli_with_device_lease",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLDP CLI must not run on shared-cache hit")),
    )

    result = {
        "run_id": "locator-run-test",
        "cache": {"topology": "miss"},
        "queried_devices": {"lldp": []},
        "coverage_gaps": [],
        "freshness": {"topology": None},
        "evidence_collected_at": None,
        "dependency_manifest": {
            "topology": {"key": "topology:global", "scope": "global", "generation": 12},
            "observations": [],
            "topology_snapshots": [],
        },
    }

    neighbors, observed_at, _task_id, status = trace_service._load_lldp_snapshot(
        device,
        "Gi1/0/48",
        cache=None,
        scope={"tenant_id": "tenant-a", "site_id": "site-a"},
        scope_hash="scope-a",
        tenant_id="tenant-a",
        target_ip="192.0.2.99",
        network_domain_id="",
        site_id="site-a",
        vrf="default",
        force_refresh=False,
        durable_run_id="",
        run_owner_id="user-a",
        cancel_check=None,
        result=result,
        wait_seconds=5,
    )

    assert neighbors[0]["neighbor_name"] == "DIST-01"
    assert neighbors[0]["evidence"] == "topology_snapshot"
    assert observed_at == collected_at
    assert status["status"] == "found"
    assert result["cache"]["topology"] == "redis"
    assert result["cache_provenance"] == [{
        "stage": "topology",
        "device_id": "access-switch",
        "device": "ACCESS-01",
        "vrf": "default",
        "variant": "shared_snapshot",
        "source": "redis",
    }]
    assert result["queried_devices"]["lldp"] == []
    assert result["dependency_manifest"]["topology_snapshots"] == [{
        "device_id": "access-switch",
        "generation": 7,
        "action_version": "action-v1",
        "parser_version": "parser-v1",
        "schema_version": "schema-v1",
    }]


def test_lldp_force_refresh_bypasses_shared_snapshot_and_queries_device(monkeypatch):
    from services import ip_locator_trace_service as trace_service
    from services import topology_lldp_snapshot_service as snapshot_service

    class _Records(list):
        status = {"status": "found", "coverage": "full"}

    device = {
        "id": "access-switch",
        "hostname": "ACCESS-01",
        "ip_address": "192.0.2.10",
        "platform": "cisco_ios",
    }
    collection = _Records([{
        "local_interface": "GigabitEthernet1/0/48",
        "neighbor": "DIST-01",
        "neighbor_port": "TenGigabitEthernet1/0/1",
        "protocol": "lldp",
    }])
    cli_calls = []
    monkeypatch.setattr(
        snapshot_service,
        "get_lldp_snapshot_marker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("force refresh must bypass snapshot reads")),
    )
    monkeypatch.setattr(
        snapshot_service,
        "load_complete_lldp_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("force refresh must bypass Redis")),
    )
    monkeypatch.setattr(trace_service, "_pending_fact_invalidation", lambda *_args: False)
    monkeypatch.setattr(trace_service, "_find_fresh_observation", lambda **_kwargs: None)
    monkeypatch.setattr(trace_service.legacy, "_collect_lldp_from_device", lambda _device: collection)
    monkeypatch.setattr(
        trace_service,
        "_run_cli_with_device_lease",
        lambda _device, _operation, callback, **_kwargs: (cli_calls.append(True), callback())[1],
    )
    monkeypatch.setattr(
        trace_service,
        "_persist_observation",
        lambda **_kwargs: {
            "observation_key": "observation-force-lldp",
            "generation": 1,
            "observation_kind": "neighbor",
            "device_id": "access-switch",
            "action_version": "action-v1",
            "parser_version": "parser-v1",
            "schema_version": "schema-v1",
        },
    )
    result = {
        "run_id": "locator-force-test",
        "queried_devices": {"lldp": []},
        "coverage_gaps": [],
        "freshness": {"topology": None},
        "evidence_collected_at": None,
        "cache": {"topology": "miss"},
        "dependency_manifest": {
            "topology": {"key": "topology:global", "scope": "global", "generation": 12},
            "observations": [],
            "topology_snapshots": [],
        },
    }

    neighbors, _collected_at, _task_id, status = trace_service._load_lldp_snapshot(
        device,
        "Gi1/0/48",
        cache=None,
        scope={"tenant_id": "tenant-a"},
        scope_hash="scope-a",
        tenant_id="tenant-a",
        target_ip="192.0.2.99",
        network_domain_id="",
        site_id="",
        vrf="default",
        force_refresh=True,
        durable_run_id="",
        run_owner_id="user-a",
        cancel_check=None,
        result=result,
        wait_seconds=5,
    )

    assert cli_calls == [True]
    assert neighbors[0]["neighbor_name"] == "DIST-01"
    assert status["status"] == "found"
    assert result["queried_devices"]["lldp"] == ["ACCESS-01"]
    assert result["cache"]["topology"] == "cli"
    assert result["cache_provenance"] == [{
        "stage": "topology",
        "device_id": "access-switch",
        "device": "ACCESS-01",
        "vrf": "default",
        "variant": "full_snapshot",
        "source": "cli",
    }]


def test_device_candidates_are_tenant_site_and_authorization_scoped(monkeypatch):
    devices = [
        {"id": "a-core", "tenant_id": "tenant-a", "site_id": "site-a", "site": "A", "status": "online"},
        {"id": "a-other-site", "tenant_id": "tenant-a", "site_id": "site-b", "site": "B", "status": "online"},
        {"id": "b-core", "tenant_id": "tenant-b", "site_id": "site-a", "site": "A", "status": "online"},
    ]
    monkeypatch.setattr("services.ip_locator_trace_service.legacy._load_eligible_devices", lambda **kwargs: devices)

    visible = _load_devices(
        tenant_id="tenant-a",
        site_id="site-a",
        authorized_device_ids=["a-core", "a-other-site", "b-core"],
    )
    missing_site = _load_devices(tenant_id="tenant-a", site_id="site-missing")
    narrowed = _load_devices(tenant_id="tenant-a", authorized_device_ids=["a-other-site"])

    assert [item["id"] for item in visible] == ["a-core"]
    assert missing_site == []
    assert [item["id"] for item in narrowed] == ["a-other-site"]


def test_unknown_network_domain_fails_closed_before_loading_devices(monkeypatch):
    monkeypatch.setattr("services.ip_locator_trace_service._cache_for_scope", lambda scope: (None, ""))
    monkeypatch.setattr(
        "services.ip_locator_trace_service.legacy._load_eligible_devices",
        lambda: (_ for _ in ()).throw(AssertionError("must not load devices for unverified domain")),
    )

    result = trace_ip("192.0.2.1", network_domain_id="domain-unknown", force_refresh=True)

    assert result["status"] == "needs_context"
    assert result["conclusion"] == "network_domain_scope_unavailable"


def test_load_devices_never_falls_back_outside_tenant_or_unmatched_site(monkeypatch):
    devices = [
        {"id": "tenant-a-core", "tenant_id": "tenant-a", "site_id": "site-a"},
        {"id": "tenant-a-access", "tenant_id": "tenant-a", "site_id": "site-b"},
        {"id": "tenant-b-core", "tenant_id": "tenant-b", "site_id": "site-a"},
    ]
    monkeypatch.setattr("services.ip_locator_trace_service.legacy._load_eligible_devices", lambda **kwargs: devices)

    site_devices = _load_devices(tenant_id="tenant-a", site_id="site-a")
    missing_site_devices = _load_devices(tenant_id="tenant-a", site_id="site-missing")
    authorized_devices = _load_devices(tenant_id="tenant-a", authorized_device_ids=["tenant-a-access", "tenant-b-core"])

    assert [item["id"] for item in site_devices] == ["tenant-a-core"]
    assert missing_site_devices == []
    assert [item["id"] for item in authorized_devices] == ["tenant-a-access"]


def test_trace_requires_core_start_when_caller_did_not_select_one(monkeypatch):
    devices = [{"id": "aggregation-1", "tenant_id": "tenant-default", "role": "aggregation"}]
    monkeypatch.setattr("services.ip_locator_trace_service._load_devices", lambda **_: devices)
    monkeypatch.setattr("services.ip_locator_trace_service._cache_for_scope", lambda scope: (None, ""))
    monkeypatch.setattr(
        "services.ip_locator_trace_service._cached_route_rows",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not probe without a core")),
    )

    result = trace_ip("192.0.2.10", force_refresh=True)

    assert result["status"] == "needs_context"
    assert result["conclusion"] == "core_start_not_configured"


@pytest.fixture
def native_projection_conn(isolated_db):
    import psycopg2
    from database import core

    conn = core._PgRawConnection(psycopg2.connect(core._DATABASE_URL))
    try:
        yield conn
    finally:
        conn.close()


def test_find_next_hop_device_candidates_matches_cidr_interface_ips(native_projection_conn):
    from services.ip_locator_trace_service import _find_next_hop_device_candidates

    conn = native_projection_conn
    conn.execute("CREATE TEMP TABLE devices (id TEXT, hostname TEXT, role TEXT, platform TEXT, ip_address TEXT)")
    conn.execute("CREATE TEMP TABLE interfaces (device_id TEXT, primary_ip TEXT, ip_address TEXT)")
    conn.execute("CREATE TEMP TABLE ip_addresses (device_id TEXT, address TEXT)")
    conn.execute("CREATE TEMP TABLE ip_inventory (device_id TEXT, ip TEXT)")
    conn.execute("CREATE TEMP TABLE cmdb_device_interface_address_observations (device_id TEXT, ip_address INET, generation BIGINT)")
    conn.execute("CREATE TEMP TABLE cmdb_collection_snapshots (device_id TEXT, domain TEXT, successful_generation BIGINT)")
    conn.execute("INSERT INTO devices VALUES ('dev-1', 'SW-CORE-1', 'core', 'hp_comware', '10.0.0.1')")
    conn.execute("INSERT INTO interfaces VALUES ('dev-1', '', '10.255.18.25/30')")
    conn.execute("INSERT INTO ip_addresses VALUES ('dev-2', '10.255.18.19/30')")
    conn.execute("INSERT INTO devices VALUES ('dev-2', 'SW-CORE-2', 'core', 'hp_comware', '10.0.0.2')")
    eligible = {
        "dev-1": {"id": "dev-1", "hostname": "SW-CORE-1", "role": "core", "platform": "hp_comware", "ip_address": "10.0.0.1"},
        "dev-2": {"id": "dev-2", "hostname": "SW-CORE-2", "role": "core", "platform": "hp_comware", "ip_address": "10.0.0.2"},
    }
    m1 = _find_next_hop_device_candidates(conn, "10.255.18.25", eligible)
    m2 = _find_next_hop_device_candidates(conn, "10.255.18.19", eligible)
    assert [d["id"] for d in m1] == ["dev-1"]
    assert [d["id"] for d in m2] == ["dev-2"]


def test_confirmed_access_hides_unrelated_next_hop_unmanaged_errors():
    result = add_legacy_compatibility({
        "target_ip": "10.16.9.11",
        "found": True,
        "status": "completed",
        "conclusion": "managed_access_confirmed",
        "location": {"device_id": "sw-1", "device": "SW-1", "port": "BAGG1", "vlan": "9", "mac": "00505696c803"},
        "coverage_gaps": ["next_hop_unmanaged:10.255.18.25", "route_failed:other-sw"],
        "errors": ["WXTJY-1015-SW254 路由查询失败"],
    })
    assert result["trace_status"] == "terminal"
    assert result["errors"] == []


def test_topology_incomplete_surfaces_readable_l2_port_mode_hint():
    result = add_legacy_compatibility({
        "target_ip": "10.16.9.11",
        "found": False,
        "status": "partial",
        "conclusion": "topology_incomplete",
        "l2_paths": [{
            "device_id": "sw-1",
            "device": "SW-ACCESS-1",
            "port": "GE1/0/5",
            "terminal_evidence": {"is_access": False, "is_trunk": False, "is_aggregation": False},
        }],
        "coverage_gaps": ["topology_incomplete:sw-1:GE1/0/5", "next_hop_unmanaged:10.255.18.25"],
        "errors": [],
    })
    assert result["trace_status"] == "incomplete"
    assert any("SW-ACCESS-1:GE1/0/5" in e and "端口模式" in e for e in result["errors"])


def test_fallback_direct_gateways_from_arp_recovers_core_switch(native_projection_conn):
    from services.ip_locator_trace_service import _brief_query_error, _fallback_direct_gateways_from_arp

    conn = native_projection_conn
    conn.execute(
        "CREATE TEMP TABLE ipam_current_arp_observations "
        "(source_device_id TEXT, ip_address TEXT, interface_name TEXT, vlan_id TEXT, observed_at TEXT)"
    )
    conn.execute(
        "INSERT INTO ipam_current_arp_observations VALUES "
        "('sw-254', '192.168.9.30', 'GE2/5/0/18', '9', '2026-11-27T16:00:00Z')"
    )
    eligible = {
        "sw-254": {"id": "sw-254", "hostname": "WXTJY-1015-SW254", "role": "core", "platform": "hp_comware"},
    }
    gateways = _fallback_direct_gateways_from_arp(conn, "192.168.9.30", eligible)
    assert len(gateways) == 1
    assert gateways[0][0]["id"] == "sw-254"
    assert gateways[0][1]["source"] == "arp_fallback"
    assert gateways[0][1]["interface"] == "GE2/5/0/18"
    assert _brief_query_error(TimeoutError("timed out")) == "连接或命令超时"
    assert _brief_query_error(ValueError("UNSUPPORTED_ACTION: get_route")) == "平台未配置路由查询动作"


def test_dual_homed_server_lag_compatibility_exposes_both_ports_as_terminal():
    result = add_legacy_compatibility({
        "target_ip": "192.168.11.111",
        "found": True,
        "status": "completed",
        "conclusion": "dual_homed_access_confirmed",
        "location": {
            "device_id": "sw-1", "device": "TOR-1", "port": "Bridge-Aggregation2",
            "vlan": "11", "mac": "565a00015e6b", "endpoint_classification": "SERVER_LAG_ENDPOINT",
        },
        "terminal_candidates": [
            {
                "device_id": "sw-1", "device": "TOR-1", "port": "Bridge-Aggregation2",
                "vlan": "11", "mac": "565a00015e6b", "endpoint_classification": "SERVER_LAG_ENDPOINT",
            },
            {
                "device_id": "sw-2", "device": "TOR-2", "port": "Bridge-Aggregation2",
                "vlan": "11", "mac": "565a00015e6b", "endpoint_classification": "SERVER_LAG_ENDPOINT",
            },
        ],
        "coverage_gaps": ["next_hop_unmanaged:10.255.18.25"],
        "errors": [],
    })
    assert result["trace_status"] == "terminal"
    assert result["mac_lookup"]["status"] == "found"
    assert len(result["locations"]) == 2
    assert {loc["switch_name"] for loc in result["locations"]} == {"TOR-1", "TOR-2"}
    assert result["errors"] == []


def test_live_lag_member_and_per_port_lldp_verbose_parsers():
    from services.ip_locator_trace_service import (
        _lag_member_command,
        _lldp_interface_verbose_command,
        _parse_lag_member_ports,
        _parse_lldp_verbose_neighbors,
    )

    h3c_dev = {"id": "sw-254", "hostname": "WXTJY-1015-SW254", "platform": "hp_comware"}
    assert _lag_member_command(h3c_dev, "BAGG2") == "display link-aggregation verbose Bridge-Aggregation2"
    assert _lldp_interface_verbose_command(h3c_dev, "XGE1/3/0/4") == (
        "display lldp neighbor-information interface Ten-GigabitEthernet1/3/0/4 verbose"
    )

    lag_out = (
        "Loadsharing Type: Shar -- Loadsharing, NonS -- Non-Loadsharing\n"
        "Aggregate Interface: Bridge-Aggregation2\n"
        "  XGE1/3/0/4     S        32768    12  0x3  ABCDEF\n"
        "  XGE2/3/0/4(R)  S        32768    13  0x3  ABCDEF\n"
    )
    assert _parse_lag_member_ports(lag_out, "bridge-aggregation2") == ["XGE1/3/0/4", "XGE2/3/0/4"]
    inactive_out = lag_out + "  XGE3/3/0/4     U     32768 14\n"
    assert _parse_lag_member_ports(inactive_out, "bridge-aggregation2") == ["XGE1/3/0/4", "XGE2/3/0/4"]
    assert _parse_lag_member_ports("Gi1/0/1(P) Gi1/0/2(D) Gi1/0/3(I)", "po2") == ["Gi1/0/1"]


    lldp_out = (
        "LLDP neighbor-information of port 10[Ten-GigabitEthernet1/3/0/4]:\n"
        "  System name             : WXTJY-1F-SW4\n"
        "  Port ID                 : Ten-GigabitEthernet1/0/49\n"
        "  Management address      : 10.16.40.4\n"
    )
    neighbors = _parse_lldp_verbose_neighbors(lldp_out, "XGE1/3/0/4")
    assert len(neighbors) == 1
    assert neighbors[0]["neighbor_name"] == "WXTJY-1F-SW4"
    assert neighbors[0]["neighbor_ip"] == "10.16.40.4"
    assert neighbors[0]["neighbor_port"] == "Ten-GigabitEthernet1/0/49"


@pytest.mark.parametrize("mode", ["all_found", "third_member_only", "empty"])
def test_per_port_lldp_verbose_recovers_from_full_snapshot_failure_without_duplicate_lag_cli(monkeypatch, mode):
    from services import ip_locator_trace_service as ts

    h3c_dev = {
        "id": "sw-254",
        "hostname": "WXTJY-1015-SW254",
        "ip_address": "10.16.40.254",
        "platform": "hp_comware",
    }
    sent_commands: list[str] = []

    def fake_send_command(device, command, force_refresh=False):
        sent_commands.append(command)
        if "link-aggregation verbose" in command:
            return (
                "Aggregate Interface: Bridge-Aggregation2\n"
                "  XGE1/3/0/4     S        32768    12  0x3  ABCDEF\n"
                "  XGE2/3/0/4(R)  S        32768    13  0x3  ABCDEF\n"
                "  XGE3/3/0/4     S        32768    14  0x3  ABCDEF\n"
                "  XGE4/3/0/4     S        32768    15  0x3  ABCDEF\n"
            )
        if "lldp neighbor-information interface" in command:
            if mode == "empty" or (mode == "third_member_only" and "3/3/0/4" not in command):
                return "unclassified response"
            return (
                "LLDP neighbor-information of port 10[Ten-GigabitEthernet1/3/0/4]:\n"
                "  System name             : WXTJY-1F-SW4\n"
                "  Port ID                 : Ten-GigabitEthernet1/0/49\n"
                "  Management address      : 10.16.40.4\n"
            )
        return ""

    from services.ip_locator_cli_service import LocatorCLIResult

    monkeypatch.setattr(ts.legacy, "_send_command", fake_send_command)
    persisted_ports = []
    def fake_lease(device, operation, callback, **kwargs):
        target = kwargs["task_context"]["target"]
        if target.get("snapshot") == "port":
            return LocatorCLIResult(
                value=callback(), collected_at=ts._now_iso(),
                task_id="port-" + target["port"], status={},
            )
        return LocatorCLIResult(
            value=[], collected_at="", task_id="t-1",
            status={"status": "query_failed", "reason": "full_lldp_timeout"},
        )

    def fake_persist(**kwargs):
        persisted_ports.append(kwargs)
        return {"observation_key": kwargs["bridge_domain"], "generation": 1}

    monkeypatch.setattr(ts, "_run_cli_with_device_lease", fake_lease)
    monkeypatch.setattr(ts, "_persist_observation", fake_persist)

    result = ts._initial_result("192.168.11.111", "default", {}, ts.TraceLimits())
    expanded, phys_names, resolved = ts._expand_lag_member_ports_live(
        None, h3c_dev, "BAGG2", result=result,
        live_query=lambda command: fake_send_command(h3c_dev, command, force_refresh=True),
    )
    assert resolved is True
    assert phys_names == ["XGE1/3/0/4", "XGE2/3/0/4", "XGE3/3/0/4", "XGE4/3/0/4"]

    selected, _, _, status = ts._load_lldp_snapshot(
        h3c_dev,
        "BAGG2",
        cache=None,
        scope={},
        scope_hash="h",
        tenant_id="tenant-default",
        target_ip="192.168.11.111",
        network_domain_id="",
        site_id="",
        vrf="default",
        force_refresh=True,
        durable_run_id="",
        run_owner_id="",
        cancel_check=None,
        result=result,
        wait_seconds=10,
        expanded_member_ports=expanded,
        physical_member_names=phys_names,
    )
    assert status["source"] == "per_port_lldp_verbose"
    if mode == "empty":
        assert status["status"] == "parse_incomplete"
        assert selected == []
    else:
        assert status["status"] == "found"
        assert len(selected) == 1
        assert selected[0]["neighbor_name"] == "WXTJY-1F-SW4"
        assert selected[0]["neighbor_ip"] == "10.16.40.4"
    assert status["coverage"] == ("targeted" if mode == "all_found" else "partial")
    assert len([c for c in sent_commands if "lldp neighbor-information interface" in c]) == 4
    assert len(persisted_ports) == 4
    assert len({entry["bridge_domain"] for entry in persisted_ports}) == 4
    assert all(entry["bridge_domain"].startswith("lldp-port:") for entry in persisted_ports)
    assert all(entry["target"]["snapshot"] == "port" for entry in persisted_ports)
    assert sum(entry["coverage"] == "targeted" for entry in persisted_ports) == {"all_found": 4, "third_member_only": 1, "empty": 0}[mode]
    assert any(gap.startswith("neighbor_parse_incomplete:") for gap in result["coverage_gaps"]) == (mode != "all_found")
    # LAG expansion CLI must only have been sent ONCE, not duplicated inside _load_lldp_snapshot
    lag_cmds = [c for c in sent_commands if "link-aggregation verbose" in c]
    assert len(lag_cmds) == 1
    if mode != "empty":
        assert any("WXTJY-1F-SW4 (10.16.40.4)" in step for step in result["trace_steps"])

def test_lag_member_query_requires_coordinated_callback(monkeypatch):
    from services import ip_locator_trace_service as ts
    device = {"id": "sw", "platform": "hp_comware", "hostname": "sw"}
    monkeypatch.setattr(ts.legacy, "_send_command", lambda *a, **kw: pytest.fail("unleased SSH"))
    result = ts._initial_result("192.0.2.5", "default", {}, ts.TraceLimits())
    _, members, resolved = ts._expand_lag_member_ports_live(None, device, "BAGG2", result=result)
    assert members == []
    assert not resolved
    assert "neighbor_parse_incomplete:sw:lag_members" in result["coverage_gaps"]

@pytest.mark.parametrize("output, selected, unresolved", [
    ("GE1/0/1 S\nGE1/0/2 U\nGE1/0/3 Unknown", ["GE1/0/1"], ["GE1/0/3"]),
    ("GE1/0/1 Selected\nGE1/0/2 Unselected\nGE1/0/3 Up", ["GE1/0/1", "GE1/0/3"], []),
    ("Gi1/0/1(P) Gi1/0/2(D) Gi1/0/3(I) Gi1/0/4(Z)", ["Gi1/0/1"], ["Gi1/0/4"]),
    ("GE1/0/1 S\nGE1/0/1 U", [], ["GE1/0/1"]),
    ("GE1/0/1 S\nGigabitEthernet1/0/1 Unknown", [], ["GE1/0/1"]),
    ("GE1/0/1", [], ["GE1/0/1"]),
])
def test_lag_state_parser_only_accepts_positive_members(output, selected, unresolved):
    assert trace_service._parse_lag_member_states(output) == (selected, unresolved)


@pytest.mark.parametrize("force_refresh, pending, expected", [
    (True, False, False), (True, True, False),
    (False, True, False), (False, False, True),
])
def test_fact_reuse_policy_is_shared_by_cache_tiers(monkeypatch, force_refresh, pending, expected):
    monkeypatch.setattr(trace_service, "_pending_fact_invalidation", lambda *args: pending)
    assert trace_service._may_reuse_locator_facts(force_refresh, "scope", "192.0.2.5") is expected


def test_historical_lookup_fails_closed_without_authorized_device(monkeypatch):
    class Conn:
        def execute(self, *args):
            pytest.fail("empty authorized scope must not read history")
    assert trace_service._lookup_historical_last_seen(
        Conn(), "192.0.2.5", tenant_id="tenant-default", authorized_device_ids=[],
    ) is None


def test_historical_lookup_applies_scope_before_limit():
    class Conn:
        def execute(self, sql, params):
            assert "JOIN devices d ON d.id = o.source_device_id" in sql
            assert "o.tenant_id = ?" in sql and "d.tenant_id = ?" in sql
            assert "o.source_device_id IN (?)" in sql
            assert "LOWER(o.site_id)" in sql and "LOWER(d.site_id)" in sql
            assert params == ("192.0.2.5", "tenant-default", "tenant-default", "site1", "site1", "sw1")
            return self
        def fetchone(self):
            return None
    assert trace_service._lookup_historical_last_seen(
        Conn(), "192.0.2.5", tenant_id="tenant-default",
        site_id="site1", authorized_device_ids=["sw1"],
    ) is None
