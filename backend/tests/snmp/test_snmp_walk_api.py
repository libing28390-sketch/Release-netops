from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

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


def test_snmp_hardware_test_reads_native_snapshot_without_python_oid_polling(monkeypatch) -> None:
    from services import librenms_diagnostic_service

    monkeypatch.setattr(
        devices_api,
        'resolve_collector_credentials',
        lambda _device: pytest.fail('native hardware diagnostic must not resolve device SNMP credentials'),
    )
    device = {'id': 'device-1', 'hostname': 'edge-01'}
    native_result = {
        'state': 'available',
        'message': 'native sample',
        'identity': {'hostname': 'edge-01'},
        'processor_sensors': [{
            'processor_descr': 'CPU 1', 'sensor_current': 37.5,
            'value_status': 'available', 'freshness': 'fresh', 'observed_at': '2026-10-07T10:00:00+00:00',
        }],
        'memory_pools': [], 'hardware_sensors': [], 'wireless_sensors': [],
    }
    monkeypatch.setattr(devices_api, '_find_snmp_walk_targets', lambda **_kwargs: [device])
    monkeypatch.setattr(librenms_diagnostic_service, 'diagnose_librenms_hardware', lambda _device: asyncio.sleep(0, result=native_result))

    response = asyncio.run(devices_api.test_snmp_hardware_metrics(
        {
            'device_id': 'device-1',
            'metric_definitions': {'cpu': {'mode': 'direct_percent', 'oid': '1.3.6.1.4.1.8'}},
        },
        user={'role': 'Operator'},
    ))

    assert response['data']['status'] == 'ok'
    assert response['data']['native_hardware'] == native_result
    assert response['data']['metrics']['processor:CPU 1']['value'] == 37.5
    assert response['data']['metrics']['processor:CPU 1']['source'] == 'librenms_native'


def test_snmp_hardware_test_requires_an_explicit_target() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            devices_api.test_snmp_hardware_metrics(
                {'metric_definitions': {}},
                user={'role': 'Operator'},
            )
        )

    assert error.value.status_code == 400
    assert 'device_id' in str(error.value.detail)


def test_snmp_interface_test_validates_submitted_template_and_returns_samples(monkeypatch) -> None:
    calls: list[dict] = []
    interface_config = {
        'enabled': True,
        'counter_mode': '64',
        'if_name_oid': '1.3.6.1.2.1.31.1.1.1.1',
        'if_hc_in_octets_oid': '1.3.6.1.2.1.31.1.1.1.6',
        'if_hc_out_octets_oid': '1.3.6.1.2.1.31.1.1.1.10',
    }

    monkeypatch.setattr(
        devices_api,
        '_find_snmp_walk_targets',
        lambda **_kwargs: [{
            'id': 'device-1',
            'hostname': 'edge-01',
            'ip_address': '10.254.0.1',
        }],
    )
    monkeypatch.setattr(
        devices_api,
        'resolve_collector_credentials',
        lambda _device: {'snmp': {'server': '10.254.0.9', 'community': 'asset-secret', 'port': 1161}},
    )

    async def fake_probe(ip, community, config, *, port=161, version='2c'):
        calls.append({
            'ip': ip,
            'community': community,
            'config': config,
            'port': port,
            'version': version,
        })
        return {
            'passed': True,
            'status': 'ok',
            'message': 'Interface table and paired Counter64 counters passed validation',
            'checks': {
                'identity': {
                    'oid': '1.3.6.1.2.1.31.1.1.1.1',
                    'passed': True,
                    'rows': 1,
                    'sample': [{'index': '55', 'value': 'FortyGigE1/0/54'}],
                },
            },
            'counter_mode': '64',
            'selected_counter_bits': 64,
            'interfaces': 1,
            'counter_supported': 1,
        }

    monkeypatch.setattr('services.snmp_service.probe_interface_definition', fake_probe)

    response = asyncio.run(
        devices_api.test_snmp_interface_oids(
            {
                'device_id': 'device-1',
                'version': '1',
                'interface_config': interface_config,
            },
            user={'role': 'Operator'},
        )
    )

    assert response['success'] is True
    assert response['data']['passed'] is True
    assert response['data']['checks']['identity']['sample'][0]['value'] == 'FortyGigE1/0/54'
    assert response['data']['version'] == '1'
    assert response['data']['target_source'] == 'asset'
    assert 'community' not in response['data']
    from services.snmp_service import DEFAULT_INTERFACE_CONFIG

    expected_config = {**DEFAULT_INTERFACE_CONFIG, **interface_config}
    assert calls == [{
        'ip': '10.254.0.9',
        'community': 'asset-secret',
        'config': expected_config,
        'port': 1161,
        'version': '1',
    }]


def test_snmp_interface_test_rejects_invalid_submitted_oid(monkeypatch) -> None:
    monkeypatch.setattr(
        devices_api,
        '_find_snmp_walk_targets',
        lambda **_kwargs: [{'id': 'device-1', 'hostname': 'edge-01', 'ip_address': '10.254.0.1'}],
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            devices_api.test_snmp_interface_oids(
                {
                    'device_id': 'device-1',
                    'interface_config': {'enabled': True, 'if_name_oid': 'not-an-oid'},
                },
                user={'role': 'Operator'},
            )
        )

    assert error.value.status_code == 400
    assert 'if_name_oid' in str(error.value.detail)


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


def test_snmp_hardware_discovery_test_returns_native_bound_result_without_python_probes(monkeypatch) -> None:
    from services import librenms_diagnostic_service

    device = {
        'id': 'device-hw-1', 'asset_id': 'asset-1', 'tenant_id': 'tenant-1',
        'hostname': 'edge-hw-01', 'ip_address': '192.0.2.10',
    }
    native_result = {
        'source': 'librenms_native', 'state': 'available', 'message': 'native snapshot',
        'matched_device_id': 'device-hw-1', 'matched_hostname': 'edge-hw-01',
        'binding': {'id': 'binding-1'}, 'engine': {'name': 'LibreNMS'},
        'identity': {'native_device_id': '17'}, 'collection': {'sample_status': 'available'},
        'health_graphs': [], 'hardware_sensors': [], 'processor_sensors': [], 'memory_pools': [],
        'transceivers': [], 'wireless_sensors': [], 'sensor_count': 0, 'metric_summary': [],
        'live_poll_status': 'not_run', 'background_snapshot_status': 'available',
    }
    seen: list[dict] = []

    monkeypatch.setattr(
        devices_api, '_find_snmp_walk_targets',
        lambda **kwargs: [device] if kwargs['user'] == {'role': 'Operator'} else [],
    )
    monkeypatch.setattr(
        devices_api, 'resolve_collector_credentials',
        lambda _device: pytest.fail('native diagnostic must not resolve SNMP credentials'),
    )
    async def fake_diagnostic(selected_device):
        seen.append(selected_device)
        return native_result

    monkeypatch.setattr(librenms_diagnostic_service, 'diagnose_librenms_hardware', fake_diagnostic)
    response = asyncio.run(devices_api.test_snmp_hardware_discovery(
        {'device_id': 'device-hw-1', 'version': 'v1', 'oid': '1.3.6.1'},
        user={'role': 'Operator'},
    ))

    assert response == {'success': True, 'data': native_result}
    assert seen == [device]


def test_snmp_hardware_discovery_test_requires_an_explicit_managed_device() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(devices_api.test_snmp_hardware_discovery({}, user={'role': 'Operator'}))
    assert error.value.status_code == 400


def test_snmp_connectivity_sync_delegates_hardware_and_keeps_explicit_interface_sync(monkeypatch) -> None:
    import asyncio as asyncio_module

    from services import collection_status_service, snmp_service

    device = {
        'id': 'device-1', 'asset_id': 'asset-1', 'tenant_id': 'tenant-1',
        'hostname': 'edge-01', 'ip_address': '192.0.2.10', 'platform': 'h3c_comware',
        'model': 'S6800', 'version': '7.1.070', 'snmp_metric_profile_id': 'profile-1',
        'snmp_discovery': {'status': 'matched', 'metrics': {'cpu': {'oid': '1.3.6.1.4.1.999'}}},
    }
    statements: list[str] = []
    interface_calls: list[dict] = []
    pending_background: list[Any] = []

    class Result:
        def fetchone(self):
            return device

    class Connection:
        closed = False

        def execute(self, sql, _params=()):
            statements.append(sql)
            return Result()

        def commit(self):
            pass

        def close(self):
            self.closed = True

    monkeypatch.setattr(devices_api, 'get_db_connection', Connection)
    monkeypatch.setattr(
        devices_api,
        'resolve_collector_credentials',
        lambda _device: {'snmp': {'server': '192.0.2.10', 'community': 'test-community', 'port': 161}},
    )

    def resolve_explicit_profile(profile_device):
        assert 'id' not in profile_device
        assert 'snmp_discovery' not in profile_device
        assert profile_device['snmp_metric_profile_id'] == 'profile-1'
        return {
            'profile_id': 'profile-1', 'profile_status': 'verified',
            'profile_source': 'snmp_template', 'metric_sources': {'cpu': 'snmp_template'},
            'metrics': {'cpu': {'oid': '1.3.6.1.4.1.999'}},
            'interface': {'enabled': True, 'if_name_oid': '1.3.6.1.2.1.31.1.1.1.1'},
        }

    monkeypatch.setattr(devices_api, 'resolve_health_metric_profiles', resolve_explicit_profile)
    async def fake_get(_host, _community, oid, _port, *, timeout=3):
        if oid.endswith('.5.0'):
            return 'edge-live-01'
        return 'H3C Comware Version 7.1.070'

    async def fake_device_info(_host, _community, _port):
        return {'sys_name': 'edge-live-01', 'sys_descr': 'H3C Comware Version 7.1.070', 'uptime': 123}

    async def fake_interface_health(_host, _community, _port, config, *, template_only):
        interface_calls.append({'config': config, 'template_only': template_only})
        return [{
            'name': 'GigabitEthernet1/0/1', 'description': 'uplink', 'status': 'up', 'speed_mbps': 1000,
        }]

    monkeypatch.setattr(snmp_service, '_snmp_get', fake_get)
    monkeypatch.setattr(snmp_service, 'collect_device_info', fake_device_info)
    monkeypatch.setattr(snmp_service, 'collect_interface_health', fake_interface_health)
    monkeypatch.setattr(collection_status_service, 'record_collection_result', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(asyncio_module, 'create_task', lambda coroutine: pending_background.append(coroutine))

    async def run_route_and_background():
        result = await devices_api.snmp_test('device-1')
        assert len(pending_background) == 1
        await pending_background[0]
        return result

    result = asyncio.run(run_route_and_background())

    assert result['success'] is True
    assert result['sys_name'] == 'edge-live-01'
    assert result['hardware_metrics'] == {}
    assert result['metric_details'] == {}
    assert result['hardware_collection_status'] == 'delegated_to_librenms'
    assert result['snmp_discovery_status'] == 'delegated_to_librenms'
    assert result['collection_mode'] == 'connectivity_interface_only'
    assert interface_calls == [{
        'config': {'enabled': True, 'if_name_oid': '1.3.6.1.2.1.31.1.1.1.1'},
        'template_only': True,
    }]
    assert any('INSERT INTO interfaces' in sql for sql in statements)
    assert not any(
        sql.startswith('UPDATE devices') and any(column in sql for column in (
            'cpu_usage', 'memory_usage', 'temp', 'fan_status', 'psu_status',
        ))
        for sql in statements
    )


def test_snmp_system_info_test_reports_live_identity_and_asset_fallback(monkeypatch) -> None:
    from services import snmp_discovery_service, snmp_service

    device = {
        'id': 'device-system-1', 'hostname': 'edge-system-01', 'ip_address': '192.0.2.20',
        'vendor': 'Cisco', 'platform': 'cisco_ios', 'model': 'C9300', 'version': '17.9.4',
    }
    monkeypatch.setattr(devices_api, '_find_snmp_walk_targets', lambda **_kwargs: [device])
    monkeypatch.setattr(
        devices_api,
        'resolve_collector_credentials',
        lambda _device: {'snmp': {'server': '192.0.2.21', 'community': 'test-community', 'port': 1161}},
    )
    requested_oids: list[str] = []
    values = {
        snmp_service.SYS_NAME: 'edge-live-01',
        snmp_service.SYS_DESCR: 'Cisco IOS XE Software, Version 17.12.1',
        snmp_service.SYS_OBJECT_ID: '.1.3.6.1.4.1.9.1.9999',
        snmp_service.SYS_UPTIME: 0,
    }

    async def fake_get(_host, _community, oid, _port, _version):
        requested_oids.append(oid)
        return values[oid]

    monkeypatch.setattr(snmp_service, '_snmp_get_versioned', fake_get)

    class Connection:
        closed = False

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(devices_api, 'get_db_connection', lambda: connection)
    monkeypatch.setattr(
        devices_api,
        'resolve_snmp_vendor_identity',
        lambda conn, **identity: {
            'status': 'identified', 'vendor': 'Cisco', 'platform': 'cisco_ios',
            'model': 'C9300', 'reason': 'matched live sysObjectID',
        } if conn is connection and identity['sys_name'] == 'edge-live-01' else {},
    )
    monkeypatch.setattr(
        snmp_discovery_service,
        'classify_identity',
        lambda **_kwargs: {
            'sys_name': 'edge-live-01', 'sys_descr': values[snmp_service.SYS_DESCR],
            'sys_object_id': values[snmp_service.SYS_OBJECT_ID], 'software_version': '',
        },
    )

    response = asyncio.run(devices_api.test_snmp_system_info(
        {'device_id': 'device-system-1'}, user={'role': 'Operator'},
    ))

    data = response['data']
    assert set(requested_oids) == set(values)
    assert data['sys_name'] == 'edge-live-01'
    assert data['sys_uptime'] == '0'
    assert data['vendor'] == 'Cisco' and data['field_sources']['vendor'] == 'snmp_identity'
    assert data['platform'] == 'cisco_ios' and data['field_sources']['platform'] == 'snmp_identity'
    assert data['model'] == 'C9300' and data['field_sources']['model'] == 'snmp_identity'
    assert data['software_version'] == '17.9.4' and data['field_sources']['software_version'] == 'asset'
    assert 'community' not in data
    assert connection.closed is True


def test_snmp_system_info_test_rejects_empty_response(monkeypatch) -> None:
    from services import snmp_service

    monkeypatch.setattr(
        devices_api, '_find_snmp_walk_targets',
        lambda **_kwargs: [{'id': 'device-system-1', 'ip_address': '192.0.2.20'}],
    )
    monkeypatch.setattr(
        devices_api, 'resolve_collector_credentials',
        lambda _device: {'snmp': {'server': '192.0.2.20', 'community': 'test-community', 'port': 161}},
    )

    async def empty_get(*_args, **_kwargs):
        return None

    monkeypatch.setattr(snmp_service, '_snmp_get_versioned', empty_get)
    with pytest.raises(HTTPException) as error:
        asyncio.run(devices_api.test_snmp_system_info(
            {'device_id': 'device-system-1'}, user={'role': 'Operator'},
        ))

    assert error.value.status_code == 504

@pytest.mark.parametrize('path', [
    '/api/platform-registry/snmp-system-info-test',
    '/api/platform-registry/snmp-hardware-test',
    '/api/platform-registry/snmp-hardware-discovery-test',
])
def test_new_snmp_diagnostics_require_operator_role(monkeypatch, path) -> None:
    from api import users

    app = FastAPI()
    app.include_router(devices_api.router, prefix='/api')
    client = TestClient(app)

    assert client.post(path, json={}).status_code == 401
    monkeypatch.setattr(users, 'validate_session_token', lambda _token: {'username': 'viewer', 'role': 'Viewer'})
    response = client.post(path, json={}, headers={'Authorization': 'Bearer synthetic'})
    assert response.status_code == 403
