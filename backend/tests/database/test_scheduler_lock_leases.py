from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from core.scheduler_lock import acquire_scheduler_lock, synchronized_scheduler_job
from database import get_db_connection


def _clear_lock(lock_name: str) -> None:
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM scheduler_locks WHERE lock_name = ?", (lock_name,))
        conn.commit()
    finally:
        conn.close()


def _lock_exists(lock_name: str) -> bool:
    conn = get_db_connection()
    try:
        return conn.execute(
            "SELECT 1 FROM scheduler_locks WHERE lock_name = ?",
            (lock_name,),
        ).fetchone() is not None
    finally:
        conn.close()


def test_scheduler_lease_atomically_claims_expired_rows_and_fences_old_owner(isolated_db):
    lock_name = "test_scheduler_lease_owner_fence"
    _clear_lock(lock_name)

    first = acquire_scheduler_lock(lock_name, expire_seconds=10)
    assert first is not None
    assert acquire_scheduler_lock(lock_name, expire_seconds=10) is None

    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE scheduler_locks SET expires_at = ? WHERE lock_name = ?",
            (datetime.now(timezone.utc) - timedelta(seconds=1), lock_name),
        )
        conn.commit()
    finally:
        conn.close()

    replacement = acquire_scheduler_lock(lock_name, expire_seconds=10)
    assert replacement is not None
    assert first.release() is False
    assert replacement.release() is True
    assert _lock_exists(lock_name) is False


def test_synchronized_job_renews_long_work_and_releases_after_completion(isolated_db):
    lock_name = "test_scheduler_lease_long_job"
    _clear_lock(lock_name)
    started = threading.Event()
    finish_job = threading.Event()
    run_count = 0

    @synchronized_scheduler_job(lock_name, expire_seconds=4)
    def job() -> None:
        nonlocal run_count
        run_count += 1
        started.set()
        finish_job.wait(timeout=8)

    worker = threading.Thread(target=job)
    worker.start()
    competitor = None
    try:
        assert started.wait(timeout=2)
        job()
        assert run_count == 1

        # The original 4-second lease would expire; its heartbeat must renew it.
        time.sleep(4.2)
        conn = get_db_connection()
        try:
            expiry = conn.execute(
                "SELECT expires_at FROM scheduler_locks WHERE lock_name = ?",
                (lock_name,),
            ).fetchone()["expires_at"]
            assert expiry.astimezone(timezone.utc) > datetime.now(timezone.utc)
        finally:
            conn.close()

        competitor = acquire_scheduler_lock(lock_name, expire_seconds=4)
        assert competitor is None
    finally:
        if competitor is not None:
            competitor.release()
        finish_job.set()
        worker.join(timeout=9)
    assert not worker.is_alive()

    # A completed job releases immediately; it need not wait for expiry.
    job()
    assert run_count == 2
    assert _lock_exists(lock_name) is False


def test_scheduler_decorators_release_leases_after_sync_and_async_failure(isolated_db):
    sync_lock = "test_scheduler_lease_sync_failure"
    async_lock = "test_scheduler_lease_async_failure"
    _clear_lock(sync_lock)
    _clear_lock(async_lock)

    @synchronized_scheduler_job(sync_lock, expire_seconds=10)
    def sync_failure() -> None:
        raise RuntimeError("synthetic scheduled failure")

    @synchronized_scheduler_job(async_lock, expire_seconds=10)
    async def async_failure() -> None:
        await asyncio.sleep(0)
        raise RuntimeError("synthetic async scheduled failure")

    sync_failure()
    asyncio.run(async_failure())

    assert _lock_exists(sync_lock) is False
    assert _lock_exists(async_lock) is False


def test_slow_synchronized_job_logs_lock_work_and_cleanup_duration(monkeypatch, caplog):
    from core import scheduler_lock

    class Lease:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc_value, _traceback):
            return None

    monkeypatch.setattr(scheduler_lock, "SLOW_SYNCHRONIZED_JOB_WARNING_SECONDS", 0.0)
    monkeypatch.setattr(scheduler_lock, "acquire_scheduler_lock", lambda *_args, **_kwargs: Lease())

    @synchronized_scheduler_job("test_slow_scheduler_timing")
    def job():
        return "done"

    with caplog.at_level(logging.WARNING, logger="core.scheduler_lock"):
        assert job() == "done"

    assert "Slow synchronized scheduler job test_slow_scheduler_timing" in caplog.text
    assert "lock_wait=" in caplog.text
    assert "work=" in caplog.text
    assert "cleanup=" in caplog.text


def test_dynamic_scheduler_releases_its_owner_fenced_lease(isolated_db, monkeypatch):
    from services import scheduler_service

    lock_name = "dyn_dynamic-lease-test"
    _clear_lock(lock_name)
    completed: list[str] = []

    async def fake_job(job_id: str) -> None:
        completed.append(job_id)

    monkeypatch.setattr(scheduler_service, "run_scheduled_automation_job", fake_job)
    scheduler_service.run_scheduled_automation_job_sync_wrapper("dynamic-lease-test")
    scheduler_service.run_scheduled_automation_job_sync_wrapper("dynamic-lease-test")

    assert completed == ["dynamic-lease-test", "dynamic-lease-test"]
    assert _lock_exists(lock_name) is False


def test_async_scheduler_keeps_loop_responsive_during_slow_acquire_and_release(monkeypatch):
    from core import scheduler_lock

    acquiring = threading.Event()
    acquired = threading.Event()
    releasing = threading.Event()
    finish_release = threading.Event()
    operation_threads = []

    class Lease:
        def __enter__(self):
            return self

        def release(self):
            operation_threads.append(threading.get_ident())
            releasing.set()
            assert finish_release.wait(timeout=3)

    def acquire(*_args):
        operation_threads.append(threading.get_ident())
        acquiring.set()
        assert acquired.wait(timeout=3)
        return Lease()

    monkeypatch.setattr(scheduler_lock, "acquire_scheduler_lock", acquire)

    @synchronized_scheduler_job("test_slow_async_lock")
    async def job():
        return "completed"

    async def scenario():
        loop_thread = threading.get_ident()
        task = asyncio.create_task(job())
        try:
            assert await asyncio.to_thread(acquiring.wait, 2)
            assert not task.done()
            assert operation_threads == [operation_threads[0]]
            assert operation_threads[0] != loop_thread
            acquired.set()
            assert await asyncio.to_thread(releasing.wait, 2)
            # A lightweight coroutine can run while release is still waiting.
            await asyncio.sleep(0)
            assert not task.done()
            assert operation_threads[1] != loop_thread
        finally:
            acquired.set()
            finish_release.set()
        assert await task == "completed"

    asyncio.run(scenario())


def test_async_scheduler_releases_lease_acquired_after_repeated_cancellation(monkeypatch):
    from core import scheduler_lock

    acquiring = threading.Event()
    finish_acquire = threading.Event()
    released = []
    invoked = []

    class Lease:
        def release(self):
            released.append(True)

    def acquire(*_args):
        acquiring.set()
        assert finish_acquire.wait(timeout=3)
        return Lease()

    monkeypatch.setattr(scheduler_lock, "acquire_scheduler_lock", acquire)

    @synchronized_scheduler_job("test_cancel_acquiring")
    async def job():
        invoked.append(True)

    async def scenario():
        task = asyncio.create_task(job())
        try:
            assert await asyncio.to_thread(acquiring.wait, 2)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            finish_acquire.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3)

    asyncio.run(scenario())
    assert released == [True]
    assert invoked == []


def test_async_scheduler_finishes_release_after_repeated_cancellation(monkeypatch):
    from core import scheduler_lock

    releasing = threading.Event()
    finish_release = threading.Event()
    released = []

    class Lease:
        def __enter__(self):
            return self

        def release(self):
            releasing.set()
            assert finish_release.wait(timeout=3)
            released.append(True)

    monkeypatch.setattr(scheduler_lock, "acquire_scheduler_lock", lambda *_args: Lease())

    @synchronized_scheduler_job("test_cancel_releasing")
    async def job():
        return "completed"

    async def scenario():
        task = asyncio.create_task(job())
        try:
            assert await asyncio.to_thread(releasing.wait, 2)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            finish_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3)

    asyncio.run(scenario())
    assert released == [True]


def test_async_scheduler_releases_real_pg_lease_when_job_is_cancelled(isolated_db):
    lock_name = "test_scheduler_cancel_active_job"
    _clear_lock(lock_name)

    async def scenario():
        started = asyncio.Event()

        @synchronized_scheduler_job(lock_name, expire_seconds=10)
        async def job():
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(job())
        await asyncio.wait_for(started.wait(), timeout=3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3)

    asyncio.run(scenario())
    assert _lock_exists(lock_name) is False
