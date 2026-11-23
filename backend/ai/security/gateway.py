"""Fail-closed AI security gateway used by every external model call."""

from __future__ import annotations

import json
import hashlib
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace as _dataclass_replace
from fnmatch import fnmatchcase
from typing import Any
from urllib.parse import urlparse

from core.config import settings
from ai.security.classification import (
    DataClassification,
    DataLevel,
    Finding,
    SecurityAction,
    action_for,
    classify,
    classification_for_level,
    normalize_classification,
    request_policy_findings,
    separate_data_and_instructions,
    redact_secrets,
)
from ai.security.dev_passthrough import dev_passthrough
from ai.security.dlp import assert_clean
from ai.security.minimizer import minimize, minimize_tool_result
from ai.security.tokenization import ScopedTokenVault, opaque_user_id, tokenize_text, token_vault, provider_user_id

logger = logging.getLogger(__name__)


class SecurityBlocked(Exception):
    """A provider call was refused before an outbound request was built."""

    code = "AI_SECURITY_BLOCKED"
    status_code = 403

    def __init__(self, reason: str, *, findings: list[Finding] | None = None, reason_code: str = "AI_SECURITY_BLOCKED"):
        # ``reason`` is retained for server-side diagnostics.  User-facing
        # clients should use the stable code/message and never receive raw
        # detector text or matched values.
        super().__init__(reason)
        self.reason = reason
        self.reason_code = reason_code
        self.user_message = {
            "AI_SECURITY_KILL_SWITCH": "AI 外部调用已被安全开关暂停。",
            "AI_SECURITY_POLICY_DISABLED": "当前安全策略不允许外部 AI 调用。",
            "AI_SECURITY_PROVIDER_DENIED": "当前供应商未通过安全策略。",
            "AI_SECURITY_CLASSIFICATION_DENIED": "当前数据分类不允许发送到该模型。",
            "AI_SECURITY_SCOPE_DENIED": "当前请求超出授权数据范围。",
            "AI_SECURITY_SENSITIVE_DATA": "检测到敏感内容，请移除凭据或缩小上下文后重试。",
            "AI_SECURITY_UNSAFE_TOOL": "该操作包含未授权的写入或不受限工具。",
            "AI_SECURITY_DLP_FAILED": "安全检查未通过，内容未发送。",
        }.get(reason_code, "请求未通过 AI 安全策略，内容未发送。")
        self.findings = findings or []


@dataclass(frozen=True)
class SecurityPolicy:
    external_ai_enabled: bool = False
    kill_switch: bool = False
    max_payload_bytes: int = 256_000
    identifiers_must_be_tokenized: bool = True
    allow_sensitive_minimization: bool = True
    allowed_provider_types: tuple[str, ...] = (
        "deepseek", "openai", "openai_compatible", "azure_openai", "ollama", "local", "qwen",
    )
    policy_version: str = "sec-v2.0"
    allowed_classifications: tuple[str, ...] = ("PUBLIC", "INTERNAL", "CONFIDENTIAL")
    allowed_data_regions: tuple[str, ...] = ("unknown", "global", "cn", "us", "eu")
    provider_kill_switches: dict[str, bool] = field(default_factory=dict)
    tenant_kill_switches: dict[str, bool] = field(default_factory=dict)
    scope_rules: dict[str, Any] = field(default_factory=dict)


@dataclass
class SecurePayload:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None
    user_id: str
    tenant_id: str
    task_id: str
    level: DataLevel
    action: SecurityAction
    provider_options: dict[str, Any] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_provider_json(self) -> str:
        return json.dumps(
            {"messages": self.messages, "tools": self.tools, "user": self.user_id, "provider_options": self.provider_options},
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )


@dataclass
class SecureEmbeddingPayload:
    texts: list[str]
    tenant_id: str
    task_id: str
    level: DataLevel
    action: SecurityAction
    findings: list[Finding] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_provider_json(self) -> str:
        return json.dumps(
            {"texts": self.texts, "tenant_id": self.tenant_id, "task_id": self.task_id, "metadata": self.metadata},
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )


def _redact_cn_secrets(value: Any) -> tuple[Any, int]:
    """Redact credential values in every string of a payload.

    Chinese (batch 6) and English (task d1) credential values, SNMP
    communities, RADIUS/TACACS keys, private-key blocks, JWTs and cookie
    values are replaced (see ``redact_secrets``); the request continues and
    the model never sees the value.  The final DLP check still refuses
    anything left over.  Field *names* are not changed: a sensitive field
    name such as ``api_key`` is still blocked by ``_has_sensitive_field``.
    """

    total = 0

    def transform(text: str) -> str:
        nonlocal total
        redacted, count = redact_secrets(text)
        total += count
        return redacted

    redacted = _walk_transform(value, transform)
    return redacted, total


_redact_secrets = _redact_cn_secrets


def _walk_transform(value: Any, transform) -> Any:
    if isinstance(value, str):
        return transform(value)
    if isinstance(value, list):
        return [_walk_transform(item, transform) for item in value]
    if isinstance(value, dict):
        return {str(key): _walk_transform(item, transform) for key, item in value.items()}
    return value


_CREDENTIAL_FIELD_MARKERS = frozenset({
    "password", "passwd", "secret", "community", "token", "apikey",
    "accesstoken", "privatekey", "credential", "authorization", "cookie",
})

# These fields identify opaque/sensitive context in the normal protection
# path.  Temporary test mode deliberately does not block the non-credential
# context markers; its contract is a blacklist of hard controls rather than a
# second classification policy.
_SENSITIVE_FIELD_MARKERS = frozenset({
    *_CREDENTIAL_FIELD_MARKERS,
    "rawoutput", "rawconfig", "runningconfig", "currentconfiguration",
    "toolargs", "requestbody",
})

_BLACKLIST_DLP_FINDING_CATEGORIES = frozenset({
    "credential", "snmp_community", "radius_or_tacacs_key", "private_key", "jwt", "cookie",
    "credential_field",
})
_BLACKLIST_WRITE_FINDING_CATEGORIES = frozenset({"change_command"})


def _has_field_marker(value: Any, markers: frozenset[str]) -> bool:
    """Detect secret-bearing field names even when the value is opaque.

    A key such as ``api_key`` is sensitive by contract even if its test value
    does not match a token regex.  This closes the nested dict/list gap before
    minimization or tokenization can build an outbound provider body.
    """

    if isinstance(value, dict):
        for key, item in value.items():
            normalized = "".join(char for char in str(key).casefold() if char.isalnum())
            if any(marker in normalized for marker in markers):
                return True
            if _has_field_marker(item, markers):
                return True
    elif isinstance(value, (list, tuple, set)):
        return any(_has_field_marker(item, markers) for item in value)
    return False


def _has_sensitive_field(value: Any) -> bool:
    return _has_field_marker(value, _SENSITIVE_FIELD_MARKERS)


def _has_credential_field(value: Any) -> bool:
    return _has_field_marker(value, _CREDENTIAL_FIELD_MARKERS)


def _tool_is_unsafe(tool: dict[str, Any]) -> bool:
    text = json.dumps(tool, ensure_ascii=False, default=str).lower()
    forbidden = (
        "raw_ssh", "raw ssh", "raw_sql", "raw sql", "snmp set", "snmpset",
        "configure terminal", "system-view", "write memory", "commit", "delete ",
        "下发配置", "修改配置", "变更配置", "删除配置", "清空配置", "重启设备", "重载设备",
        "批量关闭", "批量启用", "批量开启", "批量变更", "批量操作", "批量下发",
        "关闭端口", "关闭接口", "禁用端口", "禁用接口", "全网变更", "全网操作",
    )
    return any(marker in text for marker in forbidden)


def _classification_rank(value: DataClassification | str | None) -> int:
    try:
        return {
            DataClassification.PUBLIC.value: 1,
            DataClassification.INTERNAL.value: 2,
            DataClassification.CONFIDENTIAL.value: 3,
            DataClassification.SECRET.value: 4,
        }[str(value.value if isinstance(value, DataClassification) else value or "").upper()]
    except KeyError:
        return 0


# ── Deployment-level egress ceiling ──────────────────────────────────────
# The environment flags belong to whoever operates the deployment.  They are a
# hard ceiling on the database policy that administrators edit in the UI:
# AI_ENABLED / EXTERNAL_AI_ENABLED can only take egress away and
# AI_KILL_SWITCH can only add a stop.  Nothing stored in the database can
# override them (ADR-006).


def deployment_egress_allowed() -> bool:
    return bool(getattr(settings, "AI_ENABLED", False)) and bool(getattr(settings, "EXTERNAL_AI_ENABLED", False))


def deployment_kill_switch() -> bool:
    return bool(getattr(settings, "AI_KILL_SWITCH", False))


def deployment_status() -> dict[str, bool]:
    return {
        "ai_enabled": bool(getattr(settings, "AI_ENABLED", False)),
        "external_ai_enabled": bool(getattr(settings, "EXTERNAL_AI_ENABLED", False)),
        "kill_switch": deployment_kill_switch(),
        "egress_allowed": deployment_egress_allowed() and not deployment_kill_switch(),
        "network_write_enabled": bool(getattr(settings, "NETWORK_WRITE_ENABLED", False)),
        "production_credentials_allowed": bool(getattr(settings, "PRODUCTION_CREDENTIALS_ALLOWED", False)),
    }


def apply_deployment_limits(policy: "SecurityPolicy") -> "SecurityPolicy":
    """Intersect a stored policy with the deployment flags."""

    external = bool(policy.external_ai_enabled) and deployment_egress_allowed()
    kill = bool(policy.kill_switch) or deployment_kill_switch()
    if external == policy.external_ai_enabled and kill == policy.kill_switch:
        return policy
    return _dataclass_replace(policy, external_ai_enabled=external, kill_switch=kill)


def endpoint_host(url: Any) -> str:
    try:
        return (urlparse(str(url or "").strip()).hostname or "").lower()
    except ValueError:
        return ""


def deployment_endpoint_allowed(url: Any) -> bool:
    """Check a provider URL against ``AI_PROVIDER_ENDPOINT_ALLOWLIST``.

    The setting is a comma-separated list of host names (``*.example.com``
    wildcards allowed).  It is maintained outside the application, so the
    permission that edits a Provider cannot also approve its destination.
    An empty setting adds no restriction.
    """

    raw = str(getattr(settings, "AI_PROVIDER_ENDPOINT_ALLOWLIST", "") or "")
    patterns = []
    for item in raw.split(","):
        item = item.strip().lower()
        if not item:
            continue
        if "://" in item:
            item = endpoint_host(item)
        if item:
            patterns.append(item)
    if not patterns:
        return True
    host = endpoint_host(url)
    return bool(host) and any(fnmatchcase(host, pattern) for pattern in patterns)


_UNSET = object()


class AISecurityGateway:
    def __init__(
        self,
        *,
        vault: ScopedTokenVault | None = None,
        policy: SecurityPolicy | None = None,
        enforce_deployment_flags: bool = False,
    ):
        self.vault = vault or token_vault
        # Bounded: keeps the latest evidence without growing for the life of the process.
        self._egress_audit_events: deque[dict[str, Any]] = deque(maxlen=1000)
        # Only the process-wide gateway enforces the deployment flags and
        # follows the persisted policy; gateways built with an explicit policy
        # (tools, dry runs, tests) evaluate exactly the policy they were given.
        self.enforce_deployment_flags = enforce_deployment_flags
        self._synced_policy: SecurityPolicy | None = None
        self._synced_fingerprint: Any = None
        self._last_refresh_check = 0.0
        self._refresh_lock = threading.Lock()
        self.policy = policy or SecurityPolicy(
            external_ai_enabled=False,
            kill_switch=bool(getattr(settings, "AI_KILL_SWITCH", False)),
            max_payload_bytes=int(getattr(settings, "AI_MAX_PAYLOAD_BYTES", 256_000)),
            allowed_provider_types=tuple(
                item.strip().lower().replace("-", "_")
                for item in str(getattr(settings, "AI_PROVIDER_ALLOWLIST", "deepseek,openai,openai_compatible,azure_openai,ollama,local,qwen")).split(",")
                if item.strip()
            ) or SecurityPolicy.allowed_provider_types,
        )

    # ── Policy lifecycle ────────────────────────────────────────────────
    def install_policy(self, policy: SecurityPolicy, *, fingerprint: Any = _UNSET) -> SecurityPolicy:
        """Install the operator policy loaded from (or just written to) the database.

        ``policy`` keeps the operator's stored values; deployment flags are
        applied when the policy is read (``effective_policy``), so the policy
        page can still show what the operator configured.
        """

        self.policy = policy
        self._synced_policy = policy
        if fingerprint is not _UNSET:
            self._synced_fingerprint = fingerprint
        self._last_refresh_check = time.monotonic()
        return policy

    def effective_policy(self) -> SecurityPolicy:
        """The policy that decides egress right now."""

        if not self.enforce_deployment_flags:
            return self.policy
        self._maybe_refresh_policy()
        return apply_deployment_limits(self.policy)

    def _maybe_refresh_policy(self) -> None:
        """Follow policy changes made by other worker processes.

        Each worker re-reads a cheap change marker at most every
        ``AI_POLICY_REFRESH_SECONDS`` and reloads the policy when it differs,
        so a kill switch set on one worker reaches every worker within that
        interval.
        """

        try:
            interval = max(0.0, float(getattr(settings, "AI_POLICY_REFRESH_SECONDS", 3.0)))
        except (TypeError, ValueError):
            interval = 3.0
        now = time.monotonic()
        if now - self._last_refresh_check < interval:
            return
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            self._last_refresh_check = now
            if self._synced_policy is not None and self.policy is not self._synced_policy:
                # The policy object was replaced outside install_policy
                # (an operator tool or a test fixture); leave it in place.
                return
            from ai.api.security import load_persisted_security_policy, read_policy_fingerprint

            fingerprint = read_policy_fingerprint()
            if fingerprint is None:
                return
            if self._synced_fingerprint is None:
                self._synced_fingerprint = fingerprint
                return
            if fingerprint != self._synced_fingerprint:
                load_persisted_security_policy()
        except Exception:  # pragma: no cover - keep serving with the last known policy
            logger.warning("AI security policy refresh failed; keeping the last loaded policy")
        finally:
            self._refresh_lock.release()

    def _resolve_policy(self, policy: SecurityPolicy | None) -> SecurityPolicy:
        if policy is None:
            return self.effective_policy()
        return apply_deployment_limits(policy) if self.enforce_deployment_flags else policy

    def assert_egress_allowed(
        self,
        *,
        provider_type: str | None,
        provider_id: str | None = None,
        data_region: str | None = None,
        tenant_id: str = "tenant-default",
        policy: SecurityPolicy | None = None,
    ) -> tuple[str, str]:
        """Egress eligibility of one concrete provider/model.

        Called for the primary model, for every fallback candidate and again
        right before each provider request, so a fallback can never bypass a
        kill switch, the provider allowlist or the data-region policy.
        Returns the normalized provider type and data region.
        """

        active_policy = policy if policy is not None else self.effective_policy()
        if active_policy.kill_switch:
            raise SecurityBlocked("AI external egress is disabled by the kill switch", reason_code="AI_SECURITY_KILL_SWITCH")
        if active_policy.tenant_kill_switches.get(str(tenant_id)):
            raise SecurityBlocked("tenant AI egress is disabled by the kill switch", reason_code="AI_SECURITY_KILL_SWITCH")
        if not active_policy.external_ai_enabled:
            raise SecurityBlocked("external AI is disabled by policy", reason_code="AI_SECURITY_POLICY_DISABLED")
        normalized_provider = str(provider_type or "").lower().replace("-", "_")
        if normalized_provider not in {item.lower().replace("-", "_") for item in active_policy.allowed_provider_types}:
            raise SecurityBlocked("provider is not allowed by the AI egress policy", reason_code="AI_SECURITY_PROVIDER_DENIED")
        if active_policy.provider_kill_switches.get(normalized_provider) or (provider_id and active_policy.provider_kill_switches.get(str(provider_id))):
            raise SecurityBlocked("provider is disabled by its kill switch", reason_code="AI_SECURITY_KILL_SWITCH")
        normalized_region = str(data_region or "unknown").strip().lower()
        if normalized_region not in {str(item).lower() for item in active_policy.allowed_data_regions}:
            raise SecurityBlocked("provider data region is not allowed", reason_code="AI_SECURITY_SCOPE_DENIED")
        return normalized_provider, normalized_region

    def _classify(self, value: Any) -> tuple[DataLevel, list[Finding]]:
        return classify(value)

    def protect(
        self,
        messages: list[dict[str, Any]],
        *,
        tenant_id: str = "tenant-default",
        task_id: str = "task-default",
        user_id: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        provider_options: dict[str, Any] | None = None,
        provider_type: str = "deepseek",
        policy: SecurityPolicy | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        data_classification: str | None = None,
        data_region: str | None = None,
        workspace_id: str | None = None,
        site_id: str | None = None,
        department: str | None = None,
        document_scope: str | None = None,
        user_role: str | None = None,
        provider_allowed_classification: str | None = None,
        provider_no_training_confirmed: bool = False,
        provider_retention_days: int | None = None,
        provider_data_processing_agreement_ref: str | None = None,
        scene: str | None = None,
    ) -> SecurePayload:
        active_policy = self._resolve_policy(policy)
        normalized_provider, normalized_region = self.assert_egress_allowed(
            provider_type=provider_type,
            provider_id=provider_id,
            data_region=data_region,
            tenant_id=tenant_id,
            policy=active_policy,
        )
        scope = {"tenant": tenant_id, "workspace": workspace_id, "site": site_id, "department": department, "document_scope": document_scope, "user_role": user_role}
        required_scope = active_policy.scope_rules or {}
        for key, allowed in required_scope.items():
            if allowed and str(scope.get(key) or "") not in {str(item) for item in (allowed if isinstance(allowed, (list, tuple, set)) else [allowed])}:
                raise SecurityBlocked("request is outside the configured data scope", reason_code="AI_SECURITY_SCOPE_DENIED")

        # Credential values (Chinese and English) are redacted, not blocked:
        # a vendor manual quoting "缺省密码为Admin@123" or a pasted
        # "password cipher ..." line must not stop the answer.  Tools and
        # provider options are redacted too, otherwise a value there would
        # only be caught by the final DLP check (task d1).
        messages, redacted_secrets = _redact_secrets(messages)
        if tools:
            tools, redacted_tool_secrets = _redact_secrets(tools)
            redacted_secrets += redacted_tool_secrets
        if provider_options:
            provider_options, redacted_option_secrets = _redact_secrets(provider_options)
            redacted_secrets += redacted_option_secrets

        combined = {"messages": messages, "tools": tools or [], "provider_options": provider_options or {}}
        non_system_messages = [
            msg for msg in messages
            if not (isinstance(msg, dict) and str(msg.get("role") or "").strip().lower() == "system")
        ]
        system_messages = [
            msg for msg in messages
            if isinstance(msg, dict) and str(msg.get("role") or "").strip().lower() == "system"
        ]
        level, findings = self._classify({
            "messages": non_system_messages,
            "tools": tools or [],
            "provider_options": provider_options or {},
        })
        if system_messages:
            _, sys_findings = self._classify({"messages": system_messages})
            sys_secret_findings = [
                item for item in sys_findings
                if item.level >= DataLevel.L4_PROHIBITED or item.category in _BLACKLIST_DLP_FINDING_CATEGORIES
            ]
            if sys_secret_findings:
                findings.extend(sys_secret_findings)
                level = max(level, max(item.level for item in sys_secret_findings))
        if redacted_secrets:
            findings.append(Finding(DataLevel.L1_GENERAL, "credential_redacted", detail=str(redacted_secrets)))
        normalized_scene = str(scene or "").strip().lower()
        # In read-only configuration/diff/command analysis and change-draft
        # generation scenes, CLI syntax tokens (e.g. ``system-view``,
        # ``configure terminal``, ``running-config``, ``save``) are the subject
        # matter being analyzed rather than an attempt to execute write tools.
        # Real secrets, credentials, private keys, and unsafe tools remain
        # strictly blocked.
        if normalized_scene in {
            "config_explain",
            "config_diff",
            "command_explain",
            "alarm_analysis",
            "change_plan",
            "config_generation",
        }:
            findings = [
                item for item in findings
                if item.category not in {"change_command", "full_config", "full_configuration_or_topology"}
            ]
            level = max((item.level for item in findings), default=DataLevel.L0_PUBLIC)
        if _has_sensitive_field(combined):
            findings.append(Finding(DataLevel.L4_PROHIBITED, "sensitive_field"))
            level = max(level, DataLevel.L4_PROHIBITED)
        passthrough_active = dev_passthrough.is_active()
        if passthrough_active and _has_credential_field(combined):
            # A credential-bearing field is itself a DLP signal even when a
            # caller supplies an opaque value that does not match a secret
            # regex.  Non-credential context fields remain available in the
            # temporary blacklist mode.
            findings.append(Finding(DataLevel.L4_PROHIBITED, "credential_field"))
            level = max(level, DataLevel.L4_PROHIBITED)
        request_findings = request_policy_findings(messages, tenant_id=tenant_id)
        if request_findings:
            findings.extend(request_findings)
            level = max(level, max((item.level for item in request_findings), default=level))
        _, instruction_findings = separate_data_and_instructions(messages)
        if instruction_findings:
            findings.extend(Finding(DataLevel.L3_SENSITIVE, category) for category in instruction_findings)
        requested_classification = normalize_classification(data_classification) if data_classification is not None else classification_for_level(level)
        if data_classification is not None and requested_classification is None:
            if passthrough_active:
                # The temporary mode does not trust a caller-supplied
                # classification string, but it also does not turn a bad
                # classification label into a hard block.  Keep the audit
                # metadata stable by deriving the level-based value.
                requested_classification = classification_for_level(level)
            else:
                raise SecurityBlocked("unknown data classification", reason_code="AI_SECURITY_CLASSIFICATION_DENIED", findings=findings)

        # A caller may declare a stricter classification, never a looser one:
        # content with identifiers (IP/MAC/host names/serials) or anything
        # more sensitive is at least INTERNAL, whatever the caller declared.
        if (
            data_classification is not None
            and requested_classification is not None
            and level >= DataLevel.L2_IDENTIFIER
            and _classification_rank(requested_classification) < _classification_rank(DataClassification.INTERNAL)
        ):
            requested_classification = DataClassification.INTERNAL

        has_injection = any(item.category == "prompt_injection" for item in findings)
        if tools and any(_tool_is_unsafe(tool) for tool in tools):
            raise SecurityBlocked("raw write-capable or unrestricted tool is not allowed", findings=findings, reason_code="AI_SECURITY_UNSAFE_TOOL")

        # Temporary test mode is an explicit blacklist policy.  It can relax
        # classification, minimization and identifier tokenization, but it
        # never allows credential material or credential-bearing fields to
        # cross the provider boundary.
        if passthrough_active and any(item.category in _BLACKLIST_DLP_FINDING_CATEGORIES for item in findings):
            raise SecurityBlocked(
                "credential DLP blocked the temporary test request",
                findings=findings,
                reason_code="AI_SECURITY_DLP_FAILED",
            )

        # A write command embedded in a user message is still an operation
        # request even when no structured tool was supplied.  Check only user
        # messages so system safety instructions ("禁止修改配置/重启设备") or
        # prior assistant explanations never self-block benign user prompts.
        if normalized_scene not in {
            "config_explain",
            "config_diff",
            "command_explain",
            "alarm_analysis",
            "change_plan",
            "config_generation",
        }:
            user_only_messages = [
                msg for msg in messages
                if isinstance(msg, dict) and str(msg.get("role") or "").strip().lower() == "user"
            ]
            if user_only_messages:
                _, user_findings = self._classify(user_only_messages)
                if any(item.category in _BLACKLIST_WRITE_FINDING_CATEGORIES for item in user_findings):
                    raise SecurityBlocked(
                        "write-capable operation is not allowed in temporary test mode",
                        findings=findings,
                        reason_code="AI_SECURITY_UNSAFE_TOOL",
                    )

        # A user asking the model to retrieve credentials or another tenant's
        # private scope is prohibited even when the prompt contains no secret
        # value yet.  Keep this check outside the passthrough branch: test
        # passthrough may relax minimization, but it can never authorize secret
        # retrieval or cross-tenant access.
        if request_findings:
            raise SecurityBlocked(
                "credential retrieval or cross-tenant scope request is not allowed",
                findings=findings,
                reason_code="AI_SECURITY_SENSITIVE_DATA",
            )

        if passthrough_active:
            # Temporary testing mode: keep only the blacklist controls above
            # plus the provider, region, tenant, payload-size and kill-switch
            # controls already enforced before classification.  Ordinary
            # context is sent as-is without minimization or tokenization.
            action = SecurityAction.ALLOW
            safe_messages = messages
            safe_tools = tools if tools else None
            safe_options = provider_options or {}
        else:
            # Normal cloud egress keeps the generic classification boundary.
            # INTERNAL context may use a cloud provider when its policy allows
            # it; CONFIDENTIAL/SECRET remain local-only.
            is_local_provider = normalized_provider in {"local", "ollama"}
            if data_classification is not None and not is_local_provider and requested_classification in {
                DataClassification.CONFIDENTIAL,
                DataClassification.SECRET,
            }:
                raise SecurityBlocked(
                    "confidential or secret data may only use a local model",
                    reason_code="AI_SECURITY_CLASSIFICATION_DENIED",
                    findings=findings,
                )
            if level >= DataLevel.L4_PROHIBITED:
                raise SecurityBlocked("prohibited data detected before tokenization", findings=findings, reason_code="AI_SECURITY_SENSITIVE_DATA")
            if requested_classification.value not in {str(item).upper() for item in active_policy.allowed_classifications}:
                # L3 sensitive values may still be minimized; prohibited findings
                # and explicit SECRET payloads never cross the boundary.
                if requested_classification == DataClassification.SECRET and level < DataLevel.L4_PROHIBITED and active_policy.allow_sensitive_minimization:
                    pass
                else:
                    raise SecurityBlocked("data classification is not allowed", reason_code="AI_SECURITY_CLASSIFICATION_DENIED", findings=findings)
            if provider_allowed_classification and _classification_rank(requested_classification) > _classification_rank(provider_allowed_classification):
                raise SecurityBlocked("model classification boundary denied the request", reason_code="AI_SECURITY_CLASSIFICATION_DENIED", findings=findings)

            action = action_for(level, has_prompt_injection=has_injection)
            if level == DataLevel.L3_SENSITIVE and not active_policy.allow_sensitive_minimization:
                raise SecurityBlocked("sensitive context is not eligible for external AI", findings=findings, reason_code="AI_SECURITY_SENSITIVE_DATA")

            safe_messages = minimize(messages) if action == SecurityAction.MINIMIZE else messages

            def transform(text: str) -> str:
                # Secrets were blocked above.  Only identifiers are reversible,
                # and the vault never stores the mapping in an application table.
                return tokenize_text(text, tenant_id=tenant_id, task_id=task_id, vault=self.vault)

            safe_messages = _walk_transform(safe_messages, transform)
            safe_tools = _walk_transform(minimize(tools or []), transform) if tools else None
            safe_options = _walk_transform(minimize(provider_options or {}), transform)
        opaque_id = provider_user_id(user_id, tenant_id=tenant_id, task_id=task_id)
        payload = SecurePayload(
            messages=safe_messages,
            tools=safe_tools,
            user_id=opaque_id,
            tenant_id=tenant_id,
            task_id=task_id,
            provider_options=safe_options,
            level=level,
            action=action,
            findings=findings,
            metadata={
                "finding_categories": sorted({item.category for item in findings}),
                "prompt_injection_untrusted": has_injection,
                "policy_version": active_policy.policy_version,
                "classification": requested_classification.value,
                "data_region": normalized_region,
                "provider_id": provider_id or "",
                "model_id": model_id or "",
                "dev_passthrough": passthrough_active,
                "security_mode": "blacklist" if passthrough_active else "classification",
                "scope": {key: value for key, value in scope.items() if value},
            },
        )
        serialized = payload.as_provider_json()
        if len(serialized.encode("utf-8")) > active_policy.max_payload_bytes:
            raise SecurityBlocked("outbound payload exceeds the configured size limit", findings=findings, reason_code="AI_SECURITY_DLP_FAILED")
        try:
            assert_clean(
                serialized,
                identifiers_blocked=active_policy.identifiers_must_be_tokenized and not passthrough_active,
            )
        except ValueError as exc:
            # The final serialized-body check is mandatory even if an earlier
            # transformation looked safe; providers only receive this payload.
            raise SecurityBlocked("final serialized outbound body failed DLP", findings=findings, reason_code="AI_SECURITY_DLP_FAILED") from exc
        return payload

    def safe_tool_result(self, result: Any) -> dict[str, Any]:
        return minimize_tool_result(result)

    def protect_embedding(
        self,
        texts: list[str] | tuple[str, ...],
        *,
        tenant_id: str = "tenant-default",
        task_id: str = "embedding",
        user_id: str | None = None,
        provider_type: str = "deepseek",
        idempotency_key: str | None = None,
        policy: SecurityPolicy | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        data_classification: str | None = None,
        data_region: str | None = None,
        provider_allowed_classification: str | None = None,
        provider_no_training_confirmed: bool = False,
        provider_retention_days: int | None = None,
        provider_data_processing_agreement_ref: str | None = None,
    ) -> SecureEmbeddingPayload:
        """Apply the same fail-closed controls to external embedding egress."""

        active_policy = self._resolve_policy(policy)
        normalized_provider, normalized_region = self.assert_egress_allowed(
            provider_type=provider_type,
            provider_id=provider_id,
            data_region=data_region,
            tenant_id=tenant_id,
            policy=active_policy,
        )
        values = [str(value or "") for value in texts]
        if not values or any(not value.strip() for value in values):
            raise SecurityBlocked("embedding input must not be empty", reason_code="AI_SECURITY_DLP_FAILED")
        values, redacted_secrets = _redact_secrets(values)

        combined = {"embedding_inputs": values, "provider_type": provider_type}
        level, findings = self._classify(combined)
        if redacted_secrets:
            findings.append(Finding(DataLevel.L1_GENERAL, "credential_redacted", detail=str(redacted_secrets)))
        passthrough_active = dev_passthrough.is_active()
        requested_classification = normalize_classification(data_classification) if data_classification is not None else classification_for_level(level)
        if data_classification is not None and requested_classification is None:
            if passthrough_active:
                requested_classification = classification_for_level(level)
            else:
                raise SecurityBlocked("unknown data classification", reason_code="AI_SECURITY_CLASSIFICATION_DENIED", findings=findings)
        # A caller may declare a stricter classification, never a looser one:
        # content with identifiers (IP/MAC/host names/serials) or anything
        # more sensitive is at least INTERNAL, whatever the caller declared.
        if (
            data_classification is not None
            and requested_classification is not None
            and level >= DataLevel.L2_IDENTIFIER
            and _classification_rank(requested_classification) < _classification_rank(DataClassification.INTERNAL)
        ):
            requested_classification = DataClassification.INTERNAL
        if passthrough_active and any(item.category in _BLACKLIST_DLP_FINDING_CATEGORIES for item in findings):
            raise SecurityBlocked(
                "credential DLP blocked the temporary embedding request",
                findings=findings,
                reason_code="AI_SECURITY_DLP_FAILED",
            )
        if passthrough_active:
            action = SecurityAction.ALLOW
            safe_texts = values
        else:
            is_local_provider = normalized_provider in {"local", "ollama"}
            if data_classification is not None and not is_local_provider and requested_classification in {
                DataClassification.CONFIDENTIAL,
                DataClassification.SECRET,
            }:
                raise SecurityBlocked(
                    "confidential or secret embeddings may only use a local model",
                    reason_code="AI_SECURITY_CLASSIFICATION_DENIED",
                    findings=findings,
                )
            if requested_classification.value not in {str(item).upper() for item in active_policy.allowed_classifications} and level >= DataLevel.L3_SENSITIVE:
                raise SecurityBlocked("embedding classification is not allowed", reason_code="AI_SECURITY_CLASSIFICATION_DENIED", findings=findings)
            if provider_allowed_classification and _classification_rank(requested_classification) > _classification_rank(provider_allowed_classification):
                raise SecurityBlocked("embedding classification boundary denied the request", reason_code="AI_SECURITY_CLASSIFICATION_DENIED", findings=findings)
            if level >= DataLevel.L4_PROHIBITED:
                raise SecurityBlocked("prohibited data detected before external embedding", findings=findings, reason_code="AI_SECURITY_SENSITIVE_DATA")
            has_injection = any(item.category == "prompt_injection" for item in findings)
            action = action_for(level, has_prompt_injection=has_injection)
            if level == DataLevel.L3_SENSITIVE and not active_policy.allow_sensitive_minimization:
                raise SecurityBlocked("sensitive context is not eligible for external embedding", findings=findings, reason_code="AI_SECURITY_SENSITIVE_DATA")

            safe_texts = minimize(values) if action == SecurityAction.MINIMIZE else values

            def transform(text: str) -> str:
                return tokenize_text(text, tenant_id=tenant_id, task_id=task_id, vault=self.vault)

            safe_texts = [_walk_transform(value, transform) for value in safe_texts]
        metadata = {
            "egress_kind": "embedding",
            "provider_type": provider_type,
            "user_id": provider_user_id(user_id, tenant_id=tenant_id, task_id=task_id),
            "idempotency_key": idempotency_key or "",
            "finding_categories": sorted({item.category for item in findings}),
            "policy_version": active_policy.policy_version,
            "classification": requested_classification.value,
            "data_region": normalized_region,
            "provider_id": provider_id or "",
            "model_id": model_id or "",
            "dev_passthrough": passthrough_active,
            "security_mode": "blacklist" if passthrough_active else "classification",
        }
        payload = SecureEmbeddingPayload(
            texts=safe_texts,
            tenant_id=tenant_id,
            task_id=task_id,
            level=level,
            action=action,
            findings=findings,
            metadata=metadata,
        )
        serialized = payload.as_provider_json()
        if len(serialized.encode("utf-8")) > active_policy.max_payload_bytes:
            raise SecurityBlocked("outbound embedding payload exceeds the configured size limit", findings=findings, reason_code="AI_SECURITY_DLP_FAILED")
        try:
            assert_clean(
                serialized,
                identifiers_blocked=active_policy.identifiers_must_be_tokenized and not passthrough_active,
            )
        except ValueError as exc:
            raise SecurityBlocked("final serialized embedding body failed DLP", findings=findings, reason_code="AI_SECURITY_DLP_FAILED") from exc
        self._egress_audit_events.append(
            {
                "egress_kind": "embedding",
                "tenant_id": tenant_id,
                "task_id": task_id,
                "provider_type": provider_type,
                "input_count": len(values),
                "input_hashes": [hashlib.sha256(value.encode("utf-8")).hexdigest() for value in values],
                "level": level.value,
                "action": action.value,
                "finding_categories": metadata["finding_categories"],
                "idempotency_key": idempotency_key or "",
            }
        )
        return payload

    def embedding_audit_events(self) -> list[dict[str, Any]]:
        """Return redacted egress evidence without the original embedding text."""

        return [dict(event) for event in self._egress_audit_events]

    def resolve_output(self, value: Any, *, tenant_id: str, task_id: str) -> Any:
        from ai.security.output import sanitize_output

        return sanitize_output(value, tenant_id=tenant_id, task_id=task_id, vault=self.vault)


ai_security_gateway = AISecurityGateway(enforce_deployment_flags=True)
