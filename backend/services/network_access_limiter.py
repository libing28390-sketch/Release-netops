"""Shared concurrency gates for outbound network access.

The platform has several collectors which historically maintained their own
thread pools.  This module provides a single process-wide gate for SSH/CLI
work and separate gates for SNMP and reachability probes.  It deliberately
does not contain vendor logic; callers still own connection construction and
timeouts.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
import asyncio
from dataclasses import dataclass
import threading
from typing import Any, Callable, Iterator

from core.config import settings


class NetworkAccessLimitError(TimeoutError):
    """Raised when a network operation cannot obtain a slot in time."""


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _device_key(device: Any, username: str | None = None, port: int | None = None) -> str:
    """Return a stable key without ever including a password or secret."""
    if isinstance(device, dict):
        device_id = device.get("id") or device.get("device_id")
        host = device.get("ip_address") or device.get("ip") or device.get("hostname")
        resolved_port = port or device.get("management_port") or device.get("port") or 22
        resolved_user = username or device.get("username") or ""
    else:
        device_id = None
        host = device
        resolved_port = port or 22
        resolved_user = username or ""
    # Device id is preferred so a hostname/IP change does not create a second
    # per-device lane.  The fallback is useful for collectors with partial rows.
    return f"id:{device_id}" if device_id else f"host:{host}:{resolved_port}:{resolved_user}"


@dataclass
class _Counters:
    ssh: int = 0
    snmp: int = 0
    probe: int = 0


class NetworkAccessLimiter:
    """Process-wide SSH/SNMP/probe concurrency controller.

    The SSH gate has both a global semaphore and a per-device lock.  The
    per-device lock intentionally serializes normal/admin/collector access to
    the same device; this avoids competing CLI prompts and VTY exhaustion.
    """

    def __init__(
        self,
        *,
        ssh_global_limit: int | None = None,
        ssh_per_device_limit: int | None = None,
        snmp_global_limit: int | None = None,
        probe_global_limit: int | None = None,
        acquire_timeout: float | None = None,
    ) -> None:
        self.ssh_global_limit = _positive_int(
            ssh_global_limit if ssh_global_limit is not None
            else getattr(settings, "NETWORK_SSH_GLOBAL_CONCURRENCY", 20),
            20,
        )
        self.ssh_per_device_limit = _positive_int(
            ssh_per_device_limit if ssh_per_device_limit is not None
            else getattr(settings, "NETWORK_SSH_PER_DEVICE_CONCURRENCY", 1),
            1,
        )
        self.snmp_global_limit = _positive_int(
            snmp_global_limit if snmp_global_limit is not None
            else getattr(settings, "NETWORK_SNMP_GLOBAL_CONCURRENCY", 30),
            30,
        )
        self.probe_global_limit = _positive_int(
            probe_global_limit if probe_global_limit is not None
            else getattr(settings, "NETWORK_PROBE_GLOBAL_CONCURRENCY", 50),
            50,
        )
        self.acquire_timeout = float(
            acquire_timeout if acquire_timeout is not None
            else getattr(settings, "NETWORK_ACCESS_ACQUIRE_TIMEOUT", 120)
        )

        self._ssh_global = threading.BoundedSemaphore(self.ssh_global_limit)
        self._snmp_global = threading.BoundedSemaphore(self.snmp_global_limit)
        self._probe_global = threading.BoundedSemaphore(self.probe_global_limit)
        self._snmp_async: asyncio.Semaphore | None = None
        self._snmp_async_loop: asyncio.AbstractEventLoop | None = None
        self._probe_async: asyncio.Semaphore | None = None
        self._probe_async_loop: asyncio.AbstractEventLoop | None = None
        self._device_locks: dict[str, threading.BoundedSemaphore] = {}
        self._locks_guard = threading.Lock()
        self._counter_guard = threading.Lock()
        self._counters = _Counters()

    def _device_lock(self, key: str) -> threading.BoundedSemaphore:
        with self._locks_guard:
            lock = self._device_locks.get(key)
            if lock is None:
                lock = threading.BoundedSemaphore(self.ssh_per_device_limit)
                self._device_locks[key] = lock
            return lock

    @staticmethod
    def _acquire(semaphore: threading.BoundedSemaphore, timeout: float) -> bool:
        return semaphore.acquire(timeout=max(0.0, timeout))

    @contextmanager
    def ssh(
        self,
        device: Any,
        *,
        username: str | None = None,
        port: int | None = None,
        operation: str = "cli",
        timeout: float | None = None,
    ) -> Iterator[None]:
        """Reserve one SSH/CLI slot for the complete connection operation."""
        wait_timeout = self.acquire_timeout if timeout is None else timeout
        key = _device_key(device, username=username, port=port)
        device_lock = self._device_lock(key)
        if not self._acquire(device_lock, wait_timeout):
            raise NetworkAccessLimitError(
                f"device concurrency limit reached for {key} (operation={operation})"
            )
        global_acquired = False
        try:
            if not self._acquire(self._ssh_global, wait_timeout):
                raise NetworkAccessLimitError(
                    f"global SSH concurrency limit reached ({self.ssh_global_limit})"
                )
            global_acquired = True
            with self._counter_guard:
                self._counters.ssh += 1
            try:
                yield
            finally:
                with self._counter_guard:
                    self._counters.ssh = max(0, self._counters.ssh - 1)
                self._ssh_global.release()
        finally:
            if global_acquired is False:
                # Nothing to release from the global semaphore; the device
                # semaphore is still released below.
                pass
            device_lock.release()

    @contextmanager
    def snmp(self, *, timeout: float | None = None) -> Iterator[None]:
        wait_timeout = self.acquire_timeout if timeout is None else timeout
        if not self._acquire(self._snmp_global, wait_timeout):
            raise NetworkAccessLimitError(
                f"global SNMP concurrency limit reached ({self.snmp_global_limit})"
            )
        with self._counter_guard:
            self._counters.snmp += 1
        try:
            yield
        finally:
            with self._counter_guard:
                self._counters.snmp = max(0, self._counters.snmp - 1)
            self._snmp_global.release()

    @contextmanager
    def probe(self, *, timeout: float | None = None) -> Iterator[None]:
        wait_timeout = self.acquire_timeout if timeout is None else timeout
        if not self._acquire(self._probe_global, wait_timeout):
            raise NetworkAccessLimitError(
                f"global probe concurrency limit reached ({self.probe_global_limit})"
            )
        with self._counter_guard:
            self._counters.probe += 1
        try:
            yield
        finally:
            with self._counter_guard:
                self._counters.probe = max(0, self._counters.probe - 1)
            self._probe_global.release()

    @asynccontextmanager
    async def async_ssh(
        self,
        device: Any,
        *,
        username: str | None = None,
        port: int | None = None,
        operation: str = "cli",
        timeout: float | None = None,
    ) -> Iterator[None]:
        """Async adapter for scrapli/asyncssh collectors."""
        lease = self.ssh(
            device,
            username=username,
            port=port,
            operation=operation,
            timeout=timeout,
        )
        await asyncio.to_thread(lease.__enter__)
        try:
            yield
        finally:
            await asyncio.to_thread(lease.__exit__, None, None, None)

    @asynccontextmanager
    async def async_snmp(self) -> Iterator[None]:
        """Async SNMP gate shared by all OID GET/WALK operations."""
        loop = asyncio.get_running_loop()
        if self._snmp_async is None or self._snmp_async_loop is not loop:
            self._snmp_async = asyncio.Semaphore(self.snmp_global_limit)
            self._snmp_async_loop = loop
        async with self._snmp_async:
            with self._counter_guard:
                self._counters.snmp += 1
            try:
                yield
            finally:
                with self._counter_guard:
                    self._counters.snmp = max(0, self._counters.snmp - 1)

    @asynccontextmanager
    async def async_probe(self) -> Iterator[None]:
        """Async probe gate for the A/B monitoring loops."""
        loop = asyncio.get_running_loop()
        if self._probe_async is None or self._probe_async_loop is not loop:
            self._probe_async = asyncio.Semaphore(self.probe_global_limit)
            self._probe_async_loop = loop
        async with self._probe_async:
            with self._counter_guard:
                self._counters.probe += 1
            try:
                yield
            finally:
                with self._counter_guard:
                    self._counters.probe = max(0, self._counters.probe - 1)

    def snapshot(self) -> dict[str, int]:
        with self._counter_guard:
            return {
                "active_ssh": self._counters.ssh,
                "active_snmp": self._counters.snmp,
                "active_probes": self._counters.probe,
                "ssh_global_limit": self.ssh_global_limit,
                "ssh_per_device_limit": self.ssh_per_device_limit,
                "snmp_global_limit": self.snmp_global_limit,
                "probe_global_limit": self.probe_global_limit,
            }


_LIMITER = NetworkAccessLimiter()


def get_network_access_limiter() -> NetworkAccessLimiter:
    return _LIMITER


@contextmanager
def limited_connect_handler(
    device: Any,
    connect_handler: Callable[..., Any],
    **connection_params: Any,
) -> Iterator[Any]:
    """Wrap a Netmiko ``ConnectHandler`` context with the SSH gate."""
    username = connection_params.get("username")
    port = connection_params.get("port")
    with _LIMITER.ssh(device, username=username, port=port):
        with connect_handler(**connection_params) as client:
            yield client
