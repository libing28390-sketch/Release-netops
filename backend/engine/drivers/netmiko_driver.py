import time
from typing import Dict, Any
from netmiko import ConnectHandler
from .base_driver import BaseDriver
from ..base import Capability, ExecutionMode
from ..pool import ConnectionPool
from ..registry import DriverRegistry

@DriverRegistry.register("network")
class NetmikoDriver(BaseDriver):
    """基于 Netmiko 的网络设备驱动"""
    
    def __init__(self, device_info: Dict[str, Any]):
        super().__init__(device_info)
        # Netmiko 需要具体的 device_type
        self.device_type = self._map_device_type(self.platform)
        self.secret = device_info.get("enable_password") or ""
        self.conn = None
        self.capabilities = {Capability.EXEC_COMMAND, Capability.SEND_CONFIG}

    def _map_device_type(self, platform: str) -> str:
        mapping = {
            'cisco_ios': 'cisco_ios',
            'huawei_vrp': 'huawei',
            'h3c_comware': 'hp_comware',
            'juniper_junos': 'juniper_junos',
            'arista_eos': 'arista_eos',
        }
        return mapping.get(platform, 'cisco_ios')

    def connect(self):
        pool = ConnectionPool()
        existing = pool.get_connection(self.device_info)
        
        if existing and hasattr(existing, 'is_alive') and existing.is_alive():
            self.conn = existing
            return

        device_params = {
            'device_type': self.device_type,
            'host': self.ip,
            'username': self.username,
            'password': self.password,
            'port': self.port,
            'secret': self.secret,
            'timeout': 15,
        }
        self.conn = ConnectHandler(**device_params)
        if self.secret:
            self.conn.enable()
        
        pool.set_connection(self.device_info, self.conn)

    def disconnect(self):
        # 实际不切断，交给 Pool 管理或手动清理
        pass

    def execute(self, mode: ExecutionMode, content: Any, **kwargs) -> Dict[str, Any]:
        start_time = time.perf_counter()
        try:
            self.connect()
            
            if mode == ExecutionMode.COMMAND:
                output = self.conn.send_command(content)
                return {
                    "success": True, "stdout": output, "device": self.ip,
                    "duration": time.perf_counter() - start_time
                }
            
            elif mode == ExecutionMode.CONFIG:
                config_lines = content if isinstance(content, list) else content.splitlines()
                output = self.conn.send_config_set(config_lines)
                return {
                    "success": True, "stdout": output, "device": self.ip,
                    "duration": time.perf_counter() - start_time
                }
            
            return {"success": False, "stderr": f"Mode {mode} not supported", "device": self.ip, "duration": 0}
        except Exception as e:
            return {
                "success": False, "stderr": str(e), "device": self.ip,
                "duration": time.perf_counter() - start_time
            }
