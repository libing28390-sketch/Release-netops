from typing import List, Dict, Any
from engine.orchestrator import get_orchestrator
from drivers.base import CommandResult

class AutomationService:
    """
    业务逻辑层，现在通过 Orchestrator 调用 V3 引擎。
    """
    
    def __init__(self, driver_type: str = "netmiko", **_: Any):
        # driver_type is kept for backward compatibility with existing callers.
        self.driver_type = driver_type
        self.orchestrator = get_orchestrator()

    def execute_commands(self, device_info: Dict[str, Any], commands: List[str], is_config: bool = False) -> List[Any]:
        # 为了兼容旧接口，这里循环调用或根据场景封装
        mode = "config" if is_config else "command"
        content = commands if is_config else "\n".join(commands)
        
        result = self.orchestrator.execute_single(device_info, mode, content)
        return [result] # 返回列表以匹配旧接口预期

    def test_connectivity(self, ip_address: str, username: str, password: str, platform: str) -> bool:
        device = {
            "ip": ip_address,
            "username": username,
            "password": password,
            "platform": platform
        }
        res = self.orchestrator.execute_single(device, "command", "exit")
        return res.get("success", False)
