from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from database import get_db_connection
from services.topology_aggregation_inventory_service import persist_snmp_aggregation_inventory
from services.topology_lldp_snapshot_service import begin_lldp_snapshot_attempt, lldp_snapshot_versions
from services.topology_service import _collapse_aggregation_groups, _load_interface_aggregation_map


def _device(device_id='source'):
    device = {'id': device_id, 'hostname': device_id, 'ip_address': '10.0.0.1', 'platform': 'h3c_comware'}
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO devices (id, hostname, ip_address, platform) VALUES (?, ?, ?, ?)',
                     (device_id, device_id, device['ip_address'], device['platform']))
        conn.commit()
    finally:
        conn.close()
    generation = begin_lldp_snapshot_attempt(device, lldp_snapshot_versions(device))['generation']
    return device, generation


def _snapshot(parent='Bridge-Aggregation12', member_ports=(49, 50, 51, 52), *, prefix='Ten-GigabitEthernet', speed=10000):
    return {
        'status': 'success', 'source': 'snmp', 'membership_source': 'dot3adAggPortAttachedAggID',
        'parents': [{'interface_name': parent, 'if_index': 5130, 'oper_status': 'up', 'speed_mbps': speed * len(member_ports)}],
        'records': [{
            'aggregation_name': parent, 'aggregation_if_index': 5130,
            'member_interface': f'{prefix}1/0/{port}', 'member_if_index': port + 1,
            'member_oper_status': 'up', 'member_speed_mbps': speed,
        } for port in member_ports],
    }


def _rows(device_id):
    conn = get_db_connection()
    try:
        return [dict(row) for row in conn.execute('SELECT * FROM interfaces WHERE device_id = ? ORDER BY interface_name', (device_id,)).fetchall()]
    finally:
        conn.close()


def test_complete_snmp_snapshot_reuses_aliases_and_refreshes_removed_members(isolated_db):
    device, generation = _device()
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO interfaces (id,device_id,interface_name) VALUES ('member-existing',?,'XGE1/0/49')", (device['id'],))
        conn.execute("INSERT INTO interfaces (id,device_id,interface_name,interface_type) VALUES ('parent-existing',?,'BAgg12','physical')", (device['id'],))
        conn.commit()
    finally:
        conn.close()
    first = persist_snmp_aggregation_inventory(device, _snapshot(), snapshot_generation=generation)
    assert first['status'] == 'success'
    assert (first['parents'], first['members']) == (1, 4)
    rows = _rows(device['id'])
    assert len(rows) == 5
    assert next(row for row in rows if row['id'] == 'member-existing')['parent_interface_id'] == 'parent-existing'
    assert next(row for row in rows if row['id'] == 'parent-existing')['interface_type'] == 'port_channel'
    assert next(row for row in rows if row['id'] == 'member-existing')['speed'] == 10_000_000_000

    changed = persist_snmp_aggregation_inventory(device, _snapshot(member_ports=(49, 50)), snapshot_generation=generation)
    assert changed['members'] == 2
    members = {row['if_index']: row for row in _rows(device['id']) if row['interface_type'] == 'physical'}
    assert members[50]['parent_interface_id'] == 'parent-existing'
    assert members[52]['parent_interface_id'] is None
    assert members[52]['channel_group'] is None
    empty = persist_snmp_aggregation_inventory(device, _snapshot(member_ports=()), snapshot_generation=generation)
    assert empty['members'] == 0
    assert not any(row['parent_interface_id'] for row in _rows(device['id']))


@pytest.mark.parametrize('status', ['unavailable', 'failed', 'partial'])
def test_incomplete_snapshot_preserves_last_inventory(isolated_db, status):
    device, generation = _device()
    persist_snmp_aggregation_inventory(device, _snapshot(), snapshot_generation=generation)
    before = _rows(device['id'])
    result = persist_snmp_aggregation_inventory(device, {'status': status, 'records': [], 'parents': []}, snapshot_generation=generation)
    assert result['status'] == status
    assert _rows(device['id']) == before


def test_superseded_generation_and_changed_management_ip_cannot_write(isolated_db):
    device, generation = _device()
    newer = begin_lldp_snapshot_attempt(device, lldp_snapshot_versions(device))['generation']
    assert persist_snmp_aggregation_inventory(device, _snapshot(), snapshot_generation=generation)['status'] == 'superseded'
    conn = get_db_connection()
    try:
        conn.execute('UPDATE devices SET ip_address = ? WHERE id = ?', ('10.0.0.9', device['id']))
        conn.commit()
    finally:
        conn.close()
    assert persist_snmp_aggregation_inventory(device, _snapshot(), snapshot_generation=newer)['status'] == 'superseded'
    assert _rows(device['id']) == []


def test_valid_empty_snapshot_preserves_non_lag_interface_hierarchy(isolated_db):
    device, generation = _device()
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO interfaces (id,device_id,interface_name,interface_type) VALUES ('physical',?,'GE1/0/1','physical')", (device['id'],))
        conn.execute("INSERT INTO interfaces (id,device_id,interface_name,interface_type,parent_interface_id) VALUES ('sub',?,'GE1/0/1.100','subinterface','physical')", (device['id'],))
        conn.commit()
    finally:
        conn.close()
    result = persist_snmp_aggregation_inventory(device, {'status': 'success', 'parents': [], 'records': []}, snapshot_generation=generation)
    assert result['status'] == 'success'
    assert next(row for row in _rows(device['id']) if row['id'] == 'sub')['parent_interface_id'] == 'physical'


def test_two_snmp_bundles_keep_all_eight_member_pairs_aligned_on_reverse_observations(isolated_db):
    conn = get_db_connection()
    grouped = {}
    try:
        for device_id in ('s1', 's2', 's3', 's4'):
            device, generation = _device(device_id)
            snapshot = _snapshot() if device_id in {'s1', 's2'} else _snapshot('Route-Aggregation34', (1, 2, 3, 4), prefix='GigabitEthernet', speed=1000)
            persist_snmp_aggregation_inventory(device, snapshot, snapshot_generation=generation)
        inventory = _load_interface_aggregation_map(conn)
        for left, right, prefix, ports in [('s1', 's2', 'te', range(49, 53)), ('s3', 's4', 'gi', range(1, 5))]:
            for port in ports:
                key = f'{prefix}1/0/{port}'
                grouped[f'{left}-{right}-{port}'] = [{
                    'source_device_id': a, 'target_device_id': b,
                    'source_port_raw': key, 'target_port_raw': key,
                    'source_port_normalized': key, 'target_port_normalized': key, 'protocol': 'lldp',
                } for a, b in [(left, right), (right, left)]]
        result = _collapse_aggregation_groups(grouped, inventory)
        assert len(result) == 2
        for bundle in result.values():
            aggregation = bundle['aggregation']
            assert aggregation['member_count'] == aggregation['active_member_count'] == 4
            assert aggregation['bandwidth_mbps'] == (40000 if aggregation['source_device_id'] == 's1' else 4000)
            assert all(member['source']['device_id'] == aggregation['source_device_id'] and member['target']['device_id'] == aggregation['target_device_id'] for member in aggregation['members'])
    finally:
        conn.close()


def test_snmp_aggregation_dependency_failure_does_not_open_cli():
    from services.topology_aggregation_inventory_service import sync_snmp_aggregation_inventory

    with (
        patch('services.topology_snmp_aggregation_service.collect_snmp_aggregation_inventory', new=AsyncMock(return_value={'status': 'unavailable'})),
        patch('services.topology_service._sync_aggregation_inventory') as cli,
    ):
        result = asyncio.run(sync_snmp_aggregation_inventory({'id': 'device'}, {}, snapshot_generation=1))
    assert result['status'] == 'unavailable'
    cli.assert_not_called()
