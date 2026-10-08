from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import api.devices as devices_api
from api.devices import resolve_snmp_walk_target, test_snmp_walk as run_snmp_walk_test


def test_snmp_hardware_test_rejects_local_metric_definitions() -> None:
    with pytest.raises(HTTPException) as error:
        devices_api.test_snmp_hardware_metrics(
            {"device_id": "device-1", "metric_definitions": {"cpu": {"oid": "1.3.6.1.4.1.8"}}},
            user={"role": "Operator"},
        )
    assert error.value.status_code == 410
    assert error.value.detail["code"] == "LIBRENMS_RULES_ONLY"


def test_legacy_snmp_hardware_test_is_retired_even_with_device_id() -> None:
    with pytest.raises(HTTPException) as error:
        devices_api.test_snmp_hardware_metrics({'device_id': 'device-1'}, user={'role': 'Operator'})
    assert error.value.status_code == 410


def test_snmp_target_resolution_uses_an_exact_managed_ip(monkeypatch) -> None:
    class Result:
        def __init__(self, rows=()):
            self.rows = list(rows)

        def fetchall(self):
            return list(self.rows)

    class Connection:
        def execute(self, sql, params=()):
            assert 'd.ip_address = ?' in sql
            assert params == ('10.254.99.1', '10.254.99.1')
            return Result([{'id': 'device-exact', 'hostname': 'edge-exact', 'ip_address': '10.254.99.1', 'tenant_id': 'tenant-1'}])

        def close(self):
            pass

    monkeypatch.setattr(devices_api, 'get_db_connection', lambda: Connection())
    targets = devices_api._find_snmp_walk_targets(ip='10.254.99.1', user={'role': 'Administrator'})

    assert [target['id'] for target in targets] == ['device-exact']


def test_snmp_walk_target_confirms_exact_ip(monkeypatch) -> None:
    class Result:
        def __init__(self, rows=()):
            self.rows = list(rows)

        def fetchall(self):
            return list(self.rows)

    class Connection:
        def execute(self, sql, params=()):
            if 'FROM devices' in sql:
                return Result([{
                    'id': 'device-1',
                    'hostname': 'edge-01',
                    'ip_address': '10.254.0.1',
                    'asset_id': 'asset-1',
                }])
            return Result([])

        def close(self):
            pass

    monkeypatch.setattr(devices_api, 'get_db_connection', lambda: Connection())
    response = resolve_snmp_walk_target('10.254.0.1', user={'role': 'Administrator'})

    assert response == {
        'success': True,
        'data': {'ip': '10.254.0.1', 'device_id': 'device-1', 'hostname': 'edge-01'},
    }


def test_snmp_walk_target_reports_ip_not_found(monkeypatch) -> None:
    class Result:
        def fetchall(self):
            return []

    class Connection:
        def execute(self, sql, params=()):
            return Result()

        def close(self):
            pass

    monkeypatch.setattr(devices_api, 'get_db_connection', lambda: Connection())
    with pytest.raises(HTTPException) as error:
        resolve_snmp_walk_target('10.254.0.99', user={'role': 'Administrator'})

    assert error.value.status_code == 404
    assert 'IP not found' in str(error.value.detail)


def test_snmp_hardware_discovery_test_returns_local_snapshot_without_python_probes(monkeypatch) -> None:
    from services import librenms_diagnostic_service

    device = {
        'id': 'device-hw-1', 'asset_id': 'asset-1', 'tenant_id': 'tenant-1',
        'hostname': 'edge-hw-01', 'ip_address': '192.0.2.10',
    }
    native_result = {
        'source': 'nexora_snmp', 'state': 'available', 'message': 'local snapshot',
        'matched_device_id': 'device-hw-1', 'matched_hostname': 'edge-hw-01',
        'binding': None, 'engine': {'name': 'Nexora SNMP collector'},
        'identity': {'hostname': 'edge-hw-01'}, 'collection': {'sample_status': 'available'},
        'health_graphs': [], 'hardware_sensors': [], 'processor_sensors': [], 'memory_pools': [],
        'transceivers': [], 'wireless_sensors': [], 'sensor_count': 0, 'metric_summary': [],
        'live_poll_status': 'not_run', 'background_snapshot_status': 'available',
    }
    seen: list[dict] = []

    monkeypatch.setattr(
        devices_api, '_find_snmp_walk_targets',
        lambda **kwargs: [device] if kwargs['user'] == {'role': 'Operator', 'tenant_id': 'tenant-1'} else [],
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
        {'device_id': 'device-hw-1'},
        user={'role': 'Operator', 'tenant_id': 'tenant-1'},
    ))

    assert response == {'success': True, 'data': native_result}
    assert seen == [device]


def test_snmp_hardware_discovery_test_requires_an_explicit_managed_device() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(devices_api.test_snmp_hardware_discovery({}, user={'role': 'Operator'}))
    assert error.value.status_code == 400


def test_device_snmp_test_uses_only_the_librenms_rule_probe(monkeypatch) -> None:
    from services.librenms_source_policy import PINNED_LIBRENMS_COMMIT

    device = {"id": "device-1", "hostname": "edge-01", "ip_address": "192.0.2.1", "tenant_id": "tenant-1"}

    class Result:
        def fetchone(self):
            return device

    class Connection:
        def execute(self, _sql, _params=()):
            return Result()

        def close(self):
            pass

    monkeypatch.setattr(devices_api, "get_db_connection", Connection)
    from services import snmp_hardware_poller_service

    async def fake_inspect(target):
        assert target == device
        return {
            "status": "success",
            "identity": {"sys_name": "edge-01", "sys_descr": "H3C Comware", "sys_object_id": ".1.3.6.1.4.1.25506"},
            "rule": {
                "os_key": "comware", "vendor": "H3C", "platform": "comware",
                "source_path": "resources/definitions/os_detection/comware.yaml",
                "discovery_source_path": "resources/definitions/os_discovery/comware.yaml",
                "hardware_definitions": {"processors": [{}]},
                "source_commit": PINNED_LIBRENMS_COMMIT,
            },
            "sensor_count": 0, "sensors": [], "category_results": [],
        }

    monkeypatch.setattr(snmp_hardware_poller_service, "inspect_librenms_hardware_rules", fake_inspect)
    result = asyncio.run(devices_api.snmp_test("device-1", user={"role": "Operator", "tenant_id": "tenant-1"}))

    assert result["success"] is True
    assert result["collection_mode"] == "pinned_librenms_rule_diagnostic"
    assert result["rule_source_path"] == "resources/definitions/os_detection/comware.yaml"
    assert result["hardware_metrics"] == {}
    assert result["sensors"] == []


def test_legacy_manual_walk_endpoint_is_removed() -> None:
    with pytest.raises(HTTPException) as error:
        asyncio.run(run_snmp_walk_test(
            {"ip": "192.0.2.1", "community": "public", "oid": "1.3.6.1"},
            user={"role": "Operator"},
        ))
    assert error.value.status_code == 410
    assert error.value.detail["code"] == "MANUAL_OID_WALK_REMOVED"


def test_librenms_rule_diagnostic_accepts_only_managed_device_id(monkeypatch) -> None:
    from services.librenms_source_policy import PINNED_LIBRENMS_COMMIT

    device = {"id": "device-1", "hostname": "edge-01", "ip_address": "192.0.2.1", "tenant_id": "tenant-1"}
    monkeypatch.setattr(devices_api, "_find_snmp_walk_targets", lambda **kwargs: [device] if kwargs["device_id"] == "device-1" else [])

    async def fake_inspect(target):
        assert target is device
        return {
            "status": "success",
            "identity": {"sys_object_id": ".1.3.6.1.4.1.25506", "sys_descr": "H3C Comware", "sys_name": "edge-01"},
            "rule": {
                "id": "rule-comware", "os_key": "comware", "vendor": "H3C", "platform": "comware",
                "source_path": "resources/definitions/os_detection/comware.yaml",
                "discovery_source_path": "resources/definitions/os_discovery/comware.yaml",
                "hardware_definitions": {"processors": [{}]},
                "source_commit": PINNED_LIBRENMS_COMMIT,
            },
            "category_results": [], "sensor_count": 1,
            "sensors": [{"source_type": "librenms_rule", "source_id": "cpu-1", "component_class": "processor",
                "measurement_type": "usage", "sensor_name": "CPU", "oid": "1.3.6.1.4.1.25506.2.6.1",
                "index": [0], "value": 12.0, "raw_value": "12", "unit": "%", "quality": "good",
                "metadata": {"source_path": "resources/definitions/os_discovery/comware.yaml",
                    "source_commit": PINNED_LIBRENMS_COMMIT}}],
        }

    from services import snmp_hardware_poller_service
    monkeypatch.setattr(snmp_hardware_poller_service, "inspect_librenms_hardware_rules", fake_inspect)
    result = asyncio.run(devices_api.test_librenms_rule_probe(
        {"device_id": "device-1"}, user={"role": "Operator", "tenant_id": "tenant-1"},
    ))
    assert result["data"]["rule_source_path"] == "resources/definitions/os_detection/comware.yaml"
    assert result["data"]["rule_source_commit"] == PINNED_LIBRENMS_COMMIT
    assert result["data"]["sensors"][0]["source_type"] == "librenms_rule"


def test_librenms_rule_diagnostic_rejects_custom_oid_and_target_fields(monkeypatch) -> None:
    monkeypatch.setattr(devices_api, "_find_snmp_walk_targets", lambda **_kwargs: pytest.fail("must reject before resolving a device"))
    with pytest.raises(HTTPException) as error:
        asyncio.run(devices_api.test_librenms_rule_probe(
            {"device_id": "device-1", "oid": "1.3.6.1", "community": "public"},
            user={"role": "Operator"},
        ))
    assert error.value.status_code == 400
    assert error.value.detail["code"] == "MANUAL_OID_PROBE_DISABLED"


def test_legacy_vendor_system_and_interface_snmp_probes_are_removed() -> None:
    endpoints = (devices_api.detect_snmp_walk_vendor, devices_api.test_snmp_system_info, devices_api.test_snmp_interface_oids)
    for endpoint in endpoints:
        with pytest.raises(HTTPException) as error:
            asyncio.run(endpoint({"device_id": "device-1", "oid": "1.3.6.1"}, user={"role": "Operator"}))
        assert error.value.status_code == 410
        assert error.value.detail["code"] == "LIBRENMS_RULES_ONLY"


@pytest.mark.parametrize(('path', 'method'), [
    ('/api/platform-registry/snmp-metric-profiles', 'get'),
    ('/api/platform-registry/snmp-metric-profiles/profile-1', 'put'),
    ('/api/platform-registry/snmp-metric-profiles/profile-1/test', 'post'),
    ('/api/platform-registry/mibs/presets/models', 'get'),
    ('/api/platform-registry/mibs/auto-match', 'get'),
])
def test_local_snmp_profile_and_preset_apis_are_retired(monkeypatch, path, method) -> None:
    from api import users

    app = FastAPI()
    app.include_router(devices_api.router, prefix='/api')
    client = TestClient(app)
    monkeypatch.setattr(users, 'validate_session_token', lambda _token: {'username': 'admin', 'role': 'Operator'})
    if method == 'get':
        response = client.get(path, headers={'Authorization': 'Bearer synthetic'})
    else:
        response = getattr(client, method)(path, json={}, headers={'Authorization': 'Bearer synthetic'})
    assert response.status_code == 410
    assert response.json()['detail']['code'] == 'LIBRENMS_RULES_ONLY'


@pytest.mark.parametrize('path', [
    '/api/platform-registry/snmp-librenms-rule-test',
    '/api/platform-registry/snmp-walk-test',
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
