"""
cmdb.py — CMDB Core Inventory API

REST endpoints for the foundational CMDB entities that back the platform's
asset model: tenants, sites, VRFs and VLANs. All routes are mounted under
`/api/cmdb`.
"""

import json
import logging
import csv
import io
import math
import time
import threading
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from database import get_db_connection
from core.rbac import require_role
from core.tenant_policy import tenant_id_for_write
from core.read_cache import (
    REFERENCE_CACHE_TTL_SECONDS,
    invalidate_read_cache,
    read_cache,
)
from schemas.schemas import (
    SiteCreate, SiteUpdate, SiteImportRequest,
    VrfCreate, VrfUpdate,
    VlanCreate, VlanUpdate,
    VlanBusinessBindingCreate, VlanBusinessBindingUpdate,
)
from services import cmdb_service
from services import job_service
from services.cmdb_version_service import read_versions
from services.cmdb_cache_runtime import get_cmdb_query_cache
from services.audit_service import log_audit_event

logger = logging.getLogger(__name__)

router = APIRouter()

_CMDB_UNVERSIONED_DEPENDENCY_RESOURCES = frozenset({
    'interfaces', 'vlans', 'vlan_details',
})
_CMDB_BUILD_SEMAPHORE = threading.BoundedSemaphore(4)


def _begin_cmdb_read_snapshot(conn) -> None:
    """Pin cache generation and its SQL projection to one PostgreSQL snapshot."""
    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")


def _find_active_cmdb_interface_job(conn):
    """Reuse only an active task that explicitly owns the CMDB CLI scope."""
    rows = conn.execute(
        """SELECT id, scope_json FROM jobs
           WHERE job_type = 'interface_collection'
             AND status IN ('queued', 'running')
           ORDER BY created_at DESC"""
    ).fetchall()
    for candidate in rows:
        try:
            scope = json.loads(candidate["scope_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(scope, dict) and scope.get("cmdb_cli_only") is True:
            return candidate
    return None


def _cmdb_cache_generation(conn, domains: tuple[str, ...]) -> dict:
    versions = read_versions(conn, domains)
    return {'cmdb': versions}


def _cmdb_projection_meta(
    conn,
    generation: dict,
    cache_state: str,
    snapshot_domains: tuple[str, ...],
    *,
    tenant_id: str | None = None,
    site_ids: tuple[str, ...] | None = None,
    site_id: str = "",
) -> dict:
    domains = sorted({str(value).strip() for value in snapshot_domains if str(value).strip()})
    last_success_at: dict[str, str | None] = {}
    if domains:
        placeholders = ",".join("?" for _ in domains)
        scope_clauses: list[str] = []
        scope_params: list[str] = []
        if tenant_id is not None:
            scope_clauses.append("COALESCE(d.tenant_id, 'tenant-default') = ?")
            scope_params.append(tenant_id)
        if site_ids is not None:
            if not site_ids:
                scope_clauses.append("1 = 0")
            else:
                site_placeholders = ",".join("?" for _ in site_ids)
                scope_clauses.append(f"d.site_id IN ({site_placeholders})")
                scope_params.extend(site_ids)
        if site_id:
            device_site = "COALESCE(NULLIF(d.site_id, ''), NULLIF(d.site, ''), '')"
            if site_id == "unassigned":
                scope_clauses.append(f"{device_site} = ''")
            else:
                scope_clauses.append(f"{device_site} = ?")
                scope_params.append(site_id)
        scope_sql = " AND " + " AND ".join(scope_clauses) if scope_clauses else ""
        rows = conn.execute(
            f"""SELECT domain, MAX(last_success_at) AS last_success_at
                FROM cmdb_collection_snapshots s
                JOIN devices d ON d.id = s.device_id
                WHERE domain IN ({placeholders}){scope_sql}
                GROUP BY domain""",
            (*domains, *scope_params),
        ).fetchall()
        last_success_at = {domain: None for domain in domains}
        last_success_at.update({str(row["domain"]): row["last_success_at"] for row in rows})
    snapshot_row = conn.execute(
        "SELECT transaction_timestamp() AS snapshot_at"
    ).fetchone()
    raw_snapshot_at = snapshot_row["snapshot_at"] if snapshot_row else None
    snapshot_at = raw_snapshot_at.isoformat() if hasattr(raw_snapshot_at, "isoformat") else str(raw_snapshot_at or "")
    return {
        "inventory_revision": dict(generation.get("cmdb") or {}),
        # A request clock is not evidence of successful external collection.
        "dependency_watermark": None,
        "snapshot_at": snapshot_at,
        "last_success_at": last_success_at,
        "cache_state": cache_state,
        "stale_domains": [],
    }


def _cache_get(resource: str, generation: dict, scope: dict, query: dict):
    return get_cmdb_query_cache().get_json(
        resource, generation=generation, scope=scope, query=query,
    )


def _cache_set(resource: str, generation: dict, scope: dict, query: dict, value) -> None:
    get_cmdb_query_cache().set_json(
        resource,
        generation=generation,
        scope=scope,
        query=query,
        value=jsonable_encoder(value),
    )


def _cached_cmdb_projection(resource: str, generation: dict, scope: dict, query: dict, build):
    """Read/cache a projection with a short cross-worker rebuild lease.

    Redis remains optional. Contenders wait at most 100 ms, then use the
    PostgreSQL source of truth directly; none of these paths trigger a device
    operation. Revisioned keys prevent a slow older builder from overwriting
    a newer generation.
    """
    def build_bounded():
        with _CMDB_BUILD_SEMAPHORE:
            return build()

    # These projections include shared observations whose writers do not
    # publish a trustworthy revision. Read them from this request's database
    # snapshot, without constructing or consulting a Redis client.
    if resource in _CMDB_UNVERSIONED_DEPENDENCY_RESOURCES:
        return build_bounded(), 'bypass'

    cache = get_cmdb_query_cache()
    if cache.redis_client is None or cache.last_failure_kind:
        return build_bounded(), 'bypass'

    cached = cache.get_json(
        resource, generation=generation, scope=scope, query=query,
    )
    if cached is not None:
        return cached, 'hit'
    if cache.last_failure_kind:
        return build_bounded(), 'bypass'

    lock = cache.acquire_rebuild_lock(
        resource,
        generation=generation,
        scope=scope,
        query=query,
        lease_seconds=30,
    )
    if lock is None:
        if cache.last_failure_kind:
            return build_bounded(), 'bypass'
        deadline = time.monotonic() + 0.1
        while time.monotonic() < deadline:
            time.sleep(0.025)
            cached = cache.get_json(
                resource, generation=generation, scope=scope, query=query,
            )
            if cached is not None:
                return cached, 'hit'
            if cache.last_failure_kind:
                return build_bounded(), 'bypass'
        return build_bounded(), 'bypass'

    try:
        # Another worker may have completed between the initial GET and SET NX.
        cached = cache.get_json(
            resource, generation=generation, scope=scope, query=query,
        )
        if cached is not None:
            return cached, 'hit'
        if cache.last_failure_kind:
            return build_bounded(), 'bypass'
        value = build_bounded()
        _cache_set(resource, generation, scope, query, value)
        return value, 'miss'
    finally:
        cache.release_rebuild_lock(lock)


def _refresh_interface_profiles(conn, data):
    """Read profile fields live so a cached inventory cannot hide a profile edit."""
    rows = data.get('items') if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return data
    interface_ids = sorted({
        str(row.get('id') or '') for row in rows
        if row.get('id') and not str(row.get('id')).startswith('ipinv-')
    })
    if not interface_ids:
        return data
    placeholders = ','.join('?' for _ in interface_ids)
    profiles = conn.execute(
        f"""SELECT id, interface_role, utilization_warn_pct,
                   utilization_high_pct, utilization_critical_pct
            FROM interfaces WHERE id IN ({placeholders})""",
        tuple(interface_ids),
    ).fetchall()
    by_id = {str(row['id']): row for row in profiles}
    for item in rows:
        current = by_id.get(str(item.get('id') or ''))
        if current:
            item.update({
                'interface_role': current['interface_role'],
                'utilization_warn_pct': current['utilization_warn_pct'],
                'utilization_high_pct': current['utilization_high_pct'],
                'utilization_critical_pct': current['utilization_critical_pct'],
            })
    return data


class InterfaceMonitoringProfileUpdate(BaseModel):
    """Operator-editable CMDB monitoring profile fields."""

    model_config = ConfigDict(extra="forbid")

    interface_role: str | None = Field(default=None, min_length=1, max_length=32)
    utilization_warn_pct: float | None = Field(default=None, ge=0, le=100)
    utilization_high_pct: float | None = Field(default=None, ge=0, le=100)
    utilization_critical_pct: float | None = Field(default=None, ge=0, le=100)

    @field_validator("interface_role")
    @classmethod
    def normalize_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in cmdb_service.INTERFACE_ROLES:
            raise ValueError(
                "interface_role must be one of: "
                + ", ".join(sorted(cmdb_service.INTERFACE_ROLES))
            )
        return normalized

    @field_validator(
        "utilization_warn_pct",
        "utilization_high_pct",
        "utilization_critical_pct",
    )
    @classmethod
    def require_finite_percentage(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("utilization thresholds must be finite numbers")
        return value


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


def _cmdb_interface_resource_scope(conn, user, action: str) -> tuple[str | None, tuple[str, ...] | None]:
    """Resolve the caller's tenant/site scope for interface inventory access."""
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="Authentication required")
    if user.get("role") == "Administrator":
        return None, None

    from services.rack_scope_service import allowed_resource_scope

    scope = allowed_resource_scope(conn, user, "asset", action)
    if scope.site_ids == ():
        raise HTTPException(status_code=403, detail="Insufficient permission for the interface scope")
    return scope.tenant_id, scope.site_ids


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
    response: Response = None,
    user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        _begin_cmdb_read_snapshot(conn)
        tenant_id, site_ids = _cmdb_interface_resource_scope(conn, user, "view")
        scope = {
            'role': str(user.get('role') or ''),
            'tenant_id': tenant_id,
            'site_ids': sorted(site_ids) if site_ids is not None else None,
        }
        query = {
            'has_ip': has_ip,
            'device_id': device_id or '',
            'search': (search or '').strip(),
            'page': page,
            'page_size': page_size,
        }
        generation = _cmdb_cache_generation(conn, ('interfaces',))
        data, cache_state = _cached_cmdb_projection(
            'interfaces', generation, scope, query,
            lambda: cmdb_service.list_cmdb_interfaces(
                conn,
                has_ip=has_ip,
                device_id=device_id,
                search=search,
                page=page,
                page_size=page_size,
                tenant_id=tenant_id,
                site_ids=site_ids,
            )
        )
        if cache_state == 'hit':
            data = _refresh_interface_profiles(conn, data)
        if isinstance(data, dict):
            data['meta'] = _cmdb_projection_meta(
                conn,
                generation,
                cache_state,
                ("interface_inventory",),
                tenant_id=tenant_id,
                site_ids=site_ids,
            )
        if response is not None:
            response.headers['X-CMDB-Cache'] = cache_state
        return {"success": True, "data": data, "message": ""}
    finally:
        conn.close()


@router.patch("/cmdb/interfaces/{interface_id}/monitoring-profile")
def api_update_cmdb_interface_monitoring_profile(
    interface_id: str,
    body: InterfaceMonitoringProfileUpdate,
    user=require_role("Operator"),
):
    """Update the CMDB-owned thresholds consumed by interface monitoring."""
    conn = get_db_connection()
    try:
        tenant_id, site_ids = _cmdb_interface_resource_scope(conn, user, "update")
        profile = cmdb_service.update_interface_monitoring_profile(
            conn,
            interface_id,
            tenant_id=tenant_id,
            site_ids=site_ids,
            **body.model_dump(exclude_unset=True),
        )
        _audit(
            user,
            "interface.monitoring_profile.update",
            "info",
            f"Updated monitoring profile for interface {interface_id}",
            "interface",
            interface_id,
            profile.get("interface_name"),
        )
        return {"success": True, "data": profile, "message": "Interface monitoring profile updated"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/cmdb/interfaces/sync", status_code=202)
def api_trigger_cmdb_interface_sync(
    background_tasks: BackgroundTasks,
    user=require_role("Operator"),
):
    """Queue interface collection for online network devices only."""
    conn = get_db_connection()
    try:
        active = _find_active_cmdb_interface_job(conn)
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
            """SELECT d.id, d.site_id, d.vendor, d.status,
                      COALESCE(NULLIF(pa.asset_type, ''), 'network_device') AS canonical_asset_type,
                      COALESCE(NULLIF(d.device_category, ''), NULLIF(pa.device_category, ''), '') AS canonical_device_category,
                      COALESCE(NULLIF(d.platform, ''), NULLIF(pa.platform, ''), '') AS canonical_platform,
                      COALESCE(NULLIF(d.role, ''), NULLIF(pa.device_role, ''), '') AS canonical_role
               FROM devices d
               LEFT JOIN physical_assets pa ON pa.id = d.asset_id
               WHERE d.status = 'online'
               ORDER BY d.hostname, d.ip_address"""
        ).fetchall()
    finally:
        conn.close()

    from services.interface_collection_service import is_online_network_device_for_interface_collection

    targets = []
    for row in devices:
        device = dict(row)
        if not is_online_network_device_for_interface_collection(device):
            continue
        targets.append({
            "target_id": device['id'],
            "target_type": "device",
            "site_id": device['site_id'],
            "vendor": device['vendor'],
        })
    if not targets:
        raise HTTPException(status_code=409, detail="当前没有在线网络设备可采集接口状态")

    from services.network_access_lease_service import CMDB_SSH_GLOBAL_CAPACITY
    from services.job_worker import run_job

    job = job_service.create_job(
        job_type="interface_collection",
        task_name="CMDB接口状态采集",
        created_by=user.get("username", "system"),
        targets=targets,
        steps=["collect_interface_status"],
        # Interface collection writes several related CMDB projections per
        # device. Keep network I/O concurrent, but bound DB-writing pressure
        # to reduce lock contention and deadlocks when many devices share a site.
        concurrency_limit=CMDB_SSH_GLOBAL_CAPACITY,
        retry_limit=0,
        timeout_seconds=180,
        scope={
            "collector": "cmdb_cli_snapshot_v1",
            "cmdb_cli_only": True,
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
            "collector": "cmdb_cli_snapshot_v1",
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


@router.post("/cmdb/tenants", status_code=410)
def api_create_tenant(_user=require_role("Administrator")):
    raise HTTPException(
        status_code=410,
        detail={"code": "MULTI_TENANCY_DISABLED", "message": "Tenant management is disabled in single-organization mode"},
    )


@router.put("/cmdb/tenants/{tenant_id}")
def api_update_tenant(tenant_id: str, _user=require_role("Administrator")):
    del tenant_id
    raise HTTPException(
        status_code=410,
        detail={"code": "MULTI_TENANCY_DISABLED", "message": "Tenant management is disabled in single-organization mode"},
    )


@router.delete("/cmdb/tenants/{tenant_id}")
def api_delete_tenant(tenant_id: str, _user=require_role("Administrator")):
    del tenant_id
    raise HTTPException(
        status_code=410,
        detail={"code": "MULTI_TENANCY_DISABLED", "message": "Tenant management is disabled in single-organization mode"},
    )


# ─── Sites ──────────────────────────────────────────────

@router.get("/cmdb/sites")
def api_list_sites(tenant_id: str = Query('', description="Filter by tenant"),
                   q: str = Query('', description="Search site code or name"),
                   page: int | None = Query(None, ge=1),
                   page_size: int = Query(20, ge=1, le=100),
                   _user=require_role("Viewer")):
    if page is not None:
        conn = get_db_connection()
        try:
            return {"success": True, "data": cmdb_service.list_sites(conn, tenant_id=tenant_id, q=q, page=page, page_size=page_size), "message": ""}
        finally:
            conn.close()
    conn = get_db_connection()
    try:
        _begin_cmdb_read_snapshot(conn)
        site_revision = read_versions(conn, ("sites",)).get("sites", 0)
        cache_key = f'sites:{tenant_id}:{q}:{page}:{page_size}:revision:{site_revision}'
        cache_hit, cached = read_cache.get('references', cache_key)
        if cache_hit:
            return cached
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
            tenant_key = tenant_id_for_write(requested=payload.get('tenant_id'), user=user)
            payload['tenant_id'] = tenant_key
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
        payload = body.model_dump()
        payload['tenant_id'] = tenant_id_for_write(requested=payload.get('tenant_id'), user=user)
        s = cmdb_service.create_site(conn, **payload)
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
        payload = body.model_dump(exclude_unset=True)
        payload.pop('tenant_id', None)
        s = cmdb_service.update_site(conn, site_id, **payload)
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
        payload = body.model_dump()
        payload['tenant_id'] = tenant_id_for_write(requested=payload.get('tenant_id'), user=user)
        v = cmdb_service.create_vrf(conn, **payload)
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
        payload = body.model_dump(exclude_unset=True)
        payload.pop('tenant_id', None)
        v = cmdb_service.update_vrf(conn, vrf_id, **payload)
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
                   q: str = Query('', max_length=128, description="Search VLAN, prefix, gateway, device or business"),
                   status: str = Query('all', description="Filter by status"),
                   asset_type: str = Query('', description="Filter by asset type"),
                   device_category: str = Query('', description="Filter by device category"),
                   device_role: str = Query('', description="Filter by device role"),
                   page: int | None = Query(None, ge=1),
                   page_size: int = Query(20, ge=1, le=100),
                   include_details: bool = Query(False, description="Include full VLAN evidence for explicit export consumers"),
                   response: Response = None,
                   _user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        _begin_cmdb_read_snapshot(conn)
        scope = {
            'role': str(_user.get('role') or ''),
            'site_filter': site_id,
            'tenant_filter': tenant_id,
        }
        query = {
            'site_id': site_id,
            'tenant_id': tenant_id,
            'q': q.strip(),
            'status': status,
            'asset_type': asset_type,
            'device_category': device_category,
            'device_role': device_role,
            'page': page,
            'page_size': page_size,
            'include_details': include_details,
        }
        generation = _cmdb_cache_generation(conn, ('vlans', 'bindings', 'interfaces'))
        data, cache_state = _cached_cmdb_projection(
            'vlans', generation, scope, query,
            lambda: cmdb_service.list_vlans(
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
                include_details=include_details,
                device_scoped=True,
            )
        )
        if isinstance(data, dict):
            data['meta'] = _cmdb_projection_meta(
                conn,
                generation,
                cache_state,
                ("vlan_inventory",),
                tenant_id=tenant_id or None,
                site_id=site_id,
            )
        if response is not None:
            response.headers['X-CMDB-Cache'] = cache_state
        return {"success": True, "data": data, "message": ""}
    finally:
        conn.close()


@router.get("/cmdb/vlans/{vlan_pk}/details")
def api_get_vlan_details(
    vlan_pk: str,
    site_id: str = Query('', max_length=128),
    device_id: str = Query('', max_length=128),
    response: Response = None,
    user=require_role("Viewer"),
):
    """Read full port and endpoint evidence for the selected VLAN row only."""
    conn = get_db_connection()
    try:
        _begin_cmdb_read_snapshot(conn)
        generation = _cmdb_cache_generation(conn, ('vlans', 'bindings', 'interfaces'))
        scope = {'role': str(user.get('role') or '')}
        query = {
            'vlan_pk': vlan_pk,
            'site_id': site_id,
            'device_id': device_id,
        }
        data, cache_state = _cached_cmdb_projection(
            'vlan_details', generation, scope, query,
            lambda: cmdb_service.get_vlan_details(
                conn,
                vlan_pk,
                site_id=site_id,
                device_id=device_id,
            ),
        )
        if isinstance(data, dict) and isinstance(data.get('meta'), dict):
            data['meta']['cache_state'] = cache_state
        if response is not None:
            response.headers['X-CMDB-Cache'] = cache_state
        return {'success': True, 'data': data, 'message': ''}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    finally:
        conn.close()


@router.post("/cmdb/vlans", status_code=201)
def api_create_vlan(body: VlanCreate, user=require_role("Operator")):
    conn = get_db_connection()
    try:
        payload = body.model_dump()
        payload['tenant_id'] = tenant_id_for_write(requested=payload.get('tenant_id'), user=user)
        v = cmdb_service.create_vlan(conn, **payload)
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
        payload = body.model_dump(exclude_unset=True)
        payload.pop('tenant_id', None)
        v = cmdb_service.update_vlan(conn, vlan_pk, **payload)
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
    q: str = Query('', max_length=100),
    status: str = Query('', max_length=16),
    page: Optional[int] = Query(None, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    response: Response = None,
    user=require_role("Viewer"),
):
    if status and status not in {'active', 'planned', 'retired'}:
        raise HTTPException(status_code=422, detail="status must be active, planned, retired, or empty")
    conn = get_db_connection()
    try:
        _begin_cmdb_read_snapshot(conn)
        scope = {'role': str(user.get('role') or '')}
        query = {
            'site_id': site_id,
            'vrf_id': vrf_id,
            'vlan_id': vlan_id,
            'q': q.strip(),
            'status': status,
            'page': page,
            'page_size': page_size,
        }
        generation = _cmdb_cache_generation(conn, ('bindings',))
        data, cache_state = _cached_cmdb_projection(
            'bindings', generation, scope, query,
            lambda: cmdb_service.list_vlan_business_bindings(
                conn,
                site_id=site_id,
                vrf_id=vrf_id,
                vlan_id=vlan_id,
                q=q,
                status=status,
                page=page,
                page_size=page_size,
            )
        )
        if isinstance(data, dict):
            data['meta'] = _cmdb_projection_meta(conn, generation, cache_state, ())
        if response is not None:
            response.headers['X-CMDB-Cache'] = cache_state
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
