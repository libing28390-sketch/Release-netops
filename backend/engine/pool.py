import logging
import threading
import time
from typing import Any, Dict

from services.connection_profile import resolve_ssh_port

logger = logging.getLogger("engine.pool")


class ConnectionPool:
    """Singleton SSH connection pool to reduce repeated connection churn."""

    _instance = None
    _lock = threading.Lock()
    _pool: Dict[str, Any] = {}
    _last_used: Dict[str, float] = {}

    def __new__(cls):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @staticmethod
    def _get_key(device_info: Dict[str, Any]) -> str:
        ip = device_info.get("ip_address") or device_info.get("ip")
        return f"{ip}:{resolve_ssh_port(device_info)}@{device_info.get('username')}"

    def get_connection(self, device_info: Dict[str, Any]) -> Any:
        key = self._get_key(device_info)
        with self._lock:
            self._cleanup_locked()
            conn = self._pool.get(key)
            if conn is not None:
                self._last_used[key] = time.monotonic()
            return conn

    def set_connection(self, device_info: Dict[str, Any], conn: Any):
        key = self._get_key(device_info)
        with self._lock:
            self._cleanup_locked()
            old = self._pool.get(key)
            if old is not None and old is not conn:
                self._close_connection(old)
            self._pool[key] = conn
            self._last_used[key] = time.monotonic()
            self._enforce_size_locked()

    @staticmethod
    def _close_connection(conn: Any) -> None:
        try:
            if hasattr(conn, "disconnect"):
                conn.disconnect()
            elif hasattr(conn, "close"):
                conn.close()
        except Exception:
            logger.debug("Failed to close pooled connection", exc_info=True)

    @staticmethod
    def _limits() -> tuple[int, int]:
        try:
            from core.config import settings
            idle = max(30, int(settings.NETWORK_POOL_IDLE_SECONDS))
            maximum = max(1, int(settings.NETWORK_POOL_MAX_SIZE))
        except Exception:
            idle, maximum = 300, 100
        return idle, maximum

    def _cleanup_locked(self) -> int:
        idle_seconds, _ = self._limits()
        now = time.monotonic()
        stale = [
            key for key, last_used in self._last_used.items()
            if now - last_used >= idle_seconds
        ]
        for key in stale:
            conn = self._pool.pop(key, None)
            self._last_used.pop(key, None)
            if conn is not None:
                self._close_connection(conn)
        return len(stale)

    def _enforce_size_locked(self) -> None:
        _, maximum = self._limits()
        while len(self._pool) > maximum:
            key = min(self._pool, key=lambda item: self._last_used.get(item, 0.0))
            conn = self._pool.pop(key, None)
            self._last_used.pop(key, None)
            if conn is not None:
                self._close_connection(conn)

    def cleanup(self) -> int:
        """Close sessions idle beyond the configured TTL and return the count."""
        with self._lock:
            return self._cleanup_locked()

    def snapshot(self) -> dict[str, Any]:
        """Return non-sensitive pool state for health/diagnostic endpoints."""
        with self._lock:
            self._cleanup_locked()
            idle_seconds, maximum = self._limits()
            return {
                "active": len(self._pool),
                "max": maximum,
                "idle_timeout_seconds": idle_seconds,
            }

    def close_all(self):
        """Close all pooled connections during shutdown."""
        with self._lock:
            for conn in self._pool.values():
                self._close_connection(conn)
            self._pool.clear()
            self._last_used.clear()
