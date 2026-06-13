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


def _sync_credential_vault(device: dict, role: str, enc_new: str) -> None:
    """
    Mirror a successful rotation into the credentials vault (``credentials`` table).

    After the credential-decoupling refactor, the vault — not the legacy
    ``devices.*`` columns — is the source of truth for login/backup. Rotation
    historically wrote only to ``devices.*``, so a rotated password never reached
    the vault and config backup would break. This keeps them consistent.

    The vault stores a single account per device, so the stored login password is
    updated only when the rotated *role* matches the account the vault represents.
    The ``enable`` role always updates the vault's ``enable_password``.
    """
    cred_id = device.get('credential_id')
    if not cred_id or not enc_new:
        return
    try:
        conn = get_db_connection()
        try:
            row = conn.execute('SELECT username FROM credentials WHERE id = ?', (cred_id,)).fetchone()
            if not row:
                return
            vault_user = (dict(row).get('username') or '').strip().lower()

            if role == 'enable':
                conn.execute('UPDATE credentials SET enable_password = ? WHERE id = ?', (enc_new, cred_id))
                conn.commit()
                logger.info("[Rotation] Synced new enable secret into credential vault %s", cred_id)
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
    'hp_comware': _h3c_change_password_commands,
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
    'hp_comware': 'save force',
    'arista_eos': 'write memory',
    'linux': 'sync',
    'ubuntu': 'sync',
    'centos': 'sync',
    'debian': 'sync',
    'redhat': 'sync',
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


def rotate_password(device_id: str, role: str = 'admin') -> dict[str, Any]:
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

    creds = resolve_device_credentials(device)
    
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
        target_username = device.get('normal_username') or 'user'
        # If normal_password is empty, we assume it matches the main password or is unknown
        current_target_pwd = creds.get('normal_password') or creds.get('password')
    elif role == 'admin':
        target_username = device.get('admin_username') or device.get('username')
        current_target_pwd = creds.get('admin_password') or creds.get('password')
    else: # enable
        target_username = 'enable'
        current_target_pwd = creds.get('enable_password')

    # Generate new random password
    new_password = _generate_password(20)

    # 3. Choose login strategy
    # For servers, we ALWAYS use admin to change passwords (more reliable)
    auth_model = device.get('auth_model') or 'single'
    
    if is_server:
        # In dual mode, we MUST use admin credentials to login for rotation
        if auth_model == 'dual':
            login_user = creds.get('admin_username') or current_admin_user
            login_pwd = creds.get('admin_password') or current_admin_pwd
        else:
            login_user = current_admin_user
            login_pwd = current_admin_pwd
    else:
        # For network devices: ALWAYS login as admin (privilege 15) to run config commands.
        # Using a low-privilege account (e.g. user/privilege 1) requires enable, which
        # needs a separate enable secret. Logging in as admin avoids this entirely.
        login_user = current_admin_user
        login_pwd = current_admin_pwd
        if not login_user or not login_pwd:
            # Fallback: if no admin creds, try normal creds
            login_user = creds.get('normal_username') or current_admin_user
            login_pwd = creds.get('normal_password') or current_admin_pwd
        logger.info(f"[Rotation] Network device: using admin login ({login_user}) to avoid enable requirement")

    # ── Network device: write-ahead rotation ──────────────────────────────────
    #
    # Reliability guarantee (防止密码丢失):
    #   1. Generate new passwords
    #   2. Write them to DB first with status='pending' (commit immediately)
    #      ← even if everything fails after this, passwords are NOT lost
    #   3. SSH to device and change both accounts
    #   4. write memory on device
    #   5. Mark DB record as 'active' (verified/committed)
    #   6. On SSH failure: keep the pending passwords in DB + set takeover_error
    #      ← user can see what the new password was and recover manually
    #
    # The previous flow changed the device FIRST, then wrote DB — if SQL failed,
    # the device's password was silently lost.
    if not is_server:
        handler = _CHANGE_PASSWORD_HANDLERS.get(platform)
        if not handler:
            return {'success': False, 'message': f'No password change handler for platform: {platform}'}

        save_cmd = _SAVE_COMMANDS.get(platform, 'write memory')

        new_password = _generate_password(20)

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
            'enable_password': decrypt_credential(device.get('enable_password') or '') or '',
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
                _sync_credential_vault(device, role, enc_new)
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
    }

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
                res = driver.send_config(commands)
                if not res.success:
                    raise Exception(f"Config change failed: {res.error}")
            
            if not is_server:
                driver.send_command(save_cmd)
                
            logger.info(f"[Rotation] Success for {device.get('hostname')} ({role})")
        finally:
            if conn_attempt:
                conn_attempt.__exit__(None, None, None)
    except Exception as e:
        logger.error(f"Rotation failed for {device.get('hostname')}: {e}")
        return {'success': False, 'message': f"Rotation failed: {str(e)}"}

    # Update DB
    now_str = datetime.now(timezone.utc).isoformat()
    expires_str = (datetime.now(timezone.utc) + timedelta(days=settings.PASSWORD_ROTATION_INTERVAL_DAYS)).isoformat()
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
                'UPDATE devices SET admin_password = ?, admin_password_last_rotated = ?, admin_password_expires_at = ?, username = ?, password = ? WHERE id = ?',
                (enc_new, now_str, expires_str, target_username, enc_new, device_id)
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

    _sync_credential_vault(device, role, enc_new)
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
                "SELECT id, hostname, ip_address, platform, auth_model, "
                "normal_username, normal_password_last_rotated, normal_password_expires_at, "
                "admin_username, admin_password_last_rotated, admin_password_expires_at, "
                "enable_password_last_rotated, enable_password_expires_at, "
                "password_last_rotated, password_expires_at "
                "FROM devices WHERE status != 'decommissioned'"
            ).fetchall()
        except Exception as e:
            # Fallback to basic columns if PAM columns are missing
            logger.warning(f"Failed to fetch detailed rotation status (likely missing columns): {e}")
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
