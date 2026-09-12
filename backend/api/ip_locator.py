"""
IP Locator API — 根据 IP 地址实时定位设备所在交换机端口。
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, BackgroundTasks
from schemas.schemas import IPLocateRequest, IPLocatorRunRequest, ConnectivityProbeRequest, PathDiagnoseRequest
from core.config import settings
from core.rbac import authorize_resource, require_role
from database import get_db_connection
from services.ip_locator_service import (
    get_arp_table_async,
    run_arp_sweep_async,
    get_mac_changes_async,
    get_network_endpoints_async,
    get_ip_inventory_async,
    get_route_cache_async,
    get_routing_neighbors_async,
    get_bgp_routes_async
)
from services.connectivity_service import run_probe_async
from services.diagnose_service import run_diagnose_async
from services.audit_service import log_audit_event
from services.ip_locator_trace_service import add_legacy_compatibility, trace_ip_async

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post('/ip-locator/trace')
async def api_trace_ip(body: IPLocatorRunRequest, user=require_role("Viewer")):
    """Run the bounded four-stage CLI-only IP trace.

    The legacy ``/locate`` endpoint remains available for older clients.  The
    new endpoint exposes the explicit L3 -> ARP -> MAC -> topology contract
    and never invokes SNMP.  Blocking device I/O is moved off the event loop.
    """
    try:
        if body.network_domain_id:
            raise HTTPException(status_code=422, detail={
                'code': 'NETWORK_DOMAIN_SCOPE_UNSUPPORTED',
                'message': '当前 CMDB 尚无可核验的网络域绑定，请先按站点和 VRF 查询',
            })
        authorized_device_ids = await asyncio.to_thread(
            _authorized_locator_device_ids,
            user,
            site_id=body.site_id,
        )
        if not authorized_device_ids:
            raise HTTPException(status_code=404, detail='当前租户/站点范围内没有可访问的在线网络设备')
        if body.start_device_id and body.start_device_id not in set(authorized_device_ids):
            raise HTTPException(status_code=404, detail='指定起始设备不存在或超出当前授权范围')
        result = await trace_ip_async(
            body.ip,
            tenant_id=str(user.get('tenant_id') or 'tenant-default'),
            start_device_id=body.start_device_id,
            site_id=body.site_id,
            network_domain_id=body.network_domain_id,
            vrf=body.vrf or 'default',
            force_refresh=body.force_refresh,
            route_fresh_seconds=int(getattr(settings, 'IP_LOCATOR_ROUTE_FRESH_SECONDS', 300)),
            deadline_seconds=int(getattr(settings, 'IP_LOCATOR_TASK_DEADLINE_SECONDS', 180)),
            authorized_device_ids=authorized_device_ids,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error('[IPLocatorV2] trace failed for %s: %s', body.ip, type(exc).__name__)
        raise HTTPException(status_code=500, detail='IP 定位查询失败')

    log_audit_event(
        event_type='ip_locator.trace',
        category='network',
        severity='info',
        status=str(result.get('status') or 'failed'),
        summary=f"IP trace: {body.ip} → {result.get('conclusion') or 'unknown'}",
        actor_username=user.get('username'),
        actor_role=user.get('role'),
        target_type='ip_address',
        target_name=body.ip,
    )
    return result


@router.get('/ip-locator/health')
async def api_ip_locator_health(user=require_role("Viewer")):
    """Return safe cache/feature health without exposing Redis credentials."""
    del user
    try:
        from services.ip_locator_cache_service import get_locator_cache

        cache = get_locator_cache()
        redis_health = await cache.ahealth_summary(probe=True)
    except Exception as exc:
        logger.debug('[IPLocatorV2] cache health unavailable: %s', type(exc).__name__)
        redis_health = {
            'backend': 'unknown',
            'configured': False,
            'available': False,
            'degraded': True,
            'status': 'unavailable',
        }
    try:
        from services.ip_locator_session_pool import get_ip_locator_session_pool

        session_pool = get_ip_locator_session_pool().snapshot()
    except Exception as exc:
        logger.debug('[IPLocatorV2] CLI session pool health unavailable: %s', type(exc).__name__)
        session_pool = {
            'active_sessions': 0,
            'active_commands': 0,
            'idle_timeout_seconds': int(getattr(settings, 'IP_LOCATOR_CLI_IDLE_SECONDS', 15)),
            'max_sessions': int(getattr(settings, 'IP_LOCATOR_CLI_GLOBAL_CONCURRENCY', 5)),
        }
    return {
        'feature_enabled': True,
        'transport': 'ssh_cli_only',
        'snmp_used': False,
        'redis': redis_health,
        'ssh_session_pool': session_pool,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


def _authorized_locator_device_ids(
    user: dict,
    *,
    site_id: str = "",
    online_only: bool = True,
) -> list[str]:
    """Resolve tenant and explicit asset/site scopes to visible devices."""
    tenant_id = str(user.get('tenant_id') or '').strip()
    if not tenant_id:
        return []
    conn = get_db_connection()
    try:
        status_clause = " AND status = 'online'" if online_only else ""
        rows = conn.execute(
            """SELECT id, tenant_id, site_id, site, device_group_id
                 FROM devices
                WHERE tenant_id = ?""" + status_clause + """
                ORDER BY id""",
            (tenant_id,),
        ).fetchall()
    finally:
        conn.close()

    requested_site = str(site_id or '').strip().lower()
    allowed: list[str] = []
    authorization_cache: dict[tuple[str, str, str], bool] = {}
    for raw in rows:
        item = dict(raw)
        device_site = str(item.get('site_id') or item.get('site') or '').strip()
        if requested_site and device_site.lower() != requested_site:
            continue
        authorization_key = (
            str(item.get('tenant_id') or ''),
            device_site,
            str(item.get('device_group_id') or ''),
        )
        if authorization_key not in authorization_cache:
            authorization_cache[authorization_key] = authorize_resource(
                user,
                'asset',
                'read',
                tenant_id=authorization_key[0],
                site_id=authorization_key[1],
                device_group_id=authorization_key[2],
            )
        if authorization_cache[authorization_key]:
            allowed.append(str(item.get('id') or ''))
    return [device_id for device_id in allowed if device_id]


def _locator_scope_hash(body: IPLocatorRunRequest, user: dict, authorized_device_ids: list[str]) -> str:
    try:
        from services.ip_locator_cache_service import IPLocatorCacheService

        return IPLocatorCacheService.scope_hash({
            'tenant_id': str(user.get('tenant_id') or 'tenant-default'),
            'site_id': body.site_id,
            'network_domain_id': body.network_domain_id,
            'vrf': body.vrf or 'default',
            'start_device_id': body.start_device_id,
            'authorized_device_ids': sorted(authorized_device_ids),
        })
    except Exception:
        return ''


def _execute_locator_run_background(run_id: str) -> None:
    """Execute one durable run after the 202 response has been returned."""
    from services.ip_locator_run_worker_service import run_locator_run_by_id

    run_locator_run_by_id(run_id)


async def _locator_run_is_currently_authorized(run: dict, user: dict) -> bool:
    """Revalidate a durable run against the caller's current asset scope."""
    if not isinstance(run, dict) or not isinstance(user, dict):
        return False

    run_tenant_id = str(run.get('tenant_id') or '').strip()
    user_tenant_id = str(user.get('tenant_id') or '').strip()
    site_id = run.get('site_id')
    if not run_tenant_id or run_tenant_id != user_tenant_id or not isinstance(site_id, str):
        return False

    stats = run.get('stats')
    if isinstance(stats, str):
        try:
            stats = json.loads(stats)
        except (TypeError, ValueError):
            return False
    if not isinstance(stats, dict):
        return False

    original_device_ids = stats.get('authorized_device_ids')
    if not isinstance(original_device_ids, list) or not original_device_ids:
        return False
    if any(not isinstance(device_id, str) or not device_id.strip() for device_id in original_device_ids):
        return False
    original_device_ids = {device_id.strip() for device_id in original_device_ids}

    try:
        current_device_ids = await asyncio.to_thread(
            _authorized_locator_device_ids,
            user,
            site_id=site_id,
            online_only=False,
        )
    except Exception as exc:
        logger.debug('[IPLocatorV2] run authorization check failed: %s', type(exc).__name__)
        return False
    if not isinstance(current_device_ids, (list, tuple, set)):
        return False
    if any(not isinstance(device_id, str) or not device_id.strip() for device_id in current_device_ids):
        return False
    current_device_ids = {
        device_id.strip() for device_id in current_device_ids
    }
    return original_device_ids.issubset(current_device_ids)


@router.post('/ip-locator/runs', status_code=202)
async def api_create_locator_run(body: IPLocatorRunRequest, background_tasks: BackgroundTasks, user=require_role("Viewer")):
    """Queue a durable four-stage CLI trace and return a pollable run."""
    if body.network_domain_id:
        raise HTTPException(status_code=422, detail={
            'code': 'NETWORK_DOMAIN_SCOPE_UNSUPPORTED',
            'message': '当前 CMDB 尚无可核验的网络域绑定，请先按站点和 VRF 查询',
        })
    try:
        from services.ip_locator_task_service import create_locator_run

        owner_id = str(user.get('id') or user.get('user_id') or user.get('username') or '')
        authorized_device_ids = await asyncio.to_thread(
            _authorized_locator_device_ids,
            user,
            site_id=body.site_id,
        )
        if not authorized_device_ids:
            raise HTTPException(status_code=404, detail='当前租户/站点范围内没有可访问的在线网络设备')
        if body.start_device_id and body.start_device_id not in set(authorized_device_ids):
            raise HTTPException(status_code=404, detail='指定起始设备不存在或超出当前授权范围')
        scope_hash = _locator_scope_hash(body, user, authorized_device_ids)
        run = create_locator_run(
            owner_id=owner_id,
            target_ip=body.ip,
            tenant_id=str(user.get('tenant_id') or 'tenant-default'),
            scope_hash=scope_hash,
            network_domain_id=body.network_domain_id,
            site_id=body.site_id,
            vrf_name=body.vrf or 'default',
            start_device_id=body.start_device_id,
            force_refresh=body.force_refresh,
            authorization_scope_hash=scope_hash,
            deadline_seconds=int(getattr(settings, 'IP_LOCATOR_TASK_DEADLINE_SECONDS', 180)),
            initial_stats={'authorized_device_ids': authorized_device_ids},
        )
        background_tasks.add_task(_execute_locator_run_background, str(run.get('id') or ''))
        return run
    except HTTPException:
        raise
    except Exception as exc:
        logger.error('[IPLocatorV2] run creation failed: %s', type(exc).__name__)
        raise HTTPException(status_code=503, detail='IP 定位任务暂不可用')


@router.get('/ip-locator/runs/{run_id}')
async def api_get_locator_run(run_id: str, user=require_role("Viewer")):
    try:
        from services.ip_locator_task_service import get_locator_run

        owner_id = str(user.get('id') or user.get('user_id') or user.get('username') or '')
        run = get_locator_run(run_id, owner_id=owner_id)
        if run is not None and not await _locator_run_is_currently_authorized(run, user):
            run = None
    except Exception as exc:
        logger.debug('[IPLocatorV2] run read failed: %s', type(exc).__name__)
        run = None
    if run is None:
        raise HTTPException(status_code=404, detail='定位任务不存在或无权访问')
    return run


@router.post('/ip-locator/runs/{run_id}/cancel')
async def api_cancel_locator_run(run_id: str, user=require_role("Viewer")):
    try:
        from services.ip_locator_task_service import cancel_locator_run, get_locator_run

        owner_id = str(user.get('id') or user.get('user_id') or user.get('username') or '')
        run = get_locator_run(run_id, owner_id=owner_id)
        if run is not None and await _locator_run_is_currently_authorized(run, user):
            run = cancel_locator_run(run_id, owner_id=owner_id)
        else:
            run = None
    except Exception as exc:
        logger.debug('[IPLocatorV2] run cancel failed: %s', type(exc).__name__)
        run = None
    if run is None:
        raise HTTPException(status_code=404, detail='定位任务不存在或无权访问')
    return run


@router.post('/ip-locator/locate')
async def api_locate_ip(body: IPLocateRequest, user=require_role("Viewer")):
    """实时查询 IP 所在物理端口位置。"""
    try:
        authorized_device_ids = await asyncio.to_thread(
            _authorized_locator_device_ids,
            user,
        )
        trace_result = await trace_ip_async(
            body.ip,
            tenant_id=str(user.get('tenant_id') or 'tenant-default'),
            force_refresh=body.force_refresh,
            route_fresh_seconds=int(getattr(settings, 'IP_LOCATOR_ROUTE_FRESH_SECONDS', 300)),
            authorized_device_ids=authorized_device_ids,
            deadline_seconds=int(getattr(settings, 'IP_LOCATOR_TASK_DEADLINE_SECONDS', 180)),
        )
        result = await asyncio.to_thread(add_legacy_compatibility, trace_result)
    except Exception as exc:
        logger.error(f"[IPLocator] locate failed for {body.ip}: {exc}")
        raise HTTPException(status_code=500, detail=f'IP 定位查询失败: {exc}')

    log_audit_event(
        event_type="ip_locator.locate",
        category="network",
        severity="info",
        status="success" if result.get('found') else "not_found",
        summary=f"IP locate: {body.ip} → {'found' if result.get('found') else 'not found'}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ip_address",
        target_name=body.ip,
    )
    return result


@router.get('/ip-locator/arp-table')
async def api_get_arp_table(user=require_role("Viewer")):
    """获取全量 ARP 缓存表，供前端展示。"""
    return await get_arp_table_async()


@router.post('/ip-locator/arp-sweep')
async def api_trigger_arp_sweep(user=require_role("Operator")):
    """手动触发一次全量 ARP 采集。"""
    try:
        sweep = await run_arp_sweep_async()
        table = await get_arp_table_async()
        collected = int((sweep or {}).get('collected_entries') or 0)
        eligible = int((sweep or {}).get('eligible_devices') or 0)
        device_results = (sweep or {}).get('device_results') or []
        failed = sum(1 for item in device_results if item.get('status') == 'failed')
        no_data = sum(1 for item in device_results if item.get('status') == 'no_data')
        if collected:
            suffix = f'其中 {failed} 台失败、{no_data} 台无条目。' if failed or no_data else ''
            message = f'本次从 {eligible} 台设备采集到 {collected} 条 ARP 记录，当前共 {table["total"]} 条。{suffix}'
        elif eligible:
            message = f'已检查 {eligible} 台设备，但本次没有解析到新的 ARP 记录（失败 {failed} 台、无条目 {no_data} 台）；当前表保留 {table["total"]} 条历史数据。'
        else:
            message = '当前没有配置可用于 ARP 采集的在线设备。'
        return {
            'success': True,
            'message': message,
            'data': table,
            'sweep': sweep or {},
        }
    except Exception as exc:
        logger.error(f"[ARP Sweep] manual trigger failed: {exc}")
        raise HTTPException(status_code=500, detail=f'ARP 采集失败: {exc}')


@router.post('/ip-locator/nsot-sweep')
async def api_trigger_nsot_sweep(background_tasks: BackgroundTasks, user=require_role("Operator")):
    """手动触发全量网络事实库同步任务（包括 ARP Sweep、交换机 MAC 采集、普通路由表采集、BGP 协议路由与邻居同步）。"""
    from services.ip_locator_service import run_unified_nsot_sync
    background_tasks.add_task(run_unified_nsot_sync)
    return {'success': True, 'message': '数据采集任务已在后台启动，同步过程可能需要 1~2 分钟，请稍后刷新查看。'}


@router.get('/ip-locator/mac-changes')
async def api_get_mac_changes(limit: int = 200, user=require_role("Viewer")):
    """获取 MAC 地址变更日志。"""
    return await get_mac_changes_async(min(limit, 1000))


@router.post('/ip-locator/probe')
async def api_connectivity_probe(body: ConnectivityProbeRequest, user=require_role("Viewer")):
    """全链路连通性探测：PING + TCP + Traceroute。"""
    try:
        result = await run_probe_async(
            target=body.target,
            tests=body.tests,
            tcp_ports=body.tcp_ports,
            source_device_id=body.source_device_id,
            source_interface=body.source_interface,
            ping_count=body.ping_count,
        )
    except Exception as exc:
        logger.error(f"[ConnProbe] probe failed for {body.target}: {exc}")
        raise HTTPException(status_code=500, detail=f'连通性探测失败: {exc}')

    log_audit_event(
        event_type="connectivity.probe",
        category="network",
        severity="info",
        status="success",
        summary=f"Connectivity probe: {body.target} tests={body.tests}",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ip_address",
        target_name=body.target,
    )
    return result


@router.post('/ip-locator/diagnose')
async def api_path_diagnose(body: PathDiagnoseRequest, user=require_role("Viewer")):
    """一键路径诊断。"""
    try:
        result = await run_diagnose_async(
            source_ip=body.source_ip,
            target_ip=body.target_ip,
            port=body.port,
            protocol=body.protocol,
            vrf=body.vrf,
            src_vrf=body.src_vrf,
        )
    except Exception:
        logger.exception("[PathDiagnose] diagnose failed")
        raise HTTPException(status_code=500, detail="路径诊断失败，请检查目标和管理面连通性")

    log_audit_event(
        event_type="path.diagnose",
        category="network",
        severity="info",
        status="success",
        summary=f"Path diagnose: {body.source_ip} -> {body.target_ip}:{body.port} [{body.protocol}]",
        actor_username=user.get("username"),
        actor_role=user.get("role"),
        target_type="ip_address",
        target_name=body.target_ip,
    )
    return result


@router.get('/ip-locator/network-endpoints')
async def api_get_network_endpoints(user=require_role("Viewer")):
    """查询网络终端事实库 (network_endpoints)。"""
    return await get_network_endpoints_async()


@router.get('/ip-locator/ip-inventory')
async def api_get_ip_inventory(user=require_role("Viewer")):
    """查询 IP 资产明细 (ip_inventory)。"""
    return await get_ip_inventory_async()


@router.get('/ip-locator/route-cache')
async def api_get_route_cache(user=require_role("Viewer")):
    """查询路由缓存表 (route_cache)。"""
    return await get_route_cache_async()


@router.get('/ip-locator/routing-neighbors')
async def api_get_routing_neighbors(user=require_role("Viewer")):
    """查询路由协议邻居事实库 (routing_neighbors)。"""
    return await get_routing_neighbors_async()


@router.get('/ip-locator/bgp-routes')
async def api_get_bgp_routes(user=require_role("Viewer")):
    """查询 BGP 专属路由表事实库 (bgp_route_table)。"""
    return await get_bgp_routes_async()
