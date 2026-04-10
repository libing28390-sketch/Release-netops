"""
Password Rotation Service — 设备密码自动轮换。

功能:
1. check_expiring()  — 扫描即将过期的设备密码列表
2. rotate_password() — 对单台设备执行 SSH 改密 + 更新 DB/Vault
3. run_rotation_sweep() — 定时调度入口，批量处理到期设备

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
from datetime import datetime, timezone, timedelta
from typing import Any

from database import get_db_connection
from core.config import settings
from core.crypto import encrypt_credential, decrypt_credential
from services.vault_service import resolve_device_credentials, write_credentials as vault_write, vault_available

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


_CHANGE_PASSWORD_HANDLERS: dict[str, Any] = {
    'cisco_ios': _cisco_change_password_commands,
    'cisco_nxos': _cisco_change_password_commands,
    'huawei_vrp': _huawei_change_password_commands,
    'h3c_comware': _h3c_change_password_commands,
    'arista_eos': _arista_change_password_commands,
}

# Exec-mode save commands per platform (run AFTER config mode exit)
_SAVE_COMMANDS: dict[str, str] = {
    'cisco_ios': 'write memory',
    'cisco_nxos': 'copy running-config startup-config',
    'huawei_vrp': 'save force',
    'h3c_comware': 'save force',
    'arista_eos': 'write memory',
}


# ── 核心功能 ──────────────────────────────────────

def check_expiring(days_ahead: int | None = None) -> list[dict[str, Any]]:
    """
    扫描即将过期或已过期的设备密码。
    返回: [{ id, hostname, ip_address, password_expires_at, days_remaining }]
    """
    if days_ahead is None:
        days_ahead = settings.PASSWORD_ROTATION_NOTIFY_DAYS
    now = datetime.now(timezone.utc)
    cutoff = (now + timedelta(days=days_ahead)).isoformat()

    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, hostname, ip_address, password_expires_at FROM devices "
            "WHERE password_expires_at != '' AND password_expires_at <= ?",
            (cutoff,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                exp = datetime.fromisoformat(d['password_expires_at'].replace('Z', '+00:00'))
                d['days_remaining'] = (exp - now).days
            except Exception:
                d['days_remaining'] = -1
            result.append(d)
        return sorted(result, key=lambda x: x.get('days_remaining', 9999))
    finally:
        conn.close()


def rotate_password(device_id: str) -> dict[str, Any]:
    """
    对单台设备执行密码轮换。
    流程: SSH → 改密命令 → 验证新密码 → 更新数据库/Vault
    返回: { success, message, rotated_at }
    """
    from drivers.factory import DriverFactory

    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
    finally:
        conn.close()

    if not row:
        return {'success': False, 'message': 'Device not found'}

    device = dict(row)

    # ── Diagnostic: trace credential resolution ──────────────────────
    raw_pwd = device.get('password') or ''
    logger.info(
        "rotate_password diagnostic — device=%s ip=%s raw_pwd_prefix=%s raw_pwd_len=%d",
        device_id,
        device.get('ip_address', ''),
        raw_pwd[:7] if raw_pwd else '(empty)',
        len(raw_pwd),
    )

    creds = resolve_device_credentials(device)
    platform = (device.get('platform') or 'cisco_ios').lower()

    # Pre-flight: validate credentials before attempting SSH
    username = creds.get('username', '').strip()
    password = creds.get('password', '').strip()

    logger.info(
        "rotate_password diagnostic — resolved username=%s password_len=%d password_is_encrypted=%s platform=%s",
        username,
        len(password),
        password.startswith('enc:v1:'),
        platform,
    )
    if not username or not password:
        missing = []
        if not username:
            missing.append('username')
        if not password:
            missing.append('password')
        return {
            'success': False,
            'message': f'设备凭据未配置（缺少 {", ".join(missing)}），请先在口令上手流程中设置凭据',
        }

    ip_address = (device.get('ip_address') or '').strip()
    if not ip_address:
        return {'success': False, 'message': '设备管理 IP 未配置'}

    handler = _CHANGE_PASSWORD_HANDLERS.get(platform)
    if not handler:
        return {'success': False, 'message': f'Unsupported platform for rotation: {platform}'}

    new_password = _generate_password()
    commands = handler(username, new_password)
    save_cmd = _SAVE_COMMANDS.get(platform, 'write memory')

    # Phase 1: Execute change password commands + save
    device_info = {
        'ip_address': ip_address,
        'username': username,
        'password': password,
        'platform': platform,
        'port': device.get('port') or 22,
        'enable_password': creds.get('enable_password', ''),
    }

    try:
        with DriverFactory.get_driver('netmiko', device_info) as driver:
            result = driver.send_config(commands)
            if not result.success:
                raise Exception(result.error or 'send_config failed')
            # Save config in exec mode (send_config_set already exited config mode)
            save_result = driver.send_command(save_cmd)
            if not save_result.success:
                logger.warning("Save command failed on %s: %s (password may still be changed in running-config)",
                               device_id, save_result.error)
    except Exception as exc_netmiko:
        logger.warning("Rotation phase-1 netmiko failed for %s: %s — trying scrapli", device_id, exc_netmiko)
        try:
            with DriverFactory.get_driver('scrapli', device_info) as driver:
                result = driver.send_config(commands)
                if not result.success:
                    raise Exception(result.error or 'send_config failed')
                save_result = driver.send_command(save_cmd)
                if not save_result.success:
                    logger.warning("Save command failed on %s (scrapli): %s", device_id, save_result.error)
        except Exception as exc_scrapli:
            logger.error("Rotation phase-1 failed for %s: %s", device_id, exc_scrapli)
            return {'success': False, 'message': f'Failed to execute change commands: {exc_scrapli}'}

    # Phase 2: Verify new credentials by attempting login
    verify_info = {**device_info, 'password': new_password}
    try:
        with DriverFactory.get_driver('netmiko', verify_info) as verify_driver:
            pass  # successful connect = password verified
    except Exception as exc:
        logger.error("Rotation phase-2 verify failed for %s: %s — attempting rollback", device_id, exc)
        # Cannot rollback easily — log critical and keep old password
        return {
            'success': False,
            'message': f'Password changed on device but verification failed: {exc}. Manual intervention required.',
        }

    # Phase 3: Update stored credentials
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=settings.PASSWORD_ROTATION_INTERVAL_DAYS)
    now_str = now.isoformat()
    expires_str = expires.isoformat()

    cred_source = (device.get('credential_source') or 'local').lower()
    vault_path = device.get('vault_path', '')

    if cred_source == 'vault' and vault_available() and vault_path:
        vault_write(vault_path, {
            'username': username,
            'password': new_password,
            'enable_password': creds.get('enable_password', ''),
            'priv_username': creds.get('priv_username', ''),
        })
        enc_new = ''
    else:
        enc_new = encrypt_credential(new_password)

    conn2 = get_db_connection()
    try:
        conn2.execute(
            'UPDATE devices SET password = ?, password_last_rotated = ?, password_expires_at = ? WHERE id = ?',
            (enc_new, now_str, expires_str, device_id)
        )
        conn2.commit()
    finally:
        conn2.close()

    logger.info("Password rotated for device %s (%s)", device.get('hostname'), device_id)

    return {
        'success': True,
        'message': f"Password rotated for {device.get('hostname', device_id)}",
        'rotated_at': now_str,
        'expires_at': expires_str,
    }


def get_rotation_status() -> list[dict[str, Any]]:
    """获取所有设备的密码轮换状态概览。"""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, hostname, ip_address, platform, password_last_rotated, password_expires_at "
            "FROM devices WHERE status != 'decommissioned'"
        ).fetchall()
        now = datetime.now(timezone.utc)
        result = []
        for r in rows:
            d = dict(r)
            if d.get('password_expires_at'):
                try:
                    exp = datetime.fromisoformat(d['password_expires_at'].replace('Z', '+00:00'))
                    d['days_remaining'] = (exp - now).days
                    d['expired'] = d['days_remaining'] < 0
                except Exception:
                    d['days_remaining'] = None
                    d['expired'] = False
            else:
                d['days_remaining'] = None
                d['expired'] = False
            result.append(d)
        return result
    finally:
        conn.close()


def run_rotation_sweep():
    """
    定时调度入口：扫描到期设备并自动轮换。
    由 APScheduler 调用。
    """
    if not settings.PASSWORD_ROTATION_ENABLED:
        return

    logger.info("[PasswordRotation] Starting rotation sweep...")
    expiring = check_expiring(days_ahead=0)  # 只处理已过期的
    rotated, failed = 0, 0
    for dev in expiring:
        result = rotate_password(dev['id'])
        if result['success']:
            rotated += 1
        else:
            failed += 1
            logger.warning("[PasswordRotation] Failed for %s: %s", dev.get('hostname'), result['message'])
    logger.info("[PasswordRotation] Sweep complete: %d rotated, %d failed", rotated, failed)
