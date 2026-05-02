from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
from drivers.base import CommandResult

class ExecutionProvider(ABC):
    """
    Abstract base class for execution providers.
    """
    
    @abstractmethod
    def execute(self, device_info: Dict[str, Any], commands: List[str], is_config: bool = False) -> List[CommandResult]:
        pass
        
    @abstractmethod
    def check_connectivity(self, device_info: Dict[str, Any]) -> Tuple[bool, str]:
        pass
