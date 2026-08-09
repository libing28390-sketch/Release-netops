from __future__ import annotations

from pathlib import Path

import yaml

from ai.services.product_alias_service import build_alias_record, detect_alias_conflicts, resolve_alias


ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "docs" / "knowledge-engine-v2" / "catalog" / "CAT-010-ALIAS-SAMPLES.yaml"
CAT005 = ROOT / "docs" / "knowledge-engine-v2" / "catalog" / "CAT-005-HUAWEI-CE6800.yaml"
CAT006 = ROOT / "docs" / "knowledge-engine-v2" / "catalog" / "CAT-006-CISCO-C9300.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _model_ids() -> set[str]:
    huawei = _load(CAT005)
    cisco = _load(CAT006)
    return {
        *{
            f"huawei:cloudengine_6800:ce6800:{str(item['model_code']).lower()}"
            for item in huawei["product_family"]["product_series"][0]["model_samples"]
        },
        *{
            f"cisco:catalyst_9300:c9300:{str(item['model_code']).lower()}"
            for item in cisco["product_family"]["product_series"][0]["model_samples"]
        },
    }


def test_cat010_samples_target_known_models_and_use_all_required_kinds():
    data = _load(SAMPLE)
    rows = data["alias_samples"]
    assert {item["alias_kind"] for item in rows} == {"exact", "canonical", "prefix"}
    assert all(item["tenant_id"] == data["tenant_scope"] for item in rows)
    assert all(item["product_model_id"] in _model_ids() for item in rows)
    assert all(item["status"] == "draft" for item in rows)
    assert len({item["sample_id"] for item in rows}) == len(rows)


def test_cat010_conflicts_and_resolution_matrix_match_expected_behavior():
    data = _load(SAMPLE)
    records = [
        build_alias_record({
            "id": row["sample_id"],
            "tenant_id": row["tenant_id"],
            "product_model_id": row["product_model_id"],
            "alias": row["alias"],
            "alias_kind": row["alias_kind"],
            "status": "active",
        })
        for row in data["alias_samples"]
    ]
    annotated, conflicts = detect_alias_conflicts(records)
    prefix_groups = [item for item in conflicts if item.alias_kind == "prefix"]
    assert prefix_groups
    assert all(item.conflict_status == "ambiguous_pending_review" for item in prefix_groups)
    active = [item for item in annotated if item.conflict_status != "duplicate_same_target"]
    for item in data["resolution_matrix"]:
        result = resolve_alias(item["query"], active, tenant_id=data["tenant_scope"], trigram_threshold=0.2)
        if item["result"] == "unique_after_active_review":
            assert result.outcome == "unique"
        elif item["result"] in {"candidates_and_clarification", "candidate_requires_full_sku_confirmation"}:
            assert result.outcome in {"candidates", "ambiguous"}
        else:
            assert result.outcome == "unknown"


def test_cat010_contract_is_fail_closed_and_has_no_production_ddl():
    data = _load(SAMPLE)
    assert data["acceptance"]["target_must_be_product_model"] is True
    assert data["acceptance"]["series_aliases_are_candidate_only"] is True
    assert data["acceptance"]["no_first_match_fallback"] is True
    assert data["rollback"]["production_ddl"] == "none_in_CAT-010"

