# -*- coding: utf-8 -*-
import uuid
import json
import asyncio
import logging
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Body, Request, Query
from fastapi.responses import JSONResponse

from database import get_db_connection
from core.rbac import authorize_resource, require_permission, require_role
from services.audit_service import log_audit_event
from core.crypto import decrypt_credential
from core.read_cache import (
    PLAYBOOK_CACHE_TTL_SECONDS,
    invalidate_read_cache,
    read_cache,
)

from .builtin_scenarios import PLATFORMS
from .scenarios import (
    _all_scenarios,
    _normalize_playbook_platform,
    _render_phase_commands,
    resolve_platform_phases,
    extract_approval_steps,
    validate_controlled_phases,
)
from .manager import ws_manager
from .engine import (
    _device_locks,
    _get_device_lock,
    _pending_rollbacks,
    _run_playbook
)
from services.playbook_version_service import (
    PlaybookVersionError,
    approve_version,
    create_version,
    get_version,
    list_versions,
    publish_version,
    rollback_version,
    submit_version,
    update_version,
    validate_version,
)
from services.playbook_execution_approval_service import (
    PlaybookApprovalError,
    create_execution_approvals,
    decide_execution_approval,
    execution_start_payload,
    list_execution_approvals,
)
from services.playbook_output_service import PlaybookOutputError, load_output

router = APIRouter()
logger = logging.getLogger("api.playbooks.routes")


def _create_playbook_execution_snapshot(
    conn,
    *,
    playbook_id: str,
    tenant_id: str | None,
    name: str,
    definition: dict,
    user: dict,
) -> tuple[str, int, str]:
    """Persist the exact definition selected for this execution."""
    encoded = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    checksum = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
    version_row = conn.execute(
        'SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version FROM playbook_versions WHERE playbook_id = ?',
        (playbook_id,),
    ).fetchone()
    version_number = int(version_row['next_version'] if version_row else 1)
    snapshot_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        '''INSERT INTO playbook_versions
           (id, playbook_id, tenant_id, version_number, status, name, definition_json,
            checksum, created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'SNAPSHOT', ?, ?, ?, ?, ?, ?)''',
        (
            snapshot_id,
            playbook_id,
            tenant_id or None,
            version_number,
            name,
            encoded,
            checksum,
            user.get('id') or user.get('username') or 'system',
            now,
            now,
        ),
    )
    return snapshot_id, version_number, checksum


def _ensure_controlled_phases(phases: object, *, user: dict, operation: str) -> None:
    errors = validate_controlled_phases(phases)
    if not errors:
        return
    log_audit_event(
        event_type='PLAYBOOK_RAW_COMMAND_REJECTED',
        category='automation',
        severity='high',
        status='denied',
        summary=f'Rejected raw Playbook steps during {operation}',
        actor_id=user.get('id'),
        actor_username=user.get('username'),
        actor_role=user.get('role'),
        target_type='playbook',
        target_id='',
        details={'operation': operation, 'errors': errors},
    )
    raise HTTPException(
        status_code=400,
        detail={
            'code': errors[0].get('code') or 'INVALID_PLAYBOOK_DEFINITION',
            'message': 'Platform registry is enabled; Playbook steps must use bounded published action definitions',
            'errors': errors,
        },
    )


MAX_EXECUTION_DEVICES = 200
MAX_EXECUTION_CONCURRENCY = 20
MAX_EXECUTION_VARIABLES = 64
MAX_COMMIT_CONFIRMED_TTL = 3_600


def _validate_execution_limits(
    device_ids: object,
    variables: object,
    concurrency: object,
    dry_run: object,
    commit_confirmed_ttl: object,
) -> tuple[list[str], dict, int, bool, int]:
    if not isinstance(device_ids, list) or not device_ids:
        raise HTTPException(status_code=400, detail={'code': 'DEVICE_TARGETS_REQUIRED', 'message': 'No devices selected'})
    normalized_ids = [str(device_id or '').strip() for device_id in device_ids]
    if any(not value for value in normalized_ids):
        raise HTTPException(status_code=400, detail={'code': 'INVALID_DEVICE_TARGET', 'message': 'device_ids must contain non-empty ids'})
    if len(set(normalized_ids)) != len(normalized_ids):
        raise HTTPException(status_code=400, detail={'code': 'DUPLICATE_DEVICE_TARGET', 'message': 'device_ids must not contain duplicates'})
    if len(normalized_ids) > MAX_EXECUTION_DEVICES:
        raise HTTPException(status_code=400, detail={'code': 'DEVICE_LIMIT_EXCEEDED', 'message': f'At most {MAX_EXECUTION_DEVICES} devices may be executed at once'})
    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or not 1 <= concurrency <= MAX_EXECUTION_CONCURRENCY:
        raise HTTPException(status_code=400, detail={'code': 'CONCURRENCY_LIMIT_EXCEEDED', 'message': f'concurrency must be an integer between 1 and {MAX_EXECUTION_CONCURRENCY}'})
    if not isinstance(variables, dict) or len(variables) > MAX_EXECUTION_VARIABLES:
        raise HTTPException(status_code=400, detail={'code': 'VARIABLE_LIMIT_EXCEEDED', 'message': f'variables must be an object with at most {MAX_EXECUTION_VARIABLES} entries'})
    if not isinstance(dry_run, bool):
        raise HTTPException(status_code=400, detail={'code': 'INVALID_DRY_RUN', 'message': 'dry_run must be boolean'})
    if isinstance(commit_confirmed_ttl, bool) or not isinstance(commit_confirmed_ttl, int) or not 0 <= commit_confirmed_ttl <= MAX_COMMIT_CONFIRMED_TTL:
        raise HTTPException(status_code=400, detail={'code': 'COMMIT_TTL_LIMIT_EXCEEDED', 'message': f'commit_confirmed_ttl must be between 0 and {MAX_COMMIT_CONFIRMED_TTL} seconds'})
    return normalized_ids, variables, concurrency, dry_run, commit_confirmed_ttl


def _call_playbook_version(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except PlaybookVersionError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


def _call_playbook_approval(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except PlaybookApprovalError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


def _resume_approved_execution(execution: dict, user: dict) -> dict:
    payload = _call_playbook_approval(execution_start_payload, execution)
    asyncio.create_task(_run_playbook(
        payload['execution_id'],
        payload['device_ids'],
        payload['phases'],
        payload['variables'],
        payload['dry_run'],
        payload['concurrency'],
        payload['platform'],
        payload['commit_confirmed_ttl'],
        user,
    ))
    return payload


def _assert_execution_scope(conn, execution_id: str, user: dict, *, action: str = 'view') -> dict:
    """Require tenant/resource scope before returning execution data or output."""
    row = conn.execute(
        'SELECT id, tenant_id, device_ids FROM playbook_executions WHERE id = ?',
        (execution_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Execution not found")

    execution = dict(row)
    if user.get('role') == 'Administrator':
        return execution

    execution_tenant = str(execution.get('tenant_id') or '')
    user_tenant = str(user.get('tenant_id') or '')
    if not execution_tenant or not user_tenant or execution_tenant != user_tenant:
        raise HTTPException(status_code=403, detail={
            'code': 'RESOURCE_SCOPE_DENIED',
            'message': 'Execution belongs to another tenant or has no tenant scope',
        })
    if not authorize_resource(
        user,
        'playbook',
        action,
        tenant_id=execution_tenant,
    ):
        raise HTTPException(status_code=403, detail={
            'code': 'RESOURCE_SCOPE_DENIED',
            'message': 'Insufficient permission for this execution scope',
        })

    try:
        device_ids = json.loads(execution.get('device_ids') or '[]')
    except (TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=403, detail={
            'code': 'RESOURCE_SCOPE_DENIED',
            'message': 'Execution device scope is invalid',
        })
    if not isinstance(device_ids, list):
        raise HTTPException(status_code=403, detail={
            'code': 'RESOURCE_SCOPE_DENIED',
            'message': 'Execution device scope is invalid',
        })
    normalized_ids = [str(device_id or '').strip() for device_id in device_ids if str(device_id or '').strip()]
    if normalized_ids:
        placeholders = ','.join('?' for _ in normalized_ids)
        device_rows = conn.execute(
            f'SELECT id, tenant_id, site_id, site, device_group_id FROM devices WHERE id IN ({placeholders})',
            normalized_ids,
        ).fetchall()
        devices_by_id = {str(device['id']): dict(device) for device in device_rows}
        if len(devices_by_id) != len(set(normalized_ids)):
            raise HTTPException(status_code=403, detail={
                'code': 'RESOURCE_SCOPE_DENIED',
                'message': 'Execution device scope is unavailable',
            })
        for device_id in normalized_ids:
            device = devices_by_id[device_id]
            scope = {
                'tenant_id': str(device.get('tenant_id') or ''),
                'site_id': str(device.get('site_id') or device.get('site') or ''),
                'device_group_id': str(device.get('device_group_id') or ''),
            }
            if scope['tenant_id'] != execution_tenant or not authorize_resource(user, 'playbook', action, **scope):
                raise HTTPException(status_code=403, detail={
                    'code': 'RESOURCE_SCOPE_DENIED',
                    'message': 'Insufficient permission for an execution device scope',
                    'device_id': device_id,
                })
    return execution


def _assert_playbook_device_scope(conn, device_ids: list[str], user: dict) -> list[dict]:
    """Validate every selected device before a Playbook execution is queued."""
    normalized_ids = [str(device_id or '').strip() for device_id in device_ids]
    if not normalized_ids or any(not device_id for device_id in normalized_ids):
        raise HTTPException(status_code=400, detail={
            'code': 'DEVICE_ID_REQUIRED',
            'message': 'Every selected device must have an id',
        })
    if len(set(normalized_ids)) != len(normalized_ids):
        raise HTTPException(status_code=400, detail={
            'code': 'DUPLICATE_DEVICE_ID',
            'message': 'A device may only be selected once per execution',
        })

    placeholders = ','.join('?' for _ in normalized_ids)
    rows = conn.execute(
        f"SELECT id, tenant_id, site_id, site, device_group_id FROM devices WHERE id IN ({placeholders})",
        normalized_ids,
    ).fetchall()
    by_id = {str(row['id']): dict(row) for row in rows}
    missing = [device_id for device_id in normalized_ids if device_id not in by_id]
    if missing:
        raise HTTPException(status_code=404, detail={
            'code': 'DEVICE_NOT_FOUND',
            'message': 'One or more selected devices do not exist',
            'device_ids': missing[:32],
        })

    is_admin = user.get('role') == 'Administrator'
    user_tenant = str(user.get('tenant_id') or '')
    for device_id in normalized_ids:
        device = by_id[device_id]
        device_tenant = str(device.get('tenant_id') or '')
        if not is_admin and (not user_tenant or not device_tenant or user_tenant != device_tenant):
            raise HTTPException(status_code=403, detail={
                'code': 'RESOURCE_SCOPE_DENIED',
                'message': 'Selected device belongs to another or unscoped tenant',
                'device_id': device_id,
            })
        scope = {
            'tenant_id': device_tenant,
            'site_id': str(device.get('site_id') or device.get('site') or ''),
            'device_group_id': str(device.get('device_group_id') or ''),
        }
        for resource_type in ('playbook', 'command'):
            if not authorize_resource(user, resource_type, 'execute', **scope):
                raise HTTPException(status_code=403, detail={
                    'code': 'RESOURCE_SCOPE_DENIED',
                    'message': 'Insufficient permission for the selected device scope',
                    'resource_type': resource_type,
                    'device_id': device_id,
                })
    return [by_id[device_id] for device_id in normalized_ids]


def _audit_playbook_output_read(
    request: Request | None,
    user: dict,
    *,
    execution_id: str,
    device_id: str | None = None,
    source: str,
) -> None:
    log_audit_event(
        event_type='PLAYBOOK_OUTPUT_READ',
        category='automation',
        severity='medium',
        status='success',
        summary=f'Read Playbook execution output {execution_id}',
        actor_id=user.get('id'),
        actor_username=user.get('username'),
        actor_role=user.get('role'),
        source_ip=request.client.host if request and request.client else None,
        target_type='playbook_execution',
        target_id=execution_id,
        device_id=device_id,
        execution_id=execution_id,
        details={'source': source},
    )


def _load_output_or_http(ciphertext: str | None, legacy_json: str | None) -> object:
    try:
        return load_output(ciphertext, legacy_json)
    except PlaybookOutputError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                'code': 'PLAYBOOK_OUTPUT_UNAVAILABLE',
                'message': str(exc),
            },
        ) from exc


@router.get("/playbooks/platforms")
async def list_platforms(user=require_permission("playbook", "view")):
    """Return all supported vendor/platform definitions."""
    return PLATFORMS



@router.get("/playbooks/scenarios")
async def list_scenarios(user=require_permission("playbook", "view")):
    """Return built-in and custom scenario templates."""
    tenant_id = None if user.get('role') == 'Administrator' else str(user.get('tenant_id') or '') or None
    return _all_scenarios(tenant_id)


@router.post("/playbooks/scenarios", status_code=201)
async def create_custom_scenario(request: Request, payload: dict = Body(...), user=require_permission("playbook", "create")):
    scenario_id = (payload.get('id') or '').strip() or f"custom-{uuid.uuid4().hex[:10]}"
    name = (payload.get('name') or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail='Scenario name is required')

    supported_platforms = payload.get('supported_platforms') or []
    if not supported_platforms:
        raise HTTPException(status_code=400, detail='At least one supported platform is required')

    default_platform = payload.get('default_platform') or supported_platforms[0]
    platform_phases = payload.get('platform_phases') or {}
    if default_platform not in platform_phases:
        raise HTTPException(status_code=400, detail='platform_phases must include the default platform')
    _ensure_controlled_phases(platform_phases, user=user, operation='create')

    # Prevent ID conflicts with built-ins and existing custom scenarios
    # IDs are globally unique in the legacy table, so collision detection must
    # include scenarios owned by other tenants even though listing is scoped.
    all_ids = {s.get('id') for s in _all_scenarios()}
    if scenario_id in all_ids:
        raise HTTPException(status_code=409, detail='Scenario id already exists')

    now = datetime.now().isoformat()
    scenario_doc = {
        'id': scenario_id,
        'name': name,
        'name_zh': payload.get('name_zh') or name,
        'description': payload.get('description') or '',
        'description_zh': payload.get('description_zh') or payload.get('description') or '',
        'category': payload.get('category') or 'Custom',
        'icon': payload.get('icon') or '🧩',
        'risk': payload.get('risk') or 'medium',
        'supported_platforms': supported_platforms,
        'default_platform': default_platform,
        'variables': payload.get('variables') or [],
        'platform_phases': platform_phases,
        'is_custom': True,
    }

    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT INTO custom_scenarios (id, data_json, tenant_id, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
            (scenario_id, json.dumps(scenario_doc), user.get('tenant_id'), user.get('username') or 'admin', now, now)
        )
        conn.commit()
    finally:
        conn.close()

    log_audit_event(
        event_type='SCENARIO_CREATE',
        category='automation',
        severity='medium',
        status='success',
        summary=f"Created scenario {name}",
        actor_id=user.get('id'),
        actor_username=user.get('username') or 'admin',
        actor_role=user.get('role') or 'Viewer',
        source_ip=request.client.host if request and request.client else None,
        target_type='scenario',
        target_id=scenario_id,
        target_name=name,
        details={'risk': scenario_doc['risk'], 'platforms': supported_platforms},
    )

    return scenario_doc


@router.get("/playbooks")
def list_playbooks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    status: str = Query('all'),
    scenario: str = Query(''),
    user=require_permission("playbook", "view"),
):
    """Return paginated playbook execution summaries (no bulky results_json / phases_json)."""
    scope_key = f"{user.get('role', '')}:{user.get('tenant_id') or ''}"
    cache_key = f'{scope_key}:{page}:{page_size}:{status}:{scenario}'
    cache_hit, cached = read_cache.get('playbooks', cache_key)
    if cache_hit:
        logger.debug('[Perf] playbooks cache hit key=%s', cache_key)
        return cached

    conn = get_db_connection()
    try:
        where_clauses = []
        params: list = []
        if user.get('role') != 'Administrator':
            # Legacy rows without tenant_id are intentionally invisible to
            # tenant users until they are explicitly re-associated.
            where_clauses.append("tenant_id = ?")
            params.append(str(user.get('tenant_id') or ''))
        if status != 'all':
            where_clauses.append("status = ?")
            params.append(status)
        if scenario:
            where_clauses.append("scenario_name LIKE ?")
            params.append(f"%{scenario}%")
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM playbook_executions {where_sql}", params
        ).fetchone()[0]
        logger.debug(f"[Playbooks] Found {total} total executions (status={status}, scenario={scenario})")
        offset = (page - 1) * page_size
        rows = conn.execute(
            f'''SELECT id, scenario_id, scenario_name, platform, device_ids,
                       variables, status, dry_run, author, concurrency,
                       playbook_version_id,
                       total_devices, success_count, failed_count, partial_count,
                       created_at, updated_at
                FROM playbook_executions {where_sql}
                ORDER BY created_at DESC LIMIT ? OFFSET ?''',
            [*params, page_size, offset]
        ).fetchall()
        items = []
        for r in rows:
            row_dict = dict(r)
            if not row_dict.get('total_devices'):
                try:
                    row_dict['total_devices'] = len(json.loads(row_dict.get('device_ids', '[]')))
                except Exception:
                    row_dict['total_devices'] = 0
            items.append(row_dict)
        response = {"items": items, "total": total, "page": page, "page_size": page_size}
        read_cache.set('playbooks', cache_key, response, PLAYBOOK_CACHE_TTL_SECONDS)
        return response
    finally:
        conn.close()


@router.get("/playbooks/{playbook_id}/versions")
async def list_playbook_versions(playbook_id: str, include_snapshots: bool = Query(False), user=require_permission("playbook", "view")):
    return {"success": True, "data": _call_playbook_version(list_versions, playbook_id, user, include_snapshots=include_snapshots)}


@router.post("/playbooks/{playbook_id}/versions", status_code=201)
async def create_playbook_version(playbook_id: str, payload: dict = Body(...), user=require_permission("playbook", "create")):
    return {"success": True, "data": _call_playbook_version(create_version, playbook_id, payload, user)}


@router.get("/playbook-versions/{version_id}")
async def get_playbook_version(version_id: str, user=require_permission("playbook", "view")):
    return {"success": True, "data": _call_playbook_version(get_version, version_id, user)}


@router.put("/playbook-versions/{version_id}")
async def update_playbook_version(version_id: str, payload: dict = Body(...), user=require_permission("playbook", "edit_draft")):
    return {"success": True, "data": _call_playbook_version(update_version, version_id, payload, user)}


@router.get("/playbooks/{execution_id}/approvals")
async def get_playbook_execution_approvals(execution_id: str, user=require_permission("playbook", "view")):
    return {"success": True, "data": _call_playbook_approval(list_execution_approvals, execution_id, user)}


async def _decide_playbook_execution_approval(
    execution_id: str,
    approval_id: str,
    decision: str,
    payload: dict,
    user: dict,
):
    result = _call_playbook_approval(
        decide_execution_approval,
        execution_id,
        approval_id,
        decision,
        user,
        str(payload.get('reason') or ''),
    )
    execution = result.get('execution') or {}
    if result.get('should_start'):
        _resume_approved_execution(execution, user)
    approval = result.get('approval') or {}
    log_audit_event(
        event_type='PLAYBOOK_EXECUTION_APPROVAL',
        category='automation',
        severity='high',
        status=str(approval.get('status') or decision).lower(),
        summary=f'Playbook execution approval {str(approval.get("status") or decision).lower()}',
        actor_id=user.get('id'),
        actor_username=user.get('username'),
        actor_role=user.get('role'),
        target_type='playbook_execution',
        target_id=execution_id,
        execution_id=execution_id,
        details={
            'approval_id': approval_id,
            'step_path': approval.get('step_path'),
            'status': approval.get('status'),
            'execution_status': execution.get('status'),
            'execution_started': bool(result.get('should_start')),
        },
    )
    return {
        'approval': approval,
        'execution_id': execution_id,
        'execution_status': execution.get('status'),
        'execution_started': bool(result.get('should_start')),
    }


@router.post("/playbooks/{execution_id}/approvals/{approval_id}/approve")
async def approve_playbook_execution_approval(
    execution_id: str,
    approval_id: str,
    payload: dict = Body(default={}),
    user=require_permission("playbook", "approve"),
):
    return {"success": True, "data": await _decide_playbook_execution_approval(execution_id, approval_id, 'APPROVED', payload, user)}


@router.post("/playbooks/{execution_id}/approvals/{approval_id}/reject")
async def reject_playbook_execution_approval(
    execution_id: str,
    approval_id: str,
    payload: dict = Body(default={}),
    user=require_permission("playbook", "approve"),
):
    return {"success": True, "data": await _decide_playbook_execution_approval(execution_id, approval_id, 'REJECTED', payload, user)}


@router.post("/playbook-versions/{version_id}/validate")
async def validate_playbook_version(version_id: str, user=require_permission("playbook", "test")):
    return {"success": True, "data": _call_playbook_version(validate_version, version_id, user)}


@router.post("/playbook-versions/{version_id}/submit")
async def submit_playbook_version(version_id: str, user=require_permission("playbook", "submit")):
    return {"success": True, "data": _call_playbook_version(submit_version, version_id, user)}


@router.post("/playbook-versions/{version_id}/approve")
async def approve_playbook_version(version_id: str, user=require_permission("playbook", "approve")):
    return {"success": True, "data": _call_playbook_version(approve_version, version_id, user)}


@router.post("/playbook-versions/{version_id}/publish")
async def publish_playbook_version(version_id: str, user=require_permission("playbook", "publish")):
    return {"success": True, "data": _call_playbook_version(publish_version, version_id, user)}


@router.post("/playbooks/{playbook_id}/rollback")
async def rollback_playbook_version(playbook_id: str, payload: dict = Body(...), user=require_permission("playbook", "rollback")):
    version_id = str(payload.get("version_id") or "").strip()
    if not version_id:
        raise HTTPException(status_code=400, detail={"code": "INVALID_ROLLBACK_REQUEST", "message": "version_id is required"})
    return {"success": True, "data": _call_playbook_version(rollback_version, playbook_id, version_id, user)}

@router.get("/playbooks/{playbook_id}")
async def get_playbook(playbook_id: str, request: Request, user=require_permission("playbook", "view")):
    """Legacy endpoint — returns full row including results_json for backward compatibility."""
    conn = get_db_connection()
    try:
        _assert_execution_scope(conn, playbook_id, user, action='view')
        row = conn.execute('SELECT * FROM playbook_executions WHERE id = ?', (playbook_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Playbook execution not found")
        _audit_playbook_output_read(request, user, execution_id=playbook_id, source='execution_record')
        result = dict(row)
        if 'results_encrypted' in result:
            result['results_json'] = json.dumps(
                _load_output_or_http(result.get('results_encrypted'), result.get('results_json')),
                ensure_ascii=False,
            )
            result.pop('results_encrypted', None)
        return result
    finally:
        conn.close()

@router.delete("/playbooks/{execution_id}")
async def delete_execution(execution_id: str, user=require_role("Administrator")):
    """Delete a playbook execution and its device results."""
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT id FROM playbook_executions WHERE id = ?', (execution_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Execution not found")
        conn.execute('DELETE FROM execution_device_results WHERE execution_id = ?', (execution_id,))
        conn.execute('DELETE FROM playbook_executions WHERE id = ?', (execution_id,))
        conn.commit()
        invalidate_read_cache('playbooks')
        return {"ok": True}
    finally:
        conn.close()

@router.get("/playbooks/{execution_id}/summary")
async def get_execution_summary(execution_id: str, user=require_permission("playbook", "view")):
    """Return header-level summary for one execution (no device details)."""
    conn = get_db_connection()
    try:
        _assert_execution_scope(conn, execution_id, user, action='view')
        row = conn.execute(
            '''SELECT id, scenario_name, platform, device_ids, status, dry_run, author,
                      playbook_version_id,
                      total_devices, success_count, failed_count, partial_count,
                      created_at, updated_at
               FROM playbook_executions WHERE id = ?''',
            (execution_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Execution not found")
        d = dict(row)
        # Fallback: compute total_devices from device_ids for legacy records
        if not d.get('total_devices'):
            try:
                d['total_devices'] = len(json.loads(d.get('device_ids', '[]')))
            except Exception:
                d['total_devices'] = 0
        # Fallback: compute counts from execution_device_results or results_json for legacy records
        if not d.get('success_count') and not d.get('failed_count'):
            try:
                counts = conn.execute(
                    '''SELECT
                        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as sc,
                        SUM(CASE WHEN status IN ('failed','error') THEN 1 ELSE 0 END) as fc
                    FROM execution_device_results WHERE execution_id = ?''',
                    (execution_id,)
                ).fetchone()
                if counts and (counts['sc'] or counts['fc']):
                    d['success_count'] = counts['sc'] or 0
                    d['failed_count'] = counts['fc'] or 0
            except Exception:
                pass
        # Second fallback: parse results_json blob if counts still 0
        if not d.get('success_count') and not d.get('failed_count'):
            try:
                rj_row = conn.execute(
                    "SELECT results_json, results_encrypted FROM playbook_executions WHERE id = ?",
                    (execution_id,)
                ).fetchone()
                if rj_row and (rj_row['results_json'] or rj_row['results_encrypted']):
                    results = _load_output_or_http(rj_row['results_encrypted'], rj_row['results_json'])
                    sc = fc = pc = 0
                    for v in results.values():
                        st = v.get('status', 'success') if isinstance(v, dict) else 'success'
                        if st == 'success':
                            sc += 1
                        elif st in ('failed', 'error', 'blocked'):
                            fc += 1
                        else:
                            pc += 1
                    d['success_count'] = sc
                    d['failed_count'] = fc
                    d['partial_count'] = pc
            except Exception:
                pass
        try:
            s = datetime.fromisoformat(d['created_at'])
            e = datetime.fromisoformat(d['updated_at'])
            d['duration_ms'] = int((e - s).total_seconds() * 1000)
        except Exception:
            d['duration_ms'] = 0
        return d
    finally:
        conn.close()

@router.get("/playbooks/{execution_id}/full")
async def get_execution_full(execution_id: str, request: Request, user=require_permission("playbook", "view")):
    """Return the complete execution record, including phases_json and variables."""
    conn = get_db_connection()
    try:
        _assert_execution_scope(conn, execution_id, user, action='view')
        row = conn.execute(
            '''SELECT id, scenario_id, scenario_name, platform, device_ids, variables, 
                      status, dry_run, author, concurrency, phases_json, 
                      phases_encrypted,
                      playbook_version_id,
                      total_devices, success_count, failed_count, partial_count,
                      created_at, updated_at
               FROM playbook_executions WHERE id = ?''',
            (execution_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Execution not found")
        d = dict(row)
        # Parse JSON fields
        for field in ['device_ids', 'variables']:
            if d.get(field):
                try:
                    d[field.replace('_json', '')] = json.loads(d[field])
                except Exception:
                    d[field.replace('_json', '')] = d[field]
        d['phases'] = _load_output_or_http(d.get('phases_encrypted'), d.get('phases_json'))
        d.pop('phases_encrypted', None)
        _audit_playbook_output_read(request, user, execution_id=execution_id, source='full_execution')
        return d
    finally:
        conn.close()

@router.get("/playbooks/{execution_id}/devices")
async def get_execution_devices(
    execution_id: str,
    status: str = Query('all'),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query(''),
    user=require_permission("playbook", "view"),
):
    """Return paginated per-device results for an execution. Failed devices sorted first."""
    conn = get_db_connection()
    try:
        _assert_execution_scope(conn, execution_id, user, action='view')
        count_new = conn.execute(
            "SELECT COUNT(*) FROM execution_device_results WHERE execution_id = ?",
            (execution_id,)
        ).fetchone()[0]

        if count_new > 0:
            where_clauses = ["execution_id = ?"]
            params: list = [execution_id]
            if status != 'all':
                where_clauses.append("status = ?")
                params.append(status)
            if search:
                where_clauses.append("(hostname LIKE ? OR ip_address LIKE ?)")
                params.extend([f"%{search}%", f"%{search}%"])
            where_sql = "WHERE " + " AND ".join(where_clauses)
            total = conn.execute(
                f"SELECT COUNT(*) FROM execution_device_results {where_sql}", params
            ).fetchone()[0]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f'''SELECT id, device_id, hostname, ip_address, status, error_message,
                           started_at, completed_at, duration_ms
                    FROM execution_device_results {where_sql}
                    ORDER BY CASE status
                        WHEN 'failed' THEN 0
                        WHEN 'error' THEN 0
                        WHEN 'partial_failure' THEN 1
                        WHEN 'post_check_failed' THEN 1
                        ELSE 2 END, hostname
                    LIMIT ? OFFSET ?''',
                [*params, page_size, offset]
            ).fetchall()
            items = [dict(r) for r in rows]
        else:
            # Legacy fallback: parse results_json blob
            exec_row = conn.execute(
                "SELECT results_json, results_encrypted, device_ids FROM playbook_executions WHERE id = ?",
                (execution_id,)
            ).fetchone()
            if not exec_row:
                raise HTTPException(status_code=404, detail="Execution not found")
            try:
                results = _load_output_or_http(exec_row['results_encrypted'], exec_row['results_json'])
                device_ids_list = json.loads(exec_row['device_ids'] or '[]')
            except Exception:
                results, device_ids_list = {}, []
            all_items = []
            for did in device_ids_list:
                r = results.get(did, {})
                dev_row = conn.execute(
                    "SELECT hostname, ip_address FROM devices WHERE id = ?", (did,)
                ).fetchone()
                hostname = dev_row['hostname'] if dev_row else did
                ip_address = dev_row['ip_address'] if dev_row else ''
                all_items.append({
                    "device_id": did, "hostname": hostname, "ip_address": ip_address,
                    "status": r.get('status', 'success'),
                    "error_message": r.get('error', ''),
                    "started_at": None, "completed_at": None, "duration_ms": 0,
                })
            if status != 'all':
                all_items = [i for i in all_items if i['status'] == status]
            if search:
                sq = search.lower()
                all_items = [i for i in all_items if sq in i['hostname'].lower() or sq in i['ip_address'].lower()]
            all_items.sort(key=lambda x: (
                0 if x['status'] in ('failed', 'error') else
                1 if 'fail' in x['status'] else 2,
                x['hostname']
            ))
            total = len(all_items)
            offset = (page - 1) * page_size
            items = all_items[offset:offset + page_size]
        return {"items": items, "total": total, "page": page, "page_size": page_size}
    finally:
        conn.close()

@router.get("/playbooks/{execution_id}/devices/{device_id}")
async def get_execution_device_detail(execution_id: str, device_id: str, request: Request, user=require_permission("playbook", "view")):
    """Return full phase output for one device in an execution."""
    conn = get_db_connection()
    try:
        _assert_execution_scope(conn, execution_id, user, action='view')
        row = conn.execute(
            "SELECT * FROM execution_device_results WHERE execution_id = ? AND (device_id = ? OR ip_address = ?)",
            (execution_id, device_id, device_id)
        ).fetchone()
        if row:
            res = dict(row)
            if 'phases_encrypted' in res:
                res['phases'] = _load_output_or_http(res.get('phases_encrypted'), res.get('phases_json'))
                res.pop('phases_encrypted', None)
            elif res.get('phases_json'):
                # Keep the fail-closed loader on the legacy branch too.
                res['phases'] = _load_output_or_http(None, res.get('phases_json'))
            _audit_playbook_output_read(request, user, execution_id=execution_id, device_id=device_id, source='device_result')
            return res
        # Legacy fallback
        exec_row = conn.execute(
            "SELECT results_json, results_encrypted FROM playbook_executions WHERE id = ?", (execution_id,)
        ).fetchone()
        if not exec_row:
            raise HTTPException(status_code=404, detail="Execution not found")
        results = _load_output_or_http(exec_row['results_encrypted'], exec_row['results_json'])
        device_data = results.get(device_id)
        if not device_data:
            raise HTTPException(status_code=404, detail="Device result not found")
        dev_row = conn.execute(
            "SELECT hostname, ip_address FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
        result = {
            "device_id": device_id,
            "hostname": dev_row['hostname'] if dev_row else device_id,
            "ip_address": dev_row['ip_address'] if dev_row else '',
            "status": device_data.get('status', 'success'),
            "error_message": device_data.get('error', ''),
            "phases_json": json.dumps(device_data.get('phases', {})),
            "started_at": None, "completed_at": None, "duration_ms": 0,
        }
        _audit_playbook_output_read(request, user, execution_id=execution_id, device_id=device_id, source='legacy_results')
        return result
    finally:
        conn.close()

@router.post("/playbooks/{execution_id}/devices/{device_id}/parse")
async def parse_device_output(execution_id: str, device_id: str, request: Request, payload: dict = Body(...), user=require_permission("playbook", "test")):
    """
    使用 TextFSM 解析指定设备的执行输出。
    请求体：{ "platform": "cisco_ios", "command": "show version", "output": "..." }
    若不传 output，则从数据库中读取该设备的 execute phase 输出。
    """
    from core.platform_utils import normalize_device_platform
    from core.textfsm import (
        _find_template,
        _template_platform_candidates,
        parse_with_textfsm,
    )

    # Bind parser selection to the actual asset.  The old endpoint trusted a
    # client-supplied platform, which allowed a playbook result from one
    # vendor to be parsed with another vendor's grammar.
    device_conn = get_db_connection()
    try:
        _assert_execution_scope(device_conn, execution_id, user, action='test')
        device_row = device_conn.execute(
            'SELECT platform, vendor FROM devices WHERE id = ? OR ip_address = ?',
            (device_id, device_id),
        ).fetchone()
    finally:
        device_conn.close()
    if not device_row:
        raise HTTPException(status_code=404, detail='Device not found')

    actual_platform = normalize_device_platform(device_row['vendor'], device_row['platform'] or '')
    requested_platform = (payload.get('platform') or '').strip()
    actual_candidates = set(_template_platform_candidates(actual_platform))
    if requested_platform:
        requested_candidates = set(_template_platform_candidates(requested_platform))
        if not actual_candidates.intersection(requested_candidates):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Parser platform '{requested_platform}' does not match "
                    f"device platform '{actual_platform}'"
                ),
            )
    platform = actual_platform
    command = (payload.get('command') or '').strip()
    raw_output = payload.get('output')

    # 若未传 output，从数据库读取
    if raw_output is None:
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT phases_json, phases_encrypted, hostname FROM execution_device_results WHERE execution_id = ? AND (device_id = ? OR ip_address = ?)",
                (execution_id, device_id, device_id)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Device result not found")
            try:
                phases = _load_output_or_http(row['phases_encrypted'], row['phases_json'])
                # 取 execute phase 的 output
                raw_output = phases.get('execute', {}).get('output', '')
                if not command:
                    # 尝试从 commands 列表推断命令
                    cmds = phases.get('execute', {}).get('commands', [])
                    if cmds:
                        command = cmds[0]
            except Exception:
                raw_output = ''
            _audit_playbook_output_read(request, user, execution_id=execution_id, device_id=device_id, source='parse_from_device_result')
        finally:
            conn.close()

    if not raw_output:
        return {'success': False, 'message': '没有可解析的输出内容', 'data': None}

    if not platform or not command:
        return {'success': False, 'message': '需要提供 platform 和 command 参数', 'data': None}

    # 检查是否有对应模板
    template_path = _find_template(platform, command)
    if not template_path:
        return {
            'success': False,
            'message': f'未找到 {platform} / {command} 的解析模板',
            'data': None,
            'has_template': False,
        }

    records = parse_with_textfsm(platform, command, raw_output)
    if not records:
        return {
            'success': True,
            'message': '模板匹配为空，请检查输出格式是否与模板一致',
            'data': {'records': [], 'count': 0, 'fields': []},
            'has_template': True,
        }

    return {
        'success': True,
        'message': f'解析成功，共 {len(records)} 条记录',
        'data': {
            'records': records,
            'count': len(records),
            'fields': list(records[0].keys()) if records else [],
        },
        'has_template': True,
    }


@router.post("/playbooks/preview")
async def preview_playbook(payload: dict = Body(...), user=require_permission("playbook", "test")):
    """Preview rendered commands without executing."""
    # Direct service-level callers (including compatibility tests) do not run
    # FastAPI dependency injection, so ``user`` can still be the Depends
    # marker.  HTTP requests always arrive here with the authenticated dict.
    if not isinstance(user, dict):
        user = {"id": "direct-preview", "username": "direct-preview", "role": "Administrator"}
    scenario_id = payload.get('scenario_id')
    variables = payload.get('variables', {})
    requested_platform = payload.get('platform', 'cisco_ios')
    platform = _normalize_playbook_platform(requested_platform)

    tenant_id = None if user.get('role') == 'Administrator' else str(user.get('tenant_id') or '') or None
    try:
        scenarios = _all_scenarios(tenant_id)
    except TypeError:
        # Backward-compatible test/integration providers may still expose the
        # original no-argument scenario loader.
        scenarios = _all_scenarios()
    scenario = next((s for s in scenarios if s['id'] == scenario_id), None)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    try:
        phases, resolved_platform = resolve_platform_phases(
            scenario.get('platform_phases', {}), platform
        )
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Platform '{platform}' not supported for this scenario")

    _ensure_controlled_phases(phases, user=user, operation='preview')

    action_codes = {
        phase: [
            str(step.get('action_code')).strip()
            for step in phases.get(phase, [])
            if isinstance(step, dict) and step.get('action_code')
        ]
        for phase in ('pre_check', 'execute', 'post_check', 'rollback')
    }

    return {
        "platform": resolved_platform,
        "requested_platform": requested_platform,
        "pre_check": _render_phase_commands(phases.get('pre_check', []), variables),
        "execute": _render_phase_commands(phases.get('execute', []), variables),
        "post_check": _render_phase_commands(phases.get('post_check', []), variables),
        "rollback": _render_phase_commands(phases.get('rollback', []), variables),
        "action_codes": action_codes,
        "registry_actions_enabled": True,
    }



def _parse_iso_to_utc(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _assert_change_order_executable(row: dict, scenario_id: str, platform: str, now_utc: datetime) -> None:
    status = row.get('status') or ''
    if status not in {'approved', 'implementing'}:
        raise HTTPException(status_code=400, detail=f"工单状态为 {status}，仅已审批/执行中的工单允许执行任务")

    start_dt = _parse_iso_to_utc(row.get('scheduled_start'))
    end_dt = _parse_iso_to_utc(row.get('scheduled_end'))
    if start_dt and now_utc < start_dt:
        raise HTTPException(status_code=400, detail=f"变更窗口尚未开始（计划开始：{row.get('scheduled_start') or ''}）")
    if end_dt and now_utc > end_dt:
        raise HTTPException(status_code=400, detail=f"变更窗口已超时（计划结束：{row.get('scheduled_end') or ''}）")

    raw_template = row.get('command_template_json')
    try:
        template = json.loads(raw_template or '{}')
    except (TypeError, json.JSONDecodeError):
        template = {}
    ticket_scenario_id = str(template.get('scenario_id') or '').strip()
    ticket_platform = str(template.get('platform') or '').strip()

    if ticket_scenario_id and scenario_id and ticket_scenario_id != scenario_id:
        raise HTTPException(status_code=400, detail="工单绑定场景与当前执行任务不匹配，请检查工单号")
    if ticket_platform and platform and ticket_platform != platform:
        raise HTTPException(status_code=400, detail="工单绑定平台与当前执行平台不匹配")


def _resolve_change_order_for_playbook(
    conn,
    *,
    ticket_number: str,
    scenario_id: str,
    platform: str,
    now_utc: datetime,
) -> tuple[dict, bool]:
    """Resolve explicit ticket or auto-match one active change order for scenario execution."""
    if ticket_number:
        row = conn.execute(
            """
            SELECT id, order_number, title, status, scheduled_start, scheduled_end, command_template_json
            FROM change_orders WHERE order_number = ?
            """,
            (ticket_number,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="未找到该变更工单，请检查工单号")
        order = dict(row)
        _assert_change_order_executable(order, scenario_id, platform, now_utc)
        return order, False

    rows = conn.execute(
        """
        SELECT id, order_number, title, status, scheduled_start, scheduled_end, command_template_json, updated_at
        FROM change_orders
        WHERE status IN ('approved', 'implementing')
        ORDER BY updated_at DESC
        LIMIT 200
        """
    ).fetchall()

    matched: list[dict] = []
    for row in rows:
        order = dict(row)
        raw_template = order.get('command_template_json')
        try:
            template = json.loads(raw_template or '{}')
        except (TypeError, json.JSONDecodeError):
            template = {}

        if str(template.get('scenario_id') or '').strip() != scenario_id:
            continue
        template_platform = str(template.get('platform') or '').strip()
        if template_platform and template_platform != platform:
            continue

        start_dt = _parse_iso_to_utc(order.get('scheduled_start'))
        end_dt = _parse_iso_to_utc(order.get('scheduled_end'))
        if start_dt and now_utc < start_dt:
            continue
        if end_dt and now_utc > end_dt:
            continue

        matched.append(order)

    if len(matched) == 1:
        _assert_change_order_executable(matched[0], scenario_id, platform, now_utc)
        return matched[0], True

    if len(matched) > 1:
        raise HTTPException(status_code=400, detail="匹配到多个有效变更工单，请填写工单号后再执行")

    raise HTTPException(status_code=400, detail="未找到当前任务对应的有效变更工单，请先创建并审批工单")



@router.post("/playbooks/execute")
async def execute_playbook(
    request: Request,
    payload: dict = Body(...),
    user=require_permission("playbook", "execute"),
):
    """
    Start an async playbook execution and return immediately.
    Subscribe to /ws/playbook/{execution_id} for real-time updates.
    """
    scenario_id = payload.get('scenario_id')
    raw_device_ids = payload.get('device_ids', [])
    raw_variables = payload.get('variables', {})
    raw_dry_run = payload.get('dry_run', False)
    raw_concurrency = payload.get('concurrency', 1)
    raw_commit_confirmed_ttl = payload.get('commit_confirmed_ttl', 0)
    device_ids, variables, concurrency, dry_run, commit_confirmed_ttl = _validate_execution_limits(
        raw_device_ids,
        raw_variables,
        raw_concurrency,
        raw_dry_run,
        raw_commit_confirmed_ttl,
    )
    change_ticket = str(payload.get('change_ticket') or '').strip()
    author = user.get('username') or payload.get('author', 'admin')
    actor_id = user.get('id')
    actor_role = user.get('role') or 'Viewer'
    requested_version_id = str(payload.get('playbook_version_id') or '').strip()
    selected_version = None
    if requested_version_id:
        selected_version = _call_playbook_version(get_version, requested_version_id, user)
        if selected_version.get('status') != 'PUBLISHED':
            raise HTTPException(status_code=400, detail={
                'code': 'PLAYBOOK_VERSION_NOT_PUBLISHED',
                'message': 'Only a published Playbook version can be executed',
            })
        scenario_id = scenario_id or selected_version.get('playbook_id')

    if not device_ids:
        raise HTTPException(status_code=400, detail="No devices selected")

    version_definition = (selected_version or {}).get('definition') or {}
    requested_platform = payload.get('platform') or version_definition.get('platform') or 'cisco_ios'
    platform = _normalize_playbook_platform(requested_platform)

    tenant_id = None if user.get('role') == 'Administrator' else str(user.get('tenant_id') or '') or None
    scenario = None if selected_version else next((s for s in _all_scenarios(tenant_id) if s['id'] == scenario_id), None)
    # Allow custom playbooks (scenario can be None — user provides commands directly)
    custom_phases = version_definition.get('phases') if selected_version else payload.get('phases')
    if not scenario and not custom_phases:
        raise HTTPException(status_code=404, detail="Scenario not found and no custom phases provided")

    execution_id = str(uuid.uuid4())
    if scenario:
        phases_catalog = scenario.get('platform_phases', {})
        try:
            # Validate the requested platform for the preview/change-ticket
            # contract. Actual execution resolves this catalog again per
            # device, using the platform stored in the asset row.
            phases_def, _ = resolve_platform_phases(phases_catalog, platform)
        except KeyError:
            raise HTTPException(status_code=400, detail=f"Platform '{platform}' not supported for this scenario")
        phases_for_execution = phases_catalog
    else:
        phases_def = custom_phases
        phases_for_execution = custom_phases
    _ensure_controlled_phases(phases_for_execution, user=user, operation='execute')
    approval_steps = extract_approval_steps(phases_for_execution)
    scenario_name = selected_version.get('name') if selected_version else (scenario['name'] if scenario else payload.get('name', 'Custom Playbook'))
    scenario_risk = str((scenario or {}).get('risk') or 'low').lower()
    now_utc = datetime.now(timezone.utc)

    conn = get_db_connection()
    try:
        _assert_playbook_device_scope(conn, device_ids, user)
        resolved_change_order = None
        auto_matched_change_order = False
        if scenario and scenario_risk != 'low':
            resolved_change_order, auto_matched_change_order = _resolve_change_order_for_playbook(
                conn,
                ticket_number=change_ticket,
                scenario_id=scenario_id,
                platform=platform,
                now_utc=now_utc,
            )

        snapshot_id, snapshot_version, snapshot_checksum = _create_playbook_execution_snapshot(
            conn,
            playbook_id=str(scenario_id or 'custom'),
            tenant_id=user.get('tenant_id'),
            name=scenario_name,
            definition={
                'scenario_id': scenario_id or 'custom',
                'platform': platform,
                'requested_platform': requested_platform,
                'variables': variables,
            'phases': phases_for_execution,
            'base_playbook_version_id': requested_version_id or None,
            },
            user=user,
        )

        execution_status = 'awaiting_approval' if approval_steps else 'pending'
        conn.execute(
            '''INSERT INTO playbook_executions
               (id, scenario_id, scenario_name, platform, device_ids, variables, status, dry_run, author, concurrency, phases_json, playbook_version_id, tenant_id, commit_confirmed_ttl, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (execution_id, scenario_id or 'custom', scenario_name, platform,
             json.dumps(device_ids), json.dumps(variables),
              execution_status, int(dry_run), author, concurrency,
              json.dumps(phases_for_execution),
              snapshot_id,
              tenant_id,
              commit_confirmed_ttl,
              datetime.now().isoformat(), datetime.now().isoformat())
        )
        approvals = create_execution_approvals(conn, execution_id, phases_for_execution, user) if approval_steps else []
        conn.commit()
    finally:
        conn.close()

    # The list endpoint is cached briefly for dashboard fan-out. Invalidate it
    # after the new execution is committed so the next refresh sees it.
    invalidate_read_cache('playbooks')

    # Approval-gated executions remain paused until every gate is approved.
    if not approvals:
        asyncio.create_task(_run_playbook(execution_id, device_ids, phases_for_execution, variables, dry_run, concurrency, platform, commit_confirmed_ttl, user))

    log_audit_event(
        event_type='PLAYBOOK_EXECUTION',
        category='automation',
        severity='high' if not dry_run else 'medium',
        status='awaiting_approval' if approvals else 'pending',
        summary=f"Started playbook {scenario_name} for {len(device_ids)} device(s)",
        actor_id=str(actor_id) if actor_id is not None else None,
        actor_username=author,
        actor_role=actor_role,
        source_ip=request.client.host if request.client else None,
        target_type='playbook',
        target_id=execution_id,
        target_name=scenario_name,
        execution_id=execution_id,
        details={
            'scenario_id': scenario_id or 'custom',
            'platform': platform,
            'device_count': len(device_ids),
            'dry_run': dry_run,
            'concurrency': concurrency,
            'change_order_number': (resolved_change_order or {}).get('order_number'),
            'change_order_auto_matched': auto_matched_change_order,
            'base_playbook_version_id': requested_version_id or None,
            'playbook_version_id': snapshot_id,
            'playbook_version_number': snapshot_version,
            'playbook_version_checksum': snapshot_checksum,
            'approval_count': len(approvals),
        },
    )

    return {
        "execution_id": execution_id,
        "status": "awaiting_approval" if approvals else "pending",
        "approval_ids": [approval['id'] for approval in approvals],
        "playbook_version_id": snapshot_id,
        "playbook_version_number": snapshot_version,
        "playbook_version_checksum": snapshot_checksum,
        "change_order_number": (resolved_change_order or {}).get('order_number'),
        "change_order_auto_matched": auto_matched_change_order,
    }

# ════════════════════════════════════════════════════════════════════
# WebSocket: /ws/playbook/{execution_id}
# ════════════════════════════════════════════════════════════════════

@router.websocket("/ws/playbook/{execution_id}")
async def playbook_ws(websocket: WebSocket, execution_id: str):
    # Authenticate via query param: ?token=xxx
    token = websocket.query_params.get('token', '')
    if not token:
        await websocket.close(code=1008, reason="Missing authentication token")
        return
    from api.users import validate_session_token
    ws_user = validate_session_token(token)
    if not ws_user:
        await websocket.close(code=1008, reason="Invalid or expired session")
        return

    conn = get_db_connection()
    try:
        _assert_execution_scope(conn, execution_id, ws_user, action='view')
    except HTTPException as exc:
        await websocket.close(code=1008, reason=str(exc.detail))
        return
    finally:
        conn.close()

    await ws_manager.connect(execution_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == 'ping':
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(execution_id, websocket)



@router.post("/playbooks/executions/{execution_id}/confirm-commit")
async def confirm_commit(execution_id: str, user=require_permission("playbook", "execute")):
    """
    P3 Commit Confirmed：取消该次执行的定时自动回滚任务，正式确认变更。
    须在 commit_confirmed_ttl 秒内调用，否则自动回滚已触发。
    """
    conn = get_db_connection()
    try:
        _assert_execution_scope(conn, execution_id, user, action='execute')
    finally:
        conn.close()

    task = _pending_rollbacks.pop(execution_id, None)
    if task:
        task.cancel()
        logger.info(f"Commit confirmed for execution {execution_id}, auto-rollback cancelled")
        return {"status": "confirmed", "execution_id": execution_id,
                "message": "Commit confirmed. Auto-rollback cancelled."}
    return {"status": "no_pending", "execution_id": execution_id,
            "message": "No pending commit confirmation found (already confirmed or timed out)."}
