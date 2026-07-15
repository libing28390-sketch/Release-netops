from fastapi import APIRouter, HTTPException, Body, Request, Depends
from fastapi.responses import JSONResponse
import os
import uuid
import json
import re
from datetime import datetime, timezone
from ping3 import ping
from database import get_db_connection
import logging
import asyncio

from services.automation_service import AutomationService
from drivers.base import CommandResult
from services.audit_service import log_audit_event
from api.devices import _record_instant_execution
from services.config_approval_service import request_approval, verify_code, consume_approval
from core.rbac import require_role
from services.vault_service import resolve_device_credentials

router = APIRouter()
logger = logging.getLogger(__name__)

# ── Helper to resolve the nested Depends issue ──
# Because rbac.require_role returns a Depends object, we extract the underlying function
def get_operator(user=require_role("Operator")):
    return user

def get_admin(user=require_role("Administrator")):
    return user


def _first_complete_credential_pair(*pairs: tuple[str, str]) -> tuple[str, str]:
    for username, password in pairs:
        if username and password:
            return username, password
    return '', ''


def _resolve_execution_credentials(device: dict, auth_role: str = 'normal') -> dict:
    """Resolve paired plaintext credentials for automation command execution."""
    creds = resolve_device_credentials(device)
    role = str(auth_role or 'normal').lower().strip()

    if role == 'admin':
        username, password = _first_complete_credential_pair(
            (creds.get('admin_username') or '', creds.get('admin_password') or ''),
            (creds.get('username') or '', creds.get('password') or ''),
            (creds.get('normal_username') or '', creds.get('normal_password') or ''),
        )
    elif role == 'auto':
        username, password = _first_complete_credential_pair(
            (creds.get('username') or '', creds.get('password') or ''),
            (creds.get('admin_username') or '', creds.get('admin_password') or ''),
            (creds.get('normal_username') or '', creds.get('normal_password') or ''),
        )
    else:
        username, password = _first_complete_credential_pair(
            (creds.get('normal_username') or '', creds.get('normal_password') or ''),
            (creds.get('username') or '', creds.get('password') or ''),
            (creds.get('admin_username') or '', creds.get('admin_password') or ''),
        )

    return {
        'username': username,
        'password': password,
        'enable_password': creds.get('enable_password') or '',
        'resolved_role': role,
    }

# ── Script Management CRUD ──

@router.get("/scripts")
async def read_scripts():
    conn = get_db_connection()
    try:
        scripts = conn.execute('SELECT * FROM scripts ORDER BY updated_at DESC').fetchall()
        return [dict(s) for s in scripts]
    finally:
        conn.close()

@router.post("/scripts")
async def create_script(script: dict = Body(...), user: dict = Depends(get_operator)):
    conn = get_db_connection()
    script_id = script.get('id', '').strip()
    
    if not re.match(r'^[a-zA-Z0-9_\-]+$', script_id):
        raise HTTPException(status_code=400, detail="标识码(Code ID)仅支持英文、数字和下划线")

    submitter = user.get('username', 'admin')
    approver = script.get('approver_username', '')
    
    if submitter == approver:
        raise HTTPException(status_code=403, detail="审批回避原则：审核人不能是提单人本人")
    
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute('''
            INSERT INTO scripts (
                id, name, platform, description, content, 
                script_type, category, author, version, status, 
                submitter_name, approver_username, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            script_id, script.get('name'), script.get('platform'), script.get('description'), 
            script.get('content'), script.get('script_type', 'shell'), script.get('category', 'custom'), submitter,
            script.get('version', 'v1.0.0'), script.get('status', 'draft'),
            submitter, approver, now, now
        ))
        conn.commit()
        return {"success": True, "id": script_id}
    except Exception as e:
        logger.error(f"Failed to create script: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.put("/scripts/{script_id}")
async def update_script(script_id: str, script: dict = Body(...), user: dict = Depends(get_operator)):
    conn = get_db_connection()
    now = datetime.now(timezone.utc).isoformat()
    submitter = user.get('username', 'admin')
    
    try:
        existing = conn.execute('SELECT * FROM scripts WHERE id = ?', (script_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Script not found")
        
        approver = script.get('approver_username', existing['approver_username'])
        if script.get('status') == 'pending_audit' and submitter == approver:
             raise HTTPException(status_code=403, detail="审批回避原则：审核人不能是提单人本人")

        fields = {
            "name": script.get('name', existing['name']),
            "platform": script.get('platform', existing['platform']),
            "description": script.get('description', existing['description']),
            "content": script.get('content', existing['content']),
            "script_type": script.get('script_type', existing['script_type']),
            "category": script.get('category', existing['category']),
            "version": script.get('version', existing['version']),
            "status": script.get('status', existing['status']),
            "approver_username": approver,
            "rejected_reason": script.get('rejected_reason', existing['rejected_reason']),
            "updated_at": now
        }
        
        sql = 'UPDATE scripts SET ' + ', '.join([f"{k} = ?" for k in fields.keys()]) + ' WHERE id = ?'
        params = list(fields.values()) + [script_id]
        
        conn.execute(sql, params)
        conn.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update script {script_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.delete("/scripts/{script_id}")
async def delete_script(script_id: str, user: dict = Depends(get_admin)):
    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM scripts WHERE id = ?', (script_id,))
        conn.commit()
        return {"success": True}
    finally:
        conn.close()

# ── Execution & Task Routes ──

@router.post("/execute")
async def execute_task(request: Request, payload: dict = Body(...), user: dict = Depends(get_operator)):
    device_id = payload.get('device_id')
    device_ids = payload.get('device_ids', [])
    if isinstance(device_ids, str):
        try: device_ids = json.loads(device_ids)
        except: device_ids = [device_ids] if device_ids else []
    if not isinstance(device_ids, list): device_ids = [device_ids] if device_ids else []
    if device_id and device_id not in device_ids: device_ids.insert(0, device_id)
    if not device_ids: raise HTTPException(status_code=400, detail="device_id or device_ids is required")
    
    script_id = payload.get('script_id')
    command = payload.get('command')
    is_config_req = payload.get('isConfig')
    config_reason = payload.get('config_reason', '').strip()
    approval_token = payload.get('approval_token', '').strip()
    change_ticket = str(payload.get('change_ticket') or payload.get('order_number') or '').strip()
    actor_username = user.get('username', 'admin')

    conn = get_db_connection()
    try:
        is_shell_script = False
        is_config = False
        task_name = payload.get('task_name') or 'Custom Command'
        
        final_command = command
        if script_id:
            script = conn.execute('SELECT * FROM scripts WHERE id = ?', (script_id,)).fetchone()
            if script:
                final_command = command if command else script['content']
                task_name = f"Script: {script['name']}"
                if script.get('script_type') == 'shell':
                    is_shell_script = True
            else:
                template = conn.execute('SELECT * FROM templates WHERE id = ?', (script_id,)).fetchone()
                if template:
                    final_command = command if command else template['content']
                    task_name = f"Template: {template['name']}"
        
        if not final_command: raise HTTPException(status_code=400, detail="No command or script provided")
        
        # Detect if it's a shell script by shebang if not already known
        if not is_shell_script and final_command.strip().startswith('#!'):
            is_shell_script = True

        if is_shell_script:
            # Use a robust temp-file wrapping method to ensure shebang execution
            import uuid
            tmp_file = f"/tmp/netops_{uuid.uuid4().hex}.sh"
            wrapped_command = f"cat > {tmp_file} << 'NETOPS_EOF'\n{final_command}\nNETOPS_EOF\nchmod +x {tmp_file} && {tmp_file}; rm -f {tmp_file}"
            commands = [wrapped_command]
            is_config = False
            is_query_only = True # Treat as query to avoid approvals if not explicitly marked as config
        else:
            commands = [c.strip() for c in final_command.split('\n') if c.strip()]
            is_server = False
            if device_ids:
                placeholders = ','.join(['?'] * len(device_ids))
                rows = conn.execute(f'SELECT platform, device_category FROM devices WHERE id IN ({placeholders})', device_ids).fetchall()
                if rows:
                    is_server = all(
                        any(t in str(r['platform'] or '').lower() for t in ('linux', 'ubuntu', 'centos', 'debian', 'redhat', 'server'))
                        or str(r['device_category'] or '').lower() == 'server'
                        for r in rows
                    )

            if is_server:
                server_query_prefixes = (
                    'dis ', 'display ', 'show ', 'ping ', 'tracert ', 'traceroute ', 'dir ', 'pwd ', 'more ', 'terminal ',
                    'df ', 'free ', 'uptime', 'ip ', 'ss ', 'ps ', 'cat ', 'last ', 'env', 'tail ', 'grep ', 'uname ', 'sensors', 'dmesg', 'top '
                )
                def check_server_cmd(c):
                    c_lower = c.lower()
                    if any(c_lower.startswith(p) for p in server_query_prefixes):
                        return True
                    if c_lower in ('df', 'free', 'uptime', 'ip', 'ss', 'ps', 'last', 'env', 'uname', 'sensors', 'dmesg', 'top'):
                        return True
                    if c_lower.startswith('systemctl '):
                        allowed_sysctl = ('systemctl status', 'systemctl list-units', 'systemctl is-active', 'systemctl is-enabled')
                        return any(c_lower.startswith(p) for p in allowed_sysctl)
                    return False
                is_query_only = all(check_server_cmd(c) for c in commands)
            else:
                _show_prefixes = ('dis ', 'display ', 'show ', 'ping ', 'tracert ', 'traceroute ', 'dir ', 'pwd ', 'more ', 'terminal ')
                is_query_only = all(any(c.lower().startswith(p) for p in _show_prefixes) or c.lower() in ('pwd', 'dir') for c in commands)

            if not is_query_only:
                is_config = True
                ticket_valid = False
                if change_ticket:
                    row = conn.execute("SELECT status FROM change_orders WHERE order_number = ?", (change_ticket,)).fetchone()
                    if row and row['status'] in {'approved', 'implementing'}: ticket_valid = True
                if not ticket_valid:
                    if not consume_approval(approval_token): raise HTTPException(status_code=403, detail="配置变更类命令必须关联有效的变更工单或提供授权码")
            else:
                is_config = False

        batch_results = {}
        for dev_id in device_ids:
            device_row = conn.execute('SELECT * FROM devices WHERE id = ?', (dev_id,)).fetchone()
            if device_row:
                d = dict(device_row)
                auth_role = payload.get('auth_role') or payload.get('role') or 'normal'
                resolved_creds = _resolve_execution_credentials(d, auth_role)
                exec_username = resolved_creds['username']
                d['username'] = exec_username
                d['password'] = resolved_creds['password']
                d['enable_password'] = resolved_creds['enable_password']
                
                logger.info(f"[Automation] Executing for {d.get('hostname')} ({d.get('ip_address')}) with role={auth_role}, username={exec_username}")
                
                driver_type = 'mock' if d.get('ip_address') in ['127.0.0.1', '0.0.0.0'] else 'netmiko'
                service = AutomationService()
                def _parse_res(r):
                    if r.get('success'): return r.get('output', r.get('stdout', ''))
                    err = r.get('error') or r.get('stderr') or r.get('exception') or 'Unknown'
                    from drivers.ssh_compat import build_ssh_error_guidance
                    guidance = build_ssh_error_guidance(err)
                    if guidance != err:
                        return f"Error:\n{guidance}\n\n[原始技术报错 (Original Technical Error)]:\n{err}"
                    return f"Error: {err}"
                
                result = await asyncio.get_event_loop().run_in_executor(None, lambda: "\n".join([_parse_res(r) for r in service.execute_commands(d, commands, is_config=is_config)]))
                _record_instant_execution(d['id'], task_name, commands, 'completed', platform=d.get('platform'), output=result)
                batch_results[d['id']] = {'status': 'success', 'output': result}
        
        return {"status": "completed", "results": batch_results} if len(device_ids) > 1 else {"status": "success", "output": list(batch_results.values())[0]['output']}
    finally:
        conn.close()

@router.post("/config-approval/request")
async def request_config_approval(payload: dict = Body(...), user: dict = Depends(get_operator)):
    approver_username = (payload.get('approver_username') or '').strip()
    config_reason = (payload.get('config_reason') or '').strip()
    requester = user.get('username', 'unknown')
    token, err = request_approval(approver_username=approver_username, requester_username=requester, config_reason=config_reason, approval_type='config')
    if err: raise HTTPException(status_code=400, detail=err)
    return {"success": True, "approval_token": token}

@router.post("/config-approval/verify")
async def verify_config_approval(payload: dict = Body(...)):
    approval_token = payload.get('approval_token', '').strip()
    code = payload.get('code', '').strip()
    ok, err = verify_code(approval_token, code)
    if not ok: raise HTTPException(status_code=400, detail=err)
    return {"success": True}

@router.post("/devices/ping")
async def ping_device(payload: dict = Body(...)):
    ip = payload.get('ip_address')
    delay = await asyncio.get_event_loop().run_in_executor(None, lambda: ping(ip, timeout=2))
    return {"status": "success", "output": f"Time: {delay*1000:.2f}ms"} if delay else JSONResponse(status_code=500, content={"status":"error"})
