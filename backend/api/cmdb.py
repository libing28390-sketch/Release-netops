"""
cmdb.py — CMDB Core Inventory API

REST endpoints for the foundational CMDB entities that back the platform's
asset model: tenants, sites, VRFs and VLANs. All routes are mounted under
`/api/cmdb`.
"""

import logging
from fastapi import APIRouter, HTTPException, Query
from database import get_db_connection
from core.rbac import require_role
from schemas.schemas import (
    TenantCreate, TenantUpdate,
    SiteCreate, SiteUpdate,
    VrfCreate, VrfUpdate,
    VlanCreate, VlanUpdate,
)
from services import cmdb_service
from services.audit_service import log_audit_event

logger = logging.getLogger(__name__)

router = APIRouter()


def _audit(user, event_type, severity, summary, target_type, target_id=None, target_name=None):
    try:
        log_audit_event(
            event_type=event_type,
            category="configuration",
            severity=severity,
            status="success",
            summary=summary,
            actor_username=user.get("username") if isinstance(user, dict) else None,
            actor_role=user.get("role") if isinstance(user, dict) else None,
            target_type=target_type,
            target_id=target_id,
            target_name=target_name,
        )
    except Exception:  # auditing must never break the request
        logger.debug("audit log failed", exc_info=True)


# ─── Tenants ────────────────────────────────────────────

@router.get("/cmdb/tenants")
def api_list_tenants(_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        return {"success": True, "data": cmdb_service.list_tenants(conn), "message": ""}
    finally:
        conn.close()


@router.post("/cmdb/tenants", status_code=201)
def api_create_tenant(body: TenantCreate, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        t = cmdb_service.create_tenant(conn, **body.model_dump())
        _audit(user, "tenant.create", "info", f"Created tenant '{body.name}'", "tenant", t.get("id"), body.name)
        return {"success": True, "data": t, "message": "Tenant created"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.put("/cmdb/tenants/{tenant_id}")
def api_update_tenant(tenant_id: str, body: TenantUpdate, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        t = cmdb_service.update_tenant(conn, tenant_id, **body.model_dump(exclude_unset=True))
        _audit(user, "tenant.update", "info", f"Updated tenant {tenant_id}", "tenant", tenant_id)
        return {"success": True, "data": t, "message": "Tenant updated"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.delete("/cmdb/tenants/{tenant_id}")
def api_delete_tenant(tenant_id: str, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        cmdb_service.delete_tenant(conn, tenant_id)
        _audit(user, "tenant.delete", "warning", f"Deleted tenant {tenant_id}", "tenant", tenant_id)
        return {"success": True, "data": None, "message": "Tenant deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


# ─── Sites ──────────────────────────────────────────────

@router.get("/cmdb/sites")
def api_list_sites(tenant_id: str = Query('', description="Filter by tenant"),
                   _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        return {"success": True, "data": cmdb_service.list_sites(conn, tenant_id=tenant_id), "message": ""}
    finally:
        conn.close()


@router.get("/cmdb/sites/{site_id}")
def api_get_site(site_id: str, _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        return {"success": True, "data": cmdb_service.get_site(conn, site_id), "message": ""}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()


@router.post("/cmdb/sites", status_code=201)
def api_create_site(body: SiteCreate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        s = cmdb_service.create_site(conn, **body.model_dump())
        _audit(user, "site.create", "info", f"Created site '{body.site_code}'", "site", s.get("id"), body.site_code)
        return {"success": True, "data": s, "message": "Site created"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.put("/cmdb/sites/{site_id}")
def api_update_site(site_id: str, body: SiteUpdate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        s = cmdb_service.update_site(conn, site_id, **body.model_dump(exclude_unset=True))
        _audit(user, "site.update", "info", f"Updated site {site_id}", "site", site_id)
        return {"success": True, "data": s, "message": "Site updated"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.delete("/cmdb/sites/{site_id}")
def api_delete_site(site_id: str, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        cmdb_service.delete_site(conn, site_id)
        _audit(user, "site.delete", "warning", f"Deleted site {site_id}", "site", site_id)
        return {"success": True, "data": None, "message": "Site deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


# ─── VRFs ───────────────────────────────────────────────

@router.get("/cmdb/vrfs")
def api_list_vrfs(tenant_id: str = Query('', description="Filter by tenant"),
                  _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        return {"success": True, "data": cmdb_service.list_vrfs(conn, tenant_id=tenant_id), "message": ""}
    finally:
        conn.close()


@router.post("/cmdb/vrfs", status_code=201)
def api_create_vrf(body: VrfCreate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        v = cmdb_service.create_vrf(conn, **body.model_dump())
        _audit(user, "vrf.create", "info", f"Created VRF '{body.vrf_name}'", "vrf", v.get("id"), body.vrf_name)
        return {"success": True, "data": v, "message": "VRF created"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.put("/cmdb/vrfs/{vrf_id}")
def api_update_vrf(vrf_id: str, body: VrfUpdate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        v = cmdb_service.update_vrf(conn, vrf_id, **body.model_dump(exclude_unset=True))
        _audit(user, "vrf.update", "info", f"Updated VRF {vrf_id}", "vrf", vrf_id)
        return {"success": True, "data": v, "message": "VRF updated"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.delete("/cmdb/vrfs/{vrf_id}")
def api_delete_vrf(vrf_id: str, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        cmdb_service.delete_vrf(conn, vrf_id)
        _audit(user, "vrf.delete", "warning", f"Deleted VRF {vrf_id}", "vrf", vrf_id)
        return {"success": True, "data": None, "message": "VRF deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


# ─── VLANs ──────────────────────────────────────────────

@router.get("/cmdb/vlans")
def api_list_vlans(site_id: str = Query('', description="Filter by site"),
                   tenant_id: str = Query('', description="Filter by tenant"),
                   _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        data = cmdb_service.list_vlans(conn, site_id=site_id, tenant_id=tenant_id)
        return {"success": True, "data": data, "message": ""}
    finally:
        conn.close()


@router.post("/cmdb/vlans", status_code=201)
def api_create_vlan(body: VlanCreate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        v = cmdb_service.create_vlan(conn, **body.model_dump())
        _audit(user, "vlan.create", "info", f"Created VLAN {body.vlan_id}", "vlan", v.get("id"), body.name)
        return {"success": True, "data": v, "message": "VLAN created"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.put("/cmdb/vlans/{vlan_pk}")
def api_update_vlan(vlan_pk: str, body: VlanUpdate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        v = cmdb_service.update_vlan(conn, vlan_pk, **body.model_dump(exclude_unset=True))
        _audit(user, "vlan.update", "info", f"Updated VLAN {vlan_pk}", "vlan", vlan_pk)
        return {"success": True, "data": v, "message": "VLAN updated"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


@router.delete("/cmdb/vlans/{vlan_pk}")
def api_delete_vlan(vlan_pk: str, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        cmdb_service.delete_vlan(conn, vlan_pk)
        _audit(user, "vlan.delete", "warning", f"Deleted VLAN {vlan_pk}", "vlan", vlan_pk)
        return {"success": True, "data": None, "message": "VLAN deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()
