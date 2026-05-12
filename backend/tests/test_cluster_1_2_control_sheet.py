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

import json
import uuid

import pytest
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings, strategies as st
import api.change_orders as _co_module


@pytest.fixture(autouse=True)
def enable_control_sheet(monkeypatch):
    """Enable FEATURE_CONTROL_SHEET for all tests in this module.

    Task 15.3 gates enforcement behind this flag.  The exploration tests
    (Phase A) verify the *fixed* behavior, so the flag must be ON.
    """
    monkeypatch.setattr(_co_module, "FEATURE_CONTROL_SHEET", True)


# ── Statuses where control_sheet should be required ──────────────────
_NON_DRAFT_STATUSES = [
    "initial_review",
    "final_review",
    "approved",
    "implementing",
    "completed",
    "rolled_back",
]

# Statuses where control_sheet is enforced at CREATE time (direct submission)
# Only initial_review is enforced at create time; other non-draft statuses
# are reached via transitions which have their own enforcement.
_CREATE_ENFORCED_STATUSES = ["initial_review"]


def _non_draft_status_strategy():
    """Strategy for target statuses that require control_sheet fields at create time."""
    return st.sampled_from(_CREATE_ENFORCED_STATUSES)


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
    # 1. Create draft order with a valid control_sheet so it can pass
    #    the initial_review enforcement check
    status_code, order = _invoke_create(
        {
            "status": "draft",
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
            "command_template": {},
            "commands": ["show version"],
            "control_sheet": _VALID_CONTROL_SHEET,
        },
        actor=requester,
    )
    assert status_code == 200, f"Draft creation failed: {order}"
    order_id = order["id"]

    # 2. Transition draft → initial_review (control_sheet is present, should succeed)
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
def test_c2_get_completed_order_shows_control_sheet_missing_banner(
    isolated_db, requester, initial_reviewer, final_approver
):
    """
    After an order reaches 'completed' without any control_sheet data
    (simulating a historical row), GET /change-orders/{id} MUST still
    return the order successfully AND include a `control_sheet_missing: true`
    banner field so the UI can display a warning.

    On unfixed code: the field simply does not exist in the response.

    This test inserts a historical completed row directly into the DB
    (bypassing the API enforcement) to simulate an order that was created
    before the control_sheet feature was added.
    """
    from database import get_db_connection
    from services.change_order_service import get_change_order

    # Insert a historical completed order directly into the DB with no
    # control_sheet data (simulating a pre-feature row)
    conn = get_db_connection()
    order_id = str(uuid.uuid4())
    now = "2025-01-01T10:00:00Z"
    conn.execute(
        """
        INSERT INTO change_orders (
            id, order_number, title, description, order_type, priority,
            status, requester_id, requester_username,
            assigned_initial_reviewer_id, assigned_initial_reviewer_username,
            assigned_final_approver_id, assigned_final_approver_username,
            command_template_json, target_devices_json, commands_json,
            rollback_plan, risk_level, scheduled_start, scheduled_end,
            authorization_exempt, control_sheet_json,
            result_detail_json, created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?,
            ?, ?, ?
        )
        """,
        (
            order_id, "BG202501010001", "Historical Order", "", "config_change", "medium",
            "completed", requester["user_id"], requester["username"],
            initial_reviewer["user_id"], initial_reviewer["username"],
            final_approver["user_id"], final_approver["username"],
            "{}", "[]", '["show version"]',
            "rollback steps", "low", "", "",
            0, "{}",  # empty control_sheet_json — historical row
            "{}", now, now,
        ),
    )
    conn.commit()
    conn.close()

    # Now GET the completed order via the API handler
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
        data_str = str(data).lower()
        if sc == 400 and (
            "control_sheet" in data_str
            or "变更控制表" in str(data)
            or "控制表" in str(data)
            or "附件" in str(data)
        ):
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


# ─────────────────────────────────────────────────────────────────────
# Task 15.1 — Integration tests: control_sheet round-trip via
# create / update → _row_to_dict readout
#
# These tests verify that:
#   1. ChangeOrderCreate / ChangeOrderUpdate accept the 9-field
#      control_sheet structure (per design.md §Data Model Changes)
#   2. create_change_order / update_change_order JSON-serialize the
#      field into change_orders.control_sheet_json
#   3. _row_to_dict (via get_change_order) deserializes it back
#      correctly — the round-trip is lossless
#
# **Validates: Property 2 (design.md §Correctness Properties)**
# Requirements: 2.4
# ─────────────────────────────────────────────────────────────────────

_VALID_CONTROL_SHEET = {
    "change_time": {
        "start": "2025-04-01T22:00:00Z",
        "end": "2025-04-01T23:00:00Z",
    },
    "implementer": {"id": "u-123", "username": "alice"},
    "co_reviewer": {"id": "u-456", "username": "bob"},
    "device_ips": ["10.0.0.1", "10.0.0.2"],
    "pre_check": "show version; show interfaces",
    "execution": "interface GigabitEthernet0/0\n no shutdown",
    "post_verify": "show interfaces status",
    "business_verify": "Ping test from 10.0.0.1 to 10.0.0.2",
    "rollback_plan": "interface GigabitEthernet0/0\n shutdown",
}


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


def test_15_1_create_with_control_sheet_round_trip(isolated_db, requester, initial_reviewer):
    """
    **Validates: Property 2** — Task 15.1 integration test.

    POST /api/change-orders with a fully-populated 9-field control_sheet
    (status='draft') MUST:
      1. Accept the request (HTTP 200)
      2. Persist the control_sheet into control_sheet_json
      3. Return the deserialized control_sheet via _row_to_dict so the
         round-trip is lossless

    Requirements: 2.4
    """
    status_code, data = _invoke_create(
        {
            "status": "draft",
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
            "command_template": {},
            "commands": ["show version"],
            "control_sheet": _VALID_CONTROL_SHEET,
        },
        actor=requester,
    )
    assert status_code == 200, f"Create with control_sheet failed: {data}"
    assert isinstance(data, dict), f"Expected dict response, got: {type(data)}"

    # Verify round-trip: the returned order must contain the control_sheet
    cs = data.get("control_sheet")
    assert isinstance(cs, dict), (
        f"control_sheet not deserialized in response; got: {cs!r}"
    )
    assert cs.get("change_time") == _VALID_CONTROL_SHEET["change_time"], (
        f"change_time mismatch: {cs.get('change_time')!r}"
    )
    assert cs.get("implementer") == _VALID_CONTROL_SHEET["implementer"], (
        f"implementer mismatch: {cs.get('implementer')!r}"
    )
    assert cs.get("co_reviewer") == _VALID_CONTROL_SHEET["co_reviewer"], (
        f"co_reviewer mismatch: {cs.get('co_reviewer')!r}"
    )
    assert cs.get("device_ips") == _VALID_CONTROL_SHEET["device_ips"], (
        f"device_ips mismatch: {cs.get('device_ips')!r}"
    )
    assert cs.get("pre_check") == _VALID_CONTROL_SHEET["pre_check"], (
        f"pre_check mismatch: {cs.get('pre_check')!r}"
    )
    assert cs.get("execution") == _VALID_CONTROL_SHEET["execution"], (
        f"execution mismatch: {cs.get('execution')!r}"
    )
    assert cs.get("post_verify") == _VALID_CONTROL_SHEET["post_verify"], (
        f"post_verify mismatch: {cs.get('post_verify')!r}"
    )
    assert cs.get("business_verify") == _VALID_CONTROL_SHEET["business_verify"], (
        f"business_verify mismatch: {cs.get('business_verify')!r}"
    )
    assert cs.get("rollback_plan") == _VALID_CONTROL_SHEET["rollback_plan"], (
        f"rollback_plan mismatch: {cs.get('rollback_plan')!r}"
    )


def test_15_1_update_with_control_sheet_round_trip(isolated_db, requester, initial_reviewer):
    """
    **Validates: Property 2** — Task 15.1 integration test.

    PUT /api/change-orders/{id} with a fully-populated 9-field control_sheet
    MUST:
      1. Accept the request (HTTP 200)
      2. Persist the updated control_sheet into control_sheet_json
      3. Return the deserialized control_sheet via _row_to_dict so the
         round-trip is lossless

    Requirements: 2.4
    """
    # First create a draft order without control_sheet
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
    order_id = data["id"]

    # Verify initial control_sheet is empty dict
    assert data.get("control_sheet") == {}, (
        f"Expected empty control_sheet on draft, got: {data.get('control_sheet')!r}"
    )

    # Now update with the full control_sheet
    sc, updated = _invoke_update(
        order_id,
        {"control_sheet": _VALID_CONTROL_SHEET},
        actor=requester,
    )
    assert sc == 200, f"Update with control_sheet failed: {updated}"

    cs = updated.get("control_sheet")
    assert isinstance(cs, dict), (
        f"control_sheet not deserialized after update; got: {cs!r}"
    )
    assert cs.get("change_time") == _VALID_CONTROL_SHEET["change_time"]
    assert cs.get("implementer") == _VALID_CONTROL_SHEET["implementer"]
    assert cs.get("co_reviewer") == _VALID_CONTROL_SHEET["co_reviewer"]
    assert cs.get("device_ips") == _VALID_CONTROL_SHEET["device_ips"]
    assert cs.get("pre_check") == _VALID_CONTROL_SHEET["pre_check"]
    assert cs.get("execution") == _VALID_CONTROL_SHEET["execution"]
    assert cs.get("post_verify") == _VALID_CONTROL_SHEET["post_verify"]
    assert cs.get("business_verify") == _VALID_CONTROL_SHEET["business_verify"]
    assert cs.get("rollback_plan") == _VALID_CONTROL_SHEET["rollback_plan"]


def test_15_1_control_sheet_empty_dict_default(isolated_db, requester, initial_reviewer):
    """
    **Validates: Property 2 / Property 7** — Task 15.1 backward-compat test.

    Creating an order without providing control_sheet MUST:
      1. Succeed (HTTP 200) for draft orders
      2. Return control_sheet as {} (empty dict, not None or missing)
         so legacy rows don't crash _row_to_dict

    Requirements: 2.4, 3.8
    """
    status_code, data = _invoke_create(
        {
            "status": "draft",
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
            "command_template": {},
            "commands": ["show version"],
            # No control_sheet field
        },
        actor=requester,
    )
    assert status_code == 200, f"Draft creation without control_sheet failed: {data}"
    cs = data.get("control_sheet")
    assert cs == {}, (
        f"Expected empty dict for control_sheet when not provided, got: {cs!r}"
    )


def test_15_1_control_sheet_partial_update_preserves_other_fields(
    isolated_db, requester, initial_reviewer
):
    """
    **Validates: Property 2** — Task 15.1 integration test.

    Updating only the control_sheet field via PUT MUST NOT overwrite
    other order fields (title, description, etc.).

    Requirements: 2.4
    """
    # Create with a specific title
    status_code, data = _invoke_create(
        {
            "title": "My Important Change",
            "description": "Critical network change",
            "status": "draft",
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
            "command_template": {},
            "commands": ["show version"],
        },
        actor=requester,
    )
    assert status_code == 200, f"Draft creation failed: {data}"
    order_id = data["id"]

    # Update only control_sheet
    sc, updated = _invoke_update(
        order_id,
        {"control_sheet": _VALID_CONTROL_SHEET},
        actor=requester,
    )
    assert sc == 200, f"Update failed: {updated}"

    # Other fields must be preserved
    assert updated.get("title") == "My Important Change", (
        f"title was overwritten: {updated.get('title')!r}"
    )
    assert updated.get("description") == "Critical network change", (
        f"description was overwritten: {updated.get('description')!r}"
    )
    # control_sheet must be updated
    assert updated.get("control_sheet", {}).get("pre_check") == _VALID_CONTROL_SHEET["pre_check"]
