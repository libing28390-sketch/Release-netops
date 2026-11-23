"""Built-in MCP tool registry for Nexora AI Copilot and local MCP clients."""

from ai.mcp.registry import (
    MCPToolDefinition,
    call_mcp_tool,
    list_copilot_tools,
    list_mcp_tools,
)

__all__ = [
    "MCPToolDefinition",
    "call_mcp_tool",
    "list_copilot_tools",
    "list_mcp_tools",
]
