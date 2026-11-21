from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

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


def _create_group(conn, admin: dict, members: list[dict], name: str) -> dict:
    from services.incident_ticket_service import add_assignment_group_member, create_assignment_group

    group = create_assignment_group(conn, admin, name)
    for member in members:
        add_assignment_group_member(conn, str(group["id"]), admin, str(member["user_id"]))
    return group


def _calendar_schedule(*, all_day: bool = False) -> dict[str, list[dict[str, str]]]:
    weekdays = ("monday", "tuesday", "wednesday", "thursday", "friday")
    end = "24:00" if all_day else "17:00"
    start = "00:00" if all_day else "09:00"
    return {day: [{"start": start, "end": end}] for day in weekdays}


def _insert_source_incident(conn, incident_id: str, device_id: str, *, tenant_id: str = "tenant-default") -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        """
        INSERT INTO devices (id, hostname, ip_address, platform, status, site, site_id, tenant_id, device_group_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET site = excluded.site, site_id = excluded.site_id,
                                      tenant_id = excluded.tenant_id, device_group_id = excluded.device_group_id
        """,
        (device_id, f"{device_id}.example", "192.0.2.55", "cisco_ios", "online", "site-a", "site-a", tenant_id, "group-a"),
    )
    alert_id = f"alert-{incident_id}"
    conn.execute(
        """
        INSERT INTO alert_events (id, dedupe_key, source, severity, title, message, device_id, created_at, workflow_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open') ON CONFLICT(id) DO NOTHING
        """,
        (alert_id, f"ping_unreachable:{device_id}", "network_monitor", "warning", "Device unreachable", "Probe failed", device_id, now),
    )
    conn.execute(
        """
        INSERT INTO monitoring_incidents (
            id, incident_key, title, summary, severity, status, source, root_cause_alert_id,
            primary_device_id, site, first_seen_at, last_seen_at, impact_device_count,
            impact_alert_count, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'warning', 'open', 'alert_events', ?, ?, 'site-a', ?, ?, 1, 1, ?, ?)
        ON CONFLICT(id) DO NOTHING
        """,
        (incident_id, f"incident-key-{incident_id}", f"Incident {incident_id}", "Impact summary", alert_id, device_id, now, now, now, now),
    )
    conn.execute(
        "INSERT INTO monitoring_incident_alerts (incident_id, alert_id, linked_at, is_root) VALUES (?, ?, ?, 1) ON CONFLICT DO NOTHING",
        (incident_id, alert_id, now),
    )


def _insert_change_order(conn, *, order_id: str, number: str, requester: dict, tenant_id: str = "tenant-default") -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        """
        INSERT INTO change_orders (
            id, order_number, title, description, order_type, priority, status,
            requester_id, requester_username, tenant_id, target_devices_json,
            commands_json, created_at, updated_at
        ) VALUES (?, ?, ?, '', 'config_change', 'medium', 'draft', ?, ?, ?, '[]', '[]', ?, ?)
        """,
        (order_id, number, f"{number} 配置变更", requester["user_id"], requester["username"], tenant_id, now, now),
    )


def _create_ready_catalog(conn, admin: dict, group_id: str, *, approval_group_id: str | None = None, requires_approval: bool = False, sla_policy_version_id: str | None = None) -> dict:
    from services.service_request_service import create_catalog_item, publish_catalog_version

    draft = create_catalog_item(conn, admin, key=f"access-{group_id[:8]}", name="账号开通", description="申请网络设备账号")
    assert draft["current_version"] == 0
    assert draft["active"] is False
    return publish_catalog_version(
        conn, draft["id"], admin,
        request_schema={"fields": [
            {"key": "system", "label": "系统名称", "type": "text", "required": True},
            {"key": "reason", "label": "申请原因", "type": "textarea", "required": False},
        ]},
        requires_approval=requires_approval,
        assignment_group_id=group_id,
        approval_group_id=approval_group_id,
        fulfillment_instructions="创建账号并回填权限范围",
        acceptance_criteria="申请人确认能够登录且权限符合申请",
        sla_policy_version_id=sla_policy_version_id,
    )


def test_m0293_migration_is_repeatable_and_published_versions_are_immutable(isolated_db):
    from database import get_db_connection
    from database.migrations.m0293_service_requests_sla import upgrade

    conn = get_db_connection()
    try:
        upgrade(conn.cursor(), use_pg=True)
        upgrade(conn.cursor(), use_pg=True)
        version = conn.execute("SELECT name FROM schema_migrations WHERE version = 293").fetchone()
        assert version["name"] == "service_requests_sla"
        trigger_rows = conn.execute(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname IN ('trg_service_catalog_versions_immutable', 'trg_ticket_work_calendar_versions_immutable', 'trg_ticket_sla_policy_versions_immutable', 'trg_ticket_notification_attempts_append_only')"
        ).fetchall()
        assert len(trigger_rows) == 4
    finally:
        conn.close()


def test_catalog_starts_as_draft_request_uses_immutable_snapshot_and_approval_group(isolated_db, make_user):
    from database import get_db_connection
    from services.service_request_service import (
        create_service_request,
        get_service_request_detail,
        publish_catalog_version,
        create_catalog_item,
        perform_service_request_action,
    )

    admin = _actor(make_user("catalog_admin", role="Administrator", tenant_id="tenant-default"))
    requester = _actor(make_user("catalog_requester", role="Operator", tenant_id="tenant-default"))
    approver_user = make_user("catalog_approver", role="Operator", tenant_id="tenant-default")
    assignee_user = make_user("catalog_assignee", role="Operator", tenant_id="tenant-default")
    conn = get_db_connection()
    try:
        assignment_group = _create_group(conn, admin, [assignee_user], "Access Fulfillment")
        approval_group = _create_group(conn, admin, [approver_user], "Access Approval")
        draft = create_catalog_item(conn, admin, key="account-access", name="账号开通", description="网络设备账号")
        assert draft["current_version"] == 0
        assert not draft["active"]
        assert conn.execute("SELECT COUNT(*) AS c FROM service_catalog_versions WHERE catalog_item_id = ?", (draft["id"],)).fetchone()["c"] == 0
        with pytest.raises(HTTPException) as unpublished:
            create_service_request(conn, requester, catalog_item_id=draft["id"], version=0, title="开通账号", details={})
        assert unpublished.value.status_code == 409

        version_one = publish_catalog_version(
            conn, draft["id"], admin,
            request_schema={"fields": [{"key": "system", "label": "系统名称", "type": "text", "required": True}]},
            requires_approval=True, assignment_group_id=assignment_group["id"],
            approval_group_id=approval_group["id"], fulfillment_instructions="创建账号",
            acceptance_criteria="申请人验证登录", sla_policy_version_id=None,
        )
        created = create_service_request(
            conn, requester, catalog_item_id=draft["id"], version=1,
            title="开通核心设备账号", details={"system": "核心交换机"},
        )
        conn.commit()
        assert created["status"] == "pending_approval"
        detail = get_service_request_detail(conn, created["id"], requester)
        assert detail["request"]["catalog_snapshot"]["version"] == 1
        assert detail["request"]["ticket_key"].startswith("SR-")
        assert detail["sla"]["configured"] is False
        assert {clock["status"] for clock in detail["sla"]["clocks"]} == {"not_configured"}
        with pytest.raises(HTTPException) as self_approval:
            perform_service_request_action(conn, created["id"], requester, action="approve")
        assert self_approval.value.status_code == 403

        approver = _actor(approver_user)
        approved = perform_service_request_action(conn, created["id"], approver, action="approve")
        assert approved["status"] == "accepted"
        version_two = publish_catalog_version(
            conn, draft["id"], admin,
            request_schema={"fields": [{"key": "system", "label": "系统名称", "type": "text", "required": True}, {"key": "reason", "label": "原因", "type": "textarea", "required": True}]},
            requires_approval=False, assignment_group_id=assignment_group["id"], approval_group_id=None,
            fulfillment_instructions="创建账号并回填权限", acceptance_criteria="申请人验证登录", sla_policy_version_id=None,
        )
        assert version_one["version"] == 1 and version_two["version"] == 2
        assert get_service_request_detail(conn, created["id"], requester)["request"]["catalog_snapshot"]["version"] == 1
        conn.commit()

        with pytest.raises(Exception, match="published ITSM versions are immutable"):
            conn.execute("UPDATE service_catalog_versions SET acceptance_criteria = 'changed' WHERE catalog_item_id = ? AND version = 1", (draft["id"],))
        conn.rollback()
    finally:
        conn.close()


def test_work_calendar_sla_pause_resume_warning_and_breach_once(isolated_db, make_user, monkeypatch):
    from database import get_db_connection
    from services import service_request_service as service
    from services.service_request_service import (
        create_or_version_sla_policy,
        create_or_version_work_calendar,
        create_service_request,
        get_service_request_detail,
        perform_service_request_action,
    )

    admin = _actor(make_user("sla_admin", role="Administrator", tenant_id="tenant-default"))
    requester = _actor(make_user("sla_requester", role="Operator", tenant_id="tenant-default"))
    responder_user = make_user("sla_responder", role="Operator", tenant_id="tenant-default")
    conn = get_db_connection()
    try:
        group = _create_group(conn, admin, [responder_user], "SLA Fulfillment")
        calendar = create_or_version_work_calendar(
            conn, admin, calendar_id=None, name="Weekdays Shanghai", timezone_name="Asia/Shanghai",
            schedule=_calendar_schedule(), holidays=["2026-01-06"],
        )
        policy = create_or_version_sla_policy(
            conn, admin, policy_id=None, name="P3 Service Request", source_type="service_request", priority="P3",
            response_target_minutes=60, restore_target_minutes=None, fulfillment_target_minutes=120,
            warning_before_minutes=30, calendar_version_id=calendar["version_id"],
        )
        catalog = _create_ready_catalog(conn, admin, group["id"], sla_policy_version_id=policy["version_id"])
        current_time = [datetime(2026, 1, 5, 16, 30, tzinfo=ZoneInfo("Asia/Shanghai"))]
        monkeypatch.setattr(service, "_now", lambda: current_time[0])
        request = create_service_request(conn, requester, catalog_item_id=catalog["id"], version=1, title="开通账号", details={"system": "core"})
        conn.commit()
        detail = get_service_request_detail(conn, request["id"], requester)
        assert detail["sla"]["configured"] is True
        response_clock = next(item for item in detail["sla"]["clocks"] if item["kind"] == "response")
        fulfillment_clock = next(item for item in detail["sla"]["clocks"] if item["kind"] == "fulfillment")
        assert response_clock["deadline_at"] == "2026-01-07T01:30:00+00:00"
        assert fulfillment_clock["deadline_at"] == "2026-01-07T02:30:00+00:00"

        perform_service_request_action(conn, request["id"], admin, action="assign", assignment_group_id=group["id"])
        perform_service_request_action(conn, request["id"], admin, action="assign", assignment_group_id=group["id"], reason="same-second reassignment")
        assignment_notifications = conn.execute(
            "SELECT COUNT(*) AS c FROM ticket_notification_outbox WHERE service_request_id = ? AND event_key LIKE ?",
            (request["id"], f"service_request:{request['id']}:assigned:%"),
        ).fetchone()["c"]
        assert assignment_notifications == 2
        responder = _actor(responder_user)
        perform_service_request_action(conn, request["id"], responder, action="claim")
        current_time[0] = datetime(2026, 1, 7, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        perform_service_request_action(conn, request["id"], responder, action="start")
        current_time[0] = datetime(2026, 1, 7, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        perform_service_request_action(conn, request["id"], responder, action="wait_external")
        paused = get_service_request_detail(conn, request["id"], requester)["sla"]
        fulfillment_clock = next(item for item in paused["clocks"] if item["kind"] == "fulfillment")
        assert fulfillment_clock["status"] == "paused"
        assert fulfillment_clock["remaining_seconds"] == 60 * 60

        current_time[0] = datetime(2026, 1, 7, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        perform_service_request_action(conn, request["id"], responder, action="resume")
        resumed = get_service_request_detail(conn, request["id"], requester)["sla"]
        fulfillment_clock = next(item for item in resumed["clocks"] if item["kind"] == "fulfillment")
        assert fulfillment_clock["status"] == "running"
        assert fulfillment_clock["deadline_at"] == "2026-01-07T07:00:00+00:00"
        clock_id = conn.execute("SELECT id FROM ticket_sla_clocks WHERE service_request_id = ? AND kind = 'fulfillment'", (request["id"],)).fetchone()["id"]

        current_time[0] = datetime(2026, 1, 7, 14, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
        perform_service_request_action(conn, request["id"], responder, action="deliver", summary="账号已创建", evidence={"change": "CHG-1"})
        pending_confirmation = get_service_request_detail(conn, request["id"], requester)["sla"]
        fulfillment_clock = next(item for item in pending_confirmation["clocks"] if item["kind"] == "fulfillment")
        assert fulfillment_clock["status"] == "paused"
        assert fulfillment_clock["remaining_seconds"] == 45 * 60
        current_time[0] = datetime(2026, 1, 7, 14, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        perform_service_request_action(conn, request["id"], requester, action="return", reason="权限范围需要调整")
        after_return = get_service_request_detail(conn, request["id"], requester)["sla"]
        fulfillment_clock = next(item for item in after_return["clocks"] if item["kind"] == "fulfillment")
        assert fulfillment_clock["status"] == "running"
        assert fulfillment_clock["deadline_at"] == "2026-01-07T07:15:00+00:00"

        current_time[0] = datetime(2026, 1, 7, 14, 45, tzinfo=ZoneInfo("Asia/Shanghai"))
        assert service.evaluate_due_sla_clocks(conn) == 1
        assert service.evaluate_due_sla_clocks(conn) == 0
        warning = conn.execute("SELECT COUNT(*) AS c FROM ticket_sla_events WHERE clock_id = ? AND event_type = 'warning_approaching'", (clock_id,)).fetchone()["c"]
        assert warning == 1
        current_time[0] = datetime(2026, 1, 7, 15, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
        assert service.evaluate_due_sla_clocks(conn) == 1
        assert service.evaluate_due_sla_clocks(conn) == 0
        breach = conn.execute("SELECT COUNT(*) AS c FROM ticket_sla_events WHERE clock_id = ? AND event_type = 'breached'", (clock_id,)).fetchone()["c"]
        assert breach == 1
        assert conn.execute("SELECT status FROM ticket_sla_clocks WHERE id = ?", (clock_id,)).fetchone()["status"] == "breached"
        conn.commit()
    finally:
        conn.close()


def test_calendar_supports_end_of_day_and_notification_attempt_history(isolated_db, make_user):
    from database import get_db_connection
    from services.service_request_service import (
        claim_ticket_notifications,
        create_service_request,
        create_or_version_work_calendar,
        finish_ticket_notification,
    )
    from services import service_request_service as service
    from zoneinfo import ZoneInfo

    admin = _actor(make_user("relay_admin", role="Administrator", tenant_id="tenant-default"))
    requester = _actor(make_user("relay_requester", role="Operator", tenant_id="tenant-default"))
    responder = make_user("relay_responder", role="Operator", tenant_id="tenant-default")
    conn = get_db_connection()
    try:
        group = _create_group(conn, admin, [responder], "Relay Group")
        calendar = create_or_version_work_calendar(
            conn, admin, calendar_id=None, name="24x7", timezone_name="Asia/Shanghai",
            schedule=_calendar_schedule(all_day=True), holidays=[],
        )
        start = datetime(2026, 1, 5, 23, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        due = service._add_working_seconds(conn, calendar["version_id"], start, 2 * 60 * 60)
        assert due == datetime(2026, 1, 5, 17, 0, tzinfo=timezone.utc)
        assert service._calendar_working_seconds(conn, calendar["version_id"], start, due) == 2 * 60 * 60

        catalog = _create_ready_catalog(conn, admin, group["id"])
        request = create_service_request(conn, requester, catalog_item_id=catalog["id"], version=1, title="开通账号", details={"system": "core"})
        conn.commit()
        pending = conn.execute("SELECT id FROM ticket_notification_outbox WHERE service_request_id = ? AND status = 'pending' ORDER BY id", (request["id"],)).fetchone()
        assert pending
        worker_id = "test-ticket-relay-1"
        claimed = claim_ticket_notifications(conn, limit=1, worker_id=worker_id)
        assert len(claimed) == 1
        delivery_id = claimed[0]["id"]
        conn.commit()
        finish_ticket_notification(conn, delivery_id=delivery_id, worker_id=worker_id, success=False, error_code="test_failure")
        conn.commit()
        failed = conn.execute("SELECT status, attempts FROM ticket_notification_outbox WHERE id = ?", (delivery_id,)).fetchone()
        assert failed["status"] == "failed" and failed["attempts"] == 1
        conn.execute("UPDATE ticket_notification_outbox SET available_at = clock_timestamp() - INTERVAL '1 second' WHERE id = ?", (delivery_id,))
        claimed_again = claim_ticket_notifications(conn, limit=1, worker_id="test-ticket-relay-2")
        assert len(claimed_again) == 1
        finish_ticket_notification(conn, delivery_id=delivery_id, worker_id="test-ticket-relay-2", success=True)
        conn.commit()
        history = conn.execute("SELECT attempt_no, phase FROM ticket_notification_attempts WHERE outbox_id = ? ORDER BY attempt_no, phase", (delivery_id,)).fetchall()
        assert [(row["attempt_no"], row["phase"]) for row in history] == [(1, "failed"), (1, "started"), (2, "sent"), (2, "started")]
        assert conn.execute("SELECT status FROM ticket_notification_outbox WHERE id = ?", (delivery_id,)).fetchone()["status"] == "sent"
    finally:
        conn.close()


def test_ticket_notification_relay_uses_existing_sender_for_exact_recipients(isolated_db, make_user, monkeypatch):
    from database import get_db_connection
    from services import notification_service
    from services.service_request_service import (
        create_service_request,
        relay_ticket_notifications_once,
    )

    admin = _actor(make_user("relay_dispatch_admin", role="Administrator", tenant_id="tenant-default"))
    requester = _actor(make_user("relay_dispatch_requester", role="Operator", tenant_id="tenant-default"))
    responder = make_user("relay_dispatch_responder", role="Operator", tenant_id="tenant-default")
    conn = get_db_connection()
    try:
        group = _create_group(conn, admin, [responder], "Targeted Relay Group")
        catalog = _create_ready_catalog(conn, admin, group["id"])
        request = create_service_request(conn, requester, catalog_item_id=catalog["id"], version=1, title="Relay test", details={"system": "core"})
        conn.commit()

        deliveries: list[tuple[list[str], str]] = []
        monkeypatch.setattr(notification_service, "automatic_notifications_enabled", lambda: True)

        def capture_dispatch(alert, user_ids, tenant_id, **kwargs):
            deliveries.append((list(user_ids), tenant_id))
            return [{"success": True, "platform": "workspace", "recipient_count": len(user_ids)}]

        monkeypatch.setattr(notification_service, "dispatch_to_user_ids", capture_dispatch)
        result = relay_ticket_notifications_once(limit=10)
        assert result["claimed"] == 1
        assert result["sent"] == 1
        assert deliveries == [([responder["user_id"]], "tenant-default")]
        sent = conn.execute(
            "SELECT id FROM ticket_notification_outbox WHERE service_request_id = ? AND status = 'sent'",
            (request["id"],),
        ).fetchall()
        assert len(sent) == 1
        phases = conn.execute(
            "SELECT phase FROM ticket_notification_attempts WHERE outbox_id = ? ORDER BY phase",
            (sent[0]["id"],),
        ).fetchall()
        assert {row["phase"] for row in phases} == {"started", "sent"}
    finally:
        conn.close()


def test_service_request_change_order_link_is_idempotent_scoped_and_filtered(isolated_db, make_user):
    from database import get_db_connection
    from database.migrations.m0294_service_request_change_order_links import upgrade
    from services.service_request_service import (
        create_service_request,
        get_service_request_detail,
        link_change_order_to_service_request,
    )

    admin = _actor(make_user("sr_link_admin", role="Administrator", tenant_id="tenant-default"))
    requester = _actor(make_user("sr_link_requester", role="Operator", tenant_id="tenant-default"))
    responder = make_user("sr_link_responder", role="Operator", tenant_id="tenant-default")
    approver = _actor(make_user("sr_link_approver", role="Operator", tenant_id="tenant-default"))
    limited_user = make_user("sr_link_limited", role="Viewer", tenant_id="tenant-default")
    other_owner = make_user("sr_link_order_owner", role="Operator", tenant_id="tenant-default")
    conn = get_db_connection()
    try:
        upgrade(conn.cursor(), use_pg=True)
        upgrade(conn.cursor(), use_pg=True)
        conn.execute("UPDATE users SET role_profile = 'Change Requester' WHERE id = ?", (limited_user["user_id"],))
        limited = {**_actor(limited_user), "role_profile": "Change Requester"}
        group = _create_group(conn, admin, [responder, limited_user], "Service Request Link Group")
        approval_group = _create_group(conn, admin, [approver], "Service Request Link Approvers")
        catalog = _create_ready_catalog(conn, admin, group["id"], approval_group_id=approval_group["id"], requires_approval=True)
        request = create_service_request(conn, requester, catalog_item_id=catalog["id"], version=1, title="配置变更申请", details={"system": "core"})
        _insert_change_order(conn, order_id="co-link-owned", number="CHG-2026-101", requester=requester)
        _insert_change_order(conn, order_id="co-link-other-owner", number="CHG-2026-102", requester=other_owner)
        _insert_change_order(conn, order_id="co-link-other-tenant", number="CHG-2026-103", requester=other_owner, tenant_id="tenant-other")
        _insert_change_order(conn, order_id="co-link-limited-owner", number="CHG-2026-104", requester=limited_user)
        _insert_change_order(conn, order_id="co-link-responder-owner", number="CHG-2026-105", requester=responder)
        _insert_change_order(conn, order_id="co-link-approver-owner", number="CHG-2026-106", requester=approver)
        conn.commit()

        first = link_change_order_to_service_request(conn, request["id"], requester, change_order_number="CHG-2026-101")
        duplicate = link_change_order_to_service_request(conn, request["id"], requester, change_order_number="CHG-2026-101")
        assert first["created"] is True
        assert duplicate["created"] is False
        assert link_change_order_to_service_request(conn, request["id"], approver, change_order_number="CHG-2026-106")["created"] is True
        assert link_change_order_to_service_request(conn, request["id"], _actor(responder), change_order_number="CHG-2026-105")["created"] is True
        assert link_change_order_to_service_request(conn, request["id"], limited, change_order_number="CHG-2026-104")["created"] is True
        with pytest.raises(HTTPException) as cross_tenant:
            link_change_order_to_service_request(conn, request["id"], requester, change_order_number="CHG-2026-103")
        assert cross_tenant.value.status_code == 404

        # The requester/approver/responder link path still cannot expose a
        # change order that the actor cannot view through the existing domain.
        linked_hidden = link_change_order_to_service_request(conn, request["id"], admin, change_order_number="CHG-2026-102")
        assert linked_hidden["created"] is True
        conn.commit()
        assert conn.execute("SELECT COUNT(*) AS c FROM service_request_change_order_links WHERE service_request_id = ?", (request["id"],)).fetchone()["c"] == 5
        assert conn.execute("SELECT COUNT(*) AS c FROM service_request_events WHERE request_id = ? AND event_type = 'change_order_linked'", (request["id"],)).fetchone()["c"] == 5
        assert conn.execute("SELECT status FROM change_orders WHERE id = 'co-link-owned'").fetchone()["status"] == "draft"

        owner_detail = get_service_request_detail(conn, request["id"], requester)
        assert {item["order_number"] for item in owner_detail["linked_change_orders"]} == {
            "CHG-2026-101", "CHG-2026-102", "CHG-2026-104", "CHG-2026-105", "CHG-2026-106",
        }
        limited_detail = get_service_request_detail(conn, request["id"], limited)
        assert [item["order_number"] for item in limited_detail["linked_change_orders"]] == ["CHG-2026-104"]
        link_events = [event for event in limited_detail["events"] if event["event_type"] == "change_order_linked"]
        assert len(link_events) == 5
        hidden_events = [event for event in link_events if "change_order_number" not in event["details"]]
        assert len(hidden_events) == 4
        assert all(event["summary"] == "关联了变更单" for event in hidden_events)
        with pytest.raises(Exception, match="service request change-order links are append-only"):
            conn.execute("UPDATE service_request_change_order_links SET linked_by_username = 'changed' WHERE service_request_id = ?", (request["id"],))
        conn.rollback()
    finally:
        conn.close()


def test_unified_ticket_list_filters_each_source_before_global_pagination(isolated_db, make_user):
    from database import get_db_connection
    from services.incident_ticket_service import create_ticket_from_incident
    from services.service_request_service import create_service_request, list_service_requests, list_unified_tickets

    admin = _actor(make_user("unified_admin", role="Administrator", tenant_id="tenant-default"))
    requester = _actor(make_user("unified_requester", role="Operator", tenant_id="tenant-default"))
    responder = make_user("unified_responder", role="Operator", tenant_id="tenant-default")
    unrelated_viewer = _actor(make_user("unified_unrelated_viewer", role="Viewer", tenant_id="tenant-default"))
    other_tenant = _actor(make_user("unified_other", role="Viewer", tenant_id="tenant-other"))
    conn = get_db_connection()
    try:
        group = _create_group(conn, admin, [responder], "Unified Queue")
        catalog = _create_ready_catalog(conn, admin, group["id"])
        request = create_service_request(conn, requester, catalog_item_id=catalog["id"], version=1, title="统一列表服务申请", details={"system": "core"})
        _insert_source_incident(conn, "incident-unified", "device-unified")
        incident, _ = create_ticket_from_incident(conn, "incident-unified", admin)
        conn.commit()

        first = list_unified_tickets(conn, admin, page=1, page_size=1)
        second = list_unified_tickets(conn, admin, page=2, page_size=1)
        assert first["total"] == 2 and second["total"] == 2
        keys = {first["items"][0]["ticket_key"], second["items"][0]["ticket_key"]}
        assert keys == {request["request_number"], incident["ticket_number"]}
        only_service = list_unified_tickets(conn, admin, source_type="service_request", page_size=10)
        assert only_service["total"] == 1
        assert only_service["items"][0]["source_id"] == request["id"]
        assert only_service["items"][0]["source_type"] == "service_request"
        unrelated = list_unified_tickets(conn, unrelated_viewer, page_size=10)
        assert request["id"] not in {item["source_id"] for item in unrelated["items"]}
        assert list_unified_tickets(conn, unrelated_viewer, source_type="service_request")["total"] == 0
        assert list_service_requests(conn, unrelated_viewer)["total"] == 0
        with pytest.raises(HTTPException) as detail_denied:
            from services.service_request_service import get_service_request_detail

            get_service_request_detail(conn, request["id"], unrelated_viewer)
        assert detail_denied.value.status_code == 404
        other = list_unified_tickets(conn, other_tenant, page_size=10)
        assert other["total"] == 0
    finally:
        conn.close()
