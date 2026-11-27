"""Read-Only Local Toolset for Nexora Native Agentic Copilot Chat.

Exposes all 12 Nexora control-plane modules + Local Vendor Knowledge Base as
compact, RBAC-enforced, zero-secret OpenAI Function Calling tools so the LLM
serves as the unified conversational brain:
  - Understands multi-turn pronouns, drill-downs, and comparisons naturally
  - Calls multiple local read-only tools in parallel on demand
  - Reasons across multiple hypotheses grounded in real PostgreSQL + KB facts
  - Keeps tool payloads compact (<= 1800 chars) to minimize token cost while
    maximizing provider Prompt KV-Cache hit rates.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from ai.security.gateway import ai_security_gateway
from ai.services.entity_context import lookup_device_in_db
from ai.services.module_bus import execute_module_bus_query
from ai.services.natural_query import natural_query_service
from ai.services.ip_troubleshooting import ip_troubleshooting_service
from ai.services.mac_troubleshooting import mac_troubleshooting_service
from ai.services.rag_retriever import RetrievalRequest, rag_retriever
from ai.services.web_retrieval import web_retrieval_service
from services.official_config_template_service import search_official_templates

logger = logging.getLogger(__name__)

MAX_TOOL_RESULT_CHARS = 900

TOOL_DISPLAY_LABELS: Dict[str, str] = {
    "get_network_overview": "全网总览与容量快照",
    "query_cmdb_devices": "CMDB 资产、机柜与站点",
    "query_alarms": "告警中心活动告警",
    "query_monitoring_topology": "实时监控接口、拓扑与 IP/MAC 定位",
    "query_pam_sessions": "操作工作台（PAM）登录审计",
    "query_config_and_compliance": "配置变更、漂移与合规基线",
    "query_tickets_and_automation": "变更工单、巡检与平台概览",
    "search_local_knowledge": "本地厂商知识库与官方模板",
    "ops_memory_graph": "长期运维记忆与历史案例图谱",
    "search_public_web": "公开网页动态检索",
}

_LOCAL_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_network_overview",
            "description": "全网总览（在线率/告警/巡检）与可选容量概览（只读）。",
            "parameters": {
                "type": "object",
                "properties": {"include_capacity": {"type": "boolean"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_cmdb_devices",
            "description": "查 CMDB 设备档案/列表、机柜 U 位、IPAM 网段、站点或脱敏认证目录（只读）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "enum": ["device_profile", "device_list", "racks", "ipam", "sites", "auth_catalog"]},
                    "target": {"type": "string"},
                    "vendor": {"type": "string"},
                    "role": {"type": "string"},
                    "status": {"type": "string"},
                    "site": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_alarms",
            "description": "查未恢复告警统计与明细，可按设备/厂商/级别过滤（只读）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "vendor": {"type": "string"},
                    "severity": {"type": "string"},
                    "query_text": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_monitoring_topology",
            "description": "查接口异常、拓扑邻居或 IP/MAC 端口定位（只读）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["interfaces", "neighbors", "ip_locate", "mac_locate"]},
                    "target": {"type": "string"},
                },
                "required": ["mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_pam_sessions",
            "description": "查操作工作台 PAM 终端登录次数与活跃会话（只读）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "days": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_config_and_compliance",
            "description": "查配置备份变更、配置漂移或合规基线（只读）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["changes", "drift", "compliance"]},
                    "target": {"type": "string"},
                },
                "required": ["mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_tickets_and_automation",
            "description": "查变更工单、自动化巡检或平台账号数（只读）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["tickets", "inspections", "platform"]},
                    "target": {"type": "string"},
                    "pending_only": {"type": "boolean"},
                },
                "required": ["mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_local_knowledge",
            "description": "查本地厂商知识库与官方配置模板（可传 vendor/product_model/cli_platform/software_release）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "vendor": {"type": "string"},
                    "product_model": {"type": "string"},
                    "cli_platform": {"type": "string"},
                    "software_release": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ops_memory_graph",
            "description": "检索(recall)或沉淀(remember)企业长期运维常识与已闭环排障案例（禁存实时状态或密钥）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["recall", "remember"]},
                    "query": {"type": "string"},
                    "memory_type": {"type": "string", "enum": ["semantic", "episodic"]},
                    "entity_key": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "related_entity": {"type": "string"},
                    "relation": {"type": "string"},
                },
                "required": ["action"],
            },
        },
    },
]

_PUBLIC_WEB_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_public_web",
        "description": "仅查外部公开动态参考（CVE/EOL等，不可信数据）。",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}


def get_copilot_tools(*, allow_web_search: bool = False) -> List[Dict[str, Any]]:
    """Return the static OpenAI-compatible read-only tool schema list."""
    tools = list(_LOCAL_TOOL_SCHEMAS)
    if allow_web_search:
        tools.append(_PUBLIC_WEB_TOOL_SCHEMA)
    return tools


def build_agentic_system_prompt(*, allow_web_search: bool = False) -> str:
    """Return a day-static system prompt optimized for KV-cache prefix hits."""
    from datetime import datetime

    today_str = datetime.now().strftime("%Y-%m-%d")
    web_note = (
        "Public web search is enabled only as a secondary fallback for external dynamic facts (CVEs, vendor EOL, public news); always prefer local Nexora tools and local KB first."
        if allow_web_search
        else "Public web search is disabled: rely exclusively on local Nexora tools and the local vendor knowledge base; do not offer to search the internet."
    )
    return (
        f"Current Date: {today_str}\n"
        "You are Nexora AI Copilot, an expert enterprise network operations assistant.\n"
        "Core Operating Principles:\n"
        "1. Grounding First: For ANY question about this network's devices, IPs, alarms, interfaces, topology, PAM logins, racks, IPAM prefixes, config changes/drift, compliance, inspections, or change tickets, you MUST call the relevant local read-only tools first. Never invent devices, counts, IPs, or statuses.\n"
        "2. Multi-Tool Parallel Reasoning: When investigating an anomaly, alert, root cause, risk, or device comparison, invoke multiple relevant local tools in parallel (e.g., alarms + interfaces + PAM + config drift/changes + tickets) to build a complete evidence picture.\n"
        "3. Structured Hypothesis Reasoning: For troubleshooting or risk questions, synthesize tool evidence into:\n"
        "   - Verified Facts & Ruled-Out Causes (e.g., 0 recent PAM logins and no config drift -> rule out recent human misconfiguration).\n"
        "   - Ranked Possibilities (2-3 concrete hypotheses ordered by likelihood with supporting evidence).\n"
        "   - Actionable Read-Only Next Steps tailored to the device's real vendor/model/platform/version.\n"
        "4. CMDB + Local KB Synergy: Before giving CLI commands or configuration/troubleshooting steps for a managed device, check its exact vendor/model/platform/version via `query_cmdb_devices` and pass those fields into `search_local_knowledge` so syntax matches the actual OS.\n"
        "5. Natural Conversational Continuity: Maintain full multi-turn awareness across pronouns, drill-downs, and device comparisons. Answer concisely and directly to what the user asked—do not dump giant unrelated tables for simple questions.\n"
        "6. Strict Read-Only Safety: You only read data and never execute commands on devices. Guide configuration changes to Change Governance.\n"
        "7. Zero Redundant Calls: If [已激活的长期运维记忆] or [本地已预取实锤数据] already contains the requested facts, answer directly without re-calling tools.\n"
        f"8. Data Boundary: {web_note}"
    )


async def prefetch_local_facts(
    message: str,
    *,
    tenant_id: str = "tenant-default",
    user_id: Optional[str] = None,
    roles: Optional[Sequence[str]] = None,
    site_ids: Optional[Sequence[str]] = None,
    allow_web_search: bool = False,
) -> Dict[str, Any]:
    """0-Token parallel local pre-fetch for explicit entities & module cues.

    When the user's question names concrete managed devices (IP/hostname) and
    clear local data dimensions (alarms/interfaces/PAM/drift/tickets/racks),
    fetch them in Python (<50ms, 0 LLM tokens) BEFORE calling the LLM.
    Returns:
      - facts_block: compact Markdown/text evidence (<= 1800 chars)
      - citations: list of system citations
      - tools_used: list of prefetched tool names
      - direct_synthesis_ready: True when all requested local facts are already
        supplied so the LLM can answer in ONE single streaming call (no 2-round
        tool planning overhead, cutting input tokens by ~75%).
    """
    import re

    msg = " ".join(str(message or "").strip().split())
    lower = msg.lower()
    if not msg:
        return {"facts_block": "", "citations": [], "tools_used": [], "direct_synthesis_ready": False}

    # Explicit write-memory, KB CLI lookup, or web search still uses the tool loop.
    wants_memory_write = any(m in lower for m in ("记住", "记录一条", "存到记忆", "帮我记下"))
    wants_kb = any(m in lower for m in ("怎么配", "如何配", "什么命令", "命令", "知识库", "语法", "手册"))
    if wants_memory_write or allow_web_search:
        return {"facts_block": "", "citations": [], "tools_used": [], "direct_synthesis_ready": False}

    # Extract up to 3 explicit managed devices mentioned in the prompt
    found_devices: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for ip in re.findall(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b", msg):
        dev = lookup_device_in_db(ip=ip)
        if dev and dev["id"] not in seen_ids:
            seen_ids.add(dev["id"])
            found_devices.append(dev)
    for tok in re.findall(r"\b([A-Za-z][A-Za-z0-9_-]{2,40})\b", msg):
        if any(c.isdigit() for c in tok) or "-" in tok or "_" in tok:
            dev = lookup_device_in_db(hostname=tok)
            if dev and dev["id"] not in seen_ids:
                seen_ids.add(dev["id"])
                found_devices.append(dev)
        if len(found_devices) >= 3:
            break

    tasks: List[tuple[str, Dict[str, Any]]] = []
    # Match explicit module cues
    want_alarms = any(m in lower for m in ("告警", "报警", "alarm", "alert"))
    want_ifaces = any(m in lower for m in ("接口", "端口", "down", "interface"))
    want_pam = any(m in lower for m in ("登录", "堡垒机", "会话")) or bool(re.search(r"(?<![a-z])pam(?![a-z])", lower))
    want_drift = any(m in lower for m in ("漂移", "drift"))
    want_changes = any(m in lower for m in ("配置变更", "配置备份", "改过配置"))
    want_tickets = any(m in lower for m in ("工单", "审批"))
    want_racks = any(m in lower for m in ("机柜", "u位", "几u"))

    if found_devices:
        for dev in found_devices[:2]:
            host = dev["hostname"]
            # Always include compact CMDB profile for mentioned devices
            tasks.append(("query_cmdb_devices", {"scope": "device_profile", "target": host}))
            if want_alarms:
                tasks.append(("query_alarms", {"target": host}))
            if want_ifaces:
                tasks.append(("query_monitoring_topology", {"mode": "interfaces", "target": host}))
            if want_pam:
                days = 30 if "30天" in lower else 7
                tasks.append(("query_pam_sessions", {"target": host, "days": days}))
            if want_drift:
                tasks.append(("query_config_and_compliance", {"mode": "drift", "target": host}))
            if want_changes:
                tasks.append(("query_config_and_compliance", {"mode": "changes", "target": host}))
            if want_tickets:
                tasks.append(("query_tickets_and_automation", {"mode": "tickets", "target": host}))
            if want_racks:
                tasks.append(("query_cmdb_devices", {"scope": "racks", "target": host}))
    elif any(m in lower for m in ("全网总览", "今天全网", "全网整体")):
        tasks.append(("get_network_overview", {"include_capacity": False}))

    if not tasks:
        return {"facts_block": "", "citations": [], "tools_used": [], "direct_synthesis_ready": False}

    async def _exec(tname: str, targs: Dict[str, Any]):
        res = await execute_copilot_tool(
            tname, targs, tenant_id=tenant_id, user_id=user_id, roles=roles, site_ids=site_ids, allow_web_search=False
        )
        return tname, res

    outputs = await asyncio.gather(*[_exec(n, a) for n, a in tasks[:6]])
    blocks: List[str] = []
    citations: List[Dict[str, Any]] = []
    tools_used: List[str] = []
    for tname, res in outputs:
        tools_used.append(tname)
        citations.extend(res.get("citations") or [])
        txt = str(res.get("content") or "").strip()
        if txt:
            blocks.append(f"[{TOOL_DISPLAY_LABELS.get(tname, tname)}]\n{txt[:550]}")

    facts_block = "\n\n".join(blocks)[:2200]
    direct_ready = bool(facts_block) and not wants_kb
    return {
        "facts_block": facts_block,
        "citations": citations[:12],
        "tools_used": list(dict.fromkeys(tools_used)),
        "direct_synthesis_ready": direct_ready,
    }


def _clip(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    s = str(text or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "\n...[已按上下文预算截断]"


def _resolve_device_entity(target: Optional[str]) -> Dict[str, Any]:
    """Resolve an optional IP/hostname target into a module_bus entities dict."""
    raw = str(target or "").strip()
    if not raw:
        return {"scope_mode": "global", "device": None, "explicit_ip": None, "scope_label": "全网"}
    import re

    is_ip = bool(re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", raw))
    dev = lookup_device_in_db(ip=raw if is_ip else None, hostname=None if is_ip else raw)
    if dev:
        label = f"{dev['hostname']} ({dev['ip_address']})" if dev.get("ip_address") else dev["hostname"]
        return {
            "scope_mode": "explicit",
            "device": dev,
            "explicit_ip": raw if is_ip else dev.get("ip_address"),
            "scope_label": label,
        }
    return {
        "scope_mode": "explicit",
        "device": None,
        "explicit_ip": raw if is_ip else None,
        "scope_label": raw,
    }


def _detokenize_args(value: Any, *, tenant_id: str, task_id: str) -> Any:
    """Restore security-gateway reversible tokens (e.g. [IP_1]) inside tool args."""
    if isinstance(value, str):
        return ai_security_gateway.resolve_output(value, tenant_id=tenant_id, task_id=task_id)
    if isinstance(value, list):
        return [_detokenize_args(item, tenant_id=tenant_id, task_id=task_id) for item in value]
    if isinstance(value, dict):
        return {str(k): _detokenize_args(v, tenant_id=tenant_id, task_id=task_id) for k, v in value.items()}
    return value


def parse_and_resolve_tool_args(
    raw_arguments: Any,
    *,
    tenant_id: str,
    task_id: str,
) -> Dict[str, Any]:
    if isinstance(raw_arguments, dict):
        parsed = raw_arguments
    else:
        try:
            parsed = json.loads(str(raw_arguments or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = {}
    if not isinstance(parsed, dict):
        return {}
    return _detokenize_args(parsed, tenant_id=tenant_id, task_id=task_id)


async def execute_copilot_tool(
    tool_name: str,
    args: Dict[str, Any],
    *,
    tenant_id: str = "tenant-default",
    user_id: Optional[str] = None,
    roles: Optional[Sequence[str]] = None,
    site_ids: Optional[Sequence[str]] = None,
    allow_web_search: bool = False,
) -> Dict[str, Any]:
    """Execute one read-only Copilot tool and return compact text + citations."""
    name = str(tool_name or "").strip()
    safe_args = args if isinstance(args, dict) else {}
    citations: List[Dict[str, Any]] = []

    try:
        if name == "get_network_overview":
            mod = "capacity_summary" if safe_args.get("include_capacity") else "overview"
            res = execute_module_bus_query(mod, "全网总览", {"scope_mode": "global", "scope_label": "全网"}, roles=roles)
            citations.extend(res.get("citations") or [])
            return {"content": _clip(res.get("summary", "")), "citations": citations}

        if name == "query_cmdb_devices":
            scope = str(safe_args.get("scope") or "").strip().lower()
            target = str(safe_args.get("target") or "").strip()
            if not scope:
                scope = "device_profile" if target else "device_list"
            if scope == "device_profile" and target:
                entities = _resolve_device_entity(target)
                res = execute_module_bus_query("device_profile", f"{target} 设备信息", entities, roles=roles)
                citations.extend(res.get("citations") or [])
                return {"content": _clip(res.get("summary", "")), "citations": citations}
            if scope == "racks":
                entities = _resolve_device_entity(target)
                res = execute_module_bus_query("racks", f"{target} 机柜", entities, roles=roles)
                citations.extend(res.get("citations") or [])
                return {"content": _clip(res.get("summary", "")), "citations": citations}
            if scope == "ipam":
                entities = {"scope_mode": "explicit" if target else "global", "prefix": target or None, "scope_label": target or "全网"}
                res = execute_module_bus_query("ipam_prefix", f"IPAM {target}", entities, roles=roles)
                citations.extend(res.get("citations") or [])
                return {"content": _clip(res.get("summary", "")), "citations": citations}
            if scope in {"sites", "auth_catalog"}:
                q = "有哪些凭据" if scope == "auth_catalog" else "有哪些站点"
                res = execute_module_bus_query("cmdb_base", q, {"scope_mode": "global", "scope_label": "全网"}, roles=roles)
                citations.extend(res.get("citations") or [])
                return {"content": _clip(res.get("summary", "")), "citations": citations}
            # device_list via natural_query_service
            filters: Dict[str, Any] = {}
            for key in ("vendor", "role", "status", "site"):
                if safe_args.get(key):
                    filters[key] = str(safe_args[key]).strip()
            report = await natural_query_service.execute_asset_analysis(
                f"列出设备 {target}".strip(), filters, tenant_id=tenant_id
            )
            citations.extend(report.get("citations") or [])
            return {"content": _clip(report.get("summary", "")), "citations": citations}

        if name == "query_alarms":
            target = str(safe_args.get("target") or "").strip()
            filters: Dict[str, Any] = {}
            if target:
                entities = _resolve_device_entity(target)
                dev = entities.get("device")
                if dev and dev.get("id"):
                    filters["device_id"] = dev["id"]
                else:
                    filters["device_name"] = target
            else:
                if safe_args.get("vendor"):
                    filters["vendor"] = str(safe_args["vendor"]).strip().lower()
            if safe_args.get("severity"):
                filters["severity"] = str(safe_args["severity"]).strip().lower()
            q = str(safe_args.get("query_text") or f"{target} 告警").strip()
            report = await natural_query_service.execute_alert_analysis(q, filters, tenant_id=tenant_id)
            citations.extend(report.get("citations") or [])
            return {"content": _clip(report.get("summary", "")), "citations": citations}

        if name == "query_monitoring_topology":
            mode = str(safe_args.get("mode") or "interfaces").strip().lower()
            target = str(safe_args.get("target") or "").strip()
            if mode == "ip_locate" and target:
                ip_res = await ip_troubleshooting_service.troubleshoot_ip(target, user_id=user_id, tenant_id=tenant_id)
                return {"content": _clip(json.dumps(ip_res.get("analysis") or ip_res.get("facts") or {}, ensure_ascii=False)), "citations": citations}
            if mode == "mac_locate" and target:
                mac_res = await mac_troubleshooting_service.troubleshoot_mac(target, user_id=user_id, tenant_id=tenant_id)
                return {"content": _clip(json.dumps(mac_res.get("analysis") or mac_res.get("facts") or {}, ensure_ascii=False)), "citations": citations}
            entities = _resolve_device_entity(target)
            mod = "topology_neighbors" if mode == "neighbors" else "interface_anomalies"
            res = execute_module_bus_query(mod, f"{target} {mode}", entities, roles=roles)
            citations.extend(res.get("citations") or [])
            return {"content": _clip(res.get("summary", "")), "citations": citations}

        if name == "query_pam_sessions":
            target = str(safe_args.get("target") or "").strip()
            days = int(safe_args.get("days") or 7)
            entities = _resolve_device_entity(target)
            day_hint = "30天" if days >= 30 else ("今天" if days <= 1 else "7天")
            res = execute_module_bus_query("pam_sessions", f"{target} {day_hint} 登录记录", entities, roles=roles)
            citations.extend(res.get("citations") or [])
            return {"content": _clip(res.get("summary", "")), "citations": citations}

        if name == "query_config_and_compliance":
            mode = str(safe_args.get("mode") or "changes").strip().lower()
            target = str(safe_args.get("target") or "").strip()
            entities = _resolve_device_entity(target)
            mod_map = {"changes": "config_changes", "drift": "config_drift", "compliance": "compliance"}
            mod = mod_map.get(mode, "config_changes")
            res = execute_module_bus_query(mod, f"{target} {mode}", entities, roles=roles)
            citations.extend(res.get("citations") or [])
            return {"content": _clip(res.get("summary", "")), "citations": citations}

        if name == "query_tickets_and_automation":
            mode = str(safe_args.get("mode") or "tickets").strip().lower()
            target = str(safe_args.get("target") or "").strip()
            pending_only = bool(safe_args.get("pending_only"))
            entities = _resolve_device_entity(target)
            if mode == "inspections":
                res = execute_module_bus_query("automation_inspections", "巡检", entities, roles=roles)
            elif mode == "platform":
                res = execute_module_bus_query("platform_audit", "平台用户", {"scope_mode": "global", "scope_label": "全网"}, roles=roles)
            else:
                q = "待审批变更工单" if pending_only else f"{target} 变更工单"
                res = execute_module_bus_query("change_orders", q, entities, roles=roles)
            citations.extend(res.get("citations") or [])
            return {"content": _clip(res.get("summary", "")), "citations": citations}

        if name == "search_local_knowledge":
            query = str(safe_args.get("query") or "").strip()
            if not query:
                return {"content": "缺少检索关键词 query。", "citations": []}
            req_vals = {
                k: str(safe_args[k]).strip()
                for k in ("vendor", "product_model", "cli_platform", "software_release")
                if safe_args.get(k)
            }
            req = RetrievalRequest.from_mapping(
                query,
                req_vals,
                top_k=3,
                tenant_id=tenant_id or "tenant-default",
                user_id=user_id,
                roles=list(roles or []),
                site_ids=list(site_ids or []),
            )
            retrieval = rag_retriever.search(req)
            chunks = list(retrieval.get("results") or [])
            if not chunks:
                chunks = list(search_official_templates(req, limit=3) or [])
            if not chunks:
                return {"content": "本地厂商知识库与官方模板库暂未命中匹配文档。", "citations": []}
            from ai.security.classification import redact_secrets
            from ai.security.sanitizer import sanitize_text

            lines: List[str] = []
            for idx, c in enumerate(chunks[:3], start=1):
                title = str(c.get("document_name") or c.get("title") or c.get("source") or f"知识片段 {idx}")
                plat = str(c.get("cli_platform") or c.get("platform") or "")
                raw_body = str(c.get("content") or "").strip()[:700]
                safe_body, _ = redact_secrets(sanitize_text(raw_body))
                lines.append(f"[{idx}] {title}{f' ({plat})' if plat else ''}\n{safe_body}")
                citations.append({
                    "document": title,
                    "document_id": str(c.get("document_id") or c.get("template_id") or title),
                    "section": str(c.get("section") or ""),
                    "platform": plat,
                    "trust": "verified",
                })
            return {"content": _clip("\n\n".join(lines)), "citations": citations}

        if name == "ops_memory_graph":
            from ai.services.memory_graph import activate_memories, save_memory_node

            action = str(safe_args.get("action") or "recall").strip().lower()
            if action == "remember":
                title = str(safe_args.get("title") or "").strip()
                content = str(safe_args.get("content") or "").strip()
                if not title or not content:
                    return {"content": "写入长期记忆需要提供 title 和 content。", "citations": []}
                rel_list = []
                if safe_args.get("related_entity"):
                    rel_list.append((str(safe_args.get("relation") or "related_to"), str(safe_args["related_entity"])))
                saved = save_memory_node(
                    title=title,
                    content=content,
                    memory_type=str(safe_args.get("memory_type") or "semantic"),
                    entity_key=str(safe_args.get("entity_key") or "global"),
                    tenant_id=tenant_id or "tenant-default",
                    created_by=str(user_id or "copilot"),
                    related_entities=rel_list,
                )
                return {
                    "content": f"已写入长期记忆 [{saved['memory_type']} · {saved['entity_key']}]：{saved['title']}（ID: {saved['id']}）",
                    "citations": [{"document": f"Ops Memory {saved['id']}", "document_id": saved["id"], "trust": "system"}],
                }
            q = str(safe_args.get("query") or safe_args.get("entity_key") or "").strip()
            recalled = activate_memories(q, tenant_id=tenant_id or "tenant-default")
            if not recalled.get("prompt_block"):
                return {"content": "未在长期运维记忆库中检索到相关经验或关联关系。", "citations": []}
            return {
                "content": recalled["prompt_block"],
                "citations": [{"document": f"Ops Memory: {n['title']}", "document_id": n["id"], "trust": "system"} for n in recalled.get("nodes") or []],
            }

        if name == "search_public_web":
            if not allow_web_search:
                return {"content": "当前未启用公网联网检索，请优先基于本地数据与本地知识库回答。", "citations": []}
            query = str(safe_args.get("query") or "").strip()
            if not query:
                return {"content": "缺少检索关键词 query。", "citations": []}
            web_res = await web_retrieval_service.retrieve(query, tenant_id=tenant_id)
            items = list(web_res.get("items") or [])
            citations.extend(web_res.get("citations") or [])
            if not items:
                return {"content": "公开网页检索未返回可用结果。", "citations": citations}
            lines = [f"- {it.get('title') or '参考'} ({it.get('url') or ''}): {str(it.get('snippet') or '')[:350]}" for it in items[:4]]
            return {"content": _clip("公开网页参考（不可信外部数据）：\n" + "\n".join(lines)), "citations": citations}

        return {"content": f"未知工具: {name}", "citations": []}
    except Exception as exc:
        logger.warning("Copilot tool %s failed: %s", name, type(exc).__name__)
        return {"content": f"工具 {name} 本地只读执行失败，请基于已有事实或稍后重试。", "citations": citations}


async def execute_tool_calls_parallel(
    tool_calls: List[Dict[str, Any]],
    *,
    tenant_id: str = "tenant-default",
    user_id: Optional[str] = None,
    roles: Optional[Sequence[str]] = None,
    site_ids: Optional[Sequence[str]] = None,
    task_id: str = "",
    allow_web_search: bool = False,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Execute LLM-requested tool_calls concurrently; return (tool_messages, citations)."""

    async def _run_one(tc: Dict[str, Any]) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        tc_id = str(tc.get("id") or f"call_{id(tc)}")
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        fn_name = str(fn.get("name") or tc.get("name") or "")
        args = parse_and_resolve_tool_args(fn.get("arguments") or tc.get("arguments"), tenant_id=tenant_id, task_id=task_id)
        out = await execute_copilot_tool(
            fn_name,
            args,
            tenant_id=tenant_id,
            user_id=user_id,
            roles=roles,
            site_ids=site_ids,
            allow_web_search=allow_web_search,
        )
        return (
            {"role": "tool", "tool_call_id": tc_id, "name": fn_name, "content": out["content"]},
            out.get("citations") or [],
        )

    results = await asyncio.gather(*[_run_one(tc) for tc in (tool_calls or [])[:6]])
    tool_messages: List[Dict[str, Any]] = []
    all_citations: List[Dict[str, Any]] = []
    for msg, cits in results:
        tool_messages.append(msg)
        all_citations.extend(cits)
    return tool_messages, all_citations
