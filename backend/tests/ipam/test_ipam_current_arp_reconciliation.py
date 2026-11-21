from __future__ import annotations

from datetime import datetime, timedelta, timezone

from database import get_db_connection
from services.collector_sweep_state_service import complete_collector_sweep, reserve_collector_sweep_batch
from services.collection_status_service import record_collection_results
from services.ipam_address_space_service import create_address_space
from services.ipam_current_endpoint_observation_service import (
    begin_current_endpoint_collection,
    finish_current_endpoint_collection,
)
from services.ipam_routing_context_service import create_device_routing_context
from services.ipam_service import create_address, create_subnet
from services.ipam_discovery_service import build_ipam_reconciliation


_FORBIDDEN_SQL_TOKENS = (
    "ipam_discovery_observations",
    "ipam_discovery_snapshots",
    "ipam_discovery_scope_assertions",
)


class _HistoryReadGuard:
    def __init__(self, connection):
        self._connection = connection
        self.statements: list[str] = []

    def execute(self, statement, *args, **kwargs):
        sql = str(statement)
        lowered = sql.casefold()
        forbidden = [token for token in _FORBIDDEN_SQL_TOKENS if token in lowered]
        if forbidden:
            raise AssertionError(f"reconciliation queried forbidden historical SQL: {forbidden}")
        self.statements.append(sql)
        return self._connection.execute(statement, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._connection, name)


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


def _publish_context(
    *, device_id: str, context_type: str, local_context_key: str,
    observations: list[dict], status: str, observed_at: datetime, run_id: str,
    observation_source: str = "arp",
) -> int:
    attempted = observed_at.astimezone(timezone.utc).isoformat()
    normalized = [
        {
            "ip_address": row["ip"],
            "mac_address": row["mac"],
            "interface_name": row.get("interface") or "GigabitEthernet1/0/1",
            "context_source": "cli",
            "context_type": context_type,
            "local_context_key": local_context_key,
            "local_context_name": local_context_key,
            "vlan_id": row.get("vlan", 10),
        }
        for row in observations
    ]
    with get_db_connection() as conn:
        generation = begin_current_endpoint_collection(
            conn,
            device_id=device_id,
            observation_source=observation_source,
            context_source="cli",
            context_type=context_type,
            local_context_key=local_context_key,
            attempted_at=attempted,
            run_id=run_id,
        )
        finish_current_endpoint_collection(
            conn,
            device_id=device_id,
            observation_source=observation_source,
            context_source="cli",
            context_type=context_type,
            local_context_key=local_context_key,
            generation=generation,
            status=status,
            attempted_at=attempted,
            completed_at=attempted,
            run_id=run_id,
            observations=normalized,
        )
        conn.commit()
    return generation


def _record_complete_arp_sweep(device_entry_counts: dict[str, int], *, run_id: str) -> None:
    device_ids = list(device_entry_counts)
    total_entries = sum(device_entry_counts.values())
    reserve_collector_sweep_batch(
        "arp", total_candidates=len(device_ids), batch_size=len(device_ids), run_id=run_id,
    )
    record_collection_results([
        {
            "device_id": device_id,
            "collector": "arp",
            "status": "success",
            "source": "arp_sweep",
            "coverage_total": device_entry_counts[device_id],
            "coverage_supported": 1,
            "metadata": {
                "collection_run_id": run_id,
                "entry_count": device_entry_counts[device_id],
            },
        }
        for device_id in device_ids
    ])
    complete_collector_sweep(
        "arp", run_id=run_id, successful_devices=len(device_ids),
        failed_devices=0, collected_entries=total_entries,
    )


def test_reconciliation_uses_current_arp_by_address_space_and_guards_history(isolated_db):
    del isolated_db
    site_id = "current-arp-recon-site"
    device_a = "current-arp-recon-a"
    device_b = "current-arp-recon-b"
    _seed_device(device_a, "SW-CURRENT-ARP-A", site_id)
    _seed_device(device_b, "SW-CURRENT-ARP-B", site_id)
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO vrfs (id, vrf_name, tenant_id) VALUES ('current-arp-recon-vrf', 'CURRENT-ARP', 'tenant-default')"
        )
        conn.commit()
    vrf_space = create_address_space(
        name="Current ARP Reconciliation VRF",
        kind="vrf",
        vrf_id="current-arp-recon-vrf",
        security_tenant_id="tenant-default",
    )
    global_space = create_address_space(
        name="Current ARP Reconciliation Global",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    for device_id in (device_a, device_b):
        create_device_routing_context(
            device_id=device_id,
            context_source="cli",
            context_type="vrf",
            local_context_key="Blue",
            local_context_name="Blue",
            address_space_id=vrf_space["id"],
            security_tenant_id="tenant-default",
        )
    create_device_routing_context(
        device_id=device_a,
        context_source="cli",
        context_type="global",
        local_context_key="Global",
        local_context_name="Global",
        address_space_id=global_space["id"],
        security_tenant_id="tenant-default",
    )

    vrf_prefix = create_subnet(
        prefix="192.0.2.0/24", tenant_id="tenant-default", site_id=site_id,
        address_space_id=vrf_space["id"], gateway_device_id=device_a,
    )
    global_prefix = create_subnet(
        prefix="192.0.2.0/24", tenant_id="tenant-default", site_id=site_id,
        address_space_id=global_space["id"], gateway_device_id=device_a,
    )
    match_address = create_address(
        vrf_prefix["id"], address="192.0.2.10", mac_address="00:11:22:33:44:10", status="active",
    )
    mismatch_address = create_address(
        vrf_prefix["id"], address="192.0.2.20", mac_address="00:11:22:33:44:20", status="active",
    )
    global_same_ip = create_address(
        global_prefix["id"], address="192.0.2.10", mac_address="00:11:22:33:44:10", status="active",
    )

    observed_at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=15)
    _publish_context(
        device_id=device_a,
        context_type="vrf",
        local_context_key="Blue",
        status="complete",
        observed_at=observed_at,
        run_id="current-arp-run-a-blue",
        observations=[
            {"ip": "192.0.2.10", "mac": "00:11:22:33:44:10"},
            {"ip": "192.0.2.20", "mac": "00:11:22:33:44:99"},
            {"ip": "192.0.2.30", "mac": "00:11:22:33:44:30"},
        ],
    )
    _publish_context(
        device_id=device_b,
        context_type="vrf",
        local_context_key="Blue",
        status="complete",
        observed_at=observed_at,
        run_id="current-arp-run-b-blue",
        observations=[{"ip": "192.0.2.30", "mac": "00:11:22:33:44:30"}],
    )
    _publish_context(
        device_id=device_a,
        context_type="unknown",
        local_context_key="unmapped-local-vrf",
        status="scope_unknown",
        observed_at=observed_at,
        run_id="current-arp-run-a-unknown",
        observations=[{"ip": "192.0.2.40", "mac": "00:11:22:33:44:40"}],
    )
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO network_endpoints (
                   id, ip, mac, hostname, switch_id, switch_port, vrf, site,
                   first_seen, last_seen, is_active, vlan, source_type
               ) VALUES ('legacy-current-duplicate', '192.0.2.30', '00:11:22:33:44:30',
                         'legacy-row', ?, 'GigabitEthernet1/0/1', 'Blue', ?, ?, ?, 1, 10, 'arp')""",
            (device_a, site_id, observed_at.isoformat(), observed_at.isoformat()),
        )
        conn.commit()
    _record_complete_arp_sweep(
        {device_a: 4, device_b: 1}, run_id="current-arp-complete-sweep",
    )

    class GuardedConnection(_HistoryReadGuard):
        pass

    with get_db_connection() as conn:
        guarded = GuardedConnection(conn)
        result = build_ipam_reconciliation(guarded)

    undocumented = next(
        item for item in result["undocumented_endpoints"] if item["ip"] == "192.0.2.30"
    )
    assert undocumented["address_space_id"] == vrf_space["id"]
    assert undocumented["source_evidence_count"] == 2
    assert len(undocumented["source_devices"]) == 2
    assert undocumented["source_ambiguity"] is True
    assert undocumented["source_kind"] == "current_arp"

    mismatch = next(item for item in result["mismatched_endpoints"] if item["ipam_address_id"] == mismatch_address["id"])
    assert mismatch["address_space_id"] == vrf_space["id"]
    assert mismatch["mac_mismatch"] is True

    stale_ids = {item["ipam_address_id"] for item in result["stale_ip_addresses"]}
    assert match_address["id"] not in stale_ids
    assert global_same_ip["id"] in stale_ids

    unresolved = [item for item in result["unscoped"] if item.get("source_kind") == "current_arp"]
    assert len(unresolved) == 1
    assert unresolved[0]["ip"] == "192.0.2.40"
    assert unresolved[0]["address_space_id"] == ""
    assert unresolved[0]["reason"] == "routing_context_mapping_missing"
    assert result["summary"]["coverage_status"] == "partial"

    assert any("ipam_current_endpoint_observations" in sql.casefold() for sql in guarded.statements)
    assert all(not any(token in sql.casefold() for token in _FORBIDDEN_SQL_TOKENS) for sql in guarded.statements)


def test_reconciliation_uses_current_ndp_without_reading_discovery_history(isolated_db):
    del isolated_db
    site_id = "current-ndp-recon-site"
    device_id = "current-ndp-recon-device"
    _seed_device(device_id, "SW-CURRENT-NDP", site_id)
    space = create_address_space(
        name="Current NDP Reconciliation Global",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    create_device_routing_context(
        device_id=device_id,
        context_source="cli",
        context_type="global",
        local_context_key="Global",
        local_context_name="Global",
        address_space_id=space["id"],
        security_tenant_id="tenant-default",
    )
    create_subnet(
        prefix="2001:db8:1::/64",
        tenant_id="tenant-default",
        site_id=site_id,
        address_space_id=space["id"],
    )
    observed_at = datetime.now(timezone.utc)
    _publish_context(
        device_id=device_id,
        context_type="global",
        local_context_key="Global",
        observations=[{
            "ip": "2001:db8:1::25",
            "mac": "00:11:22:33:44:25",
            "interface": "GigabitEthernet1/0/1",
        }],
        status="complete",
        observed_at=observed_at,
        run_id="current-ndp-reconciliation",
        observation_source="ndp",
    )
    _publish_context(
        device_id=device_id,
        context_type="global",
        local_context_key="Global",
        observations=[],
        status="failed",
        observed_at=observed_at + timedelta(seconds=1),
        run_id="current-ndp-reconciliation-failed-retry",
        observation_source="ndp",
    )

    with get_db_connection() as conn:
        guarded = _HistoryReadGuard(conn)
        result = build_ipam_reconciliation(guarded)

    observation = next(
        item for item in result["undocumented_endpoints"] if item["ip"] == "2001:db8:1::25"
    )
    assert observation["address_space_id"] == space["id"]
    assert observation["source_kind"] == "current_ndp"
    assert observation["evidence_status"] == "recent"
    assert result["summary"]["coverage_status"] == "partial"
    assert any("ipam_current_endpoint_observations" in sql.casefold() for sql in guarded.statements)
    assert all(not any(token in sql.casefold() for token in _FORBIDDEN_SQL_TOKENS) for sql in guarded.statements)
