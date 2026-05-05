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

# In-memory storage for MFA codes (Simple implementation for now)
mfa_store = {}

@router.post("/request-mfa")
async def request_mfa(data: Dict[str, Any]):
    user_id = data.get("user_id")
    username = data.get("username", "Admin")
    approver_id = data.get("approver_id")
    
    if not approver_id:
        return {"success": False, "error": "请先选择审批人"}

    # 1. Generate 6-digit code — keyed by username for reliable lookup
    code = f"{random.randint(100000, 999999)}"
    mfa_store[username] = {"code": code, "expire": time.time() + 300} # 5 min
    
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[MFA] Generated code for user={username}, approver_id={approver_id}")
    
    # 2. Get Approver and their Webhook from DB
    conn = get_db_connection()
    feishu_url = ""
    approver_name = "Admin"
    try:
        # Check approver's personal settings first
        row = conn.execute("SELECT username, notification_channels FROM users WHERE id = ?", (approver_id,)).fetchone()
        if row:
            approver_name = row['username']
            import json
            try:
                channels = json.loads(row['notification_channels'] or '{}')
                feishu_cfg = channels.get('feishu', {})
                if feishu_cfg.get('enabled') and feishu_cfg.get('webhook_url'):
                    feishu_url = feishu_cfg['webhook_url']
            except:
                pass
        
        # Fallback to global if personal not set
        if not feishu_url:
            global_row = conn.execute("SELECT webhook_url FROM global_notification_channels WHERE platform = 'feishu' AND enabled = 1").fetchone()
            if global_row:
                feishu_url = global_row['webhook_url']
    finally:
        conn.close()

    if not feishu_url:
        # If no webhook configured, return the code directly for testing/debugging
        logger.warning(f"[MFA] No feishu webhook configured for approver {approver_name}, returning code in response for dev mode")
        return {"success": True, "message": f"审批人 {approver_name} 未配置飞书，授权码为: {code}（仅测试模式可见）"}

    # 3. Send via Feishu (Directed to Approver)
    ok, msg = notification_service.send_feishu_mfa_access_code(
        feishu_url, username, code, expires_min=5, approver_name=approver_name
    )
    
    if ok:
        return {"success": True, "message": f"验证码已发送至审批人 {approver_name} 的飞书"}
    else:
        return {"success": False, "error": f"推送至 {approver_name} 失败: {msg}"}

@router.get("/info")
async def get_system_info() -> Dict[str, Any]:
    """
    Returns core platform information including version and license status.
    """
    verifier = get_license_verifier()
    license_status = verifier.validate()
    
    return {
        "version": VERSION,
        "edition": EDITION,
        "build_date": BUILD_DATE,
        "project_name": settings.PROJECT_NAME,
        "license": license_status.model_dump()
    }

@router.get("/check-update")
async def check_for_updates() -> Dict[str, Any]:
    """
    Checks for available updates. 
    Currently returns a mock response for the P1 phase.
    """
    # In a real scenario, this would query a central update server
    # For now, we mock a "new version" if the current version is 0.1.0
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

@router.post("/upgrade")
async def trigger_upgrade(background_tasks: BackgroundTasks):
    """
    Priority 3: Docker-based upgrade implementation.
    Executes 'docker compose pull && docker compose up -d' in the background.
    """
    import subprocess
    import os
    import logging
    logger = logging.getLogger(__name__)

    def run_docker_upgrade():
        try:
            # Note: This assumes the environment has docker-compose installed and 
            # the backend has permissions to execute it.
            logger.info("Starting system upgrade via Docker...")
            
            # Step 1: Pull latest images
            pull_cmd = ["docker", "compose", "pull"]
            logger.info(f"Executing: {' '.join(pull_cmd)}")
            subprocess.run(pull_cmd, capture_output=True, text=True, check=True)
            
            # Step 2: Restart containers
            up_cmd = ["docker", "compose", "up", "-d"]
            logger.info(f"Executing: {' '.join(up_cmd)}")
            # Note: This will likely kill the current process as the container restarts
            subprocess.run(up_cmd, capture_output=True, text=True, check=True)
            
            logger.info("Upgrade command sent successfully.")
        except subprocess.CalledProcessError as e:
            logger.error(f"Upgrade failed: {e.stderr}")
        except Exception as e:
            logger.error(f"Unexpected upgrade error: {str(e)}")

    background_tasks.add_task(run_docker_upgrade)
    
    return {
        "success": True, 
        "message": "升级指令已下发。系统正在后台更新镜像并重启，请稍后刷新页面。"
    }

@router.get("/file-picker")
async def open_file_picker() -> Dict[str, Any]:
    """
    Opens a native Windows file picker dialog on the host machine.
    Works because the backend is running locally.
    """
    import tkinter as tk
    from tkinter import filedialog
    import asyncio
    import concurrent.futures

    def run_picker():
        try:
            root = tk.Tk()
            root.withdraw()  # Hide main window
            root.attributes("-topmost", True)  # Bring dialog to front
            file_path = filedialog.askopenfilename(
                title="选择终端程序可执行文件",
                filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")]
            )
            root.destroy()
            return {"path": file_path.replace('/', '\\')} if file_path else {"path": ""}
        except Exception as e:
            return {"path": "", "error": str(e)}

    # Run in a separate thread to avoid blocking the FastAPI event loop
    with concurrent.futures.ThreadPoolExecutor() as pool:
        result = await asyncio.get_event_loop().run_in_executor(pool, run_picker)
    
    return result

@router.post("/verify-mfa")
async def verify_mfa(data: Dict[str, Any]) -> Dict[str, Any]:
    """Verification-only endpoint for Web Terminal security."""
    mfa_code = data.get("mfa_code")
    fixed_pw = data.get("fixed_password")
    current_username = data.get("current_username")
    
    if not current_username:
        return {"success": False, "error": "无法识别当前用户身份"}
        
    import bcrypt
    from database import get_db_connection
    conn = get_db_connection()
    try:
        user_row = conn.execute("SELECT fixed_pin, mfa_fixed_password FROM users WHERE username = ?", (current_username,)).fetchone()
        if not user_row:
            return {"success": False, "error": "用户不存在"}
        
        stored_pin_hash = user_row['fixed_pin'] or user_row['mfa_fixed_password']
        if not stored_pin_hash:
            return {"success": False, "error": "您尚未在个人设置中配置 6 位固定密码"}
            
        if not bcrypt.checkpw(str(fixed_pw).encode('utf-8'), stored_pin_hash.encode('utf-8')):
            return {"success": False, "error": "固定密码验证失败"}
    except Exception:
        return {"success": False, "error": "系统错误"}
    finally:
        conn.close()

    if not mfa_code:
        return {"success": False, "error": "需要提供动态验证码"}
    
    stored = mfa_store.get(current_username)
    if not stored or str(stored["code"]) != str(mfa_code) or time.time() > stored["expire"]:
        return {"success": False, "error": "验证码错误或已过期"}
    
    # Success - clean up code
    del mfa_store[current_username]
    return {"success": True}

@router.post("/launch-terminal")
async def launch_terminal(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Directly launches a terminal application on the host machine.
    Bypasses browser protocol restrictions because backend is local.
    """
    import subprocess
    import logging
    logger = logging.getLogger(__name__)

    path = data.get("path")
    app_type = data.get("app_type", "xshell")
    host = data.get("host")
    user = data.get("user", "root")
    password = data.get("password")
    
    # MFA Check
    mfa_code = data.get("mfa_code")
    user_id = data.get("user_id", "default_user")
    is_privileged = data.get("is_privileged", False)

    if is_privileged:
        fixed_pw = data.get("fixed_password")
        current_username = data.get("current_username")
        
        if not current_username:
            return {"success": False, "error": "无法识别当前用户身份，请重新登录"}
            
        import bcrypt
        from database import get_db_connection
        conn = get_db_connection()
        try:
            user_row = conn.execute("SELECT fixed_pin, mfa_fixed_password FROM users WHERE username = ?", (current_username,)).fetchone()
            if not user_row:
                return {"success": False, "error": "无法识别当前用户身份"}
            
            stored_pin_hash = user_row['fixed_pin'] or user_row['mfa_fixed_password']
            if not stored_pin_hash:
                return {"success": False, "error": "您尚未在个人设置中配置 6 位固定密码"}
                
            if not bcrypt.checkpw(str(fixed_pw).encode('utf-8'), stored_pin_hash.encode('utf-8')):
                return {"success": False, "error": "固定密码验证失败"}
        except Exception as e:
            logger.error(f"Error checking fixed PIN: {e}")
            return {"success": False, "error": "验证码系统错误"}
        finally:
            conn.close()

        if not mfa_code:
            return {"success": False, "error": "特权登录需要提供飞书验证码"}
        
        # Lookup MFA code by username (matches the key used in request-mfa)
        stored = mfa_store.get(current_username)
        if not stored or str(stored["code"]) != str(mfa_code) or time.time() > stored["expire"]:
            return {"success": False, "error": "飞书验证码错误或已过期"}
        
        # Success - clean up code
        del mfa_store[current_username]

    if not path or not os.path.exists(path):
        return {"success": False, "error": "Executable path not found"}

    # CRITICAL FIX: Decrypt the password before passing it to Xshell/Putty
    # The passwords stored in the DB (and sent to frontend) are encrypted with 'enc:v1:'
    plain_password = decrypt_credential(password)
    if not plain_password:
        plain_password = password # Fallback if decryption fails or it's already plain

    try:
        # Use shell=True and manual quoting for maximum robustness with Windows paths and URLs
        # Format: "C:\path\to\xshell.exe" -url "ssh://user:pass@host"
        if app_type == "xshell":
            cmd = f'"{path}" -url "ssh://{user}:{plain_password}@{host}"'
        elif app_type == "putty":
            cmd = f'"{path}" -ssh {user}@{host} -pw "{plain_password}"' if plain_password else f'"{path}" -ssh {user}@{host}'
        elif app_type == "securecrt":
            cmd = f'"{path}" /SSH2 /L {user} /PASSWORD "{plain_password}" {host}' if plain_password else f'"{path}" /SSH2 /L {user} {host}'
        else:
            cmd = f'"{path}" "{user}@{host}"'

        logger.info(f"Executing: {cmd}")
        subprocess.Popen(cmd, shell=True, stdin=None, stdout=None, stderr=None, close_fds=True)
        return {"success": True}
    except Exception as e:
        logger.error(f"Launch failed: {str(e)}")
        return {"success": False, "error": str(e)}
