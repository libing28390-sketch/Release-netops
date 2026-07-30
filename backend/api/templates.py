from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel, Field
import logging
import os
import uuid
import json
import threading
import time
from urllib.request import urlopen
from urllib.error import URLError
from database import get_db_connection
from services.audit_service import log_audit_event
from services.config_template_validation_service import validate_template
from core.config import settings

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
            'last_used as lastUsed FROM templates'
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
    validation = validate_template(
        template.get("content") or "",
        variables={},
        vendor=template.get("vendor") or "",
        rollback=template.get("rollback") or "",
    )
    if not validation["syntax_valid"]:
        raise HTTPException(status_code=422, detail=validation["issues"])
    conn = get_db_connection()
    template_id = template.get('id') or str(uuid.uuid4())
    try:
        conn.execute('''
            INSERT INTO templates
            (id, name, type, category, vendor, content, rollback, last_used,
             description, platform_family, software_version, official_reference,
             validation_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            template_id,
            template.get('name'),
            template.get('type'),
            template.get('category', 'custom'),
            template.get('vendor', ''),
            template.get('content'),
            template.get('rollback'),
            template.get('lastUsed'),
            template.get('description', ''),
            template.get('platform_family', ''),
            template.get('software_version', ''),
            '',
            'draft',
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
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.put("/templates/{template_id}")
def update_template(template_id: str, template: dict = Body(...)):
    validation = validate_template(
        template.get("content") or "",
        variables={},
        vendor=template.get("vendor") or "",
        rollback=template.get("rollback") or "",
    )
    if not validation["syntax_valid"]:
        raise HTTPException(status_code=422, detail=validation["issues"])
    conn = get_db_connection()
    try:
        existing = conn.execute(
            """
            SELECT name, type, category, vendor, content, rollback, description,
                   platform_family, software_version, official_reference,
                   validation_status
            FROM templates WHERE id = ?
            """,
            (template_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Template not found")

        reviewed_fields = (
            'name', 'type', 'category', 'vendor', 'content', 'rollback',
            'description', 'platform_family', 'software_version',
        )
        reviewed_content_changed = any(
            str(template.get(field, '') or '') != str(existing[field] or '')
            for field in reviewed_fields
        )
        validation_status = str(existing['validation_status'] or 'draft')
        official_reference = str(existing['official_reference'] or '')
        if reviewed_content_changed:
            validation_status = 'draft'

        conn.execute('''
            UPDATE templates
            SET name = ?, type = ?, category = ?, vendor = ?, content = ?,
                rollback = ?, last_used = ?, description = ?, platform_family = ?,
                software_version = ?, official_reference = ?, validation_status = ?
            WHERE id = ?
        ''', (
            template.get('name'),
            template.get('type'),
            template.get('category', 'custom'),
            template.get('vendor', ''),
            template.get('content'),
            template.get('rollback'),
            template.get('lastUsed'),
            template.get('description', ''),
            template.get('platform_family', ''),
            template.get('software_version', ''),
            official_reference,
            validation_status,
            template_id
        ))
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
