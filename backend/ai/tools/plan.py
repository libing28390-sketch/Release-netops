"""Tool-call planning, compatibility checks, and one-time confirmations."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from collections.abc import Mapping
from typing import Any, Iterable

from ai.schemas.tool import ToolCallPlan, ToolPlanStatus
from ai.security.classification import classify_text
from ai.tools.risk import ToolRiskLevel


_RISK_ORDER = {
    ToolRiskLevel.R0_READ_ONLY.value: 0,
    ToolRiskLevel.R1_LOW.value: 1,
    ToolRiskLevel.R2_MEDIUM.value: 2,
    ToolRiskLevel.R3_HIGH.value: 3,
    ToolRiskLevel.R4_CRITICAL.value: 4,
}
_DANGEROUS_MARKERS = (
    "shutdown", "reload", "reboot", "erase", "reset", "delete", "remove",
    "write memory", "commit", "configure terminal", "system-view", "snmp set",
    "下发", "修改", "变更", "删除", "清空", "重启", "重载", "批量",
)
_ACTION_MARKERS = ("action", "operation", "command", "cmd")
_SENSITIVE_ARGUMENT_KEY_MARKERS = frozenset({
    "password", "passwd", "secret", "community", "token", "apikey",
    "accesstoken", "privatekey", "credential", "authorization", "cookie",
    "rawoutput", "rawconfig", "runningconfig", "currentconfiguration",
    "toolargs", "requestbody",
})
_SENSITIVE_VALUE_CATEGORIES = frozenset({
    "credential", "snmp_community", "radius_or_tacacs_key", "private_key",
    "jwt", "cookie",
})
_SENSITIVE_VALUE_MARKER_RE = re.compile(
    r"(?i)(?:password|passwd|secret|community|api[_ -]?key|access[_ -]?token|"
    r"private[_ -]?key|credential|authorization\s*[:=]|bearer\s+|"
    r"snmp(?:-agent|-server)?\s+community)"
)


class ToolPlanError(ValueError):
    """Stable, non-sensitive planning error."""

    def __init__(self, code: str, message: str = "tool call plan rejected") -> None:
        super().__init__(message)
        self.code = code


def _text(value: Any, limit: int = 256) -> str:
    return str(value or "").strip()[:limit]


def _sensitive_argument_key(key: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key or "").casefold())
    return any(marker in normalized for marker in _SENSITIVE_ARGUMENT_KEY_MARKERS)


def _contains_sensitive_arguments(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            _sensitive_argument_key(key) or _contains_sensitive_arguments(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set)):
        return any(_contains_sensitive_arguments(item) for item in value)
    if isinstance(value, str):
        if _SENSITIVE_VALUE_MARKER_RE.search(value):
            return True
        return any(item.category in _SENSITIVE_VALUE_CATEGORIES for item in classify_text(value))
    return False


def _max_risk(left: ToolRiskLevel, right: ToolRiskLevel) -> ToolRiskLevel:
    return left if _RISK_ORDER[left.value] >= _RISK_ORDER[right.value] else right


def infer_risk_level(
    *,
    declared: str,
    read_only: bool,
    tool_name: str,
    arguments: dict[str, Any],
) -> ToolRiskLevel:
    """Raise a tool's declared risk when action text contains write markers."""

    try:
        risk = ToolRiskLevel(str(declared).upper())
    except ValueError:
        raise ToolPlanError("TOOL_RISK_INVALID") from None
    if not read_only:
        risk = _max_risk(risk, ToolRiskLevel.R3_HIGH)
    serialized = json.dumps({"tool_name": tool_name, "arguments": arguments}, ensure_ascii=False, default=str).lower()
    if any(marker in serialized for marker in _DANGEROUS_MARKERS):
        risk = _max_risk(risk, ToolRiskLevel.R3_HIGH)
    if any(key in arguments for key in _ACTION_MARKERS) and risk == ToolRiskLevel.R0_READ_ONLY:
        risk = ToolRiskLevel.R2_MEDIUM
    if any(marker in serialized for marker in ("delete all", "erase all", "drop database", "清空全部", "批量删除")):
        risk = ToolRiskLevel.R4_CRITICAL
    return risk


def _plan_fingerprint(plan: ToolCallPlan) -> str:
    payload = plan.model_dump(mode="json", exclude={"confirmation_token", "status", "dry_run"})
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


class ToolConfirmationStore:
    """In-memory, short-lived, single-use approval token store.

    Tokens are never persisted or logged.  The fingerprint binds approval to
    the complete plan, so changing a device, command, or argument invalidates
    the prior approval.
    """

    def __init__(self, *, ttl_seconds: int = 300) -> None:
        self.ttl_seconds = max(30, min(int(ttl_seconds), 1800))
        self._tokens: dict[str, tuple[str, str, str, float, bool]] = {}
        self._lock = threading.RLock()

    def _purge(self, now: float) -> None:
        expired = [token for token, item in self._tokens.items() if item[3] <= now]
        for token in expired:
            self._tokens.pop(token, None)

    def issue(self, plan: ToolCallPlan, *, tenant_id: str, user_id: str | None) -> str:
        if not plan.requires_confirmation:
            raise ToolPlanError("TOOL_CONFIRMATION_NOT_REQUIRED")
        token = secrets.token_urlsafe(32)
        owner = _text(user_id, 160)
        tenant = _text(tenant_id, 160) or "tenant-default"
        with self._lock:
            now = time.time()
            self._purge(now)
            self._tokens[token] = (_plan_fingerprint(plan), tenant, owner, now + self.ttl_seconds, False)
        return token

    def consume(
        self,
        plan: ToolCallPlan,
        token: str | None,
        *,
        tenant_id: str,
        user_id: str | None,
    ) -> None:
        if not token:
            raise ToolPlanError("TOOL_CONFIRMATION_REQUIRED")
        with self._lock:
            now = time.time()
            self._purge(now)
            item = self._tokens.get(str(token))
            if item is None:
                raise ToolPlanError("TOOL_CONFIRMATION_INVALID")
            fingerprint, owner_tenant, owner_user, _expires, used = item
            if used or owner_tenant != (_text(tenant_id, 160) or "tenant-default") or owner_user != _text(user_id, 160):
                raise ToolPlanError("TOOL_CONFIRMATION_INVALID")
            if fingerprint != _plan_fingerprint(plan):
                raise ToolPlanError("TOOL_CONFIRMATION_INVALID")
            self._tokens[str(token)] = (fingerprint, owner_tenant, owner_user, _expires, True)


def build_tool_call_plan(
    spec: Any,
    arguments: dict[str, Any],
    *,
    tool_name: str,
    tenant_id: str,
    user_id: str | None,
    dry_run: bool = True,
    change_order_id: str | None = None,
    device_state: str | None = None,
    impact_scope: str | None = None,
    confirmation_token: str | None = None,
) -> tuple[ToolCallPlan, dict[str, Any]]:
    """Validate arguments and return a plan plus safe handler arguments."""

    del tenant_id, user_id
    if not isinstance(arguments, dict):
        raise ToolPlanError("TOOL_ARGUMENTS_INVALID")
    if _contains_sensitive_arguments(arguments):
        # Do not include the offending key/value in a plan, error, audit row,
        # or UI response.
        raise ToolPlanError("TOOL_SENSITIVE_ARGUMENTS_BLOCKED")
    try:
        validated = spec.input_model.model_validate(arguments)
    except Exception:
        raise ToolPlanError("TOOL_ARGUMENTS_INVALID") from None
    safe_arguments = validated.model_dump()
    device_id = _text(safe_arguments.get("device_id") or safe_arguments.get("device_identifier"), 160) or None
    vendor = _text(safe_arguments.get("vendor"), 96) or None
    platform = _text(safe_arguments.get("platform") or safe_arguments.get("cli_platform"), 128) or None
    declared = str(getattr(spec, "risk_level", "R0") or "R0")
    risk = infer_risk_level(
        declared=declared,
        read_only=bool(getattr(spec, "read_only", True)),
        tool_name=tool_name,
        arguments=safe_arguments,
    )
    supported_vendors = {str(value).strip().lower() for value in (getattr(spec, "supported_vendors", ()) or ()) if str(value).strip()}
    supported_platforms = {str(value).strip().lower() for value in (getattr(spec, "supported_platforms", ()) or ()) if str(value).strip()}
    if supported_vendors and vendor and vendor.lower() not in supported_vendors:
        raise ToolPlanError("TOOL_VENDOR_INCOMPATIBLE")
    if supported_platforms and platform and platform.lower() not in supported_platforms:
        raise ToolPlanError("TOOL_PLATFORM_INCOMPATIBLE")
    high_risk = risk in {ToolRiskLevel.R3_HIGH, ToolRiskLevel.R4_CRITICAL} or not bool(getattr(spec, "read_only", True))
    requires_confirmation = high_risk
    action = next((_text(safe_arguments.get(key), 96) for key in _ACTION_MARKERS if safe_arguments.get(key)), None)
    if not action:
        action = "read" if bool(getattr(spec, "read_only", True)) else tool_name
    status = ToolPlanStatus.CONFIRMATION_REQUIRED if requires_confirmation and not confirmation_token else ToolPlanStatus.READY
    plan = ToolCallPlan(
        tool_name=tool_name,
        arguments=safe_arguments,
        device_id=device_id,
        vendor=vendor,
        platform=platform,
        action=action,
        risk_level=risk,
        read_only=bool(getattr(spec, "read_only", True)),
        requires_confirmation=requires_confirmation,
        dry_run=bool(dry_run) if not requires_confirmation else not bool(confirmation_token),
        change_order_id=_text(change_order_id, 160) or None,
        device_state=_text(device_state, 96) or None,
        impact_scope=_text(impact_scope, 512) or None,
        expected_impact=[
            "只读查询，不修改设备" if bool(getattr(spec, "read_only", True)) else "可能改变目标设备状态",
        ],
        status=status,
        confirmation_token=_text(confirmation_token, 256) or None,
    )
    if requires_confirmation and not change_order_id and not bool(getattr(spec, "read_only", True)):
        raise ToolPlanError("TOOL_CHANGE_ORDER_REQUIRED")
    if requires_confirmation and confirmation_token and not bool(getattr(spec, "read_only", True)):
        if not plan.device_state:
            raise ToolPlanError("TOOL_DEVICE_STATE_REQUIRED")
        if not plan.impact_scope:
            raise ToolPlanError("TOOL_IMPACT_SCOPE_REQUIRED")
    return plan, safe_arguments


tool_confirmation_store = ToolConfirmationStore()


__all__ = [
    "ToolConfirmationStore",
    "ToolPlanError",
    "build_tool_call_plan",
    "infer_risk_level",
    "tool_confirmation_store",
]
