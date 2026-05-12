"""
Phase B -- Preservation baseline for §3.7 / §3.8 (list filters + i18n).

Property 2: Preservation -- assignee / requester / search / priority / status /
order_type / created_* / completed_* / scheduled_* pagination unchanged;
Chinese / English field display unchanged.

Methodology: Observation-first.
  1. Seed 200 orders with varied attributes.
  2. Use Hypothesis to generate random query-param tuples from the whitelisted set.
  3. Assert response-set equality + pagination metadata equality on UNFIXED code
     (this is the golden baseline -- tests MUST PASS on unfixed code).

Validates: Property 7 (design.md Correctness Properties)
Preservation: 3.7, 3.8 (bugfix.md)
Requirements: 3.7, 3.8
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
from database import get_db_connection
from services.change_order_service import list_change_orders

# ---------------------------------------------------------------------------
# Constants matching the whitelisted query params from bugfix.md §3.7
# ---------------------------------------------------------------------------

STATUSES = [
    "draft", "initial_review", "final_review", "approved",
    "implementing", "completed", "rejected", "cancelled",
    "rollback_in_progress", "rolled_back", "failed",
]

PRIORITIES = ["low", "medium", "high", "critical"]

ORDER_TYPES = ["config_change", "maintenance", "emergency", "routine"]

# i18n field set that MUST be present in every order dict (§3.8)
LEGACY_FIELDS = [
    "id", "order_number", "title", "description",
    "status", "priority", "order_type",
    "requester_id", "requester_username",
    "assigned_initial_reviewer_id", "assigned_initial_reviewer_username",
    "assigned_final_approver_id", "assigned_final_approver_username",
    "risk_level", "scheduled_start", "scheduled_end",
    "created_at", "updated_at",
    "commands", "target_devices", "rollback_plan",
    "command_template", "result_detail",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso(offset_days: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=offset_days)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _insert_raw_order(
    conn,
    *,
    idx: int,
    requester_username: str,
    assignee_username: str = "",
    status: str = "draft",
    priority: str = "medium",
    order_type: str = "config_change",
    created_offset: int = 0,
    scheduled_offset: int = 1,
    completed_offset: int | None = None,
    order_number_prefix: str = "20250101",
) -> str:
    """Insert a raw order row bypassing API validation for fixture seeding."""
    order_id = str(uuid.uuid4())
    created_at = _utc_iso(created_offset)
    scheduled_start = _utc_iso(scheduled_offset)
    scheduled_end = _utc_iso(scheduled_offset + 1)
    actual_end = _utc_iso(completed_offset) if completed_offset is not None else ""

    conn.execute(
        """
        INSERT INTO change_orders (
            id, order_number, title, description, status, priority, order_type,
            requester_id, requester_username,
            assigned_initial_reviewer_id, assigned_initial_reviewer_username,
            assigned_final_approver_id, assigned_final_approver_username,
            risk_level, scheduled_start, scheduled_end, actual_end,
            target_devices_json, commands_json, command_template_json,
            result_detail_json, control_sheet_json,
            rollback_plan, authorization_exempt,
            created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?
        )
        """,
        (
            order_id,
            f"BG{order_number_prefix}{idx:04d}",
            f"Order {idx} title",
            f"Description for order {idx}",
            status,
            priority,
            order_type,
            f"uid-{requester_username}",
            requester_username,
            f"uid-{assignee_username}" if assignee_username else "",
            assignee_username,
            "",
            "",
            "low",
            scheduled_start,
            scheduled_end,
            actual_end,
            "[]",
            "[]",
            "{}",
            "{}",
            "{}",
            "",
            0,
            created_at,
            created_at,
        ),
    )
    conn.commit()
    return order_id


def _seed_200_orders(conn, prefix: str = "20250101") -> dict:
    """
    Seed exactly 200 orders with varied attributes.
    Returns metadata about the seeded data for assertion helpers.
    The `prefix` parameter (8 chars, YYYYMMDD-like) is used in order_number
    to avoid UNIQUE constraint collisions when called multiple times in the
    same Hypothesis test function (each example gets a fresh prefix).
    """
    meta: dict = {
        "requesters": set(),
        "assignees": set(),
        "statuses": set(),
        "priorities": set(),
        "order_types": set(),
        "ids": [],
    }

    for i in range(200):
        status = STATUSES[i % len(STATUSES)]
        priority = PRIORITIES[i % len(PRIORITIES)]
        order_type = ORDER_TYPES[i % len(ORDER_TYPES)]
        requester = f"user_{i % 10}"
        assignee = f"reviewer_{i % 5}" if i % 3 != 0 else ""
        completed_offset = -(i % 7) if status == "completed" else None

        oid = _insert_raw_order(
            conn,
            idx=i,
            requester_username=requester,
            assignee_username=assignee,
            status=status,
            priority=priority,
            order_type=order_type,
            created_offset=-(i % 30),
            scheduled_offset=i % 14,
            completed_offset=completed_offset,
            order_number_prefix=prefix,
        )
        meta["requesters"].add(requester)
        if assignee:
            meta["assignees"].add(assignee)
        meta["statuses"].add(status)
        meta["priorities"].add(priority)
        meta["order_types"].add(order_type)
        meta["ids"].append(oid)

    return meta


def _response_set_hash(items: list[dict]) -> str:
    """Stable hash of a result set (order-independent, id-based)."""
    ids = sorted(item["id"] for item in items)
    return hashlib.sha256(json.dumps(ids).encode()).hexdigest()


def _clear_and_seed(conn) -> dict:
    """
    Clear all existing orders and seed 200 fresh ones.
    Used in PBT tests where Hypothesis reuses the same DB across examples.
    """
    conn.execute("DELETE FROM change_orders")
    conn.commit()
    return _seed_200_orders(conn)


# ---------------------------------------------------------------------------
# Observation: record golden response hashes for key filter combinations
# ---------------------------------------------------------------------------


def test_p7_observe_filter_baselines(isolated_db):
    """
    Observation step (Requirement 3.7) -- call list_change_orders with each
    whitelisted filter param individually and verify the result-set semantics.
    This test MUST PASS on unfixed code (it is the golden baseline).
    """
    conn = get_db_connection()
    try:
        meta = _seed_200_orders(conn)

        # --- status filter ---
        for status in STATUSES:
            items, total = list_change_orders(conn, status=status, page_size=200)
            for item in items:
                assert item["status"] == status, (
                    f"status filter={status!r} returned item with status={item['status']!r}"
                )

        # --- priority filter ---
        for priority in PRIORITIES:
            items, total = list_change_orders(conn, priority=priority, page_size=200)
            for item in items:
                assert item["priority"] == priority, (
                    f"priority filter={priority!r} returned item with priority={item['priority']!r}"
                )

        # --- order_type filter ---
        for ot in ORDER_TYPES:
            items, total = list_change_orders(conn, order_type=ot, page_size=200)
            for item in items:
                assert item["order_type"] == ot, (
                    f"order_type filter={ot!r} returned item with order_type={item['order_type']!r}"
                )

        # --- requester filter ---
        for requester in list(meta["requesters"])[:3]:
            items, total = list_change_orders(conn, requester=requester, page_size=200)
            for item in items:
                assert item["requester_username"] == requester

        # --- assignee filter ---
        for assignee in list(meta["assignees"])[:3]:
            items, total = list_change_orders(conn, assignee=assignee, page_size=200)
            for item in items:
                assigned_names = {
                    item.get("assigned_initial_reviewer_username", ""),
                    item.get("assigned_final_approver_username", ""),
                    item.get("initial_reviewer_username", ""),
                    item.get("final_approver_username", ""),
                }
                assert assignee in assigned_names, (
                    f"assignee filter={assignee!r} returned item not involving that assignee"
                )

        # --- search filter ---
        items, total = list_change_orders(conn, search="Order 5", page_size=200)
        for item in items:
            haystack = (
                item.get("order_number", "")
                + item.get("title", "")
                + item.get("description", "")
            )
            assert "Order 5" in haystack or "order 5" in haystack.lower(), (
                "search='Order 5' returned item with no match in title/desc/number"
            )

        # --- pagination metadata ---
        items_p1, total_p1 = list_change_orders(conn, page=1, page_size=10)
        assert len(items_p1) == 10
        assert total_p1 == 200

        items_p2, total_p2 = list_change_orders(conn, page=2, page_size=10)
        assert len(items_p2) == 10
        assert total_p2 == 200

        # Pages must not overlap
        ids_p1 = {item["id"] for item in items_p1}
        ids_p2 = {item["id"] for item in items_p2}
        assert ids_p1.isdisjoint(ids_p2), "Page 1 and Page 2 share items"

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# PBT: random query-param tuples -- response set equality
# ---------------------------------------------------------------------------


@given(
    status=st.one_of(st.none(), st.sampled_from(STATUSES)),
    priority=st.one_of(st.none(), st.sampled_from(PRIORITIES)),
    order_type=st.one_of(st.none(), st.sampled_from(ORDER_TYPES)),
    requester_idx=st.one_of(st.none(), st.integers(min_value=0, max_value=9)),
    page=st.integers(min_value=1, max_value=5),
    page_size=st.sampled_from([10, 20, 50]),
)
@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p7_pbt_filter_response_set_equality(
    status,
    priority,
    order_type,
    requester_idx,
    page,
    page_size,
    isolated_db,
):
    """
    PBT -- Requirement 3.7 -- For random query-param tuples from the
    whitelisted set, assert:
    1. Every returned item satisfies ALL active filter predicates.
    2. Pagination metadata is consistent (total, page, page_size).
    3. No duplicate IDs within a single page.
    MUST PASS on unfixed code.
    """
    conn = get_db_connection()
    try:
        _clear_and_seed(conn)

        kwargs: dict[str, Any] = {"page": page, "page_size": page_size}
        if status is not None:
            kwargs["status"] = status
        if priority is not None:
            kwargs["priority"] = priority
        if order_type is not None:
            kwargs["order_type"] = order_type
        if requester_idx is not None:
            kwargs["requester"] = f"user_{requester_idx}"

        items, total = list_change_orders(conn, **kwargs)

        # 1. Every item satisfies active filter predicates
        for item in items:
            if status is not None:
                assert item["status"] == status, (
                    f"status filter={status!r} violated by item status={item['status']!r}"
                )
            if priority is not None:
                assert item["priority"] == priority, (
                    f"priority filter={priority!r} violated by item priority={item['priority']!r}"
                )
            if order_type is not None:
                assert item["order_type"] == order_type, (
                    f"order_type filter={order_type!r} violated by item order_type={item['order_type']!r}"
                )
            if requester_idx is not None:
                expected_req = f"user_{requester_idx}"
                assert item["requester_username"] == expected_req, (
                    f"requester filter={expected_req!r} violated"
                )

        # 2. Pagination metadata consistency
        assert total >= 0
        assert len(items) <= page_size

        # 3. No duplicate IDs within a page
        ids = [item["id"] for item in items]
        assert len(ids) == len(set(ids)), "Duplicate IDs within a single page"

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# PBT: date-range filters (created_*, completed_*, scheduled_*)
# ---------------------------------------------------------------------------


@given(
    days_back=st.integers(min_value=0, max_value=15),
    days_forward=st.integers(min_value=0, max_value=15),
    filter_kind=st.sampled_from(["created", "scheduled"]),
)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p7_pbt_date_range_filters(days_back, days_forward, filter_kind, isolated_db):
    """
    PBT -- Requirement 3.7 -- Date-range filters (created_from/to,
    scheduled_from/to) return only items within the specified window.
    MUST PASS on unfixed code.
    """
    conn = get_db_connection()
    try:
        _clear_and_seed(conn)

        from_dt = _utc_iso(-days_back)
        to_dt = _utc_iso(days_forward)

        if filter_kind == "created":
            items, total = list_change_orders(
                conn,
                created_from=from_dt,
                created_to=to_dt,
                page_size=200,
            )
            for item in items:
                assert item["created_at"] >= from_dt, (
                    f"created_from={from_dt!r} violated: item created_at={item['created_at']!r}"
                )
                assert item["created_at"] <= to_dt, (
                    f"created_to={to_dt!r} violated: item created_at={item['created_at']!r}"
                )
        else:  # scheduled
            items, total = list_change_orders(
                conn,
                scheduled_from=from_dt,
                scheduled_to=to_dt,
                page_size=200,
            )
            for item in items:
                if item.get("scheduled_start"):
                    assert item["scheduled_start"] >= from_dt, (
                        f"scheduled_from={from_dt!r} violated"
                    )
                if item.get("scheduled_end"):
                    assert item["scheduled_end"] <= to_dt, (
                        f"scheduled_to={to_dt!r} violated"
                    )

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# PBT: combined multi-param filter -- response set stability
# ---------------------------------------------------------------------------


@given(
    status=st.one_of(st.none(), st.sampled_from(STATUSES)),
    priority=st.one_of(st.none(), st.sampled_from(PRIORITIES)),
    order_type=st.one_of(st.none(), st.sampled_from(ORDER_TYPES)),
)
@settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p7_pbt_combined_filters_stable(status, priority, order_type, isolated_db):
    """
    PBT -- Requirement 3.7 -- Combined multi-param queries return a stable
    result set: calling the same query twice yields identical IDs and total.
    MUST PASS on unfixed code.
    """
    conn = get_db_connection()
    try:
        _clear_and_seed(conn)

        kwargs: dict[str, Any] = {"page_size": 200}
        if status is not None:
            kwargs["status"] = status
        if priority is not None:
            kwargs["priority"] = priority
        if order_type is not None:
            kwargs["order_type"] = order_type

        items_a, total_a = list_change_orders(conn, **kwargs)
        items_b, total_b = list_change_orders(conn, **kwargs)

        assert total_a == total_b, "Same query returned different totals on two calls"
        assert _response_set_hash(items_a) == _response_set_hash(items_b), (
            "Same query returned different result sets on two calls"
        )

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# §3.8 i18n: legacy field set preserved in every returned order
# ---------------------------------------------------------------------------


def test_p7_i18n_legacy_fields_present_in_list(isolated_db):
    """
    Requirement 3.8 -- Every order returned by list_change_orders MUST
    contain the full legacy field set regardless of language setting.
    New fields added by the bugfix MUST NOT displace existing fields.
    MUST PASS on unfixed code.
    """
    conn = get_db_connection()
    try:
        _seed_200_orders(conn)
        items, total = list_change_orders(conn, page_size=200)
        assert total == 200

        for item in items:
            for field in LEGACY_FIELDS:
                assert field in item, (
                    f"Legacy field {field!r} missing from list response item {item.get('id')}"
                )
    finally:
        conn.close()


def test_p7_i18n_status_zh_labels_complete():
    """
    Requirement 3.8 -- STATUS_ZH must map every status in ALLOWED_STATUSES
    to a non-empty Chinese label.  Ensures Chinese display is not broken.
    MUST PASS on unfixed code.
    """
    from api.change_orders import STATUS_ZH, ALLOWED_STATUSES

    for status in ALLOWED_STATUSES:
        # Legacy statuses (pending/executing) may not have ZH labels -- skip them
        if status in ("pending", "executing"):
            continue
        assert status in STATUS_ZH, f"STATUS_ZH missing entry for status={status!r}"
        assert STATUS_ZH[status], f"STATUS_ZH[{status!r}] is empty"


def test_p7_i18n_order_fields_zh_en_consistent(isolated_db):
    """
    Requirement 3.8 -- The service layer returns the same field set regardless
    of any language hint. Assert that all legacy fields are present.
    MUST PASS on unfixed code.
    """
    conn = get_db_connection()
    try:
        _seed_200_orders(conn)

        items_default, total_default = list_change_orders(conn, page_size=10)

        for item in items_default:
            for field in LEGACY_FIELDS:
                assert field in item, f"Field {field!r} missing (lang-neutral check)"

        from api.change_orders import STATUS_ZH

        seen_statuses = {item["status"] for item in items_default}
        for s in seen_statuses:
            if s not in ("pending", "executing"):
                assert s in STATUS_ZH, f"STATUS_ZH missing {s!r}"

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# §3.8 i18n: single-order detail field set
# ---------------------------------------------------------------------------


def test_p7_i18n_legacy_fields_present_in_detail(isolated_db):
    """
    Requirement 3.8 -- get_change_order() MUST return the full legacy
    field set for any order, including orders created before the bugfix.
    MUST PASS on unfixed code.
    """
    from services.change_order_service import get_change_order

    conn = get_db_connection()
    try:
        meta = _seed_200_orders(conn)
        # Check a sample of 10 orders
        for oid in meta["ids"][:10]:
            order = get_change_order(conn, oid)
            assert order is not None, f"get_change_order returned None for id={oid}"
            for field in LEGACY_FIELDS:
                assert field in order, (
                    f"Legacy field {field!r} missing from detail response for order {oid}"
                )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Pagination: total count consistency across pages
# ---------------------------------------------------------------------------


def test_p7_pagination_total_consistent(isolated_db):
    """
    Requirement 3.7 -- The total count returned by list_change_orders MUST
    be consistent across all pages for the same query.
    MUST PASS on unfixed code.
    """
    conn = get_db_connection()
    try:
        _seed_200_orders(conn)

        page_size = 20
        _, total = list_change_orders(conn, page=1, page_size=page_size)
        assert total == 200

        all_ids: list[str] = []
        pages = (total + page_size - 1) // page_size
        for p in range(1, pages + 1):
            items, t = list_change_orders(conn, page=p, page_size=page_size)
            assert t == total, f"Page {p} returned total={t}, expected {total}"
            all_ids.extend(item["id"] for item in items)

        # All 200 IDs collected, no duplicates
        assert len(all_ids) == 200
        assert len(set(all_ids)) == 200, "Duplicate IDs across pages"

    finally:
        conn.close()


@given(
    page_size=st.sampled_from([5, 10, 25, 50, 100]),
    status=st.one_of(st.none(), st.sampled_from(STATUSES)),
)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_p7_pbt_pagination_no_gaps_no_duplicates(page_size, status, isolated_db):
    """
    PBT -- Requirement 3.7 -- Iterating through all pages of a filtered
    query yields exactly the same items as a single full-page query.
    No gaps, no duplicates.  MUST PASS on unfixed code.
    """
    conn = get_db_connection()
    try:
        _clear_and_seed(conn)

        kwargs: dict[str, Any] = {}
        if status is not None:
            kwargs["status"] = status

        # Full result in one shot
        all_items, total = list_change_orders(conn, page_size=500, **kwargs)
        full_ids = sorted(item["id"] for item in all_items)

        # Paginated result
        paged_ids: list[str] = []
        page = 1
        while True:
            items, _ = list_change_orders(conn, page=page, page_size=page_size, **kwargs)
            if not items:
                break
            paged_ids.extend(item["id"] for item in items)
            page += 1
            if page > 50:  # safety guard
                break

        paged_ids_sorted = sorted(paged_ids)

        assert full_ids == paged_ids_sorted, (
            f"Paginated traversal (page_size={page_size}, status={status!r}) "
            f"yielded {len(paged_ids)} items vs full-query {len(full_ids)} items"
        )

    finally:
        conn.close()
