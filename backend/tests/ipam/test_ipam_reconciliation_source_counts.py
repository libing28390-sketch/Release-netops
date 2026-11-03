from __future__ import annotations

import hashlib
import ipaddress
from datetime import datetime, timedelta, timezone

from database import get_db_connection
from services.cmdb_snapshot_service import begin_snapshot_attempt, complete_snapshot
from services.ipam_service import create_address, create_subnet, get_ipam_reconciliation
from services.ipam_discovery_service import _recent_minutes


def _seed_reconciliation_device() -> None:
    with get_db_connection() as conn:
        conn.execute("INSERT INTO tenants (id, name) VALUES ('tenant-default', 'Default') ON CONFLICT(id) DO NOTHING")
        conn.execute(
            "INSERT INTO sites (id, site_code, site_name) VALUES ('recon-source-site', 'RECON-SOURCE', 'Reconciliation Site') ON CONFLICT(id) DO NOTHING"
        )
        conn.execute(
            "INSERT INTO devices (id, hostname, tenant_id, site_id, status) VALUES ('recon-source-device', 'RECON-SW', 'tenant-default', 'recon-source-site', 'online')"
        )
        conn.commit()


def _publish_snapshot_ip(address: str) -> None:
    attempt = begin_snapshot_attempt('recon-source-device', 'interface_inventory')
    observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO cmdb_device_interface_observations (
                   device_id, normalized_interface_name, interface_name, description,
                   admin_status, oper_status, ip_address, ip_prefix_length,
                   interface_type, generation, observed_at, run_id, metadata_json
               ) VALUES (?, 'vlaninterface10', 'Vlan-interface10', '', 'up', 'up', ?, 24,
                         'svi', ?, ?, ?, '{}')""",
            ('recon-source-device', address, attempt['generation'], observed_at, attempt['run_id']),
        )
        assert complete_snapshot(
            conn,
            attempt,
            observed_at=observed_at,
            transport='ssh',
            record_count=1,
        )
        conn.commit()
    # A newer attempt is running but has not succeeded; reconciliation's source
    # count must remain fenced to the previous successful generation.
    begin_snapshot_attempt('recon-source-device', 'interface_inventory')


def _insert_endpoint(address: str, *, seen_at: str, active: int) -> None:
    if not active:
        _insert_legacy_endpoint_only(address, seen_at=seen_at, active=active)
        return
    with get_db_connection() as conn:
        normalized = str(ipaddress.ip_address(address))
        source_version = f"test:{normalized}:{seen_at}:{active}"
        digest = hashlib.sha256(source_version.encode()).hexdigest()[:24]
        snapshot_id = f"recon-snapshot-{digest}"
        observation_id = f"recon-observation-{digest}"
        identity = hashlib.sha256(f"arp|recon-source-device|tenant-default|recon-source-site||{normalized}|00:11:22:33:44:55".encode()).hexdigest()
        projected_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO ipam_discovery_snapshots (
                   id, collector, device_id, source_device_name, tenant_id, site_id, vrf_id,
                   vrf_context_status, scope_status, source_run_id, source_version,
                   source_status, coverage_status, coverage_complete, coverage_reason,
                   entry_count, observed_at, projected_at
               ) VALUES (?, 'arp', 'recon-source-device', 'RECON-SW', 'tenant-default',
                         'recon-source-site', '', 'explicit_global', 'resolved', '', ?,
                         'success', 'unavailable', 0, 'test_positive_only', 1, ?, ?)""",
            (snapshot_id, source_version, seen_at, projected_at),
        )
        conn.execute(
            """INSERT INTO ipam_discovery_observations (
                   id, snapshot_id, source_type, source_device_id, source_device_name,
                   tenant_id, site_id, vrf_id, vrf_context_status, scope_status,
                   ip, mac, interface_name, vlan, source_identity_key,
                   source_observed_at, timestamp_status, projected_at
               ) VALUES (?, ?, 'arp', 'recon-source-device', 'RECON-SW', 'tenant-default',
                         'recon-source-site', '', 'explicit_global', 'resolved', ?,
                         '00:11:22:33:44:55', 'Vlan-interface10', '100', ?, ?, 'valid', ?)""",
            (observation_id, snapshot_id, normalized, identity, seen_at, projected_at),
        )
        conn.execute(
            """INSERT INTO network_endpoints (
                   id, ip, mac, hostname, switch_id, switch_port, vrf, site,
                   first_seen, last_seen, is_active
               ) VALUES (?, ?, '00:11:22:33:44:55', ?, 'recon-source-device',
                         'Vlan-interface10', '', 'recon-source-site', ?, ?, ?)""",
            (f'legacy-endpoint-{normalized}', normalized, normalized, seen_at, seen_at, active),
        )
        conn.commit()


def _insert_legacy_endpoint_only(address: str, *, seen_at: str, active: int) -> None:
    """Legacy cache rows must not feed the rebuilt reconciliation input."""
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO network_endpoints (
                   id, ip, mac, hostname, switch_id, switch_port, vrf, site,
                   first_seen, last_seen, is_active
               ) VALUES (?, ?, '00:11:22:33:44:55', ?, 'recon-source-device',
                         'Vlan-interface10', '', 'recon-source-site', ?, ?, ?)""",
            (f'legacy-only-{address}', address, address, seen_at, seen_at, active),
        )
        conn.commit()


def test_reconciliation_summary_counts_comparable_sources_and_keeps_snapshot_out_of_findings(isolated_db) -> None:
    del isolated_db
    _seed_reconciliation_device()
    prefix = create_subnet(
        prefix='192.0.2.0/24', tenant_id='tenant-default', site_id='recon-source-site',
    )
    create_address(prefix['id'], address='192.0.2.10', status='active')
    create_address(prefix['id'], address='192.0.2.11', status='available')

    now = datetime.now(timezone.utc)
    _insert_endpoint('192.0.2.10', seen_at=now.isoformat(), active=1)
    _insert_endpoint('192.0.2.20', seen_at=(now - timedelta(minutes=_recent_minutes() + 1)).isoformat(), active=1)
    _insert_endpoint('192.0.2.30', seen_at=now.isoformat(), active=0)
    _insert_legacy_endpoint_only('192.0.2.40', seen_at=now.isoformat(), active=1)
    _publish_snapshot_ip('198.51.100.10')

    result = get_ipam_reconciliation()
    summary = result['summary']
    assert summary['ipam_address_record_count'] == 2
    assert summary['allocated_ipam_address_count'] == 1
    assert summary['active_endpoint_count'] == 1
    assert summary['endpoint_cache_fresh'] is True
    assert summary['latest_active_endpoint_seen']
    assert summary['interface_snapshot_ip_count'] == 1
    assert result['undocumented_endpoints'] == []
    assert result['stale_ip_addresses'] == []
    assert result['mismatched_endpoints'] == []


def test_reconciliation_summary_distinguishes_no_comparable_data_from_snapshot_evidence(isolated_db) -> None:
    del isolated_db
    _seed_reconciliation_device()
    now = datetime.now(timezone.utc)
    # A fresh inactive endpoint must not make the current-comparison cache
    # appear healthy while the only active endpoint is outside the window.
    _insert_legacy_endpoint_only('203.0.113.20', seen_at=now.isoformat(), active=0)
    _insert_endpoint('203.0.113.21', seen_at=(now - timedelta(minutes=_recent_minutes() + 1)).isoformat(), active=1)
    _publish_snapshot_ip('203.0.113.10')

    result = get_ipam_reconciliation()
    summary = result['summary']
    assert summary['ipam_address_record_count'] == 0
    assert summary['allocated_ipam_address_count'] == 0
    assert summary['active_endpoint_count'] == 0
    assert summary['endpoint_cache_fresh'] is False
    assert summary['latest_endpoint_seen']
    assert summary['latest_active_endpoint_seen'] == ''
    assert summary['interface_snapshot_ip_count'] == 1
    assert result['undocumented_endpoints'] == []
    assert result['stale_ip_addresses'] == []
    assert result['mismatched_endpoints'] == []
