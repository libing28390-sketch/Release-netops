"""Enterprise configuration search workspace API."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import json
import uuid
from typing import Any
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core.rbac import require_permission
from database import get_db_connection
from services.config_search_service import (
    SEARCH_SCOPES,
    SEARCH_TYPES,
    index_status,
    rebuild_index,
    search_configurations,
    search_suggestions,
)


router = APIRouter()


class ConfigSearchFilters(BaseModel):
    vendors: list[str] = Field(default_factory=list, max_length=50)
    platforms: list[str] = Field(default_factory=list, max_length=50)
    sites: list[str] = Field(default_factory=list, max_length=100)
    roles: list[str] = Field(default_factory=list, max_length=50)
    device_ids: list[str] = Field(default_factory=list, max_length=500)
    config_types: list[str] = Field(default_factory=list, max_length=10)
    integrity: list[str] = Field(default_factory=list, max_length=10)
    snapshot_ids: list[str] = Field(default_factory=list, max_length=500)
    from_time: str = Field(default="", max_length=64)
    to_time: str = Field(default="", max_length=64)


class ConfigSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=512)
    search_type: str = Field(default="AUTO", max_length=32)
    scope: str = Field(default="LATEST_VALID_RUNNING", max_length=40)
    filters: ConfigSearchFilters = Field(default_factory=ConfigSearchFilters)
    page: int = Field(default=1, ge=1, le=100_000)
    page_size: int = Field(default=20, ge=1, le=100)
    context_lines: int = Field(default=2, ge=0, le=8)
    include_sensitive: bool = False
    sensitive_confirmed: bool = False
    sensitive_reason: str = Field(default="", max_length=300)


class SearchComplianceRuleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1_000)
    query: str = Field(min_length=1, max_length=512)
    rule_type: Literal["require", "forbid"]
    search_type: str = Field(default="AUTO", max_length=32)
    scope: dict[str, Any] = Field(default_factory=dict)
    severity: Literal["critical", "high", "medium", "low"] = "medium"
    remediation: str = Field(default="", max_length=2_000)


class SavedSearchRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=512)
    search_type: str = Field(default="AUTO", max_length=32)
    scope: str = Field(default="LATEST_VALID_RUNNING", max_length=40)
    filters: ConfigSearchFilters = Field(default_factory=ConfigSearchFilters)
    is_favorite: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _validate_search_options(search_type: str, scope: str) -> tuple[str, str]:
    normalized_type = str(search_type or "AUTO").upper()
    normalized_scope = str(scope or "LATEST_VALID_RUNNING").upper()
    if normalized_type not in SEARCH_TYPES:
        raise HTTPException(status_code=422, detail="不支持的搜索类型")
    if normalized_scope not in SEARCH_SCOPES:
        raise HTTPException(status_code=422, detail="不支持的搜索作用域")
    return normalized_type, normalized_scope


@router.post("/configs/search/query")
def query_configurations(
    body: ConfigSearchRequest,
    user=require_permission("configuration", "read"),
):
    search_type, scope = _validate_search_options(body.search_type, body.scope)
    if search_type == "REGEX" and user.get("role") != "Administrator":
        raise HTTPException(status_code=403, detail="正则配置搜索仅管理员可用")
    include_sensitive = bool(
        body.include_sensitive
        and body.sensitive_confirmed
        and body.sensitive_reason.strip()
        and user.get("role") == "Administrator"
    )
    if body.include_sensitive and not include_sensitive:
        raise HTTPException(status_code=403, detail="查看敏感原文需要管理员权限、二次确认和查看原因")
    try:
        return search_configurations(
            query=body.query,
            requested_type=search_type,
            scope=scope,
            filters=body.filters.model_dump(),
            page=body.page,
            page_size=body.page_size,
            context_lines=body.context_lines,
            include_sensitive=include_sensitive,
            actor_username=str(user.get("username") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/configs/search/suggestions")
def get_config_search_suggestions(
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=12, ge=1, le=30),
    _user=require_permission("configuration", "read"),
):
    return {"items": search_suggestions(q, limit)}


@router.get("/configs/search/index/status")
def get_config_search_index_status(
    _user=require_permission("configuration", "read"),
):
    return index_status()


@router.post("/configs/search/index/rebuild")
def rebuild_config_search_index(
    limit: int = Query(default=500, ge=1, le=2_000),
    scope_type: Literal["all", "device", "platform", "parser_version"] = "all",
    scope_value: str = Query(default="", max_length=160),
    user=require_permission("configuration", "update"),
):
    job_id = str(uuid.uuid4())
    now = _now()
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO config_search_index_jobs (
                id, scope_type, scope_value, parser_version, status,
                requested_by, created_at, started_at
            ) VALUES (?, ?, ?, 'ncm-search-v1', 'running', ?, ?, ?)
            """,
            (job_id, scope_type, scope_value, user.get("username") or "", now, now),
        )
        conn.commit()
    finally:
        conn.close()
    try:
        result = rebuild_index(limit=limit, scope_type=scope_type, scope_value=scope_value)
        conn = get_db_connection()
        try:
            conn.execute(
                """
                UPDATE config_search_index_jobs
                SET status = 'completed', total_items = ?, completed_items = ?,
                    failed_items = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    result["indexed_snapshots"] + result["failed_snapshots"],
                    result["indexed_snapshots"],
                    result["failed_snapshots"],
                    _now(),
                    job_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return {"job_id": job_id, "status": "completed", **result}
    except Exception as exc:
        conn = get_db_connection()
        try:
            conn.execute(
                "UPDATE config_search_index_jobs SET status = 'failed', error_text = ?, completed_at = ? WHERE id = ?",
                (str(exc)[:2_000], _now(), job_id),
            )
            conn.commit()
        finally:
            conn.close()
        raise


@router.get("/configs/search/index/jobs")
def list_config_search_index_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    _user=require_permission("configuration", "update"),
):
    conn = get_db_connection()
    try:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM config_search_index_jobs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()]
    finally:
        conn.close()


@router.get("/configs/search/recent")
def list_recent_config_searches(
    limit: int = Query(default=20, ge=1, le=100),
    user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, query_text, search_type, search_scope, filters_json,
                   result_count, duration_ms, created_at
            FROM config_search_audit
            WHERE actor_username = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user.get("username") or "", limit),
        ).fetchall()
        return [
            {
                **dict(row),
                "filters": json.loads(row["filters_json"] or "{}"),
            }
            for row in rows
        ]
    finally:
        conn.close()


@router.delete("/configs/search/recent")
def clear_recent_config_searches(user=require_permission("configuration", "read")):
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM config_search_audit WHERE actor_username = ?",
            (user.get("username") or "",),
        )
        conn.commit()
        return {"success": True, "deleted": int(cursor.rowcount or 0)}
    finally:
        conn.close()


@router.get("/configs/search/devices/{device_id}/matches")
def get_device_config_matches(
    device_id: str,
    query: str = Query(min_length=1, max_length=512),
    search_type: str = Query(default="AUTO", max_length=32),
    scope: str = Query(default="HISTORY", max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user=require_permission("configuration", "read"),
):
    normalized_type, normalized_scope = _validate_search_options(search_type, scope)
    return search_configurations(
        query=query,
        requested_type=normalized_type,
        scope=normalized_scope,
        filters={"device_ids": [device_id]},
        page=page,
        page_size=page_size,
        context_lines=3,
        include_sensitive=False,
        actor_username=str(user.get("username") or ""),
    )


@router.get("/configs/search/associations")
def get_config_search_associations(
    device_id: str = Query(default="", max_length=120),
    address: str = Query(default="", max_length=128),
    _user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        ipam = []
        if address:
            ipam = [dict(row) for row in conn.execute(
                """
                SELECT ia.id, ia.address, ia.hostname, ia.device_id,
                       ia.interface_name, ia.status, ia.description,
                       p.prefix, p.name AS prefix_name, p.site_id
                FROM ip_addresses ia
                LEFT JOIN prefixes p ON p.id = ia.prefix_id
                WHERE ia.address = ? OR ia.ip_address = ?
                LIMIT 50
                """,
                (address, address),
            ).fetchall()]
        topology = []
        if device_id:
            topology = [dict(row) for row in conn.execute(
                """
                SELECT id, source_device_id, source_hostname, source_port,
                       target_device_id, target_hostname, target_port,
                       confidence, status, last_seen
                FROM topology_links
                WHERE source_device_id = ? OR target_device_id = ?
                ORDER BY confidence DESC, last_seen DESC
                LIMIT 100
                """,
                (device_id, device_id),
            ).fetchall()]
        return {"ipam": ipam, "topology": topology}
    finally:
        conn.close()


@router.post("/configs/search/compliance-rules")
def create_compliance_rule_from_search(
    body: SearchComplianceRuleRequest,
    user=require_permission("configuration", "update"),
):
    search_type, _scope_name = _validate_search_options(body.search_type, "LATEST_VALID_RUNNING")
    rule_id = str(uuid.uuid4())
    now = _now()
    pattern = body.query
    if search_type != "REGEX":
        import re

        pattern = re.escape(body.query)
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO config_compliance_rules (
                id, name, description, scope_json, rule_type, pattern,
                minimum_count, severity, remediation, enabled, created_by,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 1, ?, ?, ?)
            """,
            (
                rule_id, body.name, body.description,
                json.dumps(body.scope, ensure_ascii=False), body.rule_type,
                pattern, body.severity, body.remediation,
                user.get("username") or "", now, now,
            ),
        )
        conn.commit()
        return {"id": rule_id, "success": True, "rule_type": body.rule_type}
    finally:
        conn.close()


@router.get("/configs/search/saved")
def list_saved_config_searches(
    user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM saved_config_searches
            WHERE owner_username = ?
            ORDER BY is_favorite DESC, updated_at DESC
            """,
            (user.get("username") or "",),
        ).fetchall()
        return [
            {
                **dict(row),
                "filters": json.loads(row["filters_json"] or "{}"),
                "is_favorite": bool(row["is_favorite"]),
            }
            for row in rows
        ]
    finally:
        conn.close()


@router.post("/configs/search/saved")
def create_saved_config_search(
    body: SavedSearchRequest,
    user=require_permission("configuration", "read"),
):
    search_type, scope = _validate_search_options(body.search_type, body.scope)
    saved_id = str(uuid.uuid4())
    now = _now()
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO saved_config_searches (
                id, owner_username, name, query_text, search_type, search_scope,
                filters_json, is_favorite, created_at, updated_at, last_used_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
            """,
            (
                saved_id,
                user.get("username") or "",
                body.name,
                body.query,
                search_type,
                scope,
                json.dumps(body.filters.model_dump(), ensure_ascii=False),
                1 if body.is_favorite else 0,
                now,
                now,
            ),
        )
        conn.commit()
        return {"id": saved_id, "success": True}
    finally:
        conn.close()


@router.put("/configs/search/saved/{saved_id}")
def update_saved_config_search(
    saved_id: str,
    body: SavedSearchRequest,
    user=require_permission("configuration", "read"),
):
    search_type, scope = _validate_search_options(body.search_type, body.scope)
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE saved_config_searches
            SET name = ?, query_text = ?, search_type = ?, search_scope = ?,
                filters_json = ?, is_favorite = ?, updated_at = ?
            WHERE id = ? AND owner_username = ?
            """,
            (
                body.name,
                body.query,
                search_type,
                scope,
                json.dumps(body.filters.model_dump(), ensure_ascii=False),
                1 if body.is_favorite else 0,
                _now(),
                saved_id,
                user.get("username") or "",
            ),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="保存的搜索条件不存在")
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@router.delete("/configs/search/saved/{saved_id}")
def delete_saved_config_search(
    saved_id: str,
    user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM saved_config_searches WHERE id = ? AND owner_username = ?",
            (saved_id, user.get("username") or ""),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="保存的搜索条件不存在")
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@router.post("/configs/search/export")
def export_config_search(
    body: ConfigSearchRequest,
    format: Literal["csv", "xlsx", "json", "markdown"] = Query(default="csv"),
    user=require_permission("configuration", "export"),
):
    search_type, scope = _validate_search_options(body.search_type, body.scope)
    try:
        payload = search_configurations(
            query=body.query,
            requested_type=search_type,
            scope=scope,
            filters=body.filters.model_dump(),
            page=1,
            page_size=100,
            context_lines=body.context_lines,
            include_sensitive=False,
            actor_username=str(user.get("username") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if format == "json":
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        return Response(
            content=content,
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="config_search_{timestamp}.json"'},
        )
    if format == "markdown":
        lines = [
            "# 配置搜索结果",
            "",
            f"- 查询：`{body.query}`",
            f"- 类型：{payload['interpretation']['search_type']}",
            f"- 作用域：{payload['scope']}",
            f"- 命中设备：{payload['summary']['devices']}",
            f"- 命中行：{payload['summary']['matches']}",
            "",
        ]
        for result in payload["results"]:
            lines.extend(
                [
                    f"## {result['hostname']} ({result['ip_address']})",
                    "",
                    f"快照：{result['snapshot_time']}，命中 {result['total_matches']} 行。",
                    "",
                    "```text",
                ]
            )
            lines.extend(
                f"{match['line']:>6}  {match['content']}"
                for match in result["matches"]
            )
            lines.extend(["```", ""])
        return Response(
            content="\n".join(lines),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="config_search_{timestamp}.md"'},
        )

    if format == "xlsx":
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "配置搜索结果"
        headers = [
            "设备", "管理IP", "厂商", "平台", "站点", "配置版本",
            "备份时间", "对象类型", "对象名称", "匹配类型", "行号", "内容",
        ]
        sheet.append(headers)
        for result in payload["results"]:
            for match in result["matches"]:
                sheet.append([
                    result["hostname"], result["ip_address"], result["vendor"],
                    result["platform"], result["site"], result["snapshot_id"],
                    result["snapshot_time"], match["object_type"], match["object_key"],
                    match["match_reason"], match["line"], match["content"],
                ])
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(
                80, max(12, max(len(str(cell.value or "")) for cell in column) + 2)
            )
        binary = io.BytesIO()
        workbook.save(binary)
        return Response(
            content=binary.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="config_search_{timestamp}.xlsx"'},
        )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "hostname",
            "ip_address",
            "vendor",
            "platform",
            "site",
            "snapshot_time",
            "line",
            "object_type",
            "object_key",
            "match_reason",
            "content",
        ]
    )
    for result in payload["results"]:
        for match in result["matches"]:
            writer.writerow(
                [
                    result["hostname"],
                    result["ip_address"],
                    result["vendor"],
                    result["platform"],
                    result["site"],
                    result["snapshot_time"],
                    match["line"],
                    match["object_type"],
                    match["object_key"],
                    match["match_reason"],
                    match["content"],
                ]
            )
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="config_search_{timestamp}.csv"'},
    )
