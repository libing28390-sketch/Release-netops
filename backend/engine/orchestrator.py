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
            platform = str(device.get("platform") or "").lower()
            category = str(device.get("device_category") or "").lower()
            asset_type = device.get("asset_type")
            if not asset_type:
                if any(t in platform for t in ("ubuntu", "linux", "centos", "debian", "redhat", "server")) or "server" in category:
                    asset_type = "server"
                else:
                    asset_type = "network"
            driver = DriverRegistry.get_driver(asset_type, device)
            
            # 执行
            res = driver.execute(ExecutionMode(mode.lower()), content, **kwargs)
            
            # 注入审计字段
            res["task_id"] = task_id
            res["mode"] = mode
            if "device" not in res:
                res["device"] = device.get("ip_address") or device.get("ip")
            duration = time.perf_counter() - start_time
            if "duration" not in res:
                res["duration"] = duration
                
            try:
                from core.metrics import metrics_registry
                metrics_registry.record_ssh(duration, res.get("success", False))
            except Exception:
                pass
            return res
        except Exception as e:
            duration = time.perf_counter() - start_time
            try:
                from core.metrics import metrics_registry
                metrics_registry.record_ssh(duration, False)
            except Exception:
                pass
            return {
                "success": False, "stderr": str(e), "device": device.get("ip_address"),
                "task_id": task_id, "mode": mode, "duration": duration
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

class TelemetryOrchestrator:
    """
    A/B Dual Loops Telemetry Scheduler
    """
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, 'initialized'): return
        self.a_loop_task = None
        self.b_loop_task = None
        self.initialized = True

    async def a_loop(self):
        """A-Loop: 高频任务 (15s) - Ping 探活及接口状态 (ifOperStatus) 检测"""
        from services.background_monitor_service import process_device_fast, _db_quick
        import asyncio
        import os
        from database import DB_PATH
        import sys

        logger.info("[Orchestrator] Starting A-Loop (High-Frequency)")
        monitor_concurrency = 20 if sys.platform != 'win32' else 2
        sem = asyncio.Semaphore(monitor_concurrency)
        
        while True:
            try:
                if os.path.exists(DB_PATH):
                    devices = _db_quick(
                        "SELECT * FROM devices WHERE ip_address IS NOT NULL AND ip_address != ''",
                        fetchall=True,
                    )
                    async def bounded_fast(d):
                        async with sem:
                            await process_device_fast(d)
                    
                    await asyncio.gather(*(bounded_fast(d) for d in devices))
            except Exception as e:
                logger.error(f"[Orchestrator A-Loop] Error: {e}")
            await asyncio.sleep(15)

    async def b_loop(self):
        """B-Loop: 中低频任务 (60s+) - CPU/内存/硬件环境/接口全量性能数据"""
        from services.background_monitor_service import process_device_slow, _run_telemetry_maintenance, sync_lldp_neighbor_alerts, _db_quick
        import asyncio
        import os
        from database import DB_PATH
        import sys

        logger.info("[Orchestrator] Starting B-Loop (Low-Frequency)")
        monitor_concurrency = 20 if sys.platform != 'win32' else 2
        sem = asyncio.Semaphore(monitor_concurrency)
        maintenance_counter = 0

        while True:
            try:
                if os.path.exists(DB_PATH):
                    devices = _db_quick("SELECT * FROM devices WHERE status = 'online'", fetchall=True)
                    async def bounded_slow(d):
                        async with sem:
                            await process_device_slow(d)
                            
                    await asyncio.gather(*(bounded_slow(d) for d in devices))
                    
                    maintenance_counter += 1
                    if maintenance_counter >= 12: # Run ~every 12 mins
                        maintenance_counter = 0
                        _run_telemetry_maintenance()
                        
                    sync_lldp_neighbor_alerts()
            except Exception as e:
                logger.error(f"[Orchestrator B-Loop] Error: {e}")
            await asyncio.sleep(60)

    def start_loops(self):
        import asyncio
        if not self.a_loop_task:
            self.a_loop_task = asyncio.create_task(self.a_loop())
        if not self.b_loop_task:
            self.b_loop_task = asyncio.create_task(self.b_loop())

    def stop_loops(self):
        if self.a_loop_task:
            self.a_loop_task.cancel()
            self.a_loop_task = None
        if self.b_loop_task:
            self.b_loop_task.cancel()
            self.b_loop_task = None

def get_telemetry_orchestrator() -> TelemetryOrchestrator:
    return TelemetryOrchestrator()
