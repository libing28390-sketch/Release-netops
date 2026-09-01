"""
AI Intent Parser for Natural Language Query Recognition
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional
from pydantic import ValidationError
from ai.gateway.llm_gateway import llm_gateway
from ai.services.metrics import ai_metrics
from ai.services.query_normalizer import normalize_query
from ai.schemas.intent import IntentDecision, IntentRiskLevel, IntentType


# Keep the internal prompt version in a format that cannot be mistaken for a
# network hostname by the pre-egress security classifier.  A hyphenated value
# such as ``intent-v1`` matches the classifier's legacy short-hostname pattern
# and incorrectly upgrades even a generic prompt to CONFIDENTIAL.
INTENT_PROMPT_VERSION = "intent.v1"
logger = logging.getLogger(__name__)


_ASSET_ANALYSIS_AGGREGATION_MARKERS = (
    "\u7edf\u8ba1", "\u5206\u5e03", "\u5360\u6bd4", "\u805a\u5408", "\u6c47\u603b",
    "\u6982\u89c8", "\u5206\u6790", "\u6458\u8981", "\u6e05\u5355", "\u7eb3\u7ba1",
    "\u591a\u5c11\u53f0", "\u51e0\u53f0", "\u6570\u91cf", "aggregation", "breakdown", "distribution", "inventory overview",
    "how many", "count",
)

_ASSET_ANALYSIS_DIMENSION_MARKERS = (
    ("vendor", "\u5382\u5546", "\u4f9b\u5e94\u5546"),
    ("role", "\u89d2\u8272", "\u6838\u5fc3", "\u6c47\u805a", "\u63a5\u5165"),
    ("type", "\u7c7b\u578b", "\u4ea4\u6362\u673a", "\u8def\u7531\u5668", "\u9632\u706b\u5899"),
    ("version", "\u7248\u672c", "\u8f6f\u4ef6", "\u56fa\u4ef6", "eol"),
    ("site", "\u533a\u57df", "\u673a\u623f", "\u5730\u57df"),
    ("health", "\u5065\u5eb7", "\u5728\u7ebf", "\u544a\u8b66"),
)

_INTENT_RESPONSE_SCHEMA = json.dumps(
    IntentDecision.model_json_schema(),
    ensure_ascii=False,
    separators=(",", ":"),
)

_INTENT_FILTER_KEYS = frozenset({
    "ip", "mac", "device_id", "device_identifier", "device_name", "interface",
    "vendor", "product_family", "product_series", "product_model", "role",
    "device_category", "site", "status", "keyword", "query", "protocol",
    "metric", "time_range", "alarm_id", "command", "action", "platform", "os",
    "os_family", "os_generation", "software_train", "software_release",
    "cli_platform", "document_category", "knowledge_type", "request_type",
    "feature_domain", "feature", "subfeature", "filters",
})

_KNOWLEDGE_METADATA_KEYS = frozenset({
    "request_type", "knowledge_type", "vendor", "product_family",
    "product_series", "product_model", "os_family", "os_generation",
    "software_train", "software_release", "cli_platform", "document_category",
    "feature_domain", "feature", "subfeature", "device_identifier",
    "query_normalization",
})

_DANGEROUS_INTENT_MARKERS = (
    "shutdown", "reload", "reboot", "reset", "erase", "delete config",
    "下发配置", "修改配置", "变更配置", "删除配置", "清空配置", "重启设备", "重载设备",
)

_EXECUTION_INTENT_MARKERS = (
    "execute", "apply", "commit", "下发", "修改", "变更", "执行命令", "执行配置",
)
_IP_LITERAL_RE = re.compile(
    r"(?<![\w.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\w.])"
)
_MAC_LITERAL_RE = re.compile(r"(?i)(?<![\w])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![\w])")


def _bounded_json_value(value: Any, *, depth: int = 0) -> Any:
    """Keep model-controlled filter data bounded and JSON-compatible."""

    if depth >= 2:
        return str(value)[:512]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:512]
    if isinstance(value, list):
        return [_bounded_json_value(item, depth=depth + 1) for item in value[:32]]
    if isinstance(value, dict):
        return {
            str(key)[:64]: _bounded_json_value(item, depth=depth + 1)
            for key, item in list(value.items())[:32]
        }
    return str(value)[:512]


def _safe_mapping(value: Any, allowed_keys: frozenset[str]) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): _bounded_json_value(item)
        for key, item in value.items()
        if str(key).strip() in allowed_keys
    }


def _deterministic_identifier_intent(query: str) -> IntentDecision | None:
    """Recognize read-only IP/MAC location requests without cloud parsing.

    IP and MAC values are intentionally classified as confidential by the
    security gateway.  These requests already have an unambiguous local
    operation, so asking a cloud model to identify the intent only creates an
    avoidable classification failure and a misleading generic fallback.
    """

    normalized = " ".join((query or "").strip().split())
    lower = normalized.lower()
    ip_match = _IP_LITERAL_RE.search(normalized)
    mac_match = _MAC_LITERAL_RE.search(normalized)
    ip_markers = ("定位", "追踪", "查找", "ip location", "trace ip", "locate ip", "where is ip")
    mac_markers = ("定位", "追踪", "查找", "mac location", "trace mac", "locate mac", "where is mac")

    if ip_match and ("ip" in lower or any(marker in lower for marker in ip_markers)):
        return IntentDecision(
            intent=IntentType.IP_LOCATION,
            filters={"ip": ip_match.group(0)},
            confidence=1.0,
        )
    if mac_match and ("mac" in lower or any(marker in lower for marker in mac_markers)):
        return IntentDecision(
            intent=IntentType.MAC_LOCATION,
            filters={"mac": mac_match.group(0).lower()},
            confidence=1.0,
        )

    if any(marker in lower for marker in ip_markers) and re.search(r"\bip\b|ip地址|ip address", lower):
        return IntentDecision(
            intent=IntentType.IP_LOCATION,
            confidence=1.0,
            needs_clarification=True,
            missing_fields=["ip"],
            clarification_question="请提供需要定位的 IP 地址。",
        )
    if any(marker in lower for marker in mac_markers) and re.search(r"\bmac\b|mac地址|mac address", lower):
        return IntentDecision(
            intent=IntentType.MAC_LOCATION,
            confidence=1.0,
            needs_clarification=True,
            missing_fields=["mac"],
            clarification_question="请提供需要定位的 MAC 地址。",
        )
    return None


def is_asset_analysis_query(query: str) -> bool:
    """Return whether a query needs deterministic CMDB aggregation.

    LLM intent parsing is useful for open-ended questions, but it must not
    decide whether a factual inventory report is allowed to invent fields.
    Queries that ask for an inventory/distribution/aggregation report are
    routed to the read-only PostgreSQL analytics path before the LLM parser.
    """
    normalized = " ".join((query or "").lower().split())
    if not normalized:
        return False

    inventory_markers = ("\u8bbe\u5907", "\u8d44\u4ea7", "cmdb", "\u7eb3\u7ba1")
    has_inventory_scope = any(marker in normalized for marker in inventory_markers)
    has_aggregation = any(marker in normalized for marker in _ASSET_ANALYSIS_AGGREGATION_MARKERS)
    dimension_hits = sum(
        1 for _name, *markers in _ASSET_ANALYSIS_DIMENSION_MARKERS
        if any(marker in normalized for marker in markers)
    )

    return has_inventory_scope and (has_aggregation or dimension_hits >= 2)


def extract_asset_filters(query: str) -> Dict[str, str]:
    """Extract only unambiguous, low-risk CMDB filters without an LLM."""
    normalized = " ".join((query or "").lower().split())
    filters: Dict[str, str] = {}
    vendor_aliases = {
        "huawei": ("huawei", "\u534e\u4e3a"),
        "cisco": ("cisco", "\u601d\u79d1"),
        "h3c": ("h3c",),
        "juniper": ("juniper",),
    }
    for canonical, aliases in vendor_aliases.items():
        if any(alias in normalized for alias in aliases):
            filters["vendor"] = canonical
            break

    role_aliases = {
        "core": ("\u6838\u5fc3",),
        "distribution": ("\u6c47\u805a",),
        "access": ("\u63a5\u5165",),
        "firewall": ("\u9632\u706b\u5899",),
    }
    for canonical, aliases in role_aliases.items():
        if any(alias in normalized for alias in aliases):
            filters["role"] = canonical
            break

    type_aliases = {
        "switch": ("\u4ea4\u6362\u673a",),
        "router": ("\u8def\u7531\u5668",),
        "firewall": ("\u9632\u706b\u5899",),
    }
    for canonical, aliases in type_aliases.items():
        if any(alias in normalized for alias in aliases):
            filters["device_category"] = canonical
            break

    status_aliases = {
        "online": ("\u5728\u7ebf",),
        "offline": ("\u79bb\u7ebf",),
    }
    for canonical, aliases in status_aliases.items():
        if any(alias in normalized for alias in aliases):
            filters["status"] = canonical
            break

    site_match = re.search(r"(?:wh[-_ ]?dc[-_ ]?\d+|site-[a-z0-9]+)", normalized, re.IGNORECASE)
    if site_match:
        filters["site"] = site_match.group(0).replace(" ", "").upper()
    return filters


class IntentParser:
    """Parses natural language queries into structured intent & filter parameters."""

    _VENDOR_ALIASES = {
        "Huawei": ("huawei", "华为"),
        "H3C": ("h3c", "新华三", "华三"),
        "Cisco": ("cisco", "思科"),
        "Ruijie": ("ruijie", "锐捷"),
    }
    _FEATURE_ALIASES = {
        # Keep the common ``Tospf`` input typo searchable as OSPF; it is used
        # in existing operator queries and otherwise gets lost at tokenisation.
        "ospf": ("ospf", "tospf", "开放式最短路径优先"),
        "arp": ("arp", "地址解析"),
        "vlan": ("vlan", "虚拟局域网"),
        "bgp": ("bgp",),
        "stp": ("stp", "生成树"),
        "access_port": ("access port", "access-port", "接入口", "接入端口"),
        "trunk": ("trunk", "中继端口", "trunk端口"),
        "lacp": ("lacp", "eth-trunk", "etherchannel", "bridge-aggregation", "链路聚合"),
        "loopback": ("loopback", "环回接口", "环回口"),
        "ntp": ("ntp", "网络时间协议"),
        "snmp": ("snmp", "snmpv3", "简单网络管理协议"),
        "vrrp": ("vrrp", "虚拟路由器冗余"),
        "vxlan": ("vxlan",),
        "evpn": ("evpn",),
        "acl": ("acl", "访问控制列表"),
        "static_route": ("static route", "static-route", "static routing", "静态路由", "ip route-static"),
        "ssh": ("ssh", "stelnet", "secure shell", "安全登录"),
        "lldp": ("lldp", "链路层发现"),
    }

    @staticmethod
    def _normalise_product(query: str) -> tuple[Optional[str], Optional[str]]:
        text = query or ""
        upper = text.upper()
        # Product Registry aliases are resolved to the canonical series.  The
        # model token is retained separately when it is explicit.
        named_ce = re.search(r"(?<![A-Z0-9])CLOUDENGINE\s*(6800|8800|9800)(?![A-Z0-9])", upper)
        if named_ce:
            return f"CloudEngine {named_ce.group(1)}", None
        ce_alias = re.search(r"(?<![A-Z0-9])CE\s*(68|88|98)(?:XX)?(?![A-Z0-9])", upper)
        if ce_alias:
            return {"68": "CloudEngine 6800", "88": "CloudEngine 8800", "98": "CloudEngine 9800"}[ce_alias.group(1)], None
        ce_match = re.search(r"(?<![A-Z0-9])(?:CLOUDENGINE\s*)?CE\s*(6|8|9)(?:\d{2,4})(?:[A-Z0-9-]*)?(?![A-Z0-9])", upper)
        if ce_match:
            token = ce_match.group(0).replace(" ", "")
            family = {"6": "CloudEngine 6800", "8": "CloudEngine 8800", "9": "CloudEngine 9800"}[ce_match.group(1)]
            model = token if token not in {"CE6800", "CE68XX", "CE8800", "CE98XX", "CE9800"} else None
            return family, model
        xh_match = re.search(r"(?<![A-Z0-9])(?:CLOUDENGINE\s*)?XH16800(?:-[A-Z0-9-]+)?(?![A-Z0-9])", upper)
        if xh_match:
            token = xh_match.group(0).replace(" ", "")
            return "CloudEngine 16800", (None if token == "XH16800" else token)
        for prefix, series in (
            ("C9350", "C9350"),
            ("C9550", "C9550"),
            ("C9610", "C9610"),
        ):
            exact = re.search(rf"(?<![A-Z0-9]){prefix}(?:-[A-Z0-9-]+)?(?![A-Z0-9])", upper)
            if exact:
                token = exact.group(0)
                return series, (None if token == prefix else token)
        catalyst_match = re.search(
            r"(?<![A-Z0-9])(?:CATALYST\s*)?C?(9200|9300|9400|9500|9600)(?:[A-Z0-9-]*)?(?![A-Z0-9])",
            upper,
        )
        if catalyst_match:
            number = catalyst_match.group(1)
            series = f"Catalyst {number}"
            token = catalyst_match.group(0).replace(" ", "")
            return series, (None if token in {f"C{number}", f"CATALYST{number}"} else token)
        nexus_sku = re.search(r"(?<![A-Z0-9])N([39])K-[A-Z0-9-]+(?![A-Z0-9])", upper)
        if nexus_sku:
            token = nexus_sku.group(0)
            return f"Nexus {'3000' if nexus_sku.group(1) == '3' else '9000'}", token
        nexus_match = re.search(r"(?<![A-Z0-9])NEXUS\s*(3000|3550|9000)(?:\s+SERIES)?(?![A-Z0-9])", upper)
        if nexus_match:
            number = nexus_match.group(1)
            return f"Nexus {number}", None
        # Operators commonly type a short Huawei family prefix (for example
        # S57) rather than a complete S5735-L-V2 model.  Keep the prefix as a
        # search scope; the resolver will expand it against registry series.
        # ``\b`` is ASCII-word based and does not create a boundary between
        # Chinese text and an adjacent ASCII model (``交换机S5700的``).  Use
        # ASCII lookarounds so mixed-language operator queries keep the model.
        product_match = re.search(
            r"(?<![A-Z0-9])S\d{2,5}[A-Z]?(?:[-_][A-Z0-9]+)*(?![A-Z0-9])",
            upper,
        )
        if product_match:
            token = product_match.group(0).replace("_", "-")
            # A series token such as S5735-L-V2 is not a concrete model.  Do
            # not over-constrain retrieval to a literal model column.
            parts = token.split("-")
            if len(parts) > 1 and (parts[1][:1].isdigit() or any(char.isdigit() for char in parts[1])):
                series = parts[0]
                if parts[1][:1].isalpha():
                    series = f"{parts[0]}-{re.match(r'[A-Z]+', parts[1]).group(0)}"
                return series, token
            return token, None
        return None, None

    def parse_knowledge_metadata(self, query: str) -> Dict[str, Any]:
        """Deterministically extract the RAG v2 metadata contract.

        This conservative path is used before an LLM.  It only emits a
        platform when the query contains an explicit platform/train context;
        software train alone is left for the Product Registry resolver.
        """

        normalized = " ".join((query or "").strip().split())
        normalized_query = normalize_query(normalized)
        lower = normalized.lower()
        result: Dict[str, Any] = {
            "request_type": "knowledge",
            "knowledge_type": "command",
            "vendor": None,
            "product_family": None,
            "product_series": None,
            "product_model": None,
            "os_family": None,
            "os_generation": None,
            "software_train": None,
            "software_release": None,
            "cli_platform": None,
            "document_category": "command",
            "feature_domain": None,
            "feature": None,
            "subfeature": None,
            "device_identifier": None,
            "query_normalization": normalized_query.to_dict(),
        }

        for vendor, aliases in self._VENDOR_ALIASES.items():
            if any(alias in lower for alias in aliases):
                result["vendor"] = vendor
                break
        series, model = self._normalise_product(normalized)
        result["product_series"] = series
        result["product_model"] = model
        if series and not result["vendor"] and (
            series.upper().startswith("CE") or series.lower().startswith("cloudengine")
        ):
            # This is an alias lookup seed, not a CLI/platform inference; the
            # resolver verifies it against Product Registry before filtering.
            result["vendor"] = "Huawei"
        elif series and not result["vendor"] and series.lower().startswith("nexus"):
            # Nexus is a Cisco NX-OS product family; retaining the vendor here
            # lets a bare "Nexus 9000" query use the same scoped RAG path as
            # an explicit "Cisco Nexus 9000" query.
            result["vendor"] = "Cisco"
        elif series and not result["vendor"] and (
            series.lower().startswith("catalyst")
            or series.upper() in {"C9350", "C9550", "C9610"}
        ):
            result["vendor"] = "Cisco"

        train_match = re.search(r"\b(V[236]\d{2})(?:R\d+[A-Z]?\d*)?\b", normalized, re.IGNORECASE)
        if train_match:
            result["software_train"] = train_match.group(1).upper()
        release_match = re.search(r"\b(V[236]\d{2}R\d+[A-Z]?\d*)\b", normalized, re.IGNORECASE)
        if release_match:
            result["software_release"] = release_match.group(1).upper()

        explicit_platforms = (
            ("huawei_yunshan_v600", ("huawei_yunshan_v600", "yunshan v600", "yunshan os v600")),
            ("huawei_yunshan_v300", ("huawei_yunshan_v300", "yunshan v300", "yunshan os v300")),
            ("huawei_vrp5_v200", ("huawei_vrp5_v200", "vrp5 v200", "vrp v200")),
        )
        for platform, aliases in explicit_platforms:
            if any(alias in lower for alias in aliases):
                result["cli_platform"] = platform
                result["os_family"] = "YunShan OS" if "yunshan" in platform else "VRP"
                result["os_generation"] = "VRP5" if "vrp5" in platform else None
                break

        if any(token in lower for token in ("故障", "排障", "排查", "邻居down", "neighbor down", "troubleshoot")):
            result["knowledge_type"] = "troubleshooting"
            result["document_category"] = "troubleshooting"
        elif any(token in lower for token in ("配置", "config", "configuration", "命令行配置")):
            result["knowledge_type"] = "configuration"
            result["document_category"] = "configuration"
        elif any(token in lower for token in ("回显", "输出", "含义", "meaning", "output", "peer brief")):
            result["knowledge_type"] = "cli_output"
            result["document_category"] = "cli_output"
        elif any(token in lower for token in ("是什么设备", "什么设备", "设备信息", "产品", "硬件", "型号", "规格", "hardware")):
            result["knowledge_type"] = "product"
            result["document_category"] = "hardware"
        elif any(token in lower for token in ("示例", "案例", "example")):
            result["knowledge_type"] = "example"
            result["document_category"] = "example"

        for feature, aliases in self._FEATURE_ALIASES.items():
            if any(alias in lower for alias in aliases):
                result["feature"] = feature
                result["feature_domain"] = (
                    "routing" if feature in {"ospf", "bgp", "arp", "loopback", "static_route"}
                    else "switching" if feature in {"vlan", "stp", "lldp", "access_port", "trunk", "lacp"}
                    else "security" if feature in {"acl"}
                    else "management" if feature in {"ntp", "snmp", "ssh"}
                    else "reliability" if feature in {"vrrp"}
                    else "overlay" if feature in {"vxlan", "evpn"}
                    else "addressing"
                )
                break
        # The reviewed VXLAN/EVPN skeleton is shared by the Nexus 3000 and
        # 9000 data-center families.  Preserve that legacy composite scope
        # for overlay configuration queries while keeping a bare product or
        # hardware lookup on the concrete ``Nexus 9000`` series so the model
        # registry remains exact.
        if (
            result.get("product_series") == "Nexus 9000"
            and not result.get("product_model")
            and result.get("feature") in {"vxlan", "evpn"}
        ):
            result["product_series"] = "Nexus 3000/9000"
        device_match = re.search(r"\b(?:[A-Za-z][A-Za-z0-9_-]{2,}|\d{1,3}(?:\.\d{1,3}){3})\b", normalized)
        if device_match and device_match.group(0).lower() not in {"huawei", "cisco", "display", "ospf", "vlan", "arp"}:
            result["device_identifier"] = device_match.group(0)
        if any(token in lower for token in ("下发", "修改", "变更", "apply", "execute")):
            result["request_type"] = "configuration_change"
        # Additive contract projection for RET-001..003.  The legacy fields
        # above intentionally retain their established semantics; the
        # normalizer is the authoritative evidence envelope and never fills a
        # missing entity from model/context inference.
        result["query_normalization"] = normalized_query.to_dict()
        return result

    def is_knowledge_query(self, query: str) -> bool:
        metadata = self.parse_knowledge_metadata(query)
        return bool(
            metadata.get("vendor")
            or metadata.get("product_series")
            or metadata.get("feature")
            or any(token in (query or "").lower() for token in ("配置", "命令", "回显", "故障", "ospf", "vlan", "arp", "access", "trunk", "lacp", "loopback", "ntp", "snmp", "vrrp", "static route", "静态路由", "acl", "ssh", "stelnet", "hardware"))
        )

    @staticmethod
    def _json_candidate(content: Any) -> str:
        """Extract a model-shaped JSON object without trusting prose/fences.

        The gateway requests JSON mode, but compatible providers can still
        return a code fence or a short preamble.  Candidate selection is kept
        bounded and the candidate is validated by Pydantic before it is
        accepted.  We deliberately do not deserialize into an untyped dict.
        """

        text = str(content or "").strip()[:12_000]
        if not text:
            raise ValueError("intent response is empty")

        decoder = json.JSONDecoder()
        parseable_candidate: Optional[str] = None
        valid_candidate: Optional[str] = None
        for offset, character in enumerate(text):
            if character != "{":
                continue
            try:
                _value, end = decoder.raw_decode(text[offset:])
            except json.JSONDecodeError:
                continue
            candidate = text[offset:offset + end]
            parseable_candidate = candidate
            try:
                IntentDecision.model_validate_json(candidate)
            except ValidationError:
                continue
            valid_candidate = candidate

        if valid_candidate:
            return valid_candidate
        if parseable_candidate:
            return parseable_candidate
        raise ValueError("intent response does not contain a JSON object")

    @classmethod
    def _parse_decision(cls, content: Any) -> IntentDecision:
        return IntentDecision.model_validate_json(cls._json_candidate(content))

    @staticmethod
    def _validation_feedback(error: Exception) -> str:
        """Return bounded, value-free feedback for one schema correction."""

        if isinstance(error, ValidationError):
            issues = []
            for item in error.errors()[:8]:
                location = ".".join(str(part) for part in item.get("loc", ())) or "response"
                issue_type = str(item.get("type") or "invalid")[:64]
                issues.append(f"{location}: {issue_type}")
            details = "; ".join(issues) or "invalid structured response"
        else:
            details = "response is not a valid JSON object"
        return (
            "Your previous intent response failed schema validation. "
            "Return one JSON object only, with no Markdown or explanation. "
            f"Validation issues: {details}."
        )

    @staticmethod
    def _error_code(error: Exception) -> str:
        code = getattr(error, "code", None)
        if isinstance(code, str) and re.fullmatch(r"[A-Z0-9_]{1,64}", code):
            return code
        if isinstance(error, (ValidationError, ValueError, TypeError)):
            return "AI_INTENT_SCHEMA_INVALID"
        return "AI_INTENT_PROVIDER_ERROR"

    @staticmethod
    def _infer_risk_level(query: str) -> IntentRiskLevel:
        normalized = " ".join((query or "").lower().split())
        if any(marker in normalized for marker in _DANGEROUS_INTENT_MARKERS):
            return IntentRiskLevel.R3
        if any(marker in normalized for marker in _EXECUTION_INTENT_MARKERS):
            return IntentRiskLevel.R2
        return IntentRiskLevel.R0

    @staticmethod
    def _structured_fields(decision: IntentDecision) -> Dict[str, Any]:
        return {
            "confidence": decision.confidence,
            "needs_clarification": decision.needs_clarification,
            "missing_fields": list(decision.missing_fields),
            "clarification_question": decision.clarification_question,
            "risk_level": decision.risk_level.value,
            "requires_confirmation": decision.requires_confirmation,
        }

    @staticmethod
    def _has_field(values: Dict[str, Any], *names: str) -> bool:
        return any(values.get(name) not in (None, "", [], {}) for name in names)

    @classmethod
    def _apply_clarification_policy(cls, query: str, decision: IntentDecision) -> IntentDecision:
        """Add deterministic missing-slot guards after model classification.

        The model may classify a request correctly while omitting the one
        entity needed by the local operation.  These guards are deliberately
        conservative and only add a missing slot; they never invent a device,
        interface, time range, or protocol.
        """

        values = {}
        values.update(decision.metadata or {})
        values.update(decision.filters or {})
        normalized = " ".join(str(query or "").lower().split())
        missing = [str(item)[:64] for item in decision.missing_fields[:12] if str(item).strip()]

        def add(name: str) -> None:
            if name not in missing:
                missing.append(name)

        intent = decision.intent.value
        if intent == IntentType.IP_LOCATION.value and not cls._has_field(values, "ip"):
            add("ip")
        elif intent == IntentType.MAC_LOCATION.value and not cls._has_field(values, "mac"):
            add("mac")
        elif intent == IntentType.DEVICE_SEARCH.value:
            if not cls._has_field(values, "device_id", "device_identifier", "device_name", "site", "role", "vendor") and any(
                marker in normalized for marker in ("查询", "查找", "哪台", "search", "find")
            ):
                add("device_or_scope")
        elif intent == IntentType.ALARM_SEARCH.value:
            if not cls._has_field(values, "alarm_id", "device_id", "device_identifier", "site", "time_range"):
                add("device_or_time_range")
            if any(marker in normalized for marker in ("告警", "报警", "alarm", "今天", "昨天", "最近", "过去", "时间")) and not cls._has_field(values, "time_range"):
                add("time_range")
        elif intent in {IntentType.CONFIG_SEARCH.value, IntentType.TROUBLESHOOTING.value}:
            if not cls._has_field(values, "device_id", "device_identifier", "device_name", "site"):
                add("device_id")
            if any(marker in normalized for marker in ("接口", "端口", "interface", "port")) and not cls._has_field(values, "interface"):
                add("interface")
            if any(marker in normalized for marker in ("协议", "protocol", "ospf", "bgp", "vlan", "stp", "lldp", "lacp")) and not cls._has_field(values, "protocol", "feature"):
                add("protocol")
            if intent == IntentType.TROUBLESHOOTING.value and any(
                marker in normalized for marker in ("指标", "丢包", "延迟", "时延", "利用率", "cpu", "内存", "带宽", "metric", "latency", "packet loss")
            ) and not cls._has_field(values, "metric", "feature", "symptom", "problem"):
                add("metric")
            if intent == IntentType.TROUBLESHOOTING.value and not cls._has_field(
                values, "symptom", "problem", "feature", "metric", "protocol"
            ) and not any(marker in normalized for marker in ("故障", "异常", "告警", "down", "error", "timeout", "失败")):
                add("symptom_or_metric")
        if any(marker in normalized for marker in ("执行", "下发", "修改", "变更", "apply", "execute", "commit")) and not cls._has_field(values, "action", "command", "request_type"):
            add("action")

        # Preserve a model-supplied question only when it is already specific
        # enough. Otherwise ask one primary question at a time; the full
        # bounded missing_fields list remains available to the UI.
        question_by_field = {
            "ip": "请提供需要定位的 IP 地址。",
            "mac": "请提供需要定位的 MAC 地址。",
            "device_id": "请提供目标设备名称或设备 ID。",
            "interface": "请提供要检查的接口名称，例如 GigabitEthernet0/0/1。",
            "device_or_scope": "请提供设备名称、站点或角色范围。",
            "device_or_time_range": "请提供目标设备、站点或告警时间范围。",
            "time_range": "请提供需要查询的时间范围，例如最近 24 小时或今天。",
            "protocol": "请说明要查询或排查的协议，例如 OSPF、BGP 或 VLAN。",
            "metric": "请说明要关注的指标，例如延迟、丢包、CPU 或接口利用率。",
            "action": "请明确希望执行的动作或命令，并说明目标范围。",
            "symptom_or_metric": "请说明要排查的现象或指标，例如接口 down、丢包或延迟。",
            "confirmation": "该请求可能涉及高风险操作，请明确目标设备、变更内容，并确认是否继续。",
        }
        question = str(decision.clarification_question or "").strip()[:1000] or None
        if missing:
            question = question_by_field.get(missing[0], question or "请补充继续处理所需的信息。")
        if not missing and not decision.needs_clarification:
            return decision
        return decision.model_copy(
            update={
                "missing_fields": missing[:12],
                "needs_clarification": bool(missing) or decision.needs_clarification,
                "clarification_question": question,
            }
        )

    @staticmethod
    def _failure_message(parse_status: str) -> str:
        return {
            "provider_error": "意图识别服务暂时不可用，未执行任何设备操作。请稍后重试。",
            "schema_retry_failed": "意图识别结果格式异常，未执行任何设备操作。请重新描述问题或稍后重试。",
            "schema_retry_provider_error": "意图识别纠正服务暂时不可用，未执行任何设备操作。请稍后重试。",
        }.get(parse_status, "意图识别未完成，未执行任何设备操作。请稍后重试。")

    def _legacy_result(
        self,
        query: str,
        decision: IntentDecision,
        *,
        parse_status: str,
        parse_error_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Project the validated decision into the existing Assistant shape."""

        intent = decision.intent.value
        result: Dict[str, Any] = {
            "intent": intent,
            "filters": _safe_mapping(decision.filters, _INTENT_FILTER_KEYS),
            "parse_status": parse_status,
            "intent_prompt_version": INTENT_PROMPT_VERSION,
            **self._structured_fields(decision),
        }
        if parse_error_code:
            result["parse_error_code"] = parse_error_code

        if intent == IntentType.KNOWLEDGE.value:
            deterministic = self.parse_knowledge_metadata(query)
            llm_metadata = decision.metadata or decision.filters
            for key, value in _safe_mapping(llm_metadata, _KNOWLEDGE_METADATA_KEYS).items():
                if value not in (None, "", [], {}):
                    deterministic[key] = value
            result.update({
                "knowledge_intent": deterministic,
                "metadata": deterministic,
                "filters": deterministic,
                **deterministic,
            })
        elif decision.metadata:
            result["metadata"] = _safe_mapping(decision.metadata, _KNOWLEDGE_METADATA_KEYS)
        return result

    def _safe_fallback(
        self,
        query: str,
        *,
        parse_status: str,
        error_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        risk_level = self._infer_risk_level(query)
        requires_clarification = risk_level == IntentRiskLevel.R3
        decision = IntentDecision(
            intent=IntentType.GENERAL_QA,
            filters={"keyword": query},
            confidence=0.0,
            needs_clarification=requires_clarification,
            missing_fields=["confirmation"] if requires_clarification else [],
            clarification_question=(
                "为避免误操作，请明确目标设备、变更内容，并确认是否需要执行。"
                if requires_clarification else None
            ),
            risk_level=risk_level,
        )
        result = self._legacy_result(
            query,
            decision,
            parse_status=parse_status,
            parse_error_code=error_code,
        )
        result["parse_failure"] = {
            "status": parse_status,
            "message": self._failure_message(parse_status),
            "error_code": str(error_code or "AI_INTENT_PARSE_FAILED")[:64],
        }
        logger.warning(
            "Intent parsing degraded status=%s code=%s",
            str(parse_status)[:48],
            str(error_code or "AI_INTENT_PARSE_FAILED")[:64],
        )
        return result

    async def _chat_intent(
        self,
        messages: list[Dict[str, str]],
        *,
        user_id: Optional[str],
    ) -> Dict[str, Any]:
        return await llm_gateway.chat(
            scene="natural_query",
            messages=messages,
            max_tokens=512,
            response_format={"type": "json_object"},
            user_id=user_id,
        )

    async def parse_intent(self, query: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        identifier_decision = _deterministic_identifier_intent(query)
        if identifier_decision is not None:
            ai_metrics.intent_observed("deterministic", identifier_decision.intent.value)
            return self._legacy_result(query, identifier_decision, parse_status="deterministic")

        if is_asset_analysis_query(query):
            decision = IntentDecision(
                intent=IntentType.ASSET_ANALYSIS,
                filters=extract_asset_filters(query),
                confidence=1.0,
            )
            ai_metrics.intent_observed("deterministic", decision.intent.value)
            return self._legacy_result(query, decision, parse_status="deterministic")

        if self.is_knowledge_query(query):
            metadata = self.parse_knowledge_metadata(query)
            decision = IntentDecision(
                intent=IntentType.KNOWLEDGE,
                filters=metadata,
                metadata=metadata,
                confidence=1.0,
            )
            ai_metrics.intent_observed("deterministic", decision.intent.value)
            return self._legacy_result(query, decision, parse_status="deterministic")

        sys_prompt = (
            "You are an intent parser for Nexora Network Operations. "
            "Analyze the user's natural language question and extract one structured JSON intent.\n"
            f"Prompt version: {INTENT_PROMPT_VERSION}.\n"
            # Never infer cli_platform solely from software_train; keep this
            # boundary visible to source audits as well as to the model.
            "Allowed intent types: asset_analysis, device_search, ip_location, mac_location, "
            "alarm_search, config_search, troubleshooting, general_qa, knowledge.\n"
            "For knowledge, put the RAG fields in metadata. Never infer cli_platform solely "
            "from software_train; use null when not explicit.\n"
            "Use R0 for read-only, R1/R2 for low or medium impact, and R3/R4 for high-risk "
            "actions. Set needs_clarification and missing_fields when required.\n"
            "Return JSON only matching this schema:\n"
            f"{_INTENT_RESPONSE_SCHEMA}"
        )
        messages: list[Dict[str, str]] = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"User Query: {query}"},
        ]

        try:
            response = await self._chat_intent(messages, user_id=user_id)
        except Exception as error:
            code = self._error_code(error)
            ai_metrics.intent_observed("provider_error", "general_qa")
            return self._safe_fallback(query, parse_status="provider_error", error_code=code)

        try:
            content = response.get("content", "") if isinstance(response, dict) else ""
            decision = self._parse_decision(content)
        except (ValidationError, ValueError, TypeError) as error:
            ai_metrics.intent_observed("schema_retry_started", "unknown")
            retry_messages = [dict(message) for message in messages]
            retry_messages.append({"role": "user", "content": self._validation_feedback(error)})
            try:
                retry_response = await self._chat_intent(retry_messages, user_id=user_id)
                retry_content = retry_response.get("content", "") if isinstance(retry_response, dict) else ""
                decision = self._apply_clarification_policy(query, self._parse_decision(retry_content))
            except (ValidationError, ValueError, TypeError) as retry_error:
                ai_metrics.intent_observed("schema_retry_failed", "general_qa")
                return self._safe_fallback(
                    query,
                    parse_status="schema_retry_failed",
                    error_code=self._error_code(retry_error),
                )
            except Exception as retry_error:
                ai_metrics.intent_observed("provider_error", "general_qa")
                return self._safe_fallback(
                    query,
                    parse_status="schema_retry_provider_error",
                    error_code=self._error_code(retry_error),
                )
            ai_metrics.intent_observed("schema_retry_succeeded", decision.intent.value)
            return self._legacy_result(query, decision, parse_status="schema_retry_succeeded")

        decision = self._apply_clarification_policy(query, decision)
        ai_metrics.intent_observed("llm_success", decision.intent.value)
        return self._legacy_result(query, decision, parse_status="llm_success")


intent_parser = IntentParser()
