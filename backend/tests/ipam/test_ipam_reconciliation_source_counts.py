from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta, timezone

from database import get_db_connection
from services.cmdb_snapshot_service import begin_snapshot_attempt, complete_snapshot
from services.collector_sweep_state_service import reserve_collector_sweep_batch, complete_collector_sweep
from services.collection_status_service import record_collection_results
from services.ipam_address_space_service import create_address_space
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


def _test_global_space_id() -> str:
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id FROM ipam_address_spaces WHERE security_tenant_id='tenant-default' AND name='Reconciliation Source Counts Test Global' AND kind='global' LIMIT 1"
        ).fetchone()
    if row:
        return str(row['id'])
    return str(create_address_space(
        name='Reconciliation Source Counts Test Global',
        kind='global',
        vrf_id=None,
        security_tenant_id='tenant-default',
    )['id'])


def _publish_snapshot_ip(
    address: str,
    *,
    interface: str = 'Vlan-interface10',
    context_type: str = 'unknown',
    local_context_key: str = '',
) -> None:
    attempt = begin_snapshot_attempt('recon-source-device', 'interface_inventory')
    observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO cmdb_device_interface_observations (
                   device_id, normalized_interface_name, interface_name, description,
                   admin_status, oper_status, ip_address, ip_prefix_length,
                   interface_type, generation, observed_at, run_id, metadata_json
               ) VALUES (?, ?, ?, '', 'up', 'up', ?, 24,
                         'svi', ?, ?, ?, '{}')""",
            ('recon-source-device', interface.lower(), interface, address,
             attempt['generation'], observed_at, attempt['run_id']),
        )
        conn.execute(
            """INSERT INTO cmdb_device_interface_address_observations (
                   device_id, normalized_interface_name, interface_name,
                   context_source, context_type, local_context_key, local_context_name,
                   ip_address, ip_prefix_length, generation, observed_at, run_id, metadata_json
               ) VALUES (?, ?, ?, 'cli', ?, ?, ?, ?::inet, 24, ?, ?, ?, '{}'::jsonb)""",
            (
                'recon-source-device', interface.lower(), interface,
                context_type, local_context_key, local_context_key,
                address, attempt['generation'], observed_at, attempt['run_id'],
            ),
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


def _insert_endpoint(address: str, *, seen_at: str, active: int, vrf: str = '') -> None:
    with get_db_connection() as conn:
        normalized = str(ipaddress.ip_address(address))
        conn.execute(
            """INSERT INTO network_endpoints (
                   id, ip, mac, hostname, switch_id, switch_port, vrf, site,
                   first_seen, last_seen, is_active
               ) VALUES (?, ?, '00:11:22:33:44:55', ?, 'recon-source-device',
                         'Vlan-interface10', ?, 'recon-source-site', ?, ?, ?)""",
            (f'current-endpoint-{normalized}', normalized, normalized, vrf, seen_at, seen_at, active),
        )
        conn.commit()


def _insert_legacy_endpoint_only(address: str, *, seen_at: str, active: int) -> None:
    """Insert a current endpoint-cache row without discovery-ledger history."""
    _insert_endpoint(address, seen_at=seen_at, active=active)


def test_reconciliation_summary_counts_comparable_sources_and_keeps_snapshot_out_of_findings(isolated_db) -> None:
    del isolated_db
    _seed_reconciliation_device()
    prefix = create_subnet(
        prefix='192.0.2.0/24', tenant_id='tenant-default', site_id='recon-source-site',
        address_space_id=_test_global_space_id(),
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
    assert summary['active_endpoint_count'] == 2
    assert summary['endpoint_cache_fresh'] is False
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


def test_reconciliation_uses_current_sources_and_never_queries_discovery_history(isolated_db, monkeypatch) -> None:
    from services import ipam_service

    _seed_reconciliation_device()
    global_space_id = _test_global_space_id()
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_device_routing_contexts (
                   id, device_id, context_source, context_type, local_context_key,
                   local_context_name, address_space_id, status, revision,
                   created_at, updated_at
               ) VALUES ('recon-context-global', 'recon-source-device', 'cli', 'global',
                         'Global', 'Global', ?, 'active', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (global_space_id,),
        )
        conn.commit()

    now = datetime.now(timezone.utc).isoformat()
    _insert_endpoint('203.0.113.50', seen_at=now, active=1, vrf='Global')
    _publish_snapshot_ip(
        '203.0.113.51', context_type='unknown', local_context_key='Global',
    )

    class HistoryReadGuard:
        def __init__(self, connection):
            self.connection = connection
            self.statements: list[str] = []

        def execute(self, statement, params=()):
            sql = str(statement).lower()
            assert 'ipam_discovery_observations' not in sql
            assert 'ipam_discovery_snapshots' not in sql
            self.statements.append(sql)
            return self.connection.execute(statement, params)

        def __getattr__(self, name):
            return getattr(self.connection, name)

    guards: list[HistoryReadGuard] = []

    def guarded_connection():
        guard = HistoryReadGuard(get_db_connection())
        guards.append(guard)
        return guard

    monkeypatch.setattr(ipam_service, 'get_db_connection', guarded_connection)
    first = ipam_service.get_ipam_reconciliation()
    assert first['summary']['active_endpoint_count'] == 1
    assert first['summary']['interface_snapshot_ip_count'] == 1
    assert {item['ip'] for item in first['undocumented_endpoints']} == {
        '203.0.113.50', '203.0.113.51',
    }
    assert first['unscoped'] == []

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES ('recon-context-tenant', 'Reconciliation Context Tenant') ON CONFLICT (id) DO NOTHING"
        )
        conn.execute(
            "INSERT INTO vrfs (id, vrf_name, tenant_id) VALUES ('recon-context-vrf', 'Reconciliation Context VRF', 'tenant-default')"
        )
        conn.commit()
    vrf_space = create_address_space(
        name='Reconciliation Context VRF Space',
        kind='vrf',
        vrf_id='recon-context-vrf',
        security_tenant_id='tenant-default',
    )
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_device_routing_contexts (
                   id, device_id, context_source, context_type, local_context_key,
                   local_context_name, address_space_id, status, revision,
                   created_at, updated_at
               ) VALUES ('recon-context-vrf-alias', 'recon-source-device', 'cli', 'vrf',
                         'Global', 'Global', ?, 'active', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (vrf_space['id'],),
        )
        conn.commit()

    with get_db_connection() as conn:
        from services.ipam_service import _current_cmdb_interface_ip_observations

        current_rows = _current_cmdb_interface_ip_observations(conn)
    assert len(current_rows) == 1
    assert current_rows[0]['local_context_key'] == 'Global'
    assert current_rows[0]['address_space_id'] is None

    ambiguous = ipam_service.get_ipam_reconciliation()
    assert ambiguous['undocumented_endpoints'] == []
    assert {item['reason'] for item in ambiguous['unscoped']} >= {
        'routing_context_mapping_ambiguous',
    }

    _publish_snapshot_ip(
        '203.0.113.52', interface='Vlan-interface11',
        context_type='unknown', local_context_key='',
    )
    with get_db_connection() as conn:
        from services.ipam_service import _current_cmdb_interface_ip_observations

        empty_key_rows = _current_cmdb_interface_ip_observations(conn)
    assert len(empty_key_rows) == 1
    assert empty_key_rows[0]['local_context_key'] == ''
    assert empty_key_rows[0]['address_space_id'] is None

    assert all(
        'ipam_discovery_observations' not in sql
        and 'ipam_discovery_snapshots' not in sql
        for guard in guards
        for sql in guard.statements
    )
    assert any('network_endpoints' in sql for guard in guards for sql in guard.statements)
    assert any('cmdb_device_interface_address_observations' in sql for guard in guards for sql in guard.statements)


def test_current_complete_sweep_miss_is_single_run_and_latest_interface_address_covers_it(isolated_db):
    _seed_reconciliation_device()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO vrfs (id, vrf_name, tenant_id) VALUES ('recon-current-vrf', 'RECON-CURRENT', 'tenant-default')"
        )
        conn.commit()
    vrf_space = create_address_space(
        name='Reconciliation Current VRF Space',
        kind='vrf',
        vrf_id='recon-current-vrf',
        security_tenant_id='tenant-default',
    )
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_device_routing_contexts (
                   id, device_id, context_source, context_type, local_context_key,
                   local_context_name, address_space_id, status, revision,
                   created_at, updated_at
               ) VALUES ('recon-current-context', 'recon-source-device', 'cli', 'vrf',
                         'Blue', 'Blue', ?, 'active', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (vrf_space['id'],),
        )
        conn.commit()
    prefix = create_subnet(
        prefix='192.0.2.0/24', tenant_id='tenant-default', site_id='recon-source-site',
        address_space_id=vrf_space['id'], gateway_device_id='recon-source-device',
    )
    address = create_address(prefix['id'], address='192.0.2.10', status='active')

    run_id = 'recon-current-complete-sweep'
    reserve_collector_sweep_batch('arp', total_candidates=1, batch_size=1, run_id=run_id)
    record_collection_results([{
        'device_id': 'recon-source-device',
        'collector': 'arp',
        'status': 'success',
        'source': 'arp_sweep',
        'coverage_total': 0,
        'coverage_supported': 1,
        'metadata': {'collection_run_id': run_id, 'entry_count': 0},
    }])
    complete_collector_sweep(
        'arp', run_id=run_id, successful_devices=1,
        failed_devices=0, collected_entries=0,
    )

    missing = get_ipam_reconciliation()
    assert [item['ipam_address_id'] for item in missing['stale_ip_addresses']] == [address['id']]
    stale_item = missing['stale_ip_addresses'][0]
    assert stale_item['last_observed_at'] == ''
    assert stale_item['last_checked_at']
    assert stale_item['miss_count'] == stale_item['required_misses'] == 1
    assert stale_item['stale_reason'] == 'not_observed_in_latest_complete_sweep'
    assert stale_item['current_sweep_run_id'] == run_id

    _publish_snapshot_ip(
        '192.0.2.10', interface='Vlan-interface10',
        context_type='vrf', local_context_key='Blue',
    )
    covered = get_ipam_reconciliation()
    assert covered['stale_ip_addresses'] == []
