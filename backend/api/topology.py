import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Body, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.users import validate_session_token
from database import get_db_connection
from services.topology_service import (
    create_discovery_run,
    execute_discovery_run,
    get_current_links,
    get_discovery_evidence,
    get_discovery_run,
    get_unmanaged_neighbors,
    get_topology_site_summaries,
    list_discovery_runs,
    request_cancel_discovery_run,
)

router = APIRouter()


class TopologyDiscoveryRequest(BaseModel):
    scope: str = Field(default='full', pattern='^(full|site|devices)$')
    site_id: str = ''
    device_ids: list[str] = Field(default_factory=list, max_length=500)


def _get_authenticated_session(request: Request) -> dict:
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '') if auth.startswith('Bearer ') else ''
    sess = validate_session_token(token)
    if not sess:
        raise HTTPException(status_code=401, detail='Not authenticated')
    return sess


@router.post('/topology/discover')
async def trigger_discovery(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: TopologyDiscoveryRequest | None = Body(default=None),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
):
    session = _get_authenticated_session(request)
    request_payload = payload or TopologyDiscoveryRequest()
    clauses = ["status = 'online'", "COALESCE(ip_address, '') <> ''"]
    params: list[object] = []
    if request_payload.site_id:
        clauses.append('site_id = ?')
        params.append(request_payload.site_id)
    if request_payload.device_ids:
        placeholders = ','.join('?' for _ in request_payload.device_ids)
        clauses.append(f'id IN ({placeholders})')
        params.extend(request_payload.device_ids)

    conn = get_db_connection()
    try:
        device_rows = conn.execute(
            f'''
            SELECT id
            FROM devices
            WHERE {' AND '.join(clauses)}
            ORDER BY hostname
            ''',
            tuple(params),
        ).fetchall()
    finally:
        conn.close()

    device_ids = [row['id'] for row in device_rows]
    if not device_ids:
        raise HTTPException(status_code=400, detail='No online devices match the requested topology discovery scope')

    requested_by = str(session.get('username') or session.get('user_id') or 'api')
    run_id = create_discovery_run(
        device_ids=device_ids,
        requested_by=requested_by,
        scope=request_payload.scope,
        site_id=request_payload.site_id,
        scope_payload=request_payload.model_dump(),
        idempotency_key=idempotency_key or '',
    )
    existing_run = get_topology_discovery_run(run_id)
    run_status = str((existing_run or {}).get('run', {}).get('status') or 'pending')
    if run_status not in {'pending', 'running'}:
        return {
            'status': 'Discovery request already completed',
            'run_id': run_id,
            'device_count': len(device_ids),
            'run_status': run_status,
        }
    background_tasks.add_task(execute_discovery_run, run_id, device_ids)
    return {
        'status': 'Discovery started in background',
        'run_id': run_id,
        'device_count': len(device_ids),
    }


@router.get('/topology/links')
def get_links(
    limit: int = Query(default=5000, ge=1, le=20000),
    site_id: str | None = Query(default=None),
    include_stale: bool = Query(default=True),
):
    """Return all topology links, optionally capped to `limit`.

    The default 5000 cap protects against meshed-DC blowups; the Topology
    canvas filters client-side anyway so a hard cap is acceptable.
    """
    managed_links = get_current_links(limit=limit, site_id=site_id, include_stale=include_stale)
    unmanaged = get_unmanaged_neighbors(site_id=site_id)
    return {
        'links': managed_links,
        'unmanaged_nodes': unmanaged.get('unmanaged_nodes', []),
        'unmanaged_links': unmanaged.get('unmanaged_links', []),
        'truncated': len(managed_links) >= limit,
        'limit': limit,
    }


@router.get('/topology/sites')
def get_topology_sites():
    return {'items': get_topology_site_summaries()}


@router.get('/topology/layout')
def get_topology_layout(request: Request):
    sess = _get_authenticated_session(request)
    conn = get_db_connection()
    try:
        row = conn.execute(
            'SELECT layout_json, updated_at FROM topology_layouts WHERE user_id = ?',
            (sess['user_id'],),
        ).fetchone()
        if not row:
            return {'layout': {}, 'updated_at': None}
        try:
            layout = json.loads(row['layout_json'] or '{}')
        except Exception:
            layout = {}
        return {'layout': layout, 'updated_at': row['updated_at']}
    finally:
        conn.close()


@router.put('/topology/layout')
def save_topology_layout(request: Request, payload: dict = Body(...)):
    sess = _get_authenticated_session(request)
    layout = payload.get('layout') if isinstance(payload, dict) else None
    if layout is None:
        raise HTTPException(status_code=400, detail='layout is required')

    try:
        serialized = json.dumps(layout)
    except TypeError as exc:
        raise HTTPException(status_code=400, detail=f'layout is not JSON serializable: {exc}')

    conn = get_db_connection()
    try:
        updated_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            '''
            INSERT INTO topology_layouts (user_id, layout_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET layout_json = excluded.layout_json, updated_at = excluded.updated_at
            ''',
            (sess['user_id'], serialized, updated_at),
        )
        conn.commit()
        return {'success': True, 'updated_at': updated_at}
    finally:
        conn.close()


@router.get('/topology/discovery-runs')
def get_topology_discovery_runs(limit: int = 20):
    safe_limit = max(1, min(limit, 100))
    return list_discovery_runs(limit=safe_limit)


@router.get('/topology/discovery-runs/{run_id}')
def get_topology_discovery_run(
    run_id: str,
    device_limit: int = Query(default=100, ge=1, le=500),
    device_offset: int = Query(default=0, ge=0),
):
    payload = get_discovery_run(run_id, device_limit=device_limit, device_offset=device_offset)
    if not payload:
        raise HTTPException(status_code=404, detail='Topology discovery run not found')
    return payload


@router.get('/topology/discovery-runs/{run_id}/evidence')
def get_topology_discovery_evidence(
    run_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    match_status: str | None = Query(default=None),
    include_raw: bool = Query(default=False),
):
    _get_authenticated_session(request)
    payload = get_discovery_evidence(
        run_id,
        limit=limit,
        offset=offset,
        match_status=match_status,
        include_raw=include_raw,
    )
    if not payload:
        raise HTTPException(status_code=404, detail='Topology discovery run not found')
    return payload


@router.post('/topology/discovery-runs/{run_id}/cancel')
def cancel_topology_discovery_run(run_id: str, request: Request):
    _get_authenticated_session(request)
    if not request_cancel_discovery_run(run_id):
        raise HTTPException(status_code=404, detail='Topology discovery run not found')
    return {'success': True, 'run_id': run_id, 'status': 'cancelling'}
