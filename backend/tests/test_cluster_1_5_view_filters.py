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
from hypothesis import given, settings, strategies as st
from database import get_db_connection
from services.change_order_service import (
    _build_group_todo_conditions,
    get_summary,
    list_change_orders,
)

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


# ─────────────────────────────────────────────────────────────────────
# Task 16.3 — PBT: list_change_orders and get_summary produce identical
#             WHERE fragments via _build_group_todo_conditions
# ─────────────────────────────────────────────────────────────────────

# Hypothesis strategy: generate any subset of the two recognised group names
# plus arbitrary extra strings (which should produce no conditions).
_KNOWN_GROUPS = ["initial_reviewer", "final_approver"]
_group_set_st = st.frozensets(
    st.one_of(
        st.sampled_from(_KNOWN_GROUPS),
        st.text(min_size=1, max_size=20),
    ),
    min_size=0,
    max_size=4,
)
_username_st = st.one_of(st.just(""), st.text(min_size=1, max_size=30))


@given(groups=_group_set_st, exclude_requester=_username_st)
@settings(max_examples=200)
def test_p6_build_group_todo_conditions_deterministic(groups, exclude_requester):
    """
    **Validates: Requirements 2.14**

    Property: `_build_group_todo_conditions` is pure and deterministic.
    Two calls with the same (groups, exclude_requester) MUST return
    byte-identical (conditions, params) tuples.  This guarantees that
    `list_change_orders` and `get_summary` — both of which delegate to
    this helper — will always produce the same WHERE fragment for the
    same input, keeping the two views in lock-step.
    """
    result_a = _build_group_todo_conditions(set(groups), exclude_requester)
    result_b = _build_group_todo_conditions(set(groups), exclude_requester)
    assert result_a == result_b, (
        f"_build_group_todo_conditions is not deterministic for "
        f"groups={groups!r}, exclude_requester={exclude_requester!r}: "
        f"{result_a!r} != {result_b!r}"
    )


@given(groups=_group_set_st, exclude_requester=_username_st)
@settings(max_examples=200)
def test_p6_build_group_todo_conditions_fragment_contract(groups, exclude_requester):
    """
    **Validates: Requirements 2.14**

    Property: the WHERE fragment produced by `_build_group_todo_conditions`
    satisfies the group_todo contract from design.md §View Filter Semantics:

    * If neither 'initial_reviewer' nor 'final_approver' is in groups,
      the fragment MUST be the always-false sentinel ``1=0`` (no rows).
    * If 'initial_reviewer' ∈ groups, the fragment MUST reference
      ``status = 'initial_review'`` and ``assigned_initial_reviewer_id``.
    * If 'final_approver' ∈ groups, the fragment MUST reference
      ``status = 'final_review'`` and ``assigned_final_approver_id``.
    * If exclude_requester is non-empty, the fragment MUST include a
      ``requester_username != ?`` clause and the requester value MUST
      appear in params.
    """
    conds, params = _build_group_todo_conditions(set(groups), exclude_requester)
    fragment = " ".join(conds)

    has_initial = "initial_reviewer" in groups
    has_final = "final_approver" in groups

    if not has_initial and not has_final:
        assert "1=0" in fragment, (
            f"Expected always-false sentinel for empty groups, got: {fragment!r}"
        )
    else:
        if has_initial:
            assert "initial_review" in fragment, (
                f"Expected 'initial_review' in fragment for initial_reviewer group, got: {fragment!r}"
            )
            assert "assigned_initial_reviewer_id" in fragment, (
                f"Expected 'assigned_initial_reviewer_id' in fragment, got: {fragment!r}"
            )
        if has_final:
            assert "final_review" in fragment, (
                f"Expected 'final_review' in fragment for final_approver group, got: {fragment!r}"
            )
            assert "assigned_final_approver_id" in fragment, (
                f"Expected 'assigned_final_approver_id' in fragment, got: {fragment!r}"
            )
        if exclude_requester:
            assert "requester_username != ?" in fragment, (
                f"Expected requester exclusion clause, got: {fragment!r}"
            )
            assert exclude_requester in params, (
                f"Expected exclude_requester={exclude_requester!r} in params={params!r}"
            )


def test_p6_list_and_summary_group_todo_count_identical(isolated_db, make_user):
    """
    **Validates: Requirements 2.14**

    End-to-end property: for the same group_todo input, `list_change_orders`
    and `get_summary` MUST return the same count of matching orders.

    Both functions delegate to `_build_group_todo_conditions` with the same
    (groups, exclude_requester) arguments.  `get_summary` derives `groups`
    from the user's `change_groups_json` and uses `username` as
    `exclude_requester`.  The test mirrors that exact call pattern so the
    two counts are directly comparable.
    """
    # The reviewer IS the logged-in user for both list and summary calls.
    # Orders are created by a separate requester so the exclude_requester
    # filter (which removes the reviewer's own orders) does not interfere.
    u_requester = make_user("req_user", role="Operator", change_groups=[])
    u_reviewer = make_user("rev_user", role="Operator", change_groups=["initial_reviewer"])
    u_approver = make_user("app_user", role="Administrator", change_groups=["final_approver"])

    conn = get_db_connection()
    try:
        # Seed orders covering all relevant states
        seed_data = [
            # Unassigned initial_review — should appear in group_todo for initial_reviewer
            {"status": "initial_review", "assigned_initial_reviewer_id": "", "assigned_initial_reviewer_username": ""},
            {"status": "initial_review", "assigned_initial_reviewer_id": "", "assigned_initial_reviewer_username": ""},
            # Assigned initial_review — should NOT appear
            {"status": "initial_review", "assigned_initial_reviewer_id": u_reviewer["user_id"], "assigned_initial_reviewer_username": u_reviewer["username"]},
            # Unassigned final_review — should appear in group_todo for final_approver
            {"status": "final_review", "assigned_final_approver_id": "", "assigned_final_approver_username": ""},
            # Assigned final_review — should NOT appear
            {"status": "final_review", "assigned_final_approver_id": u_approver["user_id"], "assigned_final_approver_username": u_approver["username"]},
            # Other statuses — should NOT appear
            {"status": "draft"},
            {"status": "approved"},
            {"status": "completed"},
        ]
        for i, extra in enumerate(seed_data):
            _insert_raw_order(
                conn,
                idx=i,
                requester_id=u_requester["user_id"],
                requester_username=u_requester["username"],
                **extra,
            )

        # ── Test 1: initial_reviewer group ──────────────────────────────
        # get_summary uses username as exclude_requester; mirror that in list call.
        list_results, list_count = list_change_orders(
            conn,
            group_todo="initial_reviewer",
            exclude_requester=u_reviewer["username"],  # same as get_summary uses
            page_size=100,
        )
        summary = get_summary(conn, user_id=u_reviewer["user_id"], username=u_reviewer["username"])
        summary_count = summary["group_todo_count"]

        assert list_count == summary_count, (
            f"list_change_orders count ({list_count}) != get_summary group_todo_count "
            f"({summary_count}) for group='initial_reviewer'"
        )
        # Sanity: 2 unassigned initial_review rows; reviewer is not the requester so none excluded
        assert list_count == 2, f"Expected 2 unassigned initial_review rows, got {list_count}"

        # ── Test 2: final_approver group ────────────────────────────────
        list_results_fa, list_count_fa = list_change_orders(
            conn,
            group_todo="final_approver",
            exclude_requester=u_approver["username"],  # same as get_summary uses
            page_size=100,
        )
        summary_fa = get_summary(conn, user_id=u_approver["user_id"], username=u_approver["username"])
        summary_count_fa = summary_fa["group_todo_count"]

        assert list_count_fa == summary_count_fa, (
            f"list_change_orders count ({list_count_fa}) != get_summary group_todo_count "
            f"({summary_count_fa}) for group='final_approver'"
        )
        # Sanity: 1 unassigned final_review row
        assert list_count_fa == 1, f"Expected 1 unassigned final_review row, got {list_count_fa}"

        # ── Test 3: combined groups ──────────────────────────────────────
        # A user in both groups should see both unassigned initial_review and final_review
        u_both = make_user("both_user", role="Administrator", change_groups=["initial_reviewer", "final_approver"])
        list_results_both, list_count_both = list_change_orders(
            conn,
            group_todo="initial_reviewer,final_approver",
            exclude_requester=u_both["username"],  # same as get_summary uses
            page_size=100,
        )
        summary_both = get_summary(conn, user_id=u_both["user_id"], username=u_both["username"])
        summary_count_both = summary_both["group_todo_count"]

        assert list_count_both == summary_count_both, (
            f"list_change_orders count ({list_count_both}) != get_summary group_todo_count "
            f"({summary_count_both}) for combined groups"
        )
        # Sanity: 2 unassigned initial_review + 1 unassigned final_review = 3
        assert list_count_both == 3, f"Expected 3 combined unassigned rows, got {list_count_both}"

    finally:
        conn.close()
