"""Tests for Native LLM Agentic Chat + 12-Module & Local KB Read-Only Tool Calling."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from ai.gateway.exceptions import AIInvalidRequestException
from ai.security.gateway import _has_credential_field, _tool_is_unsafe
from ai.services import copilot_tools
from ai.services.assistant import AIAssistantService
from ai.services.local_router import resolve_local_intent
from core.config import settings


def test_all_copilot_tools_pass_security_gateway_read_only_and_dlp_checks():
    """Every tool schema must pass _tool_is_unsafe and contain zero credential field markers."""
    local_tools = copilot_tools.get_copilot_tools(allow_web_search=False)
    assert len(local_tools) == 9
    assert all(t["function"]["name"] != "search_public_web" for t in local_tools)

    all_tools = copilot_tools.get_copilot_tools(allow_web_search=True)
    assert len(all_tools) == 10
    for tool in all_tools:
        assert not _tool_is_unsafe(tool), f"Tool flagged unsafe: {tool['function']['name']}"
        assert not _has_credential_field(tool), f"Tool contains credential marker: {tool['function']['name']}"


def test_agentic_mode_keeps_slash_shortcuts_zero_token_and_passes_natural_language_to_llm(monkeypatch):
    """Hybrid Dual-Track: short single-fact queries take 0-token Track A; reasoning/multi-intent go to Track B LLM."""
    monkeypatch.setattr(settings, "AI_COPILOT_AGENTIC_CHAT_ENABLED", True)
    # Track A: explicit /slash shortcuts & concise single-fact queries (0 Token)
    assert resolve_local_intent("/alarms") is not None
    assert resolve_local_intent("/racks") is not None
    assert resolve_local_intent("/pam") is not None

    cnt = resolve_local_intent("查一下我们有多少台设备")
    assert cnt is not None and cnt["intent"] == "module_bus" and cnt["filters"]["module"] == "device_count_summary"

    h3c_alarm = resolve_local_intent("华三的设备有告警没有")
    assert h3c_alarm is not None and h3c_alarm["intent"] == "alarm_search"

    # Track B: reasoning, cutover advice, multi-intent, CLI commands, memory writes MUST go to LLM (None)
    assert resolve_local_intent("结合上面的信息分析下为什么告警") is None
    assert resolve_local_intent("S6850_1 最近要安排一次端口割接，有什么双机架构和变更窗口需要注意的？顺便看看 S6850-2 告警") is None
    assert resolve_local_intent("记住一条长期运维常识：S6850_1 和 S6850-2 是双核心互备") is None
    assert resolve_local_intent("针对 S6850_1 给我列出检查光功率的命令") is None


@pytest.mark.asyncio
async def test_agentic_chat_parallel_tool_loop_and_multi_hypothesis_synthesis(monkeypatch):
    """LLM calls multiple local read-only tools in parallel, detokenizes args, and synthesizes."""
    monkeypatch.setattr(settings, "AI_COPILOT_AGENTIC_CHAT_ENABLED", True)
    svc = AIAssistantService()

    call_count = 0

    async def _fake_llm_chat(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            assert kwargs.get("tools"), "Expected read-only tools passed on round 1"
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "query_alarms", "arguments": json.dumps({"target": "10.254.0.1"})},
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {"name": "query_pam_sessions", "arguments": json.dumps({"target": "10.254.0.1", "days": 7})},
                    },
                ],
                "provider_id": "prov-1",
                "model_id": "model-1",
                "input_tokens": 400,
                "output_tokens": 55,
                "cached_tokens": 200,
            }
        # Round 2 sees both role='tool' results in messages and synthesizes hypotheses
        msgs = kwargs.get("messages") or []
        tool_roles = [m for m in msgs if m.get("role") == "tool"]
        assert len(tool_roles) == 2
        return {
            "content": "已排除近期人为登录改配（近7天 PAM 登录 0 次）；结合 S6850_1 的 1 条未恢复告警，高概率原因为物理链路闪断或光模块衰减。",
            "tool_calls": None,
            "provider_id": "prov-1",
            "model_id": "model-1",
            "input_tokens": 520,
            "output_tokens": 80,
            "cached_tokens": 350,
        }

    async def _fake_exec_tool(name, args, **kwargs):
        if name == "query_alarms":
            return {"content": "S6850_1 未恢复告警 1 条：GE1/0/24 link down", "citations": [{"document": "Nexora alarms", "trust": "system"}]}
        if name == "query_pam_sessions":
            return {"content": "S6850_1 近 7 天 PAM 登录 0 次", "citations": [{"document": "Nexora PAM", "trust": "system"}]}
        return {"content": "ok", "citations": []}

    with (
        patch.object(copilot_tools, "lookup_device_in_db", return_value=None),
        patch("ai.services.assistant.llm_gateway.chat", new=AsyncMock(side_effect=_fake_llm_chat)),
        patch.object(copilot_tools, "execute_copilot_tool", new=AsyncMock(side_effect=_fake_exec_tool)),
    ):
        res = await svc.chat(
            "核心网最近有点抖动，帮我核查一下有没有异常告警或人为登录改配？",
            roles=["operator"],
            context={"conversation_id": "conv-agentic-1"},
        )

    assert res["intent"] == "agentic_chat"
    assert res["facts_retrieved"] is True
    assert set(res["tools_used"]) == {"query_alarms", "query_pam_sessions"}
    assert res["input_tokens"] == 920
    assert res["output_tokens"] == 135
    assert res["cached_tokens"] == 550
    assert "排除近期人为登录" in res["answer"]
    assert len(res["citations"]) == 2


@pytest.mark.asyncio
async def test_agentic_chat_graceful_fallback_when_model_rejects_tools(monkeypatch):
    """If a custom model rejects tools with 400, gracefully retry without tools."""
    monkeypatch.setattr(settings, "AI_COPILOT_AGENTIC_CHAT_ENABLED", True)
    svc = AIAssistantService()

    attempts = 0

    async def _fake_llm_chat(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1 and kwargs.get("tools"):
            raise AIInvalidRequestException("tools not supported")
        return {
            "content": "已降级为标准对话模式回答。",
            "tool_calls": None,
            "provider_id": "prov-local",
            "model_id": "model-small",
            "input_tokens": 100,
            "output_tokens": 20,
        }

    with patch("ai.services.assistant.llm_gateway.chat", new=AsyncMock(side_effect=_fake_llm_chat)):
        res = await svc.chat("你好，介绍一下自己", roles=["operator"])

    assert attempts == 2
    assert res["answer"] == "已降级为标准对话模式回答。"


@pytest.mark.asyncio
async def test_agentic_chat_still_blocks_destructive_cli_at_zero_tokens(monkeypatch):
    """Destructive device execution requests are still blocked locally at 0 tokens."""
    monkeypatch.setattr(settings, "AI_COPILOT_AGENTIC_CHAT_ENABLED", True)
    svc = AIAssistantService()
    res = await svc.chat("帮我在这台设备上执行 undo ospf 1 并保存", roles=["operator"])
    assert res["execution_mode"] == "local_security_block"
    assert res["input_tokens"] == 0
    assert "Copilot 不会在设备上执行命令" in res["answer"]


def test_fix_read_only_snmp_display_cli_not_over_redacted():
    """Bug 3 regression: `display snmp-agent community` must NOT be mangled into <REDACTED_CREDENTIAL>."""
    from ai.security.output import sanitize_output
    from ai.security.tokenization import ScopedTokenVault

    vault = ScopedTokenVault()
    text = "可在设备上运行 `display snmp-agent community` 查看只读配置，切勿泄露真实值。"
    cleaned = sanitize_output(text, tenant_id="t1", task_id="k1", vault=vault)
    assert "display snmp-agent community" in cleaned
    assert "<REDACTED_CREDENTIAL>" not in cleaned

    # Real secret assignment MUST still be redacted!
    leaked = "snmp-agent community read PublicSecret123!"
    redacted = sanitize_output(leaked, tenant_id="t1", task_id="k1", vault=vault)
    assert "PublicSecret123!" not in redacted
    assert "<REDACTED_CREDENTIAL>" in redacted


def test_fix_agentic_history_caps_long_sessions_and_strips_stale_placeholders():
    """Bug 2 & 4 regression: sliding window caps turns and strips any leaked [[NXA_...]] tokens."""
    long_history = []
    for i in range(40):
        long_history.append({"role": "user", "content": f"问题 {i}"})
        long_history.append({
            "role": "assistant",
            "content": f"设备 [[NXA_DEVICE_AbCdEfGhIjKlMnOpQr]] 回复 {i} " + ("详细数据" * 250),
        })
    selected = AIAssistantService._select_agentic_history(long_history)
    # 12 turns (24 messages) + at most 1 prepended short-term rolling summary
    assert len(selected) <= 25
    for msg in selected:
        assert "[[NXA_" not in msg["content"]
    # Static prompt includes today's date (YYYY-MM-DD)
    prompt = copilot_tools.build_agentic_system_prompt(allow_web_search=False)
    assert "Current Date: 202" in prompt


@pytest.mark.asyncio
async def test_fix_stream_synthesis_avoids_raw_tool_messages_and_handles_empty_stream(monkeypatch):
    """Bug 1 regression: after 2 tool rounds, final chat_stream receives clean user synthesis message (no role='tool')."""
    monkeypatch.setattr(settings, "AI_COPILOT_AGENTIC_CHAT_ENABLED", True)
    monkeypatch.setattr(settings, "AI_COPILOT_MAX_TOOL_ROUNDS", 2)
    svc = AIAssistantService()

    stream_received_messages = []

    async def _fake_chat(*args, **kwargs):
        if kwargs.get("tools"):
            return {
                "content": "",
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "query_alarms", "arguments": "{}"}}
                ],
                "provider_id": "p1",
                "model_id": "m1",
                "input_tokens": 100,
                "output_tokens": 20,
            }
        return {"content": "降级非流式兜底成功：共 1 条未恢复告警。", "provider_id": "p1", "model_id": "m1", "input_tokens": 90, "output_tokens": 15}

    async def _empty_stream(*args, **kwargs):
        stream_received_messages.extend(kwargs.get("messages") or [])
        if False:
            yield ""

    with (
        patch("ai.services.assistant.llm_gateway.chat", new=AsyncMock(side_effect=_fake_chat)),
        patch("ai.services.assistant.llm_gateway.chat_stream", side_effect=_empty_stream),
        patch.object(copilot_tools, "execute_copilot_tool", new=AsyncMock(return_value={"content": "S6850_1 告警 1 条", "citations": []})),
    ):
        events = []
        async for evt in svc.chat_stream("10.254.0.1 告警分析", roles=["operator"]):
            events.append(evt)

    # Final stream MUST NOT contain role='tool' or tool_calls when tools=None
    assert stream_received_messages
    assert all(m.get("role") in {"system", "user", "assistant"} and not m.get("tool_calls") for m in stream_received_messages)
    # Empty stream triggered non-stream fallback cleanly
    joined = "".join(events)
    assert "降级非流式兜底成功" in joined


def test_fix_sanitizer_preserves_multiline_display_snmp_community():
    """Sanitizer must NOT eat the next line after `include snmp-agent community`."""
    from ai.security.sanitizer import sanitize_text

    sample = (
        "display current-configuration | include snmp-agent community\n"
        "display snmp-agent community\n"
    )
    out = sanitize_text(sample)
    assert "display snmp-agent community" in out
    assert "<REDACTED>" not in out

    # Real secret on same line MUST still be redacted
    secret_cfg = "snmp-agent community read MyRealSecret99\n"
    redacted = sanitize_text(secret_cfg)
    assert "MyRealSecret99" not in redacted
    assert "<REDACTED>" in redacted


@pytest.mark.asyncio
async def test_zero_token_prefetch_collapses_explicit_device_alarm_query_to_single_llm_call(monkeypatch):
    """Explicit device + alarm query prefetches locally (0 tok) and uses 1 single LLM call (no 2-round tool planning)."""
    monkeypatch.setattr(settings, "AI_COPILOT_AGENTIC_CHAT_ENABLED", True)
    svc = AIAssistantService()

    dev1 = {"id": "d1", "hostname": "S6850_1", "ip_address": "10.254.0.1", "vendor": "H3C"}
    dev2 = {"id": "d2", "hostname": "S6850-2", "ip_address": "10.254.0.2", "vendor": "H3C"}

    def _fake_lookup(*, ip=None, hostname=None):
        if hostname == "S6850_1" or ip == "10.254.0.1":
            return dev1
        if hostname == "S6850-2" or ip == "10.254.0.2":
            return dev2
        return None

    llm_calls = []

    async def _fake_chat(*args, **kwargs):
        llm_calls.append(kwargs)
        return {
            "content": "S6850-2 当前存在 1 条未恢复告警，建议暂缓割接。",
            "provider_id": "p1",
            "model_id": "m1",
            "input_tokens": 1200,
            "output_tokens": 80,
        }

    with (
        patch.object(copilot_tools, "lookup_device_in_db", side_effect=_fake_lookup),
        patch.object(
            copilot_tools,
            "execute_copilot_tool",
            new=AsyncMock(return_value={"content": "S6850-2 未恢复告警 1 条：SNMP Unreachable", "citations": [{"document": "alarms"}]}),
        ),
        patch("ai.services.assistant.llm_gateway.chat", new=AsyncMock(side_effect=_fake_chat)),
    ):
        res = await svc.chat("S6850_1 要割接，顺便看看对端 S6850-2 有没有未恢复告警", roles=["operator"])

    # Exactly 1 LLM call with tools=None (skipped 2-round tool planning!)
    assert len(llm_calls) == 1
    assert llm_calls[0].get("tools") is None
    assert "本地已预取实锤数据" in llm_calls[0]["messages"][-1]["content"]
    assert "S6850-2" in res["answer"]


def test_synthesis_messages_keep_kb_cli_examples_out_of_user_role_so_security_gateway_allows():
    """Turn 4 regression: KB docs with `system-view` must not trip AI_SECURITY_UNSAFE_TOOL in user_only_messages."""
    from ai.security.gateway import AISecurityGateway, SecurityPolicy

    base = [{"role": "system", "content": "You are Nexora AI Copilot."}]
    user_q = "结合刚才查到的华三设备与告警情况，帮我分析下可能的原因并给出下一步只读排查建议"
    kb_evidence = [
        "[search_local_knowledge]\n[1] SNMPv3 基础配置（H3C Comware 7）\nsystem-view\nsnmp-agent sys-info version v3\nacl basic 2000\nrule permit source 10.0.0.1 0"
    ]
    synth = AIAssistantService._build_synthesis_messages(base, user_q, kb_evidence)
    # User messages must NOT contain the KB `system-view` config block
    user_texts = [m["content"] for m in synth if m.get("role") == "user"]
    assert all("system-view" not in t for t in user_texts)

    gw = AISecurityGateway(
        policy=SecurityPolicy(external_ai_enabled=True, allowed_classifications=("PUBLIC", "INTERNAL", "CONFIDENTIAL"))
    )
    payload = gw.protect(
        synth,
        tenant_id="tenant-default",
        task_id="test-t4",
        user_id="admin",
        provider_type="openai_compatible",
        data_classification="INTERNAL",
        scene="chat",
    )
    assert payload is not None

