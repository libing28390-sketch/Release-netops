"""API routes for device inspection (巡检管理)."""

from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import FileResponse
import os
import tempfile

from core.rbac import require_role
from core.report_generator import generate_inspection_excel
from schemas.schemas import InspectionRunRequest, InspectionScheduleCreate, InspectionScheduleUpdate, InspectionItemCreate
from services.inspection_service import (
    compare_runs,
    create_schedule,
    delete_schedule,
    get_device_inspection_history,
    get_inspection_run_detail,
    get_inspection_runs,
    list_schedules,
    run_inspection,
    update_schedule,
    list_inspection_items,
    create_inspection_item,
    update_inspection_item,
    delete_inspection_item,
)

router = APIRouter()


# ─── 巡检计划（必须在 {run_id} 之前注册，避免路由遮蔽） ───

@router.get('/inspections/schedules')
def get_schedules(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _user=require_role('Viewer'),
):
    data = list_schedules(limit=limit, offset=offset)
    return {'success': True, 'data': data, 'message': ''}


@router.post('/inspections/schedules')
def add_schedule(
    body: InspectionScheduleCreate,
    user=require_role('Operator'),
):
    data = create_schedule(
        name=body.name,
        cron_expr=body.cron_expr,
        scope_type=body.scope_type,
        scope_filter=body.scope_filter,
        created_by=user.get('username', 'unknown'),
        scheduled_at=body.scheduled_at,
        expires_at=body.expires_at,
        description=body.description,
    )
    return {'success': True, 'data': data, 'message': '巡检计划已创建'}


@router.put('/inspections/schedules/{schedule_id}')
def modify_schedule(
    schedule_id: str,
    body: InspectionScheduleUpdate,
    _user=require_role('Operator'),
):
    updates = body.model_dump(exclude_none=True)
    result = update_schedule(schedule_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail='计划不存在')
    return {'success': True, 'data': result, 'message': '巡检计划已更新'}


@router.delete('/inspections/schedules/{schedule_id}')
def remove_schedule(
    schedule_id: str,
    _user=require_role('Administrator'),
):
    deleted = delete_schedule(schedule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail='计划不存在')
    return {'success': True, 'data': None, 'message': '巡检计划已删除'}


# ─── 巡检执行 ─────────────────────────

@router.post('/inspections/run')
def trigger_inspection(
    body: InspectionRunRequest,
    user=require_role('Operator'),
):
    result = run_inspection(
        scope_type=body.scope_type,
        scope_filter=body.scope_filter,
        trigger_type='manual',
        created_by=user.get('username', 'unknown'),
    )
    if not result.get('success'):
        raise HTTPException(status_code=400, detail=result.get('message', '巡检失败'))
    return {'success': True, 'data': result, 'message': '巡检完成'}


@router.get('/inspections')
def list_inspection_runs(
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user=require_role('Viewer'),
):
    data = get_inspection_runs(limit=limit, offset=offset)
    return {'success': True, 'data': data, 'message': ''}


@router.get('/inspections/device/{device_id}/history')
def device_inspections(
    device_id: str,
    limit: int = Query(10, ge=1, le=50),
    _user=require_role('Viewer'),
):
    history = get_device_inspection_history(device_id, limit=limit)
    return {'success': True, 'data': history, 'message': ''}


@router.get('/inspections/compare')
def compare_inspection_runs(
    run_a: str = Query(..., description='第一次巡检 ID'),
    run_b: str = Query(..., description='第二次巡检 ID'),
    _user=require_role('Viewer'),
):
    result = compare_runs(run_a, run_b)
    return {'success': True, 'data': result, 'message': ''}


# ──────────────────────────────────────────────
# 巡检指标管理 (Inspection Items)
# ──────────────────────────────────────────────

@router.get('/inspections/items/all')
def get_all_inspection_items(
    _user=require_role('Viewer'),
):
    items = list_inspection_items()
    return {'success': True, 'data': items, 'message': ''}

@router.post('/inspections/items')
def add_inspection_item(
    body: InspectionItemCreate,
    _user=require_role('Operator'),
):
    item = create_inspection_item(body.model_dump())
    return {'success': True, 'data': item, 'message': '巡检指标已创建'}

@router.put('/inspections/items/{item_id}')
def update_item(
    item_id: str,
    body: dict,
    _user=require_role('Operator'),
):
    item = update_inspection_item(item_id, body)
    if not item:
        raise HTTPException(status_code=404, detail='指标不存在')
    return {'success': True, 'data': item, 'message': '指标已更新'}

@router.delete('/inspections/items/{item_id}')
def remove_item(
    item_id: str,
    _user=require_role('Operator'),
):
    ok = delete_inspection_item(item_id)
    return {'success': ok, 'message': '指标已删除' if ok else '删除失败'}


# ⚠️ {run_id} 路径参数路由放最后，避免遮蔽上方字面路由
@router.get('/inspections/{run_id}')
def inspection_run_detail(
    run_id: str,
    _user=require_role('Viewer'),
):
    detail = get_inspection_run_detail(run_id)
    if not detail:
        raise HTTPException(status_code=404, detail='巡检记录不存在')
    return {'success': True, 'data': detail, 'message': ''}

@router.get('/inspections/{run_id}/export')
def export_inspection_report(
    run_id: str,
    _user=require_role('Viewer'),
):
    detail = get_inspection_run_detail(run_id)
    if not detail:
        raise HTTPException(status_code=404, detail='巡检记录不存在')
    
    # 准备数据
    results = detail.pop('results', [])
    
    # 创建临时文件
    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.xlsx', prefix=f'inspection_{run_id}_')
    os.close(tmp_fd)
    
    try:
        generate_inspection_excel(detail, results, tmp_path)
        return FileResponse(
            tmp_path,
            filename=f"Nexora_Inspection_{run_id}_{datetime.now().strftime('%Y%m%d')}.xlsx",
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            background=None # FileResponse handles cleanup if we want, but simple here
        )
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise HTTPException(status_code=500, detail=f"报表生成失败: {str(e)}")

from datetime import datetime # Ensure datetime is available


@router.post('/inspections/parse-output')
def parse_inspection_output(
    payload: dict = Body(...),
    _user=require_role('Viewer'),
):
    """
    通用 TextFSM 解析端点（不依赖 execution_id / device_id）。
    请求体：{ "platform": "cisco_ios", "command": "show version", "output": "..." }
    供巡检详情页的每个命令块调用，返回结构化解析结果。
    """
    from core.textfsm import parse_with_textfsm, _find_template

    platform = (payload.get('platform') or '').strip()
    command = (payload.get('command') or '').strip()
    raw_output = (payload.get('output') or '').strip()

    if not platform or not command:
        return {'success': False, 'message': '需要提供 platform 和 command 参数', 'data': None}

    if not raw_output:
        return {'success': False, 'message': '没有可解析的输出内容', 'data': None}

    template_path = _find_template(platform, command)
    if not template_path:
        return {
            'success': False,
            'message': f'未找到 {platform} / {command} 的解析模板',
            'data': None,
            'has_template': False,
        }

    records = parse_with_textfsm(platform, command, raw_output)
    if not records:
        return {
            'success': True,
            'message': '模板匹配为空，请检查输出格式是否与模板一致',
            'data': {'records': [], 'count': 0, 'fields': []},
        }

    fields = list(records[0].keys()) if records else []
    return {
        'success': True,
        'message': f'解析成功，共 {len(records)} 条记录',
        'data': {'records': records, 'count': len(records), 'fields': fields},
    }
