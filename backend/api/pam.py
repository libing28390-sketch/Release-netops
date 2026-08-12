"""
PAM (Privileged Access Management) — Controlled Session Gateway

All terminal connections flow through this module:
  1. POST /pam/sessions       — Create a controlled session (returns session_token)
  2. WS   /pam/ws/{token}     — Connect to the session via WebSocket
  3. GET  /pam/sessions       — List sessions (admin monitoring)
  4. POST /pam/sessions/{id}/kill — Force-terminate a session

Security invariants:
  - Frontend NEVER sees credentials
  - All connections are proxied through the system
  - Every session is audited
"""

import uuid
import asyncio
import json
import logging
import time
import os
import threading
import re
import csv
import io
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from core.rbac import require_permission

from database import get_db_connection
from core.config import settings
from services.vault_service import resolve_device_credentials
from services.audit_service import log_audit_event
from services.connection_profile import resolve_ssh_port
from drivers.ssh_compat import build_ssh_error_guidance, get_ssh_error_code
from services.pam_audit_service import (
    CommandAssembler,
    PromptParser,
    assess_command,
    redact_output,
    record_command_output,
    build_command_submission,
    persist_command_submission,
    mark_command_event,
    create_approval_request,
    decide_approval,
    create_change_transaction,
    record_session_intervention,
    create_jit_grant,
    revoke_jit_grant,
    check_jit_grant,
    review_break_glass,
    record_file_transfer,
    create_batch_operation,
    update_batch_progress,
    create_deferred_action,
    detect_behavior_risk,
    reconcile_tacacs_event,
    create_rollback_checkpoint,
    verify_rollback_checkpoint,
    generate_session_summary,
    explain_command_risk,
    queue_external_event,
)

router = APIRouter()
# WebSocket 路由单独放在无依赖的 router，避免 FastAPI 在 WS 握手阶段
# 因 Depends(require_feature) 无法注入 Request 而返回 404。
# WS 自身已通过 session_token 做一次性令牌验证，无需额外 License 依赖。
ws_router = APIRouter()
logger = logging.getLogger(__name__)

# A newly issued PAM token is single-use, but users may need time to switch
# from the dashboard to the terminal window or local protocol assistant.
PAM_SESSION_TOKEN_TTL_MINUTES = 20

# Track active WebSocket sessions for admin kill.
# Value shape: { 'ws': WebSocket, 'loop': asyncio.AbstractEventLoop }
# The loop reference lets us schedule close operations safely from any thread
# (FastAPI may run sync handlers on AnyIO worker threads where there is no
# current event loop).
_active_sessions: dict[str, dict] = {}

# In-memory storage for MFA codes
mfa_store: dict[str, dict] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')


def recover_stale_sessions_on_startup():
    """
    One-time recovery at server startup: close sessions that were left
    in 'connecting' or 'active' state from a previous server instance.
    This is safe because at startup, no WebSocket connections exist yet.
    """
    conn = get_db_connection()
    try:
        now = _utc_now()
        orphaned = conn.execute(
            "SELECT id, connected_at FROM pam_sessions WHERE status IN ('connecting', 'active')"
        ).fetchall()
        for orphan in orphaned:
            oid = orphan['id']
            duration = 0
            if orphan['connected_at']:
                try:
                    start = datetime.fromisoformat(orphan['connected_at'].replace('Z', '+00:00'))
                    duration = int((datetime.now(timezone.utc) - start).total_seconds())
                except Exception:
                    pass
            conn.execute(
                "UPDATE pam_sessions SET status='closed', closed_at=?, close_reason='server_restart', "
                "duration_seconds=?, updated_at=? WHERE id=?",
                (now, duration, now, oid),
            )
        if orphaned:
            conn.commit()
            logger.info(f"[PAM] Recovered {len(orphaned)} stale session(s) from previous server instance")
    except Exception as e:
        logger.warning(f"[PAM] Stale session recovery error: {e}")
    finally:
        conn.close()


# ── Models ───────────────────────────────────────────────────────────

class SessionCreateIn(BaseModel):
    asset_id: str
    access_level: str = 'normal'  # normal | admin
    connect_method: str = 'web'   # web (only supported method now)
    reason: str = ''
    # MFA fields (required for admin access)
    mfa_code: Optional[str] = None
    fixed_pin: Optional[str] = None
    mfa_nonce: Optional[str] = None
    requester_username: str = 'Admin'


class AccessRequestIn(BaseModel):
    asset_id: str
    access_level: str = 'normal'
    reason: str = ''
    requester_username: str = 'unknown'
    requester_user_id: str = ''


class AccessReviewIn(BaseModel):
    reviewer_username: str = 'admin'
    comment: str = ''
    ttl_minutes: int = 5


# ── Helper: resolve login credentials (INTERNAL ONLY) ───────────────

def _resolve_session_creds(device: dict, asset: dict, access_level: str) -> dict:
    """Resolve SSH credentials. This NEVER leaves the backend."""
    from core.crypto import decrypt_credential

    creds = resolve_device_credentials(device)
    platform = (device.get('platform') or '').lower()
    category = str(device.get('device_category') or '').lower()
    is_server = any(p in platform for p in ['linux', 'windows', 'server']) or 'server' in category

    if access_level == 'admin':
        username = (
            creds.get('admin_username')
            or (asset.get('admin_username') if asset else '')
            or ('root' if is_server else 'admin')
        )
        password = creds.get('admin_password') or ''
        # Try asset-level admin password if device-level is empty
        if not password and asset and asset.get('admin_password'):
            password = decrypt_credential(asset['admin_password']) or ''
    else:
        username = (
            creds.get('normal_username')
            or (asset.get('normal_username') if asset else '')
        )
        password = creds.get('normal_password') or ''
        if (not password and asset and (asset.get('normal_password') or asset.get('password'))):
            raw = asset.get('normal_password') or asset.get('password')
            password = decrypt_credential(raw) or ''
        
        # Fallback to level-specific default if still empty
        if not username:
            username = 'user' if is_server else 'admin'

    return {'username': username or '', 'password': password or ''}


def _ssh_failure_message(error: Exception) -> tuple[str, str | None]:
    """Return a safe user-facing PAM SSH error without exposing credentials."""
    raw_error = str(error or '').strip()
    error_code = get_ssh_error_code(raw_error)
    if error_code:
        return f'{error_code}: {build_ssh_error_guidance(raw_error)}', error_code
    return f'ssh_connection_failed: {raw_error or "SSH connection failed"}', None


def _verify_mfa(username: str, fixed_pin: str, mfa_code: str, mfa_nonce: Optional[str] = None) -> tuple[bool, str]:
    """Verify MFA (fixed PIN + dynamic code). Returns (success, error_msg)."""
    import bcrypt
    import time

    if not username:
        return False, '无法识别当前用户身份'

    conn = get_db_connection()
    try:
        user_row = conn.execute(
            "SELECT fixed_pin, mfa_enabled, mfa_secret FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        if not user_row:
            return False, '用户不存在'

        if user_row['mfa_enabled'] == 1 and user_row['mfa_secret']:
            from api.users import verify_totp
            if not verify_totp(user_row['mfa_secret'], str(fixed_pin)):
                return False, '动态身份验证码验证失败'
        else:
            stored_hash = user_row['fixed_pin']
            if not stored_hash:
                return False, '您尚未在个人设置中配置 6 位固定密码'

            if not bcrypt.checkpw(str(fixed_pin).encode('utf-8'), stored_hash.encode('utf-8')):
                return False, '固定密码验证失败'
    finally:
        conn.close()

    # Check dynamic MFA code from local in-memory store.
    # Atomically pop the code first so it cannot be consumed more than once.
    stored = mfa_store.pop(username, None)
    
    if not stored:
        return False, '验证码不存在或已过期'
    
    # Validation chain:
    # 1. Nonce check (if provided, must match to prevent out-of-order usage)
    if mfa_nonce and stored.get('nonce') != mfa_nonce:
        # If nonce doesn't match, we already popped it, so the code is invalidated.
        return False, '验证码索引不匹配，请使用最新的验证码'
    
    # 2. Expiration check
    if time.time() > stored.get('expire', 0):
        return False, '验证码已过期'
    
    # 3. Code match
    if str(stored.get('code')) != str(mfa_code):
        return False, '验证码错误'

    return True, ''


def _verify_mfa_totp(username: str, fixed_pin: str, mfa_code: str) -> tuple[bool, str]:
    """Verify the device-admin factors with a bcrypt PIN and standard TOTP.

    Device authorization no longer depends on Feishu/DingTalk delivery.  The
    fixed PIN is stored as a bcrypt hash and the second factor is the current
    six-digit code from any RFC 6238-compatible authenticator application.
    """
    import bcrypt
    from api.users import verify_totp

    if not username:
        return False, '无法识别当前用户身份'
    pin = str(fixed_pin or '')
    code = str(mfa_code or '')
    if not pin.isdigit() or len(pin) != 6:
        return False, '固定安全码必须是 6 位数字'
    if not code.isdigit() or len(code) != 6:
        return False, 'MFA 验证码必须是 6 位数字'

    conn = get_db_connection()
    try:
        user_row = conn.execute(
            "SELECT fixed_pin, mfa_enabled, mfa_secret FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if not user_row:
            return False, '用户不存在'

        stored_hash = str(user_row['fixed_pin'] or '')
        if not stored_hash:
            return False, '请先在个人设置中配置 6 位固定安全码'
        if not stored_hash.startswith(('$2a$', '$2b$', '$2y$')):
            return False, '固定安全码存储格式不安全，请重新保存固定安全码'
        try:
            pin_ok = bcrypt.checkpw(pin.encode('utf-8'), stored_hash.encode('utf-8'))
        except (ValueError, TypeError):
            pin_ok = False
        if not pin_ok:
            return False, '固定安全码验证失败'

        if int(user_row['mfa_enabled'] or 0) != 1 or not user_row['mfa_secret']:
            return False, '请先在个人设置中启用 MFA 验证器'
        if not verify_totp(str(user_row['mfa_secret']), code, window=1):
            return False, 'MFA 验证码错误或已过期'
        return True, ''
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
#  CORE: Unified Session Gateway
# ══════════════════════════════════════════════════════════════════════

@router.post('/pam/sessions')
def create_session(payload: SessionCreateIn, request: Request):
    """
    Create a controlled terminal session.
    Returns a one-time session_token — frontend uses this to connect via WebSocket.
    Frontend NEVER receives any credentials.
    """
    from fastapi import Request
    conn = get_db_connection()
    try:
        # 1. Resolve asset and linked device
        asset = conn.execute(
            'SELECT * FROM physical_assets WHERE id = ?', (payload.asset_id,)
        ).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail='Asset not found')
        asset = dict(asset)

        device = conn.execute(
            'SELECT * FROM devices WHERE asset_id = ?', (payload.asset_id,)
        ).fetchone()
        if not device:
            raise HTTPException(status_code=404, detail='No linked device found for this asset')
        device = dict(device)

        ip = device.get('ip_address') or asset.get('management_ip') or ''
        if not ip:
            raise HTTPException(status_code=422, detail='Asset has no management IP configured')

        # 2. Determine requester
        auth_session = None
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            from api.users import validate_session_token
            auth_session = validate_session_token(auth_header[7:].strip())
        if not auth_session or not auth_session.get('username'):
            raise HTTPException(status_code=401, detail='Not authenticated')
        requester = auth_session['username']
        tenant_id = str(auth_session.get('tenant_id') or 'tenant-default')
        device_tenant = str(device.get('tenant_id') or 'tenant-default')
        if tenant_id != 'tenant-default' and device_tenant not in {tenant_id, 'tenant-default'}:
            raise HTTPException(status_code=404, detail='Asset not found')

        # 3. Access control: admin requires MFA
        level = (payload.access_level or 'normal').strip().lower()
        if level not in ('normal', 'admin'):
            raise HTTPException(status_code=400, detail='Invalid access_level')

        if level == 'admin':
            if not payload.mfa_code or not payload.fixed_pin:
                return {
                    'requires_mfa': True,
                    'asset_id': payload.asset_id,
                    'message': '特权访问需要 MFA 验证',
                }
            
            # Perform actual verification
            success, error = _verify_mfa_totp(requester, payload.fixed_pin, payload.mfa_code)
            if not success:
                raise HTTPException(status_code=403, detail=error)

        # 4. Resolve credentials (INTERNAL — never sent to frontend)
        creds = _resolve_session_creds(device, asset, level)
        logger.info(f"[PAM] Resolved creds for {device['hostname'] if device else asset['name']} (level={level}): user={creds['username']} has_pwd={'Yes' if creds['password'] else 'No'}")
        
        if not creds['username']:
            raise HTTPException(
                status_code=422,
                detail=f'No {"admin" if level == "admin" else "normal"} credentials configured for this asset'
            )

        # 5. Create session record
        session_id = f"session-{uuid.uuid4().hex[:12]}"
        session_token = f"pam-sess-{uuid.uuid4().hex}"
        now = _utc_now()
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=PAM_SESSION_TOKEN_TTL_MINUTES)).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        target_port = resolve_ssh_port(device if device else asset)

        conn.execute('''
            INSERT INTO pam_sessions (
                id, tenant_id, asset_id, device_id, requester_username, access_level,
                login_username, connect_method, target_ip, target_port,
                target_hostname,
                status, session_token, token_expires_at, token_consumed,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        ''', (
            session_id, tenant_id, payload.asset_id, device['id'], requester,
            level, creds['username'], payload.connect_method,
            ip, target_port,
            asset.get('hostname') or device.get('hostname') or ip,
            'connecting', session_token, expires_at, now, now,
        ))
        conn.commit()

        # 6. Audit
        log_audit_event(
            event_type='pam.session.created',
            category='access',
            severity='info' if level == 'normal' else 'warning',
            status='open',
            summary=f'PAM session created for {asset.get("hostname") or ip} ({level})',
            actor_username=requester,
            target_type='asset',
            target_id=payload.asset_id,
            target_name=asset.get('hostname') or ip,
            device_id=device['id'],
            details={
                'session_id': session_id,
                'access_level': level,
                'connect_method': payload.connect_method,
                'target_port': target_port,
                'reason': payload.reason,
            },
        )

        return {
            'session_id': session_id,
            'session_token': session_token,
            'requires_mfa': False,
            'connect': {
                'ws_url': f'/api/pam/ws/{session_token}',
            'expires_in_seconds': PAM_SESSION_TOKEN_TTL_MINUTES * 60,
            },
            'access_level': level,
            'asset': {
                'id': asset['id'],
                'hostname': asset.get('hostname') or '',
                'management_ip': ip,
            },
        }
    finally:
        conn.close()


@router.get('/pam/sessions')
def list_sessions(
    status: str = '',
    requester_username: str = '',
    search: str = '',
    access_level: str = '',
    connect_method: str = '',
    risk_level: str = '',
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    user=require_permission('pam', 'view'),
):
    """List PAM sessions for admin monitoring."""
    conn = get_db_connection()
    try:
        # NOTE: Stale-session recovery has been moved to server startup
        # (_recover_stale_sessions_on_startup). We no longer close sessions
        # during list queries because the in-memory _active_sessions dict
        # is unreliable for detecting truly active sessions (e.g. after
        # server restart, or when WebSocket is on a different worker).
        # Sessions are only closed by:
        #   1. WebSocket disconnect (normal flow)
        #   2. Admin kill
        #   3. One-time startup recovery (for sessions orphaned by crash)
        # ────────────────────────────────────────────────────────────────

        conditions = []
        params = []
        tenant_id = str(user.get('tenant_id') or 'tenant-default') if isinstance(user, dict) else None
        if tenant_id:
            conditions.append("(tenant_id = ? OR tenant_id = 'tenant-default' OR tenant_id IS NULL)")
            params.append(tenant_id)
        if status:
            normalized_status = status.strip().lower()
            if normalized_status == 'active':
                conditions.append("status IN ('active', 'connecting')")
            elif normalized_status == 'history':
                conditions.append("status NOT IN ('active', 'connecting')")
            else:
                conditions.append('status = ?')
                params.append(normalized_status)
        if requester_username:
            conditions.append('requester_username = ?')
            params.append(requester_username.strip())
        if access_level:
            normalized_access = access_level.strip().lower()
            if normalized_access not in {'normal', 'admin'}:
                raise HTTPException(status_code=400, detail='Invalid access_level filter')
            conditions.append('access_level = ?')
            params.append(normalized_access)
        if connect_method:
            normalized_method = connect_method.strip().lower()
            if normalized_method not in {'web', 'local'}:
                raise HTTPException(status_code=400, detail='Invalid connect_method filter')
            conditions.append('connect_method = ?')
            params.append(normalized_method)
        if risk_level:
            normalized_risk = risk_level.strip().lower()
            if normalized_risk == 'risky':
                conditions.append(
                    "LOWER(CAST(risk_level AS TEXT)) IN "
                    "('1', '2', 'medium', 'high', 'critical')"
                )
            elif normalized_risk == 'safe':
                conditions.append(
                    "(risk_level IS NULL OR LOWER(CAST(risk_level AS TEXT)) "
                    "IN ('', '0', 'low', 'safe'))"
                )
            else:
                raise HTTPException(status_code=400, detail='Invalid risk_level filter')
        # Free-text search across host/IP/user fields. The query adapter
        # rewrites LIKE to ILIKE on PG so case-insensitive search is free.
        if search:
            q = f"%{search.strip()}%"
            conditions.append(
                "(target_hostname LIKE ? OR target_ip LIKE ? OR "
                "requester_username LIKE ? OR login_username LIKE ?)"
            )
            params.extend([q, q, q, q])
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ''
        total = conn.execute(f'SELECT COUNT(*) FROM pam_sessions {where}', params).fetchone()[0]
        offset = (page - 1) * page_size
        rows = conn.execute(
            f'''
            SELECT id, asset_id, device_id, requester_username, access_level,
                   session_kind, web_profile_id, login_username, connect_method,
                   target_ip, target_port, target_scheme, target_path, status,
                   connected_at, closed_at, close_reason, duration_seconds,
                   command_count, recording_path, recording_status, agent_id,
                   last_heartbeat_at, risk_level, risk_summary,
                   target_hostname, archived,
                   created_at, updated_at
            FROM pam_sessions {where}
            ORDER BY created_at DESC LIMIT ? OFFSET ?
            ''',
            params + [page_size, offset],
        ).fetchall()

        # Enrich with asset hostname (live lookup) and fall back to the
        # snapshot captured at session creation time when the asset has been
        # removed since (soft-delete preserves the audit trail). After the
        # ON DELETE SET NULL FK migration runs, archived rows have
        # asset_id = NULL on PG; pre-migration SQLite rows may have ''.
        #
        # Was previously a per-row SELECT against physical_assets — a 200×
        # query amplification on the History tab. Replaced with a single
        # batched IN-list lookup keyed by asset_id.
        rows = [dict(r) for r in rows]
        asset_ids = [r['asset_id'] for r in rows if r.get('asset_id')]
        hostname_map: dict[str, str] = {}
        if asset_ids:
            unique_ids = list({aid for aid in asset_ids})
            placeholders = ', '.join(['?'] * len(unique_ids))
            asset_rows = conn.execute(
                f'SELECT id, hostname FROM physical_assets WHERE id IN ({placeholders})',
                unique_ids,
            ).fetchall()
            hostname_map = {a['id']: (a['hostname'] or '') for a in asset_rows}

        items = []
        for item in rows:
            asset_id_val = item.get('asset_id')
            live_hostname = hostname_map.get(asset_id_val) if asset_id_val else None
            item['asset_hostname'] = live_hostname or item.get('target_hostname') or ''
            # Normalise: if session is in memory map, always report as 'active'
            if item['id'] in _active_sessions:
                item['status'] = 'active'
            items.append(item)

        return {'items': items, 'total': total, 'page': page, 'page_size': page_size}
    finally:
        conn.close()


@router.get('/pam/sessions/export.csv')
def export_sessions_csv(
    status: str = '',
    requester_username: str = '',
    search: str = '',
    access_level: str = '',
    connect_method: str = '',
    risk_level: str = '',
    user=require_permission('pam', 'view'),
):
    """Export the filtered PAM audit result without exposing credentials."""
    items: list[dict] = []
    page = 1
    while True:
        result = list_sessions(
            status=status,
            requester_username=requester_username,
            search=search,
            access_level=access_level,
            connect_method=connect_method,
            risk_level=risk_level,
            page=page,
            page_size=200,
            user=user,
        )
        batch = result.get('items') or []
        items.extend(batch)
        if len(items) >= result.get('total', 0) or not batch or len(items) >= 10000:
            break
        page += 1

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'session_id', 'session_kind', 'status', 'device', 'target_ip', 'requester',
        'login_account', 'access_level', 'connect_method', 'risk_level',
        'risk_summary', 'connected_at', 'closed_at', 'duration_seconds',
        'command_count', 'close_reason', 'recording_available',
    ])
    for item in items:
        writer.writerow([
            item.get('id', ''),
            item.get('session_kind', 'ssh_terminal'),
            item.get('status', ''),
            item.get('asset_hostname', ''),
            item.get('target_ip', ''),
            item.get('requester_username', ''),
            item.get('login_username', ''),
            item.get('access_level', ''),
            item.get('connect_method', ''),
            item.get('risk_level', ''),
            item.get('risk_summary', ''),
            item.get('connected_at', ''),
            item.get('closed_at', ''),
            item.get('duration_seconds', 0),
            item.get('command_count', 0),
            item.get('close_reason', ''),
            'yes' if item.get('recording_path') else 'no',
        ])
    content = '\ufeff' + output.getvalue()
    return Response(
        content=content.encode('utf-8'),
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="pam_sessions.csv"'},
    )


@router.post('/pam/sessions/{session_id}/kill')
async def kill_session(session_id: str, user=require_permission('pam', 'intervene')):
    """Admin force-terminate an active session."""
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM pam_sessions WHERE id = ?', (session_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Session not found')
        if isinstance(user, dict):
            row_tenant = str((dict(row).get('tenant_id') or 'tenant-default'))
            user_tenant = str(user.get('tenant_id') or 'tenant-default')
            if user_tenant != 'tenant-default' and row_tenant not in {user_tenant, 'tenant-default'}:
                raise HTTPException(status_code=404, detail='Session not found')
        if row['status'] in ('closed', 'error'):
            # Still pop from memory map in case of leftover WS
            _active_sessions.pop(session_id, None)
            return {'ok': True, 'message': 'Session already closed'}

        _update_session_status(session_id, 'closed', close_reason='admin_kill')

        # Close WebSocket if still active. Use the event loop we captured
        # when the WS was established so this works regardless of which
        # thread FastAPI chose to run the handler on.
        entry = _active_sessions.pop(session_id, None)
        if entry:
            ws = entry.get('ws') if isinstance(entry, dict) else entry
            loop = entry.get('loop') if isinstance(entry, dict) else None
            if ws is not None:
                try:
                    if loop is not None and loop.is_running():
                        # Thread-safe schedule on the WebSocket's event loop.
                        asyncio.run_coroutine_threadsafe(_safe_close_ws(ws), loop)
                    else:
                        # Last resort: try the current running loop (we are async).
                        asyncio.create_task(_safe_close_ws(ws))
                except Exception as close_err:
                    logger.warning(f"[PAM] kill_session: failed to schedule WS close for {session_id}: {close_err}")

        log_audit_event(
            event_type='pam.session.killed',
            category='access',
            severity='warning',
            status='closed',
            summary=f'PAM session {session_id} force-terminated by admin',
            target_type='session',
            target_id=session_id,
            device_id=row['device_id'],
        )
        return {'ok': True}
    finally:
        conn.close()


@router.get('/pam/sessions/{session_id}/recording')
def get_session_recording(session_id: str, user=require_permission('pam', 'view')):
    """Retrieve session recording file."""
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT recording_path FROM pam_sessions WHERE id = ?', (session_id,)).fetchone()
        if not row or not row['recording_path']:
            raise HTTPException(status_code=404, detail='Recording not found')
        if isinstance(user, dict):
            session_row = conn.execute('SELECT tenant_id FROM pam_sessions WHERE id = ?', (session_id,)).fetchone()
            if session_row:
                row_tenant = str(session_row['tenant_id'] or 'tenant-default')
                user_tenant = str(user.get('tenant_id') or 'tenant-default')
                if user_tenant != 'tenant-default' and row_tenant not in {user_tenant, 'tenant-default'}:
                    raise HTTPException(status_code=404, detail='Recording not found')
        
        path = row['recording_path']
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail='File not found on disk')

        suffix = Path(str(path)).suffix.lower()
        media_types = {
            '.cast': 'application/octet-stream',
            '.gif': 'image/gif',
            '.apng': 'image/apng',
            '.mp4': 'video/mp4',
            '.zip': 'application/zip',
        }
        extension = suffix if suffix in media_types else '.bin'
        safe_session_id = ''.join(char for char in str(session_id) if char.isalnum() or char in {'-', '_'})[:100] or 'session'
        return FileResponse(
            path,
            media_type=media_types.get(suffix, 'application/octet-stream'),
            filename=f"recording_{safe_session_id}{extension}",
        )
    finally:
        conn.close()


async def _safe_close_ws(ws: WebSocket):
    try:
        await ws.close(code=1000, reason='Session terminated by administrator')
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
#  CORE: WebSocket Terminal (Session-Token Gated)
# ══════════════════════════════════════════════════════════════════════

def _validate_token(token: str) -> dict | None:
    """Check if token is valid without consuming it."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT * FROM pam_sessions WHERE session_token = ?', (token,)
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        if int(data.get('token_consumed') or 0) == 1:
            return None
        expires = data.get('token_expires_at') or ''
        if expires:
            try:
                exp_dt = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                if exp_dt < datetime.now(timezone.utc):
                    return None
            except ValueError:
                pass
        return data
    finally:
        conn.close()


def _consume_token(session_id: str):
    """Mark token as consumed."""
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE pam_sessions SET token_consumed=1, updated_at=? WHERE id=?",
            (_utc_now(), session_id),
        )
        conn.commit()
    finally:
        conn.close()


@ws_router.websocket('/pam/ws/{session_token}')
async def pam_terminal_ws(websocket: WebSocket, session_token: str):
    """
    Controlled terminal WebSocket.
    User connects with a one-time session_token.
    Backend resolves credentials internally and proxies SSH.
    """
    # 1. Validate token (don't consume yet to allow for proxy retries)
    session = _validate_token(session_token)
    if not session:
        # If not accepted yet, Starlette might return 403/404. Let's just accept and close with reason.
        await websocket.accept()
        await websocket.send_text(json.dumps({'type': 'error', 'message': 'Invalid or expired session token'}))
        await websocket.close(code=1008)
        return

    session_id = session['id']
    await websocket.accept()

    # Previous-instance takeover:
    # If there's an existing WebSocket for this session_id (e.g. from a prior
    # connection attempt that the proxy aborted before FastAPI noticed), gracefully
    # close it so this fresh WS becomes the live one. Rejecting the new WS breaks
    # legitimate first-time connections behind flaky proxies.
    prev_entry = _active_sessions.pop(session_id, None)
    if prev_entry is not None:
        prev_ws = prev_entry.get('ws') if isinstance(prev_entry, dict) else prev_entry
        if prev_ws is not None and prev_ws is not websocket:
            try:
                await prev_ws.close(code=1000, reason='Superseded by new connection')
            except Exception:
                pass

    # 2. Resolve credentials (INTERNAL)
    conn = get_db_connection()
    try:
        device = conn.execute(
            'SELECT * FROM devices WHERE id = ?', (session['device_id'],)
        ).fetchone()
        asset = conn.execute(
            'SELECT * FROM physical_assets WHERE id = ?', (session['asset_id'],)
        ).fetchone()
        if not device:
            await websocket.close(code=1011, reason='Device not found')
            return
        device = dict(device)
        asset = dict(asset) if asset else {}
    finally:
        conn.close()

    creds = _resolve_session_creds(device, asset, session['access_level'])
    username = creds['username']
    password = creds['password']
    ip = session['target_ip'] or device.get('ip_address') or ''
    port = resolve_ssh_port(session if session.get('target_port') else device)

    if not ip or not username or not password:
        _update_session_status(session_id, 'error', close_reason='missing_credentials')
        await websocket.close(code=1011, reason='Missing SSH credentials')
        return

    # 3. SSH connection
    try:
        import asyncssh

        class PAMAuthBannerClient(asyncssh.SSHClient):
            def __init__(self):
                super().__init__()
                self.auth_banner_text = ""

            def auth_banner(self, message: str, language: str) -> None:
                if message:
                    self.auth_banner_text += message

        client_ref = [None]
        def custom_client_factory():
            client = PAMAuthBannerClient()
            client_ref[0] = client
            return client

        logger.info(f"[PAM] Attempting SSH connection to {ip}:{port} as {username}...")
        legacy_ssh = bool(getattr(settings, 'PAM_ALLOW_LEGACY_SSH', False))
        encryption_algs = [
            'chacha20-poly1305@openssh.com', 'aes256-gcm@openssh.com', 'aes128-gcm@openssh.com',
            'aes256-ctr', 'aes192-ctr', 'aes128-ctr',
        ]
        kex_algs = [
            'curve25519-sha256', 'curve25519-sha256@libssh.org',
            'ecdh-sha2-nistp256', 'ecdh-sha2-nistp384', 'ecdh-sha2-nistp521',
            'diffie-hellman-group-exchange-sha256', 'diffie-hellman-group14-sha1',
        ]
        mac_algs = [
            'hmac-sha2-256-etm@openssh.com', 'hmac-sha2-512-etm@openssh.com',
            'hmac-sha2-256', 'hmac-sha2-512',
        ]
        if legacy_ssh:
            encryption_algs.extend(['aes256-cbc', 'aes192-cbc', 'aes128-cbc', '3des-cbc'])
            kex_algs.append('diffie-hellman-group1-sha1')
            mac_algs.extend(['hmac-sha1-etm@openssh.com', 'hmac-sha1', 'hmac-md5'])
        ssh_conn = await asyncssh.connect(
            ip, port=port, username=username, password=password,
            # PAM Web login intentionally does not require per-asset host-key
            # registration. The session is still recorded and audited; an
            # operator can use the separate network/security controls when a
            # deployment needs strict SSH host-key policy.
            known_hosts=None,
            client_factory=custom_client_factory,
            login_timeout=15,
            agent_path=None, client_keys=[],
            # Support legacy devices that only use CBC ciphers
            encryption_algs=encryption_algs,
            # Also support legacy KEX and MACs often found on older switches
            kex_algs=kex_algs,
            mac_algs=mac_algs,
        )
        logger.info(f"[PAM] SSH connection established to {ip}:{port}")
        
        ssh_proc = await ssh_conn.create_process(
            term_type='xterm-256color', 
            term_size=(80, 24),
            request_pty=True,
            encoding=None  # Get raw bytes to handle decoding manually
        )
        logger.info(f"[PAM] SSH process created for session {session_id}")
        # SSH Established! Now consume the token.
        _consume_token(session_id)
    except Exception as exc:
        safe_message, error_code = _ssh_failure_message(exc)
        logger.error(
            '[PAM] SSH connection failed for session %s code=%s',
            session_id,
            error_code or 'ssh_connection_failed',
            exc_info=True,
        )
        _update_session_status(
            session_id,
            'error',
            close_reason=f"ssh_connection_failed:{error_code or 'unknown'}",
        )
        try:
            await websocket.send_text(json.dumps({'type': 'error', 'message': safe_message}, ensure_ascii=False))
            await websocket.close(code=1011, reason=error_code or 'ssh_connection_failed')
        except Exception:
            pass
        return

    # 5. Recording setup
    recording_filename = f"{session_id}.cast"
    recording_path = f"data/pam_recordings/{recording_filename}"
    start_time = time.time()
    
    try:
        # Asciinema v2 header
        with open(recording_path, 'w', encoding='utf-8') as f:
            header = {
                "version": 2,
                "width": 80,
                "height": 24,
                "timestamp": int(start_time),
                "title": f"PAM Session: {username}@{ip}",
                "env": {"TERM": "xterm-256color"}
            }
            f.write(json.dumps(header) + "\n")
    except Exception as e:
        logger.warning(f"Failed to initialize recording for {session_id}: {e}")
        recording_path = ""

    _update_session_status(session_id, 'active', recording_path=recording_path)
    # Store both the WS and the running loop so kill_session can schedule
    # close operations from any thread.
    _active_sessions[session_id] = {
        'ws': websocket,
        'loop': asyncio.get_running_loop(),
    }

    log_audit_event(
        event_type='pam.session.connected',
        category='access',
        severity='info',
        status='open',
        summary=f'PAM terminal connected: {username}@{ip} (session {session_id})',
        target_type='session',
        target_id=session_id,
        device_id=session['device_id'],
        details={'login_username': username, 'target_ip': ip, 'access_level': session['access_level'], 'recording': recording_path},
    )

    # 5.5 If the device sent an SSH_MSG_USERAUTH_BANNER during handshake, relay it now
    if client_ref[0] and client_ref[0].auth_banner_text:
        banner_msg = client_ref[0].auth_banner_text
        if not banner_msg.endswith('\r\n') and not banner_msg.endswith('\n'):
            banner_msg += '\r\n'
        try:
            await websocket.send_text(json.dumps({'type': 'output', 'data': banner_msg}))
            if recording_path:
                with open(recording_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps([0.1, "o", banner_msg]) + "\n")
        except Exception as b_err:
            logger.warning(f"[PAM] Failed to send auth banner for {session_id}: {b_err}")

    # 6. IO relay
    close_reason = 'user_disconnect'
    # Track last user activity (keyboard input) for idle timeout enforcement
    last_activity_ts = [time.time()]
    command_assembler = CommandAssembler()
    prompt_parser = PromptParser()
    command_index = 0
    command_history: list[str] = []
    cli_mode_state = ['unknown']
    active_command_event_id: str | None = None
    audit_tasks: set[asyncio.Task] = set()
    audit_tail: asyncio.Task | None = None
    previous_event_hash = str(session.get('last_event_hash') or '') or None
    IDLE_TIMEOUT_SECONDS = 5 * 60  # 5 minutes
    try:
        def schedule_audit_write(function, *args, **kwargs) -> asyncio.Task:
            """Queue ordered audit I/O without delaying terminal traffic."""
            nonlocal audit_tail
            previous_task = audit_tail

            async def run_ordered():
                if previous_task:
                    await previous_task
                await asyncio.to_thread(function, *args, **kwargs)

            task = asyncio.create_task(run_ordered())
            audit_tasks.add(task)
            task.add_done_callback(audit_tasks.discard)
            audit_tail = task
            return task

        async def upstream():
            nonlocal command_index, active_command_event_id, previous_event_hash

            def record_submitted_command(command: str):
                """Build the audit projection after the device received the line."""
                nonlocal command_index, active_command_event_id, previous_event_hash
                command_index += 1
                vendor_platform = str(device.get('platform') or 'unknown')
                decision = assess_command(
                    command,
                    vendor_platform=vendor_platform,
                    context={'change_window': session.get('change_window') or 'normal'},
                    asset={'criticality': device.get('criticality') or device.get('importance') or 'normal'},
                    source_type='interactive',
                    history=command_history,
                )
                submission = build_command_submission(
                    tenant_id=str(session.get('tenant_id') or 'tenant-default'),
                    session_id=session_id,
                    actor_id=str(session.get('requester_username') or username),
                    device_id=str(session.get('device_id') or ''),
                    source_type='interactive',
                    command_index=command_index,
                    decision=decision,
                    vendor_platform=vendor_platform,
                    cli_mode=cli_mode_state[0],
                    previous_hash=previous_event_hash,
                    enforcement_mode='audit_only',
                )
                operation = submission['operation']
                command_event = submission['command']
                previous_event_hash = operation.get('event_hash') or previous_event_hash
                active_command_event_id = command_event['id']
                command_history.append(decision.command_safe)
                schedule_audit_write(persist_command_submission, submission)
                schedule_audit_write(
                    mark_command_event,
                    command_event['id'],
                    accepted_state='accepted',
                    execution_status='executing',
                    started_at=_utc_now(),
                )

            """WebSocket → SSH stdin"""
            async for message in websocket.iter_text():
                data = json.loads(message)
                if data.get('type') == 'input':
                    last_activity_ts[0] = time.time()
                    raw_input = str(data.get('data') or '')
                    if raw_input:
                        # Forward the exact browser bytes before any audit
                        # classification. Tab, Enter, arrows, paste, password
                        # prompts, and vendor-specific controls remain native.
                        ssh_proc.stdin.write(raw_input.encode('utf-8'))
                        submitted = command_assembler.feed(raw_input)
                        for command in submitted:
                            record_submitted_command(command)
                        await ssh_proc.stdin.drain()
                elif data.get('type') == 'resize':
                    try:
                        ssh_proc.change_terminal_size(data.get('cols', 80), data.get('rows', 24))
                    except Exception:
                        pass

        async def downstream():
            """SSH stdout → WebSocket & Recorder"""
            while not ssh_proc.stdout.at_eof():
                try:
                    output_bytes = await ssh_proc.stdout.read(4096)
                    if output_bytes:
                        # CRITICAL: output is bytes, must decode for JSON
                        output_str = output_bytes.decode('utf-8', errors='replace')
                        safe_output, _dlp_categories = redact_output(output_str)
                        output_command_event_id = active_command_event_id
                        
                        # Relay to UI — if WebSocket send fails, the session
                        # is truly dead (client disconnected). Break out.
                        try:
                            await websocket.send_text(json.dumps({'type': 'output', 'data': safe_output}))
                        except Exception as ws_err:
                            logger.info(f"[PAM] WebSocket send failed for session {session_id}, client disconnected: {ws_err}")
                            break

                        # Prompt parsing is only a convenience for later audit
                        # metadata.  Do it after the terminal relay and off the
                        # event loop so it can never delay a user's output or
                        # the next Enter keypress.
                        prompt_context = await asyncio.to_thread(
                            prompt_parser.parse,
                            output_str,
                            vendor_platform=str(device.get('platform') or 'unknown'),
                        )
                        if prompt_context.mode != 'unknown':
                            cli_mode_state[0] = prompt_context.mode

                        if output_command_event_id:
                            schedule_audit_write(
                                record_command_output,
                                command_event_id=output_command_event_id,
                                output=output_str,
                                device_state='observed',
                            )
                            schedule_audit_write(
                                mark_command_event,
                                output_command_event_id,
                                execution_status='completed',
                                finished_at=_utc_now(),
                            )
                        
                        # Record to file (Asciinema format)
                        if recording_path:
                            try:
                                rel_time = time.time() - start_time
                                entry = [rel_time, "o", safe_output]
                                with open(recording_path, 'a', encoding='utf-8') as f:
                                    f.write(json.dumps(entry) + "\n")
                            except Exception:
                                pass
                    else:
                        # read returned empty bytes but not EOF — brief pause
                        await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # SSH read error — connection truly broken
                    logger.error("[PAM] SSH read error for session %s", session_id, exc_info=True)
                    break
                await asyncio.sleep(0.01)
            logger.info(f"[PAM] Downstream loop exited for session {session_id} (EOF={ssh_proc.stdout.at_eof()})")

        async def idle_watchdog():
            """Disconnect the session after IDLE_TIMEOUT_SECONDS of no keyboard input."""
            warned = False
            while True:
                await asyncio.sleep(10)
                idle_seconds = time.time() - last_activity_ts[0]
                # Warn the user 60s before timeout so they can save their work
                if not warned and idle_seconds >= (IDLE_TIMEOUT_SECONDS - 60):
                    try:
                        await websocket.send_text(json.dumps({
                            'type': 'notice',
                            'level': 'warning',
                            'message': (
                                '\r\n\x1b[33m[系统提示] 会话已空闲 4 分钟，1 分钟内无操作将被自动断开。\x1b[0m\r\n'
                            ),
                        }))
                    except Exception:
                        pass
                    warned = True
                if idle_seconds >= IDLE_TIMEOUT_SECONDS:
                    try:
                        await websocket.send_text(json.dumps({
                            'type': 'notice',
                            'level': 'error',
                            'message': '\r\n\x1b[31m[系统提示] 会话空闲超时（5 分钟），已自动断开。\x1b[0m\r\n',
                        }))
                    except Exception:
                        pass
                    logger.info(f"[PAM] Session {session_id} idle timeout ({IDLE_TIMEOUT_SECONDS}s), disconnecting")
                    return  # Triggers FIRST_COMPLETED → full cleanup

        tasks = [
            asyncio.create_task(upstream()),
            asyncio.create_task(downstream()),
            asyncio.create_task(_session_heartbeat(session_id)),
            asyncio.create_task(idle_watchdog()),
        ]
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        # Detect which task finished first to set a meaningful close reason
        finished_via_idle = any(t for t in tasks if t.done() and t.get_coro().__name__ == 'idle_watchdog')
        if finished_via_idle:
            close_reason = 'idle_timeout'
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    except WebSocketDisconnect:
        close_reason = 'user_disconnect'
    except Exception:
        logger.error('[PAM] Session %s error', session_id, exc_info=True)
        close_reason = 'error: session_relay_failed'
    finally:
        # 6. Cleanup
        _active_sessions.pop(session_id, None)
        try:
            ssh_proc.close()
        except Exception:
            pass
        try:
            ssh_conn.close()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass

        if audit_tasks:
            await asyncio.gather(*tuple(audit_tasks), return_exceptions=True)

        _update_session_status(session_id, 'closed', close_reason=close_reason)
        log_audit_event(
            event_type='pam.session.closed',
            category='access',
            severity='info',
            status='closed',
            summary=f'PAM terminal closed: session {session_id} ({close_reason})',
            target_type='session',
            target_id=session_id,
            device_id=session['device_id'],
        )


async def _session_heartbeat(session_id: str):
    """Periodically update updated_at so stale-session recovery doesn't close active sessions."""
    try:
        while True:
            await asyncio.sleep(60)  # Update every 60 seconds
            try:
                conn = get_db_connection()
                conn.execute(
                    "UPDATE pam_sessions SET updated_at=? WHERE id=? AND status='active'",
                    (_utc_now(), session_id),
                )
                conn.commit()
                conn.close()
            except Exception:
                pass
    except asyncio.CancelledError:
        pass


def _scan_session_for_risk(session_id: str, recording_path: str):
    """
    Scans a terminal recording for high-risk commands.
    Updates risk_level: 0=Safe, 1=Medium, 2=High.
    """
    if not recording_path or not os.path.exists(recording_path):
        return

    # Risk patterns - expanded for network devices and servers
    HIGH_RISK = ['rm -rf', 'shutdown', 'reboot', 'reload', 'erase ', 'drop table', 'truncate ', 'delete from', 'format ', 'mkfs']
    MED_RISK = ['rm ', 'config t', 'wr erase', 'write erase', 'delete ', 'passwd', 'userdel', 'iptables -F', 'no ip routing', 'clear config']

    found_high = []
    found_med = []

    try:
        # Reconstruct commands using the same logic as get_session_commands
        commands = []
        buffer = ""
        with open(recording_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if not line.strip(): continue
                try:
                    event = json.loads(line)
                    if not isinstance(event, list) or event[1] != 'o':
                        continue
                    data = event[2]
                    for char in data:
                        if char in ('\r', '\n'):
                            clean_cmd = _strip_ansi(buffer).strip().lower()
                            if len(clean_cmd) > 1:
                                commands.append(clean_cmd)
                            buffer = ""
                        else:
                            if ord(char) >= 32: buffer += char
                            elif ord(char) == 8 or ord(char) == 127: buffer = buffer[:-1]
                except:
                    continue

        for full_cmd in commands:
            for risk in HIGH_RISK:
                if risk in full_cmd:
                    found_high.append(risk)
            for risk in MED_RISK:
                if risk in full_cmd:
                    found_med.append(risk)

        risk_level = 0
        summary = ""
        found_high = sorted(list(set(found_high)))
        found_med = sorted(list(set(found_med)))
        
        if found_high:
            risk_level = 2
            summary = f"检测到极高风险指令: {', '.join(found_high)}"
        elif found_med:
            risk_level = 1
            summary = f"检测到中等风险指令: {', '.join(found_med)}"

        # ALWAYS update the database, even if risk_level is 0, to mark it as "scanned"
        logger.info(f"[PAM RISK] Scanning session {session_id} complete. Risk Level: {risk_level}")
        conn = get_db_connection()
        try:
            conn.execute(
                "UPDATE pam_sessions SET risk_level = ?, risk_summary = ? WHERE id = ?",
                (risk_level, summary, session_id)
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[PAM RISK] Scan failed for {session_id}: {e}")


def _strip_ansi(text: str) -> str:
    """Removes ANSI escape sequences from strings."""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


@router.get('/pam/sessions/{session_id}/commands')
def get_session_commands(session_id: str, user=require_permission('pam', 'view')):
    """Extracts typed commands and timestamps from a recording for playback navigation."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT recording_path, risk_level, risk_summary, tenant_id, created_at FROM pam_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return {"commands": [], "risk_level": 0, "risk_summary": ""}

        if isinstance(user, dict):
            row_tenant = str(row['tenant_id'] or 'tenant-default')
            user_tenant = str(user.get('tenant_id') or 'tenant-default')
            if user_tenant != 'tenant-default' and row_tenant not in {user_tenant, 'tenant-default'}:
                raise HTTPException(status_code=404, detail='Session not found')

        # Prefer the structured, redacted command audit projection. The
        # terminal recording contains prompt/output echo and cannot reliably
        # distinguish a typed command from device output. Use session-relative
        # timestamps so the replay sidebar can still seek into the cast file.
        try:
            structured_rows = conn.execute(
                "SELECT command_safe, risk_level, created_at FROM pam_command_events WHERE session_id = ? ORDER BY command_index ASC",
                (session_id,),
            ).fetchall()
        except Exception:
            structured_rows = []
        if structured_rows:
            def _as_datetime(value: object) -> datetime | None:
                if isinstance(value, datetime):
                    parsed = value
                else:
                    try:
                        parsed = datetime.fromisoformat(str(value or '').replace('Z', '+00:00'))
                    except (TypeError, ValueError):
                        return None
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                return parsed

            session_start = _as_datetime(row['created_at'])
            commands = []
            for item in structured_rows:
                text = str(item['command_safe'] or '').strip()
                if not text:
                    continue
                event_time = _as_datetime(item['created_at'])
                relative_time = max(0.0, (event_time - session_start).total_seconds()) if event_time and session_start else 0.0
                risk_code = str(item['risk_level'] or '').upper()
                numeric_risk = 2 if risk_code in {'L3', 'L4', 'HIGH', 'CRITICAL'} else 1 if risk_code in {'L2', 'MEDIUM'} else 0
                commands.append({"time": relative_time, "text": text, "risk_level": numeric_risk})
            conn.execute(
                "UPDATE pam_sessions SET command_count = CASE WHEN COALESCE(command_count, 0) < ? THEN ? ELSE command_count END WHERE id = ?",
                (len(commands), len(commands), session_id),
            )
            conn.commit()
            return {
                "commands": commands,
                "risk_level": row['risk_level'],
                "risk_summary": row['risk_summary'],
            }

        if not row['recording_path'] or not os.path.exists(row['recording_path']):
            return {"commands": [], "risk_level": 0, "risk_summary": ""}
        
        path = row['recording_path']
        
        # Trigger an on-demand scan if it hasn't been done yet
        if row['risk_level'] == 0:
            threading.Thread(target=_scan_session_for_risk, args=(session_id, path), daemon=True).start()

        # Risk patterns
        HIGH_RISK = ['rm -rf', 'shutdown', 'reboot', 'reload', 'erase ', 'drop table', 'truncate ', 'delete from', 'format ', 'mkfs']
        MED_RISK = ['rm ', 'config t', 'wr erase', 'write erase', 'delete ', 'passwd', 'userdel', 'iptables -F', 'no ip routing', 'clear config']

        commands = []
        buffer = ""
        last_time = 0
        
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                if not line.strip(): continue
                try:
                    event = json.loads(line)
                    if not isinstance(event, list) or event[1] != 'o':
                        continue
                    
                    time_val = event[0]
                    data = event[2]
                    
                    for char in data:
                        if char in ('\r', '\n'):
                            clean_cmd = _strip_ansi(buffer).strip()
                            if len(clean_cmd) > 2:
                                final_text = clean_cmd
                                for p in ['#', '>', '$']:
                                    if p in final_text:
                                        parts = final_text.split(p)
                                        if len(parts) > 1 and parts[-1].strip():
                                            final_text = parts[-1].strip()
                                
                                if len(final_text) > 1 and not final_text.startswith('['):
                                    # Tag risk level
                                    cmd_risk = 0
                                    lower_text = final_text.lower()
                                    for r in HIGH_RISK:
                                        if r in lower_text: cmd_risk = 2; break
                                    if cmd_risk == 0:
                                        for r in MED_RISK:
                                            if r in lower_text: cmd_risk = 1; break

                                    commands.append({
                                        "time": last_time,
                                        "text": final_text,
                                        "risk_level": cmd_risk
                                    })
                            buffer = ""
                            last_time = time_val
                        else:
                            if ord(char) >= 32:
                                buffer += char
                            elif ord(char) == 8 or ord(char) == 127: # Backspace
                                buffer = buffer[:-1]
                except:
                    continue
        
        filtered = []
        for c in commands:
            if not filtered or filtered[-1]['text'] != c['text']:
                if len(c['text']) < 120:
                    filtered.append(c)
                
        return {
            "commands": filtered,
            "risk_level": row['risk_level'],
            "risk_summary": row['risk_summary']
        }
    finally:
        conn.close()


@router.get('/pam/sessions/{session_id}/command-events')
def get_session_command_events(
    session_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user=require_permission('pam', 'view'),
):
    """Return the structured command audit projection, never raw keystrokes."""
    conn = get_db_connection()
    try:
        if isinstance(user, dict):
            session_row = conn.execute('SELECT tenant_id FROM pam_sessions WHERE id = ?', (session_id,)).fetchone()
            if not session_row:
                raise HTTPException(status_code=404, detail='Session not found')
            row_tenant = str(session_row['tenant_id'] or 'tenant-default')
            user_tenant = str(user.get('tenant_id') or 'tenant-default')
            if user_tenant != 'tenant-default' and row_tenant not in {user_tenant, 'tenant-default'}:
                raise HTTPException(status_code=404, detail='Session not found')
        rows = conn.execute(
            """
            SELECT id, command_index, command_safe, canonical_action,
                   vendor_platform, cli_mode, risk_level, risk_dimensions_json,
                   policy_decision, confirmation_required, accepted_state,
                   execution_status, started_at, finished_at, created_at
            FROM pam_command_events
            WHERE session_id = ?
            ORDER BY command_index ASC
            LIMIT ? OFFSET ?
            """,
            (session_id, min(limit, 500), offset),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            try:
                item['risk_dimensions'] = json.loads(item.pop('risk_dimensions_json') or '{}')
            except Exception:
                item['risk_dimensions'] = {}
            items.append(item)
        total = conn.execute("SELECT COUNT(*) AS c FROM pam_command_events WHERE session_id = ?", (session_id,)).fetchone()['c']
        return {'items': items, 'total': int(total or 0), 'limit': min(limit, 500), 'offset': offset}
    except HTTPException:
        raise
    except Exception:
        # The endpoint remains backwards compatible before m0105 is applied.
        return {'items': [], 'total': 0, 'limit': min(limit, 500), 'offset': offset}
    finally:
        conn.close()


@router.post('/pam/approvals')
def request_pam_approval(
    payload: dict = Body(...),
    user=require_permission('pam', 'request_approval'),
):
    try:
        return create_approval_request(
            tenant_id=str(user.get('tenant_id') or 'tenant-default'),
            session_id=payload.get('session_id'),
            command_event_id=str(payload.get('command_event_id') or ''),
            requester_id=str(user.get('username') or user.get('id') or 'unknown'),
            reason=str(payload.get('reason') or ''),
            ttl_seconds=int(payload.get('ttl_seconds') or 900),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/pam/approvals/{approval_id}/decision')
def decide_pam_approval(
    approval_id: str,
    payload: dict = Body(...),
    user=require_permission('pam', 'approve'),
):
    try:
        return decide_approval(
            approval_id,
            approver_id=str(user.get('username') or user.get('id') or 'unknown'),
            approved=bool(payload.get('approved')),
            mfa_verified=bool(payload.get('mfa_verified')),
            decision_note=str(payload.get('decision_note') or ''),
            tenant_id=str(user.get('tenant_id') or 'tenant-default'),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/pam/change-transactions')
def create_pam_change_transaction(
    payload: dict = Body(...),
    user=require_permission('pam', 'create_change'),
):
    try:
        return create_change_transaction(
            tenant_id=str(user.get('tenant_id') or 'tenant-default'),
            session_id=payload.get('session_id'),
            device_id=payload.get('device_id'),
            created_by=str(user.get('username') or user.get('id') or 'unknown'),
            ticket_id=payload.get('ticket_id'),
            risk_level=str(payload.get('risk_level') or 'L3'),
            diff=payload.get('diff') if isinstance(payload.get('diff'), dict) else {},
            rollback_plan=payload.get('rollback_plan') if isinstance(payload.get('rollback_plan'), dict) else {},
            target_type=str(payload.get('target_type') or 'device'), target_name=str(payload.get('target_name') or ''),
            config_diff_id=payload.get('config_diff_id'), commit_model=str(payload.get('commit_model') or 'direct'),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/pam/sessions/{session_id}/interventions')
def intervene_pam_session(
    session_id: str,
    payload: dict = Body(...),
    user=require_permission('pam', 'intervene'),
):
    try:
        return record_session_intervention(
            tenant_id=str(user.get('tenant_id') or 'tenant-default'),
            session_id=session_id,
            action=str(payload.get('action') or ''),
            actor_id=str(user.get('username') or user.get('id') or 'unknown'),
            reason=str(payload.get('reason') or ''),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/pam/jit-grants')
def create_pam_jit_grant(payload: dict = Body(...), user=require_permission('pam', 'create_change')):
    tenant_id = str(user.get('tenant_id') or 'tenant-default')
    subject = str(payload.get('subject_user_id') or user.get('username') or user.get('id') or 'unknown')
    if user.get('role') != 'Administrator':
        subject = str(user.get('username') or user.get('id') or subject)
    try:
        return create_jit_grant(
            tenant_id=tenant_id,
            subject_user_id=subject,
            scope=payload.get('scope') if isinstance(payload.get('scope'), dict) else {},
            allowed_actions=payload.get('allowed_actions') if isinstance(payload.get('allowed_actions'), list) else [],
            denied_actions=payload.get('denied_actions') if isinstance(payload.get('denied_actions'), list) else [],
            created_by=str(user.get('username') or user.get('id') or 'unknown'),
            reason=str(payload.get('reason') or ''), starts_at=payload.get('starts_at'), ends_at=payload.get('ends_at'),
            break_glass=bool(payload.get('break_glass')), mfa_verified=bool(payload.get('mfa_verified')),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/pam/jit-grants/{grant_id}/revoke')
def revoke_pam_jit_grant(grant_id: str, user=require_permission('pam', 'create_change')):
    try:
        return revoke_jit_grant(grant_id, tenant_id=str(user.get('tenant_id') or 'tenant-default'), actor_id=str(user.get('username') or user.get('id') or 'unknown'))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/pam/jit-grants/{grant_id}/check')
def check_pam_jit_grant(grant_id: str, payload: dict = Body(...), user=require_permission('pam', 'view')):
    return check_jit_grant(
        grant_id=grant_id,
        tenant_id=str(user.get('tenant_id') or 'tenant-default'),
        subject_user_id=str(user.get('username') or user.get('id') or 'unknown'),
        action=str(payload.get('action') or ''),
        at=payload.get('at'),
    )


@router.post('/pam/break-glass/{grant_id}/review')
def review_pam_break_glass(grant_id: str, payload: dict = Body(...), user=require_permission('pam', 'approve')):
    try:
        return review_break_glass(
            grant_id=grant_id, tenant_id=str(user.get('tenant_id') or 'tenant-default'),
            reviewed_by=str(user.get('username') or user.get('id') or 'unknown'),
            accepted=bool(payload.get('accepted')), note=str(payload.get('note') or ''),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/pam/file-transfers')
def audit_pam_file_transfer(payload: dict = Body(...), user=require_permission('pam', 'create_change')):
    try:
        return record_file_transfer(
            tenant_id=str(user.get('tenant_id') or 'tenant-default'), session_id=payload.get('session_id'),
            actor_id=str(user.get('username') or user.get('id') or 'unknown'), file_name=str(payload.get('file_name') or ''),
            direction=str(payload.get('direction') or ''), content_hash=str(payload.get('content_hash') or ''),
            size_bytes=int(payload.get('size_bytes') or 0), approved=bool(payload.get('approved')), mfa_verified=bool(payload.get('mfa_verified')),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/pam/batch-operations')
def create_pam_batch_operation(payload: dict = Body(...), user=require_permission('pam', 'create_change')):
    try:
        return create_batch_operation(
            tenant_id=str(user.get('tenant_id') or 'tenant-default'), created_by=str(user.get('username') or user.get('id') or 'unknown'),
            target_ids=payload.get('target_ids') if isinstance(payload.get('target_ids'), list) else [],
            command_risk_score=int(payload.get('command_risk_score') or 70), asset_criticality=str(payload.get('asset_criticality') or 'normal'),
            topology_impact=int(payload.get('topology_impact') or 0), concurrency=int(payload.get('concurrency') or 1),
            canary_count=int(payload.get('canary_count') or 1), failure_threshold=float(payload.get('failure_threshold') or 0.1),
            change_transaction_id=payload.get('change_transaction_id'), scheduled_at=payload.get('scheduled_at'),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/pam/batch-operations/{operation_id}/progress')
def update_pam_batch_progress(operation_id: str, payload: dict = Body(...), user=require_permission('pam', 'create_change')):
    try:
        return update_batch_progress(
            operation_id=operation_id, tenant_id=str(user.get('tenant_id') or 'tenant-default'),
            completed_count=int(payload.get('completed_count') or 0), failed_count=int(payload.get('failed_count') or 0),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/pam/deferred-actions')
def create_pam_deferred_action(payload: dict = Body(...), user=require_permission('pam', 'create_change')):
    try:
        return create_deferred_action(
            tenant_id=str(user.get('tenant_id') or 'tenant-default'), session_id=payload.get('session_id'), command_event_id=payload.get('command_event_id'),
            action_code=str(payload.get('action_code') or ''), execute_at=str(payload.get('execute_at') or ''),
            created_by=str(user.get('username') or user.get('id') or 'unknown'), risk_level=str(payload.get('risk_level') or 'L3'), reason=str(payload.get('reason') or ''),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/pam/behavior-risk')
def detect_pam_behavior_risk(payload: dict = Body(...), user=require_permission('pam', 'view')):
    return detect_behavior_risk(
        tenant_id=str(user.get('tenant_id') or 'tenant-default'), user_id=str(user.get('username') or user.get('id') or 'unknown'),
        session_id=payload.get('session_id'), metrics=payload.get('metrics') if isinstance(payload.get('metrics'), dict) else {},
    )


@router.post('/pam/tacacs/reconcile')
def reconcile_pam_tacacs(payload: dict = Body(...), user=require_permission('pam', 'view')):
    return reconcile_tacacs_event(
        tenant_id=str(user.get('tenant_id') or 'tenant-default'), session_id=payload.get('session_id'), command_event_id=payload.get('command_event_id'),
        nexora_action=str(payload.get('nexora_action') or ''), external_action=str(payload.get('external_action') or ''),
        metadata=payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {},
    )


@router.post('/pam/rollback-checkpoints')
def create_pam_rollback_checkpoint(payload: dict = Body(...), user=require_permission('pam', 'create_change')):
    try:
        return create_rollback_checkpoint(
            tenant_id=str(user.get('tenant_id') or 'tenant-default'), change_transaction_id=str(payload.get('change_transaction_id') or ''),
            device_id=payload.get('device_id'), checkpoint_type=str(payload.get('checkpoint_type') or 'pre_change'), snapshot_id=payload.get('snapshot_id'),
            details=payload.get('details') if isinstance(payload.get('details'), dict) else {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/pam/rollback-checkpoints/{checkpoint_id}/verify')
def verify_pam_rollback_checkpoint(checkpoint_id: str, payload: dict = Body(...), user=require_permission('pam', 'create_change')):
    try:
        return verify_rollback_checkpoint(
            checkpoint_id=checkpoint_id, tenant_id=str(user.get('tenant_id') or 'tenant-default'), health_state=str(payload.get('health_state') or 'UNKNOWN'),
            passed=bool(payload.get('passed')), details=payload.get('details') if isinstance(payload.get('details'), dict) else {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/pam/sessions/{session_id}/summary')
def summarize_pam_session(session_id: str, user=require_permission('pam', 'view')):
    try:
        return generate_session_summary(tenant_id=str(user.get('tenant_id') or 'tenant-default'), session_id=session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/pam/command-events/{command_event_id}/risk-explanation')
def explain_pam_command_risk(command_event_id: str, user=require_permission('pam', 'view')):
    try:
        return explain_command_risk(command_event_id=command_event_id, tenant_id=str(user.get('tenant_id') or 'tenant-default'))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post('/pam/external-events')
def queue_pam_external_event(payload: dict = Body(...), user=require_permission('pam', 'view')):
    try:
        return queue_external_event(
            tenant_id=str(user.get('tenant_id') or 'tenant-default'), session_id=payload.get('session_id'),
            event_type=str(payload.get('event_type') or 'pam.audit'), destination_type=str(payload.get('destination_type') or 'json'),
            payload=payload.get('payload') if isinstance(payload.get('payload'), dict) else {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _cleanup_old_sessions():
    """Purges old recordings based on retention policy."""
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT value FROM system_settings WHERE key = 'pam_retention_days'").fetchone()
        days = int(row[0]) if row else 30
        
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        
        # Find sessions to purge
        old_sessions = conn.execute(
            "SELECT id, recording_path FROM pam_sessions WHERE created_at < ? AND recording_path IS NOT NULL AND recording_path != ''",
            (cutoff,)
        ).fetchall()
        
        if not old_sessions:
            return

        logger.info(f"[PAM PURGE] Found {len(old_sessions)} sessions older than {days} days")
        
        for s in old_sessions:
            sid = s['id']
            path = s['recording_path']
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    logger.info(f"[PAM PURGE] Deleted recording: {path}")
                except Exception as e:
                    logger.error(f"[PAM PURGE] Failed to delete {path}: {e}")
            
            # Update DB to mark as purged
            conn.execute(
                "UPDATE pam_sessions SET recording_path = '' WHERE id = ?",
                (sid,)
            )
        conn.commit()
    except Exception as e:
        logger.error(f"[PAM PURGE] Cleanup task failed: {e}")
    finally:
        conn.close()


def _update_session_status(session_id: str, status: str, close_reason: str = None, recording_path: str = None):
    """Internal helper to update status and close info."""
    conn = get_db_connection()
    try:
        now = _utc_now()
        if status in ('closed', 'error', 'timeout'):
            # Fetch both timestamps to avoid KeyError and calculate duration correctly
            row = conn.execute('SELECT created_at, connected_at FROM pam_sessions WHERE id = ?', (session_id,)).fetchone()
            duration = 0
            
            # If recording_path is NOT provided here, try to get it from the DB (existing record)
            if not recording_path and row:
                # Need to re-query for recording_path if not in original row
                row_full = conn.execute('SELECT recording_path FROM pam_sessions WHERE id = ?', (session_id,)).fetchone()
                recording_path = row_full['recording_path'] if row_full else ''

            if row:
                start_ts = row['connected_at'] or row['created_at']
                if start_ts:
                    try:
                        start = datetime.fromisoformat(start_ts.replace('Z', '+00:00'))
                        duration = int((datetime.now(timezone.utc) - start).total_seconds())
                    except Exception:
                        pass
            
            conn.execute(
                "UPDATE pam_sessions SET status=?, closed_at=?, close_reason=?, duration_seconds=?, recording_path=?, updated_at=? WHERE id=?",
                (status, now, close_reason, duration, recording_path or '', now, session_id),
            )
            conn.commit()
            
            if recording_path:
                threading.Thread(target=_scan_session_for_risk, args=(session_id, recording_path), daemon=True).start()
            
            threading.Thread(target=_cleanup_old_sessions, daemon=True).start()
        else:
            # For 'active' status, we MUST preserve/save the recording_path
            if recording_path:
                conn.execute(
                    "UPDATE pam_sessions SET status=?, recording_path=?, connected_at=?, updated_at=? WHERE id=?",
                    (status, recording_path, now, now, session_id),
                )
            else:
                conn.execute(
                    "UPDATE pam_sessions SET status=?, updated_at=? WHERE id=?",
                    (status, now, session_id),
                )
            conn.commit()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
#  Legacy Access Request / Approval Flow (preserved)
# ══════════════════════════════════════════════════════════════════════

@router.post('/pam/access-request')
def create_access_request(payload: AccessRequestIn):
    level = (payload.access_level or 'normal').strip().lower()
    if level not in ('normal', 'admin'):
        raise HTTPException(status_code=400, detail='Invalid access_level')

    conn = get_db_connection()
    try:
        asset = conn.execute(
            'SELECT id, hostname, management_ip FROM physical_assets WHERE id = ?',
            (payload.asset_id,),
        ).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail='Asset not found')

        request_id = f"pam-req-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        status = 'approved' if level == 'normal' else 'pending'

        conn.execute('''
            INSERT INTO pam_access_requests (
                id, asset_id, requester_user_id, requester_username,
                access_level, reason, status, expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            request_id, payload.asset_id, payload.requester_user_id,
            payload.requester_username, level, payload.reason,
            status, expires_at, now, now,
        ))
        conn.commit()
        return {
            'request_id': request_id,
            'asset': {'id': asset['id'], 'hostname': asset['hostname'], 'management_ip': asset['management_ip']},
            'access_level': level,
            'status': status,
            'expires_at': expires_at,
        }
    finally:
        conn.close()


@router.get('/pam/access-requests')
def list_access_requests(status: str = '', requester_username: str = '', limit: int = 50):
    conn = get_db_connection()
    try:
        conditions, params = [], []
        if status:
            conditions.append('status = ?')
            params.append(status.strip().lower())
        if requester_username:
            conditions.append('requester_username = ?')
            params.append(requester_username.strip())
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ''
        rows = conn.execute(
            f'SELECT * FROM pam_access_requests {where} ORDER BY created_at DESC LIMIT ?',
            params + [max(1, min(limit, 200))],
        ).fetchall()
        return {'items': [dict(r) for r in rows]}
    finally:
        conn.close()


@router.post('/pam/access-requests/{request_id}/approve')
def approve_access_request(request_id: str, payload: AccessReviewIn):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM pam_access_requests WHERE id = ?', (request_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Request not found')
        if row['status'] != 'pending':
            return {'ok': True, 'status': row['status'], 'message': 'Already finalized'}
        now = _utc_now()
        ttl = max(1, min(payload.ttl_minutes, 30))
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=ttl)).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        conn.execute(
            "UPDATE pam_access_requests SET status='approved', reviewer_username=?, review_comment=?, expires_at=?, updated_at=? WHERE id=?",
            (payload.reviewer_username, payload.comment, expires_at, now, request_id),
        )
        conn.commit()
        return {'ok': True, 'status': 'approved', 'request_id': request_id, 'expires_at': expires_at}
    finally:
        conn.close()


@router.post('/pam/access-requests/{request_id}/reject')
def reject_access_request(request_id: str, payload: AccessReviewIn):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM pam_access_requests WHERE id = ?', (request_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Request not found')
        if row['status'] != 'pending':
            return {'ok': True, 'status': row['status'], 'message': 'Already finalized'}
        now = _utc_now()
        conn.execute(
            "UPDATE pam_access_requests SET status='rejected', reviewer_username=?, review_comment=?, updated_at=? WHERE id=?",
            (payload.reviewer_username, payload.comment, now, request_id),
        )
        conn.commit()
        return {'ok': True, 'status': 'rejected', 'request_id': request_id}
    finally:
        conn.close()
# ══════════════════════════════════════════════════════════════════════
#  MFA Management
# ══════════════════════════════════════════════════════════════════════

@router.post('/pam/mfa/request')
async def request_mfa(data: dict):
    """Request a dynamic MFA code (sent via Feishu)."""
    import random
    import time
    from services import notification_service

    username = data.get("username", "Admin")
    approver_id = data.get("approver_id")
    
    if not approver_id:
        return {"success": False, "error": "请先选择审批人"}

    # 1. Rate limiting: 1 minute interval
    now = time.time()
    last_record = mfa_store.get(username)
    if last_record and (now - last_record.get('last_sent_at', 0)) < 60:
        remaining = int(60 - (now - last_record.get('last_sent_at', 0)))
        return {"success": False, "error": f"发送频率过快，请在 {remaining} 秒后重试"}

    # 2. Generate code and 2-digit index (nonce)
    code = f"{random.randint(100000, 999999)}"
    index = f"{random.randint(1, 99):02d}"
    
    mfa_store[username] = {
        "code": code, 
        "nonce": index,
        "expire": now + 300, 
        "last_sent_at": now
    }
    
    logger.info(f"[MFA] Generated code [{index}] for user={username}, approver_id={approver_id}")
    
    conn = get_db_connection()
    feishu_url = ""
    approver_name = "Admin"
    try:
        # Check selected approver's settings
        row = conn.execute("SELECT username, notification_channels FROM users WHERE id = ?", (approver_id,)).fetchone()
        if row:
            approver_name = row['username']
            try:
                channels = json.loads(row['notification_channels'] or '{}')
                feishu_cfg = channels.get('feishu', {})
                if feishu_cfg.get('webhook_url'):
                    feishu_url = feishu_cfg['webhook_url']
            except:
                pass
        
        # Fallback to global config if approver has no webhook
        if not feishu_url:
            global_row = conn.execute("SELECT webhook_url FROM global_notification_channels WHERE platform = 'feishu'").fetchone()
            if global_row and global_row[0]:
                feishu_url = global_row[0]
                logger.info(f"[MFA] Using global feishu webhook")
    finally:
        conn.close()

    if not feishu_url:
        logger.error(f"[MFA] No Feishu webhook found for {approver_name} or globally.")
        return {"success": False, "error": f"未检测到飞书配置。请确保审批人 {approver_name} 或全局设置中已配置 Webhook 地址。"}

    # 3. Attempt to send via Feishu
    ok, msg = notification_service.send_feishu_mfa_access_code(
        feishu_url, username, code, expires_min=5, approver_name=approver_name, index=index
    )
    
    if ok:
        return {"success": True, "index": index, "message": f"验证码 [索引 #{index}] 已成功发送至审批人 {approver_name} 的飞书"}
    else:
        logger.error(f"[MFA] Feishu send failed: {msg}")
        return {"success": False, "error": f"飞书推送失败: {msg}"}


@router.post('/pam/sessions/{session_id}/export')
async def export_session_video(session_id: str):
    """
    Initiates conversion of .cast to .mp4.
    Note: Requires 'agg' (asciinema gif generator) or similar on the server.
    """
    import shutil
    agg_path = shutil.which('agg')
    if not agg_path:
        return {
            "success": False, 
            "error": "服务器未安装渲染引擎 (agg)。请在服务器上安装 asciinema-agg 以支持视频导出。"
        }
    
    # Logic to call agg would go here
    # agg --font-family "JetBrains Mono" input.cast output.gif
    # ffmpeg -i output.gif output.mp4
    return {"success": False, "error": "导出功能暂处于维护状态，请下载 .cast 文件使用本地播放器查看。"}


@router.post('/pam/mfa/verify')
async def verify_mfa(data: dict):
    """Stand-alone MFA verification (Fixed PIN + dynamic code)."""
    mfa_code = data.get("mfa_code")
    mfa_nonce = data.get("mfa_nonce")
    fixed_pw = data.get("fixed_password")
    current_username = data.get("current_username")
    
    # Stand-alone verification follows the same per-user bcrypt PIN + TOTP
    # policy as device sessions; webhook-delivered codes are not accepted.
    success, error = _verify_mfa_totp(current_username, fixed_pw, mfa_code)
    if success:
        return {"success": True}
    return {"success": False, "error": error}
