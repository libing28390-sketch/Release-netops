from __future__ import annotations

import pytest

from ai.security.gateway import AISecurityGateway, SecurityBlocked, SecurityPolicy
from ai.security.output import StreamingOutputResolver
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


def test_credentials_are_redacted_before_tokenization():
    # Task d1: an English credential value is redacted and the request continues.
    gateway = enabled_gateway()
    payload = gateway.protect([{"role": "user", "content": "pass" + "word=NeverSendThisValue"}])
    body = payload.as_provider_json()
    assert "NeverSendThisValue" not in body
    assert "<REDACTED>" in body
    assert "credential_redacted" in payload.metadata["finding_categories"]
    assert "credential" not in payload.metadata["finding_categories"]


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


def test_provider_output_dlp_redacts_vrp_cipher_password_syntax():
    gateway = enabled_gateway()
    result = gateway.resolve_output(
        "aaa local-user admin password irreversible-cipher Huawei@123 local-user admin service-type ssh",
        tenant_id="tenant-a",
        task_id="task-1",
    )
    assert "Huawei@123" not in result


def test_streaming_output_dlp_redacts_credential_directive_split_across_chunks():
    resolver = StreamingOutputResolver(
        tenant_id="tenant-a",
        task_id="task-1",
        vault=ScopedTokenVault(ttl_seconds=120),
    )

    first = resolver.push("aaa local-user admin password irreversible-cipher ")
    second = resolver.push("Huawei@123 local-user admin service-type ssh")
    tail = resolver.flush()

    combined = first + second + tail
    assert "Huawei@123" not in combined


def test_streaming_output_dlp_retains_split_vrp_modifier_before_value():
    resolver = StreamingOutputResolver(
        tenant_id="tenant-a",
        task_id="task-1",
        vault=ScopedTokenVault(ttl_seconds=120),
    )

    first = resolver.push("aaa local-user admin password irreversible")
    second = resolver.push("-cipher Huawei@123 local-user admin service-type ssh")
    tail = resolver.flush()

    combined = first + second + tail
    assert "Huawei@123" not in combined


def test_streaming_output_dlp_does_not_split_harmless_word_suffix():
    resolver = StreamingOutputResolver(
        tenant_id="tenant-a",
        task_id="task-1",
        vault=ScopedTokenVault(ttl_seconds=120),
    )

    assert resolver.push("stream-ok") == "stream-ok"
    assert resolver.flush() == ""


def test_streaming_output_resolves_tokens_split_across_provider_chunks():
    vault = ScopedTokenVault(ttl_seconds=120)
    token = vault.put("192.0.2.10", kind="IP", tenant_id="tenant-a", task_id="task-1")
    resolver = StreamingOutputResolver(tenant_id="tenant-a", task_id="task-1", vault=vault)

    first = resolver.push(f"See https://example.com and {token[:12]}")
    second = resolver.push(f"{token[12:]} in the answer.")

    assert first == "See https://example.com and "
    assert second == "192.0.2.10 in the answer."
    assert resolver.flush() == ""
