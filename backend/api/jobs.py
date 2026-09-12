from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timedelta, timezone
from database import get_db_connection
from core.rbac import require_permission
from services import job_service
from services.job_worker import run_job

router = APIRouter()


class JobCreate(BaseModel):
    job_type: str
    task_name: str
    targets: list[dict]
    steps: list[str] = Field(default_factory=lambda: ['execute'])
    concurrency_limit: int = Field(5, ge=1, le=200)
    retry_limit: int = Field(0, ge=0, le=10)
    timeout_seconds: int = Field(300, ge=1, le=86400)
    scope: dict = Field(default_factory=dict)


class TargetComplete(BaseModel):
    status: str
    result: dict = Field(default_factory=dict)
    error_message: str = ''

@router.get("/jobs")
def read_jobs(
    status: Optional[str] = Query(default=None),
    time_range: Optional[str] = Query(default=None),
    page: Optional[int] = Query(default=None, ge=1),
    page_size: Optional[int] = Query(default=None, ge=1, le=200),
    _user=require_permission('job', 'read'),
):
    conn = get_db_connection()
    try:
        where_clauses = []
        params = []

        if status and status != 'all':
            where_clauses.append('status = ?')
            params.append(status)

        if time_range and time_range != 'all':
            _delta = {'24h': 1, '7d': 7, '30d': 30}.get(time_range)
            if _delta:
                _cutoff = (datetime.now(timezone.utc) - timedelta(days=_delta)).isoformat()
                where_clauses.append("created_at >= ?")
                params.append(_cutoff)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ''

        # Backward-compatible mode: no pagination params -> return array like before.
        # Safety cap: never return more than 500 rows without explicit pagination.
        if page is None or page_size is None:
            jobs = conn.execute(
                f'SELECT * FROM jobs {where_sql} ORDER BY created_at DESC LIMIT 500',
                tuple(params)
            ).fetchall()
            return [dict(j) for j in jobs]

        total_row = conn.execute(
            f'SELECT COUNT(*) AS count FROM jobs {where_sql}',
            tuple(params)
        ).fetchone()
        total = int(total_row['count']) if total_row else 0

        offset = (page - 1) * page_size
        paged_jobs = conn.execute(
            f'SELECT * FROM jobs {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?',
            tuple([*params, page_size, offset])
        ).fetchall()

        return {
            'items': [dict(j) for j in paged_jobs],
            'total': total,
            'page': page,
            'page_size': page_size,
        }
    finally:
        conn.close()

@router.get("/jobs/{job_id}")
def read_job(job_id: str, _user=require_permission('job', 'read')):
    try:
        return job_service.get_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post('/jobs', status_code=201)
def create_job(body: JobCreate, user=require_permission('job', 'execute')):
    try:
        return job_service.create_job(**body.model_dump(), created_by=user.get('username', 'system'))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post('/jobs/{job_id}/cancel')
def cancel_job(job_id: str, user=require_permission('job', 'execute')):
    try:
        return job_service.request_cancel(job_id, requested_by=user.get('username', 'system'))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/jobs/{job_id}/claim-targets')
def claim_job_targets(job_id: str, limit: int | None = Query(None, ge=1, le=200), _user=require_permission('job', 'execute')):
    try:
        return {'items': job_service.claim_targets(job_id, limit=limit)}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/jobs/targets/{target_id}/complete')
def complete_job_target(target_id: str, body: TargetComplete, _user=require_permission('job', 'execute')):
    try:
        return job_service.complete_target(target_id, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/jobs/{job_id}/retry')
def retry_job(job_id: str, user=require_permission('job', 'execute')):
    try:
        return job_service.retry_failed_targets(job_id, requested_by=user.get('username', 'system'))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/jobs/{job_id}/run')
def run_queued_job(job_id: str, background_tasks: BackgroundTasks, _user=require_permission('job', 'execute')):
    try:
        job = job_service.get_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if job.get('job_type') == 'credential_password_sync':
        from services.credential_password_sync_service import run_credential_password_sync_job
        background_tasks.add_task(run_credential_password_sync_job, job_id)
    else:
        background_tasks.add_task(run_job, job_id)
    return {'job_id': job_id, 'status': 'queued'}
