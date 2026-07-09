import abc
import logging
from typing import Dict, Any, Set
from ..base import Capability, ExecutionMode

logger = logging.getLogger("engine.driver")

class BaseDriver(abc.ABC):
    """驱动基类"""
    def __init__(self, device_info: Dict[str, Any]):
        from services.vault_service import resolve_device_credentials
        from core.crypto import decrypt_credential

        # 优先使用外层（如 scheduler, backup, PAM 等）在调用前根据特权要求显式指定好的凭据
        username = (device_info.get("username") or "").strip()
        raw_password = (device_info.get("password") or "").strip()
        password = decrypt_credential(raw_password) or raw_password

        # 如果外层未传入明确的 username，则使用全局统一支持 Vault 的凭据解析服务
        if not username:
            creds = resolve_device_credentials(device_info)
            username = creds.get("username") or "root"
            password = creds.get("password") or ""

        try:
            port = int(device_info.get("port") or device_info.get("management_port") or 22)
        except Exception:
            port = 22
        
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
