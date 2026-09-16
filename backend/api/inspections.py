"""API routes for device inspection (巡检管理)."""

from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import FileResponse
import os
import tempfile
import logging

logger = logging.getLogger(__name__)

from core.rbac import require_role
from core.report_generator import (
    generate_inspection_excel,
    generate_inspection_html,
    generate_inspection_json,
    generate_inspection_pdf,
)
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
from database import get_db_connection
import json
import uuid
from datetime import datetime, timezone, timedelta

_BEIJING_TZ = timezone(timedelta(hours=8))
def _beijing_now_iso() -> str:
    return datetime.now(_BEIJING_TZ).isoformat(timespec='seconds')

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
        use_admin_creds=body.use_admin_creds,
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
    q: str = Query('', description='Search inspection item fields'),
    category: str = Query('', description='Filter by category'),
    method: str = Query('', description='Filter by method'),
    vendor: str = Query('', description='Filter by vendor'),
    page: int | None = Query(None, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _user=require_role('Viewer'),
):
    items = list_inspection_items(
        q=q,
        category=category,
        method=method,
        vendor=vendor,
        page=page,
        page_size=page_size,
    )
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


# ─── 历史趋势 API（R5.1–R5.4, R5.8）───

@router.get('/inspections/device/{device_id}/trend')
def get_device_metric_trend(
    device_id: str,
    metric: str = Query(..., description='指标 check_key'),
    days: int = Query(30, ge=1, le=90),
    run_limit: int = Query(100, ge=1, le=500),
    _user=require_role('Viewer'),
):
    """R5: 返回指定设备指定指标的历史趋势数据。"""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            '''SELECT checked_at, metrics_json FROM inspection_results
               WHERE device_id = ?
                 AND checked_at >= datetime('now', ?)
               ORDER BY checked_at ASC
               LIMIT ?''',
            (device_id, f'-{days} days', run_limit)
        ).fetchall()

        series = []
        for row in rows:
            try:
                metrics = json.loads(row['metrics_json'] or '{}')
            except (json.JSONDecodeError, TypeError):
                continue
            val = metrics.get(metric)
            # R5.8: 过滤无效点（{value: null, error: ...} 结构）
            if val is None:
                continue
            if isinstance(val, dict):
                continue  # error structure
            try:
                numeric_val = float(val)
            except (TypeError, ValueError):
                continue
            series.append({'ts': row['checked_at'], 'value': numeric_val})

        # R5.4: 判断是否首次巡检
        first_inspection = len(rows) == 0

        # 获取指标单位（从 inspection_items 表）
        unit = ''
        try:
            item_row = conn.execute(
                "SELECT name_zh FROM inspection_items WHERE check_key = ? LIMIT 1",
                (metric,)
            ).fetchone()
            if item_row:
                # 简单推断单位
                name = item_row['name_zh'] or ''
                if '率' in name or '利用率' in name:
                    unit = '%'
                elif '温度' in name:
                    unit = '°C'
                elif '数' in name or '计数' in name:
                    unit = '个'
        except Exception:
            pass

        return {
            'device_id': device_id,
            'metric': metric,
            'unit': unit,
            'first_inspection': first_inspection,
            'series': series,
        }
    finally:
        conn.close()


# ─── 关联规则 CRUD（R4.5）─── 必须在 {run_id} 之前注册

@router.get('/inspections/correlation-rules')
def list_correlation_rules(_user=require_role('Viewer')):
    conn = get_db_connection()
    try:
        rows = conn.execute('SELECT * FROM inspection_correlation_rules ORDER BY created_at DESC').fetchall()
        return {'success': True, 'data': [dict(r) for r in rows]}
    finally:
        conn.close()


@router.post('/inspections/correlation-rules')
def create_correlation_rule(body: dict = Body(...), _user=require_role('Operator')):
    conn = get_db_connection()
    try:
        rule_id = str(uuid.uuid4())
        now = _beijing_now_iso()
        conn.execute(
            '''INSERT INTO inspection_correlation_rules
                (id, name, name_zh, description, severity, suggestion, conditions_json, enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                rule_id,
                body.get('name', ''),
                body.get('name_zh', ''),
                body.get('description', ''),
                body.get('severity', 'warning'),
                body.get('suggestion', ''),
                json.dumps(body.get('conditions', []), ensure_ascii=False),
                1 if body.get('enabled', True) else 0,
                now, now,
            )
        )
        conn.commit()
        return {'success': True, 'data': {'id': rule_id}, 'message': '关联规则已创建'}
    finally:
        conn.close()


@router.put('/inspections/correlation-rules/{rule_id}')
def update_correlation_rule(rule_id: str, body: dict = Body(...), _user=require_role('Operator')):
    conn = get_db_connection()
    try:
        existing = conn.execute('SELECT * FROM inspection_correlation_rules WHERE id=?', (rule_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail='规则不存在')
        allowed = {'name', 'name_zh', 'description', 'severity', 'suggestion', 'conditions', 'enabled'}
        sets = []
        params = []
        for k, v in body.items():
            if k in allowed:
                if k == 'conditions':
                    sets.append('conditions_json=?')
                    params.append(json.dumps(v, ensure_ascii=False))
                elif k == 'enabled':
                    sets.append('enabled=?')
                    params.append(1 if v else 0)
                else:
                    sets.append(f'{k}=?')
                    params.append(v)
        if not sets:
            return {'success': True, 'data': dict(existing), 'message': '无变更'}
        sets.append('updated_at=?')
        params.append(_beijing_now_iso())
        params.append(rule_id)
        conn.execute(f'UPDATE inspection_correlation_rules SET {", ".join(sets)} WHERE id=?', tuple(params))
        conn.commit()
        updated = conn.execute('SELECT * FROM inspection_correlation_rules WHERE id=?', (rule_id,)).fetchone()
        return {'success': True, 'data': dict(updated), 'message': '规则已更新'}
    finally:
        conn.close()


@router.delete('/inspections/correlation-rules/{rule_id}')
def delete_correlation_rule(rule_id: str, _user=require_role('Operator')):
    conn = get_db_connection()
    try:
        cursor = conn.execute('DELETE FROM inspection_correlation_rules WHERE id=?', (rule_id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail='规则不存在')
        return {'success': True, 'message': '规则已删除'}
    finally:
        conn.close()


def _get_system_name() -> str:
    system_name = "Nexora"
    try:
        from database import get_db_connection
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT value FROM system_settings WHERE key = 'platform_settings'"
            ).fetchone()
            if row:
                import json as _json
                val = row[0] if isinstance(row, (list, tuple)) else row['value']
                ps = _json.loads(val)
                if ps.get('system_name'):
                    system_name = ps['system_name']
        finally:
            conn.close()
    except Exception:
        pass
    return system_name


# ⚠️ {run_id} 路径参数路由放最后，避免遮蔽上方字面路由

@router.get('/inspections/{run_id}/export')
def export_inspection_report(
    run_id: str,
    format: str = Query('xlsx', pattern='^(xlsx|html|json|pdf)$', description='导出格式: xlsx, html, json 或 pdf'),
    source: str = Query('inspection', description='数据源: inspection 或 playbook'),
    customer_name: str = Query('', description='客户名称（HTML/PDF 报表）'),
    engineer_name: str = Query('', description='工程师名称（HTML/PDF 报表）'),
    _user=require_role('Viewer'),
):
    """
    R7.1: 支持 format 参数 (xlsx, html, json, pdf)
    R7.7: 文件名格式 Nexora_Inspection_{run_id}_{YYYYMMDD}.{ext}
    """
    conn = get_db_connection()
    try:
        if source == 'playbook':
            # --- PLAYBOOK TO INSPECTION MAPPING ---
            row = conn.execute('SELECT * FROM playbook_executions WHERE id = ?', (run_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail='Playbook 记录不存在')
            
            detail = dict(row)
            # Fetch device results
            dev_rows = conn.execute('SELECT * FROM execution_device_results WHERE execution_id = ?', (run_id,)).fetchall()
            results = []
            
            # Intelligent Parsing (replicates frontend logic in backend for PDF/HTML support)
            from core.textfsm import parse_with_textfsm
            
            total_score = 0
            for dr in dev_rows:
                dr_dict = dict(dr)
                
                # 联查真实的 platform 和 role (解决 execution_device_results 表中无对应字段导致的通用设备回退)
                dev_id = dr_dict.get('device_id')
                ip_addr = dr_dict.get('ip_address')
                dev_row = None
                if dev_id:
                    dev_row = conn.execute("SELECT platform, role FROM devices WHERE id = ?", (dev_id,)).fetchone()
                if not dev_row and ip_addr:
                    dev_row = conn.execute("SELECT platform, role FROM devices WHERE ip_address = ?", (ip_addr,)).fetchone()
                
                if dev_row:
                    dr_dict['platform'] = dev_row['platform'] or dr_dict.get('platform', '')
                    dr_dict['role'] = dev_row['role'] or dr_dict.get('role', '')

                phases = {}
                try: phases = json.loads(dr_dict.get('phases_json') or '{}')
                except: pass
                
                metrics = {}
                findings = []
                score = 100

                status_str = str(dr_dict.get('status') or '').strip().lower()
                is_failed = (status_str in ('failed', 'error')) or ('fail' in status_str)
                err_msg = dr_dict.get('error_message') or ''

                for p_name, p_data in phases.items():
                    if isinstance(p_data, dict):
                        p_st = str(p_data.get('status') or '').strip().lower()
                        if p_st in ('failed', 'error') or 'fail' in p_st:
                            is_failed = True
                            if not err_msg and p_data.get('output'):
                                err_msg = str(p_data.get('output')).strip()
                        output = p_data.get('output', '')
                        if not isinstance(output, str): output = str(output)
                        
                        if 'show version' in output.lower() or 'display version' in output.lower():
                            recs = parse_with_textfsm(dr_dict.get('platform', 'cisco_ios'), 'show version', output)
                            if recs: metrics['version'] = recs[0]
                        
                        if 'error' in output.lower() or 'drop' in output.lower():
                            findings.append({'severity': 'warning', 'item': '接口异常检查', 'message': '接口出现 error/drop 丢包', 'description': '命令输出中含有 error/drop 关键字，可能存在潜在风险。'})
                            score -= 5

                if is_failed:
                    score = 0
                    findings.append({
                        'severity': 'critical',
                        'item': '设备连接与作业状态',
                        'message': f"作业执行失败 ({err_msg or '设备连接超时或被拒绝'})",
                        'description': f"异常原因: {err_msg or '无法连接到远程设备端口，网络不在线或连接超时。'}"
                    })

                final_score = max(0, score)
                dr_dict['metrics_json'] = json.dumps(metrics)
                dr_dict['findings_json'] = json.dumps(findings, ensure_ascii=False)
                dr_dict['health_score'] = final_score
                dr_dict['health_status'] = 'healthy' if final_score >= 90 else ('warning' if final_score >= 70 else 'critical')
                total_score += final_score
                results.append(dr_dict)
            
            detail['results'] = results
            detail['avg_health_score'] = round(total_score / len(results), 1) if results else 100
            detail['total_devices'] = len(results)
            detail['started_at'] = detail.get('started_at') or detail.get('created_at')
            detail['report_type'] = 'playbook'
            detail['name'] = detail.get('scenario_name') or detail.get('playbook_name') or detail.get('name') or 'Playbook 自动化执行'
        else:
            detail = get_inspection_run_detail(run_id)
            if not detail:
                raise HTTPException(status_code=404, detail='巡检记录不存在')
            results = detail.pop('results', [])
            detail['report_type'] = 'inspection'
            detail['name'] = detail.get('name') or '例行网络巡检'
    finally:
        conn.close()

    today = datetime.now().strftime('%Y%m%d')
    ext = format
    media_type = 'application/octet-stream'
    
    if format == 'xlsx':
        suffix = '.xlsx'
        media_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    elif format == 'html':
        suffix = '.html'
        media_type = 'text/html'
    elif format == 'json':
        suffix = '.json'
        media_type = 'application/json'
    elif format == 'pdf':
        suffix = '.pdf'
        media_type = 'application/pdf'
    else:
        raise HTTPException(status_code=400, detail="不支持的导出格式")

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix=f'inspection_{run_id}_')
    os.close(tmp_fd)

    try:
        if format == 'xlsx':
            generate_inspection_excel(detail, results, tmp_path)
        elif format == 'html':
            generate_inspection_html(detail, results, tmp_path, customer_name, engineer_name)
        elif format == 'json':
            generate_inspection_json(detail, results, tmp_path)
        elif format == 'pdf':
            generate_inspection_pdf(detail, results, tmp_path, customer_name, engineer_name)
            
        sys_name = _get_system_name()
        return FileResponse(
            tmp_path,
            filename=f"{sys_name}_Inspection_{run_id}_{today}.{ext}",
            media_type=media_type,
        )
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        logger.error(f"Report generation failed for {format}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"报表生成失败 ({format}): {str(e)}")


@router.get('/inspections/{run_id}')
def inspection_run_detail(
    run_id: str,
    _user=require_role('Viewer'),
):
    detail = get_inspection_run_detail(run_id)
    if not detail:
        raise HTTPException(status_code=404, detail='巡检记录不存在')
    return {'success': True, 'data': detail, 'message': ''}

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
