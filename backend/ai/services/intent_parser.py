"""
AI Intent Parser for Natural Language Query Recognition
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional
from ai.gateway.llm_gateway import llm_gateway
from ai.services.knowledge_metadata import canonical_vendor
from ai.services.query_normalizer import normalize_query


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

    async def parse_intent(self, query: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        if is_asset_analysis_query(query):
            return {"intent": "asset_analysis", "filters": extract_asset_filters(query)}

        if self.is_knowledge_query(query):
            metadata = self.parse_knowledge_metadata(query)
            return {"intent": "knowledge", "knowledge_intent": metadata, "metadata": metadata, "filters": metadata, **metadata}

        sys_prompt = (
            "You are an intent parser for Nexora Network Operations. "
            "Analyze the user's natural language question and extract structured JSON intent.\n"
            "Allowed intent types: 'device_search', 'ip_location', 'mac_location', 'alarm_search', "
            "'config_search', 'troubleshooting', 'general_qa', 'knowledge'.\n"
            "For knowledge return metadata fields request_type, knowledge_type, vendor, product_family, "
            "product_series, product_model, os_family, os_generation, software_train, software_release, "
            "cli_platform, document_category, feature_domain, feature, subfeature, device_identifier.\n"
            "Never infer cli_platform solely from software_train; use null when not explicit.\n"
            "Return JSON: {\"intent\": \"knowledge\", \"metadata\": { ... }}"
        )
        user_prompt = f"User Query: {query}"
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            res = await llm_gateway.chat(
                scene="natural_query",
                messages=messages,
                response_format={"type": "json_object"},
                user_id=user_id
            )
            content = res.get("content", "")
            clean_json = content.strip()
            if clean_json.startswith("```json"): clean_json = clean_json[7:]
            if clean_json.startswith("```"): clean_json = clean_json[3:]
            if clean_json.endswith("```"): clean_json = clean_json[:-3]
            parsed = json.loads(clean_json.strip())
            metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else parsed.get("filters", {})
            if parsed.get("intent") == "knowledge":
                deterministic = self.parse_knowledge_metadata(query)
                deterministic.update({key: value for key, value in metadata.items() if value not in (None, "", [], {})})
                return {"intent": "knowledge", "knowledge_intent": deterministic, "metadata": deterministic, "filters": deterministic, **deterministic}
            return {"intent": parsed.get("intent", "general_qa"), "filters": parsed.get("filters", {})}
        except Exception:
            return {"intent": "general_qa", "filters": {"keyword": query}}


intent_parser = IntentParser()
