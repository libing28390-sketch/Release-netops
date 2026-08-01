from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field
import logging
import os
import uuid
import json
import threading
import time
from datetime import datetime, timezone
from urllib.request import urlopen
from urllib.error import URLError
from database import get_db_connection
from services.audit_service import log_audit_event
from services.config_template_validation_service import validate_template
from services.config_template_center_service import (
    checksum,
    json_value,
    normalize_template_definition,
    template_quality_score,
)
from services.config_vendor_platform_service import validate_vendor_platform
from core.config import settings
from core.rbac import require_permission

router = APIRouter()
logger = logging.getLogger(__name__)

_TEMPLATES_CACHE_TTL_SECONDS = max(
    0.0, float(os.environ.get('TEMPLATES_CACHE_TTL_SECONDS', '2'))
)
_templates_cache_lock = threading.Lock()
_templates_cache: tuple[float, list[dict]] | None = None


def _read_local_templates() -> list[dict]:
    conn = get_db_connection()
    try:
        templates = conn.execute(
            'SELECT id, name, type, category, vendor, content, rollback, description, '
            'platform_family, software_version, official_reference, validation_status, '
            'last_used as lastUsed, code, source_type, risk_level, status, '
            'current_version, is_official, created_by, created_at, updated_at, '
            'variable_schema_json, example_values_json, usage_notes, risk_notes, '
            'tags_json, favorite_count, use_count, quality_score FROM templates '
            "WHERE COALESCE(status, 'draft') <> 'archived'"
        ).fetchall()
        return [dict(template) for template in templates]
    finally:
        conn.close()


def _read_local_templates_cached() -> list[dict]:
    """Serve the read-heavy template list without opening a DB connection per request."""
    global _templates_cache
    if _TEMPLATES_CACHE_TTL_SECONDS <= 0:
        return _read_local_templates()

    now = time.monotonic()
    with _templates_cache_lock:
        if _templates_cache and now - _templates_cache[0] < _TEMPLATES_CACHE_TTL_SECONDS:
            return [dict(template) for template in _templates_cache[1]]
        templates = _read_local_templates()
        _templates_cache = (time.monotonic(), templates)
        return [dict(template) for template in templates]


def _invalidate_templates_cache() -> None:
    global _templates_cache
    with _templates_cache_lock:
        _templates_cache = None


def _supports_template_center_columns(conn) -> bool:
    """Allow legacy deployments to keep working before m0054 is applied."""
    try:
        conn.execute("SELECT variable_schema_json, source_type, status FROM templates LIMIT 0")
        return True
    except Exception:
        return False


def _definition_payload(template: dict, *, existing: dict | None = None) -> dict:
    """Normalize a custom template into the shared template-center model."""
    content = str(template.get("content") or "")
    schema, examples = normalize_template_definition(
        content,
        variable_schema=template.get("variable_schema"),
        example_values=template.get("example_values"),
    )
    metadata = dict(existing or {})
    metadata.update(template)
    metadata["content"] = content
    metadata["variable_schema_json"] = json.dumps(schema, ensure_ascii=False)
    metadata["example_values_json"] = json.dumps(examples, ensure_ascii=False)
    metadata["usage_notes"] = str(template.get("usage_notes", metadata.get("usage_notes", "")) or "")
    metadata["risk_notes"] = str(template.get("risk_notes", metadata.get("risk_notes", "")) or "")
    tags = template.get("tags", template.get("tags_json", metadata.get("tags_json", [])))
    if isinstance(tags, str):
        tags = json_value(tags, [])
    metadata["tags_json"] = json.dumps(tags if isinstance(tags, list) else [], ensure_ascii=False)
    metadata["schema"] = schema
    metadata["examples"] = examples
    return metadata


def _upsert_template_version(conn, template: dict, *, actor: str, now: str) -> None:
    """Keep the legacy CRUD endpoint in sync with the versioned center."""
    version = str(template.get("current_version") or "1.0")
    values = (
        template["content"],
        str(template.get("rollback") or ""),
        template["variable_schema_json"],
        template["example_values_json"],
        template.get("risk_level") or "low",
        checksum(template["content"]),
        template.get("status") or "draft",
        actor,
        now,
        template["id"],
        version,
    )
    existing = conn.execute(
        "SELECT id FROM config_template_versions WHERE template_id = ? AND version = ?",
        (template["id"], version),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE config_template_versions
            SET source = ?, rollback_source = ?, variable_schema_json = ?,
                example_values_json = ?, change_summary = ?, checksum = ?,
                status = ?, created_by = ?, created_at = ?
            WHERE template_id = ? AND version = ?
            """,
            (*values[:4], "Updated custom template definition", *values[5:]),
        )
    else:
        conn.execute(
            """
            INSERT INTO config_template_versions (
                id, template_id, version, source, rollback_source,
                variable_schema_json, example_values_json, render_options_json,
                change_summary, checksum, status, created_by, created_at, published_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()), template["id"], version, template["content"],
                str(template.get("rollback") or ""), template["variable_schema_json"],
                template["example_values_json"], "{}", "Custom template definition",
                checksum(template["content"]), template.get("status") or "draft",
                actor, now, "",
            ),
        )


class TemplateValidationRequest(BaseModel):
    content: str = Field(max_length=200_000)
    variables: dict = Field(default_factory=dict)
    vendor: str = Field(default="", max_length=80)
    platform: str = Field(default="", max_length=120)
    software_version: str = Field(default="", max_length=120)
    rollback: str = Field(default="", max_length=200_000)


@router.post("/templates/validate")
def validate_configuration_template(payload: TemplateValidationRequest):
    """Parse and render a template in a Jinja sandbox without touching devices."""
    return {
        "success": True,
        "data": validate_template(
            payload.content,
            variables=payload.variables,
            vendor=payload.vendor,
            platform=payload.platform,
            software_version=payload.software_version,
            rollback=payload.rollback,
        ),
    }

@router.get("/templates")
def read_templates():
    """Read templates from an explicitly configured API or the local DB.

    Local deployments must not perform an implicit network call. The previous
    hard-coded private address made every request wait for the five-second
    socket timeout before falling back to PostgreSQL.
    """
    external_url = settings.CONFIG_MANAGEMENT_URL.strip()
    if not external_url:
        return _read_local_templates_cached()

    timeout = max(0.1, float(settings.CONFIG_MANAGEMENT_TIMEOUT_SECONDS))
    try:
        with urlopen(external_url, timeout=timeout) as response:
            if response.status == 200:
                templates = json.loads(response.read().decode('utf-8'))
                if isinstance(templates, list):
                    return templates
                if isinstance(templates, dict) and 'data' in templates:
                    return templates.get('data', [])
                return templates
            logger.warning(
                "External configuration API returned HTTP %s; using local templates",
                response.status,
            )
    except (URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        logger.warning(
            "External configuration API unavailable; using local templates: %s",
            exc,
        )

    return _read_local_templates_cached()

@router.post("/templates")
def create_template(template: dict = Body(...)):
    try:
        normalized_vendor, normalized_platform = validate_vendor_platform(
            template.get("vendor") or "",
            template.get("platform_family") or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    definition = _definition_payload(template)
    validation = validate_template(
        definition["content"],
        variables=definition["examples"],
        vendor=normalized_vendor,
        platform=normalized_platform,
        rollback=template.get("rollback") or "",
    )
    if not validation["syntax_valid"]:
        raise HTTPException(status_code=422, detail=validation["issues"])
    conn = get_db_connection()
    template_id = template.get('id') or str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    try:
        definition["id"] = template_id
        definition["risk_level"] = validation.get("risk_level") or "low"
        definition["status"] = "draft"
        definition["current_version"] = "1.0"
        definition["is_official"] = 0
        definition["source_type"] = "custom"
        definition["created_by"] = template.get("actor_username") or "admin"
        definition["created_at"] = now
        definition["updated_at"] = now
        definition["quality_score"] = template_quality_score(definition, definition["schema"])["score"]
        if _supports_template_center_columns(conn):
            conn.execute('''
                INSERT INTO templates
                (id, name, type, category, vendor, content, rollback, last_used,
                 description, platform_family, software_version, official_reference,
                 validation_status, code, source_type, risk_level, status,
                 current_version, is_official, created_by, created_at, updated_at,
                 variable_schema_json, example_values_json, usage_notes, risk_notes,
                 tags_json, favorite_count, use_count, quality_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                template_id, template.get('name'), template.get('type') or 'Jinja2',
                template.get('category', 'custom'), normalized_vendor, definition['content'],
                template.get('rollback') or '', template.get('lastUsed'), template.get('description', ''),
                normalized_platform, template.get('software_version', ''), '', 'draft',
                template.get('code') or f"custom-{template_id[:8]}", definition['source_type'],
                definition['risk_level'], definition['status'], definition['current_version'],
                definition['is_official'], definition['created_by'], definition['created_at'],
                definition['updated_at'], definition['variable_schema_json'], definition['example_values_json'],
                definition['usage_notes'], definition['risk_notes'], definition['tags_json'], 0, 0,
                definition['quality_score'],
            ))
            _upsert_template_version(conn, definition, actor=definition['created_by'], now=now)
        else:
            conn.execute('''
                INSERT INTO templates
                (id, name, type, category, vendor, content, rollback, last_used,
                 description, platform_family, software_version, official_reference,
                 validation_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                template_id, template.get('name'), template.get('type') or 'Jinja2',
                template.get('category', 'custom'), normalized_vendor, definition['content'],
                template.get('rollback') or '', template.get('lastUsed'), template.get('description', ''),
                normalized_platform, template.get('software_version', ''), '', 'draft',
            ))
        conn.commit()
        _invalidate_templates_cache()
        log_audit_event(
            event_type='TEMPLATE_CREATE',
            category='configuration',
            severity='medium',
            status='success',
            summary=f"Created template {template.get('name')}",
            actor_username=template.get('actor_username') or 'admin',
            actor_role=template.get('actor_role') or 'Administrator',
            target_type='template',
            target_id=template_id,
            target_name=template.get('name'),
            details={'vendor': template.get('vendor'), 'type': template.get('type')},
        )
        return {"success": True, "id": template_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.put("/templates/{template_id}")
def update_template(template_id: str, template: dict = Body(...)):
    try:
        normalized_vendor, normalized_platform = validate_vendor_platform(
            template.get("vendor") or "",
            template.get("platform_family") or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conn = get_db_connection()
    try:
        existing_row = conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
        if not existing_row:
            raise HTTPException(status_code=404, detail="Template not found")
        existing = dict(existing_row)
        if bool(existing.get("is_official")) or existing.get("source_type") == "official":
            raise HTTPException(status_code=403, detail="Official templates are read-only; copy it before editing")
        definition = _definition_payload(template, existing=existing)
    except HTTPException:
        conn.close()
        raise
    except Exception:
        conn.close()
        raise
    validation = validate_template(
        definition["content"],
        variables=definition["examples"],
        vendor=normalized_vendor,
        platform=normalized_platform,
        rollback=template.get("rollback") or "",
    )
    if not validation["syntax_valid"]:
        conn.close()
        raise HTTPException(status_code=422, detail=validation["issues"])
    try:
        reviewed_fields = (
            'name', 'type', 'category', 'vendor', 'content', 'rollback',
            'description', 'platform_family', 'software_version',
        )
        reviewed_content_changed = any(
            str(template.get(field, existing.get(field, '')) or '') != str(existing.get(field) or '')
            for field in reviewed_fields
        )
        validation_status = str(existing.get('validation_status') or 'draft')
        official_reference = str(existing.get('official_reference') or '')
        if reviewed_content_changed:
            validation_status = 'draft'
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        definition["id"] = template_id
        definition["risk_level"] = validation.get("risk_level") or existing.get("risk_level") or "low"
        definition["status"] = "draft" if reviewed_content_changed else (existing.get("status") or "draft")
        definition["current_version"] = existing.get("current_version") or "1.0"
        definition["variable_schema_json"] = definition["variable_schema_json"]
        definition["example_values_json"] = definition["example_values_json"]
        definition["quality_score"] = template_quality_score({**existing, **definition, "validation_status": validation_status}, definition["schema"])["score"]

        if _supports_template_center_columns(conn):
            conn.execute('''
                UPDATE templates
                SET name = ?, type = ?, category = ?, vendor = ?, content = ?,
                    rollback = ?, last_used = ?, description = ?, platform_family = ?,
                    software_version = ?, official_reference = ?, validation_status = ?,
                    code = ?, source_type = 'custom', risk_level = ?, status = ?,
                    current_version = ?, updated_at = ?, variable_schema_json = ?,
                    example_values_json = ?, usage_notes = ?, risk_notes = ?,
                    tags_json = ?, quality_score = ?
                WHERE id = ?
            ''', (
            template.get('name', existing.get('name')),
            template.get('type', existing.get('type') or 'Jinja2'),
            template.get('category', 'custom'),
            normalized_vendor,
            definition['content'],
            template.get('rollback', existing.get('rollback') or ''),
            template.get('lastUsed', existing.get('last_used')),
            template.get('description', existing.get('description') or ''),
            normalized_platform,
            template.get('software_version', existing.get('software_version') or ''),
            official_reference,
            validation_status,
            existing.get('code') or f"custom-{template_id[:8]}",
            definition['risk_level'],
            definition['status'],
            definition['current_version'],
            now,
            definition['variable_schema_json'],
            definition['example_values_json'],
            definition['usage_notes'],
            definition['risk_notes'],
            definition['tags_json'],
            definition['quality_score'],
                template_id,
            ))
        else:
            conn.execute('''
                UPDATE templates
                SET name = ?, type = ?, category = ?, vendor = ?, content = ?,
                    rollback = ?, last_used = ?, description = ?, platform_family = ?,
                    software_version = ?, official_reference = ?, validation_status = ?
                WHERE id = ?
            ''', (
                template.get('name', existing.get('name')),
                template.get('type', existing.get('type') or 'Jinja2'),
                template.get('category', existing.get('category') or 'custom'),
                normalized_vendor, definition['content'],
                template.get('rollback', existing.get('rollback') or ''),
                template.get('lastUsed', existing.get('last_used')),
                template.get('description', existing.get('description') or ''),
                normalized_platform,
                template.get('software_version', existing.get('software_version') or ''),
                official_reference, validation_status, template_id,
            ))
        definition.update({
            "name": template.get('name', existing.get('name')),
            "type": template.get('type', existing.get('type') or 'Jinja2'),
            "rollback": template.get('rollback', existing.get('rollback') or ''),
            "status": definition['status'],
        })
        if _supports_template_center_columns(conn):
            _upsert_template_version(conn, definition, actor=template.get('actor_username') or existing.get('created_by') or 'admin', now=now)
        conn.commit()
        _invalidate_templates_cache()
        log_audit_event(
            event_type='TEMPLATE_UPDATE',
            category='configuration',
            severity='medium',
            status='success',
            summary=f"Updated template {template.get('name')}",
            actor_username=template.get('actor_username') or 'admin',
            actor_role=template.get('actor_role') or 'Administrator',
            target_type='template',
            target_id=template_id,
            target_name=template.get('name'),
            details={'type': template.get('type'), 'vendor': template.get('vendor')},
        )
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.delete("/templates/{template_id}")
def delete_template(template_id: str, user=require_permission("configuration", "update")):
    """Archive a custom template; official templates must be copied first."""
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Template not found")
        template = dict(row)
        if bool(template.get("is_official")) or template.get("source_type") == "official":
            raise HTTPException(status_code=403, detail="Official templates are read-only; archive a custom copy instead")
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        conn.execute(
            "UPDATE templates SET status = 'archived', updated_at = ?, validation_status = 'draft' WHERE id = ?",
            (now, template_id),
        )
        conn.commit()
        _invalidate_templates_cache()
        log_audit_event(
            event_type='TEMPLATE_DELETE',
            category='configuration',
            severity='medium',
            status='success',
            summary=f"Archived custom template {template.get('name') or template_id}",
            actor_username=user.get('username') or 'admin',
            actor_role=user.get('role') or 'Operator',
            target_type='template',
            target_id=template_id,
            target_name=template.get('name') or template_id,
            details={'mode': 'soft_delete', 'status': 'archived'},
        )
        return {"success": True, "archived": True, "id": template_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        conn.close()

@router.get("/vars")
def read_global_vars():
    conn = get_db_connection()
    try:
        vars = conn.execute('SELECT * FROM global_vars').fetchall()
        return [dict(v) for v in vars]
    finally:
        conn.close()

@router.post("/vars")
def create_global_var(var: dict = Body(...)):
    conn = get_db_connection()
    var_id = str(uuid.uuid4())
    try:
        conn.execute('INSERT INTO global_vars (id, key, value) VALUES (?, ?, ?)', (var_id, var.get('key'), var.get('value')))
        conn.commit()
        log_audit_event(
            event_type='GLOBAL_VAR_CREATE',
            category='configuration',
            severity='low',
            status='success',
            summary=f"Created global variable {var.get('key')}",
            actor_username=var.get('actor_username') or 'admin',
            actor_role=var.get('actor_role') or 'Administrator',
            target_type='global_var',
            target_id=var_id,
            target_name=var.get('key'),
        )
        return {"id": var_id, "key": var.get('key'), "value": var.get('value')}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.put("/vars/{var_id}")
def update_global_var(var_id: str, var: dict = Body(...)):
    conn = get_db_connection()
    try:
        conn.execute('UPDATE global_vars SET key = ?, value = ? WHERE id = ?', (var.get('key'), var.get('value'), var_id))
        conn.commit()
        log_audit_event(
            event_type='GLOBAL_VAR_UPDATE',
            category='configuration',
            severity='low',
            status='success',
            summary=f"Updated global variable {var.get('key')}",
            actor_username=var.get('actor_username') or 'admin',
            actor_role=var.get('actor_role') or 'Administrator',
            target_type='global_var',
            target_id=var_id,
            target_name=var.get('key'),
        )
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.delete("/vars/{var_id}")
def delete_global_var(var_id: str):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT key FROM global_vars WHERE id = ?', (var_id,)).fetchone()
        conn.execute('DELETE FROM global_vars WHERE id = ?', (var_id,))
        conn.commit()
        log_audit_event(
            event_type='GLOBAL_VAR_DELETE',
            category='configuration',
            severity='medium',
            status='success',
            summary=f"Deleted global variable {row['key'] if row else var_id}",
            actor_username='admin',
            actor_role='Administrator',
            target_type='global_var',
            target_id=var_id,
            target_name=row['key'] if row else var_id,
        )
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
