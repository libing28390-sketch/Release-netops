"""Owner-fenced PostgreSQL leases for synchronized scheduler jobs."""

from __future__ import annotations

import asyncio
import functools
import logging
import threading
import uuid
from typing import Any

from database import get_db_connection

logger = logging.getLogger(__name__)


class SchedulerLockLease:
    """A renewable database lease which releases only its own owner token."""

    def __init__(self, lock_name: str, owner_token: str, expire_seconds: int):
        self.lock_name = lock_name
        self.owner_token = owner_token
        self.expire_seconds = max(1, int(expire_seconds))
        self._heartbeat_interval = max(0.25, min(30.0, self.expire_seconds / 3.0))
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._released = False

    def heartbeat(self) -> bool:
        with self._state_lock:
            if self._released:
                return False
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.execute(
                """
                UPDATE scheduler_locks
                   SET expires_at = clock_timestamp() + (? * INTERVAL '1 second')
                 WHERE lock_name = ?
                   AND owner_token = ?
                   AND expires_at > clock_timestamp()
                RETURNING lock_name
                """,
                (self.expire_seconds, self.lock_name, self.owner_token),
            )
            renewed = cursor.fetchone() is not None
            conn.commit()
            return renewed
        except Exception as exc:
            try:
                if conn is not None:
                    conn.rollback()
            except Exception:
                pass
            logger.warning(
                "Scheduler lease heartbeat failed for %s (%s)",
                self.lock_name,
                type(exc).__name__,
            )
            return False
        finally:
            if conn is not None:
                conn.close()

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(self._heartbeat_interval):
            if not self.heartbeat():
                if not self._heartbeat_stop.is_set():
                    logger.warning("Scheduler lease ownership lost for %s", self.lock_name)
                return

    def __enter__(self) -> "SchedulerLockLease":
        with self._state_lock:
            if self._released:
                raise RuntimeError("Cannot enter a released scheduler lease")
            if self._heartbeat_thread is None:
                self._heartbeat_thread = threading.Thread(
                    target=self._heartbeat_loop,
                    name=f"scheduler-lease-{self.lock_name[:32]}",
                    daemon=True,
                )
                self._heartbeat_thread.start()
        return self

    def release(self) -> bool:
        with self._state_lock:
            if self._released:
                return False
            self._released = True

        self._heartbeat_stop.set()
        heartbeat_thread = self._heartbeat_thread
        if heartbeat_thread is not None and heartbeat_thread is not threading.current_thread():
            heartbeat_thread.join(timeout=max(1.0, self._heartbeat_interval + 1.0))

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.execute(
                """
                DELETE FROM scheduler_locks
                 WHERE lock_name = ? AND owner_token = ?
                RETURNING lock_name
                """,
                (self.lock_name, self.owner_token),
            )
            released = cursor.fetchone() is not None
            conn.commit()
            return released
        except Exception as exc:
            try:
                if conn is not None:
                    conn.rollback()
            except Exception:
                pass
            logger.warning(
                "Scheduler lease release failed for %s (%s)",
                self.lock_name,
                type(exc).__name__,
            )
            return False
        finally:
            if conn is not None:
                conn.close()

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.release()


def acquire_scheduler_lock(
    lock_name: str,
    expire_seconds: int = 60,
) -> SchedulerLockLease | None:
    """Atomically acquire a lease, returning ``None`` when another owner holds it.

    PostgreSQL's conflict-update predicate handles concurrent claim attempts
    without raising/logging a duplicate-key error. Expired rows are cleaned
    opportunistically; the upsert remains the authoritative atomic claim.
    """
    lease_seconds = max(1, int(expire_seconds))
    owner_token = uuid.uuid4().hex
    conn = None
    try:
        conn = get_db_connection()
        conn.execute("DELETE FROM scheduler_locks WHERE expires_at <= clock_timestamp()")
        cursor = conn.execute(
            """
            INSERT INTO scheduler_locks (lock_name, owner_token, locked_at, expires_at)
            VALUES (
                ?, ?, clock_timestamp(),
                clock_timestamp() + (? * INTERVAL '1 second')
            )
            ON CONFLICT (lock_name) DO UPDATE
               SET owner_token = EXCLUDED.owner_token,
                   locked_at = EXCLUDED.locked_at,
                   expires_at = EXCLUDED.expires_at
             WHERE scheduler_locks.expires_at <= EXCLUDED.locked_at
            RETURNING owner_token
            """,
            (lock_name, owner_token, lease_seconds),
        )
        row = cursor.fetchone()
        conn.commit()
        if row is None:
            return None
        return SchedulerLockLease(lock_name, owner_token, lease_seconds)
    except Exception as exc:
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        logger.debug(
            "Scheduler lease acquire failed for %s (%s)",
            lock_name,
            type(exc).__name__,
        )
        return None
    finally:
        if conn is not None:
            conn.close()


def synchronized_scheduler_job(lock_name: str, expire_seconds: int = 55):
    """Ensure only one instance runs; renew while active and release on exit."""

    def decorator(func):
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any):
                lease = acquire_scheduler_lock(lock_name, expire_seconds)
                if lease is None:
                    logger.debug("Scheduler lock %s is already held. Skipping execution.", lock_name)
                    return None
                try:
                    with lease:
                        return await func(*args, **kwargs)
                except Exception as exc:
                    logger.error(
                        "Error executing synchronized scheduler job %s: %s",
                        lock_name,
                        type(exc).__name__,
                        exc_info=True,
                    )
                    return None

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any):
            lease = acquire_scheduler_lock(lock_name, expire_seconds)
            if lease is None:
                logger.debug("Scheduler lock %s is already held. Skipping execution.", lock_name)
                return None
            try:
                with lease:
                    return func(*args, **kwargs)
            except Exception as exc:
                logger.error(
                    "Error executing synchronized scheduler job %s: %s",
                    lock_name,
                    type(exc).__name__,
                    exc_info=True,
                )
                return None

        return sync_wrapper

    return decorator
