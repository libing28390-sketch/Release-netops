"""
Phase B — Preservation baseline for §3.9 / §3.10 / §3.11.

**Property 2: Preservation** — The following contracts MUST remain untouched
by any bugfix work:

  §3.9  /api/change-order-templates  CRUD
  §3.10 /api/change-orders/{id}/bookmark  +  /api/change-orders-bookmarks
  §3.11 /api/change-orders/validate-ticket/{order_number}

Observation-first methodology:
  - All tests run on UNFIXED code.
  - EXPECTED OUTCOME: PASS (these are preservation baselines).

Validates: Property 7 (design.md §Correctness Properties)
Preservation: 3.9, 3.10, 3.11 (bugfix.md)
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from database import get_db_connection
from services.change_order_service import (
    create_change_order,
    delete_template,
    get_template,
    get_user_bookmarks,
    list_templates,
    save_order_as_template,
    toggle_bookmark,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso_offset(delta_seconds: int) -> str:
    """Return an ISO-8601 UTC timestamp offset by *delta_seconds* from now."""
    dt = datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _make_draft_order(conn, requester: dict, **kwargs) -> dict:
    """Insert a minimal draft change order and return the persisted dict."""
    return create_change_order(
        conn,
        title=kwargs.get("title", f"Preservation order {uuid.uuid4().hex[:6]}"),
        description=kwargs.get("description", ""),
        requester_id=requester["user_id"],
        requester_username=requester["username"],
        status="draft",
        scheduled_start=kwargs.get("scheduled_start", ""),
        scheduled_end=kwargs.get("scheduled_end", ""),
    )


# ─────────────────────────────────────────────────────────────────────────────
# §3.9  Template CRUD round-trip
# ─────────────────────────────────────────────────────────────────────────────

# Hypothesis strategies for random template payloads
_template_name_st = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters=" _-"),
    min_size=1,
    max_size=40,
).filter(lambda s: s.strip())

_template_desc_st = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters=" _-."),
    min_size=0,
    max_size=120,
)


@given(
    name=_template_name_st,
    description=_template_desc_st,
)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p7_template_crud_round_trip(name, description, isolated_db, requester):
    """
    §3.9 — Template CRUD round-trip: POST → GET → LIST → DELETE.

    Invariants:
      1. save_order_as_template returns an id and the given name.
      2. get_template(id) returns the same name and description.
      3. list_templates() contains the new template.
      4. delete_template(id) returns True and the template is gone.
      5. get_template(id) returns None after deletion.
      6. list_templates() no longer contains the deleted template.
    """
    conn = get_db_connection()
    try:
        # Create a source order to save as template
        order = _make_draft_order(conn, requester)
        order_id = order["id"]

        # POST (save as template)
        tpl = save_order_as_template(
            conn,
            name=name,
            description=description,
            order=order,
            creator_id=requester["user_id"],
            creator_username=requester["username"],
        )

        # Invariant 1: returned dict has id and name
        assert tpl.get("id"), "Template id must be non-empty"
        assert tpl.get("name") == name, f"Expected name={name!r}, got {tpl.get('name')!r}"

        tpl_id = tpl["id"]

        # GET
        fetched = get_template(conn, tpl_id)
        assert fetched is not None, "get_template must return the saved template"

        # Invariant 2: name and description round-trip
        assert fetched["name"] == name
        assert fetched.get("description", "") == description

        # LIST
        all_tpls = list_templates(conn)
        ids_in_list = [t["id"] for t in all_tpls]

        # Invariant 3: template appears in list
        assert tpl_id in ids_in_list, "Newly saved template must appear in list_templates()"

        # DELETE
        deleted = delete_template(conn, tpl_id)

        # Invariant 4: delete returns True
        assert deleted is True, "delete_template must return True for an existing template"

        # Invariant 5: get returns None after deletion
        assert get_template(conn, tpl_id) is None, "get_template must return None after deletion"

        # Invariant 6: list no longer contains the template
        remaining_ids = [t["id"] for t in list_templates(conn)]
        assert tpl_id not in remaining_ids, "Deleted template must not appear in list_templates()"
    finally:
        conn.close()


def test_p7_template_list_mine_filter(isolated_db, make_user):
    """
    §3.9 — list_templates with creator_id filter returns only that creator's templates.
    """
    suffix = uuid.uuid4().hex[:8]
    user_a = make_user(f"tpl_user_a_{suffix}", role="Operator")
    user_b = make_user(f"tpl_user_b_{suffix}", role="Operator")

    conn = get_db_connection()
    try:
        order_a = _make_draft_order(conn, user_a)
        order_b = _make_draft_order(conn, user_b)

        save_order_as_template(
            conn,
            name="Template A",
            description="",
            order=order_a,
            creator_id=user_a["user_id"],
            creator_username=user_a["username"],
        )
        save_order_as_template(
            conn,
            name="Template B",
            description="",
            order=order_b,
            creator_id=user_b["user_id"],
            creator_username=user_b["username"],
        )

        mine_a = list_templates(conn, creator_id=user_a["user_id"])
        mine_b = list_templates(conn, creator_id=user_b["user_id"])
        all_tpls = list_templates(conn)

        assert len(mine_a) == 1
        assert mine_a[0]["name"] == "Template A"

        assert len(mine_b) == 1
        assert mine_b[0]["name"] == "Template B"

        assert len(all_tpls) == 2
    finally:
        conn.close()


def test_p7_template_delete_nonexistent_returns_false(isolated_db):
    """
    §3.9 — Deleting a non-existent template returns False (no crash).
    """
    conn = get_db_connection()
    try:
        result = delete_template(conn, "nonexistent-id-xyz")
        assert result is False
    finally:
        conn.close()


def test_p7_template_get_nonexistent_returns_none(isolated_db):
    """
    §3.9 — Getting a non-existent template returns None (no crash).
    """
    conn = get_db_connection()
    try:
        result = get_template(conn, "nonexistent-id-xyz")
        assert result is None
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# §3.10  Bookmark toggle idempotency
# ─────────────────────────────────────────────────────────────────────────────

def test_p7_bookmark_toggle_basic(isolated_db, requester):
    """
    §3.10 — Basic bookmark toggle: add then remove.

    Invariants:
      1. First toggle returns True (bookmarked).
      2. get_user_bookmarks contains the order_id.
      3. Second toggle returns False (removed).
      4. get_user_bookmarks no longer contains the order_id.
    """
    conn = get_db_connection()
    try:
        order = _make_draft_order(conn, requester)
        order_id = order["id"]
        user_id = requester["user_id"]

        # First toggle → bookmark added
        result1 = toggle_bookmark(conn, user_id, order_id)
        assert result1 is True, "First toggle must return True (bookmarked)"

        bookmarks = get_user_bookmarks(conn, user_id)
        assert order_id in bookmarks, "order_id must appear in bookmarks after first toggle"

        # Second toggle → bookmark removed
        result2 = toggle_bookmark(conn, user_id, order_id)
        assert result2 is False, "Second toggle must return False (removed)"

        bookmarks_after = get_user_bookmarks(conn, user_id)
        assert order_id not in bookmarks_after, "order_id must not appear in bookmarks after second toggle"
    finally:
        conn.close()


@given(n=st.integers(min_value=2, max_value=8))
@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p7_bookmark_toggle_idempotency(n, isolated_db, requester):
    """
    §3.10 — Bookmark toggle idempotency: toggling an even number of times
    yields the same membership set as the initial state (not bookmarked).
    Toggling an odd number of times yields the bookmarked state.

    Invariant: POST bookmark twice → same membership set as before any toggle.
    """
    conn = get_db_connection()
    try:
        order = _make_draft_order(conn, requester)
        order_id = order["id"]
        user_id = requester["user_id"]

        # Perform n toggles
        last_result = None
        for _ in range(n):
            last_result = toggle_bookmark(conn, user_id, order_id)

        bookmarks = get_user_bookmarks(conn, user_id)

        if n % 2 == 0:
            # Even number of toggles → back to original (not bookmarked)
            assert order_id not in bookmarks, (
                f"After {n} (even) toggles, order must NOT be bookmarked"
            )
            assert last_result is False
        else:
            # Odd number of toggles → bookmarked
            assert order_id in bookmarks, (
                f"After {n} (odd) toggles, order MUST be bookmarked"
            )
            assert last_result is True
    finally:
        conn.close()


def test_p7_bookmark_multiple_orders_independent(isolated_db, requester):
    """
    §3.10 — Bookmarking one order does not affect bookmarks for other orders.
    """
    conn = get_db_connection()
    try:
        order_a = _make_draft_order(conn, requester, title="Order A")
        order_b = _make_draft_order(conn, requester, title="Order B")
        order_c = _make_draft_order(conn, requester, title="Order C")
        user_id = requester["user_id"]

        # Bookmark A and C, not B
        toggle_bookmark(conn, user_id, order_a["id"])
        toggle_bookmark(conn, user_id, order_c["id"])

        bookmarks = get_user_bookmarks(conn, user_id)

        assert order_a["id"] in bookmarks
        assert order_b["id"] not in bookmarks
        assert order_c["id"] in bookmarks

        # Remove A
        toggle_bookmark(conn, user_id, order_a["id"])
        bookmarks_after = get_user_bookmarks(conn, user_id)

        assert order_a["id"] not in bookmarks_after
        assert order_b["id"] not in bookmarks_after
        assert order_c["id"] in bookmarks_after
    finally:
        conn.close()


def test_p7_bookmark_user_isolation(isolated_db, make_user):
    """
    §3.10 — Bookmarks are per-user: user A's bookmarks do not affect user B's.
    """
    suffix = uuid.uuid4().hex[:8]
    user_a = make_user(f"bm_user_a_{suffix}", role="Operator")
    user_b = make_user(f"bm_user_b_{suffix}", role="Operator")

    conn = get_db_connection()
    try:
        order = _make_draft_order(conn, user_a)
        order_id = order["id"]

        # Only user_a bookmarks the order
        toggle_bookmark(conn, user_a["user_id"], order_id)

        bm_a = get_user_bookmarks(conn, user_a["user_id"])
        bm_b = get_user_bookmarks(conn, user_b["user_id"])

        assert order_id in bm_a
        assert order_id not in bm_b
    finally:
        conn.close()


def test_p7_bookmark_api_toggle_endpoint(isolated_db, requester):
    """
    §3.10 — api_toggle_bookmark endpoint returns correct bookmarked flag.
    """
    from api.change_orders import api_toggle_bookmark, api_get_my_bookmarks

    conn = get_db_connection()
    try:
        order = _make_draft_order(conn, requester)
        order_id = order["id"]
    finally:
        conn.close()

    # First call → bookmarked
    res1 = api_toggle_bookmark(order_id, user=requester)
    assert res1["success"] is True
    assert res1["data"]["bookmarked"] is True

    # Second call → removed
    res2 = api_toggle_bookmark(order_id, user=requester)
    assert res2["success"] is True
    assert res2["data"]["bookmarked"] is False

    # GET bookmarks → empty
    res3 = api_get_my_bookmarks(user=requester)
    assert res3["success"] is True
    assert order_id not in res3["data"]

    # Third call → bookmarked again
    res4 = api_toggle_bookmark(order_id, user=requester)
    assert res4["data"]["bookmarked"] is True

    # GET bookmarks → contains order
    res5 = api_get_my_bookmarks(user=requester)
    assert order_id in res5["data"]


# ─────────────────────────────────────────────────────────────────────────────
# §3.11  validate-ticket logic
# ─────────────────────────────────────────────────────────────────────────────

def _insert_order_with_status(conn, requester: dict, status: str,
                               scheduled_start: str = "",
                               scheduled_end: str = "") -> dict:
    """Create a draft order then directly update its status and schedule."""
    order = _make_draft_order(
        conn, requester,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    # Directly update status to bypass transition rules (we're testing validate-ticket, not transitions)
    conn.execute(
        "UPDATE change_orders SET status = ?, scheduled_start = ?, scheduled_end = ? WHERE id = ?",
        (status, scheduled_start, scheduled_end, order["id"]),
    )
    conn.commit()
    # Re-fetch
    row = conn.execute("SELECT * FROM change_orders WHERE id = ?", (order["id"],)).fetchone()
    return dict(row)


def test_p7_validate_ticket_approved_within_window(isolated_db, requester):
    """
    §3.11 — status=approved + within scheduled window → valid=True.
    """
    from api.change_orders import api_validate_change_ticket

    start = _iso_offset(-3600)   # 1 hour ago
    end = _iso_offset(3600)      # 1 hour from now

    conn = get_db_connection()
    try:
        order = _insert_order_with_status(
            conn, requester, "approved",
            scheduled_start=start,
            scheduled_end=end,
        )
        order_number = order["order_number"]
    finally:
        conn.close()

    res = api_validate_change_ticket(order_number, user=requester)
    data = res["data"]

    assert data["found"] is True
    assert data["valid"] is True
    assert data["reason"] == "ok"
    assert data["status"] == "approved"


def test_p7_validate_ticket_implementing_within_window(isolated_db, requester):
    """
    §3.11 — status=implementing + within scheduled window → valid=True.
    """
    from api.change_orders import api_validate_change_ticket

    start = _iso_offset(-1800)
    end = _iso_offset(1800)

    conn = get_db_connection()
    try:
        order = _insert_order_with_status(
            conn, requester, "implementing",
            scheduled_start=start,
            scheduled_end=end,
        )
        order_number = order["order_number"]
    finally:
        conn.close()

    res = api_validate_change_ticket(order_number, user=requester)
    data = res["data"]

    assert data["found"] is True
    assert data["valid"] is True
    assert data["reason"] == "ok"
    assert data["status"] == "implementing"


@given(
    status=st.sampled_from([
        "draft", "initial_review", "final_review",
        "completed", "rejected", "cancelled",
        "rollback_in_progress", "rolled_back", "failed",
    ])
)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p7_validate_ticket_non_executable_status_invalid(status, isolated_db, requester):
    """
    §3.11 — Any status outside {approved, implementing} → valid=False, reason=invalid_status.
    """
    from api.change_orders import api_validate_change_ticket

    start = _iso_offset(-3600)
    end = _iso_offset(3600)

    conn = get_db_connection()
    try:
        order = _insert_order_with_status(
            conn, requester, status,
            scheduled_start=start,
            scheduled_end=end,
        )
        order_number = order["order_number"]
    finally:
        conn.close()

    res = api_validate_change_ticket(order_number, user=requester)
    data = res["data"]

    assert data["found"] is True
    assert data["valid"] is False
    assert data["reason"] == "invalid_status"


def test_p7_validate_ticket_window_not_started(isolated_db, requester):
    """
    §3.11 — status=approved but scheduled_start is in the future → valid=False, reason=not_started.
    """
    from api.change_orders import api_validate_change_ticket

    start = _iso_offset(7200)    # 2 hours from now
    end = _iso_offset(10800)     # 3 hours from now

    conn = get_db_connection()
    try:
        order = _insert_order_with_status(
            conn, requester, "approved",
            scheduled_start=start,
            scheduled_end=end,
        )
        order_number = order["order_number"]
    finally:
        conn.close()

    res = api_validate_change_ticket(order_number, user=requester)
    data = res["data"]

    assert data["found"] is True
    assert data["valid"] is False
    assert data["reason"] == "not_started"


def test_p7_validate_ticket_window_expired(isolated_db, requester):
    """
    §3.11 — status=approved but scheduled_end is in the past → valid=False, reason=expired.
    """
    from api.change_orders import api_validate_change_ticket

    start = _iso_offset(-7200)   # 2 hours ago
    end = _iso_offset(-3600)     # 1 hour ago

    conn = get_db_connection()
    try:
        order = _insert_order_with_status(
            conn, requester, "approved",
            scheduled_start=start,
            scheduled_end=end,
        )
        order_number = order["order_number"]
    finally:
        conn.close()

    res = api_validate_change_ticket(order_number, user=requester)
    data = res["data"]

    assert data["found"] is True
    assert data["valid"] is False
    assert data["reason"] == "expired"


def test_p7_validate_ticket_not_found(isolated_db, requester):
    """
    §3.11 — Non-existent order_number → found=False, valid=False, reason=not_found.
    """
    from api.change_orders import api_validate_change_ticket

    res = api_validate_change_ticket("BG99999999ZZZZ", user=requester)
    data = res["data"]

    assert data["found"] is False
    assert data["valid"] is False
    assert data["reason"] == "not_found"


def test_p7_validate_ticket_no_window_approved(isolated_db, requester):
    """
    §3.11 — status=approved with no scheduled window → valid=True (no time constraint).
    """
    from api.change_orders import api_validate_change_ticket

    conn = get_db_connection()
    try:
        order = _insert_order_with_status(
            conn, requester, "approved",
            scheduled_start="",
            scheduled_end="",
        )
        order_number = order["order_number"]
    finally:
        conn.close()

    res = api_validate_change_ticket(order_number, user=requester)
    data = res["data"]

    assert data["found"] is True
    assert data["valid"] is True
    assert data["reason"] == "ok"


@given(
    status=st.sampled_from(["approved", "implementing"]),
    start_offset=st.integers(min_value=-7200, max_value=-60),   # started in the past
    duration=st.integers(min_value=120, max_value=14400),        # window still open
)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p7_validate_ticket_pbt_valid_window(
    status, start_offset, duration, isolated_db, requester
):
    """
    §3.11 — PBT: for status ∈ {approved, implementing} and any window that
    started in the past and ends in the future → valid=True.
    """
    from api.change_orders import api_validate_change_ticket

    start = _iso_offset(start_offset)
    end = _iso_offset(start_offset + duration)

    # Ensure end is in the future
    if start_offset + duration <= 0:
        return  # skip degenerate case

    conn = get_db_connection()
    try:
        order = _insert_order_with_status(
            conn, requester, status,
            scheduled_start=start,
            scheduled_end=end,
        )
        order_number = order["order_number"]
    finally:
        conn.close()

    res = api_validate_change_ticket(order_number, user=requester)
    data = res["data"]

    assert data["found"] is True
    assert data["valid"] is True, (
        f"Expected valid=True for status={status!r}, "
        f"start_offset={start_offset}, duration={duration}, "
        f"but got valid=False reason={data.get('reason')!r}"
    )


@given(
    status=st.sampled_from(["approved", "implementing"]),
    end_offset=st.integers(min_value=-7200, max_value=-60),  # window already closed
)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p7_validate_ticket_pbt_expired_window(
    status, end_offset, isolated_db, requester
):
    """
    §3.11 — PBT: for status ∈ {approved, implementing} and a window that
    ended in the past → valid=False, reason=expired.
    """
    from api.change_orders import api_validate_change_ticket

    start = _iso_offset(end_offset - 3600)  # started before end
    end = _iso_offset(end_offset)

    conn = get_db_connection()
    try:
        order = _insert_order_with_status(
            conn, requester, status,
            scheduled_start=start,
            scheduled_end=end,
        )
        order_number = order["order_number"]
    finally:
        conn.close()

    res = api_validate_change_ticket(order_number, user=requester)
    data = res["data"]

    assert data["found"] is True
    assert data["valid"] is False
    assert data["reason"] == "expired", (
        f"Expected reason=expired for status={status!r}, end_offset={end_offset}, "
        f"but got reason={data.get('reason')!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# §3.9  Template API endpoint round-trip (via handler functions)
# ─────────────────────────────────────────────────────────────────────────────

def test_p7_template_api_crud_round_trip(isolated_db, requester):
    """
    §3.9 — Full CRUD via API handler functions:
    POST (save_as_template) → GET → LIST → DELETE.
    """
    from api.change_orders import (
        api_delete_template,
        api_get_template,
        api_list_templates,
        api_save_as_template,
    )

    conn = get_db_connection()
    try:
        order = _make_draft_order(conn, requester)
        order_id = order["id"]
    finally:
        conn.close()

    # POST
    body = {"order_id": order_id, "name": "My Template", "description": "Test desc"}
    res_post = api_save_as_template(body=body, user=requester)
    assert res_post["success"] is True
    tpl_id = res_post["data"]["id"]
    assert tpl_id

    # GET
    res_get = api_get_template(tpl_id, user=requester)
    assert res_get["success"] is True
    assert res_get["data"]["name"] == "My Template"
    assert res_get["data"]["description"] == "Test desc"

    # LIST
    res_list = api_list_templates(mine="", user=requester)
    assert res_list["success"] is True
    ids = [t["id"] for t in res_list["data"]]
    assert tpl_id in ids

    # LIST mine=1
    res_mine = api_list_templates(mine="1", user=requester)
    assert res_mine["success"] is True
    mine_ids = [t["id"] for t in res_mine["data"]]
    assert tpl_id in mine_ids

    # DELETE
    res_del = api_delete_template(tpl_id, user=requester)
    assert res_del["success"] is True

    # GET after delete → 404
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        api_get_template(tpl_id, user=requester)
    assert exc_info.value.status_code == 404

    # LIST after delete → not present
    res_list2 = api_list_templates(mine="", user=requester)
    ids2 = [t["id"] for t in res_list2["data"]]
    assert tpl_id not in ids2


def test_p7_template_save_requires_order_id_and_name(isolated_db, requester):
    """
    §3.9 — POST /change-order-templates without order_id or name → HTTP 400.
    """
    from api.change_orders import api_save_as_template
    from fastapi import HTTPException

    # Missing name
    with pytest.raises(HTTPException) as exc_info:
        api_save_as_template(body={"order_id": "some-id", "name": ""}, user=requester)
    assert exc_info.value.status_code == 400

    # Missing order_id
    with pytest.raises(HTTPException) as exc_info:
        api_save_as_template(body={"order_id": "", "name": "Valid Name"}, user=requester)
    assert exc_info.value.status_code == 400


def test_p7_template_save_nonexistent_order_returns_404(isolated_db, requester):
    """
    §3.9 — POST /change-order-templates with non-existent order_id → HTTP 404.
    """
    from api.change_orders import api_save_as_template
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        api_save_as_template(
            body={"order_id": "nonexistent-order-id", "name": "Template"},
            user=requester,
        )
    assert exc_info.value.status_code == 404
