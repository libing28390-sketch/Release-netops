from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from database import get_db_connection
from database.migrations import m0219_locator_v2_coordination as migration
from database.migrations import m0220_locator_run_deployment_scope as deployment_scope_migration
from database.migrations import m0221_locator_global_access_slots as global_slots_migration
from database.migrations import m0222_locator_run_leases as run_leases_migration
from services.ip_locator_task_service import (
    acquire_device_access_lease,
    claim_locator_task,
    complete_locator_task,
    create_locator_run,
    enqueue_locator_invalidation,
    enqueue_locator_task,
    get_locator_observation,
    get_locator_run,
    release_device_access_lease,
    upsert_locator_observation,
)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def test_m0219_creates_coordination_tables_and_is_idempotent(isolated_db):
    conn = get_db_connection()
    try:
        migration.upgrade(conn.cursor(), use_pg=True)
        migration.upgrade(conn.cursor(), use_pg=True)
        deployment_scope_migration.upgrade(conn.cursor(), use_pg=True)
        deployment_scope_migration.upgrade(conn.cursor(), use_pg=True)
        global_slots_migration.upgrade(conn.cursor(), use_pg=True)
        global_slots_migration.upgrade(conn.cursor(), use_pg=True)
        run_leases_migration.upgrade(conn.cursor(), use_pg=True)
        run_leases_migration.upgrade(conn.cursor(), use_pg=True)
        tables = {
            str(row[0])
            for row in conn.execute(
                """SELECT table_name FROM information_schema.tables
                   WHERE table_schema = current_schema()
                     AND table_name LIKE 'locator_%'"""
            ).fetchall()
        }
    finally:
        conn.close()

    assert {
        "locator_runs",
        "locator_query_tasks",
        "locator_run_tasks",
        "locator_observations",
        "locator_history",
        "locator_invalidation_outbox",
        "locator_global_access_slots",
    } <= tables
    check_conn = get_db_connection()
    try:
        deployment_column = check_conn.execute(
            """SELECT 1 FROM information_schema.columns
               WHERE table_schema = current_schema()
                 AND table_name = 'locator_runs'
                 AND column_name = 'deployment_id'"""
        ).fetchone()
    finally:
        check_conn.close()
    assert deployment_column is not None
    check_conn = get_db_connection()
    try:
        lease_columns = {
            str(row[0])
            for row in check_conn.execute(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_schema = current_schema() AND table_name = 'locator_runs'
                     AND column_name IN ('lease_owner', 'lease_token', 'lease_until')"""
            ).fetchall()
        }
    finally:
        check_conn.close()
    assert lease_columns == {"lease_owner", "lease_token", "lease_until"}


def test_m0219_deduplicates_shared_tasks_and_completes_subscribed_run(isolated_db):
    owner = _id("locator-owner")
    run = create_locator_run(
        owner_id=owner,
        target_ip="192.0.2.100",
        tenant_id="tenant-test",
        scope_hash="scope-test",
        vrf_name="default",
        deadline_seconds=120,
    )
    first = enqueue_locator_task(
        run_id=run["id"],
        operation="route",
        tenant_id="tenant-test",
        scope_hash="scope-test",
        vrf_name="default",
        target_ip="192.0.2.100",
        priority=10,
        deadline_seconds=120,
    )
    second = enqueue_locator_task(
        run_id=run["id"],
        operation="route",
        tenant_id="tenant-test",
        scope_hash="scope-test",
        vrf_name="default",
        target_ip="192.0.2.100",
        priority=10,
        deadline_seconds=120,
    )

    assert first["id"] == second["id"]
    assert second["deduplicated"] is True

    claimed = claim_locator_task(worker_id="locator-test-worker", lease_seconds=90)
    assert claimed is not None
    assert claimed["id"] == first["id"]
    finished = complete_locator_task(
        claimed["id"],
        worker_id="locator-test-worker",
        lease_token=claimed["lease_token"],
        success=True,
        result={"stage": "route", "source": "ssh_cli"},
    )
    assert finished is not None
    refreshed = get_locator_run(run["id"], owner_id=owner)
    assert refreshed is not None
    assert refreshed["status"] == "completed"


def test_m0219_device_lease_observation_generation_and_invalidation(isolated_db):
    device_id = _id("locator-device")
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address) VALUES (?, ?, ?)",
            (device_id, "locator-device", "192.0.2.201"),
        )
        conn.commit()
    finally:
        conn.close()

    lease = acquire_device_access_lease(
        device_id,
        owner_id="locator-owner",
        task_id="locator-task",
        capacity=1,
        lease_seconds=90,
    )
    assert lease is not None
    assert release_device_access_lease(
        device_id,
        owner_id="locator-owner",
        lease_token=lease["lease_token"],
    ) is True

    observed = upsert_locator_observation(
        tenant_id="tenant-test",
        scope_hash="scope-test",
        vrf_name="default",
        device_id=device_id,
        observation_kind="arp",
        target_ip="192.0.2.100",
        target_mac="001122334455",
        records={"ip": "192.0.2.100", "mac": "001122334455"},
        collected_at=datetime.now(timezone.utc),
        fresh_seconds=300,
        retain_seconds=1800,
        generation=3,
    )
    assert observed["generation"] == 3
    key = observed["observation_key"]
    stale = upsert_locator_observation(
        tenant_id="tenant-test",
        scope_hash="scope-test",
        vrf_name="default",
        device_id=device_id,
        observation_kind="arp",
        target_ip="192.0.2.100",
        target_mac="001122334455",
        records={"stale": True},
        collected_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        fresh_seconds=300,
        retain_seconds=1800,
        generation=2,
    )
    assert stale["stale_ignored"] is True
    assert get_locator_observation(key)["generation"] == 3

    event = enqueue_locator_invalidation(
        event_key=_id("event"),
        entity_type="device",
        entity_id=device_id,
        event_type="mac_changed",
        tenant_id="tenant-test",
        scope_hash="scope-test",
        generation=4,
        payload={"kind": "mac"},
    )
    assert event["status"] == "pending"
