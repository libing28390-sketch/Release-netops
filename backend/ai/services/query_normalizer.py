"""Deterministic Query Normalizer contract for the Knowledge Engine.

The normalizer is deliberately conservative.  It extracts only evidence that
is present in the operator query; absent entities remain ``None`` and are never
filled from an LLM guess or from a user/session context.  The resulting object
is safe to pass between retrieval stages and to expose in an administrator
debug response (the raw query is represented by a hash only).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


NORMALIZER_VERSION = "query-normalizer-v1"


_VENDOR_ALIASES: dict[str, tuple[str, ...]] = {
    "Huawei": ("huawei", "华为"),
    "Cisco": ("cisco", "思科"),
    "H3C": ("h3c", "新华三", "华三"),
    "Ruijie": ("ruijie", "锐捷"),
    "Juniper": ("juniper", "瞻博", "瞻博网络"),
    "Arista": ("arista",),
}

_PRODUCT_ALIASES: dict[str, str] = {
    "ce68": "CloudEngine 6800",
    "ce6800": "CloudEngine 6800",
    "ce68xx": "CloudEngine 6800",
    "cloudengine6800": "CloudEngine 6800",
    "cloudengine 6800": "CloudEngine 6800",
    "ce88": "CloudEngine 8800",
    "ce8800": "CloudEngine 8800",
    "cloudengine8800": "CloudEngine 8800",
    "cloudengine 8800": "CloudEngine 8800",
    "ce98": "CloudEngine 9800",
    "ce9800": "CloudEngine 9800",
    "cloudengine9800": "CloudEngine 9800",
    "cloudengine 9800": "CloudEngine 9800",
    "xh16800": "CloudEngine 16800",
    "cloudenginexh16800": "CloudEngine 16800",
    "cloudengine xh16800": "CloudEngine 16800",
    "catalyst92": "Catalyst 9200",
    "c9200": "Catalyst 9200",
    "catalyst94": "Catalyst 9400",
    "c9400": "Catalyst 9400",
    "catalyst93": "Catalyst 9300",
    "c9300": "Catalyst 9300",
    "catalyst3850": "Catalyst 3850",
    "c3850": "Catalyst 3850",
    "c9350": "C9350",
    "catalyst95": "Catalyst 9500",
    "c9500": "Catalyst 9500",
    "c9550": "C9550",
    "catalyst96": "Catalyst 9600",
    "c9600": "Catalyst 9600",
    "c9610": "C9610",
    "n3k": "Nexus 3000",
    "nexus3000": "Nexus 3000",
    "nexus 3000": "Nexus 3000",
    "nexus3550": "Nexus 3550",
    "nexus 3550": "Nexus 3550",
    "n9k": "Nexus 9000",
    "nexus9000": "Nexus 9000",
    "nexus 9000": "Nexus 9000",
    "s6520x": "S6520X",
}

_FEATURE_ALIASES: dict[str, tuple[str, ...]] = {
    "ospf": ("ospf", "tospf", "开放式最短路径优先"),
    "bgp": ("bgp", "边界网关协议"),
    "arp": ("arp", "地址解析"),
    "vlan": ("vlan", "vlna", "虚拟局域网"),
    "stp": ("stp", "生成树"),
    # Do not use a bare ``acces`` prefix: it also matches ``access-list`` and
    # turns ACL queries into access-port queries.
    "access_port": (
        "access port", "access-port", "acces port", "vlan + access", "vlan+access",
        "接入口", "接入端口",
    ),
    "port_security": ("port security", "port-security", "端口安全"),
    "trunk": ("trunk", "中继端口", "trunk端口"),
    "lacp": ("lacp", "eth-trunk", "etherchannel", "bridge-aggregation", "aggregateport", "port-group", "链路聚合", "聚合口"),
    "loopback": ("loopback", "环回接口", "环回口"),
    "static_route": ("static route", "static-route", "static routing", "静态路由", "ip route-static", "ip route"),
    "ntp": ("ntp", "网络时间协议"),
    "snmp": ("snmp", "snmpv3", "简单网络管理协议"),
    "ssh": ("ssh", "stelnet", "secure shell", "安全登录"),
    "bfd": ("bfd", "双向转发检测"),
    "pam": ("pam", "aaa", "super password", "权限管理", "身份认证"),
    "system_monitoring": ("cpu-usage", "cpu usage", "memory-usage", "memory usage", "设备状态"),
    "interface": ("interface brief", "display interface brief", "interface status", "switchport", "uplink", "接口简要", "接口状态", "上联"),
    "vrrp": ("vrrp", "网关冗余", "虚拟路由器冗余"),
    "lldp": ("lldp", "链路层发现"),
    "evpn": ("evpn",),
    "vxlan": ("vxlan",),
    "acl": ("acl", "access-list", "standard access-list", "packet-filter", "访问控制列表"),
}

_COMPOSITE_ACCESS_PORT_RE = re.compile(
    r"(?<![a-z0-9])vlan\s*\+\s*access(?![a-z0-9])",
    re.IGNORECASE,
)

_OS_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("IOS XE", ("ios-xe", "ios xe", "iosxe")),
    ("IOS XR", ("ios-xr", "ios xr", "iosxr")),
    ("NX-OS", ("nx-os", "nx os", "nxos")),
    ("IOS", ("ios",)),
    ("VRP", ("vrp", "vrp5", "vrp8")),
    ("Comware", ("comware", "comware 7", "cmw710")),
    ("Junos", ("junos",)),
    ("YunShan OS", ("yunshan", "云杉")),
)

_REDaction_RE = re.compile(
    r"(?i)(?:api[_ -]?key|token|secret|password|passwd|community)\s*[:=]\s*[^\s,;]+"
)
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:-]{1,127}")
_MODEL_RE = re.compile(
    # ``\b`` misses models adjacent to Chinese characters.  Restrict the
    # boundary to ASCII letters/digits so ``交换机S5700的`` is normalized just
    # like ``交换机 S5700 的`` without matching the middle of an ASCII token.
    r"(?i)(?<![A-Z0-9])(?:N[3579]K-[A-Z0-9-]+|Nexus\s*(?:3000|3550|9000)(?:\s+Series)?|"
    r"CE\s*\d{2,5}[A-Z0-9-]*|Catalyst\s*\d{2,5}[A-Z0-9-]*|C\s*\d{3,4}[A-Z0-9-]*|"
    r"S\d{2,5}[A-Z]?(?:[-_][A-Z0-9]+)*|RG-[A-Z0-9-]+)(?![A-Z0-9])"
)
# A dotted IPv4 literal is an entity, not a software release.  Numeric
# releases are intentionally limited to two or three components and bounded
# by non-dot characters, so ``0.0.0.0`` in a default-route query cannot become
# a release filter and silently eliminate otherwise valid Cisco documents.
_VERSION_RE = re.compile(
    r"(?i)(?:\bV\d{3,4}(?:R\d+[A-Z]?\d*)?|\b(?<![\w.])\d+\.\d+(?:\.\d+)?(?![\d.]))"
)
_COMMAND_RE = re.compile(
    r"(?im)(?<![A-Za-z])(?:display|show|system-view|configure\s+terminal|conf\s+t|"
    r"interface|undo|no|router\s+(?:ospf|bgp)|ip\s+route)\b[^\n;]{0,180}"
)
_ERROR_RE = re.compile(
    r"(?i)\b(?:error|failed|failure|down|timeout|unreachable|not\s+found|"
    r"拒绝|失败|故障|中断|超时|不可达|down)\b(?:[^\n,;]{0,100})"
)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _redacted(value: str) -> str:
    return _REDaction_RE.sub(lambda m: m.group(0).split("=", 1)[0].split(":", 1)[0] + "=<redacted>", value)


def _first_alias(text: str, aliases: Mapping[str, tuple[str, ...]]) -> Optional[str]:
    lower = text.lower()
    hits = [(canonical, min(lower.find(alias.lower()) for alias in values if alias.lower() in lower)) for canonical, values in aliases.items() if any(alias.lower() in lower for alias in values)]
    return min(hits, key=lambda item: item[1])[0] if hits else None


def _canonical_product(raw: str) -> str:
    normalized = re.sub(r"\s+", "", raw).replace("-", "-").lower()
    if re.fullmatch(r"ce6\d{2,4}[a-z0-9-]*", normalized):
        return "CloudEngine 6800"
    if re.fullmatch(r"ce8\d{2,4}[a-z0-9-]*", normalized):
        return "CloudEngine 8800"
    if re.fullmatch(r"ce9\d{2,4}[a-z0-9-]*", normalized):
        return "CloudEngine 9800"
    if re.fullmatch(r"xh16800(?:-[a-z0-9-]+)?", normalized):
        return "CloudEngine 16800"
    if re.fullmatch(r"(?:c9200|catalyst92)[a-z0-9-]*", normalized):
        return "Catalyst 9200"
    if re.fullmatch(r"(?:c9300|catalyst93)[a-z0-9-]*", normalized):
        return "Catalyst 9300"
    if re.fullmatch(r"(?:c9400|catalyst94)[a-z0-9-]*", normalized):
        return "Catalyst 9400"
    if re.fullmatch(r"(?:c9500|catalyst95)[a-z0-9-]*", normalized):
        return "Catalyst 9500"
    if re.fullmatch(r"(?:c9600|catalyst96)[a-z0-9-]*", normalized):
        return "Catalyst 9600"
    if re.fullmatch(r"c9350[a-z0-9-]*", normalized):
        return "C9350"
    if re.fullmatch(r"c9550[a-z0-9-]*", normalized):
        return "C9550"
    if re.fullmatch(r"c9610[a-z0-9-]*", normalized):
        return "C9610"
    if re.fullmatch(r"n3k-[a-z0-9-]+", normalized) or re.fullmatch(r"nexus3\d{3}", normalized):
        return "Nexus 3000"
    if re.fullmatch(r"nexus3550", normalized):
        return "Nexus 3550"
    if re.fullmatch(r"n9k-[a-z0-9-]+", normalized) or re.fullmatch(r"nexus9\d{3}", normalized):
        return "Nexus 9000"
    return _PRODUCT_ALIASES.get(normalized, _PRODUCT_ALIASES.get(raw.lower(), raw.replace(" ", "")))


@dataclass(frozen=True)
class NormalizedQuery:
    """Stable, serializable query representation shared by all RET stages."""

    normalizer_version: str
    normalized_text: str
    query_hash: str
    intent: str
    topic: Optional[str] = None
    vendor: Optional[str] = None
    product: Optional[str] = None
    model: Optional[str] = None
    os_family: Optional[str] = None
    generation: Optional[str] = None
    version: Optional[str] = None
    command: Optional[str] = None
    error: Optional[str] = None
    document_category: Optional[str] = None
    tokens: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    tenant_id: str = "tenant-default"
    access_scope: str = "default"

    @property
    def entities(self) -> dict[str, Optional[str]]:
        return {
            "vendor": self.vendor,
            "product": self.product,
            "model": self.model,
            "os_family": self.os_family,
            "generation": self.generation,
            "version": self.version,
            "topic": self.topic,
            "command": self.command,
            "error": self.error,
            "intent": self.intent,
        }

    def to_dict(self, *, include_tokens: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "normalizer_version": self.normalizer_version,
            "normalized_text": self.normalized_text,
            "query_hash": self.query_hash,
            "intent": self.intent,
            "entities": self.entities,
            "document_category": self.document_category,
            "warnings": list(self.warnings),
            "tenant_id": self.tenant_id,
            "access_scope": self.access_scope,
        }
        if include_tokens:
            result["tokens"] = list(self.tokens)
        return result


def normalize_query(query: str, *, tenant_id: str = "tenant-default", access_scope: str = "default") -> NormalizedQuery:
    """Normalize an operator query without making unsupported inferences."""

    raw = _clean(query)
    safe = _redacted(raw)
    text = safe[:20000]
    lower = text.lower()
    warnings: list[str] = []
    if len(raw) > len(text):
        warnings.append("query_truncated")
    if safe != raw:
        warnings.append("sensitive_literal_redacted")

    vendor = _first_alias(text, _VENDOR_ALIASES)
    product_match = _MODEL_RE.search(text)
    model = None
    product = None
    if product_match:
        token = re.sub(r"\s+", "", product_match.group(0)).upper()
        canonical = _canonical_product(token)
        upper_token = token.upper()
        if upper_token.startswith(("CE", "XH16800", "C9200", "C9300", "C9350", "C9400", "C9500", "C9550", "C9600", "C9610", "CATALYST", "N3K-", "N9K-", "NEXUS")):
            product = canonical if canonical != token else token
            if canonical != token and token not in {"CE6800", "CE68XX"} and not token.upper().startswith(("CATALYST", "NEXUS")):
                model = token
            elif upper_token.startswith(("C9", "N[3579]K-")) and not upper_token.startswith("CATALYST"):
                model = token
        elif upper_token.startswith(("S", "RG-")):
            # Huawei S-series identifiers are product-series scopes in the
            # catalog.  Even a concrete-looking S5735-L-V2 token must not be
            # promoted to a model identity before the reviewed hierarchy
            # resolver has selected a model.
            # A suffix beginning with a port count (S9825-64D) is a concrete
            # SKU.  Preserve the model token while using the base series for
            # the catalog hard gate.  Family variants such as S5735-L-V2
            # remain a series scope for backwards compatibility.
            parts = token.split("-")
            if len(parts) > 1 and (parts[1][:1].isdigit() or any(char.isdigit() for char in parts[1])):
                product = parts[0]
                if parts[1][:1].isalpha():
                    product = f"{parts[0]}-{re.match(r'[A-Z]+', parts[1]).group(0)}"
                model = token
            else:
                product = canonical if canonical != token else token
                model = None

    os_family = _first_alias(text, dict(_OS_ALIASES))
    generation = None
    # IOS-XE/IOS-XR are OS families, not a narrower software-generation
    # boundary.  Treating them as ``os_generation`` made the SQL gate require
    # a column value that many reviewed documents intentionally leave NULL.
    # Keep only explicit VRP/Comware generation markers here.
    generation_match = re.search(r"(?i)\b(?:VRP\s*[58]|COMWARE\s*7)\b", text)
    if generation_match:
        generation = generation_match.group(0).upper().replace(" ", "-")
    version_match = _VERSION_RE.search(text)
    version = version_match.group(0).upper() if version_match else None

    # ``VLAN + Access`` contains the generic VLAN alias at the same position
    # as the more specific access-port phrase.  Give the composite intent an
    # explicit priority so normalization agrees with the metadata parser.
    topic = (
        "access_port"
        if _COMPOSITE_ACCESS_PORT_RE.search(lower)
        else _first_alias(text, _FEATURE_ALIASES)
    )
    command_match = _COMMAND_RE.search(text)
    command = _clean(command_match.group(0)) if command_match else None
    error_match = _ERROR_RE.search(text)
    error = _clean(error_match.group(0)) if error_match else None

    if any(marker in lower for marker in ("配置", "config", "configure", "下发", "修改")):
        intent, category = "configuration", "configuration"
    elif any(marker in lower for marker in ("故障", "排障", "troubleshoot", "故障排查")):
        intent, category = "troubleshooting", "troubleshooting"
    elif command or any(marker in lower for marker in ("回显", "输出", "meaning", "output")):
        intent, category = "cli_output", "cli_output"
    elif any(marker in lower for marker in ("failed", "error", "down", "超时", "不可达")):
        intent, category = "troubleshooting", "troubleshooting"
    elif any(marker in lower for marker in ("型号", "规格", "硬件", "product", "hardware")):
        intent, category = "product", "hardware"
    else:
        intent, category = "knowledge", None

    tokens = tuple(dict.fromkeys(token.lower() for token in _ASCII_TOKEN_RE.findall(text) if len(token) > 1))
    return NormalizedQuery(
        normalizer_version=NORMALIZER_VERSION,
        normalized_text=text,
        query_hash=hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest(),
        intent=intent,
        topic=topic,
        vendor=vendor,
        product=product,
        model=model,
        os_family=os_family,
        generation=generation,
        version=version,
        command=command,
        error=error,
        document_category=category,
        tokens=tokens,
        warnings=tuple(warnings),
        tenant_id=str(tenant_id or "tenant-default"),
        access_scope=str(access_scope or "default"),
    )


__all__ = ["NORMALIZER_VERSION", "NormalizedQuery", "normalize_query"]
