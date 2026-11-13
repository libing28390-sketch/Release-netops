"""Transactional incident response tickets and assignment-group operations."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from core.rbac import enforce_resource_scope, resource_action_allowed
from core.tenant_policy import DEFAULT_TENANT_ID, TENANT_ISOLATION_ENABLED, tenant_id_for_write, tenant_scope_for_user
from fastapi import HTTPException
from services.rack_scope_service import RackScope, allowed_resource_scope, device_scope_predicate


TERMINAL_STATUSES = {"closed", "cancelled", "merged"}


def _priority_for_severity(severity: str) -> tuple[str, str]:
    normalized = str(severity or "").strip().lower()
    if normalized == "critical":
        return "P1", "high"
    if normalized == "major":
        return "P2", "high"
    if normalized == "warning":
        return "P3", "medium"
    return "P4", "low"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _actor(actor: dict[str, Any]) -> tuple[str, str]:
    return (
        str(actor.get("user_id") or actor.get("id") or "").strip(),
        str(actor.get("username") or "").strip(),
    )


def _row_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _source_scope(conn, source_incident_id: str, user: dict[str, Any], action: str) -> dict[str, Any]:
    """Load a source incident only when every affected device is in scope."""
    row = conn.execute(
        """
        SELECT i.id, i.status, i.title, i.summary, i.severity, i.primary_device_id,
               COALESCE(NULLIF(d.tenant_id, ''), ?) AS tenant_id,
               COALESCE(NULLIF(d.site_id, ''), NULLIF(d.site, ''), '') AS site_id,
               COALESCE(NULLIF(d.device_group_id, ''), '') AS device_group_id
          FROM monitoring_incidents i
          LEFT JOIN devices d ON d.id = i.primary_device_id
         WHERE i.id = ?
        """,
        (DEFAULT_TENANT_ID, source_incident_id),
    ).fetchone()
    if not row or not row["primary_device_id"]:
        raise HTTPException(status_code=404, detail="Incident not found")
    source = dict(row)
    tenant_id = str(source.get("tenant_id") or DEFAULT_TENANT_ID)
    site_id = str(source.get("site_id") or "")
    device_group_id = str(source.get("device_group_id") or "")
    try:
        enforce_resource_scope(
            user,
            "incident_ticket",
            action,
            tenant_id=tenant_id or None,
            site_id=site_id or None,
            device_group_id=device_group_id or None,
        )
    except HTTPException as exc:
        # Do not disclose whether an out-of-scope source incident exists.
        if exc.status_code in {403, 404}:
            raise HTTPException(status_code=404, detail="Incident not found") from exc
        raise

    scope = allowed_resource_scope(conn, user, "incident_ticket", action)
    asset_scope = allowed_resource_scope(conn, user, "asset", "view")
    scopes = (scope, asset_scope)
    primary_sql, primary_params = _device_scope_conditions(scopes, "source_primary")
    related_sql, related_params = _device_scope_conditions(scopes, "source_related")
    if any(item.site_ids == () and item.device_group_ids == () for item in scopes):
        raise HTTPException(status_code=404, detail="Incident not found")
    visible = conn.execute(
        f"""
        SELECT 1
          FROM monitoring_incidents i
          JOIN devices source_primary ON source_primary.id = i.primary_device_id
         WHERE i.id = ?{primary_sql}
           AND NOT EXISTS (
               SELECT 1
                 FROM monitoring_incident_alerts ia
                 JOIN alert_events a ON a.id = ia.alert_id
                WHERE ia.incident_id = i.id
                  AND (a.device_id IS NULL OR NOT EXISTS (
                      SELECT 1 FROM devices source_related
                       WHERE source_related.id = a.device_id{related_sql}
                  ))
           )
        """,
        (
            source_incident_id,
            *primary_params,
            *related_params,
        ),
    ).fetchone()
    if not visible:
        raise HTTPException(status_code=404, detail="Incident not found")
    return source


def _device_scope_conditions(scopes: tuple[RackScope, ...], alias: str) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    for scope in scopes:
        if scope.site_ids == () and scope.device_group_ids == ():
            clauses.append("1 = 0")
            continue
        predicate, values = device_scope_predicate(scope, device_alias=alias)
        if predicate:
            clauses.append(f"({predicate})")
            params.extend(values)
        if scope.tenant_id:
            clauses.append(f"COALESCE(NULLIF({alias}.tenant_id, ''), ?) = ?")
            params.extend((DEFAULT_TENANT_ID, scope.tenant_id))
    return (" AND " + " AND ".join(clauses) if clauses else "", tuple(params))


def _scope_filter_sql(scopes: tuple[RackScope, ...], *, incident_alias: str = "i") -> tuple[str, tuple[Any, ...]]:
    primary_sql, primary_params = _device_scope_conditions(scopes, "ticket_primary")
    related_sql, related_params = _device_scope_conditions(scopes, "ticket_related")
    if any(scope.site_ids == () and scope.device_group_ids == () for scope in scopes):
        return "1 = 0", ()
    return (
        f"""
        EXISTS (
            SELECT 1 FROM monitoring_incidents {incident_alias}
            JOIN devices ticket_primary ON ticket_primary.id = {incident_alias}.primary_device_id
            WHERE {incident_alias}.id = t.source_incident_id{primary_sql}
              AND NOT EXISTS (
                  SELECT 1
                    FROM monitoring_incident_alerts ticket_ia
                    JOIN alert_events ticket_alert ON ticket_alert.id = ticket_ia.alert_id
                   WHERE ticket_ia.incident_id = {incident_alias}.id
                     AND (ticket_alert.device_id IS NULL OR NOT EXISTS (
                         SELECT 1 FROM devices ticket_related
                          WHERE ticket_related.id = ticket_alert.device_id{related_sql}
                     ))
              )
        )
        """,
        (*primary_params, *related_params),
    )


def _ticket(conn, ticket_id: str, *, lock: bool = False) -> dict[str, Any]:
    suffix = " FOR UPDATE" if lock else ""
    row = conn.execute(f"SELECT * FROM incident_tickets WHERE id = ?{suffix}", (ticket_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Incident ticket not found")
    item = dict(row)
    item["assignment_group_id"] = item.get("assigned_group_id")
    item["incident_id"] = item.get("source_incident_id")
    item["requester_id"] = item.get("created_by_id")
    item["requester_username"] = item.get("created_by_username")
    assigned_group_id = str(item.get("assigned_group_id") or "")
    if assigned_group_id:
        group = conn.execute("SELECT name FROM ticket_assignment_groups WHERE id = ?", (assigned_group_id,)).fetchone()
        item["assigned_group_name"] = str(group["name"] or "") if group else ""
    item["current_owner_username"] = str(item.get("assignee_username") or item.get("assigned_group_name") or "")
    if item.get("priority"):
        item["priority_label"] = _priority_for_severity(str(item.get("severity") or "warning"))[1]
    return item


def _assert_ticket_access(conn, ticket: dict[str, Any], user: dict[str, Any], action: str) -> None:
    try:
        enforce_resource_scope(
            user,
            "incident_ticket",
            action,
            tenant_id=str(ticket.get("tenant_id") or "") or None,
            site_id=str(ticket.get("site_id") or "") or None,
            device_group_id=str(ticket.get("device_group_id") or "") or None,
        )
    except HTTPException as exc:
        if exc.status_code in {403, 404}:
            raise HTTPException(status_code=404, detail="Incident ticket not found") from exc
        raise
    _source_scope(conn, str(ticket["source_incident_id"]), user, action)


def _actor_has_ticket_action_scope(
    conn,
    ticket: dict[str, Any],
    user: dict[str, Any],
    action: str,
) -> bool:
    if not resource_action_allowed(user, "incident_ticket", action):
        return False
    try:
        _assert_ticket_access(conn, ticket, user, action)
    except HTTPException:
        return False
    return True


def _allowed_ticket_actions(conn, ticket: dict[str, Any], user: dict[str, Any]) -> list[str]:
    actor_id, _ = _actor(user)
    status = str(ticket.get("status") or "")
    owner = actor_id and actor_id == str(ticket.get("created_by_id") or "")
    assignee = actor_id and actor_id == str(ticket.get("assignee_id") or "")
    group_id = str(ticket.get("assigned_group_id") or "")
    is_group_member = bool(group_id and actor_id and _is_group_member(conn, group_id, actor_id))
    active_responder = False
    if assignee and status in {"open", "in_progress"}:
        try:
            member = _active_user(conn, actor_id, str(ticket.get("tenant_id") or DEFAULT_TENANT_ID))
            _assert_member_can_view_ticket(conn, member, ticket)
            active_responder = not group_id or is_group_member
        except HTTPException:
            active_responder = False

    rules = (
        ("assign", status not in TERMINAL_STATUSES),
        ("claim", status in {"open", "in_progress"} and (not ticket.get("assignee_id") or assignee) and (not group_id or is_group_member)),
        ("start", status == "open" and active_responder),
        ("request_confirmation", status == "in_progress" and active_responder),
        ("confirm_close", status == "pending_confirmation" and (owner or user.get("role_profile") == "System Administrator")),
        ("cancel", status not in TERMINAL_STATUSES and (owner or user.get("role") == "Administrator")),
        ("merge", status not in TERMINAL_STATUSES),
    )
    return [
        action
        for action, state_allowed in rules
        if state_allowed and _actor_has_ticket_action_scope(conn, ticket, user, action)
    ]


def _append_event(
    conn,
    ticket_id: str,
    event_type: str,
    actor: dict[str, Any],
    details: dict[str, Any] | None = None,
    *,
    source_status: str = "",
) -> None:
    actor_id, username = _actor(actor)
    conn.execute(
        """
        INSERT INTO incident_ticket_events
            (id, ticket_id, event_type, actor_id, actor_username, details_json, source_status, created_at)
        VALUES (?, ?, ?, ?, ?, ?::jsonb, ?, ?)
        """,
        (
            str(uuid.uuid4()), ticket_id, event_type, actor_id, username,
            json.dumps(details or {}, ensure_ascii=False), source_status, _now(),
        ),
    )


def _device_ids(conn, source_incident_id: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT a.device_id
          FROM monitoring_incident_alerts ia
          JOIN alert_events a ON a.id = ia.alert_id
         WHERE ia.incident_id = ? AND a.device_id IS NOT NULL
        UNION
        SELECT primary_device_id FROM monitoring_incidents
         WHERE id = ? AND primary_device_id IS NOT NULL
        """,
        (source_incident_id, source_incident_id),
    ).fetchall()
    return {str(row[0]) for row in rows if row[0]}


def validate_incident_target_devices(
    conn,
    *,
    incident_id: str,
    target_devices: list[Any] | None,
    user: dict[str, Any],
    action: str = "view",
) -> dict[str, Any]:
    """Validate that every selected change target belongs to a visible incident."""
    source = _source_scope(conn, incident_id, user, action)
    selected: set[str] = set()
    for value in target_devices or []:
        if isinstance(value, dict):
            device_id = value.get("id") or value.get("device_id")
        else:
            device_id = value
        if str(device_id or "").strip():
            selected.add(str(device_id).strip())
    allowed = _device_ids(conn, incident_id)
    if not selected or not selected.issubset(allowed):
        raise HTTPException(
            status_code=422,
            detail="Change order targets must be selected from devices affected by the linked incident",
        )
    return source


def create_ticket_from_incident(
    conn,
    incident_id: str,
    actor: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    source = _source_scope(conn, incident_id, actor, "create")
    # Serialize the idempotency check on the source projection row. The unique
    # source_incident_id constraint remains the final concurrency guard.
    locked = conn.execute(
        "SELECT id FROM monitoring_incidents WHERE id = ? FOR UPDATE",
        (incident_id,),
    ).fetchone()
    if not locked:
        raise HTTPException(status_code=404, detail="Incident not found")
    existing = conn.execute(
        "SELECT * FROM incident_tickets WHERE source_incident_id = ?",
        (incident_id,),
    ).fetchone()
    if existing:
        return _ticket(conn, str(existing["id"])), False
    ticket_id = str(uuid.uuid4())
    ticket_number = f"INC-{datetime.now(timezone.utc):%Y%m%d}-{ticket_id.replace('-', '').upper()[:8]}"
    actor_id, username = _actor(actor)
    now = _now()
    priority, _priority_label = _priority_for_severity(str(source.get("severity") or "warning"))
    conn.execute(
        """
        INSERT INTO incident_tickets (
            id, ticket_number, source_incident_id, tenant_id, title, description, severity, priority, status,
            primary_device_id, site_id, device_group_id, created_by_id,
            created_by_username, source_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticket_id,
            ticket_number,
            incident_id,
            tenant_id_for_write(requested=source.get("tenant_id"), user=actor),
            str(source.get("title") or "Incident response"),
            str(source.get("summary") or ""),
            str(source.get("severity") or "warning"),
            priority,
            source.get("primary_device_id"),
            str(source.get("site_id") or ""),
            str(source.get("device_group_id") or ""),
            actor_id,
            username,
            str(source.get("status") or "open"),
            now,
            now,
        ),
    )
    _append_event(
        conn,
        ticket_id,
        "ticket_opened",
        actor,
        {"source_incident_id": incident_id, "source_status": source.get("status") or "open"},
        source_status=str(source.get("status") or "open"),
    )
    from services.service_request_service import initialize_sla_clocks

    initialize_sla_clocks(
        conn,
        source_type="incident",
        source_id=ticket_id,
        tenant_id=tenant_id_for_write(requested=source.get("tenant_id"), user=actor),
        priority=priority,
        actor=actor,
    )
    return _ticket(conn, ticket_id), True


def list_tickets(
    conn,
    user: dict[str, Any],
    *,
    page: int = 1,
    page_size: int = 10,
    status: str = "",
    search: str = "",
    my_todo: bool = False,
) -> dict[str, Any]:
    scope = allowed_resource_scope(conn, user, "incident_ticket", "view")
    asset_scope = allowed_resource_scope(conn, user, "asset", "view")
    scopes = (scope, asset_scope)
    if any(item.site_ids == () and item.device_group_ids == () for item in scopes):
        raise HTTPException(status_code=403, detail="Insufficient permission for incident tickets")
    clauses: list[str] = []
    params: list[Any] = []
    if TENANT_ISOLATION_ENABLED and scope.tenant_id:
        clauses.append("t.tenant_id = ?")
        params.append(scope.tenant_id)
    if status:
        if status == "active":
            clauses.append("t.status NOT IN ('closed', 'cancelled', 'merged')")
        else:
            clauses.append("t.status = ?")
            params.append(status)
    if search:
        clauses.append(
            "(t.title ILIKE ? OR t.description ILIKE ? OR t.id ILIKE ? OR t.ticket_number ILIKE ? "
            "OR EXISTS (SELECT 1 FROM monitoring_incidents search_primary_incident "
            "JOIN devices search_primary_device ON search_primary_device.id = search_primary_incident.primary_device_id "
            "WHERE search_primary_incident.id = t.source_incident_id "
            "AND (search_primary_device.hostname ILIKE ? OR search_primary_device.ip_address ILIKE ?)) "
            "OR EXISTS (SELECT 1 FROM monitoring_incidents search_incident "
            "JOIN monitoring_incident_alerts search_ia ON search_ia.incident_id = search_incident.id "
            "JOIN alert_events search_alert ON search_alert.id = search_ia.alert_id "
            "JOIN devices search_device ON search_device.id = search_alert.device_id "
            "WHERE search_incident.id = t.source_incident_id "
            "AND (search_device.hostname ILIKE ? OR search_device.ip_address ILIKE ?)))"
        )
        pattern = f"%{search.strip()}%"
        params.extend((pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern))
    if my_todo:
        user_id, _username = _actor(user)
        clauses.append(
            "t.status NOT IN ('closed', 'cancelled', 'merged') AND ("
            "(t.assignee_id = ? AND t.status IN ('open', 'in_progress')) "
            "OR (t.created_by_id = ? AND t.status = 'pending_confirmation') "
            "OR (t.assignee_id IS NULL AND t.status = 'open' AND EXISTS ("
            "SELECT 1 FROM ticket_assignment_group_members gm "
            "WHERE gm.group_id = t.assigned_group_id AND gm.user_id = ?)))"
        )
        params.extend((user_id, user_id, user_id))
    scope_sql, scope_params = _scope_filter_sql(scopes)
    clauses.append(scope_sql)
    params.extend(scope_params)
    where = "WHERE " + " AND ".join(clauses)
    total = int(conn.execute(f"SELECT COUNT(*) AS c FROM incident_tickets t {where}", tuple(params)).fetchone()["c"])
    rows = conn.execute(
        f"""
        SELECT t.*, g.name AS assigned_group_name
          FROM incident_tickets t
          LEFT JOIN ticket_assignment_groups g ON g.id = t.assigned_group_id
          {where}
         ORDER BY CASE t.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 WHEN 'pending_confirmation' THEN 2 ELSE 3 END,
                  t.updated_at DESC, t.id
         LIMIT ? OFFSET ?
        """,
        tuple([*params, page_size, max(0, page - 1) * page_size]),
    ).fetchall()
    items = [dict(row) for row in rows]
    for item in items:
        item["assignment_group_id"] = item.get("assigned_group_id")
        item["incident_id"] = item.get("source_incident_id")
        item["requester_id"] = item.get("created_by_id")
        item["requester_username"] = item.get("created_by_username")
        item["priority_label"] = _priority_for_severity(str(item.get("severity") or "warning"))[1]
        item["current_owner_username"] = str(item.get("assignee_username") or item.get("assigned_group_name") or "")
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def get_ticket_detail(conn, ticket_id: str, user: dict[str, Any]) -> dict[str, Any]:
    ticket = _ticket(conn, ticket_id)
    _assert_ticket_access(conn, ticket, user, "view")
    event_rows = conn.execute(
        "SELECT * FROM incident_ticket_events WHERE ticket_id = ? ORDER BY created_at, id",
        (ticket_id,),
    ).fetchall()
    events = []
    for row in event_rows:
        item = dict(row)
        item["details"] = _json_object(item.pop("details_json", {}))
        events.append(item)
    latest_recovery_event = next(
        (event for event in reversed(events) if event.get("event_type") == "request_confirmation"),
        None,
    )
    latest_recovery = None
    if latest_recovery_event:
        recovery_details = latest_recovery_event.get("details") or {}
        latest_recovery = {
            "summary": recovery_details.get("summary") or "",
            "evidence": recovery_details.get("evidence"),
            "requested_at": latest_recovery_event.get("created_at"),
            "requested_by": {
                "id": latest_recovery_event.get("actor_id") or "",
                "username": latest_recovery_event.get("actor_username") or "",
            },
        }
    linked = []
    # Linked change orders are independently filtered by their exact object
    # scope. Never let a ticket detail disclose a hidden change-order summary.
    from services.change_order_service import get_change_order
    for link in conn.execute(
        "SELECT change_order_id FROM incident_ticket_links WHERE ticket_id = ? ORDER BY created_at, id",
        (ticket_id,),
    ).fetchall():
        order = get_change_order(conn, str(link["change_order_id"]))
        if not order:
            continue
        if TENANT_ISOLATION_ENABLED and tenant_scope_for_user(user) != str(order.get("tenant_id") or ""):
            continue
        try:
            enforce_resource_scope(
                user,
                "change_order",
                "view",
                tenant_id=str(order.get("tenant_id") or "") or None,
            )
        except HTTPException:
            continue
        try:
            from api.change_orders.core import _require_change_order_access

            _require_change_order_access(order, user, "view")
        except HTTPException:
            continue
        targets = order.get("target_devices") if isinstance(order.get("target_devices"), list) else []
        hidden_target = False
        for target in targets:
            target_id = str((target.get("id") or target.get("device_id")) if isinstance(target, dict) else target or "").strip()
            if not target_id:
                hidden_target = True
                break
            device = conn.execute(
                """
                SELECT COALESCE(NULLIF(tenant_id, ''), ?) AS tenant_id,
                       COALESCE(NULLIF(site_id, ''), NULLIF(site, ''), '') AS site_id,
                       COALESCE(NULLIF(device_group_id, ''), '') AS device_group_id
                  FROM devices WHERE id = ?
                """,
                (DEFAULT_TENANT_ID, target_id),
            ).fetchone()
            if not device:
                hidden_target = True
                break
            try:
                enforce_resource_scope(
                    user,
                    "change_order",
                    "view",
                    tenant_id=str(device["tenant_id"] or "") or None,
                    site_id=str(device["site_id"] or "") or None,
                    device_group_id=str(device["device_group_id"] or "") or None,
                )
                enforce_resource_scope(
                    user,
                    "asset",
                    "view",
                    tenant_id=str(device["tenant_id"] or "") or None,
                    site_id=str(device["site_id"] or "") or None,
                    device_group_id=str(device["device_group_id"] or "") or None,
                )
            except HTTPException:
                hidden_target = True
                break
        if hidden_target:
            continue
        linked.append({key: order.get(key) for key in ("id", "order_number", "title", "status", "priority", "incident_id", "created_at")})
    ticket["assignment_group_id"] = ticket.get("assigned_group_id")
    ticket["priority_label"] = _priority_for_severity(str(ticket.get("severity") or "warning"))[1]
    ticket["incident_id"] = ticket.get("source_incident_id")
    ticket["requester_id"] = ticket.get("created_by_id")
    ticket["requester_username"] = ticket.get("created_by_username")
    ticket["current_owner_username"] = str(ticket.get("assignee_username") or ticket.get("assigned_group_name") or "")
    if latest_recovery:
        ticket["recovery_summary"] = latest_recovery["summary"]
        ticket["recovery_evidence"] = latest_recovery["evidence"]
        ticket["evidence"] = latest_recovery["evidence"]
        ticket["recovery_requested_at"] = latest_recovery["requested_at"]
    ticket["allowed_actions"] = _allowed_ticket_actions(conn, ticket, user)
    from services.service_request_service import get_incident_sla_detail

    ticket["sla"] = get_incident_sla_detail(conn, ticket_id)
    return {
        "ticket": ticket,
        "events": events,
        "linked_change_orders": linked,
        "latest_recovery": latest_recovery,
    }


def _active_user(conn, user_id: str, tenant_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, username, role, role_profile, status, tenant_id, scope_mode FROM users WHERE id = ? FOR SHARE",
        (user_id,),
    ).fetchone()
    if not row or str(row["status"] or "").strip().lower() != "active":
        raise HTTPException(status_code=422, detail="Assignee must be an active user")
    result = dict(row)
    raw_member_tenant = str(result.get("tenant_id") or "").strip()
    if TENANT_ISOLATION_ENABLED and not raw_member_tenant:
        raise HTTPException(status_code=422, detail="Assignee must have a tenant assignment")
    member_tenant = raw_member_tenant or DEFAULT_TENANT_ID
    if member_tenant != tenant_id:
        raise HTTPException(status_code=422, detail="Assignee must belong to the ticket tenant")
    return result


def _assert_member_can_view_ticket(conn, member: dict[str, Any], ticket: dict[str, Any]) -> None:
    user = {
        "id": str(member.get("id") or ""),
        "user_id": str(member.get("id") or ""),
        "username": str(member.get("username") or ""),
        "role": str(member.get("role") or ""),
        "role_profile": str(member.get("role_profile") or ""),
        "tenant_id": str(member.get("tenant_id") or ""),
        "scope_mode": str(member.get("scope_mode") or "legacy"),
    }
    try:
        _assert_ticket_access(conn, ticket, user, "view")
    except HTTPException as exc:
        raise HTTPException(
            status_code=422,
            detail="Every assigned group member must be able to view the ticket device scope",
        ) from exc


def _validate_group_ticket_members(conn, group_id: str, ticket: dict[str, Any]) -> None:
    rows = conn.execute(
        """
        SELECT u.id, u.username, u.role, u.role_profile, u.status, u.tenant_id, u.scope_mode
          FROM ticket_assignment_group_members gm
          JOIN users u ON u.id = gm.user_id
         WHERE gm.group_id = ?
        """,
        (group_id,),
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=422, detail="Assignment group must have an active member")
    for row in rows:
        member = dict(row)
        if str(member.get("status") or "").strip().lower() != "active":
            raise HTTPException(status_code=422, detail="Every assigned group member must be active")
        _assert_member_can_view_ticket(conn, member, ticket)


def _validate_group_existing_ticket_visibility(conn, group_id: str, member: dict[str, Any]) -> None:
    rows = conn.execute(
        "SELECT * FROM incident_tickets WHERE assigned_group_id = ? AND status NOT IN ('closed', 'cancelled', 'merged')",
        (group_id,),
    ).fetchall()
    for row in rows:
        _assert_member_can_view_ticket(conn, member, dict(row))


def _group(conn, group_id: str, tenant_id: str, *, lock: bool = False) -> dict[str, Any]:
    suffix = " FOR UPDATE" if lock else ""
    row = conn.execute(f"SELECT * FROM ticket_assignment_groups WHERE id = ?{suffix}", (group_id,)).fetchone()
    if not row or str(row["tenant_id"] or "") != tenant_id:
        raise HTTPException(status_code=422, detail="Assignment group is unavailable for this ticket")
    return dict(row)


def _is_group_member(conn, group_id: str, user_id: str) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM ticket_assignment_group_members gm
        JOIN users u ON u.id = gm.user_id
        WHERE gm.group_id = ? AND gm.user_id = ? AND lower(u.status) = 'active'
        """,
        (group_id, user_id),
    ).fetchone()
    return bool(row)


def perform_ticket_action(
    conn,
    ticket_id: str,
    actor: dict[str, Any],
    *,
    action: str,
    assignment_group_id: str = "",
    assignee_id: str = "",
    target_ticket_id: str = "",
    reason: str = "",
    summary: str = "",
    evidence: Any = None,
) -> dict[str, Any]:
    action_value = str(action or "").strip().lower()
    if action_value not in {"assign", "claim", "start", "request_confirmation", "confirm_close", "cancel", "merge"}:
        raise HTTPException(status_code=422, detail="Unsupported ticket action")
    if action_value == "merge" and target_ticket_id and target_ticket_id != ticket_id:
        rows = conn.execute(
            "SELECT * FROM incident_tickets WHERE id IN (?, ?) ORDER BY id FOR UPDATE",
            (ticket_id, target_ticket_id),
        ).fetchall()
        by_id = {str(row["id"]): dict(row) for row in rows}
        ticket = by_id.get(ticket_id)
    else:
        ticket = None
    if not ticket:
        ticket = _ticket(conn, ticket_id, lock=True)
    _assert_ticket_access(conn, ticket, actor, action_value)
    actor_id, actor_username = _actor(actor)
    tenant_id = str(ticket.get("tenant_id") or DEFAULT_TENANT_ID)
    status = str(ticket.get("status") or "")
    now = _now()
    details: dict[str, Any] = {"reason": str(reason or "").strip()}
    update: dict[str, Any] = {"updated_at": now}

    if action_value == "assign":
        if status in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail="A terminal ticket cannot be assigned")
        group = _group(conn, assignment_group_id, tenant_id, lock=True) if assignment_group_id else None
        assignee = _active_user(conn, assignee_id, tenant_id) if assignee_id else None
        if not group and not assignee:
            raise HTTPException(status_code=422, detail="Specify an assignment group or an assignee")
        if group and assignee and not _is_group_member(conn, str(group["id"]), str(assignee["id"])):
            raise HTTPException(status_code=422, detail="Assignee must be a member of the selected group")
        if group:
            _validate_group_ticket_members(conn, str(group["id"]), ticket)
        if assignee:
            _assert_member_can_view_ticket(conn, assignee, ticket)
        update.update({
            "assigned_group_id": str(group["id"]) if group else None,
            "assignee_id": str(assignee["id"]) if assignee else None,
            "assignee_username": str(assignee["username"]) if assignee else "",
        })
        details.update({"assignment_group_id": update["assigned_group_id"], "assignee_id": update["assignee_id"], "assignee_username": update["assignee_username"]})
    elif action_value == "claim":
        if status in TERMINAL_STATUSES or status == "pending_confirmation":
            raise HTTPException(status_code=409, detail="Ticket is not available to claim")
        assignee = _active_user(conn, actor_id, tenant_id)
        _assert_member_can_view_ticket(conn, assignee, ticket)
        current_assignee = str(ticket.get("assignee_id") or "")
        if current_assignee and current_assignee != actor_id:
            raise HTTPException(status_code=409, detail="Ticket is already claimed by another user")
        assigned_group = str(ticket.get("assigned_group_id") or "")
        if assigned_group and not _is_group_member(conn, assigned_group, actor_id):
            raise HTTPException(status_code=403, detail="Only a member of the assigned group can claim this ticket")
        update.update({"assignee_id": actor_id, "assignee_username": str(assignee["username"])})
        details.update({"assignee_id": actor_id, "assignee_username": str(assignee["username"])})
    elif action_value == "start":
        if status != "open":
            raise HTTPException(status_code=409, detail="Only open tickets can be started")
        if str(ticket.get("assignee_id") or "") != actor_id:
            raise HTTPException(status_code=403, detail="Claim the ticket before starting work")
        assignee = _active_user(conn, actor_id, tenant_id)
        _assert_member_can_view_ticket(conn, assignee, ticket)
        assigned_group = str(ticket.get("assigned_group_id") or "")
        if assigned_group and not _is_group_member(conn, assigned_group, actor_id):
            raise HTTPException(status_code=403, detail="Only an active member of the assigned group can start work")
        update["status"] = "in_progress"
    elif action_value == "request_confirmation":
        if status != "in_progress":
            raise HTTPException(status_code=409, detail="Only in-progress tickets can request confirmation")
        if str(ticket.get("assignee_id") or "") != actor_id:
            raise HTTPException(status_code=403, detail="Only the assigned responder can request confirmation")
        assignee = _active_user(conn, actor_id, tenant_id)
        _assert_member_can_view_ticket(conn, assignee, ticket)
        assigned_group = str(ticket.get("assigned_group_id") or "")
        if assigned_group and not _is_group_member(conn, assigned_group, actor_id):
            raise HTTPException(status_code=403, detail="Only an active member of the assigned group can request confirmation")
        if not str(summary or "").strip():
            raise HTTPException(status_code=422, detail="Recovery summary is required")
        if not evidence:
            raise HTTPException(status_code=422, detail="Recovery evidence is required")
        if not isinstance(evidence, (dict, list, str)) or (isinstance(evidence, str) and not evidence.strip()):
            raise HTTPException(status_code=422, detail="Recovery evidence must be a non-empty object, list, or reference")
        try:
            json.dumps(evidence, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Recovery evidence must be JSON serializable")
        update["status"] = "pending_confirmation"
        details.update({"summary": str(summary).strip(), "evidence": evidence})
    elif action_value == "confirm_close":
        if status != "pending_confirmation":
            raise HTTPException(status_code=409, detail="Ticket is not awaiting confirmation")
        if str(ticket.get("created_by_id") or "") != actor_id and actor.get("role_profile") != "System Administrator":
            raise HTTPException(status_code=403, detail="Only the ticket requester can confirm closure")
        update.update({"status": "closed", "closed_at": now})
        details["summary"] = str(summary or "").strip()
    elif action_value == "cancel":
        if status in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail="Ticket is already terminal")
        if str(ticket.get("created_by_id") or "") != actor_id and actor.get("role") != "Administrator":
            raise HTTPException(status_code=403, detail="Only the ticket requester or an administrator can cancel")
        update.update({"status": "cancelled", "closed_at": now})
    elif action_value == "merge":
        if status in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail="A terminal ticket cannot be merged")
        if not target_ticket_id or target_ticket_id == ticket_id:
            raise HTTPException(status_code=422, detail="A different target ticket is required")
        target = by_id.get(target_ticket_id) if "by_id" in locals() else None
        if target is None:
            target = _ticket(conn, target_ticket_id)
        _assert_ticket_access(conn, target, actor, "view")
        if str(target.get("tenant_id") or "") != tenant_id or str(target.get("status") or "") in {"cancelled", "merged"}:
            raise HTTPException(status_code=422, detail="Target ticket is not available for merge")
        update.update({"status": "merged", "merged_into_id": target_ticket_id, "closed_at": now})
        details["target_ticket_id"] = target_ticket_id

    update_fields = ", ".join(f"{field} = ?" for field in update)
    conn.execute(
        f"UPDATE incident_tickets SET {update_fields} WHERE id = ?",
        (*update.values(), ticket_id),
    )
    _append_event(conn, ticket_id, action_value, actor, details)
    from services.service_request_service import apply_incident_sla_event

    apply_incident_sla_event(conn, ticket_id, action_value, actor)
    return _ticket(conn, ticket_id)


def sync_source_incident_status(conn, incident_id: str, status: str) -> None:
    """Append source projection facts and return pending tickets on recurrence."""
    current_status = str(status or "").strip().lower()
    rows = conn.execute(
        "SELECT * FROM incident_tickets WHERE source_incident_id = ? FOR UPDATE",
        (incident_id,),
    ).fetchall()
    system_actor = {"user_id": "", "username": "monitoring-projection"}
    for row in rows:
        ticket = dict(row)
        previous = str(ticket.get("source_status") or "").strip().lower()
        if not current_status or previous == current_status:
            continue
        if previous == "resolved" and current_status == "open" and ticket.get("status") == "pending_confirmation":
            conn.execute(
                "UPDATE incident_tickets SET status = 'in_progress', source_status = ?, updated_at = ? WHERE id = ?",
                (current_status, _now(), ticket["id"]),
            )
            _append_event(
                conn,
                str(ticket["id"]),
                "source_reopened_returned_to_progress",
                system_actor,
                {"from_source_status": previous, "to_source_status": current_status, "from_ticket_status": "pending_confirmation", "to_ticket_status": "in_progress"},
                source_status=current_status,
            )
            from services.service_request_service import enqueue_incident_ticket_notification

            enqueue_incident_ticket_notification(
                conn,
                str(ticket["id"]),
                event_key=f"incident_ticket:{ticket['id']}:recurrence:{uuid.uuid4()}",
                title="监控告警复发",
                message=str(ticket.get("title") or ticket.get("ticket_number") or "故障已复发"),
                recipients=[str(ticket.get("created_by_id") or "")] if ticket.get("created_by_id") else [],
            )
        else:
            conn.execute(
                "UPDATE incident_tickets SET source_status = ?, updated_at = ? WHERE id = ?",
                (current_status, _now(), ticket["id"]),
            )
            _append_event(
                conn,
                str(ticket["id"]),
                "source_status_changed",
                system_actor,
                {"from_source_status": previous, "to_source_status": current_status},
                source_status=current_status,
            )


def create_assignment_group(conn, actor: dict[str, Any], name: str, description: str = "") -> dict[str, Any]:
    _assert_group_admin(actor)
    if not str(name or "").strip():
        raise HTTPException(status_code=422, detail="Group name is required")
    if TENANT_ISOLATION_ENABLED and not tenant_scope_for_user(actor) and actor.get("role_profile") != "System Administrator":
        raise HTTPException(status_code=403, detail="Administrator must have a tenant assignment")
    group_id = str(uuid.uuid4())
    actor_id, username = _actor(actor)
    tenant_id = tenant_id_for_write(user=actor)
    conn.execute(
        """
        INSERT INTO ticket_assignment_groups
            (id, tenant_id, name, description, created_by_id, created_by_username, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (group_id, tenant_id, name.strip(), description.strip(), actor_id, username, _now(), _now()),
    )
    return get_assignment_group(conn, group_id, actor)


def _assert_group_admin(actor: dict[str, Any]) -> None:
    if not resource_action_allowed(actor, "incident_ticket", "manage_groups"):
        raise HTTPException(status_code=403, detail="Only administrators can manage assignment groups")


def _group_visible(conn, group: dict[str, Any], actor: dict[str, Any], *, manage: bool = False) -> None:
    _assert_group_admin(actor) if manage else None
    tenant = str(group.get("tenant_id") or "")
    if TENANT_ISOLATION_ENABLED:
        actor_tenant = tenant_scope_for_user(actor)
        if actor.get("role_profile") != "System Administrator" and tenant != actor_tenant:
            raise HTTPException(status_code=404, detail="Assignment group not found")


def list_assignment_groups(conn, actor: dict[str, Any]) -> list[dict[str, Any]]:
    if not resource_action_allowed(actor, "incident_ticket", "assign"):
        raise HTTPException(status_code=403, detail="Insufficient permission to view assignment groups")
    tenant = tenant_id_for_write(user=actor)
    if actor.get("role_profile") == "System Administrator":
        rows = conn.execute(
            """
            SELECT group_row.*, COUNT(DISTINCT member.user_id) FILTER (WHERE lower(COALESCE(user_row.status, 'active')) = 'active')::int AS member_count
              FROM ticket_assignment_groups group_row
              LEFT JOIN ticket_assignment_group_members member ON member.group_id = group_row.id
              LEFT JOIN users user_row ON user_row.id = member.user_id
             GROUP BY group_row.id
             ORDER BY group_row.tenant_id, group_row.name, group_row.id
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT group_row.*, COUNT(DISTINCT member.user_id) FILTER (WHERE lower(COALESCE(user_row.status, 'active')) = 'active')::int AS member_count
              FROM ticket_assignment_groups group_row
              LEFT JOIN ticket_assignment_group_members member ON member.group_id = group_row.id
              LEFT JOIN users user_row ON user_row.id = member.user_id
             WHERE group_row.tenant_id = ?
             GROUP BY group_row.id
             ORDER BY group_row.name, group_row.id
            """,
            (tenant,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_assignment_group(conn, group_id: str, actor: dict[str, Any], *, manage: bool = False) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM ticket_assignment_groups WHERE id = ?", (group_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Assignment group not found")
    group = dict(row)
    _group_visible(conn, group, actor, manage=manage)
    return group


def update_assignment_group(conn, group_id: str, actor: dict[str, Any], *, name: str | None = None, description: str | None = None) -> dict[str, Any]:
    group = get_assignment_group(conn, group_id, actor, manage=True)
    fields: list[str] = []
    values: list[Any] = []
    if name is not None:
        if not name.strip():
            raise HTTPException(status_code=422, detail="Group name is required")
        fields.append("name = ?")
        values.append(name.strip())
    if description is not None:
        fields.append("description = ?")
        values.append(description.strip())
    if fields:
        fields.append("updated_at = ?")
        values.extend((_now(), group_id))
        conn.execute(f"UPDATE ticket_assignment_groups SET {', '.join(fields)} WHERE id = ?", tuple(values))
    return get_assignment_group(conn, group_id, actor, manage=True)


def delete_assignment_group(conn, group_id: str, actor: dict[str, Any]) -> None:
    get_assignment_group(conn, group_id, actor, manage=True)
    if conn.execute(
        "SELECT 1 FROM service_catalog_versions WHERE assignment_group_id = ? OR approval_group_id = ? LIMIT 1",
        (group_id, group_id),
    ).fetchone():
        raise HTTPException(status_code=409, detail="Remove this group from published service catalog versions before deleting it")
    if conn.execute(
        "SELECT 1 FROM service_requests WHERE assignment_group_id = ? OR approval_group_id = ? LIMIT 1",
        (group_id, group_id),
    ).fetchone():
        raise HTTPException(status_code=409, detail="Reassign or preserve service request history before deleting this group")
    used = conn.execute(
        """
        SELECT 1 FROM incident_tickets
         WHERE assigned_group_id = ?
           AND status NOT IN ('closed', 'cancelled', 'merged')
         LIMIT 1
        """,
        (group_id,),
    ).fetchone()
    if used:
        raise HTTPException(status_code=409, detail="Reassign active incident tickets before deleting this group")
    conn.execute("DELETE FROM ticket_assignment_groups WHERE id = ?", (group_id,))


def list_assignment_group_members(
    conn,
    group_id: str,
    actor: dict[str, Any],
    *,
    ticket_id: str | None = None,
) -> list[dict[str, Any]]:
    normalized_ticket_id = str(ticket_id or "").strip()
    if not normalized_ticket_id:
        group = get_assignment_group(conn, group_id, actor, manage=True)
        rows = conn.execute(
            """
            SELECT gm.id, gm.group_id, gm.user_id, gm.username, gm.added_by_id,
                   gm.added_by_username, gm.created_at, u.status, u.tenant_id,
                   u.role, u.role_profile
              FROM ticket_assignment_group_members gm JOIN users u ON u.id = gm.user_id
             WHERE gm.group_id = ? ORDER BY gm.username, gm.user_id
            """,
            (group_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    group = get_assignment_group(conn, group_id, actor)
    action = "assign"
    if not resource_action_allowed(actor, "incident_ticket", action):
        raise HTTPException(status_code=403, detail="Only actors with assignment permission can view eligible members")
    ticket = None
    if normalized_ticket_id:
        ticket = _ticket(conn, normalized_ticket_id)
        _assert_ticket_access(conn, ticket, actor, action)
        if str(ticket.get("tenant_id") or "") != str(group.get("tenant_id") or ""):
            raise HTTPException(status_code=404, detail="Assignment group not found")
    rows = conn.execute(
        """
        SELECT gm.id, gm.group_id, gm.user_id, gm.username, gm.added_by_id,
               gm.added_by_username, gm.created_at, u.status, u.tenant_id,
               u.role, u.role_profile, u.scope_mode
          FROM ticket_assignment_group_members gm JOIN users u ON u.id = gm.user_id
         WHERE gm.group_id = ? ORDER BY gm.username, gm.user_id
        """,
        (group_id,),
    ).fetchall()
    eligible: list[dict[str, Any]] = []
    for row in rows:
        member = dict(row)
        if str(member.get("status") or "").strip().lower() != "active":
            continue
        if str(member.get("tenant_id") or DEFAULT_TENANT_ID) != str(group.get("tenant_id") or ""):
            continue
        if ticket is not None:
            try:
                _assert_member_can_view_ticket(conn, member, ticket)
            except HTTPException:
                continue
        eligible.append({
            "id": str(member.get("user_id") or ""),
            "username": str(member.get("username") or ""),
            "role": str(member.get("role") or ""),
            "role_profile": str(member.get("role_profile") or ""),
        })
    return eligible


def add_assignment_group_member(conn, group_id: str, actor: dict[str, Any], user_id: str) -> dict[str, Any]:
    group = get_assignment_group(conn, group_id, actor, manage=True)
    conn.execute("SELECT id FROM ticket_assignment_groups WHERE id = ? FOR UPDATE", (group_id,))
    member = _active_user(conn, user_id, str(group["tenant_id"]))
    _validate_group_existing_ticket_visibility(conn, group_id, member)
    actor_id, actor_username = _actor(actor)
    conn.execute(
        """
        INSERT INTO ticket_assignment_group_members
            (id, group_id, user_id, username, added_by_id, added_by_username, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(group_id, user_id) DO NOTHING
        """,
        (str(uuid.uuid4()), group_id, user_id, member["username"], actor_id, actor_username, _now()),
    )
    row = conn.execute(
        "SELECT * FROM ticket_assignment_group_members WHERE group_id = ? AND user_id = ?",
        (group_id, user_id),
    ).fetchone()
    return dict(row)


def remove_assignment_group_member(conn, group_id: str, actor: dict[str, Any], user_id: str) -> None:
    get_assignment_group(conn, group_id, actor, manage=True)
    conn.execute("SELECT id FROM ticket_assignment_groups WHERE id = ? FOR UPDATE", (group_id,))
    assigned_active = conn.execute(
        """
        SELECT id FROM incident_tickets
         WHERE assigned_group_id = ? AND assignee_id = ?
           AND status NOT IN ('closed', 'cancelled', 'merged')
         LIMIT 1
        """,
        (group_id, user_id),
    ).fetchone()
    if assigned_active:
        raise HTTPException(
            status_code=409,
            detail="Reassign or clear the user's active tickets before removing this group member",
        )
    assigned_service_request = conn.execute(
        """
        SELECT id FROM service_requests
         WHERE (assignment_group_id = ? AND assignee_id = ? AND status IN ('accepted', 'in_progress', 'waiting_external', 'pending_confirmation'))
            OR (approval_group_id = ? AND status = 'pending_approval')
         LIMIT 1
        """,
        (group_id, user_id, group_id),
    ).fetchone()
    if assigned_service_request:
        raise HTTPException(
            status_code=409,
            detail="Reassign active service requests before removing this group member",
        )
    conn.execute(
        "DELETE FROM ticket_assignment_group_members WHERE group_id = ? AND user_id = ?",
        (group_id, user_id),
    )


def link_change_order(
    conn,
    *,
    ticket_id: str,
    change_order_id: str,
    incident_id: str,
    target_devices: list[Any],
    actor: dict[str, Any],
) -> None:
    ticket_row = conn.execute(
        "SELECT * FROM incident_tickets WHERE id = ? FOR UPDATE",
        (ticket_id,),
    ).fetchone()
    if not ticket_row:
        raise HTTPException(status_code=404, detail="Incident ticket not found")
    ticket = dict(ticket_row)
    if str(ticket.get("source_incident_id") or "") != str(incident_id or ""):
        raise HTTPException(status_code=422, detail="incident_ticket_id must match incident_id")
    validate_incident_target_devices(
        conn,
        incident_id=incident_id,
        target_devices=target_devices,
        user=actor,
        action="link_change_order",
    )
    order = conn.execute(
        "SELECT tenant_id, incident_id, target_devices_json FROM change_orders WHERE id = ? FOR UPDATE",
        (change_order_id,),
    ).fetchone()
    if not order or str(order["tenant_id"] or "") != str(ticket.get("tenant_id") or ""):
        raise HTTPException(status_code=422, detail="Change order and incident ticket must share a tenant")
    if str(order["incident_id"] or "") != str(incident_id or ""):
        raise HTTPException(status_code=422, detail="Change order incident_id must match its incident ticket")
    try:
        stored_targets = json.loads(str(order["target_devices_json"] or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        stored_targets = []
    if not isinstance(stored_targets, list):
        stored_targets = []
    validate_incident_target_devices(
        conn,
        incident_id=incident_id,
        target_devices=stored_targets,
        user=actor,
        action="link_change_order",
    )
    actor_id, username = _actor(actor)
    now = _now()
    inserted = conn.execute(
        """
        INSERT INTO incident_ticket_links
            (id, ticket_id, change_order_id, linked_by_id, linked_by_username, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticket_id, change_order_id) DO NOTHING
        RETURNING id
        """,
        (str(uuid.uuid4()), ticket_id, change_order_id, actor_id, username, now),
    ).fetchone()
    if inserted:
        _append_event(
            conn,
            ticket_id,
            "change_order_linked",
            actor,
            {"change_order_id": change_order_id, "incident_id": incident_id},
        )


def validate_ticket_link_context(
    conn,
    *,
    ticket_id: str,
    incident_id: str,
    target_devices: list[Any],
    user: dict[str, Any],
) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM incident_tickets WHERE id = ? FOR UPDATE", (ticket_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Incident ticket not found")
    ticket = dict(row)
    if str(ticket.get("source_incident_id") or "") != str(incident_id or ""):
        raise HTTPException(status_code=422, detail="incident_ticket_id must match incident_id")
    validate_incident_target_devices(
        conn,
        incident_id=incident_id,
        target_devices=target_devices,
        user=user,
        action="link_change_order",
    )
    return ticket


__all__ = [
    "add_assignment_group_member",
    "create_assignment_group",
    "create_ticket_from_incident",
    "delete_assignment_group",
    "get_assignment_group",
    "get_ticket_detail",
    "link_change_order",
    "list_assignment_group_members",
    "list_assignment_groups",
    "list_tickets",
    "perform_ticket_action",
    "remove_assignment_group_member",
    "sync_source_incident_status",
    "update_assignment_group",
    "validate_incident_target_devices",
    "validate_ticket_link_context",
]
