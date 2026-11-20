from __future__ import annotations

import pytest

from database import get_db_connection
from services.cmdb_cli_collection_service import _persist_interface_snapshot
from services.cmdb_interface_snapshot_service import build_cmdb_interface_observation_rows
from services.cmdb_snapshot_service import begin_snapshot_attempt


def _device(device_id: str) -> dict[str, str]:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO devices (id, hostname, ip_address, status)
               VALUES (?, ?, '192.0.2.20', 'online')""",
            (device_id, device_id),
        )
        conn.commit()
    return {'id': device_id}


def _build_rows(addresses: list[dict] | None) -> list[dict]:
    return build_cmdb_interface_observation_rows(
        [
            {
                'INTERFACE': 'GigabitEthernet0/1',
                'STATUS': 'up',
                'PROTO': 'up',
                'DESCRIPTION': 'uplink description',
            },
            {
                'INTERFACE': 'GigabitEthernet0/2',
                'STATUS': 'down',
                'PROTO': 'down',
                'DESCRIPTION': 'access port description',
            },
        ],
        {},
        addresses,
    )


def _persist(device: dict[str, str], attempt: dict, rows: list[dict], observed_at: str) -> int:
    return _persist_interface_snapshot(
        device,
        rows,
        attempt,
        observed_at=observed_at,
        metadata={'source': 'isolated-test'},
    )


def test_interface_snapshot_persists_multiple_context_addresses_and_clears_empty_set(isolated_db):
    device = _device('cmdb-interface-address-multi')
    addresses = [
        {
            'interface': 'GigabitEthernet0/1',
            'ip_address': '192.0.2.1',
            'prefix_length': 24,
            'context_source': 'cli',
            'context_type': 'global',
            'local_context_key': 'Global',
            'local_context_name': 'Default routing table',
        },
        {
            'interface': 'GigabitEthernet0/1',
            'ip_address': '2001:db8::1',
            'prefix_length': 64,
            'context_source': 'cli',
            'context_type': 'vrf',
            'local_context_key': 'Blue',
            'local_context_name': 'Blue tenant',
        },
        {
            'interface': 'GigabitEthernet0/3',
            'ip_address': '198.51.100.9/26',
        },
    ]
    first_attempt = begin_snapshot_attempt(device['id'], 'interface_inventory')
    rows = _build_rows(addresses)
    assert len(rows) == 3
    row_by_name = {row['interface_name']: row for row in rows}
    assert len(row_by_name['GigabitEthernet0/1']['addresses']) == 2
    assert row_by_name['GigabitEthernet0/1']['interface_ip'] == ''
    assert row_by_name['GigabitEthernet0/1']['prefix_length'] is None
    assert row_by_name['GigabitEthernet0/3']['interface_ip'] == '198.51.100.9'
    assert row_by_name['GigabitEthernet0/3']['prefix_length'] == 26

    assert _persist(device, first_attempt, rows, '2026-11-06T08:00:00+00:00') == 3

    with get_db_connection() as conn:
        parents = {
            row['interface_name']: dict(row)
            for row in conn.execute(
                """SELECT interface_name, description, admin_status, oper_status,
                          ip_address, ip_prefix_length, generation
                     FROM cmdb_device_interface_observations
                    WHERE device_id = ?""",
                (device['id'],),
            ).fetchall()
        }
        children = [
            dict(row)
            for row in conn.execute(
                """SELECT interface_name, context_source, context_type,
                          local_context_key, local_context_name, host(ip_address) AS ip_address,
                          ip_prefix_length, generation, run_id, metadata_json
                     FROM cmdb_device_interface_address_observations
                    WHERE device_id = ?
                    ORDER BY normalized_interface_name, ip_address""",
                (device['id'],),
            ).fetchall()
        ]

    assert parents['GigabitEthernet0/1']['description'] == 'uplink description'
    assert parents['GigabitEthernet0/1']['admin_status'] == 'up'
    assert parents['GigabitEthernet0/1']['oper_status'] == 'up'
    assert parents['GigabitEthernet0/1']['ip_address'] == ''
    assert parents['GigabitEthernet0/1']['ip_prefix_length'] is None
    assert parents['GigabitEthernet0/2']['description'] == 'access port description'
    assert parents['GigabitEthernet0/2']['admin_status'] == 'down'
    assert parents['GigabitEthernet0/2']['ip_address'] == ''

    by_ip = {row['ip_address']: row for row in children}
    assert set(by_ip) == {'192.0.2.1', '2001:db8::1', '198.51.100.9'}
    assert (by_ip['192.0.2.1']['context_type'], by_ip['192.0.2.1']['local_context_key']) == (
        'global', 'Global',
    )
    assert by_ip['2001:db8::1']['local_context_name'] == 'Blue tenant'
    assert (by_ip['198.51.100.9']['context_source'], by_ip['198.51.100.9']['context_type']) == (
        'cli', 'unknown',
    )
    assert by_ip['198.51.100.9']['local_context_key'] == ''
    assert by_ip['198.51.100.9']['ip_prefix_length'] == 26
    assert all(row['generation'] == first_attempt['generation'] for row in children)
    assert all(row['run_id'] == first_attempt['run_id'] for row in children)
    assert all(row['metadata_json'] == {'source': 'isolated-test'} for row in children)

    second_attempt = begin_snapshot_attempt(device['id'], 'interface_inventory')
    empty_address_rows = _build_rows([])
    assert all(not row['addresses'] for row in empty_address_rows)
    _persist(device, second_attempt, empty_address_rows, '2026-11-06T08:01:00+00:00')

    with get_db_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM cmdb_device_interface_address_observations WHERE device_id = ?",
            (device['id'],),
        ).fetchone()[0] == 0
        cleared_parent = conn.execute(
            """SELECT description, admin_status, ip_address, ip_prefix_length, generation
                 FROM cmdb_device_interface_observations
                WHERE device_id = ? AND interface_name = 'GigabitEthernet0/1'""",
            (device['id'],),
        ).fetchone()
        snapshot = conn.execute(
            """SELECT successful_generation, attempt_status, record_count
                 FROM cmdb_collection_snapshots
                WHERE device_id = ? AND domain = 'interface_inventory'""",
            (device['id'],),
        ).fetchone()
    assert tuple(cleared_parent) == (
        'uplink description', 'up', '', None, second_attempt['generation'],
    )
    assert tuple(snapshot) == (second_attempt['generation'], 'success', 2)


def test_interface_snapshot_preserves_unknown_raw_context_key(isolated_db):
    device = _device('cmdb-interface-address-unknown-context')
    attempt = begin_snapshot_attempt(device['id'], 'interface_inventory')
    rows = _build_rows([{
        'interface': 'GigabitEthernet0/1',
        'ip_address': '198.51.100.16',
        'prefix_length': 24,
        'context_source': 'cli',
        'context_type': 'unknown',
        'local_context_key': 'default',
        'local_context_name': 'default',
    }])

    _persist(device, attempt, rows, '2026-11-06T08:02:00+00:00')

    with get_db_connection() as conn:
        row = conn.execute(
            """SELECT context_type, local_context_key, local_context_name,
                      host(ip_address) AS ip_address
                 FROM cmdb_device_interface_address_observations
                WHERE device_id = ?""",
            (device['id'],),
        ).fetchone()
    assert tuple(row) == ('unknown', 'default', 'default', '198.51.100.16')


def test_invalid_address_rows_and_superseded_attempt_preserve_last_success(isolated_db):
    device = _device('cmdb-interface-address-fence')
    first_attempt = begin_snapshot_attempt(device['id'], 'interface_inventory')
    first_rows = _build_rows([{
        'interface': 'GigabitEthernet0/1',
        'ip_address': '192.0.2.10',
        'prefix_length': 24,
    }])
    _persist(device, first_attempt, first_rows, '2026-11-06T09:00:00+00:00')

    current_attempt = begin_snapshot_attempt(device['id'], 'interface_inventory')
    current_rows = _build_rows([{
        'interface': 'GigabitEthernet0/1',
        'ip_address': '198.51.100.10',
        'prefix_length': 24,
    }])
    try:
        _persist(device, first_attempt, current_rows, '2026-11-06T09:01:00+00:00')
    except RuntimeError as exc:
        assert 'superseded' in str(exc)
    else:
        raise AssertionError('A superseded interface attempt must not publish')

    invalid_addresses = [
        {
            'interface': 'GigabitEthernet0/1',
            'ip_address': 'not-an-ip',
            'prefix_length': 24,
        },
        {
            'interface': 'GigabitEthernet0/1',
            'ip_address': '192.0.2.13',
            'prefix_length': 33,
        },
        {
            'interface': 'GigabitEthernet0/1',
            'ip_address': '192.0.2.11',
            'prefix_length': 24,
            'context_type': 'vrf',
        },
        {
            'interface': 'GigabitEthernet0/1',
            'ip_address': '192.0.2.12',
            'prefix_length': 24,
            'context_source': 'discovery',
        },
    ]
    for invalid_address in invalid_addresses:
        with pytest.raises(RuntimeError):
            _persist(
                device,
                current_attempt,
                _build_rows([invalid_address]),
                '2026-11-06T09:02:00+00:00',
            )
        with get_db_connection() as conn:
            child = conn.execute(
                """SELECT host(ip_address), generation
                     FROM cmdb_device_interface_address_observations
                    WHERE device_id = ?""",
                (device['id'],),
            ).fetchone()
            snapshot = conn.execute(
                """SELECT successful_generation, attempt_status
                     FROM cmdb_collection_snapshots
                    WHERE device_id = ? AND domain = 'interface_inventory'""",
                (device['id'],),
            ).fetchone()
        assert tuple(child) == ('192.0.2.10', first_attempt['generation'])
        assert tuple(snapshot) == (first_attempt['generation'], 'running')

    _persist(device, current_attempt, current_rows, '2026-11-06T09:03:00+00:00')
    with get_db_connection() as conn:
        child = conn.execute(
            """SELECT host(ip_address), ip_prefix_length, context_type, local_context_key,
                      generation
                 FROM cmdb_device_interface_address_observations
                WHERE device_id = ?""",
            (device['id'],),
        ).fetchone()
    assert tuple(child) == (
        '198.51.100.10', 24, 'unknown', '', current_attempt['generation'],
    )
