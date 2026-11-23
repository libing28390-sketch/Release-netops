"""A new, locally recognised request must not inherit an open clarification card.

Regression for "统计下设备信息" being answered with the previous H3C card
("当前已识别 vendor: H3C · 待补充 目标设备 / desired_operation").
"""

from __future__ import annotations

from ai.services.assistant import AIAssistantService

PENDING_H3C_CARD = {
    "required": True,
    "request_kind": "intent_classification",
    "intent": "general_qa",
    "recognized_fields": {"vendor": "H3C"},
    "missing_fields": ["target_device", "desired_operation"],
    "question": "请补充继续处理所需的信息。",
    "state_id": "clar_test",
    "revision": 1,
}


def _merge(message: str, intent_info: dict, response: dict | None = None) -> dict:
    return AIAssistantService._merge_pending_clarification_intent(message, intent_info, PENDING_H3C_CARD, response)


def test_deterministic_asset_report_starts_a_new_topic():
    intent_info = {"intent": "asset_analysis", "filters": {}, "parse_status": "deterministic"}
    merged = _merge("统计下设备信息", intent_info)
    assert merged["intent"] == "asset_analysis"
    assert not merged.get("needs_clarification")
    assert "vendor" not in (merged.get("filters") or {})
    assert not merged.get("missing_fields")


def test_deterministic_alert_query_starts_a_new_topic():
    intent_info = {"intent": "alarm_search", "filters": {"time_range": "today"}, "parse_status": "deterministic"}
    merged = _merge("查询下今天有哪些告警没有处理", intent_info)
    assert merged["intent"] == "alarm_search" and not merged.get("needs_clarification")


def test_a_reply_to_the_card_is_still_merged():
    # A free-text reply parsed by the model is still treated as filling the card.
    intent_info = {"intent": "general_qa", "filters": {"device_name": "CORE-SW1"}, "parse_status": "llm_success"}
    merged = _merge("CORE-SW1", intent_info)
    assert (merged.get("filters") or {}).get("vendor") == "H3C"
    assert merged["filters"].get("device_name") == "CORE-SW1"


def test_card_selection_is_still_merged_even_for_a_deterministic_intent():
    intent_info = {"intent": "asset_analysis", "filters": {}, "parse_status": "deterministic"}
    response = {"state_id": "clar_test", "revision": 1, "values": {"device_name": "CORE-SW1"}}
    merged = _merge("CORE-SW1", intent_info, response)
    assert (merged.get("filters") or {}).get("vendor") == "H3C"
