from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from database import get_db_connection
from services import monitoring_notification_outbox_service as outbox
from services import scheduler_service


def _get_delivery(delivery_key: str) -> dict | None:
    connection = get_db_connection()
    try:
        row = connection.execute(
            "SELECT * FROM alert_delivery_outbox WHERE delivery_key = ?",
            (delivery_key,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def _insert_job(job_id: str) -> None:
    now = datetime.now().isoformat()
    connection = get_db_connection()
    try:
        connection.execute(
            """
            INSERT INTO scheduled_jobs (
                id, name, job_type, action_type, created_at, updated_at,
                tenant_id, enabled, last_run_status
            ) VALUES (?, ?, 'cron', 'command', ?, ?, 'tenant-acme', 1, 'pending')
            """,
            (job_id, f"job {job_id}", now, now),
        )
        connection.commit()
    finally:
        connection.close()


def _get_job_status(job_id: str) -> str:
    connection = get_db_connection()
    try:
        row = connection.execute(
            "SELECT last_run_status FROM scheduled_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        return str(row["last_run_status"])
    finally:
        connection.close()


def test_scheduled_job_failure_is_enqueued_once_for_owning_tenant(isolated_db, monkeypatch):
    from services import notification_service

    monkeypatch.setattr(
        notification_service,
        "dispatch_to_all_users",
        lambda *_args, **_kwargs: pytest.fail("scheduled failure must not dispatch synchronously"),
    )
    job = {"id": "job-7", "name": "nightly audit", "tenant_id": "tenant-acme"}
    details = ["device-1 execution failed"]

    first_key = asyncio.run(scheduler_service.notify_job_failure(job, details, run_id="execution-42"))
    second_key = asyncio.run(scheduler_service.notify_job_failure(job, details, run_id="execution-42"))

    delivery = _get_delivery(first_key)
    assert first_key == second_key == "scheduled-job:job-7:run:execution-42:workspace:active"
    assert delivery is not None
    assert delivery["status"] == "pending"
    assert delivery["channel"] == "workspace"
    assert delivery["tenant_id"] == "tenant-acme"
    assert delivery["event_kind"] == "active"
    assert delivery["payload"]["tenant_id"] == "tenant-acme"
    assert delivery["payload"]["status"] == "active"
    assert "device-1 execution failed" in delivery["payload"]["message"]

    connection = get_db_connection()
    try:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM alert_delivery_outbox WHERE delivery_key = ?",
            (first_key,),
        ).fetchone()["count"]
    finally:
        connection.close()
    assert count == 1


def test_scheduled_job_failure_outbox_write_failure_rolls_back(isolated_db, monkeypatch):
    job = {"id": "job-8", "name": "hourly audit", "tenant_id": "tenant-acme"}
    delivery_key = "scheduled-job:job-8:run:execution-43:workspace:active"
    original_enqueue = outbox.enqueue_alert_delivery

    def insert_then_fail(**kwargs):
        original_enqueue(**kwargs)
        raise RuntimeError("simulated enqueue failure")

    monkeypatch.setattr(outbox, "enqueue_alert_delivery", insert_then_fail)

    with pytest.raises(RuntimeError, match="simulated enqueue failure"):
        asyncio.run(scheduler_service.notify_job_failure(job, ["failure"], run_id="execution-43"))

    assert _get_delivery(delivery_key) is None


def test_scheduled_job_failure_uses_caller_transaction(isolated_db):
    job = {"id": "job-9", "name": "weekly audit", "tenant_id": "tenant-acme"}
    delivery_key = "scheduled-job:job-9:run:execution-44:workspace:active"
    _insert_job(job["id"])
    connection = get_db_connection()
    try:
        connection.execute(
            "UPDATE scheduled_jobs SET last_run_status = 'failed' WHERE id = ?",
            (job["id"],),
        )
        asyncio.run(
            scheduler_service.notify_job_failure(
                job,
                ["failure"],
                run_id="execution-44",
                connection=connection,
            )
        )
        assert _get_delivery(delivery_key) is None
        assert _get_job_status(job["id"]) == "pending"
        connection.commit()
    finally:
        connection.close()

    delivery = _get_delivery(delivery_key)
    assert delivery is not None
    assert delivery["tenant_id"] == "tenant-acme"
    assert _get_job_status(job["id"]) == "failed"


def test_scheduled_job_state_and_outbox_both_roll_back_on_enqueue_failure(isolated_db, monkeypatch):
    job = {"id": "job-10", "name": "daily audit", "tenant_id": "tenant-acme"}
    delivery_key = "scheduled-job:job-10:run:execution-45:workspace:active"
    _insert_job(job["id"])
    original_enqueue = outbox.enqueue_alert_delivery

    def insert_then_fail(**kwargs):
        original_enqueue(**kwargs)
        raise RuntimeError("simulated enqueue failure")

    monkeypatch.setattr(outbox, "enqueue_alert_delivery", insert_then_fail)
    connection = get_db_connection()
    try:
        connection.execute(
            "UPDATE scheduled_jobs SET last_run_status = 'failed' WHERE id = ?",
            (job["id"],),
        )
        with pytest.raises(RuntimeError, match="simulated enqueue failure"):
            asyncio.run(
                scheduler_service.notify_job_failure(
                    job,
                    ["failure"],
                    run_id="execution-45",
                    connection=connection,
                )
            )
        connection.rollback()
    finally:
        connection.close()

    assert _get_job_status(job["id"]) == "pending"
    assert _get_delivery(delivery_key) is None
