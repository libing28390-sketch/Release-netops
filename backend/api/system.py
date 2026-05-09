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
    
    return {
        "version": VERSION,
        "edition": EDITION,
        "build_date": BUILD_DATE,
        "project_name": settings.PROJECT_NAME,
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
    import tkinter as tk
    from tkinter import filedialog
    import asyncio
    import concurrent.futures

    def run_picker():
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            file_path = filedialog.askopenfilename(
                title="选择终端程序可执行文件",
                filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")]
            )
            root.destroy()
            return {"path": file_path.replace('/', '\\')} if file_path else {"path": ""}
        except Exception as e:
            return {"path": "", "error": str(e)}

    with concurrent.futures.ThreadPoolExecutor() as pool:
        return await asyncio.get_event_loop().run_in_executor(pool, run_picker)

@router.post("/launch-terminal")
async def launch_terminal(payload: Dict[str, Any]) -> Dict[str, Any]:
    import subprocess
    import logging
    logger = logging.getLogger(__name__)

    app_type = payload.get("app_type")
    path = payload.get("path")
    host = payload.get("host")
    user = payload.get("user")
    
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
            
    finally:
        conn.close()

    if not path or not os.path.exists(path):
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
        return {"success": True}
    except Exception as e:
        logger.error(f"[System] Launch failed: {str(e)}")
        return {"success": False, "error": str(e)}
