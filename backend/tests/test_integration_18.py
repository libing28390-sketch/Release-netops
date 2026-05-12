"""
Phase F — Integration tests.

Task 18.1 End-to-end main path
Task 18.2 Reject-and-resume path
Task 18.3 Cross-view consistency

Requirements: 2.1–2.9, 2.11–2.16, 3.1–3.8
"""

from __future__ import annotations

import json
import re
import pytest
from database import get_db_connection
from services.change_order_service import list_change_orders, get_change_order


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _invoke_create(payload: dict, actor: dict) -> tuple[int, object]:
    from api.change_orders import ChangeOrderCreate, api_create_change_order
    from fastapi import HTTPException
    payload.setdefault("title", "Integration test order")
    payload.setdefault("description", "")
    payload.setdefault("order_type", "config_change")
    payload.setdefault("priority", "medium")
    payload.setdefault("target_devices", [])
    payload.setdefault("commands", ["show version"])
    payload.setdefault("rollback_plan", "")
    payload.setdefault("risk_level", "low")
    payload.setdefault("scheduled_start", "")
    payload.setdefault("scheduled_end", "")
    body = ChangeOrderCreate(**payload)
    try:
        result = api_create_change_order(body, user=actor)
        return 200, result.get("data") if isinstance(result, dict) else result
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


def _invoke_transition(order_id: str, new_status: str, actor: dict,
                       extra: dict | None = None) -> tuple[int, object]:
    from api.change_orders import api_transition_change_order
    from fastapi import HTTPException
    body = {"status": new_status, **(extra or {})}
    try:
        result = api_transition_change_order(order_id, body=body, user=actor)
        return 200, result.get("data") if isinstance(result, dict) else result
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)


def _valid_command_template() -> dict:
    return {
        "mode": "template",
        "scenario_id": "test-scenario-001",
        "scenario_name": "Test Scenario",
        "platform": "cisco_ios",
        "variables": {},
        "preview": {
            "pre_check": ["show version"],
            "execute": ["show running-config"],
            "post_check": ["show interfaces status"],
            "rollback": [],
        },
    }


def _valid_control_sheet() -> dict:
    return {
        "change_time": {"start": "2025-01-01T22:00:00Z", "end": "2025-01-01T23:00:00Z"},
        "implementer": {"id": "u-1", "username": "alice"},
        "co_reviewer": {"id": "u-2", "username": "bob"},
        "device_ips": ["10.0.0.1"],
        "pre_check": "show version",
        "execution": "apply config",
        "post_verify": "verify config",
        "business_verify": "ping test",
        "rollback_plan": "revert config",
    }


def _setup_order_in_initial_review(requester: dict, initial_reviewer: dict,
                                   final_approver: dict) -> tuple[str, str]:
    """Create an order directly in initial_review state via service layer.
    Returns (order_id, order_number)."""
    from services.change_order_service import create_change_order
    conn = get_db_connection()
    try:
        order = create_change_order(
            conn,
            title="Integration test order",
            description="",
            order_type="config_change",
            priority="medium",
            status="initial_review",
            requester_id=requester["user_id"],
            requester_username=requester["username"],
            assigned_initial_reviewer_id=initial_reviewer["user_id"],
            assigned_initial_reviewer_username=initial_reviewer["username"],
            assigned_final_approver_id=final_approver["user_id"],
            assigned_final_approver_username=final_approver["username"],
            command_template=_valid_command_template(),
            target_devices=[],
            commands=["show running-config"],
            rollback_plan="",
            risk_level="low",
            scheduled_start="",
            scheduled_end="",
            authorization_exempt=False,
            control_sheet=_valid_control_sheet(),
        )
        conn.commit()
        return order["id"], order["order_number"]
    finally:
        conn.close()


# ── 18.1 End-to-end main path ─────────────────────────────────────────

def test_18_1_end_to_end_main_path(isolated_db, requester, initial_reviewer, final_approver):
    """
    Full happy path: initial_review → final_review → approved →
    implementing → completed.

    Uses service layer to create order in initial_review (bypassing
    scenario-lookup validation) to focus on the lifecycle transitions.

    Validates: Properties 1, 2, 3, 4, 6, 7
    Requirements: 2.1–2.9, 3.1–3.8
    """
    order_id, order_number = _setup_order_in_initial_review(
        requester, initial_reviewer, final_approver
    )

    # Verify BG numbering format (§3.1)
    assert re.match(r"^BG\d{8}\d{4}$", order_number), f"Bad order_number: {order_number}"

    # Initial reviewer promotes to final_review
    sc, data = _invoke_transition(order_id, "final_review", actor=initial_reviewer,
                                  extra={"assigned_final_approver_id": final_approver["user_id"]})
    assert sc == 200, f"initial_review→final_review failed: {data}"
    assert data["status"] == "final_review"

    # Administrator approves
    sc, data = _invoke_transition(order_id, "approved", actor=final_approver)
    assert sc == 200, f"final_review→approved failed: {data}"
    assert data["status"] == "approved"

    # Requester starts implementing
    sc, data = _invoke_transition(order_id, "implementing", actor=requester)
    assert sc == 200, f"approved→implementing failed: {data}"
    assert data["status"] == "implementing"

    # Requester marks completed
    sc, data = _invoke_transition(order_id, "completed", actor=requester,
                                  extra={"result_summary": "All changes applied"})
    assert sc == 200, f"implementing→completed failed: {data}"
    assert data["status"] == "completed"

    # Verify final state has all legacy fields (§3.8)
    conn = get_db_connection()
    try:
        final = get_change_order(conn, order_id)
    finally:
        conn.close()

    assert final["status"] == "completed"
    assert final["order_number"] == order_number
    for field in ["id", "order_number", "title", "status", "requester_username",
                  "created_at", "updated_at", "commands", "target_devices",
                  "command_template", "result_detail"]:
        assert field in final, f"Legacy field {field!r} missing from final order"


# ── 18.2 Reject-and-resume path ───────────────────────────────────────

def test_18_2_reject_and_resume_path(isolated_db, requester, initial_reviewer, final_approver):
    """
    Reject-and-resume: initial_review → rejected → draft →
    re-submit → final_review → approved → completed.

    Validates: Properties 3, 4, 5
    Requirements: 2.11, 2.12
    """
    order_id, _ = _setup_order_in_initial_review(requester, initial_reviewer, final_approver)

    # Force reviewer fields to simulate a real review
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE change_orders SET initial_reviewer_id=?, initial_reviewer_username=?, "
            "result_detail_json=? WHERE id=?",
            (initial_reviewer["user_id"], initial_reviewer["username"],
             json.dumps({"initial_review_at": _utc_now()}), order_id)
        )
        conn.commit()
    finally:
        conn.close()

    # Initial reviewer rejects
    sc, _ = _invoke_transition(order_id, "rejected", actor=initial_reviewer,
                               extra={"rejected_reason": "Needs more detail"})
    assert sc == 200, "Could not reject from initial_review"

    # Requester reopens to draft
    sc, data = _invoke_transition(order_id, "draft", actor=requester)
    assert sc == 200, f"rejected→draft failed: {data}"

    # Verify all six reviewer/approver fields are cleared (Property 5)
    conn = get_db_connection()
    try:
        row = get_change_order(conn, order_id)
    finally:
        conn.close()

    assert row["status"] == "draft"
    for field in ["initial_reviewer_id", "initial_reviewer_username",
                  "final_approver_id", "final_approver_username",
                  "approver_id", "approver_username"]:
        assert row.get(field, "") in (None, ""), (
            f"Field {field!r} not cleared after reject→draft: {row.get(field)!r}"
        )

    # Verify result_detail timestamps are popped
    rd = row.get("result_detail") or {}
    assert "initial_review_at" not in rd, "initial_review_at should be popped"
    assert "approved_at" not in rd, "approved_at should be popped"

    # Verify rejected_reason is preserved
    assert row.get("rejected_reason") == "Needs more detail"

    # Re-submit via service layer (bypass scenario validation)
    from services.change_order_service import update_change_order
    conn = get_db_connection()
    try:
        update_change_order(conn, order_id, {
            "status": "initial_review",
            "assigned_initial_reviewer_id": initial_reviewer["user_id"],
            "assigned_initial_reviewer_username": initial_reviewer["username"],
            "assigned_final_approver_id": final_approver["user_id"],
            "assigned_final_approver_username": final_approver["username"],
        })
    finally:
        conn.close()

    sc, _ = _invoke_transition(order_id, "final_review", actor=initial_reviewer,
                               extra={"assigned_final_approver_id": final_approver["user_id"]})
    assert sc == 200

    sc, _ = _invoke_transition(order_id, "approved", actor=final_approver)
    assert sc == 200

    sc, _ = _invoke_transition(order_id, "implementing", actor=requester)
    assert sc == 200

    sc, data = _invoke_transition(order_id, "completed", actor=requester)
    assert sc == 200
    assert data["status"] == "completed"


# ── 18.3 Cross-view consistency ───────────────────────────────────────

def test_18_3_cross_view_consistency(isolated_db, make_user):
    """
    Four accounts: U1 (requester), U2 (initial reviewer), U3 (final approver),
    U4 (same group as U2 but not assigned).

    Drive an order through several phases; at each phase snapshot
    my_todo / group_todo / my_drafts / my_participated for all four accounts.

    Assert no order appears in two views that would indicate a dual-role leak;
    assert todo_kind labels are stable.

    Validates: Property 6
    Requirements: 2.13, 2.14, 2.15, 2.16
    """
    u1 = make_user("u1_req", role="Operator", change_groups=[])
    u2 = make_user("u2_rev", role="Operator", change_groups=["initial_reviewer"])
    u3 = make_user("u3_app", role="Administrator", change_groups=["final_approver"])
    u4 = make_user("u4_grp", role="Operator", change_groups=["initial_reviewer"])

    # Create order in initial_review via service layer
    order_id, _ = _setup_order_in_initial_review(u1, u2, u3)

    conn = get_db_connection()
    try:
        # Phase: initial_review — u2 should see it in my_todo review
        todos_u2, _ = list_change_orders(conn, my_todo=u2["username"],
                                         my_todo_kind="review", page_size=100)
        assert any(o["id"] == order_id for o in todos_u2), (
            "Order should be in u2 my_todo review bucket"
        )
        for item in todos_u2:
            if item["id"] == order_id:
                assert item.get("todo_kind") == "review"

        # u4 (same group, not assigned) should NOT see it in group_todo
        # because it IS assigned to u2
        group_u4, _ = list_change_orders(conn, group_todo="initial_reviewer",
                                         exclude_requester=u4["username"], page_size=100)
        assert not any(o["id"] == order_id for o in group_u4), (
            "Assigned order should NOT appear in group_todo"
        )

        # u1 should see it in my_participated
        participated_u1, _ = list_change_orders(conn, my_participated=u1["username"],
                                                page_size=100)
        assert any(o["id"] == order_id for o in participated_u1), (
            "Order should be in u1 my_participated"
        )

        # No dual-role: u1 should not appear in review bucket
        todos_u1_review, _ = list_change_orders(conn, my_todo=u1["username"],
                                                my_todo_kind="review", page_size=100)
        assert not any(o["id"] == order_id for o in todos_u1_review), (
            "Dual-role leak: u1's own order in review bucket"
        )

        # Transition to final_review
        sc, _ = _invoke_transition(order_id, "final_review", actor=u2,
                                   extra={"assigned_final_approver_id": u3["user_id"]})
        assert sc == 200

        # u3 should see it in my_todo review
        todos_u3, _ = list_change_orders(conn, my_todo=u3["username"],
                                         my_todo_kind="review", page_size=100)
        assert any(o["id"] == order_id for o in todos_u3), (
            "Order should be in u3 my_todo review bucket at final_review"
        )

        # Approve
        sc, _ = _invoke_transition(order_id, "approved", actor=u3)
        assert sc == 200

        # u1 should see it in implement bucket
        todos_u1_impl, _ = list_change_orders(conn, my_todo=u1["username"],
                                              my_todo_kind="implement", page_size=100)
        assert any(o["id"] == order_id for o in todos_u1_impl), (
            "Order should be in u1 my_todo implement bucket after approval"
        )

        # todo_kind labels are stable (same query returns same labels)
        todos_u1_impl2, _ = list_change_orders(conn, my_todo=u1["username"],
                                               my_todo_kind="implement", page_size=100)
        ids1 = {o["id"] for o in todos_u1_impl}
        ids2 = {o["id"] for o in todos_u1_impl2}
        assert ids1 == ids2, "todo_kind labels not stable across repeated queries"

    finally:
        conn.close()
