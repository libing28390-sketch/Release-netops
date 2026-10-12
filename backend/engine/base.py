import time
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

class ExecutionMode(Enum):
    COMMAND = "command"
    SCRIPT = "script"
    CONFIG = "config"

class Capability(Enum):
    EXEC_COMMAND = "exec_command"
    EXEC_SCRIPT = "exec_script"
    SEND_CONFIG = "send_config"
    UPLOAD_FILE = "upload_file"

class ExecutionResult(BaseModel):
    """企业级统一返回结构 (含审计要素)"""
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    device: str
    task_id: Optional[str] = None
    mode: str
    duration: float
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self):
        return self.model_dump()
