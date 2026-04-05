"""
IPAM API — IP/VLAN resource management endpoints.
All write operations require Operator+; delete requires Administrator.
"""

import logging
from fastapi import APIRouter, HTTPException, Query
from core.rbac import require_role
from schemas.schemas import SubnetCreate, SubnetUpdate, IPAddressCreate, IPAddressUpdate
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
)
from services.audit_service import log_audit_event

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Subnets ───────────────────────────────────

@router.get('/ipam/subnets')
def api_list_subnets(
    site: str = 'all',
    status: str = 'all',
    q: str = '',
    _user=require_role("Viewer"),
):
    return list_subnets(site=site, status=status, q=q)


@router.post('/ipam/subnets', status_code=201)
def api_create_subnet(body: SubnetCreate, user=require_role("Operator")):
    try:
        result = create_subnet(
            name=body.name,
            network=body.network,
            prefix_len=body.prefix_len,
            vlan_id=body.vlan_id,
            vlan_name=body.vlan_name,
            gateway=body.gateway,
            description=body.description,
            site=body.site,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    log_audit_event(
        event_type="ipam.subnet.create",
        category="ipam",
        severity="info",
        status="success",
        summary=f"Created subnet {body.network}/{body.prefix_len}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="subnet",
        target_id=result["id"],
        target_name=body.name or f"{body.network}/{body.prefix_len}",
    )
    return result


@router.put('/ipam/subnets/{subnet_id}')
def api_update_subnet(subnet_id: str, body: SubnetUpdate, user=require_role("Operator")):
    fields = body.model_dump(exclude_none=True)
    if not update_subnet(subnet_id, **fields):
        raise HTTPException(status_code=404, detail='Subnet not found')

    log_audit_event(
        event_type="ipam.subnet.update",
        category="ipam",
        severity="info",
        status="success",
        summary=f"Updated subnet {subnet_id}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="subnet",
        target_id=subnet_id,
        details=fields,
    )
    return {'ok': True}


@router.delete('/ipam/subnets/{subnet_id}')
def api_delete_subnet(subnet_id: str, user=require_role("Administrator")):
    if not delete_subnet(subnet_id):
        raise HTTPException(status_code=404, detail='Subnet not found')

    log_audit_event(
        event_type="ipam.subnet.delete",
        category="ipam",
        severity="warning",
        status="success",
        summary=f"Deleted subnet {subnet_id}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="subnet",
        target_id=subnet_id,
    )
    return {'ok': True}


@router.post('/ipam/subnets/batch-delete')
def api_batch_delete_subnets(body: dict, user=require_role("Administrator")):
    ids = body.get("ids", [])
    if not ids or not isinstance(ids, list):
        raise HTTPException(status_code=422, detail="ids must be a non-empty list")
    deleted = 0
    failed = 0
    for sid in ids:
        if delete_subnet(str(sid)):
            deleted += 1
            log_audit_event(
                event_type="ipam.subnet.delete",
                category="ipam",
                severity="warning",
                status="success",
                summary=f"Batch deleted subnet {sid}",
                actor_username=user.get("username"),
                actor_role=user.get("role"),
                target_type="subnet",
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
def api_create_address(subnet_id: str, body: IPAddressCreate, user=require_role("Operator")):
    try:
        result = create_address(
            subnet_id,
            address=body.address,
            hostname=body.hostname,
            device_id=body.device_id,
            interface_name=body.interface_name,
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
        summary=f"Added IP {body.address} to subnet {subnet_id}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ip_address",
        target_id=result["id"],
        target_name=body.address,
    )
    return result


@router.put('/ipam/addresses/{address_id}')
def api_update_address(address_id: str, body: IPAddressUpdate, user=require_role("Operator")):
    fields = body.model_dump(exclude_none=True)
    if not update_address(address_id, **fields):
        raise HTTPException(status_code=404, detail='Address not found')

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
def api_delete_address(address_id: str, user=require_role("Administrator")):
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


# ── Conflict & Summary ────────────────────────

@router.get('/ipam/conflicts')
def api_detect_conflicts(_user=require_role("Viewer")):
    return detect_conflicts()


@router.get('/ipam/summary')
def api_ipam_summary(_user=require_role("Viewer")):
    return ipam_summary()
