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
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database import get_db_connection
from services.vault_service import resolve_device_credentials
from services.audit_service import log_audit_event
from services.connection_profile import resolve_ssh_port

router = APIRouter()
# WebSocket 路由单独放在无依赖的 router，避免 FastAPI 在 WS 握手阶段
# 因 Depends(require_feature) 无法注入 Request 而返回 404。
# WS 自身已通过 session_token 做一次性令牌验证，无需额外 License 依赖。
ws_router = APIRouter()
logger = logging.getLogger(__name__)

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
        password = (
            creds.get('admin_password')
            or creds.get('password')
        )
        # Try asset-level admin password if device-level is empty
        if not password and asset and asset.get('admin_password'):
            password = decrypt_credential(asset['admin_password']) or ''
    else:
        username = (
            creds.get('normal_username')
            or (asset.get('normal_username') if asset else '')
            or creds.get('username')
            or (asset.get('username') if asset else '')
        )
        password = (
            creds.get('normal_password')
            or creds.get('password')
        )
        if (not password and asset and (asset.get('normal_password') or asset.get('password'))):
            raw = asset.get('normal_password') or asset.get('password')
            password = decrypt_credential(raw) or ''
        
        # Fallback to level-specific default if still empty
        if not username:
            username = 'user' if is_server else 'admin'

    return {'username': username or '', 'password': password or ''}


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


# ══════════════════════════════════════════════════════════════════════
#  CORE: Unified Session Gateway
# ══════════════════════════════════════════════════════════════════════

@router.post('/pam/sessions')
def create_session(payload: SessionCreateIn):
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
        requester = payload.requester_username or 'unknown'

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
            success, error = _verify_mfa(requester, payload.fixed_pin, payload.mfa_code, payload.mfa_nonce)
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
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        target_port = resolve_ssh_port(device if device else asset)

        conn.execute('''
            INSERT INTO pam_sessions (
                id, asset_id, device_id, requester_username, access_level,
                login_username, connect_method, target_ip, target_port,
                target_hostname,
                status, session_token, token_expires_at, token_consumed,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        ''', (
            session_id, payload.asset_id, device['id'], requester,
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
                'expires_in_seconds': 300,
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
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
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
        if status:
            if status.strip().lower() == 'active':
                conditions.append("status IN ('active', 'connecting')")
            else:
                conditions.append('status = ?')
                params.append(status.strip().lower())
        if requester_username:
            conditions.append('requester_username = ?')
            params.append(requester_username.strip())
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
                   login_username, connect_method, target_ip, target_port, status,
                   connected_at, closed_at, close_reason, duration_seconds,
                   command_count, recording_path, risk_level, risk_summary,
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


@router.post('/pam/sessions/{session_id}/kill')
async def kill_session(session_id: str):
    """Admin force-terminate an active session."""
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM pam_sessions WHERE id = ?', (session_id,)).fetchone()
        if not row:
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
def get_session_recording(session_id: str):
    """Retrieve session recording file."""
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT recording_path FROM pam_sessions WHERE id = ?', (session_id,)).fetchone()
        if not row or not row['recording_path']:
            raise HTTPException(status_code=404, detail='Recording not found')
        
        import os
        path = row['recording_path']
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail='File not found on disk')
            
        return FileResponse(path, media_type='application/octet-stream', filename=f"recording_{session_id}.cast")
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
        ssh_conn = await asyncssh.connect(
            ip, port=port, username=username, password=password,
            known_hosts=None, client_factory=custom_client_factory,
            login_timeout=15,
            agent_path=None, client_keys=[],
            # Support legacy devices that only use CBC ciphers
            encryption_algs=[
                'chacha20-poly1305@openssh.com',
                'aes256-gcm@openssh.com', 'aes128-gcm@openssh.com',
                'aes256-ctr', 'aes192-ctr', 'aes128-ctr',
                'aes256-cbc', 'aes192-cbc', 'aes128-cbc', '3des-cbc'
            ],
            # Also support legacy KEX and MACs often found on older switches
            kex_algs=[
                'curve25519-sha256', 'curve25519-sha256@libssh.org',
                'ecdh-sha2-nistp256', 'ecdh-sha2-nistp384', 'ecdh-sha2-nistp521',
                'diffie-hellman-group-exchange-sha256', 'diffie-hellman-group14-sha1',
                'diffie-hellman-group1-sha1'
            ],
            mac_algs=[
                'hmac-sha2-256-etm@openssh.com', 'hmac-sha2-512-etm@openssh.com',
                'hmac-sha1-etm@openssh.com', 'hmac-sha2-256', 'hmac-sha2-512',
                'hmac-sha1', 'hmac-md5'
            ]
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
    except Exception as e:
        logger.error(f'[PAM] SSH connection failed for session {session_id}: {e}')
        _update_session_status(session_id, 'error', close_reason=f'ssh_error: {e}')
        try:
            await websocket.send_text(json.dumps({'type': 'error', 'message': f'SSH connection failed: {e}'}))
            await websocket.close(code=1011)
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
    IDLE_TIMEOUT_SECONDS = 5 * 60  # 5 minutes
    try:
        async def upstream():
            """WebSocket → SSH stdin"""
            async for message in websocket.iter_text():
                data = json.loads(message)
                if data.get('type') == 'input':
                    last_activity_ts[0] = time.time()
                    ssh_proc.stdin.write(data['data'].encode('utf-8'))
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
                        
                        # Relay to UI — if WebSocket send fails, the session
                        # is truly dead (client disconnected). Break out.
                        try:
                            await websocket.send_text(json.dumps({'type': 'output', 'data': output_str}))
                        except Exception as ws_err:
                            logger.info(f"[PAM] WebSocket send failed for session {session_id}, client disconnected: {ws_err}")
                            break
                        
                        # Record to file (Asciinema format)
                        if recording_path:
                            try:
                                rel_time = time.time() - start_time
                                entry = [rel_time, "o", output_str]
                                with open(recording_path, 'a', encoding='utf-8') as f:
                                    f.write(json.dumps(entry) + "\n")
                            except Exception:
                                pass
                    else:
                        # read returned empty bytes but not EOF — brief pause
                        await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    # SSH read error — connection truly broken
                    logger.error(f"[PAM] SSH read error for session {session_id}: {e}")
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
    except Exception as e:
        logger.error(f'[PAM] Session {session_id} error: {e}')
        close_reason = f'error: {e}'
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
def get_session_commands(session_id: str):
    """Extracts typed commands and timestamps from a recording for playback navigation."""
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT recording_path, risk_level, risk_summary FROM pam_sessions WHERE id = ?", (session_id,)).fetchone()
        if not row or not row['recording_path'] or not os.path.exists(row['recording_path']):
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
    
    success, error = _verify_mfa(current_username, fixed_pw, mfa_code, mfa_nonce)
    if success:
        return {"success": True}
    return {"success": False, "error": error}
