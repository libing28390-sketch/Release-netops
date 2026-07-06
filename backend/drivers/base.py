from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class CommandResult(BaseModel):
    """统一的命令执行结果结构"""
    success: bool
    output: str
    error: Optional[str] = None
    hostname: str
    command: str
    execution_time: float = 0.0

class BaseDriver(ABC):
    """设备驱动抽象基类"""
    
    def __init__(self, device_info: Dict[str, Any]):
        self.device_info = device_info
        self.host = device_info.get('ip_address')
        self.username = device_info.get('username')
        self.password = device_info.get('password')
        self.port = int(device_info.get('port', 22))
        self.platform = device_info.get('platform')

    @abstractmethod
    def connect(self):
        """建立连接"""
        pass

    @abstractmethod
    def disconnect(self):
        """关闭连接"""
        pass

    @abstractmethod
    def send_command(self, command: str) -> CommandResult:
        """发送单条查询命令"""
        pass

    @abstractmethod
    def send_config(self, configs: List[str]) -> CommandResult:
        """发送配置命令"""
        pass

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
