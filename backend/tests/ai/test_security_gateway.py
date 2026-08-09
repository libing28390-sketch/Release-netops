from __future__ import annotations

import pytest

from ai.security.gateway import AISecurityGateway, SecurityBlocked, SecurityPolicy
from ai.security.tokenization import ScopedTokenVault


def enabled_gateway() -> AISecurityGateway:
    return AISecurityGateway(
        vault=ScopedTokenVault(ttl_seconds=120),
        policy=SecurityPolicy(external_ai_enabled=True),
    )


def test_external_ai_is_fail_closed_by_default():
    gateway = AISecurityGateway(vault=ScopedTokenVault())
    with pytest.raises(SecurityBlocked):
        gateway.protect([{"role": "user", "content": "hello"}])


def test_credentials_are_blocked_before_tokenization():
    gateway = enabled_gateway()
    with pytest.raises(SecurityBlocked) as exc_info:
        gateway.protect([{"role": "user", "content": "password=NeverSendThisValue"}])
    assert any(item.category == "credential" for item in exc_info.value.findings)


def test_identifier_is_scoped_and_final_body_contains_no_raw_value():
    gateway = enabled_gateway()
    payload = gateway.protect(
        [{"role": "user", "content": "trace 192.0.2.10 from sw-core01.example.com"}],
        tenant_id="tenant-a",
        task_id="task-1",
        user_id="alice@example.com",
    )
    serialized = payload.as_provider_json()
    assert "192.0.2.10" not in serialized
    assert "sw-core01.example.com" not in serialized
    assert "[[NXA_" in serialized
    assert gateway.vault.resolve_text(
        payload.messages[0]["content"], tenant_id="tenant-a", task_id="task-1"
    ).find("192.0.2.10") >= 0
    assert gateway.vault.resolve_text(
        payload.messages[0]["content"], tenant_id="tenant-b", task_id="task-1"
    ) == payload.messages[0]["content"]


def test_unknown_or_fake_token_is_not_fuzzy_resolved():
    gateway = enabled_gateway()
    result = gateway.resolve_output(
        "token [[NXA_IP_not-a-real-token-00000000]]",
        tenant_id="tenant-a",
        task_id="task-1",
    )
    assert "not-a-real-token" in result


def test_write_tool_is_blocked_without_external_call():
    gateway = enabled_gateway()
    with pytest.raises(SecurityBlocked):
        gateway.protect(
            [{"role": "user", "content": "inspect"}],
            tools=[{"name": "raw_ssh", "description": "run raw SSH command"}],
        )


def test_provider_output_dlp_redacts_credentials_and_dangerous_markup():
    gateway = enabled_gateway()
    result = gateway.resolve_output(
        "<script>alert(1)</script> password=NeverShowThis",
        tenant_id="tenant-a",
        task_id="task-1",
    )
    assert "NeverShowThis" not in result
    assert "<script>" not in result
