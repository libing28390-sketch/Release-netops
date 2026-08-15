"""Fail-closed AI security gateway used by every external model call."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from core.config import settings
from ai.security.classification import DataLevel, Finding, SecurityAction, action_for, classify, classify_text
from ai.security.dlp import assert_clean
from ai.security.minimizer import minimize, minimize_tool_result
from ai.security.tokenization import ScopedTokenVault, opaque_user_id, tokenize_text, token_vault


class SecurityBlocked(Exception):
    """A provider call was refused before an outbound request was built."""

    code = "AI_SECURITY_BLOCKED"
    status_code = 403

    def __init__(self, reason: str, *, findings: list[Finding] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.findings = findings or []


@dataclass(frozen=True)
class SecurityPolicy:
    external_ai_enabled: bool = False
    kill_switch: bool = False
    max_payload_bytes: int = 256_000
    identifiers_must_be_tokenized: bool = True
    allow_sensitive_minimization: bool = True
    allowed_provider_types: tuple[str, ...] = ("deepseek",)


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


def _walk_transform(value: Any, transform) -> Any:
    if isinstance(value, str):
        return transform(value)
    if isinstance(value, list):
        return [_walk_transform(item, transform) for item in value]
    if isinstance(value, dict):
        return {str(key): _walk_transform(item, transform) for key, item in value.items()}
    return value


def _tool_is_unsafe(tool: dict[str, Any]) -> bool:
    text = json.dumps(tool, ensure_ascii=False, default=str).lower()
    forbidden = (
        "raw_ssh", "raw ssh", "raw_sql", "raw sql", "snmp set", "snmpset",
        "configure terminal", "system-view", "write memory", "commit", "delete ",
    )
    return any(marker in text for marker in forbidden)


class AISecurityGateway:
    def __init__(self, *, vault: ScopedTokenVault | None = None, policy: SecurityPolicy | None = None):
        self.vault = vault or token_vault
        self.policy = policy or SecurityPolicy(
            external_ai_enabled=bool(getattr(settings, "EXTERNAL_AI_ENABLED", False)),
            kill_switch=bool(getattr(settings, "AI_KILL_SWITCH", False)),
            max_payload_bytes=int(getattr(settings, "AI_MAX_PAYLOAD_BYTES", 256_000)),
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
    ) -> SecurePayload:
        active_policy = policy or self.policy
        if active_policy.kill_switch:
            raise SecurityBlocked("AI external egress is disabled by the kill switch")
        if not active_policy.external_ai_enabled:
            raise SecurityBlocked("external AI is disabled by policy")
        if provider_type.lower() not in {item.lower() for item in active_policy.allowed_provider_types}:
            raise SecurityBlocked("provider is not allowed by the AI egress policy")

        combined = {"messages": messages, "tools": tools or [], "provider_options": provider_options or {}}
        level, findings = self._classify(combined)
        if level >= DataLevel.L4_PROHIBITED:
            raise SecurityBlocked("prohibited data detected before tokenization", findings=findings)
        if tools and any(_tool_is_unsafe(tool) for tool in tools):
            raise SecurityBlocked("raw write-capable or unrestricted tool is not allowed", findings=findings)

        has_injection = any(item.category == "prompt_injection" for item in findings)
        action = action_for(level, has_prompt_injection=has_injection)
        if level == DataLevel.L3_SENSITIVE and not active_policy.allow_sensitive_minimization:
            raise SecurityBlocked("sensitive context is not eligible for external AI", findings=findings)

        safe_messages: Any = minimize(messages) if action == SecurityAction.MINIMIZE else messages

        def transform(text: str) -> str:
            # Secrets were blocked above.  Only identifiers are reversible, and
            # the vault never stores the mapping in an application table.
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
            },
        )
        serialized = payload.as_provider_json()
        if len(serialized.encode("utf-8")) > active_policy.max_payload_bytes:
            raise SecurityBlocked("outbound payload exceeds the configured size limit", findings=findings)
        try:
            assert_clean(serialized, identifiers_blocked=active_policy.identifiers_must_be_tokenized)
        except ValueError as exc:
            # The final serialized-body check is mandatory even if an earlier
            # transformation looked safe; providers only receive this payload.
            raise SecurityBlocked("final serialized outbound body failed DLP", findings=findings) from exc
        return payload

    def safe_tool_result(self, result: Any) -> dict[str, Any]:
        return minimize_tool_result(result)

    def resolve_output(self, value: Any, *, tenant_id: str, task_id: str) -> Any:
        from ai.security.output import sanitize_output

        return sanitize_output(value, tenant_id=tenant_id, task_id=task_id, vault=self.vault)


ai_security_gateway = AISecurityGateway()
