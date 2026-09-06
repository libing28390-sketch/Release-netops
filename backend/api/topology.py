import json
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Body, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.users import validate_session_token
from core.rbac import require_role
from database import get_db_connection
from core.read_cache import (
    TOPOLOGY_CACHE_TTL_SECONDS,
    read_cache,
)
from services.topology_service import (
    create_discovery_run,
    execute_discovery_run,
    get_current_links,
    get_discovery_evidence,
    get_discovery_run,
    get_unmanaged_neighbors,
    get_topology_generation_status,
    get_topology_node_metadata,
    get_topology_site_summaries,
    list_discovery_runs,
    request_cancel_discovery_run,
    select_topology_discovery_devices,
)
from services.topology_graph_service import (
    apply_layout_override,
    apply_relation_override,
    build_graph,
    get_edge_evidence,
    get_graph,
    get_physical_links,
    get_topology_history,
    persist_graph,
    record_manual_layout_override,
    record_manual_relation_override,
)
from services import rack_scope_service

# All topology data is tenant-scoped operational data.  Require an
# authenticated viewer at the router boundary and make state-changing or
# device-affecting operations declare their stronger role below.
router = APIRouter(dependencies=[require_role("Viewer")])


class TopologyDiscoveryRequest(BaseModel):
    scope: str = Field(default='full', pattern='^(full|site|devices)$')
    site_id: str = ''
    device_ids: list[str] = Field(default_factory=list, max_length=500)


_SCOPE_ERROR_MESSAGES = {
    'topology_scope_invalid': 'Topology discovery scope must be full, site, or devices.',
    'topology_site_required': 'site_id is required when scope is site.',
    'topology_device_ids_required': 'device_ids is required when scope is devices.',
    'topology_full_scope_has_selectors': 'Full discovery scope cannot include site_id or device_ids.',
    'topology_site_scope_has_device_ids': 'Site discovery scope cannot include device_ids.',
    'topology_device_scope_has_site_id': 'Device discovery scope cannot include site_id.',
    'topology_site_not_found': 'The requested topology site does not exist.',
}


def _get_authenticated_session(request: Request) -> dict:
    auth = request.headers.get('Authorization', '')
    token = auth.replace('Bearer ', '') if auth.startswith('Bearer ') else ''
    sess = validate_session_token(token)
    if not sess:
        raise HTTPException(status_code=401, detail='Not authenticated')
    return sess


def _resolve_graph_tenant(session: dict, requested_tenant: object = None) -> str:
    """Keep graph reads and writes inside the caller's tenant boundary."""
    session_tenant = str(session.get('tenant_id') or 'tenant-default').strip() or 'tenant-default'
    requested = str(requested_tenant or session_tenant).strip() or session_tenant
    if str(session.get('role') or '').lower() == 'administrator':
        return requested
    if requested != session_tenant:
        raise HTTPException(status_code=403, detail='Topology tenant access denied')
    return session_tenant


def _topology_asset_scope(conn, user):
    """Topology inventory follows the same site-owned asset boundary."""

    if not isinstance(user, dict):
        return None
    return rack_scope_service.allowed_resource_scope(conn, user, 'asset', 'view')


def _authorized_topology_device_ids(conn, scope) -> list[str] | None:
    """Resolve one bounded device set for all legacy topology read models."""

    if scope is None:
        return None
    if scope.site_ids is not None and not scope.site_ids:
        return []
    clauses: list[str] = []
    params: list[str] = []
    if scope.site_ids is not None:
        placeholders = ','.join('?' for _ in scope.site_ids)
        clauses.append(f's.id IN ({placeholders})')
        params.extend(scope.site_ids)
    if scope.tenant_id:
        clauses.append('s.tenant_id = ?')
        params.append(scope.tenant_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
    rows = conn.execute(
        f'''SELECT d.id
              FROM devices d
              LEFT JOIN physical_assets pa ON pa.id = d.asset_id
              LEFT JOIN sites s ON s.id = COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, ''))
              {where}
             ORDER BY d.id''',
        tuple(params),
    ).fetchall()
    return [str(row['id']) for row in rows if str(row['id'] or '').strip()]


def _enforce_topology_site_scope(conn, user, site_id: str) -> None:
    if isinstance(user, dict) and str(site_id or '').strip():
        rack_scope_service.enforce_site(
            conn,
            user,
            site_id,
            'view',
            resource_type='asset',
        )


@router.post('/topology/discover')
async def trigger_discovery(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: TopologyDiscoveryRequest | None = Body(default=None),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    _user=require_role("Operator"),
):
    session = _get_authenticated_session(request)
    request_payload = payload or TopologyDiscoveryRequest()
    scope_conn = get_db_connection()
    try:
        topology_scope = _topology_asset_scope(scope_conn, _user)
        if request_payload.site_id:
            _enforce_topology_site_scope(scope_conn, _user, request_payload.site_id)
        allowed_device_ids = _authorized_topology_device_ids(scope_conn, topology_scope)
    finally:
        scope_conn.close()
    try:
        selection = select_topology_discovery_devices(
            request_payload.scope,
            site_id=request_payload.site_id,
            device_ids=request_payload.device_ids,
            allowed_device_ids=allowed_device_ids,
        )
    except ValueError as exc:
        code = str(exc)
        raise HTTPException(
            status_code=422,
            detail={'code': code, 'message': _SCOPE_ERROR_MESSAGES.get(code, code)},
        ) from exc

    device_ids = selection['device_ids']
    if not device_ids:
        raise HTTPException(
            status_code=400,
            detail={
                'code': 'topology_scope_empty',
                'message': 'No online device with a management IP matches the requested topology discovery scope.',
                'excluded_device_ids': selection['excluded_device_ids'],
            },
        )

    requested_by = str(session.get('username') or session.get('user_id') or 'api')
    run_id = create_discovery_run(
        device_ids=device_ids,
        requested_by=requested_by,
        scope=selection['scope'],
        site_id=selection['site_id'],
        scope_payload={
            **request_payload.model_dump(),
            'resolved_site_id': selection['site_id'],
            'selected_device_ids': device_ids,
            'excluded_device_ids': selection['excluded_device_ids'],
        },
        idempotency_key=idempotency_key or '',
    )
    existing_run = get_discovery_run(run_id)
    run_status = str((existing_run or {}).get('run', {}).get('status') or 'pending')
    if run_status not in {'pending', 'running'}:
        return {
            'status': 'Discovery request already completed',
            'run_id': run_id,
            'device_count': len(device_ids),
            'excluded_device_count': len(selection['excluded_device_ids']),
            'run_status': run_status,
        }
    background_tasks.add_task(execute_discovery_run, run_id, device_ids)
    return {
        'status': 'Discovery started in background',
        'run_id': run_id,
        'device_count': len(device_ids),
        'excluded_device_count': len(selection['excluded_device_ids']),
        'scope': selection['scope'],
        'site_id': selection['site_id'],
    }


@router.get('/topology/links')
def get_links(
    limit: int = Query(default=5000, ge=1, le=20000),
    site_id: str | None = Query(default=None),
    rack_id: str | None = Query(default=None, max_length=128),
    include_stale: bool = Query(default=False),
    _user=require_role("Viewer"),
):
    """Return current topology links, optionally including stale evidence.

    The default 5000 cap protects against meshed-DC blowups; the Topology
    canvas asks explicitly for stale links when the historical-evidence toggle
    is enabled. Current topology must not silently render expired neighbors.
    """
    # v3 invalidates responses generated before the physical-link read model
    # started carrying aggregation parent/member fields.
    normalized_rack_id = str(rack_id or '').strip()
    device_ids: list[str] | None = None
    conn = get_db_connection()
    try:
        scope = _topology_asset_scope(conn, _user)
        authorized_device_ids = _authorized_topology_device_ids(conn, scope)
        if site_id:
            _enforce_topology_site_scope(conn, _user, str(site_id))
        if normalized_rack_id:
            rack = conn.execute(
                '''SELECT r.*, s.tenant_id AS site_tenant_id
                     FROM racks r LEFT JOIN sites s ON s.id = r.site_id
                    WHERE r.id = ? OR r.rack_code = ?
                    LIMIT 1''',
                (normalized_rack_id, normalized_rack_id),
            ).fetchone()
            if not rack:
                raise HTTPException(status_code=404, detail='Rack not found')
            if isinstance(_user, dict):
                rack_scope_service.enforce_loaded_rack(_user, dict(rack), 'view')
            resolved_rack_id = str(rack['id'])
            device_ids = [
                str(row['id'])
                for row in conn.execute(
                    '''SELECT DISTINCT d.id
                       FROM rack_devices rd
                       JOIN devices d ON d.asset_id = rd.asset_id
                       WHERE rd.rack_id = ?
                       ORDER BY d.id''',
                    (resolved_rack_id,),
                ).fetchall()
            ]
            if authorized_device_ids is not None:
                allowed_set = set(authorized_device_ids)
                device_ids = [item for item in device_ids if item in allowed_set]
        elif authorized_device_ids is not None:
            device_ids = authorized_device_ids
    finally:
        conn.close()

    scope_key = scope.cache_key if scope is not None else 'legacy'
    cache_key = f'links:v5:{limit}:{site_id or ""}:{normalized_rack_id}:{int(include_stale)}:{scope_key}'
    cache_hit, cached = read_cache.get('topology', cache_key)
    if cache_hit:
        return cached

    # Physical links must come from the read model that carries the LAG
    # contract (aggregation name, member count and member pairs).  The
    # evidence graph is authoritative for logical relations, but its physical
    # edge projection intentionally contains only relation facts and would
    # otherwise expand a four-member bundle back into four raw lines.
    try:
        managed_links = get_current_links(
            limit=limit,
            site_id=site_id,
            device_ids=device_ids,
            include_stale=include_stale,
        )
        graph_read_model = 'legacy_topology_links_aggregation'
    except Exception:
        managed_links = get_physical_links(
            tenant_id=(scope.tenant_id if scope and scope.tenant_id else 'tenant-default'),
            site_id=site_id,
            limit=limit,
            include_stale=include_stale,
            device_ids=device_ids,
        )
        graph_read_model = 'evidence_graph_fallback'
    if not managed_links:
        legacy_links = get_current_links(
            limit=limit,
            site_id=site_id,
            device_ids=device_ids,
            include_stale=include_stale,
        )
        if legacy_links:
            managed_links = legacy_links
            graph_read_model = 'legacy_topology_links_fallback'
    unmanaged = (
        # A rack selector is already a closed managed-device scope.  The
        # unmanaged-neighbor table is site/global evidence and must not be
        # queried for a rack-only response, otherwise unrelated neighbors can
        # be reintroduced through this auxiliary read model.
        {'unmanaged_nodes': [], 'unmanaged_links': []}
        if normalized_rack_id or (device_ids is not None and not device_ids)
        else get_unmanaged_neighbors(site_id=site_id, source_device_ids=device_ids)
    )
    node_metadata = get_topology_node_metadata(site_id=site_id, device_ids=device_ids)
    if device_ids is not None:
        scoped_ids = set(device_ids)
        node_metadata = {key: value for key, value in node_metadata.items() if key in scoped_ids}
    response = {
        'links': managed_links,
        'node_metadata': node_metadata,
        'unmanaged_nodes': unmanaged.get('unmanaged_nodes', []),
        'unmanaged_links': unmanaged.get('unmanaged_links', []),
        'truncated': len(managed_links) >= limit,
        'limit': limit,
        'graph_read_model': graph_read_model,
    }
    read_cache.set('topology', cache_key, response, TOPOLOGY_CACHE_TTL_SECONDS)
    return response


@router.get('/topology/sites')
def get_topology_sites(_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        scope = _topology_asset_scope(conn, _user)
        device_ids = _authorized_topology_device_ids(conn, scope)
    finally:
        conn.close()
    scope_key = scope.cache_key if scope is not None else 'legacy'
    cache_hit, cached = read_cache.get('topology', f'sites:v3:{scope_key}')
    if cache_hit:
        return cached
    response = {
        'items': get_topology_site_summaries(
            tenant_id=scope.tenant_id if scope else None,
            site_ids=scope.site_ids if scope else None,
            device_ids=device_ids,
        )
    }
    read_cache.set('topology', f'sites:v3:{scope_key}', response, TOPOLOGY_CACHE_TTL_SECONDS)
    return response


@router.get('/topology/generation-status')
def get_generation_status(_user=require_role("Viewer")):
    conn = get_db_connection()
    try:
        scope = _topology_asset_scope(conn, _user)
        device_ids = _authorized_topology_device_ids(conn, scope)
    finally:
        conn.close()
    return get_topology_generation_status(device_ids=device_ids)


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
def save_topology_layout(request: Request, payload: dict = Body(...), _user=require_role("Operator")):
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
def get_topology_discovery_runs(limit: int = 20, _user=require_role("Viewer")):
    safe_limit = max(1, min(limit, 100))
    conn = get_db_connection()
    try:
        scope = _topology_asset_scope(conn, _user)
        device_ids = _authorized_topology_device_ids(conn, scope)
    finally:
        conn.close()
    return list_discovery_runs(limit=safe_limit, device_ids=device_ids)


@router.get('/topology/discovery-runs/{run_id}')
def get_topology_discovery_run(
    run_id: str,
    device_limit: int = Query(default=100, ge=1, le=500),
    device_offset: int = Query(default=0, ge=0),
    _user=require_role("Viewer"),
):
    conn = get_db_connection()
    try:
        scope = _topology_asset_scope(conn, _user)
        device_ids = _authorized_topology_device_ids(conn, scope)
    finally:
        conn.close()
    payload = get_discovery_run(
        run_id,
        device_limit=device_limit,
        device_offset=device_offset,
        device_ids=device_ids,
    )
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
    session = _get_authenticated_session(request)
    conn = get_db_connection()
    try:
        scope = _topology_asset_scope(conn, session)
        device_ids = _authorized_topology_device_ids(conn, scope)
    finally:
        conn.close()
    payload = get_discovery_evidence(
        run_id,
        limit=limit,
        offset=offset,
        match_status=match_status,
        include_raw=include_raw,
        device_ids=device_ids,
    )
    if not payload:
        raise HTTPException(status_code=404, detail='Topology discovery run not found')
    return payload


@router.post('/topology/discovery-runs/{run_id}/cancel')
def cancel_topology_discovery_run(run_id: str, request: Request, _user=require_role("Operator")):
    session = _get_authenticated_session(request)
    conn = get_db_connection()
    try:
        scope = _topology_asset_scope(conn, session)
        device_ids = _authorized_topology_device_ids(conn, scope)
    finally:
        conn.close()
    if not get_discovery_run(run_id, device_limit=1, device_ids=device_ids):
        raise HTTPException(status_code=404, detail='Topology discovery run not found')
    if not request_cancel_discovery_run(run_id):
        raise HTTPException(status_code=404, detail='Topology discovery run not found')
    return {'success': True, 'run_id': run_id, 'status': 'cancelling'}


@router.get('/topology/graph')
def get_evidence_graph(
    request: Request,
    view: str = Query(default='all', pattern='^(all|physical|l2|l3|logical|site|external|oob)$'),
    site_id: str | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=20000),
    include_stale: bool = Query(default=False),
    tenant_id: str | None = Query(default=None),
):
    """Return a paged graph read model with evidence-derived layout ranks."""
    session = _get_authenticated_session(request)
    tenant_id = _resolve_graph_tenant(session, tenant_id)
    scope_conn = get_db_connection()
    try:
        topology_scope = _topology_asset_scope(scope_conn, session)
        if site_id:
            _enforce_topology_site_scope(scope_conn, session, site_id)
        allowed_device_ids = _authorized_topology_device_ids(scope_conn, topology_scope)
    finally:
        scope_conn.close()
    # Routing neighbors are collected by a separate inventory job.  Project
    # the current routing table before every graph read so the L3/logical view
    # reflects already-collected data immediately instead of waiting for the
    # next LLDP discovery cycle.
    try:
        from services.topology_service import _sync_evidence_graph_from_observations
        _sync_evidence_graph_from_observations()
    except Exception:
        pass
    return get_graph(
        tenant_id=tenant_id, view=view, site_id=site_id, limit=limit,
        include_stale=include_stale,
        device_ids=allowed_device_ids,
    )


@router.post('/topology/graph/rebuild')
def rebuild_evidence_graph(request: Request, payload: dict = Body(...), _user=require_role("Operator")):
    """Normalize a discovery batch and persist nodes/edges/evidence.

    This endpoint accepts observation metadata only. Raw device output belongs
    to the discovery evidence retention path and is not copied into the graph.
    """
    session = _get_authenticated_session(request)
    tenant_id = _resolve_graph_tenant(session, payload.get('tenant_id'))
    nodes = payload.get('nodes') if isinstance(payload.get('nodes'), list) else []
    observations = payload.get('observations') if isinstance(payload.get('observations'), list) else []
    graph = build_graph(nodes, observations, tenant_id=tenant_id)
    counts = persist_graph(graph)
    return {"success": True, **counts, "layout": graph.get("ranks", {})}


@router.get('/topology/graph/edges/{edge_id}/evidence')
def get_graph_edge_evidence(
    edge_id: str,
    request: Request,
    tenant_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
):
    session = _get_authenticated_session(request)
    tenant_id = _resolve_graph_tenant(session, tenant_id)
    conn = get_db_connection()
    try:
        topology_scope = _topology_asset_scope(conn, session)
        allowed_device_ids = _authorized_topology_device_ids(conn, topology_scope)
    finally:
        conn.close()
    return {
        "edge_id": edge_id,
        "items": get_edge_evidence(
            edge_id,
            tenant_id=tenant_id,
            limit=limit,
            device_ids=allowed_device_ids,
        ),
    }


@router.get('/topology/graph/history')
def get_graph_history(
    request: Request,
    tenant_id: str | None = Query(default=None),
    edge_id: str | None = Query(default=None),
    node_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    session = _get_authenticated_session(request)
    tenant_id = _resolve_graph_tenant(session, tenant_id)
    conn = get_db_connection()
    try:
        topology_scope = _topology_asset_scope(conn, session)
        allowed_device_ids = _authorized_topology_device_ids(conn, topology_scope)
    finally:
        conn.close()
    return get_topology_history(
        tenant_id=tenant_id,
        edge_id=edge_id,
        node_id=node_id,
        event_type=event_type,
        limit=limit,
        offset=offset,
        device_ids=allowed_device_ids,
    )


@router.put('/topology/graph/edges/{edge_id}/relation')
def override_graph_relation(edge_id: str, request: Request, payload: dict = Body(...), _user=require_role("Operator")):
    session = _get_authenticated_session(request)
    relation = str(payload.get('relation_type') or '').upper()
    tenant_id = _resolve_graph_tenant(session, payload.get('tenant_id'))
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT * FROM topology_edges WHERE id = ? AND tenant_id = ?",
            (edge_id, tenant_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Topology edge not found')
        before = dict(row)
        try:
            metadata = json.loads(row['metadata_json'] or '{}')
        except Exception:
            metadata = {}
        updated = apply_relation_override({
            "id": before['id'], "tenant_id": before['tenant_id'],
            "source_node_id": before['source_node_id'], "target_node_id": before['target_node_id'],
            "relation_type": before['relation_type'], "direction": before['direction'],
            "semantic_relation": before.get('semantic_relation') or '',
            "rank_excluded": before.get('rank_excluded') or 0,
            "metadata": metadata, "is_manual": before.get('is_manual') or 0,
        }, relation_type=relation, actor=str(session.get('username') or 'api'))
        conn.execute(
            """
            UPDATE topology_edges
            SET relation_type = ?, semantic_relation = ?, rank_excluded = ?,
                is_manual = 1, manual_confirmed = 1, metadata_json = ?, updated_at = ?
            WHERE id = ? AND tenant_id = ?
            """,
            (
                updated['relation_type'], updated.get('semantic_relation') or '',
                int(updated.get('rank_excluded') or 0),
                json.dumps(updated['metadata'], ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(), edge_id, tenant_id,
            ),
        )
        try:
            conn.execute(
                """
                UPDATE topology_relations
                SET relation_type = ?, semantic_relation = ?, rank_excluded = ?,
                    is_manual = 1, metadata_json = ?, updated_at = ?
                WHERE edge_id = ? AND tenant_id = ?
                """,
                (
                    updated['relation_type'], updated.get('semantic_relation') or '',
                    int(updated.get('rank_excluded') or 0),
                    json.dumps(updated['metadata'], ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(), edge_id, tenant_id,
                ),
            )
        except Exception:
            pass
        conn.commit()
        after = {
            'relation_type': updated['relation_type'],
            'semantic_relation': updated.get('semantic_relation') or '',
            'rank_excluded': int(updated.get('rank_excluded') or 0),
            'is_manual': 1,
            'manual_confirmed': 1,
        }
        try:
            record_manual_relation_override(
                edge_id, tenant_id=tenant_id,
                before={
                    'relation_type': before.get('relation_type'),
                    'semantic_relation': before.get('semantic_relation') or '',
                    'is_manual': before.get('is_manual') or 0,
                },
                after=after,
                actor=str(session.get('username') or 'api'),
            )
        except Exception:
            pass
        return {"success": True, "edge_id": edge_id, "relation_type": updated['relation_type'], "is_manual": True}
    finally:
        conn.close()


@router.put('/topology/graph/nodes/{node_id}/layout')
def override_graph_layout(node_id: str, request: Request, payload: dict = Body(...), _user=require_role("Operator")):
    session = _get_authenticated_session(request)
    tenant_id = _resolve_graph_tenant(session, payload.get('tenant_id'))
    try:
        override = apply_layout_override(payload.get('layout') or {}, x=float(payload['x']), y=float(payload['y']))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail='x and y must be finite numbers') from exc
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id, layout_override_json FROM topology_nodes WHERE id = ? AND tenant_id = ?",
            (node_id, tenant_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Topology node not found')
        try:
            before = json.loads(row['layout_override_json'] or '{}')
        except Exception:
            before = {}
        saved_layout = {**override, 'updated_by': session.get('username', 'api')}
        conn.execute(
            "UPDATE topology_nodes SET layout_override_json = ?, updated_at = ? WHERE id = ? AND tenant_id = ?",
            (json.dumps(saved_layout, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), node_id, tenant_id),
        )
        conn.commit()
        try:
            record_manual_layout_override(
                node_id, tenant_id=tenant_id, before=before, after=saved_layout,
                actor=str(session.get('username') or 'api'),
            )
        except Exception:
            pass
        return {"success": True, "node_id": node_id, "layout": override}
    finally:
        conn.close()
