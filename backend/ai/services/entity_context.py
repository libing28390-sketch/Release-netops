"""Conversation Entity Working Memory for Cross-Module Zero-Token Continuity.

Persists active operational entities (device, vendor, site, prefix, candidates,
last module, recent compact facts) per conversation in PostgreSQL so operators
can seamlessly chain queries across all 12 Nexora modules at 0 LLM tokens:
  "1.1.1.1 这台设备的信息" -> "这台设备最近登录了几次" -> "它有告警吗" -> "在哪个机柜"

Guardrails enforced here:
1. Scope Isolation: global queries ("全网/所有/我们") never silently inherit
   an earlier single-device focus.
2. Multi-Target Ambiguity: when a pronoun refers to >1 candidate devices
   (e.g. multiple topology neighbors), returns candidates for 0-token local
   disambiguation instead of guessing.
3. Persistence: stored in `ai_conversations.entity_context_json` (idempotent
   PostgreSQL column) so focus survives backend reloads and session re-opens.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from ai.services.intent_parser import extract_asset_filters
from database.core import get_db_connection

logger = logging.getLogger(__name__)

_ENTITY_COL_READY = False

_IPV4_RE = re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d./])")
_CIDR_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)/\d{1,2}\b")
_HOSTNAME_TOKEN_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_-]{2,48})\b")

_GLOBAL_SCOPE_MARKERS = (
    "全网", "所有", "全部", "我们", "系统里", "一共", "总共", "整体", "汇总", "各厂商", "各站点",
)
_DEVICE_PRONOUN_MARKERS = (
    "这台设备", "那台设备", "该设备", "这台", "那台", "它", "这台交换机", "这台防火墙", "这台路由器", "上面那台",
)
_NEIGHBOR_PRONOUN_MARKERS = ("对端那台", "对端设备", "邻居那台", "对端")
_OMITTED_SUBJECT_ATTR_MARKERS = (
    "最近登录", "登录了几次", "登录次数", "谁登录", "谁登过", "登过几次",
    "在哪个机柜", "哪个机柜", "几u", "第几u", "机柜位置",
    "上联连着", "连着谁", "邻居有哪些", "拓扑邻居",
    "配置改过", "配置变过", "配置有变更", "配置漂移", "有漂移吗", "合规吗",
    "有告警吗", "有告警没有", "有没有告警", "未恢复告警",
    "有工单吗", "关联工单", "有关联变更工单",
    "端口状态", "接口状态", "有down口", "哪些口down",
)
_IGNORE_HOST_TOKENS = frozenset({
    "cmdb", "ipam", "lldp", "cdp", "ospf", "bgp", "vlan", "lacp", "stp", "mstp",
    "acl", "ssh", "ntp", "snmp", "syslog", "pam", "http", "https", "down", "up",
    "cpu", "psu", "eol", "h3c", "huawei", "cisco", "ruijie", "juniper", "dell",
    "switch", "router", "firewall", "core", "access", "distribution", "online", "offline",
})


def _ensure_entity_context_column(conn: Any) -> None:
    global _ENTITY_COL_READY
    if _ENTITY_COL_READY:
        return
    try:
        conn.execute("ALTER TABLE ai_conversations ADD COLUMN IF NOT EXISTS entity_context_json TEXT DEFAULT '{}'")
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    _ENTITY_COL_READY = True


def load_entity_context(conversation_id: Optional[str]) -> Dict[str, Any]:
    """Load persisted entity working memory for a conversation."""
    cid = str(conversation_id or "").strip()
    if not cid:
        return {}
    try:
        with get_db_connection() as conn:
            _ensure_entity_context_column(conn)
            row = conn.execute(
                "SELECT entity_context_json FROM ai_conversations WHERE id = ?",
                (cid,),
            ).fetchone()
            if row and row[0]:
                parsed = json.loads(str(row[0]))
                if isinstance(parsed, dict):
                    return parsed
    except Exception as exc:
        logger.debug("Load entity context skipped: %s", type(exc).__name__)
    return {}


def save_entity_context(conversation_id: Optional[str], context: Dict[str, Any]) -> None:
    """Persist updated entity working memory for a conversation."""
    cid = str(conversation_id or "").strip()
    if not cid or not isinstance(context, dict):
        return
    # Keep recent_facts bounded to the latest 6 compact entries.
    bounded = dict(context)
    facts = bounded.get("recent_facts")
    if isinstance(facts, list) and len(facts) > 6:
        bounded["recent_facts"] = facts[-6:]
    try:
        with get_db_connection() as conn:
            _ensure_entity_context_column(conn)
            conn.execute(
                "UPDATE ai_conversations SET entity_context_json = ? WHERE id = ?",
                (json.dumps(bounded, ensure_ascii=False), cid),
            )
            conn.commit()
    except Exception as exc:
        logger.debug("Save entity context skipped: %s", type(exc).__name__)


def lookup_device_in_db(*, ip: Optional[str] = None, hostname: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Resolve a single managed device from PostgreSQL `devices` (read-only)."""
    if not ip and not hostname:
        return None
    try:
        with get_db_connection() as conn:
            row = None
            if ip:
                row = conn.execute(
                    """
                    SELECT id, hostname, ip_address, vendor, platform, model, version, role, status, site
                    FROM devices WHERE ip_address = ? LIMIT 1
                    """,
                    (ip.strip(),),
                ).fetchone()
            if row is None and hostname:
                h = hostname.strip().lower()
                row = conn.execute(
                    """
                    SELECT id, hostname, ip_address, vendor, platform, model, version, role, status, site
                    FROM devices WHERE LOWER(COALESCE(hostname, '')) = ? LIMIT 1
                    """,
                    (h,),
                ).fetchone()
                if row is None:
                    matches = conn.execute(
                        """
                        SELECT id, hostname, ip_address, vendor, platform, model, version, role, status, site
                        FROM devices WHERE LOWER(COALESCE(hostname, '')) LIKE ? LIMIT 2
                        """,
                        (f"%{h}%",),
                    ).fetchall()
                    if len(matches) == 1:
                        row = matches[0]
            if row:
                return {
                    "id": str(row[0] or ""),
                    "hostname": str(row[1] or ""),
                    "ip_address": str(row[2] or ""),
                    "vendor": str(row[3] or ""),
                    "platform": str(row[4] or ""),
                    "model": str(row[5] or ""),
                    "version": str(row[6] or ""),
                    "role": str(row[7] or ""),
                    "status": str(row[8] or ""),
                    "site": str(row[9] or ""),
                }
    except Exception as exc:
        logger.debug("Device lookup skipped: %s", type(exc).__name__)
    return None


def _extract_explicit_device_hint(message: str) -> tuple[Optional[str], Optional[str]]:
    ip_match = _IPV4_RE.search(message)
    ip = ip_match.group(0) if ip_match else None
    hostname = None
    for match in _HOSTNAME_TOKEN_RE.finditer(message):
        token = match.group(1)
        if token.lower() in _IGNORE_HOST_TOKENS:
            continue
        if any(c.isdigit() for c in token) or "-" in token or "_" in token:
            hostname = token
            break
    return ip, hostname


def resolve_target_entities(
    message: str,
    saved_ctx: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve explicit or inherited operational entities for the current turn.

    Returns a structured dict:
      - scope_mode: "explicit" | "inherited" | "global" | "ambiguous" | "none"
      - device: resolved device dict or None
      - explicit_ip: IPv4 string if explicitly present in message
      - vendor / role / status / site / prefix: extracted filters
      - ambiguous_candidates: list of candidate hostnames when pronoun is ambiguous
      - scope_label: human-readable scope string echoed on line 1 of the reply
    """
    msg = " ".join(str(message or "").strip().split())
    lower = msg.lower()
    ctx = saved_ctx if isinstance(saved_ctx, dict) else {}

    asset_filters = extract_asset_filters(msg)
    cidr_match = _CIDR_RE.search(msg)
    prefix = cidr_match.group(0) if cidr_match else None
    explicit_ip, explicit_host = _extract_explicit_device_hint(msg)

    has_global = any(m in lower for m in _GLOBAL_SCOPE_MARKERS)
    has_device_pronoun = any(m in lower for m in _DEVICE_PRONOUN_MARKERS)
    has_neighbor_pronoun = any(m in lower for m in _NEIGHBOR_PRONOUN_MARKERS)
    has_plural_list = any(m in lower for m in ("有哪些", "列表", "待审批")) and not has_device_pronoun
    has_omitted_attr = any(m in lower for m in _OMITTED_SUBJECT_ATTR_MARKERS) and not has_plural_list
    if has_plural_list:
        has_global = True

    # 1. Explicit device (IP or hostname in current turn) always wins.
    if explicit_ip or explicit_host:
        device = lookup_device_in_db(ip=explicit_ip, hostname=explicit_host)
        if device:
            label = f"{device['hostname']} ({device['ip_address']})" if device["ip_address"] else device["hostname"]
            return {
                "scope_mode": "explicit",
                "device": device,
                "explicit_ip": explicit_ip,
                "vendor": asset_filters.get("vendor") or (device["vendor"].lower() if device["vendor"] else None),
                "role": asset_filters.get("role"),
                "status": asset_filters.get("status"),
                "site": asset_filters.get("site"),
                "prefix": prefix,
                "ambiguous_candidates": [],
                "scope_label": label,
            }
        if explicit_ip:
            return {
                "scope_mode": "explicit",
                "device": None,
                "explicit_ip": explicit_ip,
                "vendor": asset_filters.get("vendor"),
                "role": asset_filters.get("role"),
                "status": asset_filters.get("status"),
                "site": asset_filters.get("site"),
                "prefix": prefix,
                "ambiguous_candidates": [],
                "scope_label": explicit_ip,
            }

    # 2. Explicit vendor / site / prefix / global marker resets single-device focus.
    if has_global or asset_filters.get("vendor") or asset_filters.get("site") or prefix:
        parts = [p for p in (
            asset_filters.get("vendor").upper() if asset_filters.get("vendor") else None,
            asset_filters.get("site"),
            prefix,
        ) if p]
        return {
            "scope_mode": "global" if has_global and not parts else "explicit",
            "device": None,
            "explicit_ip": None,
            "vendor": asset_filters.get("vendor"),
            "role": asset_filters.get("role"),
            "status": asset_filters.get("status"),
            "site": asset_filters.get("site"),
            "prefix": prefix,
            "ambiguous_candidates": [],
            "scope_label": " · ".join(parts) if parts else "全网",
        }

    # 3. Neighbor pronoun disambiguation (Guardrail 2: never guess when >1 candidates).
    candidates = ctx.get("candidate_devices") if isinstance(ctx.get("candidate_devices"), list) else []
    if has_neighbor_pronoun and len(candidates) > 1:
        return {
            "scope_mode": "ambiguous",
            "device": None,
            "explicit_ip": None,
            "vendor": None,
            "role": None,
            "status": None,
            "site": None,
            "prefix": None,
            "ambiguous_candidates": candidates[:8],
            "scope_label": "待确认对象",
        }

    # 4. Inherit active device ONLY on explicit pronoun or omitted-subject single-device attribute query.
    active_device = ctx.get("active_device") if isinstance(ctx.get("active_device"), dict) else None
    if active_device and (has_device_pronoun or has_omitted_attr):
        host = str(active_device.get("hostname") or "")
        ip_addr = str(active_device.get("ip_address") or "")
        label = f"{host} ({ip_addr})" if (host and ip_addr) else (host or ip_addr or "当前设备")
        return {
            "scope_mode": "inherited",
            "device": active_device,
            "explicit_ip": None,
            "vendor": str(active_device.get("vendor") or "").lower() or None,
            "role": None,
            "status": None,
            "site": None,
            "prefix": None,
            "ambiguous_candidates": [],
            "scope_label": label,
        }

    return {
        "scope_mode": "global",
        "device": None,
        "explicit_ip": None,
        "vendor": asset_filters.get("vendor"),
        "role": asset_filters.get("role"),
        "status": asset_filters.get("status"),
        "site": asset_filters.get("site"),
        "prefix": ctx.get("active_prefix") if ("网段" in lower or "子网" in lower) else None,
        "ambiguous_candidates": [],
        "scope_label": "全网",
    }
