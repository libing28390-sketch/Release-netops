from typing import List, Dict, Any
from engine.factory import get_execution_provider
from drivers.base import CommandResult

class AutomationService:
    """
    Business logic layer for automation tasks.
    Now uses ExecutionProvider abstraction to decouple command execution from backend logic.
    """
    
    def __init__(self, driver_type: str = 'netmiko'):
        # For P2 phase, we use the local provider but routed through the new engine
        self.provider = get_execution_provider()

    def execute_commands(self, device_info: Dict[str, Any], commands: List[str], is_config: bool = False) -> List[CommandResult]:
        return self.provider.execute(device_info, commands, is_config)

    def check_connectivity(self, device_info: Dict[str, Any]) -> tuple[bool, str]:
        return self.provider.check_connectivity(device_info)
