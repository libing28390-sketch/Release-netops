"""Typed, tenant-scoped registry for read-only AI tools."""

from __future__ import annotations

import inspect
import time
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError

from ai.security.gateway import ai_security_gateway
from ai.tools.read_only_tools import (
    tool_compare_config,
    tool_find_ip_location,
    tool_get_active_alarms,
    tool_get_arp_entry,
    tool_get_asset,
    tool_get_config_diff,
    tool_get_device_status,
    tool_get_device_neighbors,
    tool_get_lldp_neighbors,
    tool_get_mac_entry,
    tool_get_running_config,
    tool_search_ip,
    tool_search_mac,
)
from ai.tools.risk import risk_engine
from ai.services.metrics import ai_metrics


class SearchIPArgs(BaseModel):
    ip: str


class SearchMACArgs(BaseModel):
    mac: str


class DeviceArgs(BaseModel):
    device_id: str


class OptionalDeviceArgs(BaseModel):
    device_id: str | None = None


class OptionalDeviceLookupArgs(BaseModel):
    device_id: str | None = None


class ARPArgs(BaseModel):
    ip: str | None = None
    device_id: str | None = None


class MACArgs(BaseModel):
    mac: str
    device_id: str | None = None


class ConfigCompareArgs(BaseModel):
    device_id: str
    before_snapshot_id: str | None = None
    after_snapshot_id: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    display_name: str
    description: str
    category: str
    risk_level: str
    handler: Callable[..., Any]
    input_model: Type[BaseModel]
    permission_code: str = "ai.assistant"
    read_only: bool = True
    require_confirmation: bool = False
    timeout_seconds: float = 8.0


class ToolRegistry:
    """Central catalogue with schema, policy and safe-result enforcement."""

    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}
        self._concurrency = threading.BoundedSemaphore(8)
        self._seed_builtin_tools()

    def _seed_builtin_tools(self) -> None:
        self.register_tool("search_ip", "查询 IP 地址", "Search an IP in the tenant CMDB and ARP evidence.", "Asset", "R0", tool_search_ip, SearchIPArgs)
        self.register_tool("search_mac", "查询 MAC 地址", "Search a MAC in tenant switching evidence.", "Asset", "R0", tool_search_mac, SearchMACArgs)
        self.register_tool("get_neighbors", "获取 LLDP 拓扑邻居", "Read observed LLDP topology neighbors for one device.", "Topology", "R0", tool_get_device_neighbors, DeviceArgs)
        self.register_tool("get_active_alarms", "获取活动告警", "Read active alarms for one tenant/device.", "Alarm", "R0", tool_get_active_alarms, OptionalDeviceArgs)
        self.register_tool("get_config_diff", "获取配置 Diff", "Read a redacted configuration diff; never returns a raw config.", "Config", "R0", tool_get_config_diff, DeviceArgs)
        self.register_tool("get_asset", "查询资产", "Read a tenant-scoped CMDB asset projection.", "Asset", "R0", tool_get_asset, DeviceArgs)
        self.register_tool("get_device_status", "查询设备状态", "Read device and collector health without credentials.", "Health", "R0", tool_get_device_status, DeviceArgs)
        self.register_tool("get_arp_entry", "查询 ARP", "Read ARP evidence; never infer a physical edge from ARP.", "IPAM", "R0", tool_get_arp_entry, ARPArgs)
        self.register_tool("get_mac_entry", "查询 MAC", "Read MAC-table endpoint evidence.", "IPAM", "R0", tool_get_mac_entry, MACArgs)
        self.register_tool("get_lldp_neighbors", "查询 LLDP 邻居", "Read physical LLDP/CDP observations.", "Topology", "R0", tool_get_lldp_neighbors, DeviceArgs)
        self.register_tool("find_ip_location", "定位 IP", "Run deterministic IP to ARP/MAC/LLDP location tracing.", "IPAM", "R0", tool_find_ip_location, SearchIPArgs)
        self.register_tool("get_running_config", "查询配置快照", "Read configuration snapshot metadata only; raw config is unavailable to the agent.", "Config", "R0", tool_get_running_config, DeviceArgs)
        self.register_tool("compare_config", "比较配置", "Compare safe configuration snapshot metadata and hashes.", "Config", "R0", tool_compare_config, ConfigCompareArgs)

    def register_tool(
        self,
        name: str,
        display_name: str,
        description: str,
        category: str,
        risk_level: str,
        handler: Callable[..., Any],
        input_model: Type[BaseModel],
        *,
        permission_code: str = "ai.assistant",
        read_only: bool = True,
        require_confirmation: bool = False,
    ) -> None:
        if not read_only:
            raise ValueError("AI agent registry is read-only in V1")
        self._tools[name] = ToolSpec(
            name=name,
            display_name=display_name,
            description=description,
            category=category,
            risk_level=risk_level,
            handler=handler,
            input_model=input_model,
            permission_code=permission_code,
            read_only=read_only,
            require_confirmation=require_confirmation,
        )

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "display_name": spec.display_name,
                "description": spec.description,
                "category": spec.category,
                "risk_level": spec.risk_level,
                "read_only": spec.read_only,
                "require_confirmation": spec.require_confirmation,
                "permission_code": spec.permission_code,
                "input_schema": spec.input_model.model_json_schema(),
                "timeout_seconds": spec.timeout_seconds,
            }
            for spec in self._tools.values()
        ]

    def execute_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        *,
        tenant_id: str = "tenant-default",
        user_id: str | None = None,
        permissions: set[str] | None = None,
        task_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Dict[str, Any]:
        spec = self._tools.get(name)
        if not spec:
            ai_metrics.tool_finished(name, status="not_found")
            return {"success": False, "error_code": "TOOL_NOT_FOUND"}
        if not spec.read_only or not risk_engine.is_executable_by_agent(spec.risk_level):
            ai_metrics.tool_finished(name, status="blocked")
            return {"success": False, "error_code": "TOOL_POLICY_BLOCKED"}
        if permissions is not None and spec.permission_code not in permissions and "*" not in permissions:
            ai_metrics.tool_finished(name, status="denied")
            return {"success": False, "error_code": "TOOL_PERMISSION_DENIED"}

        try:
            validated = spec.input_model.model_validate(arguments or {})
        except ValidationError:
            ai_metrics.tool_finished(name, status="invalid")
            return {"success": False, "error_code": "TOOL_ARGUMENTS_INVALID"}
        safe_args = validated.model_dump()
        started = time.perf_counter()
        if not self._concurrency.acquire(timeout=max(0.1, float(timeout_seconds or spec.timeout_seconds))):
            ai_metrics.tool_finished(name, status="busy")
            return {"success": False, "error_code": "TOOL_CONCURRENCY_LIMIT"}
        try:
            def invoke():
                output = spec.handler(**safe_args, tenant_id=tenant_id)
                if inspect.isawaitable(output):
                    return {"__async__": True}
                return output
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(invoke)
                try:
                    output = future.result(timeout=max(0.1, float(timeout_seconds or spec.timeout_seconds)))
                except FutureTimeoutError:
                    future.cancel()
                    ai_metrics.tool_finished(name, status="timeout")
                    return {"success": False, "error_code": "TOOL_TIMEOUT", "duration_ms": int((time.perf_counter() - started) * 1000)}
            if isinstance(output, dict) and output.get("__async__"):
                return {"success": False, "error_code": "ASYNC_TOOL_REQUIRES_ASYNC_RUNNER"}
            safe_output = ai_security_gateway.safe_tool_result(output)
            result = {
                "success": True,
                "tool_name": name,
                "protocol_version": "nxa.tool.v1",
                "output": safe_output,
                "audit": {"task_id": task_id, "purpose": spec.description, "status": "success", "duration_ms": int((time.perf_counter() - started) * 1000), "read_only": True},
            }
            ai_metrics.tool_finished(name, status="success")
            return result
        except Exception:
            # Do not return exception strings: SQL/SSH/provider errors can
            # contain credentials or raw device output.
            ai_metrics.tool_finished(name, status="error")
            return {"success": False, "error_code": "TOOL_EXECUTION_FAILED"}
        finally:
            self._concurrency.release()


tool_registry = ToolRegistry()
