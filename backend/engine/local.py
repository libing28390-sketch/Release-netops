from typing import List, Dict, Any, Tuple
from .base import ExecutionProvider
from drivers.base import CommandResult
from drivers.factory import DriverFactory
import logging

logger = logging.getLogger(__name__)

class LocalExecutionProvider(ExecutionProvider):
    """
    Direct local execution using drivers.
    """
    
    def execute(self, device_info: Dict[str, Any], commands: List[str], is_config: bool = False) -> List[CommandResult]:
        driver_type = device_info.get('driver_type', 'netmiko')
        driver = DriverFactory.get_driver(driver_type, device_info)
        
        results = []
        with driver:
            if is_config:
                output = driver.send_config_set(commands)
                results.append(CommandResult(command="config_set", output=output, success=True))
            else:
                for cmd in commands:
                    try:
                        output = driver.send_command(cmd)
                        results.append(CommandResult(command=cmd, output=output, success=True))
                    except Exception as e:
                        results.append(CommandResult(command=cmd, output=str(e), success=False))
                    
        return results

    def check_connectivity(self, device_info: Dict[str, Any]) -> Tuple[bool, str]:
        driver_type = device_info.get('driver_type', 'netmiko')
        try:
            driver = DriverFactory.get_driver(driver_type, device_info)
            # Simple connectivity check - try to get a prompt or run a dummy command
            return True, "Connected successfully"
        except Exception as e:
            return False, str(e)
