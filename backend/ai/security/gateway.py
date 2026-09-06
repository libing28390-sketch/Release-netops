"""Fail-closed AI security gateway used by every external model call."""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from typing import Any

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
)
from ai.security.dev_passthrough import dev_passthrough
from ai.security.dlp import assert_clean
from ai.security.minimizer import minimize, minimize_tool_result
from ai.security.tokenization import ScopedTokenVault, opaque_user_id, tokenize_text, token_vault


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


def _walk_transform(value: Any, transform) -> Any:
    if isinstance(value, str):
        return transform(value)
    if isinstance(value, list):
        return [_walk_transform(item, transform) for item in value]
    if isinstance(value, dict):
        return {str(key): _walk_transform(item, transform) for key, item in value.items()}
    return value


_SENSITIVE_FIELD_MARKERS = frozenset({
    "password", "passwd", "secret", "community", "token", "apikey",
    "accesstoken", "privatekey", "credential", "authorization", "cookie",
    "rawoutput", "rawconfig", "runningconfig", "currentconfiguration",
    "toolargs", "requestbody",
})


def _has_sensitive_field(value: Any) -> bool:
    """Detect secret-bearing field names even when the value is opaque.

    A key such as ``api_key`` is sensitive by contract even if its test value
    does not match a token regex.  This closes the nested dict/list gap before
    minimization or tokenization can build an outbound provider body.
    """

    if isinstance(value, dict):
        for key, item in value.items():
            normalized = "".join(char for char in str(key).casefold() if char.isalnum())
            if any(marker in normalized for marker in _SENSITIVE_FIELD_MARKERS):
                return True
            if _has_sensitive_field(item):
                return True
    elif isinstance(value, (list, tuple, set)):
        return any(_has_sensitive_field(item) for item in value)
    return False


def _tool_is_unsafe(tool: dict[str, Any]) -> bool:
    text = json.dumps(tool, ensure_ascii=False, default=str).lower()
    forbidden = (
        "raw_ssh", "raw ssh", "raw_sql", "raw sql", "snmp set", "snmpset",
        "configure terminal", "system-view", "write memory", "commit", "delete ",
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


class AISecurityGateway:
    def __init__(self, *, vault: ScopedTokenVault | None = None, policy: SecurityPolicy | None = None):
        self.vault = vault or token_vault
        self._egress_audit_events: list[dict[str, Any]] = []
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
    ) -> SecurePayload:
        active_policy = policy or self.policy
        if self is ai_security_gateway and not active_policy.external_ai_enabled and policy is None:
            try:
                from ai.api.security import load_persisted_security_policy
                load_persisted_security_policy()
                active_policy = self.policy
            except Exception:
                pass
        if active_policy.kill_switch:
            raise SecurityBlocked("AI external egress is disabled by the kill switch", reason_code="AI_SECURITY_KILL_SWITCH")
        if active_policy.tenant_kill_switches.get(str(tenant_id)):
            raise SecurityBlocked("tenant AI egress is disabled by the kill switch", reason_code="AI_SECURITY_KILL_SWITCH")
        if not active_policy.external_ai_enabled:
            raise SecurityBlocked("external AI is disabled by policy", reason_code="AI_SECURITY_POLICY_DISABLED")
        normalized_provider = provider_type.lower().replace("-", "_")
        if normalized_provider not in {item.lower() for item in active_policy.allowed_provider_types}:
            raise SecurityBlocked("provider is not allowed by the AI egress policy", reason_code="AI_SECURITY_PROVIDER_DENIED")
        if active_policy.provider_kill_switches.get(normalized_provider) or (provider_id and active_policy.provider_kill_switches.get(provider_id)):
            raise SecurityBlocked("provider is disabled by its kill switch", reason_code="AI_SECURITY_KILL_SWITCH")
        normalized_region = str(data_region or "unknown").strip().lower()
        if normalized_region not in {str(item).lower() for item in active_policy.allowed_data_regions}:
            raise SecurityBlocked("provider data region is not allowed", reason_code="AI_SECURITY_SCOPE_DENIED")
        scope = {"tenant": tenant_id, "workspace": workspace_id, "site": site_id, "department": department, "document_scope": document_scope, "user_role": user_role}
        required_scope = active_policy.scope_rules or {}
        for key, allowed in required_scope.items():
            if allowed and str(scope.get(key) or "") not in {str(item) for item in (allowed if isinstance(allowed, (list, tuple, set)) else [allowed])}:
                raise SecurityBlocked("request is outside the configured data scope", reason_code="AI_SECURITY_SCOPE_DENIED")

        combined = {"messages": messages, "tools": tools or [], "provider_options": provider_options or {}}
        level, findings = self._classify(combined)
        if _has_sensitive_field(combined):
            findings.append(Finding(DataLevel.L4_PROHIBITED, "sensitive_field"))
            level = max(level, DataLevel.L4_PROHIBITED)
        request_findings = request_policy_findings(messages, tenant_id=tenant_id)
        if request_findings:
            findings.extend(request_findings)
            level = max(level, max((item.level for item in request_findings), default=level))
        _, instruction_findings = separate_data_and_instructions(messages)
        if instruction_findings:
            findings.extend(Finding(DataLevel.L3_SENSITIVE, category) for category in instruction_findings)
        passthrough_active = dev_passthrough.is_active()
        requested_classification = normalize_classification(data_classification) if data_classification is not None else classification_for_level(level)
        if data_classification is not None and requested_classification is None:
            raise SecurityBlocked("unknown data classification", reason_code="AI_SECURITY_CLASSIFICATION_DENIED", findings=findings)

        # Cloud egress keeps the generic classification boundary.  INTERNAL
        # context may use a cloud provider when the provider policy allows it;
        # CONFIDENTIAL/SECRET never leave the local boundary, regardless of
        # provider settings or passthrough mode.
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
        has_injection = any(item.category == "prompt_injection" for item in findings)
        if tools and any(_tool_is_unsafe(tool) for tool in tools):
            raise SecurityBlocked("raw write-capable or unrestricted tool is not allowed", findings=findings, reason_code="AI_SECURITY_UNSAFE_TOOL")

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
            # Temporary testing mode: keep the external/provider controls
            # above, but send non-secret test data as-is. Hard DLP checks
            # below still reject credentials, private keys, JWTs and cookies;
            # unsafe write-capable tools remain blocked above.
            action = SecurityAction.ALLOW
            safe_messages = messages
            safe_tools = tools if tools else None
            safe_options = provider_options or {}
        else:
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
        opaque_id = opaque_user_id(user_id, tenant_id=tenant_id, task_id=task_id)
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

        active_policy = policy or self.policy
        if active_policy.kill_switch:
            raise SecurityBlocked("AI external egress is disabled by the kill switch", reason_code="AI_SECURITY_KILL_SWITCH")
        if active_policy.tenant_kill_switches.get(str(tenant_id)):
            raise SecurityBlocked("tenant AI egress is disabled by the kill switch", reason_code="AI_SECURITY_KILL_SWITCH")
        if not active_policy.external_ai_enabled:
            raise SecurityBlocked("external AI is disabled by policy", reason_code="AI_SECURITY_POLICY_DISABLED")
        if provider_type.lower() not in {item.lower() for item in active_policy.allowed_provider_types}:
            raise SecurityBlocked("provider is not allowed by the AI egress policy", reason_code="AI_SECURITY_PROVIDER_DENIED")
        normalized_region = str(data_region or "unknown").strip().lower()
        if normalized_region not in {str(item).lower() for item in active_policy.allowed_data_regions}:
            raise SecurityBlocked("provider data region is not allowed", reason_code="AI_SECURITY_SCOPE_DENIED")
        values = [str(value or "") for value in texts]
        if not values or any(not value.strip() for value in values):
            raise SecurityBlocked("embedding input must not be empty", reason_code="AI_SECURITY_DLP_FAILED")

        combined = {"embedding_inputs": values, "provider_type": provider_type}
        level, findings = self._classify(combined)
        passthrough_active = dev_passthrough.is_active()
        requested_classification = normalize_classification(data_classification) if data_classification is not None else classification_for_level(level)
        if data_classification is not None and requested_classification is None:
            raise SecurityBlocked("unknown data classification", reason_code="AI_SECURITY_CLASSIFICATION_DENIED", findings=findings)
        is_local_provider = provider_type.lower().replace("-", "_") in {"local", "ollama"}
        if data_classification is not None and not is_local_provider and requested_classification in {
            DataClassification.CONFIDENTIAL,
            DataClassification.SECRET,
        }:
            raise SecurityBlocked(
                "confidential or secret embeddings may only use a local model",
                reason_code="AI_SECURITY_CLASSIFICATION_DENIED",
                findings=findings,
            )
        if passthrough_active:
            action = SecurityAction.ALLOW
            safe_texts = values
        else:
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
            "user_id": opaque_user_id(user_id, tenant_id=tenant_id, task_id=task_id),
            "idempotency_key": idempotency_key or "",
            "finding_categories": sorted({item.category for item in findings}),
            "policy_version": active_policy.policy_version,
            "classification": requested_classification.value,
            "data_region": normalized_region,
            "provider_id": provider_id or "",
            "model_id": model_id or "",
            "dev_passthrough": passthrough_active,
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


ai_security_gateway = AISecurityGateway()
