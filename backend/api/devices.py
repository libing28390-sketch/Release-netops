from fastapi import APIRouter, HTTPException, Body, Query
from fastapi.responses import JSONResponse
import os
import uuid
import json
import socket
import time
from typing import Optional
from database import get_db_connection
from services.audit_service import log_audit_event
from services.device_health_service import annotate_devices_with_health
from services.operational_data_service import collect_operational_data, collect_custom_command_data
from core.crypto import encrypt_credential, decrypt_credential
from drivers.ssh_compat import build_ssh_error_guidance, get_ssh_error_code

router = APIRouter()


def _probe_tcp_port(host: str, port: int, timeout: float = 1.5) -> tuple[bool, float | None, str | None]:
    started_at = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            latency_ms = round((time.perf_counter() - started_at) * 1000, 1)
            return True, latency_ms, None
    except OSError as exc:
        latency_ms = round((time.perf_counter() - started_at) * 1000, 1)
        return False, latency_ms, str(exc)


def _build_probe_stage(stage: str, ok: bool, summary: str, detail: str, latency_ms: float | None = None) -> dict:
    return {
        'stage': stage,
        'ok': ok,
        'summary': summary,
        'detail': detail,
        'latency_ms': latency_ms,
    }


def _sanitize_device_item(item: dict) -> dict:
    sanitized = dict(item)
    if 'password' in sanitized:
        sanitized['password'] = ''
    return sanitized


def _build_ssh_failure_response(hostname: str | None, ip_address: str, error_text: str, probe_output: list[str], probe_stages: list[dict], status_code: int = 400) -> JSONResponse:
    error_code = get_ssh_error_code(error_text)
    device_label = hostname or ip_address
    detail = f"SSH login failed for {device_label}: {error_text}"
    stage_detail = error_text

    if error_code == 'legacy_ssh_algorithms':
        detail = '设备 SSH 算法较旧，兼容重试后仍未完成协商。'
        stage_detail = 'SSH 协商失败，目标设备仅接受较旧的算法组合。'
    elif error_code == 'ssh_authentication_failed':
        detail = '设备可达，但 SSH 认证被拒绝。请核对账号密码或 AAA/VTY 配置。'
        stage_detail = 'TCP/22 已通，认证请求已到达设备，但用户名或密码被拒绝。'
    elif error_code == 'ssh_transport_timeout':
        detail = '设备管理口可达，但 SSH 会话建立或读取超时。'
        stage_detail = '传输层连接建立后响应超时，通常与设备负载或中间策略有关。'
    elif error_code == 'ssh_transport_unreachable':
        detail = '设备 IP 可达，但 SSH 传输层未正常建立。'
        stage_detail = '目标主机未完成 SSH 会话建立，请检查端口、SSH 服务或安全策略。'

    content = {
        'detail': detail,
        'raw_error': error_text,
        'output': "\n".join(probe_output + [f"SSH login: failed ({error_text})"]),
        'check_mode': 'deep',
        'stages': probe_stages + [
            _build_probe_stage('ssh', False, 'SSH login failed', stage_detail)
        ],
    }
    if error_code:
        content['error_code'] = error_code
        content['guidance'] = build_ssh_error_guidance(error_text)
    return JSONResponse(status_code=status_code, content=content)


def _resolve_connection_target(payload: dict) -> dict:
    device_id = payload.get('device_id')
    resolved = {
        'hostname': payload.get('hostname'),
        'ip_address': payload.get('ip_address'),
        'username': payload.get('username'),
        'password': payload.get('password'),
        'method': payload.get('method', 'ssh'),
        'platform': payload.get('platform', 'cisco_ios'),
        'check_mode': str(payload.get('check_mode') or 'quick').lower(),
    }

    if not device_id:
        return resolved

    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail='Device not found')

    stored = dict(row)
    stored_password = decrypt_credential(stored.get('password')) or ''
    payload_password = payload.get('password')

    resolved['hostname'] = resolved['hostname'] or stored.get('hostname')
    resolved['ip_address'] = resolved['ip_address'] or stored.get('ip_address')
    resolved['username'] = resolved['username'] or stored.get('username') or ''
    resolved['method'] = payload.get('method') or stored.get('connection_method') or 'ssh'
    resolved['platform'] = payload.get('platform') or stored.get('platform') or 'cisco_ios'
    if payload_password and not str(payload_password).startswith('enc:v1:'):
        resolved['password'] = payload_password
    else:
        resolved['password'] = stored_password
    return resolved

def _normalize_device_row(row):
    item = dict(row)
    try:
        item['config_history'] = json.loads(item.get('config_history', '[]'))
    except Exception:
        item['config_history'] = []

    try:
        item['interface_data'] = json.loads(item.get('interface_data', '[]'))
    except Exception:
        item['interface_data'] = []

    try:
        item['cpu_history'] = json.loads(item.get('cpu_history', '[]'))
    except Exception:
        item['cpu_history'] = []

    try:
        item['memory_history'] = json.loads(item.get('memory_history', '[]'))
    except Exception:
        item['memory_history'] = []

    return _sanitize_device_item(item)


@router.get("/devices")
def read_devices(
    search: Optional[str] = Query(default=None),
    platform: Optional[str] = Query(default=None),
    role: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    mode: Optional[str] = Query(default='full'),
    sort_key: Optional[str] = Query(default=None),
    sort_direction: Optional[str] = Query(default='asc'),
    page: Optional[int] = Query(default=None, ge=1),
    page_size: Optional[int] = Query(default=None, ge=1, le=200),
):
    conn = get_db_connection()
    try:
        where_clauses = []
        params = []

        if search and search.strip():
            q = f"%{search.strip()}%"
            where_clauses.append('(hostname LIKE ? OR ip_address LIKE ? OR sn LIKE ?)')
            params.extend([q, q, q])

        if platform and platform != 'all':
            where_clauses.append('platform = ?')
            params.append(platform)

        if role and role != 'all':
            where_clauses.append('LOWER(role) LIKE ?')
            params.append(f'%{role.lower()}%')

        if status and status != 'all':
            where_clauses.append('status = ?')
            params.append(status)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ''

        sortable_columns = {
            'hostname': 'hostname',
            'model': 'model',
            'platform': 'platform',
            'site': 'site',
            'connection_method': 'connection_method',
            'status': 'status',
            'ip_address': 'ip_address',
            'role': 'role',
        }
        order_col = sortable_columns.get(sort_key or '', 'hostname')
        order_dir = 'DESC' if str(sort_direction).lower() == 'desc' else 'ASC'
        select_clause = '*'
        if str(mode).lower() == 'light':
            # Lightweight projection for high-frequency polling.
            select_clause = (
                'id, hostname, ip_address, platform, status, compliance, sn, model, version, '
                'role, site, uptime, connection_method, cpu_usage, memory_usage, temp, '
                'fan_status, psu_status, sys_name, sys_location, sys_contact'
            )

        # Backward-compatible mode: no pagination params -> return array.
        # Safety cap: never return more than 500 rows without explicit pagination.
        if page is None or page_size is None:
            devices = conn.execute(
                f'SELECT {select_clause} FROM devices {where_sql} ORDER BY {order_col} {order_dir} LIMIT 500',
                tuple(params)
            ).fetchall()
            items = [_sanitize_device_item(dict(d)) for d in devices] if str(mode).lower() == 'light' else [_normalize_device_row(d) for d in devices]
            return annotate_devices_with_health(conn, items)

        total_row = conn.execute(
            f'SELECT COUNT(*) AS count FROM devices {where_sql}',
            tuple(params)
        ).fetchone()
        total = int(total_row['count']) if total_row else 0

        # Status counts across full filtered set (not just current page)
        status_count_rows = conn.execute(
            f'SELECT status, COUNT(*) AS cnt FROM devices {where_sql} GROUP BY status',
            tuple(params)
        ).fetchall()
        status_counts = {r['status']: r['cnt'] for r in status_count_rows}

        offset = (page - 1) * page_size
        devices = conn.execute(
            f'SELECT {select_clause} FROM devices {where_sql} ORDER BY {order_col} {order_dir} LIMIT ? OFFSET ?',
            tuple([*params, page_size, offset])
        ).fetchall()

        items = [_sanitize_device_item(dict(d)) for d in devices] if str(mode).lower() == 'light' else [_normalize_device_row(d) for d in devices]

        return {
            'items': annotate_devices_with_health(conn, items),
            'total': total,
            'page': page,
            'page_size': page_size,
            'status_counts': status_counts,
        }
    finally:
        conn.close()

@router.post("/devices")
def create_device(device: dict = Body(...)):
    conn = get_db_connection()
    device_id = device.get('id') or str(uuid.uuid4())
    try:
        conn.execute('''
            INSERT INTO devices (id, hostname, ip_address, platform, status, compliance, username, password, sn, model, version, role, site, uptime, connection_method, snmp_community, snmp_port)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            device_id,
            device.get('hostname'),
            device.get('ip_address'),
            device.get('platform'),
            device.get('status', 'pending'),
            device.get('compliance', 'unknown'),
            device.get('username'),
            encrypt_credential(device.get('password')),
            device.get('sn', ''),
            device.get('model', ''),
            device.get('version', ''),
            device.get('role', ''),
            device.get('site', ''),
            device.get('uptime', '0d 0h'),
            device.get('connection_method', 'ssh'),
            device.get('snmp_community', 'public'),
            device.get('snmp_port', 161)
        ))
        conn.commit()
        new_device = conn.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
        log_audit_event(
            event_type='DEVICE_CREATE',
            category='inventory',
            severity='medium',
            status='success',
            summary=f"Created device {device.get('hostname')}",
            actor_username=device.get('actor_username') or 'admin',
            actor_role=device.get('actor_role') or 'Administrator',
            target_type='device',
            target_id=device_id,
            target_name=device.get('hostname'),
            device_id=device_id,
            details={'ip_address': device.get('ip_address'), 'platform': device.get('platform')},
        )
        return _sanitize_device_item(dict(new_device))
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})
    finally:
        conn.close()

@router.delete("/devices/{device_id}")
def delete_device(device_id: str):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT hostname FROM devices WHERE id = ?', (device_id,)).fetchone()
        conn.execute('DELETE FROM devices WHERE id = ?', (device_id,))
        conn.commit()
        log_audit_event(
            event_type='DEVICE_DELETE',
            category='inventory',
            severity='high',
            status='success',
            summary=f"Deleted device {row['hostname'] if row else device_id}",
            actor_username='admin',
            actor_role='Administrator',
            target_type='device',
            target_id=device_id,
            target_name=row['hostname'] if row else device_id,
            device_id=device_id,
        )
        return {"status": "success"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})
    finally:
        conn.close()

@router.put("/devices/{device_id}")
def update_device(device_id: str, device: dict = Body(...)):
    conn = get_db_connection()
    try:
        existing_row = conn.execute('SELECT password FROM devices WHERE id = ?', (device_id,)).fetchone()
        if not existing_row:
            raise HTTPException(status_code=404, detail='Device not found')

        submitted_password = device.get('password')
        if submitted_password in (None, ''):
            stored_password = existing_row['password']
        else:
            stored_password = encrypt_credential(submitted_password)

        conn.execute('''
            UPDATE devices 
            SET hostname = ?, ip_address = ?, platform = ?, sn = ?, model = ?, version = ?, role = ?, site = ?, connection_method = ?, username = ?, password = ?, current_config = ?, config_history = ?, snmp_community = ?, snmp_port = ?
            WHERE id = ?
        ''', (
            device.get('hostname', ''),
            device.get('ip_address', ''),
            device.get('platform', 'cisco_ios'),
            device.get('sn', ''),
            device.get('model', ''),
            device.get('version', ''),
            device.get('role', 'Unknown'),
            device.get('site', ''),
            device.get('connection_method', 'ssh'),
            device.get('username', ''),
            stored_password,
            device.get('current_config', ''),
            json.dumps(device.get('config_history', [])) if device.get('config_history') else '[]',
            device.get('snmp_community', 'public'),
            device.get('snmp_port', 161),
            device_id
        ))
        conn.commit()
        log_audit_event(
            event_type='DEVICE_UPDATE',
            category='inventory',
            severity='medium',
            status='success',
            summary=f"Updated device {device.get('hostname', device_id)}",
            actor_username=device.get('actor_username') or 'admin',
            actor_role=device.get('actor_role') or 'Administrator',
            target_type='device',
            target_id=device_id,
            target_name=device.get('hostname', device_id),
            device_id=device_id,
            details={'ip_address': device.get('ip_address'), 'platform': device.get('platform')},
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.post("/devices/{device_id}/config")
def update_device_config(device_id: str, payload: dict = Body(...)):
    conn = get_db_connection()
    try:
        conn.execute('UPDATE devices SET current_config = ?, config_history = ? WHERE id = ?',
                     (payload.get('current_config'), json.dumps(payload.get('config_history', [])), device_id))
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})
    finally:
        conn.close()

@router.post("/devices/connect")
def test_device_connection(payload: dict = Body(...)):
    from services.automation_service import AutomationService
    from ping3 import ping
    import logging
    logger = logging.getLogger(__name__)

    resolved = _resolve_connection_target(payload)
    hostname = resolved.get('hostname')
    ip_address = resolved.get('ip_address')
    username = resolved.get('username')
    password = resolved.get('password')
    method = resolved.get('method', 'ssh')
    platform = resolved.get('platform', 'cisco_ios')
    check_mode = resolved.get('check_mode', 'quick')
    
    if not ip_address:
        raise HTTPException(status_code=400, detail="IP address is required")
    
    # 默认使用 SSH（22 端口），除非明确指定其他方式
    port = 22
    if method and method.lower() == 'telnet':
        port = 23
    
    logger.info(f"Testing connection to device: {hostname or ip_address} (IP: {ip_address}, Port: {port}, Platform: {platform}, User: {username}, Mode: {check_mode})")

    probe_output: list[str] = []
    probe_stages: list[dict] = []
    ping_ok = False
    ping_latency_ms: float | None = None
    
    # 第一步：快速 ICMP ping 测试网络连通性
    try:
        logger.debug(f"Step 1: Ping {ip_address}")
        ping_result = ping(ip_address, timeout=1.5)
        if ping_result is None or ping_result is False:
            logger.warning(f"ICMP ping failed for {ip_address}")
            probe_output.append(f"ICMP: no reply from {ip_address}")
            probe_stages.append(_build_probe_stage('icmp', False, 'ICMP unreachable', f'No ICMP reply from {ip_address}'))
        else:
            ping_ok = True
            ping_latency_ms = round(float(ping_result) * 1000, 1)
            probe_output.append(f"ICMP: reachable in {ping_latency_ms} ms")
            probe_stages.append(_build_probe_stage('icmp', True, 'ICMP reachable', f'Replied from {ip_address}', ping_latency_ms))
            logger.debug(f"Step 1: Ping successful ({ping_latency_ms:.2f}ms)")
    except Exception as ping_err:
        logger.warning(f"Ping error: {str(ping_err)}")
        probe_output.append(f"ICMP: probe error ({ping_err})")
        probe_stages.append(_build_probe_stage('icmp', False, 'ICMP probe error', str(ping_err)))

    # 第二步：快速 TCP 端口探测，判断 SSH/Telnet 端口是否真正可达
    logger.debug(f"Step 2: TCP port probe {ip_address}:{port}")
    tcp_ok, tcp_latency_ms, tcp_error = _probe_tcp_port(ip_address, port)
    if tcp_ok:
        probe_output.append(f"TCP/{port}: reachable in {tcp_latency_ms} ms")
        probe_stages.append(_build_probe_stage('tcp', True, f'TCP/{port} reachable', f'Port {port} accepted a connection', tcp_latency_ms))
    else:
        probe_output.append(f"TCP/{port}: unreachable ({tcp_error})")
        probe_stages.append(_build_probe_stage('tcp', False, f'TCP/{port} unreachable', tcp_error or f'Port {port} is not reachable', tcp_latency_ms))

    if check_mode != 'deep':
        device_label = hostname or ip_address
        if tcp_ok:
            if ping_ok:
                return {
                    "status": "success",
                    "message": f"{device_label} is reachable. ICMP responds and TCP/{port} is open.",
                    "output": "\n".join(probe_output),
                    "check_mode": "quick",
                    "stages": probe_stages,
                }
            return {
                "status": "success",
                "message": f"{device_label} is reachable on TCP/{port}. ICMP may be filtered on the path.",
                "output": "\n".join(probe_output),
                "check_mode": "quick",
                "stages": probe_stages,
            }

        failure_detail = (
            f"{device_label} did not pass the quick reachability test. "
            f"ICMP {'ok' if ping_ok else 'failed'}, TCP/{port} is not reachable."
        )
        return JSONResponse(
            status_code=400,
            content={
                "detail": failure_detail,
                "output": "\n".join(probe_output),
                "check_mode": "quick",
                "stages": probe_stages,
            },
        )
    
    # 深度模式：在快速探测通过后再做 SSH 认证测试
    if not tcp_ok:
        return JSONResponse(
            status_code=400,
            content={
                "detail": f"TCP/{port} is not reachable, so SSH login validation was skipped.",
                "output": "\n".join(probe_output),
                "check_mode": "deep",
                "stages": probe_stages + [
                    _build_probe_stage('ssh', False, 'SSH validation skipped', f'TCP/{port} was not reachable, so SSH login was skipped')
                ],
            },
        )

    if not username or not password:
        return JSONResponse(
            status_code=400,
            content={
                'detail': '设备缺少可用的 SSH 凭据，请先补充用户名和密码。',
                'check_mode': 'deep',
                'stages': probe_stages + [
                    _build_probe_stage('ssh', False, 'SSH validation skipped', '未找到可用的用户名或密码，无法执行登录校验。')
                ],
            },
        )

    logger.debug(f"Step 3: SSH authentication test")
    device_info = {
        'hostname': hostname,
        'ip_address': ip_address,
        'username': username,
        'password': password,
        'connection_method': method,
        'platform': platform,
        'port': port
    }
    
    try:
        # 使用 netmiko 驱动，除非是本地测试
        driver_type = 'mock' if ip_address in ['127.0.0.1', '0.0.0.0', 'localhost'] else 'netmiko'
        logger.debug(f"Using driver type: {driver_type}")
        service = AutomationService(driver_type=driver_type)
        
        is_connected, error_msg = service.check_connectivity(device_info)
        
        if is_connected:
            logger.info(f"Successfully connected to {hostname or ip_address}")
            return {
                "status": "success",
                "message": f"Successfully connected to {hostname or ip_address}",
                "output": "\n".join(probe_output + ["SSH login: success"]),
                "check_mode": "deep",
                "stages": probe_stages + [
                    _build_probe_stage('ssh', True, 'SSH login successful', f'Authenticated to {hostname or ip_address}')
                ],
            }
        else:
            logger.warning(f"Failed to connect to {hostname or ip_address}: {error_msg}")
            return _build_ssh_failure_response(hostname, ip_address, error_msg, probe_output, probe_stages, status_code=400)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Connection error for {hostname or ip_address}: {str(e)}", exc_info=True)
        raw_error = str(e)
        error_code = get_ssh_error_code(raw_error)
        if error_code:
            return _build_ssh_failure_response(hostname, ip_address, raw_error, probe_output, probe_stages, status_code=500)
        raise HTTPException(status_code=500, detail=f"Connection error: {raw_error}")

@router.post("/devices/import")
def import_devices(payload: dict = Body(...)):
    devices = payload.get('devices', [])
    if not isinstance(devices, list):
        raise HTTPException(status_code=400, detail="Invalid data format")
    
    conn = get_db_connection()
    try:
        for device in devices:
            device_id = device.get('id') or str(uuid.uuid4())
            conn.execute('''
                INSERT INTO devices (id, hostname, ip_address, platform, status, compliance, sn, model, version, role, site, uptime, connection_method) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                device_id,
                device.get('hostname'),
                device.get('ip_address'),
                device.get('platform', 'unknown'),
                device.get('status', 'pending'),
                device.get('compliance', 'unknown'),
                device.get('sn', ''),
                device.get('model', ''),
                device.get('version', ''),
                device.get('role', ''),
                device.get('site', ''),
                device.get('uptime', '0d 0h'),
                device.get('connection_method', 'ssh')
            ))
        conn.commit()
        log_audit_event(
            event_type='DEVICE_IMPORT',
            category='inventory',
            severity='medium',
            status='success',
            summary=f"Imported {len(devices)} device(s)",
            actor_username=payload.get('actor_username') or 'admin',
            actor_role=payload.get('actor_role') or 'Administrator',
            target_type='device_batch',
            target_name=f"{len(devices)} devices",
            details={'count': len(devices)},
        )
        return {"status": "success"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "error": str(e)})
    finally:
        conn.close()


@router.post("/devices/{device_id}/snmp-test")
async def snmp_test(device_id: str):
    """Test SNMP connectivity and immediately sync all SNMP data into DB on success."""
    import time, re as _re, json as _json
    conn = get_db_connection()
    try:
        device = conn.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
    finally:
        conn.close()

    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    ip = device['ip_address']
    community = device['snmp_community'] or 'public'
    port = device['snmp_port'] or 161

    if not ip:
        return {"success": False, "error": "No IP address configured"}

    import asyncio as _aio
    from services.snmp_service import _snmp_get, _snmp_walk, collect_device_info, collect_interface_data, collect_device_metrics

    results = {"success": False, "ip": ip, "community": community, "port": port,
               "sys_name": None, "sys_descr": None, "response_ms": None, "error": None,
               "synced": False}

    start = time.monotonic()
    try:
        # Step 1: 标准 System MIB（sysName + sysDescr）并行查询
        sys_name, sys_descr = await _aio.gather(
            _snmp_get(ip, community, '1.3.6.1.2.1.1.5.0', port, timeout=3),
            _snmp_get(ip, community, '1.3.6.1.2.1.1.1.0', port, timeout=3),
        )
        elapsed = round((time.monotonic() - start) * 1000)
        results['response_ms'] = elapsed

        if sys_name or sys_descr:
            results['success'] = True
            results['sys_name'] = sys_name
            results['sys_descr'] = sys_descr
        else:
            # Step 2: ifName (ifXTable) — 部分设备/SNMP view 不含 system MIB
            if_rows = await _snmp_walk(ip, community, '1.3.6.1.2.1.31.1.1.1.1', port, timeout=3, max_rows=3)
            if not if_rows:
                # Step 3: ifDescr (基础 IF-MIB RFC 1213) — 最广泛兼容
                if_rows = await _snmp_walk(ip, community, '1.3.6.1.2.1.2.2.1.2', port, timeout=3, max_rows=3)
            elapsed = round((time.monotonic() - start) * 1000)
            results['response_ms'] = elapsed
            if if_rows:
                results['success'] = True
                results['sys_descr'] = f"System MIBs not in SNMP view – reachable via IF-MIB ({len(if_rows)} interfaces found)"
            else:
                results['error'] = 'No SNMP response – verify community string, UDP 161 and device SNMP config'
    except Exception as e:
        elapsed = round((time.monotonic() - start) * 1000)
        results['response_ms'] = elapsed
        results['error'] = str(e)

    # ── 测试成功后立即全量同步数据 ──────────────────────────────────────
    if results['success']:
        try:
            platform = device['platform'] or 'cisco_ios'
            dev_info, intf_data, metrics = await _aio.gather(
                collect_device_info(ip, community, port),
                collect_interface_data(ip, community, port),
                collect_device_metrics(ip, platform, community, port),
            )

            updates: dict = {}

            # 设备基础信息
            if dev_info.get('sys_name'):
                updates['sys_name'] = dev_info['sys_name']
                results['sys_name'] = dev_info['sys_name']
            if dev_info.get('sys_descr'):
                descr = dev_info['sys_descr']
                results['sys_descr'] = descr
                if not device['model']:
                    first_line = descr.split('\r\n')[0].split('\n')[0].strip()
                    if first_line:
                        updates['model'] = first_line[:80]
                if not device['version']:
                    ver_match = _re.search(r'[Vv]ersion\s+([\w\.\(\)\-/]+)', descr)
                    if ver_match:
                        updates['version'] = ver_match.group(1)
            if dev_info.get('uptime'):
                updates['uptime'] = dev_info['uptime']
            if dev_info.get('sys_location'):
                updates['sys_location'] = dev_info['sys_location']

            # CPU / 内存
            if metrics.get('cpu_usage') is not None:
                updates['cpu_usage'] = metrics['cpu_usage']
            if metrics.get('memory_usage') is not None:
                updates['memory_usage'] = metrics['memory_usage']
            if metrics.get('temp') is not None:
                updates['temp'] = metrics['temp']
            if metrics.get('fan_status') is not None:
                updates['fan_status'] = metrics['fan_status']
            if metrics.get('psu_status') is not None:
                updates['psu_status'] = metrics['psu_status']

            # 接口数据
            if intf_data:
                updates['interface_data'] = _json.dumps(intf_data)

            if updates:
                conn2 = get_db_connection()
                try:
                    set_clause = ', '.join(f'{k} = ?' for k in updates)
                    conn2.execute(f'UPDATE devices SET {set_clause} WHERE id = ?',
                                  (*updates.values(), device_id))
                    conn2.commit()
                finally:
                    conn2.close()

            results['synced'] = True
        except Exception as sync_err:
            results['sync_error'] = str(sync_err)

    return results


@router.post("/devices/{device_id}/operational-data")
def collect_device_operational_data(device_id: str, payload: dict = Body(default={})): 
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail='Device not found')

    device_info = dict(row)
    device_info['password'] = decrypt_credential(device_info.get('password')) or ''
    categories = payload.get('categories') if isinstance(payload, dict) else None

    try:
        return collect_operational_data(device_info, categories=categories)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'Operational data collection failed: {exc}')


@router.post("/devices/{device_id}/parsed-command")
def collect_device_parsed_command(device_id: str, payload: dict = Body(default={})):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail='Device not found')

    device_info = dict(row)
    device_info['password'] = decrypt_credential(device_info.get('password')) or ''
    command = payload.get('command') if isinstance(payload, dict) else None

    try:
        return collect_custom_command_data(device_info, command=command)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'Parsed command execution failed: {exc}')
