"""
Phase A — Exploration test for cluster 1.4 (state machine + reject reset).

**Property 1: Bug Condition** — Terminal-state transition permissive + stale
reviewer/approver after reject→draft.

Per the spec front-matter of `tasks.md`:
    "Tests that need to fail on unfixed code are marked xfail(strict=True)
     → flip to strict-pass after the fix lands."

Two sub-properties:
  (a) Terminal-state transitions: orders in `completed` / `rolled_back` /
      `cancelled` attempting transition to any other status → must 400
      "Invalid transition". On unfixed code this MAY pass (via .get fallback)
      but is brittle — lock it in as explicit contract WITHOUT xfail.
  (b) Reject→draft stale fields: order reaching `initial_review` → `rejected`
      → `draft` (or `final_review` → `rejected` → `draft`) with non-empty
      reviewer/approver fields → after the →draft transition, all six fields
      must be cleared. On UNFIXED code this FAILS (stale fields retained).
      Marked xfail(strict=True).

Validates: Properties 4 and 5 (design.md §Correctness Properties)
Bug_Condition: `C4(input)` in `design.md §Bug Details`
Requirements: 1.10, 1.11, 1.12 (bugfix.md)
"""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings, strategies as st, assume


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


# ── DB Setup: ensure change_orders table exists even if init_db fails ──

def _ensure_change_orders_table(db_module):
    """
    Ensure the change_orders table and related tables exist.
    init_db() may fail partway through due to unrelated issues
    (e.g., inspection_items INSERT mismatch), rolling back the entire
    transaction including change_orders CREATE TABLE. This helper
    creates the minimum schema needed for these tests.
    """
    conn = db_module.get_db_connection()
    try:
        # Check if change_orders table exists
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='change_orders'"
        ).fetchone()
        if row:
            conn.close()
            return  # Table already exists

        conn.execute('''
        CREATE TABLE IF NOT EXISTS change_orders (
            id TEXT PRIMARY KEY,
            order_number TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            order_type TEXT NOT NULL DEFAULT 'config_change',
            priority TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'draft',
            requester_id TEXT DEFAULT '',
            requester_username TEXT DEFAULT '',
            approver_id TEXT DEFAULT '',
            approver_username TEXT DEFAULT '',
            target_devices_json TEXT DEFAULT '[]',
            commands_json TEXT DEFAULT '[]',
            rollback_plan TEXT DEFAULT '',
            risk_level TEXT DEFAULT 'low',
            scheduled_start TEXT DEFAULT '',
            scheduled_end TEXT DEFAULT '',
            authorization_exempt INTEGER NOT NULL DEFAULT 0,
            actual_start TEXT DEFAULT '',
            actual_end TEXT DEFAULT '',
            result_summary TEXT DEFAULT '',
            result_detail_json TEXT DEFAULT '{}',
            approval_token TEXT DEFAULT '',
            rejected_reason TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            initial_reviewer_id TEXT DEFAULT '',
            initial_reviewer_username TEXT DEFAULT '',
            final_approver_id TEXT DEFAULT '',
            final_approver_username TEXT DEFAULT '',
            assigned_initial_reviewer_id TEXT DEFAULT '',
            assigned_initial_reviewer_username TEXT DEFAULT '',
            assigned_final_approver_id TEXT DEFAULT '',
            assigned_final_approver_username TEXT DEFAULT '',
            command_template_json TEXT DEFAULT '{}'
        )
        ''')
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_change_orders_status '
            'ON change_orders(status)'
        )
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_change_orders_order_number '
            'ON change_orders(order_number)'
        )
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_change_orders_requester '
            'ON change_orders(requester_username)'
        )
        conn.execute('''
        CREATE TABLE IF NOT EXISTS change_order_bookmarks (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            order_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, order_id)
        )
        ''')
        conn.execute('''
        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL DEFAULT '',
            category TEXT DEFAULT '',
            severity TEXT DEFAULT 'info',
            status TEXT DEFAULT 'open',
            summary TEXT DEFAULT '',
            actor_id TEXT DEFAULT '',
            actor_username TEXT DEFAULT '',
            actor_role TEXT DEFAULT '',
            target_type TEXT DEFAULT '',
            target_id TEXT DEFAULT '',
            target_name TEXT DEFAULT '',
            details_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT '',
            resolved_at TEXT DEFAULT '',
            resolved_by TEXT DEFAULT ''
        )
        ''')
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _ensure_tables(isolated_db):
    """Auto-use fixture to ensure change_orders table exists for all tests."""
    _ensure_change_orders_table(isolated_db["module"])


# ── Helpers: invoke handlers in-process, bypass HTTP/middleware ───────

def _invoke_create(body_payload: dict, actor: dict) -> tuple[int, object]:
    """Return `(status_code, result_or_detail)`.  200 on success, the
    HTTPException `status_code` and `detail` on failure."""
    from api.change_orders import ChangeOrderCreate, api_create_change_order

    body_payload.setdefault("title", "Cluster 1.4 exploration test")
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


def _force_status(order_id: str, status: str, extra_fields: dict | None = None):
    """Directly update the order status in DB (bypass transition logic)."""
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
        conn.execute(
            f"UPDATE change_orders SET {', '.join(parts)} WHERE id = ?",
            values,
        )
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────
# Sub-property (a): Terminal-state transitions must be rejected
#
# ALLOWED_TRANSITIONS on unfixed code does NOT have explicit entries for
# 'completed', 'rolled_back', 'cancelled'. It relies on
# ALLOWED_TRANSITIONS.get(current_status, set()) returning empty set.
# This behavior is CORRECT but implicit — we lock it in as explicit
# contract. These tests should PASS on unfixed code (no xfail).
# ─────────────────────────────────────────────────────────────────────

TERMINAL_STATUSES = ["completed", "rolled_back", "cancelled"]

# All statuses that could be attempted as targets
ALL_TARGET_STATUSES = [
    "draft", "initial_review", "final_review", "approved",
    "implementing", "completed", "rollback_in_progress",
    "rolled_back", "rejected", "failed", "cancelled",
]


@given(
    terminal_status=st.sampled_from(TERMINAL_STATUSES),
    target_status=st.sampled_from(ALL_TARGET_STATUSES),
)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p4_terminal_state_rejects_all_transitions(
    terminal_status, target_status, isolated_db, requester, initial_reviewer
):
    """
    **Validates: Property 4** — For terminal states {completed, rolled_back,
    cancelled}, any transition to another status MUST return HTTP 400
    "Invalid transition".

    On unfixed code: ALLOWED_TRANSITIONS.get(terminal_status, set()) returns
    empty set, so transitions are rejected. This test locks in the behavior
    as an explicit contract. Should PASS on unfixed code.

    **Validates: Requirements 1.12**
    """
    # Skip self-transitions (e.g., completed → completed) — they are also
    # invalid but let's keep the assertion uniform
    assume(target_status != terminal_status)

    # Create a draft order
    status_code, data = _invoke_create(
        {
            "status": "draft",
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
        },
        actor=requester,
    )
    assert status_code == 200, f"Setup failed: {data}"
    order_id = data["id"]

    # Force the order into the terminal state directly via DB
    _force_status(order_id, terminal_status)

    # Capture pre-request state
    pre_state = _get_order_row(order_id)

    # Attempt transition — should be rejected
    # Use requester as actor (Administrator role would also be rejected for
    # terminal states since there's no valid transition)
    status_code, detail = _invoke_transition(
        order_id, target_status, actor=requester
    )

    assert status_code == 400, (
        f"Terminal-state contract violation: {terminal_status} → {target_status} "
        f"returned HTTP {status_code} (expected 400). Detail: {detail!r}"
    )
    assert "Invalid transition" in str(detail), (
        f"Expected 'Invalid transition' in error detail, got: {detail!r}"
    )

    # Persistence delta: order row must be unchanged
    post_state = _get_order_row(order_id)
    assert pre_state == post_state, (
        f"Persistence delta violated: order row changed after rejected "
        f"terminal-state transition {terminal_status} → {target_status}"
    )


# ─────────────────────────────────────────────────────────────────────
# Sub-property (b): Reject→draft must clear stale reviewer/approver fields
#
# Bug: api_transition_change_order when transitioning rejected → draft
# only updates `status` but does NOT clear:
#   - initial_reviewer_id / initial_reviewer_username
#   - final_approver_id / final_approver_username
#   - approver_id / approver_username
#   - result_detail.initial_review_at / result_detail.approved_at
#
# These tests are marked xfail(strict=True) because they encode the
# FIXED expectation and should FAIL on unfixed code.
# ─────────────────────────────────────────────────────────────────────

def test_p5_reject_from_initial_review_clears_reviewer_fields(
    isolated_db, requester, initial_reviewer, final_approver
):
    """
    **Validates: Property 5** — After reject→draft from initial_review,
    all six reviewer/approver fields and two timestamps must be cleared.

    On unfixed code: fields are retained after reject→draft → XFAIL
    (bug exists).

    **Validates: Requirements 1.11**
    """
    # Create a draft order with assigned reviewer
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

    # Use _force_status to bypass template enforcement (task 14.1) and
    # directly set the order to initial_review with reviewer fields populated.
    # This isolates the test to Property 5 (reject→draft cleanup) only.
    _force_status(order_id, "initial_review", extra_fields={
        "initial_reviewer_id": initial_reviewer["user_id"],
        "initial_reviewer_username": initial_reviewer["username"],
        "result_detail_json": json.dumps({"initial_review_at": _utc_now_iso()}),
    })

    # Initial reviewer rejects → rejected
    status_code, _ = _invoke_transition(
        order_id, "rejected", actor=initial_reviewer,
        extra_body={"rejected_reason": "needs rework"},
    )
    assert status_code == 200, "Setup: could not transition to rejected"

    # Verify the order now has reviewer fields populated
    row_before_draft = _get_order_row(order_id)
    assert row_before_draft["status"] == "rejected"
    # The initial_reviewer fields should be populated from the review step
    assert row_before_draft.get("initial_reviewer_username") or \
           row_before_draft.get("initial_reviewer_id"), \
        "Setup: expected initial_reviewer fields to be populated after review"

    # Requester reopens: rejected → draft
    status_code, _ = _invoke_transition(
        order_id, "draft", actor=requester
    )
    assert status_code == 200, "Could not transition rejected → draft"

    # Re-read the order after transition to draft
    row_after_draft = _get_order_row(order_id)
    assert row_after_draft["status"] == "draft"

    # Assert all six fields are cleared (Property 5)
    assert row_after_draft.get("initial_reviewer_id", "") == "", (
        f"Bug_Condition C4(b): after reject→draft, initial_reviewer_id "
        f"still carries '{row_after_draft.get('initial_reviewer_id')}'"
    )
    assert row_after_draft.get("initial_reviewer_username", "") == "", (
        f"Bug_Condition C4(b): after reject→draft, initial_reviewer_username "
        f"still carries '{row_after_draft.get('initial_reviewer_username')}'"
    )
    assert row_after_draft.get("final_approver_id", "") == "", (
        f"Bug_Condition C4(b): after reject→draft, final_approver_id "
        f"still carries '{row_after_draft.get('final_approver_id')}'"
    )
    assert row_after_draft.get("final_approver_username", "") == "", (
        f"Bug_Condition C4(b): after reject→draft, final_approver_username "
        f"still carries '{row_after_draft.get('final_approver_username')}'"
    )
    assert row_after_draft.get("approver_id", "") == "", (
        f"Bug_Condition C4(b): after reject→draft, approver_id "
        f"still carries '{row_after_draft.get('approver_id')}'"
    )
    assert row_after_draft.get("approver_username", "") == "", (
        f"Bug_Condition C4(b): after reject→draft, approver_username "
        f"still carries '{row_after_draft.get('approver_username')}'"
    )

    # Assert timestamps are cleared from result_detail
    result_detail_raw = row_after_draft.get("result_detail_json", "{}")
    result_detail = json.loads(result_detail_raw) if result_detail_raw else {}
    assert "initial_review_at" not in result_detail, (
        f"Bug_Condition C4(b): after reject→draft, result_detail still "
        f"contains initial_review_at='{result_detail.get('initial_review_at')}'"
    )
    assert "approved_at" not in result_detail, (
        f"Bug_Condition C4(b): after reject→draft, result_detail still "
        f"contains approved_at='{result_detail.get('approved_at')}'"
    )

    # Verify rejected_reason is preserved
    assert row_after_draft.get("rejected_reason") == "needs rework", (
        "rejected_reason should be preserved after reject→draft"
    )


def test_p5_reject_from_final_review_clears_all_approver_fields(
    isolated_db, requester, initial_reviewer, final_approver
):
    """
    **Validates: Property 5** — After reject→draft from final_review,
    all six reviewer/approver fields and two timestamps must be cleared.

    On unfixed code: fields are retained after reject→draft → XFAIL
    (bug exists).

    **Validates: Requirements 1.11**
    """
    # Create a draft order with assigned reviewer and approver
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

    # Use _force_status to bypass template enforcement (task 14.1) and
    # directly set the order to final_review with all reviewer/approver
    # fields populated. This isolates the test to Property 5 only.
    initial_review_at = _utc_now_iso()
    _force_status(order_id, "final_review", extra_fields={
        "initial_reviewer_id": initial_reviewer["user_id"],
        "initial_reviewer_username": initial_reviewer["username"],
        "assigned_final_approver_id": final_approver["user_id"],
        "assigned_final_approver_username": final_approver["username"],
        "result_detail_json": json.dumps({"initial_review_at": initial_review_at}),
    })

    # Verify reviewer fields are now populated
    row_at_final = _get_order_row(order_id)
    assert row_at_final["status"] == "final_review"
    assert row_at_final.get("initial_reviewer_username"), \
        "Setup: initial_reviewer_username should be populated after initial review"

    # Final approver rejects → rejected
    status_code, _ = _invoke_transition(
        order_id, "rejected", actor=final_approver,
        extra_body={"rejected_reason": "incomplete documentation"},
    )
    assert status_code == 200, "Setup: could not transition to rejected"

    # Verify the order has all reviewer/approver fields populated
    row_before_draft = _get_order_row(order_id)
    assert row_before_draft["status"] == "rejected"
    result_detail_before = json.loads(
        row_before_draft.get("result_detail_json", "{}") or "{}"
    )
    assert result_detail_before.get("initial_review_at"), \
        "Setup: initial_review_at should be in result_detail after final_review"

    # Requester reopens: rejected → draft
    status_code, _ = _invoke_transition(
        order_id, "draft", actor=requester
    )
    assert status_code == 200, "Could not transition rejected → draft"

    # Re-read the order after transition to draft
    row_after_draft = _get_order_row(order_id)
    assert row_after_draft["status"] == "draft"

    # Assert all six fields are cleared (Property 5)
    assert row_after_draft.get("initial_reviewer_id", "") == "", (
        f"Bug_Condition C4(b): after final_review→rejected→draft, "
        f"initial_reviewer_id still carries "
        f"'{row_after_draft.get('initial_reviewer_id')}'"
    )
    assert row_after_draft.get("initial_reviewer_username", "") == "", (
        f"Bug_Condition C4(b): after final_review→rejected→draft, "
        f"initial_reviewer_username still carries "
        f"'{row_after_draft.get('initial_reviewer_username')}'"
    )
    assert row_after_draft.get("final_approver_id", "") == "", (
        f"Bug_Condition C4(b): after final_review→rejected→draft, "
        f"final_approver_id still carries "
        f"'{row_after_draft.get('final_approver_id')}'"
    )
    assert row_after_draft.get("final_approver_username", "") == "", (
        f"Bug_Condition C4(b): after final_review→rejected→draft, "
        f"final_approver_username still carries "
        f"'{row_after_draft.get('final_approver_username')}'"
    )
    assert row_after_draft.get("approver_id", "") == "", (
        f"Bug_Condition C4(b): after final_review→rejected→draft, "
        f"approver_id still carries "
        f"'{row_after_draft.get('approver_id')}'"
    )
    assert row_after_draft.get("approver_username", "") == "", (
        f"Bug_Condition C4(b): after final_review→rejected→draft, "
        f"approver_username still carries "
        f"'{row_after_draft.get('approver_username')}'"
    )

    # Assert timestamps are cleared from result_detail
    result_detail_raw = row_after_draft.get("result_detail_json", "{}")
    result_detail = json.loads(result_detail_raw) if result_detail_raw else {}
    assert "initial_review_at" not in result_detail, (
        f"Bug_Condition C4(b): after final_review→rejected→draft, "
        f"result_detail still contains "
        f"initial_review_at='{result_detail.get('initial_review_at')}'"
    )
    assert "approved_at" not in result_detail, (
        f"Bug_Condition C4(b): after final_review→rejected→draft, "
        f"result_detail still contains "
        f"approved_at='{result_detail.get('approved_at')}'"
    )

    # Verify rejected_reason is preserved
    assert row_after_draft.get("rejected_reason") == "incomplete documentation", (
        "rejected_reason should be preserved after reject→draft"
    )


# ─────────────────────────────────────────────────────────────────────
# PBT: Combined property for reject→draft field cleanup
#
# Strategy generates orders that reach initial_review or final_review,
# get rejected, then transition back to draft. Asserts all six fields
# are cleared.
# ─────────────────────────────────────────────────────────────────────

@given(
    reject_stage=st.sampled_from(["initial_review", "final_review"]),
)
@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p5_pbt_reject_to_draft_clears_all_fields(
    reject_stage, isolated_db, requester, initial_reviewer, final_approver
):
    """
    **Validates: Property 5** — PBT: For any order reaching initial_review
    or final_review with non-empty reviewer/approver fields, after
    reject→draft, all six fields are cleared and only rejected_reason +
    timeline event remain.

    On unfixed code: stale fields retained → XFAIL (bug exists).

    **Validates: Requirements 1.11**
    """
    # Create a draft order with assigned reviewer and approver
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

    # Use _force_status to bypass template enforcement (task 14.1) and
    # directly set the order to the target review stage with reviewer fields
    # populated. This isolates the PBT to Property 5 (reject→draft cleanup).
    initial_review_at = _utc_now_iso()
    if reject_stage == "final_review":
        _force_status(order_id, "final_review", extra_fields={
            "initial_reviewer_id": initial_reviewer["user_id"],
            "initial_reviewer_username": initial_reviewer["username"],
            "assigned_final_approver_id": final_approver["user_id"],
            "assigned_final_approver_username": final_approver["username"],
            "result_detail_json": json.dumps({"initial_review_at": initial_review_at}),
        })
        # Final approver rejects
        status_code, _ = _invoke_transition(
            order_id, "rejected", actor=final_approver,
            extra_body={"rejected_reason": f"PBT reject from {reject_stage}"},
        )
        assert status_code == 200, "Setup: could not reject from final_review"
    else:
        _force_status(order_id, "initial_review", extra_fields={
            "initial_reviewer_id": initial_reviewer["user_id"],
            "initial_reviewer_username": initial_reviewer["username"],
            "result_detail_json": json.dumps({"initial_review_at": initial_review_at}),
        })
        # Initial reviewer rejects
        status_code, _ = _invoke_transition(
            order_id, "rejected", actor=initial_reviewer,
            extra_body={"rejected_reason": f"PBT reject from {reject_stage}"},
        )
        assert status_code == 200, "Setup: could not reject from initial_review"

    # Verify the order is now rejected with populated fields
    row_rejected = _get_order_row(order_id)
    assert row_rejected["status"] == "rejected"

    # Requester reopens: rejected → draft
    status_code, _ = _invoke_transition(
        order_id, "draft", actor=requester
    )
    assert status_code == 200, "Could not transition rejected → draft"

    # Re-read the order
    row_after = _get_order_row(order_id)
    assert row_after["status"] == "draft"

    # Assert all six fields are cleared
    stale_fields = []
    for field in [
        "initial_reviewer_id", "initial_reviewer_username",
        "final_approver_id", "final_approver_username",
        "approver_id", "approver_username",
    ]:
        val = row_after.get(field, "")
        if val and val != "":
            stale_fields.append(f"{field}='{val}'")

    # Check result_detail timestamps
    result_detail_raw = row_after.get("result_detail_json", "{}")
    result_detail = json.loads(result_detail_raw) if result_detail_raw else {}
    if "initial_review_at" in result_detail:
        stale_fields.append(
            f"result_detail.initial_review_at='{result_detail['initial_review_at']}'"
        )
    if "approved_at" in result_detail:
        stale_fields.append(
            f"result_detail.approved_at='{result_detail['approved_at']}'"
        )

    assert not stale_fields, (
        f"Bug_Condition C4(b): after {reject_stage}→rejected→draft, "
        f"stale fields retained: {', '.join(stale_fields)}"
    )

    # Verify rejected_reason is preserved
    assert row_after.get("rejected_reason") == f"PBT reject from {reject_stage}", (
        "rejected_reason should be preserved after reject→draft"
    )
