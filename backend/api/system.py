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
