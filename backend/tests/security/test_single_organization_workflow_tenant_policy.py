from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException


def test_config_approval_accepts_cross_history_approver_and_keeps_mfa_and_maker_checker(isolated_db, make_user):
    from backend.tests.conftest import current_test_totp
    from services import config_approval_service as approval

    requester = make_user("workflow_requester", role="Operator", tenant_id="tenant-history-a")
    approver = make_user(
        "workflow_approver",
        role="Administrator",
        tenant_id="tenant-history-b",
        mfa_enabled=True,
        mfa_secret="JBSWY3DPEHPK3PXP",
    )
    manifest = {"operation": "CONFIGURE", "device_ids": ["legacy-device"]}
    token, error = approval.request_approval(
        approver_username=approver["username"],
        requester_username=requester["username"],
        requester_id=requester["user_id"],
        requester_tenant_id=requester["tenant_id"],
        config_reason="test-only request",
        approval_type="config",
        operation_manifest=manifest,
        verification_method="mfa",
    )

    assert error is None
    assert token
    binding_hash = approval.approval_manifest_hash(manifest)
    conn = isolated_db["module"].get_db_connection()
    try:
        saved = conn.execute(
            "SELECT requester_tenant_id, status FROM config_approval_requests WHERE token_hash = ?",
            (approval._digest(token),),
        ).fetchone()
        assert saved["requester_tenant_id"] == "tenant-default"
        assert saved["status"] == "pending"
    finally:
        conn.close()

    verified, verify_error = approval.verify_code(
        token,
        current_test_totp(approver["mfa_secret"]),
        requester_id=requester["user_id"],
        requester_username=requester["username"],
        expected_approval_type="config",
        expected_binding_hash=binding_hash,
    )
    assert verified is True, verify_error

    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute("UPDATE users SET tenant_id = 'tenant-history-c' WHERE id = ?", (requester["user_id"],))
        conn.commit()
    finally:
        conn.close()

    consumed = approval.consume_approval(
        token,
        requester_id=requester["user_id"],
        expected_approval_type="config",
        expected_binding_hash=binding_hash,
    )
    assert consumed is not None
    assert consumed["requester_tenant_id"] == "tenant-default"

    _, self_approval_error = approval.request_approval(
        approver_username=approver["username"],
        requester_username=approver["username"],
        requester_id=approver["user_id"],
        requester_tenant_id=approver["tenant_id"],
        config_reason="self approval must remain blocked",
        verification_method="mfa",
        operation_manifest=manifest,
    )
    assert self_approval_error == "申请人不能审批自己的请求"


def test_scripts_are_visible_and_approvers_cross_history_but_actions_and_self_approval_remain(isolated_db, make_user):
    from api import automation

    author = make_user("script_author_history", role="Operator", tenant_id="tenant-history-a")
    approver = make_user("script_approver_history", role="Administrator", tenant_id="tenant-history-b")
    unauthorized = make_user("script_non_approver", role="Operator", tenant_id="tenant-history-c")
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            """INSERT INTO scripts (id, name, content, author, status, created_at, updated_at, tenant_id)
               VALUES ('history-script-a', 'History A', 'show version', ?, 'released', '2026-01-01', '2026-01-01', 'tenant-history-a'),
                      ('history-script-b', 'History B', 'show clock', ?, 'released', '2026-01-02', '2026-01-02', 'tenant-history-b')""",
            (author["username"], author["username"]),
        )
        conn.commit()

        assert automation._resolve_script_approver(
            conn, approver["username"], "tenant-default", author["user_id"],
        )["id"] == approver["user_id"]
    finally:
        conn.close()

    assert automation._script_tenant_for_actor(author, "tenant-history-a") == "tenant-default"
    assert automation._assert_script_row_scope(
        author, {"id": "history-script-b", "tenant_id": "tenant-history-b"}, "view",
    ) == "tenant-history-b"
    # Direct calls bypass FastAPI's Query default injection.
    visible = asyncio.run(
        automation.read_scripts(
            q="",
            platform="",
            category="",
            script_type="",
            status="",
            page=None,
            page_size=20,
            user=author,
        )
    )
    assert {row["id"] for row in visible} >= {"history-script-a", "history-script-b"}

    conn = isolated_db["module"].get_db_connection()
    try:
        with pytest.raises(HTTPException) as no_action:
            automation._resolve_script_approver(
                conn, unauthorized["username"], "tenant-default", author["user_id"],
            )
        assert no_action.value.status_code == 403
        with pytest.raises(HTTPException) as self_approval:
            automation._resolve_script_approver(
                conn, author["username"], "tenant-default", author["user_id"],
            )
        assert self_approval.value.status_code == 403
    finally:
        conn.close()


def test_scheduled_jobs_cross_history_preserves_owner_system_read_only_and_actions(isolated_db, make_user):
    from api import scheduled_jobs
    from services.scheduled_job_authorization import authorize_job_resource

    owner = make_user("scheduled_owner_history", role="Operator", tenant_id="tenant-history-b")
    other = make_user("scheduled_other_history", role="Operator", tenant_id="tenant-history-a")
    conn = isolated_db["module"].get_db_connection()
    now = "2026-10-15T00:00:00+00:00"
    try:
        for job_id, tenant_id, owner_id, auth_mode in (
            ("job-owned-cross-history", "tenant-history-a", owner["user_id"], "snapshot"),
            ("job-private-other-owner", "tenant-history-a", other["user_id"], "snapshot"),
            ("job-system-cross-history", "tenant-history-c", "", "system"),
        ):
            conn.execute(
                """INSERT INTO scheduled_jobs
                   (id, name, job_type, action_type, cron_expr, device_scope,
                    enabled, status, created_by, created_by_id, tenant_id,
                    authorization_mode, created_at, updated_at)
                   VALUES (?, ?, 'cron', 'inspection', '* * * * *', 'all',
                           1, 'approved', ?, ?, ?, ?, ?, ?)""",
                (job_id, job_id, owner["username"], owner_id, tenant_id, auth_mode, now, now),
            )
        conn.commit()

        manifest = scheduled_jobs._prepare_manifest(
            conn,
            {"name": "New schedule", "job_type": "cron", "action": "inspection", "cron_expr": "* * * * *", "scope": {"type": "all", "filter": ""}},
            owner,
            "CREATE",
        )
    finally:
        conn.close()

    assert scheduled_jobs._actor_tenant(owner) == "tenant-default"
    assert manifest["tenant_id"] == "tenant-default"
    response = scheduled_jobs.list_scheduled_jobs(user=owner)
    listed_ids = {row["id"] for row in response["data"]["items"]}
    assert "job-owned-cross-history" in listed_ids
    assert "job-system-cross-history" in listed_ids
    assert "job-private-other-owner" not in listed_ids

    conn = isolated_db["module"].get_db_connection()
    try:
        owned = dict(conn.execute("SELECT * FROM scheduled_jobs WHERE id = 'job-owned-cross-history'").fetchone())
        system = dict(conn.execute("SELECT * FROM scheduled_jobs WHERE id = 'job-system-cross-history'").fetchone())
        authorize_job_resource(owner, owned, "view")
        with pytest.raises(PermissionError):
            authorize_job_resource(owner, system, "update")
    finally:
        conn.close()

    with pytest.raises(HTTPException) as action_error:
        scheduled_jobs._require_job_collection_permission({"id": "viewer-1", "role": "Viewer"}, "create")
    assert action_error.value.status_code == 403


def test_change_orders_cross_history_and_new_rows_use_default_tenant(isolated_db, make_user):
    from api.change_orders import ChangeOrderCreate, api_create_change_order, api_get_change_order, api_list_change_orders
    from api.change_orders.attachments import _require_order_update_scope

    creator = make_user("change_order_creator_history", role="Operator", tenant_id="tenant-history-a")
    reader = make_user("change_order_reader_history", role="Operator", tenant_id="tenant-history-b")
    result = api_create_change_order(
        ChangeOrderCreate(title="Single organization workflow", status="draft", commands=["show version"]),
        user=creator,
    )
    order_id = result["data"]["id"]
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute("UPDATE change_orders SET tenant_id = 'tenant-history-a' WHERE id = ?", (order_id,))
        conn.commit()
        saved = conn.execute("SELECT tenant_id FROM change_orders WHERE id = ?", (order_id,)).fetchone()
    finally:
        conn.close()
    assert saved["tenant_id"] == "tenant-history-a"

    order = api_get_change_order(order_id=order_id, user=reader)["data"]
    assert order["id"] == order_id
    _require_order_update_scope(order, reader)

    listed = api_list_change_orders(
        page=1, page_size=100, status="", priority="", search="", requester="", assignee="",
        bookmarked="", my_todo="", group_todo="", my_participated="", my_drafts="",
        order_type="", created_from="", created_to="", completed_from="", completed_to="",
        scheduled_from="", scheduled_to="", my_todo_kind="", user=reader,
    )
    assert any(item["id"] == order_id for item in listed["data"])

    inserted = api_create_change_order(
        ChangeOrderCreate(title="New default label", status="draft", commands=[]),
        user=reader,
    )
    conn = isolated_db["module"].get_db_connection()
    try:
        tenant_id = conn.execute(
            "SELECT tenant_id FROM change_orders WHERE id = ?", (inserted["data"]["id"],),
        ).fetchone()["tenant_id"]
    finally:
        conn.close()
    assert tenant_id == "tenant-default"
