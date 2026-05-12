"""
Phase A — Exploration test for cluster 1.2 (control sheet missing).

**Property 1: Bug Condition** — Control-sheet-less order accepted through
`initial_review` / `implementing` on unfixed code.

Per the spec front-matter of `tasks.md`:
    "Tests that need to fail on unfixed code are marked xfail(strict=True)
     → flip to strict-pass after the fix lands."

The xfail-marked assertions below encode the *fixed* expectation:
  - HTTP 400 on submission that lacks `control_sheet.*` required fields
  - HTTP 400 on transition → `implementing` when
    `change_order_control_sheet_attachments` is empty
  - GET /change-orders/{id} on a historical completed order returns
    `control_sheet_missing: true` banner without crashing

On UNFIXED code the assertions fail → pytest reports XFAIL → exploration
SUCCESS (the bug exists). On FIXED code (after task 15.x) the assertions
pass → pytest reports XPASS-strict → we remove the xfail marker.

Validates: Property 2 (design.md §Correctness Properties)
Bug_Condition: `C2(input)` in `design.md §Bug Details`
Requirements: 1.4, 1.5, 1.6 (bugfix.md)
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings, strategies as st


# ── Statuses where control_sheet should be required ──────────────────
_NON_DRAFT_STATUSES = [
    "initial_review",
    "final_review",
    "approved",
    "implementing",
    "completed",
    "rolled_back",
]


def _non_draft_status_strategy():
    """Strategy for target statuses that require control_sheet fields."""
    return st.sampled_from(_NON_DRAFT_STATUSES)


# ── Helper: invoke create handler in-process ─────────────────────────
def _invoke_create(body_payload: dict, actor: dict) -> tuple[int, object]:
    """Return `(status_code, result_or_detail)`.  200 on success, the
    HTTPException `status_code` and `detail` on failure."""
    from api.change_orders import ChangeOrderCreate, api_create_change_order

    body_payload.setdefault("title", "Control sheet exploration test")
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


def _invoke_get(order_id: str, actor: dict) -> tuple[int, object]:
    """Return `(status_code, result_or_detail)` for GET /change-orders/{id}."""
    from api.change_orders import api_get_change_order

    try:
        result = api_get_change_order(order_id, user=actor)
        data = result.get("data") if isinstance(result, dict) else result
        return 200, data
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


# ── Helper: create a valid order in draft (bypasses template enforcement
#    since status='draft' does not require command_template) ──────────
def _create_draft_order(requester: dict, initial_reviewer: dict) -> dict:
    """Create a draft order that can be transitioned through the lifecycle."""
    status_code, data = _invoke_create(
        {
            "status": "draft",
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
            "command_template": {},
            "commands": ["show version"],
        },
        actor=requester,
    )
    assert status_code == 200, f"Draft creation failed: {data}"
    return data


# ─────────────────────────────────────────────────────────────────────
# Property P2 — PBT: no control_sheet field → should be rejected at
# non-draft submission (fixed expectation)
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Bug_Condition C2: on unfixed code, POST /api/change-orders with "
        "no control_sheet field and status != 'draft' is silently accepted "
        "(HTTP 200) because ChangeOrderCreate has no control_sheet field "
        "and no validation exists. Task 15.1/15.3 adds the field and "
        "enforcement → this test should flip to strict-pass."
    ),
)
@given(target_status=_non_draft_status_strategy())
@settings(
    max_examples=24,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p2_no_control_sheet_rejected_at_non_draft(
    target_status, isolated_db, requester, initial_reviewer, final_approver
):
    """
    **Validates: Property 2** — ∀ `status ∈ NON_DRAFT_STATUSES`,
    `POST /api/change-orders` without `control_sheet` structured fields
    MUST return HTTP 400.

    On unfixed code: the request succeeds (HTTP 200) because the schema
    does not expose `control_sheet` at all. Hypothesis will find this
    immediately.
    """
    payload = {
        "status": target_status,
        "assigned_initial_reviewer_id": initial_reviewer["user_id"],
        "command_template": {},
        "commands": ["show version"],
        # NOTE: No control_sheet field — this is the bug condition
    }

    status_code, _ = _invoke_create(payload, actor=requester)

    assert status_code == 400, (
        f"Bug_Condition C2 surfaced: no control_sheet field, "
        f"status={target_status!r} → HTTP {status_code} (expected 400 after fix)."
    )


# ─────────────────────────────────────────────────────────────────────
# Deterministic counterexample: submit to initial_review without
# control_sheet
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.xfail(
    strict=True,
    reason=(
        "C2 branch A: order submitted to initial_review without any "
        "control_sheet fields is accepted on unfixed code. Task 15.3 fix "
        "expected to return HTTP 400."
    ),
)
def test_c2_no_control_sheet_at_initial_review(
    isolated_db, requester, initial_reviewer
):
    """Shortest counterexample: create order with status='initial_review',
    no control_sheet → should be HTTP 400 after fix."""
    status_code, _ = _invoke_create(
        {
            "status": "initial_review",
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
            "command_template": {},
            "commands": ["show version"],
            # No control_sheet
        },
        actor=requester,
    )
    assert status_code == 400, (
        f"Bug C2: order accepted at initial_review without control_sheet "
        f"(HTTP {status_code})"
    )


# ─────────────────────────────────────────────────────────────────────
# Transition to implementing without control_sheet attachments
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.xfail(
    strict=True,
    reason=(
        "C2 branch B: transition to 'implementing' without any "
        "change_order_control_sheet_attachments is accepted on unfixed code. "
        "Task 15.3 fix expected to return HTTP 400 when attachments are empty."
    ),
)
def test_c2_transition_to_implementing_without_attachments(
    isolated_db, requester, initial_reviewer, final_approver
):
    """
    Drive a full lifecycle: draft → initial_review → final_review →
    approved → implementing, all without uploading any control sheet
    attachment. The transition to 'implementing' MUST be rejected (HTTP 400)
    after the fix because `change_order_control_sheet_attachments` is empty.

    On unfixed code: the transition succeeds (HTTP 200) because no
    attachment table or check exists.
    """
    # 1. Create draft order
    order = _create_draft_order(requester, initial_reviewer)
    order_id = order["id"]

    # 2. Transition draft → initial_review
    sc, data = _invoke_transition(order_id, "initial_review", actor=requester)
    assert sc == 200, f"draft→initial_review failed: {data}"

    # 3. Transition initial_review → final_review (by initial_reviewer)
    sc, data = _invoke_transition(
        order_id, "final_review", actor=initial_reviewer,
        extra_body={"assigned_final_approver_id": final_approver["user_id"]},
    )
    assert sc == 200, f"initial_review→final_review failed: {data}"

    # 4. Transition final_review → approved (by final_approver, Administrator)
    sc, data = _invoke_transition(order_id, "approved", actor=final_approver)
    assert sc == 200, f"final_review→approved failed: {data}"

    # 5. Transition approved → implementing (by requester)
    #    This SHOULD fail because no control_sheet attachments exist
    sc, data = _invoke_transition(order_id, "implementing", actor=requester)

    assert sc == 400, (
        f"Bug C2: transition to 'implementing' accepted without any "
        f"control_sheet attachments (HTTP {sc}). Expected HTTP 400 after fix."
    )


# ─────────────────────────────────────────────────────────────────────
# GET on historical completed order: control_sheet_missing banner
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.xfail(
    strict=True,
    reason=(
        "C2 branch C: GET /change-orders/{id} on a completed order that "
        "has no control_sheet should return control_sheet_missing=true "
        "banner field. On unfixed code this field does not exist."
    ),
)
def test_c2_get_completed_order_shows_control_sheet_missing_banner(
    isolated_db, requester, initial_reviewer, final_approver
):
    """
    After an order reaches 'completed' without any control_sheet data
    (simulating a historical row), GET /change-orders/{id} MUST still
    return the order successfully AND include a `control_sheet_missing: true`
    banner field so the UI can display a warning.

    On unfixed code: the field simply does not exist in the response.
    """
    # Create and drive order to completed (no control_sheet at any step)
    order = _create_draft_order(requester, initial_reviewer)
    order_id = order["id"]

    # Drive through lifecycle
    sc, _ = _invoke_transition(order_id, "initial_review", actor=requester)
    assert sc == 200
    sc, _ = _invoke_transition(
        order_id, "final_review", actor=initial_reviewer,
        extra_body={"assigned_final_approver_id": final_approver["user_id"]},
    )
    assert sc == 200
    sc, _ = _invoke_transition(order_id, "approved", actor=final_approver)
    assert sc == 200
    sc, _ = _invoke_transition(order_id, "implementing", actor=requester)
    assert sc == 200
    sc, _ = _invoke_transition(order_id, "completed", actor=requester)
    assert sc == 200

    # Now GET the completed order
    sc, data = _invoke_get(order_id, actor=requester)
    assert sc == 200, f"GET on completed order failed: {data}"

    # Fixed expectation: response includes control_sheet_missing banner
    assert data.get("control_sheet_missing") is True, (
        f"Bug C2: GET on completed order without control_sheet does not "
        f"include 'control_sheet_missing: true' banner. Got keys: "
        f"{list(data.keys()) if isinstance(data, dict) else type(data)}"
    )


# ─────────────────────────────────────────────────────────────────────
# PBT: transition to implementing always succeeds without attachment
# check (proves the bug across random lifecycle paths)
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.xfail(
    strict=True,
    reason=(
        "C2 PBT: on unfixed code, the full lifecycle from draft to "
        "implementing succeeds without any control_sheet or attachment "
        "enforcement. Task 15.3 adds the check."
    ),
)
@settings(
    max_examples=8,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p2_lifecycle_no_control_sheet_enforcement(
    isolated_db, requester, initial_reviewer, final_approver
):
    """
    **Validates: Property 2** — Drive an order through the full lifecycle
    without ever providing control_sheet fields or uploading attachments.
    The fixed code MUST reject at some point (either at submission to
    initial_review or at transition to implementing).

    On unfixed code: the entire lifecycle completes successfully, proving
    the bug exists.
    """
    # Create draft
    order = _create_draft_order(requester, initial_reviewer)
    order_id = order["id"]

    # Track whether any step rejected due to missing control_sheet
    rejected_for_control_sheet = False

    # Try to drive through full lifecycle
    transitions = [
        ("initial_review", requester, {}),
        ("final_review", initial_reviewer,
         {"assigned_final_approver_id": final_approver["user_id"]}),
        ("approved", final_approver, {}),
        ("implementing", requester, {}),
    ]

    for target_status, actor, extra in transitions:
        sc, data = _invoke_transition(order_id, target_status, actor=actor,
                                      extra_body=extra if extra else None)
        if sc == 400 and "control_sheet" in str(data).lower():
            rejected_for_control_sheet = True
            break
        # If it fails for other reasons, that's fine — we just need to
        # verify control_sheet enforcement exists somewhere
        if sc != 200:
            break

    assert rejected_for_control_sheet, (
        "Bug C2: entire lifecycle from draft to implementing completed "
        "without any control_sheet enforcement. Expected at least one "
        "transition to reject due to missing control_sheet fields or "
        "attachments."
    )
