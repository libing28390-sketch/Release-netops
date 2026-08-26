from fastapi import APIRouter, HTTPException, Body, Query, Depends, File, UploadFile, BackgroundTasks
from fastapi.responses import JSONResponse
import os
import uuid
import json
import re
import socket
import time
import logging
from typing import Any, Optional
from database import get_db_connection
from services.audit_service import log_audit_event
from services.device_health_service import annotate_devices_with_health, normalize_hardware_status
from services.site_identity_service import canonical_site_name
from services.operational_data_service import collect_operational_data, collect_custom_command_data
from services.platform_identification_service import _canonical_vendor
from services import tag_service
from core.crypto import encrypt_credential, decrypt_credential
from core.config import settings
from core.rbac import require_role
from services.vault_service import resolve_device_credentials, resolve_collector_credentials, write_credentials as vault_write, vault_available
from services.snmp_service import collect_device_metrics, normalize_metric_oid
from services.snmp_mib_service import (
    list_mibs_page,
    get_mib_repository_stats,
    get_mib_detail,
    delete_mib,
    parse_and_store_mib,
    parse_and_store_zip,
    extract_mib_archive_to_repo,
    search_mib_nodes,
    SUPPORTED_MIB_FILE_SUFFIXES,
)
from services.librenms_mib_service import (
    fetch_librenms_mibs,
    import_mibs_from_directory,
    MIBS_DIR,
    TARGET_DIR,
)
from services.snmp_preset_service import (
    list_preset_profiles,
    seed_builtin_mibs,
    reset_builtin_mibs,
    match_profile_for_model,
)
from services.snmp_metric_profile_service import (
    apply_official_model_preset,
    bind_model_metric_profile,
    create_model_metric_profile,
    delete_model_metric_profile,
    get_model_metric_profile_mapping,
    list_model_metric_profile_devices,
    list_model_metric_profiles_page,
    mark_model_metric_profile_test,
    normalize_model_key,
    normalize_vendor_key,
    profile_interface_config,
    profile_metric_definitions,
    HEALTH_METRIC_KEYS,
    validate_metric_definitions,
    SUPPORTED_METRIC_KEYS,
    annotate_devices_with_snmp_profile,
    resolve_health_metric_profiles,
    unbind_model_metric_profile,
    update_model_metric_profile,
)
from drivers.ssh_compat import build_ssh_error_guidance, get_ssh_error_code
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)
logger = _logger


def _normalize_device_metric_oid(value: object, field_name: str) -> str:
    """Validate an optional device-level CPU/memory metric OID."""
    try:
        return normalize_metric_oid(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f'{field_name}: {exc}') from exc


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
    if 'ruijie' in p or 'rgos' in p:
        return 'Ruijie'
    if 'zte' in p or 'zxros' in p or 'rosng' in p:
        return 'ZTE'
    if 'maipu' in p or 'mypower' in p:
        return 'Maipu'
    if 'dptech' in p or 'conplat' in p:
        return 'DPTech'
    if 'raisecom' in p or 'ros' in p:
        return 'Raisecom'
    return ''


def _resolve_platform_binding(
    conn,
    platform_profile_id: object,
    fallback_platform: object,
    *,
    existing: dict | None = None,
    clear_existing: bool = False,
    device_vendor: object = None,
) -> tuple[str, str, str, int]:
    """Resolve a concrete registry profile while keeping legacy device writes valid.

    ``platform`` is the device-facing platform code used by older consumers;
    ``platform_profile_id`` is the concrete product/version identity from the
    platform registry.  The form submits both when a registry profile is
    selected, so the backend must make the profile code authoritative and
    persist the binding atomically with the device row.
    """
    existing_profile_id = str(existing.get('platform_profile_id') or '').strip() if existing is not None else ''
    submitted_profile_id = str(platform_profile_id or '').strip()
    if existing_profile_id:
        if submitted_profile_id and submitted_profile_id != existing_profile_id:
            raise HTTPException(
                status_code=409,
                detail='Device platform binding is immutable after first assignment',
            )
        if not submitted_profile_id and not clear_existing:
            platform_profile_id = existing_profile_id
        elif submitted_profile_id:
            platform_profile_id = submitted_profile_id

    submitted = platform_profile_id
    if not submitted and existing is not None and not clear_existing:
        submitted = existing.get('platform_profile_id')

    profile_id = str(submitted or '').strip()
    if profile_id:
        profile = conn.execute(
            'SELECT id, platform_code, vendor, status FROM platform_profiles WHERE id = ?',
            (profile_id,),
        ).fetchone()
        if not profile:
            raise HTTPException(status_code=400, detail='Platform profile not found')
        if str(profile['status'] or '').upper() == 'ARCHIVED':
            raise HTTPException(status_code=400, detail='Archived platform profiles cannot be assigned to devices')
        resolved_device_vendor = _canonical_vendor(device_vendor) or _canonical_vendor(fallback_platform)
        profile_vendor = profile['vendor'] if hasattr(profile, 'keys') and 'vendor' in profile.keys() else ''
        target_vendor = _canonical_vendor(profile_vendor)
        if resolved_device_vendor and target_vendor and resolved_device_vendor != target_vendor:
            raise HTTPException(
                status_code=409,
                detail='Device vendor and target platform vendor must match',
            )
        if existing_profile_id:
            return (
                str(profile['platform_code']),
                profile_id,
                str(existing.get('platform_source') or 'MANUAL'),
                int(existing.get('platform_locked') or 0),
            )
        return str(profile['platform_code']), profile_id, 'MANUAL', 0

    platform = str(fallback_platform or '').strip() or 'cisco_ios'
    if existing is not None and not submitted and not clear_existing:
        return (
            platform,
            str(existing.get('platform_profile_id') or ''),
            str(existing.get('platform_source') or 'LEGACY'),
            int(existing.get('platform_locked') or 0),
        )
    return platform, '', 'LEGACY', 0
  
  
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
                status, lifecycle_status, purchase_date, warranty_expiry, department, notes, created_at, updated_at,
                platform, connection_method, device_category, function, zone, username, normal_username, normal_password,
                admin_username, admin_password, auth_model, enable_password, management_port
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        ''', (
            asset_id, 'network_device', '', device.get('sn', ''), vendor,
            device.get('model', ''), device.get('hostname', ''),
            device.get('site_id') or device.get('site', ''), '', '', 1, None,
            device.get('ip_address', ''), '', device.get('role', ''),
            '', '', '',
            'active', device.get('lifecycle_status') or 'staging', '', '', '', '', now, now,
            device.get('platform', ''), device.get('connection_method', 'ssh'),
            device.get('device_category', ''), device.get('function', ''), device.get('zone', 'Unknown') or 'Unknown',
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
    if 'web_access_enabled' in sanitized:
        sanitized['web_access_enabled'] = bool(sanitized.get('web_access_enabled'))
    for scheme_key in ('web_http_enabled', 'web_https_enabled'):
        if scheme_key in sanitized:
            sanitized[scheme_key] = bool(sanitized.get(scheme_key))
    display_site_name = canonical_site_name(sanitized)
    canonical_site_id = str(sanitized.get('canonical_site_id') or '').strip()
    # All device consumers use ``site`` as their display field. Keep the
    # canonical ID separately for filters and writes; never leak a generated
    # site-* identifier into a business-facing view.
    sanitized['site'] = display_site_name
    sanitized['datacenter'] = display_site_name
    if canonical_site_id:
        sanitized['site_id'] = canonical_site_id
    cmdb_rack_id = str(sanitized.get('cmdb_rack_id') or '').strip()
    if cmdb_rack_id and not str(sanitized.get('rack_id') or '').strip():
        sanitized['rack_id'] = cmdb_rack_id

    # Hardware status has one API contract even though older rows stored
    # labels (ok/redundant/fail) and some SQLite rows may contain 0/1.
    # Expose true=normal, false=abnormal, null=unknown to every device-list
    # consumer while keeping the database columns backward compatible.
    for status_key in ('fan_status', 'psu_status'):
        if status_key in sanitized:
            sanitized[status_key] = normalize_hardware_status(sanitized.get(status_key))

    # Synchronize lifecycle status prioritizing physical_assets status when linked
    asset_lifecycle = str(sanitized.get('asset_lifecycle_status') or '').strip()
    device_lifecycle = str(sanitized.get('lifecycle_status') or '').strip()
    sanitized['lifecycle_status'] = asset_lifecycle or device_lifecycle or 'staging'

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
    elif error_code == 'ssh_host_key_untrusted':
        detail = '设备可达，但 SSH 主机密钥未登记或与已登记指纹不一致。'
        stage_detail = '请管理员核对设备 SHA256 主机密钥指纹后，再在资产 PAM Host Key 设置中登记。'

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
        'ssh_host_key_untrusted': f'{device_label} SSH 主机密钥未登记或与已登记指纹不一致。',
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

def _fetch_interface_data_by_device_ids(conn, device_ids: list[str]) -> dict[str, list[dict]]:
    """Load interface state and latest telemetry for a device batch.

    The devices endpoint can return many rows at once.  Keeping this query
    batched avoids one telemetry query per device in the full response mode.
    """
    unique_ids = list(dict.fromkeys(str(device_id) for device_id in device_ids if device_id))
    if not unique_ids:
        return {}

    placeholders = ','.join('?' for _ in unique_ids)
    try:
        rows = conn.execute(f'''
            SELECT
                i.device_id,
                i.interface_name as name,
                i.description,
                COALESCE(t.status, i.oper_status) as status,
                COALESCE(t.speed_mbps, i.speed / 1000000.0) as speed_mbps,
                COALESCE(t.in_bps, 0.0) as in_bps,
                COALESCE(t.out_bps, 0.0) as out_bps,
                COALESCE(t.bw_in_pct, 0.0) as bw_in_pct,
                COALESCE(t.bw_out_pct, 0.0) as bw_out_pct,
                COALESCE(t.in_pkts, 0) as in_packets_total,
                COALESCE(t.out_pkts, 0) as out_packets_total,
                COALESCE(t.in_pkts, 0) as in_ucast_pkts,
                COALESCE(t.out_pkts, 0) as out_ucast_pkts,
                COALESCE(t.in_errors, 0) as in_errors,
                COALESCE(t.out_errors, 0) as out_errors,
                COALESCE(t.in_discards, 0) as in_discards,
                COALESCE(t.out_discards, 0) as out_discards,
                COALESCE(t.fcs_errors, 0) as fcs_errors,
                COALESCE(t.frame_too_long_errors, 0) as frame_too_long_errors,
                COALESCE(t.mac_rx_errors, 0) as mac_rx_errors,
                COALESCE(t.symbol_errors, 0) as symbol_errors,
                COALESCE(t.packet_counter_source, '') as packet_counter_source,
                COALESCE(t.fcs_source, '') as fcs_source
            FROM interfaces i
            LEFT JOIN (
                SELECT latest.*
                FROM interface_telemetry_raw latest
                INNER JOIN (
                    SELECT device_id, interface_name, MAX(ts) as max_ts
                    FROM interface_telemetry_raw
                    WHERE device_id IN ({placeholders})
                    GROUP BY device_id, interface_name
                ) sub ON latest.device_id = sub.device_id
                    AND latest.interface_name = sub.interface_name
                    AND latest.ts = sub.max_ts
                WHERE latest.device_id IN ({placeholders})
            ) t ON i.device_id = t.device_id AND i.interface_name = t.interface_name
            WHERE i.device_id IN ({placeholders})
            ORDER BY i.device_id, i.interface_name
        ''', tuple(unique_ids) * 3).fetchall()
    except Exception as exc:
        _logger.warning("Failed to fetch interfaces for device batch: %s", exc)
        return {}

    result: dict[str, list[dict]] = {device_id: [] for device_id in unique_ids}
    for row in rows:
        row_dict = dict(row)
        device_id = str(row_dict.pop('device_id'))
        result.setdefault(device_id, []).append(row_dict)

    # Keep the device inventory/health view consistent with the realtime view:
    # a structurally valid SNMP counter can still be an agent/view placeholder
    # when every physical port returns the same non-zero tuple.  The raw
    # values remain in the response; this quality marker only prevents the
    # health score from treating a known collection anomaly as real errors.
    def _is_virtual_or_aggregate(name: object) -> bool:
        lowered = str(name or '').strip().casefold()
        return (
            not lowered
            or lowered.startswith(('lo', 'loopback', 'inloopback', 'vl', 'vlan', 'tu', 'tunnel'))
            or 'tunnel' in lowered
            or any(skip in lowered for skip in ('null', 'nu0', 'unrouted', 'stack', 'cpu', 'async', 'voip', 'vo0'))
            or any(token in lowered for token in ('bridge-aggregation', 'route-aggregation', 'eth-trunk', 'port-channel', 'portchannel', 'lag'))
        )

    for device_id, items in result.items():
        physical = [
            item for item in items
            if not _is_virtual_or_aggregate(item.get('name'))
        ]
        signatures = {
            (
                int(item.get('in_errors') or 0),
                int(item.get('out_errors') or 0),
                int(item.get('in_discards') or 0),
                int(item.get('out_discards') or 0),
            )
            for item in physical
        }
        if len(physical) < 3 or len(signatures) != 1:
            continue
        signature = next(iter(signatures))
        if not any(signature):
            continue
        reason = (
            'SNMP returned the same non-zero error/discard tuple for '
            f'{len(physical)} physical interfaces '
            f'(IN errors={signature[0]}, OUT errors={signature[1]}, '
            f'IN discards={signature[2]}, OUT discards={signature[3]}); '
            'raw values are preserved but should be checked against the device SNMP view.'
        )
        for item in physical:
            item['counter_quality'] = 'suspicious_uniform'
            item['counter_quality_reason'] = reason
    return result


def _normalize_device_row(row, conn=None, interface_data=None):
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

    # Dynamically build interface_data by querying interfaces and joining the latest telemetry.
    # Callers returning a batch may provide the already-loaded data to avoid N+1 queries.
    opened_here = False
    if conn is None:
        conn = get_db_connection()
        opened_here = True
    try:
        if interface_data is None:
            interface_data = _fetch_interface_data_by_device_ids(conn, [str(item['id'])]).get(str(item['id']), [])
        item['interface_data'] = interface_data
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
        f'''SELECT dt.resource_id AS device_id, td.id, td.category, td.code, td.label, td.label_zh,
                   td.color, td.icon, td.description, td.sort_order, td.built_in, td.source_type,
                   td.is_system, td.is_active
            FROM tag_assignments dt
            JOIN tag_definitions td ON dt.tag_id = td.id
            WHERE dt.resource_type='device' AND dt.resource_id IN ({placeholders})
            ORDER BY td.category, td.sort_order, td.code''',
        tuple(device_ids)
    ).fetchall()
    tag_map: dict[str, list] = {}
    for r in rows:
        did = r['device_id']
        tag_map.setdefault(did, []).append({
            'id': r['id'], 'category': r['category'], 'code': r['code'], 'value': r['code'],
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
            'pa.lifecycle_status AS asset_lifecycle_status, pa.status AS asset_status, '
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
            'COALESCE(NULLIF(r.row, \'\'), NULLIF(r_legacy.row, \'\'), \'\') AS rack_row, '
            'EXISTS (SELECT 1 FROM asset_web_access_profiles awp '
            '        WHERE awp.asset_id = pa.id AND awp.enabled = 1) AS web_access_enabled, '
            'EXISTS (SELECT 1 FROM asset_web_access_profiles awp '
            '        WHERE awp.asset_id = pa.id AND awp.enabled = 1 AND LOWER(awp.scheme) = \'http\') AS web_http_enabled, '
            'EXISTS (SELECT 1 FROM asset_web_access_profiles awp '
            '        WHERE awp.asset_id = pa.id AND awp.enabled = 1 AND LOWER(awp.scheme) = \'https\') AS web_https_enabled'
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
                'd.snmp_cpu_oid, d.snmp_memory_oid, '
                'd.snmp_metric_profile_id, '
                'd.site_id, d.fan_status, d.psu_status, d.sys_name, d.sys_location, d.sys_contact, d.asset_id, d.vendor, '
                'd.device_category, d.management_port, d.lifecycle_status, '
                'd.platform_profile_id, d.platform_source, d.platform_locked'
                + asset_cols
            )

        # Backward-compatible mode: no pagination params -> return array.
        # Safety cap: never return more than 200 rows without explicit pagination to prevent UI hangs.
        if page is None or page_size is None:
            devices = conn.execute(
                f'SELECT {select_clause} {from_clause} {where_sql} ORDER BY {order_col} {order_dir} LIMIT 200',
                tuple(params)
            ).fetchall()
            if str(mode).lower() == 'light':
                items = [_sanitize_device_item(dict(d)) for d in devices]
            else:
                interface_data = _fetch_interface_data_by_device_ids(conn, [str(d['id']) for d in devices])
                items = [_normalize_device_row(d, conn, interface_data.get(str(d['id']), [])) for d in devices]
            items = annotate_devices_with_snmp_profile(_annotate_devices_with_tags(conn, items))
            return annotate_devices_with_health(conn, items)

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

        if str(mode).lower() == 'light':
            items = [_sanitize_device_item(dict(d)) for d in devices]
        else:
            interface_data = _fetch_interface_data_by_device_ids(conn, [str(d['id']) for d in devices])
            items = [_normalize_device_row(d, conn, interface_data.get(str(d['id']), [])) for d in devices]

        items = annotate_devices_with_snmp_profile(_annotate_devices_with_tags(conn, items))
        return {
            'items': annotate_devices_with_health(conn, items),
            'total': total,
            'page': page,
            'page_size': page_size,
            'status_counts': status_counts,
        }
    finally:
        conn.close()


@router.get("/platform-registry/snmp-metric-profiles")
def list_snmp_metric_profiles(
    search: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user=require_role("Viewer"),
):
    """List model-scoped SNMP metric templates for the management UI."""
    conn = get_db_connection()
    try:
        result = list_model_metric_profiles_page(
            conn,
            search or '',
            page=page,
            page_size=page_size,
        )
        return {
            "success": True,
            "data": result["items"],
            "total": result["total"],
            "page": result["page"],
            "page_size": result["page_size"],
            "total_pages": result["total_pages"],
        }
    finally:
        conn.close()


def _prepare_snmp_walk_target(row: dict[str, Any], *, asset_only: bool = False) -> dict[str, Any]:
    """Normalize a device/asset row for the SNMP walk credential resolver.

    Asset management stores the management address as ``management_ip`` while
    the collector contract expects ``ip_address``.  Keep that translation
    server-side so the UI never has to read or submit SNMP credentials.
    """
    target = dict(row)
    if asset_only:
        target['ip_address'] = str(target.get('management_ip') or '').strip()
    elif str(target.get('_asset_management_ip') or '').strip():
        target['ip_address'] = str(target.get('_asset_management_ip') or '').strip()
    elif not str(target.get('ip_address') or '').strip():
        target['ip_address'] = str(target.get('_asset_management_ip') or '').strip()
    if not str(target.get('hostname') or '').strip():
        target['hostname'] = str(target.get('_asset_hostname') or '').strip()
    return target


def _find_snmp_walk_targets(*, device_id: str = '', target_query: str = '') -> list[dict[str, Any]]:
    """Find SNMP test targets from the asset/device registry.

    Exact matching is attempted first.  If it does not identify a single
    target, a case-insensitive SQL ``LIKE`` search provides the requested
    fuzzy/regex-style input behavior while remaining compatible with both the
    PostgreSQL and SQLite database adapters used by the project.
    """
    conn = get_db_connection()
    try:
        if device_id:
            device_row = conn.execute(
                '''SELECT d.*, pa.management_ip AS _asset_management_ip,
                          pa.hostname AS _asset_hostname
                   FROM devices d
                   LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                   WHERE d.id = ? LIMIT 1''',
                (device_id,),
            ).fetchone()
            if device_row:
                return [_prepare_snmp_walk_target(dict(device_row))]
            asset_row = conn.execute('SELECT * FROM physical_assets WHERE id = ? LIMIT 1', (device_id,)).fetchone()
            if asset_row:
                return [_prepare_snmp_walk_target(dict(asset_row), asset_only=True)]
            return []

        query = target_query.strip()
        if not query:
            return []

        exact_sql = '''
            SELECT d.*, pa.management_ip AS _asset_management_ip,
                   pa.hostname AS _asset_hostname
            FROM devices d
            LEFT JOIN physical_assets pa ON pa.id = d.asset_id
            WHERE LOWER(COALESCE(d.ip_address, '')) = LOWER(?)
               OR LOWER(COALESCE(d.hostname, '')) = LOWER(?)
               OR LOWER(COALESCE(pa.management_ip, '')) = LOWER(?)
               OR LOWER(COALESCE(pa.hostname, '')) = LOWER(?)
            ORDER BY COALESCE(NULLIF(d.hostname, ''), pa.hostname, ''), d.id
            LIMIT 20
        '''
        exact_rows = [
            _prepare_snmp_walk_target(dict(row))
            for row in conn.execute(exact_sql, (query, query, query, query)).fetchall()
        ]
        if exact_rows:
            return exact_rows

        pattern = f'%{query}%'
        fuzzy_sql = '''
            SELECT d.*, pa.management_ip AS _asset_management_ip,
                   pa.hostname AS _asset_hostname
            FROM devices d
            LEFT JOIN physical_assets pa ON pa.id = d.asset_id
            WHERE LOWER(COALESCE(d.ip_address, '')) LIKE LOWER(?)
               OR LOWER(COALESCE(d.hostname, '')) LIKE LOWER(?)
               OR LOWER(COALESCE(pa.management_ip, '')) LIKE LOWER(?)
               OR LOWER(COALESCE(pa.hostname, '')) LIKE LOWER(?)
            ORDER BY COALESCE(NULLIF(d.hostname, ''), pa.hostname, ''), d.id
            LIMIT 20
        '''
        targets = [
            _prepare_snmp_walk_target(dict(row))
            for row in conn.execute(fuzzy_sql, (pattern, pattern, pattern, pattern)).fetchall()
        ]

        # An asset may exist before a network-device row is linked.  It is
        # still a valid source of SNMP credentials and management IP.
        if not targets:
            asset_sql = '''
                SELECT pa.*
                FROM physical_assets pa
                WHERE NOT EXISTS (SELECT 1 FROM devices d WHERE d.asset_id = pa.id)
                  AND (LOWER(COALESCE(pa.management_ip, '')) LIKE LOWER(?)
                    OR LOWER(COALESCE(pa.hostname, '')) LIKE LOWER(?)
                    OR LOWER(COALESCE(pa.asset_tag, '')) LIKE LOWER(?))
                ORDER BY COALESCE(NULLIF(pa.hostname, ''), pa.management_ip, ''), pa.id
                LIMIT 20
            '''
            targets = [
                _prepare_snmp_walk_target(dict(row), asset_only=True)
                for row in conn.execute(asset_sql, (pattern, pattern, pattern)).fetchall()
            ]

        # If the input contains regular-expression syntax (for example
        # ``10\\.254\\.\\d+\\.\\d+``), apply it to the same registry fields.
        # Invalid expressions fall back to a literal, case-insensitive search;
        # this keeps a typo from turning into an unsafe database expression.
        if not targets and len(query) <= 128:
            try:
                matcher = re.compile(query, re.IGNORECASE)
            except re.error:
                matcher = re.compile(re.escape(query), re.IGNORECASE)

            candidate_sql = '''
                SELECT d.*, pa.management_ip AS _asset_management_ip,
                       pa.hostname AS _asset_hostname
                FROM devices d
                LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                ORDER BY COALESCE(NULLIF(d.hostname, ''), pa.hostname, ''), d.id
                LIMIT 5000
            '''
            for row in conn.execute(candidate_sql).fetchall():
                item = _prepare_snmp_walk_target(dict(row))
                values = (item.get('ip_address'), item.get('hostname'), item.get('_asset_management_ip'), item.get('_asset_hostname'))
                if any(matcher.search(str(value or '')) for value in values):
                    targets.append(item)
            if not targets:
                asset_candidates = conn.execute('SELECT * FROM physical_assets LIMIT 5000').fetchall()
                for row in asset_candidates:
                    item = _prepare_snmp_walk_target(dict(row), asset_only=True)
                    values = (item.get('management_ip'), item.get('hostname'), item.get('asset_tag'))
                    if any(matcher.search(str(value or '')) for value in values):
                        targets.append(item)
        return targets
    finally:
        conn.close()


def _find_exact_snmp_walk_target(ip: str) -> dict[str, Any] | None:
    """Resolve one exact management IP from asset management.

    The confirmation field is deliberately exact: it must not use the broad
    inventory search endpoint, whose result count can include related asset
    rows.  Returning the first deterministic row also keeps legacy databases
    with duplicate device records usable while the browser only receives the
    confirmed address and identifiers.
    """
    query = ip.strip()
    if not query:
        return None
    conn = get_db_connection()
    try:
        linked_row = conn.execute(
            '''SELECT d.*, pa.management_ip AS _asset_management_ip,
                      pa.hostname AS _asset_hostname
               FROM devices d
               LEFT JOIN physical_assets pa ON pa.id = d.asset_id
               WHERE COALESCE(pa.asset_type, 'network_device') = 'network_device'
                 AND (LOWER(TRIM(COALESCE(pa.management_ip, ''))) = LOWER(TRIM(?))
                   OR LOWER(TRIM(COALESCE(d.ip_address, ''))) = LOWER(TRIM(?)))
               ORDER BY CASE WHEN LOWER(TRIM(COALESCE(pa.management_ip, ''))) = LOWER(TRIM(?)) THEN 0 ELSE 1 END,
                        CASE WHEN LOWER(TRIM(COALESCE(d.status, ''))) = 'online' THEN 0 ELSE 1 END,
                        d.id
               LIMIT 1''',
            (query, query, query),
        ).fetchone()
        if linked_row:
            return _prepare_snmp_walk_target(dict(linked_row))

        asset_row = conn.execute(
            '''SELECT pa.*
               FROM physical_assets pa
               WHERE pa.asset_type = 'network_device'
                 AND LOWER(TRIM(COALESCE(pa.management_ip, ''))) = LOWER(TRIM(?))
                 AND NOT EXISTS (SELECT 1 FROM devices d WHERE d.asset_id = pa.id)
               ORDER BY pa.id
               LIMIT 1''',
            (query,),
        ).fetchone()
        if asset_row:
            return _prepare_snmp_walk_target(dict(asset_row), asset_only=True)
        return None
    finally:
        conn.close()


@router.get("/platform-registry/snmp-walk-target")
def resolve_snmp_walk_target(
    ip: str = Query(..., min_length=1, max_length=255),
    user=require_role("Operator"),
):
    """Confirm an exact asset-management IP before running SNMP WALK."""
    target = _find_exact_snmp_walk_target(ip)
    if not target:
        raise HTTPException(status_code=404, detail='IP not found in asset management')
    resolved_ip = str(target.get('_asset_management_ip') or target.get('management_ip') or target.get('ip_address') or '').strip()
    if not resolved_ip:
        raise HTTPException(status_code=404, detail='The matched asset has no management IP')
    return {
        'success': True,
        'data': {
            'ip': resolved_ip,
            'device_id': str(target.get('id') or ''),
            'hostname': str(target.get('hostname') or ''),
        },
    }


@router.post("/platform-registry/snmp-walk-test")
async def test_snmp_walk(payload: dict = Body(default={}), user=require_role("Operator")):
    """Run one read-only SNMP WALK for the template editor.

    The endpoint deliberately accepts structured values instead of an
    arbitrary shell command.  This keeps the test path independent of
    ``snmpwalk.exe`` and prevents command injection while still matching the
    common ``snmpwalk -v2c -c COMMUNITY HOST OID`` workflow (v1 is also
    accepted for legacy devices).
    """
    host = str(payload.get('ip') or payload.get('host') or '').strip()
    community = str(payload.get('community') or '').strip()
    requested_device_id = str(payload.get('device_id') or '').strip()
    target_query = str(payload.get('target_query') or '').strip()
    matched_device: dict[str, Any] | None = None
    target_source = 'manual'

    # A template test normally supplies target_query/device_id.  Resolve the
    # actual host and community from asset-management credentials on the
    # server; the browser never receives the secret.  The legacy structured
    # ip+community form remains available for API compatibility.
    if requested_device_id or target_query:
        targets = _find_snmp_walk_targets(device_id=requested_device_id, target_query=target_query)
        if not targets:
            raise HTTPException(status_code=404, detail='No matching managed asset was found')
        if len(targets) > 1:
            raise HTTPException(status_code=409, detail='Target matches multiple assets; enter a more specific IP or hostname')
        matched_device = targets[0]
        collector_credentials = resolve_collector_credentials(matched_device)
        snmp_credentials = collector_credentials.get('snmp') or {}
        host = str(snmp_credentials.get('server') or matched_device.get('ip_address') or '').strip()
        community = str(snmp_credentials.get('community') or '').strip()
        port = snmp_credentials.get('port') or 161
        target_source = 'asset'

    raw_oid = payload.get('oid')
    if not host:
        raise HTTPException(status_code=400, detail='SNMP address is required')
    if not community:
        detail = 'Matched asset has no SNMP community configured' if matched_device else 'SNMP community is required'
        raise HTTPException(status_code=400, detail=detail)
    try:
        oid = normalize_metric_oid(raw_oid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f'oid: {exc}') from exc
    if not oid:
        raise HTTPException(status_code=400, detail='OID is required')

    version = str(payload.get('version') or payload.get('snmp_version') or '2c').strip().lower()
    if version in {'v1', '1'}:
        version = '1'
    elif version in {'v2c', '2c', '2'}:
        version = '2c'
    else:
        raise HTTPException(status_code=400, detail='SNMP version must be 1 or 2c')

    try:
        port = int(port if matched_device else (payload.get('port') or 161))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail='SNMP port must be an integer') from exc
    if not 1 <= port <= 65535:
        raise HTTPException(status_code=400, detail='SNMP port must be between 1 and 65535')
    try:
        timeout = float(payload.get('timeout') or 5)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail='SNMP timeout must be a number') from exc
    if timeout <= 0 or timeout > 60:
        raise HTTPException(status_code=400, detail='SNMP timeout must be between 0 and 60 seconds')
    try:
        max_rows = int(payload.get('max_rows') or 2000)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail='max_rows must be an integer') from exc
    if not 1 <= max_rows <= 10000:
        raise HTTPException(status_code=400, detail='max_rows must be between 1 and 10000')

    from services.snmp_service import _snmp_walk

    try:
        rows = await _snmp_walk(host, community, oid, port=port, timeout=timeout, max_rows=max_rows, version=version)
    except Exception as exc:
        logger.warning('SNMP WALK test failed for %s %s: %s', host, oid, type(exc).__name__)
        raise HTTPException(status_code=502, detail='SNMP WALK request failed') from exc

    formatted_rows = [
        {'oid': f"{oid}.{suffix}" if str(suffix).strip('.') else oid, 'value': value}
        for suffix, value in rows
    ]
    return {
        'success': bool(formatted_rows),
        'data': {
            'host': host,
            'oid': oid,
            'version': version,
            'port': port,
            'status': 'ok' if formatted_rows else 'no_data',
            'message': 'SNMP WALK succeeded' if formatted_rows else 'No rows returned; check OID, view permissions, and reachability',
            'row_count': len(formatted_rows),
            'truncated': len(formatted_rows) >= max_rows,
            'rows': formatted_rows,
            'target_source': target_source,
            'matched_device_id': str(matched_device.get('id')) if matched_device else None,
            'matched_hostname': str(matched_device.get('hostname') or '') if matched_device else '',
        },
    }


@router.post("/platform-registry/snmp-hardware-test")
async def test_snmp_hardware_metrics(payload: dict = Body(default={}), user=require_role("Operator")):
    """Read the default health hardware set and any submitted template metrics.

    This is intentionally separate from the raw WALK compatibility endpoint.
    The template editor submits its current definitions when available, but a
    live test always includes the default health set (CPU, memory, temperature,
    fan, and power supply).  Configured definitions take precedence for their
    metric; missing definitions use the vendor collector.  The operation is
    read-only and never changes the saved profile or returns an OID table.
    """
    requested_device_id = str(payload.get('device_id') or '').strip()
    target_query = str(payload.get('target_query') or '').strip()
    if not requested_device_id and not target_query:
        raise HTTPException(status_code=400, detail='A managed device_id or target_query is required')

    targets = _find_snmp_walk_targets(device_id=requested_device_id, target_query=target_query)
    if not targets:
        raise HTTPException(status_code=404, detail='No matching managed asset was found')
    if len(targets) > 1:
        raise HTTPException(status_code=409, detail='Target matches multiple assets; enter a more specific IP or hostname')

    raw_definitions = payload.get('metric_definitions')
    if raw_definitions is None:
        raw_definitions = payload.get('metrics')
    if raw_definitions is None:
        raw_definitions = {}
    if not isinstance(raw_definitions, dict):
        raise HTTPException(status_code=400, detail='metric_definitions must be an object')
    unsupported = [
        str(key)
        for key in raw_definitions
        if str(key).strip().casefold() not in {item.casefold() for item in SUPPORTED_METRIC_KEYS}
    ]
    if unsupported:
        raise HTTPException(status_code=400, detail=f'Unsupported hardware metric: {unsupported[0]}')
    try:
        definitions = validate_metric_definitions({'metric_definitions': raw_definitions}, allow_empty=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    device = targets[0]
    collector_credentials = resolve_collector_credentials(device)
    snmp_credentials = collector_credentials.get('snmp') or {}
    host = str(snmp_credentials.get('server') or device.get('ip_address') or '').strip()
    community = str(snmp_credentials.get('community') or '').strip()
    if not host or not community:
        raise HTTPException(status_code=400, detail='Matched asset has no SNMP address or community configured')
    try:
        port = int(snmp_credentials.get('port') or 161)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail='SNMP port must be an integer') from exc
    if not 1 <= port <= 65535:
        raise HTTPException(status_code=400, detail='SNMP port must be between 1 and 65535')

    version = str(payload.get('version') or payload.get('snmp_version') or '2c').strip().lower()
    if version in {'v1', '1'}:
        version = '1'
    elif version in {'v2c', '2c', '2'}:
        version = '2c'
    else:
        raise HTTPException(status_code=400, detail='SNMP version must be 1 or 2c')

    platform = str(device.get('platform') or device.get('vendor') or '').strip()
    if not platform:
        raise HTTPException(status_code=400, detail='Matched asset has no vendor or platform mapping')
    try:
        snapshot = await collect_device_metrics(
            host,
            platform,
            community,
            port,
            custom_metrics=definitions or None,
            device_id=str(device.get('id') or ''),
            metric_profile_id=str(payload.get('metric_profile_id') or 'live-test'),
            bypass_cache=True,
            version=version,
            template_only=True,
        )
    except Exception as exc:
        logger.warning('SNMP hardware metric test failed for %s: %s', host, type(exc).__name__)
        raise HTTPException(status_code=502, detail='SNMP hardware metric test failed') from exc

    result_keys = {
        'cpu': 'cpu_usage',
        'memory': 'memory_usage',
        'temperature': 'temp',
        'fan': 'fan_status',
        'power_supply': 'psu_status',
        'uptime': 'uptime',
        'storage': 'storage_usage',
        'voltage': 'voltage',
        'power': 'power_watts',
    }
    default_units = {
        'cpu': '%',
        'memory': '%',
        'temperature': '°C',
        'fan': 'bool',
        'power_supply': 'bool',
        'uptime': 's',
        'storage': '%',
        'voltage': 'V',
        'power': 'W',
    }
    requested_metrics = list(dict.fromkeys([*HEALTH_METRIC_KEYS, *definitions.keys()]))
    snapshot_values = snapshot.get('hardware_metrics') or {}
    snapshot_details = snapshot.get('metric_details') or {}

    def _builtin_status(value: Any) -> str:
        if value is None or value == '':
            return 'missing'
        if isinstance(value, bool):
            return 'ok' if value else 'fail'
        normalized = str(value).strip().casefold()
        if normalized in {'fail', 'failed', 'warning', 'down', 'offline', 'alarm'}:
            return 'fail'
        return 'ok'

    metric_results: dict[str, dict[str, Any]] = {}
    for metric in requested_metrics:
        configured_detail = snapshot_details.get(metric)
        if isinstance(configured_detail, dict):
            detail = dict(configured_detail)
            detail.setdefault('source', 'template_definition')
            metric_results[metric] = detail
            continue
        result_key = result_keys[metric]
        value = snapshot_values.get(metric, snapshot.get(result_key))
        status = _builtin_status(value)
        metric_results[metric] = {
            'value': value,
            'raw_value': value,
            'status': status,
            'passed': status == 'ok',
            'message': (
                'Applied SNMP template returned a valid value'
                if status == 'ok'
                else 'Applied SNMP template returned no value'
                if status == 'missing'
                else 'Applied SNMP template reported an abnormal state'
            ),
            'mode': 'snmp_template',
            'oid': '',
            'unit': default_units[metric],
            'source': 'snmp_template',
        }

    statuses = [str(item.get('status') or '').casefold() for item in metric_results.values()]
    if statuses and all(status == 'ok' for status in statuses):
        overall_status = 'ok'
        message = 'All applied SNMP template health metrics returned valid values'
    elif any(status in {'fail', 'warning', 'probe_error'} for status in statuses):
        overall_status = 'abnormal'
        message = 'One or more hardware metrics reported an abnormal state'
    else:
        overall_status = 'unknown'
        message = 'Applied SNMP template health metrics were read, but one or more values are missing or invalid'

    return {
        'success': True,
        'data': {
            'host': host,
            'version': version,
            'port': port,
            'platform': platform,
            'status': overall_status,
            'message': message,
            'metric_count': len(metric_results),
            'metrics': metric_results,
            'target_source': 'asset',
            'matched_device_id': str(device.get('id') or ''),
            'matched_hostname': str(device.get('hostname') or device.get('ip_address') or ''),
        },
    }


@router.post("/platform-registry/snmp-interface-test")
async def test_snmp_interface_oids(payload: dict = Body(default={}), user=require_role("Operator")):
    """Validate the draft interface MIB mapping against a managed device.

    This endpoint deliberately tests only the submitted interface definition.
    It never falls back to SSH or the hardware collector, and it returns a
    small sample for each reachable OID instead of an unbounded OID walk.
    """
    requested_device_id = str(payload.get('device_id') or '').strip()
    target_query = str(payload.get('target_query') or '').strip()
    if not requested_device_id and not target_query:
        raise HTTPException(status_code=400, detail='A managed device_id or target_query is required')

    targets = _find_snmp_walk_targets(device_id=requested_device_id, target_query=target_query)
    if not targets:
        raise HTTPException(status_code=404, detail='No matching managed asset was found')
    if len(targets) > 1:
        raise HTTPException(status_code=409, detail='Target matches multiple assets; enter a more specific IP or hostname')

    raw_config = payload.get('interface_config')
    if raw_config is None:
        raw_config = payload.get('interface')
    if not isinstance(raw_config, dict):
        raise HTTPException(status_code=400, detail='interface_config must be an object')

    from services.snmp_service import normalize_interface_config, probe_interface_definition

    try:
        interface_config = normalize_interface_config(raw_config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not interface_config:
        raise HTTPException(status_code=400, detail='interface_config cannot be empty')
    if not interface_config.get('enabled', True):
        raise HTTPException(status_code=400, detail='Enable the interface template before testing its OIDs')

    device = targets[0]
    collector_credentials = resolve_collector_credentials(device)
    snmp_credentials = collector_credentials.get('snmp') or {}
    host = str(snmp_credentials.get('server') or device.get('ip_address') or '').strip()
    community = str(snmp_credentials.get('community') or '').strip()
    if not host or not community:
        raise HTTPException(status_code=400, detail='Matched asset has no SNMP address or community configured')
    try:
        port = int(snmp_credentials.get('port') or 161)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail='SNMP port must be an integer') from exc
    if not 1 <= port <= 65535:
        raise HTTPException(status_code=400, detail='SNMP port must be between 1 and 65535')

    version = str(payload.get('version') or payload.get('snmp_version') or '2c').strip().lower()
    if version in {'v1', '1'}:
        version = '1'
    elif version in {'v2c', '2c', '2'}:
        version = '2c'
    else:
        raise HTTPException(status_code=400, detail='SNMP version must be 1 or 2c')

    try:
        probe = await probe_interface_definition(
            host,
            community,
            interface_config,
            port=port,
            version=version,
        )
    except Exception as exc:
        logger.warning('SNMP interface OID test failed for %s: %s', host, type(exc).__name__)
        raise HTTPException(status_code=502, detail='SNMP interface OID test failed') from exc

    return {
        'success': True,
        'data': {
            **probe,
            'host': host,
            'version': version,
            'port': port,
            'target_source': 'asset',
            'matched_device_id': str(device.get('id') or ''),
            'matched_hostname': str(device.get('hostname') or device.get('ip_address') or ''),
        },
    }


@router.post("/platform-registry/snmp-metric-profiles")
def create_snmp_metric_profile(payload: dict = Body(...), user=require_role("Operator")):
    conn = get_db_connection()
    try:
        profile = create_model_metric_profile(
            conn,
            payload,
            updated_by=user.get('username', 'system'),
        )
        conn.commit()
        log_audit_event(
            conn=conn,
            event_type='snmp_metric_profile.create',
            category='configuration',
            severity='info',
            status='success',
            summary=f"Created SNMP metric profile for {payload.get('vendor', '')}/{payload.get('model', '')}",
            actor_username=user.get('username', ''),
            actor_role=user.get('role', ''),
            target_type='snmp_metric_profile',
            target_id=profile.get('id', ''),
            details={'vendor': profile.get('vendor_name', ''), 'model': profile.get('model_name', '')},
        )
        conn.commit()
        return {"success": True, "data": profile}
    except ValueError as exc:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/platform-registry/snmp-metric-profiles/apply-preset")
def apply_snmp_metric_preset(payload: dict = Body(...), user=require_role("Operator")):
    conn = get_db_connection()
    preset_id = str(payload.get("preset_id") or "").strip()
    try:
        profile = apply_official_model_preset(
            conn,
            preset_id,
            updated_by=user.get("username", "system"),
        )
        conn.commit()
        log_audit_event(
            conn=conn,
            event_type="snmp_metric_profile.apply_preset",
            category="configuration",
            severity="info",
            status="success",
            summary=f"Applied official SNMP preset {preset_id}",
            actor_username=user.get("username", ""),
            actor_role=user.get("role", ""),
            target_type="snmp_metric_profile",
            target_id=profile.get("id", ""),
            details={
                "preset_id": preset_id,
                "vendor": profile.get("vendor_name", ""),
                "model": profile.get("model_name", ""),
                "applied_mode": profile.get("applied_mode", ""),
            },
        )
        conn.commit()
        return {"success": True, "data": profile}
    except ValueError as exc:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.get("/platform-registry/snmp-metric-profiles/{profile_id}/bindings")
def list_snmp_metric_profile_bindings(profile_id: str, user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        return {
            "success": True,
            "data": {
                "profile_id": profile_id,
                "devices": list_model_metric_profile_devices(conn, profile_id),
            },
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/platform-registry/snmp-metric-profiles/{profile_id}/bindings")
def bind_snmp_metric_profile_devices(
    profile_id: str,
    payload: dict = Body(...),
    user=require_role("Operator"),
):
    conn = get_db_connection()
    try:
        result = bind_model_metric_profile(conn, profile_id, payload.get("device_ids"))
        conn.commit()
        log_audit_event(
            conn=conn,
            event_type="snmp_metric_profile.bind",
            category="configuration",
            severity="info",
            status="success",
            summary=f"Bound SNMP metric profile {profile_id} to devices",
            actor_username=user.get("username", ""),
            actor_role=user.get("role", ""),
            target_type="snmp_metric_profile",
            target_id=profile_id,
            details={
                "device_count": len(result.get("devices") or []),
                "device_ids": [device.get("device_id") for device in result.get("devices") or []],
            },
        )
        conn.commit()
        return {"success": True, "data": result}
    except ValueError as exc:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/platform-registry/snmp-metric-profiles/{profile_id}/bindings/unbind")
def unbind_snmp_metric_profile_devices(
    profile_id: str,
    payload: dict = Body(...),
    user=require_role("Operator"),
):
    conn = get_db_connection()
    try:
        result = unbind_model_metric_profile(conn, profile_id, payload.get("device_ids"))
        conn.commit()
        log_audit_event(
            conn=conn,
            event_type="snmp_metric_profile.unbind",
            category="configuration",
            severity="info",
            status="success",
            summary=f"Unbound SNMP metric profile {profile_id} from devices",
            actor_username=user.get("username", ""),
            actor_role=user.get("role", ""),
            target_type="snmp_metric_profile",
            target_id=profile_id,
            details={
                "remaining_device_count": len(result.get("devices") or []),
                "device_ids": [device.get("device_id") for device in result.get("devices") or []],
            },
        )
        conn.commit()
        return {"success": True, "data": result}
    except ValueError as exc:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.put("/platform-registry/snmp-metric-profiles/{profile_id}")
def update_snmp_metric_profile(profile_id: str, payload: dict = Body(...), user=require_role("Operator")):
    conn = get_db_connection()
    try:
        profile = update_model_metric_profile(
            conn,
            profile_id,
            payload,
            updated_by=user.get('username', 'system'),
        )
        conn.commit()
        log_audit_event(
            conn=conn,
            event_type='snmp_metric_profile.update',
            category='configuration',
            severity='info',
            status='success',
            summary=f"Updated SNMP metric profile {profile_id}",
            actor_username=user.get('username', ''),
            actor_role=user.get('role', ''),
            target_type='snmp_metric_profile',
            target_id=profile_id,
            details={'vendor': profile.get('vendor_name', ''), 'model': profile.get('model_name', '')},
        )
        conn.commit()
        return {"success": True, "data": profile}
    except ValueError as exc:
        conn.rollback()
        status_code = 409 if "read-only" in str(exc).casefold() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        conn.close()


@router.delete("/platform-registry/snmp-metric-profiles/{profile_id}")
def delete_snmp_metric_profile(profile_id: str, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        delete_model_metric_profile(conn, profile_id)
        conn.commit()
        log_audit_event(
            conn=conn,
            event_type='snmp_metric_profile.delete',
            category='configuration',
            severity='info',
            status='success',
            summary=f"Deleted SNMP metric profile {profile_id}",
            actor_username=user.get('username', ''),
            actor_role=user.get('role', ''),
            target_type='snmp_metric_profile',
            target_id=profile_id,
        )
        conn.commit()
        return {"success": True, "data": {"profile_id": profile_id}}
    except ValueError as exc:
        conn.rollback()
        status_code = 409 if "still bound" in str(exc).casefold() else 404
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        conn.close()


@router.get("/platform-registry/snmp-metric-profiles/{profile_id}/mapping-validation")
def validate_snmp_metric_profile_mapping(profile_id: str, user=require_role("Viewer")):
    """Report which devices explicitly selected this template."""
    conn = get_db_connection()
    try:
        return {
            "success": True,
            "data": get_model_metric_profile_mapping(conn, profile_id),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/platform-registry/snmp-metric-profiles/{profile_id}/test")
async def test_snmp_metric_profile(
    profile_id: str,
    payload: dict = Body(default={}),
    user=require_role("Operator"),
):
    """Live-test a model profile against one selected device.

    Hardware and interface definitions are verified independently.  A custom
    interface mapping is activated only after its identity table and selected
    paired counter width pass. Verification is quality metadata and does not
    create or remove an explicit device binding.
    """
    conn = get_db_connection()
    try:
        profile_row = conn.execute(
            'SELECT * FROM snmp_metric_profiles WHERE id = ?',
            (profile_id,),
        ).fetchone()
        if not profile_row:
            raise HTTPException(status_code=404, detail='Model OID profile not found')
        profile = dict(profile_row)
        requested_device_id = str(payload.get('device_id') or '').strip()
        if requested_device_id:
            candidate_rows = conn.execute(
                'SELECT * FROM devices WHERE id = ?',
                (requested_device_id,),
            ).fetchall()
        else:
            candidate_rows = conn.execute(
                "SELECT * FROM devices WHERE LOWER(TRIM(COALESCE(model, ''))) = LOWER(TRIM(?)) "
                "ORDER BY CASE WHEN LOWER(TRIM(COALESCE(status, ''))) = 'online' THEN 0 ELSE 1 END, "
                "CASE WHEN COALESCE(TRIM(ip_address), '') <> '' THEN 0 ELSE 1 END, hostname",
                (profile['model_name'],),
            ).fetchall()
    finally:
        conn.close()

    if requested_device_id:
        # An operator may test a draft against the exact device selected in
        # the binding dialog.  Manual binding is deliberately not restricted
        # by vendor/model heuristics.
        matching = [dict(row) for row in candidate_rows]
    else:
        matching = [
            dict(row) for row in candidate_rows
            if normalize_model_key(row['model']) == str(profile['model_key'] or '')
            and normalize_vendor_key(row['vendor'], row['platform']) == str(profile['vendor_key'] or '')
        ]
    if not matching:
        raise HTTPException(status_code=400, detail='No device matches this vendor/model profile')

    device = matching[0]
    collector_credentials = resolve_collector_credentials(device)
    snmp_credentials = collector_credentials.get('snmp') or {}
    ip = snmp_credentials.get('server') or device.get('ip_address') or ''
    community = snmp_credentials.get('community') or ''
    port = snmp_credentials.get('port') or 161
    configured = profile_metric_definitions(profile)
    interface_config = profile_interface_config(profile)
    hardware_configured = bool(configured)
    interface_configured = bool(interface_config)
    test_results: dict[str, dict] = {}
    interface_result: dict[str, Any] = {}
    hardware_passed: bool | None = None if not hardware_configured else False
    interface_passed: bool | None = None if not interface_configured else False
    if not ip or not community:
        message = 'SNMP address or community is not configured on the sample device'
        if hardware_configured:
            hardware_passed = False
        if interface_configured:
            interface_passed = False
            interface_result = {
                'passed': False,
                'status': 'credentials_missing',
                'message': message,
                'checks': {},
                'counter_mode': interface_config.get('counter_mode', 'auto'),
                'interfaces': 0,
                'counter_supported': 0,
            }
    else:
        from services.snmp_service import probe_interface_definition, probe_metric_definition
        import asyncio as _aio

        async def _test_metric(metric: str, config: dict) -> tuple[str, dict]:
            try:
                detail = await probe_metric_definition(
                    ip,
                    community,
                    config,
                    int(port),
                    metric_name=metric,
                    platform=str(device.get('platform') or ''),
                )
                return metric, detail
            except Exception as exc:
                return metric, {
                    'oid': config.get('oid') or config.get('used_oid'),
                    'value': None,
                    'passed': False,
                    'status': 'probe_error',
                    'message': type(exc).__name__,
                }

        tasks = []
        if hardware_configured:
            tasks.append(_aio.gather(*[_test_metric(metric, config) for metric, config in configured.items()]))
        if interface_configured:
            tasks.append(probe_interface_definition(ip, community, interface_config, int(port)))
        task_results = await _aio.gather(*tasks) if tasks else []
        task_index = 0
        if hardware_configured:
            test_results = dict(task_results[task_index])
            task_index += 1
            hardware_passed = bool(test_results) and all(item.get('passed') for item in test_results.values())
        if interface_configured:
            interface_result = dict(task_results[task_index] or {})
            interface_passed = bool(interface_result.get('passed'))

        message_parts = []
        if hardware_configured:
            message_parts.append('hardware metrics passed' if hardware_passed else 'hardware metrics failed')
        if interface_configured:
            message_parts.append('interface OIDs passed' if interface_passed else 'interface OIDs failed')
        message = '; '.join(message_parts) or 'No configured definitions to test'

    configured_results = [value for value in (hardware_passed, interface_passed) if value is not None]
    passed = bool(configured_results) and all(configured_results)

    conn = get_db_connection()
    try:
        updated_profile = mark_model_metric_profile_test(
            conn,
            profile_id,
            str(device['id']),
            passed if hardware_configured else None,
            message,
            hardware_passed=hardware_passed,
            interface_passed=interface_passed,
            interface_message=str(interface_result.get('message') or message),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        'success': True,
        'data': {
            'passed': passed,
            'hardware_passed': hardware_passed,
            'interface_passed': interface_passed,
            'message': message,
            'profile_id': profile_id,
            'verification_status': updated_profile.get('verification_status'),
            'interface_verification_status': updated_profile.get('interface_verification_status'),
            'sample_device_id': str(device['id']),
            'sample_hostname': device.get('hostname') or device.get('ip_address') or str(device['id']),
            'metrics': test_results,
            'interface': interface_result,
        },
    }


# ═══════════════════════════════════════════════════════════════
# SNMP MIB Repository & Official Presets API
# ═══════════════════════════════════════════════════════════════

@router.get("/platform-registry/mibs")
def get_snmp_mibs(
    search: str = Query("", max_length=128),
    vendor: str = Query("", max_length=64),
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(40, ge=10, le=100),
    status: str = Query("", max_length=32),
    user=require_role("Viewer"),
):
    """List one bounded page of imported and built-in SNMP MIB modules."""
    conn = get_db_connection()
    try:
        # Seed built-in MIBs if repository is empty
        count_row = conn.execute("SELECT COUNT(*) AS c FROM snmp_mibs").fetchone()
        if not count_row or int(count_row[0] if isinstance(count_row, tuple) else count_row["c"]) == 0:
            seed_builtin_mibs()
        mibs, total = list_mibs_page(
            conn,
            search=search,
            vendor=vendor,
            page=page,
            page_size=page_size,
            status=status,
        )
        return {
            "success": True,
            "data": mibs,
            "total": total,
            "page": page,
            "page_size": page_size,
            "stats": get_mib_repository_stats(conn, search=search, vendor=vendor, status=status),
        }
    finally:
        conn.close()


@router.get("/platform-registry/mibs/nodes/search")
def search_snmp_mib_nodes(
    query: str = Query(..., min_length=1, max_length=128),
    vendor: str = Query("", max_length=64),
    mib_id: str = Query("", max_length=64),
    limit: int = Query(50, ge=1, le=200),
    scope: str = Query("all", max_length=16),
    user=require_role("Viewer"),
):
    """Fast search for OID symbol nodes across the MIB repository."""
    conn = get_db_connection()
    try:
        # Seed built-in MIBs if empty
        count_row = conn.execute("SELECT COUNT(*) AS c FROM snmp_mibs").fetchone()
        if not count_row or int(count_row[0] if isinstance(count_row, tuple) else count_row["c"]) == 0:
            seed_builtin_mibs()
        nodes = search_mib_nodes(conn, query=query, vendor=vendor, mib_id=mib_id, limit=limit, scope=scope)
        return {
            "success": True,
            "data": nodes,
            "total": len(nodes),
        }
    finally:
        conn.close()


@router.get("/platform-registry/mibs/presets/models")
def get_official_model_presets(user=require_role("Viewer")):
    """List official pre-built model metric profile templates."""
    presets = list_preset_profiles()
    return {
        "success": True,
        "data": presets,
        "total": len(presets),
    }


@router.get("/platform-registry/mibs/auto-match")
def auto_match_model_mibs(
    vendor: str = Query("", max_length=64),
    model: str = Query("", max_length=128),
    user=require_role("Viewer"),
):
    """Auto-match and recommend optimal MIB metrics and OIDs for an asset model."""
    match_result = match_profile_for_model(vendor=vendor, model=model)
    if not match_result:
        return {
            "success": True,
            "matched": False,
            "message": "No matching pre-built series found for this model",
            "data": None,
        }
    return {
        "success": True,
        "matched": True,
        "data": match_result,
    }


_librenms_sync_state: dict[str, Any] = {
    "running": False,
    "progress": "idle",
    "run_id": None,
    "started_at": None,
}


@router.post("/platform-registry/mibs/sync-librenms")
async def trigger_sync_librenms_mibs(
    background_tasks: BackgroundTasks,
    vendors: str = Query("", description="Comma-separated vendor keys or empty for all"),
    user=require_role("Operator"),
):
    """Trigger background full synchronization of LibreNMS MIB repository."""
    global _librenms_sync_state
    if _librenms_sync_state["running"]:
        return {
            "success": True,
            "message": "LibreNMS MIB synchronization is already running",
            "state": _librenms_sync_state,
        }

    def _sync_worker(target_vendors_list: list[str] | None):
        global _librenms_sync_state
        _librenms_sync_state["running"] = True
        _librenms_sync_state["progress"] = "Fetching latest MIBs from LibreNMS repository..."
        _librenms_sync_state["started_at"] = time.time()
        try:
            fetch_librenms_mibs(TARGET_DIR)
            _librenms_sync_state["progress"] = "Parsing and indexing MIB definitions into database..."
            result = import_mibs_from_directory(
                mibs_dir=MIBS_DIR,
                target_vendors=target_vendors_list,
            )
            _librenms_sync_state["last_result"] = result
            _librenms_sync_state["run_id"] = result.get("run_id")
            _librenms_sync_state["progress"] = f"Finished: {result.get('imported', 0)} MIBs imported, {result.get('nodes', 0)} OID nodes"
        except Exception as exc:
            logger.error("LibreNMS MIB sync worker failed: %s", exc)
            _librenms_sync_state["progress"] = f"Error: {exc}"
            _librenms_sync_state["last_result"] = {"success": False, "error": str(exc)}
        finally:
            _librenms_sync_state["running"] = False

    vendor_list = [v.strip().lower() for v in vendors.split(",") if v.strip()] if vendors else None
    background_tasks.add_task(_sync_worker, vendor_list)

    return {
        "success": True,
        "message": "LibreNMS MIB full synchronization started in background",
        "state": _librenms_sync_state,
    }


@router.get("/platform-registry/mibs/sync-librenms/status")
def get_sync_librenms_mibs_status(user=require_role("Viewer")):
    """Get the current progress status of LibreNMS MIB synchronization."""
    conn = get_db_connection()
    try:
        return {
            "success": True,
            "data": {
                **_librenms_sync_state,
                "repository": get_mib_repository_stats(conn),
            },
        }
    finally:
        conn.close()


@router.post("/platform-registry/mibs/reset-builtin")
def reset_builtin_snmp_mibs(user=require_role("Operator")):
    """Reset and re-seed all built-in core vendor MIB definitions."""
    count = reset_builtin_mibs()
    return {
        "success": True,
        "message": f"Successfully reloaded {count} built-in MIB modules",
        "count": count,
    }


@router.post("/platform-registry/mibs/upload")
async def upload_snmp_mib_file(
    file: UploadFile = File(...),
    vendor: str = Query("", max_length=64),
    description: str = Query("", max_length=500),
    background_tasks: BackgroundTasks = None,
    user=require_role("Operator"),
):
    """Upload and parse a .mib / .my / .txt file or a .zip MIB archive."""
    if background_tasks is None:
        background_tasks = BackgroundTasks()

    if not settings.SNMP_MIB_MANUAL_UPLOAD_ENABLED:
        raise HTTPException(
            status_code=410,
            detail="Manual MIB uploads are disabled; use the official LibreNMS synchronization or create an SNMP metric template.",
        )

    filename = os.path.basename(file.filename or "unknown.mib")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(content) > settings.SNMP_MIB_UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "Uploaded MIB file is too large; maximum size is "
                f"{settings.SNMP_MIB_UPLOAD_MAX_BYTES} bytes"
            ),
        )

    lower_filename = filename.lower()
    if not lower_filename.endswith((*SUPPORTED_MIB_FILE_SUFFIXES, ".zip")):
        raise HTTPException(
            status_code=400,
            detail="Only .zip, .mib, .my, .txt, .asn, and .smi files are supported",
        )

    if lower_filename.endswith(".zip"):
        import zipfile
        import io
        try:
            with zipfile.ZipFile(io.BytesIO(content), "r") as z_inspect:
                valid_members = [
                    f.filename for f in z_inspect.infolist()
                    if not f.is_dir() and not any(p.startswith(".") for p in f.filename.replace("\\", "/").split("/"))
                ]
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail=f"Invalid or corrupted ZIP archive: {exc}") from exc

        # If it's a large archive (> 10 files, e.g. full vendor repo or LibreNMS package),
        # automatically extract to the repository directory and trigger full background indexing.
        is_directory_or_large = len(valid_members) > 10

        if is_directory_or_large:
            extracted_count, detected_vendors = extract_mib_archive_to_repo(
                content,
                target_mibs_dir=MIBS_DIR,
                max_files=settings.SNMP_MIB_UPLOAD_MAX_FILES,
                max_uncompressed_bytes=settings.SNMP_MIB_UPLOAD_MAX_UNCOMPRESSED_BYTES,
            )
            if extracted_count == 0:
                raise HTTPException(
                    status_code=400,
                    detail="No valid MIB files found in uploaded ZIP archive.",
                )

            def _archive_sync_worker():
                global _librenms_sync_state
                _librenms_sync_state["running"] = True
                _librenms_sync_state["progress"] = f"Unpacked {extracted_count} MIB files; building symbol index and parsing..."
                _librenms_sync_state["started_at"] = time.time()
                try:
                    result = import_mibs_from_directory(mibs_dir=MIBS_DIR)
                    _librenms_sync_state["last_result"] = result
                    _librenms_sync_state["run_id"] = result.get("run_id")
                    _librenms_sync_state["progress"] = (
                        f"Finished: {result.get('imported', 0)} MIBs imported, "
                        f"{result.get('nodes', 0)} OID nodes"
                    )
                except Exception as exc:
                    logger.error("ZIP MIB sync worker failed: %s", exc)
                    _librenms_sync_state["progress"] = f"Error: {exc}"
                    _librenms_sync_state["last_result"] = {"success": False, "error": str(exc)}
                finally:
                    _librenms_sync_state["running"] = False

            background_tasks.add_task(_archive_sync_worker)
            return {
                "success": True,
                "async": True,
                "message": f"Successfully unpacked {extracted_count} MIB files. Full background indexing has started.",
                "extracted": extracted_count,
                "vendors": sorted(list(detected_vendors)),
                "state": _librenms_sync_state,
            }

    conn = get_db_connection()
    try:
        if lower_filename.endswith(".zip"):
            import_errors: list[dict[str, str]] = []
            results = parse_and_store_zip(
                conn,
                content,
                vendor=vendor,
                description=description,
                max_files=settings.SNMP_MIB_UPLOAD_MAX_FILES,
                max_uncompressed_bytes=settings.SNMP_MIB_UPLOAD_MAX_UNCOMPRESSED_BYTES,
                errors=import_errors,
            )
            conn.commit()
            if not results:
                conn.rollback()
                detail: dict[str, Any] = {
                    "message": "No valid MIB files (.mib/.my/.txt/.asn/.smi) found in zip archive",
                }
                if import_errors:
                    detail["errors"] = import_errors
                raise HTTPException(status_code=400, detail=detail)
            return {
                "success": True,
                "async": False,
                "message": f"Successfully parsed and imported {len(results)} MIB modules from zip archive",
                "data": results,
                "errors": import_errors,
                "imported": len(results),
                "failed": len(import_errors),
            }
        else:
            raw_text = content.decode("utf-8", errors="replace")
            res = parse_and_store_mib(
                conn,
                filename=filename,
                raw_text=raw_text,
                vendor=vendor,
                source_type="user_upload",
                description=description,
            )
            conn.commit()
            return {
                "success": True,
                "async": False,
                "message": f"Successfully parsed MIB module '{res['name']}' with {res['node_count']} OID nodes",
                "data": res,
            }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        logger.warning("MIB upload parsing failed for %s: %s", filename, exc)
        raise HTTPException(status_code=400, detail=f"Failed to parse MIB file: {exc}") from exc
    finally:
        conn.close()


@router.get("/platform-registry/mibs/{mib_id}")
def get_snmp_mib_detail(mib_id: str, user=require_role("Viewer")):
    """Get MIB module detail and its parsed symbol node tree."""
    conn = get_db_connection()
    try:
        detail = get_mib_detail(conn, mib_id)
        if not detail:
            raise HTTPException(status_code=404, detail="MIB module not found")
        return {
            "success": True,
            "data": detail,
        }
    finally:
        conn.close()


@router.delete("/platform-registry/mibs/{mib_id}")
def remove_snmp_mib(mib_id: str, user=require_role("Operator")):
    """Delete an imported MIB module and all its associated symbol nodes."""
    conn = get_db_connection()
    try:
        success = delete_mib(conn, mib_id)
        if not success:
            raise HTTPException(status_code=404, detail="MIB module not found")
        conn.commit()
        return {
            "success": True,
            "message": "MIB module deleted",
        }
    finally:
        conn.close()


@router.post("/devices")
def create_device(device: dict = Body(...)):
    conn = get_db_connection()
    device_id = device.get('id') or str(uuid.uuid4())
    try:
        platform, platform_profile_id, platform_source, platform_locked = _resolve_platform_binding(
            conn,
            device.get('platform_profile_id'),
            device.get('platform'),
            device_vendor=device.get('vendor'),
        )
    except HTTPException:
        conn.close()
        raise
    try:
        snmp_cpu_oid = _normalize_device_metric_oid(device.get('snmp_cpu_oid'), 'snmp_cpu_oid')
        snmp_memory_oid = _normalize_device_metric_oid(device.get('snmp_memory_oid'), 'snmp_memory_oid')
    except HTTPException:
        conn.close()
        raise
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
                device_category, function, zone, power_watts, credential_id, platform_profile_id,
                platform_source, platform_locked
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        ''', (
            device_id,
            device.get('hostname'),
            device.get('ip_address'),
            platform,
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
            device.get('function', ''),
            device.get('zone', 'Unknown') or 'Unknown',
            int(device.get('power_watts') or 0),
            credential_id,
            platform_profile_id or None,
            platform_source,
            platform_locked,
        ))
        conn.execute(
            'UPDATE devices SET site_id = ? WHERE id = ?',
            (_resolve_device_site_id(conn, device.get('site_id'), device.get('site')), device_id),
        )
        conn.execute(
            'UPDATE devices SET snmp_cpu_oid = ?, snmp_memory_oid = ? WHERE id = ?',
            (snmp_cpu_oid, snmp_memory_oid, device_id),
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
            details={'ip_address': device.get('ip_address'), 'platform': platform, 'platform_profile_id': platform_profile_id or None},
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
        row = conn.execute('SELECT hostname, asset_id FROM devices WHERE id = ?', (device_id,)).fetchone()
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
        conn.execute("DELETE FROM tag_assignments WHERE resource_type='device' AND resource_id = ?", (device_id,))
        # ``ip_inventory`` is a legacy derived projection and is not covered
        # by the foreign-key cascade on all supported PostgreSQL installations.
        conn.execute('DELETE FROM ip_inventory WHERE device_id = ?', (device_id,))
        # WAN links are device-owned records, but the original WAN migrations
        # intentionally omitted foreign keys for compatibility.  Remove the
        # link and its telemetry before deleting the device so the outbound
        # monitoring page cannot retain an undeletable orphan.
        from services.wan_link_service import delete_wan_links_for_device
        delete_wan_links_for_device(conn, device_id)
        conn.execute('DELETE FROM devices WHERE id = ?', (device_id,))
        # Credentials are managed resources and must survive asset/device
        # deletion. They can only be removed explicitly from the credential
        # center after all normal/admin device references are cleared.
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

        existing_device = dict(existing_row)
        try:
            snmp_cpu_oid = (
                _normalize_device_metric_oid(device.get('snmp_cpu_oid'), 'snmp_cpu_oid')
                if 'snmp_cpu_oid' in device
                else str(existing_device.get('snmp_cpu_oid') or '')
            )
            snmp_memory_oid = (
                _normalize_device_metric_oid(device.get('snmp_memory_oid'), 'snmp_memory_oid')
                if 'snmp_memory_oid' in device
                else str(existing_device.get('snmp_memory_oid') or '')
            )
        except HTTPException:
            raise
        clear_platform_binding = (
            'platform_profile_id' in device
            and device.get('platform_profile_id') in (None, '')
            and str(device.get('platform_source') or '').upper() == 'LEGACY'
        )
        platform, platform_profile_id, platform_source, platform_locked = _resolve_platform_binding(
            conn,
            device.get('platform_profile_id'),
            device.get('platform', existing_row['platform']),
            existing=existing_device,
            clear_existing=clear_platform_binding,
            device_vendor=device.get('vendor') or existing_device.get('vendor'),
        )

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
                device_category = ?, function = ?, zone = ?, power_watts = ?, credential_id = ?,
                snmp_cpu_oid = ?, snmp_memory_oid = ?
            WHERE id = ?
        ''', (
            device.get('hostname', ''),
            device.get('ip_address', ''),
            platform,
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
            device.get('function', ''),
            device.get('zone', 'Unknown') or 'Unknown',
            int(device.get('power_watts') or 0),
            credential_id,
            snmp_cpu_oid,
            snmp_memory_oid,
            device_id
        ))
        conn.execute(
            '''UPDATE devices
               SET platform_profile_id = ?, platform_source = ?, platform_locked = ?
               WHERE id = ?''',
            (platform_profile_id or None, platform_source, platform_locked, device_id),
        )
        conn.execute(
            'UPDATE devices SET site_id = ? WHERE id = ?',
            (_resolve_device_site_id(conn, device.get('site_id'), device.get('site')), device_id),
        )
        if existing_row['asset_id']:
            conn.execute(
                '''UPDATE physical_assets
                   SET lifecycle_status = ?, device_category = ?, function = ?, zone = ?, updated_at = ?
                   WHERE id = ?''',
                (
                    new_lifecycle,
                    device.get('device_category', ''),
                    device.get('function', ''),
                    device.get('zone', 'Unknown') or 'Unknown',
                    _utc_now(),
                    existing_row['asset_id'],
                ),
            )
        conn.commit()

        # Track lifecycle transition in audit details
        old_lifecycle = existing_row['lifecycle_status'] or 'staging'
        audit_details: dict = {
            'ip_address': device.get('ip_address'),
            'platform': platform,
            'platform_profile_id': platform_profile_id or None,
        }
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
    except HTTPException:
        raise
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
            f'SELECT id, asset_id, hostname, ip_address, {target_col} as target_pwd FROM devices WHERE id = ?',
            (device_id,),
        ).fetchone()
        if not row:
            return {"success": False, "message": "设备不存在"}
        
        pwd_to_decrypt = row['target_pwd']
        # Asset-management records keep the encrypted local role passwords on
        # physical_assets.  Fall back there for Plan-A linked devices whose
        # devices.* password columns are intentionally blank.
        if not pwd_to_decrypt and row['asset_id']:
            asset_row = conn.execute(
                f'SELECT {target_col} as target_pwd FROM physical_assets WHERE id = ?',
                (row['asset_id'],),
            ).fetchone()
            pwd_to_decrypt = asset_row['target_pwd'] if asset_row else ''
        
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
            details={'role': role, 'source': 'device_local'},
        )
        return {"success": True, "data": {"password": decrypted, "role": role}}
    finally:
        conn.close()


@router.post("/devices/{device_id}/reveal-password/copy")
def audit_device_password_copy(device_id: str, role: str = Query(default='admin'), user: dict = require_role("Administrator")):
    """Audit copying a device-local password without returning the secret."""
    valid_roles = {'normal', 'admin', 'enable'}
    if role not in valid_roles:
        return {"success": False, "message": f"无效的角色类型: {role}"}
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT id, hostname, asset_id FROM devices WHERE id = ?',
            (device_id,),
        ).fetchone()
        if not row:
            return {"success": False, "message": "设备不存在"}

        col = {'normal': 'normal_password', 'admin': 'admin_password', 'enable': 'enable_password'}[role]
        secret_row = conn.execute(
            f'SELECT {col} as target_pwd FROM devices WHERE id = ?',
            (device_id,),
        ).fetchone()
        target_pwd = secret_row['target_pwd'] if secret_row else ''
        if not target_pwd and row['asset_id']:
            asset_row = conn.execute(
                f'SELECT {col} as target_pwd FROM physical_assets WHERE id = ?',
                (row['asset_id'],),
            ).fetchone()
            target_pwd = asset_row['target_pwd'] if asset_row else ''
        if not target_pwd:
            return {"success": False, "message": f"该角色 ({role}) 尚未设置或轮换密码"}

        log_audit_event(
            event_type='PASSWORD_COPY',
            category='security',
            severity='high',
            status='success',
            summary=f"管理员复制了设备 {row['hostname']} 的 {role} 账号密码",
            actor_username=user.get('username', 'admin'),
            actor_role=user.get('role', 'Administrator'),
            target_type='device',
            target_id=device_id,
            device_id=device_id,
            details={'role': role, 'source': 'device_local'},
            conn=conn,
        )
        conn.commit()
        return {"success": True, "message": "已记录设备本地密码复制审计"}
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
    collector_credentials = resolve_collector_credentials(device_data)
    ip = device_data['ip_address']
    snmp_ip = collector_credentials['snmp'].get('server') or ip
    community = collector_credentials['snmp'].get('community') or ''
    port = collector_credentials['snmp'].get('port') or 161
    resolved_metrics = resolve_health_metric_profiles(device_data)

    if not snmp_ip:
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
            "metric_profile_id": resolved_metrics.get('profile_id') or None,
            "metric_profile_status": resolved_metrics.get('profile_status') or 'none',
            "metric_profile_source": resolved_metrics.get('profile_source') or 'template_not_applied',
            "metric_sources": resolved_metrics.get('metric_sources') or {},
            "collection_mode": "health_only",
        }

    import asyncio as _aio
    from services.snmp_service import _snmp_get, _snmp_walk, collect_device_info, collect_interface_health, collect_device_metrics

    results = {"success": False, "ip": snmp_ip, "port": port,
               "sys_name": None, "sys_descr": None, "response_ms": None, "error": None,
               "synced": False,
               "hardware_metrics": {}, "metric_details": {},
               "hardware_collection_status": "pending",
               "metric_profile_id": resolved_metrics.get('profile_id') or None,
               "metric_profile_status": resolved_metrics.get('profile_status') or 'none',
               "metric_profile_source": resolved_metrics.get('profile_source') or 'template_not_applied',
               "metric_sources": resolved_metrics.get('metric_sources') or {},
               "collection_mode": "health_only"}

    start = time.monotonic()
    try:
        # Step 1: 标准 System MIB（sysName + sysDescr）并行查询
        sys_name, sys_descr = await _aio.gather(
            _snmp_get(snmp_ip, community, '1.3.6.1.2.1.1.5.0', port, timeout=3),
            _snmp_get(snmp_ip, community, '1.3.6.1.2.1.1.1.0', port, timeout=3),
        )
        elapsed = round((time.monotonic() - start) * 1000)
        results['response_ms'] = elapsed

        if sys_name or sys_descr:
            results['success'] = True
            results['sys_name'] = sys_name
            results['sys_descr'] = sys_descr
        else:
            # Step 2: ifName (ifXTable) — 部分设备/SNMP view 不含 system MIB
            if_rows = await _snmp_walk(snmp_ip, community, '1.3.6.1.2.1.31.1.1.1.1', port, timeout=3, max_rows=3)
            if not if_rows:
                # Step 3: ifDescr (基础 IF-MIB RFC 1213) — 最广泛兼容
                if_rows = await _snmp_walk(snmp_ip, community, '1.3.6.1.2.1.2.2.1.2', port, timeout=3, max_rows=3)
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

    # ── 先同步健康快照，再在后台补齐设备详情与接口 ──────────────────────
    prefetched_metrics = None
    if results['success']:
        try:
            prefetched_metrics = await collect_device_metrics(
                snmp_ip,
                device_data.get('platform') or 'cisco_ios',
                community,
                port,
                custom_metrics=resolved_metrics.get('metrics') or {},
                device_id=str(device_data.get('id') or device_id),
                metric_profile_id=str(resolved_metrics.get('profile_id') or ''),
                bypass_cache=True,
                template_only=True,
            )
            hardware = prefetched_metrics.get('hardware_metrics') or {}
            results['hardware_metrics'] = {
                metric: hardware.get(metric)
                for metric in HEALTH_METRIC_KEYS
            }
            results['metric_details'] = prefetched_metrics.get('metric_details') or {}
            results['hardware_collection_status'] = (
                'success'
                if any(value is not None for value in results['hardware_metrics'].values())
                else 'no_data'
            )

            # Persist the health snapshot before returning the manual test
            # response.  This makes the inventory CPU/MEM column reflect the
            # same read and clears stale values such as a previous 65535°C
            # sentinel when the current read is invalid or unavailable.
            health_updates = {
                'cpu_usage': prefetched_metrics.get('cpu_usage'),
                'memory_usage': prefetched_metrics.get('memory_usage'),
                'temp': prefetched_metrics.get('temp'),
                'fan_status': prefetched_metrics.get('fan_status'),
                'psu_status': prefetched_metrics.get('psu_status'),
            }
            if isinstance(health_updates['fan_status'], bool):
                health_updates['fan_status'] = 'true' if health_updates['fan_status'] else 'false'
            if isinstance(health_updates['psu_status'], bool):
                health_updates['psu_status'] = 'true' if health_updates['psu_status'] else 'false'
            try:
                health_conn = get_db_connection()
                try:
                    health_conn.execute(
                        'UPDATE devices SET cpu_usage = ?, memory_usage = ?, temp = ?, fan_status = ?, psu_status = ? WHERE id = ?',
                        (*health_updates.values(), device_id),
                    )
                    health_conn.commit()
                    results['synced'] = True
                finally:
                    health_conn.close()
            except Exception as persist_exc:
                logger.warning('SNMP health snapshot persistence failed for %s: %s', snmp_ip, type(persist_exc).__name__)
        except Exception as exc:
            logger.warning('SNMP hardware prefetch failed for %s: %s', snmp_ip, type(exc).__name__)
            results['hardware_collection_status'] = 'failed'

        async def _background_sync(prefetched=None):
            try:
                platform = device['platform'] or 'cisco_ios'
                if prefetched is None:
                    dev_info, intf_data, metrics = await _aio.gather(
                        collect_device_info(snmp_ip, community, port),
                        collect_interface_health(
                            snmp_ip,
                            community,
                            port,
                            resolved_metrics.get('interface') or None,
                            template_only=True,
                        ),
                        collect_device_metrics(
                            snmp_ip,
                            platform,
                            community,
                            port,
                            custom_metrics=resolved_metrics.get('metrics') or {},
                            device_id=str(device_data.get('id') or device_id),
                            metric_profile_id=str(resolved_metrics.get('profile_id') or ''),
                            template_only=True,
                        ),
                    )
                else:
                    dev_info, intf_data = await _aio.gather(
                        collect_device_info(snmp_ip, community, port),
                        collect_interface_health(
                            snmp_ip,
                            community,
                            port,
                            resolved_metrics.get('interface') or None,
                            template_only=True,
                        ),
                    )
                    metrics = prefetched

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

                for field in ('cpu_usage', 'memory_usage', 'temp', 'fan_status', 'psu_status'):
                    if field in metrics:
                        updates[field] = metrics.get(field)

                # Device status columns remain TEXT for backward-compatible
                # SQLite/PostgreSQL schemas; persist the boolean contract as
                # canonical text and normalize it back to bool at API edges.
                if 'fan_status' in updates and isinstance(updates['fan_status'], bool):
                    updates['fan_status'] = 'true' if updates['fan_status'] else 'false'
                if 'psu_status' in updates and isinstance(updates['psu_status'], bool):
                    updates['psu_status'] = 'true' if updates['psu_status'] else 'false'

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
                                    id, device_id, interface_name, if_index, description, admin_status, oper_status,
                                    mac_address, speed, bandwidth, duplex, interface_type, switchport_mode, ip_enabled
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(device_id, interface_name) DO UPDATE SET
                                    if_index = excluded.if_index,
                                    description = excluded.description,
                                    admin_status = excluded.admin_status,
                                    oper_status = excluded.oper_status,
                                    speed = excluded.speed,
                                    bandwidth = excluded.bandwidth
                            ''', (f"intf-{uuid.uuid4().hex[:12]}", device_id, iname, iface.get('if_index'), desc, status, status, '', speed_bps, speed_bps, 'auto', 'physical', 'access', 0))
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

        _aio.create_task(_background_sync(prefetched_metrics))

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
        # User-initiated/manual operational-data collection should bypass default background collection plan limits.
        override_categories = set(categories) if categories else None
        res = collect_operational_data(
            device_info,
            categories=categories,
            auth_role=auth_role,
            policy_override_categories=override_categories,
        )
        _record_instant_execution(
            device_id, query_name, [], 'completed',
            platform=device_info.get('platform', 'unknown'),
            result_payload=res,
            device_info=device_info,
        )
        return res
    except ValueError as exc:
        _logger.exception("Failed operational-data collection for device %s", device_id)
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
