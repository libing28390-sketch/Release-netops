"""Process-local Redis client and adapter for shared CMDB query caching."""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

from core.config import settings
from services.cmdb_cache_service import CmdbQueryCache

logger = logging.getLogger(__name__)

_CACHE_LOCK = threading.Lock()
_CACHE: CmdbQueryCache | None = None
_CACHE_INITIALIZED = False


def get_cmdb_query_cache() -> CmdbQueryCache:
    """Return a per-worker adapter using the application's main Redis URL.

    Redis is optional at the request boundary. Invalid configuration and an
    unavailable redis-py install both produce a disabled, fail-open adapter.
    The key namespace is separate from IP locator, alert broker and LibreNMS.
    """
    global _CACHE, _CACHE_INITIALIZED
    if _CACHE_INITIALIZED and _CACHE is not None:
        return _CACHE
    with _CACHE_LOCK:
        if _CACHE_INITIALIZED and _CACHE is not None:
            return _CACHE
        client: Any | None = None
        try:
            import redis

            redis_url = str(getattr(settings, "REDIS_URL", "") or "").strip()
            if redis_url:
                client = redis.Redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=1.0,
                    socket_timeout=1.0,
                )
        except Exception as exc:
            logger.debug("CMDB Redis cache client unavailable (%s)", type(exc).__name__)

        environment = re.sub(
            r"[^a-z0-9_-]+", "_",
            str(getattr(settings, "ENVIRONMENT", "unknown") or "unknown").strip().lower(),
        ).strip("_-") or "unknown"
        namespace = f"nexora:{environment}:cmdb:v1"
        try:
            _CACHE = CmdbQueryCache(namespace, client, ttl_seconds=15)
        except Exception as exc:
            logger.debug("CMDB Redis cache adapter unavailable (%s)", type(exc).__name__)
            _CACHE = CmdbQueryCache(f"nexora:unknown:cmdb:v1", None, ttl_seconds=15)
        _CACHE_INITIALIZED = True
        return _CACHE


def reset_cmdb_query_cache() -> None:
    """Forget the process-local adapter for tests or controlled reconfiguration."""
    global _CACHE, _CACHE_INITIALIZED
    with _CACHE_LOCK:
        current = _CACHE
        _CACHE = None
        _CACHE_INITIALIZED = False
    if current is not None:
        close = getattr(current.redis_client, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:
                logger.debug("CMDB Redis client close failed (%s)", type(exc).__name__)
