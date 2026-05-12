"""
Phase E — Fix-checking PBT for Property P2: control-sheet enforcement.

Task 17.2 — Property P2 — control-sheet enforcement PBT

Generates the full matrix of:
  (control_sheet ∈ {missing, partial, complete})
  × (attachments_count ∈ {0, 1, k})
  × (status ∈ transition targets)

Asserts the acceptance matrix from design.md §Correctness Properties → Property 2:

  - transition → initial_review with missing/partial control_sheet  → HTTP 400
  - transition → initial_review with complete control_sheet         → HTTP 200
  - transition → implementing with 0 attachments                    → HTTP 400
  - transition → implementing with ≥1 attachment                    → HTTP 200

The 9 required fields for a complete control_sheet are:
  change_time      — dict with 'start' and 'end' ISO timestamps
  implementer      — dict with 'id' and 'username'
  co_reviewer      — dict with 'id' and 'username'
  device_ips       — non-empty list of IP strings
  pre_check        — non-empty string
  execution        — non-empty string
  post_verify      — non-empty string
  business_verify  — non-empty string
  rollback_plan    — non-empty string

**Validates: Requirements 2.4, 2.5, 2.6**
"""

from __future__ import annotations

import uuid
import json
import pytest
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings, strategies as st

import api.change_orders as _co_module
from database import get_db_connection


# ── Feature flag fixture ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def enable_control_sheet(monkeypatch):
    """Enable FEATURE_CONTROL_SHEET for all tests in this module.

    Task 15.3 gates enforcement behind this flag; the fix-checking PBT
    (Phase E) verifies the *fixed* behavior, so the flag must be ON.
    """
    monkeypatch.setattr(_co_module, "FEATURE_CONTROL_SHEET", True)


# ── Control sheet kind definitions ───────────────────────────────────

COMPLETE_CONTROL_SHEET = {
    "change_time": {"start": "2025-04-01T22:00:00Z", "end": "2025-04-01T23:00:00Z"},
    "implementer": {"id": "u-123", "username": "alice"},
    "co_reviewer": {"id": "u-456", "username": "bob"},
    "device_ips": ["10.0.0.1", "10.0.0.2"],
    "pre_check": "show version",
    "execution": "interface GigabitEthernet0/0\n no shutdown",
    "post_verify": "show interfaces status",
    "business_verify": "ping 10.0.0.1 repeat 5",
    "rollback_plan": "interface GigabitEthernet0/0\n shutdown",
}

# All 9 required field names
REQUIRED_FIELDS = [
    "change_time",
    "implementer",
    "co_reviewer",
    "device_ips",
    "pre_check",
    "execution",
    "post_verify",
    "business_verify",
    "rollback_plan",
]

# Partial control sheets: each is missing exactly one required field
PARTIAL_CONTROL_SHEETS = [
    {k: v for k, v in COMPLETE_CONTROL_SHEET.items() if k != missing_field}
    for missing_field in REQUIRED_FIELDS
]

# Invalid (empty) values for each field type
EMPTY_FIELD_VALUES = {
    "change_time": {},
    "implementer": {},
    "co_reviewer": {},
    "device_ips": [],
    "pre_check": "",
    "execution": "",
    "post_verify": "",
    "business_verify": "",
    "rollback_plan": "",
}

# Partial sheets with empty (but present) required fields
EMPTY_VALUE_CONTROL_SHEETS = [
    {**COMPLETE_CONTROL_SHEET, field: EMPTY_FIELD_VALUES[field]}
    for field in REQUIRED_FIELDS
]

# P2 error messages from _validate_control_sheet_completeness
P2_CONTROL_SHEET_MESSAGES = [
    "提交初审前必须填写完整的变更控制表",
    "缺失字段",
]

P2_ATTACHMENT_MESSAGES = [
    "进入实施阶段前必须上传至少一个附件",
]


# ── Helpers ───────────────────────────────────────────────────────────

def _is_p2_control_sheet_rejection(detail: object) -> bool:
    """Return True if the detail string is a P2 control-sheet completeness error."""
    detail_str = str(detail)
    return any(msg in detail_str for msg in P2_CONTROL_SHEET_MESSAGES)


def _is_p2_attachment_rejection(detail: object) -> bool:
    """Return True if the detail string is a P2 attachment requirement error."""
    detail_str = str(detail)
    return any(msg in detail_str for msg in P2_ATTACHMENT_MESSAGES)


def _create_draft_order(conn, requester: dict, reviewer: dict) -> dict:
    """Create a draft change order and return it."""
    from api.change_orders import ChangeOrderCreate, api_create_change_order
    body = ChangeOrderCreate(
        title="P2 PBT order",
        description="",
        order_type="config_change",
        priority="medium",
        status="draft",
        assigned_initial_reviewer_id=reviewer["user_id"],
        command_template={},
        target_devices=[],
        commands=[],
        rollback_plan="",
        risk_level="low",
        scheduled_start="",
        scheduled_end="",
        control_sheet={},
    )
    result = api_create_change_order(body, user=requester)
    return result["data"]


def _transition_to_initial_review(
    order_id: str,
    control_sheet: dict,
    actor: dict,
) -> tuple[int, object]:
    """Attempt to transition an order to initial_review.

    Returns (status_code, result_or_detail).
    """
    from api.change_orders import api_transition_change_order

    body = {
        "status": "initial_review",
        "control_sheet": control_sheet,
    }
    # Merge control_sheet into the order via update first, then transition
    # (the transition handler reads control_sheet from the persisted order)
    conn = get_db_connection()
    try:
        from services.change_order_service import update_change_order
        update_change_order(conn, order_id, {"control_sheet": control_sheet})
    finally:
        conn.close()

    try:
        result = api_transition_change_order(order_id, body=body, user=actor)
        return 200, result
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


def _transition_to_final_review(
    order_id: str,
    actor: dict,
    final_approver: dict,
) -> tuple[int, object]:
    """Transition an order from initial_review to final_review."""
    from api.change_orders import api_transition_change_order

    body = {
        "status": "final_review",
        "assigned_final_approver_id": final_approver["user_id"],
    }
    try:
        result = api_transition_change_order(order_id, body=body, user=actor)
        return 200, result
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


def _transition_to_approved(
    order_id: str,
    actor: dict,
) -> tuple[int, object]:
    """Transition an order from final_review to approved."""
    from api.change_orders import api_transition_change_order

    body = {"status": "approved"}
    try:
        result = api_transition_change_order(order_id, body=body, user=actor)
        return 200, result
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


def _transition_to_implementing(
    order_id: str,
    actor: dict,
) -> tuple[int, object]:
    """Attempt to transition an order to implementing.

    Returns (status_code, result_or_detail).
    """
    from api.change_orders import api_transition_change_order

    body = {"status": "implementing"}
    try:
        result = api_transition_change_order(order_id, body=body, user=actor)
        return 200, result
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


def _upload_attachment(order_id: str) -> None:
    """Insert a fake attachment row directly into the DB.

    Uses the actual schema from database.py:
      id, order_id, file_path, file_name, file_size, created_at
    """
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO change_order_control_sheet_attachments
                (id, order_id, file_path, file_name, file_size, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                order_id,
                f"attachments/{order_id}/control_sheet.pdf",
                "control_sheet.pdf",
                1024,
                "2025-04-01T22:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _drive_order_to_approved(
    requester: dict,
    reviewer: dict,
    final_approver: dict,
) -> str:
    """Create a draft order and drive it all the way to 'approved'.

    Returns the order_id.
    """
    conn = get_db_connection()
    try:
        order = _create_draft_order(conn, requester, reviewer)
    finally:
        conn.close()

    order_id = order["id"]

    # Transition to initial_review with a complete control sheet
    code, detail = _transition_to_initial_review(
        order_id, COMPLETE_CONTROL_SHEET, requester
    )
    assert code == 200, f"Expected 200 on initial_review transition, got {code}: {detail}"

    # Transition to final_review (reviewer acts)
    code, detail = _transition_to_final_review(order_id, reviewer, final_approver)
    assert code == 200, f"Expected 200 on final_review transition, got {code}: {detail}"

    # Transition to approved (final_approver acts)
    code, detail = _transition_to_approved(order_id, final_approver)
    assert code == 200, f"Expected 200 on approved transition, got {code}: {detail}"

    return order_id


# ── Tests: initial_review with missing control_sheet → HTTP 400 ───────

def test_p2_initial_review_missing_control_sheet_rejected(
    isolated_db, requester, initial_reviewer
):
    """
    **Validates: Requirements 2.4, 2.5**

    P2 enforcement: transition → initial_review with no control_sheet
    (empty dict) MUST be rejected with HTTP 400.
    """
    conn = get_db_connection()
    try:
        order = _create_draft_order(conn, requester, initial_reviewer)
    finally:
        conn.close()

    code, detail = _transition_to_initial_review(order["id"], {}, requester)
    assert code == 400, (
        f"P2 violation: initial_review + missing control_sheet → HTTP {code} "
        f"(expected 400). Detail: {detail!r}"
    )
    assert _is_p2_control_sheet_rejection(detail), (
        f"P2 violation: HTTP 400 but not for control-sheet reason. Detail: {detail!r}"
    )


@pytest.mark.parametrize("partial_sheet", PARTIAL_CONTROL_SHEETS)
def test_p2_initial_review_partial_control_sheet_rejected(
    partial_sheet, isolated_db, requester, initial_reviewer
):
    """
    **Validates: Requirements 2.4, 2.5**

    P2 enforcement: transition → initial_review with a partial control_sheet
    (missing one required field) MUST be rejected with HTTP 400.

    Tests all 9 single-field-missing variants.
    """
    conn = get_db_connection()
    try:
        order = _create_draft_order(conn, requester, initial_reviewer)
    finally:
        conn.close()

    code, detail = _transition_to_initial_review(order["id"], partial_sheet, requester)
    assert code == 400, (
        f"P2 violation: initial_review + partial control_sheet → HTTP {code} "
        f"(expected 400). Detail: {detail!r}"
    )
    assert _is_p2_control_sheet_rejection(detail), (
        f"P2 violation: HTTP 400 but not for control-sheet reason. Detail: {detail!r}"
    )


@pytest.mark.parametrize("empty_value_sheet", EMPTY_VALUE_CONTROL_SHEETS)
def test_p2_initial_review_empty_field_values_rejected(
    empty_value_sheet, isolated_db, requester, initial_reviewer
):
    """
    **Validates: Requirements 2.4, 2.5**

    P2 enforcement: transition → initial_review with a control_sheet that
    has all 9 fields present but one has an empty/falsy value MUST be
    rejected with HTTP 400.

    Tests all 9 single-field-empty variants.
    """
    conn = get_db_connection()
    try:
        order = _create_draft_order(conn, requester, initial_reviewer)
    finally:
        conn.close()

    code, detail = _transition_to_initial_review(order["id"], empty_value_sheet, requester)
    assert code == 400, (
        f"P2 violation: initial_review + empty field value → HTTP {code} "
        f"(expected 400). Detail: {detail!r}"
    )
    assert _is_p2_control_sheet_rejection(detail), (
        f"P2 violation: HTTP 400 but not for control-sheet reason. Detail: {detail!r}"
    )


def test_p2_initial_review_complete_control_sheet_accepted(
    isolated_db, requester, initial_reviewer
):
    """
    **Validates: Requirements 2.4, 2.5, 2.6**

    P2 enforcement: transition → initial_review with a complete control_sheet
    (all 9 required fields non-empty) MUST be accepted (HTTP 200).
    """
    conn = get_db_connection()
    try:
        order = _create_draft_order(conn, requester, initial_reviewer)
    finally:
        conn.close()

    code, detail = _transition_to_initial_review(
        order["id"], COMPLETE_CONTROL_SHEET, requester
    )
    assert code == 200, (
        f"P2 violation: initial_review + complete control_sheet → HTTP {code} "
        f"(expected 200). Detail: {detail!r}"
    )


# ── Tests: implementing with 0 attachments → HTTP 400 ─────────────────

def test_p2_implementing_zero_attachments_rejected(
    isolated_db, requester, initial_reviewer, final_approver
):
    """
    **Validates: Requirements 2.5, 2.6**

    P2 enforcement: transition → implementing with 0 control-sheet
    attachments MUST be rejected with HTTP 400.
    """
    order_id = _drive_order_to_approved(requester, initial_reviewer, final_approver)

    # No attachments uploaded — transition should fail
    code, detail = _transition_to_implementing(order_id, requester)
    assert code == 400, (
        f"P2 violation: implementing + 0 attachments → HTTP {code} "
        f"(expected 400). Detail: {detail!r}"
    )
    assert _is_p2_attachment_rejection(detail), (
        f"P2 violation: HTTP 400 but not for attachment reason. Detail: {detail!r}"
    )


def test_p2_implementing_one_attachment_accepted(
    isolated_db, requester, initial_reviewer, final_approver
):
    """
    **Validates: Requirements 2.5, 2.6**

    P2 enforcement: transition → implementing with exactly 1 control-sheet
    attachment MUST be accepted (HTTP 200).
    """
    order_id = _drive_order_to_approved(requester, initial_reviewer, final_approver)

    # Upload exactly 1 attachment
    _upload_attachment(order_id)

    code, detail = _transition_to_implementing(order_id, requester)
    assert code == 200, (
        f"P2 violation: implementing + 1 attachment → HTTP {code} "
        f"(expected 200). Detail: {detail!r}"
    )


def test_p2_implementing_multiple_attachments_accepted(
    isolated_db, requester, initial_reviewer, final_approver
):
    """
    **Validates: Requirements 2.5, 2.6**

    P2 enforcement: transition → implementing with k > 1 control-sheet
    attachments MUST be accepted (HTTP 200).
    """
    order_id = _drive_order_to_approved(requester, initial_reviewer, final_approver)

    # Upload 3 attachments
    for _ in range(3):
        _upload_attachment(order_id)

    code, detail = _transition_to_implementing(order_id, requester)
    assert code == 200, (
        f"P2 violation: implementing + 3 attachments → HTTP {code} "
        f"(expected 200). Detail: {detail!r}"
    )


# ── PBT: control_sheet × initial_review enforcement ──────────────────

# Strategies for generating partial control sheets
@st.composite
def partial_control_sheet_strategy(draw):
    """Generate a control_sheet with at least one missing or empty required field."""
    # Choose how many fields to omit (1 to all 9)
    n_missing = draw(st.integers(min_value=1, max_value=len(REQUIRED_FIELDS)))
    missing_fields = draw(
        st.lists(
            st.sampled_from(REQUIRED_FIELDS),
            min_size=n_missing,
            max_size=n_missing,
            unique=True,
        )
    )
    sheet = dict(COMPLETE_CONTROL_SHEET)
    for field in missing_fields:
        # Either remove the field entirely or set it to an empty value
        action = draw(st.sampled_from(["remove", "empty"]))
        if action == "remove":
            del sheet[field]
        else:
            sheet[field] = EMPTY_FIELD_VALUES[field]
    return sheet


@given(partial_sheet=partial_control_sheet_strategy())
@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p2_pbt_partial_control_sheet_rejected_at_initial_review(
    partial_sheet, isolated_db, requester, initial_reviewer
):
    """
    **Validates: Requirements 2.4, 2.5**

    Property: ∀ control_sheet with ≥1 missing/empty required field,
              transition → initial_review MUST return HTTP 400.

    This is the core P2 fix-checking property for the control-sheet
    completeness enforcement gate.
    """
    conn = get_db_connection()
    try:
        order = _create_draft_order(conn, requester, initial_reviewer)
    finally:
        conn.close()

    code, detail = _transition_to_initial_review(order["id"], partial_sheet, requester)
    assert code == 400, (
        f"P2 PBT violation: initial_review + partial control_sheet → "
        f"HTTP {code} (expected 400). Detail: {detail!r}"
    )
    assert _is_p2_control_sheet_rejection(detail), (
        f"P2 PBT violation: HTTP 400 but not for control-sheet reason. "
        f"Detail: {detail!r}"
    )


@given(
    attachments_count=st.integers(min_value=1, max_value=5),
)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p2_pbt_implementing_with_attachments_accepted(
    attachments_count, isolated_db, requester, initial_reviewer, final_approver
):
    """
    **Validates: Requirements 2.5, 2.6**

    Property: ∀ attachments_count ≥ 1,
              transition → implementing MUST return HTTP 200.

    This verifies that any non-zero number of attachments satisfies the
    P2 attachment requirement.
    """
    order_id = _drive_order_to_approved(requester, initial_reviewer, final_approver)

    for _ in range(attachments_count):
        _upload_attachment(order_id)

    code, detail = _transition_to_implementing(order_id, requester)
    assert code == 200, (
        f"P2 PBT violation: implementing + {attachments_count} attachment(s) → "
        f"HTTP {code} (expected 200). Detail: {detail!r}"
    )


# ── PBT: full matrix — control_sheet × attachments_count × status ────

@given(
    missing_field=st.sampled_from(REQUIRED_FIELDS),
    attachments_count=st.integers(min_value=0, max_value=3),
)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p2_pbt_matrix_initial_review_missing_field(
    missing_field, attachments_count, isolated_db, requester, initial_reviewer
):
    """
    **Validates: Requirements 2.4, 2.5**

    Property: ∀ missing_field ∈ REQUIRED_FIELDS,
              ∀ attachments_count ∈ {0, 1, 2, 3},
    transition → initial_review with that field missing MUST return HTTP 400.

    The attachments_count is irrelevant for initial_review enforcement
    (attachments are only required at implementing), but we include it
    to verify the enforcement is independent of attachment state.
    """
    conn = get_db_connection()
    try:
        order = _create_draft_order(conn, requester, initial_reviewer)
    finally:
        conn.close()

    order_id = order["id"]

    # Upload attachments (should not affect initial_review enforcement)
    for _ in range(attachments_count):
        _upload_attachment(order_id)

    partial_sheet = {k: v for k, v in COMPLETE_CONTROL_SHEET.items() if k != missing_field}
    code, detail = _transition_to_initial_review(order_id, partial_sheet, requester)
    assert code == 400, (
        f"P2 PBT matrix violation: initial_review + missing {missing_field!r} "
        f"+ {attachments_count} attachment(s) → HTTP {code} (expected 400). "
        f"Detail: {detail!r}"
    )
    assert _is_p2_control_sheet_rejection(detail), (
        f"P2 PBT matrix violation: HTTP 400 but not for control-sheet reason. "
        f"Detail: {detail!r}"
    )


# ── Edge cases ────────────────────────────────────────────────────────

def test_p2_complete_control_sheet_persisted_after_initial_review(
    isolated_db, requester, initial_reviewer
):
    """
    **Validates: Requirements 2.4, 2.6**

    After a successful initial_review transition with a complete control_sheet,
    the control_sheet data MUST be persisted and readable via GET.
    """
    conn = get_db_connection()
    try:
        order = _create_draft_order(conn, requester, initial_reviewer)
    finally:
        conn.close()

    code, result = _transition_to_initial_review(
        order["id"], COMPLETE_CONTROL_SHEET, requester
    )
    assert code == 200, f"Expected 200, got {code}: {result!r}"

    # Verify the control_sheet is persisted
    conn = get_db_connection()
    try:
        from services.change_order_service import get_change_order
        persisted = get_change_order(conn, order["id"])
    finally:
        conn.close()

    assert persisted is not None
    cs = persisted.get("control_sheet") or {}
    assert cs.get("pre_check") == COMPLETE_CONTROL_SHEET["pre_check"], (
        f"P2 violation: control_sheet.pre_check not persisted. Got: {cs!r}"
    )
    assert cs.get("device_ips") == COMPLETE_CONTROL_SHEET["device_ips"], (
        f"P2 violation: control_sheet.device_ips not persisted. Got: {cs!r}"
    )


def test_p2_implementing_zero_attachments_does_not_change_status(
    isolated_db, requester, initial_reviewer, final_approver
):
    """
    **Validates: Requirements 2.5**

    When transition → implementing is rejected due to 0 attachments,
    the order status MUST remain 'approved' (no partial state change).
    """
    order_id = _drive_order_to_approved(requester, initial_reviewer, final_approver)

    # Attempt transition without attachments
    code, detail = _transition_to_implementing(order_id, requester)
    assert code == 400, f"Expected 400, got {code}: {detail!r}"

    # Verify status is still 'approved'
    conn = get_db_connection()
    try:
        from services.change_order_service import get_change_order
        order = get_change_order(conn, order_id)
    finally:
        conn.close()

    assert order["status"] == "approved", (
        f"P2 violation: status changed to {order['status']!r} after rejected "
        f"implementing transition (expected 'approved')"
    )


def test_p2_initial_review_rejection_does_not_change_status(
    isolated_db, requester, initial_reviewer
):
    """
    **Validates: Requirements 2.4**

    When transition → initial_review is rejected due to incomplete
    control_sheet, the order status MUST remain 'draft' (no partial state change).
    """
    conn = get_db_connection()
    try:
        order = _create_draft_order(conn, requester, initial_reviewer)
    finally:
        conn.close()

    order_id = order["id"]

    # Attempt transition with missing control_sheet
    code, detail = _transition_to_initial_review(order_id, {}, requester)
    assert code == 400, f"Expected 400, got {code}: {detail!r}"

    # Verify status is still 'draft'
    conn = get_db_connection()
    try:
        from services.change_order_service import get_change_order
        order_after = get_change_order(conn, order_id)
    finally:
        conn.close()

    assert order_after["status"] == "draft", (
        f"P2 violation: status changed to {order_after['status']!r} after rejected "
        f"initial_review transition (expected 'draft')"
    )


def test_p2_control_sheet_missing_banner_on_historical_completed_order(
    isolated_db, requester, initial_reviewer, final_approver
):
    """
    **Validates: Requirements 2.6**

    Historical/completed orders that have no control_sheet data MUST
    return control_sheet_missing=True in the GET response (banner field),
    and MUST NOT crash.

    This tests backward compatibility for orders created before the
    control-sheet feature was added.
    """
    # Create an order and manually drive it to 'completed' without control_sheet
    # by bypassing the enforcement (flag is ON but we insert directly)
    conn = get_db_connection()
    try:
        from services.change_order_service import create_change_order, update_change_order, get_change_order
        order = create_change_order(
            conn,
            title="Historical order",
            description="",
            order_type="config_change",
            priority="medium",
            status="completed",
            requester_id=requester["user_id"],
            requester_username=requester["username"],
            control_sheet=None,  # No control sheet
        )
        order_id = order["id"]
        # Verify the banner is set
        persisted = get_change_order(conn, order_id)
    finally:
        conn.close()

    assert persisted is not None, "Order should be retrievable"
    assert persisted.get("control_sheet_missing") is True, (
        f"P2 violation: historical completed order without control_sheet "
        f"should have control_sheet_missing=True. Got: {persisted.get('control_sheet_missing')!r}"
    )
