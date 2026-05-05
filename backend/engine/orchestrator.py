import time
import uuid
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional
from .registry import DriverRegistry
from .base import ExecutionMode, ExecutionResult

logger = logging.getLogger("engine.orchestrator")

class ExecutionOrchestrator:
    """
    并发执行编排器 (Execution-as-a-Service 核心)
    """
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, max_workers: int = 50):
        if hasattr(self, 'initialized'): return
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="netops-exec")
        self.initialized = True

    def execute_single(self, device: Dict[str, Any], mode: str, content: Any, 
                       task_id: str = None, **kwargs) -> Dict[str, Any]:
        """单点执行封装"""
        start_time = time.perf_counter()
        task_id = task_id or f"task-{uuid.uuid4().hex[:8]}"
        
        try:
            asset_type = device.get("asset_type") or ("server" if device.get("platform") in ("ubuntu", "linux", "centos") else "network")
            driver = DriverRegistry.get_driver(asset_type, device)
            
            # 执行
            res = driver.execute(ExecutionMode(mode.lower()), content, **kwargs)
            
            # 注入审计字段
            res["task_id"] = task_id
            res["mode"] = mode
            if "device" not in res:
                res["device"] = device.get("ip_address") or device.get("ip")
            if "duration" not in res:
                res["duration"] = time.perf_counter() - start_time
                
            return res
        except Exception as e:
            return {
                "success": False, "stderr": str(e), "device": device.get("ip_address"),
                "task_id": task_id, "mode": mode, "duration": time.perf_counter() - start_time
            }

    def batch_execute(self, devices: List[Dict[str, Any]], mode: str, content: Any, 
                      **kwargs) -> List[Dict[str, Any]]:
        """批量并发执行模型"""
        batch_id = f"batch-{uuid.uuid4().hex[:8]}"
        
        def _exec_task(d):
            return self.execute_single(d, mode, content, task_id=batch_id, **kwargs)

        results = list(self.executor.map(_exec_task, devices))
        return results

def get_orchestrator() -> ExecutionOrchestrator:
    return ExecutionOrchestrator()
