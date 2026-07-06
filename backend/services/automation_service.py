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
        if is_config:
            # Config mode: send all lines as a config set (single transaction)
            result = self.orchestrator.execute_single(device_info, "config", commands)
            return [result]
        else:
            # Command mode: execute each command individually so every output is captured.
            # Joining multiple show commands into one string causes Netmiko to treat them
            # as a single command, resulting in empty or partial output.
            results = []
            for cmd in commands:
                if not cmd.strip():
                    continue
                result = self.orchestrator.execute_single(device_info, "command", cmd)
                results.append(result)
                # Stop on first connection-level failure (auth/timeout) to avoid
                # repeating the same error for every subsequent command.
                if not result.get('success', False):
                    err = result.get('stderr') or result.get('error') or ''
                    is_conn_err = any(k in err.lower() for k in ('connection', 'timeout', 'authentication', 'ssh'))
                    if is_conn_err:
                        break
            return results if results else [{"success": False, "stderr": "No commands provided", "stdout": ""}]

    def test_connectivity(self, ip_address: str, username: str, password: str, platform: str) -> bool:
        device = {
            "ip": ip_address,
            "username": username,
            "password": password,
            "platform": platform,
            "use_pool": False
        }
        category = str(d.get('device_category') or '').lower() if hasattr(d, 'get') else ''
        is_server = any(t in platform.lower() for t in ('linux', 'ubuntu', 'centos', 'debian', 'redhat', 'server')) or 'server' in category
        dummy_cmd = "echo 1" if is_server else "show clock"
        res = self.orchestrator.execute_single(device, "command", dummy_cmd)
        return res.get("success", False)

    def check_connectivity(self, device_info: Dict[str, Any]) -> tuple[bool, str]:
        """
        Used by the quick connect test to return both status and error message.
        """
        device = {
            "ip": device_info.get("ip_address") or device_info.get("ip"),
            "username": device_info.get("username"),
            "password": device_info.get("password"),
            "platform": device_info.get("platform", "cisco_ios"),
            "port": device_info.get("port", 22),
            "driver_type": self.driver_type,
            "use_pool": False
        }
        platform = str(device_info.get("platform") or "").lower()
        category = str(device_info.get('device_category') or '').lower()
        is_server = any(t in platform for t in ('linux', 'ubuntu', 'centos', 'debian', 'redhat', 'server')) or 'server' in category
        dummy_cmd = "echo 1" if is_server else "show clock"
        res = self.orchestrator.execute_single(device, "command", dummy_cmd)
        success = res.get("success", False)
        if success:
            return True, "Connected successfully"
        else:
            error_msg = res.get("stderr") or res.get("error") or "Connection failed"
            return False, error_msg
