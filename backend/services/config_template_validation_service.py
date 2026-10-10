"""Safe, vendor-aware validation for configuration templates."""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from jinja2 import StrictUndefined, meta, nodes
from jinja2.exceptions import SecurityError, TemplateError, TemplateSyntaxError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment


MAX_TEMPLATE_CHARS = 200_000
MAX_RENDERED_CHARS = 500_000

_CRITICAL_PATTERNS = (
    (re.compile(r"^\s*(?:write\s+erase|erase\s+startup-config)\b", re.I), "清除启动配置"),
    (re.compile(r"^\s*(?:factory-reset|reset\s+saved-configuration)\b", re.I), "恢复出厂或清除保存配置"),
    (re.compile(r"^\s*(?:reload|reboot)\b", re.I), "设备重启"),
    (re.compile(r"^\s*format\b", re.I), "格式化存储"),
)
_HIGH_PATTERNS = (
    (re.compile(r"^\s*(?:delete|remove)\b", re.I), "删除资源"),
    (re.compile(r"^\s*shutdown\s*$", re.I), "关闭接口或服务"),
    (re.compile(r"^\s*undo\s+(?:interface|vlan|ospf|bgp|isis)\b", re.I), "删除关键网络配置"),
    (re.compile(r"^\s*no\s+(?:router|interface|vlan)\b", re.I), "删除关键网络配置"),
)

_OFFICIAL_REFERENCES = {
    "cisco": [{
        "title": "Cisco IOS XE — Using the Command-Line Interface",
        "url": "https://www.cisco.com/c/en/us/td/docs/routers/ios-xe/system-management/system-management/m_cf-cli-basics.html",
        "scope": "IOS XE CLI modes and command syntax",
    }],
    "huawei": [{
        "title": "Huawei VRP — Overview of CLIs",
        "url": "https://info.support.huawei.com/enterprise/en/doc/EDOC1100411157/5fdfc46d/overview-of-clis",
        "scope": "AR300/AR700 V300R024 CLI-based configuration",
    }],
    "h3c": [{
        "title": "H3C Comware 7 — Fundamentals Configuration Guide",
        "url": "https://www.h3c.com/en/d_202004/1283136_294551_0.htm",
        "scope": "Comware 7 CLI views, syntax, and undo commands",
    }],
    "ruijie": [{
        "title": "Ruijie RGOS official configuration example",
        "url": "https://community.ruijienetworks.com/forum.php?mod=viewthread&tid=9145",
        "scope": "RGOS VLAN, VLAN interface, trunk, access port, and OSPF configuration example",
    }],
    "zte": [{
        "title": "ZTE ZXR10 official configuration/documentation package index",
        "url": "https://www.zte.com.cn/content/dam/zte-site/res-www-zte-com-cn/trust_center/eucc/ZTE_IPN_Common_Criteria_Security_Evaluation_Certified_Configuration.pdf",
        "scope": "ZXR10 5960/9900/M6000 series documentation and command-reference package list",
    }],
    "dptech": [{
        "title": "DPtech Ethernet Switches official data sheet",
        "url": "https://www.dptech.com/uploadfile/2024/0806/20240806041441420.pdf",
        "scope": "ConPlat VLAN, interface, routing, NTP, and management capability scope",
    }],
    "maipu": [{
        "title": "Maipu IFW400 official user manual",
        "url": "https://www.maipu.com/upfiles/tinymce/files/20260602/fa464387f51f47b49b37387f2cb25665.pdf",
        "scope": "Maipu interface/VLAN interface and IP address format",
    }],
}

_ALLOWED_FILTERS = {
    "default",
    "d",
    "upper",
    "lower",
    "capitalize",
    "title",
    "trim",
    "replace",
    "join",
    "length",
    "int",
    "float",
    "string",
    "list",
    "first",
    "last",
    "sort",
    "unique",
    "min",
    "max",
    "round",
    "abs",
}
_ALLOWED_TESTS = {
    "defined",
    "undefined",
    "none",
    "boolean",
    "true",
    "false",
    "integer",
    "float",
    "number",
    "string",
    "mapping",
    "sequence",
    "iterable",
    "in",
    "eq",
    "ne",
    "lt",
    "le",
    "gt",
    "ge",
}


def _ip_interface(value: Any) -> ipaddress.IPv4Interface | ipaddress.IPv6Interface:
    text = str(value or "").strip()
    if "/" not in text:
        address = ipaddress.ip_address(text)
        text = f"{text}/{'32' if address.version == 4 else '128'}"
    return ipaddress.ip_interface(text)


def _filter_ipaddr(value: Any, attribute: str = "address") -> str:
    interface = _ip_interface(value)
    requested = str(attribute or "address").lower()
    if requested in {"address", "ip", "host"}:
        return str(interface.ip)
    if requested in {"network", "network_address"}:
        return str(interface.network.network_address)
    if requested in {"prefix", "prefixlen"}:
        return str(interface.network.prefixlen)
    if requested == "netmask":
        return str(interface.network.netmask)
    if requested == "hostmask":
        return str(interface.network.hostmask)
    if requested == "broadcast":
        return str(interface.network.broadcast_address)
    raise ValueError(f"不支持的 ipaddr 属性: {attribute}")


def _filter_network_address(value: Any) -> str:
    return str(_ip_interface(value).network.network_address)


def _filter_netmask(value: Any) -> str:
    return str(_ip_interface(value).network.netmask)


def _filter_wildcard(value: Any) -> str:
    interface = _ip_interface(value)
    if interface.version != 4:
        raise ValueError("IPv6 不支持 IPv4 wildcard mask")
    return str(interface.network.hostmask)


def _filter_normalize_interface(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "")).strip()
    aliases = (
        (re.compile(r"^gi(?:gabit(?:ethernet)?)?", re.I), "GigabitEthernet"),
        (re.compile(r"^te(?:n(?:gigabit)?ethernet)?", re.I), "TenGigabitEthernet"),
        (re.compile(r"^fa(?:stethernet)?", re.I), "FastEthernet"),
        (re.compile(r"^eth(?:ernet)?", re.I), "Ethernet"),
        (re.compile(r"^lo(?:opback)?", re.I), "LoopBack"),
        (re.compile(r"^po(?:rt-channel)?", re.I), "Port-channel"),
    )
    for pattern, replacement in aliases:
        if pattern.search(text):
            return pattern.sub(replacement, text, count=1)
    return text


def _build_environment() -> SandboxedEnvironment:
    environment = SandboxedEnvironment(
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    built_in_filters = dict(environment.filters)
    environment.filters.clear()
    for name in sorted(_ALLOWED_FILTERS):
        if name in built_in_filters:
            environment.filters[name] = built_in_filters[name]
    built_in_tests = dict(environment.tests)
    environment.tests.clear()
    for name in sorted(_ALLOWED_TESTS):
        if name in built_in_tests:
            environment.tests[name] = built_in_tests[name]
    environment.filters.update({
        "ipaddr": _filter_ipaddr,
        "network_address": _filter_network_address,
        "netmask": _filter_netmask,
        "wildcard": _filter_wildcard,
        "normalize_interface": _filter_normalize_interface,
    })
    environment.globals.clear()
    return environment


def _nested_context(values: dict[str, Any] | None) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for raw_key, value in (values or {}).items():
        key = str(raw_key).strip()
        if not key:
            continue
        context[key] = value
        if "." not in key:
            continue
        cursor = context
        parts = [part for part in key.split(".") if part]
        for part in parts[:-1]:
            child = cursor.get(part)
            if not isinstance(child, dict):
                child = {}
                cursor[part] = child
            cursor = child
        if parts:
            cursor[parts[-1]] = value
    return context


def _risk_items(rendered: str) -> list[dict]:
    items: list[dict] = []
    for line_number, line in enumerate(rendered.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "!", "//")):
            continue
        for pattern, message in _CRITICAL_PATTERNS:
            if pattern.search(stripped):
                items.append({
                    "severity": "critical",
                    "line": line_number,
                    "command": stripped[:300],
                    "message": message,
                })
                break
        else:
            for pattern, message in _HIGH_PATTERNS:
                if pattern.search(stripped):
                    items.append({
                        "severity": "high",
                        "line": line_number,
                        "command": stripped[:300],
                        "message": message,
                    })
                    break
    return items


def _vendor_key(vendor: str, platform: str) -> str:
    value = f"{vendor} {platform}".lower()
    if "cisco" in value or "ios" in value:
        return "cisco"
    if "huawei" in value or "vrp" in value:
        return "huawei"
    if "h3c" in value or "comware" in value:
        return "h3c"
    if "ruijie" in value or "rgos" in value:
        return "ruijie"
    if "zte" in value or "zxros" in value:
        return "zte"
    if "dptech" in value or "conplat" in value:
        return "dptech"
    if "maipu" in value or "mypower" in value:
        return "maipu"
    return ""


def _vendor_family_warnings(rendered: str, vendor_key: str) -> list[dict]:
    warnings: list[dict] = []
    families = {
        "cisco": re.compile(r"^\s*(?:system-view|display\s|undo\s)", re.I | re.M),
        "huawei": re.compile(r"^\s*(?:configure\s+terminal|show\s+running-config|no\s+interface)\b", re.I | re.M),
        "h3c": re.compile(r"^\s*(?:configure\s+terminal|show\s+running-config|commit\s*$)", re.I | re.M),
        "ruijie": re.compile(r"^\s*(?:system-view|display\s|undo\s)", re.I | re.M),
        "zte": re.compile(r"^\s*(?:system-view|display\s|undo\s)", re.I | re.M),
        "dptech": re.compile(r"^\s*(?:system-view|display\s|undo\s)", re.I | re.M),
        "maipu": re.compile(r"^\s*(?:system-view|display\s|undo\s)", re.I | re.M),
    }
    pattern = families.get(vendor_key)
    if pattern and pattern.search(rendered):
        warnings.append({
            "code": "vendor_command_family_mismatch",
            "severity": "warning",
            "message": "检测到疑似属于其他厂商命令族的命令，请按目标型号官方命令参考复核",
        })
    return warnings


def _defaulted_variables(ast) -> set[str]:
    names: set[str] = set()
    for filter_node in ast.find_all(nodes.Filter):
        if filter_node.name not in {"default", "d"}:
            continue
        target = filter_node.node
        while isinstance(target, (nodes.Getattr, nodes.Getitem)):
            target = target.node
        if isinstance(target, nodes.Name):
            names.add(target.name)
    return names


def validate_template(
    content: str,
    *,
    variables: dict[str, Any] | None = None,
    vendor: str = "",
    platform: str = "",
    software_version: str = "",
    rollback: str = "",
) -> dict:
    source = str(content or "")
    issues: list[dict] = []
    warnings: list[dict] = []
    vendor_key = _vendor_key(vendor, platform)
    official_references = _OFFICIAL_REFERENCES.get(vendor_key, [])
    if not source.strip():
        issues.append({"code": "empty_template", "severity": "error", "message": "模板内容为空"})
    if len(source) > MAX_TEMPLATE_CHARS:
        issues.append({
            "code": "template_too_large",
            "severity": "error",
            "message": f"模板超过 {MAX_TEMPLATE_CHARS} 字符限制",
        })
    if issues:
        return {
            "valid": False,
            "syntax_valid": False,
            "render_valid": False,
            "required_variables": [],
            "missing_variables": [],
            "issues": issues,
            "warnings": warnings,
            "rendered": "",
            "rendered_rollback": "",
            "risk_level": "none",
            "risk_items": [],
            "command_count": 0,
            "vendor": vendor,
            "platform": platform,
            "software_version": software_version,
            "official_references": official_references,
        }

    environment = _build_environment()
    try:
        ast = environment.parse(source)
        required_names = set(meta.find_undeclared_variables(ast))
        defaulted = _defaulted_variables(ast)
        template = environment.from_string(source)
    except TemplateSyntaxError as exc:
        issues.append({
            "code": "jinja_syntax",
            "severity": "error",
            "line": exc.lineno,
            "message": str(exc),
        })
        return {
            "valid": False,
            "syntax_valid": False,
            "render_valid": False,
            "required_variables": [],
            "missing_variables": [],
            "issues": issues,
            "warnings": warnings,
            "rendered": "",
            "rendered_rollback": "",
            "risk_level": "none",
            "risk_items": [],
            "command_count": 0,
            "vendor": vendor,
            "platform": platform,
            "software_version": software_version,
            "official_references": official_references,
        }

    rollback_template = None
    if str(rollback or "").strip():
        try:
            rollback_ast = environment.parse(rollback)
            required_names.update(meta.find_undeclared_variables(rollback_ast))
            defaulted.update(_defaulted_variables(rollback_ast))
            rollback_template = environment.from_string(rollback)
        except TemplateSyntaxError as exc:
            issues.append({
                "code": "rollback_jinja_syntax",
                "severity": "error",
                "line": exc.lineno,
                "message": f"回滚模板语法错误: {exc}",
            })
            return {
                "valid": False,
                "syntax_valid": False,
                "render_valid": False,
                "required_variables": sorted(required_names),
                "missing_variables": [],
                "issues": issues,
                "warnings": warnings,
                "rendered": "",
                "rendered_rollback": "",
                "risk_level": "none",
                "risk_items": [],
                "command_count": 0,
                "vendor": vendor,
                "platform": platform,
                "software_version": software_version,
                "official_references": official_references,
            }

    required = sorted(required_names)
    context = _nested_context(variables)
    missing = sorted(name for name in required if name not in context and name not in defaulted)
    rendered = ""
    rendered_rollback = ""
    render_valid = not missing
    if missing:
        issues.append({
            "code": "missing_variables",
            "severity": "error",
            "message": f"未赋值变量: {', '.join(missing)}",
            "variables": missing,
        })
    else:
        try:
            rendered = template.render(context)
            if rollback_template is not None:
                rendered_rollback = rollback_template.render(context)
            if len(rendered) > MAX_RENDERED_CHARS:
                issues.append({
                    "code": "rendered_too_large",
                    "severity": "error",
                    "message": f"渲染结果超过 {MAX_RENDERED_CHARS} 字符限制",
                })
                render_valid = False
        except (UndefinedError, SecurityError, TemplateError) as exc:
            issues.append({
                "code": "render_failed",
                "severity": "error",
                "message": str(exc),
            })
            render_valid = False

    risks = _risk_items(rendered) if render_valid else []
    if render_valid:
        warnings.extend(_vendor_family_warnings(rendered, vendor_key))
    if risks:
        warnings.append({
            "code": "risky_commands",
            "severity": "warning",
            "message": f"检测到 {len(risks)} 条高风险命令，请走审批并准备回滚方案",
        })
    if risks and not str(rollback or "").strip():
        warnings.append({
            "code": "missing_rollback",
            "severity": "warning",
            "message": "模板包含高风险命令，但尚未填写回滚模板",
        })
    if vendor_key:
        warnings.append({
            "code": "device_precheck_required",
            "severity": "warning",
            "message": (
                "官方命令支持范围与设备型号、板卡和软件版本相关；静态检查不能替代"
                "目标设备候选配置/语法预检，正式下发前必须执行设备侧预检"
            ),
        })
    elif vendor or platform:
        warnings.append({
            "code": "unsupported_vendor_profile",
            "severity": "warning",
            "message": "当前厂商/平台尚无官方文档校验配置档案，只完成通用语法与风险检查",
        })
    risk_level = (
        "critical" if any(item["severity"] == "critical" for item in risks)
        else "high" if risks
        else "none"
    )
    command_count = sum(
        1 for line in rendered.splitlines()
        if line.strip() and not line.strip().startswith(("#", "!", "//"))
    )
    return {
        "valid": not issues,
        "syntax_valid": True,
        "render_valid": render_valid,
        "required_variables": required,
        "missing_variables": missing,
        "issues": issues,
        "warnings": warnings,
        "rendered": rendered,
        "rendered_rollback": rendered_rollback,
        "risk_level": risk_level,
        "risk_items": risks,
        "command_count": command_count,
        "vendor": vendor,
        "platform": platform,
        "software_version": software_version,
        "official_references": official_references,
    }
