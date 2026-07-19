from fastapi import APIRouter, HTTPException, Body, Query, Depends
from fastapi.responses import JSONResponse
import os
import uuid
import json
import socket
import time
import logging
from typing import Optional
from database import get_db_connection
from services.audit_service import log_audit_event
from services.device_health_service import annotate_devices_with_health
from services.operational_data_service import collect_operational_data, collect_custom_command_data
from services import tag_service
from core.crypto import encrypt_credential, decrypt_credential
from core.rbac import require_role
from services.vault_service import resolve_device_credentials, write_credentials as vault_write, vault_available
from drivers.ssh_compat import build_ssh_error_guidance, get_ssh_error_code
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)

router = APIRouter()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')


def _vendor_from_platform(platform: str) -> str:
    """Best-effort vendor from Netmiko platform string."""
    p = (platform or '').lower()
    if 'cisco' in p:
        return 'Cisco'
    if 'huawei' in p or 'vrp' in p:
        return 'Huawei'
    if 'h3c' in p or 'comware' in p:
        return 'H3C'
    if 'arista' in p:
        return 'Arista'
    if 'juniper' in p or 'junos' in p:
        return 'Juniper'
    return ''
  
  
def _record_instant_execution(
    device_id: str,
    name: str,
    commands: list[str],
    status: str,
    platform: str = 'unknown',
    error: str = '',
    output: str = '',
    result_payload: dict | None = None,
    device_info: dict | None = None,
):
    """Log a one-off query execution into the playbook_executions table so it shows up in history.

    If ``result_payload`` (the dict returned by ``collect_operational_data``) is provided,
    commands and outputs are derived from it so the history view shows the actual device
    response instead of an empty panel.
    """
    # Derive commands + output from the collect_operational_data payload when given.
    derived_commands: list[str] = list(commands or [])
    derived_output_parts: list[str] = []
    if result_payload and isinstance(result_payload.get('categories'), list):
        for cat in result_payload['categories']:
            if not isinstance(cat, dict):
                continue
            cat_key = cat.get('key') or ''
            for cmd in cat.get('commands') or []:
                if cmd and cmd not in derived_commands:
                    derived_commands.append(cmd)
            # Prefer raw_outputs (direct device response) for display in history.
            for ro in cat.get('raw_outputs') or []:
                if not isinstance(ro, dict):
                    continue
                cmd = ro.get('command') or ''
                out = ro.get('output') or ''
                header = f"# {cat_key}: {cmd}" if cat_key else f"# {cmd}"
                derived_output_parts.append(f"{header}\n{out}".rstrip())
            # If a category failed, surface the error in the output panel.
            if not cat.get('success', True) and cat.get('error'):
                derived_output_parts.append(f"# ERROR [{cat_key}]: {cat['error']}")

    if derived_output_parts and not output:
        output = '\n\n'.join(derived_output_parts).strip()

    # Fallback: if nothing was derived but we got a payload, serialise it so at least
    # something is visible in history.
    if not output and result_payload:
        try:
            output = json.dumps(result_payload, ensure_ascii=False, indent=2)
        except Exception:
            output = ''

    if not derived_commands:
        derived_commands = list(commands or [])

    # Determine hostname/ip for history display
    host = (device_info or {}).get('hostname') or ''
    ip = (device_info or {}).get('ip_address') or ''

    conn = get_db_connection()
    try:
        exec_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # 1. Create Playbook Execution (status: 'completed' or 'failed')
        conn.execute('''
            INSERT INTO playbook_executions
            (id, scenario_id, scenario_name, platform, device_ids, variables, status, dry_run, author, concurrency, phases_json, created_at, updated_at, total_devices, success_count, failed_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            exec_id, 'instant', name, platform, json.dumps([device_id]), '{}',
            status, 0, 'admin', 1, json.dumps({'execute': derived_commands}),
            now, now, 1, 1 if status == 'completed' else 0, 0 if status == 'completed' else 1
        ))

        # 2. Create Device Result (include hostname + ip_address so the history list
        # can render them correctly)
        conn.execute('''
            INSERT INTO execution_device_results
            (id, execution_id, device_id, hostname, ip_address, status, error_message, phases_json, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            str(uuid.uuid4()), exec_id, device_id, host, ip, status, error,
            json.dumps({
                'execute': {
                    'success': status == 'completed',
                    'output': output or error or ('' if status == 'completed' else 'Unknown error'),
                    'commands': derived_commands,
                }
            }, ensure_ascii=False),
            now, now
        ))
        conn.commit()
    except Exception as e:
        _logger.warning(f"Failed to record instant execution: {e}")
    finally:
        conn.close()


def _create_linked_asset_for_device(conn, device_id: str, device: dict) -> str | None:
    """Reverse-link: when creating a device directly, auto-create a physical_assets record."""
    now = _utc_now()
    asset_id = f"asset-{uuid.uuid4().hex[:12]}"
    vendor = device.get('vendor') or _vendor_from_platform(device.get('platform', ''))
    normal_password = device.get('normal_password') or ''
    admin_password = device.get('admin_password') or ''
    try:
        conn.execute('''
            INSERT INTO physical_assets (
                id, asset_type, asset_tag, serial_number, vendor, model, hostname,
                site_id, rack, rack_unit, u_height, planned_start_u, management_ip, business_ip, device_role,
                vlan, uplink_switch, uplink_port,
                status, purchase_date, warranty_expiry, department, notes, created_at, updated_at,
                platform, connection_method, username, normal_username, normal_password,
                admin_username, admin_password, auth_model, enable_password, management_port
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            asset_id, 'network_device', '', device.get('sn', ''), vendor,
            device.get('model', ''), device.get('hostname', ''),
            device.get('site_id') or device.get('site', ''), '', '', 1, None,
            device.get('ip_address', ''), '', device.get('role', ''),
            '', '', '',
            'active', '', '', '', '', now, now,
            device.get('platform', ''), device.get('connection_method', 'ssh'),
            device.get('username', ''), device.get('normal_username', ''),
            encrypt_credential(normal_password) if normal_password else '',
            device.get('admin_username', ''),
            encrypt_credential(admin_password) if admin_password else '',
            device.get('auth_model', 'single'),
            encrypt_credential(device.get('enable_password')) if device.get('enable_password') else '',
            int(device.get('management_port') or 22),
        ))
        conn.execute('UPDATE devices SET asset_id = ?, vendor = ? WHERE id = ?', (asset_id, vendor, device_id))
        return asset_id
    except Exception as exc:
        _logger.warning('Failed to create linked asset for device %s: %s', device_id, exc)
        return None


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
    canonical_site_name = str(
        sanitized.get('site_name') or sanitized.get('site_code') or ''
    ).strip()
    canonical_site_id = str(sanitized.get('canonical_site_id') or '').strip()
    if canonical_site_name:
        # All device consumers use ``site`` as their display field. Keep the
        # canonical ID separately for filters and writes.
        sanitized['site'] = canonical_site_name
        sanitized['datacenter'] = canonical_site_name
    if canonical_site_id:
        sanitized['site_id'] = canonical_site_id
    cmdb_rack_id = str(sanitized.get('cmdb_rack_id') or '').strip()
    if cmdb_rack_id and not str(sanitized.get('rack_id') or '').strip():
        sanitized['rack_id'] = cmdb_rack_id
    if 'password' in sanitized:
        sanitized['password'] = ''
    if 'enable_password' in sanitized:
        sanitized['enable_password'] = ''
    if 'snmp_community' in sanitized:
        sanitized['snmp_community'] = ''
    return sanitized


def _resolve_device_site_id(conn, site_id: str | None, site_name: str | None) -> str:
    requested_id = str(site_id or '').strip()
    if requested_id:
        row = conn.execute('SELECT id FROM sites WHERE id = ?', (requested_id,)).fetchone()
        if row:
            return str(row['id'])
    requested_name = str(site_name or '').strip()
    if requested_name:
        row = conn.execute(
            'SELECT id FROM sites WHERE LOWER(site_name) = LOWER(?) OR LOWER(site_code) = LOWER(?) LIMIT 1',
            (requested_name, requested_name),
        ).fetchone()
        if row:
            return str(row['id'])
    # A deleted/default-free CMDB is valid. Do not return a dangling
    # site-default identifier; leave the device unassigned until an operator
    # selects a real site.
    return ''


def _build_ssh_failure_response(hostname: str | None, ip_address: str, error_text: str, probe_output: list[str], probe_stages: list[dict], status_code: int = 400, port: int = 22) -> JSONResponse:
    # Clean up paramiko error wrapper
    friendly_err = error_text.strip()
    prefix = "A paramiko SSHException occurred during connection creation:"
    if friendly_err.startswith(prefix):
        friendly_err = friendly_err[len(prefix):].strip()
    
    if "Error reading SSH protocol banner" in friendly_err:
        friendly_err = "读取 SSH 协议 Banner 失败 (Error reading SSH protocol banner)"
    elif "Authentication failed" in friendly_err:
        friendly_err = "身份验证失败 (Authentication failed)"
    elif "Connection refused" in friendly_err:
        friendly_err = "连接被拒绝 (Connection refused)"
    elif "Connection timed out" in friendly_err:
        friendly_err = "连接超时 (Connection timed out)"

    error_code = get_ssh_error_code(error_text)
    device_label = hostname or ip_address
    detail = f"SSH login failed for {device_label}: {friendly_err}"
    stage_detail = friendly_err

    if error_code == 'legacy_ssh_algorithms':
        detail = '设备 SSH 算法较旧，兼容重试后仍未完成协商。'
        stage_detail = 'SSH 协商失败，目标设备仅接受较旧的算法组合。'
    elif error_code == 'ssh_authentication_failed':
        detail = '设备可达，但 SSH 认证被拒绝。请核对账号密码或 AAA/VTY 配置。'
        stage_detail = f'TCP/{port} 已通，认证请求已到达设备，但用户名或密码被拒绝。'
    elif error_code == 'ssh_transport_timeout':
        detail = '设备管理口可达，但 SSH 会话建立或读取超时。'
        stage_detail = '传输层连接建立后响应超时，通常与设备负载或中间策略有关。'
    elif error_code == 'ssh_transport_unreachable':
        detail = '设备 IP 可达，但 SSH 传输层未正常建立。'
        stage_detail = f'目标主机未完成 SSH 会话建立，请检查 {port} 端口、SSH 服务或安全策略。'

    content = {
        'detail': detail,
        'raw_error': friendly_err,
        'output': "\n".join(probe_output + [f"SSH login: failed ({friendly_err})"]),
        'check_mode': 'deep',
        'stages': probe_stages + [
            _build_probe_stage('ssh', False, 'SSH login failed', stage_detail)
        ],
    }
    if error_code:
        content['error_code'] = error_code
        content['guidance'] = build_ssh_error_guidance(error_text)
    return JSONResponse(status_code=status_code, content=content)


def _clean_ssh_error_text(error_text: str) -> str:
    friendly_err = (error_text or '').strip()
    prefix = "A paramiko SSHException occurred during connection creation:"
    if friendly_err.startswith(prefix):
        friendly_err = friendly_err[len(prefix):].strip()
    return friendly_err


def _build_device_operation_ssh_failure_response(
    device_info: dict,
    error_text: str,
    operation: str,
) -> JSONResponse | None:
    """Return a structured 400 response for known SSH dependency failures.

    Operational-data collection and custom read-only commands run through a
    different API path than the connection-test modal, but the user-facing SSH
    failure classes should stay identical. Unknown exceptions intentionally
    return ``None`` so callers can keep surfacing true server defects as 500s.
    """
    error_code = get_ssh_error_code(error_text)
    if not error_code:
        return None

    hostname = device_info.get('hostname') or device_info.get('name') or ''
    ip_address = device_info.get('ip_address') or device_info.get('management_ip') or ''
    device_label = hostname or ip_address or 'device'
    friendly_err = _clean_ssh_error_text(error_text)

    detail_by_code = {
        'legacy_ssh_algorithms': f'{device_label} 的 SSH 算法较旧，兼容重试后仍未完成协商。',
        'ssh_authentication_failed': f'{device_label} 可达，但 SSH 认证被拒绝。请检查账号密码或 AAA/VTY 配置。',
        'ssh_transport_timeout': f'{device_label} 管理地址可达，但 SSH 会话建立或读取超时。',
        'ssh_transport_unreachable': f'{device_label} IP/TCP 可达性检查后，SSH 传输层未正常建立。',
    }

    return JSONResponse(
        status_code=400,
        content={
            'detail': detail_by_code.get(error_code, f'{operation} failed: {friendly_err}'),
            'error_code': error_code,
            'guidance': build_ssh_error_guidance(error_text),
            'raw_error': friendly_err,
            'operation': operation,
            'device': {
                'id': device_info.get('id') or '',
                'hostname': hostname,
                'ip_address': ip_address,
            },
        },
    )


def _resolve_payload_password(value) -> str:
    """Return a plaintext password from request payload without logging secrets."""
    if value in (None, ''):
        return ''
    password = str(value)
    if password.startswith(('enc:v1:', 'enc:v2:')):
        return decrypt_credential(password) or ''
    return password


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
        'port': payload.get('port') or payload.get('management_port'),
    }

    if not device_id:
        resolved['password'] = _resolve_payload_password(resolved.get('password'))
        return resolved

    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail='Device not found')

    stored = dict(row)
    creds = resolve_device_credentials(stored)
    payload_password = payload.get('password')

    resolved['hostname'] = resolved['hostname'] or stored.get('hostname')
    resolved['ip_address'] = resolved['ip_address'] or stored.get('ip_address')
    resolved['username'] = resolved['username'] or creds['username'] or ''
    resolved['method'] = payload.get('method') or stored.get('connection_method') or 'ssh'
    resolved['platform'] = payload.get('platform') or stored.get('platform') or 'cisco_ios'
    payload_plain_password = _resolve_payload_password(payload_password)
    resolved['password'] = payload_plain_password or creds['password']
    resolved['enable_password'] = creds['enable_password']
    resolved['priv_username'] = creds.get('priv_username', '') or stored.get('priv_username') or ''
    resolved['port'] = resolved.get('port') or stored.get('management_port') or stored.get('port')
    return resolved

def _normalize_device_row(row, conn=None):
    item = dict(row)
    from core.platform_utils import normalize_device_platform
    item['platform'] = normalize_device_platform(item.get('vendor'), item.get('platform'))
    try:
        item['config_history'] = json.loads(item.get('config_history', '[]'))
    except Exception:
        item['config_history'] = []

    try:
        item['cpu_history'] = json.loads(item.get('cpu_history', '[]'))
    except Exception:
        item['cpu_history'] = []

    try:
        item['memory_history'] = json.loads(item.get('memory_history', '[]'))
    except Exception:
        item['memory_history'] = []

    # Dynamically build interface_data by querying interfaces and joining the latest telemetry
    opened_here = False
    if conn is None:
        conn = get_db_connection()
        opened_here = True
    try:
        intf_rows = conn.execute('''
            SELECT 
                i.interface_name as name,
                i.description,
                COALESCE(t.status, i.oper_status) as status,
                COALESCE(t.speed_mbps, i.speed / 1000000.0) as speed_mbps,
                COALESCE(t.in_bps, 0.0) as in_bps,
                COALESCE(t.out_bps, 0.0) as out_bps,
                COALESCE(t.bw_in_pct, 0.0) as bw_in_pct,
                COALESCE(t.bw_out_pct, 0.0) as bw_out_pct,
                COALESCE(t.in_pkts, 0) as in_ucast_pkts,
                COALESCE(t.out_pkts, 0) as out_ucast_pkts,
                COALESCE(t.in_errors, 0) as in_errors,
                COALESCE(t.out_errors, 0) as out_errors,
                COALESCE(t.in_discards, 0) as in_discards,
                COALESCE(t.out_discards, 0) as out_discards
            FROM interfaces i
            LEFT JOIN (
                SELECT latest.*
                FROM interface_telemetry_raw latest
                INNER JOIN (
                    SELECT interface_name, MAX(ts) as max_ts
                    FROM interface_telemetry_raw
                    WHERE device_id = ?
                    GROUP BY interface_name
                ) sub ON latest.interface_name = sub.interface_name AND latest.ts = sub.max_ts
                WHERE latest.device_id = ?
            ) t ON i.interface_name = t.interface_name
            WHERE i.device_id = ?
            ORDER BY i.interface_name
        ''', (item['id'], item['id'], item['id'])).fetchall()

        item['interface_data'] = [dict(r) for r in intf_rows]
    except Exception as exc:
        _logger.warning("Failed to fetch interfaces for device %s: %s", item.get('id'), exc)
        item['interface_data'] = []
    finally:
        if opened_here:
            conn.close()

    return _sanitize_device_item(item)


def _annotate_devices_with_tags(conn, items: list) -> list:
    """Attach tag list to each device item."""
    if not items:
        return items
    device_ids = [d['id'] for d in items if d.get('id')]
    if not device_ids:
        return items
    placeholders = ','.join('?' * len(device_ids))
    rows = conn.execute(
        f'''SELECT dt.device_id, td.id, td.category, td.value, td.label, td.label_zh,
                   td.color, td.icon, td.description, td.sort_order, td.built_in
            FROM device_tags dt
            JOIN tag_definitions td ON dt.tag_id = td.id
            WHERE dt.device_id IN ({placeholders})
            ORDER BY td.sort_order''',
        tuple(device_ids)
    ).fetchall()
    tag_map: dict[str, list] = {}
    for r in rows:
        did = r['device_id']
        tag_map.setdefault(did, []).append({
            'id': r['id'], 'category': r['category'], 'value': r['value'],
            'label': r['label'], 'label_zh': r['label_zh'], 'color': r['color'],
            'icon': r['icon'], 'description': r['description'],
            'sort_order': r['sort_order'], 'built_in': r['built_in'],
        })
    for item in items:
        item['tags'] = tag_map.get(item['id'], [])
        item['tag_ids'] = [t['id'] for t in item['tags']]
    return items


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
    page_size: Optional[int] = Query(default=None, ge=1, le=1000),
    asset_type: Optional[str] = Query(default='all'),
):
    conn = get_db_connection()
    try:
        where_clauses = []
        params = []

        if asset_type and asset_type != 'all':
            # Default unlinked devices to 'network_device'
            where_clauses.append("(CASE WHEN pa.asset_type IS NOT NULL THEN pa.asset_type ELSE 'network_device' END) = ?")
            params.append(asset_type)

        if search and search.strip():
            q = f"%{search.strip()}%"
            where_clauses.append('('
                'd.hostname LIKE ? OR d.ip_address LIKE ? OR d.sn LIKE ? OR '
                'pa.asset_tag LIKE ? OR pa.management_ip LIKE ? OR pa.business_ip LIKE ? OR '
                'pa.site_id LIKE ? OR pa.vendor LIKE ? OR pa.model LIKE ?'
                ')')
            params.extend([q, q, q, q, q, q, q, q, q])

        if platform and platform != 'all':
            where_clauses.append('d.platform = ?')
            params.append(platform)

        if role and role != 'all':
            where_clauses.append('LOWER(d.role) LIKE ?')
            params.append(f'%{role.lower()}%')

        if status and status != 'all':
            where_clauses.append('d.status = ?')
            params.append(status)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ''

        sortable_columns = {
            'hostname': 'd.hostname',
            'model': 'd.model',
            'platform': 'd.platform',
            'site': "COALESCE(NULLIF(s.site_name, ''), NULLIF(s.site_code, ''), d.site)",
            'connection_method': 'd.connection_method',
            'status': 'd.status',
            'ip_address': 'd.ip_address',
            'role': 'd.role',
        }
        order_col = sortable_columns.get(sort_key or '', 'd.hostname')
        order_dir = 'DESC' if str(sort_direction).lower() == 'desc' else 'ASC'

        # Plan-A: LEFT JOIN physical_assets to surface asset metadata
        asset_cols = (
            ', pa.asset_tag, pa.site_id AS asset_site_id, pa.rack, pa.rack_unit, '
            'pa.department, pa.warranty_expiry, pa.purchase_date, '
            'pa.business_ip, pa.vlan, pa.uplink_switch, pa.uplink_port, '
            'COALESCE(NULLIF(pa.site_id, \'\'), NULLIF(d.site_id, \'\'), \'\') AS canonical_site_id, '
            's.site_name, s.site_code, s.country AS site_country, '
            's.state_province AS site_state_province, s.city AS site_city, '
            's.district AS site_district, '
            'COALESCE(NULLIF(r.id, \'\'), NULLIF(r_legacy.id, \'\'), \'\') AS cmdb_rack_id, '
            'COALESCE(NULLIF(r.rack_code, \'\'), NULLIF(r_legacy.rack_code, \'\'), \'\') AS rack_code, '
            'COALESCE(NULLIF(r.rack_name, \'\'), NULLIF(r_legacy.rack_name, \'\'), NULLIF(r_legacy.name, \'\'), \'\') AS rack_name, '
            'COALESCE(NULLIF(r.datacenter, \'\'), NULLIF(r_legacy.datacenter, \'\'), \'\') AS rack_datacenter, '
            'COALESCE(NULLIF(r.floor, \'\'), NULLIF(r_legacy.floor, \'\'), \'\') AS rack_floor, '
            'COALESCE(NULLIF(r.room, \'\'), NULLIF(r_legacy.room, \'\'), \'\') AS rack_room, '
            'COALESCE(NULLIF(r.row, \'\'), NULLIF(r_legacy.row, \'\'), \'\') AS rack_row'
        )
        from_clause = (
            'FROM devices d '
            'LEFT JOIN physical_assets pa ON d.asset_id = pa.id '
            "LEFT JOIN sites s ON s.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, '')) "
            'LEFT JOIN rack_devices rd ON rd.asset_id = pa.id '
            'LEFT JOIN racks r ON r.id = COALESCE(NULLIF(d.rack_id, \'\'), NULLIF(rd.rack_id, \'\')) '
            "LEFT JOIN racks r_legacy ON NULLIF(pa.rack, '') IS NOT NULL "
            "AND r_legacy.site_id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, '')) "
            'AND (r_legacy.rack_code = pa.rack OR r_legacy.rack_name = pa.rack OR r_legacy.name = pa.rack)'
        )

        select_clause = f'd.*{asset_cols}'
        if str(mode).lower() == 'light':
            # Lightweight projection for high-frequency polling.
            select_clause = (
                'd.id, d.hostname, d.ip_address, d.platform, d.status, d.compliance, d.sn, d.model, d.version, '
                'd.role, d.site, d.uptime, d.connection_method, d.cpu_usage, d.memory_usage, d.temp, '
                'd.site_id, d.fan_status, d.psu_status, d.sys_name, d.sys_location, d.sys_contact, d.asset_id, d.vendor, '
                'd.device_category, d.management_port'
                + asset_cols
            )

        # Backward-compatible mode: no pagination params -> return array.
        # Safety cap: never return more than 200 rows without explicit pagination to prevent UI hangs.
        if page is None or page_size is None:
            devices = conn.execute(
                f'SELECT {select_clause} {from_clause} {where_sql} ORDER BY {order_col} {order_dir} LIMIT 200',
                tuple(params)
            ).fetchall()
            items = [_sanitize_device_item(dict(d)) for d in devices] if str(mode).lower() == 'light' else [_normalize_device_row(d, conn) for d in devices]
            return annotate_devices_with_health(conn, _annotate_devices_with_tags(conn, items))

        total_row = conn.execute(
            f'SELECT COUNT(*) AS count {from_clause} {where_sql}',
            tuple(params)
        ).fetchone()
        total = int(total_row['count']) if total_row else 0

        # Status counts across full filtered set (not just current page)
        status_count_rows = conn.execute(
            f'SELECT d.status, COUNT(*) AS cnt {from_clause} {where_sql} GROUP BY d.status',
            tuple(params)
        ).fetchall()
        status_counts = {r['status']: r['cnt'] for r in status_count_rows}

        offset = (page - 1) * page_size
        devices = conn.execute(
            f'SELECT {select_clause} {from_clause} {where_sql} ORDER BY {order_col} {order_dir} LIMIT ? OFFSET ?',
            tuple([*params, page_size, offset])
        ).fetchall()

        items = [_sanitize_device_item(dict(d)) for d in devices] if str(mode).lower() == 'light' else [_normalize_device_row(d, conn) for d in devices]

        return {
            'items': annotate_devices_with_health(conn, _annotate_devices_with_tags(conn, items)),
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
    cred_source = (device.get('credential_source') or 'local').lower()
    vault_path = device.get('vault_path', '')

    credential_id = ''
    if cred_source == 'vault' and vault_available() and vault_path:
        vault_write(vault_path, {
            'username': device.get('username', ''),
            'password': device.get('password', ''),
            'enable_password': device.get('enable_password', ''),
            'priv_username': device.get('priv_username', ''),
            'normal_username': device.get('normal_username', ''),
            'normal_password': device.get('normal_password', ''),
            'admin_username': device.get('admin_username', ''),
            'admin_password': device.get('admin_password', ''),
            'snmp_community': device.get('snmp_community', ''),
        })
    else:
        credential_id = f"cred-{uuid.uuid4().hex[:12]}"
        cred_name = f"cred-{device.get('hostname')}-{device_id[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        
        username = device.get('username') or device.get('normal_username') or device.get('admin_username') or ''
        raw_pwd = device.get('password') or device.get('normal_password') or device.get('admin_password') or ''
        enc_pwd = encrypt_credential(raw_pwd) if raw_pwd else ''
        enc_enable = encrypt_credential(device.get('enable_password')) if device.get('enable_password') else ''
        enc_snmp = encrypt_credential(device.get('snmp_community')) if device.get('snmp_community') else ''
        
        try:
            conn.execute('''
                INSERT INTO credentials (id, credential_name, credential_type, username, encrypted_password, enable_password, snmp_community, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (credential_id, cred_name, 'ssh_password', username, enc_pwd, enc_enable, enc_snmp, now))
        except Exception as exc:
            _logger.error("Failed to create credential row: %s", exc)

    try:
        conn.execute('''
            INSERT INTO devices (
                id, hostname, ip_address, platform, status, compliance, username, password, 
                sn, model, version, role, site, uptime, connection_method, snmp_community, 
                snmp_port, lifecycle_status, enable_password, priv_username, credential_source, 
                vault_path, normal_username, normal_password, admin_username, admin_password, auth_model,
                device_category, power_watts, credential_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            device_id,
            device.get('hostname'),
            device.get('ip_address'),
            device.get('platform'),
            device.get('status', 'pending'),
            device.get('compliance', 'unknown'),
            device.get('username'),
            '', # Store empty password in devices table
            device.get('sn', ''),
            device.get('model', ''),
            device.get('version', ''),
            device.get('role', ''),
            device.get('site', ''),
            device.get('uptime', '0d 0h'),
            device.get('connection_method', 'ssh'),
            '', # SNMP community is stored only in the credential backend
            device.get('snmp_port', 161),
            device.get('lifecycle_status', 'staging'),
            '', # Store empty enable_password in devices table
            device.get('priv_username', ''),
            cred_source,
            vault_path,
            device.get('normal_username', ''),
            '', # Store empty normal_password in devices table
            device.get('admin_username', ''),
            '', # Store empty admin_password in devices table
            device.get('auth_model', 'single'),
            device.get('device_category', ''),
            int(device.get('power_watts') or 0),
            credential_id
        ))
        conn.execute(
            'UPDATE devices SET site_id = ? WHERE id = ?',
            (_resolve_device_site_id(conn, device.get('site_id'), device.get('site')), device_id),
        )
        tag_service.sync_device_status_tag(conn, device_id, device.get('status', 'pending'))
        # Plan-A: auto-create linked physical_assets record
        _create_linked_asset_for_device(conn, device_id, device)
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
        row = conn.execute('SELECT hostname, asset_id, credential_id FROM devices WHERE id = ?', (device_id,)).fetchone()
        # Plan-A: cascade-delete linked asset
        if row and row['asset_id']:
            # PAM: archive (don't delete) sessions and access requests so the
            # audit trail survives device removal. The FK on pam_sessions.asset_id
            # is configured ON DELETE SET NULL (PG) so the column itself is
            # nulled when physical_assets is deleted below. Tokens are
            # short-lived and have no audit value, so they are hard-deleted.
            now_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')
            conn.execute(
                "UPDATE pam_sessions SET archived = 1, updated_at = ? WHERE asset_id = ?",
                (now_iso, row['asset_id']),
            )
            conn.execute(
                "UPDATE pam_access_requests SET updated_at = ? WHERE asset_id = ?",
                (now_iso, row['asset_id']),
            )
            conn.execute('DELETE FROM pam_session_tokens WHERE asset_id = ?', (row['asset_id'],))
            conn.execute('DELETE FROM physical_assets WHERE id = ?', (row['asset_id'],))
        # Remove many-to-many tag associations before deleting the device row.
        # The FK is not cascade-enabled on older PostgreSQL installations.
        conn.execute('DELETE FROM device_tags WHERE device_id = ?', (device_id,))
        conn.execute('DELETE FROM devices WHERE id = ?', (device_id,))
        if row and row['credential_id']:
            other = conn.execute('SELECT 1 FROM devices WHERE credential_id = ?', (row['credential_id'],)).fetchone()
            if not other:
                conn.execute('DELETE FROM credentials WHERE id = ?', (row['credential_id'],))
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
        existing_row = conn.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
        if not existing_row:
            raise HTTPException(status_code=404, detail='Device not found')

        cred_source = (device.get('credential_source') or existing_row['credential_source'] or 'local').lower()
        vault_path = device.get('vault_path', '')

        submitted_password = device.get('password')
        submitted_enable = device.get('enable_password')
        submitted_normal = device.get('normal_password')
        submitted_admin = device.get('admin_password')
        submitted_snmp = device.get('snmp_community')

        credential_id = existing_row['credential_id'] or ''

        if cred_source == 'vault' and vault_available() and vault_path:
            # Push credentials to Vault; store empty in DB
            existing_credentials = resolve_device_credentials(dict(existing_row))
            vault_write(vault_path, {
                'username': device.get('username') or existing_credentials.get('username', ''),
                'password': submitted_password or existing_credentials.get('password', ''),
                'enable_password': submitted_enable or existing_credentials.get('enable_password', ''),
                'priv_username': device.get('priv_username') or existing_credentials.get('priv_username', ''),
                'normal_username': device.get('normal_username') or existing_credentials.get('normal_username', ''),
                'normal_password': submitted_normal or existing_credentials.get('normal_password', ''),
                'admin_username': device.get('admin_username') or existing_credentials.get('admin_username', ''),
                'admin_password': submitted_admin or existing_credentials.get('admin_password', ''),
                'snmp_community': submitted_snmp or existing_credentials.get('snmp_community', ''),
            })
        else:
            username = device.get('username') or device.get('normal_username') or device.get('admin_username') or ''
            raw_pwd = submitted_password or submitted_normal or submitted_admin
            enc_pwd = encrypt_credential(raw_pwd) if raw_pwd else ''
            enc_enable = encrypt_credential(submitted_enable) if submitted_enable else ''
            enc_snmp = encrypt_credential(submitted_snmp) if submitted_snmp else ''

            if credential_id:
                # Update existing credentials
                cred_row = conn.execute('SELECT username, encrypted_password, enable_password, snmp_community FROM credentials WHERE id = ?', (credential_id,)).fetchone()
                
                stored_username = username if username else (cred_row['username'] if cred_row else '')
                stored_password = enc_pwd if submitted_password not in (None, '') else (cred_row['encrypted_password'] if cred_row else '')
                stored_enable = enc_enable if submitted_enable not in (None, '') else (cred_row['enable_password'] if cred_row else '')
                stored_snmp = enc_snmp if submitted_snmp not in (None, '') else (cred_row['snmp_community'] if cred_row else '')

                conn.execute('''
                    UPDATE credentials
                    SET username = ?, encrypted_password = ?, enable_password = ?, snmp_community = ?
                    WHERE id = ?
                ''', (stored_username, stored_password, stored_enable, stored_snmp, credential_id))
            else:
                # Create credentials
                credential_id = f"cred-{uuid.uuid4().hex[:12]}"
                cred_name = f"cred-{device.get('hostname', device_id)}-{device_id[:8]}"
                now = datetime.now(timezone.utc).isoformat()
                conn.execute('''
                    INSERT INTO credentials (id, credential_name, credential_type, username, encrypted_password, enable_password, snmp_community, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (credential_id, cred_name, 'ssh_password', username, enc_pwd, enc_enable, enc_snmp, now))

        new_lifecycle = device.get('lifecycle_status') or existing_row['lifecycle_status'] or 'staging'

        conn.execute('''
            UPDATE devices 
            SET hostname = ?, ip_address = ?, platform = ?, sn = ?, model = ?, version = ?, role = ?, site = ?, connection_method = ?, 
                username = ?, password = ?, current_config = ?, config_history = ?, snmp_community = ?, snmp_port = ?, 
                lifecycle_status = ?, enable_password = ?, priv_username = ?, credential_source = ?, vault_path = ?,
                normal_username = ?, normal_password = ?, admin_username = ?, admin_password = ?, auth_model = ?,
                device_category = ?, power_watts = ?, credential_id = ?
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
            '', # Empty password column
            device.get('current_config', ''),
            json.dumps(device.get('config_history', [])) if device.get('config_history') else '[]',
            '', # SNMP community is stored only in the credential backend
            device.get('snmp_port', 161),
            new_lifecycle,
            '', # Empty enable_password column
            device.get('priv_username', ''),
            cred_source,
            vault_path,
            device.get('normal_username', ''),
            '', # Empty normal_password column
            device.get('admin_username', ''),
            '', # Empty admin_password column
            device.get('auth_model', 'single'),
            device.get('device_category', ''),
            int(device.get('power_watts') or 0),
            credential_id,
            device_id
        ))
        conn.execute(
            'UPDATE devices SET site_id = ? WHERE id = ?',
            (_resolve_device_site_id(conn, device.get('site_id'), device.get('site')), device_id),
        )
        conn.commit()

        # Track lifecycle transition in audit details
        old_lifecycle = existing_row['lifecycle_status'] or 'staging'
        audit_details: dict = {'ip_address': device.get('ip_address'), 'platform': device.get('platform')}
        if old_lifecycle != new_lifecycle:
            audit_details['lifecycle_transition'] = f"{old_lifecycle} → {new_lifecycle}"

        log_audit_event(
            event_type='DEVICE_UPDATE',
            category='inventory',
            severity='high' if new_lifecycle == 'production' and old_lifecycle != 'production' else 'medium',
            status='success',
            summary=f"Updated device {device.get('hostname', device_id)}" + (f" [lifecycle: {old_lifecycle} → {new_lifecycle}]" if old_lifecycle != new_lifecycle else ''),
            actor_username=device.get('actor_username') or 'admin',
            actor_role=device.get('actor_role') or 'Administrator',
            target_type='device',
            target_id=device_id,
            target_name=device.get('hostname', device_id),
            device_id=device_id,
            details=audit_details,
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ──────────────────────────────────────────────
# 口令上手 / Device Onboarding State Machine
# ──────────────────────────────────────────────
# States: pending_credentials → credentials_set → verified → active
# Transitions:
#   pending_credentials → credentials_set  (user supplies credentials)
#   credentials_set     → verified         (connectivity test passes)
#   credentials_set     → pending_credentials (reset / credential fix)
#   verified            → active           (promote to operational)
#   any                 → pending_credentials (reset)

_ONBOARDING_TRANSITIONS: dict[str, set[str]] = {
    'pending_credentials': {'credentials_set'},
    'credentials_set':     {'verified', 'pending_credentials'},
    'verified':            {'active', 'pending_credentials'},
    'active':              {'pending_credentials'},   # allow re-onboard
}


@router.post("/devices/{device_id}/onboard")
def device_onboard(device_id: str, payload: dict = Body(...)):
    """
    Progress device through the onboarding state machine.
    Body:
      action: 'set_credentials' | 'verify' | 'activate' | 'reset'
      username, password, enable_password, priv_username (for set_credentials)
    """
    action = payload.get('action', '')
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT id, hostname, ip_address, platform, onboarding_status, credential_source, vault_path FROM devices WHERE id = ?',
            (device_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Device not found')
        device = dict(row)
        current = device.get('onboarding_status') or 'active'

        if action == 'set_credentials':
            target = 'credentials_set'
        elif action == 'verify':
            target = 'verified'
        elif action == 'activate':
            target = 'active'
        elif action == 'reset':
            target = 'pending_credentials'
        else:
            raise HTTPException(status_code=400, detail=f'Unknown onboarding action: {action}')

        # Validate transition
        allowed = _ONBOARDING_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot transition from '{current}' → '{target}'. Allowed: {sorted(allowed)}"
            )

        now = _utc_now()

        # Action-specific logic
        if action == 'set_credentials':
            cred_source = (payload.get('credential_source') or device.get('credential_source') or 'local').lower()
            vault_path = payload.get('vault_path') or device.get('vault_path') or ''
            raw_password = payload.get('password', '')
            raw_enable = payload.get('enable_password', '')

            credential_id = device.get('credential_id') or ''

            if cred_source == 'vault' and vault_available() and vault_path:
                vault_write(vault_path, {
                    'username': payload.get('username', ''),
                    'password': raw_password,
                    'enable_password': raw_enable,
                    'priv_username': payload.get('priv_username', ''),
                })
            else:
                enc_pwd = encrypt_credential(raw_password) if raw_password else ''
                enc_enable = encrypt_credential(raw_enable) if raw_enable else ''
                username = payload.get('username') or device.get('username') or ''

                if credential_id:
                    # Update credentials
                    cred_row = conn.execute('SELECT username, encrypted_password, enable_password FROM credentials WHERE id = ?', (credential_id,)).fetchone()
                    stored_username = username if username else (cred_row['username'] if cred_row else '')
                    stored_password = enc_pwd if raw_password else (cred_row['encrypted_password'] if cred_row else '')
                    stored_enable = enc_enable if raw_enable else (cred_row['enable_password'] if cred_row else '')

                    conn.execute('''
                        UPDATE credentials
                        SET username = ?, encrypted_password = ?, enable_password = ?
                        WHERE id = ?
                    ''', (stored_username, stored_password, stored_enable, credential_id))
                else:
                    # Create credentials
                    credential_id = f"cred-{uuid.uuid4().hex[:12]}"
                    cred_name = f"cred-{device.get('hostname', device_id)}-{device_id[:8]}"
                    now_time = datetime.now(timezone.utc).isoformat()
                    conn.execute('''
                        INSERT INTO credentials (id, credential_name, credential_type, username, encrypted_password, enable_password, snmp_community, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (credential_id, cred_name, 'ssh_password', username, enc_pwd, enc_enable, '', now_time))

            conn.execute(
                'UPDATE devices SET username = ?, password = ?, enable_password = ?, priv_username = ?, '
                'credential_source = ?, vault_path = ?, onboarding_status = ?, onboarding_updated_at = ?, credential_id = ? WHERE id = ?',
                (
                    payload.get('username', ''),
                    '', # Clear devices.password
                    '', # Clear devices.enable_password
                    payload.get('priv_username', ''),
                    cred_source,
                    vault_path,
                    target,
                    now,
                    credential_id,
                    device_id,
                )
            )
        elif action == 'verify':
            # Run a quick connectivity test
            from services.automation_service import AutomationService
            svc = AutomationService()
            stored = conn.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
            creds = resolve_device_credentials(dict(stored))
            try:
                test_ok = svc.test_connectivity(
                    ip_address=stored['ip_address'],
                    username=creds['username'],
                    password=creds['password'],
                    platform=stored['platform'] or 'cisco_ios',
                )
            except Exception as exc:
                _logger.warning("Onboard verify failed for %s: %s", device_id, exc)
                test_ok = False
            if not test_ok:
                raise HTTPException(status_code=422, detail='Connectivity verification failed')
            conn.execute(
                'UPDATE devices SET onboarding_status = ?, onboarding_updated_at = ? WHERE id = ?',
                (target, now, device_id)
            )
        elif action == 'activate':
            conn.execute(
                "UPDATE devices SET onboarding_status = ?, onboarding_updated_at = ?, status = 'online' WHERE id = ?",
                (target, now, device_id)
            )
            tag_service.sync_device_status_tag(conn, device_id, 'online')
        elif action == 'reset':
            conn.execute(
                'UPDATE devices SET onboarding_status = ?, onboarding_updated_at = ? WHERE id = ?',
                (target, now, device_id)
            )

        conn.commit()

        log_audit_event(
            event_type='DEVICE_ONBOARD',
            category='inventory',
            severity='medium',
            status='success',
            summary=f"Onboard {device.get('hostname', device_id)}: {current} → {target}",
            actor_username=payload.get('actor_username') or 'admin',
            actor_role=payload.get('actor_role') or 'Administrator',
            target_type='device',
            target_id=device_id,
            target_name=device.get('hostname', device_id),
            device_id=device_id,
        )

        return {"status": "success", "onboarding_status": target}
    except HTTPException:
        raise
    except Exception as e:
        _logger.exception("Onboard action failed")
        raise HTTPException(status_code=500, detail="服务内部异常，请联系管理员查看后端日志")
    finally:
        conn.close()
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


# ──────────────────────────────────────────────
# Password Rotation Endpoints
# ──────────────────────────────────────────────

@router.get("/devices/rotation/status")
def rotation_status(user=require_role("Administrator")):
    """密码轮换状态概览（仅管理员）。"""
    from services.password_rotation_service import get_rotation_status
    return {"success": True, "data": get_rotation_status()}


@router.get("/devices/rotation/expiring")
def rotation_expiring(days: int = Query(default=14), user=require_role("Administrator")):
    """即将过期的设备列表（仅管理员）。"""
    from services.password_rotation_service import check_expiring
    return {"success": True, "data": check_expiring(days_ahead=days)}


@router.post("/devices/{device_id}/rotate-password")
def rotate_device_password(device_id: str, role: str = Query(default='admin'), user: dict = require_role("Administrator")):
    """手动触发单台设备指定角色的密码轮换（仅管理员）。"""
    from services.password_rotation_service import rotate_password
    result = rotate_password(device_id, role=role)
    if result['success']:
        log_audit_event(
            event_type='PASSWORD_ROTATE',
            category='security',
            severity='high',
            status='success',
            summary=result.get('message', ''),
            actor_username=user.get('username', 'admin'),
            actor_role=user.get('role', 'Administrator'),
            target_type='device',
            target_id=device_id,
            device_id=device_id,
        )
        return {"success": True, "data": result}
    else:
        # Log failure audit
        log_audit_event(
            event_type='PASSWORD_ROTATE',
            category='security',
            severity='high',
            status='failure',
            summary=result.get('message', ''),
            actor_username=user.get('username', 'admin'),
            actor_role=user.get('role', 'Administrator'),
            target_type='device',
            target_id=device_id,
            device_id=device_id,
        )
        # Fix: Don't raise 422, return success: False with detail
        return {"success": False, "message": result.get('message', 'Rotation failed')}


@router.post("/devices/rotation/rotate-all")
def rotate_all_passwords(role: str = Query(default='admin'), user=require_role("Administrator")):
    """一键轮换所有在册设备的指定角色密码（后台执行，返回 run_id 供轮询进度）。"""
    from services.password_rotation_service import start_rotation_all
    run_id = start_rotation_all(role=role)
    log_audit_event(
        event_type='PASSWORD_ROTATE_ALL',
        category='security',
        severity='high',
        status='success',
        summary=f'Bulk password rotation started (role={role})',
        actor_username=user.get('username', 'admin'),
        actor_role=user.get('role', 'Administrator'),
        target_type='device',
        target_id='*',
    )
    return {"success": True, "data": {"run_id": run_id}}


@router.get("/devices/rotation/rotate-all/{run_id}/progress")
def rotate_all_progress(run_id: str, user=require_role("Administrator")):
    """查询一键轮换的实时进度。"""
    from services.password_rotation_service import get_rotate_all_progress
    prog = get_rotate_all_progress(run_id)
    if not prog:
        return {"success": False, "message": "run not found"}
    return {"success": True, "data": prog}


@router.get("/devices/{device_id}/reveal-password")
def reveal_device_password(device_id: str, role: str = Query(default='admin'), user: dict = require_role("Administrator")):
    """解密并返回设备指定角色的当前密码（仅管理员，审计记录）。"""
    from core.crypto import decrypt_credential
    conn = get_db_connection()
    try:
        # Map role to column name
        col_map = {
            'normal': 'normal_password',
            'admin': 'admin_password',
            'enable': 'enable_password'
        }
        target_col = col_map.get(role)
        if not target_col:
             return {"success": False, "message": f"无效的角色类型: {role}"}
        
        row = conn.execute(
            f'SELECT hostname, ip_address, {target_col} as target_pwd FROM devices WHERE id = ?',
            (device_id,),
        ).fetchone()
        if not row:
            return {"success": False, "message": "设备不存在"}
        
        pwd_to_decrypt = row['target_pwd']
        
        if not pwd_to_decrypt:
            return {"success": False, "message": f"该角色 ({role}) 尚未设置或轮换密码"}

        decrypted = decrypt_credential(pwd_to_decrypt)
        if decrypted is None:
            return {"success": False, "message": "密码解密失败，可能密钥不匹配"}
        log_audit_event(
            event_type='PASSWORD_REVEAL',
            category='security',
            severity='high',
            status='success',
            summary=f"管理员查看了设备 {row['hostname']} 的 {role} 账号明文密码",
            actor_username=user.get('username', 'admin'),
            actor_role=user.get('role', 'Administrator'),
            target_type='device',
            target_id=device_id,
            device_id=device_id,
        )
        return {"success": True, "data": {"password": decrypted, "role": role}}
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
    
    logger.info(
        "DEBUG CONNECT TARGET: hostname=%s, user=%s, pwd_present=%s, pwd_len=%s",
        hostname,
        username,
        bool(password),
        len(password or ''),
    )
    
    if not ip_address:
        raise HTTPException(status_code=400, detail="IP address is required")
    
    port = resolved.get('port')
    if not port:
        port = 22
        if method and method.lower() == 'telnet':
            port = 23
    else:
        try:
            port = int(port)
        except (ValueError, TypeError):
            port = 22
    
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
            return _build_ssh_failure_response(hostname, ip_address, error_msg, probe_output, probe_stages, status_code=400, port=port)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Connection error for {hostname or ip_address}: {str(e)}", exc_info=True)
        raw_error = str(e)
        error_code = get_ssh_error_code(raw_error)
        # 对于能识别的 SSH 错误，返回结构化用户友好响应
        if error_code:
            return _build_ssh_failure_response(hostname, ip_address, raw_error, probe_output, probe_stages, status_code=500, port=port)
        # 对于不能识别的错误（如 AttributeError、ImportError 等内部代码错误），
        # 不要将原始 Python 异常暴露给前端，返回通用的内部错误提示
        user_message = "服务内部异常，请联系管理员查看后端日志"
        return _build_ssh_failure_response(hostname, ip_address, user_message, probe_output, probe_stages, status_code=500, port=port)

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
            tag_service.sync_device_status_tag(conn, device_id, device.get('status', 'pending'))
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

    device_data = dict(device)
    credentials = resolve_device_credentials(device_data)
    ip = device_data['ip_address']
    community = credentials.get('snmp_community') or ''
    port = device_data['snmp_port'] or 161

    if not ip:
        return {"success": False, "error": "No IP address configured"}
    if not community:
        from services.collection_status_service import record_collection_result
        record_collection_result(
            device_id,
            'snmp_metrics',
            status='not_configured',
            transport='udp',
            source='snmp',
            error_code='snmp_not_configured',
            error_message='SNMP credentials are not configured',
        )
        return {
            "success": False,
            "error": "SNMP credentials are not configured",
            "error_code": "snmp_not_configured",
        }

    import asyncio as _aio
    from services.snmp_service import _snmp_get, _snmp_walk, collect_device_info, collect_interface_data, collect_device_metrics

    results = {"success": False, "ip": ip, "port": port,
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

    from services.collection_status_service import record_collection_result
    record_collection_result(
        device_id,
        'snmp_metrics',
        status='success' if results['success'] else 'failed',
        transport='udp',
        source='snmp',
        duration_ms=results.get('response_ms'),
        coverage_total=2,
        coverage_supported=int(bool(results.get('sys_name'))) + int(bool(results.get('sys_descr'))),
        error_code='' if results['success'] else 'snmp_no_response',
        error_message='' if results['success'] else str(results.get('error') or 'No SNMP response'),
    )

    # ── 测试成功后在后台异步同步数据（不阻塞响应） ──────────────────────
    if results['success']:
        async def _background_sync():
            try:
                platform = device['platform'] or 'cisco_ios'
                dev_info, intf_data, metrics = await _aio.gather(
                    collect_device_info(ip, community, port),
                    collect_interface_data(ip, community, port),
                    collect_device_metrics(ip, platform, community, port),
                )

                updates: dict = {}

                if dev_info.get('sys_name'):
                    updates['sys_name'] = dev_info['sys_name']
                if dev_info.get('sys_descr'):
                    descr = dev_info['sys_descr']
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

                conn2 = get_db_connection()
                try:
                    if updates:
                        set_clause = ', '.join(f'{k} = ?' for k in updates)
                        conn2.execute(f'UPDATE devices SET {set_clause} WHERE id = ?',
                                      (*updates.values(), device_id))
                    
                    if intf_data:
                        for iface in intf_data:
                            iname = iface['name']
                            desc = iface.get('description', '')
                            status = iface.get('status', 'down')
                            speed_mbps = float(iface.get('speed_mbps') or 0.0)
                            speed_bps = speed_mbps * 1_000_000.0
                            
                            conn2.execute('''
                                INSERT INTO interfaces (
                                    id, device_id, interface_name, description, admin_status, oper_status,
                                    mac_address, speed, bandwidth, duplex, interface_type, switchport_mode, ip_enabled
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(device_id, interface_name) DO UPDATE SET
                                    description = excluded.description,
                                    admin_status = excluded.admin_status,
                                    oper_status = excluded.oper_status,
                                    speed = excluded.speed,
                                    bandwidth = excluded.bandwidth
                            ''', (f"intf-{uuid.uuid4().hex[:12]}", device_id, iname, desc, status, status, '', speed_bps, speed_bps, 'auto', 'physical', 'access', 0))
                    conn2.commit()
                finally:
                    conn2.close()
                record_collection_result(
                    device_id,
                    'snmp_interfaces',
                    status='success' if intf_data else 'failed',
                    transport='udp',
                    source='snmp',
                    coverage_total=len(intf_data or []),
                    coverage_supported=len(intf_data or []),
                    error_code='' if intf_data else 'snmp_interface_table_empty',
                    error_message='' if intf_data else 'SNMP interface table is empty',
                )
            except Exception:
                pass  # 后台同步失败不影响测试结果

        _aio.create_task(_background_sync())

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

    categories = payload.get('categories') if isinstance(payload, dict) else None
    auth_role = payload.get('auth_role', 'auto') if isinstance(payload, dict) else 'auto'
    query_name = payload.get('name') or f"Quick Query: {', '.join(categories or [])}"

    try:
        res = collect_operational_data(device_info, categories=categories, auth_role=auth_role)
        _record_instant_execution(
            device_id, query_name, [], 'completed',
            platform=device_info.get('platform', 'unknown'),
            result_payload=res,
            device_info=device_info,
        )
        return res
    except ValueError as exc:
        _record_instant_execution(
            device_id, query_name, [], 'failed',
            platform=device_info.get('platform', 'unknown'),
            error=str(exc), device_info=device_info,
        )
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _record_instant_execution(
            device_id, query_name, [], 'failed',
            platform=device_info.get('platform', 'unknown'),
            error=str(exc), device_info=device_info,
        )
        ssh_failure_response = _build_device_operation_ssh_failure_response(
            device_info,
            str(exc),
            'operational-data',
        )
        if ssh_failure_response:
            return ssh_failure_response
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

    command = payload.get('command') if isinstance(payload, dict) else None
    if not command:
        raise HTTPException(status_code=400, detail="Command is required")

    commands = [line.strip() for line in str(command).splitlines() if line.strip()]
    
    platform = str(device_info.get('platform') or '').lower()
    category = str(device_info.get('device_category') or '').lower()
    is_server = any(t in platform for t in ('linux', 'ubuntu', 'centos', 'debian', 'redhat', 'server')) or category == 'server'

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
        raise HTTPException(status_code=403, detail="查询模式下只允许执行只读查询命令（如 show, display, ping 等）。如需修改配置，请走工单流程或通过配置模板下发！")

    auth_role = payload.get('auth_role', 'auto') if isinstance(payload, dict) else 'auto'
    query_name = payload.get('name') or "Custom Command Query"

    try:
        res = collect_custom_command_data(device_info, command=command, auth_role=auth_role)
        _record_instant_execution(
            device_id, query_name, [command] if command else [], 'completed',
            platform=device_info.get('platform', 'unknown'),
            result_payload=res, device_info=device_info,
        )
        return res
    except ValueError as exc:
        _record_instant_execution(
            device_id, query_name, [command] if command else [], 'failed',
            platform=device_info.get('platform', 'unknown'),
            error=str(exc), device_info=device_info,
        )
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _record_instant_execution(
            device_id, query_name, [command] if command else [], 'failed',
            platform=device_info.get('platform', 'unknown'),
            error=str(exc), device_info=device_info,
        )
        ssh_failure_response = _build_device_operation_ssh_failure_response(
            device_info,
            str(exc),
            'parsed-command',
        )
        if ssh_failure_response:
            return ssh_failure_response
        raise HTTPException(status_code=500, detail=f'Parsed command execution failed: {exc}')
