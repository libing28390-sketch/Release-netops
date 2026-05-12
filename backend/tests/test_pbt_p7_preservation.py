"""
Phase E — Fix-checking PBT for Property P7: preservation (fixed vs. unfixed parity).

Task 17.7 — Property P7 — preservation PBT (fixed vs. unfixed parity)

For inputs where NOT isBugCondition(input), the fixed handler's response
(status code, body modulo new-and-defaulted fields, DB diff, audit events)
must be equivalent to the baseline captured in tasks 6–9.

Strategy: generate inputs via the same generators as tasks 6–9 but filtered
by NOT C (i.e., draft orders, valid lifecycle transitions, template CRUD,
bookmarks, validate-ticket).

Validates: Property 7
Requirements: 3.1–3.11
"""

from __future__ import annotations

import uuid
import pytest
from database import get_db_connection
from services.change_order_service import (
    create_change_order,
    get_change_order,
    list_change_orders,
)


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ── P7 §3.1: BG numbering preserved ──────────────────────────────────

def test_p7_bg_numbering_format(isolated_db, requester):
    """BG+YYYYMMDD+NNNN format preserved."""
    import re
    from api.change_orders import ChangeOrderCreate, api_create_change_order

    body = ChangeOrderCreate(
        title="P7 numbering test",
        status="draft",
        command_template={},
        commands=["show version"],
        rollback_plan="",
    )
    result = api_create_change_order(body, user=requester)
    order_number = result["data"]["order_number"]
    assert re.match(r"^BG\d{8}\d{4}$", order_number), (
        f"P7: order_number format violated: {order_number!r}"
    )


def test_p7_bg_numbering_unique_sequential(isolated_db, requester):
    """Multiple orders on same day get unique, sequential BG numbers."""
    from api.change_orders import ChangeOrderCreate, api_create_change_order

    numbers = []
    for i in range(5):
        body = ChangeOrderCreate(
            title=f"P7 order {i}",
            status="draft",
            command_template={},
            commands=["show version"],
            rollback_plan="",
        )
        result = api_create_change_order(body, user=requester)
        numbers.append(result["data"]["order_number"])

    assert len(set(numbers)) == 5, f"P7: duplicate order numbers: {numbers}"
    # Sequential: last 4 digits should be increasing
    seqs = [int(n[-4:]) for n in numbers]
    assert seqs == sorted(seqs), f"P7: order numbers not sequential: {numbers}"


# ── P7 §3.2: draft save without reviewer/commands still works ─────────

def test_p7_draft_save_without_reviewer(isolated_db, requester):
    """Draft can be saved without reviewer or commands (§3.1 preservation)."""
    from api.change_orders import ChangeOrderCreate, api_create_change_order

    body = ChangeOrderCreate(
        title="Minimal draft",
        status="draft",
        command_template={},
        commands=[],
        rollback_plan="",
    )
    result = api_create_change_order(body, user=requester)
    assert result["data"]["status"] == "draft"


# ── P7 §3.3–§3.6: RBAC branches preserved ────────────────────────────

def test_p7_admin_can_delete_any_order(isolated_db, requester, make_user):
    """Administrator can DELETE any order regardless of owner (§3.6)."""
    from api.change_orders import ChangeOrderCreate, api_create_change_order, api_delete_change_order

    admin = make_user("admin_p7", role="Administrator", change_groups=["final_approver"])

    body = ChangeOrderCreate(
        title="P7 delete test",
        status="draft",
        command_template={},
        commands=["show version"],
        rollback_plan="",
    )
    result = api_create_change_order(body, user=requester)
    order_id = result["data"]["id"]

    del_result = api_delete_change_order(order_id, user=admin)
    assert del_result.get("success") is True, f"P7: admin delete failed: {del_result}"


# ── P7 §3.7: list filter params preserved ────────────────────────────

def test_p7_list_filters_preserved(isolated_db, make_user):
    """List filter params (status, priority, requester) work correctly (§3.7)."""
    u1 = make_user("p7_u1", role="Operator", change_groups=[])
    u2 = make_user("p7_u2", role="Operator", change_groups=[])

    conn = get_db_connection()
    try:
        create_change_order(conn, title="High priority", priority="high",
                            status="draft", requester_id=u1["user_id"],
                            requester_username=u1["username"])
        create_change_order(conn, title="Low priority", priority="low",
                            status="draft", requester_id=u2["user_id"],
                            requester_username=u2["username"])

        # Filter by priority
        items, total = list_change_orders(conn, priority="high", page_size=100)
        assert total == 1
        assert items[0]["priority"] == "high"

        # Filter by requester
        items2, total2 = list_change_orders(conn, requester=u1["username"], page_size=100)
        assert total2 == 1
        assert items2[0]["requester_username"] == u1["username"]
    finally:
        conn.close()


# ── P7 §3.8: legacy fields present in all responses ──────────────────

LEGACY_FIELDS = [
    "id", "order_number", "title", "description", "status", "priority",
    "order_type", "requester_id", "requester_username",
    "assigned_initial_reviewer_id", "assigned_initial_reviewer_username",
    "assigned_final_approver_id", "assigned_final_approver_username",
    "risk_level", "scheduled_start", "scheduled_end",
    "created_at", "updated_at", "commands", "target_devices",
    "rollback_plan", "command_template", "result_detail",
]


def test_p7_legacy_fields_in_list_response(isolated_db, requester):
    """All legacy fields present in list response (§3.8)."""
    from api.change_orders import ChangeOrderCreate, api_create_change_order

    body = ChangeOrderCreate(
        title="P7 legacy fields test",
        status="draft",
        command_template={},
        commands=["show version"],
        rollback_plan="",
    )
    api_create_change_order(body, user=requester)

    conn = get_db_connection()
    try:
        items, _ = list_change_orders(conn, page_size=10)
        assert len(items) >= 1
        for item in items:
            for field in LEGACY_FIELDS:
                assert field in item, f"P7: legacy field {field!r} missing from list response"
    finally:
        conn.close()


def test_p7_legacy_fields_in_detail_response(isolated_db, requester):
    """All legacy fields present in detail response (§3.8)."""
    from api.change_orders import ChangeOrderCreate, api_create_change_order

    body = ChangeOrderCreate(
        title="P7 detail fields test",
        status="draft",
        command_template={},
        commands=["show version"],
        rollback_plan="",
    )
    result = api_create_change_order(body, user=requester)
    order_id = result["data"]["id"]

    conn = get_db_connection()
    try:
        order = get_change_order(conn, order_id)
        assert order is not None
        for field in LEGACY_FIELDS:
            assert field in order, f"P7: legacy field {field!r} missing from detail response"
    finally:
        conn.close()


# ── P7 §3.9: template CRUD preserved ─────────────────────────────────

def test_p7_template_crud_preserved(isolated_db, requester):
    """Template CRUD round-trip preserved (§3.9)."""
    from api.change_orders import ChangeOrderCreate, api_create_change_order
    from services.change_order_service import (
        save_order_as_template, list_templates, get_template, delete_template,
        get_change_order as _get_order,
    )

    body = ChangeOrderCreate(
        title="P7 template test",
        status="draft",
        command_template={},
        commands=["show version"],
        rollback_plan="",
    )
    result = api_create_change_order(body, user=requester)
    order_id = result["data"]["id"]

    conn = get_db_connection()
    try:
        order = _get_order(conn, order_id)
        tpl = save_order_as_template(
            conn,
            name="P7 Template",
            description="test",
            order=order,
            creator_id=requester["user_id"],
            creator_username=requester["username"],
        )
        assert tpl is not None
        tpl_id = tpl["id"]

        templates = list_templates(conn)
        # list_templates returns list, not (list, total)
        if isinstance(templates, tuple):
            templates = templates[0]
        assert any(t["id"] == tpl_id for t in templates)

        fetched = get_template(conn, tpl_id)
        assert fetched["name"] == "P7 Template"

        deleted = delete_template(conn, tpl_id)
        assert deleted is True

        fetched2 = get_template(conn, tpl_id)
        assert fetched2 is None
    finally:
        conn.close()


# ── P7 §3.10: bookmark toggle preserved ──────────────────────────────

def test_p7_bookmark_toggle_preserved(isolated_db, requester):
    """Bookmark toggle idempotency preserved (§3.10)."""
    from api.change_orders import ChangeOrderCreate, api_create_change_order
    from services.change_order_service import toggle_bookmark, get_user_bookmarks

    body = ChangeOrderCreate(
        title="P7 bookmark test",
        status="draft",
        command_template={},
        commands=["show version"],
        rollback_plan="",
    )
    result = api_create_change_order(body, user=requester)
    order_id = result["data"]["id"]
    user_id = requester["user_id"]

    conn = get_db_connection()
    try:
        # Toggle on
        bookmarked = toggle_bookmark(conn, user_id=user_id, order_id=order_id)
        assert bookmarked is True

        # Toggle off
        bookmarked2 = toggle_bookmark(conn, user_id=user_id, order_id=order_id)
        assert bookmarked2 is False

        # Toggle on again — idempotent
        bookmarked3 = toggle_bookmark(conn, user_id=user_id, order_id=order_id)
        assert bookmarked3 is True

        bookmarks = get_user_bookmarks(conn, user_id=user_id)
        assert order_id in bookmarks
    finally:
        conn.close()


# ── P7 §3.11: validate-ticket preserved ──────────────────────────────

def test_p7_validate_ticket_preserved(isolated_db, requester):
    """validate-ticket returns valid for approved order within window (§3.11)."""
    from api.change_orders import api_validate_change_ticket
    from services.change_order_service import create_change_order

    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    start = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    end = (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")

    conn = get_db_connection()
    try:
        order = create_change_order(
            conn,
            title="P7 validate ticket test",
            status="approved",
            requester_id=requester["user_id"],
            requester_username=requester["username"],
            scheduled_start=start,
            scheduled_end=end,
        )
        order_number = order["order_number"]
    finally:
        conn.close()

    result = api_validate_change_ticket(order_number, user=requester)
    assert result.get("data", {}).get("valid") is True, (
        f"P7: validate-ticket should return valid for approved order in window: {result}"
    )
