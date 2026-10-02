from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from database import get_db_connection
from services.topology_lldp_snapshot_service import begin_lldp_snapshot_attempt
from services.topology_service import (
    _NeighborCollectionBatch,
    _collect_device_observations,
    _extract_observation_fields,
    _replace_device_observations,
    discover_device_neighbors,
)


ROW_LIMIT_OID = '1.3.6.1.2.1.31.1.1.1.1'
DEVICE = {
    'id': 'row-limit-source',
    'hostname': 'SOURCE',
    'ip_address': '10.0.0.1',
    'platform': 'h3c_comware',
    'tenant_id': 'tenant-row-limit',
}


def _neighbor(name='TARGET', port='GigabitEthernet1/0/1'):
    return {
        'source_port_raw': port,
        'neighbor_name_raw': name,
        'neighbor_ip_address': '',
        'target_port_raw': 'GigabitEthernet1/0/48',
        'protocol': 'lldp',
    }


def _truncated_batch():
    batch = _NeighborCollectionBatch([_neighbor()], 'partial')
    batch.truncated_oids = [ROW_LIMIT_OID]
    batch.max_rows = 10000
    return batch


def _credentials(*, ssh=False):
    return {
        'snmp': {'server': '10.0.0.1', 'community': 'synthetic-only', 'port': 161, 'version': '2c'},
        'ssh': {
            'username': 'test-operator' if ssh else '',
            'password': 'synthetic-only' if ssh else '',
            'enable_password': '',
        },
    }


@pytest.mark.parametrize('ssh_configured', [False, True])
def test_row_limit_retains_partial_neighbors_when_cli_cannot_complete(ssh_configured):
    with (
        patch('services.topology_service._collector_credentials_for_device', return_value=_credentials(ssh=ssh_configured)),
        patch('services.snmp_service.collect_snmp_lldp_neighbors', new=AsyncMock(return_value=_truncated_batch())),
        patch('drivers.ssh_compat.is_ssh_port_open', return_value=True),
        patch('services.topology_service._collect_neighbors_with_netmiko', new=AsyncMock(side_effect=RuntimeError('synthetic_ssh_failure'))) as cli,
    ):
        batch, method = asyncio.run(_collect_device_observations(dict(DEVICE)))

    assert method == 'snmp'
    assert batch.collection_status == 'partial'
    assert len(batch) == 1
    snmp = batch.protocol_results['snmp']
    assert snmp['status'] == 'partial'
    assert 'walk_row_limit=10000' in snmp['detail']
    assert f'truncated_oids={ROW_LIMIT_OID}' in snmp['detail']
    assert batch.protocol_results['ssh']['status'] == ('failed' if ssh_configured else 'not_configured')
    assert cli.await_count == int(ssh_configured)


def test_row_limit_attempts_cli_and_keeps_protocol_diagnostic_after_complete_fallback():
    complete_cli = _NeighborCollectionBatch([_neighbor(), _neighbor('OTHER', 'GigabitEthernet1/0/2')], 'success')
    with (
        patch('services.topology_service._collector_credentials_for_device', return_value=_credentials(ssh=True)),
        patch('services.snmp_service.collect_snmp_lldp_neighbors', new=AsyncMock(return_value=_truncated_batch())),
        patch('drivers.ssh_compat.is_ssh_port_open', return_value=True),
        patch('services.topology_service._collect_neighbors_with_netmiko', new=AsyncMock(return_value=(complete_cli, 'netmiko'))) as cli,
    ):
        batch, method = asyncio.run(_collect_device_observations(dict(DEVICE)))

    cli.assert_awaited_once()
    assert method == 'hybrid'
    assert batch.collection_status == 'success'
    assert len(batch) == 2
    assert batch.protocol_results['snmp']['status'] == 'partial'
    assert 'walk_row_limit=10000' in batch.protocol_results['snmp']['detail']
    assert batch.protocol_results['ssh']['status'] == 'success'


def test_ordinary_partial_keeps_existing_detail():
    partial = _NeighborCollectionBatch([_neighbor()], 'partial')
    with (
        patch('services.topology_service._collector_credentials_for_device', return_value=_credentials()),
        patch('services.snmp_service.collect_snmp_lldp_neighbors', new=AsyncMock(return_value=partial)),
    ):
        batch, _ = asyncio.run(_collect_device_observations(dict(DEVICE)))

    assert batch.protocol_results['snmp']['detail'] == 'SNMP LLDP MIB walk returned incomplete data'


def test_row_limit_discovery_preserves_unseen_old_observations(isolated_db, monkeypatch):
    monkeypatch.setenv('TOPOLOGY_AGGREGATION_DISCOVERY_ENABLED', '0')
    device = dict(DEVICE)
    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT INTO devices (id, hostname, ip_address, platform, tenant_id) VALUES (?, ?, ?, ?, ?)',
            (device['id'], device['hostname'], device['ip_address'], device['platform'], device['tenant_id']),
        )
        conn.commit()
    finally:
        conn.close()

    initial = begin_lldp_snapshot_attempt(device)
    previous = [_extract_observation_fields(item) for item in (
        _neighbor(), _neighbor('OLD-UNSEEN', 'GigabitEthernet1/0/2'),
    )]
    _replace_device_observations(device, previous, None, snapshot_generation=initial['generation'])

    with (
        patch('services.topology_service._collector_credentials_for_device', return_value=_credentials()),
        patch('services.snmp_service.collect_snmp_lldp_neighbors', new=AsyncMock(return_value=_truncated_batch())),
        patch('services.topology_lldp_snapshot_service.publish_completed_lldp_snapshot') as publish,
    ):
        result = asyncio.run(discover_device_neighbors(device['id'], None, rebuild_links=False))

    assert result['collection_status'] == 'partial'
    assert result['partial_data'] is True
    assert result['observations_count'] == 1
    assert 'walk_row_limit=10000' in result['protocol_results']['snmp']['detail']
    publish.assert_not_called()
    conn = get_db_connection()
    try:
        rows = conn.execute(
            'SELECT neighbor_name_raw, status, is_active, miss_count FROM topology_observations WHERE source_device_id = ? ORDER BY neighbor_name_raw',
            (device['id'],),
        ).fetchall()
        marker = conn.execute(
            'SELECT state, snapshot_complete FROM topology_device_lldp_snapshots WHERE device_id = ?',
            (device['id'],),
        ).fetchone()
    finally:
        conn.close()
    assert [tuple(row) for row in rows] == [
        ('OLD-UNSEEN', 'active', True, 0),
        ('TARGET', 'active', True, 0),
    ]
    assert tuple(marker) == ('failed', False)
