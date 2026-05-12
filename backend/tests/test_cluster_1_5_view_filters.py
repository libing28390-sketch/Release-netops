"""
Phase A — Exploration test for cluster 1.5 (view filter semantics).

**Property 1: Bug Condition** — `my_drafts` / `my_todo` / `group_todo` return rows
that violate the contract; dual-role rows leak into two views.

Validates: Property 6 (design.md §Correctness Properties)
Bug_Condition: `C5(input)` in `design.md §Bug Details`
Requirements: 1.13, 1.14, 1.15, 1.16 (bugfix.md)
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
from database import get_db_connection
from services.change_order_service import list_change_orders

# ── Helpers for fixture seeding ───────────────────────────────────────

def _insert_raw_order(conn, **fields):
    """Bypass API validation to seed 'dirty' or specific historical states."""
    import uuid
    from datetime import datetime, timezone
    
    order_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    defaults = {
        "id": order_id,
        "order_number": f"BG20250101{fields.get('idx', 0):04d}",
        "title": "Seed Order",
        "description": "",
        "status": "draft",
        "requester_id": "u-1",
        "requester_username": "alice",
        "assigned_initial_reviewer_id": "",
        "assigned_initial_reviewer_username": "",
        "assigned_final_approver_id": "",
        "assigned_final_approver_username": "",
        "created_at": now,
        "updated_at": now,
        "priority": "medium",
        "order_type": "config_change",
        "risk_level": "low",
        "target_devices_json": "[]",
        "commands_json": "[]",
        "command_template_json": "{}",
        "result_detail_json": "{}",
    }
    defaults.update(fields)
    defaults.pop("idx", None)
    
    keys = list(defaults.keys())
    placeholders = ", ".join(["?"] * len(keys))
    sql = f"INSERT INTO change_orders ({', '.join(keys)}) VALUES ({placeholders})"
    conn.execute(sql, tuple(defaults[k] for k in keys))
    conn.commit()
    return order_id

# ─────────────────────────────────────────────────────────────────────
# Property P6 — View Filter Contracts
# ─────────────────────────────────────────────────────────────────────

def test_p6_view_filters_honor_contract(isolated_db, make_user):
    seed_count = 30
    """
    **Validates: Property 6** — View filters MUST return rows matching the 
    contracted union and carrying `todo_kind` labels.
    """
    u1 = make_user("user1", role="Operator", change_groups=["initial_reviewer"])
    u2 = make_user("user2", role="Operator", change_groups=["initial_reviewer"])
    u3 = make_user("user3", role="Administrator", change_groups=["final_approver"])
    
    conn = get_db_connection()
    try:
        # Seed a mix of orders
        statuses = ["draft", "initial_review", "final_review", "approved", "implementing", "rejected", "completed"]
        for i in range(seed_count):
            status = statuses[i % len(statuses)]
            
            # Randomly assign roles to simulate various scenarios
            # requester is mostly user1
            # initial_reviewer might be user2 or user1 (dirty case)
            # final_approver might be user3
            
            payload = {
                "idx": i,
                "status": status,
                "requester_id": u1["user_id"],
                "requester_username": u1["username"],
            }
            
            if status == "initial_review":
                if i % 5 == 0: # Dirty dual-role case
                    payload["assigned_initial_reviewer_id"] = u1["user_id"]
                    payload["assigned_initial_reviewer_username"] = u1["username"]
                elif i % 5 == 1: # Unassigned (for group_todo)
                    pass
                else:
                    payload["assigned_initial_reviewer_id"] = u2["user_id"]
                    payload["assigned_initial_reviewer_username"] = u2["username"]
            
            if status == "final_review":
                if i % 5 == 2: # Unassigned
                    pass
                else:
                    payload["assigned_final_approver_id"] = u3["user_id"]
                    payload["assigned_final_approver_username"] = u3["username"]

            _insert_raw_order(conn, **payload)
        
        # Test my_todo for user1
        # Expectation: user1 should see their own drafts, approved, implementing, rejected
        # AND if they were assigned as reviewer/approver (though they shouldn't be in fixed)
        items, _ = list_change_orders(conn, my_todo=u1["username"])
        
        # Sub-property (ii) check: label must exist
        for item in items:
            assert "todo_kind" in item, "Missing todo_kind label in my_todo result"
        
        # Sub-property (iv) check: no dual-role rows in fixed code
        # On unfixed code, this will fail if we seeded dual-role rows.
        for item in items:
            req = item.get("requester_username")
            rev = item.get("assigned_initial_reviewer_username")
            app = item.get("assigned_final_approver_username")
            assert not (req == rev and rev != ""), f"Dual-role leak: requester {req} == reviewer {rev}"
            assert not (req == app and app != ""), f"Dual-role leak: requester {req} == approver {app}"
            
        # Test group_todo for user2 (initial_reviewer group)
        # Expectation: should see status='initial_review' and assigned_initial_reviewer_id is NULL/empty
        group_items, _ = list_change_orders(conn, group_todo="initial_reviewer", exclude_requester=u2["username"])
        for item in group_items:
            assert item["status"] == "initial_review"
            assert item.get("assigned_initial_reviewer_id") in (None, "", "null")

        # Test my_drafts for user1
        draft_items, _ = list_change_orders(conn, my_drafts=u1["username"])
        for item in draft_items:
            assert item["status"] == "draft"
            assert item["requester_username"] == u1["username"]

    finally:
        conn.close()

def test_c5_dual_role_bypass_via_put(isolated_db, make_user):
    """
    **Validates: Property 6 (sub-clause iv)** — `PUT /api/change-orders/{id}`
    MUST reject if requester is also the assigned reviewer. 
    Unfixed code allows this because PUT lacks the check.
    """
    from api.change_orders import ChangeOrderCreate, api_create_change_order, api_update_change_order, ChangeOrderUpdate
    
    u1 = make_user("user1", role="Operator", change_groups=["initial_reviewer"])
    u2 = make_user("user2", role="Operator", change_groups=["initial_reviewer"])
    
    # 1. Create a legal order
    payload = {
        "title": "Dual role test",
        "status": "draft",
        "assigned_initial_reviewer_id": u2["user_id"], # Legal
        "command_template": {},
        "commands": []
    }
    body = ChangeOrderCreate(**payload)
    res = api_create_change_order(body, user=u1)
    order_id = res["data"]["id"]
    
    # 2. Update to dual-role via PUT
    # This SHOULD throw 400 in fixed code (Task 12.1)
    update_payload = {
        "assigned_initial_reviewer_id": u1["user_id"] # Dirty!
    }
    update_body = ChangeOrderUpdate(**update_payload)
    
    try:
        api_update_change_order(order_id, update_body, user=u1)
        # If it reaches here, it bypasses the check (Bug exists)
        pytest.fail("Dual-role bypass via PUT was accepted (expected HTTP 400)")
    except Exception as exc:
        if hasattr(exc, "status_code"):
            assert exc.status_code == 400
        else:
            raise
