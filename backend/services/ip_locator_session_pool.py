"""Bounded, exclusive SSH sessions for the four-stage IP locator.

The pool deliberately owns both the Netmiko connection and its PostgreSQL
device/deployment leases. Idle sessions therefore continue to consume the
configured CLI budget and cannot be duplicated by another process. Session
keys contain only a one-way credential fingerprint; credentials are never
logged or persisted by this module.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import logging
import os
import socket
import threading
import time
import uuid
from types import SimpleNamespace
from typing import Any, Iterator, Mapping

from core.config import settings

logger = logging.getLogger(__name__)


class LocatorSessionError(TimeoutError):
    """A locator SSH session or its distributed lease is unavailable."""


class LocatorSessionLeaseLost(LocatorSessionError):
    """The distributed session lease was lost while a command was running."""


@dataclass
class _SessionEntry:
    device_id: str
    connection_key: str
    device: dict[str, Any]
    client: Any
    username: str
    owner_id: str
    task_id: str
    run_id: str
    network_lease: Any
    global_lease: dict[str, Any]
    last_used: float
    command_lock: threading.Lock = field(default_factory=threading.Lock)
    stop: threading.Event = field(default_factory=threading.Event)
    waiters: int = 0
    in_use: bool = False
    closing: bool = False
    close_after_use: bool = False
    lease_lost: bool = False
    disposed: bool = False
    heartbeat_thread: threading.Thread | None = None


_ACTIVE_SESSION = threading.local()


def _credential_attempts(device: Mapping[str, Any]) -> list[tuple[str, str]]:
    attempts = [(
        str(device.get("_ssh_username") or device.get("username") or ""),
        str(device.get("_ssh_password") or device.get("password") or ""),
    )]
    for item in device.get("_ssh_fallback_credentials") or []:
        try:
            username, password = item
        except (TypeError, ValueError):
            continue
        attempts.append((str(username or ""), str(password or "")))
    unique: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pair in attempts:
        if not all(pair) or pair in seen:
            continue
        seen.add(pair)
        unique.append(pair)
    return unique


def _connection_fingerprint(device: Mapping[str, Any]) -> str:
    attempts = _credential_attempts(device)
    material = {
        "device_id": str(device.get("id") or ""),
        "host": str(device.get("ip_address") or device.get("hostname") or ""),
        "port": int(device.get("port") or device.get("management_port") or 22),
        "platform": str(device.get("platform") or ""),
        "connection_driver": str(device.get("connection_driver") or ""),
        "platform_code": str(device.get("platform_code") or ""),
        "parser_platform": str(device.get("parser_platform") or ""),
        "profile_id": str(device.get("platform_profile_id") or ""),
        "algorithm_profile": str(device.get("ssh_algorithm_profile") or ""),
        "credentials": attempts,
        "enable_secret": str(device.get("_ssh_enable") or device.get("enable_password") or ""),
    }
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _connection_alive(client: Any) -> bool:
    is_alive = getattr(client, "is_alive", None)
    if not callable(is_alive):
        return True
    try:
        return bool(is_alive())
    except Exception:
        return False


def _close_client(client: Any) -> None:
    try:
        disconnect = getattr(client, "disconnect", None)
        if callable(disconnect):
            disconnect()
            return
        close = getattr(client, "close", None)
        if callable(close):
            close()
    except Exception as exc:
        logger.debug("IP locator SSH session close failed (%s)", type(exc).__name__)


class ActiveLocatorSession:
    """Safe adapter for one exclusively borrowed locator session."""

    def __init__(self, pool: "IPLocatorSessionPool", entry: _SessionEntry):
        self._pool = pool
        self._entry = entry

    @property
    def device_id(self) -> str:
        return self._entry.device_id

    def matches(self, device: Mapping[str, Any]) -> bool:
        return (
            str(device.get("id") or "") == self._entry.device_id
            and str(device.get("platform_profile_id") or "")
            == str(self._entry.device.get("platform_profile_id") or "")
            and str(device.get("connection_driver") or "")
            == str(self._entry.device.get("connection_driver") or "")
            and str(device.get("parser_platform") or "")
            == str(self._entry.device.get("parser_platform") or "")
        )

    def send_command_text(
        self,
        command: str,
        *,
        read_timeout: int = 30,
        cmd_verify: bool = False,
        strip_prompt: bool = True,
        strip_command: bool = True,
    ) -> str:
        entry = self._entry
        if entry.lease_lost or entry.closing or entry.disposed:
            raise LocatorSessionLeaseLost("locator SSH session lease is no longer owned")
        remaining = self._pool._operation_remaining()
        if remaining <= 0:
            raise TimeoutError("locator CLI task deadline exceeded")
        selected_read_timeout = max(1, min(int(read_timeout), int(remaining)))
        from services.network_access_limiter import get_network_access_limiter

        with get_network_access_limiter().ssh(
            entry.device,
            username=entry.username,
            port=int(entry.device.get("port") or entry.device.get("management_port") or 22),
            operation="ip_locator_command",
            timeout=max(0.1, remaining),
            coordinated=False,
        ):
            if entry.lease_lost or entry.closing or not entry.network_lease.is_valid:
                raise LocatorSessionLeaseLost("locator SSH session lease is no longer owned")
            try:
                output = entry.client.send_command(
                    command,
                    cmd_verify=cmd_verify,
                    strip_prompt=strip_prompt,
                    strip_command=strip_command,
                    read_timeout=selected_read_timeout,
                )
            except Exception:
                if not _connection_alive(entry.client):
                    self._pool._mark_for_close(entry)
                raise
        return str(output or "")

    def send_command(self, command: str) -> SimpleNamespace:
        """Platform-registry compatible command result adapter."""
        try:
            output = self.send_command_text(command)
            return SimpleNamespace(success=True, output=output, command=command, error="")
        except Exception as exc:
            return SimpleNamespace(
                success=False,
                output="",
                command=command,
                error=f"CLI_QUERY_FAILED:{type(exc).__name__}",
            )

    def legacy_client(self) -> "_LegacySessionClient":
        return _LegacySessionClient(self)


class _LegacySessionClient:
    """Expose the Netmiko send_command shape used by operational collectors."""

    def __init__(self, session: ActiveLocatorSession):
        self._session = session

    def send_command(self, command: str, **kwargs: Any) -> str:
        return self._session.send_command_text(
            command,
            read_timeout=int(kwargs.get("read_timeout") or 30),
            cmd_verify=bool(kwargs.get("cmd_verify", False)),
            strip_prompt=bool(kwargs.get("strip_prompt", True)),
            strip_command=bool(kwargs.get("strip_command", True)),
        )


class IPLocatorSessionPool:
    """Per-process exclusive pool backed by cross-process PostgreSQL leases."""

    def __init__(self, *, idle_seconds: int | None = None, heartbeat_interval: float | None = None):
        self.idle_seconds = max(
            1,
            int(idle_seconds if idle_seconds is not None else getattr(settings, "IP_LOCATOR_CLI_IDLE_SECONDS", 15)),
        )
        self.heartbeat_interval = max(
            0.5,
            float(heartbeat_interval if heartbeat_interval is not None else min(5, self.idle_seconds / 3)),
        )
        self._lock = threading.RLock()
        self._entries: dict[str, _SessionEntry] = {}
        self._opening_locks: dict[str, threading.Lock] = {}
        self._operation_deadline = threading.local()

    def _operation_remaining(self) -> float:
        deadline = float(getattr(self._operation_deadline, "value", 0.0) or 0.0)
        return max(0.0, deadline - time.monotonic()) if deadline else float("inf")

    @staticmethod
    def _worker_owner() -> str:
        return f"ip-locator-session:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

    def _connect(self, device: dict[str, Any], timeout: float) -> tuple[Any, str]:
        from netmiko import NetmikoAuthenticationException
        from services import ip_locator_service as legacy
        from services.network_access_limiter import get_network_access_limiter

        raw_platform = str(device.get("platform") or "").strip().lower()
        vendor = str(device.get("vendor") or "").strip()
        if not raw_platform and not vendor:
            raise LocatorSessionError("device vendor/platform is missing")
        from core.platform_utils import normalize_device_platform

        platform = str(normalize_device_platform(vendor, raw_platform) or "").strip().lower()
        expected_type = legacy.PLATFORM_DEVICE_TYPE_MAP.get(platform)
        configured_driver = str(device.get("connection_driver") or "").strip().lower()
        supported_driver_types = set(legacy.PLATFORM_DEVICE_TYPE_MAP.values())
        configured_type = (
            configured_driver
            if configured_driver in supported_driver_types
            else legacy.PLATFORM_DEVICE_TYPE_MAP.get(configured_driver)
        ) if configured_driver else None
        if not expected_type or (configured_driver and not configured_type):
            raise LocatorSessionError(f"no registered SSH driver for platform {platform or '<empty>'}")
        if configured_type and configured_type != expected_type:
            raise LocatorSessionError("device platform and connection driver do not match")

        attempts = _credential_attempts(device)
        if not attempts:
            raise PermissionError("No usable SSH credentials are configured for this device")
        last_auth_error: Exception | None = None
        for username, password in attempts:
            attempt = dict(device)
            attempt["platform"] = platform
            attempt["_ssh_username"] = username
            attempt["_ssh_password"] = password
            params = legacy._build_ssh_params(attempt)
            remaining = max(0.1, timeout)
            client = None
            try:
                with get_network_access_limiter().ssh(
                    attempt,
                    username=username,
                    port=int(params.get("port") or 22),
                    operation="ip_locator_connect",
                    timeout=remaining,
                    coordinated=False,
                ):
                    client = legacy.ConnectHandler(**params)
                if params.get("secret"):
                    try:
                        client.enable()
                    except Exception:
                        pass
                return client, username
            except NetmikoAuthenticationException as exc:
                last_auth_error = exc
                _close_client(client)
                continue
            except Exception:
                _close_client(client)
                raise
        if last_auth_error is not None:
            raise last_auth_error
        raise PermissionError("No usable SSH credentials are configured for this device")

    def _open_entry(
        self,
        device: dict[str, Any],
        *,
        task_id: str,
        run_id: str,
        deadline: float,
    ) -> _SessionEntry | None:
        device_id = str(device.get("id") or "").strip()
        if not device_id:
            raise LocatorSessionError("managed device identity is required for locator CLI")
        owner = self._worker_owner()
        lease_seconds = 90
        network_lease = None
        global_lease = None
        try:
            from services import ip_locator_task_service as tasks
            from services.network_access_lease_service import acquire_network_ssh_lease
        except Exception as exc:
            raise LocatorSessionError("locator CLI budget service is unavailable") from exc

        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            try:
                network_lease = acquire_network_ssh_lease(
                    device_id=device_id,
                    global_capacity=max(1, int(getattr(settings, "NETWORK_SSH_GLOBAL_CONCURRENCY", 20))),
                    device_capacity=max(1, int(getattr(settings, "NETWORK_SSH_PER_DEVICE_CONCURRENCY", 1))),
                    wait_timeout=remaining,
                    lease_seconds=lease_seconds,
                    heartbeat_seconds=self.heartbeat_interval,
                )
            except Exception as exc:
                raise LocatorSessionError("shared network SSH budget is unavailable") from exc
            try:
                global_lease = tasks.acquire_global_access_lease(
                    owner_id=owner,
                    run_id=run_id or task_id,
                    capacity=max(1, int(getattr(settings, "IP_LOCATOR_CLI_GLOBAL_CONCURRENCY", 5))),
                    purpose="ip_locator",
                    lease_seconds=lease_seconds,
                )
            except Exception:
                network_lease.release()
                raise
            if global_lease is None:
                network_lease.release()
                network_lease = None
                time.sleep(min(0.2, max(0.01, deadline - time.monotonic())))
                continue
            break
        else:
            raise LocatorSessionError("locator CLI device/global concurrency budget is busy")

        try:
            client, username = self._connect(device, max(0.1, deadline - time.monotonic()))
            session_device = {
                key: device.get(key)
                for key in (
                    "id",
                    "hostname",
                    "ip_address",
                    "port",
                    "management_port",
                    "platform",
                    "vendor",
                    "platform_profile_id",
                    "platform_code",
                    "parser_platform",
                    "connection_driver",
                    "ssh_algorithm_profile",
                    "tenant_id",
                    "site_id",
                    "site",
                    "device_group_id",
                )
                if device.get(key) is not None
            }
            session_device["username"] = username
            entry = _SessionEntry(
                device_id=device_id,
                connection_key=_connection_fingerprint(device),
                device=session_device,
                client=client,
                username=username,
                owner_id=owner,
                task_id=task_id,
                run_id=run_id,
                network_lease=network_lease,
                global_lease=global_lease,
                last_used=time.monotonic(),
                waiters=1,
            )
            return entry
        except Exception:
            if global_lease is not None:
                try:
                    tasks.release_global_access_lease(
                        owner_id=owner,
                        lease_token=str(global_lease.get("lease_token") or ""),
                        slot_id=int(global_lease.get("slot_id") or 0),
                        purpose="ip_locator",
                    )
                except Exception as release_exc:
                    logger.warning("[IPLocator] Locator slot release failed (%s)", type(release_exc).__name__)
            if network_lease is not None:
                network_lease.release()
            raise

    def _entry_heartbeat(self, entry: _SessionEntry) -> None:
        while not entry.stop.wait(self.heartbeat_interval):
            now = time.monotonic()
            with self._lock:
                if entry.disposed:
                    return
                idle_expired = (
                    not entry.in_use
                    and entry.waiters == 0
                    and now - entry.last_used >= self.idle_seconds
                )
                busy = entry.in_use or entry.waiters > 0
            if idle_expired:
                self._dispose_entry(entry)
                return
            try:
                from services import ip_locator_task_service as tasks

                global_ok = tasks.renew_global_access_lease(
                    owner_id=entry.owner_id,
                    lease_token=str(entry.global_lease.get("lease_token") or ""),
                    slot_id=int(entry.global_lease.get("slot_id") or 0),
                    purpose="ip_locator",
                    lease_seconds=90,
                )
                device_ok = bool(entry.network_lease.is_valid)
            except Exception as exc:
                logger.warning("[IPLocator] SSH session lease renewal failed (%s)", type(exc).__name__)
                device_ok = global_ok = False
            if not device_ok or not global_ok:
                with self._lock:
                    entry.lease_lost = True
                    entry.close_after_use = True
                    busy = entry.in_use or entry.waiters > 0
                if not busy:
                    self._dispose_entry(entry)
                    return

    def _get_or_open_entry(
        self,
        device: dict[str, Any],
        *,
        task_id: str,
        run_id: str,
        deadline: float,
    ) -> _SessionEntry:
        device_id = str(device.get("id") or "").strip()
        if not device_id:
            raise LocatorSessionError("managed device identity is required for locator CLI")
        key = _connection_fingerprint(device)
        with self._lock:
            opening_lock = self._opening_locks.setdefault(device_id, threading.Lock())
        if not opening_lock.acquire(timeout=max(0.1, deadline - time.monotonic())):
            raise LocatorSessionError("timed out waiting for local device session initialization")
        try:
            while time.monotonic() < deadline:
                with self._lock:
                    existing = self._entries.get(device_id)
                    idle_expired = bool(
                        existing
                        and not existing.in_use
                        and existing.waiters == 0
                        and time.monotonic() - existing.last_used >= self.idle_seconds
                    )
                    if (
                        existing
                        and existing.connection_key == key
                        and not existing.closing
                        and not existing.lease_lost
                        and not idle_expired
                    ):
                        if _connection_alive(existing.client):
                            existing.waiters += 1
                            existing.last_used = time.monotonic()
                            return existing
                        existing.close_after_use = True
                    elif existing:
                        existing.close_after_use = True
                    replaceable = bool(
                        existing
                        and not existing.in_use
                        and existing.waiters == 0
                    )
                if existing and replaceable:
                    self._dispose_entry(existing)
                    continue
                if existing:
                    time.sleep(min(0.1, max(0.01, deadline - time.monotonic())))
                    continue

                entry = self._open_entry(
                    device,
                    task_id=task_id,
                    run_id=run_id,
                    deadline=deadline,
                )
                with self._lock:
                    current = self._entries.get(device_id)
                    if current is not None:
                        # The per-device opening lock should make this
                        # unreachable, but keep the database slot fenced if
                        # an external caller raced pool shutdown.
                        entry.close_after_use = True
                    else:
                        self._entries[device_id] = entry
                        entry.heartbeat_thread = threading.Thread(
                            target=self._entry_heartbeat,
                            args=(entry,),
                            name=f"ip-locator-session-{device_id[:24]}",
                            daemon=True,
                        )
                        entry.heartbeat_thread.start()
                        return entry
                self._dispose_entry(entry)
            raise LocatorSessionError("timed out waiting for a reusable locator SSH session")
        finally:
            opening_lock.release()

    def _dispose_entry(self, entry: _SessionEntry) -> bool:
        with self._lock:
            if entry.disposed:
                return True
            if entry.in_use or entry.waiters > 0:
                entry.close_after_use = True
                return False
            entry.closing = True
            entry.disposed = True
            if self._entries.get(entry.device_id) is entry:
                self._entries.pop(entry.device_id, None)
            entry.stop.set()
        _close_client(entry.client)
        try:
            from services import ip_locator_task_service as tasks

            tasks.release_global_access_lease(
                owner_id=entry.owner_id,
                lease_token=str(entry.global_lease.get("lease_token") or ""),
                slot_id=int(entry.global_lease.get("slot_id") or 0),
                purpose="ip_locator",
            )
        except Exception as exc:
            logger.warning("[IPLocator] SSH session lease release failed (%s)", type(exc).__name__)
        finally:
            entry.network_lease.release()
        return True

    def _mark_for_close(self, entry: _SessionEntry) -> None:
        with self._lock:
            entry.close_after_use = True
            busy = entry.in_use or entry.waiters > 0
        if not busy:
            self._dispose_entry(entry)

    def run(
        self,
        device: dict[str, Any],
        callback: Any,
        *,
        task_id: str,
        run_id: str,
        wait_seconds: int,
    ) -> Any:
        deadline = time.monotonic() + max(1, int(wait_seconds))
        while time.monotonic() < deadline:
            entry = self._get_or_open_entry(
                device,
                task_id=task_id,
                run_id=run_id,
                deadline=deadline,
            )
            acquired = entry.command_lock.acquire(timeout=max(0.1, deadline - time.monotonic()))
            with self._lock:
                entry.waiters = max(0, entry.waiters - 1)
                if acquired and not entry.closing and not entry.lease_lost and not entry.disposed:
                    entry.in_use = True
                    entry.last_used = time.monotonic()
                    use_entry = True
                else:
                    use_entry = False
            if not acquired:
                self._mark_for_close(entry) if entry.close_after_use else None
                raise LocatorSessionError("timed out waiting for exclusive locator SSH session")
            if not use_entry:
                entry.command_lock.release()
                self._mark_for_close(entry)
                continue

            active_session = ActiveLocatorSession(self, entry)
            previous_session = getattr(_ACTIVE_SESSION, "entry", None)
            previous_deadline = getattr(self._operation_deadline, "value", None)
            _ACTIVE_SESSION.entry = (self, entry)
            self._operation_deadline.value = deadline
            try:
                result = callback()
                if entry.lease_lost:
                    raise LocatorSessionLeaseLost("locator SSH session lease was lost during the command")
                return result
            except Exception:
                if not _connection_alive(entry.client):
                    entry.close_after_use = True
                raise
            finally:
                _ACTIVE_SESSION.entry = previous_session
                if previous_deadline is None:
                    try:
                        del self._operation_deadline.value
                    except AttributeError:
                        pass
                else:
                    self._operation_deadline.value = previous_deadline
                with self._lock:
                    entry.in_use = False
                    entry.last_used = time.monotonic()
                    dispose_after_use = entry.close_after_use or entry.lease_lost
                entry.command_lock.release()
                if dispose_after_use:
                    self._dispose_entry(entry)
            # An entry whose lease disappeared while it was being borrowed is
            # discarded and the caller may establish a new bounded session.
        raise LocatorSessionError("locator CLI task deadline exceeded")

    def close_all(self) -> None:
        with self._lock:
            entries = list(self._entries.values())
        for entry in entries:
            self._mark_for_close(entry)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            entries = list(self._entries.values())
            return {
                "active_sessions": len(entries),
                "active_commands": sum(1 for entry in entries if entry.in_use),
                "idle_timeout_seconds": self.idle_seconds,
                "max_sessions": max(1, int(getattr(settings, "IP_LOCATOR_CLI_GLOBAL_CONCURRENCY", 5))),
            }


_SESSION_POOL: IPLocatorSessionPool | None = None
_SESSION_POOL_LOCK = threading.Lock()


def get_ip_locator_session_pool() -> IPLocatorSessionPool:
    global _SESSION_POOL
    if _SESSION_POOL is None:
        with _SESSION_POOL_LOCK:
            if _SESSION_POOL is None:
                _SESSION_POOL = IPLocatorSessionPool()
    return _SESSION_POOL


def close_ip_locator_sessions() -> None:
    pool = _SESSION_POOL
    if pool is not None:
        pool.close_all()


def get_active_locator_session(device: Mapping[str, Any]) -> ActiveLocatorSession | None:
    active = getattr(_ACTIVE_SESSION, "entry", None)
    if not isinstance(active, tuple) or len(active) != 2:
        return None
    pool, entry = active
    if entry is None or str(device.get("id") or "") != entry.device_id:
        return None
    return ActiveLocatorSession(pool, entry)


__all__ = [
    "ActiveLocatorSession",
    "IPLocatorSessionPool",
    "LocatorSessionError",
    "LocatorSessionLeaseLost",
    "close_ip_locator_sessions",
    "get_active_locator_session",
    "get_ip_locator_session_pool",
]
