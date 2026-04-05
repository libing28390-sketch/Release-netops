from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime, timedelta, timezone
from database import get_db_connection

router = APIRouter()

@router.get("/jobs")
def read_jobs(
    status: Optional[str] = Query(default=None),
    time_range: Optional[str] = Query(default=None),
    page: Optional[int] = Query(default=None, ge=1),
    page_size: Optional[int] = Query(default=None, ge=1, le=200),
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
def read_job(job_id: str):
    conn = get_db_connection()
    try:
        job = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return dict(job)
    finally:
        conn.close()
