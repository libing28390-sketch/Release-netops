from fastapi import APIRouter, HTTPException, Body, Request, Depends, Query
from typing import Annotated, Optional
from datetime import datetime, timedelta
import uuid
import logging
import os
from pydantic import BaseModel, Field

from database import get_db_connection
from core.rbac import require_role, authorize_resource, is_global_administrator
from core.tenant_policy import TENANT_ISOLATION_ENABLED, tenant_id_for_write, tenant_scope_for_user
from core.read_cache import (
    SCHEDULED_JOBS_CACHE_TTL_SECONDS,
    invalidate_read_cache,
    read_cache,
)
from services.config_approval_service import verify_code, consume_approval
from services.scheduled_job_authorization import (
    authorize_job_resource,
    execution_snapshot,
    job_manifest_source_from_row,
    manifest_hash,
    merge_job_source,
    normalize_job_manifest,
    scheduled_job_approval_type,
    script_snapshot,
)
from services.audit_service import log_audit_event
from services.nsot_collection_preview_service import (
    NSOTPreviewPermissionError,
    build_nsot_collection_preview,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class CronPreviewRequest(BaseModel):
    cron_expr: str = Field(..., min_length=1, max_length=120)

_CRON_ACTION_TYPES = frozenset({
    "backup",
    "command",
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
    d["updated_by"] = str(d.get("updated_by") or d.get("created_by") or "system")
    d["updated_at"] = str(d.get("updated_at") or d.get("created_at") or "")
    if d.get('action_type') == 'inspection' and d.get('commands'):
        import re
        d['check_items'] = [c.strip() for c in re.split(r'[,\n]', d['commands']) if c.strip()]
    else:
        d['check_items'] = []
    return d


def _actor_id(user: dict) -> str:
    return str(user.get("user_id") or user.get("id") or "").strip()


def _actor_tenant(user: dict) -> str:
    return tenant_id_for_write(user=user)


def _authorize_job(user: dict, row: dict, action: str) -> None:
    try:
        authorize_job_resource(user, row, action)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _prepare_manifest(
    conn,
    source: dict,
    user: dict,
    operation: str,
    *,
    job_id: str | None = None,
    tenant_id: str | None = None,
) -> dict:
    script_id = str(source.get("script_id") or "").strip()
    try:
        script_sha, _ = script_snapshot(
            conn, script_id, require_released=str(operation).upper() != "DELETE",
        )
        return normalize_job_manifest(
            source,
            operation=operation,
            requester_id=_actor_id(user),
            tenant_id=tenant_id if tenant_id is not None else tenant_id_for_write(user=user),
            script_sha256=script_sha,
            job_id=job_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _require_job_collection_permission(user: dict, action: str) -> None:
    tenant_id = tenant_scope_for_user(user)
    if TENANT_ISOLATION_ENABLED and not tenant_id and not is_global_administrator(user):
        raise HTTPException(status_code=403, detail="当前账号未分配租户")
    if not authorize_resource(user, "scheduled_job", action, tenant_id=tenant_id):
        raise HTTPException(status_code=403, detail="当前账号没有计划作业资源权限")


@router.post("/scheduled-jobs/cron-preview")
def preview_scheduled_job_cron(payload: CronPreviewRequest, user=require_role("Viewer")):
    """Return the next ten local scheduler fire times without creating a job."""
    _require_job_collection_permission(user, "view")
    expression = " ".join(payload.cron_expr.split())
    if len(expression.split()) != 5:
        raise HTTPException(status_code=400, detail="Cron 表达式必须包含 5 个字段")

    try:
        from apscheduler.triggers.cron import CronTrigger
        from core.scheduler_manager import scheduler

        trigger = CronTrigger.from_crontab(expression, timezone=scheduler.timezone)
        next_run = None
        now = datetime.now(scheduler.timezone)
        occurrences = []
        for _ in range(10):
            next_run = trigger.get_next_fire_time(next_run, now)
            if next_run is None:
                break
            occurrences.append(next_run.isoformat())
            now = next_run + timedelta(microseconds=1)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Cron 表达式无效") from exc
    except Exception as exc:
        logger.warning("Unable to preview scheduled job cron: %s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="Cron 表达式无效或无法计算") from exc

    return {"success": True, "data": {"occurrences": occurrences}}


# ── List ──

@router.get("/scheduled-jobs")
def list_scheduled_jobs(
    job_type: Optional[str] = None,
    status: Optional[str] = None,
    action_type: Annotated[Optional[str], Query(min_length=1, max_length=64)] = None,
    keyword: Annotated[str, Query(max_length=200)] = "",
    enabled: Annotated[Optional[int], Query(ge=0, le=1)] = None,
    page: int = 1,
    page_size: int = 20,
    user=require_role("Viewer"),
):
    _require_job_collection_permission(user, "view")
    conn = get_db_connection()
    try:
        where, params = [], []
        tenant_scope = tenant_scope_for_user(user)
        if tenant_scope:
            where.append("tenant_id = ?")
            params.append(tenant_scope)
        if not is_global_administrator(user):
            if user.get("role") != "Administrator":
                where.append("(created_by_id = ? OR authorization_mode = 'system')")
                params.append(_actor_id(user))
        if job_type:
            where.append("job_type = ?")
            params.append(job_type)
        if status:
            where.append("status = ?")
            params.append(status)
        if enabled is not None:
            where.append("enabled = ?")
            params.append(enabled)
        keyword_value = (keyword or "").strip().lower()
        if keyword_value:
            pattern = f"%{keyword_value}%"
            where.append("""(
                LOWER(COALESCE(name, '')) LIKE ? OR
                LOWER(COALESCE(script_id, '')) LIKE ? OR
                LOWER(COALESCE(commands, '')) LIKE ? OR
                LOWER(COALESCE(device_filter, '')) LIKE ?
            )""")
            params.extend([pattern, pattern, pattern, pattern])
        counts_where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        action_count_rows = conn.execute(
            f"SELECT action_type, COUNT(*) AS c FROM scheduled_jobs {counts_where_sql} GROUP BY action_type",
            tuple(params),
        ).fetchall()
        action_counts = {str(row["action_type"] or ""): int(row["c"] or 0) for row in action_count_rows}
        if action_type:
            where.append("action_type = ?")
            params.append(action_type)
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
                "action_counts": action_counts,
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
    _require_job_collection_permission(_user, "view")
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
    page: Optional[int] = Query(default=None, ge=1),
    page_size: Optional[int] = Query(default=None, ge=1, le=100),
    user=require_role("Viewer"),
):
    """
    计算未来一段时间内所有已启用作业（包括一次性和周期性 Cron 作业）的执行排班。
    """
    _require_job_collection_permission(user, "view")
    pagination_requested = page is not None or page_size is not None
    safe_page = page or 1
    safe_page_size = page_size or 20
    cache_key = '|'.join((
        str(user.get("user_id") or user.get("id") or ""),
        str(tenant_scope_for_user(user) or ""),
        time_range or '', start_time or '', end_time or '', query or '',
        'paged' if pagination_requested else 'legacy',
        str(safe_page) if pagination_requested else '',
        str(safe_page_size) if pagination_requested else '',
    ))
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
        tenant_scope = tenant_scope_for_user(user)
        if tenant_scope:
            sql += " AND tenant_id = ?"
            params.append(tenant_scope)
        if not is_global_administrator(user):
            if user.get("role") != "Administrator":
                sql += " AND (created_by_id = ? OR authorization_mode = 'system')"
                params.append(_actor_id(user))
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
        
        future_runs.sort(key=lambda x: (x['run_at'], str(x.get('job_id') or '')))
        if pagination_requested:
            total = len(future_runs)
            offset = (safe_page - 1) * safe_page_size
            page_items = future_runs[offset:offset + safe_page_size]
            response_data = {
                'items': page_items,
                'total': total,
                'page': safe_page,
                'page_size': safe_page_size,
            }
        else:
            # Keep the original response for existing callers that do not yet
            # request pagination (for example, the dashboard's 1-day preview).
            response_data = future_runs
        response = {
            'success': True,
            'data': response_data,
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
    _require_job_collection_permission(user, "create")
    if payload.get("skip_approval_verification") or payload.get("skip_approval"):
        raise HTTPException(status_code=400, detail="不支持跳过计划作业审批")

    name = str(payload.get("name") or "").strip()
    job_type = str(payload.get("job_type") or "cron").strip()
    action_type = str(payload.get("action_type") or payload.get("action") or "backup").strip()
    cron_expr = str(payload.get("cron_expr") or "").strip()
    scheduled_at = str(payload.get("scheduled_at") or "").strip()
    device_scope = str(payload.get("device_scope") or (payload.get("scope") or {}).get("type") or "all").strip()
    raw_filter = payload.get("device_filter", (payload.get("scope") or {}).get("filter", ""))
    device_filter = raw_filter if isinstance(raw_filter, str) else __import__("json").dumps(raw_filter, ensure_ascii=False, sort_keys=True)
    commands = str(payload.get("commands") or "").strip()
    check_items = payload.get("check_items")
    if action_type == "inspection" and isinstance(check_items, list) and check_items:
        commands = ",".join(str(item).strip() for item in check_items if str(item).strip())
    script_id = str(payload.get("script_id") or "").strip()
    is_config = 1 if payload.get("is_config") else 0
    config_reason = str(payload.get("config_reason") or "").strip()
    use_admin_creds = 1 if payload.get("use_admin_creds") else 0

    if not name:
        raise HTTPException(status_code=400, detail="作业名称不能为空")
    if job_type == "cron" and action_type not in _CRON_ACTION_TYPES:
        raise HTTPException(status_code=400, detail="定时作业支持：配置备份、命令执行、自动化脚本、巡检、服务器检查及 NSOT 事实库采集")
    if job_type == "cron" and not cron_expr:
        raise HTTPException(status_code=400, detail="定时作业需要 cron 表达式")
    if job_type == "once" and not scheduled_at:
        raise HTTPException(status_code=400, detail="执行计划需要执行时间")
    if action_type == "command" and not commands and not script_id:
        raise HTTPException(status_code=400, detail="命令类型作业需要命令或脚本")
    if action_type == "script_run" and not script_id:
        raise HTTPException(status_code=400, detail="自动化变更作业需要选择一个已发布的脚本")
    if action_type == "command" and script_id and commands:
        raise HTTPException(status_code=400, detail="命令执行作业只能选择直接命令或已发布脚本其中一种")
    if action_type == "script_run" and commands:
        raise HTTPException(status_code=400, detail="自动化脚本作业的执行内容来自已发布脚本，不能再提交单独命令")
    if script_id and action_type not in {"command", "script_run"}:
        raise HTTPException(status_code=400, detail="脚本只能用于命令执行或自动化脚本作业")
    if is_config and action_type not in {"command", "script_run"}:
        raise HTTPException(status_code=400, detail="配置变更模式只能用于命令或脚本作业")
    if is_config and not config_reason:
        raise HTTPException(status_code=400, detail="配置变更作业必须填写变更原因")
    if action_type == "nsot" and (commands or script_id or is_config or use_admin_creds):
        raise HTTPException(status_code=400, detail="NSOT 事实库采集不接受命令、脚本、配置模式或管理凭据")
    if use_admin_creds and not authorize_resource(
        user, "credential", "use", tenant_id=_actor_tenant(user) or None,
    ):
        raise HTTPException(status_code=403, detail="当前账号没有使用管理凭据的授权")

    job_id = str(uuid.uuid4())
    actor = str(user.get("username") or "unknown")
    conn = get_db_connection()
    try:
        source = {
            **payload,
            "operation": "CREATE",
            "job_id": "",
            "job_type": job_type,
            "name": name,
            "action": action_type,
            "cron_expr": cron_expr,
            "scheduled_at": scheduled_at,
            "scope": {"type": device_scope, "filter": raw_filter},
            "commands": commands,
            "check_items": check_items if isinstance(check_items, list) else [],
            "script_id": script_id,
            "is_config": is_config,
            "use_admin_creds": use_admin_creds,
            "enabled": True,
            "config_reason": config_reason,
        }
        manifest = _prepare_manifest(conn, source, user, "CREATE")
        job_type = manifest["job_type"]
        action_type = manifest["action"]
        cron_expr = manifest["cron_expr"]
        scheduled_at = manifest["scheduled_at"]
        device_scope = manifest["scope"]["type"]
        device_filter = manifest["scope"]["filter"]
        commands = manifest["commands"]
        script_id = manifest["script_id"]
        is_config = manifest["is_config"]
        config_reason = manifest["config_reason"]
        use_admin_creds = manifest["use_admin_creds"]
        execution_manifest_hash = manifest_hash({
            **manifest, "operation": "EXECUTION", "job_id": job_id,
        })
        approval_type = scheduled_job_approval_type(manifest)
        approval_token = str(payload.get("approval_token") or "").strip()
        approval_code = str(payload.get("approval_code") or "").strip()
        if not approval_token or not approval_code:
            raise HTTPException(status_code=400, detail="创建计划作业必须提供已验证的审批凭据")
        binding_hash = manifest_hash(manifest)
        ok, err = verify_code(
            approval_token, approval_code,
            requester_id=_actor_id(user),
            requester_username=actor,
            expected_approval_type=approval_type,
            expected_binding_hash=binding_hash,
        )
        if not ok:
            raise HTTPException(status_code=403, detail=err)
        approval_record = consume_approval(
            approval_token,
            requester_id=_actor_id(user),
            expected_approval_type=approval_type,
            expected_binding_hash=binding_hash,
        )
        if not approval_record:
            raise HTTPException(status_code=403, detail="审批令牌无效、已过期或与当前作业内容不匹配")

        now = datetime.now().isoformat()
        conn.execute(
            """INSERT INTO scheduled_jobs
               (id, name, job_type, action_type, cron_expr, scheduled_at,
                device_scope, device_filter, commands, script_id,
                is_config, config_reason, use_admin_creds, enabled, status,
                approved_by, approved_at, created_by, updated_by, created_at, updated_at,
                created_by_id, tenant_id, script_sha256,
                authorization_manifest_hash, authorization_mode)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,'approved',?,?,?,?,?,?,?,?,?,?,'snapshot')""",
            (
                job_id, name, job_type, action_type, cron_expr, scheduled_at,
                device_scope, device_filter, commands, script_id,
                is_config, config_reason, use_admin_creds,
                approval_record.get("approver_username") or approval_record.get("approver", ""),
                now, actor, actor, now, now,
                _actor_id(user), _actor_tenant(user), manifest.get("script_sha256", ""),
                execution_manifest_hash,
            ),
        )
        conn.commit()
        log_audit_event(
            event_type="SCHEDULED_JOB_CREATED", category="automation", severity="high", status="success",
            summary=f"Created scheduled job '{name}' (type={job_type})",
            actor_username=actor, actor_role=user.get("role", "Operator"),
            source_ip=request.client.host if request.client else None,
            details={
                "job_id": job_id, "job_type": job_type, "action_type": action_type,
                "approved_by": approval_record.get("approver_username") or approval_record.get("approver", ""),
                "approval_type": approval_type, "approval_manifest_hash": binding_hash,
                "execution_manifest_hash": execution_manifest_hash,
                "tenant_id": _actor_tenant(user),
            },
        )
        refresh_dynamic_scheduler()
        invalidate_read_cache('scheduled_jobs_future')
        return {"success": True, "data": {"id": job_id}, "message": "作业已创建并通过审批"}
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
    enabled = bool(payload.get("enabled", True))
    if payload.get("skip_approval_verification") or payload.get("skip_approval"):
        raise HTTPException(status_code=400, detail="不支持跳过计划作业审批")
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="作业不存在")
        current = dict(row)
        _authorize_job(user, current, "enable" if enabled else "disable")
        source = merge_job_source(current, {**payload, "enabled": enabled}, "ENABLE" if enabled else "DISABLE")
        manifest = _prepare_manifest(
            conn, source, user, "ENABLE" if enabled else "DISABLE",
            job_id=job_id, tenant_id=str(current.get("tenant_id") or ""),
        )
        required_approval_type = scheduled_job_approval_type(manifest)
        approval_token = str(payload.get("approval_token") or "").strip()
        approval_code = str(payload.get("approval_code") or "").strip()
        if not approval_token or not approval_code:
            raise HTTPException(status_code=400, detail="计划作业启停必须提供已验证的审批凭据")
        binding_hash = manifest_hash(manifest)
        ok, err = verify_code(
            approval_token, approval_code,
            requester_id=_actor_id(user),
            requester_username=str(user.get("username") or ""),
            expected_approval_type=required_approval_type,
            expected_binding_hash=binding_hash,
        )
        if not ok:
            raise HTTPException(status_code=403, detail=err)
        approval_record = consume_approval(
            approval_token,
            requester_id=_actor_id(user),
            expected_approval_type=required_approval_type,
            expected_binding_hash=binding_hash,
        )
        if not approval_record:
            raise HTTPException(status_code=403, detail="审批令牌无效、已过期或与当前作业内容不匹配")

        now = datetime.now().isoformat()
        new_row = {**current, "enabled": 1 if enabled else 0}
        snapshot_hash = manifest_hash(execution_snapshot(conn, new_row))
        conn.execute(
            """UPDATE scheduled_jobs
                  SET enabled = ?, status = ?, updated_at = ?, updated_by = ?,
                      authorization_manifest_hash = ?,
                      authorization_mode = 'snapshot',
                      approved_by = ?, approved_at = ?
                WHERE id = ?""",
            (
                1 if enabled else 0, "approved" if enabled else "disabled", now,
                str(user.get("username") or "unknown"),
                snapshot_hash,
                (approval_record or {}).get("approver_username", ""), now, job_id,
            ),
        )
        conn.commit()
        log_audit_event(
            event_type="SCHEDULED_JOB_ENABLED" if enabled else "SCHEDULED_JOB_DISABLED",
            category="automation", severity="high" if enabled else "medium", status="success",
            summary=f"{'Enabled' if enabled else 'Disabled'} scheduled job '{current.get('name')}'",
            actor_username=str(user.get("username") or "unknown"), actor_role=user.get("role", "Operator"),
            source_ip=request.client.host if request.client else None,
            details={
                "job_id": job_id, "manifest_hash": manifest_hash(manifest),
                "execution_manifest_hash": snapshot_hash,
                "approved_by": (approval_record or {}).get("approver_username"),
            },
        )

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
    payload: dict = Body(default={}),
    approval_token: Optional[str] = None,
    approval_code: Optional[str] = None,
    user=require_role("Operator"),
):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="作业不存在")

        current = dict(row)
        _authorize_job(user, current, "delete")
        if payload.get("skip_approval") or payload.get("skip_approval_verification"):
            raise HTTPException(status_code=400, detail="不支持跳过计划作业审批")
        manifest = _prepare_manifest(
            conn, job_manifest_source_from_row(current, "DELETE"), user, "DELETE",
            job_id=job_id, tenant_id=str(current.get("tenant_id") or ""),
        )
        approval_token = str((payload or {}).get("approval_token") or approval_token or "").strip()
        approval_code = str((payload or {}).get("approval_code") or (payload or {}).get("code") or approval_code or "").strip()
        if not approval_token or not approval_code:
            raise HTTPException(status_code=400, detail="删除计划作业必须提供已验证的审批凭据")
        required_approval_type = scheduled_job_approval_type(manifest)
        binding_hash = manifest_hash(manifest)
        ok, err = verify_code(
            approval_token, approval_code,
            requester_id=_actor_id(user),
            requester_username=str(user.get("username") or ""),
            expected_approval_type=required_approval_type,
            expected_binding_hash=binding_hash,
        )
        if not ok:
            raise HTTPException(status_code=403, detail=err)
        approval_record = consume_approval(
            approval_token,
            requester_id=_actor_id(user),
            expected_approval_type=required_approval_type,
            expected_binding_hash=binding_hash,
        )
        if not approval_record:
            raise HTTPException(status_code=403, detail="审批令牌无效、已过期或与当前作业内容不匹配")

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
            details={
                "job_id": job_id, "job_name": row["name"],
                "manifest_hash": binding_hash,
                "approved_by": approval_record.get("approver_username"),
            },
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
        _authorize_job(user, dict(row), "view")
        return {"success": True, "data": _format_job_row(row)}
    finally:
        conn.close()


@router.get("/scheduled-jobs/{job_id}/nsot-preview")
def get_scheduled_nsot_collection_preview(
    job_id: str,
    user=require_role("Viewer"),
):
    """Return a read-only collection plan for this job's current online scope."""
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="作业不存在")
        job = dict(row)
        _authorize_job(user, job, "view")
        if str(job.get("action_type") or "").strip().lower() != "nsot":
            raise HTTPException(status_code=400, detail="仅 NSOT 事实库作业支持采集预览")
        try:
            preview = build_nsot_collection_preview(conn, job, user)
        except NSOTPreviewPermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    finally:
        conn.close()
    return {"success": True, "data": preview, "message": ""}


# ── Update ──

@router.put("/scheduled-jobs/{job_id}")
def update_scheduled_job(
    job_id: str,
    request: Request,
    payload: dict = Body(...),
    user=require_role("Operator"),
):
    """Edit a job only after its exact proposed operation is approved."""
    if payload.get("skip_approval_verification") or payload.get("skip_approval"):
        raise HTTPException(status_code=400, detail="不支持跳过计划作业审批")
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="作业不存在")
        current = dict(row)
        _authorize_job(user, current, "update")
        source = merge_job_source(current, payload, "UPDATE")
        manifest = _prepare_manifest(
            conn, source, user, "UPDATE", job_id=job_id,
            tenant_id=str(current.get("tenant_id") or ""),
        )
        name = manifest["name"]
        action_type = manifest["action"]
        if manifest["job_type"] == "cron" and action_type not in _CRON_ACTION_TYPES:
            raise HTTPException(status_code=400, detail="定时作业支持：配置备份、命令执行、自动化脚本、巡检、服务器检查及 NSOT 事实库采集")
        if action_type == "command" and not manifest["commands"] and not manifest["script_id"]:
            raise HTTPException(status_code=400, detail="命令类型作业需要命令或脚本")
        if action_type == "script_run" and not manifest["script_id"]:
            raise HTTPException(status_code=400, detail="自动化变更作业需要选择一个已发布的脚本")
        if action_type == "command" and manifest["script_id"] and manifest["commands"]:
            raise HTTPException(status_code=400, detail="命令执行作业只能选择直接命令或已发布脚本其中一种")
        if action_type == "script_run" and manifest["commands"]:
            raise HTTPException(status_code=400, detail="自动化脚本作业的执行内容来自已发布脚本，不能再提交单独命令")
        if manifest["script_id"] and action_type not in {"command", "script_run"}:
            raise HTTPException(status_code=400, detail="脚本只能用于命令执行或自动化脚本作业")
        if manifest["is_config"] and action_type not in {"command", "script_run"}:
            raise HTTPException(status_code=400, detail="配置变更模式只能用于命令或脚本作业")
        if manifest["is_config"] and not manifest["config_reason"]:
            raise HTTPException(status_code=400, detail="配置变更作业必须填写变更原因")
        if manifest["use_admin_creds"] and not authorize_resource(
            user, "credential", "use", tenant_id=_actor_tenant(user) or None,
        ):
            raise HTTPException(status_code=403, detail="当前账号没有使用管理凭据的授权")

        approval_type = scheduled_job_approval_type(manifest)
        approval_token = str(payload.get("approval_token") or "").strip()
        approval_code = str(payload.get("approval_code") or "").strip()
        if not approval_token or not approval_code:
            raise HTTPException(status_code=400, detail="修改计划作业必须提供已验证的审批凭据")
        binding_hash = manifest_hash(manifest)
        ok, err = verify_code(
            approval_token, approval_code,
            requester_id=_actor_id(user),
            requester_username=str(user.get("username") or ""),
            expected_approval_type=approval_type,
            expected_binding_hash=binding_hash,
        )
        if not ok:
            raise HTTPException(status_code=403, detail=err)
        approval_record = consume_approval(
            approval_token,
            requester_id=_actor_id(user),
            expected_approval_type=approval_type,
            expected_binding_hash=binding_hash,
        )
        if not approval_record:
            raise HTTPException(status_code=403, detail="审批令牌无效、已过期或与当前作业内容不匹配")

        now = datetime.now().isoformat()
        updates = {
            "name": manifest["name"],
            "action_type": manifest["action"],
            "job_type": manifest["job_type"],
            "cron_expr": manifest["cron_expr"],
            "scheduled_at": manifest["scheduled_at"],
            "device_scope": manifest["scope"]["type"],
            "device_filter": manifest["scope"]["filter"],
            "commands": manifest["commands"],
            "script_id": manifest["script_id"],
            "is_config": manifest["is_config"],
            "config_reason": manifest["config_reason"],
            "use_admin_creds": manifest["use_admin_creds"],
            "enabled": 1 if manifest["enabled"] else 0,
            "status": "approved" if manifest["enabled"] else "disabled",
            "approved_by": approval_record.get("approver_username") or "",
            "approved_at": now,
            "script_sha256": manifest["script_sha256"],
            "authorization_mode": "snapshot",
            "updated_by": str(user.get("username") or "unknown"),
            "updated_at": now,
        }
        new_row = {**current, **updates}
        execution_manifest_hash = manifest_hash(execution_snapshot(conn, new_row))
        updates["authorization_manifest_hash"] = execution_manifest_hash
        set_clause = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(
            f"UPDATE scheduled_jobs SET {set_clause} WHERE id = ?",
            (*updates.values(), job_id),
        )
        conn.commit()
        actor = str(user.get("username") or "unknown")
        log_audit_event(
            event_type="SCHEDULED_JOB_UPDATED", category="automation", severity="high", status="success",
            summary=f"Updated scheduled job '{name}' with verified approval",
            actor_username=actor, actor_role=user.get("role", "Operator"),
            source_ip=request.client.host if request.client else None,
            details={
                "job_id": job_id, "manifest_hash": binding_hash,
                "execution_manifest_hash": execution_manifest_hash,
                "changed_fields": sorted(set(payload) - {"approval_token", "approval_code", "operation_manifest"}),
                "approved_by": approval_record.get("approver_username"),
                "tenant_id": _actor_tenant(user),
            },
        )
        refresh_dynamic_scheduler()
        invalidate_read_cache('scheduled_jobs_future')
        return {"success": True, "message": "作业已成功更新（工单审批已校验）"}
    finally:
        conn.close()
