"""FastAPI routes for the Prompt Center and immutable prompt revisions."""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from ai.schemas.prompt import (
    AIPromptAuditEventResponse,
    AIPromptAuditPageResponse,
    AIPromptCopyRequest,
    AIPromptCreate,
    AIPromptPageResponse,
    AIPromptResponse,
    AIPromptRestoreRequest,
    AIPromptUpdate,
    AIPromptVersionCompareResponse,
    AIPromptVersionResponse,
)
from ai.security.permissions import require_ai_permission
from database.core import get_db_connection
from services.audit_service import log_audit_event


router = APIRouter(prefix="/prompts", tags=["AI Prompt Center"])


def _validate_output_schema(output_schema: str | None) -> str:
    value = str(output_schema or "{}").strip() or "{}"
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="output_schema must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="output_schema must be a JSON object")
    return value


def _prompt_response(row) -> AIPromptResponse:
    return AIPromptResponse(
        id=row[0], code=row[1], name=row[2], scene=row[3], vendor=row[4], platform=row[5],
        system_prompt=row[6], user_prompt_template=row[7], output_schema=row[8],
        temperature=row[9], max_tokens=row[10], version=row[11], enabled=bool(row[12]),
        created_by=row[13], created_at=row[14], updated_at=row[15],
    )


def _version_response(row) -> AIPromptVersionResponse:
    return AIPromptVersionResponse(
        id=row[0], prompt_id=row[1], version=row[2], system_prompt=row[3],
        user_prompt_template=row[4], output_schema=row[5], temperature=row[6],
        max_tokens=row[7], created_by=row[8], created_at=row[9],
        change_reason=row[10] if len(row) > 10 else None,
        change_type=row[11] if len(row) > 11 else None,
        restored_from_version=row[12] if len(row) > 12 else None,
    )


def _prompt_select() -> str:
    return """
        SELECT id, code, name, scene, vendor, platform, system_prompt, user_prompt_template,
               output_schema, temperature, max_tokens, version, enabled, created_by, created_at, updated_at
        FROM ai_prompt
    """


def _version_select() -> str:
    return """
        SELECT id, prompt_id, version, system_prompt, user_prompt_template, output_schema,
               temperature, max_tokens, created_by, created_at,
               change_reason, change_type, restored_from_version
        FROM ai_prompt_version
    """


def _prompt_snapshot(row) -> dict[str, Any]:
    def digest(value: Any) -> str:
        return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()

    return {
        "id": str(row[0]),
        "code": str(row[1]),
        "name": str(row[2]),
        "scene": str(row[3]),
        "vendor": str(row[4] or "all"),
        "platform": str(row[5] or "all"),
        "version": int(row[11] or 1),
        "enabled": bool(row[12]),
        "content_sha256": {
            "system_prompt": digest(row[6]),
            "user_prompt_template": digest(row[7]),
            "output_schema": digest(row[8] or "{}"),
        },
        "content_lengths": {
            "system_prompt": len(str(row[6] or "")),
            "user_prompt_template": len(str(row[7] or "")),
            "output_schema": len(str(row[8] or "{}")),
        },
    }


def _write_prompt_audit(
    conn,
    user: dict[str, Any],
    *,
    operation: str,
    prompt_id: str,
    prompt_name: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    details: dict[str, Any],
) -> str:
    return log_audit_event(
        event_type=f"ai_prompt_{operation}",
        category="ai_prompt",
        severity="info",
        status="success",
        summary=f"AI prompt {operation}",
        actor_id=str(user.get("id") or user.get("user_id") or user.get("username") or "system"),
        actor_username=str(user.get("username") or user.get("id") or "system"),
        actor_role=str(user.get("role") or "system"),
        target_type="ai_prompt",
        target_id=prompt_id,
        target_name=prompt_name,
        before=before,
        after=after,
        details=details,
        conn=conn,
    )


def _filter_sql(search: str, scene: str, enabled: Optional[bool]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if search.strip():
        needle = f"%{search.strip().lower()}%"
        clauses.append(
            "(LOWER(code) LIKE ? OR LOWER(name) LIKE ? OR LOWER(scene) LIKE ? "
            "OR LOWER(COALESCE(vendor, '')) LIKE ? OR LOWER(COALESCE(platform, '')) LIKE ? "
            "OR LOWER(system_prompt) LIKE ? OR LOWER(user_prompt_template) LIKE ? "
            "OR LOWER(COALESCE(output_schema, '')) LIKE ?)"
        )
        params.extend([needle] * 8)
    if scene.strip():
        clauses.append("scene = ?")
        params.append(scene.strip())
    if enabled is not None:
        clauses.append("enabled = ?")
        params.append(int(enabled))
    return (f"WHERE {' AND '.join(clauses)}" if clauses else ""), params


@router.get("")
def list_prompts(
    search: str = Query(default="", max_length=256),
    scene: str = Query(default="", max_length=80),
    enabled: Optional[bool] = Query(default=None),
    page: Optional[int] = Query(default=None, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user=Depends(require_ai_permission("ai.view")),
):
    """Use the page envelope for the Prompt Center while keeping old readers compatible."""
    del user
    with get_db_connection() as conn:
        cursor = conn.cursor()
        where_sql, params = _filter_sql(search, scene, enabled)
        if page is None and not search.strip() and not scene.strip() and enabled is None:
            rows = cursor.execute(_prompt_select() + " ORDER BY created_at DESC, id DESC").fetchall()
            return [_prompt_response(row) for row in rows]

        total_row = cursor.execute(f"SELECT COUNT(*) FROM ai_prompt {where_sql}", tuple(params)).fetchone()
        total = int(total_row[0] if total_row else 0)
        total_pages = max(1, math.ceil(total / page_size))
        effective_page = min(page or 1, total_pages)
        rows = cursor.execute(
            _prompt_select() + f" {where_sql} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            tuple([*params, page_size, (effective_page - 1) * page_size]),
        ).fetchall()
        return AIPromptPageResponse(
            items=[_prompt_response(row) for row in rows],
            total=total,
            page=effective_page,
            page_size=page_size,
            total_pages=total_pages,
            filters={"search": search, "scene": scene, "enabled": enabled},
        )


@router.post("", response_model=AIPromptResponse, status_code=status.HTTP_201_CREATED)
def create_prompt(payload: AIPromptCreate, user=Depends(require_ai_permission("ai.prompt.manage"))):
    now_iso = datetime.now(timezone.utc).isoformat()
    prompt_id = f"prompt_{uuid.uuid4().hex[:12]}"
    username = user.get("username", "admin")
    output_schema = _validate_output_schema(payload.output_schema)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if cursor.execute("SELECT id FROM ai_prompt WHERE code = ?", (payload.code,)).fetchone():
            raise HTTPException(status_code=400, detail=f"Prompt code '{payload.code}' already exists.")
        cursor.execute(
            """
            INSERT INTO ai_prompt (
                id, code, name, scene, vendor, platform, system_prompt, user_prompt_template,
                output_schema, temperature, max_tokens, version, enabled, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (prompt_id, payload.code, payload.name, payload.scene, payload.vendor, payload.platform,
             payload.system_prompt, payload.user_prompt_template, output_schema, payload.temperature,
             payload.max_tokens, int(payload.enabled), username, now_iso, now_iso),
        )
        cursor.execute(
            """
            INSERT INTO ai_prompt_version (
                id, prompt_id, version, system_prompt, user_prompt_template, output_schema,
                temperature, max_tokens, created_by, created_at, change_reason, change_type
            ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'create')
            """,
            (f"pv_{uuid.uuid4().hex[:12]}", prompt_id, payload.system_prompt, payload.user_prompt_template,
             output_schema, payload.temperature, payload.max_tokens, username, now_iso, payload.change_reason),
        )
        created = cursor.execute(_prompt_select() + " WHERE id = ?", (prompt_id,)).fetchone()
        _write_prompt_audit(
            conn, user, operation="create", prompt_id=prompt_id, prompt_name=payload.name,
            before=None, after=_prompt_snapshot(created),
            details={"change_reason": payload.change_reason, "version": 1},
        )
        conn.commit()
    return _prompt_response(created)


@router.post("/{prompt_id}/copy", response_model=AIPromptResponse, status_code=status.HTTP_201_CREATED)
def copy_prompt(prompt_id: str, payload: AIPromptCopyRequest, user=Depends(require_ai_permission("ai.prompt.manage"))):
    now_iso = datetime.now(timezone.utc).isoformat()
    username = user.get("username", "admin")
    new_prompt_id = f"prompt_{uuid.uuid4().hex[:12]}"
    with get_db_connection() as conn:
        cursor = conn.cursor()
        source = cursor.execute(_prompt_select() + " WHERE id = ?", (prompt_id,)).fetchone()
        if not source:
            raise HTTPException(status_code=404, detail="Prompt not found")
        if cursor.execute("SELECT id FROM ai_prompt WHERE code = ?", (payload.code,)).fetchone():
            raise HTTPException(status_code=409, detail=f"Prompt code '{payload.code}' already exists.")
        new_name = (payload.name or f"{source[2]} (Copy)")[:160]
        cursor.execute(
            """
            INSERT INTO ai_prompt (
                id, code, name, scene, vendor, platform, system_prompt, user_prompt_template,
                output_schema, temperature, max_tokens, version, enabled, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (new_prompt_id, payload.code, new_name, source[3], source[4], source[5], source[6],
             source[7], source[8] or "{}", source[9], source[10], int(source[12]), username, now_iso, now_iso),
        )
        cursor.execute(
            """
            INSERT INTO ai_prompt_version (
                id, prompt_id, version, system_prompt, user_prompt_template, output_schema,
                temperature, max_tokens, created_by, created_at, change_reason, change_type
            ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'copy')
            """,
            (f"pv_{uuid.uuid4().hex[:12]}", new_prompt_id, source[6], source[7], source[8] or "{}",
             source[9], source[10], username, now_iso, payload.change_reason),
        )
        copied = cursor.execute(_prompt_select() + " WHERE id = ?", (new_prompt_id,)).fetchone()
        _write_prompt_audit(
            conn, user, operation="copy", prompt_id=new_prompt_id, prompt_name=new_name,
            before=_prompt_snapshot(source), after=_prompt_snapshot(copied),
            details={"change_reason": payload.change_reason, "source_prompt_id": prompt_id,
                     "source_version": int(source[11] or 1), "version": 1},
        )
        conn.commit()
    return _prompt_response(copied)


@router.put("/{prompt_id}", response_model=AIPromptResponse)
def update_prompt(prompt_id: str, payload: AIPromptUpdate, user=Depends(require_ai_permission("ai.prompt.manage"))):
    now_iso = datetime.now(timezone.utc).isoformat()
    username = user.get("username", "admin")
    updates = payload.model_dump(exclude_none=True)
    expected_version = updates.pop("expected_version", None)
    change_reason = str(updates.pop("change_reason", "")).strip() or "Prompt metadata updated"
    with get_db_connection() as conn:
        cursor = conn.cursor()
        current = cursor.execute(_prompt_select() + " WHERE id = ? FOR UPDATE", (prompt_id,)).fetchone()
        if not current:
            raise HTTPException(status_code=404, detail="Prompt not found")
        current_version = int(current[11] or 1)
        if expected_version is not None and int(expected_version) != current_version:
            raise HTTPException(
                status_code=409,
                detail={"code": "PROMPT_VERSION_CONFLICT", "message": "Prompt changed since it was loaded",
                        "current_version": current_version},
            )
        values: dict[str, Any] = {
            "name": current[2], "scene": current[3], "vendor": current[4], "platform": current[5],
            "system_prompt": current[6], "user_prompt_template": current[7], "output_schema": current[8] or "{}",
            "temperature": current[9], "max_tokens": current[10], "enabled": bool(current[12]),
        }
        values.update(updates)
        values["output_schema"] = _validate_output_schema(values["output_schema"])
        field_indexes = {
            "name": 2, "scene": 3, "vendor": 4, "platform": 5, "system_prompt": 6,
            "user_prompt_template": 7, "output_schema": 8, "temperature": 9, "max_tokens": 10, "enabled": 12,
        }
        changed_fields = [
            key for key, index in field_indexes.items()
            if values[key] != (bool(current[index]) if key == "enabled" else current[index])
        ]
        if not changed_fields:
            return _prompt_response(current)
        content_changed = bool({"system_prompt", "user_prompt_template", "output_schema", "temperature", "max_tokens"} & set(changed_fields))
        next_version = current_version + 1 if content_changed else current_version
        cursor.execute(
            """
            UPDATE ai_prompt SET name = ?, scene = ?, vendor = ?, platform = ?, system_prompt = ?,
                user_prompt_template = ?, output_schema = ?, temperature = ?, max_tokens = ?,
                version = ?, enabled = ?, updated_at = ? WHERE id = ?
            """,
            (values["name"], values["scene"], values["vendor"], values["platform"], values["system_prompt"],
             values["user_prompt_template"], values["output_schema"], values["temperature"], values["max_tokens"],
             next_version, int(values["enabled"]), now_iso, prompt_id),
        )
        if content_changed:
            cursor.execute(
                """
                INSERT INTO ai_prompt_version (
                    id, prompt_id, version, system_prompt, user_prompt_template, output_schema,
                    temperature, max_tokens, created_by, created_at, change_reason, change_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'update')
                """,
                (f"pv_{uuid.uuid4().hex[:12]}", prompt_id, next_version, values["system_prompt"],
                 values["user_prompt_template"], values["output_schema"], values["temperature"],
                 values["max_tokens"], username, now_iso, change_reason),
            )
        updated = cursor.execute(_prompt_select() + " WHERE id = ?", (prompt_id,)).fetchone()
        _write_prompt_audit(
            conn, user, operation="update", prompt_id=prompt_id, prompt_name=str(updated[2]),
            before=_prompt_snapshot(current), after=_prompt_snapshot(updated),
            details={"change_reason": change_reason, "changed_fields": changed_fields,
                     "content_changed": content_changed, "version_created": content_changed},
        )
        conn.commit()
    return _prompt_response(updated)


@router.get("/{prompt_id}/versions", response_model=list[AIPromptVersionResponse])
def list_prompt_versions(prompt_id: str, user=Depends(require_ai_permission("ai.view"))):
    del user
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if not cursor.execute("SELECT id FROM ai_prompt WHERE id = ?", (prompt_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Prompt not found")
        rows = cursor.execute(_version_select() + " WHERE prompt_id = ? ORDER BY version DESC", (prompt_id,)).fetchall()
    return [_version_response(row) for row in rows]


@router.get("/{prompt_id}/versions/compare", response_model=AIPromptVersionCompareResponse)
def compare_prompt_versions(
    prompt_id: str,
    left_version: int = Query(..., ge=1),
    right_version: int = Query(..., ge=1),
    user=Depends(require_ai_permission("ai.view")),
):
    del user
    with get_db_connection() as conn:
        rows = conn.execute(
            _version_select() + " WHERE prompt_id = ? AND version IN (?, ?)",
            (prompt_id, left_version, right_version),
        ).fetchall()
    by_version = {int(row[2]): row for row in rows}
    left_row, right_row = by_version.get(left_version), by_version.get(right_version)
    if not left_row or not right_row:
        raise HTTPException(status_code=404, detail="One or both prompt versions were not found")
    fields = ("system_prompt", "user_prompt_template", "output_schema", "temperature", "max_tokens")
    left_values = (left_row[3], left_row[4], left_row[5], left_row[6], left_row[7])
    right_values = (right_row[3], right_row[4], right_row[5], right_row[6], right_row[7])
    changed_fields = [field for field, left, right in zip(fields, left_values, right_values) if left != right]
    diff: dict[str, list[str]] = {}
    for field, left, right in zip(fields[:3], left_values[:3], right_values[:3]):
        if left != right:
            diff[field] = list(difflib.unified_diff(
                str(left or "").splitlines(), str(right or "").splitlines(),
                fromfile=f"v{left_version}", tofile=f"v{right_version}", lineterm="",
            ))[:600]
    return AIPromptVersionCompareResponse(
        prompt_id=prompt_id, left=_version_response(left_row), right=_version_response(right_row),
        changed_fields=changed_fields, diff=diff,
    )


@router.post("/{prompt_id}/versions/{version}/restore", response_model=AIPromptResponse)
def restore_prompt_version(
    prompt_id: str,
    version: int = Path(..., ge=1),
    payload: AIPromptRestoreRequest = ...,
    user=Depends(require_ai_permission("ai.prompt.manage")),
):
    now_iso = datetime.now(timezone.utc).isoformat()
    username = user.get("username", "admin")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        current = cursor.execute(_prompt_select() + " WHERE id = ? FOR UPDATE", (prompt_id,)).fetchone()
        if not current:
            raise HTTPException(status_code=404, detail="Prompt not found")
        current_version = int(current[11] or 1)
        if payload.expected_current_version is not None and payload.expected_current_version != current_version:
            raise HTTPException(
                status_code=409,
                detail={"code": "PROMPT_VERSION_CONFLICT", "message": "Prompt changed since it was loaded",
                        "current_version": current_version},
            )
        source = cursor.execute(_version_select() + " WHERE prompt_id = ? AND version = ?", (prompt_id, version)).fetchone()
        if not source:
            raise HTTPException(status_code=404, detail="Prompt version not found")
        if version == current_version:
            raise HTTPException(status_code=409, detail="The current version is already active")
        next_version = current_version + 1
        cursor.execute(
            """
            UPDATE ai_prompt SET system_prompt = ?, user_prompt_template = ?, output_schema = ?,
                temperature = ?, max_tokens = ?, version = ?, updated_at = ? WHERE id = ?
            """,
            (source[3], source[4], source[5], source[6], source[7], next_version, now_iso, prompt_id),
        )
        cursor.execute(
            """
            INSERT INTO ai_prompt_version (
                id, prompt_id, version, system_prompt, user_prompt_template, output_schema,
                temperature, max_tokens, created_by, created_at, change_reason, change_type,
                restored_from_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'restore', ?)
            """,
            (f"pv_{uuid.uuid4().hex[:12]}", prompt_id, next_version, source[3], source[4], source[5],
             source[6], source[7], username, now_iso, payload.change_reason, version),
        )
        restored = cursor.execute(_prompt_select() + " WHERE id = ?", (prompt_id,)).fetchone()
        _write_prompt_audit(
            conn, user, operation="restore", prompt_id=prompt_id, prompt_name=str(restored[2]),
            before=_prompt_snapshot(current), after=_prompt_snapshot(restored),
            details={"change_reason": payload.change_reason, "restored_from_version": version,
                     "version_created": next_version},
        )
        conn.commit()
    return _prompt_response(restored)


def _json_object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


@router.get("/{prompt_id}/audit", response_model=AIPromptAuditPageResponse)
def list_prompt_audit(
    prompt_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str = Query(default="", max_length=128),
    user=Depends(require_ai_permission("ai.view")),
):
    del user
    clauses = ["category = ?", "target_id = ?"]
    params: list[Any] = ["ai_prompt", prompt_id]
    if search.strip():
        needle = f"%{search.strip()}%"
        clauses.append("(event_type LIKE ? OR summary LIKE ? OR actor_username LIKE ?)")
        params.extend([needle, needle, needle])
    where_sql = "WHERE " + " AND ".join(clauses)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        total_row = cursor.execute(f"SELECT COUNT(*) FROM audit_events {where_sql}", tuple(params)).fetchone()
        total = int(total_row[0] if total_row else 0)
        total_pages = max(1, math.ceil(total / page_size))
        effective_page = min(page, total_pages)
        rows = cursor.execute(
            f"""
            SELECT id, event_type, category, severity, status, actor_username, actor_role,
                   target_type, target_id, target_name, summary, details_json,
                   before_json, after_json, created_at
            FROM audit_events {where_sql}
            ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?
            """,
            tuple([*params, page_size, (effective_page - 1) * page_size]),
        ).fetchall()
    return AIPromptAuditPageResponse(
        items=[
            AIPromptAuditEventResponse(
                id=row[0], event_type=row[1], category=row[2], severity=row[3], status=row[4],
                actor_username=row[5], actor_role=row[6], target_type=row[7], target_id=row[8],
                target_name=row[9], summary=row[10], details=_json_object(row[11]),
                before=_json_object(row[12]), after=_json_object(row[13]), created_at=row[14],
            )
            for row in rows
        ],
        total=total, page=effective_page, page_size=page_size, total_pages=total_pages,
    )
