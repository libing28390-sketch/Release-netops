from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from services import ip_locator_endpoint_evidence as endpoint_evidence
from services import ipam_discovery_service as discovery


NOW = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)
TARGET_IP = "192.0.2.44"
MAC_A = "00:11:22:33:44:55"
MAC_B = "00:11:22:33:44:66"


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return [deepcopy(row) for row in self._rows]


class _Connection:
    def __init__(self, statuses, mac_table_rows):
        self.statuses = statuses
        self.mac_table_rows = mac_table_rows
        self.closed = False

    def execute(self, sql, params=()):
        normalized_sql = " ".join(sql.lower().split())
        if "from device_collection_status" in normalized_sql:
            collector = params[0]
            device_ids = set(params[1:])
            return _Result([
                row for row in self.statuses
                if row["collector"] == collector and row["device_id"] in device_ids
            ])
        if "from mac_table" in normalized_sql:
            device_id, compact_mac = params
            return _Result([
                row for row in self.mac_table_rows
                if row["device_id"] == device_id
                and discovery._normalized_mac(row["mac_address"]).replace(":", "") == compact_mac
            ])
        raise AssertionError(f"Unexpected query in endpoint helper: {sql}")

    def close(self):
        self.closed = True


def _arp(
    observation_id="arp-a",
    *,
    source_device_id="gateway-a",
    tenant_id="tenant-a",
    site_id="site-a",
    mac=MAC_A,
    vlan="100",
    context="explicit_global",
    vrf_id="",
    observed_at=None,
    run_id="arp-run-a",
    **extra,
):
    return {
        "id": observation_id,
        "observation_id": observation_id,
        "source_type": "arp",
        "source_device_id": source_device_id,
        "source_device_name": source_device_id.upper(),
        "tenant_id": tenant_id,
        "site_id": site_id,
        "vrf_id": vrf_id,
        "vrf_context_status": context,
        "scope_status": "scope_pending" if context == "unknown" else "resolved",
        "ip": TARGET_IP,
        "mac": mac,
        "vlan": vlan,
        "interface_name": "Vlan-interface100",
        "source_observed_at": (observed_at or NOW).isoformat(),
        "timestamp_status": "valid",
        "projected_at": NOW.isoformat(),
        "source_run_id": run_id,
        "source_status": "success",
        "coverage_status": "complete",
        "coverage_complete": True,
        **extra,
    }


def _mac(
    *,
    device_id="access-a",
    tenant_id="tenant-a",
    site_id="site-a",
    mac=MAC_A,
    vlan="100",
    port="Gi1/0/7",
    observed_at=None,
):
    return {
        "id": f"mac-{device_id}-{port}-{vlan}",
        "source_type": "mac",
        "source_device_id": device_id,
        "source_device_name": device_id.upper(),
        "tenant_id": tenant_id,
        "site_id": site_id,
        "vrf_id": "",
        "vrf_context_status": "unknown",
        "scope_status": "scope_pending",
        "mac": mac,
        "vlan": vlan,
        "interface_name": port,
        "source_observed_at": (observed_at or NOW).isoformat(),
        "timestamp_status": "valid",
    }


def _status(device_id, collector, *, transport="snmp", status="success", source=None, **values):
    default_source = "arp_sweep" if collector == "arp" else "endpoint_fact_sweep"
    row = {
        "device_id": device_id,
        "collector": collector,
        "status": status,
        "transport": transport,
        "source": source or default_source,
        "last_success_at": NOW.isoformat(),
        "coverage_total": 1,
        "coverage_supported": 1,
        "metadata_json": {"collection_run_id": "arp-run-a"},
    }
    row.update(values)
    return row


def _install_mocks(monkeypatch, arp_rows, mac_rows, *, statuses=None, raw_mac_rows=None):
    if statuses is None:
        statuses = []
        for row in arp_rows:
            statuses.append(_status(
                row["source_device_id"], "arp",
                metadata_json={"collection_run_id": row["source_run_id"]},
            ))
        for device_id in sorted({row["source_device_id"] for row in mac_rows}):
            statuses.append(_status(device_id, "mac_table"))
    if raw_mac_rows is None:
        raw_mac_rows = [
            {
                "device_id": row["source_device_id"],
                "mac_address": row["mac"].replace(":", ""),
                "interface_name": row["interface_name"],
                "vlan_id": row["vlan"],
                "last_updated": row["source_observed_at"],
            }
            for row in mac_rows
        ]
    connection = _Connection(statuses, raw_mac_rows)
    loaded_inputs = []

    def load_observations(_conn, *, ip=None, mac=None, **_kwargs):
        if ip is not None:
            return [deepcopy(row) for row in arp_rows if row["ip"] == ip]
        if mac is not None:
            return [
                deepcopy(row) for row in mac_rows
                if discovery._normalized_mac(row["mac"]) == mac
            ]
        raise AssertionError("Endpoint helper must scope projected observations by exact IP or MAC")

    def decorate(rows, _conn, _now, _ipam_by_scope_override=None):
        loaded_inputs.extend(deepcopy(rows))
        all_mac_rows = [row for row in rows if row["source_type"] == "mac"]
        decorated = []
        for row in rows:
            if row["source_type"] != "arp":
                continue
            context = row["vrf_context_status"]
            candidates = [
                candidate for candidate in all_mac_rows
                if discovery._normalized_mac(candidate["mac"]) == discovery._normalized_mac(row["mac"])
                and discovery._normalize_vlan_number(candidate["vlan"]) == discovery._normalize_vlan_number(row["vlan"])
                and candidate["tenant_id"] == row["tenant_id"]
                and candidate["site_id"] == row["site_id"]
                and (context != "unknown" or candidate["source_device_id"] == row["source_device_id"])
            ]
            ports = {(candidate["source_device_id"], candidate["interface_name"]) for candidate in candidates}
            selected = candidates[0] if len(ports) == 1 and candidates else None
            basis = ""
            if selected:
                basis = "same_device_vlan_mac_access" if context == "unknown" else "scoped_vlan_mac_access"
            item = {
                "id": row["id"],
                "observation_id": row["id"],
                "source_type": "arp",
                "ip": row["ip"],
                "mac": discovery._normalized_mac(row["mac"]) or None,
                "vlan": str(row["vlan"] or ""),
                "tenant_id": row["tenant_id"],
                "site_id": row["site_id"],
                "vrf_id": row["vrf_id"],
                "vrf_context_status": context,
                "source_vrf_context_status": context,
                "scope_status": row["scope_status"],
                "source_device_id": row["source_device_id"],
                "source_device_name": row["source_device_name"],
                "source_interface_name": row.get("interface_name", ""),
                "observed_at": row["source_observed_at"],
                "mac_observed_at": selected["source_observed_at"] if selected else "",
                "evidence_status": row.get("_evidence_status", "recent"),
                "timestamp_status": row.get("_decorated_timestamp_status", "valid"),
                "switch_location_status": "matched" if selected and not row.get("_without_location") else "pending",
                "switch_location_basis": basis if not row.get("_without_location") else "",
                "switch_id": selected["source_device_id"] if selected and not row.get("_without_location") else "",
                "switch_name": selected["source_device_name"] if selected and not row.get("_without_location") else "",
                "switch_port": selected["interface_name"] if selected and not row.get("_without_location") else "",
            }
            decorated.append(item)
        return decorated

    monkeypatch.setattr(endpoint_evidence, "get_db_connection", lambda: connection)
    monkeypatch.setattr(discovery, "_load_projected_observations", load_observations)
    monkeypatch.setattr(discovery, "_decorate_observations", decorate)
    monkeypatch.setattr(discovery, "_utc_now", lambda: NOW)
    return connection, loaded_inputs


def _find(**kwargs):
    return endpoint_evidence.find_endpoint_evidence(
        TARGET_IP,
        tenant_id="tenant-a",
        authorized_device_ids={"gateway-a", "gateway-b", "access-a", "access-b"},
        **kwargs,
    )


def test_returns_unique_current_snmp_location_and_sanitized_arp_evidence(monkeypatch):
    arp_rows = [_arp()]
    mac_rows = [_mac()]
    connection, decorated_inputs = _install_mocks(monkeypatch, arp_rows, mac_rows)

    result = _find(site_id="site-a")

    assert result == {
        "location": {
            "device_id": "access-a",
            "device": "ACCESS-A",
            "port": "Gi1/0/7",
            "mac": MAC_A,
            "vlan": "100",
        },
        "arp_evidence": [{
            "observation_id": "arp-a",
            "device_id": "gateway-a",
            "source_device_id": "gateway-a",
            "device": "GATEWAY-A",
            "source_device": "GATEWAY-A",
            "interface": "Vlan-interface100",
            "ip": TARGET_IP,
            "mac": MAC_A,
            "vlan": "100",
            "site_id": "site-a",
            "vrf_id": "",
            "vrf_context_status": "explicit_global",
            "observed_at": NOW.isoformat(),
        }],
        "evidence_collected_at": NOW.isoformat(),
        "vrf_context_status": "explicit_global",
        "source_device_ids": ["gateway-a"],
    }
    assert [row["source_type"] for row in decorated_inputs] == ["arp", "mac"]
    assert connection.closed


def test_authorization_scope_filters_arp_and_mac_before_decoration(monkeypatch):
    arp_rows = [
        _arp(),
        _arp("other-tenant", source_device_id="gateway-b", tenant_id="tenant-b"),
        _arp("other-site", source_device_id="gateway-b", site_id="site-b"),
        _arp("unauthorized-device", source_device_id="outside", mac=MAC_B),
    ]
    mac_rows = [
        _mac(),
        _mac(device_id="outside", mac=MAC_A, port="Gi1/0/8"),
        _mac(device_id="access-b", tenant_id="tenant-b", mac=MAC_A, port="Gi1/0/9"),
        _mac(device_id="access-b", site_id="site-b", mac=MAC_A, port="Gi1/0/10"),
    ]
    _, decorated_inputs = _install_mocks(monkeypatch, arp_rows, mac_rows)

    result = _find(site_id="site-a")

    assert result is not None
    assert {row["source_device_id"] for row in decorated_inputs} == {"gateway-a", "access-a"}
    assert result["source_device_ids"] == ["gateway-a"]
    assert result["location"]["device_id"] == "access-a"


def test_final_switch_must_be_in_the_authorized_device_set(monkeypatch):
    _install_mocks(monkeypatch, [_arp()], [_mac(device_id="outside")])

    assert _find(site_id="site-a") is None


def test_source_candidates_include_stale_rows_but_obey_authorization_and_start(monkeypatch):
    stale = _arp(observed_at=NOW - timedelta(hours=5))
    other_site = _arp("arp-b", source_device_id="gateway-b", site_id="site-b")
    connection, _ = _install_mocks(monkeypatch, [stale, other_site], [])

    all_sources = endpoint_evidence.endpoint_source_device_ids(
        TARGET_IP,
        tenant_id="tenant-a",
        authorized_device_ids={"gateway-a", "gateway-b"},
    )
    selected_source = endpoint_evidence.endpoint_source_device_ids(
        TARGET_IP,
        tenant_id="tenant-a",
        authorized_device_ids={"gateway-a", "gateway-b"},
        start_device_id="gateway-a",
    )

    assert all_sources == ["gateway-a", "gateway-b"]
    assert selected_source == ["gateway-a"]
    assert connection.closed


def test_start_device_is_restricted_to_that_authorized_arp_source(monkeypatch):
    arp_rows = [_arp(), _arp("arp-b", source_device_id="gateway-b", run_id="arp-run-a")]
    mac_rows = [_mac()]
    _install_mocks(monkeypatch, arp_rows, mac_rows)

    result = endpoint_evidence.find_endpoint_evidence(
        TARGET_IP,
        tenant_id="tenant-a",
        site_id="site-a",
        authorized_device_ids={"gateway-a", "gateway-b", "access-a"},
        start_device_id="gateway-b",
    )

    assert result is not None
    assert result["source_device_ids"] == ["gateway-b"]


def test_unknown_vrf_is_reported_and_only_same_device_location_is_accepted(monkeypatch):
    arp_rows = [_arp(context="unknown", run_id="arp-run-a")]
    mac_rows = [_mac(device_id="gateway-a")]
    _install_mocks(monkeypatch, arp_rows, mac_rows)

    result = _find(site_id="site-a", vrf="default")

    assert result is not None
    assert result["location"]["device_id"] == "gateway-a"
    assert result["vrf_context_status"] == "unknown"

    arp_rows = [_arp(context="unknown", run_id="arp-run-a")]
    mac_rows = [_mac(device_id="access-a")]
    _install_mocks(monkeypatch, arp_rows, mac_rows)
    assert _find(site_id="site-a", vrf="default") is None


def test_explicit_vrf_requires_known_matching_source_context(monkeypatch):
    arp_rows = [_arp(context="explicit_vrf", vrf_id="blue", run_id="arp-run-a")]
    mac_rows = [_mac()]
    _install_mocks(monkeypatch, arp_rows, mac_rows)

    assert _find(site_id="site-a", vrf="blue") is not None
    assert _find(site_id="site-a", vrf="red") is None

    unknown_rows = [_arp(context="unknown", run_id="arp-run-a")]
    _install_mocks(monkeypatch, unknown_rows, [_mac(device_id="gateway-a")])
    assert _find(site_id="site-a", vrf="blue") is None


def test_expired_arp_is_not_a_location_but_stays_a_refresh_candidate(monkeypatch):
    stale = _arp(observed_at=NOW - timedelta(hours=5))
    connection, _ = _install_mocks(monkeypatch, [stale], [_mac()])

    assert _find(site_id="site-a") is None
    assert endpoint_evidence.endpoint_source_device_ids(
        TARGET_IP,
        tenant_id="tenant-a",
        site_id="site-a",
        authorized_device_ids={"gateway-a"},
    ) == ["gateway-a"]
    assert connection.closed


def test_evidence_collected_at_uses_the_oldest_required_observation(monkeypatch):
    arp_rows = [_arp()]
    mac_rows = [_mac(observed_at=NOW - timedelta(seconds=30))]
    _install_mocks(monkeypatch, arp_rows, mac_rows)

    result = _find(site_id="site-a")

    assert result is not None
    assert result["evidence_collected_at"] == (NOW - timedelta(seconds=30)).isoformat()


@pytest.mark.parametrize("ambiguity", ["multiple_macs", "multiple_vlans", "multiple_sites", "multiple_ports", "unlocated_candidate"])
def test_ambiguous_or_unlocated_recent_arp_candidates_are_rejected(monkeypatch, ambiguity):
    first = _arp()
    first_mac = _mac()
    site_id = "site-a"
    requested_site = "site-a"
    extra_macs = []

    if ambiguity == "multiple_macs":
        second = _arp("arp-b", source_device_id="gateway-b", mac=MAC_B)
        extra_macs = [_mac(mac=MAC_B, port="Gi1/0/8")]
    elif ambiguity == "multiple_vlans":
        second = _arp("arp-b", source_device_id="gateway-b", vlan="200")
        extra_macs = [_mac(vlan="200", port="Gi1/0/8")]
    elif ambiguity == "multiple_sites":
        second = _arp("arp-b", source_device_id="gateway-b", site_id="site-b")
        extra_macs = [_mac(device_id="access-b", site_id="site-b", port="Gi1/0/8")]
        site_id = "site-b"
        requested_site = ""
    elif ambiguity == "multiple_ports":
        second = _arp("arp-b", source_device_id="gateway-b")
        extra_macs = [_mac(device_id="access-b", port="Gi1/0/8")]
    else:
        second = _arp("arp-b", source_device_id="gateway-b", _without_location=True)

    first["site_id"] = site_id
    second["site_id"] = site_id if ambiguity != "multiple_sites" else "site-b"
    mac_rows = [first_mac, *extra_macs]
    if ambiguity == "multiple_sites":
        first["site_id"] = "site-a"
        first_mac["site_id"] = "site-a"
        second["site_id"] = "site-b"
        extra_macs[0]["site_id"] = "site-b"

    _install_mocks(monkeypatch, [first, second], mac_rows)

    assert _find(site_id=requested_site) is None


@pytest.mark.parametrize("collector", ["arp", "mac_table"])
def test_non_snmp_collection_transport_cannot_prove_location(monkeypatch, collector):
    arp_rows = [_arp()]
    mac_rows = [_mac()]
    statuses = [
        _status("gateway-a", "arp", metadata_json={"collection_run_id": "arp-run-a"}),
        _status("access-a", "mac_table"),
    ]
    for status in statuses:
        if status["collector"] == collector:
            status["transport"] = "ssh"
    _install_mocks(monkeypatch, arp_rows, mac_rows, statuses=statuses)

    assert _find(site_id="site-a") is None


def test_fdb_projection_must_still_exist_in_current_raw_table(monkeypatch):
    arp_rows = [_arp()]
    mac_rows = [_mac()]
    stale_raw = [{
        "device_id": "access-a",
        "mac_address": MAC_A,
        "interface_name": "Gi1/0/7",
        "vlan_id": "100",
        "last_updated": (NOW - timedelta(minutes=10)).isoformat(),
    }]
    _install_mocks(monkeypatch, arp_rows, mac_rows, raw_mac_rows=stale_raw)

    assert _find(site_id="site-a") is None


def test_network_domain_and_missing_authorization_fail_closed(monkeypatch):
    connection, _ = _install_mocks(monkeypatch, [_arp()], [_mac()])

    assert endpoint_evidence.find_endpoint_evidence(
        TARGET_IP,
        tenant_id="tenant-a",
        authorized_device_ids={"gateway-a", "access-a"},
        network_domain_id="domain-a",
    ) is None
    assert endpoint_evidence.endpoint_source_device_ids(
        TARGET_IP,
        tenant_id="tenant-a",
        authorized_device_ids={"gateway-a"},
        network_domain_id="domain-a",
    ) == []
    assert endpoint_evidence.find_endpoint_evidence(
        TARGET_IP, tenant_id="tenant-a", authorized_device_ids=None,
    ) is None
    assert not connection.closed


def test_caller_connection_is_reused_and_not_closed(monkeypatch):
    arp_rows = [_arp()]
    mac_rows = [_mac()]
    connection, _ = _install_mocks(monkeypatch, arp_rows, mac_rows)
    monkeypatch.setattr(endpoint_evidence, "get_db_connection", lambda: pytest.fail("external connection expected"))

    result = endpoint_evidence.find_endpoint_evidence(
        TARGET_IP,
        tenant_id="tenant-a",
        site_id="site-a",
        authorized_device_ids={"gateway-a", "access-a"},
        conn=connection,
    )

    assert result is not None
    assert not connection.closed
