from __future__ import annotations

from ai.services.copilot_contract import build_copilot_contract


def test_copilot_contract_explains_evidence_and_runtime_boundary():
    contract = build_copilot_contract(
        intent="knowledge",
        message="OSPF 邻居异常",
        context={"device_id": "sw-1", "interface": "Te1/0/1", "vendor": "Huawei"},
        retrieval={"results": [{"document_name": "official-sop"}], "debug": {"vector_top_n": 3}},
        citations=[{"source_type": "official_document", "document": "official-sop"}],
        runtime={"external_egress": True, "model_id": "model-1"},
    )
    assert contract["contract_version"] == "copilot.v2"
    assert contract["runtime"]["external_egress"] is True
    assert "official" in contract["source_labels"]
    assert contract["next_checks"]
    assert contract["developer_trace"]["retrieval"]["final_document_count"] == 1


def test_missing_scope_is_structured_follow_up_not_model_guess():
    contract = build_copilot_contract(intent="troubleshooting", message="链路中断", context={})
    assert "补充 vendor" in contract["required_evidence"]
    assert "补充 model" in contract["required_evidence"]
    assert contract["recognized"]["vendor"] is None


def test_inventory_consultation_does_not_require_diagnostic_scope():
    contract = build_copilot_contract(
        intent="device_search",
        message="我们现在有多少台设备",
        context={},
        citations=[{"source_type": "cmdb_system", "document": "devices"}, {"source_type": "cmdb_system", "document": "devices"}],
    )
    assert contract["required_evidence"] == []
    assert contract["next_checks"] == []
    assert contract["confidence"] == 0.95
    assert contract["source_labels"] == ["realtime_device"]


def test_context_budget_is_explainable_and_trace_has_no_raw_prompt():
    contract = build_copilot_contract(
        intent="troubleshooting",
        message="x" * 20000,
        context={"device_id": "sw-1", "recent_changes": "maintenance-window"},
    )
    assert contract["context_budget"]["truncated"] is True
    assert contract["context_budget"]["used_chars"] <= contract["context_budget"]["limit_chars"]
    assert contract["developer_trace"]["message_hash_only"] is True
    assert "x" * 100 not in str(contract["developer_trace"])
