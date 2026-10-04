from __future__ import annotations

import pytest


def _seed_inventory():
    from database import get_db_connection

    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO tenants (id, name) VALUES (?, ?)", ("tenant-circuit", "Circuit Tenant"))
        conn.execute("INSERT INTO sites (id, site_code, site_name, tenant_id) VALUES (?, ?, ?, ?)", ("site-circuit", "CIR", "Circuit Site", "tenant-circuit"))
        conn.execute("INSERT INTO devices (id, hostname, site_id, site, tenant_id, role, device_category) VALUES (?, ?, ?, ?, ?, ?, ?)", ("device-circuit", "edge-circuit", "site-circuit", "site-circuit", "tenant-circuit", "edge", "router"))
        conn.execute("INSERT INTO devices (id, hostname, site_id, site, tenant_id, role, device_category) VALUES (?, ?, ?, ?, ?, ?, ?)", ("device-other", "edge-other", "site-circuit", "site-circuit", "tenant-other", "edge", "router"))
        conn.execute("INSERT INTO interfaces (id, device_id, interface_name, if_index, speed) VALUES (?, ?, ?, ?, ?)", ("interface-circuit", "device-circuit", "GigabitEthernet0/0", 7, 1_000_000_000))
        conn.commit()
    finally:
        conn.close()


def _payload():
    return {
        "link_name": "Circuit A-Z",
        "site_id": "site-circuit",
        "contracted_download_mbps": 200,
        "contracted_upload_mbps": 100,
        "provider": "Test ISP",
        "endpoints": [
            {"side": "A", "endpoint_type": "managed", "site_id": "site-circuit", "device_id": "device-circuit", "interface_id": "interface-circuit", "counter_orientation": "normal", "measurement_scope": "dedicated"},
            {"side": "Z", "endpoint_type": "unmanaged", "site_id": "site-circuit", "endpoint_name": "Provider handoff"},
        ],
    }


def test_save_and_read_circuit_are_tenant_scoped(isolated_db):
    _seed_inventory()
    from services.wan_circuit_service import get_wan_circuit, get_wan_circuit_sla, save_wan_circuit

    item = save_wan_circuit(_payload(), tenant_id="tenant-circuit", actor_id="operator-1")
    assert item["configuration_version"] == 1
    assert {endpoint["side"] for endpoint in item["endpoints"]} == {"A", "Z"}
    assert {endpoint["binding_version"] for endpoint in item["endpoints"]} == {1}
    assert get_wan_circuit(item["id"], tenant_id="tenant-other") is None
    sla = get_wan_circuit_sla(item["id"], tenant_id="tenant-circuit")
    assert sla["status"] == "insufficient_data"
    assert sla["reason_code"] == "path_evidence_unavailable"
    assert sla["availability_pct"] is None


def test_endpoint_history_is_append_only_and_only_versions_changed_sides(isolated_db):
    from database import get_db_connection
    from services.wan_circuit_service import (
        list_wan_circuit_endpoint_history,
        save_wan_circuit,
    )

    _seed_inventory()
    payload = _payload()
    item = save_wan_circuit(payload, tenant_id="tenant-circuit", actor_id="operator-1")
    assert len(list_wan_circuit_endpoint_history(item["id"], tenant_id="tenant-circuit")) == 2

    payload["expected_version"] = item["configuration_version"]
    unchanged = save_wan_circuit(payload, tenant_id="tenant-circuit", actor_id="operator-1", link_id=item["id"])
    assert {endpoint["binding_version"] for endpoint in unchanged["endpoints"]} == {1}

    payload["expected_version"] = unchanged["configuration_version"]
    payload["endpoints"][1]["endpoint_name"] = "New provider handoff"
    changed = save_wan_circuit(payload, tenant_id="tenant-circuit", actor_id="operator-1", link_id=item["id"])
    assert {endpoint["side"]: endpoint["binding_version"] for endpoint in changed["endpoints"]} == {"A": 1, "Z": 2}

    history = list_wan_circuit_endpoint_history(item["id"], tenant_id="tenant-circuit")
    z_versions = [row for row in history if row["side"] == "Z"]
    assert [row["endpoint_version"] for row in z_versions] == [2, 1]
    assert z_versions[0]["valid_to"] is None
    assert z_versions[1]["valid_to"] is not None
    assert z_versions[0]["snapshot"]["endpoint_name"] == "New provider handoff"
    assert list_wan_circuit_endpoint_history(item["id"], tenant_id="tenant-other") is None

    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT side, COUNT(*) AS total FROM wan_link_endpoint_history WHERE link_id = ? GROUP BY side",
            (item["id"],),
        ).fetchall()
        assert {row["side"]: row["total"] for row in rows} == {"A": 1, "Z": 2}
    finally:
        conn.close()


def test_shared_a_endpoint_is_versioned_and_circuit_list_suppresses_utilization(isolated_db):
    from database import get_db_connection
    from services.wan_circuit_service import list_wan_circuits, list_wan_circuit_endpoint_history, save_wan_circuit

    _seed_inventory()
    item = save_wan_circuit(_payload(), tenant_id="tenant-circuit", actor_id="operator-1")
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO wan_link_current_status (link_id, sampled_at, download_bps, upload_bps, download_util_pct, upload_util_pct, health_status, oper_status, collection_status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item["id"], "2026-10-04T00:00:00Z", 100_000_000, 50_000_000, 50, 50, "healthy", "up", "success", "2026-10-04T00:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()

    payload = _payload()
    payload["endpoints"][0]["measurement_scope"] = "shared_interface"
    payload["expected_version"] = item["configuration_version"]
    updated = save_wan_circuit(payload, tenant_id="tenant-circuit", actor_id="operator-1", link_id=item["id"])
    assert updated["endpoints"][0]["measurement_scope"] == "shared_interface"
    assert updated["endpoints"][0]["binding_version"] == 2

    history = list_wan_circuit_endpoint_history(item["id"], tenant_id="tenant-circuit")
    a_versions = [row for row in history if row["side"] == "A"]
    assert [row["snapshot"]["measurement_scope"] for row in a_versions] == ["shared_interface", "dedicated"]

    result = list_wan_circuits(tenant_id="tenant-circuit", page=1, page_size=20)
    listed = result["items"][0]
    assert listed["endpoints"][0]["measurement_scope"] == "shared_interface"
    assert listed["download_util_pct"] is None
    assert listed["upload_util_pct"] is None
    assert listed["health_status"] == "unknown"

    conn = get_db_connection()
    try:
        status = dict(conn.execute("SELECT download_bps, upload_bps, download_util_pct, upload_util_pct FROM wan_link_current_status WHERE link_id = ?", (item["id"],)).fetchone())
    finally:
        conn.close()
    assert status == {"download_bps": None, "upload_bps": None, "download_util_pct": None, "upload_util_pct": None}


def test_save_rejects_cross_tenant_endpoint_and_stale_version(isolated_db):
    _seed_inventory()
    from database import get_db_connection
    from services.wan_circuit_service import save_wan_circuit

    payload = _payload()
    payload["endpoints"][0]["device_id"] = "device-other"
    payload["endpoints"][0]["interface_id"] = "interface-circuit"
    with pytest.raises(ValueError, match="another tenant|does not belong"):
        save_wan_circuit(payload, tenant_id="tenant-circuit", actor_id="operator-1")

    payload = _payload()
    item = save_wan_circuit(payload, tenant_id="tenant-circuit", actor_id="operator-1")
    payload["configuration_version"] = item["configuration_version"]
    updated = save_wan_circuit(payload, tenant_id="tenant-circuit", actor_id="operator-1", link_id=item["id"])
    assert updated["configuration_version"] == 2
    with pytest.raises(ValueError, match="configuration_version_conflict"):
        save_wan_circuit(payload, tenant_id="tenant-circuit", actor_id="operator-1", link_id=item["id"])

    conn = get_db_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM wan_link_contract_history WHERE link_id = ?", (item["id"],)).fetchone()[0] == 1
    finally:
        conn.close()


def test_sla_policy_is_versioned_and_defaults_are_explicit(isolated_db):
    _seed_inventory()
    from services.wan_circuit_service import save_wan_circuit, upsert_wan_circuit_sla_policy

    item = save_wan_circuit(_payload(), tenant_id="", actor_id="operator-1")
    policy = upsert_wan_circuit_sla_policy(item["id"], {"availability_rule": "all_success"}, tenant_id="", actor_id="operator-1")
    assert policy["policy_version"] == 1
    assert policy["policy"]["availability_target_pct"] == 99.9
    with pytest.raises(ValueError, match="policy_version_required"):
        upsert_wan_circuit_sla_policy(item["id"], {"availability_rule": "any_success"}, tenant_id="tenant-circuit", actor_id="operator-1")
    policy2 = upsert_wan_circuit_sla_policy(item["id"], {"policy_version": 1, "availability_target_pct": 99.99}, tenant_id="tenant-circuit", actor_id="operator-1")
    assert policy2["policy_version"] == 2
