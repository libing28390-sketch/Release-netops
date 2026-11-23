"""Copilot follow-up fixes (task t4): history scope, unreadable history rows,
non-stream truncation pass-through, provider test model, logged exports."""

from __future__ import annotations

import asyncio
import logging

import pytest

from ai.services import assistant as assistant_module


NETWORK_HISTORY = [
    {"role": "user", "content": "10.10.20.15 接在哪台交换机"},
    {"role": "assistant", "content": "10.10.20.15 位于 SW-CORE-01 的 GE1/0/12。"},
]


def test_short_pronoun_follow_up_inherits_the_network_history_scope() -> None:
    service = assistant_module.AIAssistantService()
    # No network term of its own ("负责人" is not in the network lexicon).
    policy = service._history_policy("那它的负责人是谁？", intent="general_qa", history=NETWORK_HISTORY)
    assert policy["name"] in {"network", "complex"}
    assert policy["turns"] >= 8


def test_follow_up_without_network_history_stays_public() -> None:
    service = assistant_module.AIAssistantService()
    history = [
        {"role": "user", "content": "介绍一下幂等性"},
        {"role": "assistant", "content": "幂等性是指……"},
    ]
    assert service._history_policy("那它有什么例子？", intent="general_qa", history=history)["name"] == "public"


def test_public_fresh_follow_up_keeps_the_public_scope() -> None:
    service = assistant_module.AIAssistantService()
    policy = service._history_policy("那北京今天的天气呢", intent="general_qa", history=NETWORK_HISTORY)
    assert policy["name"] == "public"


def test_long_message_is_not_treated_as_a_follow_up_by_scope_inheritance() -> None:
    service = assistant_module.AIAssistantService()
    message = "那我们换个话题，" + "请详细介绍一下这门编程语言的历史与设计理念" * 3
    assert service._history_policy(message, intent="general_qa", history=NETWORK_HISTORY)["name"] == "public"


def test_existing_policy_contract_is_unchanged() -> None:
    service = assistant_module.AIAssistantService()
    assert service._history_policy("查询北京今天的天气", intent="general_qa", history=NETWORK_HISTORY)["name"] == "public"
    assert service._history_policy(
        "那可以提供思科的吗", intent="knowledge", filters={"vendor": "cisco", "feature": "bgp"}, history=NETWORK_HISTORY,
    )["name"] == "complex"


def test_undecryptable_history_rows_are_not_sent_to_the_model() -> None:
    service = assistant_module.AIAssistantService()
    history = [
        {"role": "user", "content": "[消息内容无法解密：请检查主密钥配置]"},
        {"role": "assistant", "content": "上一条回答"},
        {"role": "user", "content": "继续排查 OSPF"},
    ]
    selected = service._select_history_for_model(history, "继续", intent="troubleshooting")
    assert [item["content"] for item in selected] == ["上一条回答", "继续排查 OSPF"]


def test_non_stream_chat_passes_truncation_through(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse_intent(*args, **kwargs):
        return {"intent": "general_qa", "filters": {}, "needs_clarification": False}

    captured: dict = {}

    async def fake_chat(*args, **kwargs):
        captured["messages"] = kwargs.get("messages")
        return {
            "content": "部分回答",
            "finish_reason": "length",
            "truncated": True,
            "provider_id": "p1",
            "model_id": "m1",
            "input_tokens": 10,
            "output_tokens": 64,
        }

    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", fake_parse_intent)
    monkeypatch.setattr(assistant_module.llm_gateway, "chat", fake_chat)
    monkeypatch.setattr(assistant_module.settings, "AI_WEB_SEARCH_ENABLED", False, raising=False)

    result = asyncio.run(
        assistant_module.AIAssistantService().chat(
            "解释一下幂等性",
            history=[{"role": "user", "content": "你好"}, {"role": "assistant", "content": "你好，有什么可以帮你？"}],
            user_id="alice",
            tenant_id="tenant-default",
        )
    )
    assert result["answer"] == "部分回答"
    assert result["truncated"] is True
    assert result["finish_reason"] == "length"
    # History reached the model ahead of the current question.
    roles = [item["role"] for item in captured["messages"]]
    assert roles[0] == "system" and roles[-1] == "user"
    assert any(item.get("content") == "你好，有什么可以帮你？" for item in captured["messages"])


def test_complete_non_stream_answer_is_not_marked_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_parse_intent(*args, **kwargs):
        return {"intent": "general_qa", "filters": {}, "needs_clarification": False}

    async def fake_chat(*args, **kwargs):
        return {"content": "完整回答", "finish_reason": "stop", "truncated": False, "provider_id": "p1", "model_id": "m1"}

    monkeypatch.setattr(assistant_module.intent_parser, "parse_intent", fake_parse_intent)
    monkeypatch.setattr(assistant_module.llm_gateway, "chat", fake_chat)
    monkeypatch.setattr(assistant_module.settings, "AI_WEB_SEARCH_ENABLED", False, raising=False)

    result = asyncio.run(assistant_module.AIAssistantService().chat("解释一下幂等性", user_id="alice", tenant_id="tenant-default"))
    assert result["truncated"] is False
    assert result["finish_reason"] == "stop"


def test_deepseek_health_probe_has_no_hard_coded_model() -> None:
    from ai.providers.deepseek import DeepSeekProvider

    provider = DeepSeekProvider({"base_url": "https://api.deepseek.com", "provider_type": "deepseek"})
    result = asyncio.run(provider.test_connection())
    assert result["success"] is False and result["error_code"] == "AI_TEST_MODEL_REQUIRED"
    wrong = asyncio.run(provider.test_connection(test_model="gpt-4o"))
    assert wrong["success"] is False and wrong["model_tested"] == "gpt-4o"


def test_frontend_notice_contract_fields_exist_in_stream_and_non_stream_paths() -> None:
    """knowledge_fallback is what the Copilot uses to label an unverified answer."""
    import inspect

    source = inspect.getsource(assistant_module.AIAssistantService)
    assert source.count('"knowledge_fallback"') >= 2
    assert '"truncated": bool(res.get("truncated"))' in source


def test_exception_codes_are_present() -> None:
    import inspect

    source = inspect.getsource(assistant_module)
    assert "AI_LANGFUSE_EXPORT_FAILED" in source
    assert "AI_OFFICIAL_SOURCE_SUGGESTION_FAILED" in source
    logging.getLogger(assistant_module.__name__)  # module logger exists
