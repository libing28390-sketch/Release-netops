import threading
import logging
from typing import Dict, Any

logger = logging.getLogger("engine.pool")

class ConnectionPool:
    """
    单例连接池，防止高频任务导致的 SSH 风暴
    """
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
        # 唯一键：IP + 端口 + 用户名
        ip = device_info.get('ip_address') or device_info.get('ip')
        return f"{ip}:{device_info.get('port', 22)}@{device_info.get('username')}"

    def get_connection(self, device_info: Dict[str, Any]) -> Any:
        key = self._get_key(device_info)
        return self._pool.get(key)

    def set_connection(self, device_info: Dict[str, Any], conn: Any):
        key = self._get_key(device_info)
        self._pool[key] = conn

    def close_all(self):
        """系统关闭时清理"""
        for key, conn in self._pool.items():
            try:
                if hasattr(conn, 'disconnect'):
                    conn.disconnect()
                elif hasattr(conn, 'close'):
                    conn.close()
            except: pass
        self._pool.clear()
