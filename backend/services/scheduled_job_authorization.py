"""Shared authorization and immutable approval manifests for scheduled jobs."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from core.rbac import authorize_resource, is_global_administrator
from core.tenant_policy import TENANT_ISOLATION_ENABLED, tenant_scope_for_user
from services.config_approval_service import approval_manifest_hash


JOB_OPERATIONS = frozenset({"CREATE", "UPDATE", "ENABLE", "DISABLE", "DELETE", "EXECUTION"})
DEVICE_SCOPES = frozenset({"all", "site", "role", "composite", "tag", "tags", "ip", "ids"})


def _canonical_filter(value: Any, scope_type: str) -> str:
    if isinstance(value, (dict, list)):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            parsed = {} if scope_type == "composite" else raw
        else:
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                parsed = raw
    if scope_type == "composite":
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError("复合设备范围必须包含至少一个有效条件")
        allowed = {"site", "role", "category", "platform"}
        if set(parsed) - allowed or not any(str(value or "").strip() for value in parsed.values()):
            raise ValueError("复合设备范围包含未知字段或空条件")
    if scope_type not in {"all", "composite"} and not parsed:
        raise ValueError("设备范围筛选条件不能为空")
    if scope_type in {"tag", "tags"} and not isinstance(parsed, (dict, list)):
        raise ValueError("标签设备范围格式无效")
    if isinstance(parsed, (dict, list)):
        return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(parsed)


def _string(value: Any) -> str:
    return str(value or "").strip()


def _decode_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def normalize_authorization_grant(value: Any) -> dict[str, Any]:
    """Validate the caller-owned bounds that will be bound into approval."""
    if not isinstance(value, dict):
        raise ValueError("计划作业必须包含有界授权条款")
    allowed = {
        "valid_until", "max_runs", "max_targets", "scope", "ticket_source_type",
        "ticket_id", "change_order_id",
    }
    if set(value) - allowed:
        raise ValueError("计划作业授权条款包含未知字段")
    raw_until = _string(value.get("valid_until"))
    try:
        valid_until = datetime.fromisoformat(raw_until.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("授权到期时间必须是 ISO UTC 时间") from exc
    if valid_until.tzinfo is None or valid_until.utcoffset() != timezone.utc.utcoffset(valid_until):
        raise ValueError("授权到期时间必须是 ISO UTC 时间")

    def bounded_integer(name: str) -> int:
        raw = value.get(name)
        if isinstance(raw, bool):
            raise ValueError(f"{name} 必须是 1 到 10000 之间的整数")
        try:
            parsed = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} 必须是 1 到 10000 之间的整数") from exc
        if str(raw).strip() != str(parsed) or not 1 <= parsed <= 10000:
            raise ValueError(f"{name} 必须是 1 到 10000 之间的整数")
        return parsed

    source_type = _string(value.get("ticket_source_type"))
    ticket_id = _string(value.get("ticket_id"))
    if source_type not in {"incident", "service_request"} or not ticket_id:
        raise ValueError("授权必须关联一个有效的 incident 或 service_request 工单")
    scope = value.get("scope")
    if not isinstance(scope, dict):
        raise ValueError("授权必须绑定设备范围")
    scope_type = _string(scope.get("type")).lower()
    if scope_type not in DEVICE_SCOPES:
        raise ValueError("授权设备范围类型无效")
    normalized_scope = {
        "type": scope_type,
        "filter": _canonical_filter(scope.get("filter", ""), scope_type),
    }
    return {
        "valid_until": valid_until.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "max_runs": bounded_integer("max_runs"),
        "max_targets": bounded_integer("max_targets"),
        "scope": normalized_scope,
        "ticket_source_type": source_type,
        "ticket_id": ticket_id,
        "change_order_id": _string(value.get("change_order_id")),
    }


def _split_check_items(value: str) -> list[str]:
    import re

    return [item.strip() for item in re.split(r"[,\n]", value) if item.strip()]


def _check_items(source: dict[str, Any], commands: str, action: str) -> list[str]:
    if action != "inspection":
        return []
    raw = source.get("check_items")
    if isinstance(raw, list):
        items = [str(item).strip() for item in raw if str(item).strip()]
        if items:
            # Scheduled jobs persist inspection selections in the commands
            # column, which the execution path splits on commas/newlines.
            # Canonicalize approval manifests to that same effective list so
            # the approved and persisted snapshots remain identical.
            return _split_check_items(",".join(items))
    if commands:
        return _split_check_items(commands)
    return []


def job_manifest_source_from_row(row: dict[str, Any], operation: str) -> dict[str, Any]:
    """Convert a database row to the public, stable manifest shape."""
    action = _string(row.get("action_type"))
    commands = _string(row.get("commands"))
    source = {
        "operation": operation,
        "job_id": _string(row.get("id")),
        "current_authorization_grant_id": _string(row.get("current_authorization_grant_id")),
        "job_type": _string(row.get("job_type")) or "cron",
        "name": _string(row.get("name")),
        "action": action,
        "cron_expr": _string(row.get("cron_expr")),
        "scheduled_at": _string(row.get("scheduled_at")),
        "scope": {
            "type": _string(row.get("device_scope")) or "all",
            "filter": row.get("device_filter") or "",
        },
        "commands": commands,
        "check_items": _check_items(row, commands, action),
        "script_id": _string(row.get("script_id")),
        "is_config": 1 if row.get("is_config") else 0,
        "use_admin_creds": 1 if row.get("use_admin_creds") else 0,
        "enabled": bool(row.get("enabled", True)),
        "config_reason": _string(row.get("config_reason")),
    }
    grant = row.get("authorization_grant")
    if not isinstance(grant, dict):
        grant = _decode_json_object(row.get("grant_json") or row.get("authorization_grant_json"))
    if grant:
        source["authorization_grant"] = normalize_authorization_grant(grant)
    return source


def merge_job_source(current: dict[str, Any], payload: dict[str, Any], operation: str) -> dict[str, Any]:
    """Apply the submitted editable fields to a saved row before hashing."""
    merged = dict(current)
    field_map = {
        "name": "name",
        "action": "action_type",
        "action_type": "action_type",
        "cron_expr": "cron_expr",
        "scheduled_at": "scheduled_at",
        "commands": "commands",
        "script_id": "script_id",
        "is_config": "is_config",
        "use_admin_creds": "use_admin_creds",
        "enabled": "enabled",
        "config_reason": "config_reason",
    }
    for incoming, stored in field_map.items():
        if incoming in payload:
            merged[stored] = payload[incoming]
    if "scope" in payload and isinstance(payload["scope"], dict):
        merged["device_scope"] = payload["scope"].get("type", merged.get("device_scope"))
        merged["device_filter"] = payload["scope"].get("filter", merged.get("device_filter"))
    else:
        if "device_scope" in payload:
            merged["device_scope"] = payload["device_scope"]
        if "device_filter" in payload:
            merged["device_filter"] = payload["device_filter"]
    if "check_items" in payload:
        items = payload.get("check_items") or []
        normalized_items = [str(item).strip() for item in items if str(item).strip()]
        if normalized_items:
            merged["commands"] = ",".join(normalized_items)
            merged["check_items"] = normalized_items
    if "authorization_grant" in payload:
        merged["authorization_grant"] = payload.get("authorization_grant")
    return job_manifest_source_from_row(merged, operation)


def normalize_job_manifest(
    source: dict[str, Any],
    *,
    operation: str,
    requester_id: str,
    tenant_id: str,
    script_sha256: str = "",
    job_id: str | None = None,
) -> dict[str, Any]:
    """Normalize user input and add server-owned identity/version fields."""
    op = _string(operation or source.get("operation")).upper()
    if op not in JOB_OPERATIONS:
        raise ValueError("计划作业操作类型无效")
    scope = source.get("scope") if isinstance(source.get("scope"), dict) else {}
    scope_type = _string(scope.get("type") or source.get("device_scope") or "all").lower()
    if scope_type not in DEVICE_SCOPES:
        raise ValueError("设备范围类型无效")
    scope_filter = _canonical_filter(
        scope.get("filter", source.get("device_filter", "")), scope_type,
    )
    action = _string(source.get("action") or source.get("action_type"))
    commands = _string(source.get("commands"))
    items = _check_items(source, commands, action)
    if action == "inspection" and items:
        commands = ",".join(items)
    job_type = _string(source.get("job_type")) or "cron"
    if job_type not in {"cron", "once"}:
        raise ValueError("计划作业类型无效")
    if not _string(source.get("name")):
        raise ValueError("作业名称不能为空")
    if job_type == "cron" and not _string(source.get("cron_expr")):
        raise ValueError("定时作业需要 cron 表达式")
    if job_type == "once" and not _string(source.get("scheduled_at")):
        raise ValueError("执行计划需要执行时间")
    if action == "nsot" and (commands or _string(source.get("script_id")) or source.get("is_config") or source.get("use_admin_creds")):
        raise ValueError("NSOT 系统采集作业不允许命令、脚本或管理凭据")
    normalized = {
        "operation": op,
        "job_id": _string(job_id if job_id is not None else source.get("job_id")),
        "job_type": job_type,
        "name": _string(source.get("name")),
        "action": action,
        "cron_expr": _string(source.get("cron_expr")),
        "scheduled_at": _string(source.get("scheduled_at")),
        "scope": {"type": scope_type, "filter": scope_filter},
        "commands": commands,
        "check_items": items,
        "script_id": _string(source.get("script_id")),
        "script_sha256": _string(script_sha256),
        "is_config": 1 if source.get("is_config") else 0,
        "use_admin_creds": 1 if source.get("use_admin_creds") else 0,
        "enabled": bool(source.get("enabled", True)),
        "config_reason": _string(source.get("config_reason")),
        "requester_id": _string(requester_id),
        "tenant_id": _string(tenant_id),
    }
    if source.get("authorization_grant") is not None:
        grant = normalize_authorization_grant(source.get("authorization_grant"))
        if grant["scope"] != normalized["scope"]:
            raise ValueError("授权设备范围必须与作业执行范围一致")
        normalized["authorization_grant"] = grant
    return normalized


def scheduled_job_approval_type(manifest: dict[str, Any]) -> str:
    if manifest.get("operation") == "DELETE" and manifest.get("job_type") != "once":
        return "scheduled_job_delete"
    return "execution_plan" if manifest.get("job_type") == "once" else "scheduled_job"


def manifest_hash(manifest: dict[str, Any]) -> str:
    return approval_manifest_hash(manifest)


def execution_snapshot(conn, row: dict[str, Any]) -> dict[str, Any]:
    source = job_manifest_source_from_row(row, "EXECUTION")
    # Enabled/disabled is a scheduler control state. It must be separately
    # approved as an operation, but it does not change the granted execution content.
    source["enabled"] = True
    if not source.get("authorization_grant"):
        grant_id = _string(row.get("current_authorization_grant_id"))
        if grant_id:
            grant_row = conn.execute(
                "SELECT grant_json FROM scheduled_job_authorization_grants WHERE grant_id = ?",
                (grant_id,),
            ).fetchone()
            if grant_row:
                source["authorization_grant"] = normalize_authorization_grant(
                    _decode_json_object(grant_row["grant_json"])
                )
    script_sha, _ = script_snapshot(conn, source.get("script_id", ""))
    return normalize_job_manifest(
        source,
        operation="EXECUTION",
        requester_id=_string(row.get("created_by_id")),
        tenant_id=_string(row.get("tenant_id")),
        script_sha256=script_sha,
        job_id=_string(row.get("id")),
    )


def template_version_for_manifest(manifest: dict[str, Any]) -> str:
    """Pin a released script by its content SHA, otherwise pin exact commands."""
    script_sha = _string(manifest.get("script_sha256"))
    if script_sha:
        return script_sha
    content = {
        "action": _string(manifest.get("action")),
        "commands": _string(manifest.get("commands")),
        "check_items": manifest.get("check_items") or [],
        "is_config": 1 if manifest.get("is_config") else 0,
        "config_reason": _string(manifest.get("config_reason")),
    }
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_authorization_grant_ticket(
    conn, grant: dict[str, Any], *, tenant_id: str,
) -> dict[str, str]:
    """Resolve and freeze the linked ticket and optional, same-tenant change order."""
    normalized = normalize_authorization_grant(grant)
    source_type = normalized["ticket_source_type"]
    if source_type == "incident":
        row = conn.execute(
            "SELECT id, ticket_number, title, tenant_id FROM incident_tickets WHERE id = ?",
            (normalized["ticket_id"],),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id, request_number AS ticket_number, title, tenant_id "
            "FROM service_requests WHERE id = ?",
            (normalized["ticket_id"],),
        ).fetchone()
    if not row:
        raise ValueError("关联工单不存在")
    ticket = dict(row)
    if _string(ticket.get("tenant_id")) != _string(tenant_id):
        raise ValueError("关联工单必须属于计划作业的租户")

    change_order_id = normalized["change_order_id"]
    change_order_number = ""
    if change_order_id:
        order_row = conn.execute(
            "SELECT id, order_number, tenant_id FROM change_orders WHERE id = ?",
            (change_order_id,),
        ).fetchone()
        if not order_row or _string(dict(order_row).get("tenant_id")) != _string(tenant_id):
            raise ValueError("关联变更单不存在或不属于计划作业的租户")
        if source_type == "incident":
            linked = conn.execute(
                "SELECT 1 FROM incident_ticket_links WHERE ticket_id = ? AND change_order_id = ?",
                (normalized["ticket_id"], change_order_id),
            ).fetchone()
        else:
            linked = conn.execute(
                "SELECT 1 FROM service_request_change_order_links "
                "WHERE service_request_id = ? AND change_order_id = ?",
                (normalized["ticket_id"], change_order_id),
            ).fetchone()
        if not linked:
            raise ValueError("关联变更单必须已通过工单链接关系关联")
        change_order_number = _string(dict(order_row).get("order_number"))

    return {
        **normalized,
        "ticket_number": _string(ticket.get("ticket_number")),
        "ticket_title": _string(ticket.get("title")),
        "change_order_number": change_order_number,
    }


def assert_authorization_grant_link_access(conn, grant: dict[str, Any], user: dict[str, Any]) -> None:
    """Require the requester to be able to view every linked ITSM record."""
    normalized = normalize_authorization_grant(grant)
    if normalized["ticket_source_type"] == "incident":
        from services.incident_ticket_service import get_ticket_detail
        get_ticket_detail(conn, normalized["ticket_id"], user)
    else:
        from services.service_request_service import get_service_request_detail
        get_service_request_detail(conn, normalized["ticket_id"], user)
    if normalized.get("change_order_id"):
        from api.change_orders.core import _require_change_order_access
        from services.change_order_service import get_change_order
        order = get_change_order(conn, normalized["change_order_id"])
        if not order:
            raise ValueError("关联变更单不存在")
        _require_change_order_access(order, user, "view")


def create_authorization_grant(
    conn,
    *,
    job_id: str,
    owner_id: str,
    tenant_id: str,
    manifest: dict[str, Any],
    approved_by_id: str = "",
) -> dict[str, Any]:
    grant_input = normalize_authorization_grant(manifest.get("authorization_grant"))
    ticket = validate_authorization_grant_ticket(conn, grant_input, tenant_id=tenant_id)
    latest = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS version "
        "FROM scheduled_job_authorization_grants WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    version = int(dict(latest).get("version") or 0) + 1 if latest else 1
    grant_id = str(uuid.uuid4())
    execution_hash = manifest_hash(manifest)
    grant_snapshot = grant_input
    conn.execute(
        """INSERT INTO scheduled_job_authorization_grants (
               grant_id, job_id, version, status, owner_id, tenant_id,
               template_version, manifest_hash, grant_json,
               valid_until, max_runs, used_runs, max_targets,
               ticket_source_type, ticket_id, ticket_number, ticket_title,
               change_order_id, change_order_number, created_by_id, approved_by_id
           ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?::jsonb,
                     ?::timestamptz, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            grant_id, job_id, version, owner_id, tenant_id,
            template_version_for_manifest(manifest), execution_hash,
            json.dumps(grant_snapshot, ensure_ascii=False, sort_keys=True), grant_input["valid_until"],
            grant_input["max_runs"], grant_input["max_targets"],
            grant_input["ticket_source_type"], grant_input["ticket_id"],
            ticket["ticket_number"], ticket["ticket_title"],
            grant_input["change_order_id"], ticket["change_order_number"],
            owner_id, approved_by_id,
        ),
    )
    conn.execute(
        """UPDATE scheduled_job_authorization_grants
              SET status = 'superseded'
            WHERE job_id = ? AND grant_id <> ? AND status = 'active'""",
        (job_id, grant_id),
    )
    return {
        "grant_id": grant_id,
        "version": version,
        "status": "active",
        "template_version": template_version_for_manifest(manifest),
        "manifest_hash": execution_hash,
        "valid_until": grant_input["valid_until"],
        "max_runs": grant_input["max_runs"],
        "used_runs": 0,
        "remaining_runs": grant_input["max_runs"],
        "max_targets": grant_input["max_targets"],
        "scope": grant_input["scope"],
        "ticket_source_type": grant_input["ticket_source_type"],
        "ticket_id": grant_input["ticket_id"],
        "ticket_number": ticket["ticket_number"],
        "ticket_title": ticket["ticket_title"],
        "change_order_id": grant_input["change_order_id"],
        "change_order_number": ticket["change_order_number"],
    }


def load_job_authorization_grant(conn, row: dict[str, Any]) -> dict[str, Any] | None:
    grant_id = _string(row.get("current_authorization_grant_id"))
    if not grant_id:
        return None
    grant_row = conn.execute(
        "SELECT * FROM scheduled_job_authorization_grants WHERE grant_id = ? AND job_id = ?",
        (grant_id, _string(row.get("id"))),
    ).fetchone()
    if not grant_row:
        return None
    grant = dict(grant_row)
    status = _string(grant.get("status"))
    valid_until = grant.get("valid_until")
    if status == "active" and valid_until is not None:
        parsed_until = valid_until
        if not isinstance(parsed_until, datetime):
            try:
                parsed_until = datetime.fromisoformat(_string(valid_until).replace("Z", "+00:00"))
            except ValueError:
                parsed_until = None
        if parsed_until is not None and parsed_until <= datetime.now(timezone.utc):
            status = "expired"
    used_runs = int(grant.get("used_runs") or 0)
    max_runs = int(grant.get("max_runs") or 0)
    if status == "active" and max_runs > 0 and used_runs >= max_runs:
        status = "exhausted"
    grant_json = _decode_json_object(grant.get("grant_json"))
    return {
        "grant_id": _string(grant.get("grant_id")),
        "version": int(grant.get("version") or 0),
        "status": status,
        "template_version": _string(grant.get("template_version")),
        "manifest_hash": _string(grant.get("manifest_hash")),
        "valid_until": _iso_timestamp(grant.get("valid_until")),
        "max_runs": max_runs,
        "used_runs": used_runs,
        "remaining_runs": max(0, max_runs - used_runs),
        "max_targets": int(grant.get("max_targets") or 0),
        "scope": grant_json.get("scope") or {},
        "ticket_source_type": _string(grant.get("ticket_source_type")),
        "ticket_id": _string(grant.get("ticket_id")),
        "ticket_number": _string(grant.get("ticket_number")),
        "ticket_title": _string(grant.get("ticket_title")),
        "change_order_id": _string(grant.get("change_order_id")),
        "change_order_number": _string(grant.get("change_order_number")),
    }


def current_authorization_grant_input(conn, row: dict[str, Any]) -> dict[str, Any] | None:
    grant_id = _string(row.get("current_authorization_grant_id"))
    if not grant_id:
        return None
    job_id = _string(row.get("id") or row.get("job_id"))
    grant_row = conn.execute(
        "SELECT grant_json FROM scheduled_job_authorization_grants WHERE grant_id = ? AND job_id = ?",
        (grant_id, job_id),
    ).fetchone()
    if not grant_row:
        return None
    parsed = _decode_json_object(grant_row["grant_json"])
    return normalize_authorization_grant(parsed) if parsed else None


def _iso_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(_string(value).replace("Z", "+00:00"))
        except ValueError:
            return _string(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _decode_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return []
        return list(parsed) if isinstance(parsed, list) else []
    return []


def script_snapshot(conn, script_id: str, *, require_released: bool = True) -> tuple[str, str]:
    """Return the SHA-256 and content for a currently released script."""
    script_id = _string(script_id)
    if not script_id:
        return "", ""
    row = conn.execute(
        "SELECT content, status, content_sha256 FROM scripts WHERE id = ?", (script_id,),
    ).fetchone()
    if not row:
        raise ValueError("选择的脚本不存在")
    script = dict(row)
    if require_released and str(script.get("status") or "").strip().lower() != "released":
        raise ValueError("计划作业只能使用已发布的脚本")
    content = str(script.get("content") or "")
    if not content:
        raise ValueError("已发布脚本内容为空")
    content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if require_released and (
        not str(script.get("content_sha256") or "")
        or str(script.get("content_sha256") or "") != content_sha256
    ):
        raise ValueError("已发布脚本内容摘要无效，必须重新审批")
    return content_sha256, content


def authorize_job_resource(user: dict[str, Any], row: dict[str, Any], action: str) -> None:
    """Enforce tenant and ownership checks before a job is read or changed."""
    if row.get("authorization_mode") == "system" and action != "view":
        raise PermissionError("Built-in system collection jobs cannot be changed through the user job API")
    tenant_id = _string(row.get("tenant_id"))
    actor_id = _string(user.get("user_id") or user.get("id"))
    owner_id = _string(row.get("created_by_id"))
    if TENANT_ISOLATION_ENABLED and not tenant_id and row.get("authorization_mode") != "system":
        raise PermissionError("计划作业未关联租户，必须重新授权")
    if not is_global_administrator(user):
        if TENANT_ISOLATION_ENABLED and tenant_scope_for_user(user) != tenant_id:
            raise PermissionError("计划作业不属于当前租户")
        if (
            row.get("authorization_mode") != "system"
            and user.get("role") != "Administrator"
            and owner_id != actor_id
        ):
            raise PermissionError("只有作业创建者或管理员可以访问此计划作业")
    if not authorize_resource(user, "scheduled_job", action, tenant_id=tenant_id or None):
        raise PermissionError("当前账号没有此计划作业的资源授权")


__all__ = [
    "authorize_job_resource", "job_manifest_source_from_row", "manifest_hash",
    "execution_snapshot", "merge_job_source", "normalize_job_manifest", "scheduled_job_approval_type",
    "script_snapshot", "normalize_authorization_grant", "template_version_for_manifest",
    "validate_authorization_grant_ticket", "create_authorization_grant", "load_job_authorization_grant",
    "current_authorization_grant_input",
    "assert_authorization_grant_link_access",
]
