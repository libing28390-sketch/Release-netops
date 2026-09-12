from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid

import pytest

from database import get_db_connection
import database.core as database_core
from database.migrations import m0224_network_global_ssh_slots as migration
from services.network_access_lease_service import (
    NETWORK_SSH_PURPOSE,
    NetworkAccessLeaseError,
    acquire_network_ssh_lease,
)


def _device_id() -> str:
    return f"network-ssh-test-{uuid.uuid4().hex[:12]}"


def _insert_device(device_id: str) -> None:
    connection = get_db_connection()
    try:
        connection.execute(
            "INSERT INTO devices (id, hostname, tenant_id) VALUES (?, ?, ?)",
            (device_id, device_id, "tenant-default"),
        )
        connection.commit()
    finally:
        connection.close()


def _read_slot_expirations(lease) -> tuple[object, object | None]:
    connection = get_db_connection()
    try:
        global_expiration = connection.execute(
            """SELECT lease_until FROM network_global_access_slots
               WHERE purpose = ? AND slot_id = ?""",
            (NETWORK_SSH_PURPOSE, lease.global_slot_id),
        ).fetchone()[0]
        device_expiration = None
        if lease.device_id is not None and lease.device_slot_id is not None:
            device_expiration = connection.execute(
                """SELECT lease_until FROM network_device_access_slots
                   WHERE canonical_device_id = ? AND purpose = ? AND slot_id = ?""",
                (lease.device_id, NETWORK_SSH_PURPOSE, lease.device_slot_id),
            ).fetchone()[0]
        return global_expiration, device_expiration
    finally:
        connection.close()


def test_m0224_creates_global_slots_idempotently_on_postgresql(isolated_db):
    connection = get_db_connection()
    try:
        migration.upgrade(connection.cursor(), use_pg=True)
        migration.upgrade(connection.cursor(), use_pg=True)
        table = connection.execute(
            """SELECT 1 FROM information_schema.tables
               WHERE table_schema = current_schema()
                 AND table_name = 'network_global_access_slots'"""
        ).fetchone()
        index = connection.execute(
            """SELECT indexdef FROM pg_indexes
               WHERE schemaname = current_schema()
                 AND indexname = 'ix_network_global_access_lease'"""
        ).fetchone()
        assert table is not None
        assert index is not None
        assert "network_global_access_slots" in index[0]
    finally:
        connection.close()


def test_competing_leases_serialize_one_managed_device(isolated_db):
    device_id = _device_id()
    _insert_device(device_id)
    first = acquire_network_ssh_lease(
        device_id=device_id,
        global_capacity=2,
        device_capacity=1,
        wait_timeout=0.1,
        lease_seconds=10,
        heartbeat_seconds=8,
    )
    try:
        with pytest.raises(NetworkAccessLeaseError, match="concurrency limit"):
            acquire_network_ssh_lease(
                device_id=device_id,
                global_capacity=2,
                device_capacity=1,
                wait_timeout=0.05,
                lease_seconds=10,
                heartbeat_seconds=8,
            )
    finally:
        assert first.release()

    second = acquire_network_ssh_lease(
        device_id=device_id,
        global_capacity=2,
        device_capacity=1,
        wait_timeout=0.1,
        lease_seconds=10,
        heartbeat_seconds=8,
    )
    assert second.release()


def test_global_capacity_is_shared_between_unmanaged_targets(isolated_db):
    first = acquire_network_ssh_lease(
        global_capacity=1,
        wait_timeout=0.1,
        lease_seconds=10,
        heartbeat_seconds=8,
    )
    try:
        with pytest.raises(NetworkAccessLeaseError, match="concurrency limit"):
            acquire_network_ssh_lease(
                global_capacity=1,
                wait_timeout=0.05,
                lease_seconds=10,
                heartbeat_seconds=8,
            )
    finally:
        assert first.release()


def test_heartbeat_renews_global_and_device_rows(isolated_db):
    device_id = _device_id()
    _insert_device(device_id)
    lease = acquire_network_ssh_lease(
        device_id=device_id,
        global_capacity=1,
        device_capacity=1,
        wait_timeout=0.1,
        lease_seconds=3,
        heartbeat_seconds=0.1,
    )
    try:
        before_global, before_device = _read_slot_expirations(lease)
        time.sleep(0.3)
        after_global, after_device = _read_slot_expirations(lease)
        assert after_global > before_global
        assert after_device > before_device
        assert lease.is_valid
    finally:
        assert lease.release()


def test_stale_token_cannot_renew_or_release_reclaimed_slots(isolated_db):
    device_id = _device_id()
    _insert_device(device_id)
    lease = acquire_network_ssh_lease(
        device_id=device_id,
        global_capacity=1,
        device_capacity=1,
        wait_timeout=0.1,
        lease_seconds=30,
        heartbeat_seconds=8,
    )
    replacement_token = uuid.uuid4().hex
    connection = get_db_connection()
    try:
        connection.execute(
            """UPDATE network_global_access_slots
               SET lease_owner = ?, lease_token = ?
               WHERE purpose = ? AND slot_id = ?""",
            ("replacement-worker", replacement_token, NETWORK_SSH_PURPOSE, lease.global_slot_id),
        )
        connection.execute(
            """UPDATE network_device_access_slots
               SET lease_owner = ?, lease_token = ?
               WHERE canonical_device_id = ? AND purpose = ? AND slot_id = ?""",
            (
                "replacement-worker",
                replacement_token,
                device_id,
                NETWORK_SSH_PURPOSE,
                lease.device_slot_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    assert lease.renew() is False
    assert lease.release() is False
    connection = get_db_connection()
    try:
        global_row = connection.execute(
            """SELECT lease_owner, lease_token FROM network_global_access_slots
               WHERE purpose = ? AND slot_id = ?""",
            (NETWORK_SSH_PURPOSE, lease.global_slot_id),
        ).fetchone()
        device_row = connection.execute(
            """SELECT lease_owner, lease_token FROM network_device_access_slots
               WHERE canonical_device_id = ? AND purpose = ? AND slot_id = ?""",
            (device_id, NETWORK_SSH_PURPOSE, lease.device_slot_id),
        ).fetchone()
    finally:
        connection.close()

    assert tuple(global_row) == ("replacement-worker", replacement_token)
    assert tuple(device_row) == ("replacement-worker", replacement_token)


def test_shared_device_lease_serializes_a_separate_worker_process(isolated_db):
    device_id = _device_id()
    _insert_device(device_id)
    first = acquire_network_ssh_lease(
        device_id=device_id,
        global_capacity=2,
        device_capacity=1,
        wait_timeout=0.2,
        lease_seconds=30,
        heartbeat_seconds=8,
    )
    child_code = (
        "import json,sys,time; "
        "from services.network_access_lease_service import acquire_network_ssh_lease; "
        "print('ready', flush=True); start=time.monotonic(); "
        "lease=acquire_network_ssh_lease(device_id=sys.argv[1], global_capacity=2, "
        "device_capacity=1, wait_timeout=5, lease_seconds=30, heartbeat_seconds=8); "
        "waited=time.monotonic()-start; print(json.dumps({'waited':waited}), flush=True); "
        "time.sleep(0.05); lease.release()"
    )
    child_env = os.environ.copy()
    child_env["DATABASE_URL"] = database_core._DATABASE_URL
    backend_path = os.path.join(os.getcwd(), "backend")
    child_env["PYTHONPATH"] = os.pathsep.join(
        filter(None, (backend_path, child_env.get("PYTHONPATH", "")))
    )
    child = subprocess.Popen(
        [sys.executable, "-c", child_code, device_id],
        cwd=os.getcwd(),
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready"
        time.sleep(0.25)
        assert child.poll() is None
        assert first.release()

        result_line = child.stdout.readline()
        assert result_line
        waited = float(json.loads(result_line)["waited"])
        assert waited >= 0.2
        assert child.wait(timeout=10) == 0
        stderr = child.stderr.read() if child.stderr else ""
        assert not stderr, stderr
    finally:
        first.release()
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
