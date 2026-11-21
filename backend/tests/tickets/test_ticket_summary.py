from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException


def _actor(user: dict) -> dict:
    return {
        "id": user["user_id"],
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
        "tenant_id": user.get("tenant_id") or "tenant-default",
        "role_profile": user.get("role_profile", ""),
        "scope_mode": user.get("scope_mode", "legacy"),
    }


def _create_group(conn, admin: dict, members: list[dict], name: str) -> dict:
    from services.incident_ticket_service import add_assignment_group_member, create_assignment_group

    group = create_assignment_group(conn, admin, name)
    for member in members:
        add_assignment_group_member(conn, str(group["id"]), admin, str(member["user_id"]))
    return group


def _create_catalog(conn, admin: dict, group_id: str, key: str) -> dict:
    from services.service_request_service import create_catalog_item, publish_catalog_version

    draft = create_catalog_item(conn, admin, key=key, name=f"目录 {key}", description="summary test")
    return publish_catalog_version(
        conn, draft["id"], admin,
        request_schema={"fields": []}, requires_approval=False,
        assignment_group_id=group_id, approval_group_id=None,
        fulfillment_instructions="履约", acceptance_criteria="申请人确认", sla_policy_version_id=None,
    )


def _insert_incident_source(conn, *, incident_id: str, device_id: str, site: str, tenant_id: str) -> None:
    now = "2026-10-01T08:00:00+00:00"
    conn.execute(
        """
        INSERT INTO devices (id, hostname, ip_address, platform, status, site, site_id, tenant_id, device_group_id)
        VALUES (?, ?, ?, 'cisco_ios', 'online', ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET site = excluded.site, site_id = excluded.site_id,
                                      tenant_id = excluded.tenant_id, device_group_id = excluded.device_group_id
        """,
        (device_id, f"{device_id}.example", "192.0.2.80", site, site, tenant_id, f"dg-{site}"),
    )
    alert_id = f"alert-{incident_id}"
    conn.execute(
        """
        INSERT INTO alert_events (id, dedupe_key, source, severity, title, message, device_id, created_at, workflow_status)
        VALUES (?, ?, 'network_monitor', 'warning', 'Device unreachable', 'Probe failed', ?, ?, 'open')
        """,
        (alert_id, f"ping_unreachable:{device_id}", device_id, now),
    )
    conn.execute(
        """
        INSERT INTO monitoring_incidents (
            id, incident_key, title, summary, severity, status, source, root_cause_alert_id,
            primary_device_id, site, first_seen_at, last_seen_at, impact_device_count,
            impact_alert_count, created_at, updated_at
        ) VALUES (?, ?, ?, 'Impact summary', 'warning', 'open', 'alert_events', ?, ?, ?, ?, ?, 1, 1, ?, ?)
        """,
        (incident_id, f"key-{incident_id}", f"Incident {incident_id}", alert_id, device_id, site, now, now, now, now),
    )
    conn.execute(
        "INSERT INTO monitoring_incident_alerts (incident_id, alert_id, linked_at, is_root) VALUES (?, ?, ?, 1)",
        (incident_id, alert_id, now),
    )


def _append_incident_event(conn, ticket_id: str, event_type: str, created_at: str) -> None:
    conn.execute(
        """
        INSERT INTO incident_ticket_events (id, ticket_id, event_type, actor_id, actor_username, details_json, source_status, created_at)
        VALUES (?, ?, ?, 'summary-worker', 'summary-worker', '{}'::jsonb, '', ?)
        """,
        (f"event-{ticket_id}-{event_type}", ticket_id, event_type, created_at),
    )


def _append_request_event(conn, request_id: str, event_type: str, created_at: str) -> None:
    conn.execute(
        """
        INSERT INTO service_request_events (id, request_id, event_type, actor_id, actor_username, summary, evidence_json, details_json, created_at)
        VALUES (?, ?, ?, 'summary-worker', 'summary-worker', '', 'null'::jsonb, '{}'::jsonb, ?)
        """,
        (f"event-{request_id}-{event_type}", request_id, event_type, created_at),
    )


def test_ticket_summary_utc_date_range_scope_and_event_duration_samples(isolated_db, make_user, monkeypatch):
    from database import get_db_connection
    from services import incident_ticket_service, service_request_service
    from services import rack_scope_service
    from services.incident_ticket_service import create_ticket_from_incident
    from services.service_request_service import create_service_request, get_ticket_summary
    from core import rbac as rbac_module
    from core import tenant_policy

    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", True)
    monkeypatch.setattr(rbac_module, "TENANT_ISOLATION_ENABLED", True)
    monkeypatch.setattr(rack_scope_service, "TENANT_ISOLATION_ENABLED", True)
    monkeypatch.setattr(incident_ticket_service, "TENANT_ISOLATION_ENABLED", True)
    monkeypatch.setattr(service_request_service, "TENANT_ISOLATION_ENABLED", True)

    admin = _actor(make_user("summary_admin", role="Administrator", tenant_id="tenant-default"))
    admin_other = _actor(make_user("summary_admin_other", role="Administrator", tenant_id="tenant-other"))
    requester_a = _actor(make_user("summary_requester_a", role="Operator", tenant_id="tenant-default"))
    requester_b = _actor(make_user("summary_requester_b", role="Operator", tenant_id="tenant-default"))
    responder_a = make_user("summary_responder_a", role="Operator", tenant_id="tenant-default")
    responder_b = make_user("summary_responder_b", role="Operator", tenant_id="tenant-default")
    viewer_user = make_user("summary_scoped_viewer", role="Viewer", tenant_id="tenant-default")
    requester_other = _actor(make_user("summary_requester_other", role="Operator", tenant_id="tenant-other"))
    responder_other = make_user("summary_responder_other", role="Operator", tenant_id="tenant-other")
    conn = get_db_connection()
    try:
        conn.execute("UPDATE users SET role_profile = 'Change Requester', scope_mode = 'restricted' WHERE id = ?", (viewer_user["user_id"],))
        viewer = {**_actor(viewer_user), "role_profile": "Change Requester", "scope_mode": "restricted"}
        group_a = _create_group(conn, admin, [responder_a, viewer_user], "Summary A")
        group_b = _create_group(conn, admin, [responder_b], "Summary B")
        group_other = _create_group(conn, admin_other, [responder_other], "Summary Other Tenant")
        catalog_a = _create_catalog(conn, admin, group_a["id"], "summary-a")
        catalog_b = _create_catalog(conn, admin, group_b["id"], "summary-b")
        catalog_other = _create_catalog(conn, admin_other, group_other["id"], "summary-other")

        fixed_time = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(service_request_service, "_now", lambda: fixed_time)
        monkeypatch.setattr(incident_ticket_service, "_now", lambda: fixed_time.isoformat())
        request_a = create_service_request(conn, requester_a, catalog_item_id=catalog_a["id"], version=1, title="A service request", details={})
        _append_request_event(conn, request_a["id"], "acknowledge", "2026-10-01T09:00:00+00:00")
        _append_request_event(conn, request_a["id"], "confirm_complete", "2026-10-01T11:00:00+00:00")
        conn.execute("UPDATE service_requests SET status = 'completed', completed_at = ? WHERE id = ?", ("2026-10-01T11:00:00+00:00", request_a["id"]))

        request_b = create_service_request(conn, requester_b, catalog_item_id=catalog_b["id"], version=1, title="B service request", details={})
        request_outside = create_service_request(conn, requester_a, catalog_item_id=catalog_a["id"], version=1, title="Outside date range", details={})
        request_cross_tenant = create_service_request(conn, requester_other, catalog_item_id=catalog_other["id"], version=1, title="Other tenant request", details={})
        conn.execute("UPDATE service_requests SET created_at = ? WHERE id = ?", ("2026-10-02T08:00:00+00:00", request_b["id"]))
        conn.execute("UPDATE service_requests SET created_at = ? WHERE id = ?", ("2026-09-30T08:00:00+00:00", request_outside["id"]))

        _insert_incident_source(conn, incident_id="summary-incident-a", device_id="summary-device-a", site="site-a", tenant_id="tenant-default")
        _insert_incident_source(conn, incident_id="summary-incident-b", device_id="summary-device-b", site="site-b", tenant_id="tenant-default")
        incident_a, _ = create_ticket_from_incident(conn, "summary-incident-a", admin)
        incident_b, _ = create_ticket_from_incident(conn, "summary-incident-b", admin)
        conn.execute("UPDATE incident_tickets SET assigned_group_id = ?, status = 'closed', closed_at = ? WHERE id = ?", (group_a["id"], "2026-10-01T10:30:00+00:00", incident_a["id"]))
        conn.execute("UPDATE incident_tickets SET assigned_group_id = ?, created_at = ? WHERE id = ?", (group_b["id"], "2026-10-02T08:00:00+00:00", incident_b["id"]))
        _append_incident_event(conn, incident_a["id"], "start", "2026-10-01T08:30:00+00:00")
        _append_incident_event(conn, incident_a["id"], "request_confirmation", "2026-10-01T10:00:00+00:00")
        _insert_incident_source(conn, incident_id="summary-incident-other", device_id="summary-device-other", site="site-a", tenant_id="tenant-other")
        incident_other, _ = create_ticket_from_incident(conn, "summary-incident-other", admin_other)
        conn.execute("UPDATE incident_tickets SET assigned_group_id = ? WHERE id = ?", (group_other["id"], incident_other["id"]))

        for resource_type in ("incident_ticket", "asset"):
            conn.execute(
                """
                INSERT INTO user_resource_scopes(id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
                VALUES (?, ?, ?, 'site', 'site-a', ?, ?)
                """,
                (f"summary-scope-{resource_type}", viewer["user_id"], resource_type, json.dumps(["view"]), "2026-10-01T08:00:00+00:00"),
            )
        conn.commit()

        visible = get_ticket_summary(conn, viewer, from_date=date(2026, 10, 1), to_date=date(2026, 10, 2))
        assert visible["totals"] == {"all": 2, "incident": 1, "service_request": 1, "active": 0, "closed": 2}
        assert visible["from"] == "2026-10-01" and visible["to"] == "2026-10-02"
        assert visible["by_priority"] == [
            {"priority": "P1", "count": 0}, {"priority": "P2", "count": 0},
            {"priority": "P3", "count": 2}, {"priority": "P4", "count": 0},
        ]
        assert visible["by_assignment_group"] == [{"id": group_a["id"], "name": "Summary A", "count": 2}]
        assert visible["durations_seconds"] == {
            "first_response_avg": 2700.0,
            "incident_restore_avg": 7200.0,
            "service_fulfillment_avg": 10800.0,
            "close_avg": 9900.0,
        }
        assert visible["sample_counts"] == {
            "first_response_avg": 2, "incident_restore_avg": 1,
            "service_fulfillment_avg": 1, "close_avg": 2,
        }
        assert visible["duration_basis"] == "elapsed_utc_ticket_events"

        broad = get_ticket_summary(conn, admin, from_date=date(2026, 10, 1), to_date=date(2026, 10, 2))
        assert broad["totals"]["all"] == 4
        assert request_outside["id"] not in {request_a["id"], request_b["id"]}
        assert request_cross_tenant["tenant_id"] == "tenant-other"
        empty = get_ticket_summary(conn, viewer, from_date=date(2026, 10, 5), to_date=date(2026, 10, 5))
        assert empty["totals"]["all"] == 0
        assert empty["sample_counts"] == {
            "first_response_avg": 0, "incident_restore_avg": 0,
            "service_fulfillment_avg": 0, "close_avg": 0,
        }
        assert all(value is None for value in empty["durations_seconds"].values())
        with pytest.raises(HTTPException) as reversed_range:
            get_ticket_summary(conn, admin, from_date=date(2026, 10, 2), to_date=date(2026, 10, 1))
        assert reversed_range.value.status_code == 422
        with pytest.raises(HTTPException) as too_long:
            get_ticket_summary(conn, admin, from_date=date(2024, 12, 31), to_date=date(2026, 1, 1))
        assert too_long.value.status_code == 422
    finally:
        conn.close()
