import pytest
from fastapi import HTTPException

from api import devices as devices_api


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self, row):
        self._row = row

    def execute(self, *_args):
        return _Result(self._row)

    def close(self):
        return None


def _device(**overrides):
    device = {
        "id": "device-scope-1",
        "tenant_id": "tenant-a",
        "site_id": "site-a",
        "site": "",
        "device_group_id": "group-a",
        "platform": "h3c_comware",
    }
    device.update(overrides)
    return device


def _operator(**overrides):
    user = {"id": "operator-1", "role": "Operator", "tenant_id": "tenant-a"}
    user.update(overrides)
    return user


def test_operational_data_denies_cross_tenant_device_before_collection(monkeypatch):
    device = _device(tenant_id="tenant-b")
    called = False

    def should_not_collect(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(devices_api, "get_db_connection", lambda: _Connection(device))
    monkeypatch.setattr(devices_api, "collect_operational_data", should_not_collect)

    with pytest.raises(HTTPException) as error:
        devices_api.collect_device_operational_data("device-scope-1", {}, user=_operator())

    assert error.value.status_code == 403
    assert error.value.detail["code"] == "RESOURCE_SCOPE_DENIED"
    assert called is False


def test_operational_data_passes_device_scope_to_command_authorization(monkeypatch):
    device = _device()
    seen = {}
    result = {"success": True, "categories": []}

    def allow(user, resource_type, action, **scope):
        seen.update({
            "user": user,
            "resource_type": resource_type,
            "action": action,
            "scope": scope,
        })
        return True

    monkeypatch.setattr(devices_api, "get_db_connection", lambda: _Connection(device))
    monkeypatch.setattr(devices_api, "authorize_resource", allow)
    monkeypatch.setattr(devices_api, "collect_operational_data", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(devices_api, "_record_instant_execution", lambda *_args, **_kwargs: None)

    assert devices_api.collect_device_operational_data(
        "device-scope-1",
        {"categories": ["transceiver"]},
        user=_operator(),
    ) == result
    assert seen["resource_type"] == "command"
    assert seen["action"] == "execute"
    assert seen["scope"] == {
        "tenant_id": "tenant-a",
        "site_id": "site-a",
        "device_group_id": "group-a",
    }


def test_operational_data_denies_site_or_group_outside_resource_scope(monkeypatch):
    device = _device(site_id="site-b", device_group_id="group-b")
    monkeypatch.setattr(devices_api, "authorize_resource", lambda *_args, **_kwargs: False)

    with pytest.raises(HTTPException) as error:
        devices_api._assert_operational_data_device_scope(_operator(), device)

    assert error.value.status_code == 403
    assert error.value.detail["resource_type"] == "command"
