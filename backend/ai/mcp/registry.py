"""MCP-compatible Tool Registry wrapping Nexora's built-in read-only services.

Exposes:
1. Standard MCP tool descriptors (`tools/list`) and invocation (`tools/call`).
2. Dynamic Copilot slash-command catalog (`GET /api/ai/assistant/tools`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ai.tools.read_only_tools import (
    tool_get_active_alarms,
    tool_get_device_neighbors,
    tool_search_ip,
    tool_search_mac,
)
from ai.services.knowledge_service import knowledge_service
from ai.services.web_retrieval import web_retrieval_service
from core.config import settings


@dataclass(frozen=True)
class MCPToolDefinition:
    name: str
    slash_command: str
    title: str
    description: str
    hint: str
    category: str
    risk_level: str
    prompt_template: str
    input_schema: Dict[str, Any]
    enable_web: bool = False
    handler: Optional[Callable[[Dict[str, Any], Optional[str]], Any]] = None

    def to_mcp_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }

    def to_copilot_item(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "cmd": self.slash_command,
            "label": f"{self.slash_command} {self.title}",
            "title": self.title,
            "description": self.description,
            "hint": self.hint,
            "category": self.category,
            "risk_level": self.risk_level,
            "prompt_template": self.prompt_template,
            "enable_web": self.enable_web,
            "mcp_callable": self.handler is not None,
        }


def _call_ip_locate(args: Dict[str, Any], tenant_id: Optional[str]) -> Dict[str, Any]:
    ip = str(args.get("ip") or "").strip()
    if not ip:
        return {"error": "缺少参数 ip"}
    return tool_search_ip(ip, tenant_id=tenant_id)


def _call_mac_locate(args: Dict[str, Any], tenant_id: Optional[str]) -> Dict[str, Any]:
    mac = str(args.get("mac") or "").strip()
    if not mac:
        return {"error": "缺少参数 mac"}
    return tool_search_mac(mac, tenant_id=tenant_id)


def _call_device_neighbors(args: Dict[str, Any], tenant_id: Optional[str]) -> Dict[str, Any]:
    device_id = str(args.get("device_id") or "").strip()
    if not device_id:
        return {"error": "缺少参数 device_id"}
    return tool_get_device_neighbors(device_id, tenant_id=tenant_id)


def _call_active_alarms(args: Dict[str, Any], tenant_id: Optional[str]) -> Dict[str, Any]:
    device_id = str(args.get("device_id") or "").strip() or None
    return tool_get_active_alarms(device_id=device_id, tenant_id=tenant_id)


def _call_knowledge_search(args: Dict[str, Any], tenant_id: Optional[str]) -> Dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "缺少参数 query"}
    top_k = max(1, min(int(args.get("top_k") or 5), 10))
    return knowledge_service.retrieve(query=query, top_k=top_k, tenant_id=tenant_id)


async def _call_web_search(args: Dict[str, Any], tenant_id: Optional[str]) -> Dict[str, Any]:
    if not bool(getattr(settings, "AI_WEB_SEARCH_ENABLED", False)):
        return {"status": "disabled", "message": "联网检索未启用（AI_WEB_SEARCH_ENABLED=false）"}
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "缺少参数 query"}
    return await web_retrieval_service.retrieve(query, tenant_id=tenant_id)


_BUILTIN_TOOLS: List[MCPToolDefinition] = [
    MCPToolDefinition(
        name="nexora_ip_locate",
        slash_command="/ip",
        title="定位目标 IP",
        description="查询指定 IP 地址在 CMDB 与 ARP 表中对应的交换机和端口（只读）",
        hint="/ip 10.0.0.1",
        category="network",
        risk_level="read_only",
        prompt_template="{args} 在哪台交换机哪个端口？",
        input_schema={
            "type": "object",
            "properties": {"ip": {"type": "string", "description": "要查询的 IPv4/IPv6 地址"}},
            "required": ["ip"],
        },
        handler=_call_ip_locate,
    ),
    MCPToolDefinition(
        name="nexora_mac_locate",
        slash_command="/mac",
        title="定位 MAC 地址",
        description="查询指定 MAC 地址所在的交换机、VLAN 与端口（只读）",
        hint="/mac aa:bb:cc:dd:ee:ff",
        category="network",
        risk_level="read_only",
        prompt_template="查询 MAC 地址 {args} 所在交换机和端口",
        input_schema={
            "type": "object",
            "properties": {"mac": {"type": "string", "description": "要查询的 MAC 地址"}},
            "required": ["mac"],
        },
        handler=_call_mac_locate,
    ),
    MCPToolDefinition(
        name="nexora_device_neighbors",
        slash_command="/neighbors",
        title="查询拓扑邻居",
        description="查询指定设备的 LLDP/CDP 拓扑邻居与互联端口（只读）",
        hint="/neighbors core-sw-01",
        category="topology",
        risk_level="read_only",
        prompt_template="查询设备 {args} 的 LLDP 拓扑邻居和互联端口",
        input_schema={
            "type": "object",
            "properties": {"device_id": {"type": "string", "description": "设备 ID 或名称"}},
            "required": ["device_id"],
        },
        handler=_call_device_neighbors,
    ),
    MCPToolDefinition(
        name="nexora_active_alarms",
        slash_command="/alarms",
        title="查询活动告警",
        description="获取当前告警中心的活动告警列表，可按设备过滤（只读）",
        hint="/alarms [设备ID]",
        category="monitoring",
        risk_level="read_only",
        prompt_template="查询当前活动告警：{args}",
        input_schema={
            "type": "object",
            "properties": {"device_id": {"type": "string", "description": "可选设备 ID"}},
        },
        handler=_call_active_alarms,
    ),
    MCPToolDefinition(
        name="nexora_knowledge_search",
        slash_command="/sop",
        title="检索本地 SOP",
        description="在本地知识库中检索运维 SOP、多厂商命令手册与排障指南（只读）",
        hint="/sop 变更规范",
        category="knowledge",
        risk_level="read_only",
        prompt_template="检索本地知识库 SOP：{args}",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词"},
                "top_k": {"type": "integer", "description": "返回条数（1-10）"},
            },
            "required": ["query"],
        },
        handler=_call_knowledge_search,
    ),
    MCPToolDefinition(
        name="nexora_config_generate",
        slash_command="/config",
        title="生成设备配置",
        description="基于多厂商规范生成带验证与回滚步骤的配置方案",
        hint="/config 华为 S6800 OSPF",
        category="assistant",
        risk_level="read_only",
        prompt_template="请生成配置：{args}",
        input_schema={
            "type": "object",
            "properties": {"requirement": {"type": "string", "description": "厂商、型号与配置需求"}},
            "required": ["requirement"],
        },
        handler=None,
    ),
    MCPToolDefinition(
        name="nexora_troubleshoot",
        slash_command="/troubleshoot",
        title="网络故障排查",
        description="针对路由、交换、链路或协议故障提供分步排查思路与只读检查命令",
        hint="/troubleshoot OSPF ExStart",
        category="assistant",
        risk_level="read_only",
        prompt_template="排查网络故障：{args}",
        input_schema={
            "type": "object",
            "properties": {"symptom": {"type": "string", "description": "故障现象或报错"}},
            "required": ["symptom"],
        },
        handler=None,
    ),
    MCPToolDefinition(
        name="nexora_web_search",
        slash_command="/web",
        title="联网实时查询",
        description="通过受控公开检索查询实时信息（天气、公告、最新版本等）",
        hint="/web 今天武汉天气",
        category="web",
        risk_level="read_only",
        prompt_template="{args}",
        enable_web=True,
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "要联网查询的问题"}},
            "required": ["query"],
        },
        handler=_call_web_search,
    ),
]


def list_mcp_tools() -> List[Dict[str, Any]]:
    """Return standard MCP tools/list descriptors for callable read-only tools."""
    return [tool.to_mcp_schema() for tool in _BUILTIN_TOOLS if tool.handler is not None]


def list_copilot_tools() -> List[Dict[str, Any]]:
    """Return full Copilot slash-command & MCP tool catalog."""
    return [tool.to_copilot_item() for tool in _BUILTIN_TOOLS]


async def call_mcp_tool(
    name: str,
    arguments: Optional[Dict[str, Any]] = None,
    *,
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Invoke a registered read-only MCP tool by name."""
    import inspect

    target = next((t for t in _BUILTIN_TOOLS if t.name == name and t.handler is not None), None)
    if target is None:
        raise KeyError(f"Unknown or non-callable MCP tool: {name}")

    result = target.handler(arguments or {}, tenant_id)
    if inspect.isawaitable(result):
        result = await result
    return result if isinstance(result, dict) else {"result": result}
