"""
cmdb.py — CMDB Core Inventory API

REST endpoints for the foundational CMDB entities that back the platform's
asset model: tenants, sites, VRFs and VLANs. All routes are mounted under
`/api/cmdb`.
"""

import logging
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
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


def _asset_online_status_sql() -> str:
    return """COALESCE(NULLIF(d.status, ''), CASE
        WHEN pa.status = 'active' THEN 'online'
        WHEN pa.status IN ('inactive', 'maintenance', 'decommissioned') THEN 'offline'
        ELSE 'pending'
    END)"""


def _attach_asset_tags(conn, items: list[dict]) -> None:
    """Attach non-sensitive tag metadata to the CMDB asset table rows."""
    device_ids = [str(item.get("device_id") or "") for item in items if item.get("device_id")]
    tag_map: dict[str, list[dict]] = {}
    if device_ids:
        placeholders = ",".join("?" for _ in device_ids)
        rows = conn.execute(
            f"""SELECT dt.device_id, td.id, td.category, td.value, td.label,
                       td.label_zh, td.color, td.icon, td.description,
                       td.sort_order, td.built_in, td.created_at
                FROM device_tags dt
                JOIN tag_definitions td ON td.id = dt.tag_id
                WHERE dt.device_id IN ({placeholders})
                ORDER BY td.category, td.sort_order, td.value""",
            device_ids,
        ).fetchall()
        for row in rows:
            tag = dict(row)
            device_id = str(tag.pop("device_id"))
            tag_map.setdefault(device_id, []).append(tag)
    for item in items:
        item["tags"] = tag_map.get(str(item.get("device_id") or ""), [])


@router.get("/cmdb/assets/tree")
def api_cmdb_asset_tree(_user=require_role("Viewer")):
    """Return the canonical CMDB asset tree source.

    The hierarchy is site → asset type → product category → physical asset
    role.  It intentionally never reads ``devices.role`` or the legacy
    retired free-text datacenter field.
    """
    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"""SELECT
                    COALESCE(NULLIF(pa.site_id, ''), 'unassigned') AS site_id,
                    COALESCE(NULLIF(s.site_name, ''), NULLIF(s.site_code, ''), 'Unassigned site') AS site_name,
                    COALESCE(NULLIF(s.site_code, ''), '') AS site_code,
                    COALESCE(NULLIF(pa.asset_type, ''), 'other') AS asset_type,
                    COALESCE(NULLIF(pa.device_category, ''), 'other') AS device_category,
                    COALESCE(NULLIF(pa.device_role, ''), 'unassigned') AS device_role,
                    {_asset_online_status_sql()} AS online_status,
                    COUNT(*) AS asset_count
                FROM physical_assets pa
                LEFT JOIN sites s ON s.id = pa.site_id
                LEFT JOIN devices d ON d.asset_id = pa.id
                GROUP BY pa.site_id, s.site_name, s.site_code,
                         pa.asset_type, pa.device_category, pa.device_role,
                         pa.status, d.status
                ORDER BY site_name, asset_type, device_category, device_role, online_status"""
        ).fetchall()
        return {"success": True, "data": {"items": [dict(row) for row in rows]}, "message": ""}
    finally:
        conn.close()


@router.get("/cmdb/assets")
def api_cmdb_assets(
    site_id: str = "",
    asset_type: str = "all",
    device_category: str = "",
    device_role: str = "",
    status: str = "all",
    tag_ids: str = "",
    tag_match_all: bool = True,
    q: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    _user=require_role("Viewer"),
):
    """List CMDB assets for the selected tree branch."""
    conn = get_db_connection()
    try:
        conditions: list[str] = []
        params: list[object] = []
        if site_id:
            conditions.append("pa.site_id = ?")
            params.append(site_id)
        if asset_type != "all":
            conditions.append("pa.asset_type = ?")
            params.append(asset_type)
        if device_category:
            conditions.append("pa.device_category = ?")
            params.append(device_category)
        if device_role:
            conditions.append("pa.device_role = ?")
            params.append(device_role)
        if status != "all":
            conditions.append(f"{_asset_online_status_sql()} = ?")
            params.append(status)
        requested_tag_ids = [value.strip() for value in tag_ids.split(",") if value.strip()][:100]
        if requested_tag_ids:
            tag_exists = [
                "EXISTS (SELECT 1 FROM device_tags dt_filter "
                "WHERE dt_filter.device_id = d.id AND dt_filter.tag_id = ?)"
                for _ in requested_tag_ids
            ]
            conditions.append(
                f"({' AND '.join(tag_exists) if tag_match_all else ' OR '.join(tag_exists)})"
            )
            params.extend(requested_tag_ids)
        if q:
            like = f"%{q}%"
            conditions.append(
                "(pa.hostname LIKE ? OR pa.asset_tag LIKE ? OR pa.serial_number LIKE ? "
                "OR pa.vendor LIKE ? OR pa.model LIKE ? OR pa.management_ip LIKE ?)"
            )
            params.extend([like] * 6)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM physical_assets pa "
            f"LEFT JOIN devices d ON d.asset_id = pa.id{where}",
            params,
        ).fetchone()[0]
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""SELECT pa.*, d.id AS device_id,
                       s.site_code, s.site_name,
                       {_asset_online_status_sql()} AS online_status,
                       COALESCE(NULLIF(pa.normal_username, ''), d.normal_username, '') AS normal_username,
                       COALESCE(NULLIF(pa.admin_username, ''), d.admin_username, '') AS admin_username,
                       COALESCE(NULLIF(pa.username, ''), d.username, '') AS username
                FROM physical_assets pa
                LEFT JOIN sites s ON s.id = pa.site_id
                LEFT JOIN devices d ON d.asset_id = pa.id
                {where}
                ORDER BY pa.updated_at DESC, pa.created_at DESC
                LIMIT ? OFFSET ?""",
            params + [page_size, offset],
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            for sensitive in ("password", "normal_password", "admin_password", "enable_password"):
                if sensitive in item:
                    item[f"{sensitive}_set"] = bool(item.get(sensitive))
                    item[sensitive] = ""
            items.append(item)
        _attach_asset_tags(conn, items)
        return {
            "success": True,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": max(1, -(-total // page_size)),
            },
            "message": "",
        }
    finally:
        conn.close()


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


# ─── Network CMDB Skeleton ──────────────────────────

@router.get("/cmdb/devices")
def api_list_cmdb_devices(_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        return {"success": True, "data": cmdb_service.list_cmdb_devices(conn), "message": ""}
    finally:
        conn.close()


@router.get("/cmdb/interfaces")
def api_list_cmdb_interfaces(_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        return {"success": True, "data": cmdb_service.list_cmdb_interfaces(conn), "message": ""}
    finally:
        conn.close()


@router.post("/cmdb/interfaces/sync", status_code=202)
def api_trigger_cmdb_interface_sync(
    background_tasks: BackgroundTasks,
    _user=require_role("Operator"),
):
    """Start an on-demand interface and topology inventory collection."""
    from services.scheduler_service import sync_topology_and_interfaces_job

    background_tasks.add_task(sync_topology_and_interfaces_job)
    return {
        "success": True,
        "data": {"started": True, "collector": "topology_interface_sync"},
        "message": "Interface collection started in the background",
    }


@router.get("/cmdb/data-quality/field-authority")
def api_cmdb_field_authority_quality(_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        return {"success": True, "data": cmdb_service.get_field_authority_quality(conn), "message": ""}
    finally:
        conn.close()


@router.post("/cmdb/data-quality/backfill-authority")
def api_cmdb_backfill_field_authority(user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        result = cmdb_service.backfill_field_authority(conn)
        _audit(
            user, "cmdb.authority.backfill", "warning",
            "Backfilled deterministic CMDB authority references",
            "cmdb_data_quality", target_name="field-authority",
        )
        return {"success": True, "data": result, "message": "Authority references backfilled"}
    finally:
        conn.close()


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
        _audit(user, "site.create", "info", f"Created site '{s.get('site_code')}'", "site", s.get("id"), s.get("site_code"))
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
def api_delete_site(
    site_id: str,
    replacement_site_id: str = Query('', description="Move references to this site before deletion"),
    user=require_role("Administrator"),
):
    conn = get_db_connection()
    try:
        result = cmdb_service.delete_site(conn, site_id, replacement_site_id=replacement_site_id)
        _audit(user, "site.delete", "warning", f"Deleted site {site_id}", "site", site_id)
        return {"success": True, "data": result, "message": "Site deleted"}
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
