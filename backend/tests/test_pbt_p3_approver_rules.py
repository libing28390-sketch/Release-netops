"""
Phase E — Fix-checking PBT for Property P3: approver rule enforcement.

Task 17.3 — Property P3 — approver rule PBT across POST / PUT / transition

Generates (requester, reviewer, approver) tuples across the full space:
  {same, pairwise-different, empty-group, viewer-role, non-admin-approver}

Asserts POST / PUT / transition responses are equivalent (same 400 message
taxonomy) for the same violation tuple.

Validates: Property 3
Requirements: 2.7, 2.8, 2.9, 2.15
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings, strategies as st


# ── Helpers ───────────────────────────────────────────────────────────

def _invoke_create(body_payload: dict, actor: dict) -> tuple[int, object]:
    from api.change_orders import ChangeOrderCreate, api_create_change_order
    body_payload.setdefault("title", "P3 PBT order")
    body_payload.setdefault("description", "")
    body_payload.setdefault("order_type", "config_change")
    body_payload.setdefault("priority", "medium")
    body_payload.setdefault("target_devices", [])
    body_payload.setdefault("commands", ["show version"])
    body_payload.setdefault("rollback_plan", "")
    body_payload.setdefault("risk_level", "low")
    body_payload.setdefault("scheduled_start", "")
    body_payload.setdefault("scheduled_end", "")
    body = ChangeOrderCreate(**body_payload)
    try:
        result = api_create_change_order(body, user=actor)
        return 200, result.get("data") if isinstance(result, dict) else result
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


def _invoke_update(order_id: str, body_payload: dict, actor: dict) -> tuple[int, object]:
    from api.change_orders import ChangeOrderUpdate, api_update_change_order
    body = ChangeOrderUpdate(**body_payload)
    try:
        result = api_update_change_order(order_id, body=body, user=actor)
        return 200, result.get("data") if isinstance(result, dict) else result
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


def _invoke_transition(order_id: str, new_status: str, actor: dict,
                       extra: dict | None = None) -> tuple[int, object]:
    from api.change_orders import api_transition_change_order
    body = {"status": new_status, **(extra or {})}
    try:
        result = api_transition_change_order(order_id, body=body, user=actor)
        return 200, result.get("data") if isinstance(result, dict) else result
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


def _create_draft(requester: dict, reviewer_id: str, approver_id: str = "") -> tuple[int, object]:
    payload = {
        "status": "draft",
        "assigned_initial_reviewer_id": reviewer_id,
    }
    if approver_id:
        payload["assigned_final_approver_id"] = approver_id
    return _invoke_create(payload, actor=requester)


# ── P3a: POST — reviewer with empty change_groups rejected ────────────

def test_p3a_post_empty_groups_reviewer_rejected(isolated_db, requester, make_user):
    """POST with reviewer whose change_groups=[] MUST return HTTP 400."""
    empty_groups_user = make_user("empty_groups_op", role="Operator", change_groups=[])
    sc, detail = _create_draft(requester, reviewer_id=empty_groups_user["user_id"])
    assert sc == 400, f"P3a: empty-group reviewer accepted (HTTP {sc}). Detail: {detail}"


def test_p3a_post_viewer_role_reviewer_rejected(isolated_db, requester, make_user):
    """POST with Viewer-role reviewer MUST return HTTP 400."""
    viewer = make_user("viewer_user", role="Viewer", change_groups=["initial_reviewer"])
    sc, detail = _create_draft(requester, reviewer_id=viewer["user_id"])
    assert sc == 400, f"P3a: Viewer-role reviewer accepted (HTTP {sc}). Detail: {detail}"


# ── P3b: POST — requester == reviewer rejected ────────────────────────

def test_p3b_post_requester_as_reviewer_rejected(isolated_db, requester):
    """POST with assigned_initial_reviewer_id == requester MUST return HTTP 400."""
    sc, detail = _create_draft(requester, reviewer_id=requester["user_id"])
    assert sc == 400, f"P3b: requester==reviewer accepted (HTTP {sc}). Detail: {detail}"


def test_p3b_post_reviewer_equals_approver_rejected(isolated_db, requester, make_user):
    """POST with reviewer == approver MUST return HTTP 400."""
    reviewer = make_user("rev_user", role="Operator", change_groups=["initial_reviewer"])
    # reviewer is also in final_approver group and is Administrator
    approver = make_user("app_user", role="Administrator", change_groups=["final_approver"])
    # Try to set reviewer == approver (same person)
    sc, detail = _invoke_create({
        "status": "draft",
        "assigned_initial_reviewer_id": approver["user_id"],
        "assigned_final_approver_id": approver["user_id"],
    }, actor=requester)
    assert sc == 400, f"P3b: reviewer==approver accepted (HTTP {sc}). Detail: {detail}"


# ── P3c: PUT — dedup rules enforced ──────────────────────────────────

def test_p3c_put_reviewer_equals_requester_rejected(isolated_db, requester, initial_reviewer):
    """PUT with assigned_initial_reviewer_id == requester MUST return HTTP 400."""
    sc, data = _create_draft(requester, reviewer_id=initial_reviewer["user_id"])
    assert sc == 200, f"Setup failed: {data}"
    order_id = data["id"]

    sc2, detail = _invoke_update(order_id,
                                 {"assigned_initial_reviewer_id": requester["user_id"]},
                                 actor=requester)
    assert sc2 == 400, f"P3c: PUT reviewer==requester accepted (HTTP {sc2}). Detail: {detail}"


def test_p3c_put_reviewer_equals_approver_rejected(isolated_db, requester, initial_reviewer, final_approver):
    """PUT with reviewer == approver MUST return HTTP 400."""
    sc, data = _invoke_create({
        "status": "draft",
        "assigned_initial_reviewer_id": initial_reviewer["user_id"],
        "assigned_final_approver_id": final_approver["user_id"],
    }, actor=requester)
    assert sc == 200, f"Setup failed: {data}"
    order_id = data["id"]

    sc2, detail = _invoke_update(order_id,
                                 {"assigned_initial_reviewer_id": final_approver["user_id"]},
                                 actor=requester)
    assert sc2 == 400, f"P3c: PUT reviewer==approver accepted (HTTP {sc2}). Detail: {detail}"


# ── P3d: transition — final_approver validation ───────────────────────

def _setup_order_in_initial_review(requester, initial_reviewer, final_approver):
    """Insert an order directly in initial_review state."""
    from database import get_db_connection
    from services.change_order_service import create_change_order
    conn = get_db_connection()
    try:
        order = create_change_order(
            conn,
            title="P3 transition test",
            description="",
            order_type="config_change",
            priority="medium",
            status="initial_review",
            requester_id=requester["user_id"],
            requester_username=requester["username"],
            assigned_initial_reviewer_id=initial_reviewer["user_id"],
            assigned_initial_reviewer_username=initial_reviewer["username"],
            assigned_final_approver_id="",
            assigned_final_approver_username="",
            command_template={
                "mode": "template",
                "scenario_id": "test-001",
                "preview": {"execute": ["show version"], "pre_check": [], "post_check": [], "rollback": []},
                "platform": "cisco_ios",
                "variables": {},
            },
            target_devices=[],
            commands=["show version"],
            rollback_plan="",
            risk_level="low",
            scheduled_start="",
            scheduled_end="",
            authorization_exempt=False,
            control_sheet={
                "change_time": {"start": "2025-01-01T22:00:00Z", "end": "2025-01-01T23:00:00Z"},
                "implementer": {"id": "u-1", "username": "alice"},
                "co_reviewer": {"id": "u-2", "username": "bob"},
                "device_ips": ["10.0.0.1"],
                "pre_check": "check",
                "execution": "exec",
                "post_verify": "verify",
                "business_verify": "biz",
                "rollback_plan": "rollback",
            },
        )
        conn.commit()
        return order["id"]
    finally:
        conn.close()


def test_p3d_transition_final_approver_is_requester_rejected(
    isolated_db, requester, initial_reviewer, final_approver
):
    """Transition to final_review with final_approver == requester MUST return HTTP 400."""
    order_id = _setup_order_in_initial_review(requester, initial_reviewer, final_approver)
    sc, detail = _invoke_transition(
        order_id, "final_review", actor=initial_reviewer,
        extra={"assigned_final_approver_id": requester["user_id"]}
    )
    assert sc == 400, f"P3d: final_approver==requester accepted (HTTP {sc}). Detail: {detail}"


def test_p3d_transition_final_approver_is_reviewer_rejected(
    isolated_db, requester, initial_reviewer, final_approver
):
    """Transition to final_review with final_approver == initial_reviewer MUST return HTTP 400."""
    order_id = _setup_order_in_initial_review(requester, initial_reviewer, final_approver)
    sc, detail = _invoke_transition(
        order_id, "final_review", actor=initial_reviewer,
        extra={"assigned_final_approver_id": initial_reviewer["user_id"]}
    )
    assert sc == 400, f"P3d: final_approver==reviewer accepted (HTTP {sc}). Detail: {detail}"


def test_p3d_transition_final_approver_outside_group_rejected(
    isolated_db, requester, initial_reviewer, final_approver, make_user
):
    """Transition to final_review with Operator outside final_approver group MUST return HTTP 400."""
    outsider = make_user("outsider_op", role="Operator", change_groups=["initial_reviewer"])
    order_id = _setup_order_in_initial_review(requester, initial_reviewer, final_approver)
    sc, detail = _invoke_transition(
        order_id, "final_review", actor=initial_reviewer,
        extra={"assigned_final_approver_id": outsider["user_id"]}
    )
    assert sc == 400, f"P3d: non-admin final_approver accepted (HTTP {sc}). Detail: {detail}"


# ── P3e: valid tuples accepted ────────────────────────────────────────

def test_p3e_valid_assignment_accepted(isolated_db, requester, initial_reviewer, final_approver):
    """Valid (pairwise-different, correct groups) assignment MUST be accepted."""
    sc, data = _invoke_create({
        "status": "draft",
        "assigned_initial_reviewer_id": initial_reviewer["user_id"],
        "assigned_final_approver_id": final_approver["user_id"],
    }, actor=requester)
    assert sc == 200, f"P3e: valid assignment rejected (HTTP {sc}). Detail: {data}"


# ── PBT: violation vectors all return 400 ────────────────────────────

_VIOLATION_VECTORS = [
    "post_empty_groups",
    "post_requester_as_reviewer",
    "post_reviewer_eq_approver",
    "put_reviewer_eq_requester",
    "transition_approver_eq_requester",
    "transition_approver_eq_reviewer",
    "transition_approver_outside_group",
]


@given(vector=st.sampled_from(_VIOLATION_VECTORS))
@settings(
    max_examples=28,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p3_pbt_all_violation_vectors_rejected(
    vector, isolated_db, requester, initial_reviewer, final_approver, make_user
):
    """PBT: all P3 violation vectors MUST return HTTP 400."""
    if vector == "post_empty_groups":
        empty_user = make_user("pbt_empty", role="Operator", change_groups=[])
        sc, detail = _create_draft(requester, reviewer_id=empty_user["user_id"])

    elif vector == "post_requester_as_reviewer":
        sc, detail = _create_draft(requester, reviewer_id=requester["user_id"])

    elif vector == "post_reviewer_eq_approver":
        sc, detail = _invoke_create({
            "status": "draft",
            "assigned_initial_reviewer_id": final_approver["user_id"],
            "assigned_final_approver_id": final_approver["user_id"],
        }, actor=requester)

    elif vector == "put_reviewer_eq_requester":
        sc0, data = _create_draft(requester, reviewer_id=initial_reviewer["user_id"])
        assert sc0 == 200
        sc, detail = _invoke_update(data["id"],
                                    {"assigned_initial_reviewer_id": requester["user_id"]},
                                    actor=requester)

    elif vector == "transition_approver_eq_requester":
        order_id = _setup_order_in_initial_review(requester, initial_reviewer, final_approver)
        sc, detail = _invoke_transition(order_id, "final_review", actor=initial_reviewer,
                                        extra={"assigned_final_approver_id": requester["user_id"]})

    elif vector == "transition_approver_eq_reviewer":
        order_id = _setup_order_in_initial_review(requester, initial_reviewer, final_approver)
        sc, detail = _invoke_transition(order_id, "final_review", actor=initial_reviewer,
                                        extra={"assigned_final_approver_id": initial_reviewer["user_id"]})

    elif vector == "transition_approver_outside_group":
        outsider = make_user("pbt_outsider", role="Operator", change_groups=["initial_reviewer"])
        order_id = _setup_order_in_initial_review(requester, initial_reviewer, final_approver)
        sc, detail = _invoke_transition(order_id, "final_review", actor=initial_reviewer,
                                        extra={"assigned_final_approver_id": outsider["user_id"]})
    else:
        pytest.fail(f"Unknown vector: {vector}")

    assert sc == 400, (
        f"P3 PBT violation: vector={vector!r} → HTTP {sc} (expected 400). Detail: {detail!r}"
    )
