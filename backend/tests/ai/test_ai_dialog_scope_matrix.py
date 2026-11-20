from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
DATASET = ROOT / "docs" / "knowledge-engine" / "eval" / "ai-dialog-remediation-v1.yaml"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _parsed_scope(prompt: str) -> dict[str, object]:
    from ai.services.intent_parser import intent_parser

    return intent_parser.parse_knowledge_metadata(prompt)


def _merged_scope(first_prompt: str, follow_up: str) -> dict[str, object]:
    from ai.services.assistant import AIAssistantService

    current = _parsed_scope(follow_up)
    info = {
        "intent": "knowledge",
        "knowledge_intent": current,
        "metadata": current,
        "filters": current,
    }
    merged = AIAssistantService._merge_history_scope_continuation(
        follow_up,
        info,
        [{"role": "user", "content": first_prompt}],
    )
    return dict(merged.get("knowledge_intent") or {})


def test_dialogue_matrix_is_frozen_and_has_required_scope_cases() -> None:
    payload = yaml.safe_load(DATASET.read_text(encoding="utf-8"))
    matrix = payload["dialogue_matrix"]
    assert len(matrix) >= 8
    assert {item["id"] for item in matrix} >= {
        "DLG-SCOPE-001", "DLG-SCOPE-002", "DLG-SCOPE-003", "DLG-SCOPE-004",
        "DLG-SCOPE-005", "DLG-SCOPE-006", "DLG-SCOPE-007", "DLG-SCOPE-008",
    }
    assert all(len(item["turns"]) >= 2 for item in matrix if item.get("turns"))


@pytest.mark.parametrize(
    ("first_prompt", "follow_up", "vendor", "feature"),
    [
        ("我想查下华为交换机的 ospf 配置示例", "那可以提供思科的吗", "Cisco", "ospf"),
        ("我想查下华为交换机的 ospf 配置示例", "华三的呢", "H3C", "ospf"),
        ("H3C Comware 7 BGP 邻居配置", "Cisco 的呢", "Cisco", "bgp"),
    ],
)
def test_vendor_follow_up_matrix_keeps_only_previous_feature(
    first_prompt: str,
    follow_up: str,
    vendor: str,
    feature: str,
) -> None:
    scope = _merged_scope(first_prompt, follow_up)
    assert scope["vendor"] == vendor
    assert scope["feature"] == feature
    assert scope["document_category"] == "configuration"
    assert scope.get("cli_platform") is None


def test_h3c_aliases_have_one_canonical_vendor() -> None:
    scopes = [_parsed_scope(prompt) for prompt in (
        "华三交换机 OSPF 配置",
        "新华三交换机 OSPF 配置",
        "H3C Comware OSPF 配置",
    )]
    assert [scope.get("vendor") for scope in scopes] == ["H3C", "H3C", "H3C"]


def test_explicit_feature_and_platform_override_history_without_pollution() -> None:
    feature_scope = _merged_scope("华为交换机 OSPF 配置", "那换成 Cisco 的 BGP 配置吧")
    assert feature_scope["vendor"] == "Cisco"
    assert feature_scope["feature"] == "bgp"
    assert feature_scope["document_category"] == "configuration"

    platform_scope = _merged_scope("华为交换机 OSPF 配置", "那换成 H3C Comware v7 吧")
    assert platform_scope["vendor"] == "H3C"
    assert platform_scope["feature"] == "ospf"
    assert platform_scope["cli_platform"] == "h3c_comware"
    assert platform_scope["document_category"] == "configuration"
    assert platform_scope.get("software_release") is None


def test_full_configuration_follow_up_does_not_inherit_feature_as_executable_scope() -> None:
    from ai.services.config_clarification import assess_configuration_request

    current = _parsed_scope("那给我思科的全部配置")
    merged = _merged_scope("华为交换机 OSPF 配置", "那给我思科的全部配置")
    decision = assess_configuration_request(
        message="那给我思科的全部配置",
        metadata=merged,
        resolution={"ambiguous": True, "platform_candidates": []},
    )
    assert current.get("vendor") == "Cisco"
    assert merged.get("feature") is None
    assert decision is not None and decision.required is True
    assert decision.retrieval_allowed is False
