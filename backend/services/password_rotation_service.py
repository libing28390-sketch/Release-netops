"""
Password Rotation Service - 设备密码自动轮换。

功能:
1. check_expiring()  - 扫描即将过期的设备密码列表
2. rotate_password() - 对单台设备执行 SSH 改密 + 更新 DB/Vault
3. run_rotation_sweep() - 定时调度入口，批量处理到期设备

支持厂商:
- Cisco IOS/IOS-XE: terminal length 0 → username secret 命令
- Huawei VRP: aaa → local-user → password cipher 命令
- H3C Comware: local-user password+service-type
- Arista EOS: username secret

轮换策略:
- 自动生成 20 字符高强度随机密码
- 登录 → 改密 → 校验新密码 → 更新 DB（两段式确认）
"""

import logging
import secrets
import string
import shlex
import threading
import uuid as _uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from typing import Any

from database import get_db_connection
from core.config import settings
from core.crypto import encrypt_credential, decrypt_credential
from services.vault_service import credential_is_shared, resolve_device_credentials, write_credentials as vault_write, vault_available

logger = logging.getLogger(__name__)


# Characters safe for use in network device CLI (avoid ?, !, #, $, %, ^, &
# which can trigger special CLI behavior on various platforms)
_SAFE_SPECIAL = '-_=+@*~'
_PWD_ALPHABET = string.ascii_letters + string.digits + _SAFE_SPECIAL


def _generate_password(length: int = 20) -> str:
    """生成高强度随机密码（大小写字母 + 数字 + CLI 安全特殊符号）。"""
    while True:
        pwd = ''.join(secrets.choice(_PWD_ALPHABET) for _ in range(length))
        if (any(c.islower() for c in pwd)
                and any(c.isupper() for c in pwd)
                and any(c.isdigit() for c in pwd)
                and any(c in _SAFE_SPECIAL for c in pwd)):
            return pwd


def _sync_credential_vault(device: dict, role: str, enc_new: str) -> None:
    """
    Mirror a successful rotation into the credentials vault (``credentials`` table).

    After the credential-decoupling refactor, the vault — not the legacy
    ``devices.*`` columns — is the source of truth for login/backup. Rotation
    historically wrote only to ``devices.*``, so a rotated password never reached
    the vault and config backup would break. This keeps them consistent.

    Explicit role bindings are authoritative: normal rotation updates the
    normal credential, admin rotation updates ``admin_credential_id`` and
    enable rotation updates the admin credential's ``enable_password``.  The
    username comparison remains only as a compatibility guard for legacy
    devices that have no explicit admin binding.
    """
    normal_cred_id = device.get('credential_id')
    admin_cred_id = device.get('admin_credential_id')
    if role == 'normal':
        cred_id = normal_cred_id
        explicit_role_binding = False
    elif role in ('admin', 'enable'):
        # Enable is a privileged secret and belongs to the admin credential
        # when one is bound. Fall back to the legacy credential for old rows.
        cred_id = admin_cred_id or normal_cred_id
        explicit_role_binding = bool(admin_cred_id)
    else:
        return

    if not cred_id or not enc_new:
        return
    try:
        conn = get_db_connection()
        try:
            row = conn.execute(
                'SELECT username, account_role FROM credentials WHERE id = ?',
                (cred_id,),
            ).fetchone()
            if not row:
                return
            credential = dict(row)
            vault_user = (credential.get('username') or '').strip().lower()
            declared_role = str(credential.get('account_role') or 'unbound').strip().lower()
            if role == 'normal':
                explicit_role_binding = declared_role == 'normal'
            elif role == 'admin':
                explicit_role_binding = bool(admin_cred_id) or declared_role in {'admin', 'privileged'}

            if role == 'enable':
                conn.execute('UPDATE credentials SET enable_password = ? WHERE id = ?', (enc_new, cred_id))
                conn.commit()
                logger.info("[Rotation] Synced new enable secret into credential vault %s", cred_id)
                return

            if explicit_role_binding:
                conn.execute('UPDATE credentials SET encrypted_password = ? WHERE id = ?', (enc_new, cred_id))
                conn.commit()
                logger.info("[Rotation] Synced new explicitly bound %s password into credential vault %s", role, cred_id)
                return

            target_user = (
                (device.get('admin_username') or device.get('username'))
                if role == 'admin'
                else (device.get('normal_username') or 'user')
            )
            if vault_user and target_user and vault_user == str(target_user).strip().lower():
                conn.execute('UPDATE credentials SET encrypted_password = ? WHERE id = ?', (enc_new, cred_id))
                conn.commit()
                logger.info("[Rotation] Synced new %s password into credential vault %s", role, cred_id)
        finally:
            conn.close()
    except Exception as exc:
        logger.error("[Rotation] Failed to sync credential vault for %s: %s",
                     device.get('hostname') or device.get('id'), exc, exc_info=True)


def _commit_vault_after_rotation(device: dict, role: str, enc_new: str, sync_vault: bool) -> None:
    """Commit a successful single-device rotation to the vault when authorized.

    Credential-wide synchronization deliberately passes ``sync_vault=False``:
    the vault is committed once, centrally, only after every target verifies.
    """
    if sync_vault:
        _sync_credential_vault(device, role, enc_new)


# ── 厂商改密命令生成 ──────────────────────────────

def _cisco_change_password_commands(username: str, new_password: str) -> list[str]:
    """Config-mode commands only. Type 0 forces plaintext interpretation."""
    return [f'username {username} secret 0 {new_password}']


def _huawei_change_password_commands(username: str, new_password: str) -> list[str]:
    """Config-mode commands only. send_config_set handles system-view entry/exit."""
    return [
        'aaa',
        f'local-user {username} password cipher {new_password}',
        'quit',   # exit AAA sub-context
    ]


def _h3c_change_password_commands(username: str, new_password: str) -> list[str]:
    """Config-mode commands only. send_config_set handles system-view entry/exit."""
    return [
        f'local-user {username} class manage',
        f'password simple {new_password}',
        'service-type ssh terminal',
        'quit',   # exit local-user sub-context
    ]


def _arista_change_password_commands(username: str, new_password: str) -> list[str]:
    """Config-mode commands only. EOS session handler manages session entry/exit."""
    return [f'username {username} secret {new_password}']


def _linux_change_password_commands(username: str, new_password: str) -> list[str]:
    """Linux shell commands. Using chpasswd for non-interactive rotation."""
    if username == 'root':
        return [f'echo "{username}:{new_password}" | chpasswd']
    return [f'echo "{username}:{new_password}" | sudo -S chpasswd']


_CHANGE_PASSWORD_HANDLERS: dict[str, Any] = {
    'cisco_ios': _cisco_change_password_commands,
    'cisco_iosxe': _cisco_change_password_commands,
    'cisco_xe': _cisco_change_password_commands,
    'cisco_nxos': _cisco_change_password_commands,
    'huawei_vrp': _huawei_change_password_commands,
    'h3c_comware': _h3c_change_password_commands,
    'arista_eos': _arista_change_password_commands,
    'linux': _linux_change_password_commands,
    'ubuntu': _linux_change_password_commands,
    'centos': _linux_change_password_commands,
    'debian': _linux_change_password_commands,
    'redhat': _linux_change_password_commands,
}

# Exec-mode save commands per platform (run AFTER config mode exit)
_SAVE_COMMANDS: dict[str, str] = {
    'cisco_ios': 'write memory',
    'cisco_iosxe': 'write memory',
    'cisco_xe': 'write memory',
    'cisco_nxos': 'copy running-config startup-config',
    'huawei_vrp': 'save force',
    'h3c_comware': 'save force',
    'arista_eos': 'write memory',
    'linux': 'sync',
    'ubuntu': 'sync',
    'centos': 'sync',
    'debian': 'sync',
    'redhat': 'sync',
}


# ── 策略持久化与核心功能 ──────────────────────────────────────

_VALID_ROTATION_ROLES = ('normal', 'admin', 'enable')


def _normalize_included_roles(roles: Any) -> list[str]:
    if not roles:
        return ['admin']
    normalized: list[str] = []
    for item in roles:
        role = str(item or '').strip().lower()
        if role in _VALID_ROTATION_ROLES and role not in normalized:
            normalized.append(role)
    return normalized or ['admin']


def _compute_next_scheduled_run_at(hour: int, minute: int) -> str:
    now = datetime.now(timezone.utc)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    return candidate.isoformat()


def _ensure_rotation_policy_row(conn) -> dict[str, Any]:
    import json as _json

    row = conn.execute(
        "SELECT * FROM password_rotation_policy WHERE id = 'default'"
    ).fetchone()
    if row:
        return dict(row)
    now_str = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    default_enabled = bool(settings.PASSWORD_ROTATION_ENABLED)
    default_interval = max(1, int(settings.PASSWORD_ROTATION_INTERVAL_DAYS or 90))
    default_notify = max(1, int(settings.PASSWORD_ROTATION_NOTIFY_DAYS or 14))
    conn.execute(
        """INSERT INTO password_rotation_policy
           (id, auto_rotate_enabled, interval_days, notify_days, schedule_hour, schedule_minute,
            included_roles_json, updated_by, updated_at)
           VALUES ('default', ?, ?, ?, 2, 0, '["admin"]', 'system', ?)
           ON CONFLICT (id) DO NOTHING""",
        (default_enabled, default_interval, default_notify, now_str),
    )
    conn.commit()
    created = conn.execute(
        "SELECT * FROM password_rotation_policy WHERE id = 'default'"
    ).fetchone()
    if created:
        return dict(created)
    return {
        'id': 'default',
        'auto_rotate_enabled': default_enabled,
        'interval_days': default_interval,
        'notify_days': default_notify,
        'schedule_hour': 2,
        'schedule_minute': 0,
        'included_roles_json': _json.dumps(['admin']),
        'updated_by': 'system',
        'updated_at': now_str,
    }


def get_rotation_policy() -> dict[str, Any]:
    """Return the effective persisted password rotation policy."""
    import json as _json

    conn = get_db_connection()
    try:
        try:
            row = _ensure_rotation_policy_row(conn)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            row = {
                'auto_rotate_enabled': bool(settings.PASSWORD_ROTATION_ENABLED),
                'interval_days': max(1, int(settings.PASSWORD_ROTATION_INTERVAL_DAYS or 90)),
                'notify_days': max(1, int(settings.PASSWORD_ROTATION_NOTIFY_DAYS or 14)),
                'schedule_hour': 2,
                'schedule_minute': 0,
                'included_roles_json': '["admin"]',
                'updated_by': 'system',
                'updated_at': None,
            }
    finally:
        conn.close()

    try:
        roles = _normalize_included_roles(_json.loads(row.get('included_roles_json') or '["admin"]'))
    except Exception:
        roles = ['admin']
    enabled = bool(row.get('auto_rotate_enabled'))
    hour = int(row.get('schedule_hour') if row.get('schedule_hour') is not None else 2)
    minute = int(row.get('schedule_minute') if row.get('schedule_minute') is not None else 0)
    return {
        'auto_rotate_enabled': enabled,
        'interval_days': int(row.get('interval_days') or 90),
        'notify_days': int(row.get('notify_days') or 14),
        'schedule_hour': hour,
        'schedule_minute': minute,
        'included_roles': roles,
        'updated_by': str(row.get('updated_by') or ''),
        'updated_at': str(row['updated_at']) if row.get('updated_at') else None,
        'next_scheduled_run_at': _compute_next_scheduled_run_at(hour, minute) if enabled else None,
        'deployment_defaults': {
            'auto_rotate_enabled': bool(settings.PASSWORD_ROTATION_ENABLED),
            'interval_days': int(settings.PASSWORD_ROTATION_INTERVAL_DAYS or 90),
            'notify_days': int(settings.PASSWORD_ROTATION_NOTIFY_DAYS or 14),
        },
    }


def update_rotation_policy(
    *,
    auto_rotate_enabled: bool | None = None,
    interval_days: int | None = None,
    notify_days: int | None = None,
    included_roles: list[str] | None = None,
    updated_by: str = '',
) -> dict[str, Any]:
    """Persist updated password rotation policy and return before/after for audit."""
    import json as _json

    before = get_rotation_policy()
    next_enabled = before['auto_rotate_enabled'] if auto_rotate_enabled is None else bool(auto_rotate_enabled)
    next_interval = before['interval_days'] if interval_days is None else int(interval_days)
    next_notify = before['notify_days'] if notify_days is None else int(notify_days)
    next_roles = before['included_roles'] if included_roles is None else _normalize_included_roles(included_roles)

    if not (1 <= next_interval <= 3650):
        raise ValueError('interval_days must be between 1 and 3650')
    if not (1 <= next_notify <= 365):
        raise ValueError('notify_days must be between 1 and 365')
    if included_roles is not None:
        invalid = [str(r) for r in included_roles if str(r or '').strip().lower() not in _VALID_ROTATION_ROLES]
        if invalid:
            raise ValueError(f'Unsupported rotation role(s): {", ".join(invalid)}')
        if not next_roles:
            raise ValueError('included_roles must contain at least one role')

    now_str = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn = get_db_connection()
    try:
        _ensure_rotation_policy_row(conn)
        conn.execute(
            """UPDATE password_rotation_policy
                  SET auto_rotate_enabled = ?, interval_days = ?, notify_days = ?,
                      included_roles_json = ?, updated_by = ?, updated_at = ?
                WHERE id = 'default'""",
            (
                next_enabled,
                next_interval,
                next_notify,
                _json.dumps(next_roles),
                str(updated_by or ''),
                now_str,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    after = get_rotation_policy()
    return {'before': before, 'after': after}


def preview_rotation_policy_impact(*, included_roles: list[str] | None = None) -> dict[str, Any]:
    """Summarize devices and accounts affected if automatic rotation is enabled."""
    policy = get_rotation_policy()
    target_roles = _normalize_included_roles(included_roles) if included_roles is not None else policy['included_roles']
    expiring_all = check_expiring(days_ahead=policy['notify_days'], roles=target_roles)
    expired = [item for item in expiring_all if item['is_expired']]
    expiring_soon = [item for item in expiring_all if not item['is_expired']]

    conn = get_db_connection()
    try:
        rows = conn.execute(
            """SELECT id, normal_password_expires_at, admin_password_expires_at,
                      enable_password_expires_at, password_expires_at
                 FROM devices
                WHERE COALESCE(status, 'online') <> 'decommissioned'"""
        ).fetchall()
    finally:
        conn.close()

    unconfigured_count = 0
    for row in rows:
        for role in target_roles:
            expiry = _resolve_role_expiry(dict(row), role)
            if not expiry:
                unconfigured_count += 1

    return {
        'total_devices': len(rows),
        'included_roles': target_roles,
        'expired_accounts_count': len(expired),
        'expiring_soon_accounts_count': len(expiring_soon),
        'unconfigured_accounts_count': unconfigured_count,
        'schedule_window': f"{policy['schedule_hour']:02d}:{policy['schedule_minute']:02d} UTC",
    }


def _resolve_role_expiry(device: dict[str, Any], role: str) -> str:
    if role == 'normal':
        return str(device.get('normal_password_expires_at') or '').strip()
    if role == 'enable':
        return str(device.get('enable_password_expires_at') or '').strip()
    return (
        str(device.get('admin_password_expires_at') or '').strip()
        or str(device.get('password_expires_at') or '').strip()
    )


def _record_rotation_notification_if_new(
    dedup_key: str,
    *,
    device_id: str,
    role: str,
    event_type: str,
    message: str = '',
) -> bool:
    """Record a deduplicated rotation notification; returns True only on first emission."""
    now_str = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            """INSERT INTO password_rotation_notification_log
               (dedup_key, device_id, role, event_type, message, notified_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (dedup_key) DO NOTHING""",
            (dedup_key, device_id, role, event_type, message, now_str),
        )
        conn.commit()
        return int(getattr(cursor, 'rowcount', 0) or 0) == 1
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def check_expiring(
    days_ahead: int | None = None,
    *,
    roles: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    扫描即将过期或已过期的设备账号密码（按分角色到期列，兼顾旧列回退）。
    返回: [{ id, device_id, hostname, ip_address, role, password_expires_at, days_remaining, is_expired }]
    """
    policy = get_rotation_policy()
    if days_ahead is None:
        days_ahead = policy['notify_days']
    target_roles = _normalize_included_roles(roles) if roles is not None else policy['included_roles']
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=int(days_ahead))

    conn = get_db_connection()
    try:
        rows = conn.execute(
            """SELECT id, hostname, ip_address,
                      normal_password_expires_at,
                      admin_password_expires_at,
                      enable_password_expires_at,
                      password_expires_at
                 FROM devices
                WHERE COALESCE(status, 'online') <> 'decommissioned'"""
        ).fetchall()
        result = []
        for r in rows:
            dev = dict(r)
            for role in target_roles:
                expiry_raw = _resolve_role_expiry(dev, role)
                if not expiry_raw:
                    continue
                try:
                    exp = datetime.fromisoformat(expiry_raw.replace('Z', '+00:00'))
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if exp <= cutoff:
                    days_remaining = (exp - now).days
                    result.append({
                        'id': dev['id'],
                        'device_id': dev['id'],
                        'hostname': dev.get('hostname') or '',
                        'ip_address': dev.get('ip_address') or '',
                        'role': role,
                        'password_expires_at': expiry_raw,
                        'days_remaining': days_remaining,
                        'is_expired': exp <= now,
                    })
        return sorted(result, key=lambda x: (x.get('days_remaining', 9999), x.get('hostname', ''), x.get('role', '')))
    finally:
        conn.close()


def rotate_password(
    device_id: str,
    role: str = 'admin',
    target_password: str = None,
    *,
    credential_snapshot: dict[str, Any] | None = None,
    sync_vault: bool = True,
    login_username: str | None = None,
    login_password: str | None = None,
    connection_timeout: int | None = None,
    command_read_timeout: int | None = None,
) -> dict[str, Any]:
    """
    对单台设备的指定角色执行密码轮换。
    role: 'normal' | 'admin' | 'enable'
    """
    from drivers.factory import DriverFactory

    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
        if not row:
            return {'success': False, 'message': 'Device not found'}
        device = dict(row)
        
        # Fallback IP resolution from physical_assets if missing in devices
        if not device.get('ip_address'):
            pa_row = conn.execute('SELECT management_ip FROM physical_assets WHERE id = ?', (device.get('asset_id'),)).fetchone()
            if pa_row and pa_row['management_ip']:
                device['ip_address'] = pa_row['management_ip']
                logger.info(f"[Rotation] Resolved missing IP from physical_assets: {device['ip_address']}")

        # Fallback platform from physical_assets if missing in devices
        if not device.get('platform'):
            pa_row = conn.execute('SELECT platform FROM physical_assets WHERE id = ?', (device.get('asset_id'),)).fetchone()
            if pa_row and pa_row['platform']:
                device['platform'] = pa_row['platform']
                logger.info(f"[Rotation] Resolved missing platform from physical_assets: {device['platform']}")
        
        # Load management_port
        if not device.get('management_port'):
            pa_row = conn.execute('SELECT management_port FROM physical_assets WHERE id = ?', (device.get('asset_id'),)).fetchone()
            if pa_row and pa_row['management_port']:
                device['management_port'] = pa_row['management_port']
            else:
                device['management_port'] = 22
    finally:
        conn.close()

    creds = credential_snapshot or resolve_device_credentials(device)

    # A bound device is not an independent password-rotation target. Rotating
    # it here would make a shared credential point at one device's new password
    # while the other bound devices still use the old password. The credential
    # center's durable synchronization job is the only supported path.
    if sync_vault and (device.get('credential_id') or device.get('admin_credential_id')):
        binding_conn = get_db_connection()
        try:
            shared_binding = False
            for binding_id in (device.get('credential_id'), device.get('admin_credential_id')):
                if not binding_id:
                    continue
                binding_row = binding_conn.execute(
                    'SELECT id, account_role FROM credentials WHERE id = ?',
                    (binding_id,),
                ).fetchone()
                if credential_is_shared(binding_conn, binding_id, dict(binding_row) if binding_row else None, device_hostname=device.get('hostname')):
                    shared_binding = True
                    break
        finally:
            binding_conn.close()
        if shared_binding:
            return {
                'success': False,
                'code': 'credential_bound_use_credential_sync',
                'message': 'Device is bound to a credential; change the password from the credential center so all bound devices stay consistent',
            }
    
    # [LOGIC] Determine login credentials vs target credentials
    platform = (device.get('platform') or '').lower()
    
    # Smart fallback: if platform is empty or 'cisco_ios' (common default), 
    # check if it's actually a server to avoid using network drivers on Linux.
    asset_type = 'network_device'
    conn3 = get_db_connection()
    try:
        pa_row = conn3.execute('SELECT asset_type FROM physical_assets WHERE id = ?', (device.get('asset_id'),)).fetchone()
        if pa_row:
            asset_type = pa_row['asset_type']
    finally:
        conn3.close()

    if not platform or platform == 'cisco_ios':
        if asset_type == 'server':
            platform = 'linux'
            logger.info(f"[Rotation] Overriding default platform to 'linux' because asset_type is 'server'")
        else:
            platform = 'cisco_ios'

    # Smart inference: if platform is not a known handler key (e.g. someone stored
    # a model name like "c2960-48" instead of "cisco_ios"), try to infer from
    # vendor, model, or platform string keywords.
    if platform not in _CHANGE_PASSWORD_HANDLERS:
        vendor = (device.get('vendor') or '').lower()
        combined = f"{vendor} {platform}".lower()
        inferred = None
        if 'cisco' in combined or 'c29' in combined or 'c93' in combined or 'c38' in combined or 'nexus' in combined:
            inferred = 'cisco_nxos' if 'nxos' in combined or 'nexus' in combined else 'cisco_ios'
        elif 'huawei' in combined or 'vrp' in combined:
            inferred = 'huawei_vrp'
        elif 'h3c' in combined or 'comware' in combined:
            inferred = 'h3c_comware'
        elif 'arista' in combined or 'eos' in combined:
            inferred = 'arista_eos'
        elif asset_type == 'server':
            inferred = 'linux'
        if inferred:
            logger.warning(f"[Rotation] Platform '{platform}' not recognized, inferred as '{inferred}' from vendor/model")
            platform = inferred
        else:
            logger.warning(f"[Rotation] Platform '{platform}' not recognized and could not be inferred")

    is_server = asset_type == 'server' or any(tag in platform for tag in ['linux', 'ubuntu', 'centos', 'debian', 'redhat', 'server']) or 'server' in str(device.get('device_category') or '').lower()
    
    logger.info(f"[Rotation] Starting: host={device.get('ip_address')}, platform={platform}, is_server={is_server}")
    
    # 1. Fallback / Auto-Ingestion: If PAM creds are missing, use main device creds
    current_admin_user = creds.get('admin_username') or creds.get('username')
    current_admin_pwd = creds.get('admin_password') or creds.get('password')
    
    # 2. Select target for rotation
    if role == 'normal':
        target_username = creds.get('normal_username') or device.get('normal_username') or 'user'
        current_target_pwd = creds.get('normal_password') or creds.get('password')
    elif role == 'admin':
        target_username = creds.get('admin_username') or device.get('admin_username') or device.get('username')
        current_target_pwd = creds.get('admin_password') or creds.get('password')
    else: # enable
        target_username = 'enable'
        current_target_pwd = creds.get('enable_password')

    # Generate or use target password
    new_password = target_password if target_password else _generate_password(20)

    # 3. Choose login strategy
    auth_model = device.get('auth_model') or 'single'
    
    if is_server:
        if auth_model == 'dual':
            login_user = creds.get('admin_username') or current_admin_user
            login_pwd = creds.get('admin_password') or current_admin_pwd
        else:
            login_user = current_admin_user
            login_pwd = current_admin_pwd
    else:
        login_user = current_admin_user
        login_pwd = current_admin_pwd
        if not login_user or not login_pwd:
            login_user = creds.get('normal_username') or current_admin_user
            login_pwd = creds.get('normal_password') or current_admin_pwd
        logger.info(f"[Rotation] Network device: using admin login ({login_user}) to avoid enable requirement")

    if login_username is not None:
        login_user = login_username
    if login_password is not None:
        login_pwd = login_password

    if not is_server:
        handler = _CHANGE_PASSWORD_HANDLERS.get(platform)
        if not handler:
            return {'success': False, 'message': f'No password change handler for platform: {platform}'}

        save_cmd = _SAVE_COMMANDS.get(platform, 'write memory')
        # Use new_password as set above (either target_password or generated)

        normal_user = creds.get('normal_username') or device.get('normal_username') or 'user'
        admin_user = current_admin_user or 'admin'

        if role == 'enable':
            if 'cisco' in platform:
                commands = [f'enable secret 0 {new_password}']
            elif 'huawei' in platform or 'h3c' in platform:
                commands = [f'super password role privilege 3 cipher {new_password}']
            else:
                return {'success': False, 'message': 'Enable password rotation not supported for this platform'}
        elif role == 'normal':
            commands = handler(normal_user, new_password)
        else: # admin
            commands = handler(admin_user, new_password)

        now_str = datetime.now(timezone.utc).isoformat()
        expires_str = (datetime.now(timezone.utc) + timedelta(days=settings.PASSWORD_ROTATION_INTERVAL_DAYS)).isoformat()
        asset_id = device.get('asset_id')

        # ─ Step 1: Write new passwords to DB with 'pending' status ──────────
        # Save old encrypted values first so we can roll back if SSH fails.
        old_enc_normal = device.get('normal_password') or ''
        old_enc_admin  = device.get('admin_password')  or device.get('password') or ''
        old_enc_enable = device.get('enable_password') or ''

        conn_pre = get_db_connection()
        try:
            enc_pending = encrypt_credential(new_password)
            if role == 'normal':
                conn_pre.execute(
                    "UPDATE devices SET "
                    "normal_password=?, "
                    "rotation_status=?, takeover_error=? "
                    "WHERE id=?",
                    (enc_pending, 'rotating', 'normal password staged, SSH change in progress', device_id)
                )
            elif role == 'admin':
                conn_pre.execute(
                    "UPDATE devices SET "
                    "admin_password=?, username=?, password=?, "
                    "rotation_status=?, takeover_error=? "
                    "WHERE id=?",
                    (enc_pending, admin_user, enc_pending, 'rotating', 'admin password staged, SSH change in progress', device_id)
                )
            elif role == 'enable':
                conn_pre.execute(
                    "UPDATE devices SET enable_password=?, rotation_status=?, takeover_error=? WHERE id=?",
                    (enc_pending, 'rotating', 'enable secret staged, SSH change in progress', device_id)
                )
            conn_pre.commit()
            logger.info(
                f"[Rotation] Staged new {role} credentials in DB for {device.get('hostname')} "
                f"(pending SSH apply)"
            )
        finally:
            conn_pre.close()

        # ─ Step 2: SSH and apply to device ──────────────────────────────────
        device_info = {
            'ip_address': (device.get('ip_address') or '').strip(),
            'username': login_user,
            'password': login_pwd,
            'platform': platform,
            'port': device.get('management_port') or device.get('ssh_port') or 22,
            # Only pass enable_password if explicitly configured by the user.
            # Do NOT fall back to the login password — devices with no enable
            # password will fail if a non-empty secret is passed (Netmiko
            # expects a "Password:" prompt that never comes).
            'enable_password': creds.get('enable_password') or decrypt_credential(device.get('enable_password') or '') or '',
        }

        ssh_error = None
        try:
            from drivers.factory import DriverFactory
            logger.info(
                f"[Rotation] SSH to {device.get('hostname')} as {login_user} "
                f"({role} role rotation)"
            )
            with DriverFactory.get_driver('netmiko', device_info) as driver:
                res = driver.send_config(commands)
                if not res.success:
                    raise Exception(f"Config change failed: {res.error}")
                if 'huawei' in platform.lower():
                    # For Huawei VRP8, staged candidate configurations must be committed
                    # to take effect. We run it in system-view; if it fails (like on VRP5
                    # which lacks commit), the error is non-fatal and ignored.
                    driver.send_config(['commit'])
                save_res = driver.send_command(save_cmd)
                if not save_res.success:
                    logger.warning(
                        f"[Rotation] Device changed but save failed: {save_res.error}. "
                        "Running-config has new passwords, but they won't survive a reboot."
                    )
            logger.info(f"[Rotation] Device updated for {device.get('hostname')}")
        except Exception as e:
            ssh_error = str(e)
            logger.error(f"[Rotation] SSH apply failed for {device.get('hostname')}: {ssh_error}")

        # ─ Step 3: Finalize DB state based on SSH outcome ───────────────────
        conn_post = get_db_connection()
        try:
            if ssh_error is None:
                # Success: mark as active, sync to physical_assets
                enc_new = encrypt_credential(new_password)
                if role == 'normal':
                    conn_post.execute(
                        "UPDATE devices SET "
                        "normal_password=?, normal_password_last_rotated=?, normal_password_expires_at=?, "
                        "rotation_status=?, takeover_error=?, is_managed=? "
                        "WHERE id=?",
                        (enc_new, now_str, expires_str, 'completed', '', 1, device_id)
                    )
                    if asset_id:
                        conn_post.execute(
                            "UPDATE physical_assets SET "
                            "normal_username=?, normal_password=?, "
                            "is_managed=?, takeover_error=? "
                            "WHERE id=?",
                            (normal_user, enc_new, 1, '', asset_id)
                        )
                elif role == 'admin':
                    conn_post.execute(
                        "UPDATE devices SET "
                        "admin_password=?, admin_password_last_rotated=?, admin_password_expires_at=?, "
                        "username=?, password=?, "
                        "rotation_status=?, takeover_error=?, is_managed=? "
                        "WHERE id=?",
                        (enc_new, now_str, expires_str, admin_user, enc_new, 'completed', '', 1, device_id)
                    )
                    if asset_id:
                        conn_post.execute(
                            "UPDATE physical_assets SET "
                            "admin_username=?,  admin_password=?, "
                            "username=?, password=?, "
                            "is_managed=?, takeover_error=? "
                            "WHERE id=?",
                            (admin_user, enc_new, admin_user, enc_new, 1, '', asset_id)
                        )
                elif role == 'enable':
                    conn_post.execute(
                        "UPDATE devices SET "
                        "enable_password=?, enable_password_last_rotated=?, enable_password_expires_at=?, "
                        "rotation_status=?, takeover_error=? "
                        "WHERE id=?",
                        (enc_new, now_str, expires_str, 'completed', '', device_id)
                    )
                    if asset_id:
                        conn_post.execute(
                            "UPDATE physical_assets SET enable_password=? WHERE id=?",
                            (enc_new, asset_id)
                        )
                conn_post.commit()
                _commit_vault_after_rotation(device, role, enc_new, sync_vault)
                logger.info(
                    f"[Rotation] Completed for {device.get('hostname')} "
                    f"({role} written to DB and device)"
                )
                return {
                    'success': True,
                    'message': f"Password rotated for {device.get('hostname', device_id)} ({role})",
                    'rotated_at': now_str,
                    'expires_at': expires_str,
                }
            else:
                # SSH failed: roll back DB to the old passwords so the DB stays
                # consistent with what's actually on the device.
                if role == 'normal':
                    conn_post.execute(
                        "UPDATE devices SET "
                        "normal_password=?, "
                        "rotation_status=?, takeover_error=? "
                        "WHERE id=?",
                        (old_enc_normal, 'failed',
                         f'SSH apply failed: {ssh_error[:400]}. '
                         f'DB has been rolled back to previous normal credentials. '
                         f'Device password was NOT changed.',
                         device_id)
                    )
                elif role == 'admin':
                    conn_post.execute(
                        "UPDATE devices SET "
                        "admin_password=?, password=?, "
                        "rotation_status=?, takeover_error=? "
                        "WHERE id=?",
                        (old_enc_admin, old_enc_admin, 'failed',
                         f'SSH apply failed: {ssh_error[:400]}. '
                         f'DB has been rolled back to previous admin credentials. '
                         f'Device password was NOT changed.',
                         device_id)
                    )
                elif role == 'enable':
                    conn_post.execute(
                        "UPDATE devices SET enable_password=?, rotation_status=?, takeover_error=? WHERE id=?",
                        (old_enc_enable, 'failed',
                         f'SSH apply failed: {ssh_error[:400]}. '
                         f'DB has been rolled back to previous enable password.',
                         device_id)
                    )
                conn_post.commit()
                return {'success': False, 'message': f"Rotation failed: {ssh_error}"}
        finally:
            conn_post.close()

    # ── Server: use chpasswd ──────────────────────────────────────────────────

    # 4. Generate commands (server path only — network path handled above)
    handler = _CHANGE_PASSWORD_HANDLERS.get(platform)
    if not handler and not is_server:
        return {'success': False, 'message': f'No password change handler for platform: {platform}'}

    commands = []  # servers don't use pre-built config commands

    save_cmd = _SAVE_COMMANDS.get(platform, 'sync')

    # 5. Execute with robustness
    device_info = {
        'ip_address': (device.get('ip_address') or '').strip(),
        'username': login_user,
        'password': login_pwd,
        'platform': platform,
        'port': device.get('management_port') or device.get('ssh_port') or 22,
        'secret': current_admin_pwd if 'cisco' in platform else '',
        'conn_timeout': connection_timeout,
        'command_read_timeout': command_read_timeout,
    }
    device_info = {key: value for key, value in device_info.items() if value is not None}

    try:
        from drivers.factory import DriverFactory
        logger.info(f"[Rotation] Attempting login to {device.get('hostname')} as {login_user}")
        
        # Try primary login_user first, fallback to target_user for Linux if failed
        conn_attempt = None
        try:
            conn_attempt = DriverFactory.get_driver('netmiko', device_info)
            driver = conn_attempt.__enter__()
        except Exception as e:
            if is_server and login_user != target_username:
                logger.warning(f"[Rotation] Primary login ({login_user}) failed, retrying as target ({target_username})...")
                device_info['username'] = target_username
                device_info['password'] = current_target_pwd
                conn_attempt = DriverFactory.get_driver('netmiko', device_info)
                driver = conn_attempt.__enter__()
            else:
                raise e

        try:
            # If server, use the highly reliable chpasswd method
            if is_server:
                # We use sudo -S if not root to pass the login password to sudo's stdin
                if login_user == 'root':
                    change_cmd = f'echo {shlex.quote(target_username + ":" + new_password)} | chpasswd'
                else:
                    # Construct a payload that feeds password to sudo, then user:new_pwd to chpasswd
                    # Note: Using printf is often more reliable than echo -e
                    change_cmd = (
                        f'printf "%s\\n%s:%s\\n" '
                        f'{shlex.quote(login_pwd)} '
                        f'{shlex.quote(target_username)} '
                        f'{shlex.quote(new_password)} '
                        f'| sudo -S chpasswd'
                    )
                
                logger.info(f"[Rotation] Executing server password change for {target_username}")
                # For shell commands with pipes, send_command is required
                # Using a generic '#' expect_string to avoid issues with complex prompts
                res = driver.send_command(change_cmd, expect_string=r'#')
                if not res.success:
                    raise Exception(f"Server password change failed: {res.error}")
            else:
                res = driver.send_config(commands, read_timeout=command_read_timeout) if command_read_timeout else driver.send_config(commands)
                if not res.success:
                    raise Exception(f"Config change failed: {res.error}")
            
            if not is_server:
                save_result = driver.send_command(save_cmd, read_timeout=command_read_timeout) if command_read_timeout else driver.send_command(save_cmd)
                if not save_result.success:
                    raise Exception(f"Save configuration failed: {save_result.error}")
                
            logger.info(f"[Rotation] Success for {device.get('hostname')} ({role})")
        finally:
            if conn_attempt:
                conn_attempt.__exit__(None, None, None)
    except Exception as e:
        logger.error(f"Rotation failed for {device.get('hostname')}: {e}")
        return {'success': False, 'message': f"Rotation failed: {str(e)}"}

    # Reconnect with the changed secret before updating local state. This is
    # the hardware-side commit check used by credential synchronization.
    verify_user = target_username if role in ('normal', 'admin') else (current_admin_user or login_user)
    verify_pwd = new_password if role in ('normal', 'admin') else (current_admin_pwd or login_pwd)
    verify_enable = new_password if role == 'enable' else (creds.get('enable_password') or '')
    verify_info = {
        'ip_address': device_info.get('ip_address'),
        'username': verify_user,
        'password': verify_pwd,
        'platform': platform,
        'port': device_info.get('port'),
        'enable_password': verify_enable,
        'secret': verify_enable,
        'conn_timeout': connection_timeout,
        'command_read_timeout': command_read_timeout,
    }
    verify_info = {key: value for key, value in verify_info.items() if value is not None}
    verify_attempt = None
    try:
        verify_attempt = DriverFactory.get_driver('netmiko', verify_info)
        verify_attempt.__enter__()
    except Exception:
        logger.error("[Rotation] New credential verification failed for %s", device.get('hostname'), exc_info=True)
        rollback_conn = get_db_connection()
        try:
            if role == 'normal':
                rollback_conn.execute(
                    "UPDATE devices SET normal_password = ?, rotation_status = 'failed', takeover_error = ? WHERE id = ?",
                    (old_enc_normal, 'New credential verification failed', device_id),
                )
            elif role == 'admin':
                rollback_conn.execute(
                    "UPDATE devices SET admin_password = ?, username = ?, password = ?, rotation_status = 'failed', takeover_error = ? WHERE id = ?",
                    (old_enc_admin, device.get('admin_username') or device.get('username') or '', old_enc_admin, 'New credential verification failed', device_id),
                )
            else:
                rollback_conn.execute(
                    "UPDATE devices SET enable_password = ?, rotation_status = 'failed', takeover_error = ? WHERE id = ?",
                    (old_enc_enable, 'New credential verification failed', device_id),
                )
            rollback_conn.commit()
        finally:
            rollback_conn.close()
        return {'success': False, 'message': 'New credential verification failed'}
    finally:
        if verify_attempt:
            verify_attempt.__exit__(None, None, None)

    # Update DB using the effective rotation policy interval
    policy = get_rotation_policy()
    now_str = datetime.now(timezone.utc).isoformat()
    expires_str = (datetime.now(timezone.utc) + timedelta(days=int(policy['interval_days']))).isoformat()
    enc_new = encrypt_credential(new_password)

    conn2 = get_db_connection()
    try:
        if role == 'normal':
            conn2.execute(
                'UPDATE devices SET normal_password = ?, normal_password_last_rotated = ?, normal_password_expires_at = ? WHERE id = ?',
                (enc_new, now_str, expires_str, device_id)
            )
        elif role == 'admin':
            conn2.execute(
                'UPDATE devices SET admin_password = ?, admin_password_last_rotated = ?, admin_password_expires_at = ?, '
                'password_last_rotated = ?, password_expires_at = ?, username = ?, password = ? WHERE id = ?',
                (enc_new, now_str, expires_str, now_str, expires_str, target_username, enc_new, device_id)
            )
        else:
            conn2.execute(
                'UPDATE devices SET enable_password = ?, enable_password_last_rotated = ?, enable_password_expires_at = ? WHERE id = ?',
                (enc_new, now_str, expires_str, device_id)
            )
        
        # ALSO update physical_assets table if linked
        asset_id = device.get('asset_id')
        if asset_id:
            if role == 'normal':
                conn2.execute(
                    'UPDATE physical_assets SET normal_username = ?, normal_password = ? WHERE id = ?',
                    (target_username, enc_new, asset_id)
                )
            elif role == 'admin':
                conn2.execute(
                    'UPDATE physical_assets SET admin_username = ?, admin_password = ?, username = ?, password = ? WHERE id = ?',
                    (target_username, enc_new, target_username, enc_new, asset_id)
                )
            elif role == 'enable':
                conn2.execute(
                    'UPDATE physical_assets SET enable_password = ? WHERE id = ?',
                    (enc_new, asset_id)
                )
        
        # Mark as managed on success
        conn2.execute("UPDATE devices SET is_managed = 1, takeover_error = '' WHERE id = ?", (device_id,))
        if asset_id:
            conn2.execute("UPDATE physical_assets SET is_managed = 1, takeover_error = '' WHERE id = ?", (asset_id,))
            
        conn2.commit()
    finally:
        conn2.close()

    _commit_vault_after_rotation(device, role, enc_new, sync_vault)
    logger.info("Password rotated for device %s (%s)", device.get('hostname'), device_id)

    return {
        'success': True,
        'message': f"Password rotated for {device.get('hostname', device_id)}",
        'rotated_at': now_str,
        'expires_at': expires_str,
    }


def get_rotation_status() -> list[dict[str, Any]]:
    """获取所有设备的密码轮换状态概览（包含 User/Admin 双凭据）。"""
    conn = get_db_connection()
    try:
        try:
            rows = conn.execute(
                "SELECT d.id, d.hostname, d.ip_address, d.platform, d.auth_model, "
                "d.credential_id, d.admin_credential_id, "
                "c_normal.credential_name AS credential_name, "
                "c_normal.username AS credential_username, "
                "c_normal.account_role AS credential_account_role, "
                "c_admin.credential_name AS admin_credential_name, "
                "c_admin.username AS admin_credential_username, "
                "c_admin.account_role AS admin_credential_account_role, "
                "d.normal_username, d.normal_password_last_rotated, d.normal_password_expires_at, "
                "d.admin_username, d.admin_password_last_rotated, d.admin_password_expires_at, "
                "d.enable_password_last_rotated, d.enable_password_expires_at, "
                "d.password_last_rotated, d.password_expires_at "
                "FROM devices d "
                "LEFT JOIN credentials c_normal ON c_normal.id = d.credential_id "
                "LEFT JOIN credentials c_admin ON c_admin.id = d.admin_credential_id "
                "WHERE d.status != 'decommissioned'"
            ).fetchall()
        except Exception as e:
            # Fallback to basic columns if PAM columns are missing
            logger.warning(f"Failed to fetch detailed rotation status (likely missing columns): {e}")
            # PostgreSQL marks the current transaction as failed after a
            # malformed/legacy-column query; clear it before using fallback.
            try:
                conn.rollback()
            except Exception:
                pass
            rows = conn.execute(
                "SELECT id, hostname, ip_address, platform, "
                "password_last_rotated, password_expires_at "
                "FROM devices WHERE status != 'decommissioned'"
            ).fetchall()

        now = datetime.now(timezone.utc)
        result = []
        for r in rows:
            d = dict(r)
            # Support legacy password field as 'admin'/'normal' if role-specific ones are empty
            if not d.get('admin_password_expires_at') and d.get('password_expires_at'):
                 d['admin_password_last_rotated'] = d['password_last_rotated']
                 d['admin_password_expires_at'] = d['password_expires_at']
            if not d.get('normal_password_expires_at') and d.get('password_expires_at'):
                 d['normal_password_last_rotated'] = d['password_last_rotated']
                 d['normal_password_expires_at'] = d['password_expires_at']
            
            # Add remaining days for each role
            for prefix in ['normal_password', 'admin_password', 'enable_password']:
                exp_key = f"{prefix}_expires_at"
                days_key = f"{prefix}_days_remaining"
                expired_key = f"{prefix}_expired"
                
                if d.get(exp_key):
                    try:
                        exp = datetime.fromisoformat(d[exp_key].replace('Z', '+00:00'))
                        d[days_key] = (exp - now).days
                        d[expired_key] = d[days_key] < 0
                    except Exception:
                        d[days_key] = None
                        d[expired_key] = False
                else:
                    d[days_key] = None
                    d[expired_key] = False
            result.append(d)
        return result
    finally:
        conn.close()


def list_credential_bound_devices(
    credential_id: str,
    page: int = 1,
    page_size: int = 20,
    keyword: str = '',
    platform: str = '',
) -> dict[str, Any]:
    """Return one searchable page of device metadata bound to a shared credential."""
    normalized_credential_id = str(credential_id or '').strip()
    safe_page = max(1, int(page or 1))
    safe_page_size = min(100, max(1, int(page_size or 20)))
    normalized_keyword = str(keyword or '').strip().lower()
    normalized_platform = str(platform or '').strip().lower()

    conditions = [
        "d.status != 'decommissioned'",
        '(d.credential_id = ? OR d.admin_credential_id = ?)',
    ]
    parameters: list[Any] = [normalized_credential_id, normalized_credential_id]
    if normalized_keyword:
        pattern = f'%{normalized_keyword}%'
        conditions.append(
            "(LOWER(COALESCE(d.hostname, '')) LIKE ? "
            "OR LOWER(COALESCE(d.ip_address, '')) LIKE ?)"
        )
        parameters.extend([pattern, pattern])
    if normalized_platform:
        conditions.append("LOWER(COALESCE(d.platform, '')) = ?")
        parameters.append(normalized_platform)

    where_clause = ' AND '.join(conditions)
    conn = get_db_connection()
    try:
        total_row = conn.execute(
            f'SELECT COUNT(*) AS total FROM devices d WHERE {where_clause}',
            tuple(parameters),
        ).fetchone()
        total = int((dict(total_row).get('total') if total_row else 0) or 0)
        offset = (safe_page - 1) * safe_page_size
        rows = conn.execute(
            'SELECT d.id, d.hostname, d.ip_address, d.platform '
            f'FROM devices d WHERE {where_clause} '
            "ORDER BY LOWER(COALESCE(d.hostname, '')), "
            "LOWER(COALESCE(d.ip_address, '')), d.id "
            'LIMIT ? OFFSET ?',
            tuple(parameters + [safe_page_size, offset]),
        ).fetchall()
        return {
            'items': [dict(row) for row in rows],
            'total': total,
            'page': safe_page,
            'page_size': safe_page_size,
        }
    finally:
        conn.close()


def _dispatch_rotation_notification(
    *,
    device_id: str,
    hostname: str,
    ip_address: str,
    role: str,
    event_type: str,
    expires_at: str,
    message: str,
    auto_rotate_enabled: bool,
) -> None:
    """Dispatch a deduplicated credential rotation alert through configured channels."""
    try:
        from services.notification_service import (
            automatic_notifications_enabled,
            dispatch_to_all_users,
        )
        if not automatic_notifications_enabled():
            return
        severity = 'critical' if event_type == 'failed' else ('major' if event_type == 'expired' else 'warning')
        title_map = {
            'expiring': '凭据即将过期提醒',
            'expired': '凭据已过期提醒',
            'failed': '自动凭据轮换失败告警',
        }
        action_hint = (
            '自动轮换已开启，将在每日调度窗口自动处理；失败项请前往 /management/credentials 人工核查。'
            if auto_rotate_enabled
            else '当前已关闭自动轮换，请前往 /management/credentials 执行手动轮换。'
        )
        alert = {
            'title': f"{title_map.get(event_type, '凭据轮换提醒')} - {hostname or device_id}",
            'severity': severity,
            'device_id': device_id,
            'hostname': hostname or device_id,
            'ip_address': ip_address,
            'metric': f'password_rotation.{role}',
            'message': f"{message} | 账号类型: {role} | 到期时间: {expires_at or '-'} | {action_hint}",
            'status': 'open',
            'source': 'password_rotation',
            'link': '/management/credentials',
        }
        dispatch_to_all_users(alert, raise_on_error=False)
    except Exception as exc:
        logger.debug("[PasswordRotation] Notification channel dispatch skipped: %s", exc)


def run_rotation_sweep() -> dict[str, Any]:
    """
    定时调度入口：读取持久化生效策略，发送去重到期提醒并在开启自动轮换时处理到期账号。
    由 APScheduler 调用。
    """
    policy = get_rotation_policy()
    included_roles = policy['included_roles']
    expiring_entries = check_expiring(days_ahead=policy['notify_days'], roles=included_roles)

    reminders_sent = 0
    for item in expiring_entries:
        event_type = 'expired' if item['is_expired'] else 'expiring'
        dedup_key = f"{item['device_id']}:{item['role']}:{event_type}:{item['password_expires_at']}"
        msg = (
            f"Device {item.get('hostname') or item['device_id']} ({item['role']}) "
            f"password {event_type} (expires_at={item['password_expires_at']})"
        )
        if _record_rotation_notification_if_new(
            dedup_key,
            device_id=item['device_id'],
            role=item['role'],
            event_type=event_type,
            message=msg,
        ):
            reminders_sent += 1
            _dispatch_rotation_notification(
                device_id=item['device_id'],
                hostname=str(item.get('hostname') or ''),
                ip_address=str(item.get('ip_address') or ''),
                role=item['role'],
                event_type=event_type,
                expires_at=str(item.get('password_expires_at') or ''),
                message=msg,
                auto_rotate_enabled=bool(policy['auto_rotate_enabled']),
            )

    if not policy['auto_rotate_enabled']:
        logger.info(
            "[PasswordRotation] Auto-rotation disabled by effective policy; reminders_sent=%d",
            reminders_sent,
        )
        return {
            'auto_rotate_enabled': False,
            'reminders_sent': reminders_sent,
            'rotated': 0,
            'failed': 0,
        }

    logger.info("[PasswordRotation] Starting rotation sweep (roles=%s)...", included_roles)
    due = [item for item in expiring_entries if item['is_expired']]
    rotated, failed = 0, 0
    for item in due:
        result = rotate_password(item['device_id'], role=item['role'])
        if result['success']:
            rotated += 1
        else:
            failed += 1
            fail_key = f"{item['device_id']}:{item['role']}:failed:{item['password_expires_at']}"
            fail_msg = str(result.get('message') or 'Rotation failed')
            if _record_rotation_notification_if_new(
                fail_key,
                device_id=item['device_id'],
                role=item['role'],
                event_type='failed',
                message=fail_msg,
            ):
                _dispatch_rotation_notification(
                    device_id=item['device_id'],
                    hostname=str(item.get('hostname') or ''),
                    ip_address=str(item.get('ip_address') or ''),
                    role=item['role'],
                    event_type='failed',
                    expires_at=str(item.get('password_expires_at') or ''),
                    message=fail_msg,
                    auto_rotate_enabled=True,
                )
            logger.warning(
                "[PasswordRotation] Failed for %s (%s): %s",
                item.get('hostname'), item['role'], result.get('message'),
            )
    logger.info(
        "[PasswordRotation] Sweep complete: %d rotated, %d failed, %d reminders",
        rotated, failed, reminders_sent,
    )
    return {
        'auto_rotate_enabled': True,
        'reminders_sent': reminders_sent,
        'rotated': rotated,
        'failed': failed,
    }


# ──────────────────────────────────────────────────────────────────
# Bulk "rotate all" — background execution with in-memory progress
# ──────────────────────────────────────────────────────────────────

# run_id -> {run_id, role, total, done, rotated, failed, status, results, ...}
_rotate_all_runs: dict[str, dict[str, Any]] = {}
_rotate_all_lock = threading.Lock()
# How many devices to rotate in parallel. Rotation performs SSH config changes,
# so keep this modest to avoid overwhelming (often emulated) lab devices.
_ROTATE_ALL_WORKERS = 5


def get_rotate_all_progress(run_id: str) -> dict[str, Any] | None:
    """Return a snapshot of a bulk-rotation run, or None if unknown."""
    with _rotate_all_lock:
        entry = _rotate_all_runs.get(run_id)
        return dict(entry) if entry else None


def run_rotation_all(role: str = 'admin', run_id: str | None = None,
                     max_workers: int = _ROTATE_ALL_WORKERS) -> dict[str, Any]:
    """
    Rotate the *role* password for ALL non-decommissioned devices.

    Progress is tracked in ``_rotate_all_runs[run_id]`` so the API can poll it.
    Runs with modest concurrency. The new secret is mirrored into the credential
    vault by ``rotate_password`` (via ``_sync_credential_vault``).
    """
    run_id = run_id or _uuid.uuid4().hex

    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, hostname FROM devices WHERE COALESCE(status, '') != 'decommissioned'"
        ).fetchall()
        devices = [dict(r) for r in rows]
    finally:
        conn.close()

    with _rotate_all_lock:
        entry = _rotate_all_runs.setdefault(run_id, {})
        entry.update({
            'run_id': run_id, 'role': role, 'total': len(devices),
            'done': 0, 'rotated': 0, 'failed': 0, 'status': 'running',
            'results': entry.get('results', []),
            'started_at': entry.get('started_at') or datetime.now(timezone.utc).isoformat(),
        })

    logger.info("[PasswordRotation] Bulk rotate-all started: run=%s role=%s devices=%d",
                run_id, role, len(devices))

    def _do(dev: dict) -> tuple[dict, dict]:
        try:
            res = rotate_password(dev['id'], role=role)
        except Exception as exc:  # noqa: BLE001
            res = {'success': False, 'message': str(exc)}
        return dev, res

    try:
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
            futures = [ex.submit(_do, d) for d in devices]
            for fut in as_completed(futures):
                dev, res = fut.result()
                ok = bool(res.get('success'))
                with _rotate_all_lock:
                    e = _rotate_all_runs[run_id]
                    e['done'] += 1
                    e['rotated'] += 1 if ok else 0
                    e['failed'] += 0 if ok else 1
                    e['results'].append({
                        'device_id': dev['id'],
                        'hostname': dev.get('hostname'),
                        'success': ok,
                        'message': res.get('message', ''),
                    })
    finally:
        with _rotate_all_lock:
            _rotate_all_runs[run_id]['status'] = 'completed'
            _rotate_all_runs[run_id]['finished_at'] = datetime.now(timezone.utc).isoformat()

    with _rotate_all_lock:
        final = dict(_rotate_all_runs[run_id])
    logger.info("[PasswordRotation] Bulk rotate-all done: run=%s rotated=%d failed=%d",
                run_id, final['rotated'], final['failed'])
    return final


def start_rotation_all(role: str = 'admin') -> str:
    """Create a bulk-rotation run and execute it on a background thread.
    Returns the run_id immediately for progress polling."""
    run_id = _uuid.uuid4().hex
    with _rotate_all_lock:
        _rotate_all_runs[run_id] = {
            'run_id': run_id, 'role': role, 'total': None,
            'done': 0, 'rotated': 0, 'failed': 0, 'status': 'starting',
            'results': [], 'started_at': datetime.now(timezone.utc).isoformat(),
        }
    threading.Thread(
        target=run_rotation_all, kwargs={'role': role, 'run_id': run_id}, daemon=True
    ).start()
    return run_id


def sync_hardware_device_password_for_credential(
    cred_id: str,
    new_password: str = None,
    new_enable_password: str = None,
    actor_username: str = None,
    max_workers: int = 10
) -> dict:
    """Compatibility guard for callers of the pre-job implementation.

    Password changes must be created through the credential API so the old
    password can be verified and the vault is not changed before hardware
    verification. Keeping this function as a hard failure prevents an older
    integration from silently reintroducing the unsafe fire-and-forget flow.
    """
    return {
        'success': False,
        'message': 'Direct credential hardware sync is deprecated; create a credential password sync job instead',
    }
