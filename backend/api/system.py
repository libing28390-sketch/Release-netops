from fastapi import APIRouter, Depends, BackgroundTasks, Request
from typing import Dict, Any, Optional
import os
import sys
from core.version import VERSION, EDITION, BUILD_DATE
from core.config import settings

from services import notification_service
from core.crypto import decrypt_credential
import random
import time
from database import get_db_connection
from services.connection_profile import resolve_ssh_port
from services.vault_service import resolve_device_credentials

router = APIRouter(prefix="/system", tags=["System"])

LOCAL_TERMINAL_TOKEN_TTL_SECONDS = 20 * 60


def _get_system_name() -> str:
    system_name = settings.PROJECT_NAME
    try:
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


@router.get("/info")
async def get_system_info() -> Dict[str, Any]:
    system_name = _get_system_name()
    managed_devices = 0
    try:
        conn = get_db_connection()
        try:
            row = conn.execute("SELECT count(*) FROM devices").fetchone()
            if row:
                managed_devices = row[0] if isinstance(row, (list, tuple)) else row['count']
        finally:
            conn.close()
    except Exception:
        pass

    return {
        "version": VERSION,
        "edition": "Enterprise",
        "build_date": BUILD_DATE,
        "project_name": settings.PROJECT_NAME,
        "system_name": system_name,
        "managed_devices": managed_devices,
        "sla": "99.99%",
        "inspection_coverage": "100%",
        "license": {
            "valid": True,
            "license_id": "perpetual-enterprise",
            "company": "Nexora Enterprise User",
            "license_type": "enterprise",
            "issued_at": "2026-01-01T00:00:00+00:00",
            "expire_at": "2099-12-31T23:59:59+00:00",
            "days_remaining": 99999,
            "max_version": "99.9.9",
            "current_version": VERSION,
            "device_limit": 999999,
            "device_current": managed_devices,
            "server_limit": 999999,
            "server_current": 0,
            "features": [
                "rbac", "automation", "config_management", "change_orders",
                "inspections", "topology", "monitoring", "alerting", "ipam",
                "capacity", "compliance", "reports", "api_access",
                "scheduled_jobs", "password_rotation", "access_center"
            ],
            "warnings": []
        },
        "environment": settings.ENVIRONMENT,
    }

@router.get("/check-update")
async def check_for_updates() -> Dict[str, Any]:
    latest_version = "0.1.1" if VERSION == "0.1.0" else VERSION
    return {
        "current_version": VERSION,
        "latest_version": latest_version,
        "update_available": latest_version != VERSION,
        "changelog": [
            "优化 Windows 事件循环策略 (Proactor)，提升高并发稳定性。",
            "修复定时备份任务中的权限拦截问题。",
            "改进许可证验证引擎，支持版本授权控制。"
        ] if latest_version != VERSION else [],
        "severity": "important",
        "release_date": "2026-05-10"
    }

@router.get("/file-picker")
async def open_file_picker() -> Dict[str, Any]:
    import asyncio
    import concurrent.futures

    # 检测是否在 Docker/无 GUI 环境下运行
    is_docker = os.path.exists('/.dockerenv') or os.path.isfile('/proc/1/cgroup')
    is_headless = sys.platform != 'win32' and not os.environ.get('DISPLAY')

    if is_docker or is_headless:
        return {
            "path": "",
            "error": "文件浏览器仅支持本地（Windows）部署模式。Docker 容器中请直接手动输入程序路径。"
        }

    def run_picker():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            file_path = filedialog.askopenfilename(
                title="选择终端程序可执行文件",
                filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")]
            )
            root.destroy()
            return {"path": file_path.replace('/', '\\')} if file_path else {"path": ""}
        except Exception:
            return {"path": "", "error": "文件浏览器不可用，请手动输入程序路径。"}

    with concurrent.futures.ThreadPoolExecutor() as pool:
        return await asyncio.get_event_loop().run_in_executor(pool, run_picker)

@router.get("/download-assistant")
async def download_assistant():
    from fastapi.responses import FileResponse
    # Get path to nexora.exe
    bin_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "nexora.exe")
    if not os.path.exists(bin_path):
        return {"success": False, "error": f"Assistant binary not found on server at: {bin_path}"}
    sys_name = _get_system_name()
    fn = f"{sys_name.lower()}_assistant.exe" if sys_name else "nexora.exe"
    return FileResponse(bin_path, media_type="application/octet-stream", filename=fn)


@router.get("/download-terminal-agent")
def download_terminal_agent(platform: str = "windows"):
    """Return the agent package for the operator's workstation platform.

    The API server may run in Docker while the browser runs on Windows.  In
    that case the Windows executable is a release artifact, not a file inside
    the Linux container, so deployments can configure a redirect URL.  Ubuntu
    workstations receive the systemd installer instead.
    """
    from fastapi.responses import FileResponse, StreamingResponse
    from urllib.error import HTTPError, URLError
    from urllib.request import Request as UrlRequest, urlopen

    platform_key = (platform or "windows").strip().lower()
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    scripts_root = os.path.join(project_root, "scripts")

    if platform_key in {"ubuntu", "linux", "unix"}:
        installer_path = os.path.join(scripts_root, "install-terminal-agent.sh")
        if not os.path.exists(installer_path):
            return {"success": False, "error": "Ubuntu Terminal Agent installer is not available in this release"}
        return FileResponse(installer_path, media_type="text/x-shellscript", filename="install-terminal-agent.sh")

    if platform_key not in {"windows", "win"}:
        return {"success": False, "error": "Unsupported Terminal Agent platform"}

    executable_path = os.path.join(project_root, "NexoraTerminalAgent.exe")
    if os.path.exists(executable_path):
        return FileResponse(executable_path, media_type="application/vnd.microsoft.portable-executable", filename="NexoraTerminalAgent.exe")

    release_url = os.environ.get(
        "TERMINAL_AGENT_WINDOWS_URL",
        "https://github.com/libing28390-sketch/Release-netops/raw/refs/heads/windows/NexoraTerminalAgent.exe",
    ).strip()
    if release_url.startswith(("https://", "http://")):
        try:
            remote_response = urlopen(
                UrlRequest(release_url, headers={"User-Agent": "Nexora-NetOps/Terminal-Agent"}),
                timeout=20,
            )
        except (HTTPError, URLError, TimeoutError) as exc:
            return {
                "success": False,
                "error": f"Windows Terminal Agent download is unavailable: {exc}",
            }

        def stream_executable():
            try:
                while True:
                    chunk = remote_response.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                remote_response.close()

        return StreamingResponse(
            stream_executable(),
            media_type="application/vnd.microsoft.portable-executable",
            headers={
                "Content-Disposition": 'attachment; filename="NexoraTerminalAgent.exe"',
                "Cache-Control": "no-store",
            },
        )

    return {
        "success": False,
        "error": "Windows Terminal Agent executable is not available in this release. Configure TERMINAL_AGENT_WINDOWS_URL or use the Python installer.",
    }


@router.get("/exchange-token")
async def exchange_token(token: str) -> Dict[str, Any]:
    import logging
    from datetime import datetime, timezone
    from core.crypto import decrypt_credential

    logger = logging.getLogger(__name__)

    conn = get_db_connection()
    try:
        res = conn.execute(
            "SELECT * FROM pam_sessions WHERE session_token = ? "
            "AND COALESCE(session_kind, 'ssh_terminal') != 'device_web' LIMIT 1",
            (token,),
        ).fetchone()

        if not res:
            return {"success": False, "error": "Invalid session token"}

        session_data = dict(res)

        if session_data.get("token_consumed"):
            return {"success": False, "error": "Token already consumed"}

        expires_at_str = session_data.get("token_expires_at")
        try:
            expires_at = datetime.strptime(expires_at_str, '%Y-%m-%dT%H:%M:%S+00:00').replace(tzinfo=timezone.utc)
        except Exception:
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
            except Exception:
                return {"success": False, "error": "Invalid expiry time format in session"}

        if datetime.now(timezone.utc) > expires_at:
            return {"success": False, "error": "Token expired"}

        host = session_data.get("target_ip")
        user = session_data.get("login_username")
        target_port = resolve_ssh_port(session_data)

        # Fetch device password
        dev_res = conn.execute("SELECT * FROM devices WHERE ip_address = ? LIMIT 1", (host,)).fetchone()
        if not dev_res:
            dev_res = conn.execute("SELECT * FROM physical_assets WHERE management_ip = ? LIMIT 1", (host,)).fetchone()

        if not dev_res:
            return {"success": False, "error": f"Device/Asset with IP {host} not found in database"}

        device_data = dict(dev_res)
        # A physical asset lookup does not carry the device-side asset_id
        # column, so add the link before resolving role-specific credentials.
        # This keeps the protocol handler aligned with the Web/PAM path.
        if not device_data.get('asset_id') and device_data.get('management_ip'):
            device_data['asset_id'] = device_data.get('id')
        target_port = resolve_ssh_port(session_data) if session_data.get("target_port") else resolve_ssh_port(device_data)
        resolved_credentials = resolve_device_credentials(device_data)
        password = ""
        if user == resolved_credentials.get('normal_username'):
            password = resolved_credentials.get('normal_password') or ''
        elif user == resolved_credentials.get('admin_username'):
            password = resolved_credentials.get('admin_password') or ''
        elif user == device_data.get("username"):
            # Legacy single-account records are still supported, but only as
            # a final fallback after the two explicit CMDB roles.
            password = resolved_credentials.get('password') or ''

        if not password:
            return {"success": False, "error": f"Password for user {user} on {host} not found"}

        # Decrypt password
        plain_password = decrypt_credential(password)
        if not plain_password:
            plain_password = password

        # Consume token
        conn.execute(
            "UPDATE pam_sessions SET token_consumed = 1, updated_at = ? WHERE session_token = ?",
            (datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00'), token)
        )
        conn.commit()

        return {
            "success": True,
            "ip": host,
            "port": target_port,
            "user": user,
            "password": plain_password
        }
    except Exception as e:
        logger.error(f"[System] Token exchange failed: {str(e)}")
        return {"success": False, "error": f"Internal error during exchange: {str(e)}"}
    finally:
        conn.close()


@router.post("/launch-terminal")
async def launch_terminal(payload: Dict[str, Any], request: Request) -> Dict[str, Any]:
    import subprocess
    import logging
    import uuid
    from datetime import datetime, timezone, timedelta
    from services.audit_service import log_audit_event

    logger = logging.getLogger(__name__)

    app_type = payload.get("app_type")
    path = payload.get("path")
    host = payload.get("host")
    user = payload.get("user")
    requester_username = payload.get("requester_username", "unknown")
    access_level = payload.get("access_level", "normal")  # 'normal' | 'admin'
    mfa_code = payload.get("mfa_code")
    fixed_pin = payload.get("fixed_pin")

    # ── 特权账号登录必须先通过 MFA 审批 ──────────────────────────
    auth_session = None
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        from api.users import validate_session_token
        auth_session = validate_session_token(auth_header[7:].strip())
    if auth_session and auth_session.get('username'):
        requester_username = auth_session['username']

    if access_level == "admin":
        if not auth_session or not auth_session.get('username'):
            return {"success": False, "error": "管理员访问需要有效的登录会话"}
        if not mfa_code or not fixed_pin:
            return {
                "success": False,
                "requires_mfa": True,
                "error": "特权访问需要 MFA 验证",
            }
        from api.pam import _verify_mfa_totp
        ok, err = _verify_mfa_totp(requester_username, fixed_pin, mfa_code)
        if not ok:
            return {"success": False, "error": err or "MFA 验证失败"}
    # ──────────────────────────────────────────────────────────────

    # 1. Fetch the password from DB
    conn = get_db_connection()
    plain_password = ""
    try:
        device_row = conn.execute("SELECT * FROM devices WHERE ip_address = ? LIMIT 1", (host,)).fetchone()
        asset_row = None
        if device_row and device_row['asset_id']:
            asset_row = conn.execute(
                "SELECT * FROM physical_assets WHERE id = ? LIMIT 1",
                (device_row['asset_id'],),
            ).fetchone()
        if not device_row:
            asset_row = conn.execute("SELECT * FROM physical_assets WHERE management_ip = ? LIMIT 1", (host,)).fetchone()

        if not device_row and not asset_row:
            return {"success": False, "error": f"Device/Asset with IP {host} not found in database"}

        device_data = dict(device_row or asset_row)
        if asset_row:
            device_data['asset_id'] = asset_row['id']
        target_port = resolve_ssh_port(device_data)
        resolved = resolve_device_credentials(device_data)
        role_prefix = 'admin' if access_level == 'admin' else 'normal'
        login_user = resolved.get(f'{role_prefix}_username') or ''
        password = resolved.get(f'{role_prefix}_password') or ''

        if not login_user or not password:
            return {"success": False, "error": f"{role_prefix} credentials for {host} not found"}

        # The asset role is authoritative. Ignore a stale generic username
        # sent by an older client and launch the selected role account.
        user = login_user

        # Decrypt password so it can be returned
        plain_password = decrypt_credential(password)
        if not plain_password:
            plain_password = password

        # ── PAM audit record for local terminal ──────────────────────
        # We cannot intercept or record local terminal traffic, but we
        # can at least create an audit trail so the session appears in
        # the PAM history with connect_method='local'.
        asset_id = device_data.get("asset_id") or device_data.get("id") or ""
        device_id = device_data.get("id") or ""
        hostname = device_data.get("hostname") or host

        session_id = f"session-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        now_str = now.strftime('%Y-%m-%dT%H:%M:%S+00:00')
        expires_at = (now + timedelta(seconds=LOCAL_TERMINAL_TOKEN_TTL_SECONDS)).strftime('%Y-%m-%dT%H:%M:%S+00:00')

        session_token = f"local-{uuid.uuid4().hex[:16]}"
        try:
            conn.execute('''
                INSERT INTO pam_sessions (
                    id, asset_id, device_id, requester_username, access_level,
                    login_username, connect_method, target_ip, target_port,
                    status, connected_at, closed_at, close_reason,
                    duration_seconds, recording_path,
                    session_token, token_expires_at, token_consumed,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session_id, asset_id, device_id, requester_username, access_level,
                user, 'local', host, target_port,
                # Local sessions are immediately 'closed' — we have no way to track
                # when the user actually disconnects from their local client.
                'closed', now_str, now_str, 'local_client_launched',
                0, '',  # no recording for local sessions
                session_token, expires_at, 0,
                now_str, now_str,
            ))
            conn.commit()
        except Exception as db_err:
            logger.warning(f"[System] Failed to write PAM audit record for local session: {db_err}")

        log_audit_event(
            event_type='pam.session.local_launch',
            category='access',
            severity='info' if access_level == 'normal' else 'warning',
            status='open',
            summary=f'Local terminal launched: {user}@{host} via {app_type} ({access_level})',
            actor_username=requester_username,
            target_type='asset',
            target_id=asset_id,
            target_name=hostname,
            device_id=device_id,
            details={
                'session_id': session_id,
                'app_type': app_type,
                'login_username': user,
                'access_level': access_level,
                'note': 'Local terminal — no recording available',
            },
        )
        # ─────────────────────────────────────────────────────────────

    finally:
        conn.close()

    if not path or not os.path.exists(path):
        # 后端不在用户 Windows 主机上时，返回令牌并让浏览器端助手接管启动。
        return {
            "success": True,
            "session_id": session_id,
            "client_side": True,
            "session_token": session_token,
            "port": target_port,
            "path_unavailable": bool(path),
        }

    try:
        if app_type == "xshell":
            cmd = f'"{path}" -url "ssh://{user}:{plain_password}@{host}:{target_port}"'
        elif app_type == "putty":
            cmd = f'"{path}" -ssh {user}@{host} -P {target_port} -pw "{plain_password}"' if plain_password else f'"{path}" -ssh {user}@{host} -P {target_port}'
        elif app_type == "securecrt":
            cmd = f'"{path}" /SSH2 /L {user} /P {target_port} /PASSWORD "{plain_password}" {host}' if plain_password else f'"{path}" /SSH2 /L {user} /P {target_port} {host}'
        else:
            cmd = f'"{path}" "{user}@{host}:{target_port}"'

        logger.info(f"[System] Launching terminal: {app_type} on {host}")
        creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(cmd, shell=True, creationflags=creation_flags)
        return {"success": True, "session_id": session_id}
    except Exception as e:
        logger.error(f"[System] Launch failed: {str(e)}")
        return {"success": False, "error": "终端启动失败，请检查程序路径是否正确。此功能仅支持本地部署。"}
