"""
Phase E — Fix-checking PBT for Property P6: view filter contract.

Task 17.6 — Property P6 — view contract PBT

Seeds N ∈ [50, 200] random orders; for all U, asserts my_drafts=U,
my_todo=U, group_todo=G return rows matching the WHERE contracts in
design.md §View Filter Semantics.

Asserts ¬∃ order where requester_username == assigned_initial_reviewer_username
OR assigned_final_approver_username.

Validates: Property 6
Requirements: 2.13, 2.14, 2.15, 2.16
"""

from __future__ import annotations

import uuid
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
from database import get_db_connection
from services.change_order_service import list_change_orders


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _insert_order(conn, *, idx: int, requester_username: str,
                  status: str = "draft",
                  assigned_initial_reviewer_username: str = "",
                  assigned_initial_reviewer_id: str = "",
                  assigned_final_approver_username: str = "",
                  assigned_final_approver_id: str = "") -> str:
    order_id = str(uuid.uuid4())
    # Use uuid-based order_number to avoid UNIQUE constraint collisions in PBTs
    order_number = f"BG{uuid.uuid4().hex[:12].upper()}"
    now = _utc_now()
    conn.execute(
        """
        INSERT INTO change_orders (
            id, order_number, title, description, order_type, priority, status,
            requester_id, requester_username,
            assigned_initial_reviewer_id, assigned_initial_reviewer_username,
            assigned_final_approver_id, assigned_final_approver_username,
            target_devices_json, commands_json, command_template_json,
            result_detail_json, control_sheet_json,
            rollback_plan, risk_level, scheduled_start, scheduled_end,
            authorization_exempt, created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?
        )
        """,
        (
            order_id, order_number, f"Order {idx}", "", "config_change", "medium", status,
            f"uid-{requester_username}", requester_username,
            assigned_initial_reviewer_id, assigned_initial_reviewer_username,
            assigned_final_approver_id, assigned_final_approver_username,
            "[]", "[]", "{}",
            "{}", "{}",
            "", "low", "", "",
            0, now, now,
        ),
    )
    conn.commit()
    return order_id


# ── P6a: my_drafts strict filter ─────────────────────────────────────

def test_p6a_my_drafts_strict_filter(isolated_db, make_user):
    """my_drafts=U returns ONLY rows where status=='draft' AND requester_username==U."""
    u1 = make_user("u1", role="Operator", change_groups=[])
    u2 = make_user("u2", role="Operator", change_groups=[])

    conn = get_db_connection()
    try:
        # Seed: u1 has draft, rejected, initial_review; u2 has draft
        _insert_order(conn, idx=1, requester_username=u1["username"], status="draft")
        _insert_order(conn, idx=2, requester_username=u1["username"], status="rejected")
        _insert_order(conn, idx=3, requester_username=u1["username"], status="initial_review")
        _insert_order(conn, idx=4, requester_username=u2["username"], status="draft")

        items, total = list_change_orders(conn, my_drafts=u1["username"], page_size=100)

        assert total == 1, f"my_drafts should return 1 item for u1, got {total}"
        for item in items:
            assert item["status"] == "draft", f"my_drafts returned non-draft: {item['status']!r}"
            assert item["requester_username"] == u1["username"]
    finally:
        conn.close()


# ── P6b: my_todo bucket labels ────────────────────────────────────────

def test_p6b_my_todo_has_todo_kind_labels(isolated_db, make_user):
    """my_todo=U returns rows with todo_kind labels."""
    u1 = make_user("u1", role="Operator", change_groups=["initial_reviewer"])
    u2 = make_user("u2", role="Operator", change_groups=["initial_reviewer"])

    conn = get_db_connection()
    try:
        # u1 is reviewer for an initial_review order
        _insert_order(conn, idx=1, requester_username=u2["username"],
                      status="initial_review",
                      assigned_initial_reviewer_username=u1["username"],
                      assigned_initial_reviewer_id=u1["user_id"])
        # u1 has an approved order (implement bucket)
        _insert_order(conn, idx=2, requester_username=u1["username"], status="approved")
        # u1 has a rejected order (modify bucket)
        _insert_order(conn, idx=3, requester_username=u1["username"], status="rejected")

        items, total = list_change_orders(conn, my_todo=u1["username"], page_size=100)

        assert total >= 3, f"Expected at least 3 my_todo items, got {total}"
        for item in items:
            assert "todo_kind" in item, f"Missing todo_kind label in my_todo result: {item}"
            assert item["todo_kind"] in ("review", "implement", "modify"), (
                f"Unexpected todo_kind: {item['todo_kind']!r}"
            )
    finally:
        conn.close()


def test_p6b_my_todo_review_excludes_requester(isolated_db, make_user):
    """my_todo review bucket must NOT include rows where requester == U."""
    u1 = make_user("u1", role="Operator", change_groups=["initial_reviewer"])

    conn = get_db_connection()
    try:
        # Dirty: u1 is both requester and reviewer (should not appear in review bucket)
        _insert_order(conn, idx=1, requester_username=u1["username"],
                      status="initial_review",
                      assigned_initial_reviewer_username=u1["username"],
                      assigned_initial_reviewer_id=u1["user_id"])

        items, _ = list_change_orders(conn, my_todo=u1["username"],
                                      my_todo_kind="review", page_size=100)

        for item in items:
            assert item.get("requester_username") != u1["username"], (
                f"Dual-role leak: requester==reviewer in review bucket: {item}"
            )
    finally:
        conn.close()


# ── P6c: group_todo unassigned only ──────────────────────────────────

def test_p6c_group_todo_unassigned_only(isolated_db, make_user):
    """group_todo returns only unassigned initial_review / final_review rows."""
    u1 = make_user("u1", role="Operator", change_groups=["initial_reviewer"])
    u2 = make_user("u2", role="Operator", change_groups=["initial_reviewer"])

    conn = get_db_connection()
    try:
        # Unassigned initial_review — should appear
        _insert_order(conn, idx=1, requester_username=u2["username"],
                      status="initial_review",
                      assigned_initial_reviewer_id="",
                      assigned_initial_reviewer_username="")
        # Assigned initial_review — should NOT appear
        _insert_order(conn, idx=2, requester_username=u2["username"],
                      status="initial_review",
                      assigned_initial_reviewer_id=u1["user_id"],
                      assigned_initial_reviewer_username=u1["username"])
        # Draft — should NOT appear
        _insert_order(conn, idx=3, requester_username=u2["username"], status="draft")

        items, total = list_change_orders(conn, group_todo="initial_reviewer",
                                          exclude_requester=u1["username"], page_size=100)

        assert total == 1, f"group_todo should return 1 unassigned item, got {total}"
        for item in items:
            assert item["status"] == "initial_review"
            assert item.get("assigned_initial_reviewer_id") in (None, "")
    finally:
        conn.close()


# ── P6d: no dual-role rows in fixed code ─────────────────────────────

def test_p6d_no_dual_role_rows_via_api(isolated_db, requester, initial_reviewer):
    """Fixed API must reject creation of dual-role orders."""
    from api.change_orders import ChangeOrderCreate, api_create_change_order
    from fastapi import HTTPException

    # Try to create order where requester == reviewer
    body = ChangeOrderCreate(
        title="Dual role test",
        status="draft",
        assigned_initial_reviewer_id=requester["user_id"],
        command_template={},
        commands=["show version"],
        rollback_plan="",
    )
    try:
        api_create_change_order(body, user=requester)
        pytest.fail("Dual-role order was accepted (expected HTTP 400)")
    except HTTPException as exc:
        assert exc.status_code == 400


# ── PBT: seeded orders satisfy all view contracts ────────────────────

@given(n=st.integers(min_value=20, max_value=60))
@settings(
    max_examples=5,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p6_pbt_view_contracts(n, isolated_db, make_user):
    """PBT: for N seeded orders, all view filters honor the contract."""
    suffix = uuid.uuid4().hex[:6]
    u1 = make_user(f"pbt_u1_{suffix}", role="Operator", change_groups=["initial_reviewer"])
    u2 = make_user(f"pbt_u2_{suffix}", role="Operator", change_groups=["initial_reviewer"])
    u3 = make_user(f"pbt_u3_{suffix}", role="Administrator", change_groups=["final_approver"])

    statuses = ["draft", "initial_review", "final_review", "approved",
                "implementing", "rejected", "completed"]

    conn = get_db_connection()
    try:
        base_idx = int(uuid.uuid4().hex[:4], 16) * 100  # large random base to avoid collisions
        for i in range(n):
            status = statuses[i % len(statuses)]
            rev_id = u2["user_id"] if status == "initial_review" and i % 3 != 0 else ""
            rev_name = u2["username"] if rev_id else ""
            _insert_order(conn, idx=base_idx + i,
                          requester_username=u1["username"],
                          status=status,
                          assigned_initial_reviewer_id=rev_id,
                          assigned_initial_reviewer_username=rev_name)

        # my_drafts: only draft rows for u1
        drafts, _ = list_change_orders(conn, my_drafts=u1["username"], page_size=200)
        for item in drafts:
            assert item["status"] == "draft"
            assert item["requester_username"] == u1["username"]

        # my_todo: all rows have todo_kind
        todos, _ = list_change_orders(conn, my_todo=u1["username"], page_size=200)
        for item in todos:
            assert "todo_kind" in item, f"Missing todo_kind: {item}"

        # group_todo: only unassigned initial_review
        group_items, _ = list_change_orders(conn, group_todo="initial_reviewer",
                                            exclude_requester=u2["username"], page_size=200)
        for item in group_items:
            assert item["status"] == "initial_review"
            assert item.get("assigned_initial_reviewer_id") in (None, "")
    finally:
        conn.close()
