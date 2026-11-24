"""
IPAM API — IP/VLAN resource management endpoints.
All write operations require Operator+; delete requires Administrator.
"""

import logging
import ipaddress as _ipaddress
from typing import Literal
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from core.rbac import authorize_resource, enforce_resource_scope, require_permission, require_role
from core.tenant_policy import (
    DEFAULT_TENANT_ID, TENANT_ISOLATION_ENABLED,
    tenant_id_for_write, tenant_scope_for_user,
)
from database import get_db_connection
from schemas.schemas import (
    AddressSpaceCreate, ResolvePrefixAddressSpaceRequest, MovePrefixAddressSpaceRequest,
    PrefixAddressSpaceBatchPreviewRequest, ResolvePrefixAddressSpaceBatchRequest,
    PrefixCreate, PrefixUpdate, BatchPrefixDeleteRequest, BatchPrefixNetworkTypeUpdate,
    IPAddressCreate, IPAddressUpdate,
    IPAMDiscoveryRegistrationRequest, IPAMDiscoveryMACCalibrationRequest,
    IPPoolCreate, IPPoolUpdate,
    VIPCreate, VIPUpdate,
    DHCPLeaseCreate, DHCPLeaseUpdate,
    IPAMRoutingContextCreate, IPAMRoutingContextUpdate,
    IPAMFHRPGroupCreate, IPAMFHRPGroupUpdate,
    IPAMFHRPGroupMemberAdd, IPAMFHRPVIPAttach,
    IPAMFHRPGroupResponse, IPAMFHRPGroupListResponse,
)
from services.ipam_service import (
    list_subnets,
    create_subnet,
    update_subnet,
    batch_update_subnet_network_type,
    delete_subnet,
    delete_subnets,
    list_addresses,
    list_ip_inventory,
    get_address_detail,
    create_address,
    update_address,
    delete_address,
    detect_conflicts,
    ipam_summary,
    get_subnets_tree,
    # New tables
    list_pools,
    create_pool,
    update_pool,
    delete_pool,
    list_vips,
    create_vip,
    update_vip,
    delete_vip,
    list_leases,
    create_lease,
    update_lease,
    delete_lease,
    get_utilization_analytics,
    get_next_available_ip_details,
    get_next_available_prefix,
    get_ipam_reconciliation,
    allocate_next_address,
    reserve_address,
    release_address,
    preview_interface_prefixes,
    preview_interface_prefix_import,
    generate_interface_prefixes,
    get_prefix_gateway_candidates,
    rebuild_prefixes_hierarchy,
    preview_delete_subnet,
    audit_ipam_scope_integrity,
)
from services.ipam_address_space_service import (
    create_address_space,
    list_address_spaces,
    preview_prefix_address_space,
    preview_prefix_address_space_move,
    preview_prefix_address_space_batch,
    resolve_prefix_address_space,
    move_prefix_address_space,
    resolve_prefix_address_space_batch,
)
from services.ipam_routing_context_service import (
    create_device_routing_context,
    get_routing_context_device_scope,
    get_routing_context_scope,
    list_device_routing_context_candidates,
    list_device_routing_contexts,
    update_device_routing_context,
)
from services.ipam_fhrp_group_service import (
    add_fhrp_group_member,
    attach_fhrp_group_vip,
    create_fhrp_group,
    delete_fhrp_group,
    detach_fhrp_group_vip,
    get_fhrp_device_scope,
    get_fhrp_group,
    get_fhrp_group_scope,
    get_fhrp_member_scope,
    get_fhrp_vip_scope,
    list_fhrp_groups,
    remove_fhrp_group_member,
    update_fhrp_group,
)
from services.ipam_current_fhrp_observation_service import get_current_fhrp_collection_states
from services.ipam_current_fhrp_projection_service import list_current_fhrp_observation_projection
from services.prefix_discovery_service import get_prefix_classification_summary
from services.audit_service import log_audit_event
from services.ipam_discovery_service import (
    list_current_discovered_endpoints,
    get_current_discovered_endpoint,
    register_current_endpoint_observation,
    calibrate_current_endpoint_mac,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _normalize_idempotency_key(value: object) -> str | None:
    """Normalize optional Header values, including FastAPI defaults on direct calls."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_expected_revision(value: object) -> int:
    """Reject missing/descriptor defaults when a route is called directly."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise HTTPException(status_code=422, detail='expected_revision must be a positive integer')
    return value


def _ipam_audit_context(user: dict) -> dict:
    return {
        'actor_id': user.get('id') or user.get('user_id'),
        'actor_username': user.get('username'),
        'actor_role': user.get('role'),
        'request_id': user.get('request_id'),
    }


def _is_stale_revision_error(exc: ValueError) -> bool:
    return 'revision is stale' in str(exc).casefold()


class AllocationRequest(BaseModel):
    hostname: str = ''
    device_id: str = ''
    interface_id: str = ''
    interface_name: str = ''
    mac_address: str = ''
    device_type: str = ''
    purpose: str = ''
    pool_id: str = ''
    requested_by: str = ''
    expires_at: str = ''
    status: str = 'allocated'


class ReservationRequest(AllocationRequest):
    address: str

    @field_validator('address')
    @classmethod
    def validate_host_address(cls, value: str) -> str:
        normalized = str(value or '').strip()
        if '/' in normalized:
            raise ValueError('address must be a host IP without a CIDR prefix length')
        try:
            return str(_ipaddress.ip_address(normalized))
        except ValueError as exc:
            raise ValueError('address must be a valid host IP') from exc


class ReleaseRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    released_by: str = ''


class InterfacePrefixGenerateRequest(BaseModel):
    candidate_ids: list[str] | None = None
    all_pending: bool = False
    vrf_overrides: dict[str, str] = Field(default_factory=dict)
    address_space_overrides: dict[str, str] = Field(default_factory=dict)


class InterfacePrefixImportPreviewRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=1)
    address_space_overrides: dict[str, str] = Field(default_factory=dict)


def _prefix_scope(subnet_id: str) -> dict:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT tenant_id, site_id FROM prefixes WHERE id = ?", (subnet_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Prefix not found')
        return {'tenant_id': row['tenant_id'], 'site_id': row['site_id']}
    finally:
        conn.close()


def _enforce_prefix_address_space_read_scope(user: dict, subnet_id: str) -> None:
    """Protect suggestions whose occupancy calculation spans an address space."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT tenant_id, address_space_id FROM prefixes WHERE id = ?',
            (subnet_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail='Prefix not found')
    address_space_id = str(row['address_space_id'] or '').strip()
    if address_space_id:
        _enforce_address_space_scope(
            user,
            address_space_id,
            str(row['tenant_id'] or DEFAULT_TENANT_ID),
            'view',
        )


def _pool_prefix_scope(pool_id: str) -> dict:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT prefix.tenant_id, prefix.site_id
                 FROM ipam_pools pool
                 JOIN prefixes prefix ON prefix.id = pool.prefix_id
                WHERE pool.id = ?""",
            (pool_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='IP Pool not found')
        return {'tenant_id': row['tenant_id'], 'site_id': row['site_id']}
    finally:
        conn.close()


def _vip_scope(vip_id: str) -> dict:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT COALESCE(prefix.tenant_id, vip.tenant_id) AS tenant_id,
                      prefix.site_id
                 FROM ipam_vips vip
                 LEFT JOIN prefixes prefix ON prefix.id = vip.prefix_id
                WHERE vip.id = ?""",
            (vip_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='VIP not found')
        return {'tenant_id': row['tenant_id'], 'site_id': row['site_id']}
    finally:
        conn.close()


def _lease_scope(lease_id: str) -> dict:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT COALESCE(prefix.tenant_id, lease.tenant_id) AS tenant_id,
                      prefix.site_id
                 FROM ipam_dhcp_leases lease
                 LEFT JOIN ipam_pools pool ON pool.id = lease.pool_id
                 LEFT JOIN prefixes prefix ON prefix.id = pool.prefix_id
                WHERE lease.id = ?""",
            (lease_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='DHCP Lease not found')
        return {'tenant_id': row['tenant_id'], 'site_id': row['site_id']}
    finally:
        conn.close()


def _visible_pending_resource_tenants(user: dict, table_name: str) -> list[str]:
    """Return tenants for unscoped legacy IPAM rows visible to this user."""
    tenant_scope = tenant_scope_for_user(user)
    conn = get_db_connection()
    try:
        if tenant_scope is not None:
            candidates = [str(tenant_scope)]
        elif table_name == 'ipam_vips':
            rows = conn.execute(
                """SELECT DISTINCT COALESCE(tenant_id, 'tenant-default') AS tenant_id
                     FROM ipam_vips
                    WHERE prefix_id IS NULL AND address_space_id IS NULL"""
            ).fetchall()
            candidates = [str(row['tenant_id']) for row in rows]
        elif table_name == 'ipam_dhcp_leases':
            rows = conn.execute(
                """SELECT DISTINCT COALESCE(tenant_id, 'tenant-default') AS tenant_id
                     FROM ipam_dhcp_leases
                    WHERE pool_id IS NULL AND address_space_id IS NULL"""
            ).fetchall()
            candidates = [str(row['tenant_id']) for row in rows]
        else:
            raise ValueError('Unsupported pending IPAM resource table')
    finally:
        conn.close()
    return sorted({
        tenant_id for tenant_id in candidates
        if authorize_resource(user, 'prefix', 'view', tenant_id=tenant_id)
    })


def _authorized_ipam_prefix_ids(user: dict, permission: str) -> list[str]:
    tenant_scope = tenant_scope_for_user(user)
    conn = get_db_connection()
    try:
        rows = conn.execute(
            'SELECT id, tenant_id, site_id FROM prefixes ORDER BY id'
        ).fetchall()
        scoped_rows = [
            row for row in rows
            if tenant_scope is None or str(row['tenant_id'] or DEFAULT_TENANT_ID) == tenant_scope
        ]
        candidate_scopes = {
            (
                str(row['tenant_id'] or DEFAULT_TENANT_ID),
                str(row['site_id'] or ''),
            )
            for row in scoped_rows
        }
        allowed_scopes = {
            scope for scope in candidate_scopes
            if authorize_resource(
                user, 'prefix', permission,
                tenant_id=scope[0], site_id=scope[1] or None,
            )
        }
        return [
            str(row['id'])
            for row in scoped_rows
            if (
                str(row['tenant_id'] or DEFAULT_TENANT_ID),
                str(row['site_id'] or ''),
            ) in allowed_scopes
        ]
    finally:
        conn.close()


def _authorized_ipam_pool_ids(user: dict, permission: str) -> list[str]:
    prefix_ids = _authorized_ipam_prefix_ids(user, permission)
    if not prefix_ids:
        return []
    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"SELECT id FROM ipam_pools WHERE prefix_id IN ({','.join('?' for _ in prefix_ids)}) ORDER BY id",
            tuple(prefix_ids),
        ).fetchall()
        return [str(row['id']) for row in rows]
    finally:
        conn.close()


def _address_scope(address_id: str) -> dict:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """SELECT p.tenant_id, p.site_id FROM ip_addresses ip
               JOIN prefixes p ON p.id = ip.subnet_id WHERE ip.id = ?""",
            (address_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Address not found')
        return {'tenant_id': row['tenant_id'], 'site_id': row['site_id']}
    finally:
        conn.close()


def _ipam_current_visible_scopes(
    user: dict,
    *,
    resource_type: str = 'ip_address',
    action: str = 'view',
) -> set[tuple[str, str]] | None:
    """Build current IPAM view scopes without consulting discovery history."""
    if user.get('role') == 'Administrator' and (
        not user.get('tenant_id') or user.get('role_profile') == 'System Administrator'
    ):
        return None
    conn = get_db_connection()
    try:
        candidates: set[tuple[str, str]] = set()
        for row in conn.execute('SELECT id, tenant_id FROM sites').fetchall():
            candidates.add((str(row['tenant_id'] or DEFAULT_TENANT_ID), str(row['id'] or '')))
        for row in conn.execute(
            """SELECT DISTINCT COALESCE(NULLIF(tenant_id, ''), ?) AS tenant_id,
                                      COALESCE(site_id, '') AS site_id
                 FROM prefixes""",
            (DEFAULT_TENANT_ID,),
        ).fetchall():
            candidates.add((str(row['tenant_id'] or ''), str(row['site_id'] or '')))
        for row in conn.execute(
            """SELECT DISTINCT COALESCE(NULLIF(s.tenant_id, ''), ?) AS tenant_id,
                                      COALESCE(e.site, '') AS site_id
                 FROM network_endpoints e
                 LEFT JOIN sites s ON s.id = e.site
                WHERE e.is_active = 1""",
            (DEFAULT_TENANT_ID,),
        ).fetchall():
            candidates.add((str(row['tenant_id'] or ''), str(row['site_id'] or '')))
        if not candidates:
            candidates.add((DEFAULT_TENANT_ID, ''))
        return {
            scope for scope in candidates
            if authorize_resource(
                user, resource_type, action,
                tenant_id=scope[0] or None, site_id=scope[1] or None,
            )
        }
    finally:
        conn.close()


def _new_ipam_child_tenant_id(requested_tenant_id: str | None, user: dict, prefix_id: str | None) -> str:
    """Keep child records attached to a legacy prefix's stored identity key."""
    normalized_prefix_id = str(prefix_id or '').strip()
    if normalized_prefix_id and not TENANT_ISOLATION_ENABLED:
        return str(_prefix_scope(normalized_prefix_id).get('tenant_id') or 'tenant-default')
    return tenant_id_for_write(requested=requested_tenant_id, user=user)


# ── Address spaces ───────────────────────────────

@router.get('/ipam/address-spaces')
def api_list_address_spaces(user=require_permission('prefix', 'view')):
    tenant_scope = tenant_scope_for_user(user)
    spaces = list_address_spaces(security_tenant_id=tenant_scope)
    # Address spaces can span physical sites. A site-only grant may see a
    # space only when it already contains a Prefix in one of those sites.
    return {
        'items': [
            item for item in spaces
            if authorize_resource(
                user, 'prefix', 'view',
                tenant_id=item['security_tenant_id'],
            ) or _address_space_has_site_view(user, item['id'], item['security_tenant_id'])
        ],
    }


def _address_space_has_site_view(user: dict, address_space_id: str, tenant_id: str) -> bool:
    return _address_space_has_site_permission(
        user, address_space_id, tenant_id, 'view',
    )


def _address_space_has_site_permission(
    user: dict,
    address_space_id: str,
    tenant_id: str,
    action: str,
) -> bool:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """SELECT DISTINCT site_id FROM prefixes
                 WHERE address_space_id = ?
                   AND COALESCE(NULLIF(btrim(tenant_id), ''), 'tenant-default') = ?
                   AND COALESCE(site_id, '') <> ''""",
            (address_space_id, tenant_id),
        ).fetchall()
    finally:
        conn.close()
    return any(
        authorize_resource(
            user, 'prefix', action, tenant_id=tenant_id, site_id=row['site_id'],
        )
        for row in rows
    )


def _address_space_scope_allowed(
    user: dict,
    address_space_id: str,
    tenant_id: str,
    action: str,
) -> bool:
    return authorize_resource(
        user, 'prefix', action, tenant_id=tenant_id,
    ) or _address_space_fully_visible_to_user(
        user, address_space_id, tenant_id, action,
    )


def _address_space_fully_visible_to_user(
    user: dict,
    address_space_id: str,
    tenant_id: str,
    action: str,
) -> bool:
    """Require site-scoped users to see every owner used by target-space reads."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """SELECT DISTINCT COALESCE(site_id, '') AS site_id FROM prefixes
                 WHERE address_space_id = ?
                   AND COALESCE(NULLIF(btrim(tenant_id), ''), 'tenant-default') = ?""",
            (address_space_id, tenant_id),
        ).fetchall()
        scope_candidates = {
            (str(tenant_id), str(row['site_id'] or ''))
            for row in rows
        }
        # Allocator previews also consult current mapped device contexts and
        # current ARP/ND/FHRP/interface observations. Include their owners in
        # the authorization boundary even when a site has not registered a
        # Prefix in this address space yet.
        context_rows = conn.execute(
            """SELECT DISTINCT
                      COALESCE(NULLIF(btrim(device.tenant_id), ''), 'tenant-default') AS tenant_id,
                      COALESCE(asset.site_id, device.site_id, '') AS site_id
                 FROM ipam_device_routing_contexts context
                 JOIN devices device ON device.id = context.device_id
                 LEFT JOIN physical_assets asset ON asset.id = device.asset_id
                WHERE context.address_space_id = ? AND context.status = 'active'""",
            (address_space_id,),
        ).fetchall()
        scope_candidates.update(
            (str(row['tenant_id'] or ''), str(row['site_id'] or ''))
            for row in context_rows
        )

        from services.ipam_current_endpoint_observation_service import list_current_endpoint_observations
        from services.ipam_current_fhrp_projection_service import list_current_fhrp_observation_projection
        from services.ipam_service import _current_cmdb_interface_ip_observations

        current_ip_rows = [
            *list_current_endpoint_observations(conn, observation_source='arp'),
            *list_current_endpoint_observations(conn, observation_source='ndp'),
            *_current_cmdb_interface_ip_observations(conn),
        ]
        current_fhrp_rows = list_current_fhrp_observation_projection(conn)
        for row in [*current_ip_rows, *current_fhrp_rows]:
            if str(row.get('address_space_id') or '') != address_space_id:
                continue
            owner_site_id = str(
                row.get('site_id') or row.get('asset_site_id') or row.get('device_site_id') or ''
            )
            scope_candidates.add((
                str(row.get('tenant_id') or tenant_id), owner_site_id,
            ))
    finally:
        conn.close()
    if not scope_candidates:
        return False
    return all(
        authorize_resource(
            user, 'prefix', action, tenant_id=scope_tenant,
            site_id=scope_site or None,
        )
        for scope_tenant, scope_site in scope_candidates
    )


def _enforce_address_space_scope(
    user: dict,
    address_space_id: str,
    tenant_id: str,
    action: str,
) -> None:
    if _address_space_scope_allowed(user, address_space_id, tenant_id, action):
        return
    # Preserve the standard structured RBAC denial response.
    enforce_resource_scope(user, 'prefix', action, tenant_id=tenant_id)


def _routing_context_response(item: dict) -> dict:
    """Expose only the stable public routing-context API fields."""
    return {
        field: item[field]
        for field in (
            'id', 'device_id', 'device_name', 'context_source', 'context_type',
            'local_context_key', 'local_context_name', 'address_space_id',
            'address_space_name', 'address_space_kind', 'vrf_id', 'status',
            'revision', 'last_verified_at', 'created_at', 'updated_at',
        )
    }


@router.get('/ipam/routing-contexts/candidates')
def api_list_routing_context_candidates(
    device_id: str = Query(..., min_length=1),
    user=require_permission('prefix', 'view'),
):
    normalized_device_id = device_id.strip()
    device_scope = get_routing_context_device_scope(normalized_device_id)
    user_tenant = tenant_scope_for_user(user)
    if not device_scope or (user_tenant is not None and device_scope['tenant_id'] != user_tenant):
        raise HTTPException(status_code=404, detail='Device not found in this security tenant')
    enforce_resource_scope(
        user, 'prefix', 'view',
        tenant_id=device_scope['tenant_id'], site_id=device_scope['site_id'],
    )
    items = list_device_routing_context_candidates(
        device_id=normalized_device_id,
        security_tenant_id=user_tenant,
    )
    return {'items': items}


@router.get('/ipam/routing-contexts')
def api_list_routing_contexts(
    device_id: str | None = Query(None),
    user=require_permission('prefix', 'view'),
):
    normalized_device_id = device_id.strip() if isinstance(device_id, str) else None
    items = list_device_routing_contexts(
        device_id=normalized_device_id or None,
        security_tenant_id=tenant_scope_for_user(user),
    )
    visible = []
    for item in items:
        tenant_id = str(item['_security_tenant_id'] or DEFAULT_TENANT_ID)
        address_space_id = str(item['address_space_id'] or '')
        if (
            tenant_id != str(item['_address_space_tenant_id'] or '')
            or not authorize_resource(
                user, 'prefix', 'view',
                tenant_id=tenant_id, site_id=item.get('_site_id'),
            )
            # This is a row-level listing: the device's site scope above and
            # any visible Prefix in the address space are sufficient. Requiring
            # full visibility of every site in a shared address space would
            # hide a mapping that is local to the user's device/site.
            or not (
                authorize_resource(user, 'prefix', 'view', tenant_id=tenant_id)
                or _address_space_has_site_view(user, address_space_id, tenant_id)
            )
        ):
            continue
        visible.append(_routing_context_response(item))
    return {'items': visible}


@router.post('/ipam/routing-contexts', status_code=201)
def api_create_routing_context(
    body: IPAMRoutingContextCreate,
    user=require_permission('prefix', 'create'),
):
    security_tenant_id = tenant_id_for_write(user=user)
    device_scope = get_routing_context_device_scope(body.device_id)
    if not device_scope or device_scope['tenant_id'] != security_tenant_id:
        raise HTTPException(status_code=404, detail='Device not found in this security tenant')
    enforce_resource_scope(
        user, 'prefix', 'create',
        tenant_id=device_scope['tenant_id'], site_id=device_scope['site_id'],
    )
    _enforce_address_space_scope(
        user, body.address_space_id, security_tenant_id, 'create',
    )
    try:
        result = create_device_routing_context(
            device_id=body.device_id,
            context_source=body.context_source,
            context_type=body.context_type,
            local_context_key=body.local_context_key,
            local_context_name=body.local_context_name,
            address_space_id=body.address_space_id,
            security_tenant_id=security_tenant_id,
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _routing_context_response(result)


@router.put('/ipam/routing-contexts/{context_id}')
def api_update_routing_context(
    context_id: str,
    body: IPAMRoutingContextUpdate,
    user=require_permission('prefix', 'update'),
):
    security_tenant_id = tenant_id_for_write(user=user)
    scope = get_routing_context_scope(context_id)
    if not scope or scope['tenant_id'] != security_tenant_id:
        raise HTTPException(status_code=404, detail='Routing-context mapping not found')
    enforce_resource_scope(
        user, 'prefix', 'update',
        tenant_id=scope['tenant_id'], site_id=scope['site_id'],
    )
    _enforce_address_space_scope(
        user, str(scope['address_space_id'] or ''), security_tenant_id, 'update',
    )

    fields = body.model_dump(exclude_unset=True)
    if 'address_space_id' in fields:
        if fields['address_space_id'] is None:
            raise HTTPException(status_code=422, detail='address_space_id must not be null')
        _enforce_address_space_scope(
            user, fields['address_space_id'], security_tenant_id, 'update',
        )
    expected_revision = fields.pop('expected_revision')
    try:
        result = update_device_routing_context(
            context_id,
            expected_revision=expected_revision,
            security_tenant_id=security_tenant_id,
            address_space_id=fields.get('address_space_id'),
            local_context_name=fields.get('local_context_name'),
            status=fields.get('status'),
            update_local_context_name='local_context_name' in fields,
            update_status='status' in fields,
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail='Routing-context mapping not found')
    return _routing_context_response(result)


@router.post('/ipam/address-spaces', status_code=201)
def api_create_address_space(body: AddressSpaceCreate, user=require_permission('prefix', 'create')):
    security_tenant_id = tenant_id_for_write(user=user)
    enforce_resource_scope(user, 'prefix', 'create', tenant_id=security_tenant_id)
    try:
        result = create_address_space(
            name=body.name,
            kind=body.kind,
            vrf_id=body.vrf_id,
            security_tenant_id=security_tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    log_audit_event(
        event_type='ipam.address_space.create',
        category='ipam',
        severity='info',
        status='success',
        summary=f"Created {body.kind} IPAM address space {body.name}",
        actor_username=user.get('username'),
        actor_role=user.get('role'),
        target_type='ipam_address_space',
        target_id=result['id'],
        target_name=result['name'],
        details={'kind': result['kind'], 'vrf_id': result.get('vrf_id')},
    )
    return result


# ── Prefixes (Subnets) ──────────────────────────

@router.get('/ipam/subnets')
def api_list_subnets(
    site: str = 'all',
    status: str = 'all',
    q: str = '',
    family: str = 'all',
    classification: str = Query('all', pattern='^(all|auto|manual|unclassified|mixed|conflict|reuse|stale)$'),
    page: int | None = None,
    page_size: int = 20,
    include_metrics: bool = Query(
        True,
        description='Set false for selector lists: skips per-prefix capacity, active-endpoint and purpose-suggestion work',
    ),
    user=require_permission('prefix', 'view'),
):
    allowed_prefix_ids = _authorized_ipam_prefix_ids(user, 'view')
    return list_subnets(
        site=site, status=status, q=q, family=family, classification=classification,
        page=page, page_size=page_size, allowed_prefix_ids=allowed_prefix_ids,
        include_metrics=include_metrics,
    )


@router.get('/ipam/prefixes/interface-candidates')
def api_preview_interface_prefixes(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status: str = Query('all', pattern='^(all|to_create|existing|scope_pending|global_default)$'),
    q: str = Query('', max_length=120),
    user=require_permission('prefix', 'view'),
):
    """Preview prefixes derived from current L3 interface collection only."""
    preview_args = {
        'page': page,
        'page_size': page_size,
        'status': status,
        'visible_scopes': _ipam_current_visible_scopes(user, resource_type='prefix', action='view'),
    }
    if isinstance(q, str) and q.strip():
        preview_args['q'] = q
    return preview_interface_prefixes(**preview_args)


@router.post('/ipam/prefixes/interface-import-preview')
def api_preview_interface_prefix_import(
    body: InterfacePrefixImportPreviewRequest,
    user=require_permission('prefix', 'create'),
):
    """Check the exact selected interface sources against current IPAM data."""
    allowed_scopes = _ipam_current_visible_scopes(user, resource_type='prefix', action='create')
    for candidate_id, address_space_id in body.address_space_overrides.items():
        if not str(candidate_id or '').strip() or not str(address_space_id or '').strip():
            raise HTTPException(status_code=422, detail='地址空间覆盖必须填写候选 ID 和地址空间 ID')
    try:
        result = preview_interface_prefix_import(
            body.candidate_ids,
            address_space_overrides=body.address_space_overrides,
            allowed_scopes=allowed_scopes,
        )
        for group in result.get('groups', []):
            space_id = str(group.get('address_space_id') or '')
            tenant_id = str(group.get('tenant_id') or '')
            if space_id:
                _enforce_address_space_scope(user, space_id, tenant_id, 'create')
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get('/ipam/prefixes/classification-summary')
def api_prefix_classification_summary(
    site: str = 'all',
    status: str = 'all',
    q: str = '',
    family: str = Query('all', pattern='^(all|ipv4|ipv6)$'),
    user=require_permission('prefix', 'view'),
):
    return get_prefix_classification_summary(
        site=site, status=status, q=q, family=family,
        allowed_prefix_ids=_authorized_ipam_prefix_ids(user, 'view'),
    )


@router.post('/ipam/prefixes/generate-from-interfaces')
def api_generate_interface_prefixes(
    body: InterfacePrefixGenerateRequest,
    idempotency_key: str | None = Header(None, alias='Idempotency-Key'),
    user=require_permission('prefix', 'create'),
):
    if body.all_pending and body.candidate_ids is not None:
        raise HTTPException(
            status_code=422,
            detail='candidate_ids 与 all_pending 不能同时提供',
        )
    if not body.all_pending and not body.candidate_ids:
        raise HTTPException(
            status_code=422,
            detail='请提供非空 candidate_ids，或显式设置 all_pending=true',
        )

    allowed_scopes = _ipam_current_visible_scopes(user, resource_type='prefix', action='create')
    preview = preview_interface_prefixes(
        page=1, page_size=100, status='all', visible_scopes=allowed_scopes,
    )
    visible_candidates = list(preview.get('candidates', []))
    for page_number in range(2, int(preview.get('total_pages') or 1) + 1):
        page_result = preview_interface_prefixes(
            page=page_number, page_size=100, status='all', visible_scopes=allowed_scopes,
        )
        visible_candidates.extend(page_result.get('candidates', []))
    candidates_by_id = {
        str(item.get('candidate_id') or ''): item for item in visible_candidates
    }
    selected_ids = (
        {key for key, item in candidates_by_id.items() if item.get('status') == 'to_create'}
        if body.all_pending
        else {str(value).strip() for value in (body.candidate_ids or []) if str(value).strip()}
    )
    if not body.all_pending and not selected_ids.issubset(candidates_by_id):
        raise HTTPException(status_code=404, detail='候选不存在或无权访问，请刷新预览')
    if not body.all_pending:
        unknown_override_ids = (
            set(body.address_space_overrides) | set(body.vrf_overrides)
        ) - selected_ids
        if unknown_override_ids:
            raise HTTPException(status_code=422, detail='归属覆盖只能用于本次选择的候选')
    for candidate_id in selected_ids:
        candidate = candidates_by_id.get(candidate_id)
        target_space_id = str(
            body.address_space_overrides.get(candidate_id)
            or (candidate or {}).get('address_space_id') or ''
        ).strip()
        if target_space_id and candidate:
            _enforce_address_space_scope(
                user, target_space_id,
                str(candidate.get('tenant_id') or ''), 'create',
            )

    try:
        result = generate_interface_prefixes(
            candidate_ids=body.candidate_ids,
            all_pending=body.all_pending,
            vrf_overrides=body.vrf_overrides,
            address_space_overrides=body.address_space_overrides,
            allowed_scopes=allowed_scopes,
            audit_context=_ipam_audit_context(user),
            idempotency_key=_normalize_idempotency_key(idempotency_key),
            idempotency_tenant_id=tenant_id_for_write(user=user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return result


@router.post('/ipam/subnets', status_code=201)
def api_create_subnet(
    body: PrefixCreate,
    idempotency_key: str | None = Header(None, alias='Idempotency-Key'),
    user=require_permission('prefix', 'create'),
):
    # Tenant/security scope is derived server-side. Client fields cannot
    # reassign a Prefix into another security tenant.
    tenant_id = tenant_id_for_write(user=user)
    enforce_resource_scope(user, 'prefix', 'create', tenant_id=tenant_id, site_id=body.site_id)
    if body.address_space_id:
        _enforce_address_space_scope(
            user, body.address_space_id, tenant_id, 'create',
        )
    try:
        result = create_subnet(
            prefix=body.prefix,
            address_space_id=body.address_space_id,
            vrf_id=body.vrf_id,
            vlan_id=body.vlan_id,
            site_id=body.site_id,
            tenant_id=tenant_id,
            status=body.status,
            name=body.name,
            gateway=body.gateway,
            description=body.description,
            network_type=body.network_type,
            gateway_device_id=body.gateway_device_id,
            gateway_interface_id=body.gateway_interface_id,
            traceable=body.traceable,
            idempotency_key=_normalize_idempotency_key(idempotency_key),
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return result


@router.get('/ipam/subnets/{subnet_id}/address-space-preview')
def api_preview_prefix_address_space(
    subnet_id: str,
    address_space_id: str = Query(..., min_length=1),
    user=require_permission('prefix', 'view'),
):
    scope = _prefix_scope(subnet_id)
    enforce_resource_scope(user, 'prefix', 'view', **scope)
    _enforce_address_space_scope(
        user, address_space_id, str(scope.get('tenant_id') or ''), 'view',
    )
    result = preview_prefix_address_space(
        subnet_id,
        address_space_id=address_space_id,
        security_tenant_id=str(scope.get('tenant_id') or ''),
    )
    if not result:
        raise HTTPException(status_code=404, detail='Prefix not found')
    return result


@router.post('/ipam/subnets/{subnet_id}/resolve-address-space')
def api_resolve_prefix_address_space(
    subnet_id: str,
    body: ResolvePrefixAddressSpaceRequest,
    user=require_permission('prefix', 'update'),
):
    scope = _prefix_scope(subnet_id)
    enforce_resource_scope(user, 'prefix', 'update', **scope)
    _enforce_address_space_scope(
        user, body.address_space_id, str(scope.get('tenant_id') or ''), 'update',
    )
    try:
        result = resolve_prefix_address_space(
            subnet_id,
            address_space_id=body.address_space_id,
            expected_updated_at=body.expected_updated_at,
            expected_revision=body.expected_revision,
            confirmed=body.confirmed,
            security_tenant_id=str(scope.get('tenant_id') or ''),
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    rebuild_prefixes_hierarchy()
    return result


@router.get('/ipam/subnets/{subnet_id}/address-space-move-preview')
def api_preview_prefix_address_space_move(
    subnet_id: str,
    address_space_id: str = Query(..., min_length=1),
    user=require_permission('prefix', 'view'),
):
    scope = _prefix_scope(subnet_id)
    enforce_resource_scope(user, 'prefix', 'view', **scope)
    _enforce_address_space_scope(
        user, address_space_id, str(scope.get('tenant_id') or ''), 'view',
    )
    result = preview_prefix_address_space_move(
        subnet_id,
        address_space_id=address_space_id,
        security_tenant_id=str(scope.get('tenant_id') or ''),
    )
    if not result:
        raise HTTPException(status_code=404, detail='Prefix not found')
    return result


@router.post('/ipam/subnets/{subnet_id}/move-address-space')
def api_move_prefix_address_space(
    subnet_id: str,
    body: MovePrefixAddressSpaceRequest,
    user=require_permission('prefix', 'update'),
):
    scope = _prefix_scope(subnet_id)
    enforce_resource_scope(user, 'prefix', 'update', **scope)
    _enforce_address_space_scope(
        user, body.address_space_id, str(scope.get('tenant_id') or ''), 'update',
    )
    try:
        result = move_prefix_address_space(
            subnet_id,
            address_space_id=body.address_space_id,
            expected_updated_at=body.expected_updated_at,
            expected_revision=body.expected_revision,
            confirmed=body.confirmed,
            security_tenant_id=str(scope.get('tenant_id') or ''),
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    rebuild_prefixes_hierarchy()
    return result


@router.post('/ipam/subnets/address-space-batch-preview')
def api_preview_prefix_address_space_batch(
    body: PrefixAddressSpaceBatchPreviewRequest,
    user=require_permission('prefix', 'view'),
):
    first_scope = _prefix_scope(body.ids[0])
    batch_tenants: set[str] = set()
    for prefix_id in body.ids:
        item_scope = _prefix_scope(prefix_id)
        enforce_resource_scope(user, 'prefix', 'view', **item_scope)
        batch_tenants.add(str(item_scope.get('tenant_id') or 'tenant-default'))
    if len(batch_tenants) > 1:
        raise HTTPException(
            status_code=409,
            detail='All Prefixes in a batch must belong to the same security tenant',
        )
    _enforce_address_space_scope(
        user, body.address_space_id, str(first_scope.get('tenant_id') or ''), 'view',
    )
    try:
        return preview_prefix_address_space_batch(
            body.ids,
            address_space_id=body.address_space_id,
            security_tenant_id=str(first_scope.get('tenant_id') or ''),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/ipam/subnets/address-space-batch-resolve')
def api_resolve_prefix_address_space_batch(
    body: ResolvePrefixAddressSpaceBatchRequest,
    user=require_permission('prefix', 'update'),
):
    first_scope = _prefix_scope(body.items[0].prefix_id)
    batch_tenants: set[str] = set()
    for item in body.items:
        item_scope = _prefix_scope(item.prefix_id)
        enforce_resource_scope(user, 'prefix', 'update', **item_scope)
        batch_tenants.add(str(item_scope.get('tenant_id') or 'tenant-default'))
    if len(batch_tenants) > 1:
        raise HTTPException(
            status_code=409,
            detail='All Prefixes in a batch must belong to the same security tenant',
        )
    _enforce_address_space_scope(
        user, body.address_space_id, str(first_scope.get('tenant_id') or ''), 'update',
    )
    try:
        result = resolve_prefix_address_space_batch(
            [item.model_dump() for item in body.items],
            address_space_id=body.address_space_id,
            expected_target_revision=body.expected_target_revision,
            confirmed=body.confirmed,
            security_tenant_id=str(first_scope.get('tenant_id') or ''),
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    rebuild_prefixes_hierarchy()
    return result


@router.put('/ipam/subnets/{subnet_id}')
def api_update_subnet(subnet_id: str, body: PrefixUpdate, user=require_permission('prefix', 'update')):
    current_scope = _prefix_scope(subnet_id)
    enforce_resource_scope(user, 'prefix', 'update', **current_scope)
    fields = body.model_dump(exclude_none=True)
    fields.pop('tenant_id', None)
    if 'site_id' in fields and str(fields['site_id'] or '') != str(current_scope.get('site_id') or ''):
        enforce_resource_scope(
            user,
            'prefix',
            'update',
            tenant_id=current_scope.get('tenant_id'),
            site_id=fields['site_id'],
        )
    audit_context = _ipam_audit_context(user)
    try:
        if not update_subnet(subnet_id, **fields, audit_context=audit_context):
            raise HTTPException(status_code=404, detail='Prefix not found')
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {'ok': True}


@router.get('/ipam/subnets/{subnet_id}/delete-preview')
def api_preview_delete_subnet(
    subnet_id: str,
    user=require_permission('prefix', 'view'),
):
    enforce_resource_scope(user, 'prefix', 'view', **_prefix_scope(subnet_id))
    preview = preview_delete_subnet(subnet_id)
    if not preview:
        raise HTTPException(status_code=404, detail='Prefix not found')
    return preview


@router.get('/ipam/audit/scope-integrity')
def api_audit_ipam_scope_integrity(
    user=require_permission('prefix', 'view'),
):
    allowed_prefix_ids = _authorized_ipam_prefix_ids(user, 'view') if isinstance(user, dict) else None
    return audit_ipam_scope_integrity(allowed_prefix_ids=allowed_prefix_ids)


@router.delete('/ipam/subnets/{subnet_id}')
def api_delete_subnet(
    subnet_id: str,
    expected_revision: int = Query(..., ge=1),
    user=require_permission('prefix', 'delete'),
):
    expected_revision = _normalize_expected_revision(expected_revision)
    enforce_resource_scope(user, 'prefix', 'delete', **_prefix_scope(subnet_id))
    try:
        if not delete_subnet(
            subnet_id,
            expected_revision=expected_revision,
            audit_context=_ipam_audit_context(user),
        ):
            raise HTTPException(status_code=404, detail='Prefix not found')
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {'ok': True}


@router.post('/ipam/subnets/batch-delete')
def api_batch_delete_subnets(body: BatchPrefixDeleteRequest, user=require_permission('prefix', 'delete')):
    for subnet_id in body.ids:
        enforce_resource_scope(user, 'prefix', 'delete', **_prefix_scope(subnet_id))
    try:
        result = delete_subnets(
            body.ids,
            expected_revisions=body.expected_revisions,
            audit_context=_ipam_audit_context(user),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {'ok': True, 'deleted': result['deleted'], 'failed': 0}


@router.post('/ipam/subnets/batch-update-network-type')
def api_batch_update_subnet_network_type(
    body: BatchPrefixNetworkTypeUpdate,
    user=require_permission('prefix', 'update'),
):
    def validate_scope(row: dict) -> None:
        enforce_resource_scope(
            user,
            'prefix',
            'update',
            tenant_id=row.get('tenant_id') or DEFAULT_TENANT_ID,
            site_id=row.get('site_id') or None,
        )

    try:
        if set(body.expected_revisions) != set(body.ids):
            raise HTTPException(status_code=422, detail='expected_revisions must include every selected Prefix')
        result = batch_update_subnet_network_type(
            body.ids,
            body.network_type,
            expected_revisions=body.expected_revisions,
            scope_validator=validate_scope,
            audit_context=_ipam_audit_context(user),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        if _is_stale_revision_error(exc):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return result


@router.get('/ipam/prefixes/gateway-candidates')
def api_prefix_gateway_candidates(
    prefix: str = Query(..., min_length=3, max_length=80),
    site_id: str | None = Query(None, min_length=1, max_length=128),
    gateway_ip: str | None = Query(None, max_length=128),
    address_space_id: str | None = Query(None, min_length=1, max_length=200),
    user=require_role('Viewer'),
):
    tenant_id = tenant_id_for_write(user=user)
    if site_id:
        enforce_resource_scope(
            user,
            'prefix',
            'view',
            tenant_id=tenant_id,
            site_id=site_id,
        )
    try:
        return get_prefix_gateway_candidates(
            prefix=prefix,
            site_id=site_id,
            tenant_id=tenant_id,
            gateway_ip=gateway_ip,
            address_space_id=address_space_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── IP Addresses ──────────────────────────────

@router.get('/ipam/addresses')
def api_list_ip_inventory(
    site_id: str = 'all',
    prefix_id: str = '',
    q: str = '',
    status: str = 'all',
    device_type: str = 'all',
    purpose: str = 'all',
    page: int = 1,
    page_size: int = 20,
    registered_only: bool = Query(False, description='Return only persisted IPAM address records'),
    _user=require_permission('ip_address', 'view'),
):
    """List manual IPAM records together with active discovered endpoints."""
    return list_ip_inventory(
        site_id=site_id,
        prefix_id=prefix_id,
        q=q,
        status=status,
        device_type=device_type,
        purpose=purpose,
        page=page,
        page_size=page_size,
        registered_only=registered_only,
        visible_scopes=(
            _ipam_current_visible_scopes(_user, resource_type='ip_address', action='view')
            if isinstance(_user, dict) else None
        ),
    )

@router.get('/ipam/addresses/{address_id}/detail')
def api_get_address_detail(address_id: str, _user=require_permission('ip_address', 'view')):
    """Read-only detail for one registered address (prefix, device, interface, discovery, history)."""
    if isinstance(_user, dict) and not authorize_resource(
        _user, 'ip_address', 'view', **_address_scope(address_id),
    ):
        raise HTTPException(status_code=404, detail='Address not found')
    detail = get_address_detail(
        address_id,
        visible_scopes=(
            _ipam_current_visible_scopes(_user, resource_type='ip_address', action='view')
            if isinstance(_user, dict) else None
        ),
    )
    if not detail:
        raise HTTPException(status_code=404, detail='Address not found')
    return detail


@router.get('/ipam/subnets/{subnet_id}/addresses')
def api_list_addresses(subnet_id: str, q: str = '', status: str = 'all', device_type: str = 'all',
                       purpose: str = 'all',
                       page: int | None = Query(None, ge=1), page_size: int = Query(20, ge=1, le=100),
                       _user=require_permission('ip_address', 'view')):
    scope = _prefix_scope(subnet_id)
    if isinstance(_user, dict) and not authorize_resource(
        _user, 'ip_address', 'view', **scope,
    ):
        raise HTTPException(status_code=404, detail='Prefix not found')
    return list_addresses(subnet_id, q=q, status=status, device_type=device_type, purpose=purpose, page=page, page_size=page_size)


@router.post('/ipam/subnets/{subnet_id}/addresses', status_code=201)
def api_create_address(
    subnet_id: str,
    body: IPAddressCreate,
    idempotency_key: str | None = Header(None, alias='Idempotency-Key'),
    user=require_permission('ip_address', 'create'),
):
    enforce_resource_scope(user, 'ip_address', 'create', **_prefix_scope(subnet_id))
    if body.pool_id:
        enforce_resource_scope(user, 'ip_address', 'create', **_pool_prefix_scope(body.pool_id))
    try:
        result = create_address(
            subnet_id,
            address=body.address,
            hostname=body.hostname,
            device_id=body.device_id,
            interface_name=body.interface_name,
            interface_id=getattr(body, 'interface_id', ''),
            mac_address=body.mac_address,
            device_type=body.device_type,
            purpose=body.purpose,
            pool_id=body.pool_id,
            description=body.description,
            status=body.status,
            requested_by=user.get('username', ''),
            expires_at=body.expires_at,
            idempotency_key=_normalize_idempotency_key(idempotency_key),
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return result


@router.post('/ipam/subnets/{subnet_id}/allocate-next', status_code=201)
def api_allocate_next_address(
    subnet_id: str,
    body: AllocationRequest,
    idempotency_key: str | None = Header(None, alias='Idempotency-Key'),
    user=require_permission('ip_address', 'allocate'),
):
    enforce_resource_scope(user, 'ip_address', 'allocate', **_prefix_scope(subnet_id))
    values = body.model_dump()
    if values.get('pool_id'):
        enforce_resource_scope(user, 'ip_address', 'allocate', **_pool_prefix_scope(values['pool_id']))
    try:
        result = allocate_next_address(
            subnet_id,
            hostname=values['hostname'], device_id=values['device_id'],
            interface_id=values['interface_id'], interface_name=values['interface_name'],
            mac_address=values['mac_address'], device_type=values['device_type'], purpose=values['purpose'],
            pool_id=values['pool_id'],
            requested_by=values['requested_by'] or user.get('username', ''),
            status=values['status'], expires_at=values['expires_at'],
            idempotency_key=_normalize_idempotency_key(idempotency_key),
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return result


@router.post('/ipam/subnets/{subnet_id}/reserve', status_code=201)
def api_reserve_address(
    subnet_id: str,
    body: ReservationRequest,
    idempotency_key: str | None = Header(None, alias='Idempotency-Key'),
    user=require_permission('ip_address', 'reserve'),
):
    enforce_resource_scope(user, 'ip_address', 'reserve', **_prefix_scope(subnet_id))
    values = body.model_dump()
    if values.get('pool_id'):
        enforce_resource_scope(user, 'ip_address', 'reserve', **_pool_prefix_scope(values['pool_id']))
    try:
        result = reserve_address(
            subnet_id,
            address=values['address'], hostname=values['hostname'],
            device_id=values['device_id'], interface_id=values['interface_id'],
            interface_name=values['interface_name'], mac_address=values['mac_address'],
            device_type=values['device_type'],
            purpose=values['purpose'], pool_id=values['pool_id'] or None,
            requested_by=values['requested_by'] or user.get('username', ''),
            expires_at=values['expires_at'],
            idempotency_key=_normalize_idempotency_key(idempotency_key),
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return result


@router.put('/ipam/addresses/{address_id}')
def api_update_address(address_id: str, body: IPAddressUpdate, user=require_permission('ip_address', 'update')):
    enforce_resource_scope(user, 'ip_address', 'update', **_address_scope(address_id))
    fields = body.model_dump(exclude_unset=True)
    try:
        if not update_address(address_id, **fields, audit_context=_ipam_audit_context(user)):
            raise HTTPException(status_code=404, detail='Address not found')
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {'ok': True}


@router.delete('/ipam/addresses/{address_id}')
def api_delete_address(
    address_id: str,
    expected_revision: int = Query(..., ge=1),
    user=require_permission('ip_address', 'delete'),
):
    expected_revision = _normalize_expected_revision(expected_revision)
    enforce_resource_scope(user, 'ip_address', 'delete', **_address_scope(address_id))
    try:
        if not delete_address(
            address_id,
            expected_revision=expected_revision,
            audit_context=_ipam_audit_context(user),
        ):
            raise HTTPException(status_code=404, detail='Address not found')
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {'ok': True}


@router.post('/ipam/addresses/{address_id}/release')
def api_release_address(address_id: str, body: ReleaseRequest, user=require_permission('ip_address', 'release')):
    enforce_resource_scope(user, 'ip_address', 'release', **_address_scope(address_id))
    values = body.model_dump()
    try:
        if not release_address(
            address_id,
            released_by=values.get('released_by') or user.get('username', ''),
            expected_revision=values['expected_revision'],
            audit_context=_ipam_audit_context(user),
        ):
            raise HTTPException(status_code=404, detail='Address not found')
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {'ok': True}


# ── Dynamic Pools (ipam_pools) ─────────────────

@router.get('/ipam/pools')
def api_list_pools(
    q: str = Query('', description='Search pool name, prefix or description'),
    status: str = Query('', description='Filter pool status'),
    prefix_id: str = Query('', description='Filter pools within a prefix'),
    page: int | None = Query(None, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=require_permission('prefix', 'view'),
):
    q_value = q if isinstance(q, str) else ''
    status_value = status if isinstance(status, str) else ''
    prefix_id_value = prefix_id if isinstance(prefix_id, str) else ''
    page_value = page if isinstance(page, int) else None
    page_size_value = page_size if isinstance(page_size, int) else 20
    if prefix_id_value:
        enforce_resource_scope(user, 'prefix', 'view', **_prefix_scope(prefix_id_value))
        allowed_prefix_ids = [prefix_id_value]
    else:
        allowed_prefix_ids = _authorized_ipam_prefix_ids(user, 'view')
    return list_pools(
        q=q_value, status=status_value, prefix_id=prefix_id_value,
        page=page_value, page_size=page_size_value,
        allowed_prefix_ids=allowed_prefix_ids,
    )


@router.post('/ipam/pools', status_code=201)
def api_create_pool(
    body: IPPoolCreate,
    idempotency_key: str | None = Header(None, alias='Idempotency-Key'),
    user=require_permission('prefix', 'create'),
):
    enforce_resource_scope(user, 'prefix', 'create', **_prefix_scope(body.prefix_id))
    try:
        result = create_pool(
            name=body.name,
            prefix_id=body.prefix_id or '',
            start_ip=body.start_ip,
            end_ip=body.end_ip,
            management_mode=body.management_mode,
            allocation_allowed=body.allocation_allowed,
            mark_populated=body.mark_populated,
            mark_utilized=body.mark_utilized,
            description=body.description,
            status=body.status,
            idempotency_key=_normalize_idempotency_key(idempotency_key),
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return result


@router.put('/ipam/pools/{pool_id}')
def api_update_pool(pool_id: str, body: IPPoolUpdate, user=require_permission('prefix', 'update')):
    enforce_resource_scope(user, 'prefix', 'update', **_pool_prefix_scope(pool_id))
    fields = body.model_dump(exclude_none=True)
    if fields.get('prefix_id'):
        enforce_resource_scope(user, 'prefix', 'update', **_prefix_scope(fields['prefix_id']))
    try:
        if not update_pool(pool_id, **fields, audit_context=_ipam_audit_context(user)):
            raise HTTPException(status_code=404, detail='IP Pool not found')
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return {'ok': True}


@router.delete('/ipam/pools/{pool_id}')
def api_delete_pool(
    pool_id: str,
    expected_revision: int = Query(..., ge=1),
    user=require_permission('prefix', 'delete'),
):
    expected_revision = _normalize_expected_revision(expected_revision)
    enforce_resource_scope(user, 'prefix', 'delete', **_pool_prefix_scope(pool_id))
    try:
        if not delete_pool(
            pool_id,
            expected_revision=expected_revision,
            audit_context=_ipam_audit_context(user),
        ):
            raise HTTPException(status_code=404, detail='IP Pool not found')
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {'ok': True}


# ── Virtual IPs (ipam_vips) ───────────────────

@router.get('/ipam/vips')
def api_list_vips(
    q: str = Query('', description='Search VIP address or description'),
    vip_type: str = Query('', description='Filter VIP type'),
    status: str = Query('', description='Filter VIP status'),
    prefix_id: str = Query('', description='Filter VIPs within a prefix'),
    page: int | None = Query(None, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=require_permission('prefix', 'view'),
):
    if prefix_id:
        enforce_resource_scope(user, 'prefix', 'view', **_prefix_scope(prefix_id))
        # The requested Prefix defines the address range, while the returned
        # VIP rows must still belong to a Prefix this user can see (including
        # visible child Prefixes in the same address space).
        allowed_prefix_ids = _authorized_ipam_prefix_ids(user, 'view')
        pending_tenants: list[str] = []
    else:
        allowed_prefix_ids = _authorized_ipam_prefix_ids(user, 'view')
        pending_tenants = _visible_pending_resource_tenants(user, 'ipam_vips')
    return list_vips(
        q=q,
        vip_type=vip_type,
        status=status,
        prefix_id=prefix_id,
        page=page,
        page_size=page_size,
        allowed_prefix_ids=allowed_prefix_ids,
        allowed_pending_tenant_ids=pending_tenants,
    )


@router.post('/ipam/vips', status_code=201)
def api_create_vip(
    body: VIPCreate,
    idempotency_key: str | None = Header(None, alias='Idempotency-Key'),
    user=require_permission('prefix', 'create'),
):
    enforce_resource_scope(user, 'prefix', 'create', **_prefix_scope(body.prefix_id))
    try:
        result = create_vip(
            address=body.address,
            vip_type=body.vip_type,
            device_id=body.device_id,
            backup_device_id=body.backup_device_id,
            interface_name=body.interface_name,
            description=body.description,
            real_servers=body.real_servers,
            status=body.status,
            prefix_id=body.prefix_id,
            idempotency_key=_normalize_idempotency_key(idempotency_key),
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return result


@router.put('/ipam/vips/{vip_id}')
def api_update_vip(vip_id: str, body: VIPUpdate, user=require_permission('prefix', 'update')):
    enforce_resource_scope(user, 'prefix', 'update', **_vip_scope(vip_id))
    fields = body.model_dump(exclude_none=True)
    if fields.get('prefix_id'):
        enforce_resource_scope(user, 'prefix', 'update', **_prefix_scope(fields['prefix_id']))
    try:
        if not update_vip(vip_id, **fields, audit_context=_ipam_audit_context(user)):
            raise HTTPException(status_code=404, detail='VIP not found')
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return {'ok': True}


@router.delete('/ipam/vips/{vip_id}')
def api_delete_vip(
    vip_id: str,
    expected_revision: int = Query(..., ge=1),
    user=require_permission('prefix', 'delete'),
):
    expected_revision = _normalize_expected_revision(expected_revision)
    enforce_resource_scope(user, 'prefix', 'delete', **_vip_scope(vip_id))
    try:
        if not delete_vip(
            vip_id,
            expected_revision=expected_revision,
            audit_context=_ipam_audit_context(user),
        ):
            raise HTTPException(status_code=404, detail='VIP not found')
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return {'ok': True}


# ── DHCP Leases (ipam_dhcp_leases) ────────────

@router.get('/ipam/leases')
def api_list_leases(
    q: str = Query('', description='Search lease address, MAC or hostname'),
    state: str = Query('', description='Filter lease state'),
    page: int | None = Query(None, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=require_role("Viewer"),
):
    allowed_pool_ids = _authorized_ipam_pool_ids(user, 'view')
    pending_tenants = _visible_pending_resource_tenants(user, 'ipam_dhcp_leases')
    return list_leases(
        q=q,
        state=state,
        page=page,
        page_size=page_size,
        allowed_pool_ids=allowed_pool_ids,
        allowed_unscoped_tenant_ids=pending_tenants,
    )


@router.post('/ipam/leases', status_code=201)
def api_create_lease(
    body: DHCPLeaseCreate,
    idempotency_key: str | None = Header(None, alias='Idempotency-Key'),
    user=require_role("Operator"),
):
    tenant_id = tenant_id_for_write(user=user)
    if body.pool_id:
        enforce_resource_scope(user, 'prefix', 'create', **_pool_prefix_scope(body.pool_id))
    else:
        # An unscoped lease has no site to authorize against. Permit its
        # creation only when the caller can create resources at tenant scope.
        enforce_resource_scope(user, 'prefix', 'create', tenant_id=tenant_id)
    try:
        result = create_lease(
            address=body.address,
            mac_address=body.mac_address,
            hostname=body.hostname,
            dhcp_server=body.dhcp_server,
            pool_id=body.pool_id,
            external_id=body.external_id,
            tenant_id=tenant_id,
            lease_state=body.lease_state,
            lease_start=body.lease_start,
            lease_end=body.lease_end,
            idempotency_key=_normalize_idempotency_key(idempotency_key),
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return result


@router.put('/ipam/leases/{lease_id}')
def api_update_lease(lease_id: str, body: DHCPLeaseUpdate, user=require_role("Operator")):
    fields = body.model_dump(exclude_none=True)
    enforce_resource_scope(user, 'prefix', 'update', **_lease_scope(lease_id))
    if str(fields.get('pool_id') or '').strip():
        enforce_resource_scope(user, 'prefix', 'update', **_pool_prefix_scope(fields['pool_id']))
    try:
        if not update_lease(lease_id, **fields, audit_context=_ipam_audit_context(user)):
            raise HTTPException(status_code=404, detail='DHCP Lease not found')
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return {'ok': True}


@router.delete('/ipam/leases/{lease_id}')
def api_delete_lease(
    lease_id: str,
    expected_revision: int = Query(..., ge=1),
    user=require_role("Administrator"),
):
    expected_revision = _normalize_expected_revision(expected_revision)
    enforce_resource_scope(user, 'prefix', 'delete', **_lease_scope(lease_id))
    try:
        if not delete_lease(
            lease_id,
            expected_revision=expected_revision,
            audit_context=_ipam_audit_context(user),
        ):
            raise HTTPException(status_code=404, detail='DHCP Lease not found')
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return {'ok': True}


# ── Conflict, Summary & Tree ──────────────────

@router.get('/ipam/conflicts')
def api_detect_conflicts(_user=require_permission('prefix', 'view')):
    return detect_conflicts(
        _authorized_ipam_prefix_ids(_user, 'view') if isinstance(_user, dict) else None,
    )


@router.get('/ipam/summary')
def api_ipam_summary(_user=require_permission('prefix', 'view')):
    return ipam_summary(
        _authorized_ipam_prefix_ids(_user, 'view') if isinstance(_user, dict) else None,
    )


@router.get('/ipam/subnets/tree')
def api_get_subnets_tree(_user=require_permission('prefix', 'view')):
    return get_subnets_tree(
        _authorized_ipam_prefix_ids(_user, 'view') if isinstance(_user, dict) else None,
    )


@router.get('/ipam/analytics')
def api_get_analytics(
    network_scope: Literal['business', 'all'] = Query(
        'all',
        description='Utilization range: classified business prefixes or all prefixes.',
    ),
    _user=require_permission('prefix', 'view'),
):
    return get_utilization_analytics(
        network_scope=network_scope,
        allowed_prefix_ids=(
            _authorized_ipam_prefix_ids(_user, 'view') if isinstance(_user, dict) else None
        ),
    )


@router.get('/ipam/subnets/{subnet_id}/next-available-ip')
def api_next_available_ip(
    subnet_id: str,
    pool_id: str = Query('', description='Optional static pool that bounds the candidate'),
    _user=require_permission('prefix', 'view'),
):
    # Direct service-style calls in focused tests pass no FastAPI-injected
    # value, leaving the Query descriptor as the Python default.
    normalized_pool_id = pool_id if isinstance(pool_id, str) else ''
    if isinstance(_user, dict):
        subnet_scope = _prefix_scope(subnet_id)
        if not authorize_resource(_user, 'prefix', 'view', **subnet_scope):
            raise HTTPException(status_code=404, detail='Prefix not found')
        _enforce_prefix_address_space_read_scope(_user, subnet_id)
    if normalized_pool_id:
        pool_scope = _pool_prefix_scope(normalized_pool_id)
        if isinstance(_user, dict):
            enforce_resource_scope(_user, 'prefix', 'view', **subnet_scope)
            enforce_resource_scope(_user, 'prefix', 'view', **pool_scope)
    try:
        details = get_next_available_ip_details(subnet_id, pool_id=normalized_pool_id or None)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    ip = details.get('next_available_ip')
    if not ip:
        raise HTTPException(status_code=404, detail="No available IP addresses in this subnet")
    return {
        "subnet_id": subnet_id,
        "next_available_ip": ip,
        "pending_discovery_count": int(details.get('pending_discovery_count') or 0),
    }


@router.get('/ipam/subnets/{subnet_id}/next-available-prefix')
def api_next_available_prefix(
    subnet_id: str,
    prefix_len: int = Query(..., ge=1, le=128),
    _user=require_permission('prefix', 'view'),
):
    if isinstance(_user, dict) and not authorize_resource(
        _user, 'prefix', 'view', **_prefix_scope(subnet_id),
    ):
        raise HTTPException(status_code=404, detail='Prefix not found')
    if isinstance(_user, dict):
        _enforce_prefix_address_space_read_scope(_user, subnet_id)
    prefix = get_next_available_prefix(subnet_id, prefix_len)
    if not prefix:
        raise HTTPException(status_code=404, detail="No available child prefixes found")
    return {"parent_subnet_id": subnet_id, "next_available_prefix": prefix}


@router.get('/ipam/reconciliation')
def api_ipam_reconciliation(
    active_tab: str = Query('', description='Current reconciliation result tab'),
    q: str = Query('', description='Search reconciliation findings'),
    page: int | None = Query(None, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=require_permission('ip_address', 'view'),
):
    return get_ipam_reconciliation(
        active_tab=active_tab, q=q, page=page, page_size=page_size,
        visible_scopes=_ipam_current_visible_scopes(user),
    )


@router.get('/ipam/endpoints')
def api_list_discovered_endpoints(
    site_id: str = Query('', description='Filter by authorized site'),
    vrf_id: str = Query('', description='Filter by evidenced VRF; use __unknown__ for unresolved scope'),
    device_id: str = Query('', description='Filter by a source device'),
    q: str = Query('', description='Search IP, MAC, site, VLAN, device, or port'),
    kind: str = Query('all', pattern='^(ip|mac|all)$'),
    evidence_status: str = Query('', pattern='^(|recent|stale|scope_pending|conflict|unknown)$'),
    registration_status: str = Query('', pattern='^(|registered|unregistered|scope_pending)$'),
    network_scope: str = Query(
        'all', pattern='^(all|business_vlan)$',
        description='Restrict discovered endpoints to active business VLAN prefixes',
    ),
    endpoint_class: str = Query('all', pattern='^(all|terminal|infrastructure|access_host|candidate)$'),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=require_permission('ip_address', 'view'),
):
    visible_scopes = _ipam_current_visible_scopes(user)
    if site_id and visible_scopes is not None and not any(site == site_id for _tenant, site in visible_scopes):
        raise HTTPException(status_code=404, detail='Discovery evidence not found')
    return list_current_discovered_endpoints(
        site_id=site_id, vrf_id=vrf_id, device_id=device_id, q=q,
        kind=kind, evidence_status=evidence_status,
        registration_status=registration_status, network_scope=network_scope,
        endpoint_class=endpoint_class,
        page=page, page_size=page_size,
        visible_scopes=visible_scopes,
    )


@router.get('/ipam/endpoints/{observation_id}')
def api_get_discovered_endpoint(
    observation_id: str,
    user=require_permission('ip_address', 'view'),
):
    visible_scopes = _ipam_current_visible_scopes(user)
    item = get_current_discovered_endpoint(observation_id, visible_scopes=visible_scopes)
    if item is None:
        raise HTTPException(status_code=404, detail='Discovery evidence not found')
    item_scope = (str(item.get('tenant_id') or ''), str(item.get('site_id') or ''))
    if visible_scopes is not None and item_scope not in visible_scopes:
        raise HTTPException(status_code=404, detail='Discovery evidence not found')
    return item


@router.post('/ipam/reconciliation/register')
def api_register_discovered_observation(
    body: IPAMDiscoveryRegistrationRequest,
    user=require_permission('ip_address', 'create'),
):
    values = body.model_dump()
    target_scope = _prefix_scope(values['subnet_id'])
    if TENANT_ISOLATION_ENABLED and tenant_id_for_write(requested=None, user=user) != str(target_scope.get('tenant_id') or DEFAULT_TENANT_ID):
        raise HTTPException(status_code=403, detail='Subnet tenant does not match the authorized tenant')
    enforce_resource_scope(
        user, 'ip_address', 'create',
        tenant_id=target_scope.get('tenant_id'), site_id=target_scope.get('site_id'),
    )
    try:
        result = register_current_endpoint_observation(
            observation_id=values['observation_id'], subnet_id=values['subnet_id'],
            expected_observed_at=values['expected_observed_at'],
            confirmed_scope=values['confirmed_scope'],
            requested_by=str(user.get('username') or ''),
            audit_context=_ipam_audit_context(user),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        status_code = 422 if str(exc) == 'scope_confirmation_required' else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    return result


@router.post('/ipam/reconciliation/calibrate')
def api_calibrate_discovered_mac(
    body: IPAMDiscoveryMACCalibrationRequest,
    user=require_permission('ip_address', 'update'),
):
    values = body.model_dump()
    address_scope = _address_scope(values['ipam_address_id'])
    if TENANT_ISOLATION_ENABLED and tenant_id_for_write(requested=None, user=user) != str(address_scope.get('tenant_id') or DEFAULT_TENANT_ID):
        raise HTTPException(status_code=403, detail='IPAM address tenant does not match the authorized tenant')
    enforce_resource_scope(user, 'ip_address', 'update', **address_scope)
    try:
        result = calibrate_current_endpoint_mac(
            observation_id=values['observation_id'], ipam_address_id=values['ipam_address_id'],
            expected_observed_at=values['expected_observed_at'],
            expected_mac_address=values['expected_mac_address'], confirmed=values['confirmed'],
            audit_context=_ipam_audit_context(user),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        status_code = 422 if str(exc) == 'mac_calibration_confirmation_required' else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    return result


# ── Explicit FHRP and Anycast logical groups ──────────────────────────────

def _fhrp_group_scope_for_api(
    group_id: str,
    user: dict,
    action: str,
    *,
    allow_missing_for_replay: bool = False,
) -> tuple[dict | None, str]:
    scope = get_fhrp_group_scope(group_id)
    if not scope:
        if allow_missing_for_replay:
            return None, tenant_id_for_write(user=user)
        raise HTTPException(status_code=404, detail='FHRP group not found')
    tenant_id = str(scope.get('security_tenant_id') or DEFAULT_TENANT_ID)
    requested_tenant = tenant_scope_for_user(user)
    if requested_tenant is not None and requested_tenant != tenant_id:
        raise HTTPException(status_code=404, detail='FHRP group not found')
    if str(scope.get('_address_space_tenant_id') or '') != tenant_id:
        raise HTTPException(status_code=404, detail='FHRP group not found')
    _enforce_address_space_scope(
        user, str(scope.get('address_space_id') or ''), tenant_id, action,
    )
    return scope, tenant_id


def _fhrp_group_response(group: dict, user: dict) -> dict:
    tenant_id = str(group.get('security_tenant_id') or DEFAULT_TENANT_ID)
    members = []
    for member in group.get('members', []):
        if (
            str(member.get('_member_tenant_id') or '') != tenant_id
            or not authorize_resource(
                user, 'prefix', 'view',
                tenant_id=tenant_id, site_id=member.get('_site_id'),
            )
        ):
            continue
        members.append({
            field: str(member[field]) if field in {'created_at', 'updated_at'} else member[field]
            for field in (
                'id', 'group_id', 'device_id', 'device_name', 'interface_id',
                'interface_name', 'normalized_interface_name', 'role', 'priority',
                'status', 'revision', 'created_at', 'updated_at',
            )
        })

    vips = []
    for vip in group.get('vips', []):
        if (
            str(vip.get('tenant_id') or '') != tenant_id
            or str(vip.get('address_space_id') or '') != str(group.get('address_space_id') or '')
            or not authorize_resource(
                user, 'prefix', 'view',
                tenant_id=tenant_id, site_id=vip.get('_site_id'),
            )
        ):
            continue
        vips.append({
            'vip_id': vip['vip_id'],
            'address': vip['address'],
            'vip_type': vip['vip_type'],
            'status': vip['status'],
            'address_space_id': vip['address_space_id'],
            'tenant_id': vip['tenant_id'],
            'prefix_id': vip['prefix_id'],
            'revision': vip['revision'],
            'linked_at': str(vip['linked_at']),
        })

    return {
        'id': group['id'],
        'security_tenant_id': tenant_id,
        'address_space_id': group['address_space_id'],
        'address_space_name': group['address_space_name'],
        'group_type': group['group_type'],
        'protocol': group['protocol'],
        'group_id': group['group_id'],
        'address_family': int(group['address_family']),
        'display_name': group['display_name'],
        'status': group['status'],
        'revision': int(group['revision']),
        'created_at': str(group['created_at']),
        'updated_at': str(group['updated_at']),
        'members': members,
        'vips': vips,
    }


def _fhrp_group_list_item(group: dict) -> dict:
    return {
        'id': group['id'],
        'security_tenant_id': str(group.get('security_tenant_id') or DEFAULT_TENANT_ID),
        'address_space_id': group['address_space_id'],
        'address_space_name': group['address_space_name'],
        'group_type': group['group_type'],
        'protocol': group['protocol'],
        'group_id': group['group_id'],
        'address_family': int(group['address_family']),
        'display_name': group['display_name'],
        'status': group['status'],
        'revision': int(group['revision']),
        'created_at': str(group['created_at']),
        'updated_at': str(group['updated_at']),
    }


@router.get('/ipam/fhrp/groups', response_model=IPAMFHRPGroupListResponse)
def api_list_fhrp_groups(
    q: str = Query('', max_length=200),
    address_space_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=require_permission('prefix', 'view'),
):
    normalized_space_id = (
        address_space_id.strip()
        if isinstance(address_space_id, str) and address_space_id.strip()
        else None
    )
    query_value = q.strip() if isinstance(q, str) else ''
    page_value = page if isinstance(page, int) and not isinstance(page, bool) else 1
    page_size_value = page_size if isinstance(page_size, int) and not isinstance(page_size, bool) else 20
    tenant_scope = tenant_scope_for_user(user)
    address_spaces = list_address_spaces(
        security_tenant_id=tenant_scope,
        include_inactive=True,
    )
    allowed_address_space_ids = []
    for space in address_spaces:
        space_id = str(space.get('id') or '')
        tenant_id = str(space.get('security_tenant_id') or DEFAULT_TENANT_ID)
        if (
            normalized_space_id and normalized_space_id != space_id
        ) or not _address_space_scope_allowed(
            user, space_id, tenant_id, 'view',
        ):
            continue
        allowed_address_space_ids.append(space_id)

    page_result = list_fhrp_groups(
        security_tenant_id=tenant_scope,
        address_space_id=normalized_space_id,
        allowed_address_space_ids=allowed_address_space_ids,
        q=query_value,
        page=page_value,
        page_size=page_size_value,
    )
    return {
        'items': [_fhrp_group_list_item(group) for group in page_result['items']],
        'total': page_result['total'],
        'page': page_result['page'],
        'page_size': page_result['page_size'],
        'total_pages': page_result['total_pages'],
    }


@router.get('/ipam/fhrp/groups/{group_id}', response_model=IPAMFHRPGroupResponse)
def api_get_fhrp_group(
    group_id: str,
    user=require_permission('prefix', 'view'),
):
    _fhrp_group_scope_for_api(group_id, user, 'view')
    group = get_fhrp_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail='FHRP group not found')
    return _fhrp_group_response(group, user)


@router.post('/ipam/fhrp/groups', status_code=201, response_model=IPAMFHRPGroupResponse)
def api_create_fhrp_group(
    body: IPAMFHRPGroupCreate,
    idempotency_key: str | None = Header(None, alias='Idempotency-Key'),
    user=require_permission('prefix', 'create'),
):
    security_tenant_id = tenant_id_for_write(user=user)
    _enforce_address_space_scope(
        user, body.address_space_id, security_tenant_id, 'create',
    )
    try:
        result = create_fhrp_group(
            address_space_id=body.address_space_id,
            security_tenant_id=security_tenant_id,
            group_type=body.group_type,
            protocol=body.protocol,
            group_id=body.group_id,
            address_family=body.address_family,
            display_name=body.display_name,
            status=body.status,
            idempotency_key=_normalize_idempotency_key(idempotency_key),
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _fhrp_group_response(result, user)


@router.put('/ipam/fhrp/groups/{group_id}', response_model=IPAMFHRPGroupResponse)
def api_update_fhrp_group(
    group_id: str,
    body: IPAMFHRPGroupUpdate,
    idempotency_key: str | None = Header(None, alias='Idempotency-Key'),
    user=require_permission('prefix', 'update'),
):
    scope, security_tenant_id = _fhrp_group_scope_for_api(
        group_id, user, 'update', allow_missing_for_replay=True,
    )
    fields = body.model_dump(exclude={'expected_revision'}, exclude_unset=True, exclude_none=True)
    try:
        result = update_fhrp_group(
            group_id,
            security_tenant_id=security_tenant_id,
            expected_revision=body.expected_revision,
            idempotency_key=_normalize_idempotency_key(idempotency_key),
            audit_context=_ipam_audit_context(user),
            **fields,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail='FHRP group not found')
    return _fhrp_group_response(result, user)


@router.delete('/ipam/fhrp/groups/{group_id}')
def api_delete_fhrp_group(
    group_id: str,
    expected_revision: int = Query(..., ge=1),
    idempotency_key: str | None = Header(None, alias='Idempotency-Key'),
    user=require_permission('prefix', 'delete'),
):
    expected_revision = _normalize_expected_revision(expected_revision)
    _scope, security_tenant_id = _fhrp_group_scope_for_api(
        group_id, user, 'delete', allow_missing_for_replay=True,
    )
    try:
        result = delete_fhrp_group(
            group_id,
            security_tenant_id=security_tenant_id,
            expected_revision=expected_revision,
            idempotency_key=_normalize_idempotency_key(idempotency_key),
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail='FHRP group not found')
    return result


@router.post('/ipam/fhrp/groups/{group_id}/members', status_code=201)
def api_add_fhrp_group_member(
    group_id: str,
    body: IPAMFHRPGroupMemberAdd,
    idempotency_key: str | None = Header(None, alias='Idempotency-Key'),
    user=require_permission('prefix', 'create'),
):
    _scope, security_tenant_id = _fhrp_group_scope_for_api(group_id, user, 'create')
    device_scope = get_fhrp_device_scope(body.device_id)
    if not device_scope or str(device_scope['tenant_id'] or '') != security_tenant_id:
        raise HTTPException(status_code=404, detail='Device not found in this security tenant')
    enforce_resource_scope(
        user, 'prefix', 'create',
        tenant_id=security_tenant_id, site_id=device_scope.get('site_id'),
    )
    try:
        result = add_fhrp_group_member(
            group_id,
            security_tenant_id=security_tenant_id,
            expected_revision=body.expected_revision,
            device_id=body.device_id,
            interface_name=body.interface_name,
            interface_id=body.interface_id,
            role=body.role,
            priority=body.priority,
            status=body.status,
            idempotency_key=_normalize_idempotency_key(idempotency_key),
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail='FHRP group not found')
    return result


@router.delete('/ipam/fhrp/groups/{group_id}/members/{member_id}')
def api_remove_fhrp_group_member(
    group_id: str,
    member_id: str,
    expected_revision: int = Query(..., ge=1),
    idempotency_key: str | None = Header(None, alias='Idempotency-Key'),
    user=require_permission('prefix', 'delete'),
):
    expected_revision = _normalize_expected_revision(expected_revision)
    _scope, security_tenant_id = _fhrp_group_scope_for_api(group_id, user, 'delete')
    member_scope = get_fhrp_member_scope(member_id)
    if member_scope:
        if (
            str(member_scope.get('group_id') or '') != group_id
            or str(member_scope.get('security_tenant_id') or '') != security_tenant_id
            or str(member_scope.get('device_tenant_id') or '') != security_tenant_id
        ):
            raise HTTPException(status_code=404, detail='FHRP member not found')
        enforce_resource_scope(
            user, 'prefix', 'delete',
            tenant_id=security_tenant_id, site_id=member_scope.get('site_id'),
        )
    try:
        result = remove_fhrp_group_member(
            group_id,
            member_id,
            security_tenant_id=security_tenant_id,
            expected_revision=expected_revision,
            idempotency_key=_normalize_idempotency_key(idempotency_key),
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail='FHRP member not found')
    return result


@router.post('/ipam/fhrp/groups/{group_id}/vips', status_code=201)
def api_attach_fhrp_group_vip(
    group_id: str,
    body: IPAMFHRPVIPAttach,
    idempotency_key: str | None = Header(None, alias='Idempotency-Key'),
    user=require_permission('prefix', 'create'),
):
    scope, security_tenant_id = _fhrp_group_scope_for_api(group_id, user, 'create')
    vip_scope = get_fhrp_vip_scope(body.vip_id)
    if not vip_scope or str(vip_scope.get('tenant_id') or '') != security_tenant_id:
        raise HTTPException(status_code=404, detail='VIP not found in this security tenant')
    if str(vip_scope.get('address_space_id') or '') != str(scope['address_space_id']):
        raise HTTPException(status_code=409, detail='VIP and FHRP group must use the same address space')
    _enforce_address_space_scope(
        user, str(vip_scope['address_space_id']), security_tenant_id, 'create',
    )
    enforce_resource_scope(
        user, 'prefix', 'create',
        tenant_id=security_tenant_id, site_id=vip_scope.get('site_id'),
    )
    try:
        result = attach_fhrp_group_vip(
            group_id,
            security_tenant_id=security_tenant_id,
            expected_revision=body.expected_revision,
            vip_id=body.vip_id,
            idempotency_key=_normalize_idempotency_key(idempotency_key),
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail='FHRP group not found')
    return result


@router.delete('/ipam/fhrp/groups/{group_id}/vips/{vip_id}')
def api_detach_fhrp_group_vip(
    group_id: str,
    vip_id: str,
    expected_revision: int = Query(..., ge=1),
    idempotency_key: str | None = Header(None, alias='Idempotency-Key'),
    user=require_permission('prefix', 'delete'),
):
    expected_revision = _normalize_expected_revision(expected_revision)
    scope, security_tenant_id = _fhrp_group_scope_for_api(group_id, user, 'delete')
    vip_scope = get_fhrp_vip_scope(vip_id)
    if not vip_scope or str(vip_scope.get('tenant_id') or '') != security_tenant_id:
        raise HTTPException(status_code=404, detail='VIP not found in this security tenant')
    if str(vip_scope.get('address_space_id') or '') != str(scope['address_space_id']):
        raise HTTPException(status_code=404, detail='VIP relationship not found')
    _enforce_address_space_scope(
        user, str(vip_scope['address_space_id']), security_tenant_id, 'delete',
    )
    enforce_resource_scope(
        user, 'prefix', 'delete',
        tenant_id=security_tenant_id, site_id=vip_scope.get('site_id'),
    )
    try:
        result = detach_fhrp_group_vip(
            group_id,
            vip_id,
            security_tenant_id=security_tenant_id,
            expected_revision=expected_revision,
            idempotency_key=_normalize_idempotency_key(idempotency_key),
            audit_context=_ipam_audit_context(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail='FHRP VIP relationship not found')
    return result


@router.get('/ipam/fhrp/groups/{group_id}/current')
def api_list_current_fhrp_group_observations(
    group_id: str,
    user=require_permission('prefix', 'view'),
):
    """Return current-only HSRP/VRRP state for this group's visible members."""
    _fhrp_group_scope_for_api(group_id, user, 'view')
    group = get_fhrp_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail='FHRP group not found')
    visible_group = _fhrp_group_response(group, user)
    visible_members = visible_group['members']
    device_names = {
        str(member['device_id']): str(member.get('device_name') or member['device_id'])
        for member in visible_members
    }
    device_ids = sorted(device_names)
    protocol = str(group.get('protocol') or '').strip().lower()
    if not device_ids or protocol not in {'hsrp', 'vrrp'}:
        return {'items': [], 'collection_states': []}

    member_identities = {
        (
            str(member['device_id']),
            str(member.get('normalized_interface_name') or '').strip().casefold(),
        )
        for member in visible_members
    }
    conn = get_db_connection()
    try:
        projected = list_current_fhrp_observation_projection(
            conn,
            device_ids=device_ids,
            protocol=protocol,
        )
        raw_states = get_current_fhrp_collection_states(
            conn,
            device_ids=device_ids,
            protocol=protocol,
        )
    finally:
        conn.close()

    items = []
    for observation in projected:
        identity = (
            str(observation.get('source_device_id') or ''),
            str(observation.get('normalized_interface_name') or '').strip().casefold(),
        )
        if (
            identity not in member_identities
            or str(observation.get('protocol') or '').lower() != protocol
            or str(observation.get('group_id') or '') != str(group.get('group_id') or '')
            or int(observation.get('address_family') or 0) != int(group.get('address_family') or 0)
        ):
            continue
        tenant_id = str(observation.get('tenant_id') or DEFAULT_TENANT_ID)
        site_id = str(observation.get('site_id') or '') or None
        if not authorize_resource(
            user, 'prefix', 'view', tenant_id=tenant_id, site_id=site_id,
        ):
            continue
        current_space = str(observation.get('address_space_id') or '')
        scope_status = str(observation.get('scope_status') or 'scope_pending')
        group_scope_status = (
            'scope_pending'
            if scope_status != 'resolved'
            else 'resolved'
            if current_space == str(group.get('address_space_id') or '')
            else 'scope_mismatch'
        )
        item = {**observation, 'group_scope_status': group_scope_status}
        if (
            group_scope_status == 'scope_mismatch'
            and not _address_space_scope_allowed(user, current_space, tenant_id, 'view')
        ):
            item['address_space_id'] = ''
            item['address_space_name'] = ''
            item['vrf_id'] = ''
            item['vrf_name'] = ''
        items.append(item)

    collection_states = []
    for state in raw_states:
        device_id = str(state.get('device_id') or '')
        if device_id not in device_names:
            continue
        collection_states.append({
            'device_id': device_id,
            'device_name': device_names[device_id],
            'protocol': protocol,
            'latest_attempt_generation': int(state.get('latest_attempt_generation') or 0),
            'latest_status': str(state.get('latest_status') or ''),
            'last_attempt_at': str(state.get('last_attempt_at') or ''),
            'last_completed_at': str(state.get('last_completed_at') or ''),
            'last_success_generation': int(state.get('last_success_generation') or 0),
            'last_success_at': str(state.get('last_success_at') or ''),
            'current_row_count': int(state.get('current_row_count') or 0),
            'last_error_code': str(state.get('last_error_code') or ''),
        })
    return {'items': items, 'collection_states': collection_states}


# ── NetBox-Aligned Native IPAM Objects (VLAN Groups, Route Targets, RIR/Aggregate/ASN) ──

class VLANGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    scope_type: str = Field(default='', max_length=32)
    scope_id: str = Field(default='', max_length=128)
    min_vid: int = Field(default=1, ge=1, le=4094)
    max_vid: int = Field(default=4094, ge=1, le=4094)
    description: str = Field(default='', max_length=500)


class RouteTargetCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=64)
    description: str = Field(default='', max_length=500)


class VRFRouteTargetsUpdate(BaseModel):
    import_target_ids: list[str] = Field(default_factory=list)
    export_target_ids: list[str] = Field(default_factory=list)


class RIRCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    is_private: bool = False
    description: str = Field(default='', max_length=500)


class AggregateCreate(BaseModel):
    prefix: str = Field(..., min_length=3, max_length=64)
    rir_id: str = Field(..., min_length=1, max_length=128)
    date_added: str = Field(default='', max_length=32)
    description: str = Field(default='', max_length=500)


class ASNCreate(BaseModel):
    asn: int = Field(..., ge=1, le=4294967295)
    rir_id: str = Field(..., min_length=1, max_length=128)
    site_id: str | None = None
    description: str = Field(default='', max_length=500)


@router.get('/ipam/vlan-groups')
def api_list_vlan_groups(
    scope_id: str = Query(default=''),
    user=require_permission('prefix', 'view'),
):
    from services.ipam_native_models_service import list_vlan_groups
    return {'items': list_vlan_groups(tenant_id=tenant_scope_for_user(user), scope_id=scope_id)}


@router.post('/ipam/vlan-groups', status_code=201)
def api_create_vlan_group(
    body: VLANGroupCreate,
    user=require_permission('prefix', 'create'),
):
    from services.ipam_native_models_service import create_vlan_group
    tenant_id = tenant_id_for_write(user=user)
    if body.scope_type == 'site' and body.scope_id:
        enforce_resource_scope(user, 'prefix', 'create', tenant_id=tenant_id, site_id=body.scope_id)
    try:
        return create_vlan_group(
            name=body.name,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            min_vid=body.min_vid,
            max_vid=body.max_vid,
            description=body.description,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/ipam/vlan-groups/{group_id}/vlans/{vlan_pk}')
def api_assign_vlan_to_group(
    group_id: str,
    vlan_pk: str,
    user=require_permission('prefix', 'update'),
):
    from services.ipam_native_models_service import assign_vlan_to_group
    tenant_id = tenant_id_for_write(user=user)
    try:
        return assign_vlan_to_group(vlan_pk, group_id, tenant_id=tenant_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete('/ipam/vlan-groups/{group_id}')
def api_delete_vlan_group(
    group_id: str,
    user=require_permission('prefix', 'delete'),
):
    from services.ipam_native_models_service import delete_vlan_group
    if not delete_vlan_group(group_id, tenant_id=tenant_id_for_write(user=user)):
        raise HTTPException(status_code=404, detail='VLAN Group not found')
    return {'ok': True}


@router.get('/ipam/route-targets')
def api_list_route_targets(user=require_permission('prefix', 'view')):
    from services.ipam_native_models_service import list_route_targets
    return {'items': list_route_targets(tenant_id=tenant_scope_for_user(user))}


@router.post('/ipam/route-targets', status_code=201)
def api_create_route_target(
    body: RouteTargetCreate,
    user=require_permission('prefix', 'create'),
):
    from services.ipam_native_models_service import create_route_target
    try:
        return create_route_target(
            name=body.name,
            description=body.description,
            tenant_id=tenant_id_for_write(user=user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete('/ipam/route-targets/{rt_id}')
def api_delete_route_target(
    rt_id: str,
    user=require_permission('prefix', 'delete'),
):
    from services.ipam_native_models_service import delete_route_target
    if not delete_route_target(rt_id, tenant_id=tenant_id_for_write(user=user)):
        raise HTTPException(status_code=404, detail='Route Target not found')
    return {'ok': True}


@router.get('/ipam/vrfs/{vrf_id}/route-targets')
def api_get_vrf_route_targets(
    vrf_id: str,
    user=require_permission('prefix', 'view'),
):
    from services.ipam_native_models_service import get_vrf_route_targets
    try:
        return get_vrf_route_targets(vrf_id, tenant_id=tenant_scope_for_user(user))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put('/ipam/vrfs/{vrf_id}/route-targets')
def api_set_vrf_route_targets(
    vrf_id: str,
    body: VRFRouteTargetsUpdate,
    user=require_permission('prefix', 'update'),
):
    from services.ipam_native_models_service import set_vrf_route_targets
    try:
        return set_vrf_route_targets(
            vrf_id,
            import_target_ids=body.import_target_ids,
            export_target_ids=body.export_target_ids,
            tenant_id=tenant_id_for_write(user=user),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get('/ipam/rirs')
def api_list_rirs(user=require_permission('prefix', 'view')):
    from services.ipam_native_models_service import list_rirs
    return {'items': list_rirs(tenant_id=tenant_scope_for_user(user))}


@router.post('/ipam/rirs', status_code=201)
def api_create_rir(
    body: RIRCreate,
    user=require_permission('prefix', 'create'),
):
    from services.ipam_native_models_service import create_rir
    try:
        return create_rir(
            name=body.name,
            is_private=body.is_private,
            description=body.description,
            tenant_id=tenant_id_for_write(user=user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete('/ipam/rirs/{rir_id}')
def api_delete_rir(
    rir_id: str,
    user=require_permission('prefix', 'delete'),
):
    from services.ipam_native_models_service import delete_rir
    try:
        if not delete_rir(rir_id, tenant_id=tenant_id_for_write(user=user)):
            raise HTTPException(status_code=404, detail='RIR not found')
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {'ok': True}


@router.get('/ipam/aggregates')
def api_list_aggregates(
    rir_id: str = Query(default=''),
    user=require_permission('prefix', 'view'),
):
    from services.ipam_native_models_service import list_aggregates
    return {'items': list_aggregates(tenant_id=tenant_scope_for_user(user), rir_id=rir_id)}


@router.post('/ipam/aggregates', status_code=201)
def api_create_aggregate(
    body: AggregateCreate,
    user=require_permission('prefix', 'create'),
):
    from services.ipam_native_models_service import create_aggregate
    try:
        return create_aggregate(
            prefix=body.prefix,
            rir_id=body.rir_id,
            date_added=body.date_added,
            description=body.description,
            tenant_id=tenant_id_for_write(user=user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete('/ipam/aggregates/{aggregate_id}')
def api_delete_aggregate(
    aggregate_id: str,
    user=require_permission('prefix', 'delete'),
):
    from services.ipam_native_models_service import delete_aggregate
    if not delete_aggregate(aggregate_id, tenant_id=tenant_id_for_write(user=user)):
        raise HTTPException(status_code=404, detail='Aggregate not found')
    return {'ok': True}


@router.get('/ipam/asns')
def api_list_asns(
    rir_id: str = Query(default=''),
    user=require_permission('prefix', 'view'),
):
    from services.ipam_native_models_service import list_asns
    return {'items': list_asns(tenant_id=tenant_scope_for_user(user), rir_id=rir_id)}


@router.post('/ipam/asns', status_code=201)
def api_create_asn(
    body: ASNCreate,
    user=require_permission('prefix', 'create'),
):
    from services.ipam_native_models_service import create_asn
    tenant_id = tenant_id_for_write(user=user)
    if body.site_id:
        enforce_resource_scope(user, 'prefix', 'create', tenant_id=tenant_id, site_id=body.site_id)
    try:
        return create_asn(
            asn=body.asn,
            rir_id=body.rir_id,
            site_id=body.site_id,
            description=body.description,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete('/ipam/asns/{asn_id}')
def api_delete_asn(
    asn_id: str,
    user=require_permission('prefix', 'delete'),
):
    from services.ipam_native_models_service import delete_asn
    if not delete_asn(asn_id, tenant_id=tenant_id_for_write(user=user)):
        raise HTTPException(status_code=404, detail='ASN not found')
    return {'ok': True}


class IPAMEventIngestRequest(BaseModel):
    event_type: str = ''
    raw_message: str = ''
    device_id: str = ''
    device_ip: str = ''
    hostname: str = ''


@router.post('/ipam/events/ingest')
def api_ingest_ipam_network_event(
    body: IPAMEventIngestRequest,
    user=require_role('Operator'),
):
    """Ingest a debounced Syslog/SNMP Trap change event for incremental IPAM/Topology refresh."""
    del user
    from services.ipam_event_refresh_service import ingest_network_change_event

    return ingest_network_change_event(
        event_type=body.event_type,
        raw_message=body.raw_message,
        device_id=body.device_id,
        device_ip=body.device_ip,
        hostname=body.hostname,
    )
