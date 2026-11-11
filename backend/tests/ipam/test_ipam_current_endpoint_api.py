from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from database import get_db_connection
from schemas.schemas import IPAMDiscoveryMACCalibrationRequest, IPAMDiscoveryRegistrationRequest
from services.ipam_address_space_service import create_address_space
from services.ipam_current_endpoint_observation_service import (
    begin_current_endpoint_collection,
    finish_current_endpoint_collection,
)
from services.ipam_current_fdb_observation_service import (
    begin_current_fdb_collection,
    finish_current_fdb_collection,
)
from services.ipam_routing_context_service import create_device_routing_context
from services.ipam_service import create_address, create_subnet


_FORBIDDEN_SQL_TOKENS = (
    "ipam_discovery_observations",
    "ipam_discovery_snapshots",
    "ipam_discovery_scope_assertions",
)


class _HistoryGuardConnection:
    def __init__(self, connection):
        self._connection = connection
        self.statements: list[str] = []

    def execute(self, sql, *args, **kwargs):
        statement = str(sql)
        lowered = statement.casefold()
        self.statements.append(statement)
        forbidden = [token for token in _FORBIDDEN_SQL_TOKENS if token in lowered]
        if forbidden:
            raise AssertionError(f"current endpoint API accessed forbidden SQL table(s): {forbidden}")
        return self._connection.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def __enter__(self):
        self._connection.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        return self._connection.__exit__(exc_type, exc, traceback)


def _seed_device(device_id: str, hostname: str, site_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute("INSERT INTO tenants (id, name) VALUES ('tenant-default', 'Default') ON CONFLICT(id) DO NOTHING")
        conn.execute(
            """INSERT INTO sites (id, site_code, site_name, tenant_id)
               VALUES (?, ?, ?, 'tenant-default') ON CONFLICT(id) DO NOTHING""",
            (site_id, site_id.upper(), f"Site {site_id}"),
        )
        conn.execute(
            """INSERT INTO devices (id, hostname, tenant_id, site_id, status)
               VALUES (?, ?, 'tenant-default', ?, 'online')""",
            (device_id, hostname, site_id),
        )
        conn.commit()


def _publish_arp(
    *, device_id: str, context_type: str, local_context_key: str,
    address: str, mac: str, status: str, observed_at: datetime,
) -> int:
    observed = observed_at.astimezone(timezone.utc).isoformat()
    context_source = "cli"
    with get_db_connection() as conn:
        generation = begin_current_endpoint_collection(
            conn,
            device_id=device_id,
            context_source=context_source,
            context_type=context_type,
            local_context_key=local_context_key,
            attempted_at=observed,
            run_id=f"run-{device_id}-{observed_at.timestamp()} ",
        )
        finish_current_endpoint_collection(
            conn,
            device_id=device_id,
            context_source=context_source,
            context_type=context_type,
            local_context_key=local_context_key,
            generation=generation,
            status=status,
            attempted_at=observed,
            completed_at=observed,
            run_id=f"run-{device_id}-{observed_at.timestamp()}",
            observations=[{
                "ip_address": address,
                "mac_address": mac,
                "interface_name": "GigabitEthernet1/0/1",
                "context_source": context_source,
                "context_type": context_type,
                "local_context_key": local_context_key,
                "local_context_name": local_context_key,
                "vlan_id": 10,
            }],
        )
        conn.commit()
    return generation


def _publish_fdb(
    *, device_id: str, context_type: str, local_context_key: str,
    mac: str, status: str, observed_at: datetime,
    interfaces: tuple[str, ...] = ("Port-channel1",),
) -> int:
    observed = observed_at.astimezone(timezone.utc).isoformat()
    with get_db_connection() as conn:
        generation = begin_current_fdb_collection(
            conn,
            device_id=device_id,
            context_source="snmp",
            context_type=context_type,
            local_context_key=local_context_key,
            attempted_at=observed,
            run_id=f"fdb-{device_id}-{observed_at.timestamp()}",
        )
        conn.commit()
    with get_db_connection() as conn:
        finish_current_fdb_collection(
            conn,
            device_id=device_id,
            context_source="snmp",
            context_type=context_type,
            local_context_key=local_context_key,
            generation=generation,
            status=status,
            attempted_at=observed,
            completed_at=observed,
            run_id=f"fdb-{device_id}-{observed_at.timestamp()}",
            observations=[{
                "mac_address": mac,
                "interface_name": interface_name,
                "vlan_id": 10,
                "entry_type": "dynamic",
            } for interface_name in interfaces],
        )
        conn.commit()
    return generation


def _seed_current_endpoint_fixture():
    site_id = "current-endpoint-site"
    _seed_device("current-endpoint-mapped", "SW-CURRENT-MAPPED", site_id)
    _seed_device("current-endpoint-unmapped", "SW-CURRENT-UNMAPPED", site_id)
    address_space = create_address_space(
        name="Current Endpoint API Global",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    other_address_space = create_address_space(
        name="Current Endpoint API Other Global",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    drift_address_space = create_address_space(
        name="Current Endpoint API Drift Global",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    create_device_routing_context(
        device_id="current-endpoint-mapped",
        context_source="cli",
        context_type="global",
        local_context_key="Global",
        local_context_name="Global",
        address_space_id=address_space["id"],
        security_tenant_id="tenant-default",
    )
    prefix = create_subnet(
        prefix="192.0.2.0/24",
        tenant_id="tenant-default",
        site_id=site_id,
        address_space_id=address_space["id"],
        network_type="server",
    )
    registration_prefix = create_subnet(
        prefix="198.51.100.0/24",
        tenant_id="tenant-default",
        site_id=site_id,
        address_space_id=address_space["id"],
        network_type="server",
    )
    other_space_prefix = create_subnet(
        prefix="192.0.2.0/24",
        tenant_id="tenant-default",
        site_id=site_id,
        address_space_id=other_address_space["id"],
        network_type="server",
    )
    legacy_prefix_id = "current-endpoint-legacy-prefix"
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO prefixes (
                   id, prefix, prefix_cidr, tenant_id, site_id, status, name,
                   address_space_id, vrf_id, is_active, ip_version, prefix_len
               ) VALUES (?, '198.51.100.0/25', '198.51.100.0/25', 'tenant-default', ?, 'active',
                         'Legacy Current Endpoint Prefix', NULL, NULL, 1, 4, 25)""",
            (legacy_prefix_id, site_id),
        )
        conn.commit()
    ipam_address = create_address(
        prefix["id"],
        address="192.0.2.10",
        mac_address="00:11:22:33:44:66",
        hostname="registered-host",
        status="active",
    )
    observed_at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=20)
    mapped_generation = _publish_arp(
        device_id="current-endpoint-mapped",
        context_type="unknown",
        local_context_key="Global",
        address="192.0.2.10",
        mac="00:11:22:33:44:55",
        status="scope_unknown",
        observed_at=observed_at,
    )
    unmapped_generation = _publish_arp(
        device_id="current-endpoint-unmapped",
        context_type="unknown",
        local_context_key="unmapped-vrf-key",
        address="198.51.100.25",
        mac="00:11:22:33:44:77",
        status="scope_unknown",
        observed_at=observed_at,
    )
    return {
        "address_space_id": address_space["id"],
        "other_address_space_id": other_address_space["id"],
        "drift_address_space_id": drift_address_space["id"],
        "other_space_prefix_id": other_space_prefix["id"],
        "prefix_id": prefix["id"],
        "registration_prefix_id": registration_prefix["id"],
        "legacy_prefix_id": legacy_prefix_id,
        "ipam_address_id": ipam_address["id"],
        "observed_at": observed_at.isoformat(),
        "mapped_generation": mapped_generation,
        "unmapped_generation": unmapped_generation,
    }


def _administrator() -> dict:
    return {
        "id": "current-endpoint-reviewer",
        "username": "current-endpoint-reviewer",
        "role": "Administrator",
        "tenant_id": "tenant-default",
        "request_id": "current-endpoint-api-test",
    }


def test_current_endpoint_routes_use_only_current_observations_and_explicit_writes(isolated_db, monkeypatch):
    del isolated_db
    from api import ipam as api
    from services import ipam_discovery_service as discovery

    seeded = _seed_current_endpoint_fixture()
    original_connection = get_db_connection
    guarded_connections: list[_HistoryGuardConnection] = []

    def guarded_connection():
        guarded = _HistoryGuardConnection(original_connection())
        guarded_connections.append(guarded)
        return guarded

    monkeypatch.setattr(api, "get_db_connection", guarded_connection)
    monkeypatch.setattr(discovery, "get_db_connection", guarded_connection)
    user = _administrator()

    listed = api.api_list_discovered_endpoints(
        site_id="", vrf_id="", device_id="", q="", kind="all",
        evidence_status="", registration_status="", network_scope="all",
        endpoint_class="all", page=1, page_size=50, user=user,
    )
    assert listed["total"] == 2
    mapped = next(item for item in listed["items"] if item["source_device_id"] == "current-endpoint-mapped")
    unmapped = next(item for item in listed["items"] if item["source_device_id"] == "current-endpoint-unmapped")
    assert mapped["id"] == mapped["observation_id"]
    assert mapped["scope_status"] == "resolved"
    assert mapped["address_space_id"] == seeded["address_space_id"]
    assert mapped["source_vrf_context_status"] == "unknown"
    assert mapped["generation"] == seeded["mapped_generation"]
    assert unmapped["scope_status"] == "scope_pending"
    assert not unmapped["address_space_id"]

    raw_context_ip = "203.0.113.40"
    raw_context_seen = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=12)
    for context_type, mac in (
        ("unknown", "00:11:22:33:44:40"),
        ("vrf", "00:11:22:33:44:41"),
    ):
        _publish_arp(
            device_id="current-endpoint-unmapped",
            context_type=context_type,
            local_context_key="same-unmapped-key",
            address=raw_context_ip,
            mac=mac,
            status="scope_unknown" if context_type == "unknown" else "complete",
            observed_at=raw_context_seen,
        )
    raw_context_list = api.api_list_discovered_endpoints(
        site_id="", vrf_id="", device_id="current-endpoint-unmapped", q="", kind="all",
        evidence_status="", registration_status="", network_scope="all",
        endpoint_class="all", page=1, page_size=50, user=user,
    )
    raw_context_siblings = [item for item in raw_context_list["items"] if item["ip"] == raw_context_ip]
    assert len(raw_context_siblings) == 2
    assert {item["context_type"] for item in raw_context_siblings} == {"unknown", "vrf"}
    assert all(item["scope_status"] == "scope_pending" for item in raw_context_siblings)
    assert all(item["ip_mac_conflict"] is False for item in raw_context_siblings)

    repeated_list = api.api_list_discovered_endpoints(
        site_id="", vrf_id="", device_id="", q="", kind="all",
        evidence_status="", registration_status="", network_scope="all",
        endpoint_class="all", page=1, page_size=50, user=user,
    )
    repeated_mapped = next(item for item in repeated_list["items"] if item["source_device_id"] == "current-endpoint-mapped")
    assert repeated_mapped["id"] == mapped["id"]
    detail = api.api_get_discovered_endpoint(mapped["id"], user=user)
    assert detail["source_evidence_count"] == 1
    assert detail["observations"][0]["source_version"] == str(seeded["mapped_generation"])

    fdb_generation = _publish_fdb(
        device_id="current-endpoint-unmapped",
        context_type="unknown",
        local_context_key="raw-fdb-context",
        mac="00:11:22:33:44:99",
        status="scope_unknown",
        observed_at=datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=10),
        interfaces=("Port-channel1", "GigabitEthernet1/0/1"),
    )
    fdb_list = api.api_list_discovered_endpoints(
        site_id="", vrf_id="", device_id="", q="", kind="mac",
        evidence_status="", registration_status="", network_scope="all",
        endpoint_class="all", page=1, page_size=50, user=user,
    )
    assert fdb_list["total"] == 2
    fdb_item = fdb_list["items"][0]
    assert all(item["path_ambiguity"] is True for item in fdb_list["items"])
    pending_fdb_list = api.api_list_discovered_endpoints(
        site_id="", vrf_id="", device_id="", q="", kind="mac",
        evidence_status="scope_pending", registration_status="", network_scope="all",
        endpoint_class="all", page=1, page_size=50, user=user,
    )
    assert pending_fdb_list["total"] == 2
    assert fdb_item["source_type"] == "mac"
    assert fdb_item["observation_source"] == "fdb"
    assert fdb_item["ip"] is None
    assert fdb_item["mac"] == "00:11:22:33:44:99"
    assert fdb_item["scope_status"] == "scope_pending"
    assert fdb_item["registration_status"] == "not_applicable"
    assert fdb_item["generation"] == fdb_generation
    fdb_detail = api.api_get_discovered_endpoint(fdb_item["id"], user=user)
    assert fdb_detail["source_evidence_count"] == 1
    assert fdb_detail["observations"][0]["source_type"] == "fdb"
    assert fdb_detail["observations"][0]["ip"] is None

    with pytest.raises(HTTPException) as fdb_registration:
        api.api_register_discovered_observation(
            IPAMDiscoveryRegistrationRequest(
                observation_id=fdb_item["id"],
                subnet_id=seeded["registration_prefix_id"],
                expected_observed_at=fdb_item["observed_at"],
                confirmed_scope=True,
            ),
            user=user,
        )
    assert fdb_registration.value.status_code in {404, 409}

    with pytest.raises(HTTPException) as cross_space_registration:
        api.api_register_discovered_observation(
            IPAMDiscoveryRegistrationRequest(
                observation_id=mapped["id"],
                subnet_id=seeded["other_space_prefix_id"],
                expected_observed_at=mapped["observed_at"],
                confirmed_scope=True,
            ),
            user=user,
        )
    assert cross_space_registration.value.status_code == 409

    with pytest.raises(HTTPException) as legacy_prefix_registration:
        api.api_register_discovered_observation(
            IPAMDiscoveryRegistrationRequest(
                observation_id=unmapped["id"],
                subnet_id=seeded["legacy_prefix_id"],
                expected_observed_at=unmapped["observed_at"],
                confirmed_scope=True,
            ),
            user=user,
        )
    assert legacy_prefix_registration.value.status_code == 409

    from services import ipam_address_space_service
    original_lock_ipam_scope = ipam_address_space_service.lock_ipam_scope

    def mutate_prefix_during_register(conn, **scope):
        original_lock_ipam_scope(conn, **scope)
        with original_connection() as external_conn:
            external_conn.execute(
                "UPDATE prefixes SET address_space_id = ? WHERE id = ?",
                (seeded["other_address_space_id"], seeded["registration_prefix_id"]),
            )
            external_conn.commit()

    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(ipam_address_space_service, "lock_ipam_scope", mutate_prefix_during_register)
        with pytest.raises(HTTPException) as registration_scope_drift:
            api.api_register_discovered_observation(
                IPAMDiscoveryRegistrationRequest(
                    observation_id=unmapped["id"],
                    subnet_id=seeded["registration_prefix_id"],
                    expected_observed_at=unmapped["observed_at"],
                    confirmed_scope=True,
                ),
                user=user,
            )
    assert registration_scope_drift.value.status_code == 409
    with original_connection() as conn:
        conn.execute(
            "UPDATE prefixes SET address_space_id = ? WHERE id = ?",
            (seeded["address_space_id"], seeded["registration_prefix_id"]),
        )
        conn.commit()

    registered = api.api_register_discovered_observation(
        IPAMDiscoveryRegistrationRequest(
            observation_id=unmapped["id"],
            subnet_id=seeded["registration_prefix_id"],
            expected_observed_at=unmapped["observed_at"],
            confirmed_scope=True,
        ),
        user=user,
    )
    assert registered["created"] is True
    assert registered["assertion_id"] == ""
    with original_connection() as conn:
        address = conn.execute(
            "SELECT * FROM ip_addresses WHERE id = ?", (registered["ipam_address_id"],)
        ).fetchone()
        assert address["source_type"] == "ipam_current_endpoint"
        assert address["source_ref"] == unmapped["id"]
        audit = conn.execute(
            "SELECT details_json FROM audit_events WHERE target_id = ? AND event_type = 'ipam.discovery.register'",
            (registered["ipam_address_id"],),
        ).fetchone()
        assert audit

    with pytest.raises(HTTPException) as stale_registration:
        api.api_register_discovered_observation(
            IPAMDiscoveryRegistrationRequest(
                observation_id=unmapped["id"],
                subnet_id=seeded["registration_prefix_id"],
                expected_observed_at=(datetime.fromisoformat(unmapped["observed_at"]) - timedelta(seconds=1)).isoformat(),
                confirmed_scope=True,
            ),
            user=user,
        )
    assert stale_registration.value.status_code == 409

    calibrated = api.api_calibrate_discovered_mac(
        IPAMDiscoveryMACCalibrationRequest(
            observation_id=mapped["id"],
            ipam_address_id=seeded["ipam_address_id"],
            expected_observed_at=mapped["observed_at"],
            expected_mac_address="00:11:22:33:44:66",
            confirmed=True,
        ),
        user=user,
    )
    assert calibrated["mac"] == "00:11:22:33:44:55"
    with original_connection() as conn:
        address = conn.execute(
            "SELECT mac_address, revision FROM ip_addresses WHERE id = ?", (seeded["ipam_address_id"],)
        ).fetchone()
        assert address["mac_address"] == "00:11:22:33:44:55"
        assert int(address["revision"]) == 2
        audit = conn.execute(
            "SELECT 1 FROM audit_events WHERE target_id = ? AND event_type = 'ipam.discovery.mac_calibrate'",
            (seeded["ipam_address_id"],),
        ).fetchone()
        assert audit

    with pytest.raises(HTTPException) as stale_calibration:
        api.api_calibrate_discovered_mac(
            IPAMDiscoveryMACCalibrationRequest(
                observation_id=mapped["id"],
                ipam_address_id=seeded["ipam_address_id"],
                expected_observed_at=(datetime.fromisoformat(mapped["observed_at"]) - timedelta(seconds=1)).isoformat(),
                expected_mac_address="00:11:22:33:44:55",
                confirmed=True,
            ),
            user=user,
        )
    assert stale_calibration.value.status_code == 409

    def mutate_prefix_during_calibration(conn, **scope):
        original_lock_ipam_scope(conn, **scope)
        with original_connection() as external_conn:
            external_conn.execute(
                "UPDATE prefixes SET address_space_id = ? WHERE id = ?",
                (seeded["drift_address_space_id"], seeded["prefix_id"]),
            )
            external_conn.commit()

    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(ipam_address_space_service, "lock_ipam_scope", mutate_prefix_during_calibration)
        with pytest.raises(HTTPException) as calibration_scope_drift:
            api.api_calibrate_discovered_mac(
                IPAMDiscoveryMACCalibrationRequest(
                    observation_id=mapped["id"],
                    ipam_address_id=seeded["ipam_address_id"],
                    expected_observed_at=mapped["observed_at"],
                    expected_mac_address="00:11:22:33:44:55",
                    confirmed=True,
                ),
                user=user,
            )
    assert calibration_scope_drift.value.status_code == 409
    with original_connection() as conn:
        conn.execute(
            "UPDATE prefixes SET address_space_id = ? WHERE id = ?",
            (seeded["address_space_id"], seeded["prefix_id"]),
        )
        conn.commit()

    with pytest.raises(HTTPException) as unresolved_calibration:
        api.api_calibrate_discovered_mac(
            IPAMDiscoveryMACCalibrationRequest(
                observation_id=unmapped["id"],
                ipam_address_id=registered["ipam_address_id"],
                expected_observed_at=unmapped["observed_at"],
                expected_mac_address="00:11:22:33:44:77",
                confirmed=True,
            ),
            user=user,
        )
    assert unresolved_calibration.value.status_code == 409

    _seed_device("current-endpoint-duplicate", "SW-CURRENT-DUPLICATE", "current-endpoint-site")
    create_device_routing_context(
        device_id="current-endpoint-duplicate",
        context_source="cli",
        context_type="global",
        local_context_key="Global",
        local_context_name="Global",
        address_space_id=seeded["address_space_id"],
        security_tenant_id="tenant-default",
    )
    _publish_arp(
        device_id="current-endpoint-duplicate",
        context_type="global",
        local_context_key="Global",
        address="192.0.2.10",
        mac="00:11:22:33:44:88",
        status="complete",
        observed_at=datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=10),
    )
    duplicate_list = api.api_list_discovered_endpoints(
        site_id="", vrf_id="", device_id="", q="", kind="all",
        evidence_status="", registration_status="", network_scope="all",
        endpoint_class="all", page=1, page_size=50, user=user,
    )
    duplicate_observation = next(
        item for item in duplicate_list["items"]
        if item["source_device_id"] == "current-endpoint-duplicate"
    )
    with pytest.raises(HTTPException) as ambiguous_calibration:
        api.api_calibrate_discovered_mac(
            IPAMDiscoveryMACCalibrationRequest(
                observation_id=duplicate_observation["id"],
                ipam_address_id=seeded["ipam_address_id"],
                expected_observed_at=duplicate_observation["observed_at"],
                expected_mac_address="00:11:22:33:44:55",
                confirmed=True,
            ),
            user=user,
        )
    assert ambiguous_calibration.value.status_code == 409

    assert guarded_connections
    assert all(
        not any(token in statement.casefold() for token in _FORBIDDEN_SQL_TOKENS)
        for connection in guarded_connections
        for statement in connection.statements
    )


def test_current_fdb_path_keeps_lag_member_trunk_and_virtual_mac_distinct(isolated_db):
    del isolated_db
    from core.interface_utils import normalize_interface_name
    from services.ipam_discovery_service import _current_fdb_endpoint_projection

    _seed_current_endpoint_fixture()
    device_id = 'current-endpoint-unmapped'
    neighbor_id = 'current-endpoint-neighbor'
    _seed_device(neighbor_id, 'SW-CURRENT-NEIGHBOR', 'current-endpoint-site')
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO interfaces
                   (id, device_id, interface_name, interface_type, switchport_mode)
               VALUES ('fdb-lag-parent', ?, 'Port-channel1', 'lag', 'trunk')""",
            (device_id,),
        )
        conn.execute(
            """INSERT INTO interfaces
                   (id, device_id, interface_name, interface_type, switchport_mode, parent_interface_id)
               VALUES ('fdb-lag-member', ?, 'GigabitEthernet1/0/1', 'physical', 'trunk', 'fdb-lag-parent')""",
            (device_id,),
        )
        conn.execute(
            """INSERT INTO interfaces
                   (id, device_id, interface_name, interface_type, switchport_mode)
               VALUES ('fdb-trunk-interface', ?, 'GigabitEthernet1/0/2', 'physical', 'trunk')""",
            (device_id,),
        )
        conn.execute(
            """INSERT INTO topology_links
                   (id, source_device_id, source_interface_id, source_port,
                    source_port_normalized, target_device_id, target_hostname,
                    target_port, link_kind, status, members_json)
               VALUES ('fdb-current-aggregation-link', ?, 'fdb-lag-parent',
                       'Port-channel1', ?, ?, 'SW-CURRENT-NEIGHBOR',
                       'Port-channel2', 'aggregation', 'up', '[]')""",
            (device_id, normalize_interface_name('Port-channel1').strip().lower(), neighbor_id),
        )
        conn.commit()
    _publish_fdb(
        device_id=device_id,
        context_type='unknown',
        local_context_key='fdb-lag-trunk-test',
        mac='00:00:5e:00:01:42',
        status='scope_unknown',
        observed_at=datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=8),
        interfaces=('Port-channel1', 'GigabitEthernet1/0/1', 'GigabitEthernet1/0/2'),
    )

    with get_db_connection() as conn:
        rows = _current_fdb_endpoint_projection(conn, device_id=device_id)

    by_port = {item['switch_port']: item for item in rows}
    assert set(by_port) == {'Port-channel1', 'GigabitEthernet1/0/1', 'GigabitEthernet1/0/2'}
    assert all(item['ip'] is None for item in rows)
    assert all(item['virtual_gateway_mac'] is True for item in rows)
    assert all(item['path_ambiguity'] is True for item in rows)
    assert by_port['Port-channel1']['path_classification'] == 'logical_aggregation'
    assert by_port['Port-channel1']['topology_link_kind'] == 'topology_aggregation_link'
    assert by_port['GigabitEthernet1/0/1']['path_classification'] == 'aggregation_member'
    assert by_port['GigabitEthernet1/0/1']['aggregation_name'] == 'Port-channel1'
    assert by_port['GigabitEthernet1/0/2']['path_classification'] == 'trunk_tagged_interface'


def test_current_fdb_path_classifier_never_promotes_unknown_interface_to_edge():
    from services.ipam_discovery_service import _classify_current_fdb_path

    assert _classify_current_fdb_path(None, None) == (
        'unknown', 'interface_inventory_missing',
    )
    assert _classify_current_fdb_path(
        {'switchport_mode': 'access'}, None,
    ) == ('access_edge', 'explicit_interface_access_mode')
    assert _classify_current_fdb_path(
        {'switchport_mode': ''}, None,
    ) == ('unknown', 'insufficient_edge_or_uplink_evidence')
