from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

import api.devices as devices_api
from api.devices import resolve_snmp_walk_target, test_snmp_walk as run_snmp_walk_test


def test_snmp_walk_test_accepts_v1_and_returns_copyable_rows(monkeypatch) -> None:
    calls: list[tuple[tuple, dict]] = []

    async def fake_walk(*args, **kwargs):
        calls.append((args, kwargs))
        return [('1', 'GigabitEthernet0/1'), ('2', 'uplink')]

    monkeypatch.setattr('services.snmp_service._snmp_walk', fake_walk)
    response = asyncio.run(
        run_snmp_walk_test(
            {
                'ip': '10.254.0.1',
                'community': 'public',
                'version': '1',
                'oid': '.1.3.6.1.2.1.47.',
            },
            user={'role': 'Operator'},
        )
    )

    assert response['success'] is True
    assert response['data']['version'] == '1'
    assert response['data']['rows'][0] == {
        'oid': '1.3.6.1.2.1.47.1',
        'value': 'GigabitEthernet0/1',
    }
    assert calls[0][0] == ('10.254.0.1', 'public', '1.3.6.1.2.1.47')
    assert calls[0][1]['version'] == '1'


def test_snmp_walk_test_rejects_unsupported_version() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            run_snmp_walk_test(
                {'ip': '192.0.2.1', 'community': 'public', 'version': '3', 'oid': '1.3.6.1'},
                user={'role': 'Operator'},
            )
        )

    assert error.value.status_code == 400
    assert 'version' in str(error.value.detail)


def test_snmp_walk_test_rejects_missing_community() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            run_snmp_walk_test(
                {'ip': '192.0.2.1', 'oid': '1.3.6.1'},
                user={'role': 'Operator'},
            )
        )

    assert error.value.status_code == 400
    assert 'community' in str(error.value.detail)


def test_snmp_walk_test_reads_community_from_managed_device(monkeypatch) -> None:
    class Result:
        def __init__(self, rows):
            self.rows = rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return list(self.rows)

    class Connection:
        def execute(self, sql, params=()):
            assert 'FROM devices' in sql
            return Result([{
                'id': 'device-1',
                'hostname': 'edge-01',
                'ip_address': '10.254.0.1',
                'asset_id': 'asset-1',
            }])

        def close(self):
            pass

    calls: list[tuple[tuple, dict]] = []

    async def fake_walk(*args, **kwargs):
        calls.append((args, kwargs))
        return [('1', 'value')]

    monkeypatch.setattr(devices_api, 'get_db_connection', lambda: Connection())
    monkeypatch.setattr(
        devices_api,
        'resolve_collector_credentials',
        lambda device: {'snmp': {'server': '10.254.0.9', 'community': 'asset-secret', 'port': 1161}},
    )
    monkeypatch.setattr('services.snmp_service._snmp_walk', fake_walk)

    response = asyncio.run(
        run_snmp_walk_test(
            {
                'device_id': 'device-1',
                'target_query': '10.254.0',
                'version': '2c',
                'oid': '1.3.6.1.2.1',
            },
            user={'role': 'Operator'},
        )
    )

    assert response['data']['target_source'] == 'asset'
    assert response['data']['matched_device_id'] == 'device-1'
    assert 'community' not in response['data']
    assert calls[0][0] == ('10.254.0.9', 'asset-secret', '1.3.6.1.2.1')
    assert calls[0][1]['port'] == 1161


def test_snmp_walk_test_rejects_ambiguous_asset_match(monkeypatch) -> None:
    class Result:
        def fetchall(self):
            return [
                {'id': 'device-1', 'hostname': 'edge-01', 'ip_address': '10.254.0.1'},
                {'id': 'device-2', 'hostname': 'edge-02', 'ip_address': '10.254.0.2'},
            ]

    class Connection:
        def execute(self, sql, params=()):
            if 'LIKE' in sql:
                return Result()
            return type('ExactResult', (), {'fetchall': lambda self: []})()

        def close(self):
            pass

    monkeypatch.setattr(devices_api, 'get_db_connection', lambda: Connection())
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            run_snmp_walk_test(
                {'target_query': 'edge', 'oid': '1.3.6.1.2.1'},
                user={'role': 'Operator'},
            )
        )

    assert error.value.status_code == 409
    assert 'multiple' in str(error.value.detail)


def test_snmp_target_query_supports_regex_matching(monkeypatch) -> None:
    class Result:
        def __init__(self, rows=()):
            self.rows = list(rows)

        def fetchall(self):
            return list(self.rows)

    class Connection:
        def execute(self, sql, params=()):
            if 'LIMIT 5000' in sql and 'FROM devices' in sql:
                return Result([{'id': 'device-regex', 'hostname': 'edge-regex', 'ip_address': '10.254.99.1'}])
            return Result()

        def close(self):
            pass

    monkeypatch.setattr(devices_api, 'get_db_connection', lambda: Connection())
    targets = devices_api._find_snmp_walk_targets(target_query=r'10\.254\.\d+\.\d+')

    assert [target['id'] for target in targets] == ['device-regex']


def test_snmp_walk_target_confirms_exact_ip(monkeypatch) -> None:
    class Result:
        def __init__(self, row=None):
            self.row = row

        def fetchone(self):
            return self.row

    class Connection:
        def execute(self, sql, params=()):
            if 'FROM devices' in sql:
                return Result({
                    'id': 'device-1',
                    'hostname': 'edge-01',
                    'ip_address': '10.254.0.1',
                    'asset_id': 'asset-1',
                })
            return Result()

        def close(self):
            pass

    monkeypatch.setattr(devices_api, 'get_db_connection', lambda: Connection())
    response = resolve_snmp_walk_target('10.254.0.1', user={'role': 'Operator'})

    assert response == {
        'success': True,
        'data': {'ip': '10.254.0.1', 'device_id': 'device-1', 'hostname': 'edge-01'},
    }


def test_snmp_walk_target_reports_ip_not_found(monkeypatch) -> None:
    class Result:
        def fetchone(self):
            return None

    class Connection:
        def execute(self, sql, params=()):
            return Result()

        def close(self):
            pass

    monkeypatch.setattr(devices_api, 'get_db_connection', lambda: Connection())
    with pytest.raises(HTTPException) as error:
        resolve_snmp_walk_target('10.254.0.99', user={'role': 'Operator'})

    assert error.value.status_code == 404
    assert 'IP not found' in str(error.value.detail)
