import logging
import threading
from typing import Any, Dict

from services.connection_profile import resolve_ssh_port

logger = logging.getLogger("engine.pool")


class ConnectionPool:
    """Singleton SSH connection pool to reduce repeated connection churn."""

    _instance = None
    _lock = threading.Lock()
    _pool: Dict[str, Any] = {}

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
        return self._pool.get(key)

    def set_connection(self, device_info: Dict[str, Any], conn: Any):
        key = self._get_key(device_info)
        self._pool[key] = conn

    def close_all(self):
        """Close all pooled connections during shutdown."""
        for _, conn in self._pool.items():
            try:
                if hasattr(conn, "disconnect"):
                    conn.disconnect()
                elif hasattr(conn, "close"):
                    conn.close()
            except Exception:
                pass
        self._pool.clear()
