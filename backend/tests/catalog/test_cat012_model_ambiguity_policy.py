from __future__ import annotations

import pytest
import yaml

from ai.services.model_ambiguity_policy import (
    ModelAmbiguityPolicyError,
    evaluate_model_ambiguity,
)


def _candidate(model: str, *, vendor: str = "huawei", family: str = "cloudengine_6800", series: str = "ce6800", os_family: str = "VRP8", train: str = "V300", platform: str = "huawei_vrp"):
    return {
        "vendor_id": vendor,
        "family_code": family,
        "series_code": series,
        "product_model_id": model,
        "os_family": os_family,
        "software_train": train,
        "cli_platform": platform,
    }


def test_cat012_same_series_is_safe_for_series_knowledge_but_requires_model():
    policy = evaluate_model_ambiguity("candidates", [
        _candidate("huawei:ce6800:ce6881"),
        _candidate("huawei:ce6800:ce6885"),
    ])
    assert policy.knowledge_scope == "series"
    assert policy.clarification_required is True
    assert policy.clarification_fields == ("product_model",)
    assert "series_capabilities" in policy.safe_knowledge_kinds
    assert "product_model" not in policy.safe_knowledge_kinds
    assert policy.platform_specific_knowledge_allowed is False
    assert policy.driver_selection_allowed is False


def test_cat012_unique_explicit_model_is_model_scoped_without_platform_guess():
    policy = evaluate_model_ambiguity("unique", [_candidate("cisco:c9300:c9300-48p", vendor="cisco", family="catalyst_9300", series="c9300", os_family="IOS-XE", train="17.9", platform="cisco_ios")])
    assert policy.knowledge_scope == "model"
    assert policy.clarification_required is False
    assert policy.platform_specific_knowledge_allowed is True
    assert policy.driver_selection_allowed is False


def test_cat012_broader_ambiguity_and_cross_vendor_drop_to_safe_scope():
    family = evaluate_model_ambiguity("ambiguous", [
        _candidate("huawei:ce6800:a", series="ce6800"),
        _candidate("huawei:ce6800:b", series="ce6810"),
    ])
    assert family.knowledge_scope == "family"
    assert family.clarification_fields == ("product_series", "product_model")
    vendor = evaluate_model_ambiguity("candidates", [
        _candidate("huawei:ce6800:a"),
        _candidate("cisco:c9300:b", vendor="cisco", family="catalyst_9300", series="c9300", os_family="IOS-XE", train="17.9", platform="cisco_ios"),
    ])
    assert vendor.knowledge_scope == "generic"
    assert "vendor" in vendor.clarification_fields
    assert vendor.platform_specific_knowledge_allowed is False


def test_cat012_unknown_and_incomplete_context_never_infer_from_model_id():
    unknown = evaluate_model_ambiguity("unknown", [])
    assert unknown.knowledge_scope == "generic"
    assert unknown.clarification_required is True
    incomplete = evaluate_model_ambiguity("candidates", [{"product_model_id": "huawei:ce6800:ce6885"}])
    assert incomplete.knowledge_scope == "generic"
    assert incomplete.rationale == "catalog_context_incomplete_no_identity_inference"
    assert incomplete.driver_selection_allowed is False


def test_cat012_invalid_outcome_is_rejected_and_contract_has_no_ddl():
    with pytest.raises(ModelAmbiguityPolicyError) as error:
        evaluate_model_ambiguity("first_match", [])
    assert error.value.code == "MODEL_RESOLUTION_OUTCOME_UNKNOWN"
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    contract = yaml.safe_load((root / "docs" / "knowledge-engine-v2" / "architecture" / "CAT-012-MODEL-AMBIGUITY-BOUNDARY.yaml").read_text(encoding="utf-8"))
    assert contract["task_id"] == "CAT-012"
    assert contract["security"]["driver_selection_allowed"] is False
    assert contract["persistence"]["production_ddl"] == "none_in_CAT-012"
