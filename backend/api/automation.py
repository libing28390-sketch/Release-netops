from fastapi import APIRouter, HTTPException, Body, Request, Depends, Query
from fastapi.responses import JSONResponse
import os
import uuid
import json
import re
import hashlib
from datetime import datetime, timezone
from ping3 import ping
from database import get_db_connection
import logging
import asyncio

from core.tenant_policy import TENANT_ISOLATION_ENABLED, tenant_id_for_write, tenant_scope_for_user
from services.automation_service import AutomationService
from services.audit_service import log_audit_event
from api.devices import _assert_operational_data_device_scope, _record_instant_execution
from services.config_approval_service import (
    list_approvers_with_methods,
    request_approval,
    verify_code,
    consume_approval,
    approval_manifest_hash,
)
from core.rbac import enforce_resource_scope, is_global_administrator, require_role
from services.vault_service import resolve_device_credentials
from services.scheduled_job_authorization import (
    authorize_job_resource,
    manifest_hash as scheduled_manifest_hash,
    normalize_job_manifest,
    scheduled_job_approval_type,
    script_snapshot,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# ── Helper to resolve the nested Depends issue ──
# Because rbac.require_role returns a Depends object, we extract the underlying function
def get_operator(user=require_role("Operator")):
    return user

def get_viewer(user=require_role("Viewer")):
    return user

def get_admin(user=require_role("Administrator")):
    return user


def _first_complete_credential_pair(*pairs: tuple[str, str]) -> tuple[str, str]:
    for username, password in pairs:
        if username and password:
            return username, password
    return '', ''


def _assert_execution_auth_role_allowed(user: dict, auth_role: str) -> None:
    if str(auth_role or '').strip().lower() == 'admin' and user.get('role') != 'Administrator':
        raise HTTPException(status_code=403, detail='使用设备特权账号需要管理员身份')


def _resolve_execution_credentials(device: dict, auth_role: str = 'normal') -> dict:
    """Resolve paired plaintext credentials for automation command execution."""
    creds = resolve_device_credentials(device)
    role = str(auth_role or 'normal').lower().strip()

    if role == 'admin':
        username, password = _first_complete_credential_pair(
            (creds.get('admin_username') or '', creds.get('admin_password') or ''),
        )
    else:
        username, password = _first_complete_credential_pair(
            (creds.get('normal_username') or '', creds.get('normal_password') or ''),
        )

    return {
        'username': username,
        'password': password,
        # Netmiko drivers automatically enter enable mode when this is set.
        # Only the explicitly authorized privileged-account path may receive it.
        'enable_password': (creds.get('enable_password') or '') if role == 'admin' else '',
        'resolved_role': role,
    }

# ── Script Management CRUD ──

def _script_tenant_for_actor(user: dict, requested_tenant: str = '') -> str:
    actor_tenant = str(user.get('tenant_id') or '').strip()
    global_admin = is_global_administrator(user)
    requested_tenant = str(requested_tenant or '').strip()
    if not TENANT_ISOLATION_ENABLED:
        return tenant_id_for_write(requested=requested_tenant, user=user)
    if requested_tenant:
        if not global_admin and requested_tenant != actor_tenant:
            raise HTTPException(status_code=403, detail='脚本只能归属当前账号所在租户')
        return requested_tenant
    if actor_tenant:
        return actor_tenant
    if global_admin:
        return 'tenant-default'
    raise HTTPException(status_code=403, detail='当前账号未绑定租户')


def _assert_script_row_scope(user: dict, row: dict, action: str) -> str:
    tenant_id = str(row.get('tenant_id') or '').strip()
    if TENANT_ISOLATION_ENABLED and not tenant_id and not is_global_administrator(user):
        raise HTTPException(status_code=404, detail='Script not found')
    if TENANT_ISOLATION_ENABLED and not is_global_administrator(user) and tenant_scope_for_user(user) != tenant_id:
        raise HTTPException(status_code=404, detail='Script not found')
    enforce_resource_scope(user, 'script', action, tenant_id=tenant_id)
    return tenant_id


def _resolve_script_approver(conn, approver_username: str, tenant_id: str, requester_id: str) -> dict:
    username = str(approver_username or '').strip()
    if not username:
        raise HTTPException(status_code=400, detail='请选择脚本审批人')
    query = """SELECT id, username, role, role_profile, status, tenant_id, scope_mode
                 FROM users WHERE LOWER(username) = LOWER(?)"""
    params = (username,)
    if TENANT_ISOLATION_ENABLED:
        query += " AND tenant_id = ?"
        params = (username, tenant_id)
    row = conn.execute(query, params).fetchone()
    if not row or str(row['status'] or '') != 'active':
        message = '审批人必须是当前租户内的有效账号' if TENANT_ISOLATION_ENABLED else '审批人必须是有效账号'
        raise HTTPException(status_code=400, detail=message)
    approver = dict(row)
    if str(approver.get('id') or '') == str(requester_id or ''):
        raise HTTPException(status_code=403, detail='审批回避原则：审核人不能是提单人本人')
    enforce_resource_scope(approver, 'script', 'approve', tenant_id=tenant_id)
    enforce_resource_scope(approver, 'script', 'publish', tenant_id=tenant_id)
    return approver


def _script_content_hash(content: object) -> str:
    return hashlib.sha256(str(content or '').encode('utf-8')).hexdigest()

@router.get("/scripts")
async def read_scripts(
    q: str = Query('', description='Search script name, id or description'),
    platform: str = Query('', description='Platform or platform group'),
    category: str = Query('', description='Script category'),
    script_type: str = Query('', description='Script type'),
    status: str = Query('', description='Script status'),
    page: int | None = Query(None, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_viewer),
):
    conn = get_db_connection()
    try:
        clauses: list[str] = []
        params: list[str] = []
        tenant_id = None if is_global_administrator(user) else tenant_scope_for_user(user)
        if TENANT_ISOLATION_ENABLED and tenant_id is None and not is_global_administrator(user):
            _script_tenant_for_actor(user)
        if tenant_id is not None:
            enforce_resource_scope(user, 'script', 'view', tenant_id=tenant_id)
            clauses.append('tenant_id = ?')
            params.append(tenant_id)
        else:
            enforce_resource_scope(user, 'script', 'view')
        if q.strip():
            clauses.append("(LOWER(id) LIKE ? OR LOWER(name) LIKE ? OR LOWER(COALESCE(description, '')) LIKE ?)")
            fuzzy = f"%{q.strip().lower()}%"
            params.extend([fuzzy, fuzzy, fuzzy])
        if platform and platform.lower() not in ('all', 'any'):
            groups = {
                'linux': ['linux', 'ubuntu', 'centos', 'debian', 'redhat'],
                'cisco': ['cisco_ios', 'cisco_nxos', 'cisco_xr', 'cisco_asa', 'cisco'],
                'huawei': ['huawei_vrp', 'huawei_vrpv8', 'huawei'],
                'h3c': ['h3c_comware', 'h3c'],
                'juniper': ['juniper_junos', 'juniper'],
                'arista': ['arista_eos', 'arista'],
            }
            values = groups.get(platform.lower(), [platform])
            placeholders = ','.join('?' for _ in values)
            clauses.append(f"LOWER(COALESCE(platform, '')) IN ({placeholders})")
            params.extend(value.lower() for value in values)
        if category and category.lower() not in ('all', 'any'):
            if category.lower() == 'inspection':
                clauses.append("LOWER(COALESCE(category, '')) IN ('inspection', 'standard')")
            elif category.lower() == 'system':
                clauses.append("(LOWER(COALESCE(submitter_name, '')) = 'system' OR LOWER(COALESCE(author, '')) = 'system')")
            else:
                clauses.append("LOWER(COALESCE(category, '')) = ?")
                params.append(category.lower())
        if script_type and script_type.lower() not in ('all', 'any'):
            clauses.append("LOWER(COALESCE(script_type, '')) = ?")
            params.append(script_type.lower())
        if status and status.lower() not in ('all', 'any'):
            clauses.append("LOWER(COALESCE(status, '')) = ?")
            params.append(status.lower())

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ''
        if page is None:
            scripts = conn.execute(f'SELECT * FROM scripts{where} ORDER BY updated_at DESC', tuple(params)).fetchall()
            return [dict(s) for s in scripts]

        total_row = conn.execute(f'SELECT COUNT(*) AS total FROM scripts{where}', tuple(params)).fetchone()
        total = int(total_row['total'] or 0) if total_row else 0
        offset = (page - 1) * page_size
        rows = conn.execute(
            f'SELECT * FROM scripts{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?',
            tuple(params + [page_size, offset]),
        ).fetchall()
        return {
            'items': [dict(row) for row in rows],
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': max(1, (total + page_size - 1) // page_size),
        }
    finally:
        conn.close()


@router.get("/scripts/approvers")
def list_script_approvers(user: dict = Depends(get_operator)):
    tenant_id = _script_tenant_for_actor(user)
    enforce_resource_scope(user, 'script', 'submit', tenant_id=tenant_id)
    conn = get_db_connection()
    try:
        query = """SELECT id, username, role, role_profile, status, tenant_id, scope_mode
                     FROM users WHERE status = 'active'"""
        params = ()
        if TENANT_ISOLATION_ENABLED:
            query += " AND tenant_id = ?"
            params = (tenant_id,)
        rows = conn.execute(query + " ORDER BY username", params).fetchall()
        items = []
        for row in rows:
            approver = dict(row)
            try:
                enforce_resource_scope(approver, 'script', 'approve', tenant_id=tenant_id)
                enforce_resource_scope(approver, 'script', 'publish', tenant_id=tenant_id)
            except HTTPException:
                continue
            items.append({
                'id': str(approver.get('id') or ''),
                'username': str(approver.get('username') or ''),
                'role': str(approver.get('role') or ''),
            })
        return {'items': items}
    finally:
        conn.close()

@router.post("/scripts")
async def create_script(script: dict = Body(...), user: dict = Depends(get_operator)):
    script_id = str(script.get('id') or '').strip()
    tenant_id = _script_tenant_for_actor(user, script.get('tenant_id') or '')
    enforce_resource_scope(user, 'script', 'create', tenant_id=tenant_id)
    actor_id = str(user.get('user_id') or user.get('id') or '').strip()
    submitter = str(user.get('username') or '').strip()
    if not actor_id or not submitter:
        raise HTTPException(status_code=403, detail='脚本操作需要稳定的用户身份')
    
    if not re.match(r'^[a-zA-Z0-9_\-]+$', script_id):
        raise HTTPException(status_code=400, detail="标识码(Code ID)仅支持英文、数字和下划线")

    conn = get_db_connection()
    now = datetime.now(timezone.utc).isoformat()
    try:
        status = str(script.get('status') or 'draft').strip().lower()
        if status not in {'draft', 'pending_audit'}:
            raise HTTPException(status_code=403, detail='新脚本必须先保存草稿或提交独立审批')
        content = str(script.get('content') or '')
        approver_username = ''
        approver_id = ''
        content_sha256 = ''
        if status == 'pending_audit':
            enforce_resource_scope(user, 'script', 'submit', tenant_id=tenant_id)
            approver = _resolve_script_approver(
                conn, str(script.get('approver_username') or ''), tenant_id, actor_id,
            )
            approver_username = str(approver['username'])
            approver_id = str(approver['id'])
            if not content.strip():
                raise HTTPException(status_code=400, detail='提交审批的脚本内容不能为空')
            content_sha256 = _script_content_hash(content)
        conn.execute('''
            INSERT INTO scripts (
                id, name, platform, description, content, 
                script_type, category, author, version, status, 
                submitter_name, approver_username, created_at, updated_at,
                created_by_id, tenant_id, approver_id, approved_by_id, content_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            script_id, script.get('name'), script.get('platform'), script.get('description'), 
            content, script.get('script_type', 'shell'), script.get('category', 'custom'), submitter,
            script.get('version', 'v1.0.0'), status,
            submitter, approver_username, now, now,
            actor_id, tenant_id, approver_id, '', content_sha256,
        ))
        log_audit_event(
            event_type='SCRIPT_CREATE', category='automation', severity='medium', status='success',
            summary=f"Created script {script_id}", actor_id=actor_id,
            actor_username=submitter, actor_role=user.get('role'), target_type='script',
            target_id=script_id, target_name=str(script.get('name') or script_id),
            details={'status': status, 'tenant_id': tenant_id, 'content_sha256': content_sha256}, conn=conn,
        )
        conn.commit()
        return {"success": True, "id": script_id}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to create script: {e}")
        raise HTTPException(status_code=409 if 'unique' in str(e).lower() else 500, detail='Failed to create script')
    finally:
        conn.close()

@router.put("/scripts/{script_id}")
async def update_script(script_id: str, script: dict = Body(...), user: dict = Depends(get_operator)):
    conn = get_db_connection()
    now = datetime.now(timezone.utc).isoformat()
    actor_id = str(user.get('user_id') or user.get('id') or '').strip()
    actor_name = str(user.get('username') or '').strip()
    
    try:
        existing = conn.execute('SELECT * FROM scripts WHERE id = ?', (script_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Script not found")
        current = dict(existing)
        current_status = str(current.get('status') or 'draft').strip().lower()
        target_status = str(script.get('status') or current_status).strip().lower()
        tenant_id = _assert_script_row_scope(
            user, current, 'approve' if current_status == 'pending_audit' else 'edit_draft',
        )
        if current.get('status') == 'released':
            raise HTTPException(status_code=409, detail='已发布脚本不可修改；请以新脚本 ID 提交新版本')
        if not actor_id:
            raise HTTPException(status_code=403, detail='脚本操作需要稳定的用户身份')
        is_admin = user.get('role') == 'Administrator'
        if current_status != 'pending_audit' and not is_admin and str(current.get('created_by_id') or '') != actor_id:
            raise HTTPException(status_code=403, detail='只有脚本提交人或租户管理员可以编辑草稿')

        if current_status == 'pending_audit':
            actual_hash = _script_content_hash(current.get('content'))
            if actual_hash != str(current.get('content_sha256') or ''):
                raise HTTPException(status_code=409, detail='待审批脚本内容与提交快照不一致，必须重新提交')
            if str(script.get('content', current.get('content')) or '') != str(current.get('content') or ''):
                raise HTTPException(status_code=409, detail='待审批期间脚本内容不可修改')
            if target_status not in {'released', 'rejected'}:
                raise HTTPException(status_code=409, detail='待审批脚本只能由指定审批人批准或驳回')
            if str(current.get('approver_id') or '') != actor_id:
                raise HTTPException(status_code=403, detail='当前账号不是该脚本的指定审批人')
            enforce_resource_scope(user, 'script', 'approve', tenant_id=tenant_id)
            if target_status == 'released':
                enforce_resource_scope(user, 'script', 'publish', tenant_id=tenant_id)
            approved_by_id = actor_id if target_status == 'released' else ''
            conn.execute(
                """UPDATE scripts SET status = ?, approved_by_id = ?,
                          rejected_reason = ?, updated_at = ? WHERE id = ?""",
                (target_status, approved_by_id, str(script.get('rejected_reason') or '')[:2000], now, script_id),
            )
            log_audit_event(
                event_type='SCRIPT_REVIEW', category='automation', severity='high', status=target_status,
                summary=f"{target_status.title()} script {script_id}", actor_id=actor_id,
                actor_username=actor_name, actor_role=user.get('role'), target_type='script',
                target_id=script_id, target_name=str(current.get('name') or script_id),
                details={'content_sha256': actual_hash, 'tenant_id': tenant_id}, conn=conn,
            )
        elif current_status in {'draft', 'rejected'}:
            if target_status not in {'draft', 'pending_audit'}:
                raise HTTPException(status_code=403, detail='草稿必须先提交独立审批，不能直接发布')
            content = str(script.get('content', current.get('content')) or '')
            approver_username = ''
            approver_id = ''
            content_sha256 = ''
            if target_status == 'pending_audit':
                enforce_resource_scope(user, 'script', 'submit', tenant_id=tenant_id)
                approver = _resolve_script_approver(
                    conn,
                    str(script.get('approver_username') or current.get('approver_username') or ''),
                    tenant_id,
                    actor_id,
                )
                if not content.strip():
                    raise HTTPException(status_code=400, detail='提交审批的脚本内容不能为空')
                approver_username = str(approver['username'])
                approver_id = str(approver['id'])
                content_sha256 = _script_content_hash(content)
            fields = {
                'name': script.get('name', current.get('name')),
                'platform': script.get('platform', current.get('platform')),
                'description': script.get('description', current.get('description')),
                'content': content,
                'script_type': script.get('script_type', current.get('script_type')),
                'category': script.get('category', current.get('category')),
                'version': script.get('version', current.get('version')),
                'status': target_status,
                'approver_username': approver_username,
                'approver_id': approver_id,
                'approver_id': approver_id,
                'approved_by_id': '',
                'content_sha256': content_sha256,
                'rejected_reason': '',
                'updated_at': now,
            }
            conn.execute(
                'UPDATE scripts SET ' + ', '.join(f'{key} = ?' for key in fields) + ' WHERE id = ?',
                (*fields.values(), script_id),
            )
            log_audit_event(
                event_type='SCRIPT_UPDATE' if target_status == 'draft' else 'SCRIPT_SUBMIT',
                category='automation', severity='medium', status='success',
                summary=f"{target_status.title()} script {script_id}", actor_id=actor_id,
                actor_username=actor_name, actor_role=user.get('role'), target_type='script',
                target_id=script_id, target_name=str(fields['name'] or script_id),
                details={'content_sha256': content_sha256, 'tenant_id': tenant_id}, conn=conn,
            )
        else:
            raise HTTPException(status_code=409, detail='脚本状态无效，不能继续流转')
        conn.commit()
        return {"success": True}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to update script {script_id}: {e}")
        raise HTTPException(status_code=500, detail='Failed to update script')
    finally:
        conn.close()

@router.delete("/scripts/{script_id}")
async def delete_script(script_id: str, user: dict = Depends(get_admin)):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM scripts WHERE id = ?', (script_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Script not found')
        current = dict(row)
        tenant_id = _assert_script_row_scope(user, current, 'delete')
        conn.execute('DELETE FROM scripts WHERE id = ?', (script_id,))
        log_audit_event(
            event_type='SCRIPT_DELETE', category='automation', severity='high', status='success',
            summary=f"Deleted script {script_id}", actor_id=str(user.get('user_id') or user.get('id') or ''),
            actor_username=user.get('username'), actor_role=user.get('role'), target_type='script',
            target_id=script_id, target_name=str(current.get('name') or script_id),
            details={'tenant_id': tenant_id, 'content_sha256': current.get('content_sha256') or ''}, conn=conn,
        )
        conn.commit()
        return {"success": True}
    except HTTPException:
        conn.rollback()
        raise
    finally:
        conn.close()

# ── Execution & Task Routes ──

def _normalize_execution_commands(value) -> list[str]:
    if isinstance(value, str):
        raw_lines = value.splitlines()
    elif isinstance(value, list):
        raw_lines = []
        for item in value:
            if not isinstance(item, str):
                raise HTTPException(status_code=400, detail='Commands must be text')
            raw_lines.extend(item.splitlines())
    else:
        return []
    return [line.strip() for line in raw_lines if line and line.strip()]


def _is_h3c_read_only_command_batch(device: dict, commands: list[str]) -> bool:
    """Keep H3C display/show commands in operational mode, one command at a time."""
    from core.platform_utils import normalize_device_platform

    platform = normalize_device_platform('', str(device.get('platform') or ''))
    if platform != 'h3c_comware' or not commands:
        return False
    return all(re.match(r'^(?:display|show)(?:\s|$)', command, re.IGNORECASE) for command in commands)


def _resolve_change_order_target_ids(conn, target_devices: list) -> list[str]:
    resolved: list[str] = []
    for target in target_devices:
        if not isinstance(target, dict):
            raise HTTPException(status_code=409, detail='变更单目标设备格式无效')
        device_id = str(target.get('device_id') or target.get('id') or '').strip()
        ip_address = str(target.get('ip_address') or '').strip()
        hostname = str(target.get('hostname') or '').strip()
        if device_id:
            matches = conn.execute('SELECT id FROM devices WHERE id = ?', (device_id,)).fetchall()
        else:
            clauses = []
            values = []
            if ip_address:
                clauses.append('ip_address = ?')
                values.append(ip_address)
            if hostname:
                clauses.append('hostname = ?')
                values.append(hostname)
            if not clauses:
                raise HTTPException(status_code=409, detail='变更单目标设备缺少稳定标识')
            matches = conn.execute(
                f"SELECT id FROM devices WHERE {' OR '.join(clauses)}",
                tuple(values),
            ).fetchall()
        if len(matches) != 1:
            raise HTTPException(status_code=409, detail='变更单目标设备无法唯一匹配资产记录')
        resolved.append(str(matches[0]['id']))
    if not resolved or len(set(resolved)) != len(resolved):
        raise HTTPException(status_code=409, detail='变更单目标设备为空或包含重复项')
    return resolved


async def _execute_approved_change_order(
    conn,
    *,
    order_number: str,
    requested_device_ids: list[str],
    requested_commands: list[str],
    auth_role: str,
    user: dict,
) -> dict:
    import hashlib
    import database as database_module
    from core.rbac import enforce_resource_scope
    from services.change_order_service import get_change_order
    from api.change_orders.helpers import (
        APPROVAL_SNAPSHOT_VERSION,
        approval_snapshot_hash,
        assert_change_order_window_open,
        assert_explicit_execution_profile,
        assert_order_mfa_valid,
        resolve_active_order_implementer,
    )

    if database_module._USE_PG:
        conn.execute('SELECT id FROM change_orders WHERE order_number = ? FOR UPDATE', (order_number,))
    row = conn.execute('SELECT id FROM change_orders WHERE order_number = ?', (order_number,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='变更工单不存在')
    order = get_change_order(conn, str(row['id']))
    if not order or str(order.get('status') or '') != 'implementing':
        raise HTTPException(status_code=409, detail='只有已进入实施阶段的变更工单可以执行')

    actor_id = str(user.get('user_id') or user.get('id') or '')
    actor_name = str(user.get('username') or '')
    tenant_id = str(order.get('tenant_id') or '').strip()
    actor_row = conn.execute(
        'SELECT id, username, role, role_profile, status, tenant_id, scope_mode FROM users WHERE id = ?',
        (actor_id,),
    ).fetchone()
    if not actor_row or str(actor_row['status'] or '').lower() != 'active':
        raise HTTPException(status_code=403, detail='当前账号已停用或不可用')
    actor_name = str(actor_row['username'] or actor_name)
    execution_user = {**user, **dict(actor_row), 'user_id': actor_id}
    implementer = resolve_active_order_implementer(conn, order)
    executor_id = str(implementer.get('id') or '').strip()
    approver_id = str(order.get('final_approver_id') or order.get('approver_id') or '')
    if not actor_id or actor_id != executor_id:
        raise HTTPException(status_code=403, detail='当前账号不是变更工单指定的实施人')
    if TENANT_ISOLATION_ENABLED and (not tenant_id or tenant_scope_for_user(execution_user) != tenant_id):
        raise HTTPException(status_code=404, detail='变更工单不存在')
    if not approver_id or approver_id == actor_id:
        raise HTTPException(status_code=403, detail='终审人不能作为该工单的实施人')
    enforce_resource_scope(execution_user, 'pam', 'intervene', tenant_id=tenant_id)
    assert_explicit_execution_profile(execution_user, 'command')

    expected_snapshot = approval_snapshot_hash(order)
    result_detail = order.get('result_detail') if isinstance(order.get('result_detail'), dict) else {}
    if int(result_detail.get('approval_snapshot_version') or 0) != APPROVAL_SNAPSHOT_VERSION:
        raise HTTPException(status_code=409, detail='工单使用旧版审批快照，必须重新审批')
    if (
        not expected_snapshot
        or str(result_detail.get('approval_snapshot_hash') or '') != expected_snapshot
        or str(result_detail.get('executing_snapshot_hash') or '') != expected_snapshot
    ):
        raise HTTPException(status_code=409, detail='工单批准快照缺失或已变化，必须重新审批')
    if not str(result_detail.get('execution_token_id') or '').strip() or not str(result_detail.get('execution_token_consumed_at') or '').strip():
        raise HTTPException(status_code=409, detail='工单缺少有效的单次执行授权')
    if result_detail.get('execution_started_at'):
        raise HTTPException(status_code=409, detail='该工单的执行授权已被消费，不能重复执行')
    assert_order_mfa_valid(order, actor_id, actor_name)
    assert_change_order_window_open(order)

    approved_commands = _normalize_execution_commands(order.get('commands'))
    if not approved_commands or requested_commands != approved_commands:
        raise HTTPException(status_code=409, detail='执行命令与最终审批的工单命令不一致')
    expected_device_ids = _resolve_change_order_target_ids(conn, order.get('target_devices') or [])
    if (
        len(requested_device_ids) != len(set(requested_device_ids))
        or set(requested_device_ids) != set(expected_device_ids)
        or len(requested_device_ids) != len(expected_device_ids)
    ):
        raise HTTPException(status_code=409, detail='执行目标设备与最终审批的工单范围不一致')

    placeholders = ','.join('?' for _ in requested_device_ids)
    device_rows = conn.execute(
        f'SELECT * FROM devices WHERE id IN ({placeholders})', tuple(requested_device_ids),
    ).fetchall()
    devices_by_id = {str(item['id']): dict(item) for item in device_rows}
    if set(devices_by_id) != set(requested_device_ids):
        raise HTTPException(status_code=409, detail='工单目标设备已从资产库删除')
    for device in devices_by_id.values():
        device_tenant = str(device.get('tenant_id') or '')
        if TENANT_ISOLATION_ENABLED and device_tenant != tenant_id:
            raise HTTPException(status_code=403, detail='工单包含其他租户的设备')
        scope = {
            'tenant_id': device_tenant,
            'site_id': device.get('site_id') or device.get('site'),
            'device_group_id': device.get('device_group_id'),
        }
        enforce_resource_scope(execution_user, 'command', 'execute', **scope)
        if auth_role == 'admin':
            _assert_execution_auth_role_allowed(execution_user, auth_role)
            enforce_resource_scope(execution_user, 'credential', 'use', **scope)

    execution_fingerprint = hashlib.sha256(json.dumps({
        'order_id': str(order.get('id') or ''),
        'snapshot': expected_snapshot,
        'device_ids': sorted(requested_device_ids),
        'commands': requested_commands,
        'actor_id': actor_id,
    }, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    updated_detail = {
        **result_detail,
        'execution_started_at': started_at,
        'execution_started_by': actor_id,
        'execution_request_hash': execution_fingerprint,
    }
    conn.execute(
        "UPDATE change_orders SET result_detail_json = ?, updated_at = ? WHERE id = ? AND status = 'implementing'",
        (json.dumps(updated_detail, ensure_ascii=False, sort_keys=True), started_at, str(order['id'])),
    )
    conn.commit()

    service = AutomationService()
    batch_results: dict[str, dict] = {}
    for device_id in requested_device_ids:
        device = devices_by_id[device_id]
        try:
            credentials = _resolve_execution_credentials(device, auth_role)
            device['username'] = credentials['username']
            device['password'] = credentials['password']
            device['enable_password'] = credentials['enable_password']
            use_operational_mode = _is_h3c_read_only_command_batch(device, approved_commands)
            rows = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda d=device, operational=use_operational_mode: service.execute_commands(
                    d, approved_commands, is_config=not operational,
                ),
            )
            lines = []
            all_success = bool(rows)
            if use_operational_mode and len(rows) != len(approved_commands):
                all_success = False
                lines.append(
                    f'Error: Received {len(rows)} of {len(approved_commands)} command results; '
                    'the remaining commands may not have run.'
                )
            from drivers.ssh_compat import contains_paging_prompt
            for result in rows:
                success = bool(result.get('success')) if isinstance(result, dict) else False
                output = str((result or {}).get('output') or (result or {}).get('stdout') or '') if isinstance(result, dict) else ''
                paginated = contains_paging_prompt(output)
                if output:
                    lines.append(output)
                if paginated:
                    all_success = False
                    lines.append('Error: CLI output stopped at a pagination prompt and is incomplete.')
                elif not success:
                    all_success = False
                    error = str((result or {}).get('error') or (result or {}).get('stderr') or 'Command failed')
                    lines.append(f'Error: {error}')
            output_text = '\n'.join(lines)
            from services.pam_audit_service import redact_output
            safe_output, _ = redact_output(output_text)
            _record_instant_execution(
                device_id, f"ChangeOrder {order_number}", approved_commands,
                'completed' if all_success else 'failed',
                platform=device.get('platform') or 'unknown', output=output_text, device_info=device,
            )
            batch_results[device_id] = {
                'status': 'success' if all_success else 'failed',
                'output': safe_output,
                'commands': approved_commands,
            }
        except Exception as exc:
            from services.pam_audit_service import redact_output
            safe_error, _ = redact_output(str(exc))
            _record_instant_execution(
                device_id, f"ChangeOrder {order_number}", approved_commands, 'failed',
                platform=device.get('platform') or 'unknown', error=safe_error, device_info=device,
            )
            batch_results[device_id] = {'status': 'failed', 'output': f'Error: {safe_error}', 'commands': approved_commands}

    execution_status = 'completed' if all(item['status'] == 'success' for item in batch_results.values()) else 'partial_failure'
    log_audit_event(
        event_type='CHANGE_ORDER_EXECUTION', category='change_order', severity='high',
        status=execution_status,
        summary=f"Executed approved change order {order_number}",
        actor_id=actor_id, actor_username=actor_name, actor_role=user.get('role'),
        target_type='change_order', target_id=str(order.get('id') or ''),
        target_name=order_number,
        details={
            'order_number': order_number,
            'execution_request_hash': execution_fingerprint,
            'device_count': len(requested_device_ids),
            'command_count': len(approved_commands),
            'result_statuses': {key: value['status'] for key, value in batch_results.items()},
        },
        conn=conn,
    )

    if database_module._USE_PG:
        conn.execute('SELECT id FROM change_orders WHERE id = ? FOR UPDATE', (str(order['id']),))
    latest_order = get_change_order(conn, str(order['id']))
    latest_detail = latest_order.get('result_detail') if latest_order and isinstance(latest_order.get('result_detail'), dict) else {}
    execution_results = latest_detail.get('execution_results')
    if not isinstance(execution_results, list):
        execution_results = []
    execution_results.append({
        'execution_id': execution_fingerprint,
        'started_at': started_at,
        'finished_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'actor': {'id': actor_id, 'username': actor_name},
        'device_statuses': {key: value['status'] for key, value in batch_results.items()},
        'status': execution_status,
    })
    latest_detail['execution_results'] = execution_results
    conn.execute(
        'UPDATE change_orders SET result_detail_json = ?, updated_at = ? WHERE id = ?',
        (json.dumps(latest_detail, ensure_ascii=False, sort_keys=True), datetime.now(timezone.utc).isoformat(), str(order['id'])),
    )
    conn.commit()
    return {'status': execution_status, 'results': batch_results}


@router.post("/execute")
async def execute_task(request: Request, payload: dict = Body(...), user: dict = Depends(get_operator)):
    raw_device_ids = payload.get('device_ids', [])
    if isinstance(raw_device_ids, str):
        try:
            raw_device_ids = json.loads(raw_device_ids)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail='device_ids must be a JSON array')
    if not isinstance(raw_device_ids, list):
        raise HTTPException(status_code=400, detail='device_ids must be a JSON array')
    device_id = str(payload.get('device_id') or '').strip()
    device_ids = [str(value).strip() for value in raw_device_ids if str(value).strip()]
    if device_id and device_id not in device_ids:
        device_ids.insert(0, device_id)
    if not device_ids or len(device_ids) != len(set(device_ids)):
        raise HTTPException(status_code=400, detail='device_id(s) must contain at least one unique device')
    if len(device_ids) > 200:
        raise HTTPException(status_code=400, detail='A single execution is limited to 200 devices')
    if payload.get('script_id'):
        raise HTTPException(status_code=403, detail='直接执行不能运行可变脚本；请使用已发布 Playbook 并关联变更工单')

    commands = _normalize_execution_commands(payload.get('command'))
    if not commands:
        raise HTTPException(status_code=400, detail='No command provided')
    if any(command.startswith('#!') for command in commands):
        raise HTTPException(status_code=403, detail='直接执行不允许运行 Shell 脚本')

    auth_role = str(payload.get('auth_role') or payload.get('role') or 'normal').strip().lower()
    if auth_role not in {'normal', 'admin'}:
        raise HTTPException(status_code=400, detail='auth_role must be normal or admin; automatic credential fallback is disabled')
    order_number = str(payload.get('change_ticket') or payload.get('order_number') or '').strip()
    if order_number:
        if not bool(payload.get('isConfig')):
            raise HTTPException(status_code=400, detail='变更工单执行必须声明为配置变更')
        conn = get_db_connection()
        try:
            return await _execute_approved_change_order(
                conn,
                order_number=order_number,
                requested_device_ids=device_ids,
                requested_commands=commands,
                auth_role=auth_role,
                user=user,
            )
        finally:
            conn.close()

    if bool(payload.get('isConfig')) or payload.get('approval_token'):
        raise HTTPException(status_code=403, detail='配置变更必须通过已批准并进入实施阶段的变更工单执行')

    from core.rbac import enforce_resource_scope
    from api.change_orders.helpers import assert_explicit_execution_profile
    assert_explicit_execution_profile(user, 'command')
    from services.platform_registry_service import (
        PlatformRegistryError,
        execute_platform_action,
        preview_platform_action,
        resolve_device_action_code,
    )
    conn = get_db_connection()
    try:
        placeholders = ','.join('?' for _ in device_ids)
        rows = conn.execute(
            f'SELECT * FROM devices WHERE id IN ({placeholders})',
            tuple(device_ids),
        ).fetchall()
        devices_by_id = {str(row['id']): dict(row) for row in rows}
        if set(devices_by_id) != set(device_ids):
            raise HTTPException(status_code=404, detail='One or more target devices were not found')
        for target_id in device_ids:
            _assert_operational_data_device_scope(user, devices_by_id[target_id])
        actions: dict[str, list[str]] = {}
        for target_id in device_ids:
            actions[target_id] = []
            for command in commands:
                try:
                    action_code = resolve_device_action_code(target_id, command)
                    if not action_code:
                        raise HTTPException(status_code=403, detail=f'命令未绑定到当前已发布平台动作：{command[:80]}')
                    preview_platform_action(target_id, action_code, user=user)
                    actions[target_id].append(action_code)
                except PlatformRegistryError as exc:
                    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        results: dict[str, dict] = {}
        for target_id in device_ids:
            action_rows = []
            outputs = []
            for command, action_code in zip(commands, actions[target_id]):
                try:
                    result = execute_platform_action(
                        target_id, action_code, user=user, include_raw_output=True,
                    )
                except PlatformRegistryError as exc:
                    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
                output = str(result.get('raw_output') or '')
                action_rows.append({
                    'command': command,
                    'action_code': action_code,
                    'success': bool(result.get('success')),
                    'output': output,
                    'records': result.get('records') or [],
                    'parse_status': result.get('parse_status'),
                    'error': result.get('error') or '',
                })
                outputs.append(output or json.dumps(result.get('records') or [], ensure_ascii=False))
            output_text = '\n'.join(outputs)
            success = all(item['success'] for item in action_rows)
            _record_instant_execution(
                target_id, payload.get('task_name') or 'Published Platform Action Query',
                commands, 'completed' if success else 'failed',
                platform=devices_by_id[target_id].get('platform') or 'unknown',
                output=output_text, device_info=devices_by_id[target_id],
            )
            results[target_id] = {'status': 'success' if success else 'failed', 'output': output_text, 'commands': action_rows}
        if len(device_ids) > 1:
            return {'status': 'completed', 'results': results}
        return {'status': 'success' if results[device_ids[0]]['status'] == 'success' else 'failed', **results[device_ids[0]]}
    finally:
        conn.close()


@router.get("/config-approval/approvers")
def list_config_approval_approvers(user: dict = Depends(get_operator)):
    """List eligible approvers across tenants, excluding the current requester."""
    requester_id = str(user.get('user_id') or user.get('id') or '').strip()
    if not requester_id:
        raise HTTPException(status_code=401, detail='Authenticated user ID is unavailable')
    return {
        "success": True,
        "data": list_approvers_with_methods(
            tenant_id_for_write(user=user),
            requester_id=requester_id,
        ),
    }


def _build_approval_manifest(approval_type: str, payload: dict, user: dict) -> dict:
    source = payload.get('operation_manifest')
    if not isinstance(source, dict) or not source:
        raise HTTPException(status_code=400, detail='审批申请必须包含待批准操作清单')
    requester_id = str(user.get('user_id') or user.get('id') or '')
    tenant_id = str(user.get('tenant_id') or '')
    if approval_type in {'alert_rule', 'alert_rule_delete'}:
        from services.alert_rule_service import build_alert_rule_approval_manifest

        operation = str(source.get('operation') or '').strip().upper()
        expected_operations = {'CREATE', 'UPDATE', 'TOGGLE'} if approval_type == 'alert_rule' else {'DELETE'}
        if operation not in expected_operations:
            raise HTTPException(status_code=400, detail='审批类型与告警规则操作不匹配')
        try:
            return build_alert_rule_approval_manifest(
                payload,
                tenant_id=tenant_id,
                requester_id=requester_id,
                expected_operation=operation,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if approval_type in {'scheduled_job', 'scheduled_job_delete', 'execution_plan'}:
        conn = get_db_connection()
        try:
            manifest_tenant_id = tenant_id_for_write(user=user)
            operation = str(source.get('operation') or '').upper()
            job_id = str(source.get('job_id') or '').strip()
            current = None
            if operation != 'CREATE':
                if not job_id:
                    raise HTTPException(status_code=400, detail='审批清单缺少计划作业 ID')
                row = conn.execute('SELECT * FROM scheduled_jobs WHERE id = ?', (job_id,)).fetchone()
                if not row or dict(row).get('deleted_at'):
                    raise HTTPException(status_code=404, detail='计划作业不存在')
                current = dict(row)
                manifest_tenant_id = str(current.get('tenant_id') or '')
                action = {
                    'UPDATE': 'update', 'ENABLE': 'enable', 'DISABLE': 'disable', 'DELETE': 'delete',
                }.get(operation)
                if not action:
                    raise HTTPException(status_code=400, detail='计划作业操作类型无效')
                try:
                    authorize_job_resource(user, current, action)
                except PermissionError as exc:
                    raise HTTPException(status_code=403, detail=str(exc)) from exc
            try:
                script_sha, _ = script_snapshot(
                    conn, str(source.get('script_id') or ''), require_released=operation != 'DELETE',
                )
            except ValueError as exc:
                # Report stale released content as a conflict before validating
                # the rest of the request, so clients can recover by refreshing it.
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            from services.scheduled_job_authorization import (
                assert_authorization_grant_link_access,
                current_authorization_grant_input,
                normalize_authorization_grant,
                validate_authorization_grant_ticket,
            )
            nested_grant = source.get('authorization_grant')
            top_level_grant = payload.get('authorization_grant')
            if operation in {'CREATE', 'UPDATE', 'ENABLE'}:
                try:
                    normalized_nested = normalize_authorization_grant(nested_grant)
                    normalized_top_level = normalize_authorization_grant(top_level_grant)
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                if normalized_nested != normalized_top_level:
                    raise HTTPException(
                        status_code=400,
                        detail='顶层授权条款必须与审批清单中的授权条款一致',
                    )
            elif not isinstance(nested_grant, dict) and current is not None:
                nested_grant = current_authorization_grant_input(conn, current)
                source = {**source, 'authorization_grant': nested_grant}
            try:
                if isinstance(nested_grant, dict):
                    source = {**source, 'authorization_grant': nested_grant}
                manifest = normalize_job_manifest(
                    source, operation=operation, requester_id=requester_id,
                    tenant_id=manifest_tenant_id, script_sha256=script_sha, job_id=job_id,
                )
                if operation in {'CREATE', 'UPDATE', 'ENABLE'}:
                    validate_authorization_grant_ticket(
                        conn, manifest['authorization_grant'], tenant_id=manifest_tenant_id,
                    )
                    assert_authorization_grant_link_access(conn, manifest['authorization_grant'], user)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if scheduled_job_approval_type(manifest) != approval_type:
                raise HTTPException(status_code=400, detail='审批类型与作业操作不匹配')
            return manifest
        finally:
            conn.close()
    return {
        'operation': source,
        'requester_id': requester_id,
        'tenant_id': tenant_id,
        'approval_type': approval_type,
    }


@router.post("/config-approval/request")
async def request_config_approval(payload: dict = Body(...), user: dict = Depends(get_operator)):
    approver_username = (payload.get('approver_username') or '').strip()
    config_reason = (payload.get('config_reason') or '').strip()
    requester = user.get('username', 'unknown')
    approval_type = str(payload.get('approval_type') or 'config').strip()
    allowed_approval_types = {
        'config', 'scheduled_job', 'scheduled_job_delete',
        'execution_plan', 'alert_rule', 'alert_rule_delete',
    }
    if approval_type not in allowed_approval_types:
        raise HTTPException(status_code=400, detail='不支持的审批业务类型')
    manifest = _build_approval_manifest(approval_type, payload, user)
    token, err = request_approval(
        approver_username=approver_username,
        requester_username=requester,
        requester_id=str(user.get('user_id') or ''),
        requester_tenant_id=tenant_id_for_write(user=user),
        config_reason=config_reason,
        device_hostname=str(payload.get('device_hostname') or ''),
        command_preview=str(payload.get('command_preview') or ''),
        approval_type=approval_type,
        operation_manifest=manifest,
        extra_fields=payload.get('extra_fields') if isinstance(payload.get('extra_fields'), dict) else None,
        verification_method=str(payload.get('verification_method') or 'feishu'),
    )
    if err: raise HTTPException(status_code=400, detail=err)
    return {"success": True, "approval_token": token, "approval_type": approval_type}

@router.post("/config-approval/verify")
async def verify_config_approval(payload: dict = Body(...), user: dict = Depends(get_operator)):
    approval_token = payload.get('approval_token', '').strip()
    code = payload.get('code', '').strip()
    approval_type = str(payload.get('approval_type') or '').strip() or None
    if not approval_type:
        raise HTTPException(status_code=400, detail='审批类型不能为空')
    manifest = _build_approval_manifest(approval_type, payload, user)
    binding_hash = (
        scheduled_manifest_hash(manifest)
        if approval_type in {'scheduled_job', 'scheduled_job_delete', 'execution_plan'}
        else approval_manifest_hash(manifest)
    )
    ok, err = verify_code(
        approval_token,
        code,
        requester_id=str(user.get('user_id') or ''),
        requester_username=str(user.get('username') or ''),
        expected_approval_type=approval_type,
        expected_binding_hash=binding_hash,
    )
    if not ok: raise HTTPException(status_code=400, detail=err)
    return {"success": True}

@router.post("/devices/ping")
async def ping_device(payload: dict = Body(...)):
    ip = payload.get('ip_address')
    delay = await asyncio.get_event_loop().run_in_executor(None, lambda: ping(ip, timeout=2))
    return {"status": "success", "output": f"Time: {delay*1000:.2f}ms"} if delay else JSONResponse(status_code=500, content={"status":"error"})
