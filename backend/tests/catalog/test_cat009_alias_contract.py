from __future__ import annotations

from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "CAT-009-ALIAS-CONTRACT.yaml"


def _record(alias_id: str, model_id: str, alias: str, kind: str, *, tenant: str = "tenant-a", status: str = "active"):
    from ai.services.product_alias_service import build_alias_record

    return build_alias_record({
        "id": alias_id,
        "tenant_id": tenant,
        "product_model_id": model_id,
        "alias": alias,
        "alias_kind": kind,
        "status": status,
        "evidence": {"source": "CAT-009-fixture"},
    })


def test_cat009_normalization_is_deterministic_and_preserves_identity():
    from ai.services.product_alias_service import build_alias_record, normalize_alias

    assert normalize_alias("  ＣＥ６８８５-48YS8CQ  ") == "ce6885 48ys8cq"
    record = build_alias_record({"id": "a1", "tenant_id": "t1", "product_model_id": "m1", "alias": "CE-6885", "alias_kind": "canonical"})
    assert record.alias == "CE-6885"
    assert record.normalized_alias == "ce 6885"
    assert record.alias_kind == "canonical"


@pytest.mark.parametrize("kind", ["exact", "canonical", "prefix", "trigram"])
def test_cat009_all_alias_kinds_have_explicit_records(kind):
    record = _record(f"{kind}-1", "model-1", "CE6885", kind)
    assert record.alias_kind == kind
    assert record.conflict_status == "none"


def test_cat009_conflicts_are_annotated_without_first_match_fallback():
    from ai.services.product_alias_service import detect_alias_conflicts, resolve_alias

    records = [
        _record("a1", "model-1", "CE-6885", "exact"),
        _record("a2", "model-2", "CE 6885", "exact"),
        _record("a3", "model-1", "CE6885", "canonical"),
        _record("a4", "model-2", "CE6885", "prefix"),
    ]
    annotated, conflicts = detect_alias_conflicts(records)
    exact_rows = [item for item in annotated if item.alias_kind == "exact"]
    assert all(item.conflict_status == "ambiguous_pending_review" for item in exact_rows)
    assert exact_rows[0].conflict_group == exact_rows[1].conflict_group
    assert any(conflict.alias_kind == "exact" and conflict.reason == "same_normalized_alias_multiple_models" for conflict in conflicts)
    resolution = resolve_alias("CE-6885", annotated, tenant_id="tenant-a")
    assert resolution.outcome == "ambiguous"
    assert len(resolution.candidates) == 2


def test_cat009_prefix_and_trigram_are_candidates_and_tenant_scoped():
    from ai.services.product_alias_service import detect_alias_conflicts, resolve_alias, trigram_similarity

    records = [
        _record("p1", "model-1", "CE68", "prefix", tenant="tenant-a"),
        _record("p2", "model-2", "CE688", "prefix", tenant="tenant-a"),
        _record("t1", "model-3", "Catalyst 9300", "trigram", tenant="tenant-a"),
        _record("other", "model-x", "CE6885", "exact", tenant="tenant-b"),
    ]
    annotated, _ = detect_alias_conflicts(records)
    prefix = resolve_alias("CE6885", annotated, tenant_id="tenant-a")
    assert prefix.outcome == "candidates"
    assert {item["product_model_id"] for item in prefix.candidates} == {"model-1", "model-2"}
    trigram = resolve_alias("Catalist 9300", annotated, tenant_id="tenant-a", trigram_threshold=0.2)
    assert trigram.outcome == "candidates"
    assert trigram.candidates[0]["product_model_id"] == "model-3"
    assert trigram.candidates[0]["similarity"] == trigram_similarity("Catalist 9300", "Catalyst 9300")
    assert resolve_alias("CE6885", annotated, tenant_id="tenant-b").outcome == "unique"


def test_cat009_unknown_inactive_and_endpoint_aliases_fail_closed():
    from ai.services.product_alias_service import ProductAliasError, resolve_alias

    with pytest.raises(ProductAliasError) as endpoint:
        _record("url", "m1", "https://example.invalid/model", "exact")
    assert endpoint.value.code == "ALIAS_ENDPOINT_OR_SECRET"
    inactive = _record("inactive", "m1", "CE6885", "exact", status="disabled")
    assert resolve_alias("CE6885", [inactive], tenant_id="tenant-a").outcome == "unknown"
    with pytest.raises(ProductAliasError) as control:
        _record("control", "m1", "CE\n6885", "exact")
    assert control.value.code == "ALIAS_CONTROL_CHARACTER"
    with pytest.raises(ProductAliasError) as evidence:
        from ai.services.product_alias_service import build_alias_record
        build_alias_record({"id": "secret", "tenant_id": "tenant-a", "product_model_id": "m1", "alias": "CE6885", "alias_kind": "exact", "evidence": {"api_key": "do-not-store"}})
    assert evidence.value.code == "ALIAS_EVIDENCE_SECRET"


def test_cat009_contract_freezes_kinds_conflicts_and_no_ddl():
    data = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert data["task_id"] == "CAT-009"
    assert set(data["contract"]["kinds"]) == {"exact", "canonical", "prefix", "trigram"}
    assert data["contract"]["conflicts"]["no_first_match_fallback"] is True
    assert data["contract"]["persistence"]["production_ddl"] == "none_in_CAT-009"
