"""
Phase A — Exploration test for cluster 1.3 (approver dedup / permission group).

**Property 1: Bug Condition** — POST bypass via empty `change_groups_json`,
PUT bypass of dedup, transition hijack of final approver.

Per the spec front-matter of `tasks.md`:
    "Tests that need to fail on unfixed code are marked xfail(strict=True)
     → flip to strict-pass after the fix lands."

The xfail-marked assertions below encode the *fixed* expectation:
  - (a) POST with reviewer whose change_groups_json='[]' → HTTP 400
  - (b) PUT with reviewer == requester or reviewer == approver → HTTP 400
  - (c) Transition to final_review with invalid final_approver → HTTP 400
        and order state unchanged

On UNFIXED code the assertions fail → pytest reports XFAIL → exploration
SUCCESS (the bug exists). On FIXED code (after task 12.x) the assertions
pass → pytest reports XPASS-strict → we remove the xfail marker.

Validates: Property 3 (design.md §Correctness Properties)
Bug_Condition: `C3(input)` in `design.md §Bug Details`
Requirements: 1.7, 1.8, 1.9 (bugfix.md)
"""

from __future__ import annotations

import json
import pytest
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings, strategies as st


# ── Helpers: invoke handlers in-process, bypass HTTP/middleware ───────

def _invoke_create(body_payload: dict, actor: dict) -> tuple[int, object]:
    """Return `(status_code, result_or_detail)`.  200 on success, the
    HTTPException `status_code` and `detail` on failure."""
    from api.change_orders import ChangeOrderCreate, api_create_change_order

    body_payload.setdefault("title", "Cluster 1.3 exploration test")
    body_payload.setdefault("description", "")
    body_payload.setdefault("order_type", "config_change")
    body_payload.setdefault("priority", "medium")
    body_payload.setdefault("target_devices", [])
    body_payload.setdefault("commands", ["show version"])
    body_payload.setdefault("rollback_plan", "rollback steps")
    body_payload.setdefault("risk_level", "low")
    body_payload.setdefault("scheduled_start", "")
    body_payload.setdefault("scheduled_end", "")
    body = ChangeOrderCreate(**body_payload)
    try:
        result = api_create_change_order(body, user=actor)
        data = result.get("data") if isinstance(result, dict) else result
        return 200, data
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


def _invoke_update(order_id: str, body_payload: dict, actor: dict) -> tuple[int, object]:
    """Return `(status_code, result_or_detail)` for PUT /change-orders/{id}."""
    from api.change_orders import ChangeOrderUpdate, api_update_change_order

    body = ChangeOrderUpdate(**body_payload)
    try:
        result = api_update_change_order(order_id, body=body, user=actor)
        data = result.get("data") if isinstance(result, dict) else result
        return 200, data
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


def _invoke_transition(order_id: str, new_status: str, actor: dict,
                       extra_body: dict | None = None) -> tuple[int, object]:
    """Return `(status_code, result_or_detail)` for a transition call."""
    from api.change_orders import api_transition_change_order

    body = {"status": new_status}
    if extra_body:
        body.update(extra_body)
    try:
        result = api_transition_change_order(order_id, body=body, user=actor)
        data = result.get("data") if isinstance(result, dict) else result
        return 200, data
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


def _get_order_row(order_id: str) -> dict | None:
    """Read the raw change_orders row from DB for persistence delta checks."""
    from database import get_db_connection
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM change_orders WHERE id = ?", (order_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _create_legal_draft(requester: dict, initial_reviewer: dict) -> str:
    """Create a legal draft order and return its id."""
    status_code, data = _invoke_create(
        {
            "status": "draft",
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
        },
        actor=requester,
    )
    assert status_code == 200, f"Setup failed: could not create draft order: {data}"
    return data["id"]


def _create_legal_order_in_initial_review(
    requester: dict, initial_reviewer: dict, final_approver: dict
) -> str:
    """Create a legal order and transition it to initial_review, return id."""
    # Create as draft first
    order_id = _create_legal_draft(requester, initial_reviewer)
    # Transition to initial_review
    status_code, data = _invoke_transition(
        order_id, "initial_review", actor=requester
    )
    assert status_code == 200, (
        f"Setup failed: could not transition to initial_review: {data}"
    )
    return order_id


# ─────────────────────────────────────────────────────────────────────
# Sub-property (a): POST bypass via empty change_groups_json
#
# Bug: _resolve_assignment_user has `if groups and 'initial_reviewer' not
# in groups` — when change_groups_json='[]', `groups` is an empty set
# (falsy), so the check is skipped entirely. A user with NO group
# membership can be assigned as initial_reviewer.
# ─────────────────────────────────────────────────────────────────────

@given(
    role=st.sampled_from(["Operator", "Administrator"]),
)
@settings(
    max_examples=8,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p3a_post_empty_groups_reviewer_rejected(
    role, isolated_db, requester, make_user
):
    """
    **Validates: Property 3** — POST /change-orders with
    assigned_initial_reviewer_id = user whose change_groups_json='[]'
    MUST return HTTP 400.

    On unfixed code: the `if groups` short-circuit in
    _resolve_assignment_user means empty groups bypass the membership
    check → HTTP 200 (bug exists).
    """
    # Create a user with empty change_groups (the bug vector)
    empty_groups_user = make_user(
        f"empty_groups_{role.lower()}",
        role=role,
        change_groups=[],  # This is the key: empty list
    )

    payload = {
        "status": "draft",
        "assigned_initial_reviewer_id": empty_groups_user["user_id"],
    }

    status_code, detail = _invoke_create(payload, actor=requester)

    assert status_code == 400, (
        f"Bug_Condition C3(a) surfaced: POST with reviewer whose "
        f"change_groups_json='[]' (role={role}) → HTTP {status_code} "
        f"(expected 400 after fix). Detail: {detail!r}"
    )


# ─────────────────────────────────────────────────────────────────────
# Sub-property (b): PUT bypass of dedup rules
#
# Bug: api_update_change_order does NOT check:
#   - assigned_initial_reviewer_id != requester_id
#   - assigned_initial_reviewer_id != assigned_final_approver_id
# These checks only exist in api_create_change_order.
# ─────────────────────────────────────────────────────────────────────

def test_p3b_put_reviewer_equals_requester_rejected(
    isolated_db, requester, initial_reviewer, final_approver
):
    """
    **Validates: Property 3** — PUT /change-orders/{id} with
    assigned_initial_reviewer_id = existing.requester_id MUST return
    HTTP 400.

    On unfixed code: PUT path has no dedup check → HTTP 200 (bug exists).
    Persistence delta: order row must be byte-identical to pre-request state.
    """
    # Create a legal draft order
    order_id = _create_legal_draft(requester, initial_reviewer)

    # Capture pre-request state
    pre_state = _get_order_row(order_id)

    # PUT: try to set initial_reviewer to the requester (self-review)
    status_code, detail = _invoke_update(
        order_id,
        {"assigned_initial_reviewer_id": requester["user_id"]},
        actor=requester,
    )

    # Fixed expectation: HTTP 400
    assert status_code == 400, (
        f"Bug_Condition C3(b) surfaced: PUT with "
        f"assigned_initial_reviewer_id=requester_id → HTTP {status_code} "
        f"(expected 400 after fix). Detail: {detail!r}"
    )

    # Persistence delta: row must be unchanged
    post_state = _get_order_row(order_id)
    assert pre_state == post_state, (
        "Persistence delta violated: order row changed despite expected rejection"
    )


def test_p3b_put_reviewer_equals_approver_rejected(
    isolated_db, requester, initial_reviewer, final_approver
):
    """
    **Validates: Property 3** — PUT /change-orders/{id} with
    assigned_initial_reviewer_id == assigned_final_approver_id MUST
    return HTTP 400.

    On unfixed code: PUT path has no dedup check → HTTP 200 (bug exists).
    Persistence delta: order row must be byte-identical to pre-request state.
    """
    # Create a legal draft order with both reviewer and approver set
    status_code, data = _invoke_create(
        {
            "status": "draft",
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
            "assigned_final_approver_id": final_approver["user_id"],
        },
        actor=requester,
    )
    assert status_code == 200, f"Setup failed: {data}"
    order_id = data["id"]

    # Capture pre-request state
    pre_state = _get_order_row(order_id)

    # PUT: try to set initial_reviewer to the same person as final_approver
    # We need a user who is in both groups — use final_approver (Administrator)
    status_code, detail = _invoke_update(
        order_id,
        {"assigned_initial_reviewer_id": final_approver["user_id"]},
        actor=requester,
    )

    # Fixed expectation: HTTP 400 (reviewer == approver)
    assert status_code == 400, (
        f"Bug_Condition C3(b) surfaced: PUT with "
        f"assigned_initial_reviewer_id == assigned_final_approver_id → "
        f"HTTP {status_code} (expected 400 after fix). Detail: {detail!r}"
    )

    # Persistence delta: row must be unchanged
    post_state = _get_order_row(order_id)
    assert pre_state == post_state, (
        "Persistence delta violated: order row changed despite expected rejection"
    )


# ─────────────────────────────────────────────────────────────────────
# Sub-property (c): Transition hijack of final approver
#
# Bug: api_transition_change_order when new_status='final_review' and
# body.assigned_final_approver_id is present, only does:
#   SELECT username FROM users WHERE id = ?
# It does NOT call _resolve_assignment_user, so:
#   - requester can be set as final_approver
#   - initial_reviewer can be set as final_approver
#   - Operator-role user outside final_approver group can be set
# ─────────────────────────────────────────────────────────────────────

def test_p3c_transition_final_approver_is_requester_rejected(
    isolated_db, requester, initial_reviewer, final_approver
):
    """
    **Validates: Property 3** — POST /transition to final_review with
    body.assigned_final_approver_id = requester_id MUST return HTTP 400
    and order state MUST NOT change.

    On unfixed code: transition path accepts any valid user_id as
    final_approver → HTTP 200 (bug exists).
    """
    # Create order in initial_review
    order_id = _create_legal_order_in_initial_review(
        requester, initial_reviewer, final_approver
    )

    # Capture pre-request state
    pre_state = _get_order_row(order_id)

    # Transition: initial_reviewer moves to final_review, setting
    # final_approver = requester (the person who created the order)
    status_code, detail = _invoke_transition(
        order_id,
        "final_review",
        actor=initial_reviewer,
        extra_body={"assigned_final_approver_id": requester["user_id"]},
    )

    # Fixed expectation: HTTP 400 (final_approver cannot be requester)
    assert status_code == 400, (
        f"Bug_Condition C3(c) surfaced: transition to final_review with "
        f"assigned_final_approver_id=requester_id → HTTP {status_code} "
        f"(expected 400 after fix). Detail: {detail!r}"
    )

    # Persistence delta: order state must not change
    post_state = _get_order_row(order_id)
    assert pre_state == post_state, (
        "Persistence delta violated: order state changed despite expected rejection. "
        f"Pre: status={pre_state.get('status')}, Post: status={post_state.get('status')}"
    )


def test_p3c_transition_final_approver_is_initial_reviewer_rejected(
    isolated_db, requester, initial_reviewer, final_approver
):
    """
    **Validates: Property 3** — POST /transition to final_review with
    body.assigned_final_approver_id = current initial_reviewer_id MUST
    return HTTP 400 and order state MUST NOT change.

    On unfixed code: transition path accepts any valid user_id →
    HTTP 200 (bug exists).
    """
    # Create order in initial_review
    order_id = _create_legal_order_in_initial_review(
        requester, initial_reviewer, final_approver
    )

    # Capture pre-request state
    pre_state = _get_order_row(order_id)

    # Transition: initial_reviewer moves to final_review, setting
    # final_approver = themselves (the initial_reviewer)
    status_code, detail = _invoke_transition(
        order_id,
        "final_review",
        actor=initial_reviewer,
        extra_body={"assigned_final_approver_id": initial_reviewer["user_id"]},
    )

    # Fixed expectation: HTTP 400 (initial_reviewer == final_approver)
    assert status_code == 400, (
        f"Bug_Condition C3(c) surfaced: transition to final_review with "
        f"assigned_final_approver_id=initial_reviewer_id → HTTP {status_code} "
        f"(expected 400 after fix). Detail: {detail!r}"
    )

    # Persistence delta: order state must not change
    post_state = _get_order_row(order_id)
    assert pre_state == post_state, (
        "Persistence delta violated: order state changed despite expected rejection. "
        f"Pre: status={pre_state.get('status')}, Post: status={post_state.get('status')}"
    )


def test_p3c_transition_final_approver_outside_group_rejected(
    isolated_db, requester, initial_reviewer, final_approver, make_user
):
    """
    **Validates: Property 3** — POST /transition to final_review with
    body.assigned_final_approver_id = Operator-role user outside
    final_approver group MUST return HTTP 400 and order state MUST NOT
    change.

    On unfixed code: transition path only checks user exists via
    SELECT username → HTTP 200 (bug exists).
    """
    # Create an Operator who is NOT in the final_approver group
    outsider = make_user(
        "outsider_operator",
        role="Operator",
        change_groups=["initial_reviewer"],  # NOT in final_approver group
    )

    # Create order in initial_review
    order_id = _create_legal_order_in_initial_review(
        requester, initial_reviewer, final_approver
    )

    # Capture pre-request state
    pre_state = _get_order_row(order_id)

    # Transition: initial_reviewer moves to final_review, setting
    # final_approver = outsider (Operator, not in final_approver group)
    status_code, detail = _invoke_transition(
        order_id,
        "final_review",
        actor=initial_reviewer,
        extra_body={"assigned_final_approver_id": outsider["user_id"]},
    )

    # Fixed expectation: HTTP 400 (user not in final_approver group)
    assert status_code == 400, (
        f"Bug_Condition C3(c) surfaced: transition to final_review with "
        f"assigned_final_approver_id=Operator outside final_approver group → "
        f"HTTP {status_code} (expected 400 after fix). Detail: {detail!r}"
    )

    # Persistence delta: order state must not change
    post_state = _get_order_row(order_id)
    assert pre_state == post_state, (
        "Persistence delta violated: order state changed despite expected rejection. "
        f"Pre: status={pre_state.get('status')}, Post: status={post_state.get('status')}"
    )


# ─────────────────────────────────────────────────────────────────────
# PBT: Combined property covering all three sub-properties
# ─────────────────────────────────────────────────────────────────────

# Strategy for the bypass vector to test
_BYPASS_VECTORS = [
    "post_empty_groups",
    "put_reviewer_eq_requester",
    "put_reviewer_eq_approver",
    "transition_approver_eq_requester",
    "transition_approver_eq_reviewer",
    "transition_approver_outside_group",
]


@given(vector=st.sampled_from(_BYPASS_VECTORS))
@settings(
    max_examples=24,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p3_combined_all_bypass_vectors_rejected(
    vector, isolated_db, requester, initial_reviewer, final_approver, make_user
):
    """
    **Validates: Property 3** — Combined PBT covering all bypass vectors.
    For each vector, the fixed code MUST return HTTP 400.

    On unfixed code: at least one vector succeeds → XFAIL (bug exists).
    """
    if vector == "post_empty_groups":
        # User with empty change_groups as reviewer
        empty_user = make_user(
            "pbt_empty_groups", role="Operator", change_groups=[]
        )
        status_code, detail = _invoke_create(
            {
                "status": "draft",
                "assigned_initial_reviewer_id": empty_user["user_id"],
            },
            actor=requester,
        )

    elif vector == "put_reviewer_eq_requester":
        # PUT: set reviewer = requester
        order_id = _create_legal_draft(requester, initial_reviewer)
        status_code, detail = _invoke_update(
            order_id,
            {"assigned_initial_reviewer_id": requester["user_id"]},
            actor=requester,
        )

    elif vector == "put_reviewer_eq_approver":
        # PUT: set reviewer = final_approver (same person for both roles)
        sc, data = _invoke_create(
            {
                "status": "draft",
                "assigned_initial_reviewer_id": initial_reviewer["user_id"],
                "assigned_final_approver_id": final_approver["user_id"],
            },
            actor=requester,
        )
        assert sc == 200, f"Setup failed: {data}"
        order_id = data["id"]
        status_code, detail = _invoke_update(
            order_id,
            {"assigned_initial_reviewer_id": final_approver["user_id"]},
            actor=requester,
        )

    elif vector == "transition_approver_eq_requester":
        # Transition: final_approver = requester
        order_id = _create_legal_order_in_initial_review(
            requester, initial_reviewer, final_approver
        )
        status_code, detail = _invoke_transition(
            order_id,
            "final_review",
            actor=initial_reviewer,
            extra_body={"assigned_final_approver_id": requester["user_id"]},
        )

    elif vector == "transition_approver_eq_reviewer":
        # Transition: final_approver = initial_reviewer
        order_id = _create_legal_order_in_initial_review(
            requester, initial_reviewer, final_approver
        )
        status_code, detail = _invoke_transition(
            order_id,
            "final_review",
            actor=initial_reviewer,
            extra_body={"assigned_final_approver_id": initial_reviewer["user_id"]},
        )

    elif vector == "transition_approver_outside_group":
        # Transition: final_approver = Operator not in final_approver group
        outsider = make_user(
            "pbt_outsider", role="Operator", change_groups=["initial_reviewer"]
        )
        order_id = _create_legal_order_in_initial_review(
            requester, initial_reviewer, final_approver
        )
        status_code, detail = _invoke_transition(
            order_id,
            "final_review",
            actor=initial_reviewer,
            extra_body={"assigned_final_approver_id": outsider["user_id"]},
        )

    else:
        pytest.fail(f"Unknown vector: {vector}")

    assert status_code == 400, (
        f"Bug_Condition C3 surfaced via vector={vector!r}: "
        f"HTTP {status_code} (expected 400 after fix). Detail: {detail!r}"
    )
