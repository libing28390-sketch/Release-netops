"""Regression tests for unified zero-token local router & KV-cache stability."""

from __future__ import annotations

import pytest

from ai.services.assistant import AIAssistantService
from ai.services.local_router import compact_local_report_for_history, resolve_local_intent
from core.config import settings


@pytest.fixture(autouse=True)
def _use_legacy_deterministic_bus_mode(monkeypatch):
    monkeypatch.setattr(settings, "AI_COPILOT_AGENTIC_CHAT_ENABLED", False)


def test_single_turn_cmdb_list_queries_route_locally_with_zero_tokens():
    for query, expected_vendor in (
        ("有哪些思科设备", "cisco"),
        ("列出所有华为交换机", "huawei"),
        ("查一下H3C的防火墙", "h3c"),
    ):
        decision = resolve_local_intent(query, history=None)
        assert decision is not None, query
        assert decision["intent"] == "asset_analysis"
        assert decision["parse_status"] == "deterministic"
        assert decision["filters"].get("vendor") == expected_vendor

    offline = resolve_local_intent("离线设备有哪些", history=None)
    assert offline is not None
    assert offline["intent"] == "asset_analysis"
    assert offline["filters"].get("status") == "offline"


def test_config_cli_and_hardware_spec_queries_are_never_hijacked():
    for query in (
        "华为 S5735 怎么配置 OSPF",
        "H3C S5560X-54F-EI 支持 MACsec 吗？",
        "列出 Cisco IOS XE 的 LLDP 查看命令",
        "它有多少个千兆光口？",
        "今天武汉天气怎么样",
    ):
        assert resolve_local_intent(query, history=None) is None, query


def test_multi_turn_cmdb_and_alarm_followups_inherit_local_zero_token_domain():
    cmdb_history = [
        {"role": "user", "content": "H3C设备有多少台"},
        {"role": "assistant", "content": "## Nexora CMDB 资产核对结果\n本次匹配 9 台设备。"},
    ]
    for q, key, val in (
        ("那华为设备呢", "vendor", "huawei"),
        ("那思科呢", "vendor", "cisco"),
        ("防火墙呢", "role", "firewall"),
        ("离线的呢", "status", "offline"),
    ):
        res = resolve_local_intent(q, cmdb_history)
        assert res is not None, q
        assert res["intent"] == "asset_analysis"
        assert res["filters"].get(key) == val

    all_res = resolve_local_intent("那全部设备呢", cmdb_history)
    assert all_res is not None
    assert all_res["intent"] == "asset_analysis"
    assert all_res["filters"] == {}

    # Switching from CMDB asset report to an alarm question must route to alarm_search!
    h3c_alarm = resolve_local_intent("华三的设备有告警没有", cmdb_history)
    assert h3c_alarm is not None
    assert h3c_alarm["intent"] == "alarm_search"
    assert h3c_alarm["filters"].get("vendor") == "h3c"

    # Standalone vendor alarm existence query must also route to alarm_search.
    standalone_alarm = resolve_local_intent("华三的设备有告警没有", None)
    assert standalone_alarm is not None
    assert standalone_alarm["intent"] == "alarm_search"
    assert standalone_alarm["filters"].get("vendor") == "h3c"

    # Switching to CLI config inside a CMDB thread must NOT be hijacked.
    assert resolve_local_intent("华为怎么配置 OSPF", cmdb_history) is None

    alarm_history = [
        {"role": "user", "content": "今天有多少条未恢复告警"},
        {"role": "assistant", "content": "## Nexora 告警统计\n未恢复告警 3 条。"},
    ]
    yesterday = resolve_local_intent("那昨天的呢", alarm_history)
    assert yesterday is not None
    assert yesterday["intent"] == "alarm_search"
    assert yesterday["filters"].get("time_range") == "yesterday"


def test_merge_history_scope_never_downgrades_local_operational_intents():
    hist = [{"role": "user", "content": "H3C S5560X-54F-EI 怎么样"}]
    for intent_name in ("asset_analysis", "device_search", "alarm_search"):
        merged = AIAssistantService._merge_history_scope_continuation(
            "我们有多少台设备",
            {"intent": intent_name, "parse_status": "deterministic", "filters": {}},
            hist,
        )
        assert merged["intent"] == intent_name


def test_compact_local_report_strips_detail_table_deterministically():
    report = (
        "## Nexora CMDB 资产核对结果\n"
        "本次匹配 9 台设备。\n\n"
        "### 一、厂商分布\nH3C: 9\n\n"
        "### 八、设备明细\n"
        "| 主机名 | 厂商 |\n| S6850-1 | H3C |\n" + ("| S6850-X | H3C |\n" * 40)
    )
    c1 = compact_local_report_for_history(report)
    c2 = compact_local_report_for_history(report)
    assert c1 == c2  # Byte-identical for KV cache
    assert "Nexora CMDB 资产核对结果" in c1
    assert "H3C: 9" in c1
    assert "S6850-1" not in c1
    assert "本地明细表已在历史上下文中省略" in c1


def test_history_policy_stays_stable_inside_long_technical_conversation():
    long_history = []
    for i in range(8):
        long_history.append({"role": "user", "content": f"H3C S5560X OSPF 问题 {i}"})
        long_history.append({"role": "assistant", "content": f"解答 {i}"})

    p_general = AIAssistantService._history_policy("简单总结一下", intent="general_qa", history=long_history)
    p_knowledge = AIAssistantService._history_policy("H3C VLAN 怎么配", intent="knowledge", history=long_history)
    assert p_general["name"] == p_knowledge["name"] == "complex"
    assert p_general["token_budget"] == p_knowledge["token_budget"]
