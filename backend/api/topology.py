import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Request

from api.users import validate_session_token
from database import get_db_connection
from services.topology_service import (
    create_discovery_run,
    discover_lldp_neighbors,
    execute_discovery_run,
    get_current_links,
    get_discovery_run,
    get_unmanaged_neighbors,
    list_discovery_runs,
)

router = APIRouter()


def _get_authenticated_session(request: Request) -> dict:
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '') if auth.startswith('Bearer ') else ''
    sess = validate_session_token(token)
    if not sess:
        raise HTTPException(status_code=401, detail='Not authenticated')
    return sess


@router.post('/topology/discover')
async def trigger_discovery(background_tasks: BackgroundTasks):
    conn = get_db_connection()
    try:
        device_rows = conn.execute(
            '''
            SELECT id
            FROM devices
            WHERE status = 'online'
              AND COALESCE(ip_address, '') <> ''
              AND COALESCE(username, '') <> ''
              AND COALESCE(password, '') <> ''
            ORDER BY hostname
            '''
        ).fetchall()
    finally:
        conn.close()

    device_ids = [row['id'] for row in device_rows]
    if not device_ids:
        raise HTTPException(status_code=400, detail='No online devices with valid credentials available for topology discovery')

    run_id = create_discovery_run(device_ids=device_ids, requested_by='api', scope='full')
    background_tasks.add_task(execute_discovery_run, run_id, device_ids)
    return {
        'status': 'Discovery started in background',
        'run_id': run_id,
        'device_count': len(device_ids),
    }


@router.get('/topology/links')
def get_links(limit: int = 5000):
    """Return all topology links, optionally capped to `limit`.

    The default 5000 cap protects against meshed-DC blowups; the Topology
    canvas filters client-side anyway so a hard cap is acceptable.
    """
    managed_links = get_current_links(limit=limit)
    unmanaged = get_unmanaged_neighbors()
    return {
        'links': managed_links,
        'unmanaged_nodes': unmanaged.get('unmanaged_nodes', []),
        'unmanaged_links': unmanaged.get('unmanaged_links', []),
        'truncated': len(managed_links) >= limit,
        'limit': limit,
    }


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
def get_topology_discovery_run(run_id: str):
    payload = get_discovery_run(run_id)
    if not payload:
        raise HTTPException(status_code=404, detail='Topology discovery run not found')
    return payload