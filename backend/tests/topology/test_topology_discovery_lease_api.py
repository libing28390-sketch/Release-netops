from __future__ import annotations

import asyncio

import pytest
from fastapi import BackgroundTasks, HTTPException
from starlette.requests import Request

from api import topology as topology_api


class _Connection:
    def close(self):
        pass


class _Lease:
    def __init__(self):
        self.release_count = 0

    def release(self):
        self.release_count += 1
        return True


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/topology/discover",
        "headers": [],
        "query_string": b"",
    })


def _mock_selection_path(monkeypatch) -> None:
    monkeypatch.setattr(topology_api, "get_db_connection", lambda: _Connection())
    monkeypatch.setattr(topology_api, "_get_authenticated_session", lambda _request: {"username": "operator-a"})
    monkeypatch.setattr(topology_api, "_topology_asset_scope", lambda *_args: None)
    monkeypatch.setattr(topology_api, "_authorized_topology_device_ids", lambda *_args: None)
    monkeypatch.setattr(
        topology_api,
        "select_topology_discovery_devices",
        lambda scope, **_kwargs: {
            "scope": scope,
            "site_id": "",
            "device_ids": ["dev-a"],
            "excluded_device_ids": [],
        },
    )


def test_manual_discovery_returns_conflict_when_shared_lease_is_held(monkeypatch):
    _mock_selection_path(monkeypatch)
    monkeypatch.setattr(topology_api, "acquire_topology_discovery_lease", lambda: None)
    monkeypatch.setattr(
        topology_api,
        "create_discovery_run",
        lambda **_kwargs: pytest.fail("busy discovery must not create a pending run"),
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(topology_api.trigger_discovery(
            _request(),
            BackgroundTasks(),
            topology_api.TopologyDiscoveryRequest(),
            _user={"id": "operator-a", "role": "Operator"},
        ))

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "topology_discovery_active"


def test_manual_discovery_same_key_replay_returns_original_run_before_busy_check(monkeypatch):
    _mock_selection_path(monkeypatch)
    monkeypatch.setattr(
        topology_api,
        "find_discovery_run_by_idempotency_key",
        lambda key: {
            "id": "run-original",
            "scope": "full",
            "status": "running",
            "requested_by": "operator-a",
            "site_id": "",
            "total_devices": 1,
            "has_live_lease": True,
            "scope_payload": {
                "selected_device_ids": ["dev-a"],
                "excluded_device_ids": [],
            },
        },
    )
    monkeypatch.setattr(
        topology_api,
        "acquire_topology_discovery_lease",
        lambda: pytest.fail("same-key replay must reuse the existing run"),
    )

    result = asyncio.run(topology_api.trigger_discovery(
        _request(),
        BackgroundTasks(),
        topology_api.TopologyDiscoveryRequest(),
        idempotency_key="request-key-1",
        _user={"id": "operator-a", "role": "Operator"},
    ))

    assert result["run_id"] == "run-original"
    assert result["device_count"] == 1


def test_manual_discovery_passes_reserved_lease_to_background_worker(monkeypatch):
    _mock_selection_path(monkeypatch)
    lease = _Lease()
    monkeypatch.setattr(topology_api, "acquire_topology_discovery_lease", lambda: lease)
    monkeypatch.setattr(topology_api, "create_discovery_run", lambda **_kwargs: "run-new")
    monkeypatch.setattr(topology_api, "get_discovery_run", lambda _run_id: {"run": {"status": "pending"}})
    background_tasks = BackgroundTasks()

    result = asyncio.run(topology_api.trigger_discovery(
        _request(),
        background_tasks,
        topology_api.TopologyDiscoveryRequest(),
        _user={"id": "operator-a", "role": "Operator"},
    ))

    assert result["run_id"] == "run-new"
    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func is topology_api.execute_discovery_run
    assert task.args == ("run-new", ["dev-a"])
    assert task.kwargs["discovery_lease"] is lease
    assert lease.release_count == 0
