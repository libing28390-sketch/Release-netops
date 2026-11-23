"""Scheduled topology discovery reuses the manual discovery pipeline.

The job is opt-in (TOPOLOGY_AUTOMATIC_DISCOVERY_ENABLED). These tests patch
the run store and the worker, so no database or device is touched.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from services import topology_service


class _Lease:
    def __init__(self):
        self.release_count = 0

    def __enter__(self):
        return self

    def release(self):
        self.release_count += 1
        return True


def _run(coro):
    return asyncio.run(coro)


def test_scheduled_discovery_is_a_no_op_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(topology_service, "TOPOLOGY_AUTOMATIC_DISCOVERY_ENABLED", False)

    def _fail(*_args, **_kwargs):
        raise AssertionError("disabled scheduled discovery must not select devices")

    monkeypatch.setattr(topology_service, "select_topology_discovery_devices", _fail)

    assert _run(topology_service.run_automatic_topology_discovery()) == {"status": "disabled"}


def test_scheduled_discovery_skips_while_another_run_is_active(monkeypatch) -> None:
    monkeypatch.setattr(topology_service, "TOPOLOGY_AUTOMATIC_DISCOVERY_ENABLED", True)
    monkeypatch.setattr(topology_service, "_has_recent_active_discovery_run", lambda: True)

    def _fail(*_args, **_kwargs):
        raise AssertionError("an active run must block a second scheduled run")

    monkeypatch.setattr(topology_service, "create_discovery_run", _fail)
    monkeypatch.setattr(topology_service, "acquire_topology_discovery_lease", _fail)

    assert _run(topology_service.run_automatic_topology_discovery()) == {"status": "skipped_active_run"}


def test_scheduled_discovery_skips_when_no_device_is_eligible(monkeypatch) -> None:
    monkeypatch.setattr(topology_service, "TOPOLOGY_AUTOMATIC_DISCOVERY_ENABLED", True)
    monkeypatch.setattr(topology_service, "_has_recent_active_discovery_run", lambda: False)
    lease = _Lease()
    monkeypatch.setattr(topology_service, "acquire_topology_discovery_lease", lambda: lease)
    monkeypatch.setattr(
        topology_service,
        "select_topology_discovery_devices",
        lambda scope, **_kwargs: {"scope": scope, "device_ids": [], "excluded_device_ids": []},
    )

    assert _run(topology_service.run_automatic_topology_discovery()) == {"status": "no_devices"}
    assert lease.release_count == 1


def test_scheduled_discovery_creates_an_idempotent_full_scope_run(monkeypatch) -> None:
    monkeypatch.setattr(topology_service, "TOPOLOGY_AUTOMATIC_DISCOVERY_ENABLED", True)
    monkeypatch.setattr(topology_service, "_has_recent_active_discovery_run", lambda: False)
    lease = _Lease()
    monkeypatch.setattr(topology_service, "acquire_topology_discovery_lease", lambda: lease)
    selected_scopes: list[str] = []

    def _select(scope, **_kwargs):
        selected_scopes.append(scope)
        return {"scope": scope, "device_ids": ["dev-a", "dev-b"], "excluded_device_ids": []}

    created: list[dict] = []

    def _create(**kwargs):
        created.append(kwargs)
        return "run-auto-1"

    executed: list[tuple[str, list[str], object]] = []

    async def _execute(run_id, device_ids, *, discovery_lease=None):
        executed.append((run_id, list(device_ids), discovery_lease))

    monkeypatch.setattr(topology_service, "select_topology_discovery_devices", _select)
    monkeypatch.setattr(topology_service, "create_discovery_run", _create)
    monkeypatch.setattr(topology_service, "execute_discovery_run", _execute)

    result = _run(topology_service.run_automatic_topology_discovery())

    assert result == {"status": "started", "run_id": "run-auto-1", "device_count": 2}
    assert selected_scopes == ["full"]
    assert executed == [("run-auto-1", ["dev-a", "dev-b"], lease)]
    assert lease.release_count == 1
    request = created[0]
    assert request["device_ids"] == ["dev-a", "dev-b"]
    assert request["requested_by"] == "system:automatic"
    assert request["scope"] == "full"
    assert request["scope_payload"]["trigger"] == "automatic"
    assert request["idempotency_key"].startswith(f"{topology_service.TOPOLOGY_AUTOMATIC_DISCOVERY_JOB_ID}:")


def test_old_started_at_does_not_hide_a_live_scheduler_or_run_lease(isolated_db) -> None:
    database = isolated_db["module"]
    conn = database.get_db_connection()
    try:
        conn.execute(
            "INSERT INTO topology_discovery_runs (id, status, started_at) VALUES (?, ?, ?)",
            ("old-run", "running", "2000-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    assert topology_service._has_recent_active_discovery_run() is False
    lease = topology_service.acquire_topology_discovery_lease()
    assert lease is not None
    try:
        # A recent scheduler lease is authoritative even when the run itself
        # has an old started_at value.
        assert topology_service._has_recent_active_discovery_run() is True
    finally:
        lease.release()
    assert topology_service._has_recent_active_discovery_run() is False


def test_live_run_heartbeat_blocks_even_after_shared_scheduler_lease_expires(isolated_db):
    database = isolated_db["module"]
    conn = database.get_db_connection()
    try:
        conn.execute(
            "INSERT INTO topology_discovery_runs (id, status, started_at) VALUES (?, ?, ?)",
            ("live-run", "running", "2000-01-01T00:00:00+00:00"),
        )
        now = datetime.now(timezone.utc)
        conn.execute(
            "UPDATE topology_discovery_runs SET lease_expires_at = ?, heartbeat_at = ? WHERE id = ?",
            (
                (now + timedelta(minutes=2)).replace(microsecond=0).isoformat(),
                now.replace(microsecond=0).isoformat(),
                "live-run",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    assert topology_service._has_recent_active_discovery_run() is True
    assert topology_service.acquire_topology_discovery_lease() is None
