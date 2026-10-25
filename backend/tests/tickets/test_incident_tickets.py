from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException


def _actor(user: dict) -> dict:
    return {
        "id": user["user_id"],
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
        "role_profile": user.get("role_profile", ""),
        "tenant_id": user.get("tenant_id") or "tenant-default",
        "scope_mode": user.get("scope_mode", "legacy"),
    }


def _insert_source_incident(
    conn,
    incident_id: str,
    device_id: str,
    *,
    site_id: str = "site-a",
    group_id: str = "group-a",
    tenant_id: str = "tenant-default",
) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        """
        INSERT INTO devices (id, hostname, ip_address, platform, status, site, site_id, tenant_id, device_group_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET site = excluded.site, site_id = excluded.site_id,
                                      tenant_id = excluded.tenant_id, device_group_id = excluded.device_group_id
        """,
        (device_id, f"{device_id}.example", "192.0.2.10", "cisco_ios", "online", site_id, site_id, tenant_id, group_id),
    )
    alert_id = f"alert-{incident_id}"
    conn.execute(
        """
        INSERT INTO alert_events (id, dedupe_key, source, severity, title, message, device_id, created_at, workflow_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')
        ON CONFLICT(id) DO NOTHING
        """,
        (alert_id, f"ping_unreachable:{device_id}", "network_monitor", "major", "Device unreachable", "Probe failed", device_id, now),
    )
    conn.execute(
        """
        INSERT INTO monitoring_incidents (
            id, incident_key, title, summary, severity, status, source,
            root_cause_alert_id, primary_device_id, site, first_seen_at,
            last_seen_at, impact_device_count, impact_alert_count, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'major', 'open', 'alert_events', ?, ?, ?, ?, ?, 1, 1, ?, ?)
        ON CONFLICT(id) DO NOTHING
        """,
        (incident_id, f"incident-key-{incident_id}", f"Incident {incident_id}", "Impact summary", alert_id, device_id, site_id, now, now, now, now),
    )
    conn.execute(
        "INSERT INTO monitoring_incident_alerts (incident_id, alert_id, linked_at, is_root) VALUES (?, ?, ?, 1) ON CONFLICT DO NOTHING",
        (incident_id, alert_id, now),
    )


def _open_ticket(database, actor: dict, incident_id: str) -> dict:
    from services.incident_ticket_service import create_ticket_from_incident

    conn = database.get_db_connection()
    try:
        ticket, created = create_ticket_from_incident(conn, incident_id, actor)
        conn.commit()
        return {"ticket": ticket, "created": created}
    finally:
        conn.close()

def test_incident_ticket_migration_is_idempotent_and_has_unique_ticket_numbers(isolated_db):
    from database import get_db_connection
    from database.migrations.m0292_incident_tickets import upgrade

    conn = get_db_connection()
    try:
        upgrade(conn.cursor(), use_pg=True)
        upgrade(conn.cursor(), use_pg=True)
        tables = {
            row["table_name"]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
            ).fetchall()
        }
        assert {
            "incident_tickets", "incident_ticket_events", "incident_ticket_links",
            "ticket_assignment_groups", "ticket_assignment_group_members",
        }.issubset(tables)
        indexes = {
            row["indexname"]
            for row in conn.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() AND tablename = 'incident_tickets'"
            ).fetchall()
        }
        assert "uq_incident_tickets_ticket_number" in indexes
    finally:
        conn.close()


def test_open_from_incident_is_idempotent_under_concurrent_requests(isolated_db, make_user):
    from database import get_db_connection
    from services.incident_ticket_service import create_ticket_from_incident

    database = isolated_db["module"]
    actor = _actor(make_user("ticket_creator", role="Operator"))
    seed = get_db_connection()
    try:
        _insert_source_incident(seed, "incident-concurrent", "device-concurrent")
        seed.commit()
    finally:
        seed.close()

    barrier = threading.Barrier(2)

    def request_ticket():
        conn = database.get_db_connection()
        try:
            barrier.wait(timeout=10)
            ticket, created = create_ticket_from_incident(conn, "incident-concurrent", actor)
            conn.commit()
            return ticket["id"], created
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: request_ticket(), range(2)))

    assert results[0][0] == results[1][0]
    assert sorted(created for _, created in results) == [False, True]
    conn = get_db_connection()
    try:
        assert conn.execute("SELECT COUNT(*) AS c FROM incident_tickets WHERE source_incident_id = ?", ("incident-concurrent",)).fetchone()["c"] == 1
        assert conn.execute("SELECT COUNT(*) AS c FROM incident_ticket_events WHERE ticket_id = ?", (results[0][0],)).fetchone()["c"] == 1
    finally:
        conn.close()


def test_ticket_scope_filters_list_and_detail_for_every_incident_device(isolated_db, make_user):
    from database import get_db_connection
    from services.incident_ticket_service import create_ticket_from_incident, get_ticket_detail, list_tickets

    database = isolated_db["module"]
    admin = _actor(make_user("ticket_scope_admin", role="Administrator"))
    viewer = make_user("ticket_scope_viewer", role="Viewer")
    viewer_actor = _actor(viewer)
    conn = get_db_connection()
    try:
        _insert_source_incident(conn, "incident-visible", "device-visible", site_id="site-a")
        _insert_source_incident(conn, "incident-hidden", "device-hidden", site_id="site-b")
        visible, _ = create_ticket_from_incident(conn, "incident-visible", admin)
        hidden, _ = create_ticket_from_incident(conn, "incident-hidden", admin)
        conn.execute("UPDATE users SET scope_mode = 'restricted' WHERE id = ?", (viewer["user_id"],))
        conn.execute(
            """
            INSERT INTO user_resource_scopes (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
            VALUES (?, ?, 'incident_ticket', 'site', 'site-a', ?, ?)
            """,
            ("scope-ticket-site-a", viewer["user_id"], json.dumps(["view"]), datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            """
            INSERT INTO user_resource_scopes (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
            VALUES (?, ?, 'asset', 'site', 'site-a', ?, ?)
            """,
            ("scope-ticket-viewer-asset-a", viewer["user_id"], json.dumps(["view"]), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

        page = list_tickets(conn, viewer_actor, page=1, page_size=10)
        assert [item["id"] for item in page["items"]] == [visible["id"]]
        assert page["total"] == 1
        assert page["items"][0]["incident_id"] == "incident-visible"
        assert page["items"][0]["requester_id"] == admin["user_id"]
        assert get_ticket_detail(conn, visible["id"], viewer_actor)["ticket"]["id"] == visible["id"]
        with pytest.raises(HTTPException) as error:
            get_ticket_detail(conn, hidden["id"], viewer_actor)
        assert error.value.status_code == 404

        no_asset_viewer = make_user("ticket_no_asset_viewer", role="Viewer")
        no_asset_actor = {**_actor(no_asset_viewer), "scope_mode": "restricted"}
        conn.execute("UPDATE users SET scope_mode = 'restricted' WHERE id = ?", (no_asset_viewer["user_id"],))
        conn.execute(
            """
            INSERT INTO user_resource_scopes (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
            VALUES (?, ?, 'incident_ticket', 'site', 'site-a', ?, ?)
            """,
            ("scope-ticket-only-no-asset", no_asset_viewer["user_id"], json.dumps(["view"]), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        with pytest.raises(HTTPException) as denied:
            list_tickets(conn, no_asset_actor)
        assert denied.value.status_code == 403
    finally:
        conn.close()


def test_ticket_device_group_scope_filters_list_and_detail(isolated_db, make_user):
    from database import get_db_connection
    from services.incident_ticket_service import create_ticket_from_incident, get_ticket_detail, list_tickets

    admin = _actor(make_user("ticket_group_scope_admin", role="Administrator"))
    viewer = make_user("ticket_group_scope_viewer", role="Viewer")
    viewer_actor = {**_actor(viewer), "scope_mode": "restricted"}
    conn = get_db_connection()
    try:
        _insert_source_incident(conn, "incident-group-visible", "device-group-visible", group_id="group-a")
        _insert_source_incident(conn, "incident-group-hidden", "device-group-hidden", group_id="group-b")
        visible, _ = create_ticket_from_incident(conn, "incident-group-visible", admin)
        hidden, _ = create_ticket_from_incident(conn, "incident-group-hidden", admin)
        for resource, ident in (
            ("incident_ticket", "scope-ticket-group-a"),
            ("asset", "scope-asset-group-a"),
        ):
            conn.execute(
                "INSERT INTO user_resource_scopes (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at) VALUES (?, ?, ?, 'device_group', 'group-a', ?, ?)",
                (ident, viewer["user_id"], resource, json.dumps(["view"]), datetime.now(timezone.utc).isoformat()),
            )
        conn.commit()
        page = list_tickets(conn, viewer_actor)
        assert [item["id"] for item in page["items"]] == [visible["id"]]
        assert page["total"] == 1
        assert get_ticket_detail(conn, visible["id"], viewer_actor)["ticket"]["id"] == visible["id"]
        with pytest.raises(HTTPException) as denied:
            get_ticket_detail(conn, hidden["id"], viewer_actor)
        assert denied.value.status_code == 404
    finally:
        conn.close()


def test_ticket_tenant_scope_is_enforced_when_tenant_isolation_is_enabled(isolated_db, make_user, monkeypatch):
    from core import rbac as rbac_module
    from core import tenant_policy
    from database import get_db_connection
    from services import incident_ticket_service, rack_scope_service
    from services.incident_ticket_service import create_ticket_from_incident, get_ticket_detail, list_tickets

    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", True)
    monkeypatch.setattr(rbac_module, "TENANT_ISOLATION_ENABLED", True)
    monkeypatch.setattr(rack_scope_service, "TENANT_ISOLATION_ENABLED", True)
    monkeypatch.setattr(incident_ticket_service, "TENANT_ISOLATION_ENABLED", True)
    owner = _actor(make_user("ticket_tenant_owner", role="Operator", tenant_id="tenant-a"))
    other = _actor(make_user("ticket_tenant_other", role="Operator", tenant_id="tenant-b"))
    conn = get_db_connection()
    try:
        _insert_source_incident(conn, "incident-tenant-a", "device-tenant-a", tenant_id="tenant-a")
        ticket, _ = create_ticket_from_incident(conn, "incident-tenant-a", owner)
        conn.commit()
        assert [item["id"] for item in list_tickets(conn, owner)["items"]] == [ticket["id"]]
        assert list_tickets(conn, other)["total"] == 0
        with pytest.raises(HTTPException) as denied:
            get_ticket_detail(conn, ticket["id"], other)
        assert denied.value.status_code == 404
    finally:
        conn.close()


def test_assignment_requires_active_same_tenant_and_scope_visible_group_members(isolated_db, make_user):
    from api.tickets.routes import api_list_ticket_assignment_group_members
    from database import get_db_connection
    from services.incident_ticket_service import (
        add_assignment_group_member,
        create_assignment_group,
        create_ticket_from_incident,
        perform_ticket_action,
        list_assignment_group_members,
        perform_ticket_action,
    )

    requester = _actor(make_user("ticket_group_requester", role="Operator"))
    admin = _actor(make_user("ticket_group_admin", role="Administrator"))
    member = make_user("ticket_group_member", role="Operator")
    conn = get_db_connection()
    try:
        _insert_source_incident(conn, "incident-group", "device-group", site_id="site-a")
        ticket, _ = create_ticket_from_incident(conn, "incident-group", requester)
        group = create_assignment_group(conn, admin, "Site B responders")
        add_assignment_group_member(conn, group["id"], admin, member["user_id"])
        conn.execute("UPDATE users SET scope_mode = 'restricted' WHERE id = ?", (member["user_id"],))
        conn.execute(
            """
            INSERT INTO user_resource_scopes (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
            VALUES (?, ?, 'incident_ticket', 'site', 'site-b', ?, ?)
            """,
            ("scope-ticket-member-site-b", member["user_id"], json.dumps(["view"]), datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            """
            INSERT INTO user_resource_scopes (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
            VALUES (?, ?, 'asset', 'site', 'site-b', ?, ?)
            """,
            ("scope-ticket-member-asset-b", member["user_id"], json.dumps(["view"]), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

        assert list_assignment_group_members(conn, group["id"], admin, ticket_id=ticket["id"]) == []
        viewer = _actor(make_user("ticket_group_candidate_viewer", role="Viewer"))
        with pytest.raises(HTTPException) as view_only:
            api_list_ticket_assignment_group_members(group["id"], ticket_id=ticket["id"], user=viewer)
        assert view_only.value.status_code == 403

        with pytest.raises(HTTPException) as error:
            perform_ticket_action(
                conn,
                ticket["id"],
                admin,
                action="assign",
                assignment_group_id=group["id"],
            )
        assert error.value.status_code == 422
        with pytest.raises(HTTPException) as non_admin:
            create_assignment_group(conn, requester, "Forbidden group")
        assert non_admin.value.status_code == 403
    finally:
        conn.close()


def test_group_member_cannot_be_removed_while_assigned_ticket_is_active(isolated_db, make_user):
    from database import get_db_connection
    from services.incident_ticket_service import (
        add_assignment_group_member,
        create_assignment_group,
        create_ticket_from_incident,
        list_assignment_group_members,
        perform_ticket_action,
        remove_assignment_group_member,
    )

    admin = _actor(make_user("ticket_group_removal_admin", role="Administrator"))
    member = make_user("ticket_group_removal_member", role="Operator")
    member_actor = _actor(member)
    conn = get_db_connection()
    try:
        _insert_source_incident(conn, "incident-group-removal", "device-group-removal")
        ticket, _ = create_ticket_from_incident(conn, "incident-group-removal", admin)
        group = create_assignment_group(conn, admin, "Active ticket responders")
        add_assignment_group_member(conn, group["id"], admin, member["user_id"])
        perform_ticket_action(
            conn,
            ticket["id"],
            admin,
            action="assign",
            assignment_group_id=group["id"],
            assignee_id=member["user_id"],
        )
        assert len(list_assignment_group_members(conn, group["id"], admin)) == 1
        with pytest.raises(HTTPException) as non_admin:
            list_assignment_group_members(conn, group["id"], member_actor)
        assert non_admin.value.status_code == 403
        with pytest.raises(HTTPException) as assigned:
            remove_assignment_group_member(conn, group["id"], admin, member["user_id"])
        assert assigned.value.status_code == 409
    finally:
        conn.close()


def test_my_todo_hides_terminal_assignee_and_group_tickets(isolated_db, make_user):
    from database import get_db_connection
    from services.incident_ticket_service import (
        add_assignment_group_member,
        create_assignment_group,
        create_ticket_from_incident,
        list_tickets,
        perform_ticket_action,
    )

    admin = _actor(make_user("ticket_todo_admin", role="Administrator"))
    member = _actor(make_user("ticket_todo_member", role="Operator"))
    conn = get_db_connection()
    try:
        _insert_source_incident(conn, "incident-todo-assignee", "device-todo-assignee")
        _insert_source_incident(conn, "incident-todo-group", "device-todo-group")
        assignee_ticket, _ = create_ticket_from_incident(conn, "incident-todo-assignee", admin)
        group_ticket, _ = create_ticket_from_incident(conn, "incident-todo-group", admin)
        group = create_assignment_group(conn, admin, "Todo responders")
        add_assignment_group_member(conn, group["id"], admin, member["user_id"])
        perform_ticket_action(conn, assignee_ticket["id"], admin, action="assign", assignee_id=member["user_id"])
        perform_ticket_action(conn, group_ticket["id"], admin, action="assign", assignment_group_id=group["id"])
        conn.commit()

        active_ids = {item["id"] for item in list_tickets(conn, member, my_todo=True)["items"]}
        assert active_ids == {assignee_ticket["id"], group_ticket["id"]}
        conn.execute("UPDATE incident_tickets SET status = 'closed' WHERE id = ?", (assignee_ticket["id"],))
        conn.execute("UPDATE incident_tickets SET status = 'cancelled' WHERE id = ?", (group_ticket["id"],))
        conn.commit()
        assert list_tickets(conn, member, my_todo=True)["total"] == 0
    finally:
        conn.close()


def test_assignment_group_delete_blocks_nonterminal_ticket_and_allows_unused_group(isolated_db, make_user):
    from api.tickets.routes import api_delete_ticket_assignment_group
    from database import get_db_connection
    from services.incident_ticket_service import (
        add_assignment_group_member,
        create_assignment_group,
        create_ticket_from_incident,
        perform_ticket_action,
    )

    admin = _actor(make_user("ticket_group_delete_admin", role="Administrator"))
    member = make_user("ticket_group_delete_member", role="Operator")
    conn = get_db_connection()
    try:
        _insert_source_incident(conn, "incident-group-delete", "device-group-delete")
        ticket, _ = create_ticket_from_incident(conn, "incident-group-delete", admin)
        group = create_assignment_group(conn, admin, "Group with active ticket")
        add_assignment_group_member(conn, group["id"], admin, member["user_id"])
        perform_ticket_action(conn, ticket["id"], admin, action="assign", assignment_group_id=group["id"])
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(HTTPException) as active_ticket:
        api_delete_ticket_assignment_group(group["id"], admin)
    assert active_ticket.value.status_code == 409

    conn = get_db_connection()
    try:
        perform_ticket_action(conn, ticket["id"], admin, action="cancel", reason="No longer needed")
        conn.commit()
    finally:
        conn.close()

    deleted = api_delete_ticket_assignment_group(group["id"], admin)
    assert deleted["success"] is True
    conn = get_db_connection()
    try:
        unused_group = create_assignment_group(conn, admin, "Unused group")
        conn.commit()
    finally:
        conn.close()
    unused_deleted = api_delete_ticket_assignment_group(unused_group["id"], admin)
    assert unused_deleted["data"]["deleted"] is True
    conn = get_db_connection()
    try:
        persisted_ticket = conn.execute("SELECT status, assigned_group_id FROM incident_tickets WHERE id = ?", (ticket["id"],)).fetchone()
        assert persisted_ticket["status"] == "cancelled"
        assert persisted_ticket["assigned_group_id"] is None
    finally:
        conn.close()


def test_ticket_search_matches_ticket_number_and_related_device_identity(isolated_db, make_user):
    from database import get_db_connection
    from services.incident_ticket_service import create_ticket_from_incident, list_tickets

    actor = _actor(make_user("ticket_search_actor", role="Operator"))
    conn = get_db_connection()
    try:
        _insert_source_incident(conn, "incident-search", "device-search")
        ticket, _ = create_ticket_from_incident(conn, "incident-search", actor)
        conn.commit()
        by_number = list_tickets(conn, actor, search=ticket["ticket_number"])
        by_hostname = list_tickets(conn, actor, search="device-search.example")
        by_ip = list_tickets(conn, actor, search="192.0.2.10")
        assert [item["id"] for item in by_number["items"]] == [ticket["id"]]
        assert [item["id"] for item in by_hostname["items"]] == [ticket["id"]]
        assert [item["id"] for item in by_ip["items"]] == [ticket["id"]]
    finally:
        conn.close()


def test_monitoring_resolution_does_not_close_ticket_and_recurrence_returns_confirmation_to_progress(isolated_db, make_user):
    from database import get_db_connection
    from services.incident_ticket_service import perform_ticket_action
    from services.monitoring_incident_service import sync_incidents

    actor = _actor(make_user("ticket_responder", role="Operator"))
    conn = get_db_connection()
    try:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        _insert_source_incident(conn, "placeholder", "device-reopen")
        # Exercise the projection's identity derivation rather than a hand-made incident row.
        conn.execute("DELETE FROM monitoring_incident_alerts WHERE incident_id = ?", ("placeholder",))
        conn.execute("DELETE FROM monitoring_incidents WHERE id = ?", ("placeholder",))
        conn.execute("DELETE FROM alert_events WHERE id = ?", ("alert-placeholder",))
        conn.execute(
            "INSERT INTO alert_events (id, dedupe_key, source, severity, title, message, device_id, created_at, workflow_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')",
            ("alert-reopen", "ping_unreachable:device-reopen", "network_monitor", "major", "Device unreachable", "Probe failed", "device-reopen", now),
        )
        incident = sync_incidents(conn)[0]
        ticket, _ = __import__("services.incident_ticket_service", fromlist=["create_ticket_from_incident"]).create_ticket_from_incident(conn, incident["id"], actor)
        perform_ticket_action(conn, ticket["id"], actor, action="claim")
        perform_ticket_action(conn, ticket["id"], actor, action="start")
        with pytest.raises(HTTPException) as missing_evidence:
            perform_ticket_action(conn, ticket["id"], actor, action="request_confirmation")
        assert missing_evidence.value.status_code == 422
        perform_ticket_action(
            conn,
            ticket["id"],
            actor,
            action="request_confirmation",
            summary="Probe and interface health recovered",
            evidence=[{"kind": "monitoring", "reference": "alert-reopen"}],
        )
        conn.commit()

        conn.execute("UPDATE alert_events SET resolved_at = ?, workflow_status = 'resolved' WHERE id = ?", (now, "alert-reopen"))
        sync_incidents(conn, return_incidents=False)
        assert conn.execute("SELECT status FROM incident_tickets WHERE id = ?", (ticket["id"],)).fetchone()["status"] == "pending_confirmation"

        conn.execute("UPDATE alert_events SET resolved_at = NULL, workflow_status = 'open' WHERE id = ?", ("alert-reopen",))
        sync_incidents(conn, return_incidents=False)
        refreshed = conn.execute("SELECT status, source_status FROM incident_tickets WHERE id = ?", (ticket["id"],)).fetchone()
        assert refreshed["status"] == "in_progress"
        assert refreshed["source_status"] == "open"
        event_types = [row["event_type"] for row in conn.execute("SELECT event_type FROM incident_ticket_events WHERE ticket_id = ? ORDER BY created_at", (ticket["id"],)).fetchall()]
        assert "source_status_changed" in event_types
        assert "source_reopened_returned_to_progress" in event_types
        from services.incident_ticket_service import get_ticket_detail
        details = get_ticket_detail(conn, ticket["id"], actor)
        assert details["ticket"]["ticket_number"].startswith("INC-")
        assert details["ticket"]["priority"] == "P2"
        assert details["ticket"]["priority_label"] == "high"
        assert details["latest_recovery"]["summary"] == "Probe and interface health recovered"
        assert details["latest_recovery"]["evidence"] == [{"kind": "monitoring", "reference": "alert-reopen"}]
        assert details["ticket"]["recovery_evidence"] == details["latest_recovery"]["evidence"]
    finally:
        conn.close()


def test_change_order_schema_and_atomic_incident_ticket_link(isolated_db, make_user, monkeypatch):
    from api.change_orders import core as change_order_api
    from api.change_orders.schemas import ChangeOrderCreate, ChangeOrderUpdate
    from database import get_db_connection
    from services.incident_ticket_service import create_ticket_from_incident

    actor = _actor(make_user("ticket_link_creator", role="Operator"))
    conn = get_db_connection()
    try:
        _insert_source_incident(conn, "incident-link-a", "device-link-a")
        _insert_source_incident(conn, "incident-link-b", "device-link-b")
        ticket_a, _ = create_ticket_from_incident(conn, "incident-link-a", actor)
        ticket_b, _ = create_ticket_from_incident(conn, "incident-link-b", actor)
        conn.commit()
        assert ticket_a["incident_id"] == "incident-link-a"
        assert ticket_a["requester_id"] == actor["user_id"]
        assert ticket_a["requester_username"] == actor["username"]
    finally:
        conn.close()

    monkeypatch.setattr(change_order_api, "is_template_required", lambda: False)
    monkeypatch.setattr(change_order_api, "is_control_sheet_enabled", lambda: False)
    body = ChangeOrderCreate(
        title="Ticket linked change",
        incident_id=ticket_a["incident_id"],
        incident_ticket_id=ticket_a["id"],
        target_devices=[{"id": "device-link-a"}],
        commands=["show version"],
    )
    assert body.model_dump()["incident_ticket_id"] == ticket_a["id"]
    created = change_order_api.api_create_change_order(body, actor)
    assert created["success"] is True
    order_id = created["data"]["id"]
    with pytest.raises(HTTPException) as target_error:
        change_order_api.api_update_change_order(
            order_id,
            ChangeOrderUpdate(target_devices=[{"id": "device-link-b"}]),
            actor,
        )
    assert target_error.value.status_code == 422
    conn = get_db_connection()
    try:
        link = conn.execute(
            "SELECT ticket_id, change_order_id FROM incident_ticket_links WHERE change_order_id = ?",
            (order_id,),
        ).fetchone()
        assert link["ticket_id"] == ticket_a["id"]
        event = conn.execute(
            "SELECT event_type FROM incident_ticket_events WHERE ticket_id = ? AND details_json ->> 'change_order_id' = ?",
            (ticket_a["id"], order_id),
        ).fetchone()
        assert event["event_type"] == "change_order_linked"
        from services.incident_ticket_service import get_ticket_detail
        owner_detail = get_ticket_detail(conn, ticket_a["id"], actor)
        assert [item["id"] for item in owner_detail["linked_change_orders"]] == [order_id]
        before = conn.execute("SELECT COUNT(*) AS c FROM change_orders").fetchone()["c"]
    finally:
        conn.close()

    mismatched = ChangeOrderCreate(
        title="Reject mismatched ticket",
        incident_id="incident-link-a",
        incident_ticket_id=ticket_b["id"],
        target_devices=[{"id": "device-link-a"}],
        commands=["show version"],
    )
    with pytest.raises(HTTPException) as error:
        change_order_api.api_create_change_order(mismatched, actor)
    assert error.value.status_code == 422
    conn = get_db_connection()
    try:
        after = conn.execute("SELECT COUNT(*) AS c FROM change_orders").fetchone()["c"]
        assert after == before
    finally:
        conn.close()


def test_linked_change_order_summary_obeys_change_requester_ownership(isolated_db, make_user, monkeypatch):
    from api.change_orders import core as change_order_api
    from api.change_orders.schemas import ChangeOrderCreate
    from database import get_db_connection
    from services.incident_ticket_service import create_ticket_from_incident, get_ticket_detail

    owner = _actor(make_user("ticket_order_owner", role="Operator"))
    stranger = make_user("ticket_order_stranger", role="Viewer")
    stranger_actor = _actor({**stranger, "role_profile": "Change Requester"})
    conn = get_db_connection()
    try:
        _insert_source_incident(conn, "incident-order-privacy", "device-order-privacy")
        ticket, _ = create_ticket_from_incident(conn, "incident-order-privacy", owner)
        conn.execute("UPDATE users SET role_profile = 'Change Requester', scope_mode = 'restricted' WHERE id = ?", (stranger["user_id"],))
        for resource, action, ident in (
            ("incident_ticket", "view", "ticket-order-stranger-ticket"),
            ("asset", "view", "ticket-order-stranger-asset"),
        ):
            conn.execute(
                "INSERT INTO user_resource_scopes (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at) VALUES (?, ?, ?, 'site', 'site-a', ?, ?)",
                (ident, stranger["user_id"], resource, json.dumps([action]), datetime.now(timezone.utc).isoformat()),
            )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(change_order_api, "is_template_required", lambda: False)
    monkeypatch.setattr(change_order_api, "is_control_sheet_enabled", lambda: False)
    created = change_order_api.api_create_change_order(
        ChangeOrderCreate(
            title="Private order summary",
            incident_id="incident-order-privacy",
            incident_ticket_id=ticket["id"],
            target_devices=[{"id": "device-order-privacy"}],
        ),
        owner,
    )
    conn = get_db_connection()
    try:
        detail = get_ticket_detail(conn, ticket["id"], stranger_actor)
        assert detail["linked_change_orders"] == []
        owner_detail = get_ticket_detail(conn, ticket["id"], owner)
        assert owner_detail["linked_change_orders"][0]["id"] == created["data"]["id"]
    finally:
        conn.close()


def test_change_requester_can_create_confirm_and_cancel_only_owned_tickets(isolated_db, make_user):
    from api.tickets.routes import api_get_incident_ticket
    from database import get_db_connection
    from services.incident_ticket_service import create_ticket_from_incident, perform_ticket_action

    requester = make_user("ticket_change_requester", role="Viewer")
    other_requester = make_user("ticket_other_requester", role="Viewer")
    responder = _actor(make_user("ticket_requester_responder", role="Operator"))
    requester_actor = _actor({**requester, "role_profile": "Change Requester"})
    other_actor = _actor({**other_requester, "role_profile": "Change Requester"})
    conn = get_db_connection()
    try:
        _insert_source_incident(conn, "incident-requester-own", "device-requester-own")
        _insert_source_incident(conn, "incident-requester-cancel", "device-requester-cancel")
        for user in (requester, other_requester):
            conn.execute("UPDATE users SET role_profile = 'Change Requester', scope_mode = 'restricted' WHERE id = ?", (user["user_id"],))
            for resource, ident in (("incident_ticket", f"ticket-scope-{user['user_id']}"), ("asset", f"asset-scope-{user['user_id']}")):
                conn.execute(
                    "INSERT INTO user_resource_scopes (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at) VALUES (?, ?, ?, 'site', 'site-a', ?, ?)",
                    (ident, user["user_id"], resource, json.dumps(["view", "create", "cancel", "confirm_close"]), datetime.now(timezone.utc).isoformat()),
                )
        own_ticket, _ = create_ticket_from_incident(conn, "incident-requester-own", requester_actor)
        cancel_ticket, _ = create_ticket_from_incident(conn, "incident-requester-cancel", requester_actor)
        conn.commit()
        open_detail = api_get_incident_ticket(own_ticket["id"], requester_actor)
        assert open_detail["data"]["ticket"]["incident_id"] == "incident-requester-own"
        assert open_detail["data"]["ticket"]["requester_id"] == requester["user_id"]
        assert "cancel" in open_detail["data"]["ticket"]["allowed_actions"]
        other_detail = api_get_incident_ticket(own_ticket["id"], other_actor)
        assert other_detail["data"]["ticket"]["allowed_actions"] == []
        perform_ticket_action(conn, own_ticket["id"], responder, action="claim")
        perform_ticket_action(conn, own_ticket["id"], responder, action="start")
        perform_ticket_action(
            conn,
            own_ticket["id"],
            responder,
            action="request_confirmation",
            summary="Service restored",
            evidence={"monitor": "healthy"},
        )
        conn.commit()
        pending_detail = api_get_incident_ticket(own_ticket["id"], requester_actor)
        assert "confirm_close" in pending_detail["data"]["ticket"]["allowed_actions"]
        assert pending_detail["data"]["latest_recovery"]["summary"] == "Service restored"
        from services.incident_ticket_service import list_tickets
        assert [item["id"] for item in list_tickets(conn, requester_actor, my_todo=True)["items"]] == [own_ticket["id"]]
        assert list_tickets(conn, responder, my_todo=True)["total"] == 0
        with pytest.raises(HTTPException) as non_owner_close:
            perform_ticket_action(conn, own_ticket["id"], other_actor, action="confirm_close", summary="not my request")
        assert non_owner_close.value.status_code == 403
        closed = perform_ticket_action(conn, own_ticket["id"], requester_actor, action="confirm_close", summary="Requester confirmed restoration")
        assert closed["status"] == "closed"
        conn.commit()
        closed_detail = api_get_incident_ticket(own_ticket["id"], requester_actor)
        assert closed_detail["data"]["ticket"]["allowed_actions"] == []
        assert all(item["id"] != own_ticket["id"] for item in list_tickets(conn, requester_actor, my_todo=True)["items"])
        with pytest.raises(HTTPException) as non_owner_cancel:
            perform_ticket_action(conn, cancel_ticket["id"], other_actor, action="cancel")
        assert non_owner_cancel.value.status_code == 403
        cancelled = perform_ticket_action(conn, cancel_ticket["id"], requester_actor, action="cancel", reason="No longer required")
        assert cancelled["status"] == "cancelled"
        assert list_tickets(conn, requester_actor, my_todo=True)["total"] == 0
        closure_event = conn.execute(
            "SELECT details_json ->> 'summary' AS summary FROM incident_ticket_events WHERE ticket_id = ? AND event_type = 'confirm_close'",
            (own_ticket["id"],),
        ).fetchone()
        assert closure_event["summary"] == "Requester confirmed restoration"
    finally:
        conn.close()


def test_incident_ticket_events_reject_update_and_delete(isolated_db, make_user):
    from database import get_db_connection
    from services.incident_ticket_service import create_ticket_from_incident

    actor = _actor(make_user("ticket_audit_actor", role="Operator"))
    conn = get_db_connection()
    try:
        _insert_source_incident(conn, "incident-append-only", "device-append-only")
        ticket, _ = create_ticket_from_incident(conn, "incident-append-only", actor)
        conn.commit()
        with pytest.raises(Exception) as error:
            conn.execute("UPDATE incident_ticket_events SET event_type = 'rewritten' WHERE ticket_id = ?", (ticket["id"],))
        assert "incident_ticket_events is append-only" in str(error.value)
        conn.rollback()
    finally:
        conn.close()


def test_monitoring_incident_detail_omits_unfiltered_change_order_summaries(isolated_db, make_user):
    from database import get_db_connection
    from services.monitoring_incident_service import get_incident

    conn = get_db_connection()
    try:
        _insert_source_incident(conn, "incident-no-leak", "device-no-leak")
        conn.execute(
            "INSERT INTO change_orders (id, order_number, title, description, status, created_at, updated_at, incident_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("hidden-order", "BG202610240001", "Hidden change summary", "", "draft", "2026-10-24T00:00:00Z", "2026-10-24T00:00:00Z", "incident-no-leak"),
        )
        detail = get_incident(conn, "incident-no-leak")
        assert detail is not None
        assert "work_orders" not in detail
    finally:
        conn.close()

\n