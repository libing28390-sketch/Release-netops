"""CMDB-managed device names used for exact-match tokenization (D2).

Bare device names such as ``sw-core01`` are *not* tokenized by a generic
regex any more: a pattern loose enough to catch them also hits product
models like ``CE6800-48S``.  Instead only names that are actually managed
in the CMDB (``devices`` table) are replaced, by exact, case-insensitive,
ASCII-bounded matching (see ``tokenization.tokenize_text``).

Multi-tenancy: Nexora currently runs in single-organization mode, so every
row of ``devices`` belongs to the one organization and all device names are
loaded.  When real tenants arrive this loader must be keyed by tenant_id
(one cache entry per tenant) instead of returning a process-wide set.

Reading the database is disabled by default under tests (same detection as
``main.py`` / ``collector_sync_service.py``): the dev database may contain
devices such as ``CORE-SW1`` that would change payloads asserted verbatim
by existing tests.  Tests inject names explicitly with
:func:`set_known_device_names_for_tests`.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
from typing import Callable, Iterable

from core.config import settings


logger = logging.getLogger(__name__)

KNOWN_HOSTNAMES_UNAVAILABLE = "AI_KNOWN_HOSTNAMES_UNAVAILABLE"
DEFAULT_TTL_SECONDS = 300
MAX_DEVICE_NAMES = 20_000
MIN_NAME_LENGTH = 3
MAX_NAME_LENGTH = 64

# A name must contain an ASCII letter: purely numeric values are IDs/ports,
# and the matcher uses ASCII boundaries, so a Chinese-only "name" would hit
# ordinary prose everywhere.
_HAS_ASCII_LETTER_RE = re.compile(r"[A-Za-z]")


def is_test_environment() -> bool:
    return (
        os.environ.get("ENVIRONMENT", "").lower() == "test"
        or "PYTEST_CURRENT_TEST" in os.environ
        or "pytest" in sys.modules
    )


def normalize_device_names(values: Iterable[object]) -> frozenset[str]:
    """Keep non-empty names of 3-64 chars that contain a letter (max 20000)."""
    names: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        name = str(value).strip()
        if not (MIN_NAME_LENGTH <= len(name) <= MAX_NAME_LENGTH):
            continue
        if not _HAS_ASCII_LETTER_RE.search(name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
        if len(names) >= MAX_DEVICE_NAMES:
            break
    return frozenset(names)


def _load_from_database() -> list[object]:
    from database.core import get_db_connection

    values: list[object] = []
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(f"SELECT hostname, sys_name FROM devices LIMIT {MAX_DEVICE_NAMES}")
            rows = cursor.fetchall() or []
            for row in rows:
                values.append(row[0])
                values.append(row[1])
        except Exception:
            # Older databases may lack sys_name; hostname alone still helps.
            try:
                conn.rollback()
            except Exception:
                pass
            cursor = conn.cursor()
            cursor.execute(f"SELECT hostname FROM devices LIMIT {MAX_DEVICE_NAMES}")
            for row in cursor.fetchall() or []:
                values.append(row[0])
    return values


def _ttl_seconds() -> float:
    try:
        ttl = float(getattr(settings, "AI_KNOWN_HOSTNAME_TTL_SECONDS", DEFAULT_TTL_SECONDS))
    except (TypeError, ValueError):
        ttl = DEFAULT_TTL_SECONDS
    return ttl if ttl > 0 else DEFAULT_TTL_SECONDS


class KnownDeviceNameCache:
    """Process-local TTL cache; never raises to the caller."""

    def __init__(
        self,
        *,
        loader: Callable[[], Iterable[object]] | None = None,
        clock: Callable[[], float] | None = None,
        ttl_seconds: float | None = None,
        enabled: Callable[[], bool] | None = None,
    ):
        self._loader = loader or _load_from_database
        self._clock = clock or time.monotonic
        self._ttl_seconds = ttl_seconds
        self._enabled = enabled or (lambda: not is_test_environment())
        self._names: frozenset[str] = frozenset()
        self._loaded_at: float | None = None
        self._override: frozenset[str] | None = None
        self._version = 0
        self._lock = threading.Lock()

    @property
    def version(self) -> int:
        return self._version

    def _ttl(self) -> float:
        return float(self._ttl_seconds) if self._ttl_seconds else _ttl_seconds()

    def _set(self, names: frozenset[str]) -> None:
        if names != self._names:
            self._names = names
            self._version += 1

    def get(self) -> frozenset[str]:
        with self._lock:
            if self._override is not None:
                return self._override
            now = self._clock()
            if self._loaded_at is not None and now - self._loaded_at < self._ttl():
                return self._names
            if not self._enabled():
                names: frozenset[str] = frozenset()
            else:
                try:
                    names = normalize_device_names(self._loader())
                except Exception as exc:  # table missing, no connection, ...
                    logger.debug(
                        "%s: device names unavailable (%s)",
                        KNOWN_HOSTNAMES_UNAVAILABLE,
                        type(exc).__name__,
                        extra={"error_code": KNOWN_HOSTNAMES_UNAVAILABLE},
                    )
                    names = frozenset()
            self._set(names)
            self._loaded_at = now
            return self._names

    def set_for_tests(self, names: Iterable[object] | None) -> None:
        with self._lock:
            if names is None:
                self._override = None
            else:
                self._override = normalize_device_names(names)
                self._version += 1

    def reset(self) -> None:
        with self._lock:
            self._override = None
            self._names = frozenset()
            self._loaded_at = None
            self._version += 1


_cache = KnownDeviceNameCache()


def known_device_names() -> frozenset[str]:
    """CMDB device names (cached, TTL 300s by default); empty on any failure."""
    try:
        return _cache.get()
    except Exception:  # defensive: tokenization must never fail on this
        return frozenset()


def known_device_names_version() -> int:
    return _cache.version


def reset_cache() -> None:
    """Drop cached names and any test override (tests only)."""
    _cache.reset()


def set_known_device_names_for_tests(names: Iterable[object] | None) -> None:
    """Inject names (bypasses DB/TTL); ``None`` removes the override."""
    _cache.set_for_tests(names)
