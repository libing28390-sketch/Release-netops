"""
Phase B — Preservation baseline for §3.1 / §3.2 (main lifecycle).

**Property 2: Preservation** — BG numbering + draft→initial_review→final_review→
approved→implementing→completed stays working.

Validates: Property 7 (design.md §Correctness Properties)
Preservation: 3.1, 3.2 (bugfix.md)
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
from database import get_db_connection

# ── Property: BG Numbering Uniqueness and Sequentiality ───────────────

@given(n=st.integers(min_value=5, max_value=20))
@settings(
    max_examples=10,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p7_bg_numbering_preservation(n, isolated_db, requester):
    """
    **Validates: Requirement 3.1** — BG numbering rule: BG + YYYYMMDD + NNNN.
    Numbers MUST be unique and strictly increasing for orders created on the same day.
    """
    from services.change_order_service import create_change_order
    
    conn = get_db_connection()
    try:
        order_numbers = []
        for i in range(n):
            order = create_change_order(
                conn,
                title=f"Preservation test {i}",
                requester_id=requester["user_id"],
                requester_username=requester["username"]
            )
            num = order["order_number"]
            assert num.startswith("BG")
            assert len(num) == 14 # BG (2) + YYYYMMDD (8) + NNNN (4)
            order_numbers.append(num)
        
        # Uniqueness
        assert len(set(order_numbers)) == n
        
        # Sequentiality
        for i in range(len(order_numbers) - 1):
            curr_seq = int(order_numbers[i][-4:])
            next_seq = int(order_numbers[i+1][-4:])
            assert next_seq == curr_seq + 1
    finally:
        conn.close()

# ── Property: Main Lifecycle Happy Path ───────────────────────────────

def test_p7_main_lifecycle_happy_path_preservation(isolated_db, requester, initial_reviewer, final_approver):
    """
    **Validates: Requirement 3.2** — Happy path sequence:
    draft -> initial_review -> final_review -> approved -> implementing -> completed.
    Asserts timestamps and status changes are preserved.
    """
    from api.change_orders import api_create_change_order, api_transition_change_order, ChangeOrderCreate
    
    # 1. Create (draft)
    payload = {
        "title": "Main Path Test",
        "status": "draft",
        "assigned_initial_reviewer_id": initial_reviewer["user_id"]
    }
    res = api_create_change_order(ChangeOrderCreate(**payload), user=requester)
    order = res["data"]
    order_id = order["id"]
    assert order["status"] == "draft"
    
    # 2. To initial_review
    res = api_transition_change_order(order_id, {"status": "initial_review"}, user=requester)
    assert res["success"]
    
    # 3. To final_review (by initial_reviewer)
    # On unfixed code, this requires assigned_final_approver_id in body if not already in order
    res = api_transition_change_order(
        order_id, 
        {"status": "final_review", "assigned_final_approver_id": final_approver["user_id"]}, 
        user=initial_reviewer
    )
    assert res["success"]
    
    # 4. To approved (by final_approver)
    res = api_transition_change_order(order_id, {"status": "approved"}, user=final_approver)
    assert res["success"]
    order = res["data"]
    assert order["status"] == "approved"
    assert order["result_detail"].get("approved_at") is not None
    
    # 5. To implementing (by requester)
    res = api_transition_change_order(order_id, {"status": "implementing"}, user=requester)
    assert res["success"]
    order = res["data"]
    assert order["status"] == "implementing"
    assert order["actual_start"] is not None
    
    # 6. To completed (by requester)
    res = api_transition_change_order(order_id, {"status": "completed", "result_summary": "Done"}, user=requester)
    assert res["success"]
    order = res["data"]
    assert order["status"] == "completed"
    assert order["actual_end"] is not None
    assert order["result_summary"] == "Done"
