"""Seed the built-in Agent definitions used by the AI Agent API."""

from __future__ import annotations

import json
from datetime import datetime, timezone


VERSION = 187
NAME = "seed_builtin_ai_agents"


_BUILTIN_AGENTS = (
    {
        "id": "agent_troubleshooting",
        "code": "troubleshooting_agent",
        "name": "网络排障 Agent",
        "description": "使用租户范围内的只读网络证据进行多步故障排查。",
        "system_prompt": (
            "You are the Nexora network troubleshooting agent. "
            "Use only tenant-scoped read-only tools to gather evidence. "
            "Do not invent device facts or claim that a configuration change was made. "
            "Return either a tool_call JSON object or a final_answer JSON object."
        ),
        "allowed_tools": (
            "search_ip",
            "search_mac",
            "get_neighbors",
            "get_active_alarms",
            "get_config_diff",
            "get_asset",
            "get_device_status",
            "get_arp_entry",
            "get_mac_entry",
            "get_lldp_neighbors",
            "find_ip_location",
            "get_running_config",
            "compare_config",
        ),
        "max_steps": 6,
        "timeout": 180,
    },
)


def upgrade(cursor, use_pg: bool) -> None:
    """Insert missing system Agents without overwriting existing definitions."""

    del use_pg  # The database adapter translates portable '?' placeholders.
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    for agent in _BUILTIN_AGENTS:
        existing = cursor.execute(
            "SELECT id FROM ai_agent WHERE code = ?",
            (agent["code"],),
        ).fetchone()
        if existing:
            continue

        cursor.execute(
            """
            INSERT INTO ai_agent (
                id, code, name, description, system_prompt, allowed_tools,
                max_steps, timeout, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                agent["id"],
                agent["code"],
                agent["name"],
                agent["description"],
                agent["system_prompt"],
                json.dumps(list(agent["allowed_tools"]), ensure_ascii=False),
                agent["max_steps"],
                agent["timeout"],
                now,
                now,
            ),
        )


def downgrade(cursor, use_pg: bool) -> None:
    """Keep Agent definitions and any related run history on downgrade."""

    del cursor, use_pg
    return None
