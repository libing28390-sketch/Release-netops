from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest

from database import get_db_connection
from database.migrations import m0219_locator_v2_coordination as migration
from services import ip_locator_task_service as tasks


def _device_id() -> str:
    return f"locator-test-device-{uuid.uuid4().hex[:12]}"


@pytest.fixture()
def device(isolated_db) -> str:
    device_id = _device_id()
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO devices (id, hostname, tenant_id) VALUES (?, ?, ?)", (device_id, device_id, "tenant-default"))
        conn.commit()
    finally:
        conn.close()
    return device_id


def test_m0219_is_additive_and_idempotent(isolated_db) -> None:
    conn = get_db_connection()
    try:
        migration.upgrade(conn.cursor(), use_pg=True)
        migration.upgrade(conn.cursor(), use_pg=True)
        rows = conn.execute(
            """
            SELECT table_name FROM information_schema.tables
             WHERE table_schema = current_schema()
               AND table_name IN (
                   'locator_runs', 'locator_query_tasks', 'locator_run_tasks',
                   'locator_observations', 'network_device_access_slots',
                   'locator_history', 'locator_invalidation_outbox'
               )
             ORDER BY table_name
            """
        ).fetchall()
        assert [row[0] for row in rows] == [
            "locator_history",
            "locator_invalidation_outbox",
            "locator_observations",
            "locator_query_tasks",
            "locator_run_tasks",
            "locator_runs",
            "network_device_access_slots",
        ]
    finally:
        conn.close()


def test_query_key_dedup_and_shared_completion(device: str) -> None:
    first = tasks.create_locator_run(owner_id="user-a", target_ip="192.0.2.10")
    second = tasks.create_locator_run(owner_id="user-b", target_ip="192.0.2.10")
    first_task = tasks.enqueue_locator_task(
        run_id=first["id"],
        operation="arp",
        device_id=device,
        target_ip="192.0.2.10",
    )
    second_task = tasks.enqueue_locator_task(
        run_id=second["id"],
        operation="arp",
        device_id=device,
        target_ip="192.0.2.10",
    )
    assert first_task["id"] == second_task["id"]
    assert second_task["deduplicated"] is True

    claimed = tasks.claim_locator_task(worker_id="worker-a")
    assert claimed is not None
    assert tasks.complete_locator_task(
        claimed["id"],
        worker_id="worker-a",
        lease_token=claimed["lease_token"],
        success=True,
        result={"mac": "0011.2233.4455"},
    ) is not None
    assert tasks.get_locator_run(first["id"], owner_id="user-a")["status"] == "completed"
    assert tasks.get_locator_run(second["id"], owner_id="user-b")["status"] == "completed"

    refreshed = tasks.enqueue_locator_task(
        run_id=first["id"],
        operation="arp",
        device_id=device,
        target_ip="192.0.2.10",
        force_requeue=True,
    )
    assert refreshed["id"] == first_task["id"]
    assert refreshed["status"] == "pending"


def test_late_worker_cannot_complete_reclaimed_task(device: str) -> None:
    run = tasks.create_locator_run(owner_id="user-a", target_ip="192.0.2.11")
    queued = tasks.enqueue_locator_task(
        run_id=run["id"],
        operation="route",
        device_id=device,
        target_ip="192.0.2.11",
    )
    claimed = tasks.claim_locator_task(worker_id="worker-a", lease_seconds=1)
    assert claimed and claimed["id"] == queued["id"]

    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE locator_query_tasks SET lease_until = ? WHERE id = ?",
            (datetime.now(timezone.utc) - timedelta(seconds=1), queued["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    replacement = tasks.claim_locator_task(worker_id="worker-b")
    assert replacement and replacement["id"] == queued["id"]
    assert tasks.complete_locator_task(
        queued["id"],
        worker_id="worker-a",
        lease_token=claimed["lease_token"],
        success=True,
        result={"late": True},
    ) is None
    assert tasks.complete_locator_task(
        replacement["id"],
        worker_id="worker-b",
        lease_token=replacement["lease_token"],
        success=True,
        result={"current": True},
    ) is not None


def test_cancel_detaches_one_subscriber_without_cancelling_shared_task(device: str) -> None:
    first = tasks.create_locator_run(owner_id="user-a", target_ip="192.0.2.12")
    second = tasks.create_locator_run(owner_id="user-b", target_ip="192.0.2.12")
    kwargs = {
        "operation": "mac",
        "device_id": device,
        "target_ip": "192.0.2.12",
        "target_mac": "0011.2233.4455",
    }
    first_task = tasks.enqueue_locator_task(run_id=first["id"], **kwargs)
    second_task = tasks.enqueue_locator_task(run_id=second["id"], **kwargs)
    assert first_task["id"] == second_task["id"]

    cancelled = tasks.cancel_locator_run(first["id"], owner_id="user-a")
    assert cancelled and cancelled["status"] == "cancelled"
    conn = get_db_connection()
    try:
        state = conn.execute("SELECT status FROM locator_query_tasks WHERE id = ?", (first_task["id"],)).fetchone()[0]
        assert state == "pending"
    finally:
        conn.close()


def test_observation_generation_ignores_late_fact(device: str) -> None:
    collected = datetime.now(timezone.utc).replace(microsecond=0)
    current = tasks.upsert_locator_observation(
        device_id=device,
        observation_kind="arp",
        target_ip="192.0.2.13",
        generation=2,
        collected_at=collected,
        records={"mac": "0011.2233.4455"},
    )
    stale = tasks.upsert_locator_observation(
        device_id=device,
        observation_kind="arp",
        target_ip="192.0.2.13",
        generation=1,
        collected_at=collected + timedelta(seconds=1),
        records={"mac": "0066.7788.99aa"},
    )
    assert current["generation"] == 2
    assert stale["stale_ignored"] is True
    assert stale["records"] == {"mac": "0011.2233.4455"}
