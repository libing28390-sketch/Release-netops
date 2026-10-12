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
            from services.network_access_limiter import get_network_access_limiter
            limiter = get_network_access_limiter()
            with limiter.ssh(device, operation=f"automation:{mode}"):
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
    OFFLINE_FAST_PROBE_BASE_SECONDS = 60
    OFFLINE_FAST_PROBE_MAX_SECONDS = 300
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, 'initialized'): return
        self.a_loop_task = None
        self.b_loop_task = None
        self.snmp_hardware_loop_task = None
        self.snmp_hardware_discovery_loop_task = None
        self._offline_fast_probe_next_at = {}
        self._offline_fast_probe_failures = {}
        self.initialized = True

    def _should_probe_fast_device(self, device, *, now_monotonic=None) -> bool:
        device_id = str(device.get("id") or "")
        status = str(device.get("status") or "").strip().lower()
        if not device_id:
            return True
        if status != "offline":
            self._offline_fast_probe_next_at.pop(device_id, None)
            self._offline_fast_probe_failures.pop(device_id, None)
            return True

        next_probe_at = self._offline_fast_probe_next_at.get(device_id)
        now = time.monotonic() if now_monotonic is None else float(now_monotonic)
        return next_probe_at is None or now >= next_probe_at

    def _record_fast_probe_completed(self, device_id, *, reachable, now_monotonic=None) -> None:
        normalized_id = str(device_id or "")
        if not normalized_id:
            return
        if reachable:
            self._offline_fast_probe_next_at.pop(normalized_id, None)
            self._offline_fast_probe_failures.pop(normalized_id, None)
            return

        failures = self._offline_fast_probe_failures.get(normalized_id, 0) + 1
        self._offline_fast_probe_failures[normalized_id] = failures
        delay = self.OFFLINE_FAST_PROBE_BASE_SECONDS
        for _ in range(failures - 1):
            if delay >= self.OFFLINE_FAST_PROBE_MAX_SECONDS:
                break
            delay = min(delay * 2, self.OFFLINE_FAST_PROBE_MAX_SECONDS)
        now = time.monotonic() if now_monotonic is None else float(now_monotonic)
        self._offline_fast_probe_next_at[normalized_id] = now + delay

    async def a_loop(self):
        """A-Loop: 高频任务 (15s) - Ping 探活及接口状态 (ifOperStatus) 检测"""
        from services.background_monitor_service import process_device_fast, _as_dict, _db_quick
        import asyncio
        import sys

        logger.info("[Orchestrator] Starting A-Loop (High-Frequency)")
        monitor_concurrency = 20 if sys.platform != 'win32' else 2
        sem = asyncio.Semaphore(monitor_concurrency)
        
        while True:
            try:
                # Always query through the configured PostgreSQL adapter.
                devices = await asyncio.to_thread(
                    _db_quick,
                    "SELECT * FROM devices WHERE ip_address IS NOT NULL AND ip_address != ''",
                    fetchall=True,
                )
                devices = [_as_dict(device) for device in devices]
                current_device_ids = {str(device.get("id") or "") for device in devices}
                self._offline_fast_probe_next_at = {
                    device_id: next_probe_at
                    for device_id, next_probe_at in self._offline_fast_probe_next_at.items()
                    if device_id in current_device_ids
                }
                self._offline_fast_probe_failures = {
                    device_id: failures
                    for device_id, failures in self._offline_fast_probe_failures.items()
                    if device_id in current_device_ids
                }
                async def bounded_fast(d):
                    device_id = str(d.get("id") or "")
                    if not self._should_probe_fast_device(d):
                        return
                    async with sem:
                        reachable = await process_device_fast(d)
                    self._record_fast_probe_completed(device_id, reachable=bool(reachable))

                await asyncio.gather(*(bounded_fast(d) for d in devices))
            except Exception as e:
                logger.error(f"[Orchestrator A-Loop] Error: {e}")
            await asyncio.sleep(15)

    async def b_loop(self):
        """B-Loop: 中低频任务 (60s+) - CPU/内存/硬件环境/接口全量性能数据"""
        from services.background_monitor_service import (
            process_device_slow,
            _run_monitoring_sync_work,
            _run_telemetry_maintenance,
            sync_lldp_neighbor_alerts,
            _db_quick,
        )
        import asyncio
        import sys

        logger.info("[Orchestrator] Starting B-Loop (Low-Frequency)")
        monitor_concurrency = 20 if sys.platform != 'win32' else 2
        sem = asyncio.Semaphore(monitor_concurrency)
        maintenance_counter = 0
        # Cycle 0 performs the initial metadata/protocol pass. Later cycles
        # honor the role profile instead of forcing CLI collection every minute.
        slow_cycle_tick = 0

        while True:
            try:
                # As in the A-Loop, PostgreSQL is authoritative.
                devices = await asyncio.to_thread(
                    _db_quick,
                    "SELECT * FROM devices WHERE status = 'online'",
                    fetchall=True,
                )
                current_slow_cycle = slow_cycle_tick
                slow_cycle_tick += 1
                async def bounded_slow(d):
                    async with sem:
                        await process_device_slow(d, cycle_tick=current_slow_cycle)

                await asyncio.gather(*(bounded_slow(d) for d in devices))

                maintenance_counter += 1
                if maintenance_counter >= 12: # Run ~every 12 mins
                    maintenance_counter = 0
                    await asyncio.to_thread(_run_telemetry_maintenance)
                    # Reclaim idle SSH sessions independently of collector
                    # success so a failed device cannot leak a login session.
                    from engine.pool import ConnectionPool
                    ConnectionPool().cleanup()

                await _run_monitoring_sync_work(sync_lldp_neighbor_alerts)
            except Exception as e:
                logger.error(f"[Orchestrator B-Loop] Error: {e}")
            await asyncio.sleep(60)

    async def snmp_hardware_loop(self):
        """Sample discovered OIDs without waiting for full discovery walks."""
        await self._run_snmp_hardware_loop(discovery_only=False)

    async def snmp_hardware_discovery_loop(self):
        """Refresh rule-derived inventory independently of frequent samples."""
        await self._run_snmp_hardware_loop(discovery_only=True)

    async def _run_snmp_hardware_loop(self, *, discovery_only: bool):
        import asyncio

        operation = "discovery" if discovery_only else "sampling"
        logger.info("[Orchestrator] Starting LibreNMS-rule SNMP %s loop", operation)
        concurrency = asyncio.Semaphore(2 if discovery_only else 4)
        tick_seconds = 60 if discovery_only else 10
        loop = asyncio.get_running_loop()
        while True:
            cycle_started = loop.time()
            try:
                from services.background_monitor_service import _db_quick
                from services.snmp_hardware_poller_service import collect_device_hardware

                devices = await asyncio.to_thread(
                    _db_quick,
                    """
                    SELECT d.*, COALESCE(pa.asset_type, '') AS asset_type
                      FROM devices AS d
                      LEFT JOIN physical_assets AS pa ON pa.id = d.asset_id
                     WHERE d.status = 'online'
                       AND d.ip_address IS NOT NULL AND d.ip_address <> ''
                     ORDER BY d.id
                    """,
                    fetchall=True,
                )

                async def collect_one(device):
                    async with concurrency:
                        try:
                            return await collect_device_hardware(
                                device, discovery_only=discovery_only, poll_only=not discovery_only,
                            )
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            device_id = device.get("id") if isinstance(device, dict) else "unknown"
                            logger.warning(
                                "LibreNMS-rule SNMP %s failed for device %s (%s)",
                                operation,
                                device_id,
                                type(exc).__name__,
                            )
                            return {"status": "failed"}

                await asyncio.gather(*(collect_one(device) for device in devices or []))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("LibreNMS-rule SNMP %s cycle failed: %s", operation, type(exc).__name__)
            # Account for execution time instead of adding a fixed sleep to
            # every cycle. Discovery has its own semaphore and task, so it
            # cannot block a device's otherwise healthy sampling schedule.
            await asyncio.sleep(max(0.1, tick_seconds - (loop.time() - cycle_started)))

    def start_loops(self):
        import asyncio
        if not self.a_loop_task:
            self.a_loop_task = asyncio.create_task(self.a_loop())
        if not self.b_loop_task:
            self.b_loop_task = asyncio.create_task(self.b_loop())
        if not self.snmp_hardware_loop_task:
            self.snmp_hardware_loop_task = asyncio.create_task(self.snmp_hardware_loop())
        if not self.snmp_hardware_discovery_loop_task:
            self.snmp_hardware_discovery_loop_task = asyncio.create_task(self.snmp_hardware_discovery_loop())

    def stop_loops(self):
        if self.a_loop_task:
            self.a_loop_task.cancel()
            self.a_loop_task = None
        if self.b_loop_task:
            self.b_loop_task.cancel()
            self.b_loop_task = None
        if self.snmp_hardware_loop_task:
            self.snmp_hardware_loop_task.cancel()
            self.snmp_hardware_loop_task = None
        if self.snmp_hardware_discovery_loop_task:
            self.snmp_hardware_discovery_loop_task.cancel()
            self.snmp_hardware_discovery_loop_task = None

def get_telemetry_orchestrator() -> TelemetryOrchestrator:
    return TelemetryOrchestrator()
