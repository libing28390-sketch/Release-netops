"""
assets.py - Physical Asset Management (PAM) API
Provides CRUD for servers and network devices with physical/location metadata.
When asset_type='network_device', a linked record in the `devices` table is
auto-created / synced / cascade-deleted so that the asset registry serves as
the single source of truth (Plan-A).
"""

import os
import uuid
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator
from database import get_db_connection
from core.crypto import encrypt_credential, decrypt_credential
from drivers.ssh_compat import get_ssh_error_code, build_ssh_error_guidance
from services import tag_service
from services.vault_service import credential_is_shared
from services.site_identity_service import resolve_canonical_site_id

import ping3
import socket
from scrapli import Scrapli

logger = logging.getLogger(__name__)

router = APIRouter()

_ASSET_IDENTITY_FIELDS = ('hostname', 'asset_tag', 'serial_number', 'management_ip')
_ASSET_IDENTITY_LABELS = {
    'hostname': '主机名',
    'asset_tag': '资产编号',
    'serial_number': '序列号',
    'management_ip': '管理IP',
}


def _find_asset_identity_duplicates(conn, values: dict, exclude_asset_id: str = '') -> list[dict]:
    """Find non-empty identity fields already used by another physical asset."""
    duplicates = []
    for field in _ASSET_IDENTITY_FIELDS:
        value = str(values.get(field) or '').strip()
        if not value:
            continue
        query = (
            f"SELECT id, hostname FROM physical_assets "
            f"WHERE LOWER(TRIM(COALESCE({field}, ''))) = LOWER(TRIM(?))"
        )
        params: list[str] = [value]
        if exclude_asset_id:
            query += ' AND id != ?'
            params.append(exclude_asset_id)
        existing = conn.execute(query, params).fetchone()
        if existing:
            duplicates.append({
                'field': field,
                'label': _ASSET_IDENTITY_LABELS[field],
                'value': value,
                'existing_id': existing['id'],
                'existing_hostname': existing['hostname'] or '',
            })
    return duplicates


def _identity_duplicate_detail(duplicates: list[dict]) -> str:
    parts = [f"{item['label']}「{item['value']}」" for item in duplicates]
    return '资产唯一性校验失败：' + '、'.join(parts) + '已存在，请修改后再提交。'


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')


# ── helpers: devices ↔ physical_assets sync ──────────────────────────

def _platform_from_vendor(vendor: str, asset_type: str = 'network_device') -> str:
    """Map asset vendor string to a best-guess Scrapli/Netmiko platform."""
    v = (vendor or '').lower()
    if 'cisco' in v:
        return 'cisco_iosxe'
    if 'huawei' in v:
        return 'huawei_vrp'
    if 'h3c' in v or 'comware' in v:
        return 'hp_comware'
    if 'arista' in v:
        return 'arista_eos'
    if 'juniper' in v:
        return 'juniper_junos'
    if 'ruijie' in v or 'rgos' in v or '锐捷' in v:
        return 'ruijie_rgos'
    if 'zte' in v or 'zhongxing' in v or '中兴' in v:
        return 'zte_zxros'
    if 'maipu' in v or '迈普' in v:
        return 'maipu'
    if 'dptech' in v or '迪普' in v:
        if 'fw' in v or 'firewall' in v or '防火墙' in v or asset_type == 'firewall':
            return 'dptech_conplat_fw'
        return 'dptech_conplat'
    if any(x in v for x in ['ubuntu', 'debian', 'centos', 'redhat', 'linux']):
        return 'linux'
    
    if asset_type == 'server':
        return 'linux'
    return 'cisco_iosxe'


_VENDOR_PLATFORM_RULES: tuple[tuple[str, set[str], str], ...] = (
    ('cisco', {'cisco', 'ios', 'iosxe', 'cisco_ios', 'cisco_iosxe', 'cisco_xe', 'cisco_nxos', 'nxos', 'nexus'}, 'cisco_ios'),
    ('huawei', {'huawei', 'huawei_vrp', 'huawei_vrpv8', 'vrp', 'ce', 'ce_vrp', 'ne'}, 'huawei_vrp'),
    ('h3c', {
        'h3c', 'h3c_comware', 'h3c_comware9', 'hp_comware',
        'comware', 'comware5', 'comware7', 'comware9',
    }, 'h3c_comware'),
    ('comware', {
        'h3c', 'h3c_comware', 'h3c_comware9', 'hp_comware',
        'comware', 'comware5', 'comware7', 'comware9',
    }, 'h3c_comware'),
    ('arista', {'arista', 'arista_eos', 'eos'}, 'arista_eos'),
    ('juniper', {'juniper', 'juniper_junos', 'junos'}, 'juniper_junos'),
    ('ruijie', {'ruijie', 'ruijie_os', 'ruijie_rgos', 'rgos'}, 'ruijie_rgos'),
    ('zte', {'zte', 'zte_zxros', 'zxros'}, 'zte_zxros'),
    ('maipu', {'maipu', 'maipu_network', 'maipu_mypower', 'mypower'}, 'maipu'),
    ('dptech', {'dptech', 'dptech_ios', 'dptech_conplat', 'dptech_conplat_fw', 'conplat'}, 'dptech_conplat'),
)

_SERVER_PLATFORMS = {
    'linux', 'ubuntu', 'centos', 'debian', 'redhat', 'windows', 'windows_server', 'esxi',
}


def _normalize_asset_platform(vendor: str, platform: str, asset_type: str = 'network_device') -> str:
    """Keep the persisted platform compatible with the selected asset vendor/type."""
    raw = str(platform or '').strip()
    normalized = raw.lower()
    if asset_type == 'server':
        return raw if normalized in _SERVER_PLATFORMS else 'linux'

    vendor_normalized = str(vendor or '').strip().lower()
    for vendor_marker, allowed, default_platform in _VENDOR_PLATFORM_RULES:
        if vendor_marker in vendor_normalized:
            if normalized in allowed:
                return raw
            if raw:
                logger.warning(
                    "Correcting incompatible asset platform vendor=%s platform=%s -> %s",
                    vendor,
                    raw,
                    default_platform,
                )
            return default_platform
    return raw or _platform_from_vendor(vendor, asset_type)


def _safe_encrypt(plaintext: str) -> str:
    """Encrypt credential, return empty string if encryption key is not configured."""
    if not plaintext:
        return plaintext
    try:
        return encrypt_credential(plaintext)
    except RuntimeError:
        logger.warning('CREDENTIAL_ENCRYPTION_KEY not configured, storing empty password')
        return ''


def _resolve_snmp_credential_id(conn, value: str | None) -> str:
    """Validate and normalize an independent SNMP credential binding."""
    requested = str(value or '').strip()
    if not requested:
        return ''
    row = conn.execute(
        '''SELECT id, credential_type, snmp_community
           FROM credentials WHERE id = ? OR credential_name = ?''',
        (requested, requested),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=422, detail=f'SNMP凭据不存在: {requested}')
    if str(row['credential_type'] or '').lower() != 'snmpv2':
        raise HTTPException(status_code=422, detail='SNMP关联必须选择 SNMPv2 凭据')
    if not (decrypt_credential(row['snmp_community']) or str(row['snmp_community'] or '').strip()):
        raise HTTPException(status_code=422, detail='SNMP凭据未配置 Community')
    return str(row['id'])


def _create_device_local_credential(
    conn,
    *,
    hostname: str,
    device_id: str,
    suffix: str = '',
    username: str = '',
    password: str = '',
    enable_password: str = '',
    snmp_community: str = '',
) -> str:
    """Create a device-local credential record for one account role.

    These records are deliberately marked ``unbound``: they are storage and
    display metadata for credentials entered on one device, not shared
    credential-center authorities.  The device/asset fields remain the source
    used for local connection and rotation workflows.
    """
    credential_id = f"cred-{uuid.uuid4().hex[:12]}"
    name_suffix = suffix.strip()
    credential_name = f"cred-{hostname or 'device'}-{device_id[:8]}{name_suffix}"
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        '''INSERT INTO credentials
           (id, credential_name, credential_type, username, account_role,
            encrypted_password, enable_password, snmp_community, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            credential_id,
            credential_name,
            'ssh_password',
            username or '',
            'unbound',
            _safe_encrypt(password) if password else '',
            _safe_encrypt(enable_password) if enable_password else '',
            _safe_encrypt(snmp_community) if snmp_community else '',
            now,
        ),
    )
    return credential_id


def _sync_device_type_power(conn, vendor: str, model: str, power_watts: int, device_role: str = 'switch', u_height: int = 1) -> None:
    """Sync power_watts and role to device_types table to ensure rack power calculation is accurate."""
    if not model:
        return
    v = (vendor or '').strip()
    m = model.strip()
    p = power_watts or 0
    row = conn.execute('SELECT id, u_height, power_watts FROM device_types WHERE model = ? AND vendor = ?', (m, v)).fetchone()
    if row:
        updates = []
        params = []
        if p > 0 and row['power_watts'] != p:
            updates.append("power_watts = ?")
            params.append(p)
        if u_height > 0 and row['u_height'] != u_height:
            updates.append("u_height = ?")
            params.append(u_height)
        if updates:
            updates.append("updated_at = ?")
            params.append(_utc_now())
            params.append(row['id'])
            conn.execute(f"UPDATE device_types SET {', '.join(updates)} WHERE id = ?", params)
    else:
        dt_id = str(uuid.uuid4())
        now = _utc_now()
        conn.execute(
            '''INSERT INTO device_types (id, model, vendor, u_height, device_role, is_full_depth, description, power_watts, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (dt_id, m, v, u_height or 1, device_role or 'switch', 1, 'Auto-created from asset onboarding', p, now, now)
        )


def _pre_resolve_credential(conn, body) -> None:
    existing_cred_id = getattr(body, 'credential_id', '') or ''
    if existing_cred_id:
        cred_row = conn.execute(
            'SELECT id, username, encrypted_password, enable_password, snmp_community FROM credentials WHERE id = ? OR credential_name = ?',
            (existing_cred_id, existing_cred_id)
        ).fetchone()
        if not cred_row:
            raise HTTPException(status_code=422, detail=f'普通凭据不存在: {existing_cred_id}')
        body.credential_id = cred_row['id']
        from core.crypto import decrypt_credential
        c_dict = dict(cred_row)
        dec_pwd = decrypt_credential(c_dict.get('encrypted_password')) or ''
        dec_enable = decrypt_credential(c_dict.get('enable_password')) or ''
        dec_snmp = decrypt_credential(c_dict.get('snmp_community')) or ''
        c_user = c_dict.get('username') or ''

        # An explicit binding wins over any stale/manual secret in the
        # request. The vault row is the canonical value for this role.
        body.username = c_user
        body.normal_username = c_user
        body.normal_password = dec_pwd
        body.enable_password = dec_enable
        # An explicitly entered Community is authoritative.  In particular,
        # ``public`` is a valid SNMPv2c value and must not be replaced by an
        # empty value from an SSH credential that has no SNMP secret.
        if not getattr(body, 'snmp_community', None):
            body.snmp_community = dec_snmp

    existing_admin_cred_id = getattr(body, 'admin_credential_id', '') or ''
    if existing_admin_cred_id:
        cred_row = conn.execute(
            'SELECT id, username, encrypted_password, enable_password FROM credentials WHERE id = ? OR credential_name = ?',
            (existing_admin_cred_id, existing_admin_cred_id)
        ).fetchone()
        if not cred_row:
            raise HTTPException(status_code=422, detail=f'特权凭据不存在: {existing_admin_cred_id}')
        body.admin_credential_id = cred_row['id']
        from core.crypto import decrypt_credential
        c_dict = dict(cred_row)
        dec_pwd = decrypt_credential(c_dict.get('encrypted_password')) or ''
        dec_enable = decrypt_credential(c_dict.get('enable_password')) or ''
        c_user = c_dict.get('username') or ''

        body.admin_username = c_user
        body.admin_password = dec_pwd
        # A privileged credential owns the enable secret when both roles are
        # bound. This prevents the normal credential from winning by order.
        body.enable_password = dec_enable


def _create_linked_device(conn, asset_id: str, body) -> str:
    """Create a devices row linked to a physical_assets row."""
    device_id = str(uuid.uuid4())
    platform = _normalize_asset_platform(
        body.vendor,
        getattr(body, 'platform', ''),
        body.asset_type,
    )
    method = getattr(body, 'connection_method', '') or 'ssh'
    uname = getattr(body, 'username', '') or ''
    pwd = getattr(body, 'password', '') or ''
    community = getattr(body, 'snmp_community', '') or ''
    port = getattr(body, 'snmp_port', None) or 161
    mgmt_port = getattr(body, 'management_port', None) or 22

    # PAM (dual-account) fields
    normal_user = getattr(body, 'normal_username', '') or ''
    normal_pwd  = getattr(body, 'normal_password', '') or ''
    admin_user  = getattr(body, 'admin_username', '')  or ''
    admin_pwd   = getattr(body, 'admin_password', '')  or ''
    enable_pwd  = getattr(body, 'enable_password', '') or ''
    auth_model  = getattr(body, 'auth_model', '') or 'single'

    # Auto-detect dual-account mode if PAM credentials are provided
    if auth_model == 'single' and (normal_user or admin_user or normal_pwd or admin_pwd):
        auth_model = 'dual'

    # If PAM is in use but legacy username/password are empty, fill them from
    # the admin side so existing code paths that still read username/password
    # (e.g. quick connectivity check) keep working.
    if auth_model == 'dual':
        if not uname and admin_user:
            uname = admin_user
        if not pwd and admin_pwd:
            pwd = admin_pwd

    # If credentials are provided during import, mark onboarding as verified
    # so the user doesn't have to manually verify each device before takeover.
    has_creds = bool((uname and pwd) or (admin_user and admin_pwd) or (normal_user and normal_pwd))
    
    existing_cred_id = getattr(body, 'credential_id', '') or ''
    existing_admin_cred_id = getattr(body, 'admin_credential_id', '') or ''
    is_bound = False
    is_admin_bound = False
    credential_id = ''
    admin_credential_id = ''
    
    if existing_cred_id:
        # Check if credential exists in DB (either by ID or by name)
        cred_row = conn.execute(
            'SELECT id, username, encrypted_password, enable_password, snmp_community FROM credentials WHERE id = ? OR credential_name = ?',
            (existing_cred_id, existing_cred_id)
        ).fetchone()
        if cred_row:
            credential_id = cred_row['id']
            has_creds = True
            is_bound = True
            from core.crypto import decrypt_credential
            c_dict = dict(cred_row)
            dec_pwd = decrypt_credential(c_dict.get('encrypted_password')) or ''
            dec_enable = decrypt_credential(c_dict.get('enable_password')) or ''
            dec_snmp = decrypt_credential(c_dict.get('snmp_community')) or ''
            c_user = c_dict.get('username') or ''
            
            # Sync back to local fields
            if not uname: uname = c_user
            if not normal_user: normal_user = c_user
            if not normal_pwd: normal_pwd = dec_pwd
            if not enable_pwd: enable_pwd = dec_enable
            # Preserve an explicit asset-local Community, including the very
            # common SNMPv2c value ``public``.
            if not community: community = dec_snmp

    if existing_admin_cred_id:
        # Check if admin credential exists in DB (either by ID or by name)
        cred_row = conn.execute(
            'SELECT id, username, encrypted_password, enable_password FROM credentials WHERE id = ? OR credential_name = ?',
            (existing_admin_cred_id, existing_admin_cred_id)
        ).fetchone()
        if cred_row:
            admin_credential_id = cred_row['id']
            has_creds = True
            is_admin_bound = True
            from core.crypto import decrypt_credential
            c_dict = dict(cred_row)
            dec_pwd = decrypt_credential(c_dict.get('encrypted_password')) or ''
            dec_enable = decrypt_credential(c_dict.get('enable_password')) or ''
            c_user = c_dict.get('username') or ''
            
            # Sync back to local fields
            if not admin_user: admin_user = c_user
            if not admin_pwd: admin_pwd = dec_pwd
            if not enable_pwd: enable_pwd = dec_enable

    onboarding = 'verified' if has_creds else 'pending_credentials'

    resolved_pwd = normal_pwd or pwd or admin_pwd or ''
    enc_pwd = _safe_encrypt(resolved_pwd) if resolved_pwd else ''
    enc_enable = _safe_encrypt(enable_pwd) if enable_pwd else ''
    enc_snmp = _safe_encrypt(community) if community else ''
    resolved_uname = normal_user or uname or admin_user or ''

    # Manual dual-account entry creates two separate device-local records so
    # the credential center can distinguish the normal and privileged account.
    # They remain ``unbound`` and therefore do not expose a shared vault secret.
    if not is_bound and (normal_user or normal_pwd or (auth_model != 'dual' and (uname or pwd or community))):
        credential_id = _create_device_local_credential(
            conn,
            hostname=body.hostname,
            device_id=device_id,
            username=normal_user or uname,
            password=normal_pwd or (pwd if auth_model != 'dual' else ''),
            enable_password=enable_pwd if auth_model != 'dual' else '',
            snmp_community=community,
        )
    if not is_admin_bound and auth_model == 'dual' and (admin_user or admin_pwd):
        admin_credential_id = _create_device_local_credential(
            conn,
            hostname=body.hostname,
            device_id=device_id,
            suffix='-admin',
            username=admin_user,
            password=admin_pwd,
            enable_password=enable_pwd,
        )

    conn.execute('''
        INSERT INTO devices (
            id, asset_id, hostname, ip_address, platform, status, compliance,
            username, password, sn, model, version, role, site, uptime,
            connection_method, vendor, snmp_community, snmp_port,
            normal_username, normal_password, admin_username, admin_password,
            enable_password, auth_model, device_category, power_watts,
            onboarding_status, credential_id, admin_credential_id, management_port
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        device_id, asset_id,
        body.hostname, body.management_ip,
        platform, 'pending', 'unknown',
        uname, '', # password column empty
        body.serial_number, body.model, '', body.device_role,
        body.site_id, '0d 0h', method, body.vendor,
        _safe_encrypt(community), port,
        normal_user, '', # normal_password column empty
        admin_user,  '', # admin_password column empty
        '', # enable_password column empty
        auth_model,
        getattr(body, 'device_category', '') or '',
        getattr(body, 'power_watts', 0) or 0,
        onboarding,
        credential_id or '',
        admin_credential_id or '',
        mgmt_port
    ))
    # The physical asset is the canonical source for CMDB location. Keep the
    # normalized foreign-key-style field populated for device inventory and
    # topology consumers; ``site`` remains only as a legacy display field.
    conn.execute('UPDATE devices SET site_id = ? WHERE id = ?', (body.site_id, device_id))
    conn.execute('UPDATE devices SET snmp_credential_id = ? WHERE id = ?', (getattr(body, 'snmp_credential_id', '') or '', device_id))
    conn.execute(
        'UPDATE physical_assets SET credential_id = ?, admin_credential_id = ?, snmp_credential_id = ? WHERE id = ?',
        (credential_id or '', admin_credential_id or '', getattr(body, 'snmp_credential_id', '') or '', asset_id),
    )
    tag_service.sync_device_status_tag(conn, device_id, 'pending')
    return device_id


def _resolve_asset_tag_ids(conn, body) -> list[str] | None:
    """Resolve interactive tag IDs and import-friendly stable tag codes."""
    raw_ids = list(getattr(body, 'tag_ids', None) or [])
    raw_codes = getattr(body, 'tag_codes', None) or ''
    tokens = raw_ids + [item.strip() for item in str(raw_codes).replace(';', ',').replace('，', ',').split(',') if item.strip()]
    if not tokens and getattr(body, 'tag_ids', None) is None and getattr(body, 'tag_codes', None) is None:
        return None
    resolved: list[str] = []
    for token in tokens:
        row = conn.execute('SELECT id FROM tag_definitions WHERE id = ? OR code = ?', (token, token.lower())).fetchone()
        if not row:
            raise HTTPException(status_code=422, detail=f'标签不存在或已停用: {token}')
        resolved.append(str(row['id']))
    return list(dict.fromkeys(resolved))


def _sync_asset_tags(conn, asset_id: str, tag_ids: list[str] | None) -> None:
    if tag_ids is None:
        return
    device_row = conn.execute('SELECT id FROM devices WHERE asset_id = ?', (asset_id,)).fetchone()
    if not device_row:
        raise HTTPException(status_code=422, detail='资产尚未关联设备，无法绑定标签')
    try:
        tag_service.set_device_tags(conn, str(device_row['id']), tag_ids, created_by='asset-management')
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _sync_device_from_asset(conn, asset_id: str, body) -> None:
    """Push basic-info changes from asset to its linked device row."""
    row = conn.execute('SELECT id, credential_id, admin_credential_id FROM devices WHERE asset_id = ?', (asset_id,)).fetchone()
    if not row:
        return
    device_id = row['id']
    credential_id = row['credential_id']
    admin_credential_id = row['admin_credential_id']

    # Extract manual fields from body
    username = getattr(body, 'username', None)
    pwd = getattr(body, 'password', None)
    enable_pwd = getattr(body, 'enable_password', None)
    community = getattr(body, 'snmp_community', None)
    normal_username = getattr(body, 'normal_username', None)
    admin_username = getattr(body, 'admin_username', None)
    normal_pwd = getattr(body, 'normal_password', None)
    admin_pwd = getattr(body, 'admin_password', None)

    input_credential_id = getattr(body, 'credential_id', None)
    input_admin_credential_id = getattr(body, 'admin_credential_id', None)
    
    # If a new credential_id is passed, update binding
    if input_credential_id is not None:
        if input_credential_id:
            # Lookup credential in DB
            cred_row = conn.execute(
                'SELECT id, username, encrypted_password, enable_password, snmp_community FROM credentials WHERE id = ? OR credential_name = ?',
                (input_credential_id, input_credential_id)
            ).fetchone()
            if cred_row:
                input_id = cred_row['id']
                if input_id != credential_id:
                    conn.execute('UPDATE devices SET credential_id = ? WHERE id = ?', (input_id, device_id))
                    conn.execute('UPDATE physical_assets SET credential_id = ? WHERE id = ?', (input_id, asset_id))
                    credential_id = input_id
                    
                    # Decrypt and sync to local fields
                    from core.crypto import decrypt_credential
                    c_dict = dict(cred_row)
                    dec_pwd = decrypt_credential(c_dict.get('encrypted_password')) or ''
                    dec_enable = decrypt_credential(c_dict.get('enable_password')) or ''
                    dec_snmp = decrypt_credential(c_dict.get('snmp_community')) or ''
                    c_user = c_dict.get('username') or ''
                    
                    conn.execute('''
                        UPDATE devices
                        SET normal_username = ?, normal_password = ?,
                            enable_password = ?, snmp_community = ?
                        WHERE id = ?
                    ''', (c_user, _safe_encrypt(dec_pwd), _safe_encrypt(dec_enable), _safe_encrypt(dec_snmp), device_id))
                    
                    conn.execute('''
                        UPDATE physical_assets
                        SET normal_username = ?, normal_password = ?,
                            enable_password = ?, snmp_community = ?
                        WHERE id = ?
                    ''', (c_user, _safe_encrypt(dec_pwd), _safe_encrypt(dec_enable), _safe_encrypt(dec_snmp), asset_id))
        else:
            # Clear binding
            if credential_id:
                conn.execute('UPDATE devices SET credential_id = NULL WHERE id = ?', (device_id,))
                conn.execute('UPDATE physical_assets SET credential_id = \'\' WHERE id = ?', (asset_id,))
                credential_id = None

    # If a new admin_credential_id is passed, update binding
    if input_admin_credential_id is not None:
        if input_admin_credential_id:
            # Lookup credential in DB
            cred_row = conn.execute(
                'SELECT id, username, encrypted_password, enable_password FROM credentials WHERE id = ? OR credential_name = ?',
                (input_admin_credential_id, input_admin_credential_id)
            ).fetchone()
            if cred_row:
                input_id = cred_row['id']
                if input_id != admin_credential_id:
                    conn.execute('UPDATE devices SET admin_credential_id = ? WHERE id = ?', (input_id, device_id))
                    conn.execute('UPDATE physical_assets SET admin_credential_id = ? WHERE id = ?', (input_id, asset_id))
                    admin_credential_id = input_id
                    
                    # Decrypt and sync to local fields
                    from core.crypto import decrypt_credential
                    c_dict = dict(cred_row)
                    dec_pwd = decrypt_credential(c_dict.get('encrypted_password')) or ''
                    dec_enable = decrypt_credential(c_dict.get('enable_password')) or ''
                    c_user = c_dict.get('username') or ''
                    
                    conn.execute('''
                        UPDATE devices
                        SET admin_username = ?, admin_password = ?, enable_password = ?
                        WHERE id = ?
                    ''', (c_user, _safe_encrypt(dec_pwd), _safe_encrypt(dec_enable), device_id))
                    
                    conn.execute('''
                        UPDATE physical_assets
                        SET admin_username = ?, admin_password = ?, enable_password = ?
                        WHERE id = ?
                    ''', (c_user, _safe_encrypt(dec_pwd), _safe_encrypt(dec_enable), asset_id))
        else:
            # Clear binding
            if admin_credential_id:
                conn.execute('UPDATE devices SET admin_credential_id = NULL WHERE id = ?', (device_id,))
                conn.execute('UPDATE physical_assets SET admin_credential_id = \'\' WHERE id = ?', (asset_id,))
                admin_credential_id = None

    # Sync credential row if it's device-specific
    if credential_id:
        cred_row = conn.execute('SELECT credential_name, username, encrypted_password, enable_password, snmp_community FROM credentials WHERE id = ?', (credential_id,)).fetchone()
        if cred_row:
            # Check if this credential is device-specific
            cred_name = cred_row['credential_name'] or ''
            is_device_specific = cred_name.startswith(f"cred-{body.hostname or ''}-") or cred_name.startswith(f"cred-device-")
            if is_device_specific:
                # A device-local credential referenced by credential_id belongs
                # to the normal-account slot.  Do not overwrite its username
                # with the generic/privileged device username (often ``admin``).
                stored_uname = normal_username if normal_username is not None else cred_row['username']
                local_password = normal_pwd if normal_pwd is not None else pwd
                stored_pwd = _safe_encrypt(local_password) if local_password is not None and local_password != '' else cred_row['encrypted_password']
                stored_enable = _safe_encrypt(enable_pwd) if enable_pwd is not None and enable_pwd != '' else cred_row['enable_password']
                stored_snmp = _safe_encrypt(community) if community is not None and community != '' else cred_row['snmp_community']
                conn.execute('''
                    UPDATE credentials
                    SET username = ?, encrypted_password = ?, enable_password = ?, snmp_community = ?
                    WHERE id = ?
                ''', (stored_uname, stored_pwd, stored_enable, stored_snmp, credential_id))
    elif not admin_credential_id:
        # Create credential_id if missing and we have local credentials
        if normal_username not in (None, '') or normal_pwd not in (None, '') or username not in (None, '') or (pwd is not None and pwd != '') or (enable_pwd is not None and enable_pwd != '') or (community is not None and community != ''):
            credential_id = _create_device_local_credential(
                conn,
                hostname=body.hostname or 'device',
                device_id=device_id,
                username=normal_username or username or '',
                password=normal_pwd or (pwd or ''),
                enable_password=enable_pwd or '',
                snmp_community=community or '',
            )
            
            conn.execute('UPDATE devices SET credential_id = ? WHERE id = ?', (credential_id, device_id))

    # A normal credential may already exist while the privileged account was
    # entered manually later.  Create the missing device-local admin record and
    # bind it to the admin slot instead of leaving the privileged password only
    # in the device columns.
    if not admin_credential_id and (
        admin_username not in (None, '') or admin_pwd not in (None, '')
    ):
        admin_credential_id = _create_device_local_credential(
            conn,
            hostname=body.hostname or 'device',
            device_id=device_id,
            suffix='-admin',
            username=admin_username or '',
            password=admin_pwd or '',
            enable_password=enable_pwd or '',
        )
        conn.execute('UPDATE devices SET admin_credential_id = ? WHERE id = ?', (admin_credential_id, device_id))
        conn.execute('UPDATE physical_assets SET admin_credential_id = ? WHERE id = ?', (admin_credential_id, asset_id))

    updates = {
        'hostname': body.hostname,
        'ip_address': body.management_ip,
        'sn': body.serial_number,
        'model': body.model,
        'role': body.device_role,
        'site': body.site_id,
        'site_id': body.site_id,
        'vendor': body.vendor,
        'platform': _normalize_asset_platform(
            getattr(body, 'vendor', None) or '',
            getattr(body, 'platform', None) or '',
            getattr(body, 'asset_type', None) or 'network_device',
        ) if getattr(body, 'platform', None) is not None else None,
        'connection_method': getattr(body, 'connection_method', None),
        'snmp_port': getattr(body, 'snmp_port', None),
        'snmp_credential_id': getattr(body, 'snmp_credential_id', None),
        'auth_model': getattr(body, 'auth_model', None),
        'device_category': getattr(body, 'device_category', None),
        'power_watts': getattr(body, 'power_watts', None),
        'management_port': getattr(body, 'management_port', None),
    }

    if getattr(body, 'snmp_community', None) not in (None, ''):
        updates['snmp_community'] = _safe_encrypt(body.snmp_community)

    if getattr(body, 'username', None) is not None: updates['username'] = body.username
    if getattr(body, 'normal_username', None) is not None: updates['normal_username'] = body.normal_username
    if getattr(body, 'admin_username', None) is not None: updates['admin_username'] = body.admin_username
    
    updates['password'] = ''
    updates['normal_password'] = ''
    updates['admin_password'] = ''
    updates['enable_password'] = ''

    set_parts = []
    params = []
    for col, val in updates.items():
        if val is not None:
            set_parts.append(f'{col} = ?')
            params.append(val)
    if set_parts:
        params.append(row['id'])
        conn.execute(f"UPDATE devices SET {', '.join(set_parts)} WHERE id = ?", params)



def _sync_rack_device_from_asset(conn, asset_id: str, obj) -> None:
    # obj can be a dict, DictRow, or a Pydantic model
    def get_val(key, default=None):
        if hasattr(obj, key):
            val = getattr(obj, key)
            if val is not None:
                return val
        try:
            val = obj[key]
            if val is not None:
                return val
        except (KeyError, TypeError, IndexError):
            pass
        return default

    hostname = get_val('hostname')
    rack = get_val('rack')
    u_height = get_val('u_height', 1)
    planned_start_u = get_val('planned_start_u')
    serial_number = get_val('serial_number', '')
    vendor = get_val('vendor', '')
    model = get_val('model', '')
    power_watts = get_val('power_watts', 0)
    device_role = get_val('device_role', 'switch')

    if planned_start_u in (None, '', 'null'):
        planned_start_u = None
    else:
        try:
            planned_start_u = int(planned_start_u)
        except (ValueError, TypeError):
            planned_start_u = None

    try:
        u_height = int(u_height)
    except (ValueError, TypeError):
        u_height = 1

    existing = conn.execute("SELECT id FROM rack_devices WHERE asset_id = ?", (asset_id,)).fetchone()

    if not rack or planned_start_u is None:
        if existing:
            from services import rack_service
            rack_service.delete_rack_device(conn, existing['id'])
        return

    rack_row = conn.execute("SELECT id, total_u FROM racks WHERE name = ? OR rack_name = ?", (rack, rack)).fetchone()
    if not rack_row:
        raise ValueError(f"Rack '{rack}' does not exist")

    _sync_device_type_power(conn, vendor, model, power_watts, device_role, u_height)
    dt_row = conn.execute("SELECT id FROM device_types WHERE model = ? AND vendor = ?", (model, vendor)).fetchone()
    if not dt_row:
        raise ValueError(f"Failed to resolve device type for vendor '{vendor}' model '{model}'")
    device_type_id = dt_row['id']

    from services import rack_service
    if existing:
        rack_service.update_rack_device(
            conn,
            existing['id'],
            name=hostname,
            rack_id=rack_row['id'],
            device_type_id=device_type_id,
            start_u=planned_start_u,
            serial_number=serial_number,
            asset_id=asset_id
        )
    else:
        rack_service.create_rack_device(
            conn,
            name=hostname,
            rack_id=rack_row['id'],
            device_type_id=device_type_id,
            start_u=planned_start_u,
            serial_number=serial_number,
            asset_id=asset_id
        )



def _delete_linked_device(conn, asset_id: str) -> None:
    """Cascade-delete the devices row linked to the asset, cleaning up all FK references first."""
    row = conn.execute('SELECT id FROM devices WHERE asset_id = ?', (asset_id,)).fetchone()
    if not row:
        return
    device_id = row['id'] if isinstance(row, dict) else row[0]

    # IPAM prefixes are site-scoped resources, so deleting a device must not
    # delete every prefix at the device's site. It must, however, remove
    # device-owned address observations and detach prefix gateway references;
    # otherwise IPAM keeps showing stale addresses after the device is gone.
    interface_cursor = conn.execute(
        'SELECT id FROM interfaces WHERE device_id = ?', (device_id,)
    )
    interface_rows = interface_cursor.fetchall() if hasattr(interface_cursor, 'fetchall') else []
    interface_ids = [r['id'] if isinstance(r, dict) else r[0] for r in interface_rows]
    conn.execute('DELETE FROM ip_addresses WHERE device_id = ?', (device_id,))
    conn.execute('DELETE FROM ip_inventory WHERE device_id = ?', (device_id,))
    conn.execute('UPDATE prefixes SET gateway_device_id = NULL WHERE gateway_device_id = ?', (device_id,))
    if interface_ids:
        placeholders = ','.join('?' for _ in interface_ids)
        conn.execute(
            f'DELETE FROM ip_addresses WHERE interface_id IN ({placeholders})',
            interface_ids,
        )
        conn.execute(
            f'UPDATE prefixes SET gateway_interface_id = NULL WHERE gateway_interface_id IN ({placeholders})',
            interface_ids,
        )

    # Delete from all tables that reference devices(id)
    conn.execute('DELETE FROM jobs WHERE device_id = ?', (device_id,))
    conn.execute('DELETE FROM config_snapshots WHERE device_id = ?', (device_id,))
    conn.execute('DELETE FROM topology_links WHERE source_device_id = ? OR target_device_id = ?', (device_id, device_id))
    conn.execute('DELETE FROM topology_discovery_run_devices WHERE device_id = ?', (device_id,))
    conn.execute('DELETE FROM topology_observations WHERE source_device_id = ? OR target_device_id = ?', (device_id, device_id))
    conn.execute('DELETE FROM compliance_findings WHERE device_id = ?', (device_id,))
    conn.execute('DELETE FROM device_health_samples WHERE device_id = ?', (device_id,))
    conn.execute('DELETE FROM config_drift_results WHERE device_id = ?', (device_id,))
    conn.execute('DELETE FROM capacity_snapshots WHERE device_id = ?', (device_id,))
    conn.execute('DELETE FROM inspection_results WHERE device_id = ?', (device_id,))
    # Tags are a many-to-many association and the FK is intentionally kept
    # explicit for compatibility with existing PostgreSQL installations.
    conn.execute("DELETE FROM tag_assignments WHERE resource_type='device' AND resource_id = ?", (device_id,))

    conn.execute('DELETE FROM devices WHERE id = ?', (device_id,))
    # Credentials are managed resources, not children of an asset. Deleting
    # an asset only removes the device binding; credential cleanup is an
    # explicit action from the credential center after all device references
    # have been cleared.


# ── Pydantic Models ──────────────────────────────────────────────────

class AssetCreate(BaseModel):
    asset_type: str  # 'server' | 'network_device'
    asset_tag: str = ''
    serial_number: str = ''
    vendor: str = ''
    model: str = ''
    hostname: str = ''
    site_id: str = ''
    rack: str = ''
    rack_unit: str = ''
    u_height: int = 1
    planned_start_u: Optional[int] = None
    management_ip: str = ''
    business_ip: str = ''
    device_role: str = ''  # switch/router/firewall/ap - only for network_device
    vlan: str = ''
    uplink_switch: str = ''
    uplink_port: str = ''
    status: str = 'active'
    lifecycle_status: str = 'staging'
    asset_origin: str = 'new'
    takeover_exempt_reason: str = ''
    purchase_date: str = ''
    warranty_expiry: str = ''
    department: str = ''
    notes: str = ''
    # Network-device-only fields (forwarded to devices table)
    platform: str = ''
    connection_method: str = 'ssh'
    username: str = ''
    password: str = ''
    # PAM fields
    normal_username: str = ''
    normal_password: str = ''
    admin_username: str = ''
    admin_password: str = ''
    enable_password: str = ''
    auth_model: str = 'single'
    snmp_community: str = ''
    snmp_port: int = 161
    management_port: int = 22
    device_category: str = ''
    power_watts: int = 0
    credential_id: Optional[str] = ''
    admin_credential_id: Optional[str] = ''
    snmp_credential_id: Optional[str] = ''
    tag_ids: list[str] = []
    tag_codes: str = ''

    @field_validator('u_height', mode='before')
    @classmethod
    def validate_u_height(cls, v):
        if v is None or v == '':
            return 1
        try:
            return max(1, min(60, int(v)))
        except (ValueError, TypeError):
            return 1

    @field_validator('planned_start_u', mode='before')
    @classmethod
    def validate_planned_start_u(cls, v):
        if v is None or v == '':
            return None
        try:
            vi = int(v)
        except (ValueError, TypeError):
            return None
        if vi < 1 or vi > 60:
            return None
        return vi

    @field_validator('power_watts', mode='before')
    @classmethod
    def validate_power_watts(cls, v):
        if v is None or v == '':
            return 0
        try:
            return int(v)
        except (ValueError, TypeError):
            return 0

    @field_validator('snmp_port', mode='before')
    @classmethod
    def validate_snmp_port(cls, v):
        if v is None or v == '':
            return 161
        try:
            return int(v)
        except (ValueError, TypeError):
            return 161

    @field_validator('management_port', mode='before')
    @classmethod
    def validate_management_port(cls, v):
        if v is None or v == '':
            return 22
        try:
            return int(v)
        except (ValueError, TypeError):
            return 22


class AssetUpdate(BaseModel):
    asset_type: Optional[str] = None
    asset_tag: Optional[str] = None
    serial_number: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    hostname: Optional[str] = None
    site_id: Optional[str] = None
    rack: Optional[str] = None
    rack_unit: Optional[str] = None
    u_height: Optional[int] = None
    planned_start_u: Optional[int] = None
    management_ip: Optional[str] = None
    business_ip: Optional[str] = None
    device_role: Optional[str] = None
    vlan: Optional[str] = None
    uplink_switch: Optional[str] = None
    uplink_port: Optional[str] = None
    status: Optional[str] = None
    lifecycle_status: Optional[str] = None
    asset_origin: Optional[str] = None
    purchase_date: Optional[str] = None
    warranty_expiry: Optional[str] = None
    department: Optional[str] = None
    notes: Optional[str] = None
    # Network-device-only fields (forwarded to devices table)
    platform: Optional[str] = None
    connection_method: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    # PAM fields
    normal_username: Optional[str] = None
    normal_password: Optional[str] = None
    admin_username: Optional[str] = None
    admin_password: Optional[str] = None
    enable_password: Optional[str] = None   # Cisco enable secret / privilege exec password
    auth_model: Optional[str] = None
    snmp_community: Optional[str] = None
    snmp_port: Optional[int] = None
    management_port: Optional[int] = None
    device_category: Optional[str] = None
    power_watts: Optional[int] = None
    production_mode: Optional[str] = None
    takeover_exempt_reason: Optional[str] = None
    credential_id: Optional[str] = None
    admin_credential_id: Optional[str] = None
    snmp_credential_id: Optional[str] = None
    tag_ids: Optional[list[str]] = None
    tag_codes: Optional[str] = None

    @field_validator('power_watts', mode='before')
    @classmethod
    def validate_power_watts_update(cls, v):
        if v is None or v == '':
            return 0
        try:
            return int(v)
        except (ValueError, TypeError):
            return 0



class BatchTakeoverRequest(BaseModel):
    asset_ids: list[str]


# ── Summary ──────────────────────────────────────────────────────────

@router.get('/assets/summary')
def asset_summary():
    conn = get_db_connection()
    try:
        total = conn.execute('SELECT COUNT(*) FROM physical_assets').fetchone()[0]
        servers = conn.execute("SELECT COUNT(*) FROM physical_assets WHERE asset_type = 'server'").fetchone()[0]
        network = conn.execute("SELECT COUNT(*) FROM physical_assets WHERE asset_type = 'network_device'").fetchone()[0]

        # Warranty expiring within 90 days
        now_str = _utc_now()[:10]
        future_str = (datetime.now(timezone.utc) + timedelta(days=90)).strftime('%Y-%m-%d')
        warranty_soon = conn.execute(
            "SELECT COUNT(*) FROM physical_assets WHERE warranty_expiry != '' AND warranty_expiry <= ? AND warranty_expiry >= ?",
            (future_str, now_str)
        ).fetchone()[0]

        # By status
        by_status = {}
        for row in conn.execute('SELECT status, COUNT(*) as cnt FROM physical_assets GROUP BY status'):
            by_status[row['status']] = row['cnt']

        # By vendor (top 10)
        by_vendor = {}
        for row in conn.execute("SELECT vendor, COUNT(*) as cnt FROM physical_assets WHERE vendor != '' GROUP BY vendor ORDER BY cnt DESC LIMIT 10"):
            by_vendor[row['vendor']] = row['cnt']

        # By CMDB site
        by_site = {}
        for row in conn.execute(
            """SELECT COALESCE(NULLIF(s.site_name, ''), NULLIF(s.site_code, ''), 'unassigned') AS site_name,
                      COUNT(*) AS cnt
               FROM physical_assets pa
               LEFT JOIN sites s ON s.id = pa.site_id
               GROUP BY s.site_name, s.site_code
               ORDER BY cnt DESC"""
        ):
            by_site[row['site_name']] = row['cnt']

        # By department
        by_department = {}
        for row in conn.execute("SELECT department, COUNT(*) as cnt FROM physical_assets WHERE department != '' GROUP BY department ORDER BY cnt DESC"):
            by_department[row['department']] = row['cnt']

        return {
            'total': total,
            'by_type': {'server': servers, 'network_device': network},
            'warranty_expiring_soon': warranty_soon,
            'by_status': by_status,
            'by_vendor': by_vendor,
            'by_site': by_site,
            'by_department': by_department,
        }
    finally:
        conn.close()


# ── List / Search ────────────────────────────────────────────────────

@router.get('/assets')
def list_assets(
    asset_type: str = 'all',
    vendor: str = '',
    site_id: str = '',
    department: str = '',
    device_category: str = '',
    lifecycle_status: str = '',
    status: str = 'all',
    device_role: str = '',
    tag_ids: str = '',
    tag_match_all: bool = True,
    q: str = '',
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
):
    conn = get_db_connection()
    try:
        conditions = []
        params = []

        if asset_type != 'all':
            conditions.append('pa.asset_type = ?')
            params.append(asset_type)
        if vendor:
            conditions.append('pa.vendor = ?')
            params.append(vendor)
        if site_id:
            conditions.append('pa.site_id = ?')
            params.append(site_id)
        if department:
            conditions.append('pa.department = ?')
            params.append(department)
        if device_category:
            conditions.append('pa.device_category = ?')
            params.append(device_category)
        if lifecycle_status and lifecycle_status != 'all':
            # Device onboarding is the authoritative lifecycle state for a
            # linked device; standalone assets use their own lifecycle field.
            conditions.append(
                "COALESCE(NULLIF(d.lifecycle_status, ''), NULLIF(pa.lifecycle_status, ''), 'staging') = ?"
            )
            params.append(lifecycle_status)
        if status != 'all':
            if status in ('online', 'offline', 'pending'):
                conditions.append(
                    "COALESCE(NULLIF(d.status, ''), CASE WHEN pa.status = 'active' THEN 'online' WHEN pa.status IN ('inactive', 'maintenance', 'decommissioned') THEN 'offline' ELSE 'pending' END) = ?"
                )
            else:
                conditions.append('pa.status = ?')
            params.append(status)
        if device_role:
            conditions.append('pa.device_role = ?')
            params.append(device_role)
        requested_tag_ids = [item.strip() for item in tag_ids.split(',') if item.strip()][:100]
        if requested_tag_ids:
            tag_exists = [
                "EXISTS (SELECT 1 FROM tag_assignments dt_filter WHERE dt_filter.resource_type='device' AND dt_filter.resource_id = d.id AND dt_filter.tag_id = ?)"
                for _ in requested_tag_ids
            ]
            if tag_match_all:
                conditions.extend(tag_exists)
            else:
                conditions.append(f"({' OR '.join(tag_exists)})")
            params.extend(requested_tag_ids)
        if q:
            conditions.append(
                "(pa.asset_tag LIKE ? OR pa.serial_number LIKE ? OR pa.hostname LIKE ? OR pa.vendor LIKE ? OR pa.model LIKE ? OR pa.management_ip LIKE ? OR pa.business_ip LIKE ? OR pa.rack LIKE ? OR s.site_name LIKE ? OR s.site_code LIKE ?)"
            )
            like = f'%{q}%'
            params.extend([like] * 10)

        where = (' WHERE ' + ' AND '.join(conditions)) if conditions else ''
        total = conn.execute(
            f'''SELECT COUNT(*) FROM physical_assets pa
                LEFT JOIN devices d ON d.asset_id = pa.id
                LEFT JOIN sites s ON s.id = pa.site_id{where}''',
            params,
        ).fetchone()[0]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f'''SELECT pa.*,
                d.id AS device_id,
                s.site_name,
                s.site_code,
                d.lifecycle_status AS device_lifecycle_status,
                COALESCE(NULLIF(d.status, ''), CASE WHEN pa.status = 'active' THEN 'online' WHEN pa.status IN ('inactive', 'maintenance', 'decommissioned') THEN 'offline' ELSE 'pending' END) AS online_status,
                COALESCE(NULLIF(pa.normal_username,''), d.normal_username, '') AS normal_username,
                COALESCE(NULLIF(pa.admin_username,''),  d.admin_username,  '') AS admin_username,
                COALESCE(NULLIF(pa.username,''),        d.username,        '') AS username
            FROM physical_assets pa
            LEFT JOIN devices d ON d.asset_id = pa.id
            LEFT JOIN sites s ON s.id = pa.site_id
            {where} ORDER BY pa.created_at DESC LIMIT ? OFFSET ?''',
            params + [page_size, offset]
        ).fetchall()

        # Sanitise sensitive fields: convert encrypted password columns into
        # boolean *_set flags so the frontend can show "configured/not configured"
        # without exposing ciphertext.
        items = []
        for r in rows:
            item = dict(r)
            if item.get('device_lifecycle_status'):
                item['lifecycle_status'] = item['device_lifecycle_status']
            item.pop('device_lifecycle_status', None)
            for sensitive in ('password', 'normal_password', 'admin_password', 'enable_password'):
                if sensitive in item:
                    item[f'{sensitive}_set'] = bool(item.get(sensitive))
                    # Keep the ciphertext out of the response payload
                    item[sensitive] = ''
            if 'snmp_community' in item:
                item['snmp_community_set'] = bool(item.get('snmp_community'))
                item['snmp_community'] = ''
            items.append(item)

        # Return tag definitions alongside assets so the asset inventory can
        # filter and display the same tags managed under /assets/tags.
        device_ids = [str(item.get('device_id') or '') for item in items if item.get('device_id')]
        tag_map: dict[str, list[dict]] = {}
        if device_ids:
            placeholders = ','.join('?' for _ in device_ids)
            tag_rows = conn.execute(
                    f'''SELECT dt.resource_id AS device_id, td.id, td.category, td.code, td.code AS value, td.label,
                           td.label_zh, td.color, td.icon, td.description,
                           td.sort_order, td.built_in, td.created_at, td.source_type, td.is_system
                    FROM tag_assignments dt
                    JOIN tag_definitions td ON td.id = dt.tag_id
                    WHERE dt.resource_type='device' AND dt.resource_id IN ({placeholders})
                    ORDER BY td.category, td.sort_order, td.code''',
                device_ids,
            ).fetchall()
            for tag_row in tag_rows:
                tag = dict(tag_row)
                device_id = str(tag.pop('device_id'))
                tag_map.setdefault(device_id, []).append(tag)
        for item in items:
            item['tags'] = tag_map.get(str(item.get('device_id') or ''), [])

        return {
            'items': items,
            'total': total,
            'page': page,
            'page_size': page_size,
            'total_pages': max(1, -(-total // page_size)),
        }
    finally:
        conn.close()


@router.get('/assets/tree')
def asset_tree():
    """Return a compact, server-side asset classification tree source."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            '''SELECT
                 COALESCE(NULLIF(pa.asset_type, ''), 'other') AS asset_type,
                 COALESCE(NULLIF(pa.device_category, ''), 'other') AS device_category,
                 COALESCE(NULLIF(pa.site_id, ''), 'unassigned') AS site_id,
                 COALESCE(NULLIF(s.site_name, ''), NULLIF(s.site_code, ''), 'Unassigned site') AS site_name,
                 COALESCE(NULLIF(d.status, ''),
                   CASE
                     WHEN pa.status = 'active' THEN 'online'
                     WHEN pa.status IN ('inactive', 'maintenance', 'decommissioned') THEN 'offline'
                     ELSE 'pending'
                   END
                 ) AS online_status,
                 COUNT(*) AS asset_count
               FROM physical_assets pa
               LEFT JOIN sites s ON s.id = pa.site_id
               LEFT JOIN devices d ON d.asset_id = pa.id
               GROUP BY pa.site_id, s.site_name, s.site_code, pa.asset_type,
                        pa.device_category, pa.device_role, pa.status, d.status
               ORDER BY site_name, pa.asset_type, pa.device_category, pa.device_role, online_status'''
        ).fetchall()
        return {'items': [dict(row) for row in rows]}
    finally:
        conn.close()


@router.get('/assets/{asset_id}')
def get_asset(asset_id: str):
    """Single asset row (same fields as list items) for rack drawer / cross-module detail."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            '''SELECT pa.*,
               COALESCE(NULLIF(pa.normal_username,''), d.normal_username, '') AS normal_username,
               COALESCE(NULLIF(pa.admin_username,''),  d.admin_username,  '') AS admin_username,
               COALESCE(NULLIF(pa.username,''),        d.username,        '') AS username
            FROM physical_assets pa
            LEFT JOIN devices d ON d.asset_id = pa.id
            WHERE pa.id = ?''',
            (asset_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Asset not found')
        item = dict(row)
        # Sanitise sensitive password fields
        for sensitive in ('password', 'normal_password', 'admin_password', 'enable_password'):
            if sensitive in item:
                item[f'{sensitive}_set'] = bool(item.get(sensitive))
                item[sensitive] = ''
        if 'snmp_community' in item:
            item['snmp_community_set'] = bool(item.get('snmp_community'))
            item['snmp_community'] = ''
        return item
    finally:
        conn.close()


# ── Create ───────────────────────────────────────────────────────────

@router.post('/assets')
def create_asset(body: AssetCreate):
    conn = get_db_connection()
    try:
        _pre_resolve_credential(conn, body)
        requested_tag_ids = _resolve_asset_tag_ids(conn, body)
        try:
            body.site_id = resolve_canonical_site_id(conn, body.site_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        asset_id = f"asset-{uuid.uuid4().hex[:12]}"
        body.snmp_credential_id = _resolve_snmp_credential_id(conn, body.snmp_credential_id)
        now = _utc_now()
        asset_origin = body.asset_origin if body.asset_origin in ('new', 'legacy') else 'new'
        body.platform = _normalize_asset_platform(body.vendor, body.platform, body.asset_type)
        legacy_production = asset_origin == 'legacy' and body.lifecycle_status == 'production'
        initial_lifecycle = 'production' if legacy_production else 'staging'
        if legacy_production:
            reason = (body.takeover_exempt_reason or '').strip()
            normal_username = (body.normal_username or body.username or '').strip()
            normal_password = (body.normal_password or body.password or '').strip()
            if len(reason) < 5:
                raise HTTPException(status_code=422, detail='存量设备直接投产必须填写至少 5 个字符的免上收原因。')
            if not normal_username or not normal_password:
                raise HTTPException(status_code=422, detail='存量设备直接投产必须配置普通账号用户名和密码。')

        duplicates = _find_asset_identity_duplicates(conn, body.model_dump())
        if duplicates:
            raise HTTPException(status_code=409, detail=_identity_duplicate_detail(duplicates))

        conn.execute('''
            INSERT INTO physical_assets (
                id, asset_type, asset_tag, serial_number, vendor, model, hostname,
                site_id, rack, rack_unit, u_height, planned_start_u, management_ip, business_ip, device_role,
                vlan, uplink_switch, uplink_port,
                status, lifecycle_status, asset_origin, purchase_date, warranty_expiry, department, notes,
                platform, connection_method, username, password,
                normal_username, normal_password, admin_username, admin_password,
                enable_password, auth_model,
                snmp_community, snmp_port, device_category, power_watts,
                credential_id, admin_credential_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            asset_id, body.asset_type, body.asset_tag, body.serial_number, body.vendor,
            body.model, body.hostname, body.site_id, body.rack, body.rack_unit,
            max(1, min(60, body.u_height)), body.planned_start_u,
            body.management_ip, body.business_ip, body.device_role,
            body.vlan, body.uplink_switch, body.uplink_port,
            body.status, initial_lifecycle, asset_origin,
            body.purchase_date, body.warranty_expiry, body.department, body.notes,
            body.platform, body.connection_method,
            body.username, _safe_encrypt(body.password),
            getattr(body, 'normal_username', '') or '',
            _safe_encrypt(getattr(body, 'normal_password', '') or ''),
            getattr(body, 'admin_username', '') or '',
            _safe_encrypt(getattr(body, 'admin_password', '') or ''),
            _safe_encrypt(getattr(body, 'enable_password', '') or ''),
            getattr(body, 'auth_model', '') or 'single',
            _safe_encrypt(body.snmp_community), body.snmp_port, body.device_category, body.power_watts,
            body.credential_id or '',
            body.admin_credential_id or '',
            now, now
        ))
        conn.execute('UPDATE physical_assets SET snmp_credential_id = ? WHERE id = ?', (body.snmp_credential_id or '', asset_id))

        # Plan-A: auto-create linked device for managed assets
        device_id = None
        if body.asset_type in ('network_device', 'server'):
            device_id = _create_linked_device(conn, asset_id, body)
            _sync_asset_tags(conn, asset_id, requested_tag_ids)
            if legacy_production:
                conn.execute(
                    "UPDATE devices SET lifecycle_status = 'production', rotation_status = 'exempt', "
                    "is_managed = 0 WHERE id = ?",
                    (device_id,),
                )
            logger.info('Auto-created device %s for asset %s (%s)', device_id, asset_id, body.asset_type)

        if legacy_production:
            conn.execute(
                "UPDATE physical_assets SET credential_governance_mode = 'legacy_exempt', "
                "takeover_exempt_reason = ?, takeover_exempt_at = ?, is_managed = 0 WHERE id = ?",
                ((body.takeover_exempt_reason or '').strip(), now, asset_id),
            )

        try:
            _sync_rack_device_from_asset(conn, asset_id, body)
        except ValueError as e:
            conn.rollback()
            raise HTTPException(status_code=400, detail=str(e))

        _sync_device_type_power(conn, body.vendor, body.model, body.power_watts, body.device_role, body.u_height)

        conn.commit()
        return {'id': asset_id, 'device_id': device_id, 'legacy_exempt': legacy_production}
    finally:
        conn.close()


# ── Update ───────────────────────────────────────────────────────────

@router.put('/assets/{asset_id}')
def update_asset(asset_id: str, body: AssetUpdate, run_bg_rotate: bool = True):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM physical_assets WHERE id = ?', (asset_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Asset not found')

        requested_tag_ids = _resolve_asset_tag_ids(conn, body)

        if body.site_id is not None:
            try:
                body.site_id = resolve_canonical_site_id(conn, body.site_id)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))

        # Normalize and validate bound credential references before any
        # lifecycle checks or asset writes. This also refreshes the local
        # compatibility cache from the authoritative vault row.
        _pre_resolve_credential(conn, body)

        effective_vendor = body.vendor if body.vendor is not None else row['vendor']
        effective_asset_type = body.asset_type if body.asset_type is not None else row['asset_type']
        effective_platform = body.platform if body.platform is not None else row['platform']
        normalized_platform = _normalize_asset_platform(
            effective_vendor,
            effective_platform,
            effective_asset_type,
        )
        if normalized_platform != effective_platform or body.platform is not None or body.vendor is not None:
            body.platform = normalized_platform

        identity_values = {
            field: getattr(body, field) if getattr(body, field, None) is not None else row[field]
            for field in _ASSET_IDENTITY_FIELDS
        }
        duplicates = _find_asset_identity_duplicates(conn, identity_values, exclude_asset_id=asset_id)
        if duplicates:
            raise HTTPException(status_code=409, detail=_identity_duplicate_detail(duplicates))

        # Detect lifecycle transition for auto password rotation
        old_lifecycle = row['lifecycle_status'] if 'lifecycle_status' in row.keys() else 'staging'
        new_lifecycle = body.lifecycle_status if body.lifecycle_status is not None else old_lifecycle
        transitioning_to_production = (new_lifecycle == 'production' and old_lifecycle != 'production')
        legacy_exempt = transitioning_to_production and body.production_mode == 'legacy_exempt'
        if legacy_exempt and (row['asset_origin'] or 'new') != 'legacy':
            raise HTTPException(status_code=422, detail='只有标记为存量设备的资产才能使用免上收投产。')

        # ── Pre-flight: block production transition if onboarding not complete ──
        if transitioning_to_production and row['asset_type'] in ('network_device', 'server'):
            device_row = conn.execute(
                'SELECT id, onboarding_status, username, password, ip_address, '
                'normal_username, normal_password, admin_username, admin_password, auth_model, '
                'credential_source, credential_id, vault_path '
                'FROM devices WHERE asset_id = ?',
                (asset_id,)
            ).fetchone()
            if not device_row:
                raise HTTPException(
                    status_code=422,
                    detail='投产前请先完成设备关联与口令上收准备，当前资产缺少关联设备记录。'
                )
            if device_row:
                device_row = dict(device_row)
                ob_status = device_row['onboarding_status'] or 'pending_credentials'
                if ob_status not in ('verified', 'active'):
                    status_labels = {
                        'pending_credentials': '待设置凭据',
                        'credentials_set': '待验证连通性',
                    }
                    hint = status_labels.get(ob_status, ob_status)
                    raise HTTPException(
                        status_code=422,
                        detail=f'投产前请先完成口令上手流程（当前状态: {hint}）。请在设备详情中完成凭据设置与连通性验证。'
                    )
                # Also check credentials exist - merge values from request body
                # (body may carry new username/password that hasn't been persisted yet)
                from services.vault_service import resolve_device_credentials
                creds = resolve_device_credentials(device_row)
                
                auth_model = getattr(body, 'auth_model', None) or device_row.get('auth_model', 'single')
                
                ip = (getattr(body, 'management_ip', None) or device_row.get('ip_address', '') or '').strip()
                
                missing = []
                if not ip:
                    missing.append('管理IP')

                if legacy_exempt:
                    reason = (body.takeover_exempt_reason or '').strip()
                    if len(reason) < 5:
                        raise HTTPException(status_code=422, detail='存量设备免上收投产必须填写至少 5 个字符的豁免原因。')
                    normal_username = (
                        getattr(body, 'normal_username', None)
                        or creds.get('normal_username')
                        or creds.get('username')
                        or ''
                    ).strip()
                    normal_password = (
                        getattr(body, 'normal_password', None)
                        or creds.get('normal_password')
                        or creds.get('password')
                        or ''
                    ).strip()
                    if not normal_username: missing.append('普通用户名')
                    if not normal_password: missing.append('普通密码')
                elif auth_model == 'dual':
                    # For dual mode: body password fields take priority; if left blank (edit mode),
                    # fall back to existing DB values. Also accept legacy/resolved 'password' field as fallback
                    # for both normal and admin passwords so old single-mode records don't block production transition.
                    n_uname = (getattr(body, 'normal_username', None) or creds.get('normal_username') or creds.get('username') or '').strip()
                    n_pwd_body = getattr(body, 'normal_password', None)
                    n_pwd = (n_pwd_body if n_pwd_body else None) or \
                            creds.get('normal_password') or \
                            creds.get('password') or ''
                    n_pwd = n_pwd.strip()

                    a_uname = (getattr(body, 'admin_username', None) or creds.get('admin_username') or creds.get('username') or '').strip()
                    a_pwd_body = getattr(body, 'admin_password', None)
                    a_pwd = (a_pwd_body if a_pwd_body else None) or \
                            creds.get('admin_password') or \
                            creds.get('password') or ''
                    a_pwd = a_pwd.strip()

                    if not n_uname: missing.append('普通用户名')
                    if not n_pwd:   missing.append('普通密码')
                    if not a_uname: missing.append('特权用户名')
                    if not a_pwd:   missing.append('特权密码')
                else:
                    uname = (getattr(body, 'username', None) or creds.get('username') or '').strip()
                    pwd_body = getattr(body, 'password', None)
                    pwd = (pwd_body if pwd_body else None) or \
                          creds.get('password') or ''
                    pwd = pwd.strip()
                    if not uname: missing.append('用户名')
                    if not pwd:   missing.append('密码')

                if missing:
                    raise HTTPException(
                        status_code=422,
                        detail=f'投产前请先配置设备凭据（缺少: {", ".join(missing)}）'
                    )

        updates = []
        params = []
        updatable = [
            'asset_type', 'asset_tag', 'serial_number', 'vendor', 'model', 'hostname',
            'site_id', 'rack', 'rack_unit', 'u_height', 'planned_start_u', 'management_ip', 'business_ip', 'device_role',
            'vlan', 'uplink_switch', 'uplink_port',
            'status', 'lifecycle_status', 'asset_origin', 'purchase_date', 'warranty_expiry', 'department', 'notes',
            'platform', 'connection_method', 'username', 'password',
            'normal_username', 'normal_password', 'admin_username', 'admin_password', 'enable_password', 'auth_model',
            'snmp_community', 'snmp_port', 'management_port', 'device_category', 'power_watts', 'credential_id', 'admin_credential_id', 'snmp_credential_id'
        ]
        for field in updatable:
            val = getattr(body, field, None)
            if val is not None:
                if field == 'snmp_credential_id':
                    val = _resolve_snmp_credential_id(conn, val)
                if field == 'lifecycle_status' and transitioning_to_production:
                    continue
                if field in ('password', 'normal_password', 'admin_password', 'enable_password', 'snmp_community'):
                    # Empty string = "keep existing" — skip the update
                    if val != '':
                        updates.append(f'{field} = ?')
                        params.append(_safe_encrypt(val))
                else:
                    updates.append(f'{field} = ?')
                    params.append(_safe_encrypt(val) if field == 'snmp_community' else val)

        if legacy_exempt:
            exempt_reason = (body.takeover_exempt_reason or '').strip()
            exempt_at = _utc_now()
            if updates:
                updates.append('updated_at = ?')
                params.extend([exempt_at, asset_id])
                conn.execute(f"UPDATE physical_assets SET {', '.join(updates)} WHERE id = ?", tuple(params))
                updated_row = conn.execute("SELECT * FROM physical_assets WHERE id = ?", (asset_id,)).fetchone()
                try:
                    _sync_rack_device_from_asset(conn, asset_id, updated_row)
                except ValueError as exc:
                    conn.rollback()
                    raise HTTPException(status_code=400, detail=str(exc))
                _sync_device_from_asset(conn, asset_id, body)
            conn.execute(
                "UPDATE physical_assets SET lifecycle_status = 'production', is_managed = 0, "
                "credential_governance_mode = 'legacy_exempt', takeover_exempt_reason = ?, "
                "takeover_exempt_at = ?, takeover_error = '', updated_at = ? WHERE id = ?",
                (exempt_reason, exempt_at, exempt_at, asset_id),
            )
            conn.execute(
                "UPDATE devices SET lifecycle_status = 'production', rotation_status = 'exempt', "
                "is_managed = 0, takeover_error = '' WHERE asset_id = ?",
                (asset_id,),
            )
            _sync_asset_tags(conn, asset_id, requested_tag_ids)
            conn.commit()
            return {
                'ok': True,
                'password_rotated': False,
                'rotation_pending': False,
                'rotation_detail': None,
                'lifecycle_reverted': False,
                'legacy_exempt': True,
            }

        rotation_result = None
        if updates or transitioning_to_production:
            updates.append('updated_at = ?')
            params.append(_utc_now())
            params.append(asset_id)
            conn.execute(f"UPDATE physical_assets SET {', '.join(updates)} WHERE id = ?", tuple(params))

            # Sync and validate rack device placement
            updated_row = conn.execute("SELECT * FROM physical_assets WHERE id = ?", (asset_id,)).fetchone()
            try:
                _sync_rack_device_from_asset(conn, asset_id, updated_row)
            except ValueError as e:
                conn.rollback()
                raise HTTPException(status_code=400, detail=str(e))

            # Plan-A: sync basic info to linked device
            current_type = body.asset_type if body.asset_type is not None else row['asset_type']
            if current_type in ('network_device', 'server'):
                _sync_device_from_asset(conn, asset_id, body)
                # Also sync lifecycle_status to linked device
                if body.lifecycle_status is not None and not transitioning_to_production:
                    conn.execute(
                        'UPDATE devices SET lifecycle_status = ? WHERE asset_id = ?',
                        (body.lifecycle_status, asset_id)
                    )

            row_dict = dict(row)
            _sync_device_type_power(
                conn,
                body.vendor if body.vendor is not None else row_dict.get('vendor', ''),
                body.model if body.model is not None else row_dict.get('model', ''),
                body.power_watts if body.power_watts is not None else row_dict.get('power_watts', 0),
                body.device_role if body.device_role is not None else row_dict.get('device_role', 'switch'),
                body.u_height if body.u_height is not None else row_dict.get('u_height', 1)
            )

            conn.commit()


            # Auto-rotate default password when transitioning to production
            # Run in background thread to avoid blocking HTTP response (~8-10s SSH)
            if transitioning_to_production:
                device_row = conn.execute(
                    'SELECT id FROM devices WHERE asset_id = ?', (asset_id,)
                ).fetchone()
                if device_row:
                    _device_id = device_row['id'] if isinstance(device_row, dict) else device_row[0]
                    # Mark rotation pending immediately
                    conn.execute(
                        "UPDATE devices SET rotation_status = 'rotating' WHERE id = ?",
                        (_device_id,)
                    )
                    conn.commit()

                    def _bg_rotate(dev_id: str, a_id: str, old_lc: str):
                        try:
                            from services.password_rotation_service import rotate_password
                            # Fetch current device state to check auth_model and management_port
                            bg_conn_init = get_db_connection()
                            try:
                                dev_state = bg_conn_init.execute('SELECT auth_model, hostname FROM devices WHERE id = ?', (dev_id,)).fetchone()
                            finally:
                                bg_conn_init.close()
                                
                            auth_model = dev_state['auth_model'] if dev_state else 'single'
                            hostname = dev_state['hostname'] if dev_state else dev_id
                            
                            # Start the atomic takeover sequence.
                            logger.info(f"[Takeover] Starting Admin role for {hostname}")
                            admin_result = rotate_password(dev_id, role='admin')
                            if not admin_result or not admin_result.get('success'):
                                raise Exception(f"特权账号改密失败: {admin_result.get('message') if admin_result else '连接超时'}")
                            logger.info(f"[Takeover] Admin role success for {hostname}")

                            if auth_model == 'dual':
                                logger.info(f"[Takeover] Starting Normal role for {hostname}")
                                normal_result = rotate_password(dev_id, role='normal')
                                if not normal_result or not normal_result.get('success'):
                                    raise Exception(f"普通账号改密失败: {normal_result.get('message') if normal_result else '连接超时'}")
                                logger.info(f"[Takeover] Normal role success for {hostname}")

                            logger.info(f"[Takeover] Takeover success for {hostname}. Transitioning to production.")
                            # SUCCESS: Commit lifecycle change and clear errors
                            bg_conn = get_db_connection()
                            try:
                                bg_conn.execute(
                                    "UPDATE devices SET rotation_status = 'completed', onboarding_status = 'active', lifecycle_status = 'production', status = 'online', is_managed = 1, takeover_error = '' WHERE id = ?",
                                    (dev_id,)
                                )
                                tag_service.sync_device_status_tag(bg_conn, dev_id, 'online')
                                bg_conn.execute(
                                    "UPDATE physical_assets SET lifecycle_status = 'production', is_managed = 1, takeover_error = '' WHERE id = ?",
                                    (a_id,)
                                )
                                bg_conn.commit()
                            finally:
                                bg_conn.close()

                        except Exception as e:
                            err_msg = str(e)
                            logger.error(f"[Takeover] FAILED for {dev_id}: {err_msg}")
                            try:
                                bg_conn_fail = get_db_connection()
                                # Rollback lifecycle status on failure
                                bg_conn_fail.execute(
                                    "UPDATE devices SET rotation_status = 'failed', lifecycle_status = ?, takeover_error = ? WHERE id = ?",
                                    (old_lc, err_msg, dev_id)
                                )
                                bg_conn_fail.execute(
                                    'UPDATE physical_assets SET lifecycle_status = ?, takeover_error = ? WHERE id = ?',
                                    (old_lc, err_msg, a_id)
                                )
                                bg_conn_fail.commit()
                                bg_conn_fail.close()
                            except Exception:
                                pass

                    if run_bg_rotate:
                        threading.Thread(
                            target=_bg_rotate,
                            args=(_device_id, asset_id, old_lifecycle),
                            daemon=True,
                        ).start()
                    rotation_result = {'pending': True}

        if requested_tag_ids is not None:
            _sync_asset_tags(conn, asset_id, requested_tag_ids)
            conn.commit()

        return {
            'ok': True,
            'password_rotated': rotation_result is not None and rotation_result.get('success', False),
            'rotation_pending': rotation_result is not None and rotation_result.get('pending', False),
            'rotation_detail': rotation_result.get('message', '') if rotation_result and not rotation_result.get('pending') else None,
            'lifecycle_reverted': rotation_result is not None and not rotation_result.get('success', False) and not rotation_result.get('pending', False),
        }
    finally:
        conn.close()


# ── Delete ───────────────────────────────────────────────────────────

@router.delete('/assets/{asset_id}')
def delete_asset(asset_id: str):
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT id FROM physical_assets WHERE id = ?', (asset_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Asset not found')
        # Plan-A: cascade-delete linked device first
        _delete_linked_device(conn, asset_id)

        # Cascade-delete linked rack device if exists
        conn.execute('DELETE FROM rack_devices WHERE asset_id = ?', (asset_id,))

        # PAM: archive (don't delete) sessions and access requests so the audit
        # trail survives asset removal. We mark `archived = 1` here; the FK on
        # asset_id is configured ON DELETE SET NULL (PG) so the column itself
        # is nulled automatically when physical_assets is deleted below.
        # Tokens are short-lived and have no audit value, so they are still
        # hard-deleted to free the asset_id reference cleanly.
        now_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')
        conn.execute(
            "UPDATE pam_sessions SET archived = 1, updated_at = ? WHERE asset_id = ?",
            (now_iso, asset_id),
        )
        conn.execute(
            "UPDATE pam_access_requests SET updated_at = ? WHERE asset_id = ?",
            (now_iso, asset_id),
        )
        conn.execute('DELETE FROM pam_session_tokens WHERE asset_id = ?', (asset_id,))

        conn.execute('DELETE FROM physical_assets WHERE id = ?', (asset_id,))
        conn.commit()
        return {'ok': True}
    finally:
        conn.close()


# ── Rotation status polling ──────────────────────────────────────────

@router.get('/assets/{asset_id}/rotation-status')
def get_rotation_status(asset_id: str):
    """Poll rotation progress after async production transition."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT d.rotation_status, d.lifecycle_status, d.password_last_rotated, d.takeover_error '
            'FROM devices d WHERE d.asset_id = ?', (asset_id,)
        ).fetchone()
        if not row:
            return {'rotation_status': 'none'}
        return {
            'rotation_status': row['rotation_status'] or '',
            'lifecycle_status': row['lifecycle_status'] or 'staging',
            'password_last_rotated': row['password_last_rotated'] or '',
            'takeover_error': row['takeover_error'] or '',
        }
    finally:
        conn.close()


# ── Import (batch) ───────────────────────────────────────────────────

@router.post('/assets/import')
def import_assets(items: list[AssetCreate]):
    conn = get_db_connection()
    try:
        now = _utc_now()
        created = 0
        skipped = 0
        skipped_items = []
        for body in items:
            _pre_resolve_credential(conn, body)
            requested_tag_ids = _resolve_asset_tag_ids(conn, body)
            try:
                body.site_id = resolve_canonical_site_id(conn, body.site_id)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            asset_id = f"asset-{uuid.uuid4().hex[:12]}"
            body.platform = _normalize_asset_platform(body.vendor, body.platform, body.asset_type)
            asset_origin = body.asset_origin if body.asset_origin in ('new', 'legacy') else 'new'
            legacy_production = asset_origin == 'legacy' and body.lifecycle_status == 'production'
            initial_lifecycle = 'production' if legacy_production else 'staging'
            if not (body.hostname or '').strip() and not (body.asset_tag or '').strip():
                raise HTTPException(status_code=422, detail='导入资产必须至少填写主机名或资产编号')
            if legacy_production:
                reason = (body.takeover_exempt_reason or '').strip()
                normal_username = (body.normal_username or body.username or '').strip()
                normal_password = (body.normal_password or body.password or '').strip()
                if len(reason) < 5:
                    raise HTTPException(status_code=422, detail='存量设备直接投产必须填写至少 5 个字符的免上收原因')
                if not normal_username or not normal_password:
                    raise HTTPException(status_code=422, detail='存量设备直接投产必须配置普通账号用户名和密码')
            duplicates = _find_asset_identity_duplicates(conn, body.model_dump())
            if duplicates:
                skipped += 1
                skipped_items.append({
                    'asset_tag': body.asset_tag,
                    'hostname': body.hostname,
                    'reason': 'duplicate_identity',
                    'duplicate_fields': [item['field'] for item in duplicates],
                    'duplicate_labels': [item['label'] for item in duplicates],
                    'duplicate_values': [item['value'] for item in duplicates],
                    'existing_hostname': next(
                        (item['existing_hostname'] for item in duplicates if item['existing_hostname']),
                        '',
                    ),
                })
                continue

            conn.execute('''
                INSERT INTO physical_assets (
                    id, asset_type, asset_tag, serial_number, vendor, model, hostname,
                    site_id, rack, rack_unit, u_height, planned_start_u, management_ip, business_ip, device_role,
                    vlan, uplink_switch, uplink_port,
                    status, lifecycle_status, asset_origin, purchase_date, warranty_expiry, department, notes,
                    platform, connection_method, username, password,
                    normal_username, normal_password, admin_username, admin_password,
                    enable_password, auth_model,
                    snmp_community, snmp_port, management_port, device_category, power_watts,
                    credential_governance_mode, takeover_exempt_reason, takeover_exempt_at, is_managed,
                    credential_id, admin_credential_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                asset_id, body.asset_type, body.asset_tag, body.serial_number, body.vendor,
                body.model, body.hostname, body.site_id, body.rack, body.rack_unit,
                max(1, min(60, body.u_height)), body.planned_start_u,
                body.management_ip, body.business_ip, body.device_role,
                body.vlan, body.uplink_switch, body.uplink_port,
                body.status, initial_lifecycle, asset_origin,
                body.purchase_date, body.warranty_expiry, body.department, body.notes,
                body.platform, body.connection_method, body.username, _safe_encrypt(body.password),
                getattr(body, 'normal_username', '') or '',
                _safe_encrypt(getattr(body, 'normal_password', '') or ''),
                getattr(body, 'admin_username', '') or '',
                _safe_encrypt(getattr(body, 'admin_password', '') or ''),
                _safe_encrypt(getattr(body, 'enable_password', '') or ''),
                getattr(body, 'auth_model', '') or 'single',
                _safe_encrypt(body.snmp_community), body.snmp_port,
                getattr(body, 'management_port', 22) or 22,
                body.device_category, body.power_watts,
                'legacy_exempt' if legacy_production else 'managed',
                (body.takeover_exempt_reason or '').strip() if legacy_production else '',
                now if legacy_production else None,
                0 if legacy_production else 1,
                body.credential_id or '',
                body.admin_credential_id or '',
                now, now
            ))
            conn.execute('UPDATE physical_assets SET snmp_credential_id = ? WHERE id = ?', (body.snmp_credential_id or '', asset_id))
            # Plan-A: auto-create linked device for managed assets
            if body.asset_type in ('network_device', 'server'):
                device_id = _create_linked_device(conn, asset_id, body)
                _sync_asset_tags(conn, asset_id, requested_tag_ids)
                if legacy_production:
                    conn.execute(
                        "UPDATE devices SET lifecycle_status = 'production', rotation_status = 'exempt', is_managed = 0 WHERE id = ?",
                        (device_id,),
                    )
            
            try:
                _sync_rack_device_from_asset(conn, asset_id, body)
            except ValueError as e:
                logger.warning("Failed to sync rack device during import for asset %s: %s", asset_id, e)

            created += 1
        conn.commit()
        return {
            'created': created,
            'skipped': skipped,
            'skipped_items': skipped_items,
        }
    finally:
        conn.close()

@router.get("/assets/{asset_id}/verify")
async def verify_asset_connectivity(asset_id: str):
    """
    Perform a quick connectivity check:
    1. Ping management IP
    2. Try the configured SSH management port (defaults to 22)
    3. If credentials exist, try SSH login (fast)
    """
    conn = get_db_connection()
    try:
        asset = conn.execute('SELECT * FROM physical_assets WHERE id = ?', (asset_id,)).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        
        asset = dict(asset)
        ip = asset.get('management_ip')
        if not ip:
            return {"success": False, "error": "No management IP configured", "ping": False, "ssh": False}

        results = {
            "ping": False,
            "ssh": False,
            "latency": 0,
            "ssh_error": None,
            "ping_error": None
        }

        # 1. Ping Test
        try:
            latency = ping3.ping(ip, timeout=1)
            if latency is not None and latency is not False:
                results["ping"] = True
                results["latency"] = round(latency * 1000, 2)
            else:
                results["ping_error"] = "Ping timeout"
        except Exception as e:
            results["ping_error"] = str(e)

        # 2. SSH Port Test (Quick check)
        from services.connection_profile import resolve_ssh_port
        ssh_port = resolve_ssh_port(asset)
        try:
            with socket.create_connection((ip, ssh_port), timeout=1):
                results["ssh_port_open"] = True
        except Exception:
            results["ssh_port_open"] = False
            results["ssh_error"] = "SSH port closed or unreachable"
            return results

        # 3. SSH Login Test (if credentials found)
        # Check physical_assets first, then linked device
        username = asset.get('username')
        password_enc = asset.get('password')
        
        if not username or not password_enc:
            dev = conn.execute('SELECT username, password, platform FROM devices WHERE asset_id = ?', (asset_id,)).fetchone()
            if dev:
                username = dev['username']
                password_enc = dev['password']
                # FORCE linux if it's a server
                if asset['asset_type'] == 'server':
                    platform = 'linux'
                else:
                    platform = dev['platform']
            else:
                platform = _platform_from_vendor(asset['vendor'], asset['asset_type'])
        else:
            if asset['asset_type'] == 'server':
                platform = 'linux'
            else:
                platform = _platform_from_vendor(asset['vendor'], asset['asset_type'])

        if username and password_enc:
            try:
                password = decrypt_credential(password_enc)
                # Use Scrapli for a quick "fast" login
                # We just want to see if we can get a prompt
                import platform as platform_module
                device_config = {
                    "host": ip,
                    "port": ssh_port,
                    "auth_username": username,
                    "auth_password": password,
                    "platform": platform or "linux",
                    "auth_strict_key": False,
                    "timeout_socket": 5,
                    "timeout_transport": 10,
                }
                
                # Windows compatibility (same as ScrapliDriver)
                if platform_module.system() == 'Windows':
                    device_config['transport'] = 'paramiko'
                    device_config['transport_options'] = {
                        'paramiko_open_options': {
                            'look_for_keys': False,
                            'allow_agent': False,
                        }
                    }

                if asset['asset_type'] == 'server':
                    # FOR SERVERS: Use direct Paramiko to avoid prompt detection complexity
                    import paramiko
                    client = paramiko.SSHClient()
                    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    try:
                        client.connect(
                            hostname=ip,
                            username=username,
                            password=password,
                            port=ssh_port,
                            timeout=10,
                            allow_agent=False,
                            look_for_keys=False,
                            disabled_algorithms={}
                        )
                        results["ssh"] = True
                        results["ssh_summary"] = "SSH 登录验证成功 (直接认证通过)"
                    finally:
                        client.close()
                else:
                    # FOR NETWORK DEVICES: Use Scrapli for full stateful check
                    with Scrapli(**device_config) as conn_ssh:
                        results["ssh"] = True
                        results["ssh_summary"] = f"SSH 登录验证成功 ({platform} 提示符已捕获)"
            except Exception as e:
                err_str = str(e)
                logger.error(f"Asset verification failed for {ip}: {err_str}", exc_info=True)
                # Humanize the error for the UI
                err_code = get_ssh_error_code(err_str)
                if err_code == 'ssh_authentication_failed':
                    results["ssh_error"] = "认证失败：用户名或密码错误，或服务器禁用了密码登录"
                elif err_code == 'ssh_transport_timeout':
                    results["ssh_error"] = "连接超时：网络不通或 SSH 服务未响应"
                elif 'ScrapliConnectionNotOpened' in err_str:
                    results["ssh_error"] = "连接未建立：请检查 IP 和端口"
                else:
                    # 不将原始 Python 异常暴露给前端
                    results["ssh_error"] = "服务内部异常，请联系管理员查看后端日志"
        else:
            results["ssh_error"] = "No credentials provided for login test"

        return results
    finally:
        conn.close()


TAKEOVER_CONCURRENCY = int(os.environ.get('TAKEOVER_CONCURRENCY', '10'))
TAKEOVER_MAX_LIMIT = 100

def _run_batch_takeover(tasks: list[dict]):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from services.password_rotation_service import rotate_password

    start_time = time.time()
    total_tasks = len(tasks)
    logger.info(f"[Batch Takeover] Starting batch takeover task for {total_tasks} devices... Concurrency limit: {TAKEOVER_CONCURRENCY} at a time.")

    success_count = 0
    failed_count = 0

    def _worker(task):
        nonlocal success_count, failed_count
        dev_id = task['dev_id']
        a_id = task['a_id']
        old_lc = task['old_lc']
        hostname = task['hostname']

        try:
            # Re-fetch current device state to check auth_model
            bg_conn_init = get_db_connection()
            try:
                dev_state = bg_conn_init.execute('SELECT auth_model, hostname FROM devices WHERE id = ?', (dev_id,)).fetchone()
            finally:
                bg_conn_init.close()
                
            auth_model = dev_state['auth_model'] if dev_state else 'single'
            hostname = dev_state['hostname'] if dev_state else dev_id
            
            # Start the atomic takeover sequence.
            logger.info(f"[Takeover] Starting Admin role for {hostname}")
            admin_result = rotate_password(dev_id, role='admin')
            if not admin_result or not admin_result.get('success'):
                raise Exception(f"特权账号改密失败: {admin_result.get('message') if admin_result else '连接超时'}")
            logger.info(f"[Takeover] Admin role success for {hostname}")

            if auth_model == 'dual':
                logger.info(f"[Takeover] Starting Normal role for {hostname}")
                normal_result = rotate_password(dev_id, role='normal')
                if not normal_result or not normal_result.get('success'):
                    raise Exception(f"普通账号改密失败: {normal_result.get('message') if normal_result else '连接超时'}")
                logger.info(f"[Takeover] Normal role success for {hostname}")

            # SUCCESS: Commit lifecycle change and clear errors
            logger.info(f"[Takeover] Takeover success for {hostname}. Transitioning to production.")
            bg_conn = get_db_connection()
            try:
                bg_conn.execute(
                    "UPDATE devices SET rotation_status = 'completed', onboarding_status = 'active', lifecycle_status = 'production', status = 'online', is_managed = 1, takeover_error = '' WHERE id = ?",
                    (dev_id,)
                )
                tag_service.sync_device_status_tag(bg_conn, dev_id, 'online')
                bg_conn.execute(
                    "UPDATE physical_assets SET lifecycle_status = 'production', is_managed = 1, takeover_error = '' WHERE id = ?",
                    (a_id,)
                )
                bg_conn.commit()
            finally:
                bg_conn.close()
            success_count += 1

        except Exception as e:
            err_msg = str(e)
            logger.error(f"[Takeover] FAILED for {dev_id}: {err_msg}")
            failed_count += 1
            try:
                bg_conn_fail = get_db_connection()
                # Rollback lifecycle status on failure
                bg_conn_fail.execute(
                    "UPDATE devices SET rotation_status = 'failed', lifecycle_status = ?, takeover_error = ? WHERE id = ?",
                    (old_lc, err_msg, dev_id)
                )
                bg_conn_fail.execute(
                    'UPDATE physical_assets SET lifecycle_status = ?, takeover_error = ? WHERE id = ?',
                    (old_lc, err_msg, a_id)
                )
                bg_conn_fail.commit()
                bg_conn_fail.close()
            except Exception:
                pass

    with ThreadPoolExecutor(max_workers=TAKEOVER_CONCURRENCY) as executor:
        executor.map(_worker, tasks)

    duration = round(time.time() - start_time, 2)
    logger.info(f"[Batch Takeover] Done - {success_count} succeeded, {failed_count} failed. Concurrency limit: {TAKEOVER_CONCURRENCY}. Total elapsed time: {duration} seconds.")


@router.post('/assets/takeover/batch')
def batch_takeover(body: BatchTakeoverRequest):
    """
    Batch transition multiple assets to production state, triggering atomic takeover.
    """
    if len(body.asset_ids) > TAKEOVER_MAX_LIMIT:
        raise HTTPException(status_code=400, detail=f'批量上收的设备数量超过上限（最多支持 {TAKEOVER_MAX_LIMIT} 台设备）')

    results = []
    tasks = []
    
    conn = get_db_connection()
    try:
        for asset_id in body.asset_ids:
            try:
                # First check old lifecycle
                row = conn.execute('SELECT lifecycle_status FROM physical_assets WHERE id = ?', (asset_id,)).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail='Asset not found')
                old_lc = row['lifecycle_status']
                
                # Check linked device
                device_row = conn.execute(
                    'SELECT id, hostname, ip_address, credential_id, admin_credential_id '
                    'FROM devices WHERE asset_id = ?',
                    (asset_id,),
                ).fetchone()
                if not device_row:
                    raise HTTPException(status_code=404, detail='Linked device not found')
                dev_id = device_row['id']
                hostname = device_row['hostname']

                # A device bound to the credential center must be changed through
                # the credential sync workflow.  Starting takeover here would
                # only fail later in the background worker and leave the user
                # with a misleading "started" message.
                credential_ids = [
                    value for value in (device_row['credential_id'], device_row['admin_credential_id'])
                    if value
                ]
                shared_credential_ids: list[str] = []
                shared_credential_names: list[str] = []
                for credential_id in credential_ids:
                    credential_row = conn.execute(
                        'SELECT id, credential_name, account_role FROM credentials WHERE id = ?',
                        (credential_id,),
                    ).fetchone()
                    if credential_is_shared(conn, credential_id, dict(credential_row) if credential_row else None, device_hostname=hostname):
                        shared_credential_ids.append(credential_id)
                        if credential_row:
                            shared_credential_names.append(str(credential_row['credential_name'] or credential_id))

                if shared_credential_ids:
                    results.append({
                        'id': asset_id,
                        'status': 'blocked_credential',
                        'hostname': hostname,
                        'management_ip': device_row['ip_address'] or '',
                        'credential_id': device_row['credential_id'] if device_row['credential_id'] in shared_credential_ids else '',
                        'admin_credential_id': device_row['admin_credential_id'] if device_row['admin_credential_id'] in shared_credential_ids else '',
                        'credential_name': '、'.join(shared_credential_names),
                        'message': '该设备已绑定凭据，不能执行批量口令上收；请从凭据中心发起密码同步',
                    })
                    continue
                
                # Run update_asset with run_bg_rotate=False
                update_asset(asset_id, AssetUpdate(lifecycle_status='production'), run_bg_rotate=False)
                
                tasks.append({
                    'dev_id': dev_id,
                    'a_id': asset_id,
                    'old_lc': old_lc,
                    'hostname': hostname
                })
                
                results.append({
                    'id': asset_id,
                    'status': 'triggered',
                    'hostname': hostname,
                    'management_ip': device_row['ip_address'] or '',
                    'message': 'Takeover process started in background'
                })
            except HTTPException as e:
                results.append({
                    'id': asset_id,
                    'status': 'error',
                    'message': str(e.detail)
                })
            except Exception as e:
                results.append({
                    'id': asset_id,
                    'status': 'error',
                    'message': str(e)
                })
    finally:
        conn.close()
        
    if tasks:
        import threading
        threading.Thread(
            target=_run_batch_takeover,
            args=(tasks,),
            daemon=True
        ).start()
        
    return {
        'results': results,
        'triggered_count': sum(1 for item in results if item['status'] == 'triggered'),
        'blocked_count': sum(1 for item in results if item['status'] == 'blocked_credential'),
    }
