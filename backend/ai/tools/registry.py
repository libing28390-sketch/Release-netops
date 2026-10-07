"""Typed, tenant-scoped registry for read-only AI tools."""

from __future__ import annotations

import inspect
import time
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel, ConfigDict

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
from ai.schemas.tool import ToolCallPlan
from ai.tools.plan import (
    ToolPlanError,
    build_tool_call_plan,
    tool_confirmation_store,
)
from ai.services.metrics import ai_metrics


class StrictToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SearchIPArgs(StrictToolArgs):
    ip: str


class SearchMACArgs(StrictToolArgs):
    mac: str


class DeviceArgs(StrictToolArgs):
    device_id: str


class OptionalDeviceArgs(StrictToolArgs):
    device_id: str | None = None


class OptionalDeviceLookupArgs(StrictToolArgs):
    device_id: str | None = None


class ARPArgs(StrictToolArgs):
    ip: str | None = None
    device_id: str | None = None


class MACArgs(StrictToolArgs):
    mac: str
    device_id: str | None = None


class ConfigCompareArgs(StrictToolArgs):
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
    supported_vendors: tuple[str, ...] = field(default_factory=tuple)
    supported_platforms: tuple[str, ...] = field(default_factory=tuple)


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
        supported_vendors: tuple[str, ...] = (),
        supported_platforms: tuple[str, ...] = (),
    ) -> None:
        normalized_risk = str(risk_level or "").upper()
        if normalized_risk not in {"R0", "R1", "R2", "R3", "R4"}:
            raise ValueError("invalid tool risk level")
        if not read_only and normalized_risk not in {"R3", "R4"}:
            raise ValueError("write-capable tools must be R3 or R4")
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
            require_confirmation=require_confirmation or not read_only or normalized_risk in {"R3", "R4"},
            supported_vendors=tuple(str(value).strip() for value in supported_vendors if str(value).strip()),
            supported_platforms=tuple(str(value).strip() for value in supported_platforms if str(value).strip()),
        )

    @staticmethod
    def _safe_plan(plan: ToolCallPlan | None) -> dict[str, Any] | None:
        if plan is None:
            return None
        return plan.model_dump(mode="json", exclude={"confirmation_token"})

    def _build_plan(
        self,
        name: str,
        arguments: Dict[str, Any],
        *,
        tenant_id: str,
        user_id: str | None,
        permissions: set[str] | None,
        dry_run: bool,
        change_order_id: str | None,
        device_state: str | None,
        impact_scope: str | None,
        confirmation_token: str | None,
    ) -> tuple[ToolSpec | None, ToolCallPlan | None, dict[str, Any] | None, str | None]:
        spec = self._tools.get(name)
        if not spec:
            return None, None, None, "TOOL_NOT_FOUND"
        if permissions is not None and spec.permission_code not in permissions and "*" not in permissions:
            return spec, None, None, "TOOL_PERMISSION_DENIED"
        try:
            plan, safe_arguments = build_tool_call_plan(
                spec,
                arguments,
                tool_name=name,
                tenant_id=tenant_id,
                user_id=user_id,
                dry_run=dry_run,
                change_order_id=change_order_id,
                device_state=device_state,
                impact_scope=impact_scope,
                confirmation_token=confirmation_token,
            )
        except ToolPlanError as error:
            return spec, None, None, error.code
        return spec, plan, safe_arguments, None

    def plan_tool_call(
        self,
        name: str,
        arguments: Dict[str, Any],
        *,
        tenant_id: str = "tenant-default",
        user_id: str | None = None,
        permissions: set[str] | None = None,
        dry_run: bool = True,
        change_order_id: str | None = None,
        device_state: str | None = None,
        impact_scope: str | None = None,
    ) -> Dict[str, Any]:
        """Validate and return a non-executing plan for UI/audit surfaces."""

        _spec, plan, _safe_arguments, error_code = self._build_plan(
            name,
            arguments,
            tenant_id=tenant_id,
            user_id=user_id,
            permissions=permissions,
            dry_run=dry_run,
            change_order_id=change_order_id,
            device_state=device_state,
            impact_scope=impact_scope,
            confirmation_token=None,
        )
        if error_code:
            ai_metrics.tool_finished(name, status="plan_rejected")
            return {"success": False, "error_code": error_code}
        assert plan is not None
        return {
            "success": True,
            "tool_name": name,
            "protocol_version": "nxa.tool.v1",
            "plan": self._safe_plan(plan),
            "requires_confirmation": plan.requires_confirmation,
            "status": plan.status.value,
        }

    def issue_confirmation_token(
        self,
        name: str,
        arguments: Dict[str, Any],
        *,
        tenant_id: str = "tenant-default",
        user_id: str | None = None,
        permissions: set[str] | None = None,
        change_order_id: str | None = None,
        device_state: str | None = None,
        impact_scope: str | None = None,
    ) -> Dict[str, Any]:
        """Issue a short-lived token bound to the exact high-risk plan."""

        _spec, plan, _safe_arguments, error_code = self._build_plan(
            name,
            arguments,
            tenant_id=tenant_id,
            user_id=user_id,
            permissions=permissions,
            dry_run=True,
            change_order_id=change_order_id,
            device_state=device_state,
            impact_scope=impact_scope,
            confirmation_token=None,
        )
        if error_code:
            return {"success": False, "error_code": error_code}
        assert plan is not None
        if not plan.requires_confirmation:
            return {"success": False, "error_code": "TOOL_CONFIRMATION_NOT_REQUIRED"}
        if not plan.device_state:
            return {"success": False, "error_code": "TOOL_DEVICE_STATE_REQUIRED"}
        if not plan.impact_scope:
            return {"success": False, "error_code": "TOOL_IMPACT_SCOPE_REQUIRED"}
        try:
            token = tool_confirmation_store.issue(plan, tenant_id=tenant_id, user_id=user_id)
        except ToolPlanError as error:
            return {"success": False, "error_code": error.code}
        return {
            "success": True,
            "tool_name": name,
            "protocol_version": "nxa.tool.v1",
            "plan": self._safe_plan(plan),
            "confirmation_token": token,
            "expires_in_seconds": tool_confirmation_store.ttl_seconds,
        }

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
        confirmation_token: str | None = None,
        change_order_id: str | None = None,
        device_state: str | None = None,
        impact_scope: str | None = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        spec, plan, safe_args, error_code = self._build_plan(
            name,
            arguments,
            tenant_id=tenant_id,
            user_id=user_id,
            permissions=permissions,
            dry_run=dry_run,
            change_order_id=change_order_id,
            device_state=device_state,
            impact_scope=impact_scope,
            confirmation_token=confirmation_token,
        )
        if error_code == "TOOL_NOT_FOUND":
            ai_metrics.tool_finished(name, status="not_found")
            return {"success": False, "error_code": error_code}
        if error_code == "TOOL_PERMISSION_DENIED":
            ai_metrics.tool_finished(name, status="denied")
            return {"success": False, "error_code": error_code}
        if error_code or plan is None or safe_args is None or spec is None:
            ai_metrics.tool_finished(name, status="invalid" if error_code == "TOOL_ARGUMENTS_INVALID" else "blocked")
            return {"success": False, "error_code": error_code or "TOOL_POLICY_BLOCKED"}
        if spec.read_only and not risk_engine.is_executable_by_agent(spec.risk_level):
            ai_metrics.tool_finished(name, status="blocked")
            return {"success": False, "error_code": "TOOL_POLICY_BLOCKED", "plan": self._safe_plan(plan)}
        if plan.requires_confirmation:
            if plan.dry_run:
                ai_metrics.tool_finished(name, status="confirmation_required")
                return {
                    "success": False,
                    "error_code": "TOOL_CONFIRMATION_REQUIRED",
                    "plan": self._safe_plan(plan),
                }
            try:
                tool_confirmation_store.consume(
                    plan,
                    confirmation_token,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
            except ToolPlanError as error:
                ai_metrics.tool_finished(name, status="confirmation_invalid")
                return {"success": False, "error_code": error.code, "plan": self._safe_plan(plan)}
        if not spec.read_only and not change_order_id:
            ai_metrics.tool_finished(name, status="blocked")
            return {"success": False, "error_code": "TOOL_CHANGE_ORDER_REQUIRED", "plan": self._safe_plan(plan)}
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
                "plan": self._safe_plan(plan),
                "audit": {"task_id": task_id, "purpose": spec.description, "status": "success", "duration_ms": int((time.perf_counter() - started) * 1000), "read_only": spec.read_only, "risk_level": plan.risk_level.value},
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
