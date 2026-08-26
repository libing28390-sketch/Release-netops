from fastapi import APIRouter, HTTPException, Body, Request, Depends
from typing import Optional
from datetime import datetime, timedelta
import uuid
import logging
import os

from database import get_db_connection
from core.rbac import require_role
from core.config import settings
from core.read_cache import (
    SCHEDULED_JOBS_CACHE_TTL_SECONDS,
    invalidate_read_cache,
    read_cache,
)
from services.config_approval_service import verify_code, consume_approval
from services.audit_service import log_audit_event

router = APIRouter()
logger = logging.getLogger(__name__)

_CRON_ACTION_TYPES = frozenset({
    "backup",
    "inspection",
    "script_run",
    "server_check",
    "health_check",
    "nsot",
})

# Import refresh logic from scheduler_manager
from core.scheduler_manager import refresh_dynamic_scheduler


def _format_job_row(row) -> dict:
    d = dict(row)
    if d.get('action_type') == 'inspection' and d.get('commands'):
        import re
        d['check_items'] = [c.strip() for c in re.split(r'[,\n]', d['commands']) if c.strip()]
    else:
        d['check_items'] = []
    return d


# ── List ──

@router.get("/scheduled-jobs")
def list_scheduled_jobs(
    job_type: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        where, params = [], []
        if job_type:
            where.append("job_type = ?")
            params.append(job_type)
        if status:
            where.append("status = ?")
            params.append(status)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM scheduled_jobs {where_sql}", tuple(params)
        ).fetchone()["c"]

        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT * FROM scheduled_jobs {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, page_size, offset),
        ).fetchall()

        return {
            "success": True,
            "data": {
                "items": [_format_job_row(r) for r in rows],
                "total": total,
                "page": page,
                "page_size": page_size,
            },
        }
    finally:
        conn.close()


# ── System Jobs ──
# Operator-facing platform schedules (APScheduler). The scheduler also contains
# low-level samplers and cache-refresh daemons, but those are implementation
# details rather than jobs an operator can act on. Keep this catalog as an
# explicit allow-list so adding an internal daemon never makes the Scheduled
# Jobs page noisy again.
_SYSTEM_JOB_CATALOG = {
    'daily_backup': {
        'name_zh': '配置自动备份',
        'name_en': 'Scheduled Config Backup',
        'description_zh': '每日扫描所有在线网络设备，自动抓取运行配置并归档到备份中心。',
        'description_en': 'Daily collection of running-config across all online network devices, archived in the Backup Center.',
        'category': 'collection',
        'action_type': 'backup',
        'deep_link': '/config/schedule',
    },
    'inspection_scheduler': {
        'name_zh': '周期巡检 (主发条引擎)',
        'name_en': 'Inspection Master Daemon',
        'description_zh': '内置主调度器，按周期轮询并触发左侧导航栏【巡检计划】中用户自定义的各设备巡检策略。',
        'description_en': 'Master daemon polling and triggering active user-defined inspection plans on schedule.',
        'category': 'collection',
        'action_type': 'inspection',
        'deep_link': '/automation/schedule',
    },
    'password_rotation_sweep': {
        'name_zh': '凭据轮换扫描',
        'name_en': 'Password Rotation Sweep',
        'description_zh': '每日凌晨检查到期凭据，并按策略执行自动轮换。',
        'description_en': 'Daily scan for expiring credentials with policy-driven rotation.',
        'category': 'security',
        'action_type': 'password_rotation',
        'deep_link': '/credentials',
    },
}


def _describe_trigger(trigger) -> str:
    """Best-effort human-readable description of an APScheduler trigger."""
    try:
        s = str(trigger)
        if 'cron' in s.lower():
            # CronTrigger's __str__ is already reasonably human (e.g.
            # "cron[hour='2', minute='0']")
            return s
        if 'interval' in s.lower():
            return s
        return s
    except Exception:
        return 'unknown'


@router.get("/scheduled-jobs/system")
def list_system_scheduled_jobs(_user=require_role("Viewer")):
    """Return operator-facing platform schedules (read-only).

    Sourced from APScheduler's in-memory job registry, enriched with the static
    metadata in ``_SYSTEM_JOB_CATALOG``. Internal and unknown scheduler IDs are
    deliberately omitted: they remain running, but do not belong in the user
    job-management surface.
    """
    from core.scheduler_manager import scheduler

    items: list[dict] = []
    try:
        jobs = scheduler.get_jobs()
    except Exception as exc:
        logger.warning(f"[SystemJobs] Could not list APScheduler jobs: {exc}")
        jobs = []

    running_jobs = {
        sjob.id: sjob
        for sjob in jobs
        if not sjob.id.startswith('dyn_')
    }

    # Dict insertion order is the product-defined display order. Iterating the
    # allow-list (rather than scheduler.get_jobs()) also keeps the API stable.
    for jid, meta in _SYSTEM_JOB_CATALOG.items():
        sjob = running_jobs.get(jid)
        if sjob is None:
            continue
        next_run = None
        try:
            if sjob.next_run_time:
                next_run = sjob.next_run_time.isoformat()
        except Exception:
            pass
        items.append({
            'id': jid,
            'name_zh': meta['name_zh'],
            'name_en': meta['name_en'],
            'description_zh': meta['description_zh'],
            'description_en': meta['description_en'],
            'category': meta.get('category'),
            'action_type': meta.get('action_type'),
            'deep_link': meta.get('deep_link'),
            'trigger': _describe_trigger(sjob.trigger),
            'next_run_at': next_run,
        })
    return {'success': True, 'data': {'items': items, 'total': len(items)}}


@router.get("/scheduled-jobs/future")
def list_future_execution_plans(
    time_range: str = '1d',
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    query: Optional[str] = None,
    user=require_role("Viewer"),
):
    """
    计算未来一段时间内所有已启用作业（包括一次性和周期性 Cron 作业）的执行排班。
    """
    cache_key = '|'.join((time_range or '', start_time or '', end_time or '', query or ''))
    cache_hit, cached = read_cache.get('scheduled_jobs_future', cache_key)
    if cache_hit:
        logger.debug('[Perf] scheduled-jobs/future cache hit key=%s', cache_key)
        return cached

    now = datetime.now()
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            if start_dt.tzinfo:
                start_dt = start_dt.astimezone().replace(tzinfo=None)
        except Exception:
            start_dt = now
    else:
        start_dt = now

    if time_range == '1h':
        end_dt = start_dt + timedelta(hours=1)
    elif time_range == '4h':
        end_dt = start_dt + timedelta(hours=4)
    elif time_range == '12h':
        end_dt = start_dt + timedelta(hours=12)
    elif time_range == '1d':
        end_dt = start_dt + timedelta(days=1)
    elif time_range == '3d':
        end_dt = start_dt + timedelta(days=3)
    elif time_range == 'custom' and end_time:
        try:
            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            if end_dt.tzinfo:
                end_dt = end_dt.astimezone().replace(tzinfo=None)
        except Exception:
            end_dt = start_dt + timedelta(days=1)
    else:
        end_dt = start_dt + timedelta(days=1)

    conn = get_db_connection()
    try:
        sql = "SELECT * FROM scheduled_jobs WHERE enabled = 1"
        params = []
        if query:
            sql += " AND name LIKE ?"
            params.append(f"%{query}%")
        
        jobs = conn.execute(sql, tuple(params)).fetchall()
        
        future_runs = []
        for job in jobs:
            job_dict = _format_job_row(job)
            if job['job_type'] == 'once':
                if job['scheduled_at']:
                    try:
                        run_dt = datetime.fromisoformat(job['scheduled_at'])
                        if start_dt <= run_dt <= end_dt:
                            run_item = dict(job_dict)
                            run_item['job_id'] = job['id']
                            run_item['run_at'] = run_dt.isoformat()
                            future_runs.append(run_item)
                    except Exception:
                        pass
            elif job['job_type'] == 'cron':
                if job['cron_expr']:
                    try:
                        from croniter import croniter
                        expr = job['cron_expr'].strip()
                        parts = expr.split()
                        if len(parts) > 5:
                            expr = " ".join(parts[:5])
                        
                        iter = croniter(expr, start_dt)
                        count = 0
                        while count < 100:
                            next_run = iter.get_next(datetime)
                            if next_run > end_dt:
                                break
                            run_item = dict(job_dict)
                            run_item['job_id'] = job['id']
                            run_item['run_at'] = next_run.isoformat()
                            future_runs.append(run_item)
                            count += 1
                    except Exception as e:
                        logger.error(f"Error parsing cron expression '{job['cron_expr']}' for job '{job['name']}': {e}")
                        pass
        
        future_runs.sort(key=lambda x: x['run_at'])
        response = {
            'success': True,
            'data': future_runs
        }
        read_cache.set(
            'scheduled_jobs_future',
            cache_key,
            response,
            SCHEDULED_JOBS_CACHE_TTL_SECONDS,
        )
        return response
    finally:
        conn.close()


# ── Create ──

@router.post("/scheduled-jobs")
def create_scheduled_job(
    request: Request,
    payload: dict = Body(...),
    user=require_role("Operator"),
):
    """
    创建定时作业或执行计划。
    
    生产环境需验证审批码；测试环境可通过 skip_approval_verification=true 跳过飞书验证。
    """
    is_test_env = getattr(settings, 'ENVIRONMENT', 'development') != 'production'
    skip_approval_verification = payload.get("skip_approval_verification", False) if is_test_env else False
    
    approval_token = (payload.get("approval_token") or "").strip()
    approval_code = (payload.get("approval_code") or "").strip()

    # Approval verification logic
    approval_record = None
    if not skip_approval_verification:
        # Production mode or not skipping: require full approval flow
        if not approval_token or not approval_code:
            raise HTTPException(
                status_code=400, 
                detail="审批令牌和验证码不能为空" if not is_test_env else "审批令牌和验证码不能为空（或在测试环境中使用 skip_approval_verification=true）"
            )

        ok, err = verify_code(approval_token, approval_code)
        if not ok:
            raise HTTPException(status_code=403, detail=err)

    else:
        # Test mode with skip flag: create mock approval record
        logger.warning(f"Creating scheduled job with approval verification skipped by {user.get('username', 'unknown')}")
        approval_record = {
            "approver": "test-system",
            "verified_at": datetime.now().isoformat(),
            "test_mode": True,
        }

    name = (payload.get("name") or "").strip()
    job_type = payload.get("job_type", "cron")  # 'cron' | 'once'
    action_type = payload.get("action_type", "backup")  # 'backup' | 'inspection' | 'script_run' | 'nsot' (cron); 'command' | 'backup' | 'inspection' (once)
    cron_expr = (payload.get("cron_expr") or "").strip()
    scheduled_at = (payload.get("scheduled_at") or "").strip()
    device_scope = payload.get("device_scope", "all")
    device_filter = (payload.get("device_filter") or "").strip()
    commands = (payload.get("commands") or "").strip()
    if action_type == "inspection" and payload.get("check_items"):
        commands = ",".join(payload.get("check_items"))
    script_id = (payload.get("script_id") or "").strip()
    is_config = 1 if payload.get("is_config") else 0
    config_reason = (payload.get("config_reason") or "").strip()
    use_admin_creds = 1 if payload.get("use_admin_creds") else 0

    # NSOT is a composed, read-only workflow.  It always targets the platform's
    # eligible online devices and does not accept arbitrary commands, scripts,
    # config mode, or borrowed privileged credentials.
    if action_type == "nsot":
        device_scope = "all"
        device_filter = ""
        commands = ""
        script_id = ""
        is_config = 0
        use_admin_creds = 0

    if not name:
        raise HTTPException(status_code=400, detail="作业名称不能为空")
    # 定时作业（cron）仅支持备份和巡检
    if job_type == "cron" and action_type not in _CRON_ACTION_TYPES:
        raise HTTPException(status_code=400, detail="定时作业支持：配置备份、网络巡检、服务器巡检、健康检查、脚本执行及 NSOT 事实库采集")
    if job_type == "cron" and not cron_expr:
        raise HTTPException(status_code=400, detail="定时作业需要 cron 表达式")
    if job_type == "once" and not scheduled_at:
        raise HTTPException(status_code=400, detail="执行计划需要执行时间")
    if action_type == "command" and not commands and not script_id:
        raise HTTPException(status_code=400, detail="命令类型作业需要命令或脚本")
    if action_type == "script_run" and not script_id:
        raise HTTPException(status_code=400, detail="自动化变更作业需要选择一个已发布的脚本")

    # 5. ALL VALIDATIONS PASSED -> Consume approval token
    if not skip_approval_verification:
        approval_record = consume_approval(approval_token)
        if not approval_record:
            raise HTTPException(status_code=403, detail="审批令牌无效或已过期，请重新获取验证码")

    now = datetime.now().isoformat()
    job_id = str(uuid.uuid4())
    actor = user.get("username", "unknown")

    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO scheduled_jobs
               (id, name, job_type, action_type, cron_expr, scheduled_at,
                device_scope, device_filter, commands, script_id,
                is_config, config_reason, use_admin_creds, enabled, status,
                approved_by, approved_at, created_by, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,'approved',?,?,?,?,?)""",
            (
                job_id, name, job_type, action_type, cron_expr, scheduled_at,
                device_scope, device_filter, commands, script_id,
                is_config, config_reason, use_admin_creds,
                approval_record.get("approver", ""),
                now,
                actor, now, now,
            ),
        )
        conn.commit()

        log_audit_event(
            event_type="SCHEDULED_JOB_CREATED",
            category="automation",
            severity="high",
            status="success",
            summary=f"Created scheduled job '{name}' (type={job_type})",
            actor_username=actor,
            actor_role=user.get("role", "Operator"),
            source_ip=request.client.host if request.client else None,
            details={
                "job_id": job_id,
                "job_type": job_type,
                "action_type": action_type,
                "cron_expr": cron_expr,
                "scheduled_at": scheduled_at,
                "approved_by": approval_record.get("approver", ""),
                "approval_skipped": skip_approval_verification,
            },
        )
        
        # Refresh scheduler
        refresh_dynamic_scheduler()
        invalidate_read_cache('scheduled_jobs_future')

        return {
            "success": True,
            "data": {"id": job_id},
            "message": "作业已创建并通过审批",
        }
    finally:
        conn.close()


# ── Toggle Enable ──

@router.put("/scheduled-jobs/{job_id}/toggle")
def toggle_scheduled_job(
    job_id: str,
    request: Request,
    payload: dict = Body(...),
    user=require_role("Operator"),
):
    """
    启用/禁用定时作业。
    
    启用时需要审批验证，生产环境需飞书验证码；测试环境可通过 skip_approval_verification=true 跳过。
    """
    is_test_env = getattr(settings, 'ENVIRONMENT', 'development') != 'production'
    skip_approval_verification = payload.get("skip_approval_verification", False) if is_test_env else False
    
    enabled = payload.get("enabled", True)

    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="作业不存在")

        # 启用时要求审批验证
        if enabled:
            if not skip_approval_verification:
                approval_token = (payload.get("approval_token") or "").strip()
                approval_code = (payload.get("approval_code") or "").strip()
                if not approval_token or not approval_code:
                    raise HTTPException(
                        status_code=400, 
                        detail="启用作业需要审批验证码" if not is_test_env else "启用作业需要审批验证码（或在测试环境中使用 skip_approval_verification=true）"
                    )
                ok, err = verify_code(approval_token, approval_code)
                if not ok:
                    raise HTTPException(status_code=403, detail=err)
                consume_approval(approval_token)
            else:
                logger.warning(f"Enabling scheduled job {job_id} with approval verification skipped by {user.get('username', 'unknown')}")

        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE scheduled_jobs SET enabled = ?, status = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, "approved" if enabled else "disabled", now, job_id),
        )
        conn.commit()

        # Refresh scheduler
        refresh_dynamic_scheduler()
        invalidate_read_cache('scheduled_jobs_future')

        return {"success": True, "message": "已更新"}
    finally:
        conn.close()


# ── Delete ──

@router.delete("/scheduled-jobs/{job_id}")
def delete_scheduled_job(
    job_id: str,
    request: Request,
    approval_token: Optional[str] = None,
    approval_code: Optional[str] = None,
    skip_approval: Optional[bool] = False,
    user=require_role("Operator"),
):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="作业不存在")

        is_test_env = getattr(settings, 'ENVIRONMENT', 'development') != 'production'
        skip_verification = skip_approval if is_test_env else False

        if not skip_verification:
            if not approval_token or not approval_code:
                raise HTTPException(status_code=400, detail="安全校验失败：删除定时作业必须提供有效工单审批码。请先申请审批。")
            ok, err = verify_code(approval_token, approval_code)
            if not ok:
                raise HTTPException(status_code=403, detail=err)
            consume_approval(approval_token)
        else:
            logger.warning(f"Deleting scheduled job {job_id} with approval verification skipped by {user.get('username', 'unknown')}")

        conn.execute("DELETE FROM scheduled_jobs WHERE id = ?", (job_id,))
        conn.commit()

        log_audit_event(
            event_type="SCHEDULED_JOB_DELETED",
            category="automation",
            severity="medium",
            status="success",
            summary=f"Deleted scheduled job '{row['name']}'",
            actor_username=user.get("username", "unknown"),
            actor_role=user.get("role", "Operator"),
            source_ip=request.client.host if request.client else None,
            details={"job_id": job_id, "job_name": row["name"]},
        )

        # Refresh scheduler
        refresh_dynamic_scheduler()
        invalidate_read_cache('scheduled_jobs_future')

        return {"success": True, "message": "已删除"}
    finally:
        conn.close()


# ── Detail ──

@router.get("/scheduled-jobs/{job_id}")
def get_scheduled_job(
    job_id: str,
    user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="作业不存在")
        return {"success": True, "data": _format_job_row(row)}
    finally:
        conn.close()


# ── Update ──

@router.put("/scheduled-jobs/{job_id}")
def update_scheduled_job(
    job_id: str,
    request: Request,
    payload: dict = Body(...),
    user=require_role("Operator"),
):
    """编辑已有定时作业（名称、调度、设备范围、执行脚本等）。

    ⚠️ 安全升级：定时作业全生命周期操作（创建、修改、启用、删除）均受工单验证码防线保护。
    """
    is_test_env = getattr(settings, 'ENVIRONMENT', 'development') != 'production'
    skip_approval_verification = payload.get("skip_approval_verification", False) if is_test_env else False

    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="作业不存在")

        name = (payload.get("name") or "").strip()
        action_type = payload.get("action_type", row["action_type"])
        cron_expr = (payload.get("cron_expr") or "").strip()
        device_scope = payload.get("device_scope", row["device_scope"])
        device_filter = (payload.get("device_filter") or "").strip()
        config_reason = (payload.get("config_reason") or "").strip()
        new_script_id = (payload.get("script_id") or "").strip() if "script_id" in payload else None
        new_commands = (payload.get("commands") or "").strip() if "commands" in payload else None
        if action_type == "inspection" and "check_items" in payload:
            new_commands = ",".join(payload.get("check_items") or [])
        new_use_admin_creds = (1 if payload.get("use_admin_creds") else 0) if "use_admin_creds" in payload else None

        if action_type == "nsot":
            device_scope = "all"
            device_filter = ""
            new_script_id = ""
            new_commands = ""
            new_use_admin_creds = 0

        if not name:
            raise HTTPException(status_code=400, detail="作业名称不能为空")
        if row["job_type"] == "cron" and action_type not in _CRON_ACTION_TYPES:
            raise HTTPException(status_code=400, detail="定时作业支持：配置备份、网络巡检、服务器巡检、健康检查、脚本执行及 NSOT 事实库采集")
        if row["job_type"] == "cron" and not cron_expr:
            raise HTTPException(status_code=400, detail="定时作业需要 cron 表达式")

        # ── 强制工单审批校验 ──────────────────────────
        approval_record = None
        if not skip_approval_verification:
            approval_token = (payload.get("approval_token") or "").strip()
            approval_code = (payload.get("approval_code") or "").strip()
            if not approval_token or not approval_code:
                raise HTTPException(
                    status_code=400,
                    detail="安全校验失败：修改定时作业配置必须提供有效工单审批码。请先发送验证码并验证。"
                )
            ok, err = verify_code(approval_token, approval_code)
            if not ok:
                raise HTTPException(status_code=403, detail=err)
            approval_record = consume_approval(approval_token)
            if not approval_record:
                raise HTTPException(status_code=403, detail="审批令牌无效或已过期，请重新获取验证码")
        else:
            logger.warning(f"Scheduled job {job_id} update with approval skipped by {user.get('username', 'unknown')}")

        sensitive_changed = True
        sensitive_fields = list(payload.keys())

        now = datetime.now().isoformat()

        # 构建动态 UPDATE 语句（只更新提供了的字段）
        updates = {
            'name': name,
            'action_type': action_type,
            'cron_expr': cron_expr,
            'device_scope': device_scope,
            'device_filter': device_filter,
            'config_reason': config_reason,
            'updated_at': now,
        }
        if new_script_id is not None:
            updates['script_id'] = new_script_id
        if new_commands is not None:
            updates['commands'] = new_commands
        if new_use_admin_creds is not None:
            updates['use_admin_creds'] = new_use_admin_creds
        if action_type == "nsot":
            updates['is_config'] = 0
        if "enabled" in payload:
            updates['enabled'] = 1 if payload.get("enabled") else 0
            if payload.get("enabled"):
                updates['status'] = 'approved'

        set_clause = ', '.join(f"{k} = ?" for k in updates.keys())
        params = list(updates.values()) + [job_id]
        conn.execute(f"UPDATE scheduled_jobs SET {set_clause} WHERE id = ?", params)
        conn.commit()

        actor = user.get("username", "unknown")
        log_audit_event(
            event_type="SCHEDULED_JOB_UPDATED",
            category="automation",
            severity="high",
            status="success",
            summary=f"Updated scheduled job '{name}' with verified approval",
            actor_username=actor,
            actor_role=user.get("role", "Operator"),
            source_ip=request.client.host if request.client else None,
            details={
                "job_id": job_id,
                "job_name": name,
                "changes": payload,
                "sensitive_changed": sensitive_changed,
                "sensitive_fields": sensitive_fields,
                "approved_by": approval_record.get("approver", "") if approval_record else None,
                "approval_skipped": skip_approval_verification,
            },
        )

        # Refresh scheduler
        refresh_dynamic_scheduler()
        invalidate_read_cache('scheduled_jobs_future')

        return {"success": True, "message": "作业已成功更新（工单审批已校验）"}
    finally:
        conn.close()
