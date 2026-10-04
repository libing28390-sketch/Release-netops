from __future__ import annotations

import asyncio

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


def test_snmp_hardware_test_returns_metric_results_without_oid_rows(monkeypatch) -> None:
    calls: list[dict] = []

    monkeypatch.setattr(
        devices_api,
        '_find_snmp_walk_targets',
        lambda **_kwargs: [{
            'id': 'device-1',
            'hostname': 'edge-01',
            'ip_address': '10.254.0.1',
            'platform': 'h3c_comware',
        }],
    )
    monkeypatch.setattr(
        devices_api,
        'resolve_collector_credentials',
        lambda _device: {'snmp': {'server': '10.254.0.1', 'community': 'secret', 'port': 161}},
    )

    async def fake_collect(
        _ip,
        _platform,
        _community,
        _port,
        *,
        custom_metrics=None,
        device_id='',
        metric_profile_id='',
        bypass_cache=False,
        version='2c',
        template_only=False,
    ):
        calls.append({
            'custom_metrics': custom_metrics,
            'device_id': device_id,
            'metric_profile_id': metric_profile_id,
            'bypass_cache': bypass_cache,
            'version': version,
            'template_only': template_only,
        })
        return {
            'cpu_usage': 18,
            'memory_usage': 42,
            'temp': 32,
            'fan_status': True,
            'psu_status': True,
            'hardware_metrics': {
                'cpu': 18,
                'memory': 42,
                'temperature': 32,
                'fan': True,
                'power_supply': True,
            },
            'metric_details': {
                'temperature': {
                    'value': 32,
                    'raw_value': 32,
                    'status': 'ok',
                    'passed': True,
                    'mode': 'direct_value',
                    'oid': '1.3.6.1.4.1.7',
                    'unit': '°C',
                },
                'cpu': {
                    'value': 18,
                    'raw_value': 18,
                    'status': 'ok',
                    'passed': True,
                    'mode': 'direct_percent',
                    'oid': '1.3.6.1.4.1.8',
                    'unit': '%',
                },
            },
        }

    monkeypatch.setattr(devices_api, 'collect_device_metrics', fake_collect)
    from api.devices import test_snmp_hardware_metrics

    response = asyncio.run(
        test_snmp_hardware_metrics(
            {
                'device_id': 'device-1',
                'version': '2c',
                'metric_definitions': {
                    'temperature': {
                        'mode': 'direct_value',
                        'oid': '1.3.6.1.4.1.7',
                        'unit': '°C',
                    },
                    'cpu': {
                        'mode': 'direct_percent',
                        'oid': '1.3.6.1.4.1.8',
                    },
                },
            },
            user={'role': 'Operator'},
        )
    )

    assert response['success'] is True
    assert response['data']['status'] == 'ok'
    assert response['data']['metric_count'] == 5
    assert set(response['data']['metrics']) == {'temperature', 'cpu', 'memory', 'fan', 'power_supply'}
    assert response['data']['metrics']['temperature']['source'] == 'template_definition'
    assert response['data']['metrics']['fan']['source'] == 'snmp_template'
    assert 'rows' not in response['data']
    assert calls[0]['version'] == '2c'
    assert calls[0]['bypass_cache'] is True
    assert calls[0]['template_only'] is True
    assert calls[0]['device_id'] == 'device-1'
    assert set(calls[0]['custom_metrics']) == {'temperature', 'cpu'}


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


def test_snmp_hardware_discovery_test_uses_collection_discovery_and_bounds_response(monkeypatch) -> None:
    from services import snmp_discovery_service

    calls: list[dict] = []
    device = {
        'id': 'device-hw-1', 'hostname': 'edge-hw-01', 'ip_address': '192.0.2.10',
        'vendor': 'H3C', 'platform': 'h3c_comware', 'model': 'S6800', 'version': '7.1.070',
        'role': 'access_switch',
    }
    monkeypatch.setattr(devices_api, '_find_snmp_walk_targets', lambda **_kwargs: [device])
    monkeypatch.setattr(
        devices_api,
        'resolve_collector_credentials',
        lambda _device: {'snmp': {'server': '192.0.2.11', 'community': 'test-community', 'port': 1161}},
    )

    async def fake_discovery(host, community, port, **kwargs):
        calls.append({'host': host, 'community': community, 'port': port, **kwargs})
        return {
            'status': 'supported',
            'identity': {'status': 'identified', 'vendor': 'H3C', 'platform': 'h3c_comware', 'model': 'S6800'},
            'librenms_rule_id': 'h3c-comware',
            'librenms_source_path': 'definitions/os_discovery/comware.yaml',
            'hardware_support_status': 'partial',
            'hardware_compatibility': {'reason': 'One optional category is unavailable'},
            'hardware_category_results': [{
                'source_type': 'librenms', 'component_class': 'temperature', 'status': 'available',
                'coverage_complete': False, 'reason_code': 'partial', 'reason': 'Some sensors did not answer',
            }],
            'hardware_sensors': [
                {'source_type': 'librenms', 'component_class': 'temperature', 'measurement_type': 'temperature',
                 'sensor_name': f'Temperature {index}', 'value': index, 'raw_value': str(index), 'unit': 'celsius',
                 'quality': 'good', 'oid': '1.3.6.1.4.1.25506.2', 'index': [index]}
                for index in range(205)
            ],
        }

    monkeypatch.setattr(snmp_discovery_service, 'discover_device_oid_config', fake_discovery)
    response = asyncio.run(devices_api.test_snmp_hardware_discovery(
        {'device_id': 'device-hw-1', 'version': 'v1'}, user={'role': 'Operator'},
    ))

    data = response['data']
    assert calls == [{
        'host': '192.0.2.11', 'community': 'test-community', 'port': 1161,
        'vendor': 'H3C', 'platform': 'h3c_comware', 'model': 'S6800', 'version': '7.1.070',
        'role': 'access_switch', 'snmp_version': '1',
    }]
    assert data['version'] == '1'
    assert data['librenms_rule_id'] == 'h3c-comware'
    assert data['hardware_support_status'] == 'partial'
    assert data['category_results'][0]['reason_code'] == 'partial'
    assert data['sensor_count'] == 205
    assert len(data['hardware_sensors']) == 200
    assert data['sensors_truncated'] is True
    assert 'community' not in data


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
        lambda _device: {'snmp': {'server': '192.0.2.21', 'community': 'test-community', 'port': 161}},
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
        lambda **_kwargs: {'sys_name': 'edge-live-01', 'sys_descr': values[snmp_service.SYS_DESCR],
                           'sys_object_id': values[snmp_service.SYS_OBJECT_ID], 'software_version': ''},
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
        devices_api,
        '_find_snmp_walk_targets',
        lambda **_kwargs: [{'id': 'device-system-1', 'ip_address': '192.0.2.20'}],
    )
    monkeypatch.setattr(
        devices_api,
        'resolve_collector_credentials',
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


def test_new_snmp_diagnostics_require_operator_role(monkeypatch) -> None:
    from api import users

    app = FastAPI()
    app.include_router(devices_api.router, prefix='/api')
    client = TestClient(app)
    path = '/api/platform-registry/snmp-system-info-test'

    assert client.post(path, json={}).status_code == 401
    monkeypatch.setattr(users, 'validate_session_token', lambda _token: {'username': 'viewer', 'role': 'Viewer'})
    response = client.post(path, json={}, headers={'Authorization': 'Bearer synthetic'})
    assert response.status_code == 403
