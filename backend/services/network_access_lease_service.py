"""PostgreSQL-backed leases for shared managed-device SSH concurrency."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import threading
import time
import uuid
from typing import Any

from core.config import settings
from database import _USE_PG, get_db_connection


logger = logging.getLogger(__name__)

NETWORK_SSH_PURPOSE = "network_ssh"
DEFAULT_LEASE_SECONDS = 90.0
DEFAULT_HEARTBEAT_SECONDS = 20.0
_RETRY_INTERVAL_SECONDS = 0.05


class NetworkAccessLeaseError(TimeoutError):
    """Raised when shared SSH capacity cannot be acquired safely."""


@dataclass(frozen=True)
class _LeaseClaim:
    owner_id: str
    lease_token: str
    global_slot_id: int
    device_id: str | None
    device_slot_id: int | None


def _positive_capacity(value: Any, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _claim_slots_once(
    *,
    owner_id: str,
    lease_token: str,
    device_id: str | None,
    global_capacity: int,
    device_capacity: int,
    lease_seconds: float,
) -> _LeaseClaim | None:
    """Claim the global and optional device rows in one short transaction."""
    if not _USE_PG:
        raise RuntimeError("shared SSH leases require PostgreSQL")

    connection = get_db_connection()
    try:
        connection.execute(
            """
            INSERT INTO network_global_access_slots
                (purpose, slot_id, lease_owner, lease_token, lease_until, updated_at)
            SELECT ?, slot_id, '', '', NULL, clock_timestamp()
              FROM generate_series(0, ? - 1) AS slots(slot_id)
            ON CONFLICT (purpose, slot_id) DO NOTHING
            """,
            (NETWORK_SSH_PURPOSE, global_capacity),
        )

        if device_id:
            connection.execute(
                """
                INSERT INTO network_device_access_slots
                    (canonical_device_id, purpose, slot_id, lease_owner,
                     lease_token, task_id, lease_until, connection_state,
                     last_acquired_at, updated_at)
                SELECT ?, ?, slot_id, '', '', NULL, NULL, 'idle', NULL, clock_timestamp()
                  FROM generate_series(0, ? - 1) AS slots(slot_id)
                ON CONFLICT (canonical_device_id, purpose, slot_id) DO NOTHING
                """,
                (device_id, NETWORK_SSH_PURPOSE, device_capacity),
            )

        global_row = connection.execute(
            """
            SELECT slot_id FROM network_global_access_slots
             WHERE purpose = ? AND slot_id < ?
               AND (lease_until IS NULL OR lease_until <= clock_timestamp())
             ORDER BY slot_id
             LIMIT 1
             FOR UPDATE SKIP LOCKED
            """,
            (NETWORK_SSH_PURPOSE, global_capacity),
        ).fetchone()
        if global_row is None:
            connection.commit()
            return None

        device_slot_id: int | None = None
        if device_id:
            device_row = connection.execute(
                """
                SELECT slot_id FROM network_device_access_slots
                 WHERE canonical_device_id = ? AND purpose = ?
                   AND slot_id < ? AND connection_state <> 'draining'
                   AND (lease_until IS NULL OR lease_until <= clock_timestamp())
                 ORDER BY slot_id
                 LIMIT 1
                 FOR UPDATE SKIP LOCKED
                """,
                (device_id, NETWORK_SSH_PURPOSE, device_capacity),
            ).fetchone()
            if device_row is None:
                # The global row is only locked, not changed; committing here
                # releases it and keeps the seed rows available for retries.
                connection.commit()
                return None
            device_slot_id = int(device_row[0])

        global_slot_id = int(global_row[0])
        global_update = connection.execute(
            """
            UPDATE network_global_access_slots
               SET lease_owner = ?, lease_token = ?,
                   lease_until = clock_timestamp() + (? * INTERVAL '1 second'),
                   updated_at = clock_timestamp()
             WHERE purpose = ? AND slot_id = ?
            """,
            (owner_id, lease_token, lease_seconds, NETWORK_SSH_PURPOSE, global_slot_id),
        )
        if global_update.rowcount != 1:
            raise RuntimeError("global SSH slot changed while locked")

        if device_id and device_slot_id is not None:
            device_update = connection.execute(
                """
                UPDATE network_device_access_slots
                   SET lease_owner = ?, lease_token = ?, task_id = NULL,
                       lease_until = clock_timestamp() + (? * INTERVAL '1 second'),
                       connection_state = 'leased', last_acquired_at = clock_timestamp(),
                       updated_at = clock_timestamp()
                 WHERE canonical_device_id = ? AND purpose = ? AND slot_id = ?
                """,
                (
                    owner_id,
                    lease_token,
                    lease_seconds,
                    device_id,
                    NETWORK_SSH_PURPOSE,
                    device_slot_id,
                ),
            )
            if device_update.rowcount != 1:
                raise RuntimeError("device SSH slot changed while locked")

        connection.commit()
        return _LeaseClaim(
            owner_id=owner_id,
            lease_token=lease_token,
            global_slot_id=global_slot_id,
            device_id=device_id,
            device_slot_id=device_slot_id,
        )
    except Exception:
        try:
            connection.rollback()
        except Exception:
            pass
        raise
    finally:
        connection.close()


def _renew_claim(claim: _LeaseClaim, lease_seconds: float) -> bool:
    if not _USE_PG:
        raise RuntimeError("shared SSH leases require PostgreSQL")
    connection = get_db_connection()
    try:
        global_update = connection.execute(
            """
            UPDATE network_global_access_slots
               SET lease_until = clock_timestamp() + (? * INTERVAL '1 second'),
                   updated_at = clock_timestamp()
             WHERE purpose = ? AND slot_id = ?
               AND lease_owner = ? AND lease_token = ?
            """,
            (
                lease_seconds,
                NETWORK_SSH_PURPOSE,
                claim.global_slot_id,
                claim.owner_id,
                claim.lease_token,
            ),
        )
        if global_update.rowcount != 1:
            connection.rollback()
            return False

        if claim.device_id and claim.device_slot_id is not None:
            device_update = connection.execute(
                """
                UPDATE network_device_access_slots
                   SET lease_until = clock_timestamp() + (? * INTERVAL '1 second'),
                       updated_at = clock_timestamp()
                 WHERE canonical_device_id = ? AND purpose = ? AND slot_id = ?
                   AND lease_owner = ? AND lease_token = ?
                   AND connection_state = 'leased'
                """,
                (
                    lease_seconds,
                    claim.device_id,
                    NETWORK_SSH_PURPOSE,
                    claim.device_slot_id,
                    claim.owner_id,
                    claim.lease_token,
                ),
            )
            if device_update.rowcount != 1:
                connection.rollback()
                return False

        connection.commit()
        return True
    except Exception:
        try:
            connection.rollback()
        except Exception:
            pass
        raise
    finally:
        connection.close()


def _release_claim(claim: _LeaseClaim) -> bool:
    if not _USE_PG:
        raise RuntimeError("shared SSH leases require PostgreSQL")
    connection = get_db_connection()
    try:
        global_update = connection.execute(
            """
            UPDATE network_global_access_slots
               SET lease_owner = '', lease_token = '', lease_until = NULL,
                   updated_at = clock_timestamp()
             WHERE purpose = ? AND slot_id = ?
               AND lease_owner = ? AND lease_token = ?
            """,
            (
                NETWORK_SSH_PURPOSE,
                claim.global_slot_id,
                claim.owner_id,
                claim.lease_token,
            ),
        )
        if global_update.rowcount != 1:
            connection.rollback()
            return False

        if claim.device_id and claim.device_slot_id is not None:
            device_update = connection.execute(
                """
                UPDATE network_device_access_slots
                   SET lease_owner = '', lease_token = '', task_id = NULL,
                       lease_until = NULL, connection_state = 'idle',
                       updated_at = clock_timestamp()
                 WHERE canonical_device_id = ? AND purpose = ? AND slot_id = ?
                   AND lease_owner = ? AND lease_token = ?
                """,
                (
                    claim.device_id,
                    NETWORK_SSH_PURPOSE,
                    claim.device_slot_id,
                    claim.owner_id,
                    claim.lease_token,
                ),
            )
            if device_update.rowcount != 1:
                connection.rollback()
                return False

        connection.commit()
        return True
    except Exception:
        try:
            connection.rollback()
        except Exception:
            pass
        raise
    finally:
        connection.close()


class NetworkAccessLease:
    """A cross-thread-safe claimed SSH lease with a renewable expiration."""

    def __init__(self, claim: _LeaseClaim, *, lease_seconds: float, heartbeat_seconds: float) -> None:
        self.owner_id = claim.owner_id
        self.lease_token = claim.lease_token
        self.global_slot_id = claim.global_slot_id
        self.device_id = claim.device_id
        self.device_slot_id = claim.device_slot_id
        self._claim = claim
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._state_lock = threading.Lock()
        self._release_lock = threading.Lock()
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._released = False
        self._release_succeeded: bool | None = None
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="network-ssh-lease-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    @property
    def is_valid(self) -> bool:
        return not self._lost.is_set() and not self._released

    def __enter__(self) -> "NetworkAccessLease":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # noqa: ANN001
        self.release()

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self._heartbeat_seconds):
            if not self.renew():
                return

    def renew(self) -> bool:
        """Extend both rows, fenced by this handle's owner and token."""
        with self._state_lock:
            if self._released or self._lost.is_set():
                return False
            try:
                renewed = _renew_claim(self._claim, self._lease_seconds)
            except Exception:
                self._lost.set()
                self._stop.set()
                logger.warning("Shared SSH lease renewal failed; the lease is no longer trusted")
                return False
            if not renewed:
                self._lost.set()
                self._stop.set()
            return renewed

    def release(self) -> bool:
        """Stop heartbeats and release only rows still bearing this token."""
        with self._release_lock:
            if self._released:
                return bool(self._release_succeeded)
            self._stop.set()
            if threading.current_thread() is not self._heartbeat_thread:
                self._heartbeat_thread.join()
            with self._state_lock:
                self._released = True
                try:
                    self._release_succeeded = _release_claim(self._claim)
                except Exception:
                    self._release_succeeded = False
                    self._lost.set()
                    logger.warning("Shared SSH lease release failed; the lease will expire")
                return bool(self._release_succeeded)


def acquire_network_ssh_lease(
    *,
    device_id: str | None = None,
    global_capacity: int | None = None,
    device_capacity: int | None = None,
    wait_timeout: float | None = None,
    lease_seconds: float = DEFAULT_LEASE_SECONDS,
    heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
) -> NetworkAccessLease:
    """Atomically acquire shared global and optional managed-device capacity.

    Database errors fail closed.  Transactions cover only slot seeding and
    claim/renew/release statements; no transaction remains open while callers
    perform network I/O.
    """
    resolved_global_capacity = _positive_capacity(
        global_capacity if global_capacity is not None else getattr(settings, "NETWORK_SSH_GLOBAL_CONCURRENCY", 20),
        20,
    )
    resolved_device_capacity = _positive_capacity(
        device_capacity if device_capacity is not None else getattr(settings, "NETWORK_SSH_PER_DEVICE_CONCURRENCY", 1),
        1,
    )
    resolved_wait_timeout = max(
        0.0,
        float(
            wait_timeout if wait_timeout is not None
            else getattr(settings, "NETWORK_ACCESS_ACQUIRE_TIMEOUT", 120.0)
        ),
    )
    resolved_lease_seconds = max(0.1, float(lease_seconds))
    if heartbeat_seconds <= 0:
        raise ValueError("heartbeat_seconds must be positive")
    resolved_heartbeat_seconds = min(
        float(heartbeat_seconds),
        max(0.05, resolved_lease_seconds / 3.0),
    )
    canonical_device_id = str(device_id).strip() if device_id is not None else ""
    canonical_device_id = canonical_device_id or None
    owner_id = f"network-ssh:{os.getpid()}:{uuid.uuid4().hex}"
    lease_token = uuid.uuid4().hex
    deadline = time.monotonic() + resolved_wait_timeout

    while True:
        try:
            claim = _claim_slots_once(
                owner_id=owner_id,
                lease_token=lease_token,
                device_id=canonical_device_id,
                global_capacity=resolved_global_capacity,
                device_capacity=resolved_device_capacity,
                lease_seconds=resolved_lease_seconds,
            )
        except Exception:
            logger.warning("Shared SSH lease acquisition failed; denying SSH access")
            raise NetworkAccessLeaseError(
                "shared SSH lease coordination is unavailable; access denied"
            ) from None

        if claim is not None:
            return NetworkAccessLease(
                claim,
                lease_seconds=resolved_lease_seconds,
                heartbeat_seconds=resolved_heartbeat_seconds,
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise NetworkAccessLeaseError("shared SSH concurrency limit reached")
        time.sleep(min(_RETRY_INTERVAL_SECONDS, remaining))


__all__ = [
    "DEFAULT_HEARTBEAT_SECONDS",
    "DEFAULT_LEASE_SECONDS",
    "NETWORK_SSH_PURPOSE",
    "NetworkAccessLease",
    "NetworkAccessLeaseError",
    "acquire_network_ssh_lease",
]
