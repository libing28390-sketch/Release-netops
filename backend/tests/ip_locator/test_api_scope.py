from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from api import ip_locator
from services import ip_locator_task_service


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.rows = rows
        self.closed = False

    def execute(self, _sql, params):
        tenant_id = params[0]
        return _Rows([row for row in self.rows if row["tenant_id"] == tenant_id])

    def close(self):
        self.closed = True


def test_authorized_locator_devices_apply_tenant_site_and_asset_scope(monkeypatch):
    rows = [
        {"id": "a-core", "tenant_id": "tenant-a", "site_id": "site-a", "site": ""},
        {"id": "a-access", "tenant_id": "tenant-a", "site_id": "site-b", "site": ""},
        {"id": "b-core", "tenant_id": "tenant-b", "site_id": "site-a", "site": ""},
    ]
    connection = _Connection(rows)
    monkeypatch.setattr(ip_locator, "get_db_connection", lambda: connection)
    monkeypatch.setattr(
        ip_locator,
        "authorize_resource",
        lambda user, resource, action, **scope: (
            resource == "asset"
            and action == "read"
            and scope.get("tenant_id") == "tenant-a"
            and scope.get("site_id") in {"site-a", "site-b"}
        ),
    )

    selected = ip_locator._authorized_locator_device_ids(
        {"id": "viewer-1", "role": "Viewer", "tenant_id": "tenant-a"},
        site_id="site-a",
    )

    assert selected == ["a-core"]
    assert connection.closed is True


def test_authorized_locator_device_candidates_fail_closed_without_tenant(monkeypatch):
    monkeypatch.setattr(
        ip_locator,
        "get_db_connection",
        lambda: (_ for _ in ()).throw(AssertionError("must not query without tenant")),
    )

    assert ip_locator._authorized_locator_device_ids({"role": "Viewer", "tenant_id": ""}) == []


_USER = {"id": "viewer-1", "role": "Viewer", "tenant_id": "tenant-a"}


def _run(*, tenant_id="tenant-a", site_id="site-a", stats=None):
    return {
        "id": "run-1",
        "owner_id": "viewer-1",
        "tenant_id": tenant_id,
        "site_id": site_id,
        "stats": {"authorized_device_ids": ["device-a"]} if stats is None else stats,
        "result": {"target_ip": "192.0.2.10"},
    }


def _mock_run_service(monkeypatch, run, *, cancelled=None):
    calls = []

    def get_locator_run(run_id, *, owner_id):
        calls.append(("get", run_id, owner_id))
        return run

    def cancel_locator_run(run_id, *, owner_id):
        calls.append(("cancel", run_id, owner_id))
        return cancelled if cancelled is not None else run

    monkeypatch.setattr(ip_locator_task_service, "get_locator_run", get_locator_run)
    monkeypatch.setattr(ip_locator_task_service, "cancel_locator_run", cancel_locator_run)
    return calls


@pytest.mark.parametrize("operation", ["get", "cancel"])
@pytest.mark.parametrize(
    "stats",
    [
        {"authorized_device_ids": ["device-a"]},
        '{"authorized_device_ids":["device-a"]}',
    ],
    ids=["decoded-stats", "json-stats"],
)
def test_locator_run_access_is_accepted_when_current_scope_still_covers_run(
    monkeypatch, operation, stats
):
    run = _run(stats=stats)
    cancelled = {**run, "status": "cancelled"}
    calls = _mock_run_service(monkeypatch, run, cancelled=cancelled)
    authorization_checks = []

    def current_devices(user, *, site_id="", online_only=True):
        authorization_checks.append((user, site_id))
        assert online_only is False
        return ["device-a", "device-b"]

    monkeypatch.setattr(ip_locator, "_authorized_locator_device_ids", current_devices)

    if operation == "get":
        result = asyncio.run(ip_locator.api_get_locator_run("run-1", user=_USER))
        assert result is run
        assert [call[0] for call in calls] == ["get"]
    else:
        result = asyncio.run(ip_locator.api_cancel_locator_run("run-1", user=_USER))
        assert result is cancelled
        assert [call[0] for call in calls] == ["get", "cancel"]

    assert authorization_checks == [(_USER, "site-a")]


@pytest.mark.parametrize("operation", ["get", "cancel"])
@pytest.mark.parametrize(
    "run,current_devices",
    [
        (_run(tenant_id="tenant-b"), ["device-a"]),
        (_run(site_id=None), ["device-a"]),
        (_run(), []),
        (_run(), ["device-b"]),
    ],
    ids=["tenant-mismatch", "malformed-site", "site-scope-empty", "device-revoked"],
)
def test_locator_run_denies_tenant_or_revoked_device_scope_with_404(
    monkeypatch, operation, run, current_devices
):
    calls = _mock_run_service(monkeypatch, run)
    monkeypatch.setattr(
        ip_locator,
        "_authorized_locator_device_ids",
        lambda user, *, site_id="", online_only=True: current_devices,
    )

    endpoint = ip_locator.api_get_locator_run if operation == "get" else ip_locator.api_cancel_locator_run
    with pytest.raises(HTTPException) as error:
        asyncio.run(endpoint("run-1", user=_USER))

    assert error.value.status_code == 404
    assert error.value.detail == "定位任务不存在或无权访问"
    assert [call[0] for call in calls] == ["get"]


@pytest.mark.parametrize("operation", ["get", "cancel"])
@pytest.mark.parametrize(
    "stats",
    [None, "not-json", {"authorized_device_ids": "device-a"}, {"authorized_device_ids": []}],
    ids=["missing", "malformed-json", "malformed-device-list", "empty-device-list"],
)
def test_locator_run_denies_missing_or_malformed_authorization_metadata(
    monkeypatch, operation, stats
):
    run = _run()
    if stats is None:
        run.pop("stats")
    else:
        run["stats"] = stats
    calls = _mock_run_service(monkeypatch, run)
    monkeypatch.setattr(
        ip_locator,
        "_authorized_locator_device_ids",
        lambda user, *, site_id="", online_only=True: ["device-a"],
    )

    endpoint = ip_locator.api_get_locator_run if operation == "get" else ip_locator.api_cancel_locator_run
    with pytest.raises(HTTPException) as error:
        asyncio.run(endpoint("run-1", user=_USER))

    assert error.value.status_code == 404
    assert error.value.detail == "定位任务不存在或无权访问"
    assert [call[0] for call in calls] == ["get"]


@pytest.mark.parametrize("operation", ["get", "cancel"])
@pytest.mark.parametrize("service_result", [None, RuntimeError("owner mismatch")], ids=["missing", "other-owner"])
def test_locator_run_missing_or_cross_owner_keeps_indistinguishable_404(
    monkeypatch, operation, service_result
):
    calls = []

    def get_locator_run(run_id, *, owner_id):
        calls.append((run_id, owner_id))
        if isinstance(service_result, Exception):
            raise service_result
        return service_result

    monkeypatch.setattr(ip_locator_task_service, "get_locator_run", get_locator_run)
    monkeypatch.setattr(
        ip_locator_task_service,
        "cancel_locator_run",
        lambda *args, **kwargs: pytest.fail("must not cancel an unreadable run"),
    )
    monkeypatch.setattr(
        ip_locator,
        "_authorized_locator_device_ids",
        lambda *args, **kwargs: pytest.fail("must not authorize an unreadable run"),
    )

    endpoint = ip_locator.api_get_locator_run if operation == "get" else ip_locator.api_cancel_locator_run
    with pytest.raises(HTTPException) as error:
        asyncio.run(endpoint("run-1", user=_USER))

    assert error.value.status_code == 404
    assert error.value.detail == "定位任务不存在或无权访问"
    assert calls == [("run-1", "viewer-1")]
