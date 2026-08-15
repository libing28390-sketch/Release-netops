from typing import List, Dict, Any
from engine.orchestrator import get_orchestrator
from drivers.base import CommandResult
from services.connection_profile import resolve_ssh_port

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
        from core.platform_utils import normalize_device_platform
        normalized_platform = normalize_device_platform("", platform)
        device = {
            "ip": ip_address,
            "username": username,
            "password": password,
            "platform": normalized_platform,
            "use_pool": False
        }
        category = ''
        is_server = any(t in normalized_platform.lower() for t in ('linux', 'ubuntu', 'centos', 'debian', 'redhat', 'server')) or 'server' in category
        if is_server:
            dummy_cmd = "echo 1"
        elif 'huawei' in normalized_platform or 'vrp' in normalized_platform:
            dummy_cmd = "display clock"
        elif 'h3c' in normalized_platform or 'comware' in normalized_platform:
            dummy_cmd = "display clock"
        else:
            dummy_cmd = "show clock"
            
        res = self.orchestrator.execute_single(device, "command", dummy_cmd)
        return res.get("success", False)

    def check_connectivity(self, device_info: Dict[str, Any]) -> tuple[bool, str]:
        """
        Used by the quick connect test to return both status and error message.
        """
        from core.platform_utils import normalize_device_platform
        vendor = device_info.get("vendor") or ""
        platform = normalize_device_platform(vendor, device_info.get("platform") or "")
        
        device = {
            "ip": device_info.get("ip_address") or device_info.get("ip"),
            "username": device_info.get("username"),
            "password": device_info.get("password"),
            "platform": platform,
            "port": resolve_ssh_port(device_info),
            "driver_type": self.driver_type,
            "use_pool": False
        }
        category = str(device_info.get('device_category') or '').lower()
        is_server = any(t in platform for t in ('linux', 'ubuntu', 'centos', 'debian', 'redhat', 'server')) or 'server' in category
        if is_server:
            dummy_cmd = "echo 1"
        elif 'huawei' in platform or 'vrp' in platform:
            dummy_cmd = "display clock"
        elif 'h3c' in platform or 'comware' in platform:
            dummy_cmd = "display clock"
        else:
            dummy_cmd = "show clock"
            
        res = self.orchestrator.execute_single(device, "command", dummy_cmd)
        success = res.get("success", False)
        if success:
            return True, "Connected successfully"
        else:
            error_msg = res.get("stderr") or res.get("error") or "Connection failed"
            return False, error_msg
