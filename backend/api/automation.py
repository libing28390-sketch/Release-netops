from fastapi import APIRouter, HTTPException, Body, Request, Depends
from fastapi.responses import JSONResponse
import os
import uuid
import json
from datetime import datetime
from ping3 import ping
try:
    from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
    HAS_NETMIKO = True
except ImportError:
    HAS_NETMIKO = False

try:
    from scrapli.driver.core import AsyncIOSXEDriver, AsyncNXOSDriver, AsyncEOSDriver, AsyncJunosDriver
    from scrapli.exceptions import ScrapliException
    HAS_SCRAPLI = True
except ImportError:
    HAS_SCRAPLI = False

try:
    from scrapli_community.huawei.vrp.async_driver import AsyncHuaweiVRPDriver
    from scrapli_community.hp.comware.async_driver import AsyncHPComwareDriver
except ImportError:
    pass
from database import get_db_connection
import logging
import asyncio

from services.automation_service import AutomationService
from drivers.base import CommandResult
from services.audit_service import log_audit_event
from services.config_approval_service import request_approval, verify_code, consume_approval
from core.crypto import decrypt_credential
from core.rbac import require_role

router = APIRouter()
logger = logging.getLogger(__name__)

# ── Dangerous command blacklist ──
# Commands that can cause irreversible damage to network devices.
_DANGEROUS_COMMANDS = [
    'write erase', 'erase startup', 'erase nvram', 'erase flash',
    'format ', 'delete /force', 'delete /recursive',
    'reload', 'reboot', 'reset saved-configuration',
    'restore factory-default', 'system-shutdown',
    'license boot', 'boot system',
]

def _check_command_safety(commands: list[str]) -> str | None:
    """Return an error message if any command matches the blacklist, or None if safe."""
    for cmd in commands:
        cmd_lower = cmd.lower().strip()
        for dangerous in _DANGEROUS_COMMANDS:
            if cmd_lower.startswith(dangerous) or cmd_lower == dangerous.strip():
                return f"Blocked dangerous command: '{cmd}'. This operation requires direct console access."
    return None

# 初始化业务服务
automation_service = AutomationService(driver_type='netmiko') # 使用 Netmiko 驱动执行命令


# ── 配置审批验证码 ─────────────────────────────────────


@router.post("/config-approval/request")
async def request_config_approval(payload: dict = Body(...), user=require_role("Operator")):
    """请求配置变更审批验证码，发送到审批人的飞书。"""
    approver_username = (payload.get('approver_username') or '').strip()
    config_reason = (payload.get('config_reason') or '').strip()
    device_hostname = (payload.get('device_hostname') or '').strip()
    command_preview = (payload.get('command_preview') or '').strip()

    if not approver_username:
        raise HTTPException(status_code=400, detail="approver_username is required")
    if not config_reason or len(config_reason) < 2:
        raise HTTPException(status_code=400, detail="config_reason is required (min 2 chars)")

    requester = user.get('username', 'unknown')
    token, err = request_approval(
        approver_username=approver_username,
        requester_username=requester,
        config_reason=config_reason,
        device_hostname=device_hostname,
        command_preview=command_preview,
    )
    if err:
        raise HTTPException(status_code=400, detail=err)

    return {"success": True, "approval_token": token, "message": "Approval code sent to approver via Feishu"}


@router.post("/config-approval/verify")
async def verify_config_approval(payload: dict = Body(...), user=require_role("Operator")):
    """验证审批码。"""
    approval_token = (payload.get('approval_token') or '').strip()
    code = (payload.get('code') or '').strip()

    if not approval_token or not code:
        raise HTTPException(status_code=400, detail="approval_token and code are required")

    ok, err = verify_code(approval_token, code)
    if not ok:
        raise HTTPException(status_code=400, detail=err)

    return {"success": True, "message": "Approval code verified"}


@router.post("/execute")
async def execute_task(request: Request, payload: dict = Body(...), user=require_role("Operator")):
    device_id = payload.get('device_id')
    script_id = payload.get('script_id')
    command = payload.get('command')
    is_config_req = payload.get('isConfig')
    config_reason = payload.get('config_reason', '').strip()
    approval_token = payload.get('approval_token', '').strip()
    save_history = payload.get('save_history', True)
    actor_username = user.get('username', 'admin')
    actor_id = user.get('id')
    actor_role = user.get('role', 'Operator')

    # 配置模式强制要求填写变更原因 + 已通过的审批令牌
    if is_config_req and not config_reason:
        raise HTTPException(status_code=400, detail="Config mode requires a change reason (config_reason)")
    if is_config_req:
        if not approval_token:
            raise HTTPException(status_code=400, detail="Config mode requires an approved approval_token")
        approval_record = consume_approval(approval_token)
        if not approval_record:
            raise HTTPException(status_code=403, detail="Invalid or expired approval token. Please request a new code.")

    conn = get_db_connection()
    try:
        device = conn.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        device_dict = dict(device)
        # Decrypt stored credentials before passing to driver
        device_dict['password'] = decrypt_credential(device_dict.get('password')) or ''
        final_command = command
        task_name = 'Direct Command'
        
        if script_id:
            # Try scripts table first
            script = conn.execute('SELECT * FROM scripts WHERE id = ?', (script_id,)).fetchone()
            if script:
                # If command is provided, it means the user edited the script content in the UI
                final_command = command if command else script['content']
                task_name = f"Script: {script['name']}"
            else:
                # Try templates table
                template = conn.execute('SELECT * FROM templates WHERE id = ?', (script_id,)).fetchone()
                if template:
                    final_command = command if command else template['content']
                    task_name = f"Template: {template['name']}"
        
        if not final_command:
            raise HTTPException(status_code=400, detail="No command or script provided")

        job_id = str(uuid.uuid4())
        if save_history:
            conn.execute('INSERT INTO jobs (id, device_id, task_name, status, created_at) VALUES (?, ?, ?, ?, ?)',
                         (job_id, device_id, task_name, 'running', datetime.now().isoformat()))
            conn.commit()

        try:
            commands = [c.strip() for c in final_command.split('\n') if c.strip()]

            # 以实际命令内容判断是否进入配置模式：
            # 1. 只要有任一行是 show/display/ping 类只读命令 → exec 模式（防止误配置）
            # 2. 否则：若前端明确传了 isConfig，以前端为准
            # 3. 若前端未传：扫描全部行，出现常见配置关键词则走配置模式
            _show_prefixes = ('dis ', 'display ', 'show ', 'ping ', 'tracert ', 'traceroute ')
            _has_show = any(
                c.lower().startswith(p) for c in commands for p in _show_prefixes
            )
            if _has_show:
                is_config = False
            elif is_config_req is not None:
                is_config = is_config_req
            else:
                _joined = '\n'.join(commands).lower()
                _config_kws = (
                    'conf t', 'configure terminal', 'system-view',
                    'interface ', 'ip route', 'ip address', 'vlan ',
                    'router ', 'access-list', 'route-map', 'no shutdown',
                )
                is_config = any(kw in _joined for kw in _config_kws)

            # ── Safety check: block dangerous/destructive commands ──
            safety_err = _check_command_safety(commands)
            if safety_err:
                conn.execute('UPDATE jobs SET status = ?, output = ? WHERE id = ?', ('blocked', safety_err, job_id))
                conn.commit()
                log_audit_event(
                    event_type='COMMAND_BLOCKED',
                    category='automation',
                    severity='critical',
                    status='blocked',
                    summary=f"Blocked dangerous command on {device_dict.get('hostname')}",
                    actor_username=actor_username,
                    actor_role=actor_role,
                    source_ip=request.client.host if request.client else None,
                    target_type='device',
                    target_id=device_id,
                    target_name=device_dict.get('hostname'),
                    device_id=device_id,
                    job_id=job_id,
                    details={'blocked_reason': safety_err, 'command_preview': '\n'.join(commands[:8])},
                )
                raise HTTPException(status_code=403, detail=safety_err)
            
            # 自动选择驱动：如果是测试 IP 则使用 Mock 驱动
            driver_type = 'mock' if device_dict.get('ip_address') in ['127.0.0.1', '0.0.0.0', 'localhost'] else 'netmiko'
            
            # 使用新架构的 Service 执行任务
            service = AutomationService(driver_type=driver_type)
            
            # 在线程池中执行同步驱动任务，避免阻塞 FastAPI 事件循环
            import time
            exec_start = time.time()
            
            def _execute():
                exec_begin = time.time()
                results = service.execute_commands(device_dict, commands, is_config=is_config)
                exec_elapsed = time.time() - exec_begin
                logger.info(f"Command execution took {exec_elapsed:.2f}s for device {device_dict.get('hostname')}")
                
                # 合并结果回显
                merge_start = time.time()
                output = "\n".join([r.output if r.success else f"Error: {r.error}" for r in results])
                merge_elapsed = time.time() - merge_start
                logger.info(f"Result merge took {merge_elapsed:.3f}s, output size: {len(output)} chars")
                
                return output

            result = await asyncio.get_event_loop().run_in_executor(None, _execute)
            total_elapsed = time.time() - exec_start
            logger.info(f"Total execution time: {total_elapsed:.2f}s")
            
            if save_history:
                conn.execute('UPDATE jobs SET status = ?, output = ? WHERE id = ?', ('success', result, job_id))
                conn.commit()
            log_audit_event(
                event_type='DIRECT_EXECUTION',
                category='automation',
                severity='high' if is_config else 'medium',
                status='success',
                summary=f"Executed {task_name} on {device_dict.get('hostname')}",
                actor_id=str(actor_id) if actor_id is not None else None,
                actor_username=actor_username,
                actor_role=actor_role,
                source_ip=request.client.host if request.client else None,
                target_type='device',
                target_id=device_id,
                target_name=device_dict.get('hostname'),
                device_id=device_id,
                job_id=job_id,
                details={
                    'task_name': task_name,
                    'command_count': len(commands),
                    'is_config': is_config,
                    'script_id': script_id,
                    'command_preview': '\n'.join(commands[:8]),
                    'config_reason': config_reason if is_config else None,
                },
            )
            return {"status": "success", "jobId": job_id, "output": result}
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Job execution failed: {error_msg}", exc_info=True)
            if save_history:
                conn.execute('UPDATE jobs SET status = ?, output = ? WHERE id = ?', ('failed', error_msg, job_id))
                conn.commit()
            log_audit_event(
                event_type='DIRECT_EXECUTION',
                category='automation',
                severity='high' if is_config_req else 'medium',
                status='failed',
                summary=f"Execution failed for {device_dict.get('hostname')}",
                actor_id=str(actor_id) if actor_id is not None else None,
                actor_username=actor_username,
                actor_role=actor_role,
                source_ip=request.client.host if request.client else None,
                target_type='device',
                target_id=device_id,
                target_name=device_dict.get('hostname'),
                device_id=device_id,
                job_id=job_id,
                details={'task_name': task_name, 'error': error_msg, 'script_id': script_id},
            )
            return JSONResponse(status_code=500, content={"status": "error", "error": error_msg, "jobId": job_id})
    finally:
        conn.close()

@router.post("/devices/ping")
async def ping_device(payload: dict = Body(...)):
    ip = payload.get('ip_address')
    if not ip:
        raise HTTPException(status_code=400, detail="IP address is required")
    
    try:
        # Run ping in a thread to avoid blocking
        def _ping():
            return ping(ip, timeout=2)
            
        delay = await asyncio.get_event_loop().run_in_executor(None, _ping)
        
        if delay is not None:
            return {
                "status": "success", 
                "message": f"Ping to {payload.get('hostname')} ({ip}) successful", 
                "output": f"Response time: {delay*1000:.2f}ms"
            }
        else:
            raise Exception(f"Ping to {ip} timed out")
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})

@router.get("/scripts")
def read_scripts():
    conn = get_db_connection()
    try:
        scripts = conn.execute('SELECT * FROM scripts').fetchall()
        return [dict(s) for s in scripts]
    finally:
        conn.close()

@router.post("/scripts")
def create_script(script: dict = Body(...)):
    conn = get_db_connection()
    script_id = script.get('id') or str(uuid.uuid4())
    try:
        conn.execute('INSERT INTO scripts (id, name, platform, description, content) VALUES (?, ?, ?, ?, ?)',
                     (script_id, script.get('name'), script.get('platform'), script.get('description'), script.get('content')))
        conn.commit()
        return {"success": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})
    finally:
        conn.close()
