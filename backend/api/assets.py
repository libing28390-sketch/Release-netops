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
import time
import ipaddress
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from database import get_db_connection
from core.crypto import encrypt_credential, decrypt_credential
from core.rbac import enforce_resource_scope, require_role
from core.context import request_id_var
from drivers.ssh_compat import get_ssh_error_code, build_ssh_error_guidance
from services import tag_service
from services import rack_scope_service
from services.vault_service import credential_is_shared, resolve_collector_credentials
from services.site_identity_service import resolve_canonical_site_id
from services.pam_web_service import replace_asset_web_profiles
from services.audit_service import log_audit_event
from schemas.web import WebAccessProfileInput

import ping3
import socket
from scrapli import Scrapli

logger = logging.getLogger(__name__)

# Asset inventory is a CMDB surface.  Keep reads available to authenticated
# viewers, while write/external-action routes below declare their stronger
# role requirements explicitly.  This also prevents newly added asset routes
# from accidentally becoming anonymous endpoints.
router = APIRouter(dependencies=[require_role("Viewer")])

_ASSET_IDENTITY_FIELDS = ('hostname', 'asset_tag', 'serial_number', 'management_ip')
_ASSET_IDENTITY_LABELS = {
    'hostname': '主机名',
    'asset_tag': '资产编号',
    'serial_number': '序列号',
    'management_ip': '管理IP',
}

# The inventory tables contain operational, credential-governance and
# migration-only columns that are not part of the public asset contract.  Keep
# the compatibility SQL joins for now, but make the response projection
# explicit so a future schema column cannot silently become an API field.
_PUBLIC_ASSET_FIELDS = frozenset({
    'id', 'asset_type', 'asset_tag', 'serial_number', 'vendor', 'model',
    'hostname', 'site_id', 'site_name', 'site_code',
    'rack', 'rack_unit', 'rack_id', 'rack_position', 'rack_mount_kind',
    'rack_height_u', 'rack_placement_status', 'rack_placement_source',
    'rack_dimension_status', 'rack_location_note', 'rack_model_key',
    'u_height', 'planned_start_u', 'management_ip', 'business_ip',
    'device_role', 'vlan', 'uplink_switch', 'uplink_port', 'status',
    'online_status', 'lifecycle_status', 'asset_origin', 'purchase_date',
    'warranty_expiry', 'department', 'notes', 'platform',
    'connection_method', 'username', 'normal_username', 'admin_username',
    'password', 'normal_password', 'admin_password', 'enable_password',
    'snmp_community',
    'snmp_port', 'management_port', 'device_category', 'function', 'zone',
    'power_watts', 'device_id', 'is_managed', 'takeover_error',
    'credential_id', 'admin_credential_id', 'snmp_credential_id',
    'password_set', 'normal_password_set', 'admin_password_set',
    'enable_password_set', 'snmp_community_set', 'created_at', 'updated_at',
})

# Connectivity verification is an outbound network capability.  Keep the
# safety limits process-local for the current deployment, while making the
# defaults conservative enough that a single worker cannot be used as an
# unbounded scanner.  A shared rate limiter can be added later without
# changing the endpoint contract.
_CONNECTIVITY_MAX_CONCURRENT = max(
    1, min(int(os.environ.get('ASSET_VERIFY_MAX_CONCURRENCY', '4')), 32)
)
_CONNECTIVITY_TIMEOUT_SECONDS = max(
    0.2, min(float(os.environ.get('ASSET_VERIFY_TIMEOUT_SECONDS', '1')), 5.0)
)
_CONNECTIVITY_SSH_TIMEOUT_SECONDS = max(
    1.0, min(float(os.environ.get('ASSET_VERIFY_SSH_TIMEOUT_SECONDS', '5')), 10.0)
)
_CONNECTIVITY_RATE_LIMIT = max(
    1, min(int(os.environ.get('ASSET_VERIFY_RATE_LIMIT', '10')), 60)
)
_CONNECTIVITY_RATE_WINDOW_SECONDS = max(
    10.0, min(float(os.environ.get('ASSET_VERIFY_RATE_WINDOW_SECONDS', '60')), 600.0)
)
_CONNECTIVITY_SEMAPHORE = threading.BoundedSemaphore(_CONNECTIVITY_MAX_CONCURRENT)
_CONNECTIVITY_RATE_LOCK = threading.Lock()
_CONNECTIVITY_RATE_BUCKETS: dict[str, deque[float]] = {}

_ALLOWED_PRIVATE_NETWORKS = (
    ipaddress.ip_network('10.0.0.0/8'),
    ipaddress.ip_network('172.16.0.0/12'),
    ipaddress.ip_network('192.168.0.0/16'),
    ipaddress.ip_network('fc00::/7'),
)
_CLOUD_METADATA_NETWORKS = (
    ipaddress.ip_network('169.254.169.254/32'),  # AWS/Azure/GCP/OCI
    ipaddress.ip_network('100.100.100.200/32'),  # Alibaba Cloud
)


def _connectivity_http_error(code: str, message: str, *, status_code: int = 422) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={'code': code, 'message': message},
    )


def _validate_connectivity_target(value: object) -> str:
    """Validate an asset management IP before any outbound network call.

    Only literal IP addresses are accepted.  RFC1918/ULA addresses remain
    valid because they are normal data-centre management targets; link-local,
    loopback, multicast, unspecified, documentation/reserved, shared/CGNAT
    and cloud-metadata ranges are rejected.
    """

    raw = str(value or '').strip()
    try:
        address = ipaddress.ip_address(raw)
    except ValueError as exc:
        raise _connectivity_http_error(
            'CONNECTIVITY_TARGET_INVALID',
            '资产管理地址必须是有效的 IP 地址。',
        ) from exc

    mapped = getattr(address, 'ipv4_mapped', None)
    metadata_address = mapped or address
    if any(metadata_address in network for network in _CLOUD_METADATA_NETWORKS):
        raise _connectivity_http_error(
            'CONNECTIVITY_TARGET_NOT_ALLOWED',
            '云元数据地址不允许进行连通性验证。',
        )
    if (
        address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_multicast
        or address.is_reserved
    ):
        raise _connectivity_http_error(
            'CONNECTIVITY_TARGET_NOT_ALLOWED',
            '环回、链路本地、组播、未指定或保留地址不允许进行连通性验证。',
        )

    if address.is_private:
        if not any(address in network for network in _ALLOWED_PRIVATE_NETWORKS):
            raise _connectivity_http_error(
                'CONNECTIVITY_TARGET_NOT_ALLOWED',
                '该私有或共享地址段不在允许的机房管理地址范围内。',
            )
    elif not address.is_global:
        raise _connectivity_http_error(
            'CONNECTIVITY_TARGET_NOT_ALLOWED',
            '该地址段不允许进行连通性验证。',
        )
    return str(address)


def _validate_connectivity_port(value: object) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise _connectivity_http_error(
            'CONNECTIVITY_PORT_INVALID',
            'SSH 管理端口必须是 1 到 65535 之间的整数。',
        ) from exc
    if not 1 <= port <= 65535:
        raise _connectivity_http_error(
            'CONNECTIVITY_PORT_INVALID',
            'SSH 管理端口必须是 1 到 65535 之间的整数。',
        )
    return port


def _acquire_connectivity_slot(asset_id: str) -> None:
    if not _CONNECTIVITY_SEMAPHORE.acquire(blocking=False):
        raise _connectivity_http_error(
            'CONNECTIVITY_BUSY',
            '当前连通性验证请求过多，请稍后重试。',
            status_code=429,
        )
    now = time.monotonic()
    try:
        with _CONNECTIVITY_RATE_LOCK:
            bucket = _CONNECTIVITY_RATE_BUCKETS.setdefault(str(asset_id), deque())
            cutoff = now - _CONNECTIVITY_RATE_WINDOW_SECONDS
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= _CONNECTIVITY_RATE_LIMIT:
                raise _connectivity_http_error(
                    'CONNECTIVITY_RATE_LIMITED',
                    '该资产的连通性验证次数已达到限制，请稍后重试。',
                    status_code=429,
                )
            bucket.append(now)
    except Exception:
        _CONNECTIVITY_SEMAPHORE.release()
        raise


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


def _tenant_id_from_authenticated_user(user: dict) -> str:
    """Return the non-empty tenant that owns a linked device row."""
    # Direct service-level callers do not pass through FastAPI dependency
    # resolution. Keep those legacy calls on the built-in tenant; HTTP routes
    # always receive a session dictionary from require_role below.
    if not isinstance(user, dict):
        return 'tenant-default'
    tenant_id = str(user.get('tenant_id') or '').strip()
    if not tenant_id:
        # A few legacy service-level callers invoke the endpoint function
        # directly, so FastAPI's Depends placeholder (or a role-only test
        # stub) has no session identity.  Preserve the built-in tenant for
        # that compatibility path; a real authenticated session always has a
        # user id and is rejected closed when tenant assignment is missing.
        if not str(user.get('user_id') or user.get('id') or '').strip():
            return 'tenant-default'
        raise HTTPException(
            status_code=403,
            detail='Authenticated user is not assigned to a tenant',
        )
    return tenant_id


def _management_port_for_storage(body) -> int:
    method = str(getattr(body, 'connection_method', '') or 'ssh').lower()
    if method in {'web', 'none'}:
        return 0
    value = getattr(body, 'management_port', None)
    return int(value or (830 if method == 'netconf' else 22))


def _get_asset_web_profiles(conn, asset_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT id, asset_id, profile_name, scheme, port, path, enabled,
                  credential_mode, normal_username, normal_password,
                  admin_username, admin_password, credential_id, admin_credential_id,
                  created_at, updated_at
           FROM asset_web_access_profiles WHERE asset_id = ?
           ORDER BY enabled DESC, profile_name, scheme, port""",
        (asset_id,),
    ).fetchall()
    return [_sanitize_web_profile(dict(row)) for row in rows]


def _sanitize_web_profile(item: dict) -> dict:
    item['enabled'] = bool(item.get('enabled'))
    for field in ('normal_password', 'admin_password'):
        item[f'{field}_set'] = bool(item.get(field))
        item[field] = ''
    return item


def _sanitize_asset_item(item: dict) -> dict:
    """Return the explicit public asset projection without secret columns.

    Asset list/detail endpoints historically selected ``physical_assets.*``
    for convenience.  Keep the compatibility query during the migration
    window, but allow only the stable UI/CMDB fields below to leave the API
    boundary.  Encrypted/secret values become presence flags.
    """

    source = dict(item)
    for sensitive in ('password', 'normal_password', 'admin_password', 'enable_password'):
        if sensitive in source:
            source[f'{sensitive}_set'] = bool(source.get(sensitive))
    if 'snmp_community' in source:
        source['snmp_community_set'] = bool(source.get('snmp_community'))

    # A Vault path and credential-governance internals are deliberately not
    # represented in this allowlist, even when they are present in a joined
    # row.  Do not echo empty placeholders that clients might persist.
    projected = {
        key: source[key]
        for key in _PUBLIC_ASSET_FIELDS
        if key in source
    }
    for key in ('password', 'normal_password', 'admin_password', 'enable_password', 'snmp_community'):
        if key in projected:
            projected[key] = ''

    item.clear()
    item.update(projected)
    return item


def _asset_placement_map(
    conn,
    asset_ids: list[str],
    user: object = None,
) -> dict[str, dict]:
    """Return canonical placement DTOs keyed by physical asset ID.

    ``physical_assets`` keeps a denormalized compatibility projection for the
    existing inventory UI. RackVision consumers must be able to distinguish
    that projection from the authoritative ``rack_devices`` row, so asset
    list/detail responses expose a nested ``placement`` object built from the
    canonical row. The query is batched to avoid one placement lookup per
    asset and applies both asset and rack visibility scopes before returning
    rack identity fields.
    """

    normalized_ids = sorted({str(asset_id).strip() for asset_id in asset_ids if str(asset_id).strip()})
    if not normalized_ids:
        return {}

    asset_placeholders = ','.join('?' for _ in normalized_ids)
    clauses = [f'rd.asset_id IN ({asset_placeholders})']
    params: list[str] = list(normalized_ids)

    if isinstance(user, dict):
        asset_scope = rack_scope_service.allowed_resource_scope(conn, user, 'asset', 'view')
        if asset_scope.site_ids is not None:
            if not asset_scope.site_ids:
                return {}
            site_placeholders = ','.join('?' for _ in asset_scope.site_ids)
            clauses.append(f'pa.site_id IN ({site_placeholders})')
            params.extend(asset_scope.site_ids)
            if asset_scope.tenant_id:
                clauses.append(
                    '''EXISTS (
                           SELECT 1 FROM sites placement_asset_scope_site
                            WHERE placement_asset_scope_site.id = pa.site_id
                              AND placement_asset_scope_site.tenant_id = ?
                       )'''
                )
                params.append(asset_scope.tenant_id)
        elif asset_scope.tenant_id:
            clauses.append(
                '''EXISTS (
                       SELECT 1 FROM sites placement_asset_scope_site
                        WHERE placement_asset_scope_site.id = pa.site_id
                          AND placement_asset_scope_site.tenant_id = ?
                   )'''
            )
            params.append(asset_scope.tenant_id)

        rack_scope = rack_scope_service.allowed_rack_scope(conn, user, 'view')
        if rack_scope.site_ids is not None:
            if not rack_scope.site_ids:
                return {}
            site_placeholders = ','.join('?' for _ in rack_scope.site_ids)
            clauses.append(f'r.site_id IN ({site_placeholders})')
            params.extend(rack_scope.site_ids)
            if rack_scope.tenant_id:
                clauses.append(
                    '''EXISTS (
                           SELECT 1 FROM sites placement_rack_scope_site
                            WHERE placement_rack_scope_site.id = r.site_id
                              AND placement_rack_scope_site.tenant_id = ?
                       )'''
                )
                params.append(rack_scope.tenant_id)
        elif rack_scope.tenant_id:
            clauses.append(
                '''EXISTS (
                       SELECT 1 FROM sites placement_rack_scope_site
                        WHERE placement_rack_scope_site.id = r.site_id
                          AND placement_rack_scope_site.tenant_id = ?
                   )'''
            )
            params.append(rack_scope.tenant_id)

    rows = conn.execute(
        f'''SELECT rd.id AS placement_id, rd.asset_id, rd.rack_id,
                   r.rack_code, r.rack_name, r.name AS rack_display_name,
                   r.site_id AS rack_site_id,
                   rs.site_code AS rack_site_code,
                   rs.site_name AS rack_site_name,
                   rd.device_type_id, rd.start_u, rd.position, rd.mount_kind,
                   rd.height_u, rd.placement_status, rd.placement_source,
                   rd.dimension_status, rd.location_note, rd.model_key,
                   rd.status, rd.serial_number, rd.updated_at
              FROM rack_devices rd
              JOIN physical_assets pa ON pa.id = rd.asset_id
              JOIN racks r ON r.id = rd.rack_id
              LEFT JOIN sites rs ON rs.id = r.site_id
             WHERE {' AND '.join(clauses)}
             ORDER BY rd.asset_id, rd.updated_at DESC, rd.id''',
        params,
    ).fetchall()

    placements: dict[str, dict] = {}
    for row in rows:
        source = dict(row)
        asset_id = str(source.get('asset_id') or '').strip()
        if not asset_id or asset_id in placements:
            # The canonical uniqueness index prevents this in clean data. A
            # legacy duplicate must not make the API return nondeterministic
            # placement data, so keep the newest row selected by the query.
            continue
        start_u = source.get('start_u')
        height_u = source.get('height_u')
        try:
            end_u = int(start_u) + int(height_u) - 1 if start_u is not None and height_u is not None else None
        except (TypeError, ValueError):
            end_u = None
        placements[asset_id] = {
            'id': source.get('placement_id'),
            'asset_id': asset_id,
            'rack_id': source.get('rack_id'),
            'rack_code': source.get('rack_code') or '',
            'rack_name': source.get('rack_display_name') or source.get('rack_name') or '',
            'rack_site_id': source.get('rack_site_id') or '',
            'rack_site_code': source.get('rack_site_code') or '',
            'rack_site_name': source.get('rack_site_name') or '',
            'device_type_id': source.get('device_type_id'),
            'start_u': start_u,
            'end_u': end_u,
            'height_u': height_u,
            'position': source.get('position') or 'unknown',
            'mount_kind': source.get('mount_kind') or 'unknown',
            'placement_status': source.get('placement_status') or 'unknown',
            'placement_source': source.get('placement_source') or 'legacy_rack_device',
            'dimension_status': source.get('dimension_status') or 'unknown',
            'location_note': source.get('location_note') or '',
            'model_key': source.get('model_key') or '',
            'status': source.get('status') or 'active',
            'serial_number': source.get('serial_number') or '',
        }
    return placements


_ASSET_AUDIT_FIELDS = frozenset({
    'id', 'asset_type', 'asset_tag', 'serial_number', 'vendor', 'model',
    'hostname', 'site_id', 'rack_id', 'rack_position', 'rack_mount_kind',
    'rack_height_u', 'rack_placement_status', 'rack_placement_source',
    'rack_dimension_status', 'rack_location_note', 'rack_model_key',
    'u_height', 'planned_start_u', 'management_ip', 'business_ip',
    'device_role', 'status', 'lifecycle_status', 'asset_origin',
    'platform', 'connection_method', 'device_id', 'is_managed',
    'credential_id', 'admin_credential_id', 'snmp_credential_id',
})


def _asset_audit_projection(value: object) -> dict:
    """Project an asset row for audit without persisting credential material."""

    if value is None:
        return {}
    source = dict(value) if hasattr(value, 'keys') else dict(value or {})
    return {
        key: source.get(key)
        for key in _ASSET_AUDIT_FIELDS
        if key in source
    }


def _audit_asset_event(
    conn,
    *,
    event_type: str,
    summary: str,
    user: object,
    asset_id: str | None = None,
    target_name: str | None = None,
    status: str = 'success',
    before: object = None,
    after: object = None,
    details: dict | None = None,
) -> None:
    """Write a redacted asset audit event in the caller's transaction."""

    actor = user if isinstance(user, dict) else {}
    request_id = request_id_var.get('-')
    log_audit_event(
        event_type=event_type,
        category='asset',
        severity='info' if status == 'success' else 'warning',
        status=status,
        summary=summary,
        actor_id=actor.get('user_id') or actor.get('id'),
        actor_username=actor.get('username'),
        actor_role=actor.get('role'),
        target_type='physical_asset',
        target_id=asset_id,
        target_name=target_name,
        request_id='' if request_id == '-' else request_id,
        before=_asset_audit_projection(before),
        after=_asset_audit_projection(after),
        details=details or {},
        conn=conn,
    )


def _asset_scope_clauses(
    conn,
    user,
    *,
    action: str = 'view',
    alias: str = 'pa',
) -> tuple[list[str], list[str]]:
    """Build one SQL visibility filter for physical assets.

    ``physical_assets`` is site-owned in the current schema, so tenant scope
    is resolved through ``sites.tenant_id``.  A site-scoped grant is always
    additionally constrained to the session tenant when the session has one;
    this prevents a malformed cross-tenant scope row from widening access.
    Direct service-level tests intentionally omit the FastAPI dependency and
    therefore keep the legacy unfiltered behavior when ``user`` is not a
    resolved session dictionary.
    """

    if not isinstance(user, dict):
        return [], []

    scope = rack_scope_service.allowed_resource_scope(conn, user, 'asset', action)
    clauses: list[str] = []
    params: list[str] = []
    if scope.site_ids is not None:
        if not scope.site_ids:
            return ['1 = 0'], []
        placeholders = ','.join('?' for _ in scope.site_ids)
        clauses.append(f'{alias}.site_id IN ({placeholders})')
        params.extend(scope.site_ids)
        if scope.tenant_id:
            clauses.append(
                f'''EXISTS (
                       SELECT 1 FROM sites asset_scope_site
                        WHERE asset_scope_site.id = {alias}.site_id
                          AND asset_scope_site.tenant_id = ?
                   )'''
            )
            params.append(scope.tenant_id)
    elif scope.tenant_id:
        clauses.append(
            f'''EXISTS (
                   SELECT 1 FROM sites asset_scope_site
                    WHERE asset_scope_site.id = {alias}.site_id
                      AND asset_scope_site.tenant_id = ?
               )'''
        )
        params.append(scope.tenant_id)
    return clauses, params


def _enforce_asset_row_scope(user, row, action: str = 'view') -> None:
    if isinstance(user, dict):
        rack_scope_service.enforce_loaded_resource(user, dict(row), 'asset', action)


def _enforce_asset_site_scope(conn, user, site_id: str, action: str = 'create') -> None:
    """Check the target site's tenant/site grant before an asset write."""

    if not isinstance(user, dict):
        return
    requested = str(site_id or '').strip()
    if requested:
        rack_scope_service.enforce_site(
            conn,
            user,
            requested,
            action,
            resource_type='asset',
        )
        return

    # An asset without a site cannot be assigned to a tenant-scoped user.
    # Keep legacy unscoped service calls and tenant-less operators compatible,
    # while preventing a real session from creating an orphaned cross-scope
    # record that it could not subsequently read or manage.
    enforce_resource_scope(user, 'asset', action)
    if user.get('role') != 'Administrator' and str(user.get('tenant_id') or '').strip():
        raise HTTPException(
            status_code=422,
            detail={
                'code': 'ASSET_SITE_REQUIRED',
                'message': '租户范围内的资产必须绑定有效站点后才能保存。',
            },
        )


# ── helpers: devices ↔ physical_assets sync ──────────────────────────

def _platform_from_vendor(vendor: str, asset_type: str = 'network_device') -> str:
    """Map an asset vendor to the canonical persisted platform identity.

    H3C is persisted as the single public ``h3c_comware`` platform.  The
    concrete Comware release is selected by ``platform_profile_id``.
    """
    v = (vendor or '').lower()
    if 'cisco' in v:
        return 'cisco_iosxe'
    if 'huawei' in v:
        return 'huawei_vrp'
    if 'h3c' in v or 'comware' in v:
        return 'h3c_comware'
    if 'arista' in v:
        return 'arista_eos'
    if 'juniper' in v:
        return 'juniper_junos'
    if 'ruijie' in v or 'rgos' in v or '锐捷' in v:
        return 'ruijie_rgos'
    if 'zte' in v or 'zhongxing' in v or '中兴' in v:
        return 'zte_zxros'
    if 'raisecom' in v or '瑞斯康达' in v:
        return 'raisecom_ros'
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
    ('h3c', {'h3c_comware'}, 'h3c_comware'),
    ('comware', {'h3c_comware'}, 'h3c_comware'),
    ('arista', {'arista', 'arista_eos', 'eos'}, 'arista_eos'),
    ('juniper', {'juniper', 'juniper_junos', 'junos'}, 'juniper_junos'),
    ('ruijie', {'ruijie', 'ruijie_os', 'ruijie_rgos', 'rgos'}, 'ruijie_rgos'),
    ('zte', {'zte', 'zte_zxros', 'zxros'}, 'zte_zxros'),
    ('raisecom', {'raisecom', 'raisecom_ros', 'raisecom_ros5', 'raisecom_ros_5'}, 'raisecom_ros'),
    ('瑞斯康达', {'raisecom', 'raisecom_ros', 'raisecom_ros5', 'raisecom_ros_5'}, 'raisecom_ros'),
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
    normalized = {'h3c': 'h3c_comware', 'comware': 'h3c_comware'}.get(normalized, normalized)
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


def _create_linked_device(conn, asset_id: str, body, user: dict) -> str:
    """Create a devices row linked to a physical_assets row."""
    device_id = str(uuid.uuid4())
    tenant_id = _tenant_id_from_authenticated_user(user)
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
    mgmt_port = _management_port_for_storage(body)

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
            id, tenant_id, asset_id, hostname, ip_address, platform, status, compliance,
            username, password, sn, model, version, role, site, uptime,
            connection_method, vendor, snmp_community, snmp_port,
            normal_username, normal_password, admin_username, admin_password,
            enable_password, auth_model, device_category, function, zone, power_watts,
            onboarding_status, credential_id, admin_credential_id, management_port
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
    ''', (
        device_id, tenant_id, asset_id,
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
        getattr(body, 'function', '') or '',
        getattr(body, 'zone', 'Unknown') or 'Unknown',
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
    # Asset create/import owns the surrounding transaction.  Do not let the
    # automatic status tag seed or commit release a row SAVEPOINT used by
    # detailed batch import.
    tag_service.sync_device_status_tag(conn, device_id, 'pending', commit=False)
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
        tag_service.set_device_tags(
            conn,
            str(device_row['id']),
            tag_ids,
            created_by='asset-management',
            commit=False,
        )
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
        'function': getattr(body, 'function', None),
        'zone': getattr(body, 'zone', None),
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



def _sync_rack_device_from_asset(conn, asset_id: str, obj, user: dict | None = None) -> None:
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
    rack_id = get_val('rack_id')
    rack_position = get_val('rack_position')
    rack_mount_kind = get_val('rack_mount_kind')
    rack_height_u = get_val('rack_height_u')
    rack_placement_status = get_val('rack_placement_status')
    rack_dimension_status = get_val('rack_dimension_status')
    rack_location_note = get_val('rack_location_note', '')
    rack_model_key = get_val('rack_model_key', '')
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

    existing = conn.execute("SELECT id FROM rack_devices WHERE asset_id = ? LIMIT 1", (asset_id,)).fetchone()

    from services import rack_service
    rack_reference = rack_id or rack
    resolved_rack = rack_service.resolve_rack_reference(conn, rack_reference)
    rack_row = (
        {'id': resolved_rack['id'], 'total_u': resolved_rack['total_u']}
        if resolved_rack
        else None
    )

    if not rack_row:
        if existing:
            if isinstance(user, dict):
                old_rack_row = conn.execute(
                    """SELECT r.*, s.tenant_id AS site_tenant_id
                         FROM racks r LEFT JOIN sites s ON s.id = r.site_id
                        WHERE r.id = (SELECT rack_id FROM rack_devices WHERE id = ?)""",
                    (existing['id'],),
                ).fetchone()
                if old_rack_row:
                    rack_scope_service.enforce_loaded_rack(user, dict(old_rack_row), "update")
            rack_service.delete_rack_device(conn, existing['id'], commit=False)
        if rack or rack_id:
            raise ValueError(f"Rack '{rack_id or rack}' does not exist")
        return

    if isinstance(user, dict):
        scope_row = conn.execute(
            """SELECT r.*, s.tenant_id AS site_tenant_id
                 FROM racks r LEFT JOIN sites s ON s.id = r.site_id
                WHERE r.id = ?""",
            (rack_row['id'],),
        ).fetchone()
        if scope_row:
            rack_scope_service.enforce_loaded_rack(user, dict(scope_row), "update")

    # Resolve the device type before deciding whether a missing start_u means
    # "uninstalled" (legacy asset form) or an explicit non-U placement.
    _sync_device_type_power(conn, vendor, model, power_watts, device_role, u_height)
    dt_row = conn.execute(
        "SELECT id, default_mount_kind, dimension_status FROM device_types WHERE model = ? AND vendor = ?",
        (model, vendor),
    ).fetchone()
    if not dt_row:
        raise ValueError(f"Failed to resolve device type for vendor '{vendor}' model '{model}'")
    device_type_id = dt_row['id']

    explicit_mount_kind = rack_mount_kind not in (None, '')
    mount_kind = str(rack_mount_kind or dt_row['default_mount_kind'] or 'u_mount').strip().lower()
    if planned_start_u is None and not explicit_mount_kind and not rack_position and not rack_location_note:
        if existing:
            from services import rack_service
            rack_service.delete_rack_device(conn, existing['id'], commit=False)
        return

    if rack_height_u in (None, '', 'null'):
        rack_height_u = u_height if mount_kind == 'u_mount' else None
    else:
        try:
            rack_height_u = int(rack_height_u)
        except (ValueError, TypeError):
            rack_height_u = None
    position = rack_position or ('front' if mount_kind == 'u_mount' else 'unknown')
    placement_source = get_val('rack_placement_source') or get_val('placement_source') or (
        'legacy_asset' if str(get_val('asset_origin', '')).lower() == 'legacy' else 'asset_import'
    )
    placement_status = rack_placement_status or ('estimated' if mount_kind == 'u_mount' else 'unknown')
    dimension_status = rack_dimension_status or dt_row['dimension_status'] or 'unknown'

    if existing:
        rack_service.update_rack_device(
            conn,
            existing['id'],
            name=hostname,
            rack_id=rack_row['id'],
            device_type_id=device_type_id,
            start_u=planned_start_u,
            position=position,
            mount_kind=mount_kind,
            height_u=rack_height_u,
            placement_status=placement_status,
            placement_source=placement_source,
            dimension_status=dimension_status,
            location_note=rack_location_note,
            model_key=rack_model_key,
            serial_number=serial_number,
            asset_id=asset_id,
            commit=False,
        )
    else:
        rack_service.create_rack_device(
            conn,
            name=hostname,
            rack_id=rack_row['id'],
            device_type_id=device_type_id,
            start_u=planned_start_u,
            position=position,
            mount_kind=mount_kind,
            height_u=rack_height_u,
            placement_status=placement_status,
            placement_source=placement_source,
            dimension_status=dimension_status,
            location_note=rack_location_note,
            model_key=rack_model_key,
            serial_number=serial_number,
            asset_id=asset_id,
            commit=False,
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

    # WAN links are device-owned records without a database FK on older
    # installations.  Clean them in the same asset-delete transaction before
    # removing the linked device row.
    from services.wan_link_service import delete_wan_links_for_device
    delete_wan_links_for_device(conn, device_id)

    conn.execute('DELETE FROM devices WHERE id = ?', (device_id,))
    # Credentials are managed resources, not children of an asset. Deleting
    # an asset only removes the device binding; credential cleanup is an
    # explicit action from the credential center after all device references
    # have been cleared.


# ── Pydantic Models ──────────────────────────────────────────────────

def _validate_asset_ip_address(raw_value: object, field_name: str = '管理IP') -> str:
    raw = str(raw_value or '').strip()
    if not raw:
        return ''
    import ipaddress
    try:
        ipaddress.ip_address(raw)
        return raw
    except ValueError:
        raise ValueError(f"{field_name} '{raw}' 不是有效的 IPv4 或 IPv6 地址")


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
    # Canonical rack placement inputs. Legacy rack/rack_unit/planned_start_u
    # remain accepted during the migration window; rack_devices is the write
    # model and these fields are projected back to physical_assets.
    rack_id: Optional[str] = None
    rack_position: Optional[str] = None
    rack_mount_kind: Optional[str] = None
    rack_height_u: Optional[int] = None
    rack_placement_status: Optional[str] = None
    rack_placement_source: Optional[str] = None
    rack_dimension_status: Optional[str] = None
    rack_location_note: str = ''
    rack_model_key: str = ''
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
    function: str = ''
    zone: str = 'Unknown'
    power_watts: int = 0
    credential_id: Optional[str] = ''
    admin_credential_id: Optional[str] = ''
    snmp_credential_id: Optional[str] = ''
    tag_ids: list[str] = []
    tag_codes: str = ''
    web_profiles: list[WebAccessProfileInput] = Field(default_factory=list)

    @field_validator('management_ip', 'business_ip', mode='before')
    @classmethod
    def validate_ips(cls, v, info):
        label = '管理IP' if info.field_name == 'management_ip' else '业务IP'
        return _validate_asset_ip_address(v, label)

    @field_validator('connection_method', mode='before')
    @classmethod
    def validate_connection_method(cls, v):
        method = str(v or 'ssh').strip().lower()
        if method not in {'ssh', 'netconf', 'web', 'none'}:
            raise ValueError('Connection method must be ssh, netconf, web or none')
        return method

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
            return max(0, min(65535, int(v)))
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
    rack_id: Optional[str] = None
    rack_position: Optional[str] = None
    rack_mount_kind: Optional[str] = None
    rack_height_u: Optional[int] = None
    rack_placement_status: Optional[str] = None
    rack_placement_source: Optional[str] = None
    rack_dimension_status: Optional[str] = None
    rack_location_note: Optional[str] = None
    rack_model_key: Optional[str] = None
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
    function: Optional[str] = None
    zone: Optional[str] = None
    power_watts: Optional[int] = None
    production_mode: Optional[str] = None
    takeover_exempt_reason: Optional[str] = None
    credential_id: Optional[str] = None
    admin_credential_id: Optional[str] = None
    snmp_credential_id: Optional[str] = None
    tag_ids: Optional[list[str]] = None
    tag_codes: Optional[str] = None
    web_profiles: Optional[list[WebAccessProfileInput]] = None

    @field_validator('management_ip', 'business_ip', mode='before')
    @classmethod
    def validate_ips_update(cls, v, info):
        if v is None:
            return None
        label = '管理IP' if info.field_name == 'management_ip' else '业务IP'
        return _validate_asset_ip_address(v, label)

    @field_validator('connection_method', mode='before')
    @classmethod
    def validate_connection_method(cls, v):
        if v is None:
            return None
        method = str(v).strip().lower()
        if method not in {'ssh', 'netconf', 'web', 'none'}:
            raise ValueError('Connection method must be ssh, netconf, web or none')
        return method

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
def asset_summary(_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        scope_clauses, scope_params = _asset_scope_clauses(conn, _user)
        scope_where = (' WHERE ' + ' AND '.join(scope_clauses)) if scope_clauses else ''
        total = conn.execute(
            f'SELECT COUNT(*) FROM physical_assets pa{scope_where}',
            scope_params,
        ).fetchone()[0]
        servers = conn.execute(
            f"SELECT COUNT(*) FROM physical_assets pa{scope_where}"
            " AND pa.asset_type = 'server'" if scope_where else
            "SELECT COUNT(*) FROM physical_assets pa WHERE pa.asset_type = 'server'",
            scope_params,
        ).fetchone()[0]
        network = conn.execute(
            f"SELECT COUNT(*) FROM physical_assets pa{scope_where}"
            " AND pa.asset_type = 'network_device'" if scope_where else
            "SELECT COUNT(*) FROM physical_assets pa WHERE pa.asset_type = 'network_device'",
            scope_params,
        ).fetchone()[0]

        # Warranty expiring within 90 days
        now_str = _utc_now()[:10]
        future_str = (datetime.now(timezone.utc) + timedelta(days=90)).strftime('%Y-%m-%d')
        warranty_soon = conn.execute(
            f"SELECT COUNT(*) FROM physical_assets pa{scope_where}"
            " AND pa.warranty_expiry != '' AND pa.warranty_expiry <= ? AND pa.warranty_expiry >= ?"
            if scope_where else
            "SELECT COUNT(*) FROM physical_assets pa WHERE pa.warranty_expiry != '' AND pa.warranty_expiry <= ? AND pa.warranty_expiry >= ?",
            [*scope_params, future_str, now_str],
        ).fetchone()[0]

        # By status
        by_status = {}
        for row in conn.execute(
            f'SELECT pa.status, COUNT(*) as cnt FROM physical_assets pa{scope_where} GROUP BY pa.status',
            scope_params,
        ):
            by_status[row['status']] = row['cnt']

        # By vendor (top 10)
        by_vendor = {}
        for row in conn.execute(
            f"SELECT pa.vendor, COUNT(*) as cnt FROM physical_assets pa{scope_where}"
            " AND pa.vendor != '' GROUP BY pa.vendor ORDER BY cnt DESC LIMIT 10"
            if scope_where else
            "SELECT pa.vendor, COUNT(*) as cnt FROM physical_assets pa WHERE pa.vendor != '' GROUP BY pa.vendor ORDER BY cnt DESC LIMIT 10",
            scope_params,
        ):
            by_vendor[row['vendor']] = row['cnt']

        # By CMDB site
        by_site = {}
        for row in conn.execute(
            f"""SELECT COALESCE(NULLIF(s.site_name, ''), NULLIF(s.site_code, ''), 'unassigned') AS site_name,
                      COUNT(*) AS cnt
               FROM physical_assets pa
               LEFT JOIN sites s ON s.id = pa.site_id
               {('WHERE ' + ' AND '.join(scope_clauses)) if scope_clauses else ''}
               GROUP BY s.site_name, s.site_code
               ORDER BY cnt DESC""",
            scope_params,
        ):
            by_site[row['site_name']] = row['cnt']

        # By department
        by_department = {}
        for row in conn.execute(
            f"SELECT pa.department, COUNT(*) as cnt FROM physical_assets pa{scope_where}"
            " AND pa.department != '' GROUP BY pa.department ORDER BY cnt DESC"
            if scope_where else
            "SELECT pa.department, COUNT(*) as cnt FROM physical_assets pa WHERE pa.department != '' GROUP BY pa.department ORDER BY cnt DESC",
            scope_params,
        ):
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
    _user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        conditions = []
        params = []
        scope_clauses, scope_params = _asset_scope_clauses(conn, _user)
        conditions.extend(scope_clauses)
        params.extend(scope_params)

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
                s.tenant_id AS site_tenant_id,
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
            _sanitize_asset_item(item)
            items.append(item)

        placement_map = _asset_placement_map(
            conn,
            [str(item.get('id') or '') for item in items],
            _user,
        )
        for item in items:
            item['placement'] = placement_map.get(str(item.get('id') or ''))

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

        asset_ids = [str(item.get('id') or '') for item in items if item.get('id')]
        web_profile_map: dict[str, list[dict]] = {}
        if asset_ids:
            placeholders = ','.join('?' for _ in asset_ids)
            web_rows = conn.execute(
                f'''SELECT id, asset_id, profile_name, scheme, port, path, enabled,
                           credential_mode, normal_username, normal_password,
                           admin_username, admin_password, credential_id, admin_credential_id,
                           created_at, updated_at
                    FROM asset_web_access_profiles
                    WHERE asset_id IN ({placeholders})
                    ORDER BY profile_name, scheme, port''',
                asset_ids,
            ).fetchall()
            for web_row in web_rows:
                profile = _sanitize_web_profile(dict(web_row))
                web_profile_map.setdefault(str(profile['asset_id']), []).append(profile)
        for item in items:
            item['web_profiles'] = web_profile_map.get(str(item.get('id') or ''), [])

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
def asset_tree(_user=require_role("Viewer")):
    """Return a compact, server-side asset classification tree source."""
    conn = get_db_connection()
    try:
        scope_clauses, scope_params = _asset_scope_clauses(conn, _user)
        rows = conn.execute(
            f'''SELECT
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
               {('WHERE ' + ' AND '.join(scope_clauses)) if scope_clauses else ''}
               GROUP BY pa.site_id, s.site_name, s.site_code, pa.asset_type,
                        pa.device_category, pa.device_role, pa.status, d.status
               ORDER BY site_name, pa.asset_type, pa.device_category, pa.device_role, online_status''',
            scope_params,
        ).fetchall()
        return {'items': [dict(row) for row in rows]}
    finally:
        conn.close()


@router.get('/assets/{asset_id}')
def get_asset(asset_id: str, _user=require_role("Viewer")):
    """Single asset row (same fields as list items) for rack drawer / cross-module detail."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            '''SELECT pa.*, s.tenant_id AS site_tenant_id,
               COALESCE(NULLIF(pa.normal_username,''), d.normal_username, '') AS normal_username,
               COALESCE(NULLIF(pa.admin_username,''),  d.admin_username,  '') AS admin_username,
               COALESCE(NULLIF(pa.username,''),        d.username,        '') AS username
            FROM physical_assets pa
            LEFT JOIN devices d ON d.asset_id = pa.id
            LEFT JOIN sites s ON s.id = pa.site_id
            WHERE pa.id = ?''',
            (asset_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Asset not found')
        _enforce_asset_row_scope(_user, row, 'view')
        item = dict(row)
        _sanitize_asset_item(item)
        item['placement'] = _asset_placement_map(conn, [asset_id], _user).get(asset_id)
        item['web_profiles'] = _get_asset_web_profiles(conn, asset_id)
        return item
    finally:
        conn.close()


@router.get('/assets/{asset_id}/web-profiles')
def list_asset_web_profiles(asset_id: str, _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        asset = conn.execute(
            '''SELECT pa.id, pa.site_id, s.tenant_id AS site_tenant_id
               FROM physical_assets pa LEFT JOIN sites s ON s.id = pa.site_id
              WHERE pa.id = ?''',
            (asset_id,),
        ).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail='Asset not found')
        _enforce_asset_row_scope(_user, asset, 'view')
        return {'items': _get_asset_web_profiles(conn, asset_id)}
    finally:
        conn.close()


@router.post('/assets/{asset_id}/web-profiles')
def create_asset_web_profile(asset_id: str, body: WebAccessProfileInput, _user=require_role("Operator")):
    conn = get_db_connection()
    try:
        asset = conn.execute(
            '''SELECT pa.id, pa.site_id, s.tenant_id AS site_tenant_id
               FROM physical_assets pa LEFT JOIN sites s ON s.id = pa.site_id
              WHERE pa.id = ?''',
            (asset_id,),
        ).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail='Asset not found')
        _enforce_asset_row_scope(_user, asset, 'update')
        existing = _get_asset_web_profiles(conn, asset_id)
        body.id = None
        try:
            profiles = replace_asset_web_profiles(conn, asset_id, [*existing, body])
        except ValueError as exc:
            conn.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        conn.commit()
        return _sanitize_web_profile(profiles[-1])
    finally:
        conn.close()


@router.put('/assets/{asset_id}/web-profiles/{profile_id}')
def update_asset_web_profile(asset_id: str, profile_id: str, body: WebAccessProfileInput, _user=require_role("Operator")):
    conn = get_db_connection()
    try:
        asset = conn.execute(
            '''SELECT pa.id, pa.site_id, s.tenant_id AS site_tenant_id
               FROM physical_assets pa LEFT JOIN sites s ON s.id = pa.site_id
              WHERE pa.id = ?''',
            (asset_id,),
        ).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail='Asset not found')
        _enforce_asset_row_scope(_user, asset, 'update')
        existing = _get_asset_web_profiles(conn, asset_id)
        if not any(str(item['id']) == profile_id for item in existing):
            raise HTTPException(status_code=404, detail='Web profile not found')
        body.id = profile_id
        replacement = [body if str(item['id']) == profile_id else item for item in existing]
        try:
            profiles = replace_asset_web_profiles(conn, asset_id, replacement)
        except ValueError as exc:
            conn.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        conn.commit()
        return _sanitize_web_profile(next(item for item in profiles if item['id'] == profile_id))
    finally:
        conn.close()


@router.delete('/assets/{asset_id}/web-profiles/{profile_id}')
def delete_asset_web_profile(asset_id: str, profile_id: str, _user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        asset = conn.execute(
            '''SELECT pa.id, pa.site_id, s.tenant_id AS site_tenant_id
               FROM physical_assets pa LEFT JOIN sites s ON s.id = pa.site_id
              WHERE pa.id = ?''',
            (asset_id,),
        ).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail='Asset not found')
        _enforce_asset_row_scope(_user, asset, 'update')
        row = conn.execute(
            'SELECT id FROM asset_web_access_profiles WHERE id = ? AND asset_id = ?',
            (profile_id, asset_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Web profile not found')
        conn.execute(
            'DELETE FROM asset_web_access_profiles WHERE id = ? AND asset_id = ?',
            (profile_id, asset_id),
        )
        conn.commit()
        return {'ok': True}
    finally:
        conn.close()


# ── Create ───────────────────────────────────────────────────────────

@router.post('/assets')
def create_asset(body: AssetCreate, _user=require_role("Operator")):
    conn = get_db_connection()
    try:
        _pre_resolve_credential(conn, body)
        requested_tag_ids = _resolve_asset_tag_ids(conn, body)
        try:
            body.site_id = resolve_canonical_site_id(conn, body.site_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        _enforce_asset_site_scope(conn, _user, body.site_id, 'create')
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
                snmp_community, snmp_port, device_category, function, zone, power_watts,
                credential_id, admin_credential_id,
                created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
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
            _safe_encrypt(body.snmp_community), body.snmp_port, body.device_category,
            getattr(body, 'function', '') or '', getattr(body, 'zone', 'Unknown') or 'Unknown', body.power_watts,
            body.credential_id or '',
            body.admin_credential_id or '',
            now, now
        ))
        conn.execute(
            'UPDATE physical_assets SET snmp_credential_id = ?, management_port = ? WHERE id = ?',
            (body.snmp_credential_id or '', _management_port_for_storage(body), asset_id),
        )

        # Plan-A: auto-create linked device for managed assets
        device_id = None
        if body.asset_type in ('network_device', 'server'):
            device_id = _create_linked_device(conn, asset_id, body, _user)
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
            _sync_rack_device_from_asset(conn, asset_id, body, _user)
        except ValueError as e:
            conn.rollback()
            raise HTTPException(status_code=400, detail=str(e))

        _sync_device_type_power(conn, body.vendor, body.model, body.power_watts, body.device_role, body.u_height)

        try:
            replace_asset_web_profiles(conn, asset_id, body.web_profiles)
        except ValueError as exc:
            conn.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        created_row = conn.execute(
            'SELECT * FROM physical_assets WHERE id = ?', (asset_id,)
        ).fetchone()
        _audit_asset_event(
            conn,
            event_type='asset.create',
            summary='Physical asset created',
            user=_user,
            asset_id=asset_id,
            target_name=body.hostname or body.asset_tag,
            after=created_row,
            details={'asset_type': body.asset_type, 'source': 'api'},
        )
        conn.commit()
        return {'id': asset_id, 'device_id': device_id, 'legacy_exempt': legacy_production}
    finally:
        conn.close()


# ── Update ───────────────────────────────────────────────────────────

@router.put('/assets/{asset_id}')
def update_asset(asset_id: str, body: AssetUpdate, run_bg_rotate: bool = True, _user=require_role("Operator")):
    conn = get_db_connection()
    try:
        row = conn.execute(
            '''SELECT pa.*, s.tenant_id AS site_tenant_id
               FROM physical_assets pa LEFT JOIN sites s ON s.id = pa.site_id
              WHERE pa.id = ?''',
            (asset_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Asset not found')
        _enforce_asset_row_scope(_user, row, 'update')

        requested_tag_ids = _resolve_asset_tag_ids(conn, body)

        if body.site_id is not None:
            try:
                body.site_id = resolve_canonical_site_id(conn, body.site_id)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            _enforce_asset_site_scope(conn, _user, body.site_id, 'update')

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
            'snmp_community', 'snmp_port', 'management_port', 'device_category', 'function', 'zone', 'power_watts', 'credential_id', 'admin_credential_id', 'snmp_credential_id'
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
                    merged_row = {**dict(updated_row), **body.model_dump(exclude_unset=True)}
                    _sync_rack_device_from_asset(conn, asset_id, merged_row, _user)
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
            if body.web_profiles is not None:
                try:
                    replace_asset_web_profiles(conn, asset_id, body.web_profiles)
                except ValueError as exc:
                    conn.rollback()
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
            _sync_asset_tags(conn, asset_id, requested_tag_ids)
            updated_row = conn.execute(
                'SELECT * FROM physical_assets WHERE id = ?', (asset_id,)
            ).fetchone()
            _audit_asset_event(
                conn,
                event_type='asset.update',
                summary='Physical asset updated',
                user=_user,
                asset_id=asset_id,
                target_name=updated_row['hostname'] if updated_row else asset_id,
                before=row,
                after=updated_row,
                details={'source': 'api', 'legacy_exempt': True},
            )
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
                merged_row = {**dict(updated_row), **body.model_dump(exclude_unset=True)}
                _sync_rack_device_from_asset(conn, asset_id, merged_row, _user)
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

        if body.web_profiles is not None:
            try:
                replace_asset_web_profiles(conn, asset_id, body.web_profiles)
            except ValueError as exc:
                conn.rollback()
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            conn.commit()

        updated_row = conn.execute(
            'SELECT * FROM physical_assets WHERE id = ?', (asset_id,)
        ).fetchone()
        _audit_asset_event(
            conn,
            event_type='asset.update',
            summary='Physical asset updated',
            user=_user,
            asset_id=asset_id,
            target_name=updated_row['hostname'] if updated_row else asset_id,
            before=row,
            after=updated_row,
            details={'source': 'api', 'production_transition': transitioning_to_production},
        )
        # If no earlier branch committed this update, the audit row and all
        # asset mutations are committed together.  A second commit is safe
        # for the legacy path and keeps the function's existing contract.
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
def delete_asset(asset_id: str, _user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        row = conn.execute(
            '''SELECT pa.id, pa.site_id, s.tenant_id AS site_tenant_id
               FROM physical_assets pa LEFT JOIN sites s ON s.id = pa.site_id
              WHERE pa.id = ?''',
            (asset_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Asset not found')
        _enforce_asset_row_scope(_user, row, 'delete')
        # Plan-A: cascade-delete linked device first
        _delete_linked_device(conn, asset_id)

        # Cascade-delete linked rack device through the canonical placement
        # service so the asset projection is cleared and rack layout_revision
        # is bumped in the same transaction.
        rack_device_rows = conn.execute(
            'SELECT id FROM rack_devices WHERE asset_id = ?', (asset_id,)
        ).fetchall()
        if rack_device_rows:
            from services import rack_service
            for rack_device_row in rack_device_rows:
                rack_service.delete_rack_device(conn, rack_device_row['id'], commit=False)

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
        _audit_asset_event(
            conn,
            event_type='asset.delete',
            summary='Physical asset deleted',
            user=_user,
            asset_id=asset_id,
            target_name=asset_id,
            before=row,
            details={'source': 'api'},
        )
        conn.commit()
        return {'ok': True}
    finally:
        conn.close()


# ── Rotation status polling ──────────────────────────────────────────

@router.get('/assets/{asset_id}/rotation-status')
def get_rotation_status(asset_id: str, _user=require_role("Viewer")):
    """Poll rotation progress after async production transition."""
    conn = get_db_connection()
    try:
        asset = conn.execute(
            '''SELECT pa.id, pa.site_id, s.tenant_id AS site_tenant_id
               FROM physical_assets pa LEFT JOIN sites s ON s.id = pa.site_id
              WHERE pa.id = ?''',
            (asset_id,),
        ).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail='Asset not found')
        _enforce_asset_row_scope(_user, asset, 'view')
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
def import_assets(
    items: list[AssetCreate],
    atomic: bool = False,
    detailed: bool = False,
    _user=require_role("Operator"),
):
    conn = get_db_connection()
    batch_id = f"asset-import-{uuid.uuid4().hex[:12]}"
    try:
        now = _utc_now()
        created = 0
        skipped = 0
        skipped_items = []
        failed_items: list[dict] = []
        row_results: list[dict] = []

        def _safe_import_error(exc: Exception) -> dict:
            detail = exc.detail if isinstance(exc, HTTPException) else None
            if isinstance(detail, dict):
                return {
                    'code': str(detail.get('code') or 'ASSET_IMPORT_ROW_FAILED'),
                    'message': str(detail.get('message') or '资产导入失败'),
                }
            if isinstance(exc, ValueError):
                return {'code': 'ASSET_IMPORT_VALIDATION_FAILED', 'message': str(exc)}
            logger.exception('Asset import row failed')
            return {'code': 'ASSET_IMPORT_ROW_FAILED', 'message': '资产导入行处理失败，请检查数据后重试。'}

        def _import_one(body: AssetCreate, row_number: int) -> dict:
            _pre_resolve_credential(conn, body)
            requested_tag_ids = _resolve_asset_tag_ids(conn, body)
            try:
                body.site_id = resolve_canonical_site_id(conn, body.site_id)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail={
                    'code': 'ASSET_SITE_INVALID', 'message': str(exc),
                }) from exc
            _enforce_asset_site_scope(conn, _user, body.site_id, 'create')
            asset_id = f"asset-{uuid.uuid4().hex[:12]}"
            body.platform = _normalize_asset_platform(body.vendor, body.platform, body.asset_type)
            asset_origin = body.asset_origin if body.asset_origin in ('new', 'legacy') else 'new'
            legacy_production = asset_origin == 'legacy' and body.lifecycle_status == 'production'
            initial_lifecycle = 'production' if legacy_production else 'staging'
            if not (body.hostname or '').strip() and not (body.asset_tag or '').strip():
                raise HTTPException(status_code=422, detail={
                    'code': 'ASSET_IDENTITY_REQUIRED',
                    'message': '导入资产必须至少填写主机名或资产编号',
                })
            if legacy_production:
                reason = (body.takeover_exempt_reason or '').strip()
                normal_username = (body.normal_username or body.username or '').strip()
                normal_password = (body.normal_password or body.password or '').strip()
                if len(reason) < 5:
                    raise HTTPException(status_code=422, detail={
                        'code': 'LEGACY_EXEMPT_REASON_REQUIRED',
                        'message': '存量设备直接投产必须填写至少 5 个字符的免上收原因',
                    })
                if not normal_username or not normal_password:
                    raise HTTPException(status_code=422, detail={
                        'code': 'LEGACY_CREDENTIAL_REQUIRED',
                        'message': '存量设备直接投产必须配置普通账号用户名和密码',
                    })
            duplicates = _find_asset_identity_duplicates(conn, body.model_dump())
            if duplicates:
                skipped_item = {
                    'row': row_number,
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
                }
                skipped_items.append(skipped_item)
                return {'status': 'skipped', **skipped_item}

            conn.execute('''
                INSERT INTO physical_assets (
                    id, asset_type, asset_tag, serial_number, vendor, model, hostname,
                    site_id, rack, rack_unit, u_height, planned_start_u, management_ip, business_ip, device_role,
                    vlan, uplink_switch, uplink_port,
                    status, lifecycle_status, asset_origin, purchase_date, warranty_expiry, department, notes,
                    platform, connection_method, username, password,
                    normal_username, normal_password, admin_username, admin_password,
                    enable_password, auth_model,
                    snmp_community, snmp_port, management_port, device_category, function, zone, power_watts,
                    credential_governance_mode, takeover_exempt_reason, takeover_exempt_at, is_managed,
                    credential_id, admin_credential_id,
                    created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
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
                _management_port_for_storage(body),
                body.device_category, getattr(body, 'function', '') or '', getattr(body, 'zone', 'Unknown') or 'Unknown', body.power_watts,
                'legacy_exempt' if legacy_production else 'managed',
                (body.takeover_exempt_reason or '').strip() if legacy_production else '',
                now if legacy_production else None,
                0 if legacy_production else 1,
                body.credential_id or '',
                body.admin_credential_id or '',
                now, now
            ))
            conn.execute(
                'UPDATE physical_assets SET snmp_credential_id = ?, management_port = ? WHERE id = ?',
                (body.snmp_credential_id or '', _management_port_for_storage(body), asset_id),
            )
            device_id = None
            if body.asset_type in ('network_device', 'server'):
                device_id = _create_linked_device(conn, asset_id, body, _user)
                _sync_asset_tags(conn, asset_id, requested_tag_ids)
                if legacy_production:
                    conn.execute(
                        "UPDATE devices SET lifecycle_status = 'production', rotation_status = 'exempt', is_managed = 0 WHERE id = ?",
                        (device_id,),
                    )

            # A placement failure is a failed row, never a successful import
            # with a warning in the server log.
            _sync_rack_device_from_asset(conn, asset_id, body, _user)
            try:
                replace_asset_web_profiles(conn, asset_id, body.web_profiles)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail={
                    'code': 'ASSET_WEB_PROFILE_INVALID', 'message': str(exc),
                }) from exc

            imported_row = conn.execute(
                'SELECT * FROM physical_assets WHERE id = ?', (asset_id,)
            ).fetchone()
            _audit_asset_event(
                conn,
                event_type='asset.import',
                summary='Physical asset imported',
                user=_user,
                asset_id=asset_id,
                target_name=body.hostname or body.asset_tag,
                after=imported_row,
                details={
                    'asset_type': body.asset_type,
                    'source': 'batch_import',
                    'batch_id': batch_id,
                    'row': row_number,
                },
            )
            return {
                'status': 'created',
                'row': row_number,
                'asset_id': asset_id,
                'device_id': device_id,
                'hostname': body.hostname,
                'asset_tag': body.asset_tag,
            }

        for row_number, body in enumerate(items, start=1):
            savepoint = f"asset_import_row_{row_number}"
            if detailed and not atomic:
                conn.execute(f'SAVEPOINT {savepoint}')
            try:
                result = _import_one(body, row_number)
                if result['status'] == 'created':
                    created += 1
                else:
                    skipped += 1
                row_results.append(result)
                if detailed and not atomic:
                    conn.execute(f'RELEASE SAVEPOINT {savepoint}')
            except Exception as exc:
                if atomic:
                    conn.rollback()
                    error = _safe_import_error(exc)
                    raise HTTPException(status_code=422, detail={
                        'code': 'ASSET_IMPORT_ATOMIC_FAILED',
                        'message': '资产批量导入已回滚，未提交任何行。',
                        'details': {'batch_id': batch_id, 'row': row_number, **error},
                    }) from exc
                if detailed:
                    conn.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
                    conn.execute(f'RELEASE SAVEPOINT {savepoint}')
                    error = _safe_import_error(exc)
                    item = {
                        'status': 'failed',
                        'row': row_number,
                        'asset_tag': body.asset_tag,
                        'hostname': body.hostname,
                        **error,
                    }
                    failed_items.append(item)
                    row_results.append(item)
                    continue
                conn.rollback()
                raise
        conn.commit()
        response = {
            'created': created,
            'skipped': skipped,
            'skipped_items': skipped_items,
        }
        if detailed or atomic:
            response.update({
                'batch_id': batch_id,
                'atomic': atomic,
                'failed': len(failed_items),
                'failed_items': failed_items,
                'results': row_results,
            })
        return response
    finally:
        conn.close()

@router.get("/assets/{asset_id}/verify")
def verify_asset_connectivity(asset_id: str, _user=require_role("Operator")):
    """
    Perform a quick connectivity check:
    1. Ping management IP
    2. Try the configured SSH management port (defaults to 22)
    3. If credentials exist, try SSH login (fast)
    """
    conn = get_db_connection()
    connectivity_slot_acquired = False
    try:
        asset = conn.execute(
            '''SELECT pa.*, s.tenant_id AS site_tenant_id
               FROM physical_assets pa LEFT JOIN sites s ON s.id = pa.site_id
              WHERE pa.id = ?''',
            (asset_id,),
        ).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        _enforce_asset_row_scope(_user, asset, 'verify')
        
        asset = dict(asset)
        ip = asset.get('management_ip')
        if not ip:
            _audit_asset_event(
                conn,
                event_type='asset.connectivity_verify',
                summary='Asset connectivity verification rejected: no management IP',
                user=_user,
                asset_id=asset_id,
                target_name=asset.get('hostname') or asset_id,
                status='failure',
                details={'reason': 'missing_management_ip'},
            )
            conn.commit()
            return {"success": False, "error": "No management IP configured", "ping": False, "ssh": False}

        # The target is always loaded from the already-authorized asset row;
        # validate it again at the network boundary so legacy rows cannot turn
        # this endpoint into a hostname/metadata/loopback probe.
        ip = _validate_connectivity_target(ip)
        from services.connection_profile import resolve_ssh_port
        try:
            ssh_port = _validate_connectivity_port(resolve_ssh_port(asset))
        except HTTPException:
            raise
        except Exception as exc:
            raise _connectivity_http_error(
                'CONNECTIVITY_PORT_INVALID',
                '资产的 SSH 管理端口配置无效。',
            ) from exc
        _acquire_connectivity_slot(asset_id)
        connectivity_slot_acquired = True

        results = {
            "ping": False,
            "ssh": False,
            "latency": 0,
            "ssh_error": None,
            "ping_error": None
        }

        # 1. Ping Test
        try:
            latency = ping3.ping(ip, timeout=_CONNECTIVITY_TIMEOUT_SECONDS)
            if latency is not None and latency is not False:
                results["ping"] = True
                results["latency"] = round(latency * 1000, 2)
            else:
                results["ping_error"] = "Ping timeout"
        except Exception:
            # Keep network/library details in server logs only.
            results["ping_error"] = "Ping failed or timed out"

        # 2. SSH Port Test (Quick check)
        try:
            with socket.create_connection((ip, ssh_port), timeout=_CONNECTIVITY_TIMEOUT_SECONDS):
                results["ssh_port_open"] = True
        except Exception:
            results["ssh_port_open"] = False
            results["ssh_error"] = "SSH port closed or unreachable"
            _audit_asset_event(
                conn,
                event_type='asset.connectivity_verify',
                summary='Asset connectivity verification completed',
                user=_user,
                asset_id=asset_id,
                target_name=asset.get('hostname') or asset_id,
                status='failure',
                details={
                    'target': ip,
                    'port': ssh_port,
                    'ping': bool(results.get('ping')),
                    'ssh_port_open': False,
                },
            )
            conn.commit()
            return results

        # 3. SSH Login Test (if credentials found)
        # Check physical_assets first, then linked device
        username = asset.get('username')
        password_enc = asset.get('password')
        password = decrypt_credential(password_enc) if password_enc else ''
        
        if not username or not password:
            dev = conn.execute('SELECT * FROM devices WHERE asset_id = ?', (asset_id,)).fetchone()
            if dev:
                device = dict(dev)
                collector_credentials = resolve_collector_credentials(device, ssh_role='normal')
                ssh_credentials = collector_credentials['ssh']
                username = str(ssh_credentials['username'] or '')
                password = str(ssh_credentials['password'] or '')
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

        if username and password:
            try:
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
                    "timeout_socket": _CONNECTIVITY_SSH_TIMEOUT_SECONDS,
                    "timeout_transport": _CONNECTIVITY_SSH_TIMEOUT_SECONDS,
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
                            timeout=_CONNECTIVITY_SSH_TIMEOUT_SECONDS,
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

        _audit_asset_event(
            conn,
            event_type='asset.connectivity_verify',
            summary='Asset connectivity verification completed',
            user=_user,
            asset_id=asset_id,
            target_name=asset.get('hostname') or asset_id,
            status='success' if results.get('ping') or results.get('ssh_port_open') else 'failure',
            details={
                'target': ip,
                'port': ssh_port,
                'ping': bool(results.get('ping')),
                'ssh_port_open': bool(results.get('ssh_port_open')),
                'ssh': bool(results.get('ssh')),
            },
        )
        return results
    finally:
        conn.close()
        if connectivity_slot_acquired:
            _CONNECTIVITY_SEMAPHORE.release()


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
def batch_takeover(body: BatchTakeoverRequest, _user=require_role("Administrator")):
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
                row = conn.execute(
                    '''SELECT pa.id, pa.lifecycle_status, pa.site_id,
                              s.tenant_id AS site_tenant_id
                         FROM physical_assets pa LEFT JOIN sites s ON s.id = pa.site_id
                        WHERE pa.id = ?''',
                    (asset_id,),
                ).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail='Asset not found')
                _enforce_asset_row_scope(_user, row, 'update')
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
                update_asset(
                    asset_id,
                    AssetUpdate(lifecycle_status='production'),
                    run_bg_rotate=False,
                    _user=_user,
                )
                
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
