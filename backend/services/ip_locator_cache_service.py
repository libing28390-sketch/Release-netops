"""Shared Redis cache adapter for the IP locator.

Redis is deliberately treated as a rebuildable projection.  This module owns
the connection policy, key namespace, TTL accounting and failure isolation so
locator workers do not each create subtly different clients or cache keys.
It does not contain persistence or task queue logic; PostgreSQL remains the
source of truth for those concerns.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlsplit

from core.config import settings

logger = logging.getLogger(__name__)

try:  # redis is a production dependency, but imports stay optional for tools.
    import redis
except Exception:  # pragma: no cover - exercised only in minimal tooling envs
    redis = None  # type: ignore[assignment]


_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9_.:@/-]+")
_UTC_FORMATS = ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z")


@dataclass(frozen=True)
class CachePolicy:
    """Freshness and physical retention windows for one observation kind."""

    fresh_seconds: int
    retain_seconds: int


_POLICY_FIELDS: dict[str, tuple[str, str]] = {
    "route": ("IP_LOCATOR_ROUTE_FRESH_SECONDS", "IP_LOCATOR_ROUTE_RETAIN_SECONDS"),
    "arp": ("IP_LOCATOR_ARP_FRESH_SECONDS", "IP_LOCATOR_ARP_RETAIN_SECONDS"),
    "mac": ("IP_LOCATOR_MAC_FRESH_SECONDS", "IP_LOCATOR_MAC_RETAIN_SECONDS"),
    "result": ("IP_LOCATOR_RESULT_FRESH_SECONDS", "IP_LOCATOR_RESULT_RETAIN_SECONDS"),
    "subnet": ("IP_LOCATOR_SUBNET_FRESH_SECONDS", "IP_LOCATOR_SUBNET_RETAIN_SECONDS"),
    "topology": ("IP_LOCATOR_TOPOLOGY_FRESH_SECONDS", "IP_LOCATOR_TOPOLOGY_RETAIN_SECONDS"),
    "negative": ("IP_LOCATOR_NEGATIVE_CACHE_SECONDS", "IP_LOCATOR_NEGATIVE_CACHE_SECONDS"),
}


def _parse_timestamp(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        for fmt in _UTC_FORMATS:
            try:
                return datetime.strptime(raw, fmt).timestamp()
            except (TypeError, ValueError, OverflowError):
                continue
    return None


def _safe_component(value: Any) -> str:
    """Return a bounded key component without accepting arbitrary key syntax."""

    cleaned = _SAFE_COMPONENT.sub("_", str(value or "").strip())
    return cleaned[:256] or "unknown"


class IPLocatorCacheService:
    """Fault-isolated, namespaced Redis adapter used by locator workers.

    All operations are best effort.  A Redis connection or command failure is
    converted to ``None``/``False`` and opens a short circuit.  Callers can
    continue with PostgreSQL facts and the normal locator task semantics.
    """

    def __init__(self, settings_obj: Any = settings, client: Any = None) -> None:
        self.settings = settings_obj
        self.namespace = str(getattr(settings_obj, "IP_LOCATOR_REDIS_NAMESPACE", "") or "").strip().strip(":")
        self.backend = str(getattr(settings_obj, "IP_LOCATOR_CACHE_BACKEND", "redis") or "redis").strip().lower()
        self._client = client
        self._client_factory = None
        self._state_lock = threading.RLock()
        self._last_failure_at = 0.0
        self._last_error_kind: str | None = None
        self._last_checked_at = 0.0
        self._last_latency_ms: float | None = None

        if self._client is None and self.backend == "redis" and redis is not None:
            self._client_factory = self._make_client

    def _make_client(self) -> Any:
        url = str(getattr(self.settings, "REDIS_URL", "") or "").strip()
        if not url:
            return None
        try:
            return redis.Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=float(getattr(self.settings, "IP_LOCATOR_REDIS_CONNECT_TIMEOUT_SECONDS", 1.0)),
                socket_timeout=float(getattr(self.settings, "IP_LOCATOR_REDIS_SOCKET_TIMEOUT_SECONDS", 1.0)),
                health_check_interval=30,
            )
        except Exception as exc:
            self._record_failure(exc)
            return None

    def _get_client(self) -> Any:
        if self.backend != "redis" or redis is None:
            return None
        with self._state_lock:
            if self._circuit_open_locked():
                return None
            if self._client is None and self._client_factory is not None:
                self._client = self._client_factory()
            return self._client

    def _circuit_open_locked(self) -> bool:
        cooldown = max(0.1, float(getattr(self.settings, "IP_LOCATOR_REDIS_FAILURE_COOLDOWN_SECONDS", 30.0)))
        return bool(self._last_failure_at and time.monotonic() - self._last_failure_at < cooldown)

    def _record_failure(self, exc: Exception) -> None:
        # Never include exception text: redis-py errors can echo connection URLs.
        with self._state_lock:
            self._last_failure_at = time.monotonic()
            self._last_error_kind = type(exc).__name__
            self._last_checked_at = time.time()
            self._last_latency_ms = None
        logger.debug("IP locator Redis operation failed (%s)", type(exc).__name__)

    def _record_success(self, latency_ms: float | None = None) -> None:
        with self._state_lock:
            self._last_failure_at = 0.0
            self._last_error_kind = None
            self._last_checked_at = time.time()
            self._last_latency_ms = latency_ms

    @staticmethod
    def scope_hash(scope: Mapping[str, Any] | None = None, **kwargs: Any) -> str:
        """Hash locator context so tenant/site/VRF boundaries are in every key."""

        values: dict[str, Any] = dict(scope or {})
        values.update(kwargs)
        canonical = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]

    def build_key(self, kind: str, *parts: Any) -> str:
        if not self.namespace:
            return ""
        components = [_safe_component(kind), *(_safe_component(part) for part in parts)]
        return f"{self.namespace}:" + ":".join(components)

    # Stable alias for callers that use the shorter key naming.
    key = build_key

    def policy(self, kind: str) -> CachePolicy | None:
        normalized = str(kind or "").strip().lower()
        fields = _POLICY_FIELDS.get(normalized)
        if fields is None:
            return None
        fresh = max(1, int(getattr(self.settings, fields[0], 1)))
        retain = max(fresh, int(getattr(self.settings, fields[1], fresh)))
        return CachePolicy(fresh_seconds=fresh, retain_seconds=retain)

    def ttl_for(
        self,
        kind: str,
        *,
        collected_at: Any = None,
        retain_seconds: int | None = None,
        now: float | None = None,
    ) -> int:
        """Return remaining physical retention TTL, never extending old facts."""

        policy = self.policy(kind)
        if policy is None and retain_seconds is None:
            return 0
        configured = max(1, int(retain_seconds if retain_seconds is not None else policy.retain_seconds))
        collected_ts = _parse_timestamp(collected_at)
        if collected_ts is None:
            return configured
        remaining = configured - ((time.time() if now is None else float(now)) - collected_ts)
        return max(0, int(remaining))

    def fresh_until(self, kind: str, collected_at: Any = None) -> float | None:
        timestamp = _parse_timestamp(collected_at)
        policy = self.policy(kind)
        if timestamp is None or policy is None:
            return None
        return timestamp + policy.fresh_seconds

    def is_fresh(self, kind: str, collected_at: Any = None, *, now: float | None = None) -> bool:
        deadline = self.fresh_until(kind, collected_at)
        return deadline is not None and (time.time() if now is None else float(now)) <= deadline

    def get(self, key: str) -> str | None:
        client = self._get_client()
        if client is None or not key:
            return None
        try:
            value = client.get(key)
            self._record_success()
            return value
        except Exception as exc:
            self._record_failure(exc)
            return None

    def set(self, key: str, value: str, ttl: int) -> bool | None:
        client = self._get_client()
        if client is None or not key or int(ttl) <= 0:
            return None
        try:
            result = client.set(key, value, ex=max(1, int(ttl)))
            self._record_success()
            return bool(result)
        except Exception as exc:
            self._record_failure(exc)
            return None

    def get_json(self, key: str) -> Any | None:
        raw = self.get(key)
        if raw is None:
            return None
        if not isinstance(raw, str):
            return raw
        try:
            return json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            # Corrupt cache data is equivalent to a miss.  Best-effort removal
            # avoids repeatedly parsing the same invalid value.
            self.delete(key)
            return None

    def set_json(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
        *,
        kind: str | None = None,
        collected_at: Any = None,
        retain_seconds: int | None = None,
    ) -> bool | None:
        if ttl is None:
            if kind is None:
                ttl = 0
            else:
                ttl = self.ttl_for(kind, collected_at=collected_at, retain_seconds=retain_seconds)
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        except (TypeError, ValueError):
            return None
        return self.set(key, encoded, int(ttl))

    def delete(self, key: str) -> bool | None:
        client = self._get_client()
        if client is None or not key:
            return None
        try:
            result = client.delete(key)
            self._record_success()
            return bool(result)
        except Exception as exc:
            self._record_failure(exc)
            return None

    def delete_prefix(self, prefix: str, *, batch_size: int = 100) -> int | None:
        """Delete namespaced keys under a prefix using bounded Redis SCAN batches."""
        client = self._get_client()
        selected = str(prefix or "")
        if (
            client is None
            or not selected
            or not self.namespace
            or not selected.startswith(f"{self.namespace}:")
        ):
            return None
        scanner = getattr(client, "scan_iter", None)
        if not callable(scanner):
            return None
        count = max(1, min(1000, int(batch_size)))
        removed = 0
        batch: list[Any] = []
        try:
            for key in scanner(match=f"{selected}*", count=count):
                batch.append(key)
                if len(batch) >= count:
                    removed += int(client.delete(*batch) or 0)
                    batch.clear()
            if batch:
                removed += int(client.delete(*batch) or 0)
            self._record_success()
            return removed
        except Exception as exc:
            self._record_failure(exc)
            return None

    def acquire_lock(self, key: str, *, ttl: int = 20, token: str | None = None) -> str | None:
        """Acquire a short single-flight lock without exposing lock contents."""
        client = self._get_client()
        if client is None or not key:
            return None
        value = token or hashlib.sha256(f"{time.time_ns()}:{threading.get_ident()}".encode()).hexdigest()
        try:
            acquired = client.set(key, value, nx=True, ex=max(1, int(ttl)))
            self._record_success()
            return value if acquired else None
        except Exception as exc:
            self._record_failure(exc)
            return None

    def release_lock(self, key: str, token: str) -> bool | None:
        """Release only a lock owned by this caller."""
        client = self._get_client()
        if client is None or not key or not token:
            return None
        try:
            # Redis Lua keeps GET+DEL atomic.  The fallback is useful for
            # small test doubles and Redis-compatible services without eval.
            evaluator = getattr(client, "eval", None)
            if callable(evaluator):
                result = evaluator(
                    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
                    1,
                    key,
                    token,
                )
            elif client.get(key) == token:
                result = client.delete(key)
            else:
                result = 0
            self._record_success()
            return bool(result)
        except Exception as exc:
            self._record_failure(exc)
            return None

    def ping(self) -> bool | None:
        client = self._get_client()
        if client is None:
            return None
        started = time.monotonic()
        try:
            result = bool(client.ping())
            self._record_success((time.monotonic() - started) * 1000)
            return result
        except Exception as exc:
            self._record_failure(exc)
            return None

    def health_summary(self, *, probe: bool = True) -> dict[str, Any]:
        """Return a safe operational summary without URL, username or password."""

        url = str(getattr(self.settings, "REDIS_URL", "") or "").strip()
        try:
            parsed = urlsplit(url) if url else None
        except ValueError:
            # Malformed endpoint values are reported as unavailable without
            # echoing the value or allowing a health page to fail.
            parsed = None
        configured = self.backend == "redis" and bool(url) and bool(self.namespace)
        with self._state_lock:
            circuit_open = self._circuit_open_locked()
            last_error_kind = self._last_error_kind
            checked_at = self._last_checked_at
            latency_ms = self._last_latency_ms
        result: dict[str, Any] = {
            "backend": self.backend,
            "configured": configured,
            "namespace": self.namespace,
            "status": "disabled" if self.backend != "redis" else ("configured_unverified" if configured else "not_configured"),
            "available": False,
            "degraded": self.backend == "redis",
            "host": self._host_from_url(parsed),
            "port": self._port_from_url(parsed),
            "db": self._database_from_url(parsed),
            "tls": bool(parsed and parsed.scheme.lower() == "rediss"),
            "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
            "checked_at": datetime.fromtimestamp(checked_at, timezone.utc).isoformat() if checked_at else None,
            "error_kind": last_error_kind,
        }
        if self.backend != "redis":
            result["degraded"] = False
            return result
        if not configured:
            return result
        if circuit_open:
            result.update({"status": "cooldown", "error_kind": last_error_kind})
            return result
        if probe:
            healthy = self.ping()
            result["available"] = healthy is True
            result["degraded"] = healthy is not True
            result["status"] = "healthy" if healthy is True else "degraded"
            with self._state_lock:
                result["latency_ms"] = round(self._last_latency_ms, 2) if self._last_latency_ms is not None else None
                result["checked_at"] = datetime.fromtimestamp(self._last_checked_at, timezone.utc).isoformat() if self._last_checked_at else None
                result["error_kind"] = self._last_error_kind
        return result

    @staticmethod
    def _database_from_url(parsed: Any) -> int | None:
        if parsed is None:
            return None
        try:
            return int((parsed.path or "/0").strip("/") or 0)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _port_from_url(parsed: Any) -> int | None:
        if parsed is None:
            return None
        try:
            return parsed.port
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _host_from_url(parsed: Any) -> str | None:
        if parsed is None:
            return None
        try:
            return parsed.hostname
        except (TypeError, ValueError):
            return None

    async def aget_json(self, key: str) -> Any | None:
        return await asyncio.to_thread(self.get_json, key)

    async def aset_json(self, key: str, value: Any, ttl: int | None = None, **kwargs: Any) -> bool | None:
        return await asyncio.to_thread(self.set_json, key, value, ttl, **kwargs)

    async def ahealth_summary(self, *, probe: bool = True) -> dict[str, Any]:
        return await asyncio.to_thread(self.health_summary, probe=probe)

    def close(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            try:
                close = getattr(client, "close", None)
                if callable(close):
                    close()
            except Exception as exc:
                logger.debug("IP locator Redis client close failed (%s)", type(exc).__name__)


_SERVICE_LOCK = threading.Lock()
_SERVICE: IPLocatorCacheService | None = None


def get_locator_cache() -> IPLocatorCacheService:
    """Return the process-local adapter; Redis itself remains shared."""

    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = IPLocatorCacheService()
        return _SERVICE


def reset_locator_cache() -> None:
    """Close and forget the singleton (used by focused tests and shutdown)."""

    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is not None:
            _SERVICE.close()
        _SERVICE = None


__all__ = [
    "CachePolicy",
    "IPLocatorCacheService",
    "get_locator_cache",
    "reset_locator_cache",
]
