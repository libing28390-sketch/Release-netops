import abc
import logging
from typing import Dict, Any, Set
from ..base import Capability, ExecutionMode

logger = logging.getLogger("engine.driver")

class BaseDriver(abc.ABC):
    """驱动基类"""
    def __init__(self, device_info: Dict[str, Any]):
        from core.crypto import resolve_device_credentials
        username, password, port = resolve_device_credentials(device_info)
        
        self.device_info = device_info
        self.ip = device_info.get("ip") or device_info.get("ip_address")
        self.username = username
        self.password = password
        self.port = port
        self.platform = device_info.get("platform", "")
        self.capabilities: Set[Capability] = set()

    def has_capability(self, cap: Capability) -> bool:
        return cap in self.capabilities

    @abc.abstractmethod
    def connect(self):
        pass

    @abc.abstractmethod
    def disconnect(self):
        pass

    @abc.abstractmethod
    def execute(self, mode: ExecutionMode, content: Any, **kwargs) -> Dict[str, Any]:
        """统一执行入口"""
        pass
