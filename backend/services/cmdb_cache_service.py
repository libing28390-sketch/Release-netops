"""Best-effort Redis adapter for rebuildable CMDB query projections.

The adapter only serializes JSON-safe values and performs Redis ``GET`` and
``SET`` operations with an ``EX`` expiry, plus ``EVAL`` compare-and-delete for
short rebuild locks. It never queries PostgreSQL, starts a device operation,
or treats Redis as durable business storage. A missing or failing Redis client
is a cache miss/write skip so the caller can continue with its normal source
of truth.

Callers must obtain and pass a *persistent, versioned generation* (for
example, CMDB read revisions committed with the corresponding database facts)
as part of every key. Deleting a fixed key after a write is insufficient:
another worker can finish an older read later and repopulate that key. With a
new generation, such a worker can only write under the old generation, which
future reads no longer address. The caller remains responsible for reading
the generation and query result from a consistent database view.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any


MAX_TTL_SECONDS = 300
DEFAULT_MAX_ENTRY_BYTES = 256 * 1024
MAX_ENTRY_BYTES = 1024 * 1024
MAX_KEY_MATERIAL_BYTES = 16 * 1024
MAX_NAMESPACE_BYTES = 192
REDIS_FAILURE_COOLDOWN_SECONDS = 30.0
_LOCK_SUFFIX = ":rebuild-lock"
_LOCK_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32}$")
_RELEASE_LOCK_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


def _monotonic() -> float:
    """Isolated clock seam so cooldown behavior can be tested without sleeping."""

    return time.monotonic()


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON numeric constant: {value}")


def _validate_json_value(value: Any, active_containers: set[int] | None = None) -> None:
    """Reject Python-only values and non-finite floats instead of stringifying."""

    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return

    if active_containers is None:
        active_containers = set()

    if isinstance(value, list):
        container_id = id(value)
        if container_id in active_containers:
            raise ValueError("Cyclic values are not JSON-safe")
        active_containers.add(container_id)
        try:
            for item in value:
                _validate_json_value(item, active_containers)
        finally:
            active_containers.remove(container_id)
        return

    if isinstance(value, dict):
        container_id = id(value)
        if container_id in active_containers:
            raise ValueError("Cyclic values are not JSON-safe")
        active_containers.add(container_id)
        try:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError("JSON object keys must be strings")
                _validate_json_value(key, active_containers)
                _validate_json_value(item, active_containers)
        finally:
            active_containers.remove(container_id)
        return

    raise TypeError(f"Unsupported JSON value type: {type(value).__name__}")


def _canonical_json(value: Any) -> str:
    _validate_json_value(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True)
class CmdbCacheLock:
    """Opaque handle for one short-lived CMDB query rebuild lease."""

    key: str
    token: str = field(repr=False)


class CmdbQueryCache:
    """Small, fail-open JSON cache for already-authorized CMDB read results.

    ``namespace`` should identify the environment and schema version, such as
    ``nexora:production:cmdb:v1``. ``redis_client`` may be ``None`` to disable
    caching. TTLs are restricted to 1-300 seconds; individual entries default
    to a 256 KiB limit and can never exceed 1 MiB.

    Cache identity includes the resource name, caller-supplied persistent
    generation, authorization scope and normalized query. Those values are
    canonicalized and SHA-256 hashed, so raw search text, site IDs and revision
    details are not present in Redis keys. The caller must authenticate and
    compute the effective scope before using this adapter.

    All Redis and cache-encoding failures fail open: reads return ``None`` and
    writes return ``False``. ``failure_count`` and ``last_failure_kind`` are
    process-local diagnostics; they expose only exception class names and do
    not include Redis exception text or connection URLs. Redis command errors
    open a 30-second process-local cooldown, which successful Redis commands
    clear. Cold rebuilds can use ``acquire_rebuild_lock`` and
    ``release_rebuild_lock``; leases are bounded to 1-30 seconds and
    compare-and-delete protects another worker's lease.
    """

    def __init__(
        self,
        namespace: str,
        redis_client: Any | None,
        ttl_seconds: int = 30,
        max_entry_bytes: int = DEFAULT_MAX_ENTRY_BYTES,
    ) -> None:
        if not isinstance(namespace, str):
            raise TypeError("namespace must be a string")
        normalized_namespace = namespace.strip().strip(":")
        try:
            namespace_size = len(normalized_namespace.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ValueError("namespace must be valid UTF-8") from exc
        if namespace_size > MAX_NAMESPACE_BYTES:
            raise ValueError(f"namespace must be at most {MAX_NAMESPACE_BYTES} bytes")

        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
            raise TypeError("ttl_seconds must be an integer")
        if not 1 <= ttl_seconds <= MAX_TTL_SECONDS:
            raise ValueError(f"ttl_seconds must be between 1 and {MAX_TTL_SECONDS}")

        if isinstance(max_entry_bytes, bool) or not isinstance(max_entry_bytes, int):
            raise TypeError("max_entry_bytes must be an integer")
        if not 1 <= max_entry_bytes <= MAX_ENTRY_BYTES:
            raise ValueError(f"max_entry_bytes must be between 1 and {MAX_ENTRY_BYTES}")

        self.namespace = normalized_namespace
        self.redis_client = redis_client
        self.ttl_seconds = ttl_seconds
        self.max_entry_bytes = max_entry_bytes
        self._failure_count = 0
        self._last_failure_kind: str | None = None
        self._retry_after: float | None = None
        self._probe_in_progress = False
        self._state_lock = threading.Lock()

    @property
    def failure_count(self) -> int:
        """Number of Redis command failures observed by this process-local adapter."""

        with self._state_lock:
            return self._failure_count

    @property
    def last_failure_kind(self) -> str | None:
        """Class name of the most recent Redis error, without exception details."""

        with self._state_lock:
            return self._last_failure_kind

    @property
    def is_cooling_down(self) -> bool:
        """Whether Redis commands are currently skipped after an outage."""

        with self._state_lock:
            return self._retry_after is not None and _monotonic() < self._retry_after

    @property
    def cooldown_remaining_seconds(self) -> float:
        """Seconds until the next single Redis probe is allowed, or zero."""

        with self._state_lock:
            if self._retry_after is None:
                return 0.0
            return max(0.0, self._retry_after - _monotonic())

    def _redis_available_for_command(self) -> bool:
        if self.redis_client is None:
            return False
        with self._state_lock:
            if self._retry_after is None:
                return True
            if _monotonic() < self._retry_after:
                return False
            if self._probe_in_progress:
                return False
            self._probe_in_progress = True
            return True

    def _record_failure(self, exc: Exception) -> None:
        with self._state_lock:
            self._failure_count += 1
            self._last_failure_kind = type(exc).__name__
            self._retry_after = _monotonic() + REDIS_FAILURE_COOLDOWN_SECONDS
            self._probe_in_progress = False

    def _record_success(self) -> None:
        with self._state_lock:
            self._last_failure_kind = None
            self._retry_after = None
            self._probe_in_progress = False

    def build_key(
        self,
        resource: str,
        *,
        generation: Any,
        scope: Any,
        query: Any,
    ) -> str | None:
        """Build a bounded key; return ``None`` for disabled/unsafe identity data."""

        if not self.namespace or not isinstance(resource, str) or not resource.strip():
            return None
        try:
            material = _canonical_json(
                {
                    "generation": generation,
                    "query": query,
                    "resource": resource,
                    "scope": scope,
                }
            ).encode("utf-8")
            if len(material) > MAX_KEY_MATERIAL_BYTES:
                return None
        except (TypeError, ValueError, UnicodeEncodeError, RecursionError, OverflowError):
            return None

        digest = hashlib.sha256(material).hexdigest()
        return f"{self.namespace}:{digest}"

    def get_json(
        self,
        resource: str,
        *,
        generation: Any,
        scope: Any,
        query: Any,
    ) -> Any | None:
        """Return a decoded cached value, or ``None`` on miss/invalid data/error."""

        key = self.build_key(resource, generation=generation, scope=scope, query=query)
        if key is None or not self._redis_available_for_command():
            return None

        try:
            raw_value = self.redis_client.get(key)
            self._record_success()
        except Exception as exc:
            self._record_failure(exc)
            return None
        if raw_value is None:
            return None

        try:
            if isinstance(raw_value, bytes):
                if len(raw_value) > self.max_entry_bytes:
                    return None
                encoded_value = raw_value.decode("utf-8")
            elif isinstance(raw_value, str):
                if len(raw_value.encode("utf-8")) > self.max_entry_bytes:
                    return None
                encoded_value = raw_value
            else:
                return None

            value = json.loads(encoded_value, parse_constant=_reject_json_constant)
            # json.loads is permissive about a few Python edge cases. Recheck
            # parsed values so callers only receive finite, JSON-safe objects.
            _canonical_json(value).encode("utf-8")
            return value
        except (TypeError, ValueError, UnicodeDecodeError, RecursionError, OverflowError):
            return None

    def set_json(
        self,
        resource: str,
        *,
        generation: Any,
        scope: Any,
        query: Any,
        value: Any,
    ) -> bool:
        """Store a JSON-safe cache projection with ``SET ... EX``; never raises on cache failure."""

        key = self.build_key(resource, generation=generation, scope=scope, query=query)
        if key is None:
            return False
        try:
            encoded_value = _canonical_json(value)
            encoded_size = len(encoded_value.encode("utf-8"))
        except (TypeError, ValueError, UnicodeEncodeError, RecursionError, OverflowError):
            return False
        if encoded_size > self.max_entry_bytes:
            return False
        if not self._redis_available_for_command():
            return False

        try:
            result = self.redis_client.set(key, encoded_value, ex=self.ttl_seconds)
            self._record_success()
        except Exception as exc:
            self._record_failure(exc)
            return False
        return bool(result)

    def acquire_rebuild_lock(
        self,
        resource: str,
        *,
        generation: Any,
        scope: Any,
        query: Any,
        lease_seconds: int,
    ) -> CmdbCacheLock | None:
        """Try to acquire a per-query ``SET NX EX`` lease; fail open on Redis errors.

        ``None`` means another worker owns the lease, Redis is unavailable, or
        the supplied identity cannot form a safe cache key. Callers should
        bound any wait and may perform their normal source-of-truth read when
        no handle is returned.
        """

        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int):
            raise TypeError("lease_seconds must be an integer")
        if not 1 <= lease_seconds <= 30:
            raise ValueError("lease_seconds must be between 1 and 30")

        cache_key = self.build_key(
            resource, generation=generation, scope=scope, query=query
        )
        if cache_key is None or not self._redis_available_for_command():
            return None

        handle = CmdbCacheLock(
            key=f"{cache_key}{_LOCK_SUFFIX}",
            token=secrets.token_urlsafe(24),
        )
        try:
            result = self.redis_client.set(
                handle.key,
                handle.token,
                ex=lease_seconds,
                nx=True,
            )
            self._record_success()
        except Exception as exc:
            self._record_failure(exc)
            return None
        return handle if result else None

    def release_rebuild_lock(self, handle: CmdbCacheLock) -> bool:
        """Release only the lease represented by ``handle`` using compare-and-delete."""

        if not self._is_valid_lock_handle(handle) or not self._redis_available_for_command():
            return False
        try:
            result = self.redis_client.eval(
                _RELEASE_LOCK_SCRIPT,
                1,
                handle.key,
                handle.token,
            )
            self._record_success()
        except Exception as exc:
            self._record_failure(exc)
            return False
        return result == 1

    def _is_valid_lock_handle(self, handle: CmdbCacheLock) -> bool:
        if (
            not isinstance(handle, CmdbCacheLock)
            or not isinstance(handle.key, str)
            or not isinstance(handle.token, str)
            or not self.namespace
        ):
            return False
        prefix = f"{self.namespace}:"
        if not handle.key.startswith(prefix) or not handle.key.endswith(_LOCK_SUFFIX):
            return False
        digest = handle.key[len(prefix) : -len(_LOCK_SUFFIX)]
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            return False
        return bool(_LOCK_TOKEN_PATTERN.fullmatch(handle.token))
