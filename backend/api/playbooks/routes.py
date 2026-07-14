# -*- coding: utf-8 -*-
import uuid
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Body, Request, Query
from fastapi.responses import JSONResponse

from database import get_db_connection
from services.audit_service import log_audit_event
from core.crypto import decrypt_credential

from .builtin_scenarios import PLATFORMS
from .scenarios import (
    _all_scenarios,
    _normalize_playbook_platform,
    _render_phase_commands,
    resolve_platform_phases,
)
from .manager import ws_manager
from .engine import (
    _device_locks,
    _get_device_lock,
    _pending_rollbacks,
    _run_playbook
)

router = APIRouter()
logger = logging.getLogger("api.playbooks.routes")


@router.get("/playbooks/platforms")
async def list_platforms():
    """Return all supported vendor/platform definitions."""
    return PLATFORMS



@router.get("/playbooks/scenarios")
async def list_scenarios():
    """Return built-in and custom scenario templates."""
    return _all_scenarios()


@router.post("/playbooks/scenarios", status_code=201)
async def create_custom_scenario(request: Request, payload: dict = Body(...)):
    scenario_id = (payload.get('id') or '').strip() or f"custom-{uuid.uuid4().hex[:10]}"
    name = (payload.get('name') or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail='Scenario name is required')

    supported_platforms = payload.get('supported_platforms') or []
    if not supported_platforms:
        raise HTTPException(status_code=400, detail='At least one supported platform is required')

    default_platform = payload.get('default_platform') or supported_platforms[0]
    platform_phases = payload.get('platform_phases') or {}
    if default_platform not in platform_phases:
        raise HTTPException(status_code=400, detail='platform_phases must include the default platform')

    # Prevent ID conflicts with built-ins and existing custom scenarios
    all_ids = {s.get('id') for s in _all_scenarios()}
    if scenario_id in all_ids:
        raise HTTPException(status_code=409, detail='Scenario id already exists')

    now = datetime.now().isoformat()
    scenario_doc = {
        'id': scenario_id,
        'name': name,
        'name_zh': payload.get('name_zh') or name,
        'description': payload.get('description') or '',
        'description_zh': payload.get('description_zh') or payload.get('description') or '',
        'category': payload.get('category') or 'Custom',
        'icon': payload.get('icon') or '🧩',
        'risk': payload.get('risk') or 'medium',
        'supported_platforms': supported_platforms,
        'default_platform': default_platform,
        'variables': payload.get('variables') or [],
        'platform_phases': platform_phases,
        'is_custom': True,
    }

    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT INTO custom_scenarios (id, data_json, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
            (scenario_id, json.dumps(scenario_doc), payload.get('author', 'admin'), now, now)
        )
        conn.commit()
    finally:
        conn.close()

    log_audit_event(
        event_type='SCENARIO_CREATE',
        category='automation',
        severity='medium',
        status='success',
        summary=f"Created scenario {name}",
        actor_username=payload.get('author', 'admin'),
        actor_role=payload.get('actor_role') or 'Administrator',
        source_ip=request.client.host if request and request.client else None,
        target_type='scenario',
        target_id=scenario_id,
        target_name=name,
        details={'risk': scenario_doc['risk'], 'platforms': supported_platforms},
    )

    return scenario_doc


@router.get("/playbooks")
async def list_playbooks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    status: str = Query('all'),
    scenario: str = Query(''),
):
    """Return paginated playbook execution summaries (no bulky results_json / phases_json)."""
    conn = get_db_connection()
    try:
        where_clauses = []
        params: list = []
        if status != 'all':
            where_clauses.append("status = ?")
            params.append(status)
        if scenario:
            where_clauses.append("scenario_name LIKE ?")
            params.append(f"%{scenario}%")
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM playbook_executions {where_sql}", params
        ).fetchone()[0]
        logger.info(f"[Playbooks] Found {total} total executions (status={status}, scenario={scenario})")
        offset = (page - 1) * page_size
        rows = conn.execute(
            f'''SELECT id, scenario_id, scenario_name, platform, device_ids,
                       variables, status, dry_run, author, concurrency,
                       total_devices, success_count, failed_count, partial_count,
                       created_at, updated_at
                FROM playbook_executions {where_sql}
                ORDER BY created_at DESC LIMIT ? OFFSET ?''',
            [*params, page_size, offset]
        ).fetchall()
        items = []
        for r in rows:
            row_dict = dict(r)
            if not row_dict.get('total_devices'):
                try:
                    row_dict['total_devices'] = len(json.loads(row_dict.get('device_ids', '[]')))
                except Exception:
                    row_dict['total_devices'] = 0
            items.append(row_dict)
        return {"items": items, "total": total, "page": page, "page_size": page_size}
    finally:
        conn.close()

@router.get("/playbooks/{playbook_id}")
async def get_playbook(playbook_id: str):
    """Legacy endpoint — returns full row including results_json for backward compatibility."""
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT * FROM playbook_executions WHERE id = ?', (playbook_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Playbook execution not found")
        return dict(row)
    finally:
        conn.close()

@router.delete("/playbooks/{execution_id}")
async def delete_execution(execution_id: str):
    """Delete a playbook execution and its device results."""
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT id FROM playbook_executions WHERE id = ?', (execution_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Execution not found")
        conn.execute('DELETE FROM execution_device_results WHERE execution_id = ?', (execution_id,))
        conn.execute('DELETE FROM playbook_executions WHERE id = ?', (execution_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()

@router.get("/playbooks/{execution_id}/summary")
async def get_execution_summary(execution_id: str):
    """Return header-level summary for one execution (no device details)."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            '''SELECT id, scenario_name, platform, device_ids, status, dry_run, author,
                      total_devices, success_count, failed_count, partial_count,
                      created_at, updated_at
               FROM playbook_executions WHERE id = ?''',
            (execution_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Execution not found")
        d = dict(row)
        # Fallback: compute total_devices from device_ids for legacy records
        if not d.get('total_devices'):
            try:
                d['total_devices'] = len(json.loads(d.get('device_ids', '[]')))
            except Exception:
                d['total_devices'] = 0
        # Fallback: compute counts from execution_device_results or results_json for legacy records
        if not d.get('success_count') and not d.get('failed_count'):
            try:
                counts = conn.execute(
                    '''SELECT
                        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as sc,
                        SUM(CASE WHEN status IN ('failed','error') THEN 1 ELSE 0 END) as fc
                    FROM execution_device_results WHERE execution_id = ?''',
                    (execution_id,)
                ).fetchone()
                if counts and (counts['sc'] or counts['fc']):
                    d['success_count'] = counts['sc'] or 0
                    d['failed_count'] = counts['fc'] or 0
            except Exception:
                pass
        # Second fallback: parse results_json blob if counts still 0
        if not d.get('success_count') and not d.get('failed_count'):
            try:
                rj_row = conn.execute(
                    "SELECT results_json FROM playbook_executions WHERE id = ?",
                    (execution_id,)
                ).fetchone()
                if rj_row and rj_row['results_json']:
                    results = json.loads(rj_row['results_json'])
                    sc = fc = pc = 0
                    for v in results.values():
                        st = v.get('status', 'success') if isinstance(v, dict) else 'success'
                        if st == 'success':
                            sc += 1
                        elif st in ('failed', 'error', 'blocked'):
                            fc += 1
                        else:
                            pc += 1
                    d['success_count'] = sc
                    d['failed_count'] = fc
                    d['partial_count'] = pc
            except Exception:
                pass
        try:
            s = datetime.fromisoformat(d['created_at'])
            e = datetime.fromisoformat(d['updated_at'])
            d['duration_ms'] = int((e - s).total_seconds() * 1000)
        except Exception:
            d['duration_ms'] = 0
        return d
    finally:
        conn.close()

@router.get("/playbooks/{execution_id}/full")
async def get_execution_full(execution_id: str):
    """Return the complete execution record, including phases_json and variables."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            '''SELECT id, scenario_id, scenario_name, platform, device_ids, variables, 
                      status, dry_run, author, concurrency, phases_json, 
                      total_devices, success_count, failed_count, partial_count,
                      created_at, updated_at
               FROM playbook_executions WHERE id = ?''',
            (execution_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Execution not found")
        d = dict(row)
        # Parse JSON fields
        for field in ['device_ids', 'variables', 'phases_json']:
            if d.get(field):
                try:
                    d[field.replace('_json', '')] = json.loads(d[field])
                except Exception:
                    d[field.replace('_json', '')] = d[field]
        return d
    finally:
        conn.close()

@router.get("/playbooks/{execution_id}/devices")
async def get_execution_devices(
    execution_id: str,
    status: str = Query('all'),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query(''),
):
    """Return paginated per-device results for an execution. Failed devices sorted first."""
    conn = get_db_connection()
    try:
        count_new = conn.execute(
            "SELECT COUNT(*) FROM execution_device_results WHERE execution_id = ?",
            (execution_id,)
        ).fetchone()[0]

        if count_new > 0:
            where_clauses = ["execution_id = ?"]
            params: list = [execution_id]
            if status != 'all':
                where_clauses.append("status = ?")
                params.append(status)
            if search:
                where_clauses.append("(hostname LIKE ? OR ip_address LIKE ?)")
                params.extend([f"%{search}%", f"%{search}%"])
            where_sql = "WHERE " + " AND ".join(where_clauses)
            total = conn.execute(
                f"SELECT COUNT(*) FROM execution_device_results {where_sql}", params
            ).fetchone()[0]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f'''SELECT id, device_id, hostname, ip_address, status, error_message,
                           started_at, completed_at, duration_ms
                    FROM execution_device_results {where_sql}
                    ORDER BY CASE status
                        WHEN 'failed' THEN 0
                        WHEN 'error' THEN 0
                        WHEN 'partial_failure' THEN 1
                        WHEN 'post_check_failed' THEN 1
                        ELSE 2 END, hostname
                    LIMIT ? OFFSET ?''',
                [*params, page_size, offset]
            ).fetchall()
            items = [dict(r) for r in rows]
        else:
            # Legacy fallback: parse results_json blob
            exec_row = conn.execute(
                "SELECT results_json, device_ids FROM playbook_executions WHERE id = ?",
                (execution_id,)
            ).fetchone()
            if not exec_row:
                raise HTTPException(status_code=404, detail="Execution not found")
            try:
                results = json.loads(exec_row['results_json'] or '{}')
                device_ids_list = json.loads(exec_row['device_ids'] or '[]')
            except Exception:
                results, device_ids_list = {}, []
            all_items = []
            for did in device_ids_list:
                r = results.get(did, {})
                dev_row = conn.execute(
                    "SELECT hostname, ip_address FROM devices WHERE id = ?", (did,)
                ).fetchone()
                hostname = dev_row['hostname'] if dev_row else did
                ip_address = dev_row['ip_address'] if dev_row else ''
                all_items.append({
                    "device_id": did, "hostname": hostname, "ip_address": ip_address,
                    "status": r.get('status', 'success'),
                    "error_message": r.get('error', ''),
                    "started_at": None, "completed_at": None, "duration_ms": 0,
                })
            if status != 'all':
                all_items = [i for i in all_items if i['status'] == status]
            if search:
                sq = search.lower()
                all_items = [i for i in all_items if sq in i['hostname'].lower() or sq in i['ip_address'].lower()]
            all_items.sort(key=lambda x: (
                0 if x['status'] in ('failed', 'error') else
                1 if 'fail' in x['status'] else 2,
                x['hostname']
            ))
            total = len(all_items)
            offset = (page - 1) * page_size
            items = all_items[offset:offset + page_size]
        return {"items": items, "total": total, "page": page, "page_size": page_size}
    finally:
        conn.close()

@router.get("/playbooks/{execution_id}/devices/{device_id}")
async def get_execution_device_detail(execution_id: str, device_id: str):
    """Return full phase output for one device in an execution."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM execution_device_results WHERE execution_id = ? AND (device_id = ? OR ip_address = ?)",
            (execution_id, device_id, device_id)
        ).fetchone()
        if row:
            res = dict(row)
            if res.get('phases_json'):
                try:
                    res['phases'] = json.loads(res['phases_json'])
                except Exception:
                    res['phases'] = {}
            return res
        # Legacy fallback
        exec_row = conn.execute(
            "SELECT results_json FROM playbook_executions WHERE id = ?", (execution_id,)
        ).fetchone()
        if not exec_row:
            raise HTTPException(status_code=404, detail="Execution not found")
        results = json.loads(exec_row['results_json'] or '{}')
        device_data = results.get(device_id)
        if not device_data:
            raise HTTPException(status_code=404, detail="Device result not found")
        dev_row = conn.execute(
            "SELECT hostname, ip_address FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
        return {
            "device_id": device_id,
            "hostname": dev_row['hostname'] if dev_row else device_id,
            "ip_address": dev_row['ip_address'] if dev_row else '',
            "status": device_data.get('status', 'success'),
            "error_message": device_data.get('error', ''),
            "phases_json": json.dumps(device_data.get('phases', {})),
            "started_at": None, "completed_at": None, "duration_ms": 0,
        }
    finally:
        conn.close()

@router.post("/playbooks/{execution_id}/devices/{device_id}/parse")
async def parse_device_output(execution_id: str, device_id: str, payload: dict = Body(...)):
    """
    使用 TextFSM 解析指定设备的执行输出。
    请求体：{ "platform": "cisco_ios", "command": "show version", "output": "..." }
    若不传 output，则从数据库中读取该设备的 execute phase 输出。
    """
    from core.textfsm import parse_with_textfsm, _find_template

    platform = (payload.get('platform') or '').strip()
    command = (payload.get('command') or '').strip()
    raw_output = payload.get('output')

    # 若未传 output，从数据库读取
    if raw_output is None:
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT phases_json, hostname FROM execution_device_results WHERE execution_id = ? AND (device_id = ? OR ip_address = ?)",
                (execution_id, device_id, device_id)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Device result not found")
            try:
                phases = json.loads(row['phases_json'] or '{}')
                # 取 execute phase 的 output
                raw_output = phases.get('execute', {}).get('output', '')
                if not command:
                    # 尝试从 commands 列表推断命令
                    cmds = phases.get('execute', {}).get('commands', [])
                    if cmds:
                        command = cmds[0]
            except Exception:
                raw_output = ''
        finally:
            conn.close()

    if not raw_output:
        return {'success': False, 'message': '没有可解析的输出内容', 'data': None}

    if not platform or not command:
        return {'success': False, 'message': '需要提供 platform 和 command 参数', 'data': None}

    # 检查是否有对应模板
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
            'has_template': True,
        }

    return {
        'success': True,
        'message': f'解析成功，共 {len(records)} 条记录',
        'data': {
            'records': records,
            'count': len(records),
            'fields': list(records[0].keys()) if records else [],
        },
        'has_template': True,
    }


@router.post("/playbooks/preview")
async def preview_playbook(payload: dict = Body(...)):
    """Preview rendered commands without executing."""
    scenario_id = payload.get('scenario_id')
    variables = payload.get('variables', {})
    requested_platform = payload.get('platform', 'cisco_ios')
    platform = _normalize_playbook_platform(requested_platform)

    scenario = next((s for s in _all_scenarios() if s['id'] == scenario_id), None)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    try:
        phases, resolved_platform = resolve_platform_phases(
            scenario.get('platform_phases', {}), platform
        )
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Platform '{platform}' not supported for this scenario")

    return {
        "platform": resolved_platform,
        "requested_platform": requested_platform,
        "pre_check": _render_phase_commands(phases.get('pre_check', []), variables),
        "execute": _render_phase_commands(phases.get('execute', []), variables),
        "post_check": _render_phase_commands(phases.get('post_check', []), variables),
        "rollback": _render_phase_commands(phases.get('rollback', []), variables),
    }



def _parse_iso_to_utc(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _assert_change_order_executable(row: dict, scenario_id: str, platform: str, now_utc: datetime) -> None:
    status = row.get('status') or ''
    if status not in {'approved', 'implementing'}:
        raise HTTPException(status_code=400, detail=f"工单状态为 {status}，仅已审批/执行中的工单允许执行任务")

    start_dt = _parse_iso_to_utc(row.get('scheduled_start'))
    end_dt = _parse_iso_to_utc(row.get('scheduled_end'))
    if start_dt and now_utc < start_dt:
        raise HTTPException(status_code=400, detail=f"变更窗口尚未开始（计划开始：{row.get('scheduled_start') or ''}）")
    if end_dt and now_utc > end_dt:
        raise HTTPException(status_code=400, detail=f"变更窗口已超时（计划结束：{row.get('scheduled_end') or ''}）")

    raw_template = row.get('command_template_json')
    try:
        template = json.loads(raw_template or '{}')
    except (TypeError, json.JSONDecodeError):
        template = {}
    ticket_scenario_id = str(template.get('scenario_id') or '').strip()
    ticket_platform = str(template.get('platform') or '').strip()

    if ticket_scenario_id and scenario_id and ticket_scenario_id != scenario_id:
        raise HTTPException(status_code=400, detail="工单绑定场景与当前执行任务不匹配，请检查工单号")
    if ticket_platform and platform and ticket_platform != platform:
        raise HTTPException(status_code=400, detail="工单绑定平台与当前执行平台不匹配")


def _resolve_change_order_for_playbook(
    conn,
    *,
    ticket_number: str,
    scenario_id: str,
    platform: str,
    now_utc: datetime,
) -> tuple[dict, bool]:
    """Resolve explicit ticket or auto-match one active change order for scenario execution."""
    if ticket_number:
        row = conn.execute(
            """
            SELECT id, order_number, title, status, scheduled_start, scheduled_end, command_template_json
            FROM change_orders WHERE order_number = ?
            """,
            (ticket_number,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="未找到该变更工单，请检查工单号")
        order = dict(row)
        _assert_change_order_executable(order, scenario_id, platform, now_utc)
        return order, False

    rows = conn.execute(
        """
        SELECT id, order_number, title, status, scheduled_start, scheduled_end, command_template_json, updated_at
        FROM change_orders
        WHERE status IN ('approved', 'implementing')
        ORDER BY updated_at DESC
        LIMIT 200
        """
    ).fetchall()

    matched: list[dict] = []
    for row in rows:
        order = dict(row)
        raw_template = order.get('command_template_json')
        try:
            template = json.loads(raw_template or '{}')
        except (TypeError, json.JSONDecodeError):
            template = {}

        if str(template.get('scenario_id') or '').strip() != scenario_id:
            continue
        template_platform = str(template.get('platform') or '').strip()
        if template_platform and template_platform != platform:
            continue

        start_dt = _parse_iso_to_utc(order.get('scheduled_start'))
        end_dt = _parse_iso_to_utc(order.get('scheduled_end'))
        if start_dt and now_utc < start_dt:
            continue
        if end_dt and now_utc > end_dt:
            continue

        matched.append(order)

    if len(matched) == 1:
        _assert_change_order_executable(matched[0], scenario_id, platform, now_utc)
        return matched[0], True

    if len(matched) > 1:
        raise HTTPException(status_code=400, detail="匹配到多个有效变更工单，请填写工单号后再执行")

    raise HTTPException(status_code=400, detail="未找到当前任务对应的有效变更工单，请先创建并审批工单")



@router.post("/playbooks/execute")
async def execute_playbook(request: Request, payload: dict = Body(...)):
    """
    Start an async playbook execution and return immediately.
    Subscribe to /ws/playbook/{execution_id} for real-time updates.
    """
    scenario_id = payload.get('scenario_id')
    device_ids = payload.get('device_ids', [])
    variables = payload.get('variables', {})
    dry_run = payload.get('dry_run', False)
    concurrency = payload.get('concurrency', 1)         # Parallel device count
    change_ticket = str(payload.get('change_ticket') or '').strip()
    author = payload.get('author', 'admin')
    actor_id = payload.get('actor_id')
    actor_role = payload.get('actor_role') or 'Administrator'
    commit_confirmed_ttl = int(payload.get('commit_confirmed_ttl', 0))  # P3: 秒数，0=关闭

    if not device_ids:
        raise HTTPException(status_code=400, detail="No devices selected")

    requested_platform = payload.get('platform', 'cisco_ios')
    platform = _normalize_playbook_platform(requested_platform)

    scenario = next((s for s in _all_scenarios() if s['id'] == scenario_id), None)
    # Allow custom playbooks (scenario can be None — user provides commands directly)
    custom_phases = payload.get('phases')
    if not scenario and not custom_phases:
        raise HTTPException(status_code=404, detail="Scenario not found and no custom phases provided")

    execution_id = str(uuid.uuid4())
    if scenario:
        phases_catalog = scenario.get('platform_phases', {})
        try:
            # Validate the requested platform for the preview/change-ticket
            # contract. Actual execution resolves this catalog again per
            # device, using the platform stored in the asset row.
            phases_def, _ = resolve_platform_phases(phases_catalog, platform)
        except KeyError:
            raise HTTPException(status_code=400, detail=f"Platform '{platform}' not supported for this scenario")
        phases_for_execution = phases_catalog
    else:
        phases_def = custom_phases
        phases_for_execution = custom_phases
    scenario_name = scenario['name'] if scenario else payload.get('name', 'Custom Playbook')
    scenario_risk = str((scenario or {}).get('risk') or 'low').lower()
    now_utc = datetime.now(timezone.utc)

    conn = get_db_connection()
    try:
        resolved_change_order = None
        auto_matched_change_order = False
        if scenario and scenario_risk != 'low':
            resolved_change_order, auto_matched_change_order = _resolve_change_order_for_playbook(
                conn,
                ticket_number=change_ticket,
                scenario_id=scenario_id,
                platform=platform,
                now_utc=now_utc,
            )

        conn.execute(
            '''INSERT INTO playbook_executions
               (id, scenario_id, scenario_name, platform, device_ids, variables, status, dry_run, author, concurrency, phases_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (execution_id, scenario_id or 'custom', scenario_name, platform,
             json.dumps(device_ids), json.dumps(variables),
             'pending', int(dry_run), author, concurrency,
             json.dumps(phases_for_execution),
             datetime.now().isoformat(), datetime.now().isoformat())
        )
        conn.commit()
    finally:
        conn.close()

    # Fire-and-forget the execution coroutine
    asyncio.create_task(_run_playbook(execution_id, device_ids, phases_for_execution, variables, dry_run, concurrency, platform, commit_confirmed_ttl))

    log_audit_event(
        event_type='PLAYBOOK_EXECUTION',
        category='automation',
        severity='high' if not dry_run else 'medium',
        status='pending',
        summary=f"Started playbook {scenario_name} for {len(device_ids)} device(s)",
        actor_id=str(actor_id) if actor_id is not None else None,
        actor_username=author,
        actor_role=actor_role,
        source_ip=request.client.host if request.client else None,
        target_type='playbook',
        target_id=execution_id,
        target_name=scenario_name,
        execution_id=execution_id,
        details={
            'scenario_id': scenario_id or 'custom',
            'platform': platform,
            'device_count': len(device_ids),
            'dry_run': dry_run,
            'concurrency': concurrency,
            'change_order_number': (resolved_change_order or {}).get('order_number'),
            'change_order_auto_matched': auto_matched_change_order,
        },
    )

    return {
        "execution_id": execution_id,
        "status": "pending",
        "change_order_number": (resolved_change_order or {}).get('order_number'),
        "change_order_auto_matched": auto_matched_change_order,
    }

# ════════════════════════════════════════════════════════════════════
# WebSocket: /ws/playbook/{execution_id}
# ════════════════════════════════════════════════════════════════════

@router.websocket("/ws/playbook/{execution_id}")
async def playbook_ws(websocket: WebSocket, execution_id: str):
    # Authenticate via query param: ?token=xxx
    token = websocket.query_params.get('token', '')
    if not token:
        await websocket.close(code=1008, reason="Missing authentication token")
        return
    from api.users import validate_session_token
    if not validate_session_token(token):
        await websocket.close(code=1008, reason="Invalid or expired session")
        return

    await ws_manager.connect(execution_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == 'ping':
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(execution_id, websocket)



@router.post("/playbooks/executions/{execution_id}/confirm-commit")
async def confirm_commit(execution_id: str):
    """
    P3 Commit Confirmed：取消该次执行的定时自动回滚任务，正式确认变更。
    须在 commit_confirmed_ttl 秒内调用，否则自动回滚已触发。
    """
    task = _pending_rollbacks.pop(execution_id, None)
    if task:
        task.cancel()
        logger.info(f"Commit confirmed for execution {execution_id}, auto-rollback cancelled")
        return {"status": "confirmed", "execution_id": execution_id,
                "message": "Commit confirmed. Auto-rollback cancelled."}
    return {"status": "no_pending", "execution_id": execution_id,
            "message": "No pending commit confirmation found (already confirmed or timed out)."}
