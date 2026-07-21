"""
IPAM API — IP/VLAN resource management endpoints.
All write operations require Operator+; delete requires Administrator.
"""

import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from core.rbac import enforce_resource_scope, require_permission, require_role
from database import get_db_connection
from schemas.schemas import (
    PrefixCreate, PrefixUpdate,
    IPAddressCreate, IPAddressUpdate,
    IPPoolCreate, IPPoolUpdate,
    VIPCreate, VIPUpdate,
    DHCPLeaseCreate, DHCPLeaseUpdate
)
from services.ipam_service import (
    list_subnets,
    create_subnet,
    update_subnet,
    delete_subnet,
    list_addresses,
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
    get_next_available_ip,
    get_next_available_prefix,
    get_ipam_reconciliation,
    allocate_next_address,
    reserve_address,
    release_address,
)
from services.audit_service import log_audit_event

logger = logging.getLogger(__name__)

router = APIRouter()


class AllocationRequest(BaseModel):
    hostname: str = ''
    device_id: str = ''
    interface_id: str = ''
    interface_name: str = ''
    mac_address: str = ''
    purpose: str = ''
    requested_by: str = ''
    expires_at: str = ''
    status: str = 'allocated'


class ReservationRequest(AllocationRequest):
    address: str


class ReleaseRequest(BaseModel):
    released_by: str = ''


def _prefix_scope(subnet_id: str) -> dict:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT tenant_id, site_id FROM prefixes WHERE id = ?", (subnet_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Prefix not found')
        return {'tenant_id': row['tenant_id'], 'site_id': row['site_id']}
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


# ── Prefixes (Subnets) ──────────────────────────

@router.get('/ipam/subnets')
def api_list_subnets(
    site: str = 'all',
    status: str = 'all',
    q: str = '',
    _user=require_role("Viewer"),
):
    return list_subnets(site=site, status=status, q=q)


@router.post('/ipam/subnets', status_code=201)
def api_create_subnet(body: PrefixCreate, user=require_permission('prefix', 'create')):
    enforce_resource_scope(user, 'prefix', 'create', tenant_id=body.tenant_id, site_id=body.site_id)
    try:
        result = create_subnet(
            prefix=body.prefix,
            vrf_id=body.vrf_id,
            vlan_id=body.vlan_id,
            site_id=body.site_id,
            tenant_id=body.tenant_id,
            status=body.status,
            name=body.name,
            gateway=body.gateway,
            description=body.description,
            network_type=body.network_type,
            gateway_device_id=body.gateway_device_id,
            gateway_interface_id=body.gateway_interface_id,
            traceable=body.traceable,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    log_audit_event(
        event_type="ipam.prefix.create",
        category="ipam",
        severity="info",
        status="success",
        summary=f"Created prefix {body.prefix}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="prefix",
        target_id=result["id"],
        target_name=body.name or body.prefix,
    )
    return result


@router.put('/ipam/subnets/{subnet_id}')
def api_update_subnet(subnet_id: str, body: PrefixUpdate, user=require_permission('prefix', 'update')):
    enforce_resource_scope(user, 'prefix', 'update', **_prefix_scope(subnet_id))
    fields = body.model_dump(exclude_none=True)
    if not update_subnet(subnet_id, **fields):
        raise HTTPException(status_code=404, detail='Prefix not found')

    log_audit_event(
        event_type="ipam.prefix.update",
        category="ipam",
        severity="info",
        status="success",
        summary=f"Updated prefix {subnet_id}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="prefix",
        target_id=subnet_id,
        details=fields,
    )
    return {'ok': True}


@router.delete('/ipam/subnets/{subnet_id}')
def api_delete_subnet(subnet_id: str, user=require_permission('prefix', 'delete')):
    enforce_resource_scope(user, 'prefix', 'delete', **_prefix_scope(subnet_id))
    if not delete_subnet(subnet_id):
        raise HTTPException(status_code=404, detail='Prefix not found')

    log_audit_event(
        event_type="ipam.prefix.delete",
        category="ipam",
        severity="warning",
        status="success",
        summary=f"Deleted prefix {subnet_id}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="prefix",
        target_id=subnet_id,
    )
    return {'ok': True}


@router.post('/ipam/subnets/batch-delete')
def api_batch_delete_subnets(body: dict, user=require_permission('prefix', 'delete')):
    ids = body.get("ids", [])
    if not ids or not isinstance(ids, list):
        raise HTTPException(status_code=422, detail="ids must be a non-empty list")
    deleted = 0
    failed = 0
    for sid in ids:
        enforce_resource_scope(user, 'prefix', 'delete', **_prefix_scope(str(sid)))
        if delete_subnet(str(sid)):
            deleted += 1
            log_audit_event(
                event_type="ipam.prefix.delete",
                category="ipam",
                severity="warning",
                status="success",
                summary=f"Batch deleted prefix {sid}",
                actor_username=user.get("username"),
                actor_role=user.get("role"),
                target_type="prefix",
                target_id=str(sid),
            )
        else:
            failed += 1
    return {'ok': True, 'deleted': deleted, 'failed': failed}


# ── IP Addresses ──────────────────────────────

@router.get('/ipam/subnets/{subnet_id}/addresses')
def api_list_addresses(subnet_id: str, _user=require_role("Viewer")):
    return list_addresses(subnet_id)


@router.post('/ipam/subnets/{subnet_id}/addresses', status_code=201)
def api_create_address(subnet_id: str, body: IPAddressCreate, user=require_permission('ip_address', 'create')):
    enforce_resource_scope(user, 'ip_address', 'create', **_prefix_scope(subnet_id))
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
            description=body.description,
            status=body.status,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    log_audit_event(
        event_type="ipam.address.create",
        category="ipam",
        severity="info",
        status="success",
        summary=f"Added IP {body.address} to prefix {subnet_id}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ip_address",
        target_id=result["id"],
        target_name=body.address,
    )
    return result


@router.post('/ipam/subnets/{subnet_id}/allocate-next', status_code=201)
def api_allocate_next_address(subnet_id: str, body: AllocationRequest, user=require_permission('ip_address', 'allocate')):
    enforce_resource_scope(user, 'ip_address', 'allocate', **_prefix_scope(subnet_id))
    values = body.model_dump()
    try:
        result = allocate_next_address(
            subnet_id,
            hostname=values['hostname'], device_id=values['device_id'],
            interface_id=values['interface_id'], interface_name=values['interface_name'],
            mac_address=values['mac_address'], purpose=values['purpose'],
            requested_by=values['requested_by'] or user.get('username', ''),
            status=values['status'], expires_at=values['expires_at'],
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    log_audit_event(
        event_type="ipam.address.allocate",
        category="ipam",
        severity="info",
        status="success",
        summary=f"Allocated next IP {result.get('address')} from prefix {subnet_id}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ip_address",
        target_id=result["id"],
        target_name=result.get("address"),
        details={'subnet_id': subnet_id, **values},
    )
    return result


@router.post('/ipam/subnets/{subnet_id}/reserve', status_code=201)
def api_reserve_address(subnet_id: str, body: ReservationRequest, user=require_permission('ip_address', 'reserve')):
    enforce_resource_scope(user, 'ip_address', 'reserve', **_prefix_scope(subnet_id))
    values = body.model_dump()
    try:
        result = reserve_address(
            subnet_id,
            address=values['address'], hostname=values['hostname'],
            device_id=values['device_id'], interface_id=values['interface_id'],
            interface_name=values['interface_name'], mac_address=values['mac_address'],
            purpose=values['purpose'], requested_by=values['requested_by'] or user.get('username', ''),
            expires_at=values['expires_at'],
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    log_audit_event(
        event_type="ipam.address.reserve",
        category="ipam",
        severity="info",
        status="success",
        summary=f"Reserved IP {result.get('address')} in prefix {subnet_id}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ip_address",
        target_id=result["id"],
        target_name=result.get("address"),
        details={'subnet_id': subnet_id, **values},
    )
    return result


@router.put('/ipam/addresses/{address_id}')
def api_update_address(address_id: str, body: IPAddressUpdate, user=require_permission('ip_address', 'update')):
    enforce_resource_scope(user, 'ip_address', 'update', **_address_scope(address_id))
    fields = body.model_dump(exclude_none=True)
    try:
        if not update_address(address_id, **fields):
            raise HTTPException(status_code=404, detail='Address not found')
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    log_audit_event(
        event_type="ipam.address.update",
        category="ipam",
        severity="info",
        status="success",
        summary=f"Updated address {address_id}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ip_address",
        target_id=address_id,
        details=fields,
    )
    return {'ok': True}


@router.delete('/ipam/addresses/{address_id}')
def api_delete_address(address_id: str, user=require_permission('ip_address', 'delete')):
    enforce_resource_scope(user, 'ip_address', 'delete', **_address_scope(address_id))
    if not delete_address(address_id):
        raise HTTPException(status_code=404, detail='Address not found')

    log_audit_event(
        event_type="ipam.address.delete",
        category="ipam",
        severity="warning",
        status="success",
        summary=f"Deleted address {address_id}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ip_address",
        target_id=address_id,
    )
    return {'ok': True}


@router.post('/ipam/addresses/{address_id}/release')
def api_release_address(address_id: str, body: ReleaseRequest | None = None, user=require_permission('ip_address', 'release')):
    enforce_resource_scope(user, 'ip_address', 'release', **_address_scope(address_id))
    values = body.model_dump() if body else {}
    if not release_address(address_id, released_by=values.get('released_by') or user.get('username', '')):
        raise HTTPException(status_code=404, detail='Address not found')

    log_audit_event(
        event_type="ipam.address.release",
        category="ipam",
        severity="info",
        status="success",
        summary=f"Released address {address_id}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ip_address",
        target_id=address_id,
        details=values,
    )
    return {'ok': True}


# ── Dynamic Pools (ipam_pools) ─────────────────

@router.get('/ipam/pools')
def api_list_pools(_user=require_role("Viewer")):
    return list_pools()


@router.post('/ipam/pools', status_code=201)
def api_create_pool(body: IPPoolCreate, user=require_role("Operator")):
    try:
        result = create_pool(
            name=body.name,
            prefix_id=body.prefix_id,
            start_ip=body.start_ip,
            end_ip=body.end_ip,
            description=body.description,
            status=body.status,
            tenant_id=body.tenant_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    log_audit_event(
        event_type="ipam.pool.create",
        category="ipam",
        severity="info",
        status="success",
        summary=f"Created IP Pool {body.name}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ipam_pool",
        target_id=result["id"],
        target_name=body.name,
    )
    return result


@router.put('/ipam/pools/{pool_id}')
def api_update_pool(pool_id: str, body: IPPoolUpdate, user=require_role("Operator")):
    fields = body.model_dump(exclude_none=True)
    if not update_pool(pool_id, **fields):
        raise HTTPException(status_code=404, detail='IP Pool not found')

    log_audit_event(
        event_type="ipam.pool.update",
        category="ipam",
        severity="info",
        status="success",
        summary=f"Updated IP Pool {pool_id}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ipam_pool",
        target_id=pool_id,
        details=fields,
    )
    return {'ok': True}


@router.delete('/ipam/pools/{pool_id}')
def api_delete_pool(pool_id: str, user=require_role("Administrator")):
    if not delete_pool(pool_id):
        raise HTTPException(status_code=404, detail='IP Pool not found')

    log_audit_event(
        event_type="ipam.pool.delete",
        category="ipam",
        severity="warning",
        status="success",
        summary=f"Deleted IP Pool {pool_id}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ipam_pool",
        target_id=pool_id,
    )
    return {'ok': True}


# ── Virtual IPs (ipam_vips) ───────────────────

@router.get('/ipam/vips')
def api_list_vips(_user=require_role("Viewer")):
    return list_vips()


@router.post('/ipam/vips', status_code=201)
def api_create_vip(body: VIPCreate, user=require_role("Operator")):
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
            tenant_id=body.tenant_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    log_audit_event(
        event_type="ipam.vip.create",
        category="ipam",
        severity="info",
        status="success",
        summary=f"Created VIP {body.address}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ipam_vip",
        target_id=result["id"],
        target_name=body.address,
    )
    return result


@router.put('/ipam/vips/{vip_id}')
def api_update_vip(vip_id: str, body: VIPUpdate, user=require_role("Operator")):
    fields = body.model_dump(exclude_none=True)
    if not update_vip(vip_id, **fields):
        raise HTTPException(status_code=404, detail='VIP not found')

    log_audit_event(
        event_type="ipam.vip.update",
        category="ipam",
        severity="info",
        status="success",
        summary=f"Updated VIP {vip_id}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ipam_vip",
        target_id=vip_id,
        details=fields,
    )
    return {'ok': True}


@router.delete('/ipam/vips/{vip_id}')
def api_delete_vip(vip_id: str, user=require_role("Administrator")):
    if not delete_vip(vip_id):
        raise HTTPException(status_code=404, detail='VIP not found')

    log_audit_event(
        event_type="ipam.vip.delete",
        category="ipam",
        severity="warning",
        status="success",
        summary=f"Deleted VIP {vip_id}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ipam_vip",
        target_id=vip_id,
    )
    return {'ok': True}


# ── DHCP Leases (ipam_dhcp_leases) ────────────

@router.get('/ipam/leases')
def api_list_leases(_user=require_role("Viewer")):
    return list_leases()


@router.post('/ipam/leases', status_code=201)
def api_create_lease(body: DHCPLeaseCreate, user=require_role("Operator")):
    try:
        result = create_lease(
            address=body.address,
            mac_address=body.mac_address,
            hostname=body.hostname,
            dhcp_server=body.dhcp_server,
            lease_state=body.lease_state,
            lease_start=body.lease_start,
            lease_end=body.lease_end,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    log_audit_event(
        event_type="ipam.lease.create",
        category="ipam",
        severity="info",
        status="success",
        summary=f"Created DHCP Lease {body.address}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ipam_lease",
        target_id=result["id"],
        target_name=body.address,
    )
    return result


@router.put('/ipam/leases/{lease_id}')
def api_update_lease(lease_id: str, body: DHCPLeaseUpdate, user=require_role("Operator")):
    fields = body.model_dump(exclude_none=True)
    if not update_lease(lease_id, **fields):
        raise HTTPException(status_code=404, detail='DHCP Lease not found')

    log_audit_event(
        event_type="ipam.lease.update",
        category="ipam",
        severity="info",
        status="success",
        summary=f"Updated DHCP Lease {lease_id}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ipam_lease",
        target_id=lease_id,
        details=fields,
    )
    return {'ok': True}


@router.delete('/ipam/leases/{lease_id}')
def api_delete_lease(lease_id: str, user=require_role("Administrator")):
    if not delete_lease(lease_id):
        raise HTTPException(status_code=404, detail='DHCP Lease not found')

    log_audit_event(
        event_type="ipam.lease.delete",
        category="ipam",
        severity="warning",
        status="success",
        summary=f"Deleted DHCP Lease {lease_id}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ipam_lease",
        target_id=lease_id,
    )
    return {'ok': True}


# ── Conflict, Summary & Tree ──────────────────

@router.get('/ipam/conflicts')
def api_detect_conflicts(_user=require_role("Viewer")):
    return detect_conflicts()


@router.get('/ipam/summary')
def api_ipam_summary(_user=require_role("Viewer")):
    return ipam_summary()


@router.get('/ipam/subnets/tree')
def api_get_subnets_tree(_user=require_role("Viewer")):
    return get_subnets_tree()


@router.get('/ipam/analytics')
def api_get_analytics(_user=require_role("Viewer")):
    return get_utilization_analytics()


@router.get('/ipam/subnets/{subnet_id}/next-available-ip')
def api_next_available_ip(subnet_id: str, _user=require_role("Viewer")):
    ip = get_next_available_ip(subnet_id)
    if not ip:
        raise HTTPException(status_code=404, detail="No available IP addresses in this subnet")
    return {"subnet_id": subnet_id, "next_available_ip": ip}


@router.get('/ipam/subnets/{subnet_id}/next-available-prefix')
def api_next_available_prefix(subnet_id: str, prefix_len: int = Query(..., ge=1, le=128), _user=require_role("Viewer")):
    prefix = get_next_available_prefix(subnet_id, prefix_len)
    if not prefix:
        raise HTTPException(status_code=404, detail="No available child prefixes found")
    return {"parent_subnet_id": subnet_id, "next_available_prefix": prefix}


@router.get('/ipam/reconciliation')
def api_ipam_reconciliation(_user=require_role("Viewer")):
    return get_ipam_reconciliation()
