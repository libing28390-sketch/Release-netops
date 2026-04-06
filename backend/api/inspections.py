"""API routes for device inspection (巡检管理)."""

from fastapi import APIRouter, HTTPException, Query

from core.rbac import require_role
from schemas.schemas import InspectionRunRequest, InspectionScheduleCreate, InspectionScheduleUpdate
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
)

router = APIRouter()


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
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _user=require_role('Viewer'),
):
    data = get_inspection_runs(limit=limit, offset=offset)
    return {'success': True, 'data': data, 'message': ''}


@router.get('/inspections/{run_id}')
def inspection_run_detail(
    run_id: str,
    _user=require_role('Viewer'),
):
    detail = get_inspection_run_detail(run_id)
    if not detail:
        raise HTTPException(status_code=404, detail='巡检记录不存在')
    return {'success': True, 'data': detail, 'message': ''}


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


# ─── 巡检计划 ─────────────────────────

@router.get('/inspections/schedules')
def get_schedules(
    _user=require_role('Viewer'),
):
    data = list_schedules()
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
