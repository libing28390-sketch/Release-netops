"""Shared authorization and immutable approval manifests for scheduled jobs."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core.rbac import authorize_resource, is_global_administrator
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


def _check_items(source: dict[str, Any], commands: str, action: str) -> list[str]:
    raw = source.get("check_items")
    if isinstance(raw, list):
        items = [str(item).strip() for item in raw if str(item).strip()]
        if items:
            return items
    if action == "inspection" and commands:
        import re
        return [item.strip() for item in re.split(r"[,\n]", commands) if item.strip()]
    return []


def job_manifest_source_from_row(row: dict[str, Any], operation: str) -> dict[str, Any]:
    """Convert a database row to the public, stable manifest shape."""
    action = _string(row.get("action_type"))
    commands = _string(row.get("commands"))
    return {
        "operation": operation,
        "job_id": _string(row.get("id")),
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
    return {
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


def scheduled_job_approval_type(manifest: dict[str, Any]) -> str:
    if manifest.get("operation") == "DELETE" and manifest.get("job_type") != "once":
        return "scheduled_job_delete"
    return "execution_plan" if manifest.get("job_type") == "once" else "scheduled_job"


def manifest_hash(manifest: dict[str, Any]) -> str:
    return approval_manifest_hash(manifest)


def execution_snapshot(conn, row: dict[str, Any]) -> dict[str, Any]:
    source = job_manifest_source_from_row(row, "EXECUTION")
    script_sha, _ = script_snapshot(conn, source.get("script_id", ""))
    return normalize_job_manifest(
        source,
        operation="EXECUTION",
        requester_id=_string(row.get("created_by_id")),
        tenant_id=_string(row.get("tenant_id")),
        script_sha256=script_sha,
        job_id=_string(row.get("id")),
    )


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
    if not tenant_id and row.get("authorization_mode") != "system":
        raise PermissionError("计划作业未关联租户，必须重新授权")
    if not is_global_administrator(user):
        if _string(user.get("tenant_id")) != tenant_id:
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
    "script_snapshot",
]
