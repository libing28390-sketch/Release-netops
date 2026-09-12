"""Small in-process TTL cache for safe, read-only API projections.

The cache is intentionally bounded by time rather than by unbounded request
keys. It is suitable for dashboard summaries that are expensive to assemble
but may be a few seconds stale. Mutating workflows can invalidate a whole
namespace after committing their database changes.
"""

from __future__ import annotations

import copy
import os
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    value: Any


class ReadTTLCache:
    def __init__(self, max_entries: int = 512) -> None:
        self._entries: dict[tuple[str, str], _CacheEntry] = {}
        self._lock = threading.RLock()
        self._max_entries = max(1, max_entries)

    def get(self, namespace: str, key: str) -> tuple[bool, Any]:
        cache_key = (namespace, key)
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(cache_key)
            if entry is None:
                return False, None
            if entry.expires_at <= now:
                self._entries.pop(cache_key, None)
                return False, None
            return True, copy.deepcopy(entry.value)

    def set(self, namespace: str, key: str, value: Any, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        with self._lock:
            now = time.monotonic()
            for cache_key, entry in list(self._entries.items()):
                if entry.expires_at <= now:
                    self._entries.pop(cache_key, None)
            if len(self._entries) >= self._max_entries and (namespace, key) not in self._entries:
                oldest_key = min(self._entries, key=lambda item: self._entries[item].expires_at)
                self._entries.pop(oldest_key, None)
            self._entries[(namespace, key)] = _CacheEntry(
                expires_at=now + ttl_seconds,
                value=copy.deepcopy(value),
            )

    def invalidate(self, namespace: str | None = None) -> None:
        with self._lock:
            if namespace is None:
                self._entries.clear()
                return
            for cache_key in [key for key in self._entries if key[0] == namespace]:
                self._entries.pop(cache_key, None)


read_cache = ReadTTLCache()

# Keep these settings local and optional so deployments do not need a schema
# or Redis dependency just to tune dashboard freshness.
TOPOLOGY_CACHE_TTL_SECONDS = max(
    0.0, float(os.environ.get('READ_CACHE_TOPOLOGY_SECONDS', '10'))
)
PLAYBOOK_CACHE_TTL_SECONDS = max(
    0.0, float(os.environ.get('READ_CACHE_PLAYBOOKS_SECONDS', '5'))
)
SCHEDULED_JOBS_CACHE_TTL_SECONDS = max(
    0.0, float(os.environ.get('READ_CACHE_SCHEDULED_JOBS_SECONDS', '5'))
)
RACK_CACHE_TTL_SECONDS = max(
    0.0, float(os.environ.get('READ_CACHE_RACKS_SECONDS', '10'))
)
REFERENCE_CACHE_TTL_SECONDS = max(
    0.0, float(os.environ.get('READ_CACHE_REFERENCES_SECONDS', '30'))
)


def invalidate_read_cache(namespace: str | None = None) -> None:
    read_cache.invalidate(namespace)
