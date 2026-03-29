from fastapi import APIRouter, HTTPException, Body, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
import os
import re
import uuid
import json
import logging
import hmac
import hashlib
import time
import bcrypt
from datetime import datetime
from database import get_db_connection
from services.audit_service import log_audit_event
from services import notification_service

router = APIRouter()
logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)
ALLOWED_CHANGE_GROUPS = {'requester', 'initial_reviewer', 'final_approver', 'implementer'}

# Simple in-memory session store: token -> { user_id, username, role, created_at }
_sessions: dict[str, dict] = {}
_SESSION_TTL = 28800  # 8 hours (reduced from 24h for security)

# Login failure tracking: username -> { count, locked_until }
_login_failures: dict[str, dict] = {}
_MAX_LOGIN_ATTEMPTS = 5
_LOCKOUT_SECONDS = 900  # 15 minutes initial lockout

def _hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def _verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash.
    Also handles legacy plaintext passwords by direct comparison."""
    if hashed.startswith('$2b$') or hashed.startswith('$2a$'):
        return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))
    # Legacy plaintext comparison — will be migrated on successful login
    return plain == hashed

def _is_bcrypt_hash(value: str) -> bool:
    return value.startswith('$2b$') or value.startswith('$2a$')

def _validate_password_strength(password: str) -> str | None:
    """Return an error message if password is too weak, or None if OK."""
    if len(password) < 10:
        return 'Password must be at least 10 characters'
    if not re.search(r'[A-Z]', password):
        return 'Password must contain at least one uppercase letter'
    if not re.search(r'[a-z]', password):
        return 'Password must contain at least one lowercase letter'
    if not re.search(r'[0-9]', password):
        return 'Password must contain at least one digit'
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{}|;:\'",.<>?/\\`~]', password):
        return 'Password must contain at least one special character'
    # Check common weak patterns
    lower = password.lower()
    weak_patterns = ['password', '12345678', 'qwerty', 'admin123', 'letmein', 'welcome', 'changeme']
    for wp in weak_patterns:
        if wp in lower:
            return 'Password contains a commonly used weak pattern'
    return None


def _normalize_change_groups(raw_groups) -> list[str]:
    if not isinstance(raw_groups, (list, tuple, set)):
        return []

    normalized: list[str] = []
    for item in raw_groups:
        value = str(item or '').strip()
        if value in ALLOWED_CHANGE_GROUPS and value not in normalized:
            normalized.append(value)
    return normalized


def _hydrate_user_row(row) -> dict:
    result = dict(row)
    try:
        result['notification_channels'] = json.loads(result.get('notification_channels') or '{}')
    except Exception:
        result['notification_channels'] = {}

    try:
        raw_groups = json.loads(result.get('change_groups_json') or '[]')
    except Exception:
        raw_groups = []
    result['change_groups'] = _normalize_change_groups(raw_groups)
    result.pop('change_groups_json', None)
    result['group_name'] = str(result.get('group_name') or '')
    return result

def _check_lockout(username: str) -> int | None:
    """Return remaining lockout seconds, or None if not locked. Uses DB for persistence."""
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT locked_until FROM login_failures WHERE username = ?', (username,)).fetchone()
        if not row:
            return None
        locked_until = row['locked_until'] or 0
        if locked_until and time.time() < locked_until:
            return int(locked_until - time.time())
        return None
    finally:
        conn.close()

def _record_login_failure(username: str):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT count, locked_until FROM login_failures WHERE username = ?', (username,)).fetchone()
        if row:
            new_count = row['count'] + 1
        else:
            new_count = 1
        locked_until = 0
        if new_count >= _MAX_LOGIN_ATTEMPTS:
            # Progressive lockout: 15min, 30min, 1h based on cumulative failures
            multiplier = max(1, new_count // _MAX_LOGIN_ATTEMPTS)
            locked_until = time.time() + _LOCKOUT_SECONDS * min(multiplier, 4)
            # Do NOT reset count — cumulative tracking
        conn.execute(
            'INSERT INTO login_failures (username, count, locked_until) VALUES (?, ?, ?) '
            'ON CONFLICT(username) DO UPDATE SET count = ?, locked_until = ?',
            (username, new_count, locked_until, new_count, locked_until)
        )
        conn.commit()
    finally:
        conn.close()

def _clear_login_failures(username: str):
    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM login_failures WHERE username = ?', (username,))
        conn.commit()
    finally:
        conn.close()

def _create_token() -> str:
    return hmac.new(os.urandom(32), str(time.time()).encode(), hashlib.sha256).hexdigest()

def _clean_sessions():
    """Remove expired sessions from DB."""
    cutoff = time.time() - _SESSION_TTL
    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM sessions WHERE created_at < ?', (cutoff,))
        conn.commit()
    finally:
        conn.close()

def _store_session(token: str, user_dict: dict):
    """Persist session to DB."""
    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT INTO sessions (token, user_id, username, role, created_at) VALUES (?, ?, ?, ?, ?)',
            (token, user_dict['id'], user_dict['username'], user_dict['role'], time.time())
        )
        conn.commit()
    finally:
        conn.close()

def _get_session(token: str) -> dict | None:
    """Retrieve a session from DB. Returns None if not found or expired."""
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM sessions WHERE token = ?', (token,)).fetchone()
        if not row:
            return None
        if time.time() - row['created_at'] > _SESSION_TTL:
            conn.execute('DELETE FROM sessions WHERE token = ?', (token,))
            conn.commit()
            return None
        return dict(row)
    finally:
        conn.close()

def _delete_session(token: str):
    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM sessions WHERE token = ?', (token,))
        conn.commit()
    finally:
        conn.close()

def validate_session_token(token: str) -> dict | None:
    """Validate a session token and return session info, or None if invalid.
    Public API used by WebSocket authentication and other modules."""
    if not token:
        return None
    return _get_session(token)

@router.get("/users")
def read_users():
    conn = get_db_connection()
    try:
        users = conn.execute(
            'SELECT id, username, role, status, last_login as lastLogin, avatar_url, group_name, change_groups_json, notification_channels, preferred_language FROM users'
        ).fetchall()
        return [_hydrate_user_row(u) for u in users]
    finally:
        conn.close()

@router.post("/users")
def create_user(request: Request, user: dict = Body(...)):
    conn = get_db_connection()
    user_id = user.get('id') or str(uuid.uuid4())
    raw_password = user.get('password', '')
    group_name = str(user.get('group_name') or '').strip()
    change_groups = _normalize_change_groups(user.get('change_groups'))
    strength_err = _validate_password_strength(raw_password)
    if strength_err:
        raise HTTPException(status_code=400, detail=strength_err)
    hashed = _hash_password(raw_password)
    try:
        conn.execute(
            'INSERT INTO users (id, username, password, role, status, last_login, avatar_url, group_name, change_groups_json) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                user_id,
                user.get('username'),
                hashed,
                user.get('role'),
                'active',
                'Never',
                user.get('avatar_url'),
                group_name,
                json.dumps(change_groups, ensure_ascii=False),
            ),
        )
        conn.commit()
        log_audit_event(
            event_type='USER_CREATE',
            category='identity',
            severity='medium',
            status='success',
            summary=f"Created user {user.get('username')}",
            actor_username=user.get('actor_username') or 'admin',
            actor_role=user.get('actor_role') or 'Administrator',
            source_ip=request.client.host if request and request.client else None,
            target_type='user',
            target_id=user_id,
            target_name=user.get('username'),
            details={'role': user.get('role'), 'group_name': group_name, 'change_groups': change_groups},
        )
        row = conn.execute(
            'SELECT id, username, role, status, last_login as lastLogin, avatar_url, group_name, change_groups_json, notification_channels, preferred_language FROM users WHERE id = ?',
            (user_id,),
        ).fetchone()
        return _hydrate_user_row(row)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, payload: dict = Body(...)):
    username = payload.get('username')
    password = payload.get('password')
    safe_username = (username or '')[:64]  # truncate for logging safety
    logger.info(f"Login attempt for user: {safe_username}")

    # --- Account lockout check ---
    remaining = _check_lockout(safe_username)
    if remaining is not None:
        logger.warning(f"Login blocked for user: {safe_username} - account locked ({remaining}s remaining)")
        log_audit_event(
            event_type='LOGIN_LOCKED',
            category='identity',
            severity='high',
            status='failed',
            summary=f"Login blocked for {safe_username} (account locked)",
            actor_username=safe_username,
            actor_role='unknown',
            source_ip=request.client.host if request and request.client else None,
            target_type='session',
            target_name=safe_username,
        )
        raise HTTPException(
            status_code=429,
            detail=f"Account locked due to too many failed attempts. Try again in {remaining} seconds.",
        )

    conn = get_db_connection()
    try:
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user and _verify_password(password, user['password']):
            logger.info(f"Login successful for user: {safe_username}")
            last_login = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Migrate legacy plaintext password to bcrypt on the fly
            if not _is_bcrypt_hash(user['password']):
                hashed = _hash_password(password)
                conn.execute('UPDATE users SET last_login = ?, password = ? WHERE id = ?', (last_login, hashed, user['id']))
                logger.info(f"Migrated password to bcrypt for user: {safe_username}")
            else:
                conn.execute('UPDATE users SET last_login = ? WHERE id = ?', (last_login, user['id']))
            conn.commit()

            user_dict = dict(user)
            _clear_login_failures(safe_username)
            log_audit_event(
                event_type='LOGIN_SUCCESS',
                category='identity',
                severity='low',
                status='success',
                summary=f"User {safe_username} logged in",
                actor_id=str(user_dict['id']),
                actor_username=user_dict['username'],
                actor_role=user_dict['role'],
                source_ip=request.client.host if request and request.client else None,
                target_type='session',
                target_id=str(user_dict['id']),
                target_name=user_dict['username'],
            )
            _clean_sessions()
            token = _create_token()
            _store_session(token, user_dict)
            profile_row = conn.execute(
                'SELECT id, username, role, avatar_url, group_name, change_groups_json, notification_channels, preferred_language FROM users WHERE id = ?',
                (user_dict['id'],),
            ).fetchone()
            profile = _hydrate_user_row(profile_row)
            profile['lastLogin'] = last_login
            return {
                "success": True,
                "token": token,
                "user": profile,
            }
        else:
            _record_login_failure(safe_username)
            # Look up current failure count from DB
            fail_conn = get_db_connection()
            try:
                fail_row = fail_conn.execute('SELECT count FROM login_failures WHERE username = ?', (safe_username,)).fetchone()
                current_count = fail_row['count'] if fail_row else 0
            finally:
                fail_conn.close()
            attempts_left = _MAX_LOGIN_ATTEMPTS - (current_count % _MAX_LOGIN_ATTEMPTS)
            logger.warning(f"Login failed for user: {safe_username} - Invalid credentials")
            log_audit_event(
                event_type='LOGIN_FAILED',
                category='identity',
                severity='medium',
                status='failed',
                summary=f"Failed login attempt for user {safe_username}",
                actor_username=safe_username,
                actor_role='unknown',
                source_ip=request.client.host if request and request.client else None,
                target_type='session',
                target_name=safe_username,
            )
            detail = "Invalid credentials"
            if 0 < attempts_left <= 3:
                detail += f" ({attempts_left} attempts remaining before lockout)"
            raise HTTPException(status_code=401, detail=detail)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.put("/users/{user_id}")
def update_user(user_id: str, request: Request, user: dict = Body(...)):
    conn = get_db_connection()
    try:
        existing = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="User not found")
        username = user.get('username', existing['username'])
        role = user.get('role', existing['role'])
        avatar_url = user.get('avatar_url', existing['avatar_url'])
        group_name = str(user.get('group_name', existing['group_name'] if 'group_name' in existing.keys() else '') or '').strip()
        try:
            existing_change_groups = json.loads(existing['change_groups_json'] or '[]') if 'change_groups_json' in existing.keys() else []
        except Exception:
            existing_change_groups = []
        change_groups = _normalize_change_groups(user.get('change_groups', existing_change_groups))
        preferred_language = user.get('preferred_language', existing['preferred_language'] if 'preferred_language' in (existing.keys() if existing else []) else 'zh')
        if preferred_language not in ('zh', 'en'):
            preferred_language = 'zh'
        notification_channels_raw = user.get('notification_channels')
        notification_channels_str = json.dumps(notification_channels_raw) if notification_channels_raw is not None else (existing['notification_channels'] or '{}')
        change_groups_str = json.dumps(change_groups, ensure_ascii=False)
        password = user.get('password')
        if password:
            strength_err = _validate_password_strength(password)
            if strength_err:
                raise HTTPException(status_code=400, detail=strength_err)
            hashed = _hash_password(password)
            conn.execute(
                'UPDATE users SET username = ?, role = ?, password = ?, avatar_url = ?, group_name = ?, change_groups_json = ?, notification_channels = ?, preferred_language = ? WHERE id = ?',
                (username, role, hashed, avatar_url, group_name, change_groups_str, notification_channels_str, preferred_language, user_id)
            )
        else:
            conn.execute(
                'UPDATE users SET username = ?, role = ?, avatar_url = ?, group_name = ?, change_groups_json = ?, notification_channels = ?, preferred_language = ? WHERE id = ?',
                (username, role, avatar_url, group_name, change_groups_str, notification_channels_str, preferred_language, user_id)
            )
        conn.commit()
        result = conn.execute(
            'SELECT id, username, role, status, last_login as lastLogin, avatar_url, group_name, change_groups_json, notification_channels, preferred_language FROM users WHERE id = ?',
            (user_id,)
        ).fetchone()
        log_audit_event(
            event_type='USER_UPDATE',
            category='identity',
            severity='medium',
            status='success',
            summary=f"Updated user {username}",
            actor_username=user.get('actor_username') or 'admin',
            actor_role=user.get('actor_role') or 'Administrator',
            source_ip=request.client.host if request and request.client else None,
            target_type='user',
            target_id=user_id,
            target_name=username,
            details={'role': role, 'group_name': group_name, 'change_groups': change_groups},
        )
        return _hydrate_user_row(result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.get("/session")
def check_session(request: Request):
    """Validate a session token and return user info."""
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '') if auth.startswith('Bearer ') else ''
    sess = validate_session_token(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Not authenticated")
    conn = get_db_connection()
    try:
        user = conn.execute(
            'SELECT id, username, role, avatar_url, group_name, change_groups_json, notification_channels, preferred_language FROM users WHERE id = ?',
            (sess['user_id'],)
        ).fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="Session user not found")
        return {"success": True, "user": _hydrate_user_row(user)}
    finally:
        conn.close()


@router.post("/users/{user_id}/notify-test")
def test_notification_channel(user_id: str, request: Request, payload: dict = Body(...)):
    """
    对指定平台发送一条测试消息，验证 webhook 配置是否正确。
    payload: {
        "platform": "feishu" | "dingtalk" | "wechat",
        "webhook_url": "https://...",   # 直接使用，无需提前保存
        "secret": "..."                 # 钉钉加签密钥（可选）
    }
    """
    platform = (payload.get('platform') or '').strip().lower()
    if platform not in ('feishu', 'dingtalk', 'wechat'):
        raise HTTPException(status_code=400, detail="platform must be feishu | dingtalk | wechat")

    # 优先使用请求体中的 webhook_url（不保存即可测试）
    webhook_url = (payload.get('webhook_url') or '').strip()
    secret = (payload.get('secret') or '').strip()

    # 如果请求体没有 webhook_url，则回退读 DB（兼容旧调用）
    if not webhook_url:
        conn = get_db_connection()
        try:
            user_row = conn.execute('SELECT username, notification_channels FROM users WHERE id = ?', (user_id,)).fetchone()
            if not user_row:
                raise HTTPException(status_code=404, detail="User not found")
            try:
                channels = json.loads(user_row['notification_channels'] or '{}')
            except Exception:
                channels = {}
            ch = channels.get(platform) or {}
            webhook_url = ch.get('webhook_url', '').strip()
            secret = ch.get('secret', '').strip()
            username = user_row['username']
        finally:
            conn.close()
        if not webhook_url:
            raise HTTPException(status_code=400, detail=f"{platform} webhook_url is not configured")
    else:
        conn = get_db_connection()
        try:
            user_row = conn.execute('SELECT username FROM users WHERE id = ?', (user_id,)).fetchone()
            username = user_row['username'] if user_row else str(user_id)
        finally:
            conn.close()

    test_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    test_alert = {
        'title':            'NetPilot 连通性测试',
        'object_name':      f'{platform.capitalize()} 机器人',
        'ip_address':       'webhook',
        'status':           'active',
        'severity':         'info',
        'message':          f'用户 {username} 发起的 Webhook 连通性测试，配置验证成功！',
        'first_occurrence': test_ts,
        'last_occurrence':  test_ts,
    }

    if platform == 'feishu':
        ok, msg = notification_service.send_feishu(webhook_url, test_alert)
    elif platform == 'dingtalk':
        ok, msg = notification_service.send_dingtalk(webhook_url, test_alert, secret=secret)
    else:
        ok, msg = notification_service.send_wechat(webhook_url, test_alert)

    if ok:
        return {"success": True, "platform": platform, "message": "Test message sent successfully"}
    else:
        raise HTTPException(status_code=502, detail=f"Send failed: {msg[:300]}")
