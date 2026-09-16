"""Deterministic clarification policy for network configuration requests.

The Copilot must not treat a vendor-only configuration question as permission
to expose every matching knowledge-base document.  This module keeps the
decision deterministic and separate from the LLM prompt: it decides whether a
request has enough scope for content retrieval, which fields are missing, and
which bounded choices can be shown to the operator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import os
import re
from typing import Any, Mapping

from ai.security.sanitizer import sanitize_text
from ai.services.knowledge_metadata import canonical_cli_platform


_CHANGE_MARKERS = (
    "下发",
    "修改",
    "变更",
    "执行",
    "apply",
    "execute",
    "push",
)
_FULL_CONFIG_MARKERS = (
    "全量配置",
    "完整配置",
    "运行配置",
    "running-config",
    "running config",
    "current configuration",
    "当前配置",
)
_GENERIC_MARKERS = ("通用", "示例", "模板", "参考")
_SCOPED_CONFIGURATION_MARKERS = (
    "interface",
    "switchport",
    "uplink",
    "port",
    "ip route",
    "ssh server",
    "crypto key",
    "ntp server",
    "ntp-service",
    "router ospf",
    "接口",
    "端口",
    "上联",
)

# A read-only guard must not be treated as an instruction to change a device.
# Strip only the negated action span before checking positive change markers so
# a sentence containing both "不要执行..." and a later explicit action still
# remains conservative.
_NEGATED_CHANGE_RE = re.compile(
    r"(?:不要|不|无需|无须|禁止|严禁)\s*(?:执行|下发|修改|变更|apply|execute|push|commit)"
    r"[^，,。；;！？!?]{0,32}"
    r"|(?:do\s+not|don't|never)\s+(?:execute|apply|push|commit)"
    r"[^,.;!?]{0,32}",
    re.IGNORECASE,
)

_FEATURE_OPTIONS = (
    {"field": "feature", "value": "baseline", "label": "新设备基础配置"},
    {"field": "feature", "value": "vlan", "label": "VLAN / Access / Trunk"},
    {"field": "feature", "value": "ospf", "label": "OSPF"},
    {"field": "feature", "value": "static_route", "label": "静态路由"},
    {"field": "feature", "value": "stp", "label": "STP"},
    {"field": "feature", "value": "management", "label": "SSH / SNMP / NTP"},
    {"field": "feature", "value": "acl", "label": "ACL"},
    {"field": "feature", "value": "port_security", "label": "端口安全 / Port Security"},
)

_PLATFORM_LABELS = {
    "huawei_vrp5_v200": "Huawei VRP5（V200）",
    "huawei_yunshan_v300": "Huawei YunShan（V300）",
    "huawei_yunshan_v600": "Huawei YunShan（V600）",
    "huawei_vrp": "Huawei VRP",
    "huawei_vrpv8": "Huawei VRP8",
    "huawei_vrp_v200": "Huawei VRP（V200）",
    "huawei_vrp_v300": "Huawei VRP（V300）",
    "huawei_vrp_v600": "Huawei VRP（V600）",
    "h3c_comware": "H3C Comware",
    "h3c_comware7": "H3C Comware 7",
    "cisco_iosxe": "Cisco IOS XE",
    "cisco_ios": "Cisco IOS",
    "cisco_nxos": "Cisco NX-OS",
}


def clarification_policy_enabled(tenant_id: str | None = None) -> bool:
    """Return the deterministic rollout decision for the configuration guard."""

    enabled = str(os.environ.get("AI_CONFIG_CLARIFICATION_ENABLED", "1") or "1").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return False
    try:
        rollout = max(0, min(100, int(os.environ.get("AI_CONFIG_CLARIFICATION_ROLLOUT_PERCENT", "100"))))
    except (TypeError, ValueError):
        rollout = 100
    if rollout >= 100:
        return True
    if rollout <= 0:
        return False
    identity = str(tenant_id or "tenant-default").encode("utf-8")
    bucket = int(hashlib.sha256(identity).hexdigest()[:8], 16) % 100
    return bucket < rollout


def _text(value: Any, limit: int = 160) -> str:
    return sanitize_text(str(value or "")).strip()[:limit]


def _resolution_dict(resolution: Any) -> dict[str, Any]:
    if hasattr(resolution, "to_dict"):
        value = resolution.to_dict()
    else:
        value = resolution
    return dict(value) if isinstance(value, Mapping) else {}


def _scope_fields(metadata: Mapping[str, Any] | None, context: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge parser/request fields with explicit Copilot context.

    Context is only used as an additive source.  It never overwrites an
    explicit request field, because a user correction must win over a stale
    selected-device value.
    """

    result = dict(metadata or {})
    context = context or {}
    aliases = {
        "product_model": ("model",),
        "cli_platform": ("platform", "os"),
        "software_release": ("version",),
        "device_identifier": ("device_id",),
    }
    for target, candidates in aliases.items():
        if result.get(target) not in (None, "", [], {}):
            continue
        for candidate in candidates:
            value = context.get(candidate)
            if value not in (None, "", [], {}):
                result[target] = value
                break
    for key in ("vendor", "product_series", "feature", "feature_domain", "impact_scope"):
        if result.get(key) in (None, "", [], {}) and context.get(key) not in (None, "", [], {}):
            result[key] = context[key]
    return result


def merge_context_fields(metadata: Mapping[str, Any] | None, context: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return request metadata enriched by explicit Copilot context fields."""

    return _scope_fields(metadata, context)


def _platform_options(*, vendor: str, resolution: Mapping[str, Any]) -> list[dict[str, str]]:
    candidates = resolution.get("platform_candidates") or resolution.get("candidates") or []
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        # Product resolver candidates are rich internal records.  Only the
        # reviewed platform scalar may cross into a user-visible option; never
        # stringify the whole mapping (it can contain tenant/model metadata).
        if isinstance(candidate, Mapping):
            candidate = candidate.get("cli_platform")
        if not isinstance(candidate, str):
            continue
        value = canonical_cli_platform(_text(candidate, 96))
        if not value or value in seen:
            continue
        seen.add(value)
        options.append({"field": "cli_platform", "value": value, "label": _PLATFORM_LABELS.get(value, value.replace("_", " "))})
    if vendor.lower() == "huawei":
        # These are platform choices only.  No document body is exposed while
        # the request is still incomplete.
        for value, label in (
            ("huawei_vrp", "Huawei VRP"),
            ("huawei_yunshan_v300", "Huawei YunShan V300"),
            ("huawei_yunshan_v600", "Huawei YunShan V600"),
        ):
            if value not in seen:
                options.append({"field": "cli_platform", "value": value, "label": label})
    elif vendor.lower() == "cisco":
        # Keep vendor switching useful without broadening retrieval.  These
        # are bounded platform choices; document bodies are still withheld
        # until the operator selects one or supplies an exact model/version.
        for value, label in (
            ("cisco_iosxe", "Cisco IOS XE"),
            ("cisco_ios", "Cisco IOS"),
            ("cisco_nxos", "Cisco NX-OS"),
        ):
            if value not in seen:
                options.append({"field": "cli_platform", "value": value, "label": label})
    elif vendor.lower() == "h3c":
        # 华三、新华三和 H3C 统一进入 Comware 平台边界；具体 V5/V7/V9
        # 仍由设备型号或 display version 决定，不能在缺少证据时猜测。
        if "h3c_comware" not in seen:
            options.append({"field": "cli_platform", "value": "h3c_comware", "label": "H3C Comware"})
    options.append({"field": "cli_platform", "value": "display_version", "label": "我不确定，提供 display version"})
    return options[:8]


def _display_value(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_text(item, 80) for item in list(value)[:4] if _text(item, 80))
    return _text(value, 120)


def _has_positive_change_marker(message: str) -> bool:
    normalized = " ".join(str(message or "").lower().split())
    actionable = _NEGATED_CHANGE_RE.sub(" ", normalized)
    return any(marker in actionable for marker in _CHANGE_MARKERS)


@dataclass(frozen=True)
class ClarificationDecision:
    """Safe, bounded result consumed by the Assistant and Copilot UI."""

    required: bool
    request_kind: str
    risk: str
    reason_code: str | None = None
    missing_fields: tuple[str, ...] = ()
    recognized_fields: dict[str, str] = field(default_factory=dict)
    question: str = ""
    options: tuple[dict[str, str], ...] = ()
    allow_free_text: bool = True
    allow_generic_reference: bool = False
    retrieval_allowed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "request_kind": self.request_kind,
            "risk": self.risk,
            "reason_code": self.reason_code,
            "missing_fields": list(self.missing_fields),
            "recognized_fields": dict(self.recognized_fields),
            "question": self.question,
            "options": [dict(item) for item in self.options],
            "allow_free_text": self.allow_free_text,
            "allow_generic_reference": self.allow_generic_reference,
            "retrieval_allowed": self.retrieval_allowed,
        }


def _request_kind(*, message: str, category: str) -> tuple[str, str]:
    lower = str(message or "").lower()
    if any(marker in lower for marker in _FULL_CONFIG_MARKERS):
        return "running_config_export", "medium"
    if _has_positive_change_marker(message):
        return "configuration_change", "high"
    if category in {"command", "cli_output"}:
        return "read_only_command", "low"
    return "configuration_reference", "medium"


def assess_configuration_request(
    *,
    message: str,
    metadata: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    resolution: Any = None,
) -> ClarificationDecision | None:
    """Assess a knowledge request before any content retrieval.

    ``None`` means the request is not a configuration/CLI request and should
    remain on the existing knowledge path.  Read-only command questions are
    intentionally not blocked by this policy unless the caller supplies a
    separate high-risk context.
    """

    raw = dict(metadata or {})
    category = str(raw.get("document_category") or raw.get("knowledge_type") or "").lower()
    if category not in {"configuration", "command", "cli_output"}:
        return None

    kind, risk = _request_kind(message=message, category=category)
    scope = _scope_fields(raw, context)
    resolved = _resolution_dict(resolution)
    vendor = _text(scope.get("vendor"))
    feature = _text(scope.get("feature"))
    target = _text(scope.get("device_identifier"))
    platform = _text(scope.get("cli_platform"))
    product_model = _text(scope.get("product_model"))
    product_series = _text(scope.get("product_series"))
    software_version = _text(scope.get("software_release") or scope.get("software_train"))
    ambiguous = bool(resolved.get("ambiguous"))
    platform_known = bool(platform) or bool((product_model or product_series) and not ambiguous)
    generic_requested = any(marker in str(message or "") for marker in _GENERIC_MARKERS)

    recognized: dict[str, str] = {}
    for key, value in (
        ("vendor", vendor),
        ("product_series", product_series),
        ("product_model", product_model),
        ("cli_platform", platform),
        ("software_version", software_version),
        ("feature", feature),
        ("target_device", target),
    ):
        if value:
            recognized[key] = value

    missing: list[str] = []
    reason_code: str | None = None
    if kind == "read_only_command":
        msg_lower = str(message or "").lower()
        v_low = vendor.lower()
        if v_low == "cisco" and re.search(r"\bdisplay\b", msg_lower):
            return ClarificationDecision(
                required=True,
                request_kind=kind,
                risk=risk,
                reason_code="CLI_DIALECT_CONFLICT",
                recognized_fields=recognized,
                question="Cisco 设备使用的是 show 命令体系，未定义 display 命令。请确认是否查询对应的 show 命令？",
                options=(
                    {"field": "command_dialect", "value": "show", "label": "纠正为 Cisco show 命令查询"},
                ),
                allow_free_text=True,
                allow_generic_reference=False,
                retrieval_allowed=False,
            )
        if v_low in ("huawei", "h3c") and re.search(r"\bshow\b", msg_lower):
            return ClarificationDecision(
                required=True,
                request_kind=kind,
                risk=risk,
                reason_code="CLI_DIALECT_CONFLICT",
                recognized_fields=recognized,
                question=f"{vendor} 设备使用的是 display 命令体系，未定义 show 命令。请确认是否查询对应的 display 命令？",
                options=(
                    {"field": "command_dialect", "value": "display", "label": f"纠正为 {vendor} display 命令查询"},
                ),
                allow_free_text=True,
                allow_generic_reference=False,
                retrieval_allowed=False,
            )

        # Existing cross-platform command explanations remain available, but
        # the response is still bounded by the normal command renderer.
        return ClarificationDecision(
            required=False,
            request_kind=kind,
            risk=risk,
            recognized_fields=recognized,
            allow_generic_reference=True,
        )

    if kind == "running_config_export":
        if not target:
            missing.append("target_device")
            reason_code = "MISSING_TARGET_DEVICE"
        return ClarificationDecision(
            required=True,
            request_kind=kind,
            risk=risk,
            reason_code=reason_code,
            missing_fields=tuple(missing),
            recognized_fields=recognized,
            question=(
                "请先指定要读取当前配置的设备，例如设备名称或设备 ID。"
                if missing
                else "已识别目标设备；当前配置应从设备只读数据源获取，而不是从知识库拼接。"
            ),
            options=({"field": "target_device", "value": "current_device", "label": "使用当前选中设备"},) if missing else (),
            allow_generic_reference=False,
            retrieval_allowed=False,
        )

    if not feature:
        # A concrete model/platform plus an interface/port request is already
        # a safe, bounded configuration scope even when no canonical feature
        # alias (VLAN, trunk, access, ...) was extracted.  Requiring a second
        # clarification here used to turn valid access/uplink questions into
        # empty results despite matching official templates.
        if vendor and platform_known and any(marker in str(message or "").lower() for marker in _SCOPED_CONFIGURATION_MARKERS):
            return ClarificationDecision(
                required=False,
                request_kind=kind,
                risk=risk,
                recognized_fields=recognized,
                allow_generic_reference=False,
            )
        missing.append("feature")
        reason_code = "MISSING_CONFIGURATION_FEATURE"
    if not platform_known:
        missing.append("platform_or_model")
        reason_code = reason_code or "MISSING_PLATFORM_OR_MODEL"

    if not missing:
        return ClarificationDecision(
            required=False,
            request_kind=kind,
            risk=risk,
            recognized_fields=recognized,
            allow_generic_reference=generic_requested,
        )

    if "feature" in missing and "platform_or_model" in missing:
        question = "你想配置哪项功能？同时请提供设备型号/OS 或 display version 回显。"
    elif "feature" in missing:
        question = "已识别设备范围，请说明需要配置的功能，例如 VLAN、OSPF、静态路由或 SSH。"
    else:
        question = "已识别配置功能，请提供设备型号、CLI 平台或软件版本；也可以粘贴 display version 回显。"

    options: list[dict[str, str]] = []
    if "feature" in missing:
        options.extend(_FEATURE_OPTIONS)
    if "platform_or_model" in missing:
        options.extend(_platform_options(vendor=vendor, resolution=resolved))
    return ClarificationDecision(
        required=True,
        request_kind=kind,
        risk=risk,
        reason_code=reason_code,
        missing_fields=tuple(missing),
        recognized_fields=recognized,
        question=question,
        options=tuple(options[:12]),
        allow_free_text=True,
        allow_generic_reference=generic_requested,
        retrieval_allowed=False,
    )


def render_clarification_answer(decision: ClarificationDecision) -> str:
    """Render a concise operator-facing clarification message."""

    if decision.request_kind == "running_config_export":
        lines = [
            "当前请求看起来是读取设备的全量/运行配置。",
            "这类内容必须来自目标设备的授权只读数据源，不能从知识库文档拼接或直接返回。",
        ]
        if decision.missing_fields:
            lines.append(decision.question)
            if decision.options:
                lines.append("你可以选择当前选中设备，或在输入框中补充设备名称/设备 ID。")
        else:
            lines.append("已识别目标设备；请改用设备配置查看/备份功能获取实时配置。")
        return "\n\n".join(lines)

    lines = ["可以帮你整理配置，但当前范围还不够明确。为了避免返回不适用的命令，请先补充："]
    if decision.recognized_fields:
        labels = {
            "vendor": "厂商",
            "product_series": "产品系列",
            "product_model": "型号",
            "cli_platform": "CLI 平台",
            "software_version": "软件版本",
            "feature": "配置功能",
            "target_device": "目标设备",
        }
        recognized = "；".join(
            f"{labels.get(key, key)}：{value}"
            for key, value in decision.recognized_fields.items()
        )
        lines.append(f"已识别：{recognized}")
    lines.append(decision.question)
    if decision.options:
        lines.append("你可以直接选择一个常用选项，或在输入框中补充具体信息。")
    if "platform_or_model" in decision.missing_fields:
        lines.append("如果不清楚型号，可以粘贴 display version 回显；在信息补齐前不会直接输出整套知识库配置。")
    return "\n\n".join(lines)


def render_clarification_payload(payload: Mapping[str, Any] | None) -> str:
    """Render a previously serialized clarification object safely."""

    data = dict(payload or {})
    recognized = data.get("recognized_fields") if isinstance(data.get("recognized_fields"), Mapping) else {}
    missing = data.get("missing_fields") if isinstance(data.get("missing_fields"), (list, tuple)) else []
    options = data.get("options") if isinstance(data.get("options"), (list, tuple)) else []
    normalized_options = tuple(
        {
            "field": _text(item.get("field"), 64),
            "value": _text(item.get("value"), 96),
            "label": _text(item.get("label"), 160),
        }
        for item in options
        if isinstance(item, Mapping) and _text(item.get("value"), 96) and _text(item.get("label"), 160)
    )
    decision = ClarificationDecision(
        required=bool(data.get("required", True)),
        request_kind=_text(data.get("request_kind"), 80),
        risk=_text(data.get("risk"), 32),
        reason_code=_text(data.get("reason_code"), 96) or None,
        missing_fields=tuple(_text(item, 80) for item in missing if _text(item, 80)),
        recognized_fields={_text(key, 64): _text(value, 160) for key, value in recognized.items() if _text(key, 64) and _text(value, 160)},
        question=_text(data.get("question"), 600),
        options=normalized_options,
        allow_free_text=bool(data.get("allow_free_text", True)),
        allow_generic_reference=bool(data.get("allow_generic_reference", False)),
        retrieval_allowed=bool(data.get("retrieval_allowed", False)),
    )
    return render_clarification_answer(decision)


__all__ = [
    "ClarificationDecision",
    "assess_configuration_request",
    "clarification_policy_enabled",
    "merge_context_fields",
    "render_clarification_answer",
    "render_clarification_payload",
]
