from __future__ import annotations

import uuid
from typing import Any

import pytest

import database
import api.device_health as device_health_api
import api.topology as topology_api
from services import device_health_service, rack_service


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _seed_rack_fixtures(conn) -> dict[str, str]:
    site_id = _new_id('site')
    dt_one = _new_id('dt')
    dt_two = _new_id('dt')
    conn.execute(
        'INSERT INTO sites (id, site_code, site_name) VALUES (?, ?, ?)',
        (site_id, _new_id('DC'), 'Rack read model test site'),
    )
    conn.execute(
        '''INSERT INTO device_types (
               id, vendor, model, u_height, power_watts, device_role, is_full_depth
           ) VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (dt_one, _new_id('vendor'), _new_id('model'), 1, 100, 'switch', 1),
    )
    conn.execute(
        '''INSERT INTO device_types (
               id, vendor, model, u_height, power_watts, device_role, is_full_depth
           ) VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (dt_two, _new_id('vendor'), _new_id('model'), 2, 200, 'server', 1),
    )
    return {'site_id': site_id, 'dt_one': dt_one, 'dt_two': dt_two}


def _insert_rack(conn, site_id: str, rack_id: str, name: str, *, total_u: int = 42) -> None:
    conn.execute(
        '''INSERT INTO racks (
               id, name, rack_name, rack_code, site_id, datacenter, floor, room, row,
               room_name, row_name, total_u, status, power_capacity_watts,
               power_capacity_w, placement_strategy
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 1000, 1000, 'bottom_first')''',
        (rack_id, name, name, _new_id('rack-code'), site_id, 'DC-A', '3', '301', 'A', '301', 'A', total_u),
    )


def _insert_rack_device(
    conn,
    device_id: str,
    rack_id: str,
    device_type_id: str,
    start_u: int,
    *,
    position: str = 'front',
    asset_id: str = '',
    name: str | None = None,
) -> None:
    conn.execute(
        '''INSERT INTO rack_devices (
               id, name, rack_id, device_type_id, start_u, position, status, serial_number,
               asset_id, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)''',
        (device_id, name or device_id, rack_id, device_type_id, start_u, position, _new_id('serial'), asset_id),
    )


def _insert_device(conn, device_id: str, asset_id: str, status: str | None) -> None:
    conn.execute(
        '''INSERT INTO devices (id, asset_id, hostname, status, site_id, site, platform)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (device_id, asset_id, _new_id('host'), status, '', 'Rack read model test site', 'cisco_ios'),
    )


def test_rack_summary_aggregates_capacity_and_conservative_health_states(isolated_db) -> None:
    conn = isolated_db['module'].get_db_connection()
    seed = _seed_rack_fixtures(conn)
    racks = {
        name: _new_id('rack')
        for name in ('empty', 'healthy', 'partial', 'unknown', 'unknown-status', 'offline', 'invalid')
    }
    for name, rack_id in racks.items():
        _insert_rack(conn, seed['site_id'], rack_id, f'A-{name}')

    healthy_asset_one = _new_id('asset')
    healthy_asset_two = _new_id('asset')
    partial_asset = _new_id('asset')
    unknown_asset = _new_id('asset')
    unknown_status_asset = _new_id('asset')
    offline_asset = _new_id('asset')
    invalid_asset = _new_id('asset')
    _insert_rack_device(conn, _new_id('rd'), racks['healthy'], seed['dt_one'], 1, asset_id=healthy_asset_one)
    _insert_rack_device(conn, _new_id('rd'), racks['healthy'], seed['dt_two'], 2, asset_id=healthy_asset_two)
    _insert_rack_device(conn, _new_id('rd'), racks['partial'], seed['dt_one'], 1, asset_id=partial_asset)
    _insert_rack_device(conn, _new_id('rd'), racks['partial'], seed['dt_one'], 3)
    _insert_rack_device(conn, _new_id('rd'), racks['unknown'], seed['dt_one'], 1, asset_id=unknown_asset)
    _insert_rack_device(conn, _new_id('rd'), racks['unknown-status'], seed['dt_one'], 1, asset_id=unknown_status_asset)
    _insert_rack_device(conn, _new_id('rd'), racks['offline'], seed['dt_one'], 1, asset_id=offline_asset)
    _insert_rack_device(conn, _new_id('rd'), racks['invalid'], seed['dt_two'], 42, asset_id=invalid_asset)

    _insert_device(conn, _new_id('dev'), healthy_asset_one, 'online')
    _insert_device(conn, _new_id('dev'), healthy_asset_two, 'active')
    _insert_device(conn, _new_id('dev'), partial_asset, 'online')
    _insert_device(conn, _new_id('dev'), unknown_asset, None)
    _insert_device(conn, _new_id('dev'), unknown_status_asset, 'unknown')
    _insert_device(conn, _new_id('dev'), offline_asset, 'offline')
    _insert_device(conn, _new_id('dev'), invalid_asset, 'online')

    result = rack_service.list_rack_summaries(conn, page=1, page_size=50)
    by_id = {item['id']: item for item in result['items']}

    assert result['total'] >= 7
    assert by_id[racks['empty']]['health_status'] == 'empty'
    assert by_id[racks['empty']]['data_quality_status'] == 'empty'
    assert by_id[racks['healthy']]['health_status'] == 'healthy'
    assert by_id[racks['healthy']]['used_u'] == 3
    assert by_id[racks['healthy']]['power_used_watts'] == 300
    assert by_id[racks['partial']]['health_status'] == 'partial'
    assert by_id[racks['partial']]['unmonitored_device_count'] == 1
    assert by_id[racks['unknown']]['health_status'] == 'unknown'
    assert by_id[racks['unknown-status']]['health_status'] == 'unknown'
    assert by_id[racks['unknown-status']]['unknown_monitoring_device_count'] == 1
    assert by_id[racks['unknown-status']]['data_quality_status'] == 'partial'
    assert by_id[racks['offline']]['health_status'] == 'offline'
    assert by_id[racks['invalid']]['invalid_device_count'] == 1
    assert by_id[racks['invalid']]['data_quality_status'] == 'invalid'


def test_rack_summary_filters_search_and_pagination_use_the_same_health_contract(isolated_db) -> None:
    conn = isolated_db['module'].get_db_connection()
    seed = _seed_rack_fixtures(conn)
    rack_a = _new_id('rack')
    rack_b = _new_id('rack')
    rack_c = _new_id('rack')
    _insert_rack(conn, seed['site_id'], rack_a, 'A-01')
    _insert_rack(conn, seed['site_id'], rack_b, 'B-01')
    _insert_rack(conn, seed['site_id'], rack_c, 'C-01')
    asset_a = _new_id('asset')
    asset_b = _new_id('asset')
    _insert_rack_device(conn, _new_id('rd'), rack_a, seed['dt_one'], 1, asset_id=asset_a, name='Core Search Device')
    _insert_rack_device(conn, _new_id('rd'), rack_b, seed['dt_one'], 1, asset_id=asset_b)
    _insert_device(conn, _new_id('dev'), asset_a, 'online')
    _insert_device(conn, _new_id('dev'), asset_b, 'unknown')

    page = rack_service.list_rack_summaries(conn, page=2, page_size=2)
    assert page['total'] == 3
    assert page['page'] == 2
    assert len(page['items']) == 1

    search = rack_service.list_rack_summaries(conn, keyword='search device')
    assert search['total'] == 1
    assert search['items'][0]['id'] == rack_a

    healthy = rack_service.list_rack_summaries(conn, health='healthy')
    assert [item['id'] for item in healthy['items']] == [rack_a]

    unknown = rack_service.list_rack_summaries(conn, health='unknown')
    assert [item['id'] for item in unknown['items']] == [rack_b]


def test_rack_device_asset_identity_is_normalized_and_duplicate_installation_is_rejected(isolated_db) -> None:
    conn = isolated_db['module'].get_db_connection()
    seed = _seed_rack_fixtures(conn)
    rack_a = _new_id('rack')
    rack_b = _new_id('rack')
    _insert_rack(conn, seed['site_id'], rack_a, 'A-01')
    _insert_rack(conn, seed['site_id'], rack_b, 'B-01')

    created = rack_service.create_rack_device(
        conn,
        name='device-a',
        rack_id=rack_a,
        device_type_id=seed['dt_one'],
        start_u=1,
        asset_id='  asset-shared  ',
    )
    assert created['asset_id'] == 'asset-shared'

    with pytest.raises(ValueError, match='资产已上架'):
        rack_service.create_rack_device(
            conn,
            name='device-b',
            rack_id=rack_b,
            device_type_id=seed['dt_one'],
            start_u=1,
            asset_id='asset-shared',
        )


def test_postgres_asset_check_uses_transaction_scoped_advisory_and_row_locks(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple[Any, ...] | None]] = []

    class _Result:
        def fetchone(self):
            return None

    class _Connection:
        def execute(self, sql: str, params=None):
            calls.append((sql, params))
            return _Result()

    monkeypatch.setattr(database, '_USE_PG', True)
    rack_service._check_asset_installation(_Connection(), ' asset-1 ')

    assert 'pg_advisory_xact_lock' in calls[0][0]
    assert calls[0][1] == ('asset-1',)
    assert 'FOR UPDATE' in calls[1][0]
    assert calls[1][1] == ('asset-1',)


def test_health_loader_applies_rack_scope(isolated_db, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = isolated_db['module'].get_db_connection()
    seed = _seed_rack_fixtures(conn)
    rack_a = _new_id('rack')
    rack_b = _new_id('rack')
    _insert_rack(conn, seed['site_id'], rack_a, 'A-01')
    _insert_rack(conn, seed['site_id'], rack_b, 'B-01')
    asset_a = _new_id('asset')
    asset_b = _new_id('asset')
    device_a = _new_id('dev')
    device_b = _new_id('dev')
    _insert_device(conn, device_a, asset_a, 'online')
    _insert_device(conn, device_b, asset_b, 'online')
    _insert_rack_device(conn, _new_id('rd'), rack_a, seed['dt_one'], 1, asset_id=asset_a)
    _insert_rack_device(conn, _new_id('rd'), rack_b, seed['dt_one'], 1, asset_id=asset_b)
    monkeypatch.setattr(device_health_service, 'fetch_interface_data', lambda _conn, _device_id: [])

    rows = device_health_service.load_devices_for_health(conn, rack_id=rack_a)
    assert [row['id'] for row in rows] == [device_a]


def test_topology_route_passes_rack_scope_and_filters_metadata(isolated_db, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = isolated_db['module'].get_db_connection()
    seed = _seed_rack_fixtures(conn)
    rack_id = _new_id('rack')
    _insert_rack(conn, seed['site_id'], rack_id, 'A-01')
    asset_one = _new_id('asset')
    asset_two = _new_id('asset')
    device_one = _new_id('dev')
    device_two = _new_id('dev')
    _insert_device(conn, device_one, asset_one, 'online')
    _insert_device(conn, device_two, asset_two, 'online')
    _insert_rack_device(conn, _new_id('rd'), rack_id, seed['dt_one'], 1, asset_id=asset_one)
    _insert_rack_device(conn, _new_id('rd'), rack_id, seed['dt_one'], 2, asset_id=asset_two)

    captured: dict[str, Any] = {}
    monkeypatch.setattr(topology_api, 'get_db_connection', lambda: conn)
    monkeypatch.setattr(topology_api.read_cache, 'get', lambda _namespace, _key: (False, None))
    monkeypatch.setattr(topology_api.read_cache, 'set', lambda *_args: None)
    monkeypatch.setattr(
        topology_api,
        'get_current_links',
        lambda **kwargs: captured.update(kwargs) or [{'id': 'link-1'}],
    )
    monkeypatch.setattr(
        topology_api,
        'get_topology_node_metadata',
        lambda **_kwargs: {device_one: {'topology_rank': 1}, 'dev-outside': {'topology_rank': 9}},
    )
    monkeypatch.setattr(
        topology_api,
        'get_unmanaged_neighbors',
        lambda **_kwargs: pytest.fail('rack-scoped topology must not load global unmanaged neighbors'),
    )

    response = topology_api.get_links(limit=500, site_id=seed['site_id'], rack_id=f' {rack_id} ', include_stale=False)

    assert captured['device_ids'] == sorted([device_one, device_two])
    assert response['links'] == [{'id': 'link-1'}]
    assert response['node_metadata'] == {device_one: {'topology_rank': 1}}
    assert response['unmanaged_nodes'] == []


def test_health_route_returns_scoped_devices_as_items(isolated_db, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = isolated_db['module'].get_db_connection()
    devices = [{'id': _new_id('dev'), 'asset_id': _new_id('asset')}]
    monkeypatch.setattr(device_health_api, 'get_db_connection', lambda: conn)

    calls: dict[str, Any] = {}

    def _load_devices(_conn, rack_id=None):
        calls['rack_id'] = rack_id
        return devices

    monkeypatch.setattr(device_health_api, 'load_devices_for_health', _load_devices)
    monkeypatch.setattr(device_health_api, 'annotate_devices_with_snmp_profile', lambda rows: rows)
    monkeypatch.setattr(device_health_api, 'annotate_devices_with_health', lambda _conn, rows: rows)
    monkeypatch.setattr(
        device_health_api,
        'build_health_overview',
        lambda rows: {'items': [], 'total_devices': len(rows)},
    )

    result = device_health_api.device_health_overview(' rack-1 ')

    assert calls['rack_id'] == 'rack-1'
    assert result['items'] == devices
    assert result['total_devices'] == 1
