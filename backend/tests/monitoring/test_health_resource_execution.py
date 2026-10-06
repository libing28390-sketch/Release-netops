from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import threading
import uuid

import httpx
import pytest
from fastapi import FastAPI

from api import health
from database import get_db_connection


def _snapshot() -> dict:
    return {
        "status": "critical",
        "metrics_available": True,
        "cpu_percent": 98.0,
        "memory_percent": 25.0,
        "memory_used_gb": 2.0,
        "memory_total_gb": 8.0,
        "disk_percent": 30.0,
        "disk_used_gb": 30.0,
        "disk_total_gb": 100.0,
        "disk_free_gb": 70.0,
        "load_1m": 1.0,
        "uptime_hours": 10.0,
        "database_status": "connected",
        "database_ok": True,
        "process_memory_mb": 100.0,
        "process_cpu_percent": 1.0,
        "hostname": "test-host",
        "platform": "test",
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def _alert(dedupe_key: str | None = None) -> dict:
    return {
        "dedupe_key": dedupe_key or f"system_resource:test-{uuid.uuid4().hex}",
        "severity": "critical",
        "title": "Test host resource alert",
        "message": "Test host resource threshold exceeded",
        "metric_key": "cpu_percent",
    }


def _patch_snapshot_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "init_db", lambda: None)
    monkeypatch.setattr(health, "_get_db_health", lambda: (True, "connected"))
    monkeypatch.setattr(health, "_build_resource_snapshot", lambda _ok, _status: _snapshot())


class _TrackedConnection:
    def __init__(self, connection, *, fail_commit: bool = False):
        self.connection = connection
        self.closed = False
        self.fail_commit = fail_commit

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("simulated commit failure")
        return self.connection.commit()

    def close(self):
        self.closed = True
        return self.connection.close()


def test_resource_read_routes_sample_without_sending_notifications(isolated_db, monkeypatch):
    _patch_snapshot_inputs(monkeypatch)
    monkeypatch.setattr(health, "_get_host_resource_alerts", lambda _snapshot: [_alert()])
    monkeypatch.setattr(
        health,
        "_dispatch_host_resource_notification",
        lambda *_args, **_kwargs: pytest.fail("read routes must not dispatch notifications"),
    )

    current = health.health_resources()
    history = health.health_resource_history(range_hours=1)

    assert current["active_alert_count"] == 1
    assert history["current"]["active_alert_count"] == 1
    assert history["range_hours"] == 1


def test_background_sampler_dispatches_after_commit_and_connection_close(isolated_db, monkeypatch):
    _patch_snapshot_inputs(monkeypatch)
    alert = _alert()
    monkeypatch.setattr(health, "_get_host_resource_alerts", lambda _snapshot: [alert])
    monkeypatch.setattr(health.alert_maintenance_service, "find_active_window_for_alert", lambda *_args, **_kwargs: None)

    original_get_connection = health.get_db_connection
    tracked_connections: list[_TrackedConnection] = []

    def tracked_get_connection():
        tracked = _TrackedConnection(original_get_connection())
        tracked_connections.append(tracked)
        return tracked

    monkeypatch.setattr(health, "get_db_connection", tracked_get_connection)
    dispatched: list[dict] = []

    def dispatch_after_commit(dispatched_alert, **kwargs):
        assert tracked_connections[-1].closed
        connection = original_get_connection()
        try:
            row = connection.execute(
                "SELECT workflow_status FROM alert_events WHERE source = ? AND dedupe_key = ?",
                (health.HOST_RESOURCE_ALERT_SOURCE, alert["dedupe_key"]),
            ).fetchone()
        finally:
            connection.close()
        assert row is not None
        assert row["workflow_status"] == "open"
        dispatched.append({"alert": dispatched_alert, **kwargs})

    monkeypatch.setattr(health, "_dispatch_host_resource_notification", dispatch_after_commit)

    result = health.record_host_resource_snapshot()

    assert result["active_alert_count"] == 1
    assert len(dispatched) == 1
    assert dispatched[0]["alert"]["dedupe_key"] == alert["dedupe_key"]
    assert dispatched[0]["status"] == "active"


def test_notification_failure_does_not_undo_committed_alert(isolated_db, monkeypatch, caplog):
    _patch_snapshot_inputs(monkeypatch)
    alert = _alert()
    monkeypatch.setattr(health, "_get_host_resource_alerts", lambda _snapshot: [alert])
    monkeypatch.setattr(health.alert_maintenance_service, "find_active_window_for_alert", lambda *_args, **_kwargs: None)
    dispatch_attempts: list[str] = []

    def failed_dispatch(dispatched_alert, **_kwargs):
        dispatch_attempts.append(dispatched_alert["dedupe_key"])
        raise RuntimeError("failed posting https://hooks.example.invalid/send?token=synthetic-canary")

    monkeypatch.setattr(health, "_dispatch_host_resource_notification", failed_dispatch)

    result = health.record_host_resource_snapshot()

    connection = get_db_connection()
    try:
        row = connection.execute(
            "SELECT workflow_status FROM alert_events WHERE source = ? AND dedupe_key = ?",
            (health.HOST_RESOURCE_ALERT_SOURCE, alert["dedupe_key"]),
        ).fetchone()
    finally:
        connection.close()

    assert result["active_alert_count"] == 1
    assert dispatch_attempts == [alert["dedupe_key"]]
    assert row is not None
    assert row["workflow_status"] == "open"
    assert "synthetic-canary" not in caplog.text


def test_failed_alert_commit_does_not_dispatch(isolated_db, monkeypatch):
    _patch_snapshot_inputs(monkeypatch)
    alert = _alert()
    monkeypatch.setattr(health, "_get_host_resource_alerts", lambda _snapshot: [alert])
    monkeypatch.setattr(health.alert_maintenance_service, "find_active_window_for_alert", lambda *_args, **_kwargs: None)

    original_get_connection = health.get_db_connection
    tracked_connections: list[_TrackedConnection] = []

    def fail_alert_commit():
        tracked = _TrackedConnection(
            original_get_connection(),
            fail_commit=len(tracked_connections) == 1,
        )
        tracked_connections.append(tracked)
        return tracked

    monkeypatch.setattr(health, "get_db_connection", fail_alert_commit)
    dispatch_attempts: list[str] = []
    monkeypatch.setattr(
        health,
        "_dispatch_host_resource_notification",
        lambda dispatched_alert, **_kwargs: dispatch_attempts.append(dispatched_alert["dedupe_key"]),
    )

    with pytest.raises(RuntimeError, match="simulated commit failure"):
        health.record_host_resource_snapshot()

    connection = original_get_connection()
    try:
        row = connection.execute(
            "SELECT 1 FROM alert_events WHERE source = ? AND dedupe_key = ?",
            (health.HOST_RESOURCE_ALERT_SOURCE, alert["dedupe_key"]),
        ).fetchone()
    finally:
        connection.close()

    assert dispatch_attempts == []
    assert row is None
    assert tracked_connections[-1].closed


def test_suppressed_alert_and_its_recovery_do_not_dispatch(isolated_db, monkeypatch):
    alert = _alert()
    monkeypatch.setattr(health, "_get_host_resource_alerts", lambda _snapshot: [alert])
    monkeypatch.setattr(
        health.alert_maintenance_service,
        "find_active_window_for_alert",
        lambda *_args, **_kwargs: {"name": "planned maintenance"},
    )
    dispatch_attempts: list[dict] = []
    monkeypatch.setattr(
        health,
        "_dispatch_host_resource_notification",
        lambda dispatched_alert, **kwargs: dispatch_attempts.append({"alert": dispatched_alert, **kwargs}),
    )

    health._sync_host_resource_alerts(_snapshot())

    connection = get_db_connection()
    try:
        row = connection.execute(
            "SELECT workflow_status, resolved_at FROM alert_events WHERE source = ? AND dedupe_key = ?",
            (health.HOST_RESOURCE_ALERT_SOURCE, alert["dedupe_key"]),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    assert row["workflow_status"] == "suppressed"
    assert row["resolved_at"] is None

    monkeypatch.setattr(health, "_get_host_resource_alerts", lambda _snapshot: [])
    health._sync_host_resource_alerts(_snapshot())

    connection = get_db_connection()
    try:
        recovered = connection.execute(
            "SELECT workflow_status, resolved_at FROM alert_events WHERE source = ? AND dedupe_key = ?",
            (health.HOST_RESOURCE_ALERT_SOURCE, alert["dedupe_key"]),
        ).fetchone()
    finally:
        connection.close()

    assert recovered["workflow_status"] == "resolved"
    assert recovered["resolved_at"] is not None
    assert dispatch_attempts == []


def test_open_alert_recovery_dispatches_after_commit(isolated_db, monkeypatch):
    alert = _alert()
    created_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).replace(microsecond=0).isoformat()
    connection = get_db_connection()
    try:
        connection.execute(
            """
            INSERT INTO alert_events (
                id, dedupe_key, source, severity, title, message, device_id, interface_name,
                created_at, resolved_at, workflow_status, note, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, 'open', '', ?)
            """,
            (
                str(uuid.uuid4()), alert["dedupe_key"], health.HOST_RESOURCE_ALERT_SOURCE,
                "critical", alert["title"], alert["message"], alert["metric_key"],
                created_at, created_at,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    monkeypatch.setattr(health, "_get_host_resource_alerts", lambda _snapshot: [])
    original_get_connection = health.get_db_connection
    tracked_connections: list[_TrackedConnection] = []

    def tracked_get_connection():
        tracked = _TrackedConnection(original_get_connection())
        tracked_connections.append(tracked)
        return tracked

    monkeypatch.setattr(health, "get_db_connection", tracked_get_connection)
    dispatches: list[dict] = []

    def verify_recovery_after_commit(dispatched_alert, **kwargs):
        assert tracked_connections[-1].closed
        connection = original_get_connection()
        try:
            row = connection.execute(
                "SELECT workflow_status, resolved_at FROM alert_events WHERE source = ? AND dedupe_key = ?",
                (health.HOST_RESOURCE_ALERT_SOURCE, alert["dedupe_key"]),
            ).fetchone()
        finally:
            connection.close()
        assert row["workflow_status"] == "resolved"
        assert row["resolved_at"] is not None
        dispatches.append({"alert": dispatched_alert, **kwargs})

    monkeypatch.setattr(health, "_dispatch_host_resource_notification", verify_recovery_after_commit)

    health._sync_host_resource_alerts(_snapshot())

    assert len(dispatches) == 1
    assert dispatches[0]["alert"]["dedupe_key"] == alert["dedupe_key"]
    assert dispatches[0]["status"] == "resolved"
    assert dispatches[0]["alert_count"] == 1


@pytest.mark.asyncio
async def test_live_request_progresses_while_resource_handler_waits(monkeypatch):
    entered = threading.Event()
    resume = threading.Event()

    def slow_snapshot(*, sync_alerts: bool = True):
        assert sync_alerts is False
        entered.set()
        if not resume.wait(timeout=5):
            raise TimeoutError("resource handler test gate was not released")
        return {"status": "healthy"}

    monkeypatch.setattr(health, "record_host_resource_snapshot", slow_snapshot)
    app = FastAPI()
    app.include_router(health.router, prefix="/api")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resource_task = asyncio.create_task(client.get("/api/health/resources"))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            live_response = await asyncio.wait_for(client.get("/api/health/live"), timeout=1)
            assert live_response.status_code == 200
            assert live_response.json() == {"status": "alive"}
        finally:
            resume.set()

        resource_response = await resource_task

    assert resource_response.status_code == 200
    assert resource_response.json() == {"status": "healthy"}
