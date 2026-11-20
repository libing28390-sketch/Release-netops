from __future__ import annotations

import pytest
import yaml

from ai.services.product_alias_service import (
    ProductAliasError,
    adjudicate_alias_conflict,
    build_alias_record,
    detect_alias_conflicts,
    list_alias_candidates,
    resolve_alias,
)


def _record(alias_id: str, model_id: str, alias: str, kind: str = "exact", *, tenant: str = "tenant-a"):
    return build_alias_record({
        "id": alias_id,
        "tenant_id": tenant,
        "product_model_id": model_id,
        "alias": alias,
        "alias_kind": kind,
        "status": "active",
        "evidence": {"source": "CAT-011-fixture"},
    })


def _conflict_records(*, kind: str = "exact"):
    return [
        _record("alias-a", "model-a", "CE6885", kind),
        _record("alias-b", "model-b", "CE6885", kind),
    ]


def test_cat011_candidate_list_is_bounded_and_requires_clarification():
    annotated, conflicts = detect_alias_conflicts(_conflict_records())
    assert len(conflicts) == 1
    result = list_alias_candidates("CE6885", annotated, tenant_id="tenant-a")
    assert result.outcome == "ambiguous"
    assert result.requires_clarification is True
    assert result.selection_allowed is False
    assert result.manual_review_required is True
    assert {item["product_model_id"] for item in result.candidates} == {"model-a", "model-b"}
    assert [item["candidate_rank"] for item in result.candidates] == [1, 2]


def test_cat011_approve_records_audit_and_allows_only_selected_identity():
    records = _conflict_records()
    annotated, conflicts = detect_alias_conflicts(records)
    updated, audit = adjudicate_alias_conflict(
        annotated,
        conflicts[0].conflict_group,
        decision="approve",
        selected_record_id="alias-a",
        reviewer_id="operator-42",
        reviewed_at="2026-08-09T16:20:00+08:00",
        review_note="Official SKU evidence identifies model-a",
    )
    assert audit.decision == "approve"
    assert audit.selected_record_ids == ("alias-a",)
    assert audit.rejected_record_ids == ("alias-b",)
    selected = next(item for item in updated if item.id == "alias-a")
    rejected = next(item for item in updated if item.id == "alias-b")
    assert selected.review_status == "approved"
    assert selected.conflict_status == "manual_approved"
    assert selected.status == "active"
    assert rejected.review_status == "rejected"
    assert resolve_alias("CE6885", updated, tenant_id="tenant-a").outcome == "unique"
    result = list_alias_candidates("CE6885", updated, tenant_id="tenant-a")
    assert result.selection_allowed is True
    assert result.candidates[0]["product_model_id"] == "model-a"


def test_cat011_prefix_approval_never_becomes_unique_and_rejection_is_unknown():
    records = _conflict_records(kind="prefix")
    annotated, conflicts = detect_alias_conflicts(records)
    updated, _ = adjudicate_alias_conflict(
        annotated,
        conflicts[0].conflict_group,
        decision="approve",
        selected_record_id="alias-a",
        reviewer_id="operator-42",
        reviewed_at="2026-08-09T16:21:00+08:00",
        review_note="Candidate retained for reviewed series evidence",
    )
    candidate_result = list_alias_candidates("CE6885", updated, tenant_id="tenant-a")
    assert candidate_result.outcome == "candidates"
    assert candidate_result.selection_allowed is False
    assert candidate_result.candidates[0]["product_model_id"] == "model-a"

    annotated, conflicts = detect_alias_conflicts(_conflict_records())
    rejected, audit = adjudicate_alias_conflict(
        annotated,
        conflicts[0].conflict_group,
        decision="reject",
        reviewer_id="operator-42",
        reviewed_at="2026-08-09T16:22:00+08:00",
        review_note="Insufficient source evidence",
    )
    assert audit.rejected_record_ids == ("alias-a", "alias-b")
    assert list_alias_candidates("CE6885", rejected, tenant_id="tenant-a").outcome == "unknown"


def test_cat011_reset_and_validation_are_fail_closed():
    annotated, conflicts = detect_alias_conflicts(_conflict_records())
    rejected, _ = adjudicate_alias_conflict(
        annotated,
        conflicts[0].conflict_group,
        decision="reject",
        reviewer_id="operator-42",
        reviewed_at="2026-08-09T16:23:00+08:00",
        review_note="Temporary rejection",
    )
    reset, audit = adjudicate_alias_conflict(
        rejected,
        conflicts[0].conflict_group,
        decision="reset",
        reviewer_id="operator-42",
        reviewed_at="2026-08-09T16:24:00+08:00",
        review_note="New manufacturer evidence arrived",
    )
    assert audit.decision == "reset"
    assert all(item.review_status == "pending_review" for item in reset)
    assert list_alias_candidates("CE6885", reset, tenant_id="tenant-a").manual_review_required is True

    with pytest.raises(ProductAliasError) as missing:
        adjudicate_alias_conflict(
            annotated,
            conflicts[0].conflict_group,
            decision="approve",
            reviewer_id="",
            reviewed_at="2026-08-09T16:25:00+08:00",
            review_note="Missing reviewer",
            selected_record_id="alias-a",
        )
    assert missing.value.code == "ALIAS_REVIEWER_REQUIRED"
    with pytest.raises(ProductAliasError) as secret:
        adjudicate_alias_conflict(
            annotated,
            conflicts[0].conflict_group,
            decision="reject",
            reviewer_id="operator-42",
            reviewed_at="2026-08-09T16:26:00+08:00",
            review_note="Bearer do-not-store",
        )
    assert secret.value.code == "ALIAS_REVIEW_SECRET"
    with pytest.raises(ProductAliasError) as unknown:
        adjudicate_alias_conflict(
            annotated,
            "missing-group",
            decision="reject",
            reviewer_id="operator-42",
            reviewed_at="2026-08-09T16:27:00+08:00",
            review_note="No such group",
        )
    assert unknown.value.code == "ALIAS_CONFLICT_NOT_FOUND"


def test_cat011_contract_and_rollback_have_no_production_ddl():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    contract = yaml.safe_load((root / "docs" / "knowledge-engine" / "architecture" / "CAT-011-ALIAS-ADJUDICATION.yaml").read_text(encoding="utf-8"))
    assert contract["task_id"] == "CAT-011"
    assert contract["manual_adjudication"]["decisions"] == ["approve", "reject", "reset"]
    assert contract["candidate_list"]["one_row_per_product_model"] is True
    assert contract["persistence"]["production_ddl"] == "none_in_CAT-011"
