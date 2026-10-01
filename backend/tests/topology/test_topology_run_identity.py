from __future__ import annotations

import json
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.interface_utils import normalize_interface_name
from database import get_db_connection
from services.collection_status_service import record_collection_result
from services.topology_aggregation_inventory_service import persist_snmp_aggregation_inventory
from services.topology_lldp_snapshot_service import (
    begin_lldp_snapshot_attempt,
    lldp_snapshot_versions,
    load_complete_lldp_snapshot,
    publish_completed_lldp_snapshot,
)
from services.topology_service import (
    _build_target_device_identity_indexes,
    _NeighborCollectionBatch,
    _load_target_device_identity_rows,
    _match_target_device_with_evidence,
    _refresh_run_observation_identities,
    _replace_device_observations,
    decorate_topology_link_evidence,
    discover_device_neighbors,
    get_current_links,
    get_unmanaged_neighbors,
    rebuild_links_from_observations,
)


def _device(name, management_ip, *, tenant='tenant-run-test', asset_hostname=None):
    device = {'id': name, 'hostname': name, 'sys_name': name, 'ip_address': management_ip,
              'platform': 'h3c_comware', 'tenant_id': tenant}
    asset_id = f'{name}-asset' if asset_hostname else None
    device['asset_id'] = asset_id
    conn = get_db_connection()
    try:
        if asset_id:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT INTO physical_assets
                   (id, asset_type, hostname, management_ip, created_at, updated_at)
                   VALUES (?, 'network_device', ?, ?, ?, ?)""",
                (asset_id, asset_hostname, management_ip, now, now),
            )
        conn.execute(
            'INSERT INTO devices (id, asset_id, hostname, sys_name, ip_address, platform, tenant_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (name, asset_id, name, name, management_ip, device['platform'], tenant),
        )
        conn.commit()
    finally:
        conn.close()
    return device


def _observation(target, ip, port, target_port=None):
    return {
        'source_port_raw': port, 'source_port_normalized': normalize_interface_name(port).lower(),
        'neighbor_name_raw': target, 'neighbor_name_normalized': target.lower(),
        'neighbor_ip_address': ip,
        'target_port_raw': target_port or port,
        'target_port_normalized': normalize_interface_name(target_port or port).lower(),
        'protocol': 'lldp', 'confidence': 0.9,
        'raw_payload_json': json.dumps({'_collection_sources': ['snmp', 'ssh'], 'confidence': 0.9}),
    }


def _snapshot(device, run_id, ips, observations=(), *, identity_status='success', aggregation_snapshot=None):
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO topology_discovery_runs (id, started_at) VALUES (?, ?) ON CONFLICT(id) DO NOTHING",
            (run_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            "INSERT INTO topology_discovery_run_devices (id, run_id, device_id) VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING",
            (f'{run_id}-{device["id"]}', run_id, device['id']),
        )
        conn.commit()
    finally:
        conn.close()
    marker = begin_lldp_snapshot_attempt(device, lldp_snapshot_versions(device))
    if aggregation_snapshot is not None:
        assert persist_snmp_aggregation_inventory(device, aggregation_snapshot, snapshot_generation=marker['generation'])['members'] == 4
    _replace_device_observations(device, list(observations), run_id, snapshot_generation=marker['generation'])
    record_collection_result(
        device['id'], 'topology_lldp', status='success' if observations else 'no_neighbors',
        coverage_total=len(observations), metadata={
            'run_id': run_id, 'snapshot_generation': marker['generation'],
            'local_identity': {'status': identity_status, 'ip_addresses': ips, 'collection_sources': ['snmp']},
            'protocol_results': {'snmp': {'status': 'success'}, 'ssh': {'status': 'success'}},
        },
    )
    return marker


def _indexes(tenant, run_id):
    conn = get_db_connection()
    try:
        return _build_target_device_identity_indexes(
            _load_target_device_identity_rows(conn, tenant_id=tenant, discovery_run_id=run_id)
        )
    finally:
        conn.close()


def test_full_lab_rebinds_34_observations_into_11_device_pairs_without_extra_devices(isolated_db):
    # IP ownership and LLDP are independent device outputs. No name/IP mapping
    # is inferred from the neighbor rows themselves.
    ip_ownership = {
        'S1': ['10.254.0.1', '10.254.100.4', '10.254.13.1', '10.254.14.1'],
        'S2': ['10.254.0.2', '10.254.100.5', '10.254.23.1', '10.254.24.1'],
        'S3': ['10.254.0.3', '10.254.13.2', '10.254.23.2', '10.254.35.1'],
        'S4': ['10.254.0.4', '10.254.14.2', '10.254.24.2', '10.254.46.1'],
        'S5': ['10.254.0.5', '10.254.35.2'], 'S6': ['10.254.0.6', '10.254.46.2'],
        'F9': ['192.168.56.11', '10.254.100.2', '10.254.252.1'],
        'F10': ['192.168.56.12', '10.254.100.3', '10.254.252.2'],
    }
    devices = {name: _device(name, ips[0]) for name, ips in ip_ownership.items()}
    neighbors = {name: [] for name in devices}

    def pair(a, b, ip_a, ip_b, port_a, port_b=None):
        neighbors[a].append(_observation(b, ip_b, port_a, port_b))
        neighbors[b].append(_observation(a, ip_a, port_b or port_a, port_a))

    pair('S1', 'F9', '10.254.100.4', '10.254.100.2', 'GE1/0/1', 'GE1/0/0')
    pair('S2', 'F10', '10.254.100.5', '10.254.100.3', 'GE1/0/1', 'GE1/0/0')
    pair('F9', 'F10', '10.254.252.1', '10.254.252.2', 'GE1/0/2')
    for port in range(49, 53):
        pair('S1', 'S2', '10.254.100.4', '10.254.100.5', f'XGE1/0/{port}')
    pair('S1', 'S3', '10.254.13.1', '10.254.13.2', 'FortyGigE1/0/53')
    pair('S1', 'S4', '10.254.14.1', '10.254.14.2', 'FortyGigE1/0/54')
    pair('S2', 'S4', '10.254.24.1', '10.254.24.2', 'FortyGigE1/0/53')
    pair('S2', 'S3', '10.254.23.1', '10.254.23.2', 'FortyGigE1/0/54')
    for port in range(1, 5):
        pair('S3', 'S4', '', '', f'GE1/0/{port}')
    pair('S3', 'S5', '10.254.35.1', '10.254.35.2', 'XGE1/0/49')
    pair('S4', 'S6', '10.254.46.1', '10.254.46.2', 'XGE1/0/49')
    assert sum(map(len, neighbors.values())) == 34
    # Reverse order proves a reporter need not wait for its target's facts.
    for name in reversed(list(devices)):
        aggregation_snapshot = None
        if name in {'S1', 'S2', 'S3', 'S4'}:
            core = name in {'S1', 'S2'}
            parent = 'Bridge-Aggregation12' if core else 'Route-Aggregation34'
            ports = range(49, 53) if core else range(1, 5)
            speed = 10000 if core else 1000
            aggregation_snapshot = {
                'status': 'success', 'source': 'snmp', 'membership_source': 'dot3adAggPortAttachedAggID',
                'parents': [{'interface_name': parent, 'if_index': 5130, 'oper_status': 'up', 'speed_mbps': speed * 4}],
                'records': [{
                    'aggregation_name': parent, 'member_interface': f'{"XGE" if core else "GE"}1/0/{port}',
                    'member_if_index': port + 1, 'member_oper_status': 'up', 'member_speed_mbps': speed,
                } for port in ports],
            }
        _snapshot(devices[name], 'lab-run', ip_ownership[name], neighbors[name], aggregation_snapshot=aggregation_snapshot)
    conn = get_db_connection()
    try:
        # Simulate the old management-IP-only result at the start of finalization.
        conn.execute("UPDATE topology_observations SET target_device_id = NULL, match_status = 'unmatched' WHERE neighbor_ip_address <> ''")
        conn.commit()
    finally:
        conn.close()
    with patch('services.topology_lldp_snapshot_service.publish_completed_lldp_snapshot') as publish:
        summary = _refresh_run_observation_identities('lab-run')
    assert summary == {'matched': 34, 'hostname_mismatch': 0, 'ambiguous': 0, 'unmatched': 0}
    assert publish.call_count == 8
    assert all(call.kwargs['refresh_from_postgres'] is True for call in publish.call_args_list)
    assert rebuild_links_from_observations() == 11  # 9 physical edges and two four-member LAGs.
    links = decorate_topology_link_evidence(get_current_links())
    aggregations = [link for link in links if link['link_kind'] == 'aggregation']
    assert len(aggregations) == 2
    assert all(link['member_count'] == len(link['members']) == 4 for link in aggregations)
    assert len({frozenset((link['source_device_id'], link['target_device_id'])) for link in links}) == 11
    assert all(link['evidence_status'] == 'bidirectional_confirmed' for link in links)
    assert get_unmanaged_neighbors()['unmanaged_nodes'] == []
    conn = get_db_connection()
    try:
        assert conn.execute('SELECT COUNT(*) FROM devices').fetchone()[0] == 8
        assert conn.execute("SELECT COUNT(*) FROM topology_observations WHERE match_method = 'run_local_ip'").fetchone()[0] == 26
        assert conn.execute('SELECT SUM(coverage_supported) FROM device_collection_status').fetchone()[0] == 34
    finally:
        conn.close()


@pytest.mark.parametrize('invalid_fact', ['old_run', 'old_generation', 'failed_identity', 'other_tenant'])
def test_secondary_ip_requires_current_run_device_owned_evidence(isolated_db, invalid_fact):
    source = _device('SOURCE', '10.0.0.1')
    target = _device('TARGET', '10.0.0.2', tenant='other-tenant' if invalid_fact == 'other_tenant' else source['tenant_id'])
    target_run = 'old-run' if invalid_fact == 'old_run' else 'current-run'
    _snapshot(target, target_run, ['10.1.1.2'], identity_status='unavailable' if invalid_fact == 'failed_identity' else 'success')
    if invalid_fact == 'old_generation':
        begin_lldp_snapshot_attempt(target, lldp_snapshot_versions(target))
    indexes = _indexes(source['tenant_id'], 'current-run')
    result = _match_target_device_with_evidence(None, 'TARGET', '10.1.1.2', device_indexes=indexes)
    assert result['device'] is None
    assert result['method'] == 'management_ip_not_found'


def test_duplicate_owned_ip_including_management_collision_stays_ambiguous(isolated_db):
    target = _device('TARGET', '10.0.0.2')
    collision = _device('COLLISION', '10.1.1.2')
    _snapshot(target, 'current-run', ['10.1.1.2'])
    result = _match_target_device_with_evidence(None, 'TARGET', '10.1.1.2', device_indexes=_indexes(target['tenant_id'], 'current-run'))
    assert result['status'] == 'ambiguous'
    assert {item['device_id'] for item in result['candidates']} == {target['id'], collision['id']}


def test_single_sided_observation_uses_target_with_empty_lldp_snapshot_and_keeps_name_mismatch(isolated_db):
    source = _device('SOURCE', '10.0.0.1')
    target = _device('TARGET', '10.0.0.2')
    _snapshot(source, 'current-run', ['10.0.0.1'], [_observation('WRONG-NAME', '10.1.1.2', 'GE1/0/1')])
    _snapshot(target, 'current-run', ['10.1.1.2'])
    with patch('services.topology_lldp_snapshot_service.publish_completed_lldp_snapshot'):
        result = _refresh_run_observation_identities('current-run')
    assert result['hostname_mismatch'] == 1
    assert result['unmatched'] == 0
    assert rebuild_links_from_observations() == 1
    link = get_current_links()[0]
    assert json.loads(link['metadata_json'])['reverse_seen'] is False
    assert get_unmanaged_neighbors()['unmanaged_nodes'] == []


def test_cli_observation_rebinds_by_current_asset_hostname_when_reported_ip_conflicts(isolated_db):
    source = _device('CLI-SOURCE', '10.0.0.1', asset_hostname='CLI-SOURCE')
    target = _device('ASSET-TARGET', '10.0.0.2', asset_hostname='S6850-4')
    _device('IP-OWNER', '10.0.0.3', asset_hostname='IP-OWNER')
    observation = _observation('S6850-4', '10.0.0.3', 'GE1/0/1')
    payload = json.loads(observation['raw_payload_json'])
    payload['_collection_sources'] = ['ssh']
    observation['raw_payload_json'] = json.dumps(payload)

    _snapshot(source, 'cli-asset-hostname-run', ['10.0.0.1'], [observation])
    conn = get_db_connection()
    try:
        stored = conn.execute(
            'SELECT target_device_id, match_method FROM topology_observations WHERE source_device_id = ?',
            (source['id'],),
        ).fetchone()
        assert stored['target_device_id'] == target['id']
        assert stored['match_method'] == 'cli_system_name_exact_asset_hostname'
        # Re-run binding from the persisted source marker: the IP belongs to a
        # different current asset, but CLI System Name remains authoritative.
        conn.execute(
            "UPDATE topology_observations SET target_device_id = NULL, match_status = 'unmatched' WHERE source_device_id = ?",
            (source['id'],),
        )
        conn.commit()
    finally:
        conn.close()

    with patch('services.topology_lldp_snapshot_service.publish_completed_lldp_snapshot'):
        summary = _refresh_run_observation_identities('cli-asset-hostname-run')
    assert summary['matched'] == 1
    assert summary['unmatched'] == 0
    assert rebuild_links_from_observations() == 1
    link = get_current_links()[0]
    assert {link['source_device_id'], link['target_device_id']} == {source['id'], target['id']}


def test_cli_name_mismatch_is_diagnostic_only_and_does_not_reuse_previous_binding(isolated_db):
    source = _device('CLI-SOURCE', '10.0.0.1', asset_hostname='CLI-SOURCE')
    target = _device('OLD-TARGET-NAME', '10.0.0.2', asset_hostname='OLD-TARGET-NAME')
    observation = _observation('OLD-TARGET-NAME', '10.0.0.2', 'GE1/0/1')
    observation['raw_payload_json'] = json.dumps({'_collection_sources': ['ssh']})
    _snapshot(source, 'cli-name-change-run', [], [observation])
    assert rebuild_links_from_observations() == 1

    # Only the current CMDB name may authorize a CLI binding. The retained
    # device name, matching IP, and previously bound observation cannot do so.
    with get_db_connection() as conn:
        conn.execute('UPDATE physical_assets SET hostname = ? WHERE id = ?', ('NEW-CMDB-NAME', target['asset_id']))
        conn.commit()
    with patch('services.topology_lldp_snapshot_service.publish_completed_lldp_snapshot'):
        summary = _refresh_run_observation_identities('cli-name-change-run')
    assert summary['unmatched'] == 1
    assert summary['matched'] == 0
    rebuild_links_from_observations()
    assert get_current_links(include_stale=False) == []
    diagnostics = get_unmanaged_neighbors()
    assert diagnostics['resolved_links'] == []
    assert len(diagnostics['unmanaged_nodes']) == 1
    assert diagnostics['unmanaged_nodes'][0]['match_reason_code'] == 'cli_system_name_not_found_in_cmdb'
    with get_db_connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM devices').fetchone()[0] == 2


def test_superseded_source_is_not_rebound_and_read_projection_uses_run_identity(isolated_db):
    source = _device('SOURCE', '10.0.0.1')
    target = _device('TARGET', '10.0.0.2')
    _snapshot(source, 'current-run', ['10.0.0.1'], [_observation('TARGET', '10.1.1.2', 'GE1/0/1')])
    _snapshot(target, 'current-run', ['10.1.1.2'])
    assert len(get_unmanaged_neighbors()['resolved_links']) == 1
    begin_lldp_snapshot_attempt(source, lldp_snapshot_versions(source))
    with patch('services.topology_lldp_snapshot_service.publish_completed_lldp_snapshot'):
        summary = _refresh_run_observation_identities('current-run')
    assert sum(summary.values()) == 0
    conn = get_db_connection()
    try:
        assert conn.execute('SELECT target_device_id FROM topology_observations').fetchone()[0] is None
    finally:
        conn.close()


def test_republish_after_rebinding_overwrites_cached_unresolved_neighbor(isolated_db):
    source = _device('SOURCE', '10.0.0.1')
    target = _device('TARGET', '10.0.0.2')
    marker = _snapshot(source, 'current-run', ['10.0.0.1'], [_observation('TARGET', '10.1.1.2', 'GE1/0/1')])
    cache = MagicMock()
    cache.backend = 'redis'
    cache.scope_hash.return_value = 'scope'
    cache.build_key.return_value = 'snapshot'
    cache.get_json.return_value = None
    cache.set_json.return_value = True
    cache.policy.return_value.retain_seconds = 1000
    first = load_complete_lldp_snapshot(source, cache=cache)
    assert first['neighbors'][0]['neighbor_id'] == ''
    cache.get_json.return_value = first
    _snapshot(target, 'current-run', ['10.1.1.2'])
    with patch('services.topology_lldp_snapshot_service.publish_completed_lldp_snapshot'):
        _refresh_run_observation_identities('current-run')
    assert publish_completed_lldp_snapshot(source, generation=marker['generation'], cache=cache, refresh_from_postgres=True)
    refreshed = cache.set_json.call_args.args[1]
    assert refreshed['neighbors'][0]['neighbor_id'] == target['id']


@pytest.mark.parametrize('identity_failed', [False, True])
def test_ssh_lldp_survives_snmp_failure_and_persists_this_run_local_identity(identity_failed):
    device = {'id': 'SOURCE', 'hostname': 'SOURCE', 'ip_address': '10.0.0.1', 'tenant_id': 'tenant-test'}
    batch = _NeighborCollectionBatch([_observation('TARGET', '10.1.1.2', 'GE1/0/1')], collection_status='success')
    batch.protocol_results = {'snmp': {'status': 'failed', 'detail': 'timeout'}, 'ssh': {'status': 'success'}}
    local_identity = {'status': 'success', 'ip_addresses': ['10.1.1.1'], 'collection_sources': ['ssh']}
    identity_collector = AsyncMock(side_effect=RuntimeError('unavailable') if identity_failed else None, return_value=local_identity)
    with (
        patch('services.topology_service._get_device', return_value=device),
        patch('services.topology_service._collector_credentials_for_device', return_value={
            'snmp': {'configured': True}, 'ssh': {'username': 'test-operator', 'password': 'synthetic-only'},
        }),
        patch('services.topology_service._collect_device_observations', new=AsyncMock(return_value=(batch, 'ssh'))),
        patch('services.topology_service._sync_aggregation_inventory', return_value={'parents': 0, 'members': 0}),
        patch('services.topology_lldp_snapshot_service.lldp_snapshot_versions', return_value={}),
        patch('services.topology_lldp_snapshot_service.begin_lldp_snapshot_attempt', return_value={'generation': 7}),
        patch('services.topology_lldp_snapshot_service.publish_completed_lldp_snapshot', return_value=True),
        patch('services.topology_local_identity_service.collect_topology_local_identity', new=identity_collector),
        patch('services.topology_service._replace_device_observations', return_value={
            'matched': 0, 'hostname_mismatch': 0, 'ambiguous': 0, 'unmatched': 1,
        }),
        patch('services.topology_service.record_collection_result') as record,
    ):
        result = asyncio.run(discover_device_neighbors('SOURCE', 'current-run', rebuild_links=False))
    assert result['observations_count'] == 1
    assert result['collection_status'] == 'partial'
    metadata = record.call_args.kwargs['metadata']
    assert metadata['run_id'] == 'current-run'
    assert metadata['snapshot_generation'] == 7
    assert metadata['local_identity']['status'] == ('unavailable' if identity_failed else 'success')
    assert metadata['protocol_results']['snmp']['status'] == 'failed'
    identity_collector.assert_awaited_once()


@pytest.mark.parametrize('hostname_failed', [False, True])
@pytest.mark.parametrize('aggregation_failed', [False, True])
def test_snmp_hostname_refresh_precedes_observations_without_cli(hostname_failed, aggregation_failed):
    device = {'id': 'SOURCE', 'hostname': '10.0.0.1', 'ip_address': '10.0.0.1', 'tenant_id': 'tenant-test'}
    batch = _NeighborCollectionBatch([_observation('TARGET', '10.0.0.2', 'GE1/0/1')], collection_status='success')
    batch.protocol_results = {'snmp': {'status': 'success'}, 'ssh': {'status': 'not_attempted'}}
    verified_name = {'status': 'synced', 'changed': True, 'hostname': 'S6850-1', 'sys_name': 'S6850-1'}
    hostname_collector = AsyncMock(
        side_effect=RuntimeError('unavailable') if hostname_failed else None,
        return_value=verified_name,
    )
    aggregation_collector = AsyncMock(
        side_effect=RuntimeError('unavailable') if aggregation_failed else None,
        return_value={'status': 'success', 'source': 'snmp', 'parents': 1, 'members': 4},
    )
    with (
        patch('services.topology_service._get_device', return_value=device),
        patch('services.topology_service._collector_credentials_for_device', return_value={
            'snmp': {'configured': True}, 'ssh': {'username': 'test-operator', 'password': 'synthetic-only'},
        }),
        patch('services.topology_service._collect_device_observations', new=AsyncMock(return_value=(batch, 'snmp'))),
        patch('services.topology_service._sync_aggregation_inventory') as aggregation_cli,
        patch('services.topology_aggregation_inventory_service.sync_snmp_aggregation_inventory', new=aggregation_collector),
        patch('services.topology_lldp_snapshot_service.lldp_snapshot_versions', return_value={}),
        patch('services.topology_lldp_snapshot_service.begin_lldp_snapshot_attempt', return_value={'generation': 7}),
        patch('services.topology_lldp_snapshot_service.publish_completed_lldp_snapshot', return_value=True),
        patch('services.topology_hostname_service.refresh_topology_hostname', new=hostname_collector),
        patch('services.topology_local_identity_service.collect_topology_local_identity', new=AsyncMock(return_value={
            'status': 'success', 'ip_addresses': ['10.0.0.1'], 'collection_sources': ['snmp'],
        })),
        patch('services.topology_service._replace_device_observations', return_value={
            'matched': 1, 'hostname_mismatch': 0, 'ambiguous': 0, 'unmatched': 0,
        }) as replace_observations,
        patch('services.topology_service.record_collection_result') as record,
    ):
        result = asyncio.run(discover_device_neighbors('SOURCE', 'current-run', rebuild_links=False))

    expected_name = '10.0.0.1' if hostname_failed else 'S6850-1'
    assert result['collection_status'] == 'success'
    assert result['observations_count'] == 1
    assert result['hostname'] == expected_name
    assert replace_observations.call_args.args[0]['hostname'] == expected_name
    assert record.call_args.kwargs['metadata']['hostname_identity']['status'] == ('unavailable' if hostname_failed else 'synced')
    hostname_collector.assert_awaited_once()
    assert hostname_collector.call_args.kwargs['snapshot_generation'] == 7
    aggregation_cli.assert_not_called()
    aggregation_collector.assert_awaited_once()
    assert aggregation_collector.call_args.kwargs['snapshot_generation'] == 7
    aggregation = record.call_args.kwargs['metadata']['aggregation']
    assert aggregation['status'] == ('unavailable' if aggregation_failed else 'success')
    assert aggregation['members'] == (0 if aggregation_failed else 4)
