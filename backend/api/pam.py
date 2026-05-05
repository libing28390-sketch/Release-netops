import uuid
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import paramiko

from database import get_db_connection
from services.vault_service import resolve_device_credentials

router = APIRouter()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')


class AccessRequestIn(BaseModel):
    asset_id: str
    access_level: str = 'normal'  # normal | admin
    reason: str = ''
    requester_username: str = 'unknown'
    requester_user_id: str = ''


class AccessReviewIn(BaseModel):
    reviewer_username: str = 'admin'
    comment: str = ''
    ttl_minutes: int = 5


class TerminalSessionIn(BaseModel):
    request_id: str


@router.post('/pam/access-request')
def create_access_request(payload: AccessRequestIn):
    level = (payload.access_level or 'normal').strip().lower()
    if level not in ('normal', 'admin'):
        raise HTTPException(status_code=400, detail='Invalid access_level')

    conn = get_db_connection()
    try:
        asset = conn.execute('SELECT id, hostname, management_ip FROM physical_assets WHERE id = ?', (payload.asset_id,)).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail='Asset not found')

        request_id = f"pam-req-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S+00:00')

        # MVP policy:
        # - normal access is granted immediately
        # - admin access enters pending approval state
        status = 'approved' if level == 'normal' else 'pending'

        dev = conn.execute('SELECT id, username FROM devices WHERE asset_id = ?', (payload.asset_id,)).fetchone()
        conn.execute(
            '''
            INSERT INTO pam_access_requests (
                id, asset_id, device_id, requester_user_id, requester_username,
                access_level, reason, status, expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                request_id,
                payload.asset_id,
                dev['id'] if dev else '',
                payload.requester_user_id,
                payload.requester_username,
                level,
                payload.reason,
                status,
                expires_at,
                now,
                now,
            ),
        )

        session_token = None
        if status == 'approved':
            session_token = f"pam-sess-{uuid.uuid4().hex}"
            conn.execute(
                '''
                INSERT INTO pam_session_tokens (
                    token, request_id, asset_id, access_level, username, expires_at, consumed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                ''',
                (
                    session_token,
                    request_id,
                    payload.asset_id,
                    level,
                    dev['username'] if dev and dev['username'] else '',
                    expires_at,
                    now,
                ),
            )

        conn.commit()
        return {
            'request_id': request_id,
            'asset': {'id': asset['id'], 'hostname': asset['hostname'], 'management_ip': asset['management_ip']},
            'access_level': level,
            'status': status,
            'session_token': session_token,
            'expires_at': expires_at,
        }
    finally:
        conn.close()


@router.get('/pam/access-requests')
def list_access_requests(status: str = '', requester_username: str = '', limit: int = 50):
    conn = get_db_connection()
    try:
        conditions = []
        params = []
        if status:
            conditions.append('status = ?')
            params.append(status.strip().lower())
        if requester_username:
            conditions.append('requester_username = ?')
            params.append(requester_username.strip())
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ''
        rows = conn.execute(
            f'''
            SELECT id, asset_id, device_id, requester_user_id, requester_username, access_level,
                   reason, status, reviewer_username, review_comment, expires_at, created_at, updated_at
            FROM pam_access_requests
            {where}
            ORDER BY created_at DESC
            LIMIT ?
            ''',
            params + [max(1, min(limit, 200))],
        ).fetchall()
        return {'items': [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get('/pam/access-requests/{request_id}')
def get_access_request(request_id: str):
    conn = get_db_connection()
    try:
        row = conn.execute(
            '''
            SELECT id, asset_id, device_id, requester_user_id, requester_username, access_level,
                   reason, status, reviewer_username, review_comment, expires_at, created_at, updated_at
            FROM pam_access_requests WHERE id = ?
            ''',
            (request_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Request not found')
        return dict(row)
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
            return {'ok': True, 'status': row['status'], 'message': 'Request already finalized'}

        now = _utc_now()
        ttl = max(1, min(payload.ttl_minutes, 30))
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=ttl)).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        conn.execute(
            '''
            UPDATE pam_access_requests
            SET status = 'approved', reviewer_username = ?, review_comment = ?, expires_at = ?, updated_at = ?
            WHERE id = ?
            ''',
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
            return {'ok': True, 'status': row['status'], 'message': 'Request already finalized'}
        now = _utc_now()
        conn.execute(
            '''
            UPDATE pam_access_requests
            SET status = 'rejected', reviewer_username = ?, review_comment = ?, updated_at = ?
            WHERE id = ?
            ''',
            (payload.reviewer_username, payload.comment, now, request_id),
        )
        conn.commit()
        return {'ok': True, 'status': 'rejected', 'request_id': request_id}
    finally:
        conn.close()


@router.post('/pam/terminal-session')
def create_terminal_session(payload: TerminalSessionIn):
    conn = get_db_connection()
    try:
        req = conn.execute('SELECT * FROM pam_access_requests WHERE id = ?', (payload.request_id,)).fetchone()
        if not req:
            raise HTTPException(status_code=404, detail='Access request not found')
        if req['status'] != 'approved':
            raise HTTPException(status_code=409, detail=f"Access request status is '{req['status']}', not approved")

        now_dt = datetime.now(timezone.utc)
        expires_at_raw = req['expires_at'] or ''
        if expires_at_raw:
            try:
                exp_dt = datetime.fromisoformat(expires_at_raw.replace('Z', '+00:00'))
                if exp_dt < now_dt:
                    conn.execute("UPDATE pam_access_requests SET status='expired', updated_at=? WHERE id = ?", (_utc_now(), req['id']))
                    conn.commit()
                    raise HTTPException(status_code=410, detail='Access request expired')
            except ValueError:
                pass

        asset = conn.execute(
            '''
            SELECT id, hostname, management_ip, connection_method, auth_model, username, password, normal_username, normal_password, admin_username, admin_password
            FROM physical_assets WHERE id = ?
            ''',
            (req['asset_id'],),
        ).fetchone()
        dev = conn.execute('SELECT id, username, priv_username FROM devices WHERE asset_id = ?', (req['asset_id'],)).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail='Asset not found')

        access_level = req['access_level'] or 'normal'
        login_user = ''
        if access_level == 'admin':
            login_user = (asset['admin_username'] if asset and asset['admin_username'] else '') or (dev['priv_username'] if dev and dev['priv_username'] else '') or (dev['username'] if dev else '')
        else:
            login_user = (
                (asset['normal_username'] if asset and asset['normal_username'] else '')
                or (asset['username'] if asset and asset['username'] else '')
                or (dev['username'] if dev else '')
            )
            if (asset.get('auth_model') or '').lower() == 'dual' and not (asset.get('normal_username') or '').strip():
                raise HTTPException(status_code=422, detail='Dual auth mode requires normal_username for normal access')

        session_token = f"pam-sess-{uuid.uuid4().hex}"
        created_at = _utc_now()
        expires_at = (now_dt + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        conn.execute(
            '''
            INSERT INTO pam_session_tokens (token, request_id, asset_id, access_level, username, expires_at, consumed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            ''',
            (session_token, req['id'], req['asset_id'], access_level, login_user, expires_at, created_at),
        )
        conn.commit()
        return {
            'session_token': session_token,
            'request_id': req['id'],
            'access_level': access_level,
            'asset': {'id': asset['id'], 'hostname': asset['hostname'], 'management_ip': asset['management_ip']},
            'connect': {
                'method': asset['connection_method'] or 'ssh',
                'host': asset['management_ip'] or '',
                'port': 22,
                'username': login_user,
                'proxy_hint': '127.0.0.1:2222',
            },
            'expires_at': expires_at,
        }
    finally:
        conn.close()


def _get_live_session_token(token: str):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM pam_session_tokens WHERE token = ?', (token,)).fetchone()
        if not row:
            return None
        data = dict(row)
        if int(data.get('consumed') or 0) == 1:
            return None
        expires_at = data.get('expires_at') or ''
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                if exp_dt < datetime.now(timezone.utc):
                    return None
            except ValueError:
                pass
        return data
    finally:
        conn.close()


def _consume_session_token(token: str):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT consumed FROM pam_session_tokens WHERE token = ?', (token,)).fetchone()
        if not row or int(row['consumed'] or 0) == 1:
            return False
        conn.execute('UPDATE pam_session_tokens SET consumed = 1 WHERE token = ?', (token,))
        conn.commit()
        return True
    finally:
        conn.close()


@router.websocket('/pam/ws/terminal/{session_token}')
async def pam_terminal_ws(websocket: WebSocket, session_token: str):
    session = _get_live_session_token(session_token)
    if not session:
        await websocket.close(code=1008, reason='Invalid or expired session token')
        return

    if not _consume_session_token(session_token):
        await websocket.close(code=1008, reason='Session token already consumed')
        return

    conn = get_db_connection()
    try:
        asset = conn.execute(
            'SELECT id, hostname, management_ip, username, password, normal_username, normal_password, admin_username, admin_password FROM physical_assets WHERE id = ?',
            (session['asset_id'],),
        ).fetchone()
        dev = conn.execute(
            'SELECT id, hostname, ip_address, platform, username, password, priv_username, enable_password, credential_source, vault_path '
            'FROM devices WHERE asset_id = ?',
            (session['asset_id'],),
        ).fetchone()
        if not dev or not asset:
            await websocket.close(code=1011, reason='No linked device found')
            return
        asset_dict = dict(asset)
        dev_dict = dict(dev)
    finally:
        conn.close()

    creds = resolve_device_credentials(dev_dict)
    username = creds.get('username') or dev_dict.get('username') or ''
    password = creds.get('password') or ''
    if session.get('access_level') == 'admin':
        if asset_dict.get('admin_username'):
            username = asset_dict.get('admin_username')
        elif dev_dict.get('priv_username'):
            username = dev_dict.get('priv_username')
        if asset_dict.get('admin_password'):
            try:
                from core.crypto import decrypt_credential
                password = decrypt_credential(asset_dict.get('admin_password')) or password
            except Exception:
                pass
    else:
        if (asset_dict.get('auth_model') or '').lower() == 'dual' and not (asset_dict.get('normal_username') or '').strip():
            await websocket.close(code=1011, reason='Dual auth mode requires normal_username')
            return
        if asset_dict.get('normal_username') or asset_dict.get('username'):
            username = asset_dict.get('normal_username') or asset_dict.get('username')
        normal_pwd = asset_dict.get('normal_password') or asset_dict.get('password')
        if normal_pwd:
            try:
                from core.crypto import decrypt_credential
                password = decrypt_credential(normal_pwd) or password
            except Exception:
                pass

    if not dev_dict.get('ip_address') or not username or not password:
        await websocket.close(code=1011, reason='Missing SSH credentials or IP')
        return

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    chan = None

    try:
        await asyncio.to_thread(
            ssh.connect,
            hostname=dev_dict['ip_address'],
            username=username,
            password=password,
            timeout=10,
            allow_agent=False,
            look_for_keys=False,
        )
        chan = await asyncio.to_thread(ssh.invoke_shell)
        await websocket.accept()
        await websocket.send_text(f"[PAM] Connected to {dev_dict.get('hostname') or dev_dict['ip_address']} as {username}\r\n")

        async def pump_remote_output():
            while True:
                if chan.recv_ready():
                    data = await asyncio.to_thread(chan.recv, 4096)
                    if not data:
                        break
                    await websocket.send_text(data.decode('utf-8', errors='ignore'))
                else:
                    await asyncio.sleep(0.05)

        output_task = asyncio.create_task(pump_remote_output())

        while True:
            text = await websocket.receive_text()
            if text == '__ping__':
                await websocket.send_text('__pong__')
                continue
            await asyncio.to_thread(chan.send, text)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.accept()
        except Exception:
            pass
        await websocket.send_text(f"[PAM] Terminal error: {e}\r\n")
    finally:
        try:
            if chan is not None:
                await asyncio.to_thread(chan.close)
        except Exception:
            pass
        try:
            await asyncio.to_thread(ssh.close)
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass
