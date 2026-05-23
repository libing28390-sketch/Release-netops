from fastapi import APIRouter, Depends, BackgroundTasks
from typing import Dict, Any, Optional
import os
import sys
from core.version import VERSION, EDITION, BUILD_DATE
from license_auth.verifier import get_license_verifier
from license_auth.models import LicenseStatus
from core.config import settings

from services import notification_service
from core.crypto import decrypt_credential
import random
import time
from database import get_db_connection

router = APIRouter(prefix="/system", tags=["System"])


@router.get("/info")
async def get_system_info() -> Dict[str, Any]:
    verifier = get_license_verifier()
    license_status = verifier.validate()

    # 读取用户在 setup 向导里保存的 system_name
    system_name = settings.PROJECT_NAME
    try:
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT value FROM global_vars WHERE key = 'platform_settings'"
            ).fetchone()
            if row:
                import json as _json
                ps = _json.loads(row[0] if isinstance(row, (list, tuple)) else row['value'])
                if ps.get('system_name'):
                    system_name = ps['system_name']
        finally:
            conn.close()
    except Exception:
        pass

    return {
        "version": VERSION,
        "edition": EDITION,
        "build_date": BUILD_DATE,
        "project_name": settings.PROJECT_NAME,
        "system_name": system_name,
        "license": license_status.model_dump()
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

@router.post("/launch-terminal")
async def launch_terminal(payload: Dict[str, Any]) -> Dict[str, Any]:
    import subprocess
    import logging
    import uuid
    from datetime import datetime, timezone
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
    if access_level == "admin":
        if not mfa_code or not fixed_pin:
            return {
                "success": False,
                "requires_mfa": True,
                "error": "特权访问需要 MFA 验证",
            }
        from api.pam import _verify_mfa
        mfa_nonce = payload.get("mfa_nonce")
        ok, err = _verify_mfa(requester_username, fixed_pin, mfa_code, mfa_nonce)
        if not ok:
            return {"success": False, "error": err or "MFA 验证失败"}
    # ──────────────────────────────────────────────────────────────

    # 1. Fetch the password from DB
    conn = get_db_connection()
    try:
        res = conn.execute("SELECT * FROM devices WHERE ip_address = ? LIMIT 1", (host,)).fetchone()
        if not res:
            res = conn.execute("SELECT * FROM physical_assets WHERE management_ip = ? LIMIT 1", (host,)).fetchone()

        if not res:
            return {"success": False, "error": f"Device/Asset with IP {host} not found in database"}

        device_data = dict(res)
        password = ""
        if user == device_data.get("username") or user == device_data.get("admin_username"):
            password = device_data.get("password") or device_data.get("admin_password")
        elif user == device_data.get("normal_username"):
            password = device_data.get("normal_password")

        if not password:
            return {"success": False, "error": f"Password for user {user} on {host} not found"}

        # ── PAM audit record for local terminal ──────────────────────
        # We cannot intercept or record local terminal traffic, but we
        # can at least create an audit trail so the session appears in
        # the PAM history with connect_method='local'.
        asset_id = device_data.get("asset_id") or device_data.get("id") or ""
        device_id = device_data.get("id") or ""
        hostname = device_data.get("hostname") or host

        session_id = f"session-{uuid.uuid4().hex[:12]}"
        now_str = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')

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
                user, 'local', host, 22,
                # Local sessions are immediately 'closed' — we have no way to track
                # when the user actually disconnects from their local client.
                'closed', now_str, now_str, 'local_client_launched',
                0, '',  # no recording for local sessions
                session_token, now_str, 1,
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
        # 前端客户端侧启动模式：path 为特殊标记，跳过文件检查，只写审计日志
        if path in ('__client_side_launch__', '__mfa_verify_only__'):
            return {"success": True, "session_id": session_id, "client_side": True}
        return {"success": False, "error": f"Executable path not found: {path}"}

    plain_password = decrypt_credential(password)
    if not plain_password:
        plain_password = password

    try:
        if app_type == "xshell":
            cmd = f'"{path}" -url "ssh://{user}:{plain_password}@{host}"'
        elif app_type == "putty":
            cmd = f'"{path}" -ssh {user}@{host} -pw "{plain_password}"' if plain_password else f'"{path}" -ssh {user}@{host}'
        elif app_type == "securecrt":
            cmd = f'"{path}" /SSH2 /L {user} /PASSWORD "{plain_password}" {host}' if plain_password else f'"{path}" /SSH2 /L {user} {host}'
        else:
            cmd = f'"{path}" "{user}@{host}"'

        logger.info(f"[System] Launching terminal: {app_type} on {host}")
        subprocess.Popen(cmd, shell=True, creationflags=subprocess.CREATE_NEW_CONSOLE)
        return {"success": True, "session_id": session_id}
    except Exception as e:
        logger.error(f"[System] Launch failed: {str(e)}")
        return {"success": False, "error": "终端启动失败，请检查程序路径是否正确。此功能仅支持本地部署。"}
