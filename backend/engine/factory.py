from typing import Dict, Any
from .base import ExecutionProvider
from .local import LocalExecutionProvider

class ExecutionEngine:
    """
    Factory class for managing execution providers.
    In the future, this can be extended to return RemoteAgentProvider based on device metadata.
    """
    
    _providers: Dict[str, ExecutionProvider] = {}

    @classmethod
    def get_provider(cls, name: str = "local") -> ExecutionProvider:
        if name not in cls._providers:
            if name == "local":
                cls._providers[name] = LocalExecutionProvider()
            else:
                raise ValueError(f"Unknown execution provider: {name}")
        
        return cls._providers[name]

def get_execution_provider(device_info: Dict[str, Any] = None) -> ExecutionProvider:
    """
    Returns the appropriate execution provider for a device.
    Currently always returns 'local', but ready for 'agent' routing.
    """
    # Logic for routing can be added here
    # e.g., if device_info.get('use_agent'): return ExecutionEngine.get_provider('agent')
    return ExecutionEngine.get_provider("local")
