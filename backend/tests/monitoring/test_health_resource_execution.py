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


def test_resource_read_routes_reuse_stored_sample_without_sampling_or_writing(isolated_db, monkeypatch):
    _patch_snapshot_inputs(monkeypatch)
    monkeypatch.setattr(health, "_get_host_resource_alerts", lambda _snapshot: [_alert()])
    monkeypatch.setattr(
        health.monitoring_notification_outbox_service,
        "enqueue_alert_delivery",
        lambda **_kwargs: pytest.fail("read routes must not enqueue notifications"),
    )
    seeded = health.record_host_resource_snapshot(sync_alerts=False)
    monkeypatch.setattr(
        health,
        "record_host_resource_snapshot",
        lambda **_kwargs: pytest.fail("read routes must reuse the scheduled snapshot"),
    )

    connection = get_db_connection()
    try:
        before_count = connection.execute("SELECT COUNT(*) AS count FROM host_resource_samples").fetchone()["count"]
    finally:
        connection.close()

    current = health.health_resources()
    history = health.health_resource_history(range_hours=1)

    connection = get_db_connection()
    try:
        after_count = connection.execute("SELECT COUNT(*) AS count FROM host_resource_samples").fetchone()["count"]
    finally:
        connection.close()

    assert current["active_alert_count"] == 1
    assert history["current"]["active_alert_count"] == 1
    assert history["range_hours"] == 1
    assert current["updated_at"] == seeded["updated_at"]
    assert history["sample_count"] == 1
    assert after_count == before_count == 1


def test_resource_read_routes_return_empty_state_before_first_scheduled_sample(isolated_db, monkeypatch):
    monkeypatch.setattr(
        health,
        "record_host_resource_snapshot",
        lambda **_kwargs: pytest.fail("read routes must not sample the host"),
    )

    current = health.health_resources()
    history = health.health_resource_history(range_hours=1)

    assert current["status"] == "degraded"
    assert current["metrics_available"] is False
    assert current["database_status"] == "not sampled yet"
    assert current["database_ok"] is True
    assert current["active_alerts"] == []
    assert history["current"]["updated_at"] == ""
    assert history["series"] == []
    assert history["sample_count"] == 0


def test_background_sampler_commits_alert_and_outbox_together(isolated_db, monkeypatch):
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
    result = health.record_host_resource_snapshot()

    connection = original_get_connection()
    try:
        alert_row = connection.execute(
            "SELECT id, workflow_status FROM alert_events WHERE source = ? AND dedupe_key = ?",
            (health.HOST_RESOURCE_ALERT_SOURCE, alert["dedupe_key"]),
        ).fetchone()
        delivery_rows = connection.execute(
            "SELECT delivery_key, tenant_id, event_kind, payload FROM alert_delivery_outbox WHERE alert_id = ?",
            (alert_row["id"],),
        ).fetchall()
    finally:
        connection.close()

    assert result["active_alert_count"] == 1
    assert tracked_connections[-1].closed
    assert alert_row["workflow_status"] == "open"
    assert len(delivery_rows) == 1
    delivery = dict(delivery_rows[0])
    assert delivery["delivery_key"] == f"host-resource:{alert_row['id']}:workspace:active"
    assert delivery["tenant_id"] == "tenant-default"
    assert delivery["event_kind"] == "active"
    assert delivery["payload"]["status"] == "active"
    assert delivery["payload"]["tenant_id"] == "tenant-default"


def test_outbox_enqueue_failure_rolls_back_alert_then_reconciliation_retries(isolated_db, monkeypatch):
    _patch_snapshot_inputs(monkeypatch)
    alert = _alert()
    monkeypatch.setattr(health, "_get_host_resource_alerts", lambda _snapshot: [alert])
    monkeypatch.setattr(health.alert_maintenance_service, "find_active_window_for_alert", lambda *_args, **_kwargs: None)
    original_enqueue = health.monitoring_notification_outbox_service.enqueue_alert_delivery

    def fail_after_enqueue(**kwargs):
        original_enqueue(**kwargs)
        raise RuntimeError("simulated outbox failure")

    monkeypatch.setattr(health.monitoring_notification_outbox_service, "enqueue_alert_delivery", fail_after_enqueue)

    with pytest.raises(RuntimeError, match="simulated outbox failure"):
        health.record_host_resource_snapshot()

    connection = get_db_connection()
    try:
        alert_row = connection.execute(
            "SELECT 1 FROM alert_events WHERE source = ? AND dedupe_key = ?",
            (health.HOST_RESOURCE_ALERT_SOURCE, alert["dedupe_key"]),
        ).fetchone()
        delivery_count = connection.execute(
            "SELECT COUNT(*) AS count FROM alert_delivery_outbox WHERE delivery_key LIKE 'host-resource:%:workspace:active'"
        ).fetchone()["count"]
    finally:
        connection.close()

    assert alert_row is None
    assert delivery_count == 0

    monkeypatch.setattr(health.monitoring_notification_outbox_service, "enqueue_alert_delivery", original_enqueue)
    health._sync_host_resource_alerts(_snapshot())

    connection = get_db_connection()
    try:
        alert_row = connection.execute(
            "SELECT id, workflow_status FROM alert_events WHERE source = ? AND dedupe_key = ?",
            (health.HOST_RESOURCE_ALERT_SOURCE, alert["dedupe_key"]),
        ).fetchone()
        delivery = connection.execute(
            "SELECT delivery_key, alert_id, event_kind FROM alert_delivery_outbox WHERE alert_id = ?",
            (alert_row["id"],),
        ).fetchone()
    finally:
        connection.close()

    assert alert_row["workflow_status"] == "open"
    assert delivery["delivery_key"] == f"host-resource:{alert_row['id']}:workspace:active"
    assert delivery["alert_id"] == alert_row["id"]
    assert delivery["event_kind"] == "active"


def test_failed_alert_outbox_commit_rolls_back_alert_and_delivery(isolated_db, monkeypatch):
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
    with pytest.raises(RuntimeError, match="simulated commit failure"):
        health.record_host_resource_snapshot()

    connection = original_get_connection()
    try:
        alert_row = connection.execute(
            "SELECT 1 FROM alert_events WHERE source = ? AND dedupe_key = ?",
            (health.HOST_RESOURCE_ALERT_SOURCE, alert["dedupe_key"]),
        ).fetchone()
        delivery_count = connection.execute(
            "SELECT COUNT(*) AS count FROM alert_delivery_outbox"
        ).fetchone()["count"]
    finally:
        connection.close()

    assert alert_row is None
    assert delivery_count == 0
    assert tracked_connections[-1].closed


def test_suppressed_alert_and_its_recovery_do_not_enqueue(isolated_db, monkeypatch):
    alert = _alert()
    monkeypatch.setattr(health, "_get_host_resource_alerts", lambda _snapshot: [alert])
    monkeypatch.setattr(
        health.alert_maintenance_service,
        "find_active_window_for_alert",
        lambda *_args, **_kwargs: {"name": "planned maintenance"},
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
    connection = get_db_connection()
    try:
        assert connection.execute("SELECT COUNT(*) AS count FROM alert_delivery_outbox").fetchone()["count"] == 0
    finally:
        connection.close()


def test_open_alert_recovery_enqueues_resolved_event_with_same_lifecycle_id(isolated_db, monkeypatch):
    alert = _alert()
    alert_id = str(uuid.uuid4())
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
                alert_id, alert["dedupe_key"], health.HOST_RESOURCE_ALERT_SOURCE,
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
    health._sync_host_resource_alerts(_snapshot())

    connection = original_get_connection()
    try:
        row = connection.execute(
            "SELECT workflow_status, resolved_at FROM alert_events WHERE source = ? AND dedupe_key = ?",
            (health.HOST_RESOURCE_ALERT_SOURCE, alert["dedupe_key"]),
        ).fetchone()
        delivery = connection.execute(
            "SELECT delivery_key, alert_id, tenant_id, event_kind, payload FROM alert_delivery_outbox WHERE alert_id = ?",
            (alert_id,),
        ).fetchone()
    finally:
        connection.close()

    assert tracked_connections[-1].closed
    assert row["workflow_status"] == "resolved"
    assert row["resolved_at"] is not None
    assert delivery["delivery_key"] == f"host-resource:{alert_id}:workspace:resolved"
    assert delivery["alert_id"] == alert_id
    assert delivery["tenant_id"] == "tenant-default"
    assert delivery["event_kind"] == "resolved"
    assert delivery["payload"]["status"] == "resolved"
    assert delivery["payload"]["alert_count"] == 1


def test_live_request_progresses_while_resource_handler_waits(monkeypatch):
    entered = threading.Event()
    resume = threading.Event()

    def slow_snapshot(conn=None):
        assert conn is None
        entered.set()
        if not resume.wait(timeout=5):
            raise TimeoutError("resource handler test gate was not released")
        return {"status": "healthy"}

    monkeypatch.setattr(health, "_load_latest_host_resource_snapshot", slow_snapshot)
    app = FastAPI()
    app.include_router(health.router, prefix="/api")

    async def scenario():
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

    asyncio.run(scenario())
