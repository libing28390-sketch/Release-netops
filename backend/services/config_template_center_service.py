"""Schema inference, typed parameter validation, rendering, and quality checks."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import re
from typing import Any

from services.config_search_service import redact_config_line
from services.config_template_validation_service import validate_template


_VARIABLE_PATTERN = re.compile(
    r"\{\{\s*([A-Za-z_][\w.-]*)"
    r"(?:\s*\|\s*(?:default|d)\s*\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^,)]+))[^)]*\))?"
)
_UNSAFE_VALUE = re.compile(r"[\r\n;|`]")
_HOSTNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,251}[A-Za-z0-9])?$")
_MAC = re.compile(r"^(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$|^[0-9A-Fa-f]{4}(?:-[0-9A-Fa-f]{4}){2}$")
_INTERFACE = re.compile(
    r"^(?:GigabitEthernet|TenGigabitEthernet|TwentyFiveGigE|FortyGigabitEthernet|"
    r"HundredGigE|Ethernet|Eth-Trunk|Bridge-Aggregation|Port-Channel|LoopBack|"
    r"Loopback|Vlanif|Vlan-interface|GE|XGE)[\w/.:_-]+$",
    re.I,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def json_value(raw: Any, fallback: Any) -> Any:
    if isinstance(raw, type(fallback)):
        return raw
    if not raw:
        return fallback
    try:
        value = json.loads(raw)
        return value if isinstance(value, type(fallback)) else fallback
    except (TypeError, ValueError):
        return fallback


def _label_for(name: str) -> str:
    known = {
        "vlan_id": "VLAN ID",
        "vlan_name": "VLAN 名称",
        "interface_name": "接口名称",
        "interface_description": "接口描述",
        "gateway_ip": "网关地址",
        "network": "网络地址",
        "source_network": "源网段",
        "destination_network": "目标网段",
        "neighbor_ip": "邻居地址",
        "local_as": "本地 AS",
        "remote_as": "对端 AS",
        "process_id": "进程 ID",
        "password": "密码",
        "community": "SNMP 团体字",
    }
    return known.get(name, name.replace("_", " ").replace(".", " / ").title())


def _type_for(name: str, default_value: Any) -> str:
    lowered = name.lower()
    if "password" in lowered or "secret" in lowered or "community" in lowered:
        return "password"
    if lowered in {"vlan", "vlan_id", "native_vlan", "access_vlan"} or lowered.endswith("_vlan"):
        return "vlan_id"
    if lowered.endswith("_asn") or lowered in {"asn", "local_as", "remote_as"}:
        return "asn"
    if "interface" in lowered or lowered in {"port", "port_name"}:
        return "interface"
    if "ipv6" in lowered and any(token in lowered for token in ("network", "prefix", "cidr")):
        return "ipv6_network"
    if "ipv6" in lowered or lowered.endswith("_ipv6"):
        return "ipv6_address"
    if any(token in lowered for token in ("network", "prefix", "cidr", "subnet")):
        return "ipv4_network"
    if lowered.endswith("_ip") or lowered in {"ip", "gateway", "neighbor", "address"}:
        return "ipv4_address"
    if "hostname" in lowered or lowered in {"host_name", "device_name"}:
        return "hostname"
    if "mac" in lowered:
        return "mac_address"
    if lowered.startswith(("enable_", "is_", "use_")):
        return "boolean"
    if isinstance(default_value, bool):
        return "boolean"
    if isinstance(default_value, int) or lowered.endswith(("_id", "_count", "_metric", "_priority")):
        return "integer"
    if lowered.endswith(("s", "_list")) and lowered not in {"address", "process"}:
        return "list"
    if "description" in lowered or "remark" in lowered:
        return "text"
    return "string"


def _parse_default(raw: str | None) -> Any:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return ""
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if re.fullmatch(r"-?\d+", value):
        try:
            return int(value)
        except ValueError:
            return value
    return value


def infer_variable_schema(content: str) -> list[dict[str, Any]]:
    """Infer a useful typed schema when an older template has no explicit one."""
    schema: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _VARIABLE_PATTERN.finditer(str(content or "")):
        name = match.group(1)
        if name in seen:
            continue
        seen.add(name)
        raw_default = next((item for item in match.groups()[1:] if item is not None), None)
        default = _parse_default(raw_default)
        parameter_type = _type_for(name, default)
        item: dict[str, Any] = {
            "name": name,
            "label": _label_for(name),
            "description": "",
            "type": parameter_type,
            "required": raw_default is None,
            "default_value": default,
            "example_value": default,
            "placeholder": "",
            "validation_rules": {},
            "options": [],
            "sort_order": len(schema),
            "group_name": (
                "接口与应用范围" if "interface" in name.lower()
                else "地址与路由" if any(token in name.lower() for token in ("ip", "network", "route", "neighbor", "asn"))
                else "基础参数"
            ),
            "is_secret": parameter_type == "password",
            "is_advanced": False,
            "allow_multiline": parameter_type in {"text", "command_block"},
        }
        if parameter_type == "vlan_id":
            item["validation_rules"] = {"min": 1, "max": 4094}
            # Network identifiers must be explicitly confirmed in production.
            item["required"] = True
        elif parameter_type == "integer":
            item["validation_rules"] = {"min": 0, "max": 2_147_483_647}
        elif parameter_type == "asn":
            item["validation_rules"] = {"min": 1, "max": 4_294_967_295}
            item["required"] = True
        elif parameter_type in {"ipv4_address", "ipv4_network", "ipv6_address", "ipv6_network", "interface"}:
            item["required"] = True
        schema.append(item)
    return schema


def _coerce_boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"true", "1", "yes", "on", "是", "启用"}:
        return True
    if lowered in {"false", "0", "no", "off", "否", "禁用"}:
        return False
    return None


def validate_parameters(
    schema: list[dict[str, Any]],
    values: dict[str, Any],
    *,
    vendor: str = "",
    platform: str = "",
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    normalized: dict[str, Any] = {}
    sources: dict[str, str] = {}
    defaulted: list[str] = []
    used: list[str] = []

    for item in schema:
        name = str(item.get("name") or "")
        if not name:
            continue
        provided = name in values and values[name] not in (None, "")
        value = values.get(name)
        if not provided and item.get("default_value") not in (None, ""):
            value = item.get("default_value")
            defaulted.append(name)
            sources[name] = "template_default"
        elif provided:
            sources[name] = "user"
        if value in (None, ""):
            if item.get("required"):
                errors.append({"field": name, "code": "required", "message": f"{item.get('label') or name} 为必填参数"})
            continue

        parameter_type = str(item.get("type") or "string")
        rules = item.get("validation_rules") if isinstance(item.get("validation_rules"), dict) else {}
        normalized_value: Any = value
        try:
            if parameter_type in {"integer", "vlan_id", "asn"}:
                normalized_value = int(str(value).strip())
                minimum = int(rules.get("min", 1 if parameter_type in {"vlan_id", "asn"} else 0))
                maximum = int(rules.get("max", 4094 if parameter_type == "vlan_id" else 4_294_967_295))
                if not minimum <= normalized_value <= maximum:
                    raise ValueError(f"必须在 {minimum}～{maximum} 之间")
            elif parameter_type == "boolean":
                normalized_boolean = _coerce_boolean(value)
                if normalized_boolean is None:
                    raise ValueError("必须为 true/false")
                normalized_value = normalized_boolean
            elif parameter_type == "ipv4_address":
                normalized_value = str(ipaddress.IPv4Address(str(value).strip()))
            elif parameter_type == "ipv6_address":
                normalized_value = str(ipaddress.IPv6Address(str(value).strip()))
            elif parameter_type == "ipv4_network":
                network = ipaddress.IPv4Network(str(value).strip(), strict=False)
                normalized_value = str(network)
                if normalized_value != str(value).strip():
                    warnings.append({"field": name, "code": "network_normalized", "message": f"{name} 已标准化为 {normalized_value}"})
            elif parameter_type == "ipv6_network":
                network = ipaddress.IPv6Network(str(value).strip(), strict=False)
                normalized_value = str(network)
            elif parameter_type == "mac_address":
                if not _MAC.fullmatch(str(value).strip()):
                    raise ValueError("MAC 地址格式无效")
                normalized_value = str(value).strip().lower().replace("-", ":")
            elif parameter_type == "hostname":
                if not _HOSTNAME.fullmatch(str(value).strip()):
                    raise ValueError("主机名格式无效")
                normalized_value = str(value).strip()
            elif parameter_type == "interface":
                normalized_value = re.sub(r"\s+", "", str(value).strip())
                if not _INTERFACE.fullmatch(normalized_value):
                    raise ValueError("接口名称不符合受支持的厂商格式")
            elif parameter_type == "select":
                options = [option.get("value") if isinstance(option, dict) else option for option in item.get("options", [])]
                if options and value not in options:
                    raise ValueError("不在允许的选项中")
            elif parameter_type == "multi_select":
                selected = value if isinstance(value, list) else [part.strip() for part in str(value).split(",") if part.strip()]
                options = [option.get("value") if isinstance(option, dict) else option for option in item.get("options", [])]
                if options and any(option not in options for option in selected):
                    raise ValueError("包含不允许的选项")
                normalized_value = selected
            elif parameter_type == "list":
                normalized_value = value if isinstance(value, list) else [part.strip() for part in str(value).split(",") if part.strip()]
            else:
                normalized_value = str(value)
                if not item.get("allow_multiline") and _UNSAFE_VALUE.search(normalized_value):
                    raise ValueError("包含换行、分号、管道符或反引号等禁止字符")
                minimum_length = int(rules.get("min_length", 0))
                maximum_length = int(rules.get("max_length", 10_000))
                if len(normalized_value) < minimum_length or len(normalized_value) > maximum_length:
                    raise ValueError(f"长度必须在 {minimum_length}～{maximum_length} 之间")
                pattern = str(rules.get("pattern") or "")
                if pattern and not re.fullmatch(pattern, normalized_value):
                    raise ValueError("格式不符合模板约束")
        except (ValueError, TypeError) as exc:
            errors.append({"field": name, "code": "invalid", "message": f"{item.get('label') or name}：{exc}"})
            continue

        if str(vendor).lower() in {"juniper", "junos"} and parameter_type in {"string", "hostname"} and " " in str(normalized_value):
            warnings.append({"field": name, "code": "junos_space", "message": f"{name} 包含空格，请确认 Junos 标识符是否允许"})
        normalized[name] = normalized_value
        used.append(name)

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "normalized_values": normalized,
        "sources": sources,
        "used_variables": used,
        "defaulted_variables": defaulted,
        "vendor": vendor,
        "platform": platform,
    }


def _mask_secret_values(output: str, schema: list[dict[str, Any]], values: dict[str, Any]) -> str:
    masked = output
    for item in schema:
        if not item.get("is_secret") and item.get("type") != "password":
            continue
        value = str(values.get(item.get("name")) or "")
        if value:
            masked = masked.replace(value, "••••••••")
    return masked


def _source_map(
    output: str,
    schema: list[dict[str, Any]],
    values: dict[str, Any],
    sources: dict[str, str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    secret_names = {
        str(item.get("name"))
        for item in schema
        if item.get("is_secret") or item.get("type") == "password"
    }
    for line_number, line in enumerate(output.splitlines(), start=1):
        for name, raw_value in values.items():
            value = str(raw_value)
            if not value or name in secret_names or value not in line:
                continue
            items.append({
                "output_line": line_number,
                "variable": name,
                "value": value,
                "source": sources.get(name, "user"),
            })
    return items[:2_000]


def render_template_center(
    *,
    content: str,
    rollback: str,
    schema: list[dict[str, Any]],
    values: dict[str, Any],
    vendor: str,
    platform: str,
    software_version: str,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = options or {}
    parameter_result = validate_parameters(schema, values, vendor=vendor, platform=platform)
    if not parameter_result["valid"]:
        return {
            "success": False,
            "render_status": "parameter_error",
            "rendered_output": "",
            "line_count": 0,
            "command_count": 0,
            "used_variables": parameter_result["used_variables"],
            "defaulted_variables": parameter_result["defaulted_variables"],
            "warnings": parameter_result["warnings"],
            "errors": parameter_result["errors"],
            "risk_level": "none",
            "risk_items": [],
            "source_map": [],
            "parameter_validation": parameter_result,
        }

    validation = validate_template(
        content,
        variables=parameter_result["normalized_values"],
        vendor=vendor,
        platform=platform,
        software_version=software_version,
        rollback=rollback,
    )
    output = validation.get("rendered") or ""
    if options.get("trim_blank_lines", True):
        output = re.sub(r"\n{3,}", "\n\n", output).strip() + ("\n" if output.strip() else "")
    masked_output = _mask_secret_values(output, schema, parameter_result["normalized_values"])
    source_map = _source_map(
        masked_output,
        schema,
        parameter_result["normalized_values"],
        parameter_result["sources"],
    ) if options.get("include_source_map", True) else []
    errors = [
        {
            "field": "",
            "code": issue.get("code", "render_error"),
            "line": issue.get("line"),
            "message": issue.get("message", "模板渲染失败"),
        }
        for issue in validation.get("issues", [])
    ]
    warnings = [
        {
            "field": "",
            "code": warning.get("code", "warning"),
            "message": warning.get("message", ""),
        }
        for warning in validation.get("warnings", [])
    ]
    warnings = parameter_result["warnings"] + warnings
    return {
        "success": bool(validation.get("render_valid")) and not errors,
        "render_status": "success" if validation.get("render_valid") and not errors else "render_error",
        "rendered_output": masked_output,
        "rendered_rollback": _mask_secret_values(validation.get("rendered_rollback") or "", schema, parameter_result["normalized_values"]),
        "line_count": len(masked_output.splitlines()),
        "command_count": validation.get("command_count", 0),
        "used_variables": parameter_result["used_variables"],
        "defaulted_variables": parameter_result["defaulted_variables"],
        "warnings": warnings,
        "errors": errors,
        "risk_level": validation.get("risk_level", "none"),
        "risk_items": validation.get("risk_items", []),
        "source_map": source_map,
        "parameter_validation": parameter_result,
        "official_references": validation.get("official_references", []),
    }


def redact_output(output: str) -> str:
    return "\n".join(redact_config_line(line) for line in str(output or "").splitlines())


def redact_parameter_values(schema: list[dict[str, Any]], values: dict[str, Any]) -> dict[str, Any]:
    secret_names = {
        str(item.get("name"))
        for item in schema
        if item.get("is_secret") or item.get("type") == "password"
    }
    return {
        key: ("***" if key in secret_names and value not in (None, "") else value)
        for key, value in values.items()
    }


def template_quality_score(template: dict[str, Any], schema: list[dict[str, Any]]) -> dict[str, Any]:
    checks = {
        "has_description": bool(str(template.get("description") or "").strip()),
        "has_source": bool(str(template.get("content") or "").strip()),
        "has_schema": bool(schema),
        "schema_described": bool(schema) and all(item.get("label") for item in schema),
        "has_examples": bool(json_value(template.get("example_values_json"), {})) or any(item.get("example_value") not in (None, "") for item in schema),
        "has_usage_notes": bool(str(template.get("usage_notes") or "").strip()),
        "has_rollback": bool(str(template.get("rollback") or "").strip()),
        "has_compatibility": bool(str(template.get("platform_family") or "").strip()),
        "has_official_reference": bool(str(template.get("official_reference") or "").strip()) if template.get("is_official") else True,
        "published_or_reviewed": str(template.get("status") or "") == "published" or str(template.get("validation_status") or "") != "draft",
    }
    score = sum(10 for passed in checks.values() if passed)
    return {"score": score, "checks": checks}


def checksum(content: str) -> str:
    return hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()

