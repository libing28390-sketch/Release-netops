"""PostgreSQL-backed service requests, versioned SLA clocks, and ticket lists."""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from core.rbac import enforce_resource_scope, resource_action_allowed
from core.tenant_policy import DEFAULT_TENANT_ID, TENANT_ISOLATION_ENABLED, tenant_id_for_write, tenant_scope_for_user
from services.incident_ticket_service import _scope_filter_sql, _actor as _incident_actor
from services.rack_scope_service import allowed_resource_scope


_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_REQUEST_STATUSES = {
    "submitted", "pending_approval", "accepted", "in_progress", "waiting_external",
    "pending_confirmation", "completed", "rejected", "cancelled",
}
_ACTIVE_REQUEST_STATUSES = {"accepted", "in_progress", "waiting_external", "pending_confirmation"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _json_value(value: Any, fallback: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return fallback
    return value if value is not None else fallback


def _actor(user: dict[str, Any]) -> tuple[str, str]:
    return _incident_actor(user)


def _tenant(user: dict[str, Any]) -> str:
    return str(tenant_scope_for_user(user) or user.get("tenant_id") or DEFAULT_TENANT_ID).strip()


def _assert_resource(user: dict[str, Any], resource: str, action: str, tenant_id: str) -> None:
    if not resource_action_allowed(user, resource, action):
        raise HTTPException(status_code=403, detail="Insufficient permission")
    try:
        enforce_resource_scope(user, resource, action, tenant_id=tenant_id)
    except HTTPException as exc:
        if exc.status_code in {403, 404}:
            raise HTTPException(status_code=404, detail="Service request not found") from exc
        raise
    if user.get("role_profile") != "System Administrator" and _tenant(user) != str(tenant_id or DEFAULT_TENANT_ID):
        raise HTTPException(status_code=404, detail="Service request not found")


def _group(conn, group_id: str | None, tenant_id: str) -> dict[str, Any] | None:
    if not group_id:
        return None
    row = conn.execute(
        "SELECT id, tenant_id, name FROM ticket_assignment_groups WHERE id = ? AND tenant_id = ?",
        (group_id, tenant_id),
    ).fetchone()
    return dict(row) if row else None


def _group_members(conn, group_id: str | None) -> list[str]:
    if not group_id:
        return []
    rows = conn.execute(
        """
        SELECT gm.user_id
          FROM ticket_assignment_group_members gm
          JOIN users u ON u.id = gm.user_id
         WHERE gm.group_id = ? AND COALESCE(u.status, 'active') = 'active'
         ORDER BY gm.user_id
        """,
        (group_id,),
    ).fetchall()
    return [str(row["user_id"]) for row in rows]


def _is_group_member(conn, group_id: str | None, user_id: str) -> bool:
    if not group_id or not user_id:
        return False
    return bool(conn.execute(
        """
        SELECT 1 FROM ticket_assignment_group_members gm
          JOIN users u ON u.id = gm.user_id
         WHERE gm.group_id = ? AND gm.user_id = ? AND COALESCE(u.status, 'active') = 'active'
        """,
        (group_id, user_id),
    ).fetchone())


def _can_browse_all_service_requests(user: dict[str, Any]) -> bool:
    if user.get("role") == "Administrator" or user.get("role_profile") == "System Administrator":
        return True
    if user.get("role_profile") == "Service Desk Manager":
        return resource_action_allowed(user, "service_request", "view")
    # Legacy Operators are the service desk queue role. A Change Requester
    # profile narrows that account back to its own requests and assigned groups.
    return user.get("role") == "Operator" and user.get("role_profile") != "Change Requester"


def _append_request_event(
    conn,
    request_id: str,
    event_type: str,
    actor: dict[str, Any],
    *,
    summary: str = "",
    evidence: Any = None,
    details: dict[str, Any] | None = None,
) -> None:
    actor_id, username = _actor(actor)
    conn.execute(
        """
        INSERT INTO service_request_events
            (id, request_id, event_type, actor_id, actor_username, summary, evidence_json, details_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?::jsonb, ?::jsonb, ?)
        """,
        (
            str(uuid.uuid4()), request_id, event_type, actor_id, username, summary,
            json.dumps(evidence, ensure_ascii=False),
            json.dumps(details or {}, ensure_ascii=False), _iso(_now()),
        ),
    )


def _append_sla_event(conn, clock_id: str, event_type: str, actor: dict[str, Any] | None, details: dict[str, Any] | None = None) -> None:
    actor_id, username = _actor(actor or {})
    conn.execute(
        """
        INSERT INTO ticket_sla_events (id, clock_id, event_type, actor_id, actor_username, details_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?::jsonb, ?)
        """,
        (str(uuid.uuid4()), clock_id, event_type, actor_id, username,
         json.dumps(details or {}, ensure_ascii=False), _iso(_now())),
    )


def _validate_calendar_schedule(schedule: Any, holidays: Any) -> tuple[dict[str, list[dict[str, str]]], list[str]]:
    if not isinstance(schedule, dict) or set(schedule) - set(_WEEKDAYS):
        raise HTTPException(status_code=422, detail="工作时间须按 monday 至 sunday 设置")
    result: dict[str, list[dict[str, str]]] = {}
    start_time_re = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end_time_re = re.compile(r"^(?:(?:[01]\d|2[0-3]):[0-5]\d|24:00)$")
    for weekday in _WEEKDAYS:
        periods = schedule.get(weekday, [])
        if not isinstance(periods, list):
            raise HTTPException(status_code=422, detail=f"{weekday} 必须是时间区间列表")
        normalized: list[dict[str, str]] = []
        for period in periods:
            if not isinstance(period, dict):
                raise HTTPException(status_code=422, detail="工作时间区间格式无效")
            start = str(period.get("start") or "")
            end = str(period.get("end") or "")
            if not start_time_re.fullmatch(start) or not end_time_re.fullmatch(end) or start >= end:
                raise HTTPException(status_code=422, detail="工作时间须为同日 HH:MM 区间，开始时间须早于结束时间")
            normalized.append({"start": start, "end": end})
        normalized.sort(key=lambda item: item["start"])
        for previous, current in zip(normalized, normalized[1:]):
            if previous["end"] > current["start"]:
                raise HTTPException(status_code=422, detail=f"{weekday} 的工作时间区间不能重叠")
        result[weekday] = normalized
    if not isinstance(holidays, list) or len(holidays) > 5000:
        raise HTTPException(status_code=422, detail="节假日必须是日期列表")
    normalized_holidays: list[str] = []
    for value in holidays:
        try:
            normalized_holidays.append(date.fromisoformat(str(value)).isoformat())
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="节假日须使用 YYYY-MM-DD 格式") from exc
    return result, sorted(set(normalized_holidays))


def _validate_request_schema(schema: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(schema, dict) or not isinstance(schema.get("fields", []), list):
        raise HTTPException(status_code=422, detail="申请字段须使用 {fields: [...]} 格式")
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed_types = {"text", "textarea", "number", "select", "boolean"}
    for item in schema.get("fields", []):
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="申请字段定义格式无效")
        key = str(item.get("key") or "").strip()
        label = str(item.get("label") or "").strip()
        field_type = str(item.get("type") or "text").strip().lower()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key) or not label or field_type not in allowed_types:
            raise HTTPException(status_code=422, detail="申请字段须提供合法 key、label 和支持的 type")
        if key in seen:
            raise HTTPException(status_code=422, detail="申请字段 key 不能重复")
        seen.add(key)
        if "required" in item and not isinstance(item["required"], bool):
            raise HTTPException(status_code=422, detail=f"{label} 的 required 须为布尔值")
        options: list[str] = []
        if field_type == "select":
            raw_options = item.get("options")
            if not isinstance(raw_options, list) or not raw_options or len(raw_options) > 100:
                raise HTTPException(status_code=422, detail=f"{label} 须至少配置一个选项")
            options = [str(value)[:200] for value in raw_options]
        fields.append({
            "key": key,
            "label": label[:120],
            "type": field_type,
            "required": bool(item.get("required", False)),
            **({"options": options} if field_type == "select" else {}),
        })
    return {"fields": fields}


def _validate_details(schema: dict[str, Any], details: Any) -> dict[str, Any]:
    if not isinstance(details, dict):
        raise HTTPException(status_code=422, detail="申请内容必须是对象")
    fields = schema.get("fields", [])
    allowed = {field["key"] for field in fields}
    if set(details) - allowed:
        raise HTTPException(status_code=422, detail="申请内容包含目录未定义的字段")
    result: dict[str, Any] = {}
    for field in fields:
        key, field_type = field["key"], field["type"]
        value = details.get(key)
        if value is None or value == "":
            if field.get("required"):
                raise HTTPException(status_code=422, detail=f"请填写必填项：{field['label']}")
            continue
        if field_type in {"text", "textarea"}:
            if not isinstance(value, str) or len(value) > 8000:
                raise HTTPException(status_code=422, detail=f"{field['label']} 须为不超过 8000 字符的文本")
        elif field_type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise HTTPException(status_code=422, detail=f"{field['label']} 须为数字")
        elif field_type == "boolean" and not isinstance(value, bool):
            raise HTTPException(status_code=422, detail=f"{field['label']} 须为布尔值")
        elif field_type == "select" and value not in field.get("options", []):
            raise HTTPException(status_code=422, detail=f"{field['label']} 须从已配置选项中选择")
        result[key] = value
    return result


def create_catalog_item(conn, user: dict[str, Any], *, key: str, name: str, description: str) -> dict[str, Any]:
    _assert_resource(user, "service_catalog", "create", _tenant(user))
    normalized_key = key.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", normalized_key):
        raise HTTPException(status_code=422, detail="目录标识只允许小写字母、数字、下划线和连字符")
    if not name.strip():
        raise HTTPException(status_code=422, detail="目录名称不能为空")
    tenant_id = tenant_id_for_write(user=user)
    item_id = str(uuid.uuid4())
    actor_id, username = _actor(user)
    now = _iso(_now())
    try:
        conn.execute(
            """
            INSERT INTO service_catalog_items
                (id, tenant_id, item_key, name, description, current_version, created_by_id, created_by_username, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
            """,
            (item_id, tenant_id, normalized_key, name.strip(), description.strip(), actor_id, username, now, now),
        )
    except Exception as exc:
        if getattr(exc, "sqlstate", None) == "23505" or getattr(exc, "pgcode", None) == "23505":
            raise HTTPException(status_code=409, detail="目录标识已存在") from exc
        raise
    return get_service_catalog_item(conn, item_id, user, include_inactive=True)


def _catalog_version_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "key": str(row["item_key"]),
        "name": str(row["name"]),
        "description": str(row.get("description") or ""),
        "current_version": int(row["current_version"] or 0),
        "version": int(row.get("version") or 0),
        "request_schema": _json_value(row.get("request_schema_json"), {"fields": []}),
        "requires_approval": bool(row.get("requires_approval")),
        "assignment_group_id": row.get("assignment_group_id"),
        "approval_group_id": row.get("approval_group_id"),
        "fulfillment_instructions": str(row.get("fulfillment_instructions") or ""),
        "acceptance_criteria": str(row.get("acceptance_criteria") or ""),
        "sla_policy_version_id": row.get("sla_policy_version_id"),
        "active": bool(row.get("active")),
    }


def _catalog_select(where: str = "") -> str:
    return f"""
        SELECT item.*, version.id AS version_id, version.version, version.request_schema_json,
               version.requires_approval, version.assignment_group_id,
               assignment_group.name AS assignment_group_name, version.approval_group_id,
               approval_group.name AS approval_group_name, version.fulfillment_instructions,
               version.acceptance_criteria, version.sla_policy_version_id
          FROM service_catalog_items item
          LEFT JOIN service_catalog_versions version
            ON version.catalog_item_id = item.id AND version.version = item.current_version
          LEFT JOIN ticket_assignment_groups assignment_group ON assignment_group.id = version.assignment_group_id
          LEFT JOIN ticket_assignment_groups approval_group ON approval_group.id = version.approval_group_id
          {where}
    """


def list_service_catalog(conn, user: dict[str, Any], *, include_inactive: bool = False) -> list[dict[str, Any]]:
    if not resource_action_allowed(user, "service_catalog", "view"):
        raise HTTPException(status_code=403, detail="Insufficient permission")
    if include_inactive and user.get("role") != "Administrator" and user.get("role_profile") != "System Administrator":
        raise HTTPException(status_code=403, detail="Only administrators can view unpublished catalog items")
    tenant_id = _tenant(user)
    clauses = ["item.tenant_id = ?"]
    params: list[Any] = [tenant_id]
    if not include_inactive:
        clauses.append("item.active = TRUE")
    rows = conn.execute(_catalog_select("WHERE " + " AND ".join(clauses) + " ORDER BY item.name, item.item_key"), tuple(params)).fetchall()
    return [_catalog_version_payload(dict(row)) for row in rows]


def get_service_catalog_item(conn, item_id: str, user: dict[str, Any], *, include_inactive: bool = False) -> dict[str, Any]:
    clauses = ["item.id = ?", "item.tenant_id = ?"]
    params: list[Any] = [item_id, _tenant(user)]
    if not include_inactive:
        clauses.append("item.active = TRUE")
    row = conn.execute(_catalog_select("WHERE " + " AND ".join(clauses)), tuple(params)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="服务目录项不存在")
    return _catalog_version_payload(dict(row))


def publish_catalog_version(
    conn,
    item_id: str,
    user: dict[str, Any],
    *,
    request_schema: Any,
    requires_approval: bool,
    assignment_group_id: str | None,
    approval_group_id: str | None,
    fulfillment_instructions: str,
    acceptance_criteria: str,
    sla_policy_version_id: str | None,
) -> dict[str, Any]:
    _assert_resource(user, "service_catalog", "publish", _tenant(user))
    item = conn.execute(
        "SELECT * FROM service_catalog_items WHERE id = ? AND tenant_id = ? FOR UPDATE",
        (item_id, _tenant(user)),
    ).fetchone()
    if not item:
        raise HTTPException(status_code=404, detail="服务目录项不存在")
    if requires_approval and not approval_group_id:
        raise HTTPException(status_code=422, detail="启用审批时必须指定审批责任组")
    if not assignment_group_id:
        raise HTTPException(status_code=422, detail="发布目录前必须指定受理责任组")
    for group_id in (assignment_group_id, approval_group_id):
        if group_id and not _group(conn, group_id, str(item["tenant_id"])):
            raise HTTPException(status_code=422, detail="责任组不存在或不属于当前租户")
        if group_id and not _group_members(conn, group_id):
            raise HTTPException(status_code=422, detail="责任组至少需要一名有效成员")
    if sla_policy_version_id:
        policy = conn.execute(
            """
            SELECT version.id
              FROM ticket_sla_policy_versions version
              JOIN ticket_sla_policies policy ON policy.id = version.policy_id
              JOIN ticket_work_calendar_versions calendar ON calendar.id = version.calendar_version_id
              JOIN ticket_work_calendars calendar_parent ON calendar_parent.id = calendar.calendar_id
             WHERE version.id = ? AND policy.tenant_id = ? AND calendar_parent.tenant_id = ?
               AND version.source_type = 'service_request' AND version.priority = 'P3'
            """,
            (sla_policy_version_id, item["tenant_id"], item["tenant_id"]),
        ).fetchone()
        if not policy:
            raise HTTPException(status_code=422, detail="SLA 策略版本不存在或与当前目录租户/类型不匹配")
    normalized_schema = _validate_request_schema(request_schema)
    actor_id, username = _actor(user)
    version = int(item["current_version"]) + 1
    version_id = str(uuid.uuid4())
    now = _iso(_now())
    conn.execute(
        """
        INSERT INTO service_catalog_versions
            (id, catalog_item_id, version, request_schema_json, requires_approval, assignment_group_id,
             approval_group_id, fulfillment_instructions, acceptance_criteria, sla_policy_version_id,
             published_by_id, published_by_username, published_at)
        VALUES (?, ?, ?, ?::jsonb, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (version_id, item_id, version, json.dumps(normalized_schema), requires_approval,
         assignment_group_id or None, approval_group_id or None, fulfillment_instructions.strip(),
         acceptance_criteria.strip(), sla_policy_version_id or None, actor_id, username, now),
    )
    conn.execute("UPDATE service_catalog_items SET current_version = ?, active = TRUE, updated_at = ? WHERE id = ?", (version, now, item_id))
    return get_service_catalog_item(conn, item_id, user)


def _calendar_by_version(conn, version_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT cv.*, c.id AS calendar_id, c.name AS calendar_name, c.tenant_id AS tenant_id
          FROM ticket_work_calendar_versions cv
          JOIN ticket_work_calendars c ON c.id = cv.calendar_id
         WHERE cv.id = ?
        """,
        (version_id,),
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["schedule"] = _json_value(result.pop("schedule_json", None), {})
    result["holidays"] = _json_value(result.pop("holidays_json", None), [])
    return result


def list_work_calendars(conn, user: dict[str, Any]) -> list[dict[str, Any]]:
    if not resource_action_allowed(user, "service_catalog", "view"):
        raise HTTPException(status_code=403, detail="Insufficient permission")
    rows = conn.execute(
        """
        SELECT calendar.*, version.id AS version_id, version.version, version.timezone,
               version.schedule_json, version.holidays_json
          FROM ticket_work_calendars calendar
          JOIN ticket_work_calendar_versions version
            ON version.calendar_id = calendar.id AND version.version = calendar.current_version
         WHERE calendar.tenant_id = ?
         ORDER BY calendar.name, calendar.id
        """,
        (_tenant(user),),
    ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "version_id": str(row["version_id"]),
            "name": str(row["name"]),
            "version": int(row["version"]),
            "timezone": str(row["timezone"]),
            "schedule": _json_value(row["schedule_json"], {}),
            "holidays": _json_value(row["holidays_json"], []),
        }
        for row in rows
    ]


def create_or_version_work_calendar(
    conn, user: dict[str, Any], *, calendar_id: str | None, name: str, timezone_name: str,
    schedule: Any, holidays: Any,
) -> dict[str, Any]:
    _assert_resource(user, "service_catalog", "manage_calendar", _tenant(user))
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=422, detail="时区须使用有效的 IANA 名称") from exc
    normalized_schedule, normalized_holidays = _validate_calendar_schedule(schedule, holidays)
    if not name.strip():
        raise HTTPException(status_code=422, detail="工作日历名称不能为空")
    tenant_id = tenant_id_for_write(user=user)
    actor_id, username = _actor(user)
    now = _iso(_now())
    if calendar_id:
        calendar = conn.execute(
            "SELECT * FROM ticket_work_calendars WHERE id = ? AND tenant_id = ? FOR UPDATE",
            (calendar_id, tenant_id),
        ).fetchone()
        if not calendar:
            raise HTTPException(status_code=404, detail="工作日历不存在")
        calendar_id = str(calendar["id"])
        version = int(calendar["current_version"]) + 1
        conn.execute("UPDATE ticket_work_calendars SET current_version = ?, name = ?, updated_at = ? WHERE id = ?", (version, name.strip(), now, calendar_id))
    else:
        calendar_id = str(uuid.uuid4())
        version = 1
        conn.execute(
            "INSERT INTO ticket_work_calendars(id, tenant_id, name, current_version, created_by_id, created_by_username, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?, ?, ?)",
            (calendar_id, tenant_id, name.strip(), actor_id, username, now, now),
        )
    version_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO ticket_work_calendar_versions
            (id, calendar_id, version, timezone, schedule_json, holidays_json, created_by_id, created_by_username, created_at)
        VALUES (?, ?, ?, ?, ?::jsonb, ?::jsonb, ?, ?, ?)
        """,
        (version_id, calendar_id, version, timezone_name, json.dumps(normalized_schedule), json.dumps(normalized_holidays), actor_id, username, now),
    )
    return {"id": calendar_id, "version_id": version_id, "name": name.strip(), "version": version, "timezone": timezone_name, "schedule": normalized_schedule, "holidays": normalized_holidays}


def list_sla_policies(conn, user: dict[str, Any]) -> list[dict[str, Any]]:
    if not resource_action_allowed(user, "service_catalog", "view"):
        raise HTTPException(status_code=403, detail="Insufficient permission")
    rows = conn.execute(
        """
        SELECT policy.id, policy.name, version.id AS version_id, version.version,
               version.source_type, version.priority, version.response_target_minutes,
               version.restore_target_minutes, version.fulfillment_target_minutes,
               version.warning_before_minutes, version.calendar_version_id,
               assignment.source_type AS assigned_source_type
          FROM ticket_sla_policies policy
          JOIN ticket_sla_policy_versions version ON version.policy_id = policy.id
          LEFT JOIN ticket_sla_policy_assignments assignment ON assignment.policy_version_id = version.id
         WHERE policy.tenant_id = ?
         ORDER BY policy.name, version.version DESC
        """,
        (_tenant(user),),
    ).fetchall()
    return [
        {
            "id": str(row["id"]), "version_id": str(row["version_id"]),
            "name": str(row["name"]), "version": int(row["version"]),
            "source_type": str(row["source_type"]), "priority": str(row["priority"]),
            "response_target_minutes": row["response_target_minutes"],
            "restore_target_minutes": row["restore_target_minutes"],
            "fulfillment_target_minutes": row["fulfillment_target_minutes"],
            "warning_before_minutes": row["warning_before_minutes"],
            "calendar_version_id": str(row["calendar_version_id"]),
            "active": bool(row["assigned_source_type"]),
        }
        for row in rows
    ]


def create_or_version_sla_policy(
    conn, user: dict[str, Any], *, policy_id: str | None, name: str, source_type: str,
    priority: str, response_target_minutes: int | None, restore_target_minutes: int | None,
    fulfillment_target_minutes: int | None, warning_before_minutes: int | None,
    calendar_version_id: str,
) -> dict[str, Any]:
    _assert_resource(user, "service_catalog", "manage_sla", _tenant(user))
    if not any((response_target_minutes, restore_target_minutes, fulfillment_target_minutes)):
        raise HTTPException(status_code=422, detail="至少设置一项正数服务时限")
    if not name.strip():
        raise HTTPException(status_code=422, detail="SLA 策略名称不能为空")
    if source_type == "incident" and fulfillment_target_minutes is not None:
        raise HTTPException(status_code=422, detail="故障工单不配置履约时限")
    if source_type == "service_request" and restore_target_minutes is not None:
        raise HTTPException(status_code=422, detail="服务申请不配置恢复时限")
    calendar = _calendar_by_version(conn, calendar_version_id)
    if not calendar or str(calendar["tenant_id"]) != _tenant(user):
        raise HTTPException(status_code=422, detail="工作日历版本不存在或不属于当前租户")
    tenant_id = tenant_id_for_write(user=user)
    actor_id, username = _actor(user)
    now = _iso(_now())
    if policy_id:
        policy = conn.execute("SELECT * FROM ticket_sla_policies WHERE id = ? AND tenant_id = ? FOR UPDATE", (policy_id, tenant_id)).fetchone()
        if not policy:
            raise HTTPException(status_code=404, detail="SLA 策略不存在")
        version = int(policy["current_version"]) + 1
        conn.execute("UPDATE ticket_sla_policies SET name = ?, current_version = ?, updated_at = ? WHERE id = ?", (name.strip(), version, now, policy_id))
    else:
        policy_id = str(uuid.uuid4())
        version = 1
        conn.execute(
            "INSERT INTO ticket_sla_policies(id, tenant_id, name, current_version, created_by_id, created_by_username, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?, ?, ?)",
            (policy_id, tenant_id, name.strip(), actor_id, username, now, now),
        )
    version_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO ticket_sla_policy_versions
            (id, policy_id, version, source_type, priority, response_target_minutes,
             restore_target_minutes, fulfillment_target_minutes, warning_before_minutes, calendar_version_id,
             created_by_id, created_by_username, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (version_id, policy_id, version, source_type, priority, response_target_minutes,
         restore_target_minutes, fulfillment_target_minutes, warning_before_minutes,
         calendar_version_id, actor_id, username, now),
    )
    conn.execute(
        """
        INSERT INTO ticket_sla_policy_assignments
            (tenant_id, source_type, priority, policy_version_id, updated_by_id, updated_by_username, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (tenant_id, source_type, priority) DO UPDATE
            SET policy_version_id = excluded.policy_version_id,
                updated_by_id = excluded.updated_by_id,
                updated_by_username = excluded.updated_by_username,
                updated_at = excluded.updated_at
        """,
        (tenant_id, source_type, priority, version_id, actor_id, username, now),
    )
    return {
        "id": policy_id, "version_id": version_id, "name": name.strip(), "version": version, "source_type": source_type,
        "priority": priority, "response_target_minutes": response_target_minutes,
        "restore_target_minutes": restore_target_minutes, "fulfillment_target_minutes": fulfillment_target_minutes,
        "warning_before_minutes": warning_before_minutes,
        "calendar_version_id": calendar_version_id, "active": True,
    }


def _calendar_working_seconds(conn, calendar_version_id: str, start: datetime, end: datetime) -> int:
    if end <= start:
        return 0
    calendar = _calendar_by_version(conn, calendar_version_id)
    if not calendar:
        return 0
    tz = ZoneInfo(str(calendar["timezone"]))
    schedule = calendar["schedule"] if isinstance(calendar["schedule"], dict) else {}
    holidays = set(calendar["holidays"] if isinstance(calendar["holidays"], list) else [])
    local_start = start.astimezone(tz)
    local_end = end.astimezone(tz)
    current_day = local_start.date()
    total_seconds = 0
    while current_day <= local_end.date():
        if current_day.isoformat() not in holidays:
            weekday = _WEEKDAYS[current_day.weekday()]
            for period in schedule.get(weekday, []):
                window_start = _calendar_boundary(current_day, period["start"], tz)
                window_end = _calendar_boundary(current_day, period["end"], tz)
                overlap_start = max(start.astimezone(timezone.utc), window_start)
                overlap_end = min(end.astimezone(timezone.utc), window_end)
                if overlap_end > overlap_start:
                    total_seconds += int((overlap_end - overlap_start).total_seconds())
        current_day += timedelta(days=1)
    return total_seconds


def _calendar_boundary(calendar_day: date, value: str, tz: ZoneInfo) -> datetime:
    if value == "24:00":
        local_value = datetime.combine(calendar_day + timedelta(days=1), time.min, tzinfo=tz)
    else:
        local_value = datetime.combine(calendar_day, time.fromisoformat(value), tzinfo=tz)
    return local_value.astimezone(timezone.utc)


def _add_working_seconds(conn, calendar_version_id: str, start: datetime, seconds: int) -> datetime:
    remaining = max(0, int(seconds))
    if remaining == 0:
        return start.astimezone(timezone.utc)
    calendar = _calendar_by_version(conn, calendar_version_id)
    if not calendar:
        raise HTTPException(status_code=409, detail="SLA 绑定的工作日历版本不存在")
    tz = ZoneInfo(str(calendar["timezone"]))
    schedule = calendar["schedule"] if isinstance(calendar["schedule"], dict) else {}
    holidays = set(calendar["holidays"] if isinstance(calendar["holidays"], list) else [])
    cursor = start.astimezone(timezone.utc)
    # Finite cap prevents corrupt calendars from producing an unbounded search.
    for _ in range(3660):
        local_day = cursor.astimezone(tz).date()
        if local_day.isoformat() not in holidays:
            weekday = _WEEKDAYS[local_day.weekday()]
            windows = schedule.get(weekday, [])
            for period in windows:
                window_start = _calendar_boundary(local_day, period["start"], tz)
                window_end = _calendar_boundary(local_day, period["end"], tz)
                begin = max(cursor, window_start)
                if begin >= window_end:
                    continue
                available = int((window_end - begin).total_seconds())
                if remaining <= available:
                    return begin + timedelta(seconds=remaining)
                remaining -= available
                cursor = window_end
        next_local_midnight = datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=tz)
        cursor = next_local_midnight.astimezone(timezone.utc)
    raise HTTPException(status_code=422, detail="目标时限超出工作日历可计算范围")


def _active_policy(conn, tenant_id: str, source_type: str, priority: str, pinned_policy_id: str | None = None) -> dict[str, Any] | None:
    if pinned_policy_id:
        row = conn.execute(
            """
            SELECT version.*
              FROM ticket_sla_policy_versions version
              JOIN ticket_sla_policies policy ON policy.id = version.policy_id
              JOIN ticket_work_calendar_versions calendar ON calendar.id = version.calendar_version_id
              JOIN ticket_work_calendars calendar_parent ON calendar_parent.id = calendar.calendar_id
             WHERE version.id = ? AND policy.tenant_id = ? AND calendar_parent.tenant_id = ?
            """,
            (pinned_policy_id, tenant_id, tenant_id),
        ).fetchone()
        return dict(row) if row and row["source_type"] == source_type and row["priority"] == priority else None
    row = conn.execute(
        """
        SELECT version.*
          FROM ticket_sla_policy_assignments assignment
          JOIN ticket_sla_policy_versions version ON version.id = assignment.policy_version_id
         WHERE assignment.tenant_id = ? AND assignment.source_type = ? AND assignment.priority = ?
        """,
        (tenant_id, source_type, priority),
    ).fetchone()
    return dict(row) if row else None


def initialize_sla_clocks(
    conn, *, source_type: str, source_id: str, tenant_id: str, priority: str,
    actor: dict[str, Any] | None = None, pinned_policy_id: str | None = None,
) -> int:
    """Create clocks only when an explicit matching policy is configured."""
    policy = _active_policy(conn, tenant_id, source_type, priority, pinned_policy_id)
    if not policy:
        return 0
    clock_kinds = (
        [("response", policy.get("response_target_minutes")), ("restore", policy.get("restore_target_minutes"))]
        if source_type == "incident"
        else [("response", policy.get("response_target_minutes")), ("fulfillment", policy.get("fulfillment_target_minutes"))]
    )
    created = 0
    now = _now()
    for kind, target_minutes in clock_kinds:
        if not target_minutes:
            continue
        existing = conn.execute(
            "SELECT id FROM ticket_sla_clocks WHERE source_type = ? AND (incident_ticket_id = ? OR service_request_id = ?) AND kind = ?",
            (source_type, source_id if source_type == "incident" else None, source_id if source_type == "service_request" else None, kind),
        ).fetchone()
        if existing:
            continue
        deadline = _add_working_seconds(conn, str(policy["calendar_version_id"]), now, int(target_minutes) * 60)
        clock_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO ticket_sla_clocks
                (id, source_type, incident_ticket_id, service_request_id, kind, policy_version_id,
                 tenant_id, status, started_at, running_since, deadline_at, remaining_work_seconds, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?)
            """,
            (clock_id, source_type, source_id if source_type == "incident" else None,
             source_id if source_type == "service_request" else None, kind,
             policy["id"], tenant_id, _iso(now), _iso(now), _iso(deadline), int(target_minutes) * 60, _iso(now), _iso(now)),
        )
        _append_sla_event(conn, clock_id, "started", actor, {"policy_version_id": policy["id"], "target_minutes": int(target_minutes)})
        created += 1
    return created


def _stop_sla_clock(conn, *, source_type: str, source_id: str, kind: str, event_type: str, actor: dict[str, Any] | None) -> None:
    col = "incident_ticket_id" if source_type == "incident" else "service_request_id"
    row = conn.execute(
        f"SELECT clock.*, policy.calendar_version_id FROM ticket_sla_clocks clock JOIN ticket_sla_policy_versions policy ON policy.id = clock.policy_version_id WHERE clock.{col} = ? AND clock.kind = ? AND clock.status IN ('running', 'paused') ORDER BY clock.created_at DESC LIMIT 1 FOR UPDATE OF clock",
        (source_id, kind),
    ).fetchone()
    if not row:
        return
    now = _now()
    if row["status"] == "running" and row.get("running_since"):
        running_since = row["running_since"]
        if isinstance(running_since, str):
            running_since = datetime.fromisoformat(running_since.replace("Z", "+00:00"))
        elapsed = _calendar_working_seconds(conn, str(row["calendar_version_id"]), running_since, now)
    else:
        elapsed = 0
    remaining = max(0, int(row["remaining_work_seconds"] or 0) - elapsed)
    conn.execute(
        "UPDATE ticket_sla_clocks SET status = 'met', remaining_work_seconds = ?, running_since = NULL, completed_at = ?, updated_at = ? WHERE id = ?",
        (remaining, _iso(now), _iso(now), row["id"]),
    )
    _append_sla_event(conn, str(row["id"]), event_type, actor, {"remaining_work_seconds": remaining})


def _stop_active_sla_clocks(conn, *, source_type: str, source_id: str, event_type: str, actor: dict[str, Any] | None) -> None:
    col = "incident_ticket_id" if source_type == "incident" else "service_request_id"
    rows = conn.execute(
        f"SELECT id FROM ticket_sla_clocks WHERE {col} = ? AND status IN ('running', 'paused') FOR UPDATE",
        (source_id,),
    ).fetchall()
    now = _iso(_now())
    for row in rows:
        conn.execute(
            "UPDATE ticket_sla_clocks SET status = 'stopped', running_since = NULL, completed_at = ?, updated_at = ? WHERE id = ?",
            (now, now, row["id"]),
        )
        _append_sla_event(conn, str(row["id"]), event_type, actor, {})


def _pause_resume_sla_clocks(conn, *, source_type: str, source_id: str, pause: bool, actor: dict[str, Any]) -> None:
    col = "incident_ticket_id" if source_type == "incident" else "service_request_id"
    target_status = "running" if pause else "paused"
    rows = conn.execute(
        f"SELECT clock.*, policy.calendar_version_id FROM ticket_sla_clocks clock JOIN ticket_sla_policy_versions policy ON policy.id = clock.policy_version_id WHERE clock.{col} = ? AND clock.status = ? FOR UPDATE",
        (source_id, target_status),
    ).fetchall()
    now = _now()
    for row in rows:
        remaining = int(row["remaining_work_seconds"] or 0)
        if pause and row.get("running_since"):
            running_since = row["running_since"]
            if isinstance(running_since, str):
                running_since = datetime.fromisoformat(running_since.replace("Z", "+00:00"))
            consumed = _calendar_working_seconds(conn, str(row["calendar_version_id"]), running_since, now)
            remaining = max(0, remaining - consumed)
            status, running_since_value, deadline = "paused", None, row["deadline_at"]
            event = "paused"
        else:
            status = "running"
            running_since_value = _iso(now)
            deadline = _iso(_add_working_seconds(conn, str(row["calendar_version_id"]), now, remaining))
            event = "resumed"
        conn.execute(
            "UPDATE ticket_sla_clocks SET status = ?, remaining_work_seconds = ?, running_since = ?, deadline_at = ?, updated_at = ? WHERE id = ?",
            (status, remaining, running_since_value, deadline, _iso(now), row["id"]),
        )
        _append_sla_event(conn, str(row["id"]), event, actor, {"remaining_work_seconds": remaining})


def _request_row(conn, request_id: str, *, lock: bool = False) -> dict[str, Any]:
    suffix = " FOR UPDATE OF request" if lock else ""
    row = conn.execute(
        f"""
        SELECT request.*, assignment_group.name AS assignment_group_name,
               approval_group.name AS approval_group_name
          FROM service_requests request
          LEFT JOIN ticket_assignment_groups assignment_group ON assignment_group.id = request.assignment_group_id
          LEFT JOIN ticket_assignment_groups approval_group ON approval_group.id = request.approval_group_id
         WHERE request.id = ?{suffix}
        """,
        (request_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Service request not found")
    item = dict(row)
    item["details"] = _json_value(item.pop("details_json", {}), {})
    item["catalog_snapshot"] = _json_value(item.pop("catalog_snapshot_json", {}), {})
    item["delivery_evidence"] = _json_value(item.pop("delivery_evidence_json", None), None)
    item["ticket_key"] = str(item.get("request_number") or "")
    item["source_type"] = "service_request"
    item["source_id"] = str(item["id"])
    item["current_owner_username"] = str(item.get("assignee_username") or item.get("assignment_group_name") or "")
    return item


def _can_request_action(conn, request: dict[str, Any], user: dict[str, Any], action: str) -> bool:
    user_id, username = _actor(user)
    requester = user_id == str(request.get("requester_id") or "")
    group_id = str(request.get("assignment_group_id") or "")
    approval_group_id = str(request.get("approval_group_id") or "")
    assignee = user_id == str(request.get("assignee_id") or "")
    assigned_member = bool(group_id and _is_group_member(conn, group_id, user_id))
    approval_member = bool(approval_group_id and _is_group_member(conn, approval_group_id, user_id))
    status = str(request.get("status") or "")
    admin = user.get("role") == "Administrator" or user.get("role_profile") == "System Administrator"
    if action == "approve":
        return status == "pending_approval" and not requester and (admin or approval_member)
    if action == "reject":
        return status == "pending_approval" and not requester and (admin or approval_member)
    if action == "assign":
        return status not in {"completed", "rejected", "cancelled"} and resource_action_allowed(user, "service_request", "assign")
    if action == "claim":
        return status in {"accepted", "in_progress"} and not request.get("assignee_id") and assigned_member and resource_action_allowed(user, "service_request", "claim")
    if action in {"acknowledge", "start"}:
        return status in {"accepted", "in_progress"} and (assignee or assigned_member or admin) and resource_action_allowed(user, "service_request", action)
    if action == "wait_external":
        return status == "in_progress" and (assignee or assigned_member or admin) and resource_action_allowed(user, "service_request", action)
    if action == "resume":
        return status == "waiting_external" and (assignee or assigned_member or admin) and resource_action_allowed(user, "service_request", action)
    if action == "deliver":
        return status in {"in_progress", "waiting_external"} and (assignee or assigned_member or admin) and resource_action_allowed(user, "service_request", action)
    if action == "confirm_complete":
        return status == "pending_confirmation" and (requester or admin)
    if action == "return":
        return status == "pending_confirmation" and (requester or admin)
    if action == "cancel":
        return status not in {"completed", "rejected", "cancelled"} and (requester or admin)
    if action == "link_change_order":
        return status not in {"completed", "rejected", "cancelled"} and (
            requester or assignee or assigned_member or approval_member or admin
        ) and resource_action_allowed(user, "service_request", "link_change_order")
    return False


def _allowed_request_actions(conn, request: dict[str, Any], user: dict[str, Any]) -> list[str]:
    actions = ("approve", "reject", "assign", "claim", "acknowledge", "start", "wait_external", "resume", "deliver", "confirm_complete", "return", "cancel", "link_change_order")
    allowed: list[str] = []
    for action in actions:
        if not _can_request_action(conn, request, user, action):
            continue
        try:
            _assert_resource(user, "service_request", action, str(request["tenant_id"]))
        except HTTPException:
            # Group-member approvals are controlled by the group membership
            # contract above; requesters may act on their own completion or
            # cancellation step even when their profile is read-only elsewhere.
            if action in {"approve", "reject"} and (
                user.get("role") == "Administrator"
                or _is_group_member(conn, str(request.get("approval_group_id") or ""), _actor(user)[0])
            ):
                allowed.append(action)
            elif action in {"confirm_complete", "return", "cancel"} and _actor(user)[0] == str(request.get("requester_id") or ""):
                allowed.append(action)
            continue
        allowed.append(action)
    return allowed


def _sla_detail(conn, *, source_type: str, source_id: str) -> dict[str, Any]:
    col = "incident_ticket_id" if source_type == "incident" else "service_request_id"
    rows = conn.execute(
        f"""
        SELECT clock.*, policy.calendar_version_id, calendar_version.timezone AS calendar_timezone
          FROM ticket_sla_clocks clock
          JOIN ticket_sla_policy_versions policy ON policy.id = clock.policy_version_id
          JOIN ticket_work_calendar_versions calendar_version ON calendar_version.id = policy.calendar_version_id
         WHERE clock.{col} = ? ORDER BY clock.created_at, clock.kind
        """,
        (source_id,),
    ).fetchall()
    now = _now()
    clocks = []
    for row in rows:
        remaining = int(row["remaining_work_seconds"] or 0)
        if row["status"] == "running" and row.get("running_since"):
            running_since = row["running_since"]
            if isinstance(running_since, str):
                running_since = datetime.fromisoformat(running_since.replace("Z", "+00:00"))
            consumed = _calendar_working_seconds(conn, str(row["calendar_version_id"]), running_since, now)
            remaining = max(0, remaining - consumed)
        clocks.append({
            "kind": str(row["kind"]), "status": str(row["status"]), "configured": True,
            "started_at": _iso(row["started_at"]), "deadline_at": _iso(row["deadline_at"]),
            "remaining_seconds": remaining, "calendar_timezone": str(row["calendar_timezone"]),
        })
    expected = {"response", "restore"} if source_type == "incident" else {"response", "fulfillment"}
    configured = bool(expected.intersection(clock["kind"] for clock in clocks))
    for kind in expected:
        if not any(clock["kind"] == kind for clock in clocks):
            clocks.append({
                "kind": kind, "status": "not_configured", "configured": False,
                "started_at": None, "deadline_at": None, "remaining_seconds": None,
                "calendar_timezone": None,
            })
    clocks.sort(key=lambda item: (item["kind"] != "response", item["kind"]))
    return {"configured": configured, "clocks": clocks}


def list_service_requests(
    conn, user: dict[str, Any], *, page: int = 1, page_size: int = 10,
    status: str = "", search: str = "", my_todo: bool = False,
) -> dict[str, Any]:
    scope = allowed_resource_scope(conn, user, "service_request", "view")
    if not resource_action_allowed(user, "service_request", "view"):
        return {"items": [], "total": 0, "page": page, "page_size": page_size}
    clauses = ["request.tenant_id = ?"]
    params: list[Any] = [_tenant(user)]
    if TENANT_ISOLATION_ENABLED and scope.tenant_id:
        clauses.append("request.tenant_id = ?")
        params.append(scope.tenant_id)
    if status:
        if status == "active":
            clauses.append("request.status NOT IN ('completed', 'rejected', 'cancelled')")
        else:
            clauses.append("request.status = ?")
            params.append(status)
    if search:
        pattern = f"%{search.strip()}%"
        clauses.append("(request.title ILIKE ? OR request.request_number ILIKE ? OR request.requester_username ILIKE ?)")
        params.extend((pattern, pattern, pattern))
    if my_todo:
        user_id, username = _actor(user)
        clauses.append(
            "((request.requester_id = ? AND request.status IN ('pending_confirmation', 'rejected')) "
            "OR (request.assignee_id = ? AND request.status IN ('accepted', 'in_progress', 'waiting_external')) "
            "OR (request.status = 'pending_approval' AND EXISTS (SELECT 1 FROM ticket_assignment_group_members gm WHERE gm.group_id = request.approval_group_id AND gm.user_id = ?)) "
            "OR (request.status IN ('accepted', 'in_progress') AND request.assignee_id IS NULL AND EXISTS (SELECT 1 FROM ticket_assignment_group_members gm WHERE gm.group_id = request.assignment_group_id AND gm.user_id = ?)))"
        )
        params.extend((user_id, user_id, user_id, user_id))
    if not _can_browse_all_service_requests(user):
        user_id, _ = _actor(user)
        clauses.append(
            "(request.requester_id = ? OR request.assignee_id = ? "
            "OR EXISTS (SELECT 1 FROM ticket_assignment_group_members gm JOIN users member_user ON member_user.id = gm.user_id "
            "WHERE gm.group_id = request.assignment_group_id AND gm.user_id = ? AND lower(COALESCE(member_user.status, 'active')) = 'active') "
            "OR EXISTS (SELECT 1 FROM ticket_assignment_group_members gm JOIN users member_user ON member_user.id = gm.user_id "
            "WHERE gm.group_id = request.approval_group_id AND gm.user_id = ? AND lower(COALESCE(member_user.status, 'active')) = 'active'))"
        )
        params.extend((user_id, user_id, user_id, user_id))
    where = "WHERE " + " AND ".join(clauses)
    total = int(conn.execute(f"SELECT COUNT(*) FROM service_requests request {where}", tuple(params)).fetchone()[0])
    rows = conn.execute(
        f"""
        SELECT request.*, group_row.name AS assignment_group_name
          FROM service_requests request
          LEFT JOIN ticket_assignment_groups group_row ON group_row.id = request.assignment_group_id
          {where}
         ORDER BY CASE request.status WHEN 'pending_approval' THEN 0 WHEN 'accepted' THEN 1 WHEN 'in_progress' THEN 2 ELSE 3 END,
                  request.updated_at DESC, request.id
         LIMIT ? OFFSET ?
        """,
        tuple([*params, page_size, max(0, page - 1) * page_size]),
    ).fetchall()
    return {"items": [_request_row(conn, str(row["id"])) for row in rows], "total": total, "page": page, "page_size": page_size}


def list_unified_tickets(
    conn, user: dict[str, Any], *, page: int = 1, page_size: int = 10,
    source_type: str = "all", status: str = "", search: str = "", my_todo: bool = False,
) -> dict[str, Any]:
    if source_type not in {"all", "incident", "service_request"}:
        raise HTTPException(status_code=422, detail="工单类型无效")
    unions: list[str] = []
    params: list[Any] = []
    if source_type in {"all", "incident"} and resource_action_allowed(user, "incident_ticket", "view"):
        incident_scope = allowed_resource_scope(conn, user, "incident_ticket", "view")
        asset_scope = allowed_resource_scope(conn, user, "asset", "view")
        if not any(item.site_ids == () and item.device_group_ids == () for item in (incident_scope, asset_scope)):
            incident_clauses: list[str] = []
            incident_params: list[Any] = []
            if user.get("role_profile") != "System Administrator":
                incident_clauses.append("t.tenant_id = ?")
                incident_params.append(_tenant(user))
            if TENANT_ISOLATION_ENABLED and incident_scope.tenant_id:
                incident_clauses.append("t.tenant_id = ?")
                incident_params.append(incident_scope.tenant_id)
            if status:
                incident_clauses.append("t.status = ?")
                incident_params.append(status)
            if search:
                pattern = f"%{search.strip()}%"
                incident_clauses.append("(t.title ILIKE ? OR t.ticket_number ILIKE ? OR t.description ILIKE ?)")
                incident_params.extend((pattern, pattern, pattern))
            if my_todo:
                user_id, _ = _actor(user)
                incident_clauses.append(
                    "((t.assignee_id = ? AND t.status IN ('open','in_progress')) "
                    "OR (t.created_by_id = ? AND t.status = 'pending_confirmation') "
                    "OR (t.assignee_id IS NULL AND t.status = 'open' AND EXISTS (SELECT 1 FROM ticket_assignment_group_members gm WHERE gm.group_id = t.assigned_group_id AND gm.user_id = ?)))"
                )
                incident_params.extend((user_id, user_id, user_id))
            scope_sql, scope_params = _scope_filter_sql((incident_scope, asset_scope))
            incident_clauses.append(scope_sql)
            incident_params.extend(scope_params)
            incident_where = "WHERE " + " AND ".join(incident_clauses)
            unions.append(
                f"""
                SELECT 'incident' AS source_type, t.id AS source_id, t.ticket_number AS ticket_key,
                       t.title, t.status, t.priority, t.created_by_username AS requester_username,
                       COALESCE(NULLIF(t.assignee_username, ''), group_row.name, '') AS current_owner_username,
                       group_row.name AS assignment_group_name, t.assignee_username,
                       t.created_at, t.updated_at, t.tenant_id,
                       t.id AS incident_ticket_id, NULL::text AS service_request_id
                  FROM incident_tickets t
                  LEFT JOIN ticket_assignment_groups group_row ON group_row.id = t.assigned_group_id
                  {incident_where}
                """
            )
            params.extend(incident_params)
    if source_type in {"all", "service_request"} and resource_action_allowed(user, "service_request", "view"):
        request_clauses = ["request.tenant_id = ?"]
        request_params: list[Any] = [_tenant(user)]
        request_scope = allowed_resource_scope(conn, user, "service_request", "view")
        if TENANT_ISOLATION_ENABLED and request_scope.tenant_id:
            request_clauses.append("request.tenant_id = ?")
            request_params.append(request_scope.tenant_id)
        if status:
            request_clauses.append("request.status = ?")
            request_params.append(status)
        if search:
            pattern = f"%{search.strip()}%"
            request_clauses.append("(request.title ILIKE ? OR request.request_number ILIKE ? OR request.requester_username ILIKE ?)")
            request_params.extend((pattern, pattern, pattern))
        if my_todo:
            user_id, _ = _actor(user)
            request_clauses.append(
                "((request.requester_id = ? AND request.status = 'pending_confirmation') "
                "OR (request.assignee_id = ? AND request.status IN ('accepted','in_progress','waiting_external')) "
                "OR (request.status = 'pending_approval' AND EXISTS (SELECT 1 FROM ticket_assignment_group_members gm WHERE gm.group_id = request.approval_group_id AND gm.user_id = ?)) "
                "OR (request.status IN ('accepted','in_progress') AND request.assignee_id IS NULL AND EXISTS (SELECT 1 FROM ticket_assignment_group_members gm WHERE gm.group_id = request.assignment_group_id AND gm.user_id = ?)))"
            )
            request_params.extend((user_id, user_id, user_id, user_id))
        if not _can_browse_all_service_requests(user):
            user_id, _ = _actor(user)
            request_clauses.append(
                "(request.requester_id = ? OR request.assignee_id = ? "
                "OR EXISTS (SELECT 1 FROM ticket_assignment_group_members gm JOIN users member_user ON member_user.id = gm.user_id "
                "WHERE gm.group_id = request.assignment_group_id AND gm.user_id = ? AND lower(COALESCE(member_user.status, 'active')) = 'active') "
                "OR EXISTS (SELECT 1 FROM ticket_assignment_group_members gm JOIN users member_user ON member_user.id = gm.user_id "
                "WHERE gm.group_id = request.approval_group_id AND gm.user_id = ? AND lower(COALESCE(member_user.status, 'active')) = 'active'))"
            )
            request_params.extend((user_id, user_id, user_id, user_id))
        request_where = "WHERE " + " AND ".join(request_clauses)
        unions.append(
            f"""
            SELECT 'service_request' AS source_type, request.id AS source_id, request.request_number AS ticket_key,
                   request.title, request.status, request.priority, request.requester_username,
                   COALESCE(NULLIF(request.assignee_username, ''), group_row.name, '') AS current_owner_username,
                   group_row.name AS assignment_group_name, request.assignee_username,
                   request.created_at, request.updated_at, request.tenant_id,
                   NULL::text AS incident_ticket_id, request.id AS service_request_id
              FROM service_requests request
              LEFT JOIN ticket_assignment_groups group_row ON group_row.id = request.assignment_group_id
              {request_where}
            """
        )
        params.extend(request_params)
    if not unions:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}
    combined = " UNION ALL ".join(unions)
    total = int(conn.execute(f"SELECT COUNT(*) FROM ({combined}) unified", tuple(params)).fetchone()[0])
    rows = conn.execute(
        f"""
        SELECT * FROM ({combined}) unified
         ORDER BY CASE status WHEN 'pending_approval' THEN 0 WHEN 'open' THEN 1 WHEN 'accepted' THEN 2 WHEN 'in_progress' THEN 3 ELSE 4 END,
                  updated_at DESC, source_type, source_id
         LIMIT ? OFFSET ?
        """,
        tuple([*params, page_size, max(0, page - 1) * page_size]),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if item["source_type"] == "incident":
            from services.incident_ticket_service import get_ticket_detail

            detail = get_ticket_detail(conn, str(item["source_id"]), user)
            item["allowed_actions"] = detail["ticket"].get("allowed_actions", [])
            item["next_step"] = _incident_next_step(detail["ticket"])
        else:
            request = _request_row(conn, str(item["source_id"]))
            _assert_resource(user, "service_request", "view", str(request["tenant_id"]))
            item["allowed_actions"] = _allowed_request_actions(conn, request, user)
            item["next_step"] = _service_request_next_step(request, item["allowed_actions"])
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def get_ticket_summary(conn, user: dict[str, Any], *, from_date: date, to_date: date) -> dict[str, Any]:
    """Summarize only the incident/service-request rows visible to this actor.

    Date inputs are inclusive UTC calendar dates. Duration metrics are elapsed
    UTC seconds derived from stored ticket events/completion facts, not SLA
    clock business seconds.
    """
    if to_date < from_date:
        raise HTTPException(status_code=422, detail="结束日期不能早于开始日期")
    day_count = (to_date - from_date).days + 1
    if day_count > 366:
        raise HTTPException(status_code=422, detail="统计范围最多为 366 天")
    try:
        start_at = datetime.combine(from_date, time.min, tzinfo=timezone.utc)
        end_at = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    except OverflowError as exc:
        raise HTTPException(status_code=422, detail="日期范围超出可统计边界") from exc
    start_text, end_text = _iso(start_at), _iso(end_at)

    source_queries: list[str] = []
    source_params: list[Any] = []
    if resource_action_allowed(user, "incident_ticket", "view"):
        incident_scope = allowed_resource_scope(conn, user, "incident_ticket", "view")
        asset_scope = allowed_resource_scope(conn, user, "asset", "view")
        if not any(item.site_ids == () and item.device_group_ids == () for item in (incident_scope, asset_scope)):
            clauses = ["t.created_at >= ?", "t.created_at < ?"]
            params: list[Any] = [start_text, end_text]
            if user.get("role_profile") != "System Administrator":
                clauses.append("t.tenant_id = ?")
                params.append(_tenant(user))
            if TENANT_ISOLATION_ENABLED and incident_scope.tenant_id:
                clauses.append("t.tenant_id = ?")
                params.append(incident_scope.tenant_id)
            scope_sql, scope_params = _scope_filter_sql((incident_scope, asset_scope))
            clauses.append(scope_sql)
            params.extend(scope_params)
            source_queries.append(
                f"""
                SELECT 'incident'::text AS source_type, t.id AS source_id, t.priority, t.status,
                       t.created_at, t.closed_at, NULL::timestamptz AS completed_at,
                       t.assigned_group_id AS assignment_group_id
                  FROM incident_tickets t
                 WHERE {' AND '.join(clauses)}
                """
            )
            source_params.extend(params)

    if resource_action_allowed(user, "service_request", "view"):
        request_scope = allowed_resource_scope(conn, user, "service_request", "view")
        clauses = ["request.created_at >= ?", "request.created_at < ?", "request.tenant_id = ?"]
        params = [start_text, end_text, _tenant(user)]
        if TENANT_ISOLATION_ENABLED and request_scope.tenant_id:
            clauses.append("request.tenant_id = ?")
            params.append(request_scope.tenant_id)
        if not _can_browse_all_service_requests(user):
            user_id, _ = _actor(user)
            clauses.append(
                "(request.requester_id = ? OR request.assignee_id = ? "
                "OR EXISTS (SELECT 1 FROM ticket_assignment_group_members gm JOIN users member_user ON member_user.id = gm.user_id "
                "WHERE gm.group_id = request.assignment_group_id AND gm.user_id = ? AND lower(COALESCE(member_user.status, 'active')) = 'active') "
                "OR EXISTS (SELECT 1 FROM ticket_assignment_group_members gm JOIN users member_user ON member_user.id = gm.user_id "
                "WHERE gm.group_id = request.approval_group_id AND gm.user_id = ? AND lower(COALESCE(member_user.status, 'active')) = 'active'))"
            )
            params.extend((user_id, user_id, user_id, user_id))
        source_queries.append(
            f"""
            SELECT 'service_request'::text AS source_type, request.id AS source_id,
                   request.priority, request.status, request.created_at,
                   NULL::timestamptz AS closed_at, request.completed_at,
                   request.assignment_group_id
              FROM service_requests request
             WHERE {' AND '.join(clauses)}
            """
        )
        source_params.extend(params)

    if source_queries:
        visible_cte = "WITH visible_tickets AS (" + " UNION ALL ".join(source_queries) + ") "
        visible_params = tuple(source_params)
    else:
        visible_cte = "WITH visible_tickets AS (SELECT NULL::text AS source_type, NULL::text AS source_id, NULL::text AS priority, NULL::text AS status, NULL::timestamptz AS created_at, NULL::timestamptz AS closed_at, NULL::timestamptz AS completed_at, NULL::text AS assignment_group_id WHERE FALSE) "
        visible_params = ()

    totals_row = conn.execute(
        visible_cte + """
        SELECT COUNT(*)::int AS all_count,
               COUNT(*) FILTER (WHERE source_type = 'incident')::int AS incident_count,
               COUNT(*) FILTER (WHERE source_type = 'service_request')::int AS service_request_count,
               COUNT(*) FILTER (
                   WHERE (source_type = 'incident' AND status NOT IN ('closed', 'cancelled', 'merged'))
                      OR (source_type = 'service_request' AND status NOT IN ('completed', 'rejected', 'cancelled'))
               )::int AS active_count,
               COUNT(*) FILTER (
                   WHERE (source_type = 'incident' AND status = 'closed')
                      OR (source_type = 'service_request' AND status = 'completed')
               )::int AS closed_count
          FROM visible_tickets
        """,
        visible_params,
    ).fetchone()
    priority_rows = conn.execute(
        visible_cte + "SELECT priority, COUNT(*)::int AS count FROM visible_tickets GROUP BY priority",
        visible_params,
    ).fetchall()
    priority_counts = {str(row["priority"] or ""): int(row["count"] or 0) for row in priority_rows}
    group_rows = conn.execute(
        visible_cte + """
        SELECT item.assignment_group_id AS id,
               COALESCE(group_row.name, '未分组') AS name,
               COUNT(*)::int AS count
          FROM visible_tickets item
          LEFT JOIN ticket_assignment_groups group_row ON group_row.id = item.assignment_group_id
         GROUP BY item.assignment_group_id, group_row.name
         ORDER BY count DESC, name, item.assignment_group_id
        """,
        visible_params,
    ).fetchall()
    duration_rows = conn.execute(
        visible_cte + """
        , duration_samples AS (
            SELECT 'first_response_avg'::text AS metric,
                   EXTRACT(EPOCH FROM (MIN(event.created_at) - ticket.created_at))::float8 AS seconds
              FROM visible_tickets ticket
              JOIN incident_ticket_events event ON event.ticket_id = ticket.source_id
             WHERE ticket.source_type = 'incident' AND event.event_type = 'start'
               AND event.created_at >= ticket.created_at
             GROUP BY ticket.source_id, ticket.created_at
            UNION ALL
            SELECT 'first_response_avg'::text AS metric,
                   EXTRACT(EPOCH FROM (MIN(event.created_at) - ticket.created_at))::float8 AS seconds
              FROM visible_tickets ticket
              JOIN service_request_events event ON event.request_id = ticket.source_id
             WHERE ticket.source_type = 'service_request' AND event.event_type IN ('acknowledge', 'start')
               AND event.created_at >= ticket.created_at
             GROUP BY ticket.source_id, ticket.created_at
            UNION ALL
            SELECT 'incident_restore_avg'::text AS metric,
                   EXTRACT(EPOCH FROM (MIN(event.created_at) - ticket.created_at))::float8 AS seconds
              FROM visible_tickets ticket
              JOIN incident_ticket_events event ON event.ticket_id = ticket.source_id
             WHERE ticket.source_type = 'incident' AND event.event_type = 'request_confirmation'
               AND event.created_at >= ticket.created_at
             GROUP BY ticket.source_id, ticket.created_at
            UNION ALL
            SELECT 'service_fulfillment_avg'::text AS metric,
                   EXTRACT(EPOCH FROM (MIN(event.created_at) - ticket.created_at))::float8 AS seconds
              FROM visible_tickets ticket
              JOIN service_request_events event ON event.request_id = ticket.source_id
             WHERE ticket.source_type = 'service_request' AND event.event_type = 'confirm_complete'
               AND event.created_at >= ticket.created_at
             GROUP BY ticket.source_id, ticket.created_at
            UNION ALL
            SELECT 'close_avg'::text AS metric,
                   EXTRACT(EPOCH FROM (ticket.closed_at - ticket.created_at))::float8 AS seconds
              FROM visible_tickets ticket
             WHERE ticket.source_type = 'incident' AND ticket.status = 'closed'
               AND ticket.closed_at IS NOT NULL AND ticket.closed_at >= ticket.created_at
            UNION ALL
            SELECT 'close_avg'::text AS metric,
                   EXTRACT(EPOCH FROM (ticket.completed_at - ticket.created_at))::float8 AS seconds
              FROM visible_tickets ticket
             WHERE ticket.source_type = 'service_request' AND ticket.status = 'completed'
               AND ticket.completed_at IS NOT NULL AND ticket.completed_at >= ticket.created_at
        )
        SELECT metric, COUNT(*)::int AS sample_count, AVG(seconds)::float8 AS average_seconds
          FROM duration_samples GROUP BY metric
        """,
        visible_params,
    ).fetchall()
    durations = {
        "first_response_avg": None,
        "incident_restore_avg": None,
        "service_fulfillment_avg": None,
        "close_avg": None,
    }
    samples = {key: 0 for key in durations}
    for row in duration_rows:
        key = str(row["metric"])
        samples[key] = int(row["sample_count"] or 0)
        value = row["average_seconds"]
        durations[key] = round(float(value), 2) if value is not None and samples[key] > 0 else None

    return {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "totals": {
            "all": int(totals_row["all_count"] or 0),
            "incident": int(totals_row["incident_count"] or 0),
            "service_request": int(totals_row["service_request_count"] or 0),
            "active": int(totals_row["active_count"] or 0),
            "closed": int(totals_row["closed_count"] or 0),
        },
        "by_priority": [
            {"priority": priority, "count": priority_counts.get(priority, 0)}
            for priority in ("P1", "P2", "P3", "P4")
        ],
        "by_assignment_group": [
            {"id": row["id"], "name": str(row["name"]), "count": int(row["count"])}
            for row in group_rows
        ],
        "durations_seconds": durations,
        "sample_counts": samples,
        "duration_basis": "elapsed_utc_ticket_events",
    }


def _incident_next_step(ticket: dict[str, Any]) -> str:
    return {
        "open": "指派或认领" if not ticket.get("assignee_id") else "开始处理",
        "in_progress": "恢复后提交确认",
        "pending_confirmation": "等待确认关闭",
        "closed": "已关闭",
        "cancelled": "已取消",
        "merged": "已合并",
    }.get(str(ticket.get("status") or ""), "查看工单状态")


def _service_request_next_step(request: dict[str, Any], allowed_actions: list[str]) -> str:
    status = str(request.get("status") or "")
    steps = {
        "pending_approval": "等待审批",
        "submitted": "等待受理",
        "accepted": "开始受理" if "start" in allowed_actions else "指派或认领",
        "in_progress": "填写交付结果" if "deliver" in allowed_actions else "等待处理",
        "waiting_external": "等待外部资源" if "resume" not in allowed_actions else "恢复受理",
        "pending_confirmation": "等待申请人确认",
        "completed": "已完成",
        "rejected": "已拒绝",
        "cancelled": "已取消",
    }
    return steps.get(status, "查看申请状态")


def create_service_request(conn, user: dict[str, Any], *, catalog_item_id: str, version: int, title: str, details: Any) -> dict[str, Any]:
    _assert_resource(user, "service_request", "create", _tenant(user))
    if not title.strip():
        raise HTTPException(status_code=422, detail="申请标题不能为空")
    catalog = conn.execute(
        _catalog_select("WHERE item.id = ? AND item.tenant_id = ? AND item.active = TRUE AND version.version = item.current_version"),
        (catalog_item_id, _tenant(user)),
    ).fetchone()
    if not catalog or int(catalog["version"]) != int(version):
        raise HTTPException(status_code=409, detail="服务目录版本已变化，请刷新后重新提交")
    for group_id in (catalog["assignment_group_id"], catalog["approval_group_id"]):
        if group_id and not _group(conn, str(group_id), str(catalog["tenant_id"])):
            raise HTTPException(status_code=409, detail="服务目录引用了其他租户或已失效的责任组")
    catalog_row = dict(catalog)
    request_schema = _json_value(catalog_row.get("request_schema_json"), {"fields": []})
    validated_details = _validate_details(request_schema, details)
    requester_id, requester_username = _actor(user)
    tenant_id = tenant_id_for_write(requested=catalog_row["tenant_id"], user=user)
    group_id = str(catalog_row.get("assignment_group_id") or "") or None
    approval_group_id = str(catalog_row.get("approval_group_id") or "") or None
    status = "pending_approval" if catalog_row["requires_approval"] else "accepted"
    request_id = str(uuid.uuid4())
    request_number = f"SR-{_now():%Y%m%d}-{request_id.replace('-', '').upper()[:8]}"
    now = _iso(_now())
    snapshot = {
        "catalog_item_id": catalog_item_id,
        "key": catalog_row["item_key"],
        "name": catalog_row["name"],
        "version": int(catalog_row["version"]),
        "request_schema": request_schema,
        "requires_approval": bool(catalog_row["requires_approval"]),
        "assignment_group_id": group_id,
        "assignment_group_name": catalog_row.get("assignment_group_name"),
        "approval_group_id": approval_group_id,
        "approval_group_name": catalog_row.get("approval_group_name"),
        "fulfillment_instructions": catalog_row.get("fulfillment_instructions") or "",
        "acceptance_criteria": catalog_row.get("acceptance_criteria") or "",
        "sla_policy_version_id": catalog_row.get("sla_policy_version_id"),
    }
    conn.execute(
        """
        INSERT INTO service_requests
            (id, request_number, catalog_item_id, catalog_version_id, tenant_id, title, priority, status,
             requester_id, requester_username, assignment_group_id, approval_group_id,
             details_json, catalog_snapshot_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'P3', ?, ?, ?, ?, ?, ?::jsonb, ?::jsonb, ?, ?)
        """,
        (request_id, request_number, catalog_item_id, catalog_row["version_id"], tenant_id, title.strip(), status,
         requester_id, requester_username, group_id, approval_group_id,
         json.dumps(validated_details, ensure_ascii=False), json.dumps(snapshot, ensure_ascii=False), now, now),
    )
    _append_request_event(conn, request_id, "submitted", user, summary="服务申请已提交", details={"catalog_version": int(version)})
    if status == "pending_approval":
        _append_request_event(conn, request_id, "approval_requested", user, summary="已提交审批")
    else:
        _append_request_event(conn, request_id, "accepted", user, summary="申请已受理")
    initialize_sla_clocks(
        conn, source_type="service_request", source_id=request_id, tenant_id=tenant_id,
        priority="P3", actor=user, pinned_policy_id=snapshot.get("sla_policy_version_id"),
    )
    notify_group = approval_group_id if status == "pending_approval" else group_id
    _enqueue_group_notification(
        conn, source_type="service_request", source_id=request_id, tenant_id=tenant_id,
        group_id=notify_group, event_key=f"service_request:{request_id}:{status}",
        title="服务申请待审批" if status == "pending_approval" else "新服务申请待受理",
        message=title.strip(),
    )
    return _request_row(conn, request_id)


def _enqueue_group_notification(
    conn, *, source_type: str, source_id: str, tenant_id: str, group_id: str | None,
    event_key: str, title: str, message: str, also_user_ids: list[str] | None = None,
) -> int:
    if not group_id and not also_user_ids:
        return 0
    recipients = set(also_user_ids or [])
    recipients.update(_group_members(conn, group_id))
    col_incident = source_id if source_type == "incident" else None
    col_request = source_id if source_type == "service_request" else None
    count = 0
    for user_id in sorted(recipients):
        payload = {
            "title": title[:200], "message": message[:2000], "ticket_type": source_type,
            "ticket_id": source_id,
            "path": f"/tickets?ticket_id={source_id}" if source_type == "incident" else f"/tickets?request_id={source_id}",
        }
        conn.execute(
            """
            INSERT INTO ticket_notification_outbox
                (id, event_key, source_type, incident_ticket_id, service_request_id, tenant_id,
                 recipient_user_id, payload_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?::jsonb, ?, ?)
            ON CONFLICT (event_key, recipient_user_id) DO NOTHING
            """,
            (str(uuid.uuid4()), event_key, source_type, col_incident, col_request, tenant_id,
             user_id, json.dumps(payload, ensure_ascii=False), _iso(_now()), _iso(_now())),
        )
        count += 1
    return count


def enqueue_incident_ticket_notification(
    conn, ticket_id: str, *, event_key: str, title: str, message: str,
    recipients: list[str] | None = None, include_group: bool = True,
) -> int:
    ticket = conn.execute(
        "SELECT tenant_id, assigned_group_id FROM incident_tickets WHERE id = ?",
        (ticket_id,),
    ).fetchone()
    if not ticket:
        return 0
    return _enqueue_group_notification(
        conn, source_type="incident", source_id=ticket_id,
        tenant_id=str(ticket["tenant_id"] or DEFAULT_TENANT_ID),
        group_id=str(ticket["assigned_group_id"] or "") if include_group else None,
        event_key=event_key, title=title, message=message,
        also_user_ids=recipients,
    )


def _assert_request_access(conn, request: dict[str, Any], user: dict[str, Any], action: str) -> None:
    _assert_resource(user, "service_request", action, str(request["tenant_id"]))
    user_id, _ = _actor(user)
    admin = user.get("role") == "Administrator" or user.get("role_profile") == "System Administrator"
    is_requester = user_id == str(request.get("requester_id") or "")
    assignment_member = _is_group_member(conn, str(request.get("assignment_group_id") or ""), user_id)
    approval_member = _is_group_member(conn, str(request.get("approval_group_id") or ""), user_id)
    if not (admin or _can_browse_all_service_requests(user) or is_requester or assignment_member or approval_member):
        raise HTTPException(status_code=404, detail="Service request not found")


def get_service_request_detail(conn, request_id: str, user: dict[str, Any]) -> dict[str, Any]:
    request = _request_row(conn, request_id)
    _assert_request_access(conn, request, user, "view")
    events = []
    rows = conn.execute(
        "SELECT * FROM service_request_events WHERE request_id = ? ORDER BY created_at, id",
        (request_id,),
    ).fetchall()
    for row in rows:
        item = dict(row)
        item["evidence"] = _json_value(item.pop("evidence_json", None), None)
        item["details"] = _json_value(item.pop("details_json", {}), {})
        if item.get("event_type") == "change_order_linked":
            linked_id = str((item["details"] or {}).get("change_order_id") or "")
            visible_link = _visible_change_order_summary(
                conn, linked_id, user, expected_tenant_id=str(request["tenant_id"]),
            ) if linked_id else None
            if not visible_link:
                item["summary"] = "关联了变更单"
                item["details"] = {"linked": True}
        events.append(item)
    request["allowed_actions"] = _allowed_request_actions(conn, request, user)
    request["next_step"] = _service_request_next_step(request, request["allowed_actions"])
    linked_orders = []
    for link in conn.execute(
        "SELECT change_order_id FROM service_request_change_order_links WHERE service_request_id = ? ORDER BY created_at, id",
        (request_id,),
    ).fetchall():
        summary = _visible_change_order_summary(
            conn, str(link["change_order_id"]), user, expected_tenant_id=str(request["tenant_id"]),
        )
        if summary:
            linked_orders.append(summary)
    return {
        "request": request,
        "events": events,
        "sla": _sla_detail(conn, source_type="service_request", source_id=request_id),
        "linked_change_orders": linked_orders,
    }


def _visible_change_order_summary(
    conn, change_order_id: str, user: dict[str, Any], *, expected_tenant_id: str,
) -> dict[str, Any] | None:
    from api.change_orders.core import _require_change_order_access
    from services.change_order_service import get_change_order

    order = get_change_order(conn, change_order_id)
    if not order or str(order.get("tenant_id") or DEFAULT_TENANT_ID) != expected_tenant_id:
        return None
    try:
        _require_change_order_access(order, user, "view")
        enforce_resource_scope(user, "change_order", "view", tenant_id=expected_tenant_id)
        targets = order.get("target_devices") if isinstance(order.get("target_devices"), list) else []
        for target in targets:
            target_id = str((target.get("id") or target.get("device_id")) if isinstance(target, dict) else target or "").strip()
            if not target_id:
                return None
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
                return None
            enforce_resource_scope(
                user, "change_order", "view", tenant_id=str(device["tenant_id"] or "") or None,
                site_id=str(device["site_id"] or "") or None,
                device_group_id=str(device["device_group_id"] or "") or None,
            )
            enforce_resource_scope(
                user, "asset", "view", tenant_id=str(device["tenant_id"] or "") or None,
                site_id=str(device["site_id"] or "") or None,
                device_group_id=str(device["device_group_id"] or "") or None,
            )
    except HTTPException:
        return None
    return {
        key: order.get(key)
        for key in ("id", "order_number", "title", "status", "priority", "created_at")
    }


def link_change_order_to_service_request(
    conn, request_id: str, user: dict[str, Any], *, change_order_number: str,
) -> dict[str, Any]:
    request = _request_row(conn, request_id, lock=True)
    _assert_resource(user, "service_request", "link_change_order", str(request["tenant_id"]))
    user_id, username = _actor(user)
    assignment_member = _is_group_member(conn, str(request.get("assignment_group_id") or ""), user_id)
    approval_member = _is_group_member(conn, str(request.get("approval_group_id") or ""), user_id)
    is_requester = user_id == str(request.get("requester_id") or "")
    is_admin = user.get("role") == "Administrator" or user.get("role_profile") == "System Administrator"
    is_assignee = user_id == str(request.get("assignee_id") or "")
    if not (is_admin or is_requester or is_assignee or assignment_member or approval_member):
        raise HTTPException(status_code=404, detail="Service request not found")
    if request["status"] in {"completed", "rejected", "cancelled"}:
        raise HTTPException(status_code=409, detail="已结束的服务申请不能关联变更单")
    order_row = conn.execute(
        "SELECT id, tenant_id FROM change_orders WHERE order_number = ?",
        (change_order_number.strip(),),
    ).fetchone()
    if not order_row:
        raise HTTPException(status_code=404, detail="Change order not found")
    if str(order_row["tenant_id"] or DEFAULT_TENANT_ID) != str(request["tenant_id"]):
        raise HTTPException(status_code=404, detail="Change order not found")
    order_id = str(order_row["id"])
    summary = _visible_change_order_summary(
        conn, order_id, user, expected_tenant_id=str(request["tenant_id"]),
    )
    if not summary:
        raise HTTPException(status_code=404, detail="Change order not found")
    existing = conn.execute(
        "SELECT id FROM service_request_change_order_links WHERE service_request_id = ? AND change_order_id = ?",
        (request_id, order_id),
    ).fetchone()
    if existing:
        return {"created": False, "linked_change_order": summary}
    link_id = str(uuid.uuid4())
    now = _iso(_now())
    conn.execute(
        """
        INSERT INTO service_request_change_order_links
            (id, service_request_id, change_order_id, linked_by_id, linked_by_username, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (link_id, request_id, order_id, user_id, username, now),
    )
    _append_request_event(
        conn, request_id, "change_order_linked", user,
        summary=f"关联变更单 {summary['order_number']}",
        details={"change_order_id": order_id, "change_order_number": summary["order_number"]},
    )
    return {"created": True, "linked_change_order": summary}


def perform_service_request_action(
    conn, request_id: str, user: dict[str, Any], *, action: str, assignment_group_id: str | None = None,
    assignee_id: str | None = None, reason: str = "", summary: str = "", evidence: Any = None,
    change_order_number: str | None = None,
) -> dict[str, Any]:
    request = _request_row(conn, request_id, lock=True)
    if action not in _allowed_request_actions(conn, request, user):
        raise HTTPException(status_code=403, detail="当前账号不能执行此操作")
    if action == "link_change_order":
        if not change_order_number or not change_order_number.strip():
            raise HTTPException(status_code=422, detail="请填写变更单编号")
        link_change_order_to_service_request(conn, request_id, user, change_order_number=change_order_number)
        return _request_row(conn, request_id)
    previous = str(request["status"])
    actor_id, username = _actor(user)
    now = _iso(_now())
    event_ref = str(uuid.uuid4())
    update_fields: dict[str, Any] = {"updated_at": now}
    event_type = action
    event_summary = summary.strip() or {
        "approve": "审批通过", "reject": "审批拒绝", "assign": "更新责任分配", "claim": "处理人已认领",
        "acknowledge": "已响应申请", "start": "开始办理", "wait_external": "等待外部资源",
        "resume": "恢复办理", "deliver": "提交交付结果，等待申请人确认",
        "confirm_complete": "申请人确认完成", "return": "申请人退回补充处理", "cancel": "申请已取消",
    }.get(action, "更新服务申请")
    if action == "approve":
        update_fields["status"] = "accepted"
        _enqueue_group_notification(conn, source_type="service_request", source_id=request_id, tenant_id=request["tenant_id"], group_id=request.get("assignment_group_id"), event_key=f"service_request:{request_id}:accepted:{event_ref}", title="服务申请已审批", message=request["title"], also_user_ids=[request["requester_id"]])
    elif action == "reject":
        if not reason.strip():
            raise HTTPException(status_code=422, detail="请填写拒绝原因")
        update_fields["status"] = "rejected"
        event_summary = reason.strip()
        _enqueue_group_notification(conn, source_type="service_request", source_id=request_id, tenant_id=request["tenant_id"], group_id=None, event_key=f"service_request:{request_id}:rejected:{event_ref}", title="服务申请未通过", message=event_summary, also_user_ids=[request["requester_id"]])
    elif action == "assign":
        if not assignment_group_id:
            raise HTTPException(status_code=422, detail="请选择受理责任组")
        group = _group(conn, assignment_group_id, str(request["tenant_id"]))
        if not group:
            raise HTTPException(status_code=422, detail="责任组不存在或不属于当前租户")
        if assignee_id:
            member = conn.execute(
                "SELECT user_id, username FROM ticket_assignment_group_members gm JOIN users u ON u.id = gm.user_id WHERE gm.group_id = ? AND gm.user_id = ? AND COALESCE(u.status, 'active') = 'active'",
                (assignment_group_id, assignee_id),
            ).fetchone()
            if not member:
                raise HTTPException(status_code=422, detail="受理人必须是当前责任组的有效成员")
            update_fields["assignee_id"] = assignee_id
            update_fields["assignee_username"] = str(member["username"] or "")
        else:
            update_fields["assignee_id"] = None
            update_fields["assignee_username"] = ""
        update_fields["assignment_group_id"] = assignment_group_id
        event_summary = reason.strip() or f"指派至 {group['name']}"
        _enqueue_group_notification(conn, source_type="service_request", source_id=request_id, tenant_id=request["tenant_id"], group_id=assignment_group_id, event_key=f"service_request:{request_id}:assigned:{event_ref}", title="有服务申请指派给责任组", message=request["title"], also_user_ids=[assignee_id] if assignee_id else [])
    elif action == "claim":
        update_fields["assignee_id"] = actor_id
        update_fields["assignee_username"] = username
    elif action == "acknowledge":
        _stop_sla_clock(conn, source_type="service_request", source_id=request_id, kind="response", event_type="response_acknowledged", actor=user)
    elif action == "start":
        update_fields["status"] = "in_progress"
        _stop_sla_clock(conn, source_type="service_request", source_id=request_id, kind="response", event_type="response_acknowledged", actor=user)
    elif action == "wait_external":
        update_fields["status"] = "waiting_external"
        _pause_resume_sla_clocks(conn, source_type="service_request", source_id=request_id, pause=True, actor=user)
    elif action == "resume":
        update_fields["status"] = "in_progress"
        _pause_resume_sla_clocks(conn, source_type="service_request", source_id=request_id, pause=False, actor=user)
    elif action == "deliver":
        if not summary.strip():
            raise HTTPException(status_code=422, detail="请填写交付结果")
        update_fields["status"] = "pending_confirmation"
        update_fields["delivery_summary"] = summary.strip()
        update_fields["delivery_evidence_json"] = json.dumps(evidence, ensure_ascii=False)
        _pause_resume_sla_clocks(conn, source_type="service_request", source_id=request_id, pause=True, actor=user)
        _enqueue_group_notification(conn, source_type="service_request", source_id=request_id, tenant_id=request["tenant_id"], group_id=None, event_key=f"service_request:{request_id}:pending_confirmation:{event_ref}", title="服务申请待确认", message=summary.strip(), also_user_ids=[request["requester_id"]])
    elif action == "confirm_complete":
        update_fields["status"] = "completed"
        update_fields["completed_at"] = now
        _stop_sla_clock(conn, source_type="service_request", source_id=request_id, kind="fulfillment", event_type="fulfillment_confirmed", actor=user)
    elif action == "return":
        if not reason.strip():
            raise HTTPException(status_code=422, detail="请填写退回原因")
        update_fields["status"] = "in_progress"
        event_summary = reason.strip()
        _pause_resume_sla_clocks(conn, source_type="service_request", source_id=request_id, pause=False, actor=user)
        _enqueue_group_notification(conn, source_type="service_request", source_id=request_id, tenant_id=request["tenant_id"], group_id=request.get("assignment_group_id"), event_key=f"service_request:{request_id}:returned:{event_ref}", title="服务申请被退回", message=event_summary)
    elif action == "cancel":
        update_fields["status"] = "cancelled"
        event_summary = reason.strip() or "服务申请已取消"
        _stop_active_sla_clocks(conn, source_type="service_request", source_id=request_id, event_type="cancelled", actor=user)
    if action == "reject":
        _stop_active_sla_clocks(conn, source_type="service_request", source_id=request_id, event_type="rejected", actor=user)

    assignments = ", ".join(f"{column} = ?" for column in update_fields)
    conn.execute(
        f"UPDATE service_requests SET {assignments} WHERE id = ?",
        tuple([*update_fields.values(), request_id]),
    )
    _append_request_event(
        conn, request_id, event_type, user, summary=event_summary,
        evidence=evidence, details={"from_status": previous, "to_status": update_fields.get("status", previous), "reason": reason.strip()},
    )
    _enqueue_group_notification(
        conn, source_type="service_request", source_id=request_id, tenant_id=request["tenant_id"],
        group_id=None, event_key=f"service_request:{request_id}:event:{event_type}:{event_ref}",
        title=f"服务申请 {request['request_number']} 状态更新", message=event_summary,
        also_user_ids=[request["requester_id"]] if actor_id != request["requester_id"] else [],
    )
    refreshed = _request_row(conn, request_id)
    return refreshed


def get_incident_sla_detail(conn, ticket_id: str) -> dict[str, Any]:
    return _sla_detail(conn, source_type="incident", source_id=ticket_id)


def apply_incident_sla_event(conn, ticket_id: str, event_type: str, actor: dict[str, Any] | None = None) -> None:
    if event_type in {"start", "acknowledge"}:
        _stop_sla_clock(conn, source_type="incident", source_id=ticket_id, kind="response", event_type="response_acknowledged", actor=actor)
    elif event_type == "request_confirmation":
        _stop_sla_clock(conn, source_type="incident", source_id=ticket_id, kind="restore", event_type="recovery_submitted", actor=actor)
    elif event_type in {"confirm_close", "cancel", "merge"}:
        _stop_active_sla_clocks(conn, source_type="incident", source_id=ticket_id, event_type=event_type, actor=actor)
    ticket = conn.execute(
        "SELECT ticket_number, title, created_by_id, assigned_group_id, assignee_id, assignee_username FROM incident_tickets WHERE id = ?",
        (ticket_id,),
    ).fetchone()
    if not ticket:
        return
    if event_type == "assign":
        recipients = [str(ticket["assignee_id"])] if ticket["assignee_id"] else []
        title = "故障工单已更新责任分配"
        message = f"{ticket['ticket_number']} {ticket['title']}"
        include_group = True
    elif event_type == "request_confirmation":
        recipients = [str(ticket["created_by_id"])] if ticket["created_by_id"] else []
        title = "故障工单待确认恢复"
        message = f"{ticket['ticket_number']} {ticket['title']}"
        include_group = False
    elif event_type in {"confirm_close", "cancel"}:
        recipients = [str(ticket["created_by_id"])] if ticket["created_by_id"] else []
        title = "故障工单状态更新"
        message = f"{ticket['ticket_number']} {event_type}"
        include_group = event_type == "cancel"
    else:
        return
    enqueue_incident_ticket_notification(
        conn, ticket_id, event_key=f"incident_ticket:{ticket_id}:{event_type}:{uuid.uuid4()}",
        title=title, message=message, recipients=recipients, include_group=include_group,
    )


def evaluate_due_sla_clocks(conn, *, limit: int = 100) -> int:
    now = _now()
    now_text = _iso(now)
    rows = conn.execute(
        """
        SELECT clock.*, policy.warning_before_minutes
          FROM ticket_sla_clocks clock
          JOIN ticket_sla_policy_versions policy ON policy.id = clock.policy_version_id
         WHERE clock.status = 'running'
           AND (
               clock.deadline_at <= ?
               OR (policy.warning_before_minutes IS NOT NULL
                   AND clock.warning_sent_at IS NULL
                   AND clock.deadline_at <= ?::timestamptz + (policy.warning_before_minutes * INTERVAL '1 minute'))
           )
         ORDER BY clock.deadline_at, clock.id
         LIMIT ? FOR UPDATE OF clock SKIP LOCKED
        """,
        (now_text, now_text, max(1, min(500, int(limit)))),
    ).fetchall()
    count = 0
    for row in rows:
        deadline = row["deadline_at"]
        if isinstance(deadline, str):
            deadline = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        breached = deadline <= now
        if breached:
            conn.execute("UPDATE ticket_sla_clocks SET status = 'breached', updated_at = ? WHERE id = ? AND status = 'running'", (now_text, row["id"]))
            event_type = "breached"
            event_key_suffix = "breached"
            summary = "工单 SLA 已超时"
            message = f"{row['kind']} 时限已超出。"
        else:
            conn.execute("UPDATE ticket_sla_clocks SET warning_sent_at = ?, updated_at = ? WHERE id = ? AND status = 'running' AND warning_sent_at IS NULL", (now_text, now_text, row["id"]))
            event_type = "warning_approaching"
            event_key_suffix = "warning"
            summary = "工单 SLA 即将超时"
            message = f"{row['kind']} 时限将在 {int(row['warning_before_minutes'])} 分钟内到期。"
        _append_sla_event(conn, str(row["id"]), event_type, None, {"deadline_at": _iso(deadline), "warning_before_minutes": row["warning_before_minutes"]})
        source_type = str(row["source_type"])
        source_id = str(row["incident_ticket_id"] if source_type == "incident" else row["service_request_id"])
        if source_type == "incident":
            source = conn.execute("SELECT tenant_id, assigned_group_id, created_by_id, title FROM incident_tickets WHERE id = ?", (source_id,)).fetchone()
            title = f"工单 SLA 超时：{source['title']}" if source else "工单 SLA 超时"
            group_id = source["assigned_group_id"] if source else None
            requester_id = source["created_by_id"] if source else None
        else:
            source = conn.execute("SELECT tenant_id, assignment_group_id, requester_id, title FROM service_requests WHERE id = ?", (source_id,)).fetchone()
            title = f"工单 SLA 超时：{source['title']}" if source else "工单 SLA 超时"
            group_id = source["assignment_group_id"] if source else None
            requester_id = source["requester_id"] if source else None
        if source:
            _enqueue_group_notification(
                conn, source_type=source_type, source_id=source_id, tenant_id=str(source["tenant_id"]),
                group_id=group_id, event_key=f"sla:{row['id']}:{event_key_suffix}",
                title=title if breached else summary,
                message=message, also_user_ids=[requester_id] if requester_id else [],
            )
        count += 1
    return count


def _serialize_outbox(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["payload"] = _json_value(item.pop("payload_json", {}), {})
    return item


def claim_ticket_notifications(conn, *, limit: int = 50, worker_id: str) -> list[dict[str, Any]]:
    lease_seconds = 60
    rows = conn.execute(
        """
        WITH candidates AS (
            SELECT id FROM ticket_notification_outbox
             WHERE status IN ('pending','failed','sending') AND available_at <= clock_timestamp()
               AND (lease_until IS NULL OR lease_until <= clock_timestamp())
             ORDER BY available_at, created_at, id LIMIT ?
             FOR UPDATE SKIP LOCKED
        )
        UPDATE ticket_notification_outbox outbox
           SET status = 'sending', lease_owner = ?, lease_until = clock_timestamp() + (? * INTERVAL '1 second'),
               attempts = attempts + 1, updated_at = clock_timestamp()
          FROM candidates
         WHERE outbox.id = candidates.id
        RETURNING outbox.*
        """,
        (max(1, min(100, int(limit))), worker_id, lease_seconds),
    ).fetchall()
    deliveries = [_serialize_outbox(row) for row in rows]
    for delivery in deliveries:
        conn.execute(
            "INSERT INTO ticket_notification_attempts(id, outbox_id, attempt_no, phase, worker_id, created_at) VALUES (?, ?, ?, 'started', ?, ?) ON CONFLICT(outbox_id, attempt_no, phase) DO NOTHING",
            (str(uuid.uuid4()), delivery["id"], int(delivery["attempts"]), worker_id, _iso(_now())),
        )
    return deliveries


def finish_ticket_notification(conn, *, delivery_id: str, worker_id: str, success: bool, error_code: str = "", suppressed: bool = False) -> None:
    row = conn.execute(
        "SELECT attempts FROM ticket_notification_outbox WHERE id = ? AND status = 'sending' AND lease_owner = ? FOR UPDATE",
        (delivery_id, worker_id),
    ).fetchone()
    if not row:
        return
    attempts = max(1, int(row["attempts"] or 1))
    phase = "suppressed" if suppressed and success else "sent" if success else "failed"
    conn.execute(
        "INSERT INTO ticket_notification_attempts(id, outbox_id, attempt_no, phase, worker_id, error_code, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(outbox_id, attempt_no, phase) DO NOTHING",
        (str(uuid.uuid4()), delivery_id, attempts, phase, worker_id, str(error_code or "")[:160], _iso(_now())),
    )
    if success:
        conn.execute(
            "UPDATE ticket_notification_outbox SET status = ?, sent_at = clock_timestamp(), lease_owner = '', lease_until = NULL, last_error = '', updated_at = clock_timestamp() WHERE id = ?",
            ("suppressed" if suppressed else "sent", delivery_id),
        )
    else:
        delay = min(3600, 2 ** min(attempts, 10) * 5)
        conn.execute(
            "UPDATE ticket_notification_outbox SET status = 'failed', available_at = clock_timestamp() + (? * INTERVAL '1 second'), lease_owner = '', lease_until = NULL, last_error = ?, updated_at = clock_timestamp() WHERE id = ?",
            (delay, str(error_code or "delivery_failed")[:160], delivery_id),
        )


def ticket_notification_delivery_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    return {
        "title": str(payload.get("title") or "工单通知"),
        "message": str(payload.get("message") or "工单状态有更新"),
        "object_name": str(payload.get("ticket_id") or ""),
        "status": "active",
        "severity": "info",
        "notification_user_ids": [str(row["recipient_user_id"])],
        "tenant_id": str(row["tenant_id"]),
    }


def relay_ticket_notifications_once(*, limit: int = 50) -> dict[str, int]:
    worker_id = str(uuid.uuid4())
    conn = __import__("database").get_db_connection()
    try:
        evaluated = evaluate_due_sla_clocks(conn, limit=limit)
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    try:
        rows = claim_ticket_notifications(conn, limit=limit, worker_id=worker_id)
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    conn.close()
    counts = {"evaluated": evaluated, "claimed": len(rows), "sent": 0, "failed": 0, "suppressed": 0}
    from services import notification_service
    for row in rows:
        connection = __import__("database").get_db_connection()
        try:
            payload = ticket_notification_delivery_payload(row)
            if not notification_service.automatic_notifications_enabled():
                finish_ticket_notification(connection, delivery_id=row["id"], worker_id=worker_id, success=True, suppressed=True)
                counts["suppressed"] += 1
            else:
                results = notification_service.dispatch_to_user_ids(
                    payload, [str(row["recipient_user_id"])], str(row["tenant_id"]), raise_on_error=True,
                )
                failures = [result for result in results if not result.get("success", False)]
                if not results or failures:
                    error = str(failures[0].get("error") or "delivery_failed") if failures else "delivery_unavailable"
                    finish_ticket_notification(connection, delivery_id=row["id"], worker_id=worker_id, success=False, error_code=error)
                    counts["failed"] += 1
                else:
                    finish_ticket_notification(connection, delivery_id=row["id"], worker_id=worker_id, success=True)
                    counts["sent"] += 1
            connection.commit()
        except Exception as exc:
            connection.rollback()
            retry_conn = __import__("database").get_db_connection()
            try:
                finish_ticket_notification(retry_conn, delivery_id=row["id"], worker_id=worker_id, success=False, error_code=type(exc).__name__)
                retry_conn.commit()
            except Exception:
                retry_conn.rollback()
            finally:
                retry_conn.close()
            counts["failed"] += 1
        finally:
            connection.close()
    return counts


__all__ = [
    "apply_incident_sla_event", "claim_ticket_notifications", "create_catalog_item",
    "create_or_version_sla_policy", "create_or_version_work_calendar", "create_service_request",
    "evaluate_due_sla_clocks", "finish_ticket_notification", "get_incident_sla_detail",
    "get_service_catalog_item", "get_service_request_detail", "initialize_sla_clocks",
    "enqueue_incident_ticket_notification", "list_service_catalog", "list_sla_policies", "list_unified_tickets", "list_work_calendars",
    "link_change_order_to_service_request", "perform_service_request_action", "publish_catalog_version", "relay_ticket_notifications_once",
    "ticket_notification_delivery_payload",
]
