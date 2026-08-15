"""
cmdb.py — CMDB Core Inventory API

REST endpoints for the foundational CMDB entities that back the platform's
asset model: tenants, sites, VRFs and VLANs. All routes are mounted under
`/api/cmdb`.
"""

import logging
import csv
import io
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import Response
from database import get_db_connection
from core.rbac import require_role
from core.read_cache import (
    REFERENCE_CACHE_TTL_SECONDS,
    invalidate_read_cache,
    read_cache,
)
from schemas.schemas import (
    TenantCreate, TenantUpdate,
    SiteCreate, SiteUpdate, SiteImportRequest,
    VrfCreate, VrfUpdate,
    VlanCreate, VlanUpdate,
    VlanBusinessBindingCreate, VlanBusinessBindingUpdate,
)
from services import cmdb_service
from services import job_service
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
            f"""SELECT dt.resource_id AS device_id, td.id, td.category, td.code, td.code AS value, td.label,
                       td.label_zh, td.color, td.icon, td.description,
                       td.sort_order, td.built_in, td.created_at, td.source_type, td.is_system
                FROM tag_assignments dt
                JOIN tag_definitions td ON td.id = dt.tag_id
                WHERE dt.resource_type='device' AND dt.resource_id IN ({placeholders})
                ORDER BY td.category, td.sort_order, td.code""",
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
                "EXISTS (SELECT 1 FROM tag_assignments dt_filter "
                "WHERE dt_filter.resource_type='device' AND dt_filter.resource_id = d.id AND dt_filter.tag_id = ?)"
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


@router.get("/cmdb/resources")
def api_cmdb_resources(
    q: str = "",
    search_field: str = "all",
    search_mode: str = "fuzzy",
    site_id: str = "",
    asset_type: str = "all",
    device_category: str = "",
    vendor: str = "",
    platform: str = "",
    status: str = "all",
    lifecycle_status: str = "all",
    tag_ids: str = "",
    tag_match_all: bool = True,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    _user=require_role("Viewer"),
):
    """Search the complete device resource population read-only."""
    conn = get_db_connection()
    try:
        result = cmdb_service.list_resource_search(
            conn,
            q=q,
            search_field=search_field,
            search_mode=search_mode,
            site_id=site_id,
            asset_type=asset_type,
            device_category=device_category,
            vendor=vendor,
            platform=platform,
            status=status,
            lifecycle_status=lifecycle_status,
            tag_ids=[value.strip() for value in tag_ids.replace('，', ',').replace(';', ',').split(',') if value.strip()],
            tag_match_all=tag_match_all,
            page=page,
            page_size=page_size,
        )
        _attach_asset_tags(conn, result['items'])
        return {"success": True, "data": result, "message": ""}
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
def api_list_cmdb_interfaces(
    has_ip: Optional[bool] = Query(default=None, description="Optionally filter by whether an interface has an assigned IP"),
    device_id: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        return {"success": True, "data": cmdb_service.list_cmdb_interfaces(
            conn, has_ip=has_ip, device_id=device_id, search=search,
            page=page, page_size=page_size,
        ), "message": ""}
    finally:
        conn.close()


@router.post("/cmdb/interfaces/sync", status_code=202)
def api_trigger_cmdb_interface_sync(
    background_tasks: BackgroundTasks,
    user=require_role("Operator"),
):
    """Queue a durable, device-level TextFSM interface status collection."""
    conn = get_db_connection()
    try:
        active = conn.execute(
            """SELECT id FROM jobs
               WHERE job_type = 'interface_collection'
                 AND status IN ('queued', 'running')
               ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()
        if active:
            job = job_service.get_job(
                active['id'], conn=conn,
                target_statuses={'queued', 'running', 'failed', 'timeout'}, target_limit=100,
            )
            return {
                "success": True,
                "data": {"job_id": active['id'], "job": job, "reused": True},
                "message": "接口采集任务正在执行中",
            }

        devices = conn.execute(
            """SELECT id, site_id, vendor FROM devices
               WHERE status = 'online'
               ORDER BY hostname, ip_address"""
        ).fetchall()
    finally:
        conn.close()

    targets = [
        {"target_id": row['id'], "target_type": "device", "site_id": row['site_id'], "vendor": row['vendor']}
        for row in devices
    ]
    if not targets:
        raise HTTPException(status_code=409, detail="当前没有在线设备可采集接口状态")

    from core.config import settings
    from services.job_worker import run_job

    configured_concurrency = int(getattr(settings, "NETWORK_SSH_GLOBAL_CONCURRENCY", 20))
    job = job_service.create_job(
        job_type="interface_collection",
        task_name="CMDB接口状态采集",
        created_by=user.get("username", "system"),
        targets=targets,
        steps=["collect_interface_status"],
        # Interface collection writes several related CMDB projections per
        # device. Keep network I/O concurrent, but bound DB-writing pressure
        # to reduce lock contention and deadlocks when many devices share a site.
        concurrency_limit=max(1, min(configured_concurrency, 8)),
        retry_limit=0,
        timeout_seconds=180,
        scope={
            "collector": "playbook_interfaces_textfsm",
            "site_concurrency": 2,
            "vendor_concurrency": 4,
        },
    )
    background_tasks.add_task(run_job, job['id'])
    compact_job = job_service.get_job(
        job['id'],
        target_statuses={'queued', 'running', 'failed', 'timeout'}, target_limit=100,
    )
    return {
        "success": True,
        "data": {
            "started": True,
            "job_id": job['id'],
            "collector": "playbook_interfaces_textfsm",
            "job": compact_job,
        },
        "message": "接口状态采集任务已启动",
    }


@router.get("/cmdb/interfaces/sync/{job_id}")
def api_get_cmdb_interface_sync(job_id: str, _user=require_role("Viewer")):
    """Return durable device-level progress and failure details for the UI."""
    try:
        job = job_service.get_job(
            job_id,
            target_statuses={'queued', 'running', 'failed', 'timeout'}, target_limit=100,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if job.get('job_type') != 'interface_collection':
        raise HTTPException(status_code=404, detail="接口采集任务不存在")
    return {"success": True, "data": job, "message": ""}


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
                   q: str = Query('', description="Search site code or name"),
                   page: int | None = Query(None, ge=1),
                   page_size: int = Query(20, ge=1, le=100),
                   _user=require_role("Viewer")):
    cache_key = f'sites:{tenant_id}:{q}:{page}:{page_size}'
    if page is not None:
        conn = get_db_connection()
        try:
            return {"success": True, "data": cmdb_service.list_sites(conn, tenant_id=tenant_id, q=q, page=page, page_size=page_size), "message": ""}
        finally:
            conn.close()
    cache_hit, cached = read_cache.get('references', cache_key)
    if cache_hit:
        return cached
    conn = get_db_connection()
    try:
        response = {"success": True, "data": cmdb_service.list_sites(conn, tenant_id=tenant_id, q=q), "message": ""}
        read_cache.set('references', cache_key, response, REFERENCE_CACHE_TTL_SECONDS)
        return response
    finally:
        conn.close()


@router.get("/cmdb/sites/export")
def api_export_sites(
    tenant_id: str = Query('', description="Filter by tenant"),
    q: str = Query('', description="Search site code or name"),
    _user=require_role("Viewer"),
):
    """Export the complete site reference set, independent of UI pagination."""
    conn = get_db_connection()
    try:
        rows = cmdb_service.list_sites(conn, tenant_id=tenant_id, q=q)
        columns = [
            '站点编码', '站点名称', '国家', '省份 / 州', '城市', '区县',
            '联系人', '联系电话', '联系邮箱', '时区', '详细地址', '状态',
            '租户', '创建时间', '更新时间',
        ]
        field_map = {
            '站点编码': 'site_code',
            '站点名称': 'site_name',
            '国家': 'country',
            '省份 / 州': 'state_province',
            '城市': 'city',
            '区县': 'district',
            '联系人': 'contact_name',
            '联系电话': 'contact_phone',
            '联系邮箱': 'contact_email',
            '时区': 'timezone',
            '详细地址': 'address',
            '状态': 'status',
            '租户': 'tenant_id',
            '创建时间': 'created_at',
            '更新时间': 'updated_at',
        }
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=columns,
            extrasaction='ignore',
            lineterminator='\n',
        )
        writer.writeheader()
        writer.writerows({column: row.get(field) or '' for column, field in field_map.items()} for row in rows)
        content = '\ufeff' + output.getvalue()
        return Response(
            content=content,
            media_type='text/csv; charset=utf-8',
            headers={'Content-Disposition': 'attachment; filename="sites_export.csv"'},
        )
    finally:
        conn.close()


@router.post("/cmdb/sites/import")
def api_import_sites(body: SiteImportRequest, user=require_role("Operator")):
    """Create sites from a validated spreadsheet payload.

    The UI blocks files with validation errors, while this endpoint repeats
    duplicate-name checks so API clients cannot accidentally create ambiguous
    site references.
    """
    conn = get_db_connection()
    imported: list[dict] = []
    errors: list[dict] = []
    prepared: list[tuple[int, dict]] = []
    seen_names: set[tuple[str, str]] = set()
    try:
        for row_number, row in enumerate(body.rows, start=2):
            payload = row.model_dump()
            normalized_name = str(payload.get('site_name') or '').strip().casefold()
            tenant_key = str(payload.get('tenant_id') or 'tenant-default').strip()
            name_key = (tenant_key, normalized_name)
            if name_key in seen_names:
                errors.append({'row': row_number, 'message': '站点名称在导入文件中重复'})
                continue
            seen_names.add(name_key)
            duplicate = conn.execute(
                "SELECT 1 FROM sites WHERE tenant_id = ? AND LOWER(site_name) = ? LIMIT 1",
                (tenant_key, normalized_name),
            ).fetchone()
            if duplicate:
                errors.append({'row': row_number, 'message': f"站点名称已存在：{payload.get('site_name')}"})
                continue
            prepared.append((row_number, payload))

        # Do not partially create a spreadsheet when the preflight detects a
        # duplicate. The caller can correct the file and retry safely.
        if errors:
            return {
                'success': True,
                'data': {'imported': 0, 'failed': len(errors), 'errors': errors, 'items': []},
                'message': 'Site import preflight failed',
            }

        for row_number, payload in prepared:
            try:
                site = cmdb_service.create_site(conn, **payload)
                imported.append(site)
            except ValueError as exc:
                errors.append({'row': row_number, 'message': str(exc)})
        if imported:
            _audit(user, "site.import", "info", f"Imported {len(imported)} site(s)", "site", None)
            invalidate_read_cache('references')
            invalidate_read_cache('rack_page')
        return {
            'success': True,
            'data': {
                'imported': len(imported),
                'failed': len(errors),
                'errors': errors,
                'items': imported,
            },
            'message': 'Site import processed',
        }
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
        invalidate_read_cache('references')
        invalidate_read_cache('rack_page')
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
        invalidate_read_cache('references')
        invalidate_read_cache('rack_page')
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
        invalidate_read_cache('references')
        invalidate_read_cache('rack_page')
        return {"success": True, "data": result, "message": "Site deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


# ─── VRFs ───────────────────────────────────────────────

@router.get("/cmdb/vrfs")
def api_list_vrfs(tenant_id: str = Query('', description="Filter by tenant"),
                  q: str = Query('', description="Search VRF, RD or description"),
                  page: int | None = Query(None, ge=1),
                  page_size: int = Query(20, ge=1, le=100),
                  _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        return {"success": True, "data": cmdb_service.list_vrfs(conn, tenant_id=tenant_id, q=q, page=page, page_size=page_size), "message": ""}
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
                   q: str = Query('', description="Search VLAN ID or description"),
                   status: str = Query('all', description="Filter by status"),
                   asset_type: str = Query('', description="Filter by asset type"),
                   device_category: str = Query('', description="Filter by device category"),
                   device_role: str = Query('', description="Filter by device role"),
                   page: int | None = Query(None, ge=1),
                   page_size: int = Query(20, ge=1, le=100),
                   _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        data = cmdb_service.list_vlans(
            conn,
            site_id=site_id,
            tenant_id=tenant_id,
            q=q,
            status=status,
            asset_type=asset_type,
            device_category=device_category,
            device_role=device_role,
            page=page,
            page_size=page_size,
            device_scoped=True,
        )
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


@router.get("/cmdb/vlans/export")
def api_export_vlans(
    site_id: str = Query('', description="Filter by site"),
    tenant_id: str = Query('', description="Filter by tenant"),
    _user=require_role("Viewer"),
):
    """Export the complete VLAN evidence set, independent of UI pagination."""
    conn = get_db_connection()
    try:
        rows = cmdb_service.export_vlans(conn, site_id=site_id, tenant_id=tenant_id)
        columns = [
            '站点', '设备名称', '设备IP', 'VLAN ID', 'VLAN描述', '网关', '网段',
            '接入接口', '接口描述', 'ARP/MAC信息', '接口采集时间', 'ARP采集时间', 'MAC采集时间',
            '业务系统', '业务部门', '负责人',
        ]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction='ignore', lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
        content = '\ufeff' + output.getvalue()
        return Response(
            content=content,
            media_type='text/csv; charset=utf-8',
            headers={'Content-Disposition': 'attachment; filename="vlan_inventory.csv"'},
        )
    finally:
        conn.close()


# VLAN business ownership bindings. Network facts remain collector-owned;
# operators maintain only the business meaning of a VLAN scope here.

@router.get("/cmdb/vlan-business-bindings")
def api_list_vlan_business_bindings(
    site_id: str = Query(''),
    vrf_id: str = Query(''),
    vlan_id: Optional[int] = Query(None, ge=1, le=4094),
    _user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        data = cmdb_service.list_vlan_business_bindings(
            conn, site_id=site_id, vrf_id=vrf_id, vlan_id=vlan_id
        )
        return {"success": True, "data": data, "message": ""}
    finally:
        conn.close()


@router.post("/cmdb/vlan-business-bindings", status_code=201)
def api_create_vlan_business_binding(body: VlanBusinessBindingCreate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        data = cmdb_service.create_vlan_business_binding(conn, **body.model_dump())
        _audit(
            user, "vlan_business_binding.create", "info",
            f"Created VLAN business binding for VLAN {body.vlan_id}",
            "vlan_business_binding", data.get("id"), body.business_system,
        )
        return {"success": True, "data": data, "message": "VLAN business binding created"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()


@router.put("/cmdb/vlan-business-bindings/{binding_id}")
def api_update_vlan_business_binding(
    binding_id: str,
    body: VlanBusinessBindingUpdate,
    user=require_role("Operator"),
):
    conn = get_db_connection()
    try:
        data = cmdb_service.update_vlan_business_binding(
            conn, binding_id, **body.model_dump(exclude_unset=True)
        )
        _audit(
            user, "vlan_business_binding.update", "info",
            f"Updated VLAN business binding {binding_id}",
            "vlan_business_binding", binding_id,
        )
        return {"success": True, "data": data, "message": "VLAN business binding updated"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()


@router.delete("/cmdb/vlan-business-bindings/{binding_id}")
def api_delete_vlan_business_binding(binding_id: str, user=require_role("Administrator")):
    conn = get_db_connection()
    try:
        cmdb_service.delete_vlan_business_binding(conn, binding_id)
        _audit(
            user, "vlan_business_binding.delete", "warning",
            f"Deleted VLAN business binding {binding_id}",
            "vlan_business_binding", binding_id,
        )
        return {"success": True, "data": None, "message": "VLAN business binding deleted"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()
