from __future__ import annotations

import pytest

from ai.services.conversation_service import (
    clear_clarification_state,
    create_conversation,
    get_context,
    set_clarification_state,
)


def test_m0197_adds_bounded_clarification_state_columns(isolated_db) -> None:
    database = isolated_db["module"]
    with database.get_db_connection() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = ?",
                ("ai_conversations",),
            ).fetchall()
        }
    assert {
        "clarification_state_json",
        "clarification_state_version",
        "clarification_updated_at",
    }.issubset(columns)


def test_clarification_state_round_trip_and_revision_guard(isolated_db) -> None:
    del isolated_db
    owner = "clarification-owner"
    conversation = create_conversation(
        tenant_id="tenant-default",
        user_id=owner,
        title="配置范围测试",
    )
    state = {
        "required": True,
        "request_kind": "configuration_reference",
        "risk": "medium",
        "reason_code": "MISSING_PLATFORM_OR_MODEL",
        "missing_fields": ["platform_or_model"],
        "recognized_fields": {"vendor": "Huawei", "feature": "vlan"},
        "question": "请补充设备型号或 CLI 平台。",
        "options": [
            {"field": "cli_platform", "value": "huawei_vrp", "label": "Huawei VRP"},
        ],
        "allow_free_text": True,
        "retrieval_allowed": False,
    }

    persisted = set_clarification_state(
        conversation_id=conversation["id"],
        tenant_id="tenant-default",
        user_id=owner,
        state=state,
        expected_revision=0,
    )
    assert persisted["required"] is True
    assert persisted["revision"] == 1
    assert persisted["state_id"].startswith("clar_")

    context = get_context(
        conversation_id=conversation["id"],
        tenant_id="tenant-default",
        user_id=owner,
    )
    assert context["conversation"]["pending_clarification"]["revision"] == 1
    assert context["conversation"]["pending_clarification"]["recognized_fields"] == {
        "vendor": "Huawei",
        "feature": "vlan",
    }

    with pytest.raises(RuntimeError, match="revision conflict"):
        set_clarification_state(
            conversation_id=conversation["id"],
            tenant_id="tenant-default",
            user_id=owner,
            state=state,
            expected_revision=0,
        )

    clear_clarification_state(
        conversation_id=conversation["id"],
        tenant_id="tenant-default",
        user_id=owner,
        expected_revision=1,
        expected_state_id=persisted["state_id"],
    )
    cleared = get_context(
        conversation_id=conversation["id"],
        tenant_id="tenant-default",
        user_id=owner,
    )
    assert cleared["conversation"]["pending_clarification"] is None
    assert cleared["conversation"]["clarification_state_version"] == 2


def test_clarification_state_rejects_secret_markers(isolated_db) -> None:
    del isolated_db
    conversation = create_conversation(tenant_id="tenant-default", user_id="safe-owner")
    with pytest.raises(ValueError, match="prohibited secret"):
        set_clarification_state(
            conversation_id=conversation["id"],
            tenant_id="tenant-default",
            user_id="safe-owner",
            state={
                "required": True,
                "question": "请提供 password=...",
            },
        )


def test_expired_clarification_is_hidden_and_cannot_reuse_old_slots(isolated_db) -> None:
    del isolated_db
    conversation = create_conversation(tenant_id="tenant-default", user_id="expiry-owner")
    expired = set_clarification_state(
        conversation_id=conversation["id"],
        tenant_id="tenant-default",
        user_id="expiry-owner",
        state={
            "required": True,
            "request_kind": "intent_classification",
            "intent": "device_search",
            "missing_fields": ["device_or_scope"],
            "recognized_fields": {"site": "old-site"},
            "question": "请补充设备范围。",
            "expires_at": "2000-01-01T00:00:00+00:00",
        },
    )

    context = get_context(
        conversation_id=conversation["id"],
        tenant_id="tenant-default",
        user_id="expiry-owner",
    )
    assert context["conversation"]["pending_clarification"] is None

    fresh = set_clarification_state(
        conversation_id=conversation["id"],
        tenant_id="tenant-default",
        user_id="expiry-owner",
        state={
            "required": True,
            "request_kind": "intent_classification",
            "intent": "ip_location",
            "missing_fields": ["ip"],
            "question": "请提供 IP 地址。",
        },
    )
    assert fresh["state_id"] != expired["state_id"]
    assert "recognized_fields" not in fresh
