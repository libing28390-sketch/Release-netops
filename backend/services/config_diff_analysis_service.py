"""Structured configuration diff, risk analysis, compliance, and correlation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import difflib
import hashlib
import json
import re
from typing import Any

from services.config_search_service import redact_config_line


NORMALIZATION_VERSION = "ncm-normalize-v2"
PARSER_VERSION = "ncm-object-v2"
RISK_RULE_VERSION = "risk-v2"
SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass
class StructuredObject:
    object_type: str
    object_name: str
    module: str
    start_line: int
    end_line: int
    lines: list[str]
    fields: dict[str, Any]


_HEADER_PATTERNS = (
    ("interface", "interface", re.compile(r"^\s*interface\s+(.+)$", re.I)),
    ("vlan", "layer2", re.compile(r"^\s*vlan(?:\s+batch)?\s+(.+)$", re.I)),
    ("acl", "security", re.compile(r"^\s*(?:acl(?:\s+(?:number|name))?|ip\s+access-list)\s+(.+)$", re.I)),
    ("bgp", "routing", re.compile(r"^\s*(?:bgp|router\s+bgp)\s+(.+)$", re.I)),
    ("ospf", "routing", re.compile(r"^\s*(?:ospf|router\s+ospf)\s*(.*)$", re.I)),
    ("isis", "routing", re.compile(r"^\s*(?:isis|router\s+isis)\s*(.*)$", re.I)),
    ("route_policy", "routing", re.compile(r"^\s*(?:route-policy|route-map)\s+(.+)$", re.I)),
    ("prefix_list", "routing", re.compile(r"^\s*(?:ip\s+ip-prefix|ip\s+prefix-list)\s+(.+)$", re.I)),
    ("aaa", "management", re.compile(r"^\s*(?:aaa|radius-server|tacacs-server|hwtacacs-server)\b\s*(.*)$", re.I)),
    ("snmp", "management", re.compile(r"^\s*(?:snmp-agent|snmp-server)\s+(.+)$", re.I)),
    ("ntp", "management", re.compile(r"^\s*(?:ntp-service|ntp)\s+(.+)$", re.I)),
    ("vty", "management", re.compile(r"^\s*(?:user-interface\s+vty|line\s+vty)\s+(.+)$", re.I)),
    ("vrf", "routing", re.compile(r"^\s*(?:ip\s+vpn-instance|vrf\s+definition)\s+(.+)$", re.I)),
    ("local_user", "management", re.compile(r"^\s*(?:local-user|username)\s+(\S+).*$", re.I)),
    ("syslog", "management", re.compile(r"^\s*(?:info-center\s+loghost|logging\s+(?:host\s+)?)(.+)$", re.I)),
    ("lldp", "layer2", re.compile(r"^\s*(lldp(?:\s+.+)?)$", re.I)),
)
_ROUTE_PATTERN = re.compile(r"^\s*(?:ip\s+route(?:-static)?|ipv6\s+route-static)\s+(.+)$", re.I)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_config(content: str, *, vendor: str = "") -> str:
    lines: list[str] = []
    vendor_key = str(vendor or "").lower()
    volatile = (
        re.compile(r"^\s*(?:Building configuration|Current configuration\s*:)", re.I),
        re.compile(r"^\s*(?:Last configuration change|NVRAM config last updated)", re.I),
        re.compile(r"^\s*(?:<--- More --->|--More--|\x1b\[[0-9;]*[A-Za-z])", re.I),
        re.compile(r"^\s*(?:generated at|last commit)\b", re.I),
    )
    prompt = re.compile(r"^\s*[<\[].+[>\]]\s*(?:display|show)\s+(?:current|running).*$", re.I)
    for raw in str(content or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.replace("\t", "    ").rstrip()
        if any(pattern.search(line) for pattern in volatile) or prompt.search(line):
            continue
        if vendor_key in {"cisco", "cisco_ios", "cisco_iosxe"} and line.strip().lower() == "end":
            continue
        if vendor_key in {"huawei", "h3c"} and line.strip().lower() == "return":
            continue
        lines.append(redact_config_line(line))
    normalized = "\n".join(lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip() + ("\n" if normalized.strip() else "")


def validate_snapshot_content(content: str, *, vendor: str = "", historical_line_count: int = 0) -> dict[str, Any]:
    raw = str(content or "")
    lines = raw.splitlines()
    non_empty = [line for line in lines if line.strip()]
    issues: list[dict[str, str]] = []
    lower = raw.lower()
    error_patterns = (
        "% invalid input detected",
        "% authorization failed",
        "% incomplete command",
        "% ambiguous command",
        "unrecognized command",
        "too many parameters",
        "permission denied",
        "the command is not supported",
        "connection timed out",
    )
    if not non_empty:
        issues.append({"code": "empty", "message": "配置内容为空"})
    if 0 < len(non_empty) < 3:
        issues.append({"code": "too_short", "message": "配置正文行数过少"})
    if historical_line_count > 0 and len(lines) < max(3, int(historical_line_count * 0.35)):
        issues.append({"code": "historical_size_anomaly", "message": "行数显著低于该设备历史正常水平"})
    for marker in error_patterns:
        if marker in lower:
            issues.append({"code": "command_error", "message": f"检测到设备错误输出：{marker}"})
            break
    if "\x00" in raw or sum(1 for char in raw if ord(char) < 9) > 3:
        issues.append({"code": "encoding", "message": "包含异常不可打印字符"})
    if "--more--" in lower or "<--- more --->" in lower:
        issues.append({"code": "paging", "message": "配置包含分页提示，可能采集不完整"})
    vendor_key = str(vendor or "").lower()
    if vendor_key and len(non_empty) >= 3:
        known = any(
            re.search(pattern, raw, re.I | re.M)
            for pattern in (r"^\s*interface\b", r"^\s*(?:hostname|sysname)\b", r"^\s*(?:vlan|ip route|ip route-static)\b")
        )
        if not known:
            issues.append({"code": "vendor_marker_missing", "message": "未发现常见配置关键标识，请人工确认采集命令"})
    status = "valid"
    if issues:
        status = "invalid" if any(issue["code"] in {"empty", "command_error", "encoding"} for issue in issues) else "partial"
    return {
        "status": status,
        "valid_for_auto_compare": status == "valid",
        "issues": issues,
        "line_count": len(lines),
        "size": len(raw.encode("utf-8")),
        "content_hash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    }


def _interface_fields(lines: list[str]) -> dict[str, Any]:
    text = "\n".join(lines)
    description = re.search(r"(?im)^\s*description\s+(.+)$", text)
    ip_match = re.search(r"(?im)^\s*(?:ip address|ip address)\s+(\S+)(?:\s+(\S+))?", text)
    link_type = re.search(r"(?im)^\s*(?:port link-type|switchport mode)\s+(\S+)", text)
    access_vlan = re.search(r"(?im)^\s*(?:port default vlan|switchport access vlan)\s+(\d+)", text)
    allowed = re.search(r"(?im)^\s*(?:port trunk allow-pass vlan|switchport trunk allowed vlan)\s+(.+)$", text)
    mtu = re.search(r"(?im)^\s*mtu\s+(\d+)", text)
    vrf = re.search(r"(?im)^\s*(?:ip binding vpn-instance|vrf forwarding)\s+(\S+)", text)
    acl = re.search(r"(?im)^\s*(?:traffic-filter|ip access-group)\s+(.+)$", text)
    shutdown = bool(re.search(r"(?im)^\s*shutdown\s*$", text)) and not bool(re.search(r"(?im)^\s*(?:undo|no)\s+shutdown\s*$", text))
    return {
        "description": description.group(1).strip() if description else "",
        "admin_status": "down" if shutdown else "up",
        "ip_address": " ".join(item for item in (ip_match.group(1), ip_match.group(2) or "") if item) if ip_match else "",
        "link_type": link_type.group(1).lower() if link_type else "",
        "access_vlan": int(access_vlan.group(1)) if access_vlan else None,
        "allowed_vlans": allowed.group(1).strip() if allowed else "",
        "mtu": int(mtu.group(1)) if mtu else None,
        "vrf": vrf.group(1) if vrf else "",
        "acl": acl.group(1).strip() if acl else "",
    }


def _generic_fields(object_type: str, lines: list[str]) -> dict[str, Any]:
    text = "\n".join(lines)
    if object_type == "bgp":
        neighbors = sorted(set(re.findall(r"(?im)^\s*(?:peer|neighbor)\s+(\S+)", text)))
        as_number = re.search(r"(?im)^\s*(?:bgp|router bgp)\s+(\S+)", text)
        return {"as_number": as_number.group(1) if as_number else "", "neighbors": neighbors}
    if object_type == "route":
        default = bool(re.search(r"(?i)(?:0\.0\.0\.0\s+0\.0\.0\.0|0\.0\.0\.0/0|::/0)", text))
        return {"route": lines[0].strip() if lines else "", "is_default": default}
    if object_type == "acl":
        permit_any = bool(re.search(r"(?im)^\s*(?:rule\s+\d+\s+permit|permit)\b.*\bany\b", text))
        return {"permit_any": permit_any, "rule_count": len([line for line in lines if re.search(r"(?i)\b(?:permit|deny)\b", line)])}
    if object_type == "vlan":
        values = sorted({int(value) for value in re.findall(r"\b([1-9]\d{0,3})\b", lines[0] if lines else "") if 1 <= int(value) <= 4094})
        return {"vlan_ids": values}
    return {"content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def parse_structured_config(content: str, *, vendor: str = "") -> list[StructuredObject]:
    normalized = normalize_config(content, vendor=vendor)
    lines = normalized.splitlines()
    headers: list[tuple[int, str, str, str]] = []
    consumed_route_lines: set[int] = set()
    for index, line in enumerate(lines):
        route_match = _ROUTE_PATTERN.match(line)
        if route_match:
            headers.append((index, "route", route_match.group(1).strip(), "routing"))
            consumed_route_lines.add(index)
            continue
        for object_type, module, pattern in _HEADER_PATTERNS:
            match = pattern.match(line)
            if match:
                name = (match.group(1) or object_type).strip()
                headers.append((index, object_type, name, module))
                break

    objects: list[StructuredObject] = []
    for position, (start, object_type, name, module) in enumerate(headers):
        if start in consumed_route_lines:
            block = [lines[start]]
        else:
            end_candidate = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
            block = lines[start:min(end_candidate, start + 800)]
            while block and not block[-1].strip():
                block.pop()
        fields = _interface_fields(block) if object_type == "interface" else _generic_fields(object_type, block)
        objects.append(
            StructuredObject(
                object_type=object_type,
                object_name=name,
                module=module,
                start_line=start + 1,
                end_line=start + max(1, len(block)),
                lines=block,
                fields=fields,
            )
        )
    return objects


def _field_changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for field in sorted(set(before) | set(after)):
        left = before.get(field)
        right = after.get(field)
        if left != right:
            changes.append({"field": field, "before": left, "after": right})
    return changes


def _risk_for_change(change: dict[str, Any], device: dict[str, Any]) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    object_type = change["object_type"]
    name = str(change["object_name"])
    before_fields = change.get("before_fields") or {}
    after_fields = change.get("after_fields") or {}
    before_text = "\n".join(change.get("before_lines") or [])
    after_text = "\n".join(change.get("after_lines") or [])
    role = str(device.get("role") or "").lower()

    def add(rule_id: str, severity: str, message: str, impact: str, approval: bool = False, mfa: bool = False) -> None:
        risks.append({
            "rule_id": rule_id,
            "severity": severity,
            "message": message,
            "potential_impact": impact,
            "requires_secondary_approval": approval,
            "requires_mfa": mfa,
        })

    if object_type == "interface":
        before_ip = str(before_fields.get("ip_address") or "")
        after_ip = str(after_fields.get("ip_address") or "")
        if before_ip and before_ip != after_ip and re.search(r"(?i)(management|mgmt|m-eth|vlanif|loopback)", name):
            add("MGMT_IP_CHANGE", "critical", "管理接口 IP 地址发生变化", "平台、监控和 SSH 可能失联", True, True)
        if before_fields.get("admin_status") == "up" and after_fields.get("admin_status") == "down":
            severity = "critical" if role in {"core", "distribution", "router", "firewall"} or re.search(r"(?i)(uplink|trunk)", before_text) else "high"
            add("IFACE_SHUTDOWN", severity, f"接口 {name} 被关闭", "链路或下游网络可能中断", True, True)
        if before_fields.get("link_type") == "access" and after_fields.get("link_type") == "trunk":
            add("ACCESS_TO_TRUNK", "high", f"接口 {name} 从 Access 改为 Trunk", "可能导致 VLAN 泄漏或终端失联", True, False)
        if before_ip != after_ip and not any(item["rule_id"] == "MGMT_IP_CHANGE" for item in risks):
            add("INTERFACE_IP_CHANGE", "high", f"接口 {name} 的三层地址发生变化", "路由邻接、网关或管理可达性可能受影响", True, False)
        if before_fields.get("access_vlan") != after_fields.get("access_vlan"):
            add("ACCESS_VLAN_CHANGE", "high", f"接口 {name} 的 Access VLAN 发生变化", "终端可能进入错误广播域或失联", True, False)
        if before_fields.get("allowed_vlans") != after_fields.get("allowed_vlans"):
            add("TRUNK_ALLOWED_CHANGE", "high", f"接口 {name} 的 Trunk VLAN 范围发生变化", "业务 VLAN 可能中断或发生越权透传", True, False)
        if before_fields.get("mtu") != after_fields.get("mtu"):
            add("INTERFACE_MTU_CHANGE", "medium", f"接口 {name} 的 MTU 发生变化", "可能产生分片、丢包或邻接异常")
        if before_fields.get("vrf") != after_fields.get("vrf"):
            add("INTERFACE_VRF_CHANGE", "critical", f"接口 {name} 的 VRF 绑定发生变化", "接口可能迁移到错误路由域", True, True)
        if before_fields.get("acl") != after_fields.get("acl"):
            add("INTERFACE_ACL_CHANGE", "high", f"接口 {name} 的 ACL 绑定发生变化", "流量放行或阻断范围可能改变", True, False)
        if before_fields.get("description") != after_fields.get("description") and len(risks) == 0:
            add("INTERFACE_DESCRIPTION", "low", f"接口 {name} 描述发生变化", "通常不影响转发")
    if object_type == "route":
        if change["change_type"] == "deleted":
            if before_fields.get("is_default"):
                add("DEFAULT_ROUTE_DELETE", "critical", "默认路由被删除", "可能导致全局出口中断", True, True)
            else:
                add("STATIC_ROUTE_DELETE", "high", "静态路由被删除", "相关网段可能不可达", True, False)
        elif change["change_type"] == "added" and after_fields.get("is_default"):
            add("DEFAULT_ROUTE_ADD", "high", "新增默认路由", "可能改变全局出口和故障切换路径", True, False)
        elif change["change_type"] == "modified":
            add("STATIC_ROUTE_NEXTHOP_CHANGE", "high", "静态路由下一跳或属性发生变化", "相关流量路径可能切换或形成黑洞", True, False)
    if object_type == "bgp":
        removed_neighbors = sorted(set(before_fields.get("neighbors") or []) - set(after_fields.get("neighbors") or []))
        added_neighbors = sorted(set(after_fields.get("neighbors") or []) - set(before_fields.get("neighbors") or []))
        if removed_neighbors:
            add("BGP_NEIGHBOR_DELETE", "critical", f"删除 BGP 邻居：{', '.join(removed_neighbors)}", "可能导致大范围路由撤销", True, True)
        if added_neighbors:
            add("BGP_NEIGHBOR_ADD", "high", f"新增 BGP 邻居：{', '.join(added_neighbors)}", "可能引入非预期路由或扩大路由传播范围", True, False)
        if before_fields.get("as_number") and before_fields.get("as_number") != after_fields.get("as_number"):
            add("BGP_AS_CHANGE", "critical", "BGP AS 号发生变化", "邻居关系可能无法建立", True, True)
    if object_type == "vrf":
        if change["change_type"] == "deleted":
            add("VRF_DELETE", "critical", f"VRF {name} 被删除", "业务隔离网络可能整体中断", True, True)
        elif change["change_type"] == "added":
            add("VRF_ADD", "medium", f"新增 VRF {name}", "需确认 RD、RT 与接口绑定符合隔离设计")
    if object_type == "acl" and not before_fields.get("permit_any") and after_fields.get("permit_any"):
        add("ACL_WIDEN_ANY", "high", f"ACL {name} 放宽到 any", "可能造成安全暴露", True, False)
    if object_type == "acl" and change["change_type"] == "deleted":
        add("ACL_DELETE", "critical", f"ACL {name} 被删除", "依赖该策略的访问控制可能失效", True, True)
    if object_type == "ospf":
        add(
            "OSPF_PROCESS_DELETE" if change["change_type"] == "deleted" else "OSPF_PROCESS_CHANGE",
            "critical" if change["change_type"] == "deleted" else "high",
            f"OSPF 进程 {name} {'被删除' if change['change_type'] == 'deleted' else '发生变化'}",
            "IGP 邻接与路由收敛可能受影响",
            True,
            change["change_type"] == "deleted",
        )
    if object_type == "isis":
        add(
            "ISIS_PROCESS_DELETE" if change["change_type"] == "deleted" else "ISIS_PROCESS_CHANGE",
            "critical" if change["change_type"] == "deleted" else "high",
            f"ISIS 进程 {name} {'被删除' if change['change_type'] == 'deleted' else '发生变化'}",
            "骨干 IGP 邻接与路由收敛可能受影响",
            True,
            change["change_type"] == "deleted",
        )
    if object_type == "route_policy":
        add("ROUTE_POLICY_CHANGE", "high", f"路由策略 {name} 发生变化", "路由接收、发布或属性设置可能改变", True, False)
    if object_type == "prefix_list":
        add("PREFIX_LIST_CHANGE", "high", f"前缀列表 {name} 发生变化", "依赖该列表的路由策略可能改变", True, False)
    if object_type == "aaa" and before_text != after_text:
        add("AAA_CHANGE", "high", "AAA/TACACS/RADIUS 配置发生变化", "管理员可能无法登录", True, True)
    if object_type == "snmp" and before_text != after_text:
        if re.search(r"(?i)\b(?:public|private)\b", after_text):
            add("SNMP_DEFAULT_COMMUNITY", "critical", "SNMP 使用默认 Community", "设备管理面可能被未授权访问", True, True)
        else:
            add("SNMP_CHANGE", "medium", "SNMP 配置发生变化", "监控采集可能中断")
    if object_type == "ntp" and before_text != after_text:
        add("NTP_SERVER_DELETE" if change["change_type"] == "deleted" else "NTP_CHANGE", "high" if change["change_type"] == "deleted" else "medium", "NTP 配置发生变化", "日志时间与审计可能异常")
    if object_type == "vlan":
        if change["change_type"] == "deleted":
            add("VLAN_DELETE", "high", f"VLAN {name} 被删除", "该二层广播域内业务可能整体中断", True, False)
        elif change["change_type"] == "added" and not risks:
            add("VLAN_ADD", "low", f"新增 VLAN {name}", "需结合接口放行范围确认影响")
    if object_type == "vty" and re.search(r"(?i)(?:protocol\s+inbound|transport\s+input).*\btelnet\b", after_text):
        add("TELNET_ENABLE", "critical", "VTY 开放 Telnet 管理", "管理凭据和命令可能被明文窃听", True, True)
    if object_type == "local_user":
        add("LOCAL_USER_CHANGE", "high", f"本地管理员 {name} 发生变化", "可能产生未授权账号或导致应急账号不可用", True, True)
    if object_type == "syslog":
        add("SYSLOG_CHANGE", "medium", "日志服务器配置发生变化", "集中审计、告警关联或事件取证可能中断")
    if object_type == "lldp" and change["change_type"] == "deleted":
        add("LLDP_DISABLE", "medium", "LLDP 配置被删除或关闭", "拓扑发现与邻居资产关联可能失真")
    if not risks:
        add("CONFIG_OBJECT_CHANGE", "info", f"{object_type} 对象发生变化", "未命中内置高风险规则")
    return risks


def compare_structured_configs(
    before_content: str,
    after_content: str,
    *,
    vendor: str,
    device: dict[str, Any],
    mode: str = "normalized",
) -> dict[str, Any]:
    before_normalized = normalize_config(before_content, vendor=vendor) if mode == "normalized" else before_content
    after_normalized = normalize_config(after_content, vendor=vendor) if mode == "normalized" else after_content
    before_lines = before_normalized.splitlines()
    after_lines = after_normalized.splitlines()
    line_diff = list(difflib.ndiff(before_lines, after_lines))
    additions = [line[2:] for line in line_diff if line.startswith("+ ")]
    removals = [line[2:] for line in line_diff if line.startswith("- ")]

    before_objects = {(item.object_type, item.object_name): item for item in parse_structured_config(before_content, vendor=vendor)}
    after_objects = {(item.object_type, item.object_name): item for item in parse_structured_config(after_content, vendor=vendor)}
    changes: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    for key in sorted(set(before_objects) | set(after_objects)):
        before = before_objects.get(key)
        after = after_objects.get(key)
        if before and after and before.lines == after.lines:
            continue
        change_type = "modified" if before and after else "deleted" if before else "added"
        change = {
            "id": hashlib.sha256(f"{key[0]}:{key[1]}".encode("utf-8")).hexdigest()[:16],
            "object_type": key[0],
            "object_name": key[1],
            "module": (after or before).module,
            "change_type": change_type,
            "before_lines": before.lines if before else [],
            "after_lines": after.lines if after else [],
            "before_fields": before.fields if before else {},
            "after_fields": after.fields if after else {},
            "field_changes": _field_changes(before.fields if before else {}, after.fields if after else {}),
            "start_line_a": before.start_line if before else None,
            "start_line_b": after.start_line if after else None,
        }
        change_risks = _risk_for_change(change, device)
        highest = max(change_risks, key=lambda item: SEVERITY_ORDER[item["severity"]])
        change["risk_level"] = highest["severity"]
        change["risk_reason"] = highest["message"]
        change["potential_impact"] = highest["potential_impact"]
        change["requires_secondary_approval"] = any(item["requires_secondary_approval"] for item in change_risks)
        change["requires_mfa"] = any(item["requires_mfa"] for item in change_risks)
        changes.append(change)
        risks.extend([{**item, "object_id": change["id"], "object_type": key[0], "object_name": key[1]} for item in change_risks])

    module_counts = Counter(change["module"] for change in changes)
    object_counts = Counter(change["object_type"] for change in changes)
    risk_counts = Counter(item["severity"] for item in risks)
    unified = list(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile="A",
            tofile="B",
            lineterm="",
            n=3,
        )
    )
    return {
        "summary": {
            "added_lines": len(additions),
            "removed_lines": len(removals),
            "changed_objects": len(changes),
            "affected_modules": len(module_counts),
            "high_risk_changes": risk_counts["critical"] + risk_counts["high"],
            "module_counts": dict(module_counts),
            "object_counts": dict(object_counts),
            "risk_counts": {
                severity: risk_counts[severity]
                for severity in ("critical", "high", "medium", "low", "info")
            },
        },
        "objects": changes,
        "risks": sorted(risks, key=lambda item: SEVERITY_ORDER[item["severity"]], reverse=True),
        "unified_diff": unified,
        "normalized_a": before_normalized,
        "normalized_b": after_normalized,
        "has_changes": bool(additions or removals),
        "requires_secondary_approval": any(item["requires_secondary_approval"] for item in risks),
        "requires_mfa": any(item["requires_mfa"] for item in risks),
        "versions": {
            "normalization": NORMALIZATION_VERSION,
            "parser": PARSER_VERSION,
            "risk_rules": RISK_RULE_VERSION,
        },
    }


def evaluate_compliance(content: str, rules: list[dict[str, Any]], device: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    compliant = 0
    noncompliant = 0
    role = str(device.get("role") or "").lower()
    vendor = str(device.get("vendor") or "").lower()
    platform = str(device.get("platform") or "").lower()
    for rule in rules:
        scope = rule.get("scope") or {}
        if scope.get("roles") and role not in {str(item).lower() for item in scope["roles"]}:
            continue
        if scope.get("vendors") and vendor not in {str(item).lower() for item in scope["vendors"]}:
            continue
        if scope.get("platforms") and platform not in {str(item).lower() for item in scope["platforms"]}:
            continue
        try:
            count = len(re.findall(str(rule["pattern"]), content))
        except re.error:
            count = 0
        minimum = int(rule.get("minimum_count") or 1)
        is_compliant = count < minimum if rule.get("rule_type") == "forbid" else count >= minimum
        if is_compliant:
            compliant += 1
        else:
            noncompliant += 1
        findings.append({
            "rule_id": rule["id"],
            "name": rule["name"],
            "status": "compliant" if is_compliant else "missing" if rule.get("rule_type") == "require" else "conflict",
            "severity": rule.get("severity") or "medium",
            "observed_count": count,
            "expected_count": minimum,
            "remediation": rule.get("remediation") or "",
        })
    total = compliant + noncompliant
    return {
        "compliant_count": compliant,
        "noncompliant_count": noncompliant,
        "compliance_rate": round(compliant / total * 100) if total else 100,
        "findings": findings,
    }


def cache_key(
    device_id: str,
    snapshot_a_hash: str,
    snapshot_b_hash: str,
    mode: str,
) -> str:
    raw = "|".join(
        (
            device_id,
            snapshot_a_hash,
            snapshot_b_hash,
            mode,
            NORMALIZATION_VERSION,
            PARSER_VERSION,
            RISK_RULE_VERSION,
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def safe_json(raw: Any, fallback: Any) -> Any:
    if isinstance(raw, type(fallback)):
        return raw
    try:
        parsed = json.loads(raw or "")
        return parsed if isinstance(parsed, type(fallback)) else fallback
    except (TypeError, ValueError):
        return fallback
