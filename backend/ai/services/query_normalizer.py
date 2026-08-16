"""Deterministic Query Normalizer contract for Knowledge Engine V2.

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
    "catalyst93": "Catalyst 9300",
    "c9300": "Catalyst 9300",
    "s6520x": "S6520X",
}

_FEATURE_ALIASES: dict[str, tuple[str, ...]] = {
    "ospf": ("ospf", "tospf", "开放式最短路径优先"),
    "bgp": ("bgp", "边界网关协议"),
    "arp": ("arp", "地址解析"),
    "vlan": ("vlan", "虚拟局域网"),
    "stp": ("stp", "生成树"),
    "lldp": ("lldp", "链路层发现"),
    "evpn": ("evpn",),
    "vxlan": ("vxlan",),
    "acl": ("acl", "访问控制列表"),
}

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
    r"(?i)\b(?:CE\s*\d{2,5}[A-Z0-9-]*|C\s*\d{3,4}|Catalyst\s*\d{2,5}[A-Z0-9-]*|"
    r"S\d{2,5}(?:[-_][A-Z0-9]+)*|RG-[A-Z0-9-]+)\b"
)
_VERSION_RE = re.compile(r"(?i)\b(?:V\d{3,4}(?:R\d+[A-Z]?\d*)?|\d+\.\d+(?:\.\d+){0,2})\b")
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
    if re.fullmatch(r"(?:c9300|catalyst93)\w*", normalized):
        return "Catalyst 9300"
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
        if token.upper().startswith(("CE", "C9300", "CATALYST93")):
            product = canonical if canonical != token else token
            if canonical != token and token not in {"CE6800", "CE68XX"}:
                model = token
        elif token.upper().startswith(("S", "RG-")):
            product = canonical if canonical != token else token
            model = token if re.search(r"[-_]", token) else None

    os_family = _first_alias(text, dict(_OS_ALIASES))
    generation = None
    generation_match = re.search(r"(?i)\b(?:VRP\s*[58]|IOS\s*(?:XE|XR)|COMWARE\s*7)\b", text)
    if generation_match:
        generation = generation_match.group(0).upper().replace(" ", "-")
    version_match = _VERSION_RE.search(text)
    version = version_match.group(0).upper() if version_match else None

    topic = _first_alias(text, _FEATURE_ALIASES)
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
