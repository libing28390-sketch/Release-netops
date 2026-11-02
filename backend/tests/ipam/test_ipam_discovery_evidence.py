from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from database import get_db_connection
from database.migrations.m0301_ipam_discovery_evidence import upgrade
from services import ipam_discovery_service as discovery
from services.ipam_service import create_address, create_subnet, get_ipam_reconciliation, list_ip_inventory

MAC = "00:11:22:33:44:55"
OTHER_MAC = "00:11:22:33:44:66"


def seed(device="gateway-a", site="discovery-site-a"):
    with get_db_connection() as c:
        c.execute("INSERT INTO tenants(id,name) VALUES ('tenant-default','Default') ON CONFLICT DO NOTHING")
        c.execute("INSERT INTO sites(id,site_code,site_name,tenant_id) VALUES (?,?,?,'tenant-default') ON CONFLICT DO NOTHING", (site, site, site))
        c.execute("INSERT INTO devices(id,hostname,tenant_id,site_id,status) VALUES (?,?,'tenant-default',?,'online') ON CONFLICT DO NOTHING", (device, device, site))
        c.commit()


def raw_arp(when, *, device="gateway-a", ip="192.0.2.10", mac=MAC):
    with get_db_connection() as c:
        c.execute("DELETE FROM arp_table WHERE device_id=?", (device,))
        c.execute("INSERT INTO arp_table(id,device_id,ip_address,mac_address,interface_name,vlan_id,last_updated) VALUES (?,?,?,?, 'Vlan-interface100',100,?)", (device+ip, device, ip, mac, when if isinstance(when, str) else when.isoformat()))
        c.commit()


def mark_run(when, run="run-current", *, device="gateway-a", count=1, status="success", context="global"):
    attempt=(when-timedelta(seconds=1)).isoformat()
    completed=(when+timedelta(seconds=1)).isoformat()
    metadata={"collection_run_id":run,"entry_count":count}
    if context is not None:
        metadata["vrf_context"]=context
    with get_db_connection() as c:
        c.execute("""INSERT INTO device_collection_status(device_id,collector,status,source,transport,last_attempt_at,last_success_at,coverage_total,coverage_supported,metadata_json,updated_at)
          VALUES (?,'arp',?,'arp_sweep','snmp',?,?,?,?,?,?) ON CONFLICT(device_id,collector) DO UPDATE SET status=excluded.status,last_attempt_at=excluded.last_attempt_at,last_success_at=excluded.last_success_at,coverage_total=excluded.coverage_total,coverage_supported=excluded.coverage_supported,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at""", (device,status,attempt,attempt,count,1,json.dumps(metadata),completed))
        c.execute("""INSERT INTO collector_sweep_state(collector,last_run_id,last_completed_at,last_eligible,last_selected,last_successful,last_failed,last_collected,updated_at)
          VALUES ('arp',?,?,1,1,1,0,?,?) ON CONFLICT(collector) DO UPDATE SET last_run_id=excluded.last_run_id,last_completed_at=excluded.last_completed_at,last_eligible=1,last_selected=1,last_successful=1,last_failed=0,last_collected=excluded.last_collected,updated_at=excluded.updated_at""", (run,completed,count,completed))
        c.commit()


def evidence(when, run, *, device="gateway-a", site="discovery-site-a", ip="192.0.2.10", mac=MAC, vlan="100", kind="arp", context="explicit_global", vrf="", projected=None):
    scope={"tenant_id":"tenant-default","site_id":site,"vrf_id":vrf,"vrf_context_status":context,"scope_status":"resolved" if context != "unknown" else "scope_pending"}
    with get_db_connection() as c:
        snapshot=discovery._insert_snapshot(c,collector=kind,device_id=device,source_device_name=device,scope=scope,source_run_id=run,source_version=run,source_status="success",coverage_status="complete",coverage_complete=kind=="arp",coverage_reason="",entry_count=1 if ip else 0,observed_at=when.isoformat(),projected_at=(projected or when).isoformat())
        if ip or kind=="mac":
            discovery._insert_observation(c,snapshot_id=snapshot,source_type=kind,device_id=device,source_device_name=device,scope=scope,ip=ip,mac=mac,interface_name="Ethernet1" if kind=="mac" else "Vlan-interface100",vlan=vlan,raw_timestamp=when.isoformat(),projected_at=(projected or when).isoformat())
        c.commit()
        row=c.execute("SELECT id FROM ipam_discovery_observations WHERE snapshot_id=?",(snapshot,)).fetchone()
        return row["id"] if row else snapshot


def test_migration_is_repeatable_and_keeps_source_identity_scoped(isolated_db):
    with get_db_connection() as c:
        upgrade(c.cursor(),True)
        upgrade(c.cursor(),True)
        seed_rows=c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='ipam_discovery_observations'").fetchall()
        assert {r["column_name"] for r in seed_rows} >= {"source_observed_at","projected_at","source_identity_key","vrf_context_status"}
        constraints=c.execute("SELECT pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE conrelid='ipam_discovery_observations'::regclass").fetchall()
        assert any("snapshot_id, source_identity_key" in r["definition"] for r in constraints)
        c.commit()


def test_projection_keeps_arp_without_mac_and_does_not_renew_time(isolated_db,monkeypatch):
    seed()
    now=datetime.now(timezone.utc)
    observed=now-timedelta(minutes=2)
    raw_arp(observed)
    first=discovery.run_ipam_discovery_projection()
    rows=discovery.list_discovered_endpoints(kind="ip")["items"]
    assert len(rows)==1 and rows[0]["ip"]=="192.0.2.10"
    assert rows[0]["scope_status"]=="scope_pending"
    assert rows[0]["hostname"]=="" and rows[0]["switch_port"]==""
    assert datetime.fromisoformat(rows[0]["observed_at"])==observed
    monkeypatch.setattr(discovery,"_utc_now",lambda:now+timedelta(minutes=40))
    second=discovery.run_ipam_discovery_projection()
    again=discovery.list_discovered_endpoints(kind="ip")["items"][0]
    assert first["observations_created"]==1 and second["observations_created"]==0
    assert again["observed_at"]==rows[0]["observed_at"] and again["evidence_status"]=="historical"
    summary=discovery.list_discovered_endpoints(kind="ip")["summary"]
    assert summary["discovered_ip_count"]==1 and summary["recent_ip_count"]==0
    assert summary["coverage_status"]!="complete"
    with get_db_connection() as c:
        assert c.execute("SELECT last_updated FROM arp_table").fetchone()["last_updated"]==observed.isoformat()
        assert c.execute("SELECT COUNT(*) AS n FROM network_endpoints").fetchone()["n"]==0


def test_completed_run_context_and_failed_metadata_are_distinguished(isolated_db, monkeypatch):
    seed()
    now=datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(discovery, "_utc_now", lambda: now)
    when=now-timedelta(seconds=10)
    raw_arp(when)
    mark_run(when)
    discovery.run_ipam_discovery_projection()
    item=discovery.list_discovered_endpoints(kind="ip")["items"][0]
    assert item["scope_status"]=="resolved" and item["vrf_context_status"]=="explicit_global"
    assert item["coverage_complete"]
    result=get_ipam_reconciliation()
    assert len(result["undocumented_endpoints"])==1  # Empty ledger is a valid comparison.
    mark_run(when+timedelta(seconds=2),run="failed-run",status="failed")
    discovery.run_ipam_discovery_projection()
    response=discovery.list_discovered_endpoints(kind="ip")
    # Both source contexts remain visible with the same observed_at. UUID
    # ordering cannot identify which collector run an assertion belongs to.
    failed_items=[row for row in response["items"] if row["source_run_id"]=="failed-run"]
    assert len(failed_items)==1
    item=failed_items[0]
    assert item["scope_status"]=="scope_pending" and not item["coverage_complete"]
    assert any(row["source_run_id"]=="run-current" and row["coverage_complete"] for row in response["items"])
    assert response["summary"]["coverage_status"]!="complete"


def test_unknown_source_timestamp_cannot_be_hidden_by_old_valid_row(isolated_db):
    seed()
    raw_arp(datetime.now(timezone.utc)-timedelta(minutes=1))
    discovery.run_ipam_discovery_projection()
    raw_arp("not-a-time")
    discovery.run_ipam_discovery_projection()
    item=discovery.list_discovered_endpoints(kind="ip")["items"][0]
    assert item["evidence_status"]=="unknown" and item["timestamp_status"]=="invalid"
    assert item["observed_at"]==""
    raw_arp(datetime.now(timezone.utc)+timedelta(minutes=5))
    discovery.run_ipam_discovery_projection()
    assert discovery.list_discovered_endpoints(kind="ip")["items"][0]["timestamp_status"]=="future"


def test_scope_reuse_and_same_ip_mac_conflicts_preserve_all_evidence(isolated_db):
    seed()
    seed("gateway-b","discovery-site-b")
    now=datetime.now(timezone.utc)-timedelta(seconds=2)
    evidence(now,"a")
    evidence(now,"b",device="gateway-b",site="discovery-site-b")
    rows=discovery.list_discovered_endpoints(kind="ip")["items"]
    assert len(rows)==2 and {r["site_id"] for r in rows}=={"discovery-site-a","discovery-site-b"}
    evidence(now,"conflict",device="gateway-a",mac=OTHER_MAC)
    result=get_ipam_reconciliation()
    assert result["mismatched_endpoints"]
    assert all(not r.get("calibration_safe") for r in result["mismatched_endpoints"])
    assert len(discovery.list_discovered_endpoints(kind="ip",visible_scopes={("tenant-default","discovery-site-b")})["items"])==1
    with get_db_connection() as c:
        c.execute("INSERT INTO vrfs(id,vrf_name,tenant_id) VALUES ('blue','BLUE','tenant-default'),('red','RED','tenant-default')")
        c.commit()
    evidence(now,"blue-source",context="explicit_vrf",vrf="blue")
    evidence(now,"red-source",context="explicit_vrf",vrf="red")
    scoped=[r for r in discovery.list_discovered_endpoints(kind="ip")["items"] if r["vrf_id"] in {"blue","red"}]
    assert len(scoped)==2 and all(r["evidence_status"]!="conflict" for r in scoped)


def test_mac_only_is_separate_and_old_port_is_not_current(isolated_db):
    seed()
    now=datetime.now(timezone.utc)
    evidence(now-timedelta(minutes=1),"arp-current")
    evidence(now-timedelta(hours=4),"old-mac",kind="mac",ip=None)
    rows=discovery.list_discovered_endpoints(kind="all")["items"]
    arp=next(r for r in rows if r["ip"])
    assert arp["switch_port"]==""
    macs=discovery.list_discovered_endpoints(kind="mac")["items"]
    assert macs and all(not r["ip"] for r in macs)


def test_business_vlan_scope_keeps_only_active_business_vlan_endpoints(isolated_db):
    seed()
    with get_db_connection() as c:
        c.execute(
            """INSERT INTO vlans(id, vlan_id, name, site_id, status, tenant_id)
               VALUES
                 ('vlan-100', 100, 'User VLAN', 'discovery-site-a', 'active', 'tenant-default'),
                 ('vlan-200', 200, 'Transit VLAN', 'discovery-site-a', 'active', 'tenant-default'),
                 ('vlan-300', 300, 'Management VLAN', 'discovery-site-a', 'active', 'tenant-default'),
                 ('vlan-400', 400, 'Unclassified VLAN', 'discovery-site-a', 'active', 'tenant-default')"""
        )
        c.commit()
    create_subnet(prefix="192.0.2.0/24", site_id="discovery-site-a", tenant_id="tenant-default", vlan_id="vlan-100", network_type="user_access")
    create_subnet(prefix="198.51.100.0/24", site_id="discovery-site-a", tenant_id="tenant-default", vlan_id="vlan-200", network_type="transit")
    create_subnet(prefix="203.0.113.0/24", site_id="discovery-site-a", tenant_id="tenant-default", vlan_id="vlan-300", network_type="management")
    create_subnet(prefix="100.64.0.0/24", site_id="discovery-site-a", tenant_id="tenant-default", network_type="server")
    create_subnet(prefix="172.20.0.0/24", site_id="discovery-site-a", tenant_id="tenant-default", vlan_id="vlan-400", network_type="unclassified")
    with get_db_connection() as c:
        c.execute("INSERT INTO vrfs(id, vrf_name, tenant_id) VALUES ('discovery-blue', 'BLUE', 'tenant-default')")
        c.commit()
    create_subnet(prefix="100.65.0.0/24", site_id="discovery-site-a", tenant_id="tenant-default", network_type="server")
    create_subnet(prefix="100.65.0.0/24", site_id="discovery-site-a", tenant_id="tenant-default", vrf_id="discovery-blue", network_type="server")
    now = datetime.now(timezone.utc) - timedelta(seconds=2)
    evidence(now, "business-ip", ip="192.0.2.10", mac=MAC, vlan="100")
    evidence(now, "transit-ip", ip="198.51.100.10", mac=OTHER_MAC, vlan="200")
    evidence(now, "management-ip", ip="203.0.113.10", mac="00:11:22:33:44:77", vlan="300")
    evidence(now, "business-without-vlan", ip="100.64.0.11", mac="00:11:22:33:44:88", vlan="", context="unknown")
    evidence(now, "unclassified-ip", ip="172.20.0.10", mac="00:11:22:33:44:99", vlan="400")
    evidence(now, "vlan-mismatch", ip="192.0.2.20", mac="00:11:22:33:44:aa", vlan="200")
    evidence(now, "inferred-default-business-vlan", ip="100.64.0.10", mac="00:11:22:33:44:bc", vlan="500", context="unknown")
    evidence(now, "ambiguous-vrf-business-vlan", ip="100.65.0.10", mac="00:11:22:33:44:cd", vlan="500", context="unknown")
    evidence(now, "business-mac-only", ip=None, mac="00:11:22:33:44:bb", vlan="100", kind="mac")

    business = discovery.list_discovered_endpoints(kind="all", network_scope="business_vlan")
    ip_items = {row["ip"]: row for row in business["items"] if row["ip"]}
    assert set(ip_items) == {"192.0.2.10", "100.64.0.10"}
    assert ip_items["100.64.0.10"]["vrf_name"] == "全局/默认"
    assert ip_items["100.64.0.10"]["vrf_context_inferred"] is True
    assert ip_items["100.64.0.10"]["scope_status"] == "scope_pending"
    assert business["summary"]["coverage_status"] == "partial"
    assert any(row["source_type"] == "mac" and row["vlan"] == "100" for row in business["items"])
    assert business["summary"]["discovered_ip_count"] == 2
    assert business["summary"]["mac_only_count"] == 1
    assert business["network_scope"] == "business_vlan"

    all_ip_observations = discovery.list_discovered_endpoints(kind="ip", network_scope="all")
    assert all_ip_observations["total"] == 8
    assert {row["ip"] for row in all_ip_observations["items"]} >= {
        "192.0.2.10", "198.51.100.10", "203.0.113.10", "100.64.0.10", "100.64.0.11",
        "100.65.0.10", "172.20.0.10", "192.0.2.20",
    }


def test_business_terminals_exclude_gateways_device_ips_and_non_host_addresses(isolated_db):
    seed()
    prefix = create_subnet(prefix="192.0.2.0/24", site_id="discovery-site-a",
                           tenant_id="tenant-default", network_type="user_access", gateway="192.0.2.1")
    own = create_address(subnet_id=prefix['id'], address="192.0.2.2", device_type="device")
    with get_db_connection() as c:
        c.execute("UPDATE ip_addresses SET source_type='interface_collection' WHERE id=?", (own['id'],))
        c.commit()
    now = datetime.now(timezone.utc) - timedelta(seconds=2)
    for suffix in (0, 1, 2, 10, 255):
        evidence(now, f"host-{suffix}", ip=f"192.0.2.{suffix}")
    # Raw diagnostic observations remain inspectable; only the business view
    # excludes infrastructure addresses and network/broadcast addresses.
    assert discovery.list_discovered_endpoints(kind="ip")['total'] == 5
    business = discovery.list_discovered_endpoints(kind="ip", network_scope="business_vlan")
    assert [r['ip'] for r in business['items']] == ['192.0.2.10']


def test_unknown_arp_vrf_cannot_borrow_explicit_global_mac_port(isolated_db):
    seed()
    seed('access-a')
    prefix = create_subnet(prefix='192.0.2.0/24', site_id='discovery-site-a')
    create_address(prefix['id'], address='192.0.2.10', hostname='known-global-host')
    now = datetime.now(timezone.utc) - timedelta(seconds=2)
    evidence(now, 'unknown-arp', context='unknown')
    evidence(now, 'known-mac', device='access-a', kind='mac', ip=None)
    item = discovery.list_discovered_endpoints(kind='ip')['items'][0]
    assert item['switch_port'] == ''
    assert item['switch_location_status'] == 'pending'
    assert item['registration_status'] == 'scope_pending'
    assert item['hostname'] == ''
    assert item['ipam_address_id'] == ''


def test_only_proven_access_mac_port_can_locate_a_business_host(isolated_db, monkeypatch):
    from services import ip_locator_service
    seed()
    seed('access-a')
    now = datetime.now(timezone.utc) - timedelta(seconds=2)
    evidence(now, 'known-arp')
    evidence(now, 'known-mac', device='access-a', kind='mac', ip=None)
    monkeypatch.setattr(ip_locator_service, 'endpoint_access_port_evidence', lambda *args: 'uplink')
    assert discovery.list_discovered_endpoints(kind='ip')['items'][0]['switch_port'] == ''
    monkeypatch.setattr(ip_locator_service, 'endpoint_access_port_evidence', lambda *args: 'unknown')
    assert discovery.list_discovered_endpoints(kind='ip')['items'][0]['switch_port'] == ''
    monkeypatch.setattr(ip_locator_service, 'endpoint_access_port_evidence', lambda *args: 'access')
    item = discovery.list_discovered_endpoints(kind='ip')['items'][0]
    assert item['switch_id'] == 'access-a'
    assert item['switch_port'] == 'Ethernet1'


def test_layer_two_mac_uses_unique_vlan_vrf_binding_without_changing_source_scope(isolated_db, monkeypatch):
    from services import ip_locator_service
    seed()
    seed('access-a')
    with get_db_connection() as c:
        c.execute("""INSERT INTO vlans(id,vlan_id,name,site_id,status,tenant_id)
                     VALUES ('business-vlan-100',100,'Business','discovery-site-a','active','tenant-default')""")
        c.commit()
    create_subnet(prefix='192.0.2.0/24', site_id='discovery-site-a',
                  vlan_id='business-vlan-100', network_type='user_access')
    now = datetime.now(timezone.utc) - timedelta(seconds=2)
    evidence(now, 'known-arp')
    evidence(now, 'layer-two-mac', device='access-a', kind='mac', ip=None, context='unknown')
    monkeypatch.setattr(ip_locator_service, 'endpoint_access_port_evidence', lambda *args: 'access')
    item = discovery.list_discovered_endpoints(kind='ip')['items'][0]
    assert item['switch_id'] == 'access-a'
    source = discovery.list_discovered_endpoints(kind='mac')['items'][0]
    assert source['source_vrf_context_status'] == 'unknown'
    assert source['scope_status'] == 'scope_pending'
    with get_db_connection() as c:
        c.execute("INSERT INTO vrfs(id,vrf_name,tenant_id) VALUES ('ambiguous-vrf','Ambiguous','tenant-default')")
        c.commit()
    create_subnet(prefix='198.51.100.0/24', site_id='discovery-site-a', vrf_id='ambiguous-vrf',
                  vlan_id='business-vlan-100', network_type='user_access')
    assert discovery.list_discovered_endpoints(kind='ip')['items'][0]['switch_port'] == ''


def test_registration_assertion_survives_generation_but_not_prefix_change(isolated_db,monkeypatch):
    seed()
    observed=datetime.now(timezone.utc)-timedelta(minutes=2)
    raw_arp(observed)
    discovery.run_ipam_discovery_projection()
    item=discovery.list_discovered_endpoints(kind="ip")["items"][0]
    prefix=create_subnet(prefix="192.0.2.0/24",site_id="discovery-site-a",tenant_id="tenant-default")
    result=discovery.register_discovered_observation(observation_id=item["id"],subnet_id=prefix["id"],expected_observed_at=item["observed_at"],confirmed_scope=True,requested_by="reviewer")
    with get_db_connection() as c:
        address=dict(c.execute("SELECT * FROM ip_addresses WHERE id=?",(result["ipam_address_id"],)).fetchone())
        assert not address.get("device_id") and not address.get("hostname") and not address.get("interface_name")
    with monkeypatch.context() as clock:
        clock.setattr(discovery,"_utc_now",lambda:observed+timedelta(hours=1))
        assert get_ipam_reconciliation()["never_observed"]==[]
    raw_arp(observed+timedelta(seconds=30))
    discovery.run_ipam_discovery_projection()
    mapped=discovery.list_discovered_endpoints(kind="ip")["items"][0]
    assert mapped["registration_status"]=="registered" and mapped["scope_resolution"]=="manual_assertion"
    assert mapped["vrf_context_status"]=="explicit_global"
    with get_db_connection() as c:
        c.execute("UPDATE prefixes SET prefix='192.0.2.0/25' WHERE id=?",(prefix["id"],))
        c.commit()
    invalid=discovery.list_discovered_endpoints(kind="ip")["items"][0]
    assert invalid["scope_status"]=="scope_pending" and invalid["scope_assertion_status"]=="invalid"


def test_stale_dialog_observation_is_rejected_and_registration_rolls_back(isolated_db):
    seed()
    observed=datetime.now(timezone.utc)-timedelta(minutes=2)
    raw_arp(observed)
    discovery.run_ipam_discovery_projection()
    item=discovery.list_discovered_endpoints(kind="ip")["items"][0]
    prefix=create_subnet(prefix="192.0.2.0/24",site_id="discovery-site-a",tenant_id="tenant-default")
    raw_arp(observed+timedelta(seconds=30),mac=OTHER_MAC)
    discovery.run_ipam_discovery_projection()
    with pytest.raises(ValueError,match="observation_version_changed"):
        discovery.register_discovered_observation(observation_id=item["id"],subnet_id=prefix["id"],expected_observed_at=item["observed_at"],confirmed_scope=True,requested_by="reviewer")
    current=next(r for r in discovery.list_discovered_endpoints(kind="ip")["items"] if r["mac"]==OTHER_MAC)
    with get_db_connection() as c:
        c.execute("DELETE FROM arp_table WHERE device_id='gateway-a'")
        c.commit()
    with pytest.raises(ValueError,match="observation_no_longer_in_source_snapshot"):
        discovery.register_discovered_observation(observation_id=current["id"],subnet_id=prefix["id"],expected_observed_at=current["observed_at"],confirmed_scope=True,requested_by="reviewer")
    with get_db_connection() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM ip_addresses").fetchone()["n"]==0
        assert c.execute("SELECT COUNT(*) AS n FROM ipam_discovery_scope_assertions").fetchone()["n"]==0


def test_calibration_changes_only_mac_and_checks_current_value(isolated_db):
    seed()
    observed=datetime.now(timezone.utc)-timedelta(seconds=10)
    raw_arp(observed)
    mark_run(observed)
    discovery.run_ipam_discovery_projection()
    prefix=create_subnet(prefix="192.0.2.0/24",site_id="discovery-site-a",tenant_id="tenant-default")
    address=create_address(prefix["id"],address="192.0.2.10",hostname="real-pc",mac_address=OTHER_MAC,status="active")
    item=discovery.list_discovered_endpoints(kind="ip")["items"][0]
    assert item["calibration_safe"]
    with pytest.raises(ValueError):
        discovery.calibrate_ipam_mac(observation_id=item["id"],ipam_address_id=address["id"],expected_observed_at=item["observed_at"],expected_mac_address="wrong",confirmed=True)
    discovery.calibrate_ipam_mac(observation_id=item["id"],ipam_address_id=address["id"],expected_observed_at=item["observed_at"],expected_mac_address=OTHER_MAC,confirmed=True)
    with get_db_connection() as c:
        record=dict(c.execute("SELECT * FROM ip_addresses WHERE id=?",(address["id"],)).fetchone())
        assert record["mac_address"]==MAC and record["hostname"]=="real-pc"


def test_absence_requires_all_responsible_sources_and_distinct_runs(isolated_db):
    seed()
    now=datetime.now(timezone.utc)
    prefix=create_subnet(prefix="192.0.2.0/24",site_id="discovery-site-a",tenant_id="tenant-default",gateway_device_id="gateway-a")
    address=create_address(prefix["id"],address="192.0.2.10",status="active")
    with get_db_connection() as c:
        c.execute("UPDATE ip_addresses SET created_at=? WHERE id=?",((now-timedelta(days=12)).isoformat(),address["id"]))
        c.commit()
    evidence(now-timedelta(days=10),"positive")
    for index,days in enumerate((6,3,0)):
        when=now-timedelta(days=days,minutes=2)
        evidence(when,f"missing-{index}",ip=None)
    mark_run(now-timedelta(minutes=2),run="missing-2",count=0)
    result=get_ipam_reconciliation()
    assert len(result["stale_ip_addresses"])==1
    assert result["stale_ip_addresses"][0]["miss_count"]==3
    seed("gateway-b")
    with get_db_connection() as c:
        c.execute("UPDATE prefixes SET gateway_device_id='gateway-b' WHERE id=?",(prefix["id"],))
        c.commit()
    result=get_ipam_reconciliation()
    assert result["stale_ip_addresses"]==[] and result["unavailable"]


def test_retention_keeps_latest_source_even_when_old(isolated_db):
    seed()
    now=datetime.now(timezone.utc)
    latest=evidence(now-timedelta(days=100),"latest-old")
    older=evidence(now-timedelta(days=110),"older-old")
    discovery.run_ipam_discovery_projection()
    with get_db_connection() as c:
        assert c.execute("SELECT id FROM ipam_discovery_observations WHERE id=?",(latest,)).fetchone()
        assert c.execute("SELECT id FROM ipam_discovery_observations WHERE id=?",(older,)).fetchone() is None


def test_registered_only_inventory_excludes_unregistered_observations(isolated_db):
    seed()
    raw_arp(datetime.now(timezone.utc)-timedelta(minutes=1))
    discovery.run_ipam_discovery_projection()
    prefix=create_subnet(prefix="192.0.2.0/24",site_id="discovery-site-a",tenant_id="tenant-default",gateway="192.0.2.1")
    create_address(prefix["id"],address="192.0.2.20",source_type="interface_collection",status="active")
    result=list_ip_inventory(registered_only=True,page_size=100)
    assert [r["address"] for r in result["items"]]==["192.0.2.20"]
    assert result["summary"]["discovered"]==0
