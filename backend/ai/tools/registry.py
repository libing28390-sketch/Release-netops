"""
Nexora Tool Registry - Central Catalog for Agent-Callable Tools
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional
from ai.tools.risk import risk_engine
from ai.tools.read_only_tools import (
    tool_search_ip,
    tool_search_mac,
    tool_get_device_neighbors,
    tool_get_active_alarms,
    tool_get_config_diff,
)


class ToolRegistry:
    """Registry managing tool schemas, risk levels, and execution handlers."""

    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._seed_builtin_tools()

    def _seed_builtin_tools(self):
        self.register_tool(
            name="search_ip",
            display_name="查询 IP 地址",
            description="Searches IP address in CMDB asset database and ARP cache.",
            category="Asset",
            risk_level="R0",
            handler=tool_search_ip,
        )
        self.register_tool(
            name="search_mac",
            display_name="查询 MAC 地址",
            description="Searches MAC address in ARP cache and MAC table.",
            category="Asset",
            risk_level="R0",
            handler=tool_search_mac,
        )
        self.register_tool(
            name="get_neighbors",
            display_name="获取 LLDP 拓扑邻居",
            description="Retrieves LLDP topology neighbors for a target device.",
            category="Topology",
            risk_level="R0",
            handler=tool_get_device_neighbors,
        )
        self.register_tool(
            name="get_active_alarms",
            display_name="获取活动告警",
            description="Retrieves active alarms from Nexora alarm desk.",
            category="Alarm",
            risk_level="R0",
            handler=tool_get_active_alarms,
        )
        self.register_tool(
            name="get_config_diff",
            display_name="获取配置 Diff",
            description="Retrieves latest configuration diff from Nexora Diff Engine.",
            category="Config",
            risk_level="R0",
            handler=tool_get_config_diff,
        )

    def register_tool(
        self,
        name: str,
        display_name: str,
        description: str,
        category: str,
        risk_level: str,
        handler: Callable[..., Any],
    ):
        self._tools[name] = {
            "name": name,
            "display_name": display_name,
            "description": description,
            "category": category,
            "risk_level": risk_level,
            "handler": handler,
        }

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": t["name"],
                "display_name": t["display_name"],
                "description": t["description"],
                "category": t["category"],
                "risk_level": t["risk_level"],
            }
            for t in self._tools.values()
        ]

    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if name not in self._tools:
            return {"success": False, "error": f"Tool '{name}' not found in registry."}
        
        tool = self._tools[name]
        risk_level = tool["risk_level"]
        
        # Enforce Agent Risk Policy
        if not risk_engine.is_executable_by_agent(risk_level):
            return {
                "success": False,
                "error": f"Tool '{name}' with risk level '{risk_level}' requires human approval and cannot be executed automatically by Agent."
            }

        try:
            handler = tool["handler"]
            output = handler(**arguments)
            return {"success": True, "output": output}
        except Exception as exc:
            return {"success": False, "error": str(exc)}


tool_registry = ToolRegistry()
