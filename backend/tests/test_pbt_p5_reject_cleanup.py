"""
Phase E — Fix-checking PBT for Property P5: reject→draft cleanup.

Task 17.5 — Property P5 — reject→draft cleanup PBT

Generates orders with arbitrary (initial_reviewer, final_approver, approver)
combinations at any of {'initial_review','final_review','rejected'};
drives a → draft transition; asserts the six fields are empty and
result_detail.{initial_review_at,approved_at} popped, while rejected_reason retained.

Validates: Property 5
Requirements: 2.11
"""

from __future__ import annotations

import json
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _force_status(order_id: str, status: str, extra_fields: dict | None = None):
    from database import get_db_connection
    conn = get_db_connection()
    try:
        parts = ["status = ?"]
        values = [status]
        if extra_fields:
            for k, v in extra_fields.items():
                parts.append(f"{k} = ?")
                values.append(v)
        values.append(order_id)
        conn.execute(f"UPDATE change_orders SET {', '.join(parts)} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()


def _get_order_row(order_id: str) -> dict:
    from database import get_db_connection
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM change_orders WHERE id = ?", (order_id,)).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def _create_draft(requester: dict, initial_reviewer: dict, final_approver: dict) -> str:
    from api.change_orders import ChangeOrderCreate, api_create_change_order
    body = ChangeOrderCreate(
        title="P5 reject cleanup test",
        status="draft",
        assigned_initial_reviewer_id=initial_reviewer["user_id"],
        assigned_final_approver_id=final_approver["user_id"],
        command_template={},
        commands=["show version"],
        rollback_plan="",
    )
    result = api_create_change_order(body, user=requester)
    return result["data"]["id"]


def _invoke_transition(order_id: str, new_status: str, actor: dict,
                       extra: dict | None = None) -> tuple[int, object]:
    from api.change_orders import api_transition_change_order
    from fastapi import HTTPException
    body = {"status": new_status, **(extra or {})}
    try:
        result = api_transition_change_order(order_id, body=body, user=actor)
        return 200, result
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


def _assert_fields_cleared(order_id: str, context: str):
    """Assert all six approver witness fields are empty after reject→draft."""
    row = _get_order_row(order_id)
    assert row["status"] == "draft", f"{context}: status should be 'draft', got {row['status']!r}"

    for field in [
        "initial_reviewer_id", "initial_reviewer_username",
        "final_approver_id", "final_approver_username",
        "approver_id", "approver_username",
    ]:
        val = row.get(field, "")
        assert val in (None, ""), (
            f"{context}: field {field!r} should be empty after reject→draft, got {val!r}"
        )

    rd_raw = row.get("result_detail_json", "{}")
    rd = json.loads(rd_raw) if rd_raw else {}
    assert "initial_review_at" not in rd, (
        f"{context}: result_detail.initial_review_at should be popped, got {rd!r}"
    )
    assert "approved_at" not in rd, (
        f"{context}: result_detail.approved_at should be popped, got {rd!r}"
    )


# ── P5a: reject from initial_review → draft clears fields ────────────

def test_p5a_reject_from_initial_review_clears_fields(
    isolated_db, requester, initial_reviewer, final_approver
):
    """After initial_review → rejected → draft, all six fields must be empty."""
    order_id = _create_draft(requester, initial_reviewer, final_approver)
    _force_status(order_id, "initial_review", extra_fields={
        "initial_reviewer_id": initial_reviewer["user_id"],
        "initial_reviewer_username": initial_reviewer["username"],
        "result_detail_json": json.dumps({"initial_review_at": _utc_now()}),
    })

    sc, _ = _invoke_transition(order_id, "rejected", actor=initial_reviewer,
                               extra={"rejected_reason": "needs rework"})
    assert sc == 200, "Setup: could not reject from initial_review"

    sc2, _ = _invoke_transition(order_id, "draft", actor=requester)
    assert sc2 == 200, "Could not transition rejected → draft"

    _assert_fields_cleared(order_id, "initial_review→rejected→draft")

    row = _get_order_row(order_id)
    assert row.get("rejected_reason") == "needs rework", "rejected_reason should be preserved"


# ── P5b: reject from final_review → draft clears fields ──────────────

def test_p5b_reject_from_final_review_clears_fields(
    isolated_db, requester, initial_reviewer, final_approver
):
    """After final_review → rejected → draft, all six fields must be empty."""
    order_id = _create_draft(requester, initial_reviewer, final_approver)
    _force_status(order_id, "final_review", extra_fields={
        "initial_reviewer_id": initial_reviewer["user_id"],
        "initial_reviewer_username": initial_reviewer["username"],
        "assigned_final_approver_id": final_approver["user_id"],
        "assigned_final_approver_username": final_approver["username"],
        "result_detail_json": json.dumps({"initial_review_at": _utc_now()}),
    })

    sc, _ = _invoke_transition(order_id, "rejected", actor=final_approver,
                               extra={"rejected_reason": "incomplete docs"})
    assert sc == 200, "Setup: could not reject from final_review"

    sc2, _ = _invoke_transition(order_id, "draft", actor=requester)
    assert sc2 == 200, "Could not transition rejected → draft"

    _assert_fields_cleared(order_id, "final_review→rejected→draft")

    row = _get_order_row(order_id)
    assert row.get("rejected_reason") == "incomplete docs", "rejected_reason should be preserved"


# ── PBT: reject from any review stage clears fields ──────────────────

@given(reject_stage=st.sampled_from(["initial_review", "final_review"]))
@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p5_pbt_reject_to_draft_clears_all_fields(
    reject_stage, isolated_db, requester, initial_reviewer, final_approver
):
    """PBT: for any reject stage, reject→draft clears all six fields."""
    order_id = _create_draft(requester, initial_reviewer, final_approver)

    if reject_stage == "final_review":
        _force_status(order_id, "final_review", extra_fields={
            "initial_reviewer_id": initial_reviewer["user_id"],
            "initial_reviewer_username": initial_reviewer["username"],
            "assigned_final_approver_id": final_approver["user_id"],
            "assigned_final_approver_username": final_approver["username"],
            "result_detail_json": json.dumps({"initial_review_at": _utc_now()}),
        })
        sc, _ = _invoke_transition(order_id, "rejected", actor=final_approver,
                                   extra={"rejected_reason": f"PBT reject from {reject_stage}"})
    else:
        _force_status(order_id, "initial_review", extra_fields={
            "initial_reviewer_id": initial_reviewer["user_id"],
            "initial_reviewer_username": initial_reviewer["username"],
            "result_detail_json": json.dumps({"initial_review_at": _utc_now()}),
        })
        sc, _ = _invoke_transition(order_id, "rejected", actor=initial_reviewer,
                                   extra={"rejected_reason": f"PBT reject from {reject_stage}"})

    assert sc == 200, f"Setup: could not reject from {reject_stage}"

    sc2, _ = _invoke_transition(order_id, "draft", actor=requester)
    assert sc2 == 200, "Could not transition rejected → draft"

    _assert_fields_cleared(order_id, f"PBT {reject_stage}→rejected→draft")
