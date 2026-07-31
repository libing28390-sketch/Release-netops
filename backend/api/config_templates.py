"""Configuration template center API.

This router complements the legacy ``/templates`` CRUD contract with a
versioned, schema-driven workspace contract.  It never connects to devices or
executes commands; creating a task produces a reviewable draft only.
"""

from __future__ import annotations

from datetime import datetime, timezone
import difflib
import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core.rbac import require_permission
from database import get_db_connection
from services.config_template_center_service import (
    checksum,
    infer_variable_schema,
    json_value,
    redact_output,
    redact_parameter_values,
    render_template_center,
    template_quality_score,
    validate_parameters,
)


router = APIRouter()


class ParameterValidationRequest(BaseModel):
    version: str = Field(default="", max_length=40)
    parameters: dict[str, Any] = Field(default_factory=dict)


class RenderOptions(BaseModel):
    strict: bool = True
    trim_blank_lines: bool = True
    include_source_map: bool = True


class TemplateRenderRequest(ParameterValidationRequest):
    parameter_profile_id: str = Field(default="", max_length=100)
    options: RenderOptions = Field(default_factory=RenderOptions)
    device_ids: list[str] = Field(default_factory=list, max_length=100)


class ParameterProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1_000)
    version: str = Field(default="", max_length=40)
    values: dict[str, Any] = Field(default_factory=dict)
    value_sources: dict[str, str] = Field(default_factory=dict)
    scope: Literal["private", "team", "global", "official_example"] = "private"
    is_default: bool = False


class TemplateVersionRequest(BaseModel):
    version: str = Field(min_length=1, max_length=40)
    source: str = Field(min_length=1, max_length=200_000)
    rollback_source: str = Field(default="", max_length=200_000)
    variable_schema: list[dict[str, Any]] = Field(default_factory=list)
    example_values: dict[str, Any] = Field(default_factory=dict)
    render_options: dict[str, Any] = Field(default_factory=dict)
    change_summary: str = Field(default="", max_length=2_000)
    status: Literal["draft", "review", "published", "archived"] = "draft"


class TemplateImportRequest(BaseModel):
    template: dict[str, Any]
    version: dict[str, Any] = Field(default_factory=dict)
    expected_checksum: str = Field(default="", max_length=128)


class TaskDraftRequest(TemplateRenderRequest):
    template_id: str = Field(min_length=1, max_length=120)


class VendorComparisonRequest(BaseModel):
    template_ids: list[str] = Field(min_length=2, max_length=5)
    parameters: dict[str, Any] = Field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _template_row(conn, template_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="配置模板不存在")
    return dict(row)


def _version_row(conn, template: dict[str, Any], version: str = "") -> dict[str, Any]:
    selected_version = version or str(template.get("current_version") or "1.0")
    row = conn.execute(
        """
        SELECT * FROM config_template_versions
        WHERE template_id = ? AND version = ?
        """,
        (template["id"], selected_version),
    ).fetchone()
    if row:
        return dict(row)
    return {
        "id": "",
        "template_id": template["id"],
        "version": selected_version,
        "source": template.get("content") or "",
        "rollback_source": template.get("rollback") or "",
        "variable_schema_json": template.get("variable_schema_json") or "[]",
        "example_values_json": template.get("example_values_json") or "{}",
        "render_options_json": "{}",
        "change_summary": "",
        "checksum": checksum(template.get("content") or ""),
        "status": template.get("status") or "draft",
        "created_by": template.get("created_by") or "",
        "created_at": template.get("created_at") or "",
        "published_at": "",
    }


def _schema_for(template: dict[str, Any], version: dict[str, Any]) -> list[dict[str, Any]]:
    schema = json_value(version.get("variable_schema_json"), [])
    if not schema:
        schema = json_value(template.get("variable_schema_json"), [])
    return schema or infer_variable_schema(version.get("source") or template.get("content") or "")


def _serialize_template(
    conn,
    template: dict[str, Any],
    *,
    username: str = "",
    include_detail: bool = False,
    version_name: str = "",
) -> dict[str, Any]:
    version = _version_row(conn, template, version_name)
    schema = _schema_for(template, version)
    quality = template_quality_score(template, schema)
    favorite = False
    if username:
        favorite = conn.execute(
            "SELECT 1 FROM config_template_favorites WHERE template_id = ? AND username = ?",
            (template["id"], username),
        ).fetchone() is not None
    payload = {
        **template,
        "lastUsed": template.get("last_used"),
        "variable_count": len(schema),
        "current_version": version.get("version") or "1.0",
        "source_type": template.get("source_type") or ("official" if template.get("is_official") else "custom"),
        "is_official": bool(template.get("is_official")),
        "is_favorite": favorite,
        "quality": quality,
        "quality_score": quality["score"],
        "tags": json_value(template.get("tags_json"), []),
    }
    if include_detail:
        versions = conn.execute(
            """
            SELECT id, version, change_summary, checksum, status, created_by,
                   created_at, published_at
            FROM config_template_versions
            WHERE template_id = ?
            ORDER BY created_at DESC
            """,
            (template["id"],),
        ).fetchall()
        compatibility = conn.execute(
            "SELECT * FROM config_template_compatibility WHERE template_id = ? ORDER BY vendor, platform",
            (template["id"],),
        ).fetchall()
        payload.update(
            {
                "version": {
                    **version,
                    "variable_schema": schema,
                    "example_values": json_value(version.get("example_values_json"), {}),
                    "render_options": json_value(version.get("render_options_json"), {}),
                },
                "variable_schema": schema,
                "example_values": json_value(version.get("example_values_json"), {}),
                "versions": [dict(row) for row in versions] or [
                    {
                        "id": "",
                        "version": version["version"],
                        "change_summary": "兼容旧模板资产",
                        "checksum": version["checksum"],
                        "status": version["status"],
                        "created_by": version["created_by"],
                        "created_at": version["created_at"],
                        "published_at": version["published_at"],
                    }
                ],
                "compatibility": [
                    {
                        **dict(row),
                        "required_capabilities": json_value(row["required_capabilities_json"], []),
                        "excluded_versions": json_value(row["excluded_versions_json"], []),
                    }
                    for row in compatibility
                ],
            }
        )
    return payload


@router.get("/config-templates")
def list_config_templates(
    keyword: str = Query(default="", max_length=200),
    vendor: str = Query(default="", max_length=80),
    platform: str = Query(default="", max_length=120),
    category: str = Query(default="", max_length=80),
    source_type: str = Query(default="", max_length=40),
    status: str = Query(default="", max_length=40),
    risk_level: str = Query(default="", max_length=40),
    sort: Literal["name", "updated", "usage", "quality"] = "updated",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user=require_permission("configuration", "read"),
):
    clauses = ["1 = 1"]
    params: list[Any] = []
    if keyword:
        clauses.append(
            """
            (
                LOWER(COALESCE(name, '')) LIKE ?
                OR LOWER(COALESCE(description, '')) LIKE ?
                OR LOWER(COALESCE(vendor, '')) LIKE ?
                OR LOWER(COALESCE(platform_family, '')) LIKE ?
                OR LOWER(COALESCE(category, '')) LIKE ?
                OR LOWER(COALESCE(code, '')) LIKE ?
                OR LOWER(COALESCE(content, '')) LIKE ?
                OR LOWER(COALESCE(tags_json, '')) LIKE ?
            )
            """
        )
        term = f"%{keyword.lower()}%"
        params.extend([term] * 8)
    for value, column in (
        (vendor, "vendor"),
        (platform, "platform_family"),
        (category, "category"),
        (source_type, "source_type"),
        (status, "status"),
        (risk_level, "risk_level"),
    ):
        if value:
            clauses.append(f"LOWER(COALESCE({column}, '')) = ?")
            params.append(value.lower())

    order_by = {
        "name": "name ASC",
        "updated": "updated_at DESC, name ASC",
        "usage": "use_count DESC, name ASC",
        "quality": "quality_score DESC, name ASC",
    }[sort]
    conn = get_db_connection()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS count FROM templates WHERE {' AND '.join(clauses)}",
            tuple(params),
        ).fetchone()["count"]
        rows = conn.execute(
            f"""
            SELECT * FROM templates
            WHERE {' AND '.join(clauses)}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
            """,
            (*params, page_size, (page - 1) * page_size),
        ).fetchall()
        items = [
            _serialize_template(conn, dict(row), username=str(user.get("username") or ""))
            for row in rows
        ]
        return {
            "items": items,
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (int(total or 0) + page_size - 1) // page_size),
        }
    finally:
        conn.close()


@router.get("/config-templates/{template_id}")
def get_config_template(
    template_id: str,
    version: str = Query(default="", max_length=40),
    user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        template = _template_row(conn, template_id)
        return _serialize_template(
            conn,
            template,
            username=str(user.get("username") or ""),
            include_detail=True,
            version_name=version,
        )
    finally:
        conn.close()


@router.post("/config-templates/{template_id}/validate-parameters")
def validate_config_template_parameters(
    template_id: str,
    body: ParameterValidationRequest,
    _user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        template = _template_row(conn, template_id)
        version = _version_row(conn, template, body.version)
        return validate_parameters(
            _schema_for(template, version),
            body.parameters,
            vendor=template.get("vendor") or "",
            platform=template.get("platform_family") or "",
        )
    finally:
        conn.close()


def _render_for_template(
    conn,
    template: dict[str, Any],
    body: TemplateRenderRequest,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    version = _version_row(conn, template, body.version)
    schema = _schema_for(template, version)
    result = render_template_center(
        content=version.get("source") or "",
        rollback=version.get("rollback_source") or "",
        schema=schema,
        values=body.parameters,
        vendor=template.get("vendor") or "",
        platform=template.get("platform_family") or "",
        software_version=template.get("software_version") or "",
        options=body.options.model_dump(),
    )
    return result, version, schema


@router.post("/config-templates/{template_id}/render")
def render_config_template(
    template_id: str,
    body: TemplateRenderRequest,
    user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        template = _template_row(conn, template_id)
        result, version, schema = _render_for_template(conn, template, body)
        actor = str(user.get("username") or "")
        now = _now()
        conn.execute(
            """
            INSERT INTO config_template_render_history (
                id, template_id, template_version, parameter_profile_id,
                parameters_json, rendered_output, render_status,
                validation_result_json, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                template_id,
                version.get("version") or "1.0",
                body.parameter_profile_id,
                json.dumps(redact_parameter_values(schema, body.parameters), ensure_ascii=False),
                redact_output(result.get("rendered_output") or ""),
                result["render_status"],
                json.dumps(
                    {
                        "warnings": result.get("warnings", []),
                        "errors": result.get("errors", []),
                        "risk_level": result.get("risk_level", "none"),
                    },
                    ensure_ascii=False,
                ),
                actor,
                now,
            ),
        )
        quality = template_quality_score(template, schema)["score"]
        conn.execute(
            """
            UPDATE templates
            SET last_used = ?, use_count = COALESCE(use_count, 0) + 1,
                quality_score = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, quality, now, template_id),
        )
        conn.commit()
        return {
            **result,
            "template_id": template_id,
            "template_version": version.get("version") or "1.0",
            "quality_score": quality,
        }
    finally:
        conn.close()


@router.post("/config-templates/{template_id}/render-per-device")
def render_config_template_per_device(
    template_id: str,
    body: TemplateRenderRequest,
    user=require_permission("configuration", "read"),
):
    if not body.device_ids:
        raise HTTPException(status_code=422, detail="至少选择一台设备")
    conn = get_db_connection()
    try:
        template = _template_row(conn, template_id)
        rows = conn.execute(
            f"""
            SELECT id, hostname, ip_address, vendor, platform, model, version, role, site
            FROM devices
            WHERE id IN ({','.join('?' for _ in body.device_ids)})
            ORDER BY hostname
            """,
            tuple(body.device_ids),
        ).fetchall()
        results = []
        for row in rows:
            device = dict(row)
            merged = {
                **body.parameters,
                "device": device,
                "device.hostname": device.get("hostname") or "",
                "device.ip_address": device.get("ip_address") or "",
                "device.model": device.get("model") or "",
                "device.version": device.get("version") or "",
            }
            per_device_body = body.model_copy(update={"parameters": merged, "device_ids": []})
            result, version, _schema = _render_for_template(conn, template, per_device_body)
            results.append(
                {
                    "device_id": device["id"],
                    "hostname": device["hostname"],
                    "success": result["success"],
                    "render_status": result["render_status"],
                    "rendered_output": result["rendered_output"],
                    "warnings": result["warnings"],
                    "errors": result["errors"],
                    "template_version": version.get("version") or "1.0",
                }
            )
        success_count = sum(1 for result in results if result["success"])
        return {
            "items": results,
            "total": len(results),
            "success_count": success_count,
            "failed_count": len(results) - success_count,
        }
    finally:
        conn.close()


@router.get("/config-templates/{template_id}/parameter-profiles")
def list_parameter_profiles(
    template_id: str,
    user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        _template_row(conn, template_id)
        rows = conn.execute(
            """
            SELECT * FROM config_template_parameter_profiles
            WHERE template_id = ?
              AND (scope IN ('global', 'official_example')
                   OR created_by = ?)
            ORDER BY is_default DESC, updated_at DESC
            """,
            (template_id, user.get("username") or ""),
        ).fetchall()
        return [
            {
                **dict(row),
                "values": json_value(row["values_json"], {}),
                "value_sources": json_value(row["value_sources_json"], {}),
                "is_default": bool(row["is_default"]),
            }
            for row in rows
        ]
    finally:
        conn.close()


@router.post("/config-templates/{template_id}/parameter-profiles")
def create_parameter_profile(
    template_id: str,
    body: ParameterProfileRequest,
    user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        template = _template_row(conn, template_id)
        version = _version_row(conn, template, body.version)
        schema = _schema_for(template, version)
        validation = validate_parameters(
            schema,
            body.values,
            vendor=template.get("vendor") or "",
            platform=template.get("platform_family") or "",
        )
        if not validation["valid"]:
            raise HTTPException(status_code=422, detail=validation["errors"])
        if body.scope in {"team", "global", "official_example"} and user.get("role") == "Viewer":
            raise HTTPException(status_code=403, detail="无权创建共享参数方案")
        profile_id = str(uuid.uuid4())
        now = _now()
        if body.is_default:
            conn.execute(
                "UPDATE config_template_parameter_profiles SET is_default = 0 WHERE template_id = ? AND created_by = ?",
                (template_id, user.get("username") or ""),
            )
        conn.execute(
            """
            INSERT INTO config_template_parameter_profiles (
                id, template_id, template_version, name, description, values_json,
                value_sources_json, scope, is_default, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                template_id,
                version.get("version") or "1.0",
                body.name,
                body.description,
                json.dumps(redact_parameter_values(schema, validation["normalized_values"]), ensure_ascii=False),
                json.dumps(body.value_sources, ensure_ascii=False),
                body.scope,
                1 if body.is_default else 0,
                user.get("username") or "",
                now,
                now,
            ),
        )
        conn.commit()
        return {"id": profile_id, "success": True, "compatibility": "compatible"}
    finally:
        conn.close()


@router.put("/config-templates/{template_id}/parameter-profiles/{profile_id}")
def update_parameter_profile(
    template_id: str,
    profile_id: str,
    body: ParameterProfileRequest,
    user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        template = _template_row(conn, template_id)
        version = _version_row(conn, template, body.version)
        schema = _schema_for(template, version)
        validation = validate_parameters(schema, body.values, vendor=template.get("vendor") or "", platform=template.get("platform_family") or "")
        if not validation["valid"]:
            raise HTTPException(status_code=422, detail=validation["errors"])
        if body.is_default:
            conn.execute(
                "UPDATE config_template_parameter_profiles SET is_default = 0 WHERE template_id = ? AND created_by = ?",
                (template_id, user.get("username") or ""),
            )
        cursor = conn.execute(
            """
            UPDATE config_template_parameter_profiles
            SET template_version = ?, name = ?, description = ?, values_json = ?,
                value_sources_json = ?, scope = ?, is_default = ?, updated_at = ?
            WHERE id = ? AND template_id = ? AND created_by = ?
            """,
            (
                version.get("version") or "1.0",
                body.name,
                body.description,
                json.dumps(redact_parameter_values(schema, validation["normalized_values"]), ensure_ascii=False),
                json.dumps(body.value_sources, ensure_ascii=False),
                body.scope,
                1 if body.is_default else 0,
                _now(),
                profile_id,
                template_id,
                user.get("username") or "",
            ),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="参数方案不存在或无权修改")
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@router.delete("/config-templates/{template_id}/parameter-profiles/{profile_id}")
def delete_parameter_profile(
    template_id: str,
    profile_id: str,
    user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            """
            DELETE FROM config_template_parameter_profiles
            WHERE id = ? AND template_id = ? AND created_by = ?
            """,
            (profile_id, template_id, user.get("username") or ""),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="参数方案不存在或无权删除")
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@router.post("/config-templates/{template_id}/versions")
def create_template_version(
    template_id: str,
    body: TemplateVersionRequest,
    user=require_permission("configuration", "update"),
):
    conn = get_db_connection()
    try:
        template = _template_row(conn, template_id)
        schema = body.variable_schema or infer_variable_schema(body.source)
        now = _now()
        version_id = str(uuid.uuid4())
        try:
            conn.execute(
                """
                INSERT INTO config_template_versions (
                    id, template_id, version, source, rollback_source,
                    variable_schema_json, example_values_json, render_options_json,
                    change_summary, checksum, status, created_by, created_at, published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    template_id,
                    body.version,
                    body.source,
                    body.rollback_source,
                    json.dumps(schema, ensure_ascii=False),
                    json.dumps(body.example_values, ensure_ascii=False),
                    json.dumps(body.render_options, ensure_ascii=False),
                    body.change_summary,
                    checksum(body.source),
                    body.status,
                    user.get("username") or "",
                    now,
                    now if body.status == "published" else "",
                ),
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail=f"模板版本已存在或数据无效: {exc}") from exc
        if body.status == "published":
            conn.execute(
                """
                UPDATE templates
                SET current_version = ?, content = ?, rollback = ?,
                    variable_schema_json = ?, example_values_json = ?,
                    status = 'published', updated_at = ?
                WHERE id = ?
                """,
                (
                    body.version,
                    body.source,
                    body.rollback_source,
                    json.dumps(schema, ensure_ascii=False),
                    json.dumps(body.example_values, ensure_ascii=False),
                    now,
                    template_id,
                ),
            )
        else:
            conn.execute("UPDATE templates SET updated_at = ? WHERE id = ?", (now, template_id))
        conn.commit()
        return {"id": version_id, "success": True, "template_name": template.get("name")}
    finally:
        conn.close()


@router.get("/config-templates/{template_id}/versions/diff")
def diff_template_versions(
    template_id: str,
    from_version: str = Query(min_length=1, max_length=40),
    to_version: str = Query(min_length=1, max_length=40),
    _user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        template = _template_row(conn, template_id)
        left = _version_row(conn, template, from_version)
        right = _version_row(conn, template, to_version)
        if left["version"] == right["version"]:
            return {"from_version": from_version, "to_version": to_version, "diff": [], "summary": {"added": 0, "removed": 0}}
        diff = list(
            difflib.unified_diff(
                str(left.get("source") or "").splitlines(),
                str(right.get("source") or "").splitlines(),
                fromfile=from_version,
                tofile=to_version,
                lineterm="",
            )
        )
        return {
            "from_version": from_version,
            "to_version": to_version,
            "diff": diff,
            "summary": {
                "added": sum(1 for line in diff if line.startswith("+") and not line.startswith("+++")),
                "removed": sum(1 for line in diff if line.startswith("-") and not line.startswith("---")),
            },
        }
    finally:
        conn.close()


@router.get("/config-templates/{template_id}/render-history")
def list_template_render_history(
    template_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, template_version, parameter_profile_id, render_status,
                   validation_result_json, created_by, created_at
            FROM config_template_render_history
            WHERE template_id = ?
              AND (created_by = ? OR ? = 'Administrator')
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (template_id, user.get("username") or "", user.get("role") or "", limit),
        ).fetchall()
        return [
            {
                **dict(row),
                "validation_result": json_value(row["validation_result_json"], {}),
            }
            for row in rows
        ]
    finally:
        conn.close()


@router.put("/config-templates/{template_id}/favorite")
def toggle_template_favorite(
    template_id: str,
    favorite: bool = Query(default=True),
    user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        _template_row(conn, template_id)
        username = str(user.get("username") or "")
        exists = conn.execute(
            "SELECT 1 FROM config_template_favorites WHERE template_id = ? AND username = ?",
            (template_id, username),
        ).fetchone()
        if favorite and not exists:
            conn.execute(
                "INSERT INTO config_template_favorites (template_id, username, created_at) VALUES (?, ?, ?)",
                (template_id, username, _now()),
            )
        elif not favorite and exists:
            conn.execute(
                "DELETE FROM config_template_favorites WHERE template_id = ? AND username = ?",
                (template_id, username),
            )
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM config_template_favorites WHERE template_id = ?",
            (template_id,),
        ).fetchone()["count"]
        conn.execute("UPDATE templates SET favorite_count = ? WHERE id = ?", (count, template_id))
        conn.commit()
        return {"success": True, "favorite": favorite, "favorite_count": int(count or 0)}
    finally:
        conn.close()


@router.post("/config-templates/{template_id}/copy")
def copy_config_template(
    template_id: str,
    user=require_permission("configuration", "create"),
):
    conn = get_db_connection()
    try:
        source = _template_row(conn, template_id)
        new_id = str(uuid.uuid4())
        now = _now()
        conn.execute(
            """
            INSERT INTO templates (
                id, name, type, category, vendor, content, rollback, last_used,
                description, platform_family, software_version, official_reference,
                validation_status, code, source_type, risk_level, status,
                current_version, is_official, created_by, created_at, updated_at,
                variable_schema_json, example_values_json, usage_notes, risk_notes,
                tags_json, favorite_count, use_count, quality_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id,
                f"{source.get('name') or 'Template'} - 副本",
                source.get("type") or "Jinja2",
                "custom",
                source.get("vendor") or "",
                source.get("content") or "",
                source.get("rollback") or "",
                None,
                source.get("description") or "",
                source.get("platform_family") or "",
                source.get("software_version") or "",
                "",
                "draft",
                f"{source.get('code') or template_id}-copy-{new_id[:8]}",
                "custom",
                source.get("risk_level") or "low",
                "draft",
                "1.0",
                0,
                user.get("username") or "",
                now,
                now,
                source.get("variable_schema_json") or "[]",
                source.get("example_values_json") or "{}",
                source.get("usage_notes") or "",
                source.get("risk_notes") or "",
                source.get("tags_json") or "[]",
                0,
                0,
                0,
            ),
        )
        conn.commit()
        return {"id": new_id, "success": True}
    finally:
        conn.close()


@router.get("/config-templates/{template_id}/export")
def export_config_template(
    template_id: str,
    _user=require_permission("configuration", "export"),
):
    conn = get_db_connection()
    try:
        template = _template_row(conn, template_id)
        payload = _serialize_template(conn, template, include_detail=True)
        content = json.dumps(
            {
                "format": "nexora-config-template",
                "format_version": 1,
                "exported_at": _now(),
                "template": payload,
                "checksum": checksum(payload["version"]["source"]),
            },
            ensure_ascii=False,
            indent=2,
        )
        return Response(
            content=content,
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="template-{template_id}.json"'},
        )
    finally:
        conn.close()


@router.post("/config-templates/import")
def import_config_template(
    body: TemplateImportRequest,
    user=require_permission("configuration", "create"),
):
    source = str(body.version.get("source") or body.template.get("content") or "")
    if not source.strip():
        raise HTTPException(status_code=422, detail="导入文件缺少模板源码")
    actual_checksum = checksum(source)
    if body.expected_checksum and body.expected_checksum != actual_checksum:
        raise HTTPException(status_code=422, detail="导入文件校验和不匹配")
    if body.template.get("is_official") and user.get("role") != "Administrator":
        raise HTTPException(status_code=403, detail="非管理员不能导入为官方模板")

    template_id = str(uuid.uuid4())
    schema = body.version.get("variable_schema") or infer_variable_schema(source)
    now = _now()
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO templates (
                id, name, type, category, vendor, content, rollback, last_used,
                description, platform_family, software_version, official_reference,
                validation_status, code, source_type, risk_level, status,
                current_version, is_official, created_by, created_at, updated_at,
                variable_schema_json, example_values_json, usage_notes, risk_notes,
                tags_json, favorite_count, use_count, quality_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                template_id,
                body.template.get("name") or "导入模板",
                body.template.get("type") or "Jinja2",
                "custom",
                body.template.get("vendor") or "",
                source,
                body.version.get("rollback_source") or body.template.get("rollback") or "",
                None,
                body.template.get("description") or "",
                body.template.get("platform_family") or "",
                body.template.get("software_version") or "",
                body.template.get("official_reference") if user.get("role") == "Administrator" else "",
                "draft",
                body.template.get("code") or f"import-{template_id[:8]}",
                "custom",
                body.template.get("risk_level") or "low",
                "draft",
                "1.0",
                0,
                user.get("username") or "",
                now,
                now,
                json.dumps(schema, ensure_ascii=False),
                json.dumps(body.version.get("example_values") or {}, ensure_ascii=False),
                body.template.get("usage_notes") or "",
                body.template.get("risk_notes") or "",
                json.dumps(body.template.get("tags") or [], ensure_ascii=False),
                0,
                0,
                0,
            ),
        )
        conn.commit()
        return {"id": template_id, "success": True, "checksum": actual_checksum}
    finally:
        conn.close()


@router.post("/config-templates/render-comparison")
def compare_vendor_templates(
    body: VendorComparisonRequest,
    _user=require_permission("configuration", "read"),
):
    conn = get_db_connection()
    try:
        items = []
        for template_id in body.template_ids:
            template = _template_row(conn, template_id)
            render_body = TemplateRenderRequest(parameters=body.parameters)
            result, version, _schema = _render_for_template(conn, template, render_body)
            items.append(
                {
                    "template_id": template_id,
                    "name": template.get("name"),
                    "vendor": template.get("vendor"),
                    "platform": template.get("platform_family"),
                    "version": version.get("version"),
                    **result,
                }
            )
        return {"items": items}
    finally:
        conn.close()


@router.post("/automation/tasks/from-template")
def create_automation_task_from_template(
    body: TaskDraftRequest,
    user=require_permission("job", "create"),
):
    conn = get_db_connection()
    try:
        template = _template_row(conn, body.template_id)
        result, version, schema = _render_for_template(conn, template, body)
        if not result["success"]:
            raise HTTPException(status_code=422, detail={
                "message": "模板渲染或参数校验未通过，不能创建任务草稿",
                "errors": result.get("errors", []),
            })
        draft_id = str(uuid.uuid4())
        now = _now()
        conn.execute(
            """
            INSERT INTO config_template_task_drafts (
                id, template_id, template_version, parameter_profile_id,
                parameters_json, rendered_output, render_summary_json,
                risk_level, validation_result_json, status, created_by,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)
            """,
            (
                draft_id,
                body.template_id,
                version.get("version") or "1.0",
                body.parameter_profile_id,
                json.dumps(redact_parameter_values(schema, body.parameters), ensure_ascii=False),
                redact_output(result["rendered_output"]),
                json.dumps(
                    {
                        "line_count": result["line_count"],
                        "command_count": result["command_count"],
                        "used_variables": result["used_variables"],
                        "defaulted_variables": result["defaulted_variables"],
                    },
                    ensure_ascii=False,
                ),
                result.get("risk_level") or "none",
                json.dumps(
                    {
                        "warnings": result.get("warnings", []),
                        "errors": result.get("errors", []),
                        "risk_items": result.get("risk_items", []),
                    },
                    ensure_ascii=False,
                ),
                user.get("username") or "",
                now,
                now,
            ),
        )
        conn.commit()
        return {
            "id": draft_id,
            "status": "draft",
            "success": True,
            "redirect_path": f"/automation/tasks?template_draft={draft_id}",
            "message": "任务草稿已创建；尚未选择设备、审批或执行。",
        }
    finally:
        conn.close()

