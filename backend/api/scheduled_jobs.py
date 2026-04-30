from fastapi import APIRouter, HTTPException, Body, Request, Depends
from typing import Optional
from datetime import datetime
import uuid
import logging
import os

from database import get_db_connection
from core.rbac import require_role
from core.config import settings
from services.config_approval_service import verify_code, consume_approval
from services.audit_service import log_audit_event

router = APIRouter()
logger = logging.getLogger(__name__)

# Import refresh logic from scheduler_manager
from core.scheduler_manager import refresh_dynamic_scheduler


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
                "items": [dict(r) for r in rows],
                "total": total,
                "page": page,
                "page_size": page_size,
            },
        }
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
    action_type = payload.get("action_type", "backup")  # 'backup' | 'inspection' (cron); 'command' | 'backup' | 'inspection' (once)
    cron_expr = (payload.get("cron_expr") or "").strip()
    scheduled_at = (payload.get("scheduled_at") or "").strip()
    device_scope = payload.get("device_scope", "all")
    device_filter = (payload.get("device_filter") or "").strip()
    commands = (payload.get("commands") or "").strip()
    script_id = (payload.get("script_id") or "").strip()
    is_config = 1 if payload.get("is_config") else 0
    config_reason = (payload.get("config_reason") or "").strip()

    if not name:
        raise HTTPException(status_code=400, detail="作业名称不能为空")
    # 定时作业（cron）仅支持备份和巡检
    if job_type == "cron" and action_type not in ("backup", "inspection", "script_run"):
        raise HTTPException(status_code=400, detail="定时作业仅支持配置备份、设备巡检和脚本执行")
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
                is_config, config_reason, enabled, status,
                approved_by, approved_at, created_by, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,'approved',?,?,?,?,?)""",
            (
                job_id, name, job_type, action_type, cron_expr, scheduled_at,
                device_scope, device_filter, commands, script_id,
                is_config, config_reason,
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

        return {"success": True, "message": "已更新"}
    finally:
        conn.close()


# ── Delete ──

@router.delete("/scheduled-jobs/{job_id}")
def delete_scheduled_job(
    job_id: str,
    request: Request,
    user=require_role("Operator"),
):
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM scheduled_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="作业不存在")
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
        return {"success": True, "data": dict(row)}
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
    """编辑已有定时作业（名称、调度、设备范围等）。"""
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

        if not name:
            raise HTTPException(status_code=400, detail="作业名称不能为空")
        if row["job_type"] == "cron" and action_type not in ("backup", "inspection", "script_run"):
            raise HTTPException(status_code=400, detail="定时作业仅支持配置备份、设备巡检和脚本执行")
        if row["job_type"] == "cron" and not cron_expr:
            raise HTTPException(status_code=400, detail="定时作业需要 cron 表达式")

        now = datetime.now().isoformat()
        conn.execute(
            """UPDATE scheduled_jobs
               SET name = ?, action_type = ?, cron_expr = ?,
                   device_scope = ?, device_filter = ?, config_reason = ?,
                   updated_at = ?
               WHERE id = ?""",
            (name, action_type, cron_expr, device_scope, device_filter, config_reason, now, job_id),
        )
        conn.commit()

        actor = user.get("username", "unknown")
        log_audit_event(
            event_type="SCHEDULED_JOB_UPDATED",
            category="automation",
            severity="medium",
            status="success",
            summary=f"Updated scheduled job '{name}'",
            actor_username=actor,
            actor_role=user.get("role", "Operator"),
            source_ip=request.client.host if request.client else None,
            details={"job_id": job_id, "job_name": name, "changes": payload},
        )
        
        # Refresh scheduler
        refresh_dynamic_scheduler()

        return {"success": True, "message": "作业已更新"}
    finally:
        conn.close()
