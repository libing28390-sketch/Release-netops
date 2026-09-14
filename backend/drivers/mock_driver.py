import time
import asyncio
from typing import List, Dict, Any
from .base import BaseDriver, CommandResult

class MockDriver(BaseDriver):
    """用于演示和测试的模拟驱动"""
    
    def connect(self):
        # 模拟连接延迟
        time.sleep(0.5)
        pass

    def disconnect(self):
        pass

    def send_command(self, command: str) -> CommandResult:
        time.sleep(0.2)
        return CommandResult(
            success=True,
            output=f"[Mock Output for {self.platform}] Received: {command}\nConfiguration is valid.",
            hostname=self.device_info.get('hostname', 'MockDevice'),
            command=command,
            execution_time=0.2
        )

    def send_config(self, configs: List[str]) -> CommandResult:
        time.sleep(0.5)
        return CommandResult(
            success=True,
            output=f"[Mock Config] Applied {len(configs)} lines successfully.\n" + "\n".join([f"OK: {c}" for c in configs]),
            hostname=self.device_info.get('hostname', 'MockDevice'),
            command="\n".join(configs),
            execution_time=0.5
        )
