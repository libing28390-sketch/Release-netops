"""
AI Intent Parser for Natural Language Query Recognition
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional
from ai.gateway.llm_gateway import llm_gateway
from ai.services.knowledge_metadata import canonical_vendor


_ASSET_ANALYSIS_AGGREGATION_MARKERS = (
    "\u7edf\u8ba1", "\u5206\u5e03", "\u5360\u6bd4", "\u805a\u5408", "\u6c47\u603b",
    "\u6982\u89c8", "\u5206\u6790", "\u6458\u8981", "\u6e05\u5355", "\u7eb3\u7ba1",
    "aggregation", "breakdown", "distribution", "inventory overview",
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
    }

    @staticmethod
    def _normalise_product(query: str) -> tuple[Optional[str], Optional[str]]:
        text = query or ""
        upper = text.upper()
        # Product Registry aliases are resolved to the canonical series.  The
        # model token is retained separately when it is explicit.
        if re.search(r"\bCE\s*68(?:\d{2}|XX)?\b", upper) or "CLOUDENGINE 6800" in upper:
            model_match = re.search(r"\bCE\s*\d{4,}[A-Z0-9-]*\b", upper)
            model = model_match.group(0).replace(" ", "") if model_match else None
            return "CloudEngine 6800", (None if model in {"CE6800", "CE68XX"} else model)
        # Operators commonly type a short Huawei family prefix (for example
        # S57) rather than a complete S5735-L-V2 model.  Keep the prefix as a
        # search scope; the resolver will expand it against registry series.
        product_match = re.search(r"\bS\d{2,5}(?:[-_][A-Z0-9]+)*\b", upper)
        if product_match:
            token = product_match.group(0).replace("_", "-")
            # A series token such as S5735-L-V2 is not a concrete model.  Do
            # not over-constrain retrieval to a literal model column.
            return token, None
        return None, None

    def parse_knowledge_metadata(self, query: str) -> Dict[str, Any]:
        """Deterministically extract the RAG v2 metadata contract.

        This conservative path is used before an LLM.  It only emits a
        platform when the query contains an explicit platform/train context;
        software train alone is left for the Product Registry resolver.
        """

        normalized = " ".join((query or "").strip().split())
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
        }

        for vendor, aliases in self._VENDOR_ALIASES.items():
            if any(alias in lower for alias in aliases):
                result["vendor"] = vendor
                break
        series, model = self._normalise_product(normalized)
        result["product_series"] = series
        result["product_model"] = model
        if series and not result["vendor"] and (series.upper().startswith(("CE", "S")) or series.lower().startswith("cloudengine")):
            # This is an alias lookup seed, not a CLI/platform inference; the
            # resolver verifies it against Product Registry before filtering.
            result["vendor"] = "Huawei"

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
                result["feature_domain"] = "routing" if feature in {"ospf", "bgp", "arp"} else "switching" if feature in {"vlan", "stp"} else "addressing"
                break
        device_match = re.search(r"\b(?:[A-Za-z][A-Za-z0-9_-]{2,}|\d{1,3}(?:\.\d{1,3}){3})\b", normalized)
        if device_match and device_match.group(0).lower() not in {"huawei", "cisco", "display", "ospf", "vlan", "arp"}:
            result["device_identifier"] = device_match.group(0)
        if any(token in lower for token in ("下发", "修改", "变更", "apply", "execute")):
            result["request_type"] = "configuration_change"
        return result

    def is_knowledge_query(self, query: str) -> bool:
        metadata = self.parse_knowledge_metadata(query)
        return bool(
            metadata.get("vendor")
            or metadata.get("product_series")
            or metadata.get("feature")
            or any(token in (query or "").lower() for token in ("配置", "命令", "回显", "故障", "ospf", "vlan", "arp", "hardware"))
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
