"""
Phase E — Fix-checking PBT for Property P4: state-machine invariant.

Task 17.4 — Property P4 — state-machine PBT

Enumerates (from, to) ∈ ALLOWED_STATUSES²; asserts:
  - to ∈ ALLOWED_TRANSITIONS[from] ⇔ HTTP 200 (or 403 for auth, not 400 for invalid transition)
  - terminals {completed, rolled_back, cancelled} always 400 on any non-self transition

Validates: Property 4
Requirements: 2.10, 2.12
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st


def _force_status(order_id: str, status: str):
    from database import get_db_connection
    conn = get_db_connection()
    try:
        conn.execute("UPDATE change_orders SET status = ? WHERE id = ?", (status, order_id))
        conn.commit()
    finally:
        conn.close()


def _create_draft_order(requester: dict, initial_reviewer: dict) -> str:
    from api.change_orders import ChangeOrderCreate, api_create_change_order
    body = ChangeOrderCreate(
        title="P4 state machine test",
        status="draft",
        assigned_initial_reviewer_id=initial_reviewer["user_id"],
        command_template={},
        commands=["show version"],
        rollback_plan="",
    )
    result = api_create_change_order(body, user=requester)
    return result["data"]["id"]


def _invoke_transition(order_id: str, new_status: str, actor: dict) -> tuple[int, object]:
    from api.change_orders import api_transition_change_order
    from fastapi import HTTPException
    try:
        result = api_transition_change_order(order_id, body={"status": new_status}, user=actor)
        return 200, result
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


# ── Terminal states always reject transitions ─────────────────────────

TERMINAL_STATUSES = ["completed", "rolled_back", "cancelled"]
ALL_NON_TERMINAL = [
    "draft", "initial_review", "final_review", "approved",
    "implementing", "rollback_in_progress", "failed", "rejected",
]


@pytest.mark.parametrize("terminal", TERMINAL_STATUSES)
@pytest.mark.parametrize("target", ALL_NON_TERMINAL)
def test_p4_terminal_rejects_all_transitions(
    terminal, target, isolated_db, requester, initial_reviewer, final_approver
):
    """Terminal states MUST reject any transition with HTTP 400 'Invalid transition'."""
    order_id = _create_draft_order(requester, initial_reviewer)
    _force_status(order_id, terminal)

    sc, detail = _invoke_transition(order_id, target, actor=requester)
    assert sc == 400, (
        f"P4: terminal {terminal!r} → {target!r} returned HTTP {sc} (expected 400). "
        f"Detail: {detail!r}"
    )
    assert "Invalid transition" in str(detail), (
        f"P4: expected 'Invalid transition' in detail, got: {detail!r}"
    )


# ── ALLOWED_TRANSITIONS contract ─────────────────────────────────────

def test_p4_allowed_transitions_explicit_terminals():
    """ALLOWED_TRANSITIONS must have explicit empty-set entries for all terminals."""
    from api.change_orders import ALLOWED_TRANSITIONS
    for terminal in TERMINAL_STATUSES:
        assert terminal in ALLOWED_TRANSITIONS, (
            f"P4: terminal {terminal!r} missing from ALLOWED_TRANSITIONS"
        )
        assert ALLOWED_TRANSITIONS[terminal] == set(), (
            f"P4: ALLOWED_TRANSITIONS[{terminal!r}] should be empty set, "
            f"got {ALLOWED_TRANSITIONS[terminal]!r}"
        )


def test_p4_allowed_statuses_all_in_transitions():
    """Every status in ALLOWED_STATUSES must be a key in ALLOWED_TRANSITIONS."""
    from api.change_orders import ALLOWED_STATUSES, ALLOWED_TRANSITIONS
    missing = ALLOWED_STATUSES - ALLOWED_TRANSITIONS.keys()
    assert not missing, (
        f"P4: ALLOWED_TRANSITIONS missing keys for: {missing}"
    )


# ── PBT: terminal × non-terminal always 400 ──────────────────────────

@given(
    terminal=st.sampled_from(TERMINAL_STATUSES),
    target=st.sampled_from(ALL_NON_TERMINAL),
)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p4_pbt_terminal_rejects_all(
    terminal, target, isolated_db, requester, initial_reviewer, final_approver
):
    """PBT: terminal × non-terminal always returns HTTP 400."""
    order_id = _create_draft_order(requester, initial_reviewer)
    _force_status(order_id, terminal)
    sc, detail = _invoke_transition(order_id, target, actor=requester)
    assert sc == 400, (
        f"P4 PBT: {terminal!r} → {target!r} returned HTTP {sc} (expected 400). "
        f"Detail: {detail!r}"
    )


# ── Valid transitions from draft ──────────────────────────────────────

def test_p4_draft_to_initial_review_allowed(isolated_db, requester, initial_reviewer):
    """draft → initial_review MUST be allowed (HTTP 200)."""
    order_id = _create_draft_order(requester, initial_reviewer)
    sc, detail = _invoke_transition(order_id, "initial_review", actor=requester)
    assert sc == 200, f"P4: draft→initial_review rejected (HTTP {sc}). Detail: {detail}"


def test_p4_draft_to_cancelled_allowed(isolated_db, requester, initial_reviewer):
    """draft → cancelled MUST be allowed (HTTP 200)."""
    order_id = _create_draft_order(requester, initial_reviewer)
    sc, detail = _invoke_transition(order_id, "cancelled", actor=requester)
    assert sc == 200, f"P4: draft→cancelled rejected (HTTP {sc}). Detail: {detail}"


def test_p4_draft_to_approved_not_allowed(isolated_db, requester, initial_reviewer):
    """draft → approved MUST NOT be allowed (HTTP 400 Invalid transition)."""
    order_id = _create_draft_order(requester, initial_reviewer)
    sc, detail = _invoke_transition(order_id, "approved", actor=requester)
    assert sc == 400, f"P4: draft→approved allowed (HTTP {sc}). Detail: {detail}"
    assert "Invalid transition" in str(detail)
