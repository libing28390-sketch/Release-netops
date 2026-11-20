from __future__ import annotations

from ai.services.conversation_service import _safe_message_content


def test_assistant_history_keeps_links_and_identifiers_readable():
    content = "官方入口 https://support.example.com/docs，设备地址 192.0.2.10"

    result = _safe_message_content(
        content,
        tenant_id="tenant-a",
        scope_id="conversation-1",
        role="assistant",
    )

    assert result == content
    assert "[[NXA_" not in result


def test_user_history_still_tokenizes_identifiers():
    result = _safe_message_content(
        "设备地址 192.0.2.10",
        tenant_id="tenant-a",
        scope_id="conversation-1",
        role="user",
    )

    assert "192.0.2.10" not in result
    assert "[[NXA_IP_" in result
