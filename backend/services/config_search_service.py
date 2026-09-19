"""Vendor-aware configuration search, indexing, ranking, and redaction.

The service deliberately keeps SQL portable between SQLite and PostgreSQL and
performs configuration-aware matching in bounded Python workers.  Snapshot
files remain the source of truth; the database index stores metadata and parsed
objects, never credentials or an additional unencrypted copy of raw configs.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import ipaddress
import json
import os
import re
import time
import uuid
from typing import Any, Iterable

from database import get_db_connection


SEARCH_TYPES = {
    "AUTO",
    "TEXT",
    "EXACT_TEXT",
    "IPV4",
    "IPV6",
    "CIDR",
    "VLAN",
    "ASN",
    "INTERFACE",
    "PROTOCOL",
    "REGEX",
    "STRUCTURED",
}
SEARCH_SCOPES = {
    "LATEST_VALID_RUNNING",
    "LATEST_RUNNING",
    "ALL_LATEST",
    "HISTORY",
    "RUNNING_HISTORY",
    "STARTUP_HISTORY",
    "BASELINE",
    "TIME_RANGE",
    "SPECIFIC_VERSION",
    "TEMPLATES",
}

MAX_QUERY_LENGTH = 512
MAX_REGEX_LENGTH = 256
MAX_FILE_READS = 500
MAX_SNAPSHOT_CANDIDATES = 2_000
MAX_MATCHES_PER_DEVICE = 200
PARSER_VERSION = "ncm-search-v1"

_BACKUP_ROOT = os.path.join(os.getcwd(), "backup")
_IP_TOKEN = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f:.]+)(?:/\d{1,3})?(?![\w:])")
_INTERFACE_TOKEN = re.compile(
    r"\b(?:GigabitEthernet|TenGigabitEthernet|TwentyFiveGigE|FortyGigabitEthernet|"
    r"HundredGigE|Ethernet|Eth-Trunk|Bridge-Aggregation|Port-Channel|LoopBack|"
    r"Loopback|Vlanif|Vlan-interface|GE|XGE)\s*[\d/.:_-]+",
    re.I,
)
_SENSITIVE_LINE = re.compile(
    r"(?i)^(\s*(?:username\s+\S+\s+(?:password|secret)|enable\s+(?:password|secret)|"
    r"snmp-server\s+community|snmp-agent\s+community|password|secret|"
    r"authentication-key|cipher)\b)(.*)$"
)
_SENSITIVE_INLINE = re.compile(
    r"(?i)\b(password|secret|community|cipher|authentication-key)\s+(\S+)"
)
_PROTOCOLS = ("ospf", "bgp", "isis", "rip", "eigrp", "mpls", "vxlan", "evpn", "stp", "ntp", "snmp", "aaa")


@dataclass(frozen=True)
class SearchInterpretation:
    search_type: str
    normalized_query: str
    title: str
    description: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConfigObject:
    object_type: str
    object_key: str
    start_line: int
    end_line: int
    search_text: str
    attributes: dict[str, Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_json(value: Any, fallback: Any) -> Any:
    if isinstance(value, type(fallback)):
        return value
    if not value:
        return fallback
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, type(fallback)) else fallback
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _read_config_file(file_path: str) -> str:
    """Read a snapshot below the configured backup root without path traversal."""
    normalized = str(file_path or "").replace("\\", os.sep).replace("/", os.sep)
    root = os.path.abspath(_BACKUP_ROOT)
    absolute = os.path.abspath(os.path.join(root, normalized))
    if os.path.commonpath((root, absolute)) != root or not os.path.isfile(absolute):
        return ""
    try:
        with open(absolute, "rb") as handle:
            data = handle.read()
        if data.startswith(b"ENCRYPTED:"):
            from core.crypto import _get_fernet

            data = _get_fernet().decrypt(data[len(b"ENCRYPTED:") :])
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def redact_config_line(line: str, include_sensitive: bool = False) -> str:
    if include_sensitive:
        return line
    match = _SENSITIVE_LINE.match(line)
    if match:
        return f"{match.group(1)} ***"
    return _SENSITIVE_INLINE.sub(lambda item: f"{item.group(1)} ***", line)


def classify_query(query: str, requested_type: str = "AUTO") -> SearchInterpretation:
    raw = str(query or "").strip()
    if not raw:
        raise ValueError("搜索内容不能为空")
    if len(raw) > MAX_QUERY_LENGTH:
        raise ValueError(f"搜索内容不能超过 {MAX_QUERY_LENGTH} 个字符")

    requested = str(requested_type or "AUTO").upper()
    if requested not in SEARCH_TYPES:
        raise ValueError("不支持的搜索类型")

    warnings: list[str] = []
    detected = requested
    normalized = raw
    if requested == "AUTO":
        try:
            value = ipaddress.ip_network(raw, strict=False)
            if "/" in raw:
                detected = "CIDR"
                normalized = str(value)
            else:
                address = ipaddress.ip_address(raw)
                detected = "IPV4" if address.version == 4 else "IPV6"
                normalized = str(address)
        except ValueError:
            vlan_match = re.fullmatch(r"(?:vlan\s*[:#]?\s*)(\d{1,4})", raw, re.I)
            asn_match = re.fullmatch(r"(?:as|asn)\s*[:#]?\s*(\d{1,10})", raw, re.I)
            if vlan_match and 1 <= int(vlan_match.group(1)) <= 4094:
                detected = "VLAN"
                normalized = vlan_match.group(1)
            elif asn_match and 1 <= int(asn_match.group(1)) <= 4_294_967_295:
                detected = "ASN"
                normalized = asn_match.group(1)
            elif len(raw) >= 2 and raw[0] == raw[-1] == '"':
                detected = "EXACT_TEXT"
                normalized = raw[1:-1]
            elif raw.isdigit():
                # A bare number may be a VLAN, ASN, ACL number, metric, timer,
                # or part of an address.  Keep it as exact text until the user
                # explicitly selects a semantic type.
                detected = "EXACT_TEXT"
                warnings.append("纯数字存在歧义；可手工切换为 VLAN 或 ASN 精确检索。")
            elif _INTERFACE_TOKEN.fullmatch(raw):
                detected = "INTERFACE"
            elif raw.lower() in _PROTOCOLS:
                detected = "PROTOCOL"
            elif re.search(r"(?:^|\s)[a-z_]+:", raw, re.I):
                detected = "STRUCTURED"
            else:
                detected = "TEXT"

    if detected == "REGEX":
        _compile_safe_regex(raw)

    descriptions = {
        "TEXT": "按不区分大小写的文本与词组检索配置行。",
        "EXACT_TEXT": "按完整文本边界检索，减少模糊命中。",
        "IPV4": "按 IPv4 地址边界精确检索。",
        "IPV6": "按标准化 IPv6 地址检索。",
        "CIDR": "同时判断网段相等、包含与被包含关系。",
        "VLAN": "仅匹配 VLAN 对象和 VLAN 相关命令中的编号。",
        "ASN": "匹配 BGP/路由进程中的自治系统号。",
        "INTERFACE": "匹配接口名称、接口块及相关引用。",
        "PROTOCOL": "匹配协议进程、协议对象及相关命令。",
        "REGEX": "使用受限正则表达式逐行检索。",
        "STRUCTURED": "按字段表达式组合过滤，例如 vendor:cisco vlan:100。",
    }
    return SearchInterpretation(
        search_type=detected,
        normalized_query=normalized,
        title=f"已识别为 {detected}",
        description=descriptions.get(detected, descriptions["TEXT"]),
        warnings=tuple(warnings),
    )


def _compile_safe_regex(pattern: str) -> re.Pattern[str]:
    if len(pattern) > MAX_REGEX_LENGTH:
        raise ValueError(f"正则表达式不能超过 {MAX_REGEX_LENGTH} 个字符")
    blocked = (
        r"\(\?<",
        r"\(\?=",
        r"\(\?!",
        r"\\[1-9]",
        r"\([^)]*[+*][^)]*\)[+*{]",
        r"\.\*[+*{]",
    )
    if any(re.search(item, pattern) for item in blocked):
        raise ValueError("正则表达式包含不安全或复杂度过高的结构")
    try:
        return re.compile(pattern, re.I)
    except re.error as exc:
        raise ValueError(f"正则表达式无效: {exc}") from exc


def _line_networks(line: str) -> Iterable[ipaddress._BaseNetwork]:
    for token in _IP_TOKEN.findall(line):
        candidate = token.strip("[](),;")
        if not candidate or not any(char.isdigit() for char in candidate):
            continue
        try:
            if "/" in candidate:
                yield ipaddress.ip_network(candidate, strict=False)
            else:
                address = ipaddress.ip_address(candidate)
                yield ipaddress.ip_network(f"{address}/{address.max_prefixlen}", strict=False)
        except ValueError:
            continue


def _structured_terms(query: str) -> dict[str, str]:
    terms: dict[str, str] = {}
    for chunk in query.split():
        key, separator, value = chunk.partition(":")
        if separator and key and value:
            terms[key.lower()] = value
    return terms


def _line_matches(
    line: str,
    interpretation: SearchInterpretation,
    *,
    device: dict[str, Any],
) -> tuple[bool, str, int]:
    query = interpretation.normalized_query
    line_lower = line.lower()
    query_lower = query.lower()
    kind = interpretation.search_type

    if kind == "TEXT":
        tokens = [token for token in re.split(r"\s+", query_lower) if token]
        if query_lower in line_lower:
            return True, "完整词组", 100
        if tokens and all(token in line_lower for token in tokens):
            return True, "全部关键词", 70
        return False, "", 0
    if kind == "EXACT_TEXT":
        matched = bool(re.search(rf"(?<!\w){re.escape(query)}(?!\w)", line, re.I))
        return matched, "精确文本" if matched else "", 110 if matched else 0
    if kind in {"IPV4", "IPV6"}:
        try:
            target = ipaddress.ip_address(query)
            matched = any(
                network.prefixlen == network.max_prefixlen and network.network_address == target
                for network in _line_networks(line)
            )
        except ValueError:
            matched = False
        return matched, "IP 地址精确命中" if matched else "", 130 if matched else 0
    if kind == "CIDR":
        target = ipaddress.ip_network(query, strict=False)
        relation = ""
        for candidate in _line_networks(line):
            if candidate.version != target.version:
                continue
            if candidate == target:
                relation = "网段相等"
                break
            if candidate.subnet_of(target):
                relation = "配置网段位于查询网段内"
                break
            if target.subnet_of(candidate):
                relation = "查询网段位于配置网段内"
                break
        return bool(relation), relation, 140 if relation == "网段相等" else 105
    if kind == "VLAN":
        vlan_id = int(query)
        matched = bool(
            re.search(
                rf"(?i)\b(?:vlan(?:-id)?|vlanif|vlan-interface|access\s+vlan|native\s+vlan|"
                rf"pvid\s+vlan|permit\s+vlan)\s*(?:batch\s+)?{vlan_id}(?!\d)",
                line,
            )
        )
        return matched, "VLAN 对象" if matched else "", 125 if matched else 0
    if kind == "ASN":
        matched = bool(
            re.search(rf"(?i)\b(?:bgp|router\s+bgp|as-number|local-as|remote-as)\s+{re.escape(query)}(?!\d)", line)
        )
        return matched, "BGP ASN" if matched else "", 120 if matched else 0
    if kind == "INTERFACE":
        normalized_line = re.sub(r"\s+", "", line_lower)
        normalized_query = re.sub(r"\s+", "", query_lower)
        matched = normalized_query in normalized_line
        return matched, "接口名称" if matched else "", 120 if matched else 0
    if kind == "PROTOCOL":
        matched = bool(re.search(rf"(?<!\w){re.escape(query_lower)}(?!\w)", line_lower))
        return matched, "协议关键字" if matched else "", 100 if matched else 0
    if kind == "REGEX":
        matched = bool(_compile_safe_regex(query).search(line[:10_000]))
        return matched, "正则表达式" if matched else "", 95 if matched else 0
    if kind == "STRUCTURED":
        terms = _structured_terms(query)
        metadata_fields = {
            "vendor": str(device.get("vendor") or "").lower(),
            "platform": str(device.get("platform") or "").lower(),
            "site": str(device.get("site") or "").lower(),
            "role": str(device.get("role") or "").lower(),
            "device": f"{device.get('hostname', '')} {device.get('ip_address', '')}".lower(),
        }
        for key in ("vendor", "platform", "site", "role", "device"):
            if key in terms and terms[key].lower() not in metadata_fields[key]:
                return False, "", 0
        content_terms = {key: value for key, value in terms.items() if key not in metadata_fields}
        if "vlan" in content_terms:
            nested = SearchInterpretation("VLAN", content_terms["vlan"], "", "")
            matched, reason, score = _line_matches(line, nested, device=device)
            return matched, reason, score + 10 if matched else 0
        if "ip" in content_terms:
            try:
                nested = classify_query(content_terms["ip"])
            except ValueError:
                return False, "", 0
            matched, reason, score = _line_matches(line, nested, device=device)
            return matched, reason, score + 10 if matched else 0
        if "text" in content_terms:
            nested = SearchInterpretation("TEXT", content_terms["text"], "", "")
            matched, reason, score = _line_matches(line, nested, device=device)
            return matched, reason, score + 10 if matched else 0
        if "protocol" in content_terms:
            nested = SearchInterpretation("PROTOCOL", content_terms["protocol"], "", "")
            matched, reason, score = _line_matches(line, nested, device=device)
            return matched, reason, score + 10 if matched else 0
        return True, "设备元数据", 80
    return False, "", 0


def parse_config_objects(content: str, vendor: str = "") -> list[ConfigObject]:
    """Extract common Cisco IOS, Huawei VRP, and H3C Comware object blocks."""
    lines = content.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    starts: list[tuple[int, str, str]] = []
    patterns = (
        ("interface", re.compile(r"^\s*(?:interface)\s+(.+)$", re.I)),
        ("vlan", re.compile(r"^\s*(?:vlan|vlan\s+batch)\s+(.+)$", re.I)),
        ("acl", re.compile(r"^\s*(?:acl(?:\s+(?:number|name))?|ip\s+access-list)\s+(.+)$", re.I)),
        ("bgp", re.compile(r"^\s*(?:bgp|router\s+bgp)\s+(.+)$", re.I)),
        ("ospf", re.compile(r"^\s*(?:ospf|router\s+ospf)\s*(.*)$", re.I)),
        ("route", re.compile(r"^\s*(?:ip\s+route|ip\s+route-static|ipv6\s+route-static)\s+(.+)$", re.I)),
        ("snmp", re.compile(r"^\s*(?:snmp-agent|snmp-server)\s+(.+)$", re.I)),
        ("ntp", re.compile(r"^\s*(?:ntp-service|ntp)\s+(.+)$", re.I)),
        ("aaa", re.compile(r"^\s*(?:aaa|radius-server|tacacs-server|hwtacacs-server)\b\s*(.*)$", re.I)),
    )
    for index, line in enumerate(lines):
        for object_type, pattern in patterns:
            match = pattern.match(line)
            if match:
                key = (match.group(1) or object_type).strip()[:240]
                starts.append((index, object_type, key))
                break

    objects: list[ConfigObject] = []
    for position, (start, object_type, key) in enumerate(starts):
        next_start = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        end = min(next_start, start + 400)
        block_lines = lines[start:end]
        while block_lines and not block_lines[-1].strip():
            block_lines.pop()
        if object_type in {"route", "snmp", "ntp"}:
            block_lines = block_lines[:1]
        objects.append(
            ConfigObject(
                object_type=object_type,
                object_key=key,
                start_line=start + 1,
                end_line=start + max(1, len(block_lines)),
                search_text="\n".join(block_lines)[:20_000],
                attributes={},
            )
        )

    # Add leaf objects whose operational meaning would otherwise be hidden
    # inside a parent block.  These expressions intentionally cover equivalent
    # IOS/IOS-XE, VRP, and Comware command families.
    leaf_patterns = (
        (
            "interface_ip",
            re.compile(
                r"^\s*(?:ip\s+address|ipv6\s+address)\s+"
                r"((?:[0-9A-Fa-f:.]+)(?:/\d{1,3})?(?:\s+[0-9.]+)?)",
                re.I,
            ),
        ),
        (
            "static_route",
            re.compile(r"^\s*(?:ip\s+route(?:-static)?|ipv6\s+route(?:-static)?)\s+(.+)$", re.I),
        ),
        (
            "ospf_network",
            re.compile(r"^\s*(?:network|ospf\s+network-type)\s+(.+)$", re.I),
        ),
        (
            "ospf_neighbor",
            re.compile(r"^\s*(?:peer|neighbor)\s+([0-9A-Fa-f:.]+)(?:\s|$)", re.I),
        ),
        (
            "bgp_peer",
            re.compile(
                r"^\s*(?:peer|neighbor)\s+([0-9A-Fa-f:.]+)\s+"
                r"(?:as-number|remote-as|connect-interface|description|enable|route-policy).*$",
                re.I,
            ),
        ),
        (
            "bgp_network",
            re.compile(r"^\s*network\s+([0-9A-Fa-f:.]+(?:/\d{1,3})?(?:\s+mask\s+[0-9.]+)?)$", re.I),
        ),
        (
            "route_policy",
            re.compile(r"^\s*(?:route-policy|route-map)\s+(.+)$", re.I),
        ),
        (
            "prefix_list",
            re.compile(r"^\s*(?:ip\s+ip-prefix|ip\s+prefix-list|prefix-list)\s+(.+)$", re.I),
        ),
        (
            "local_user",
            re.compile(r"^\s*(?:local-user|username)\s+(\S+).*$", re.I),
        ),
        (
            "vrf",
            re.compile(r"^\s*(?:ip\s+vpn-instance|vrf\s+definition|vrf\s+instance)\s+(.+)$", re.I),
        ),
        (
            "first_hop_redundancy",
            re.compile(r"^\s*(?:vrrp|standby)\s+(.+)$", re.I),
        ),
        (
            "lldp",
            re.compile(r"^\s*(lldp(?:\s+.+)?)$", re.I),
        ),
        (
            "syslog",
            re.compile(r"^\s*(?:info-center|logging)\s+(.+)$", re.I),
        ),
    )
    leaf_objects: list[ConfigObject] = []
    for index, line in enumerate(lines):
        parent = _match_object_for_line(objects, index + 1)
        parent_type = parent.object_type if parent else ""
        for object_type, pattern in leaf_patterns:
            # "network" and "neighbor" only have protocol meaning inside
            # their corresponding process blocks.
            if object_type.startswith("ospf_") and parent_type != "ospf":
                continue
            if object_type.startswith("bgp_") and parent_type != "bgp":
                continue
            match = pattern.match(line)
            if not match:
                continue
            key = (match.group(1) or object_type).strip()[:240]
            if object_type == "static_route" and re.search(r"(?:^|\s)(?:0\.0\.0\.0(?:/0|\s+0\.0\.0\.0)|::/0)(?:\s|$)", key):
                object_type = "default_route"
            leaf_objects.append(
                ConfigObject(
                    object_type=object_type,
                    object_key=key,
                    start_line=index + 1,
                    end_line=index + 1,
                    search_text=line[:20_000],
                    attributes={
                        "parent_type": parent_type,
                        "parent_name": parent.object_key if parent else "",
                        "parser_vendor": str(vendor or "").lower(),
                        "confidence": 0.9 if parent else 0.78,
                    },
                )
            )
            break
    objects.extend(leaf_objects)
    objects.sort(key=lambda item: (item.start_line, item.end_line, item.object_type))
    return objects


def _select_snapshot_rows(conn, scope: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
    clauses = ["1 = 1"]
    params: list[Any] = []
    field_map = {
        "vendors": "COALESCE(cs.vendor, '')",
        "platforms": "COALESCE(d.platform, '')",
        "sites": "COALESCE(NULLIF(s.site_name, ''), NULLIF(s.site_code, ''), NULLIF(d.site, ''))",
        "roles": "COALESCE(d.role, '')",
        "device_ids": "cs.device_id",
        "config_types": "COALESCE(cs.config_type, 'running')",
        "integrity": "COALESCE(cs.integrity_status, 'unknown')",
        "snapshot_ids": "cs.id",
    }
    for key, column in field_map.items():
        values = [str(value) for value in (filters.get(key) or []) if str(value).strip()]
        if not values:
            continue
        placeholders = ",".join("?" for _ in values)
        clauses.append(f"{column} IN ({placeholders})")
        params.extend(values)
    if filters.get("from_time"):
        clauses.append("cs.timestamp >= ?")
        params.append(str(filters["from_time"]))
    if filters.get("to_time"):
        clauses.append("cs.timestamp <= ?")
        params.append(str(filters["to_time"]))
    if scope == "LATEST_VALID_RUNNING":
        clauses.extend(
            [
                "COALESCE(cs.config_type, 'running') = 'running'",
                "COALESCE(cs.integrity_status, 'unknown') NOT IN ('invalid', 'corrupt')",
            ]
        )
    elif scope == "LATEST_RUNNING":
        clauses.append("COALESCE(cs.config_type, 'running') = 'running'")
    elif scope == "RUNNING_HISTORY":
        clauses.append("COALESCE(cs.config_type, 'running') = 'running'")
    elif scope == "STARTUP_HISTORY":
        clauses.append("COALESCE(cs.config_type, 'running') = 'startup'")
    elif scope == "BASELINE":
        clauses.append(
            "EXISTS (SELECT 1 FROM config_baselines cb "
            "WHERE cb.snapshot_id = cs.id AND cb.device_id = cs.device_id)"
        )

    rows = conn.execute(
        f"""
        SELECT cs.id, cs.device_id, cs.hostname, cs.vendor, cs.timestamp,
               cs.trigger, cs.author, cs.file_path, cs.size,
               COALESCE(cs.integrity_status, 'unknown') AS integrity_status,
               COALESCE(cs.lifecycle_status, '') AS lifecycle_status,
               COALESCE(cs.config_type, 'running') AS config_type,
               COALESCE(cs.raw_hash, '') AS raw_hash,
               COALESCE(d.ip_address, '') AS ip_address,
               COALESCE(d.platform, '') AS platform,
               COALESCE(NULLIF(s.site_name, ''), NULLIF(s.site_code, ''), NULLIF(d.site, '')) AS site,
               COALESCE(d.role, '') AS role,
               COALESCE(d.status, '') AS device_status,
               COALESCE(d.hostname, cs.hostname, '') AS device_hostname
        FROM config_snapshots cs
        LEFT JOIN devices d ON d.id = cs.device_id
        LEFT JOIN sites s ON (
            s.id = COALESCE(NULLIF(d.site_id, ''), NULLIF(d.site, ''))
            OR (COALESCE(d.site_id, '') = '' AND (s.site_code = d.site OR s.site_name = d.site))
        )
        WHERE {' AND '.join(clauses)}
        ORDER BY cs.timestamp DESC
        LIMIT {MAX_SNAPSHOT_CANDIDATES}
        """,
        tuple(params),
    ).fetchall()
    mapped = [dict(row) for row in rows]
    if scope in {"HISTORY", "RUNNING_HISTORY", "STARTUP_HISTORY", "TIME_RANGE", "SPECIFIC_VERSION", "BASELINE"}:
        return mapped

    latest: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in mapped:
        device_id = str(row.get("device_id") or "")
        if device_id in seen:
            continue
        seen.add(device_id)
        latest.append(row)
    return latest


def _match_object_for_line(objects: list[ConfigObject], line_number: int) -> ConfigObject | None:
    for item in objects:
        if item.start_line <= line_number <= item.end_line:
            return item
    return None


def _index_snapshot(conn, row: dict[str, Any], content: str, objects: list[ConfigObject]) -> None:
    snapshot_id = str(row["id"])
    content_hash = str(row.get("raw_hash") or "") or hashlib.sha256(content.encode("utf-8")).hexdigest()
    existing = conn.execute(
        "SELECT content_hash, parser_version FROM config_search_documents WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchone()
    if existing and existing["content_hash"] == content_hash and existing["parser_version"] == PARSER_VERSION:
        return
    conn.execute("DELETE FROM config_search_objects WHERE snapshot_id = ?", (snapshot_id,))
    if existing:
        conn.execute(
            """
            UPDATE config_search_documents
            SET device_id = ?, content_hash = ?, parser_version = ?, line_count = ?,
                object_count = ?, index_status = 'ready', error_text = '', indexed_at = ?
            WHERE snapshot_id = ?
            """,
            (
                row["device_id"],
                content_hash,
                PARSER_VERSION,
                len(content.splitlines()),
                len(objects),
                _utc_now(),
                snapshot_id,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO config_search_documents (
                snapshot_id, device_id, content_hash, parser_version, line_count,
                object_count, index_status, error_text, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'ready', '', ?)
            """,
            (
                snapshot_id,
                row["device_id"],
                content_hash,
                PARSER_VERSION,
                len(content.splitlines()),
                len(objects),
                _utc_now(),
            ),
        )
    for item in objects:
        attributes = dict(item.attributes)
        parent_type = str(attributes.get("parent_type") or "")
        parent_name = str(attributes.get("parent_name") or "")
        confidence = float(attributes.get("confidence") or 0.75)
        object_hash = hashlib.sha256(
            f"{item.object_type}|{item.object_key}|{item.search_text}".encode("utf-8")
        ).hexdigest()
        seen = conn.execute(
            """
            SELECT MIN(first_seen_at) AS first_seen_at, MAX(last_seen_at) AS last_seen_at
            FROM config_search_objects
            WHERE device_id = ? AND object_type = ? AND object_key = ?
            """,
            (row["device_id"], item.object_type, item.object_key),
        ).fetchone()
        timestamp = str(row.get("timestamp") or _utc_now())
        first_seen_at = str(seen["first_seen_at"] or timestamp) if seen else timestamp
        conn.execute(
            """
            INSERT INTO config_search_objects (
                id, snapshot_id, device_id, vendor, object_type, object_key,
                start_line, end_line, search_text, attributes_json, parent_type,
                parent_name, object_hash, first_seen_at, last_seen_at,
                current_present, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                str(uuid.uuid4()),
                snapshot_id,
                row["device_id"],
                row.get("vendor") or "",
                item.object_type,
                item.object_key,
                item.start_line,
                item.end_line,
                item.search_text,
                json.dumps(attributes, ensure_ascii=False),
                parent_type,
                parent_name,
                object_hash,
                first_seen_at,
                timestamp,
                confidence,
            ),
        )


def _build_facets(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    fields = ("vendor", "platform", "site", "role", "integrity_status", "config_type")
    facets: dict[str, list[dict[str, Any]]] = {}
    for field in fields:
        counts = Counter(str(item.get(field) or "未设置") for item in results)
        facets[field] = [
            {"value": value, "count": count}
            for value, count in counts.most_common(20)
        ]
    object_counts = Counter(
        str(match.get("object_type") or "line")
        for result in results
        for match in result.get("matches", [])
    )
    facets["object_type"] = [
        {"value": value, "count": count}
        for value, count in object_counts.most_common(20)
    ]
    return facets


def search_configurations(
    *,
    query: str,
    requested_type: str,
    scope: str,
    filters: dict[str, Any],
    page: int,
    page_size: int,
    context_lines: int,
    include_sensitive: bool,
    actor_username: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    interpretation = classify_query(query, requested_type)
    normalized_scope = str(scope or "LATEST_VALID_RUNNING").upper()
    if normalized_scope not in SEARCH_SCOPES:
        raise ValueError("不支持的搜索作用域")
    context_lines = max(0, min(int(context_lines), 8))

    conn = get_db_connection()
    files_read = 0
    matched_results: list[dict[str, Any]] = []
    timeline: dict[str, list[str]] = defaultdict(list)
    index_updates = 0
    try:
        if normalized_scope == "TEMPLATES":
            return _search_templates(
                conn,
                query=query,
                interpretation=interpretation,
                page=page,
                page_size=page_size,
                actor_username=actor_username,
                started=started,
            )
        rows = _select_snapshot_rows(conn, normalized_scope, filters)
        for row in rows:
            if files_read >= MAX_FILE_READS:
                break
            file_path = str(row.get("file_path") or "")
            if not file_path:
                continue
            files_read += 1
            content = _read_config_file(file_path)
            if not content:
                continue
            objects = parse_config_objects(content, str(row.get("vendor") or ""))
            before = conn.execute(
                "SELECT snapshot_id FROM config_search_documents WHERE snapshot_id = ?",
                (row["id"],),
            ).fetchone()
            _index_snapshot(conn, row, content, objects)
            if not before:
                index_updates += 1

            lines = content.replace("\r\n", "\n").replace("\r", "\n").splitlines()
            matches: list[dict[str, Any]] = []
            score = 0
            for index, line in enumerate(lines):
                matched, reason, line_score = _line_matches(
                    line,
                    interpretation,
                    device=row,
                )
                if not matched:
                    continue
                line_number = index + 1
                obj = _match_object_for_line(objects, line_number)
                start = max(0, index - context_lines)
                end = min(len(lines), index + context_lines + 1)
                matches.append(
                    {
                        "line": line_number,
                        "content": redact_config_line(line, include_sensitive),
                        "context": [
                            {
                                "line": context_index + 1,
                                "content": redact_config_line(lines[context_index], include_sensitive),
                            }
                            for context_index in range(start, end)
                        ],
                        "match_reason": reason,
                        "object_type": obj.object_type if obj else "line",
                        "object_key": obj.object_key if obj else "",
                        "score": line_score,
                    }
                )
                score += line_score + (20 if obj else 0)
                if len(matches) >= MAX_MATCHES_PER_DEVICE:
                    break
            if not matches:
                continue
            timestamp = str(row.get("timestamp") or "")
            timeline[str(row["device_id"])].append(timestamp)
            matched_results.append(
                {
                    "device_id": row["device_id"],
                    "hostname": row.get("device_hostname") or row.get("hostname") or "",
                    "ip_address": row.get("ip_address") or "",
                    "vendor": row.get("vendor") or "",
                    "platform": row.get("platform") or "",
                    "site": row.get("site") or "",
                    "role": row.get("role") or "",
                    "device_status": row.get("device_status") or "",
                    "snapshot_id": row["id"],
                    "snapshot_time": timestamp,
                    "trigger": row.get("trigger") or "",
                    "integrity_status": row.get("integrity_status") or "unknown",
                    "config_type": row.get("config_type") or "running",
                    "total_matches": len(matches),
                    "matches": matches,
                    "score": score + min(len(matches), 20) * 5,
                }
            )

        matched_results.sort(
            key=lambda item: (item["score"], item["snapshot_time"]),
            reverse=True,
        )
        total = len(matched_results)
        total_matches = sum(item["total_matches"] for item in matched_results)
        total_objects = len({
            (item["device_id"], match.get("object_type"), match.get("object_key"))
            for item in matched_results
            for match in item.get("matches", [])
            if match.get("object_type") != "line"
        })
        start = (page - 1) * page_size
        paged = matched_results[start : start + page_size]
        for item in paged:
            occurrences = sorted(timeline.get(str(item["device_id"]), []))
            item["first_seen"] = occurrences[0] if occurrences else item["snapshot_time"]
            item["last_seen"] = occurrences[-1] if occurrences else item["snapshot_time"]
            item["occurrence_count"] = len(occurrences) or 1

        duration_ms = int((time.perf_counter() - started) * 1000)
        conn.execute(
            """
            INSERT INTO config_search_audit (
                id, actor_username, query_text, search_type, search_scope,
                filters_json, result_count, duration_ms, created_at,
                result_device_count, result_object_count, result_line_count,
                viewed_sensitive_content
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                actor_username,
                query,
                interpretation.search_type,
                normalized_scope,
                json.dumps(filters, ensure_ascii=False),
                total,
                duration_ms,
                _utc_now(),
                len({item["device_id"] for item in matched_results}),
                total_objects,
                total_matches,
                1 if include_sensitive else 0,
            ),
        )
        conn.commit()
        return {
            "query": query,
            "interpretation": {
                "search_type": interpretation.search_type,
                "normalized_query": interpretation.normalized_query,
                "title": interpretation.title,
                "description": interpretation.description,
                "warnings": list(interpretation.warnings),
            },
            "scope": normalized_scope,
            "summary": {
                "devices": len({item["device_id"] for item in matched_results}),
                "snapshots": total,
                "matches": total_matches,
                "objects": total_objects,
                "searched_snapshots": files_read,
                "index_updates": index_updates,
                "duration_ms": duration_ms,
                "truncated": files_read >= MAX_FILE_READS,
            },
            "facets": _build_facets(matched_results),
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "results": paged,
        }
    finally:
        conn.close()


def _search_templates(
    conn,
    *,
    query: str,
    interpretation: SearchInterpretation,
    page: int,
    page_size: int,
    actor_username: str,
    started: float,
) -> dict[str, Any]:
    """Search reusable templates without mixing them with device snapshots."""
    rows = conn.execute(
        """
        SELECT id, name, vendor, platform_family, category, content,
               current_version, updated_at, source_type, status
        FROM templates
        ORDER BY updated_at DESC, name ASC
        LIMIT 2000
        """
    ).fetchall()
    results: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        lines = str(row.get("content") or "").splitlines()
        matches = []
        device = {
            "vendor": row.get("vendor") or "",
            "platform": row.get("platform_family") or "",
            "site": "",
            "role": "template",
            "hostname": row.get("name") or "",
            "ip_address": "",
        }
        for index, line in enumerate(lines):
            matched, reason, score = _line_matches(line, interpretation, device=device)
            if matched:
                matches.append({
                    "line": index + 1,
                    "content": redact_config_line(line),
                    "context": [{"line": index + 1, "content": redact_config_line(line)}],
                    "match_reason": reason,
                    "object_type": "template",
                    "object_key": row.get("category") or "",
                    "score": score,
                })
            if len(matches) >= MAX_MATCHES_PER_DEVICE:
                break
        if matches:
            results.append({
                "device_id": "",
                "hostname": row.get("name") or "",
                "ip_address": "",
                "vendor": row.get("vendor") or "",
                "platform": row.get("platform_family") or "",
                "site": "",
                "role": "template",
                "device_status": row.get("status") or "",
                "snapshot_id": row["id"],
                "snapshot_time": row.get("updated_at") or "",
                "trigger": row.get("source_type") or "",
                "integrity_status": "verified",
                "config_type": "template",
                "total_matches": len(matches),
                "matches": matches,
                "score": sum(item["score"] for item in matches),
                "first_seen": row.get("updated_at") or "",
                "last_seen": row.get("updated_at") or "",
                "occurrence_count": 1,
            })
    results.sort(key=lambda item: item["score"], reverse=True)
    total = len(results)
    duration_ms = int((time.perf_counter() - started) * 1000)
    start = (page - 1) * page_size
    conn.execute(
        """
        INSERT INTO config_search_audit (
            id, actor_username, query_text, search_type, search_scope,
            filters_json, result_count, duration_ms, created_at,
            result_device_count, result_object_count, result_line_count
        ) VALUES (?, ?, ?, ?, 'TEMPLATES', '{}', ?, ?, ?, 0, ?, ?)
        """,
        (
            str(uuid.uuid4()), actor_username, query, interpretation.search_type,
            total, duration_ms, _utc_now(), total,
            sum(item["total_matches"] for item in results),
        ),
    )
    conn.commit()
    return {
        "query": query,
        "interpretation": {
            "search_type": interpretation.search_type,
            "normalized_query": interpretation.normalized_query,
            "title": interpretation.title,
            "description": interpretation.description,
            "warnings": list(interpretation.warnings),
        },
        "scope": "TEMPLATES",
        "summary": {
            "devices": 0,
            "snapshots": total,
            "matches": sum(item["total_matches"] for item in results),
            "objects": total,
            "searched_snapshots": len(rows),
            "index_updates": 0,
            "duration_ms": duration_ms,
            "truncated": False,
        },
        "facets": _build_facets(results),
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "results": results[start:start + page_size],
    }


def rebuild_index(
    *,
    limit: int = MAX_FILE_READS,
    scope_type: str = "all",
    scope_value: str = "",
) -> dict[str, Any]:
    conn = get_db_connection()
    indexed = 0
    failed = 0
    objects_count = 0
    try:
        clauses = ["1 = 1"]
        params: list[Any] = []
        if scope_type == "device" and scope_value:
            clauses.append("cs.device_id = ?")
            params.append(scope_value)
        elif scope_type == "platform" and scope_value:
            clauses.append("LOWER(COALESCE(d.platform, '')) = ?")
            params.append(scope_value.lower())
        elif scope_type == "parser_version" and scope_value:
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM config_search_documents sd "
                "WHERE sd.snapshot_id = cs.id AND sd.parser_version = ?)"
            )
            params.append(scope_value)
        rows = conn.execute(
            f"""
            SELECT cs.id, cs.device_id, cs.vendor, cs.file_path, cs.raw_hash, cs.timestamp
            FROM config_snapshots cs
            LEFT JOIN devices d ON d.id = cs.device_id
            WHERE {' AND '.join(clauses)}
            ORDER BY cs.timestamp DESC
            LIMIT {max(1, min(int(limit), MAX_SNAPSHOT_CANDIDATES))}
            """,
            tuple(params),
        ).fetchall()
        for raw_row in rows:
            row = dict(raw_row)
            content = _read_config_file(str(row.get("file_path") or ""))
            if not content:
                failed += 1
                continue
            objects = parse_config_objects(content, str(row.get("vendor") or ""))
            _index_snapshot(conn, row, content, objects)
            indexed += 1
            objects_count += len(objects)
        conn.commit()
        return {
            "indexed_snapshots": indexed,
            "parsed_objects": objects_count,
            "failed_snapshots": failed,
            "parser_version": PARSER_VERSION,
            "scope_type": scope_type,
            "scope_value": scope_value,
        }
    finally:
        conn.close()


def index_status() -> dict[str, Any]:
    conn = get_db_connection()
    try:
        snapshot_count = conn.execute("SELECT COUNT(*) AS count FROM config_snapshots").fetchone()["count"]
        document_count = conn.execute("SELECT COUNT(*) AS count FROM config_search_documents").fetchone()["count"]
        object_count = conn.execute("SELECT COUNT(*) AS count FROM config_search_objects").fetchone()["count"]
        latest = conn.execute("SELECT MAX(indexed_at) AS latest FROM config_search_documents").fetchone()["latest"]
        return {
            "snapshot_count": int(snapshot_count or 0),
            "indexed_count": int(document_count or 0),
            "object_count": int(object_count or 0),
            "coverage_percent": round((document_count / snapshot_count * 100), 1) if snapshot_count else 100.0,
            "last_indexed_at": latest or "",
            "parser_version": PARSER_VERSION,
        }
    finally:
        conn.close()


def search_suggestions(query: str, limit: int = 12) -> list[dict[str, str]]:
    normalized = str(query or "").strip().lower()
    suggestions: list[dict[str, str]] = []
    common = [
        ("vlan", "协议/对象"),
        ("interface", "对象"),
        ("ospf", "协议"),
        ("bgp", "协议"),
        ("acl", "对象"),
        ("route-static", "命令"),
        ("ntp", "服务"),
        ("snmp", "服务"),
        ("aaa", "安全"),
    ]
    for value, category in common:
        if not normalized or normalized in value:
            suggestions.append({"value": value, "category": category})
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT hostname, ip_address, platform
            FROM devices
            WHERE LOWER(COALESCE(hostname, '')) LIKE ?
               OR LOWER(COALESCE(ip_address, '')) LIKE ?
               OR LOWER(COALESCE(platform, '')) LIKE ?
            ORDER BY hostname
            LIMIT ?
            """,
            (f"%{normalized}%", f"%{normalized}%", f"%{normalized}%", max(1, limit)),
        ).fetchall()
        for row in rows:
            for value, category in (
                (row["hostname"], "设备"),
                (row["ip_address"], "管理地址"),
                (row["platform"], "平台"),
            ):
                if value and (not normalized or normalized in str(value).lower()):
                    suggestions.append({"value": str(value), "category": category})
    finally:
        conn.close()
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for item in suggestions:
        key = item["value"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique
