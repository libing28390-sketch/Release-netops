"""Configuration-backup policy persistence and target resolution."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Iterable

from services import tag_service


DEFAULT_POLICY_ID = "backup-policy-default"
DEFAULT_SCOPE = {
    "site_ids": [],
    "roles": [],
    "platforms": [],
    "vendors": [],
    "device_ids": [],
    "exclude_device_ids": [],
    "tag_expression": None,
}


def _now() -> str:
    return datetime.now().isoformat()


def _json_object(value: object, fallback: dict) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or ""))
        return parsed if isinstance(parsed, dict) else dict(fallback)
    except (TypeError, ValueError, json.JSONDecodeError):
        return dict(fallback)


def _json_list(value: object, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value or ""))
        return [str(item) for item in parsed] if isinstance(parsed, list) else list(fallback)
    except (TypeError, ValueError, json.JSONDecodeError):
        return list(fallback)


def _normalize_values(values: Iterable[object]) -> list[str]:
    return list(dict.fromkeys(
        str(value).strip()
        for value in values
        if str(value).strip()
    ))


def normalize_scope(scope: dict | None) -> dict:
    raw = scope if isinstance(scope, dict) else {}
    normalized = {
        key: _normalize_values(raw.get(key) or [])
        for key in (
            "site_ids",
            "roles",
            "platforms",
            "vendors",
            "device_ids",
            "exclude_device_ids",
        )
    }
    normalized["tag_expression"] = (
        raw.get("tag_expression")
        if isinstance(raw.get("tag_expression"), dict)
        else None
    )
    return normalized


def _row_to_policy(row) -> dict:
    item = dict(row)
    item["enabled"] = bool(item.get("enabled"))
    item["change_only"] = bool(item.get("change_only"))
    item["scope"] = normalize_scope(_json_object(item.pop("scope_json", "{}"), DEFAULT_SCOPE))
    item["config_types"] = _json_list(item.pop("config_types_json", '["running"]'), ["running"])
    return item


def ensure_default_policy(conn) -> dict:
    row = conn.execute(
        "SELECT * FROM config_backup_policies WHERE id = ?",
        (DEFAULT_POLICY_ID,),
    ).fetchone()
    if row:
        return _row_to_policy(row)

    schedule = {"enabled": True, "cron": "0 2 * * *"}
    retention = {"max_days": 90, "max_per_device": 30}
    for key, target in (("backup_schedule", schedule), ("backup_retention", retention)):
        legacy = conn.execute("SELECT value FROM global_vars WHERE key = ?", (key,)).fetchone()
        if legacy:
            target.update(_json_object(legacy["value"], target))

    now = _now()
    conn.execute(
        """
        INSERT INTO config_backup_policies
        (id, name, description, enabled, cron_expr, timezone, priority,
         scope_json, config_types_json, change_only, retention_days,
         max_versions_per_device, concurrency, retry_count, timeout_seconds,
         created_by, updated_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            DEFAULT_POLICY_ID,
            "默认全网备份",
            "由原全局备份计划自动迁移，可继续通过兼容设置维护。",
            1 if schedule.get("enabled", True) else 0,
            str(schedule.get("cron") or "0 2 * * *"),
            "Asia/Shanghai",
            100,
            json.dumps(DEFAULT_SCOPE, ensure_ascii=False),
            '["running"]',
            1,
            int(retention.get("max_days") or 90),
            int(retention.get("max_per_device") or 30),
            10,
            1,
            30,
            "system",
            "system",
            now,
            now,
        ),
    )
    conn.commit()
    return get_policy(conn, DEFAULT_POLICY_ID) or {}


def list_policies(conn, *, search: str = "", page: int = 1, page_size: int = 20) -> dict:
    ensure_default_policy(conn)
    clauses: list[str] = []
    params: list[object] = []
    if search.strip():
        clauses.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ?)")
        term = f"%{search.strip().lower()}%"
        params.extend([term, term])
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    total = conn.execute(
        f"SELECT COUNT(*) AS c FROM config_backup_policies{where}",
        tuple(params),
    ).fetchone()["c"]
    offset = (page - 1) * page_size
    rows = conn.execute(
        f"""
        SELECT * FROM config_backup_policies{where}
        ORDER BY priority, name
        LIMIT ? OFFSET ?
        """,
        tuple([*params, page_size, offset]),
    ).fetchall()
    return {
        "items": [_row_to_policy(row) for row in rows],
        "total": int(total or 0),
        "page": page,
        "page_size": page_size,
    }


def get_policy(conn, policy_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM config_backup_policies WHERE id = ?",
        (policy_id,),
    ).fetchone()
    return _row_to_policy(row) if row else None


def list_enabled_policies(conn) -> list[dict]:
    ensure_default_policy(conn)
    rows = conn.execute(
        """
        SELECT * FROM config_backup_policies
        WHERE enabled = 1
        ORDER BY priority, name
        """
    ).fetchall()
    return [_row_to_policy(row) for row in rows]


def create_policy(conn, payload: dict, *, actor: str) -> dict:
    policy_id = f"backup-policy-{uuid.uuid4().hex[:16]}"
    now = _now()
    scope = normalize_scope(payload.get("scope"))
    conn.execute(
        """
        INSERT INTO config_backup_policies
        (id, name, description, enabled, cron_expr, timezone, priority,
         scope_json, config_types_json, change_only, retention_days,
         max_versions_per_device, concurrency, retry_count, timeout_seconds,
         created_by, updated_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            policy_id,
            payload["name"].strip(),
            payload.get("description", "").strip(),
            1 if payload.get("enabled", True) else 0,
            payload.get("cron_expr", "0 2 * * *").strip(),
            payload.get("timezone", "Asia/Shanghai").strip(),
            int(payload.get("priority", 100)),
            json.dumps(scope, ensure_ascii=False),
            json.dumps(payload.get("config_types") or ["running"], ensure_ascii=False),
            1 if payload.get("change_only", True) else 0,
            int(payload.get("retention_days", 90)),
            int(payload.get("max_versions_per_device", 30)),
            int(payload.get("concurrency", 10)),
            int(payload.get("retry_count", 1)),
            int(payload.get("timeout_seconds", 30)),
            actor,
            actor,
            now,
            now,
        ),
    )
    conn.commit()
    return get_policy(conn, policy_id) or {}


def update_policy(conn, policy_id: str, payload: dict, *, actor: str) -> dict | None:
    existing = get_policy(conn, policy_id)
    if not existing:
        return None
    merged = {**existing, **payload}
    scope = normalize_scope(merged.get("scope"))
    conn.execute(
        """
        UPDATE config_backup_policies
        SET name = ?, description = ?, enabled = ?, cron_expr = ?, timezone = ?,
            priority = ?, scope_json = ?, config_types_json = ?, change_only = ?,
            retention_days = ?, max_versions_per_device = ?, concurrency = ?,
            retry_count = ?, timeout_seconds = ?, updated_by = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            str(merged["name"]).strip(),
            str(merged.get("description") or "").strip(),
            1 if merged.get("enabled", True) else 0,
            str(merged.get("cron_expr") or "0 2 * * *").strip(),
            str(merged.get("timezone") or "Asia/Shanghai").strip(),
            int(merged.get("priority", 100)),
            json.dumps(scope, ensure_ascii=False),
            json.dumps(merged.get("config_types") or ["running"], ensure_ascii=False),
            1 if merged.get("change_only", True) else 0,
            int(merged.get("retention_days", 90)),
            int(merged.get("max_versions_per_device", 30)),
            int(merged.get("concurrency", 10)),
            int(merged.get("retry_count", 1)),
            int(merged.get("timeout_seconds", 30)),
            actor,
            _now(),
            policy_id,
        ),
    )
    conn.commit()
    return get_policy(conn, policy_id)


def delete_policy(conn, policy_id: str) -> bool:
    if policy_id == DEFAULT_POLICY_ID:
        raise ValueError("默认备份策略不能删除，可以停用")
    cursor = conn.execute(
        "DELETE FROM config_backup_policies WHERE id = ?",
        (policy_id,),
    )
    conn.commit()
    return bool(getattr(cursor, "rowcount", 0))


def sync_default_policy_from_legacy(conn, *, enabled: bool, cron_expr: str) -> dict:
    ensure_default_policy(conn)
    return update_policy(
        conn,
        DEFAULT_POLICY_ID,
        {"enabled": enabled, "cron_expr": cron_expr},
        actor="system",
    ) or {}


def _expression_has_terms(group: object, depth: int = 0) -> bool:
    if depth > 16 or not isinstance(group, dict):
        return False
    if any(str(tag_id).strip() for tag_id in (group.get("tag_ids") or [])):
        return True
    return any(_expression_has_terms(child, depth + 1) for child in (group.get("groups") or []))


def _device_vendor(device: dict) -> str:
    explicit = str(device.get("vendor") or "").strip()
    if explicit:
        return explicit.lower()
    platform = str(device.get("platform") or "").lower()
    aliases = (
        (("cisco",), "cisco"),
        (("huawei", "vrp"), "huawei"),
        (("h3c", "comware"), "h3c"),
        (("juniper", "junos"), "juniper"),
        (("arista", "eos"), "arista"),
        (("ruijie", "rgos"), "ruijie"),
        (("zte", "zxros"), "zte"),
        (("maipu",), "maipu"),
    )
    for markers, vendor in aliases:
        if any(marker in platform for marker in markers):
            return vendor
    return ""


def filter_devices_by_scope(conn, devices: Iterable[object], scope: dict | None) -> list[dict]:
    normalized = normalize_scope(scope)
    include_ids = set(normalized["device_ids"])
    exclude_ids = set(normalized["exclude_device_ids"])
    site_values = {value.lower() for value in normalized["site_ids"]}
    roles = {value.lower() for value in normalized["roles"]}
    platforms = {value.lower() for value in normalized["platforms"]}
    vendors = {value.lower() for value in normalized["vendors"]}
    tag_expression = normalized.get("tag_expression")
    tag_ids: set[str] | None = None
    if _expression_has_terms(tag_expression):
        tag_ids = set(tag_service.resolve_device_ids_by_expression(conn, tag_expression))

    result: list[dict] = []
    for raw in devices:
        device = dict(raw)
        device_id = str(device.get("id") or "")
        if not device_id or device_id in exclude_ids:
            continue
        if include_ids and device_id not in include_ids:
            continue
        if site_values:
            candidates = {
                str(device.get("site_id") or "").lower(),
                str(device.get("site") or "").lower(),
            }
            if not candidates.intersection(site_values):
                continue
        if roles and str(device.get("role") or "").lower() not in roles:
            continue
        if platforms and str(device.get("platform") or "").lower() not in platforms:
            continue
        if vendors and _device_vendor(device) not in vendors:
            continue
        if tag_ids is not None and device_id not in tag_ids:
            continue
        if int(device.get("config_backup_enabled") if device.get("config_backup_enabled") is not None else 1) == 0:
            continue
        result.append(device)
    return result


def preview_policy(
    conn,
    policy: dict,
    *,
    search: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    rows = conn.execute(
        """
        SELECT id, hostname, ip_address, platform, vendor, role, site, site_id,
               status, config_backup_enabled
        FROM devices
        ORDER BY hostname, ip_address
        """
    ).fetchall()
    matched = filter_devices_by_scope(conn, rows, policy.get("scope"))
    if search.strip():
        term = search.strip().lower()
        matched = [
            device for device in matched
            if term in str(device.get("hostname") or "").lower()
            or term in str(device.get("ip_address") or "").lower()
            or term in str(device.get("platform") or "").lower()
        ]
    total = len(matched)
    offset = (page - 1) * page_size
    items = matched[offset:offset + page_size]
    return {
        "items": items,
        "total": total,
        "online": sum(1 for item in matched if str(item.get("status") or "").lower() == "online"),
        "offline": sum(1 for item in matched if str(item.get("status") or "").lower() != "online"),
        "page": page,
        "page_size": page_size,
    }
