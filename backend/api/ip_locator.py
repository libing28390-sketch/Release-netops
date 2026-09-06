"""
IP Locator API — 根据 IP 地址实时定位设备所在交换机端口。
"""

import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from schemas.schemas import IPLocateRequest, ConnectivityProbeRequest, PathDiagnoseRequest
from core.rbac import require_role
from services.ip_locator_service import (
    locate_ip_async_with_options,
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

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post('/ip-locator/locate')
async def api_locate_ip(body: IPLocateRequest, user=require_role("Viewer")):
    """实时查询 IP 所在物理端口位置。"""
    try:
        result = await locate_ip_async_with_options(body.ip, body.force_refresh)
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
