from __future__ import annotations

from datetime import datetime, timezone

import pytest

from database import get_db_connection
from services import ipam_discovery_service as discovery
from services.ip_locator_endpoint_evidence import find_current_endpoint_evidence
from services.ipam_current_endpoint_observation_service import (
    begin_current_endpoint_collection,
    finish_current_endpoint_collection,
)
from services.ipam_current_fdb_observation_service import (
    begin_current_fdb_collection,
    finish_current_fdb_collection,
)


TARGET_IP = "172.16.5.10"
TARGET_MAC = "8e:47:57:60:07:06"
DEVICE_ID = "current-locator-s6850-5"
SITE_ID = "current-locator-site"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _seed_access_device(*, device_id: str = DEVICE_ID, ports: tuple[str, ...] = ("GigabitEthernet1/0/2",)) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES ('tenant-default', 'Default') ON CONFLICT(id) DO NOTHING"
        )
        conn.execute(
            """INSERT INTO sites (id, site_code, site_name, tenant_id)
               VALUES (?, ?, 'Current Locator Site', 'tenant-default')
               ON CONFLICT(id) DO NOTHING""",
            (SITE_ID, SITE_ID.upper()),
        )
        conn.execute(
            """INSERT INTO devices (id, hostname, tenant_id, site_id, status, role, platform)
               VALUES (?, 'S6850-5', 'tenant-default', ?, 'online', 'access', 'h3c_comware')""",
            (device_id, SITE_ID),
        )
        for index, port in enumerate(ports):
            conn.execute(
                """INSERT INTO interfaces
                       (id, device_id, interface_name, interface_type, description,
                        switchport_mode, access_vlan)
                   VALUES (?, ?, ?, 'physical', ?, 'access', 7)""",
                (f"{device_id}-interface-{index}", device_id, port, "TO-PC-7" if index == 0 else "duplicate path"),
            )
        conn.commit()


def _publish_current_arp(*, device_id: str = DEVICE_ID, ip: str = TARGET_IP, mac: str = TARGET_MAC) -> int:
    observed_at = _now()
    context = {"context_source": "snmp", "context_type": "unknown", "local_context_key": ""}
    with get_db_connection() as conn:
        generation = begin_current_endpoint_collection(
            conn,
            device_id=device_id,
            observation_source="arp",
            **context,
            attempted_at=observed_at,
            run_id=f"arp-{device_id}-{observed_at}",
        )
        finish_current_endpoint_collection(
            conn,
            device_id=device_id,
            observation_source="arp",
            **context,
            generation=generation,
            status="scope_unknown",
            attempted_at=observed_at,
            completed_at=observed_at,
            run_id=f"arp-{device_id}-{observed_at}",
            observations=[{
                "ip_address": ip,
                "mac_address": mac,
                "interface_name": "Vlan-interface7",
                "vlan_id": 7,
                **context,
            }],
        )
        conn.commit()
    return generation


def _publish_current_fdb(*, ports: tuple[str, ...] = ("GigabitEthernet1/0/2",), device_id: str = DEVICE_ID) -> int:
    observed_at = _now()
    context = {"context_source": "snmp", "context_type": "unknown", "local_context_key": ""}
    with get_db_connection() as conn:
        generation = begin_current_fdb_collection(
            conn, device_id=device_id, **context,
            attempted_at=observed_at,
            run_id=f"fdb-{device_id}-{observed_at}",
        )
        finish_current_fdb_collection(
            conn,
            device_id=device_id,
            **context,
            generation=generation,
            status="scope_unknown",
            attempted_at=observed_at,
            completed_at=observed_at,
            run_id=f"fdb-{device_id}-{observed_at}",
            observations=[{
                "mac_address": TARGET_MAC,
                "interface_name": port,
                "vlan_id": 7,
                "entry_type": "dynamic",
            } for port in ports],
        )
        conn.commit()
    return generation


def _find(*, device_ids: set[str] | None = None):
    return find_current_endpoint_evidence(
        TARGET_IP,
        tenant_id="tenant-default",
        site_id=SITE_ID,
        authorized_device_ids=device_ids or {DEVICE_ID},
        vrf="default",
    )


def test_current_unknown_context_arp_links_to_unique_same_device_vlan_access_port(isolated_db, monkeypatch):
    _seed_access_device()
    _publish_current_arp()
    fdb_generation = _publish_current_fdb()
    monkeypatch.setattr(
        discovery,
        "_load_projected_observations",
        lambda *_args, **_kwargs: pytest.fail("current endpoint locator must not read historical discovery snapshots"),
    )

    result = _find()

    assert result is not None
    assert result["location"] == {
        "device_id": DEVICE_ID,
        "device": "S6850-5",
        "port": "GigabitEthernet1/0/2",
        "mac": TARGET_MAC,
        "vlan": "7",
    }
    assert result["vrf_context_status"] == "unknown"
    assert result["collection_source"] == "snmp"
    assert result["fdb_evidence"][0]["generation"] == fdb_generation
    assert result["fdb_evidence"][0]["path_classification"] == "access_edge"


@pytest.mark.parametrize("failure", ["multiple_ports", "latest_arp_attempt_failed", "other_device_only", "interface_vlan_mismatch"])
def test_current_endpoint_locator_fails_closed_on_ambiguous_or_inconsistent_current_facts(isolated_db, failure):
    _seed_access_device(ports=("GigabitEthernet1/0/2", "GigabitEthernet1/0/3"))
    _publish_current_arp()
    if failure == "multiple_ports":
        _publish_current_fdb(ports=("GigabitEthernet1/0/2", "GigabitEthernet1/0/3"))
    elif failure == "latest_arp_attempt_failed":
        _publish_current_fdb()
        attempted_at = _now()
        with get_db_connection() as conn:
            begin_current_endpoint_collection(
                conn,
                device_id=DEVICE_ID,
                observation_source="arp",
                context_source="snmp",
                context_type="unknown",
                local_context_key="",
                attempted_at=attempted_at,
                run_id="arp-latest-failed",
            )
            conn.commit()
    elif failure == "interface_vlan_mismatch":
        _publish_current_fdb()
        with get_db_connection() as conn:
            conn.execute("UPDATE interfaces SET access_vlan = 8 WHERE device_id = ?", (DEVICE_ID,))
            conn.commit()
    else:
        other_device = "current-locator-other-access"
        _seed_access_device(device_id=other_device)
        _publish_current_fdb(device_id=other_device)

    assert _find() is None

@pytest.mark.parametrize("other_mac", [TARGET_MAC, "02:11:22:33:44:55"])
def test_current_endpoint_does_not_ignore_unresolved_arp_source(isolated_db, other_mac):
    _seed_access_device()
    _publish_current_arp()
    _publish_current_fdb()
    other_device = "current-locator-unresolved-arp"
    _seed_access_device(device_id=other_device)
    _publish_current_arp(device_id=other_device, mac=other_mac)

    assert _find(device_ids={DEVICE_ID, other_device}) is None


def test_current_endpoint_ignores_unauthorized_arp_source(isolated_db):
    _seed_access_device()
    _publish_current_arp()
    _publish_current_fdb()
    other_device = "current-locator-unauthorized-arp"
    _seed_access_device(device_id=other_device)
    _publish_current_arp(device_id=other_device, mac="02:11:22:33:44:55")

    assert _find(device_ids={DEVICE_ID}) is not None

def test_targeted_current_projection_retains_same_target_conflicts(isolated_db):
    _seed_access_device()
    _publish_current_arp()
    _publish_current_fdb()
    with get_db_connection() as conn:
        arp = discovery._current_endpoint_projection(
            conn, device_id=DEVICE_ID, observation_source="arp",
        )
        assert discovery._current_endpoint_projection(
            conn, device_id=DEVICE_ID, observation_source="arp", target_ip=TARGET_IP,
        ) == arp
        assert discovery._current_endpoint_projection(
            conn, device_id=DEVICE_ID, observation_source="arp", target_ip="172.16.5.99",
        ) == []
        fdb = discovery._current_fdb_endpoint_projection(conn, device_id=DEVICE_ID)
        assert discovery._current_fdb_endpoint_projection(
            conn, device_id=DEVICE_ID, target_mac=TARGET_MAC,
        ) == fdb
        assert discovery._current_fdb_endpoint_projection(
            conn, device_id=DEVICE_ID, target_mac="02:11:22:33:44:55",
        ) == []
