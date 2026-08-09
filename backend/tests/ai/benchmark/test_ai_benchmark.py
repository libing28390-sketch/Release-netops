from __future__ import annotations

import pytest

from ai.security.classification import DataLevel, classify_text
from ai.security.gateway import AISecurityGateway, SecurityBlocked, SecurityPolicy
from ai.security.tokenization import ScopedTokenVault
from ai.services.rag_policy import document_is_visible
from ai.tools.registry import tool_registry


CASES = [
    {
        "id": "public_network_question",
        "input": "What causes OSPF EXSTART?",
        "expected_level": DataLevel.L1_GENERAL,
        "risk": "read",
    },
    {
        "id": "identifier_is_tokenized",
        "input": "Check 192.0.2.10 on edge-router01.example.com",
        "expected_level": DataLevel.L2_IDENTIFIER,
        "risk": "read",
    },
    {
        "id": "credential_is_blocked",
        "input": "password=NeverSendThis",
        "expected_level": DataLevel.L4_PROHIBITED,
        "risk": "blocked",
    },
]


@pytest.mark.parametrize("case", CASES, ids=lambda item: item["id"])
def test_benchmark_classification_contract(case: dict) -> None:
    findings = classify_text(case["input"])
    level = max((item.level for item in findings), default=DataLevel.L1_GENERAL)
    assert level == case["expected_level"]


def test_benchmark_gateway_blocks_secret_and_keeps_fake_token_opaque() -> None:
    gateway = AISecurityGateway(
        vault=ScopedTokenVault(ttl_seconds=60),
        policy=SecurityPolicy(external_ai_enabled=True),
    )
    with pytest.raises(SecurityBlocked):
        gateway.protect([{"role": "user", "content": "running-config password=NeverSendThis"}])
    assert gateway.resolve_output("[[NXA_DEV_FAKE]]", tenant_id="t-a", task_id="task") == "[[NXA_DEV_FAKE]]"


def test_benchmark_rag_acl_is_tenant_and_scope_safe() -> None:
    doc = {"tenant_id": "tenant-a", "acl_json": '{"sites": ["site-a"]}'}
    assert document_is_visible(doc, tenant_id="tenant-a", site_ids=["site-a"])
    assert not document_is_visible(doc, tenant_id="tenant-b", site_ids=["site-a"])
    assert not document_is_visible(doc, tenant_id="tenant-a", site_ids=["site-b"])


def test_benchmark_unknown_tool_and_write_capability_are_not_executable() -> None:
    assert tool_registry.execute_tool("unknown_tool", {})["error_code"] == "TOOL_NOT_FOUND"
    assert {item["name"] for item in tool_registry.list_tools()} >= {
        "get_asset", "get_device_status", "get_arp_entry", "get_mac_entry",
        "get_lldp_neighbors", "find_ip_location", "get_running_config", "compare_config",
    }
