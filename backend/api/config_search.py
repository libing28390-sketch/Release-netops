"""Enterprise configuration search workspace API."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import json
import uuid
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
    # Raw secrets are never returned through the general search workspace.
    include_sensitive = body.include_sensitive and user.get("role") == "Administrator"
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
    _user=require_permission("configuration", "update"),
):
    return rebuild_index(limit=limit)


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
    format: Literal["csv", "json", "markdown"] = Query(default="csv"),
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

