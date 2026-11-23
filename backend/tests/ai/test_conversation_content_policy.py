from __future__ import annotations

from ai.security import field_crypto
from ai.services.conversation_service import _read_message_content, _readable_message_content, _safe_message_content


def test_history_is_encrypted_at_rest_and_readable_after_decryption():
    """M12: stored text is encrypted; identifiers survive a vault reset."""
    content = "官方入口 https://support.example.com/docs，设备地址 192.0.2.10"
    for role in ("user", "assistant"):
        stored = _safe_message_content(content, tenant_id="tenant-a", scope_id="conversation-1", role=role)
        assert field_crypto.is_encrypted(stored)
        assert "192.0.2.10" not in stored and "[[NXA_" not in stored
        assert _read_message_content(stored, tenant_id="tenant-a", conversation_id="conversation-1") == content


def test_encrypted_history_is_bound_to_its_conversation():
    stored = _safe_message_content("设备地址 192.0.2.10", tenant_id="tenant-a", scope_id="conversation-1", role="user")
    restored = _read_message_content(stored, tenant_id="tenant-a", conversation_id="conversation-2")
    assert "192.0.2.10" not in restored
    assert "无法解密" in restored


def test_legacy_tokenized_rows_still_resolve_through_the_vault():
    from ai.security.tokenization import token_vault, tokenize_text

    legacy = tokenize_text("设备地址 192.0.2.10", tenant_id="tenant-a", task_id="conversation-9", vault=token_vault)
    assert "[[NXA_IP_" in legacy
    assert _read_message_content(legacy, tenant_id="tenant-a", conversation_id="conversation-9") == "设备地址 192.0.2.10"


def test_secrets_are_redacted_and_full_configuration_is_still_rejected_before_storage():
    import pytest
    from ai.services.conversation_service import ConversationSecurityError

    # Task d1: a private key is stored redacted instead of being rejected.
    stored = _readable_message_content("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----")
    assert stored == "<REDACTED_PRIVATE_KEY>"
    with pytest.raises(ConversationSecurityError):
        _readable_message_content("display current-configuration")
