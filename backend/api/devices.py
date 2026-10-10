from fastapi import APIRouter, HTTPException, Body, Query, Depends, File, UploadFile, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from collections.abc import Mapping
import os
import uuid
import json
import re
import socket
import time
import logging
from typing import Annotated, Any, Literal, Optional
from database import get_db_connection
from services.audit_service import log_audit_event
from services.device_health_service import annotate_devices_with_health, normalize_hardware_status
from services.site_identity_service import canonical_site_name
from services.operational_data_service import collect_operational_data, collect_custom_command_data
from services.platform_identification_service import _canonical_vendor
from services.platform_registry_service import PLATFORM_CATALOG_METADATA, list_platform_vendor_names
from services import tag_service
from core.crypto import encrypt_credential, decrypt_credential
from core.config import settings
from core.rbac import authorize_resource, require_role
from services.vault_service import resolve_device_credentials, resolve_collector_credentials, write_credentials as vault_write, vault_available
from services.snmp_mib_service import (
    list_mibs_page,
    get_mib_repository_stats,
    count_mib_nodes,
    list_mib_node_vendors,
    get_mib_detail,
    delete_mib,
    parse_and_store_mib,
    parse_and_store_zip,
    extract_mib_archive_to_repo,
    search_mib_nodes,
    resolve_mib_nodes_for_oids,
    SUPPORTED_MIB_FILE_SUFFIXES,
)
from services.librenms_mib_service import (
    VENDOR_DIR_MAP,
    import_mibs_from_directory,
    LIBRENMS_BUNDLE_DIR,
    MIBS_DIR,
)
from services.librenms_rule_service import sync_rules_from_repository
from services.snmp_vendor_registry import ASSET_NETWORK_VENDORS, ASSET_SECURITY_VENDORS
from services.snmp_preset_service import (
    seed_builtin_mibs,
    reset_builtin_mibs,
)
from drivers.ssh_compat import (
    build_ssh_error_guidance,
    get_ssh_error_code,
    normalize_ssh_algorithm_profile,
)
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)
logger = _logger


router = APIRouter()


@router.api_route(
    "/platform-registry/snmp-metric-profiles",
    methods=["GET", "POST", "PUT", "DELETE"],
)
@router.api_route(
    "/platform-registry/snmp-metric-profiles/{legacy_path:path}",
    methods=["GET", "POST", "PUT", "DELETE"],
)
def reject_custom_snmp_metric_profiles(legacy_path: str = "", user=require_role("Operator")):
    """Prevent local OID profiles from becoming an alternate collection rule source."""
    raise HTTPException(
        status_code=410,
        detail={
            "code": "LIBRENMS_RULES_ONLY",
            "message": "Custom SNMP metric profiles are retired; collection uses only the pinned LibreNMS rule bundle.",
        },
    )


@router.get("/platform-registry/mibs/presets/models")
@router.get("/platform-registry/mibs/auto-match")
def reject_local_snmp_model_presets(user=require_role("Viewer")):
    """Retire static Nexora OID presets and identity-based local matching."""
    raise HTTPException(
        status_code=410,
        detail={
            "code": "LIBRENMS_RULES_ONLY",
            "message": "Local SNMP model presets are retired; use the pinned LibreNMS rule diagnostic.",
        },
    )


def _snmp_request_transport(
    snmp_credentials: Mapping[str, Any],
    requested_version: Any = None,
) -> tuple[str, str | Mapping[str, Any]]:
    """Select a read-only SNMP transport without exposing secrets to clients."""
    configured_version = str(snmp_credentials.get('version') or '').strip().casefold()
    requested_key = str(requested_version or '').strip().casefold()
    version_aliases = {
        '1': '1', 'v1': '1',
        '2': '2c', '2c': '2c', 'v2c': '2c',
        '3': '3', 'v3': '3', 'snmpv3': '3',
    }
    configured_version = version_aliases.get(configured_version, '')
    requested_version_key = version_aliases.get(requested_key, '')

    # The bound credential profile is authoritative for v3, even when older
    # clients still submit their default UI value of "2c".
    if configured_version == '3':
        error_code = str(snmp_credentials.get('configuration_error') or '').strip()
        configured = bool(snmp_credentials.get('configured', snmp_credentials.get('username')))
        if error_code or not configured:
            raise HTTPException(
                status_code=400,
                detail=f"Bound SNMPv3 credential profile is incomplete ({error_code or 'profile_missing'})",
            )
        return '3', snmp_credentials

    if requested_version_key == '3':
        raise HTTPException(status_code=400, detail='SNMP version 3 requires a bound SNMPv3 credential profile')

    version = requested_version_key or configured_version or '2c'
    community = str(snmp_credentials.get('community') or '').strip()
    if not community:
        raise HTTPException(status_code=400, detail='Matched asset has no usable SNMP credentials configured')
    return version, community


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')


def _tenant_id_from_authenticated_user(user: dict) -> str:
    """Return the non-empty tenant that owns a newly written device."""
    tenant_id = str(user.get('tenant_id') or '').strip() if isinstance(user, dict) else ''
    if not tenant_id:
        raise HTTPException(
            status_code=403,
            detail='Authenticated user is not assigned to a tenant',
        )
    return tenant_id


def _assert_operational_data_device_scope(user: dict, device: dict) -> None:
    """Require command execution access to the selected device's scope.

    Operational-data collection resolves device credentials and may perform
    SNMP/SSH requests.  Treat the device row as the object being authorized so
    a caller cannot use a guessed device id to cross tenant, site, or group
    boundaries.
    """
    device_id = str(device.get('id') or '')
    is_admin = user.get('role') == 'Administrator'
    user_tenant = str(user.get('tenant_id') or '').strip()
    device_tenant = str(device.get('tenant_id') or '').strip()

    # Non-admin users must be explicitly tenant-scoped and the device must
    # carry the same tenant.  This also fails closed for legacy rows without a
    # tenant instead of allowing credential-backed collection by id alone.
    if not is_admin and (not user_tenant or not device_tenant or user_tenant != device_tenant):
        raise HTTPException(status_code=403, detail={
            'code': 'RESOURCE_SCOPE_DENIED',
            'message': 'Device belongs to another or unscoped tenant',
            'device_id': device_id,
        })

    scope = {
        'tenant_id': device_tenant,
        'site_id': str(device.get('site_id') or device.get('site') or '').strip(),
        'device_group_id': str(device.get('device_group_id') or '').strip(),
    }
    if not authorize_resource(user, 'command', 'execute', **scope):
        raise HTTPException(status_code=403, detail={
            'code': 'RESOURCE_SCOPE_DENIED',
            'message': 'Insufficient permission for this device scope',
            'resource_type': 'command',
            'device_id': device_id,
        })


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


def _mib_vendor_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _platform_mib_vendor_map(platform_vendors: list[str]) -> dict[str, str]:
    allowed = {_mib_vendor_token(name): name for name in platform_vendors if str(name or '').strip()}
    allowed["standard"] = "Standard"
    for vendor_key, vendor_name in VENDOR_DIR_MAP.items():
        canonical = allowed.get(_mib_vendor_token(vendor_name))
        if canonical:
            allowed[_mib_vendor_token(vendor_key)] = canonical
    return allowed


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
        if clear_existing:
            raise HTTPException(
                status_code=409,
                detail={
                    'code': 'PLATFORM_BINDING_LOCKED',
                    'message': (
                        'Existing device platform binding cannot be cleared through ordinary device update; '
                        'use the administrator platform binding unbind endpoint.'
                    ),
                },
            )
        if submitted_profile_id and submitted_profile_id != existing_profile_id:
            raise HTTPException(
                status_code=409,
                detail={
                    'code': 'PLATFORM_BINDING_LOCKED',
                    'message': (
                        'Existing device platform binding cannot be replaced through ordinary device update; '
                        'use the administrator platform binding endpoint.'
                    ),
                },
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

    from services.platform_registry_service import normalize_platform_code
    platform = normalize_platform_code(str(fallback_platform or '').strip()) or 'cisco_ios'
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
        conn.execute(
            'UPDATE physical_assets SET ssh_algorithm_profile = ? WHERE id = ?',
            (normalize_ssh_algorithm_profile(device.get('ssh_algorithm_profile')), asset_id),
        )
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
    # A linked physical asset is the CMDB source of truth for the display
    # hostname. Keep the legacy device column as a fallback for unlinked rows.
    cmdb_hostname = str(sanitized.get('asset_hostname') or '').strip()
    if cmdb_hostname:
        sanitized['hostname'] = cmdb_hostname
    sanitized['ssh_algorithm_profile'] = normalize_ssh_algorithm_profile(
        sanitized.get('ssh_algorithm_profile')
    )
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
        'ssh_algorithm_profile': payload.get('ssh_algorithm_profile'),
        'check_mode': str(payload.get('check_mode') or 'quick').lower(),
        'port': payload.get('port') or payload.get('management_port'),
    }

    if not device_id:
        resolved['password'] = _resolve_payload_password(resolved.get('password'))
        return resolved

    conn = get_db_connection()
    try:
        row = conn.execute(
            '''SELECT d.*, pa.hostname AS asset_hostname
               FROM devices d
               LEFT JOIN physical_assets pa ON pa.id = d.asset_id
               WHERE d.id = ?''',
            (device_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail='Device not found')

    stored = dict(row)
    creds = resolve_device_credentials(stored)
    payload_password = payload.get('password')

    resolved['hostname'] = (
        stored.get('asset_hostname')
        or resolved['hostname']
        or stored.get('hostname')
    )
    resolved['ip_address'] = resolved['ip_address'] or stored.get('ip_address')
    resolved['username'] = resolved['username'] or creds['username'] or ''
    resolved['method'] = payload.get('method') or stored.get('connection_method') or 'ssh'
    resolved['platform'] = payload.get('platform') or stored.get('platform') or 'cisco_ios'
    resolved['ssh_algorithm_profile'] = (
        payload.get('ssh_algorithm_profile')
        or stored.get('ssh_algorithm_profile')
    )
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
    item['ssh_algorithm_profile'] = normalize_ssh_algorithm_profile(
        item.get('ssh_algorithm_profile')
    )
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


def _annotate_devices_with_platform_binding(conn, items: list) -> list:
    """Attach the concrete command/parser binding without changing device facts.

    ``devices.version`` is the software version collected from SNMP/CLI and
    must remain the source of truth for the device itself.  The registry
    profile is a separate automation concern (driver, command catalog and
    TextFSM/parser generation), so expose its display metadata as a nested
    object rather than overloading ``platform`` or ``version``.  The query is
    batched for the current page to avoid an N+1 lookup in the inventory UI.
    """
    if not items:
        return items
    profile_ids = list(dict.fromkeys(
        str(item.get('platform_profile_id') or '').strip()
        for item in items
        if str(item.get('platform_profile_id') or '').strip()
    ))
    profile_map: dict[str, dict[str, Any]] = {}
    if profile_ids:
        placeholders = ','.join('?' for _ in profile_ids)
        try:
            rows = conn.execute(
                f'''SELECT id, platform_code, name_zh, name_en, vendor,
                           parser_platform, source, status
                    FROM platform_profiles
                    WHERE id IN ({placeholders})''',
                tuple(profile_ids),
            ).fetchall()
            for row in rows:
                profile = dict(row)
                code = str(profile.get('platform_code') or '').strip().lower()
                metadata = PLATFORM_CATALOG_METADATA.get(code) or {}
                profile_map[str(profile.get('id') or '')] = {
                    'id': profile.get('id'),
                    'platform_code': profile.get('platform_code'),
                    'name_zh': profile.get('name_zh'),
                    'name_en': profile.get('name_en'),
                    'vendor': profile.get('vendor'),
                    'parser_platform': profile.get('parser_platform'),
                    'source': profile.get('source'),
                    'adaptation_version': metadata.get('version', 'common'),
                }
        except Exception as exc:
            # The registry migration is optional for a few legacy/read-only
            # fixtures.  Keep the device list usable and let the UI fall back
            # to the profile id when metadata is unavailable.
            _logger.warning('Failed to annotate platform binding metadata: %s', exc)

    for item in items:
        profile_id = str(item.get('platform_profile_id') or '').strip()
        item['platform_binding'] = profile_map.get(profile_id) if profile_id else None
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
                "COALESCE(NULLIF(pa.hostname, ''), d.hostname) LIKE ? OR d.ip_address LIKE ? OR d.sn LIKE ? OR "
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
            'hostname': "COALESCE(NULLIF(pa.hostname, ''), d.hostname)",
            'model': 'd.model',
            'platform': 'd.platform',
            'site': "COALESCE(NULLIF(s.site_name, ''), NULLIF(s.site_code, ''), d.site)",
            'connection_method': 'd.connection_method',
            'status': 'd.status',
            'ip_address': 'd.ip_address',
            'role': 'd.role',
        }
        order_col = sortable_columns.get(
            sort_key or '',
            "COALESCE(NULLIF(pa.hostname, ''), d.hostname)",
        )
        order_dir = 'DESC' if str(sort_direction).lower() == 'desc' else 'ASC'

        # Plan-A: LEFT JOIN physical_assets to surface asset metadata
        asset_cols = (
            ', pa.asset_tag, pa.serial_number AS asset_serial_number, '
            'pa.hostname AS asset_hostname, pa.vendor AS asset_vendor, '
            'pa.model AS asset_model, pa.asset_type, '
            'pa.management_ip AS asset_management_ip, pa.business_ip AS asset_business_ip, '
            'pa.business_ip, '
            'pa.site_id AS asset_site_id, pa.rack, pa.rack_unit, '
            'pa.department, pa.warranty_expiry, pa.purchase_date, '
            'pa.vlan, pa.uplink_switch, pa.uplink_port, '
            'pa.lifecycle_status AS asset_lifecycle_status, pa.status AS asset_status, '
            'COALESCE(NULLIF(pa.site_id, \'\'), NULLIF(d.site_id, \'\'), \'\') AS canonical_site_id, '
            's.site_name, s.site_code, s.country AS site_country, '
            's.state_province AS site_state_province, s.city AS site_city, '
            's.district AS site_district, '
            'COALESCE(NULLIF(r.id, \'\'), NULLIF(r_legacy.id, \'\'), \'\') AS cmdb_rack_id, '
            'COALESCE(NULLIF(r.rack_code, \'\'), NULLIF(r_legacy.rack_code, \'\'), \'\') AS rack_code, '
            'COALESCE(NULLIF(TRIM(r.name), \'\'), NULLIF(TRIM(r_legacy.name), \'\'), NULLIF(TRIM(r.rack_name), \'\'), NULLIF(TRIM(r_legacy.rack_name), \'\'), \'\') AS rack_name, '
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
            ', COALESCE(pa.winrm_enabled, FALSE) AS winrm_enabled'
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
                'd.device_category, d.management_port, d.lifecycle_status, d.ssh_algorithm_profile, '
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
            items = _annotate_devices_with_platform_binding(conn, items)
            items = _annotate_devices_with_tags(conn, items)
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

        items = _annotate_devices_with_platform_binding(conn, items)
        items = _annotate_devices_with_tags(conn, items)
        return {
            'items': annotate_devices_with_health(conn, items),
            'total': total,
            'page': page,
            'page_size': page_size,
            'status_counts': status_counts,
        }
    finally:
        conn.close()


@router.get("/devices/summary")
def read_devices_summary(
    asset_type: Optional[str] = Query(default='network_device'),
    user=require_role("Viewer"),
):
    """Return database-only device counters for the complete asset filter set.

    Keep this endpoint independent from the device-list enrichment pipeline:
    dashboard callers only need aggregate state and platform counts, and the
    joined asset rows must never turn one device into multiple counts.
    """
    conn = get_db_connection()
    try:
        where_clauses = []
        params = []

        if asset_type and asset_type != 'all':
            # Match /devices: an unlinked device is treated as a network
            # device, while a linked asset keeps its explicit asset_type.
            where_clauses.append(
                "(CASE WHEN pa.asset_type IS NOT NULL THEN pa.asset_type "
                "ELSE 'network_device' END) = ?"
            )
            params.append(asset_type)

        # Device rows are tenant-owned.  Administrators retain the existing
        # cross-tenant read behavior; all other sessions use the same default
        # tenant fallback as the monitoring read APIs.
        if isinstance(user, dict) and user.get('role') != 'Administrator':
            tenant_id = str(user.get('tenant_id') or 'tenant-default').strip() or 'tenant-default'
            where_clauses.append("COALESCE(d.tenant_id, 'tenant-default') = ?")
            params.append(tenant_id)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ''
        platform_expr = "COALESCE(NULLIF(TRIM(d.platform), ''), 'unknown')"
        status_expr = "LOWER(TRIM(COALESCE(d.status, '')))"

        # Aggregate status and platform counts in one query.  COUNT(DISTINCT)
        # keeps the result stable if a legacy/auxiliary join ever yields more
        # than one matching row for a device.
        rows = conn.execute(
            f'''
            SELECT {platform_expr} AS platform,
                   COUNT(DISTINCT d.id) AS platform_count,
                   COUNT(DISTINCT CASE WHEN {status_expr} = 'online' THEN d.id END) AS online_count,
                   COUNT(DISTINCT CASE WHEN {status_expr} = 'offline' THEN d.id END) AS offline_count,
                   COUNT(DISTINCT CASE WHEN {status_expr} = 'pending' THEN d.id END) AS pending_count,
                   COUNT(DISTINCT CASE WHEN {status_expr} NOT IN ('online', 'offline', 'pending')
                                       THEN d.id END) AS unknown_count
              FROM devices d
              LEFT JOIN physical_assets pa ON pa.id = d.asset_id
              {where_sql}
             GROUP BY {platform_expr}
             ORDER BY {platform_expr}
            ''',
            tuple(params),
        ).fetchall()

        summary = {
            'total': 0,
            'online': 0,
            'offline': 0,
            'pending': 0,
            'unknown': 0,
            'by_platform': [],
        }
        for row in rows:
            summary['total'] += int(row['platform_count'] or 0)
            summary['online'] += int(row['online_count'] or 0)
            summary['offline'] += int(row['offline_count'] or 0)
            summary['pending'] += int(row['pending_count'] or 0)
            summary['unknown'] += int(row['unknown_count'] or 0)
            summary['by_platform'].append({
                'platform': str(row['platform'] or 'unknown'),
                'count': int(row['platform_count'] or 0),
            })
        return summary
    finally:
        conn.close()



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
        allowed_vendors = [*list_platform_vendor_names(conn), "Standard"]
        mibs, total = list_mibs_page(
            conn,
            search=search,
            vendor=vendor,
            page=page,
            page_size=page_size,
            status=status,
            allowed_vendors=allowed_vendors,
        )
        return {
            "success": True,
            "data": mibs,
            "total": total,
            "page": page,
            "page_size": page_size,
            "stats": get_mib_repository_stats(
                conn,
                search=search,
                vendor=vendor,
                status=status,
                allowed_vendors=allowed_vendors,
            ),
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
        nodes = search_mib_nodes(
            conn,
            query=query,
            vendor=vendor,
            mib_id=mib_id,
            limit=limit,
            scope=scope,
            allowed_vendors=[*ASSET_NETWORK_VENDORS, *ASSET_SECURITY_VENDORS, 'Standard'],
        )
        return {
            "success": True,
            "data": nodes,
            "total": len(nodes),
        }
    finally:
        conn.close()


@router.get("/platform-registry/mibs/nodes")
def list_snmp_mib_nodes(
    q: str = Query("", max_length=128),
    category: Literal["public", "private"] = Query("public"),
    vendor: str = Query("", max_length=64),
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(20, ge=10, le=100),
    user=require_role("Viewer"),
):
    """Return a paginated public-standard or vendor-private MIB symbol catalog."""
    conn = get_db_connection()
    try:
        count_row = conn.execute("SELECT COUNT(*) AS c FROM snmp_mibs").fetchone()
        if not count_row or int(count_row[0] if isinstance(count_row, tuple) else count_row["c"]) == 0:
            seed_builtin_mibs()
        search = (q or "").strip()
        allowed_vendors = (
            [*ASSET_NETWORK_VENDORS, *ASSET_SECURITY_VENDORS]
            if category == "private"
            else None
        )
        total = count_mib_nodes(
            conn,
            query=search,
            vendor=vendor,
            category=category,
            allowed_vendors=allowed_vendors,
        )
        safe_page_size = max(10, min(100, int(page_size)))
        safe_page = max(1, int(page))
        nodes = search_mib_nodes(
            conn,
            query=search,
            vendor=vendor,
            limit=safe_page_size,
            offset=(safe_page - 1) * safe_page_size,
            category=category,
            allowed_vendors=allowed_vendors,
        )
        return {
            "success": True,
            "data": nodes,
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "category": category,
            "vendor": vendor,
            "vendors": list_mib_node_vendors(
                conn,
                category=category,
                allowed_vendors=allowed_vendors,
            ),
            "query": search,
        }
    finally:
        conn.close()




_librenms_sync_state: dict[str, Any] = {
    "running": False,
    "progress": "idle",
    "run_id": None,
    "started_at": None,
}


@router.post("/platform-registry/mibs/sync-librenms")
async def trigger_sync_librenms_mibs(
    background_tasks: BackgroundTasks,
    vendors: str = Query("", description="Comma-separated registered platform vendors; empty selects all platform vendors and standard MIBs"),
    user=require_role("Operator"),
):
    """Index the project-bundled LibreNMS MIB snapshot for platform vendors."""
    global _librenms_sync_state
    if _librenms_sync_state["running"]:
        return {
            "success": True,
            "message": "LibreNMS MIB synchronization is already running",
            "state": _librenms_sync_state,
        }

    platform_vendors = list_platform_vendor_names()
    if not platform_vendors:
        raise HTTPException(status_code=409, detail="No platform vendors are registered for LibreNMS MIB synchronization")

    allowed_vendor_map = _platform_mib_vendor_map(platform_vendors)
    requested_vendors = [value.strip() for value in vendors.split(",") if value.strip()]
    if requested_vendors:
        unknown_vendors = [value for value in requested_vendors if _mib_vendor_token(value) not in allowed_vendor_map]
        if unknown_vendors:
            raise HTTPException(
                status_code=400,
                detail="LibreNMS MIB sync only accepts vendors registered in the platform",
            )
        scoped_vendors = list(dict.fromkeys(allowed_vendor_map[_mib_vendor_token(value)] for value in requested_vendors))
        retire_out_of_scope = False
    else:
        scoped_vendors = list(platform_vendors)
        retire_out_of_scope = True
    if "standard" not in {_mib_vendor_token(value) for value in scoped_vendors}:
        scoped_vendors.append("Standard")

    def _sync_worker(target_vendors_list: list[str], retire_unlisted_vendors: bool):
        global _librenms_sync_state
        _librenms_sync_state["running"] = True
        _librenms_sync_state["progress"] = "Loading the project-local LibreNMS source bundle..."
        _librenms_sync_state["started_at"] = time.time()
        try:
            _librenms_sync_state["progress"] = "Parsing bundled MIB definitions into the local catalog..."
            result = import_mibs_from_directory(
                mibs_dir=MIBS_DIR,
                target_vendors=target_vendors_list,
                retire_out_of_scope=retire_unlisted_vendors,
                retire_missing_files=False,
            )
            result["platform_vendor_scope"] = target_vendors_list
            rule_result = sync_rules_from_repository(LIBRENMS_BUNDLE_DIR)
            result["librenms_rules"] = rule_result
            _librenms_sync_state["last_result"] = result
            _librenms_sync_state["run_id"] = result.get("run_id")
            _librenms_sync_state["progress"] = f"Finished: {result.get('imported', 0)} MIBs imported, {result.get('nodes', 0)} OID nodes, {rule_result.get('imported', 0)} LibreNMS OS rules"
        except Exception as exc:
            logger.error("LibreNMS MIB sync worker failed: %s", exc)
            _librenms_sync_state["progress"] = f"Error: {exc}"
            _librenms_sync_state["last_result"] = {"success": False, "error": str(exc)}
        finally:
            _librenms_sync_state["running"] = False

    background_tasks.add_task(_sync_worker, scoped_vendors, retire_out_of_scope)

    return {
        "success": True,
        "message": "Project-local LibreNMS MIB indexing started for registered platform vendors",
        "vendor_scope": scoped_vendors,
        "state": _librenms_sync_state,
    }


@router.get("/platform-registry/mibs/sync-librenms/status")
def get_sync_librenms_mibs_status(user=require_role("Viewer")):
    """Get the current progress status of LibreNMS MIB synchronization."""
    conn = get_db_connection()
    try:
        rule_count = conn.execute("SELECT COUNT(*) AS count FROM snmp_librenms_rules").fetchone()
        allowed_vendors = [*list_platform_vendor_names(conn), "Standard"]
        return {
            "success": True,
            "data": {
                **_librenms_sync_state,
                "repository": get_mib_repository_stats(conn, allowed_vendors=allowed_vendors),
                "librenms_rule_count": int((rule_count["count"] if rule_count else 0) or 0),
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
            platform_vendor_scope = [*list_platform_vendor_names(), "Standard"]
            allowed_vendors = _platform_mib_vendor_map(platform_vendor_scope)
            detected_platform_vendors = sorted({
                allowed_vendors[_mib_vendor_token(value)]
                for value in detected_vendors
                if _mib_vendor_token(value) in allowed_vendors
            })

            def _archive_sync_worker():
                global _librenms_sync_state
                _librenms_sync_state["running"] = True
                _librenms_sync_state["progress"] = f"Unpacked {extracted_count} MIB files; importing only platform-supported vendors..."
                _librenms_sync_state["started_at"] = time.time()
                try:
                    result = import_mibs_from_directory(
                        mibs_dir=MIBS_DIR,
                        target_vendors=platform_vendor_scope,
                        retire_missing_files=False,
                    )
                    result["platform_vendor_scope"] = platform_vendor_scope
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
                "vendors": detected_platform_vendors,
                "platform_vendor_scope": platform_vendor_scope,
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
def create_device(device: dict = Body(...), user=require_role("Operator")):
    tenant_id = _tenant_id_from_authenticated_user(user)
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
                id, tenant_id, hostname, ip_address, platform, status, compliance, username, password,
                sn, model, version, role, site, uptime, connection_method, snmp_community, 
                snmp_port, lifecycle_status, enable_password, priv_username, credential_source, 
                vault_path, normal_username, normal_password, admin_username, admin_password, auth_model,
                device_category, function, zone, power_watts, credential_id, platform_profile_id,
                platform_source, platform_locked
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        ''', (
            device_id,
            tenant_id,
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
            'UPDATE devices SET ssh_algorithm_profile = ? WHERE id = ?',
            (normalize_ssh_algorithm_profile(device.get('ssh_algorithm_profile')), device_id),
        )
        tag_service.sync_device_status_tag(conn, device_id, device.get('status', 'pending'))
        # Plan-A: auto-create linked physical_assets record
        _create_linked_asset_for_device(conn, device_id, device)
        conn.commit()
        try:
            from services.collector_sync_service import trigger_async_monitoring_sync
            trigger_async_monitoring_sync()
        except Exception:
            pass
        new_device = conn.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
        log_audit_event(
            event_type='DEVICE_CREATE',
            category='inventory',
            severity='medium',
            status='success',
            summary=f"Created device {device.get('hostname')}",
            actor_username=user.get('username') or 'system',
            actor_role=user.get('role') or 'Operator',
            target_type='device',
            target_id=device_id,
            target_name=device.get('hostname'),
            device_id=device_id,
            details={
                'ip_address': device.get('ip_address'),
                'platform': platform,
                'platform_profile_id': platform_profile_id or None,
                'ssh_algorithm_profile': normalize_ssh_algorithm_profile(
                    device.get('ssh_algorithm_profile')
                ),
            },
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
            # A direct device delete must remove the canonical rack placement
            # before deleting the linked physical asset.  The asset-delete
            # endpoint already performs this cleanup, but this endpoint is
            # also used by the network-device inventory page.  Leaving the
            # rack_devices row behind makes a later re-import fail with a
            # false U-position conflict.
            rack_device_rows = conn.execute(
                'SELECT id FROM rack_devices WHERE asset_id = ?', (row['asset_id'],)
            ).fetchall()
            if rack_device_rows:
                from services import rack_service
                for rack_device_row in rack_device_rows:
                    rack_service.delete_rack_device(conn, rack_device_row['id'], commit=False)
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
        try:
            from services.collector_sync_service import trigger_async_monitoring_sync
            trigger_async_monitoring_sync()
        except Exception:
            pass
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
        existing_row = conn.execute(
            '''SELECT d.*, pa.hostname AS asset_hostname
               FROM devices d
               LEFT JOIN physical_assets pa ON pa.id = d.asset_id
               WHERE d.id = ?''',
            (device_id,),
        ).fetchone()
        if not existing_row:
            raise HTTPException(status_code=404, detail='Device not found')

        existing_device = dict(existing_row)
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
        cmdb_hostname = ''
        if existing_device.get('asset_id'):
            # Serialize the mirror with asset/SNMP name updates. Lock the
            # CMDB asset before UPDATE devices, matching hostname sync order.
            current_asset = conn.execute(
                'SELECT hostname FROM physical_assets WHERE id = ? FOR UPDATE',
                (existing_device['asset_id'],),
            ).fetchone()
            cmdb_hostname = str(current_asset['hostname'] or '').strip() if current_asset else ''
        effective_hostname = cmdb_hostname or device.get('hostname', '')

        conn.execute('''
            UPDATE devices 
            SET hostname = ?, ip_address = ?, platform = ?, sn = ?, model = ?, version = ?, role = ?, site = ?, connection_method = ?, 
                username = ?, password = ?, current_config = ?, config_history = ?, snmp_community = ?, snmp_port = ?, 
                lifecycle_status = ?, enable_password = ?, priv_username = ?, credential_source = ?, vault_path = ?,
                normal_username = ?, normal_password = ?, admin_username = ?, admin_password = ?, auth_model = ?,
                device_category = ?, function = ?, zone = ?, power_watts = ?, credential_id = ?
            WHERE id = ?
        ''', (
            effective_hostname,
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
            device_id
        ))
        conn.execute(
            '''UPDATE devices
               SET platform_profile_id = ?, platform_source = ?, platform_locked = ?
               WHERE id = ?''',
            (platform_profile_id or None, platform_source, platform_locked, device_id),
        )
        if 'ssh_algorithm_profile' in device:
            profile = normalize_ssh_algorithm_profile(device.get('ssh_algorithm_profile'))
            conn.execute(
                'UPDATE devices SET ssh_algorithm_profile = ? WHERE id = ?',
                (profile, device_id),
            )
            if existing_device.get('asset_id'):
                conn.execute(
                    'UPDATE physical_assets SET ssh_algorithm_profile = ? WHERE id = ?',
                    (profile, existing_device['asset_id']),
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
        try:
            from services.collector_sync_service import trigger_async_monitoring_sync
            trigger_async_monitoring_sync()
        except Exception:
            pass

        # Track lifecycle transition in audit details
        old_lifecycle = existing_row['lifecycle_status'] or 'staging'
        audit_details: dict = {
            'ip_address': device.get('ip_address'),
            'platform': platform,
            'platform_profile_id': platform_profile_id or None,
            'ssh_algorithm_profile': normalize_ssh_algorithm_profile(
                device.get('ssh_algorithm_profile')
                if 'ssh_algorithm_profile' in device
                else existing_device.get('ssh_algorithm_profile')
            ),
        }
        if old_lifecycle != new_lifecycle:
            audit_details['lifecycle_transition'] = f"{old_lifecycle} → {new_lifecycle}"

        log_audit_event(
            event_type='DEVICE_UPDATE',
            category='inventory',
            severity='high' if new_lifecycle == 'production' and old_lifecycle != 'production' else 'medium',
            status='success',
            summary=f"Updated device {effective_hostname or device_id}" + (f" [lifecycle: {old_lifecycle} → {new_lifecycle}]" if old_lifecycle != new_lifecycle else ''),
            actor_username=device.get('actor_username') or 'admin',
            actor_role=device.get('actor_role') or 'Administrator',
            target_type='device',
            target_id=device_id,
            target_name=effective_hostname or device_id,
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


@router.get("/devices/rotation/credentials/{credential_id}/devices")
def rotation_credential_devices(
    credential_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: str = Query(default='', max_length=200),
    platform: str = Query(default='', max_length=100),
    user=require_role("Administrator"),
):
    """Search and page through device metadata bound to one shared credential."""
    from services.password_rotation_service import list_credential_bound_devices
    return {
        "success": True,
        "data": list_credential_bound_devices(
            credential_id=credential_id,
            page=page,
            page_size=page_size,
            keyword=keyword,
            platform=platform,
        ),
    }


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
        'ssh_algorithm_profile': resolved.get('ssh_algorithm_profile'),
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
def import_devices(payload: dict = Body(...), user=require_role("Operator")):
    tenant_id = _tenant_id_from_authenticated_user(user)
    devices = payload.get('devices', [])
    if not isinstance(devices, list):
        raise HTTPException(status_code=400, detail="Invalid data format")
    
    conn = get_db_connection()
    try:
        for device in devices:
            device_id = device.get('id') or str(uuid.uuid4())
            conn.execute('''
                INSERT INTO devices (id, tenant_id, hostname, ip_address, platform, status, compliance, sn, model, version, role, site, uptime, connection_method)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                device_id,
                tenant_id,
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
        try:
            from services.collector_sync_service import trigger_async_monitoring_sync
            trigger_async_monitoring_sync()
        except Exception:
            pass
        log_audit_event(
            event_type='DEVICE_IMPORT',
            category='inventory',
            severity='medium',
            status='success',
            summary=f"Imported {len(devices)} device(s)",
            actor_username=user.get('username') or 'system',
            actor_role=user.get('role') or 'Operator',
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
async def snmp_test(device_id: str, user=require_role("Operator")):
    """Run an on-demand probe through the pinned LibreNMS rule executor only."""
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Device not found")

    device = dict(row)
    _assert_snmp_diagnostic_device_scope(user, device)
    from services.snmp_hardware_poller_service import inspect_librenms_hardware_rules
    from services.librenms_source_policy import is_trusted_hardware_sensor, verify_bundled_rule

    probe = await inspect_librenms_hardware_rules(device)
    identity = probe.get("identity") if isinstance(probe.get("identity"), Mapping) else {}
    rule = probe.get("rule") if isinstance(probe.get("rule"), Mapping) else None
    if not verify_bundled_rule(rule or {}):
        rule = None
    sensors = [
        sensor for sensor in (probe.get("sensors") or [])
        if isinstance(sensor, Mapping) and is_trusted_hardware_sensor(sensor)
    ]
    reachable = any(str(identity.get(key) or "").strip() for key in ("sys_name", "sys_descr", "sys_object_id"))
    return {
        "success": reachable,
        "ip": str(device.get("ip_address") or ""),
        "sys_name": str(identity.get("sys_name") or ""),
        "sys_descr": str(identity.get("sys_descr") or ""),
        "sys_object_id": str(identity.get("sys_object_id") or ""),
        "response_ms": None,
        "error": "No SNMP system identity was returned" if not reachable else None,
        "hardware_metrics": {},
        "metric_details": {},
        "hardware_collection_status": str(probe.get("status") or "unknown"),
        "snmp_discovery_status": "matched" if rule else "unsupported",
        "collection_mode": "pinned_librenms_rule_diagnostic",
        "rule": rule,
        "rule_source_path": str((rule or {}).get("source_path") or ""),
        "rule_source_commit": str((rule or {}).get("source_commit") or ""),
        "sensor_count": len(sensors),
        "sensors": sensors,
        "category_results": probe.get("category_results") or [],
    }


def _assert_snmp_diagnostic_device_scope(user: dict, device: dict) -> None:
    """Require tenant and asset-view scope before any credential-backed probe."""
    if not isinstance(user, dict):
        raise HTTPException(status_code=403, detail="Authenticated device scope is required")
    if user.get("role") == "Administrator":
        return

    user_tenant = str(user.get("tenant_id") or "").strip()
    device_tenant = str(device.get("site_tenant_id") or device.get("tenant_id") or "").strip()
    if not user_tenant or not device_tenant or user_tenant != device_tenant:
        raise HTTPException(
            status_code=403,
            detail={"code": "RESOURCE_SCOPE_DENIED", "message": "Device belongs to another or unscoped tenant"},
        )
    if not authorize_resource(
        user,
        "asset",
        "view",
        tenant_id=device_tenant,
        site_id=str(device.get("resolved_site_id") or device.get("site_id") or device.get("site") or "").strip(),
        device_group_id=str(device.get("device_group_id") or "").strip(),
    ):
        raise HTTPException(
            status_code=403,
            detail={"code": "RESOURCE_SCOPE_DENIED", "message": "Insufficient permission for this device scope"},
        )


def _find_snmp_walk_targets(
    *,
    device_id: str = "",
    ip: str = "",
    user: dict | None = None,
) -> list[dict[str, Any]]:
    """Resolve only exact, CMDB-managed device IDs or addresses."""
    normalized_device_id = str(device_id or "").strip()
    normalized_ip = str(ip or "").strip()
    if bool(normalized_device_id) == bool(normalized_ip):
        return []
    where_sql = "d.id = ?" if normalized_device_id else "(d.ip_address = ? OR pa.management_ip = ?)"
    params = (normalized_device_id,) if normalized_device_id else (normalized_ip, normalized_ip)
    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"""SELECT d.*, COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, '')) AS resolved_site_id,
                       s.tenant_id AS site_tenant_id
                  FROM devices d
                  LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                  LEFT JOIN sites s ON s.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''))
                 WHERE {where_sql}
                 ORDER BY d.id
                 LIMIT 2""",
            params,
        ).fetchall()
    finally:
        conn.close()

    targets = [dict(row) for row in rows]
    for target in targets:
        if user is not None:
            _assert_snmp_diagnostic_device_scope(user, target)
    return targets


@router.get("/platform-registry/snmp-walk-target")
def resolve_snmp_walk_target(ip: str = Query(..., min_length=1, max_length=128), user=require_role("Operator")):
    """Resolve a manually entered IP to exactly one visible CMDB device."""
    targets = _find_snmp_walk_targets(ip=ip.strip(), user=user)
    if not targets:
        raise HTTPException(status_code=404, detail={"code": "DEVICE_NOT_FOUND", "message": "IP not found in managed devices"})
    if len(targets) != 1:
        raise HTTPException(status_code=409, detail={"code": "DEVICE_IP_AMBIGUOUS", "message": "IP resolves to more than one managed device"})
    target = targets[0]
    return {"success": True, "data": {
        "ip": str(target.get("ip_address") or ip).strip(),
        "device_id": str(target.get("id") or ""),
        "hostname": str(target.get("hostname") or ""),
    }}


@router.post("/platform-registry/snmp-librenms-rule-test")
async def test_librenms_rule_probe(payload: dict = Body(...), user=require_role("Operator")):
    """Probe one managed device with the pinned LibreNMS YAML rule executor."""
    if not isinstance(payload, dict) or set(payload) != {"device_id"} or not str(payload.get("device_id") or "").strip():
        raise HTTPException(status_code=400, detail={
            "code": "MANUAL_OID_PROBE_DISABLED",
            "message": "Only a managed device_id is accepted; custom OIDs and target credentials are disabled.",
        })
    targets = _find_snmp_walk_targets(device_id=str(payload["device_id"]).strip(), user=user)
    if not targets:
        raise HTTPException(status_code=404, detail={"code": "DEVICE_NOT_FOUND", "message": "Managed device not found"})
    device = targets[0]
    from services.snmp_hardware_poller_service import inspect_librenms_hardware_rules
    from services.librenms_source_policy import is_trusted_hardware_sensor, verify_bundled_rule

    probe = await inspect_librenms_hardware_rules(device)
    rule = probe.get("rule") if isinstance(probe.get("rule"), Mapping) else None
    if not verify_bundled_rule(rule or {}):
        rule = None
    sensors = [
        sensor for sensor in (probe.get("sensors") or [])
        if isinstance(sensor, Mapping) and is_trusted_hardware_sensor(sensor)
    ]
    identity = probe.get("identity") if isinstance(probe.get("identity"), Mapping) else {}
    data = {
        "status": str(probe.get("status") or "unknown"),
        "message": str(probe.get("reason") or probe.get("message") or ""),
        "identity": dict(identity),
        "rule": dict(rule) if rule else None,
        "rule_source_path": str((rule or {}).get("source_path") or ""),
        "rule_source_commit": str((rule or {}).get("source_commit") or ""),
        "sensor_count": len(sensors),
        "sensors": sensors,
        "category_results": probe.get("category_results") or [],
    }
    return {"success": bool(rule), "data": data}


@router.post("/platform-registry/snmp-hardware-discovery-test")
async def test_snmp_hardware_discovery(payload: dict = Body(...), user=require_role("Operator")):
    """Read saved hardware inventory; values must pass pinned-rule provenance checks."""
    if not isinstance(payload, dict) or set(payload) != {"device_id"} or not str(payload.get("device_id") or "").strip():
        raise HTTPException(status_code=400, detail={"code": "DEVICE_ID_REQUIRED", "message": "A managed device_id is required"})
    targets = _find_snmp_walk_targets(device_id=str(payload["device_id"]).strip(), user=user)
    if not targets:
        raise HTTPException(status_code=404, detail={"code": "DEVICE_NOT_FOUND", "message": "Managed device not found"})
    from services.librenms_diagnostic_service import diagnose_librenms_hardware
    return {"success": True, "data": await diagnose_librenms_hardware(targets[0])}


@router.post("/platform-registry/snmp-system-lldp-test")
async def test_snmp_system_lldp(payload: dict = Body(...), user=require_role("Operator")):
    """Read standard MIB-2 system scalars and LLDP for one scoped CMDB device."""
    if (
        not isinstance(payload, dict)
        or set(payload) != {"device_id"}
        or not isinstance(payload.get("device_id"), str)
        or not payload["device_id"].strip()
    ):
        raise HTTPException(status_code=400, detail={
            "code": "DEVICE_ID_REQUIRED",
            "message": "Only a managed device_id is accepted for this diagnostic.",
        })

    device_id = payload["device_id"].strip()
    targets = _find_snmp_walk_targets(device_id=device_id, user=user)
    if not targets:
        raise HTTPException(status_code=404, detail={
            "code": "DEVICE_NOT_FOUND",
            "message": "Managed device not found",
        })
    device = targets[0]

    from services.snmp_service import (
        SYS_CONTACT,
        SYS_DESCR,
        SYS_LOCATION,
        SYS_NAME,
        SYS_OBJECT_ID,
        SYS_UPTIME,
        _snmp_get_versioned,
        collect_snmp_lldp_neighbors,
        parse_snmp_uptime_seconds,
    )

    hostname = str(device.get("hostname") or "").strip()
    system_info: dict[str, Any] = {
        "sys_name": None,
        "sys_descr": None,
        "sys_object_id": None,
        "sys_uptime": None,
        "uptime": None,
        "uptime_seconds": None,
        "sys_location": None,
        "sys_contact": None,
    }
    lldp: dict[str, Any] = {
        "status": "unsupported",
        "neighbors": [],
        "truncated_oids": [],
        "max_rows": None,
        "message": "Bound SNMP credentials are unavailable.",
    }
    data: dict[str, Any] = {
        "device_id": str(device.get("id") or device_id),
        "hostname": hostname,
        "host": str(device.get("ip_address") or "").strip(),
        "version": None,
        "status": "unsupported",
        "system_info": system_info,
        "lldp": lldp,
    }

    try:
        credentials = resolve_collector_credentials(device)
        snmp_credentials = credentials.get("snmp") if isinstance(credentials, Mapping) else None
        if not isinstance(snmp_credentials, Mapping):
            raise ValueError("SNMP credential profile is unavailable")
        host = str(snmp_credentials.get("server") or device.get("ip_address") or "").strip()
        data["host"] = host
        try:
            version, transport_credentials = _snmp_request_transport(snmp_credentials)
        except HTTPException:
            # An unconfigured or invalid bound profile is not a successful probe,
            # but return the stable diagnostic contract without exposing details.
            configured_version = str(snmp_credentials.get("version") or "").strip().casefold()
            version_aliases = {
                "1": "1", "v1": "1",
                "2": "2c", "2c": "2c", "v2c": "2c",
                "3": "3", "v3": "3", "snmpv3": "3",
            }
            data["version"] = version_aliases.get(configured_version)
            return {"success": True, "data": data}

        data["version"] = version
        port = int(snmp_credentials.get("port") or 161)
        if not host:
            data["status"] = "failed"
            lldp.update({"status": "failed", "message": "The bound SNMP target is unavailable."})
            return {"success": True, "data": data}

        import asyncio

        scalar_specs = (
            ("sys_name", SYS_NAME),
            ("sys_descr", SYS_DESCR),
            ("sys_object_id", SYS_OBJECT_ID),
            ("sys_uptime", SYS_UPTIME),
            ("sys_location", SYS_LOCATION),
            ("sys_contact", SYS_CONTACT),
        )

        async def read_system_scalar(name: str, oid: str) -> tuple[str, Optional[str]]:
            try:
                value = await asyncio.wait_for(
                    _snmp_get_versioned(host, transport_credentials, oid, port, version),
                    timeout=3.5,
                )
                return name, str(value).strip() if value is not None and str(value).strip() else None
            except Exception:
                return name, None

        scalar_results = await asyncio.gather(
            *(read_system_scalar(name, oid) for name, oid in scalar_specs)
        )
        system_info.update(dict(scalar_results))

        raw_uptime = system_info["sys_uptime"]
        if raw_uptime:
            uptime_seconds = parse_snmp_uptime_seconds(raw_uptime)
            system_info["uptime_seconds"] = uptime_seconds
            if uptime_seconds is not None:
                whole_seconds = int(uptime_seconds)
                days, remainder = divmod(whole_seconds, 86400)
                hours, remainder = divmod(remainder, 3600)
                minutes, seconds = divmod(remainder, 60)
                system_info["uptime"] = f"{days}d {hours}h {minutes}m {seconds}s"
            else:
                system_info["uptime"] = raw_uptime

        neighbor_result = None
        try:
            neighbor_result = await asyncio.wait_for(
                collect_snmp_lldp_neighbors(
                    host,
                    transport_credentials,
                    port=port,
                    version=version,
                    timeout=30.0,
                    max_rows=None,
                ),
                timeout=35.0,
            )
            neighbors = [dict(item) for item in neighbor_result if isinstance(item, Mapping)]
            lldp_status = str(getattr(neighbor_result, "collection_status", "success") or "success")
            if lldp_status not in {"success", "partial", "unsupported", "failed"}:
                lldp_status = "success"
            lldp.update({
                "status": lldp_status,
                "neighbors": neighbors,
                "truncated_oids": list(getattr(neighbor_result, "truncated_oids", []) or []),
                "max_rows": None,
                "message": (
                    "LLDP collection was partial because one or more walks failed or timed out."
                    if lldp_status == "partial"
                    else "LLDP collection completed; no neighbors were returned."
                    if not neighbors
                    else ""
                ),
            })
        except Exception as exc:
            exception_text = str(exc).casefold()
            timed_out = (
                isinstance(exc, TimeoutError)
                or type(exc).__name__.casefold() == "timeouterror"
                or "timeout" in exception_text
                or "timed out" in exception_text
            )
            lldp.update({
                "status": "failed",
                "neighbors": [],
                "truncated_oids": [],
                "message": (
                    "LLDP collection timed out before all LLDP tables were read."
                    if timed_out
                    else "LLDP collection failed (" + type(exc).__name__ + ")."
                ),
            })

        system_values = [system_info.get(key) for key in ("sys_name", "sys_descr", "sys_object_id")]
        if all(value is not None for value in system_values):
            system_status = "success"
        elif any(value is not None for value in system_values):
            system_status = "partial"
        else:
            system_status = "failed"

        if system_status == "success" and lldp["status"] == "success":
            data["status"] = "success"
        elif system_status in {"success", "partial"} or lldp["status"] in {"success", "partial"}:
            data["status"] = "partial"
        else:
            data["status"] = "failed"
    except Exception:
        # Credential resolution errors are intentionally generic so vault or
        # transport details cannot be reflected to the diagnostic caller.
        data["status"] = "failed"
        lldp.update({"status": "failed", "message": "Bound SNMP credentials could not be resolved."})

    return {"success": True, "data": data}


def test_snmp_walk(payload: dict = Body(default={}), user=require_role("Operator")):
    """Reject arbitrary SNMP walks; diagnostics are tied to LibreNMS rules."""
    raise HTTPException(status_code=410, detail={
        "code": "MANUAL_OID_WALK_REMOVED",
        "message": "Arbitrary OID walks are retired; use the pinned LibreNMS rule diagnostic.",
    })


@router.post("/platform-registry/snmp-walk-test")
def _retired_snmp_walk_route(payload: dict = Body(default={}), user=require_role("Operator")):
    return test_snmp_walk(payload, user)


def test_snmp_hardware_metrics(payload: dict = Body(default={}), user=require_role("Operator")):
    raise HTTPException(status_code=410, detail={"code": "LIBRENMS_RULES_ONLY", "message": "Custom SNMP OID definitions are retired."})


def detect_snmp_walk_vendor(payload: dict = Body(default={}), user=require_role("Operator")):
    raise HTTPException(status_code=410, detail={"code": "LIBRENMS_RULES_ONLY", "message": "Vendor detection uses the pinned LibreNMS OS rules."})


def test_snmp_system_info(payload: dict = Body(default={}), user=require_role("Operator")):
    raise HTTPException(status_code=410, detail={"code": "LIBRENMS_RULES_ONLY", "message": "System information is read through the pinned LibreNMS rule diagnostic."})


def test_snmp_interface_oids(payload: dict = Body(default={}), user=require_role("Operator")):
    raise HTTPException(status_code=410, detail={"code": "LIBRENMS_RULES_ONLY", "message": "Custom interface OID probes are retired."})


for _retired_path in ("/platform-registry/snmp-hardware-test", "/platform-registry/snmp-system-info-test"):
    router.add_api_route(
        _retired_path,
        test_snmp_hardware_metrics if "hardware" in _retired_path else test_snmp_system_info,
        methods=["POST"],
    )



@router.post("/devices/{device_id}/operational-data")
def collect_device_operational_data(
    device_id: str,
    payload: dict = Body(default={}),
    user=require_role('Operator'),
):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail='Device not found')

    device_info = dict(row)
    _assert_operational_data_device_scope(user, device_info)

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


