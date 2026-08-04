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
import asyncio
from database import get_db_connection
from services.audit_service import log_audit_event
from services import notification_service
from core.config import settings
from core.rbac import RECOMMENDED_ROLE_PROFILES

router = APIRouter()
logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)
ALLOWED_CHANGE_GROUPS = {'requester', 'initial_reviewer', 'final_approver', 'implementer'}

# Simple in-memory session store: token -> { user_id, username, role, created_at }
_sessions: dict[str, dict] = {}
_SESSION_TTL = max(300, int(settings.SESSION_TTL_SECONDS))

# Login failure tracking: username -> { count, locked_until }
_login_failures: dict[str, dict] = {}
_MAX_LOGIN_ATTEMPTS = 5
_LOCKOUT_SECONDS = 900  # 15 minutes initial lockout

async def _hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt (offloaded to thread)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, 
        lambda: bcrypt.hashpw(plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    )

async def _verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash (offloaded to thread)."""
    if hashed.startswith('$2b$') or hashed.startswith('$2a$'):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))
        )
    # Legacy plaintext comparison
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


def _validate_new_user_fields(username: str, password: str, display_name: str, phone: str, email: str, role: str, group_name: str) -> str | None:
    """Validate the required identity/contact fields before creating a user."""
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9._-]{2,31}', username):
        return 'Username must start with a letter and contain 3-32 letters, digits, dot, underscore, or hyphen'
    password_error = _validate_password_strength(password)
    if password_error:
        return password_error
    if not re.fullmatch(r"[A-Za-z\u4e00-\u9fff][A-Za-z\u4e00-\u9fff .'-]{1,49}", display_name):
        return 'Display name must contain 2-50 Chinese or English characters'
    if not re.fullmatch(r'\+?[0-9][0-9\s().-]{6,24}', phone) or not (7 <= len(re.sub(r'\D', '', phone)) <= 15):
        return 'Phone must contain 7-15 digits and may include a country code'
    if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]{2,}', email):
        return 'Enter a valid email address'
    if role not in ('Administrator', 'Operator', 'Viewer'):
        return 'Invalid role'
    if len(group_name) > 100:
        return 'Group name must be 100 characters or fewer'
    return None


def _validate_role_profile(value: object) -> str | None:
    profile = str(value or '').strip()
    if profile and profile not in RECOMMENDED_ROLE_PROFILES:
        return None
    return profile or None


def _normalize_change_groups(raw_groups) -> list[str]:
    if not isinstance(raw_groups, (list, tuple, set)):
        return []

    normalized: list[str] = []
    for item in raw_groups:
        value = str(item or '').strip()
        if value in ALLOWED_CHANGE_GROUPS and value not in normalized:
            normalized.append(value)
    return normalized


def _mask_webhook_url(url: str) -> str:
    if not url:
        return ''
    if 'feishu.cn' in url and '/hook/' in url:
        base, token = url.split('/hook/', 1)
        if len(token) > 12:
            masked_token = token[:4] + '-****-****-****-' + token[-4:]
        else:
            masked_token = '****'
        return f"{base}/hook/{masked_token}"
    elif 'access_token=' in url:
        base, token = url.split('access_token=', 1)
        if len(token) > 8:
            masked_token = token[:4] + '****' + token[-4:]
        else:
            masked_token = '****'
        return f"{base}access_token={masked_token}"
    elif 'key=' in url:
        base, token = url.split('key=', 1)
        if len(token) > 8:
            masked_token = token[:4] + '****' + token[-4:]
        else:
            masked_token = '****'
        return f"{base}key={masked_token}"
    else:
        if len(url) > 24:
            return url[:12] + '***' + url[-6:]
        return '***'


def _fetch_global_notification_channels() -> list[dict]:
    """Fetch the (small) global channel template list once.

    The table has at most a handful of rows (one per platform). Hoisting this
    query out of `_hydrate_user_row` removes a 500× amplification when listing
    all users — previously each row opened a new connection and ran this query.
    """
    conn = get_db_connection()
    try:
        rows = conn.execute(
            'SELECT platform, webhook_url, enabled, secret, creator_username FROM global_notification_channels'
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _build_user_channels(user_channels: dict, shared_rows: list[dict]) -> dict:
    """Merge a user's personal channel prefs with the shared channel templates."""
    final_channels: dict[str, dict] = {}
    for s_row in shared_rows:
        platform = s_row['platform']
        url = (s_row.get('webhook_url') or '').strip()
        masked_url = _mask_webhook_url(url)
        user_pref = user_channels.get(platform, {})
        is_enabled = (
            bool(user_pref.get('enabled'))
            if 'enabled' in user_pref
            else bool(s_row.get('enabled'))
        )
        final_channels[platform] = {
            'webhook_url': masked_url,
            'enabled': is_enabled,
            'secret': '***' if (s_row.get('secret') or '').strip() else '',
            'creator_username': s_row.get('creator_username'),
        }
    # Ensure all standard platforms are present even if not configured.
    for p in ('feishu', 'dingtalk', 'wechat'):
        if p not in final_channels:
            final_channels[p] = {
                'webhook_url': '',
                'enabled': False,
                'secret': '',
                'creator_username': '',
            }
    return final_channels


def _hydrate_user_row(row, shared_channels: list[dict] | None = None) -> dict:
    """Project a raw user row to the API response shape.

    Pass `shared_channels` when hydrating multiple users in a batch — the
    caller fetches the list once and the helper reuses it for every row.
    Falls back to fetching on its own when called for a single row (e.g. the
    profile endpoint), which keeps the public API stable.
    """
    result = dict(row)

    # 1. Parse user's personal notification settings.
    try:
        user_channels = json.loads(result.get('notification_channels') or '{}')
    except Exception:
        user_channels = {}

    try:
        if shared_channels is None:
            shared_channels = _fetch_global_notification_channels()
        result['notification_channels'] = _build_user_channels(user_channels, shared_channels)
    except Exception as e:
        logger.error(f"Error hydrating user row: {e}")
        result['notification_channels'] = user_channels

    try:
        raw_groups = json.loads(result.get('change_groups_json') or '[]')
    except Exception:
        raw_groups = []
    result['change_groups'] = _normalize_change_groups(raw_groups)
    result.pop('change_groups_json', None)
    result['group_name'] = str(result.get('group_name') or '')
    result['display_name'] = str(result.get('display_name') or '')
    result['phone'] = str(result.get('phone') or '')
    result['email'] = str(result.get('email') or '')
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

# --- MFA (Multi-Factor Authentication) Pure Python TOTP Implementation ---
import base64
import struct

def generate_totp_secret() -> str:
    import secrets
    raw = secrets.token_bytes(10)
    return base64.b32encode(raw).decode('utf-8').replace('=', '')

def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    try:
        secret = secret.strip().replace(" ", "")
        missing_padding = len(secret) % 8
        if missing_padding:
            secret += '=' * (8 - missing_padding)
        key = base64.b32decode(secret, casefold=True)
    except Exception:
        return False

    try:
        val_code = int(code.strip())
    except ValueError:
        return False

    time_step = int(time.time() / 30)

    for t in range(time_step - window, time_step + window + 1):
        msg = struct.pack(">Q", t)
        hmac_hash = hmac.new(key, msg, hashlib.sha1).digest()
        offset = hmac_hash[-1] & 0x0f
        truncated = struct.unpack(">I", hmac_hash[offset:offset+4])[0] & 0x7fffffff
        computed_code = truncated % 1000000
        if computed_code == val_code:
            return True
            
    return False

# In-memory session store for temporary MFA tickets: temp_token -> { user_id, username, expires_at }
_temp_mfa_tokens: dict[str, dict] = {}


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
        row = conn.execute(
            "SELECT s.*, COALESCE(u.role_profile, '') AS role_profile, "
            "COALESCE(u.tenant_id, '') AS tenant_id "
            "FROM sessions s LEFT JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()
        if not row:
            logger.debug("[Auth Session] Token '%s...' not found in sessions table", token[:10])
            return None
        created_at = row['created_at']
        try:
            created_at_float = float(created_at)
        except (ValueError, TypeError):
            created_at_float = 0.0
            logger.error(f"[Auth Session Debug] Failed to convert created_at '{created_at}' to float")
        
        elapsed = time.time() - created_at_float
        if elapsed > _SESSION_TTL:
            logger.debug(
                "[Auth Session] Token '%s...' expired. elapsed=%.2fs TTL=%ss",
                token[:10], elapsed, _SESSION_TTL,
            )
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

def _require_user_administrator(request: Request) -> dict:
    """Protect user-management reads/writes, including role-profile assignment."""
    auth_header = request.headers.get('Authorization', '') if request else ''
    token = auth_header.replace('Bearer ', '', 1) if auth_header.startswith('Bearer ') else ''
    session = validate_session_token(token)
    if not session:
        raise HTTPException(status_code=401, detail='Not authenticated')
    if session.get('role') != 'Administrator' and session.get('role_profile') != 'System Administrator':
        raise HTTPException(status_code=403, detail='Administrator permission required')
    return session

@router.get("/users")
def read_users(request: Request):
    _require_user_administrator(request)
    conn = get_db_connection()
    try:
        users = conn.execute(
            'SELECT id, username, role, role_profile, status, last_login as lastLogin, avatar_url, group_name, change_groups_json, notification_channels, preferred_language, display_name, phone, email, mfa_enabled FROM users'
        ).fetchall()
        # Fetch the (small) shared notification-channel templates once and
        # reuse for every row — was previously per-row (N+1 query and
        # connection amplification).
        shared_rows = conn.execute(
            'SELECT platform, webhook_url, enabled, secret, creator_username FROM global_notification_channels'
        ).fetchall()
        shared_channels = [dict(r) for r in shared_rows]
        return [_hydrate_user_row(u, shared_channels=shared_channels) for u in users]
    finally:
        conn.close()

@router.post("/users")
async def create_user(request: Request, user: dict = Body(...)):
    actor = _require_user_administrator(request)
    user_id = user.get('id') or str(uuid.uuid4())
    raw_password = str(user.get('password') or '')
    username = str(user.get('username') or '').strip()
    group_name = str(user.get('group_name') or '').strip()
    change_groups = _normalize_change_groups(user.get('change_groups'))
    display_name = str(user.get('display_name') or '').strip()
    phone = str(user.get('phone') or '').strip()
    email = str(user.get('email') or '').strip()
    role = str(user.get('role') or '').strip()
    role_profile = _validate_role_profile(user.get('role_profile'))
    if role_profile is None and str(user.get('role_profile') or '').strip():
        raise HTTPException(status_code=400, detail='Invalid resource role profile')
    validation_error = _validate_new_user_fields(username, raw_password, display_name, phone, email, role, group_name)
    if validation_error:
        raise HTTPException(status_code=400, detail=validation_error)
    hashed = await _hash_password(raw_password)
    conn = get_db_connection()
    try:
        duplicate = conn.execute('SELECT 1 FROM users WHERE username = ? LIMIT 1', (username,)).fetchone()
        if duplicate:
            raise HTTPException(status_code=409, detail='Username already exists')
        conn.execute(
            'INSERT INTO users (id, username, password, role, role_profile, status, last_login, avatar_url, group_name, change_groups_json, display_name, phone, email) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                user_id,
                username,
                hashed,
                role,
                role_profile or '',
                'active',
                'Never',
                user.get('avatar_url'),
                group_name,
                json.dumps(change_groups, ensure_ascii=False),
                display_name,
                phone,
                email,
            ),
        )
        conn.commit()
        log_audit_event(
            event_type='USER_CREATE',
            category='identity',
            severity='medium',
            status='success',
            summary=f"Created user {username}",
            actor_username=actor.get('username') or user.get('actor_username') or 'admin',
            actor_role=actor.get('role') or user.get('actor_role') or 'Administrator',
            source_ip=request.client.host if request and request.client else None,
            target_type='user',
            target_id=user_id,
            target_name=username,
            details={'role': user.get('role'), 'group_name': group_name, 'change_groups': change_groups},
        )
        row = conn.execute(
            'SELECT id, username, role, role_profile, status, last_login as lastLogin, avatar_url, group_name, change_groups_json, notification_channels, preferred_language, display_name, phone, email FROM users WHERE id = ?',
            (user_id,),
        ).fetchone()
        return _hydrate_user_row(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/switch-user")
def switch_user(request: Request, payload: dict = Body(...)):
    """
    GitHub-like account switcher. 
    Allows an Administrator to switch to another user session without password.
    """
    target_username = payload.get('username')
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '') if auth.startswith('Bearer ') else ''
    current_sess = validate_session_token(token)
    
    if not current_sess or current_sess['role'] != 'Administrator':
        raise HTTPException(status_code=403, detail="Only administrators can switch users")
        
    conn = get_db_connection()
    try:
        user = conn.execute('SELECT * FROM users WHERE username = ?', (target_username,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="Target user not found")
            
        user_dict = dict(user)
        new_token = _create_token()
        # await _store_session is not async yet but we can keep it as is or wrap it
        _store_session(new_token, user_dict)
        
        # Hydrate user data for frontend
        profile_row = conn.execute(
            'SELECT id, username, role, role_profile, avatar_url, group_name, change_groups_json, notification_channels, preferred_language FROM users WHERE id = ?',
            (user_dict['id'],),
        ).fetchone()
        profile = _hydrate_user_row(profile_row)
        
        log_audit_event(
            event_type='USER_SWITCH',
            category='identity',
            severity='medium',
            status='success',
            summary=f"Admin {current_sess['username']} switched to user {target_username}",
            actor_username=current_sess['username'],
            actor_role='Administrator',
            source_ip=request.client.host if request and request.client else None,
            target_type='user',
            target_name=target_username,
        )
        
        return {
            "success": True,
            "token": new_token,
            "user": profile,
        }
    finally:
        conn.close()


@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, payload: dict = Body(...)):
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
        if user:
            db_pwd = user['password']
            logger.info(f"[Auth Debug] User found: '{safe_username}', input_pwd_len={len(password or '')}, db_pwd_hash_prefix='{db_pwd[:12] if db_pwd else 'empty'}', is_bcrypt={_is_bcrypt_hash(db_pwd)}")
        else:
            logger.warning(f"[Auth Debug] User NOT found in database: '{safe_username}'")

        if user and await _verify_password(password, user['password']):
            logger.info(f"Login successful for user: {safe_username}")
            last_login = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Migrate legacy plaintext password to bcrypt on the fly
            if not _is_bcrypt_hash(user['password']):
                hashed = await _hash_password(password)
                conn.execute('UPDATE users SET last_login = ?, password = ? WHERE id = ?', (last_login, hashed, user['id']))
                logger.info(f"Migrated password to bcrypt for user: {safe_username}")
            else:
                conn.execute('UPDATE users SET last_login = ? WHERE id = ?', (last_login, user['id']))
            conn.commit()

            user_dict = dict(user)
            _clear_login_failures(safe_username)
            
            # --- MFA Check ---
            if user['mfa_enabled']:
                temp_token = _create_token()
                _temp_mfa_tokens[temp_token] = {
                    "user_id": user_dict['id'],
                    "username": user_dict['username'],
                    "expires_at": time.time() + 300
                }
                return {
                    "success": True,
                    "mfa_required": True,
                    "temp_token": temp_token
                }

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
                'SELECT id, username, role, role_profile, avatar_url, group_name, change_groups_json, notification_channels, preferred_language, mfa_enabled FROM users WHERE id = ?',
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
                detail = "Invalid credentials. Account may be locked soon."
            raise HTTPException(status_code=401, detail=detail)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


# ── Forgot-password: send verification code via notification channels ──

_RESET_CODE_EXPIRE_MIN = 5
_RESET_CODE_LENGTH = 6

import secrets as _secrets

def _generate_reset_code() -> str:
    return ''.join([str(_secrets.randbelow(10)) for _ in range(_RESET_CODE_LENGTH)])


@router.post("/forgot-password/send-code")
@limiter.limit("3/minute")
def forgot_password_send_code(request: Request, payload: dict = Body(...)):
    """Send a verification code to the user's configured notification channels."""
    username = (payload.get('username') or '').strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")

    conn = get_db_connection()
    try:
        user = conn.execute(
            'SELECT id, username, notification_channels, preferred_language FROM users WHERE username = ?',
            (username,),
        ).fetchone()
        # Always return success to avoid username enumeration
        if not user:
            logger.warning(f"Password reset requested for non-existent user: {username}")
            return {"success": True, "message": "If an account with that username exists and has notification channels configured, a code has been sent."}

        channels = {}
        try:
            channels = json.loads(user['notification_channels'] or '{}')
        except Exception:
            pass

        # Find at least one enabled channel
        feishu = channels.get('feishu') or {}
        dingtalk = channels.get('dingtalk') or {}
        wechat = channels.get('wechat') or {}

        has_channel = (
            (feishu.get('enabled') and feishu.get('webhook_url', '').strip()) or
            (dingtalk.get('enabled') and dingtalk.get('webhook_url', '').strip()) or
            (wechat.get('enabled') and wechat.get('webhook_url', '').strip())
        )
        if not has_channel:
            # Return generic message — don't reveal whether channels are configured
            return {"success": False, "message": "No notification channels configured for this account. Please contact your administrator."}

        # Generate and store code
        code = _generate_reset_code()
        now = time.time()
        expires_at = now + _RESET_CODE_EXPIRE_MIN * 60

        # Invalidate previous unused codes
        conn.execute("UPDATE password_reset_codes SET used = 1 WHERE username = ? AND used = 0", (username,))
        conn.execute(
            "INSERT INTO password_reset_codes (username, code, created_at, expires_at, used) VALUES (?, ?, ?, ?, 0)",
            (username, code, now, expires_at),
        )
        conn.commit()

        lang = (user['preferred_language'] or 'zh').lower()
        sent_to = []

        # Send to all enabled channels
        if feishu.get('enabled') and feishu.get('webhook_url', '').strip():
            ok, msg = notification_service.send_feishu_verification_code(
                feishu['webhook_url'], username, code, _RESET_CODE_EXPIRE_MIN, lang
            )
            sent_to.append({"platform": "feishu", "success": ok})
            if not ok:
                logger.warning(f"Feishu verification code send failed for {username}: {msg}")

        if dingtalk.get('enabled') and dingtalk.get('webhook_url', '').strip():
            ok, msg = notification_service.send_dingtalk_verification_code(
                dingtalk['webhook_url'], username, code, _RESET_CODE_EXPIRE_MIN, lang,
                secret=dingtalk.get('secret', ''),
            )
            sent_to.append({"platform": "dingtalk", "success": ok})

        if wechat.get('enabled') and wechat.get('webhook_url', '').strip():
            ok, msg = notification_service.send_wechat_verification_code(
                wechat['webhook_url'], username, code, _RESET_CODE_EXPIRE_MIN, lang,
            )
            sent_to.append({"platform": "wechat", "success": ok})

        any_success = any(s['success'] for s in sent_to)
        if not any_success:
            return {"success": False, "message": "Failed to send verification code. Please try again later."}

        log_audit_event(
            event_type='PASSWORD_RESET_REQUESTED',
            category='identity',
            severity='medium',
            status='success',
            summary=f"Password reset code sent for user {username}",
            actor_username=username,
            actor_role='unknown',
            source_ip=request.client.host if request and request.client else None,
            target_type='user',
            target_name=username,
        )
        logger.info(f"Password reset code sent for user: {username}")
        return {"success": True, "message": "Verification code sent to your notification channels.", "channels": sent_to}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Forgot password error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@router.post("/forgot-password/reset")
@limiter.limit("5/minute")
async def forgot_password_reset(request: Request, payload: dict = Body(...)):
    """Verify code and reset password."""
    username = (payload.get('username') or '').strip()
    code = (payload.get('code') or '').strip()
    new_password = payload.get('new_password', '')

    if not username or not code or not new_password:
        raise HTTPException(status_code=400, detail="Username, code, and new_password are required")

    # Validate password strength
    pwd_error = _validate_password_strength(new_password)
    if pwd_error:
        raise HTTPException(status_code=400, detail=pwd_error)

    conn = get_db_connection()
    try:
        # Find valid unused code
        row = conn.execute(
            "SELECT id, code, expires_at FROM password_reset_codes WHERE username = ? AND used = 0 ORDER BY created_at DESC LIMIT 1",
            (username,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=400, detail="Invalid or expired verification code")

        if time.time() > row['expires_at']:
            conn.execute("UPDATE password_reset_codes SET used = 1 WHERE id = ?", (row['id'],))
            conn.commit()
            raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new one.")

        if not hmac.compare_digest(code, row['code']):
            raise HTTPException(status_code=400, detail="Invalid verification code")

        # Mark code as used
        conn.execute("UPDATE password_reset_codes SET used = 1 WHERE id = ?", (row['id'],))

        # Update password
        hashed = await _hash_password(new_password)
        conn.execute("UPDATE users SET password = ? WHERE username = ?", (hashed, username))

        # Clear login failures / lockout
        conn.execute("DELETE FROM login_failures WHERE username = ?", (username,))
        # A password reset must invalidate existing sessions so the old
        # credential cannot remain usable through an already-issued token.
        conn.execute(
            "DELETE FROM sessions WHERE user_id = (SELECT id FROM users WHERE username = ?)",
            (username,),
        )
        conn.commit()

        log_audit_event(
            event_type='PASSWORD_RESET_COMPLETED',
            category='identity',
            severity='high',
            status='success',
            summary=f"Password reset completed for user {username}",
            actor_username=username,
            actor_role='unknown',
            source_ip=request.client.host if request and request.client else None,
            target_type='user',
            target_name=username,
        )
        logger.info(f"Password reset completed for user: {username}")
        return {"success": True, "message": "Password reset successfully. You can now log in with your new password."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Password reset error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@router.post("/forgot-password/mfa-reset")
@limiter.limit("5/minute")
async def forgot_password_mfa_reset(request: Request, payload: dict = Body(...)):
    """Reset a password with the account's enrolled TOTP authenticator."""
    username = (payload.get('username') or '').strip()
    code = (payload.get('code') or '').strip()
    new_password = payload.get('new_password', '')

    if not username or not code or not new_password:
        raise HTTPException(status_code=400, detail="Username, code, and new_password are required")

    pwd_error = _validate_password_strength(new_password)
    if pwd_error:
        raise HTTPException(status_code=400, detail=pwd_error)

    conn = get_db_connection()
    try:
        user = conn.execute(
            'SELECT id, username, role, mfa_enabled, mfa_secret FROM users WHERE username = ?',
            (username,),
        ).fetchone()
        if not user or not user['mfa_enabled'] or not user['mfa_secret'] or not verify_totp(user['mfa_secret'], code):
            raise HTTPException(status_code=400, detail="Invalid account or MFA code")

        hashed = await _hash_password(new_password)
        conn.execute('UPDATE users SET password = ? WHERE id = ?', (hashed, user['id']))
        conn.execute('DELETE FROM login_failures WHERE username = ?', (username,))
        conn.execute('DELETE FROM sessions WHERE user_id = ?', (user['id'],))
        conn.commit()

        log_audit_event(
            event_type='PASSWORD_RESET_COMPLETED',
            category='identity',
            severity='high',
            status='success',
            summary=f"Password reset completed with MFA for user {username}",
            actor_id=str(user['id']),
            actor_username=username,
            actor_role=user['role'] or 'unknown',
            source_ip=request.client.host if request and request.client else None,
            target_type='user',
            target_id=str(user['id']),
            target_name=username,
            details={'method': 'totp'},
        )
        return {"success": True, "message": "Password reset successfully. You can now log in with your new password."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MFA password reset error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@router.put("/users/{user_id}")
async def update_user(user_id: str, request: Request, user: dict = Body(...)):
    auth_header = request.headers.get('Authorization', '')
    session_token = auth_header.replace('Bearer ', '', 1) if auth_header.startswith('Bearer ') else ''
    session = validate_session_token(session_token)
    if not session:
        raise HTTPException(status_code=401, detail='Not authenticated')
    if str(session.get('user_id')) != str(user_id) and session.get('role') != 'Administrator' and session.get('role_profile') != 'System Administrator':
        raise HTTPException(status_code=403, detail='You may only update your own profile')

    conn = get_db_connection()
    try:
        existing = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="User not found")
        username = user.get('username', existing['username'])
        is_admin = session.get('role') == 'Administrator' or session.get('role_profile') == 'System Administrator'
        role = user.get('role', existing['role']) if is_admin else existing['role']
        requested_profile = user.get('role_profile', existing['role_profile'] if 'role_profile' in existing.keys() else '')
        role_profile = _validate_role_profile(requested_profile) if is_admin else str(existing['role_profile'] or '')
        if is_admin and str(requested_profile or '').strip() and role_profile is None:
            raise HTTPException(status_code=400, detail='Invalid resource role profile')
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
        if notification_channels_raw is not None and isinstance(notification_channels_raw, dict):
            for platform, cfg in notification_channels_raw.items():
                if not isinstance(cfg, dict):
                    continue
                
                existing_global = conn.execute(
                    'SELECT webhook_url, secret, creator_username FROM global_notification_channels WHERE platform = ?',
                    (platform,)
                ).fetchone()
                
                new_url = str(cfg.get('webhook_url') or '').strip()
                new_enabled = 1 if cfg.get('enabled') else 0
                new_secret = str(cfg.get('secret') or '').strip()
                
                final_url = ''
                final_secret = ''
                
                auth_username = existing['username']
                
                if not existing_global:
                    final_url = new_url
                    final_secret = new_secret
                    final_enabled = new_enabled
                    creator = auth_username
                else:
                    creator = existing_global['creator_username'] or auth_username
                    if auth_username == creator or existing['role'] == 'Administrator':
                        if '***' not in new_url and '****' not in new_url and new_url != '':
                            final_url = new_url
                        else:
                            final_url = existing_global['webhook_url']
                            
                        if '***' not in new_secret and '****' not in new_secret and new_secret != '':
                            final_secret = new_secret
                        else:
                            final_secret = existing_global['secret']
                            
                        final_enabled = new_enabled
                    else:
                        final_url = existing_global['webhook_url']
                        final_secret = existing_global['secret']
                        final_enabled = existing_global['enabled']
                
                conn.execute(
                    '''
                    INSERT INTO global_notification_channels (platform, webhook_url, enabled, secret, creator_username, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(platform) DO UPDATE SET webhook_url=excluded.webhook_url, enabled=excluded.enabled, secret=excluded.secret, updated_at=excluded.updated_at
                    ''',
                    (platform, final_url, final_enabled, final_secret, creator, datetime.now().isoformat())
                )

        notification_channels_str = json.dumps(notification_channels_raw) if notification_channels_raw is not None else (existing['notification_channels'] or '{}')
        change_groups_str = json.dumps(change_groups, ensure_ascii=False)
        password = user.get('password')
        old_password = user.get('old_password') or user.get('oldPassword')
        fixed_pin = user.get('fixedPin')
        if fixed_pin is not None and str(fixed_pin) != '':
            if str(existing['role'] or '').lower() not in ('administrator', 'admin'):
                raise HTTPException(status_code=403, detail='Only administrator accounts may configure a fixed PIN')
            if not str(fixed_pin).isdigit() or len(str(fixed_pin)) != 6:
                raise HTTPException(status_code=400, detail='Fixed PIN must be exactly 6 digits')
        display_name = str(user.get('display_name', existing['display_name'] if 'display_name' in existing.keys() else '') or '').strip()
        phone = str(user.get('phone', existing['phone'] if 'phone' in existing.keys() else '') or '').strip()
        email = str(user.get('email', existing['email'] if 'email' in existing.keys() else '') or '').strip()
        
        existing_dict = dict(existing)
        hashed_pin = existing_dict.get('fixed_pin', '')
        if fixed_pin:
            hashed_pin = await _hash_password(str(fixed_pin))
            
        if password:
            if not old_password or not await _verify_password(old_password, existing['password']):
                raise HTTPException(status_code=400, detail="Current password is incorrect / 当前密码不正确")
            strength_err = _validate_password_strength(password)
            if strength_err:
                raise HTTPException(status_code=400, detail=strength_err)
            hashed = await _hash_password(password)
            conn.execute(
                'UPDATE users SET username = ?, role = ?, role_profile = ?, password = ?, avatar_url = ?, group_name = ?, change_groups_json = ?, notification_channels = ?, preferred_language = ?, fixed_pin = ?, display_name = ?, phone = ?, email = ? WHERE id = ?',
                (username, role, role_profile or '', hashed, avatar_url, group_name, change_groups_str, notification_channels_str, preferred_language, hashed_pin, display_name, phone, email, user_id)
            )
        else:
            conn.execute(
                'UPDATE users SET username = ?, role = ?, role_profile = ?, avatar_url = ?, group_name = ?, change_groups_json = ?, notification_channels = ?, preferred_language = ?, fixed_pin = ?, display_name = ?, phone = ?, email = ? WHERE id = ?',
                (username, role, role_profile or '', avatar_url, group_name, change_groups_str, notification_channels_str, preferred_language, hashed_pin, display_name, phone, email, user_id)
            )
        conn.commit()
        result = conn.execute(
            'SELECT id, username, role, role_profile, status, last_login as lastLogin, avatar_url, group_name, change_groups_json, notification_channels, preferred_language, display_name, phone, email, mfa_enabled FROM users WHERE id = ?',
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
            'SELECT id, username, role, role_profile, avatar_url, group_name, change_groups_json, notification_channels, preferred_language, display_name, phone, email, mfa_enabled FROM users WHERE id = ?',
            (sess['user_id'],)
        ).fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="Session user not found")
        return {"success": True, "user": _hydrate_user_row(user)}
    finally:
        conn.close()


def _get_system_name() -> str:
    system_name = "Nexora"
    try:
        from database import get_db_connection
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key = 'platform_settings'"
            ).fetchone()
            if row:
                import json as _json
                val = row[0] if isinstance(row, (list, tuple)) else row['value']
                ps = _json.loads(val)
                if ps.get('system_name'):
                    system_name = ps['system_name']
        finally:
            conn.close()
    except Exception:
        pass
    return system_name


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
    sys_name = _get_system_name()
    test_alert = {
        'title':            f'{sys_name} 连通性测试',
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


# --- MFA SETUP & VERIFICATION ENDPOINTS ---

def _get_session_user(request: Request) -> dict:
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '') if auth.startswith('Bearer ') else ''
    sess = validate_session_token(token)
    if not sess:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return sess

@router.post("/mfa/setup")
def mfa_setup(request: Request):
    sess = _get_session_user(request)
    conn = get_db_connection()
    try:
        user = conn.execute('SELECT username, mfa_secret FROM users WHERE id = ?', (sess['user_id'],)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Use existing secret if already configured, otherwise generate new one
        secret = user['mfa_secret'] or generate_totp_secret()
        sys_name = _get_system_name()
        qr_code_uri = f"otpauth://totp/{sys_name}:{user['username']}?secret={secret}&issuer={sys_name}"
        return {
            "success": True,
            "secret": secret,
            "qr_code_uri": qr_code_uri
        }
    finally:
        conn.close()

@router.post("/mfa/enable")
def mfa_enable(request: Request, payload: dict = Body(...)):
    sess = _get_session_user(request)
    code = payload.get('code')
    secret = payload.get('secret')
    if not code or not secret:
        raise HTTPException(status_code=400, detail="code and secret are required")

    if not verify_totp(secret, code, window=1):
        raise HTTPException(status_code=400, detail="验证码错误，请重新输入")

    conn = get_db_connection()
    try:
        conn.execute('UPDATE users SET mfa_secret = ?, mfa_enabled = 1 WHERE id = ?', (secret, sess['user_id']))
        conn.commit()
        return {"success": True, "message": "MFA 开启成功"}
    finally:
        conn.close()

@router.post("/mfa/disable")
async def mfa_disable(request: Request, payload: dict = Body(...)):
    sess = _get_session_user(request)
    password = payload.get('password')
    if not password:
        raise HTTPException(status_code=400, detail="password is required")

    conn = get_db_connection()
    try:
        user = conn.execute('SELECT password FROM users WHERE id = ?', (sess['user_id'],)).fetchone()
        if not user or not await _verify_password(password, user['password']):
            raise HTTPException(status_code=400, detail="当前密码错误，无法关闭 MFA")

        conn.execute('UPDATE users SET mfa_secret = ?, mfa_enabled = 0 WHERE id = ?', ('', sess['user_id']))
        conn.commit()
        return {"success": True, "message": "MFA 关闭成功"}
    finally:
        conn.close()

@router.post("/mfa/verify")
async def mfa_verify(request: Request, payload: dict = Body(...)):
    temp_token = payload.get('temp_token')
    code = payload.get('code')
    
    # Clean up expired temp tokens first
    now_ts = time.time()
    for k in list(_temp_mfa_tokens.keys()):
        if _temp_mfa_tokens[k]["expires_at"] < now_ts:
            _temp_mfa_tokens.pop(k, None)

    if not temp_token or not code:
        raise HTTPException(status_code=400, detail="temp_token and code are required")

    token_info = _temp_mfa_tokens.get(temp_token)
    if not token_info:
        raise HTTPException(status_code=400, detail="验证链接已失效或已过期，请重新登录")

    username = token_info["username"]
    conn = get_db_connection()
    try:
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if not user or not user['mfa_enabled'] or not user['mfa_secret']:
            raise HTTPException(status_code=400, detail="未启用 MFA 二次认证或用户不存在")

        if not verify_totp(user['mfa_secret'], code, window=1):
            raise HTTPException(status_code=401, detail="二次验证码错误")

        # Success!
        _temp_mfa_tokens.pop(temp_token, None) # consume temp token
        user_dict = dict(user)
        last_login = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute('UPDATE users SET last_login = ? WHERE id = ?', (last_login, user['id']))
        conn.commit()

        _clear_login_failures(username)
        log_audit_event(
            event_type='LOGIN_SUCCESS_MFA',
            category='identity',
            severity='low',
            status='success',
            summary=f"User {username} logged in via MFA",
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
            'SELECT id, username, role, role_profile, avatar_url, group_name, change_groups_json, notification_channels, preferred_language, mfa_enabled FROM users WHERE id = ?',
            (user_dict['id'],),
        ).fetchone()
        profile = _hydrate_user_row(profile_row)
        profile['lastLogin'] = last_login

        return {
            "success": True,
            "token": token,
            "user": profile,
        }
    finally:
        conn.close()
