from fastapi import APIRouter, Body, HTTPException, Query, Request

from services.compliance_service import (
    ensure_builtin_rules,
    get_finding,
    get_overview,
    list_findings,
    list_rules,
    run_compliance_audit,
    update_finding,
)

router = APIRouter()


@router.get('/compliance/overview')
def read_compliance_overview():
    ensure_builtin_rules()
    return get_overview()


@router.get('/compliance/rules')
def read_compliance_rules():
    ensure_builtin_rules()
    return list_rules()


@router.get('/compliance/findings')
def read_compliance_findings(
    severity: str = Query(default='all'),
    status: str = Query(default='all'),
    category: str = Query(default='all'),
    search: str = Query(default=''),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    return list_findings(
        severity=severity,
        status=status,
        category=category,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.get('/compliance/findings/{finding_id}')
def read_compliance_finding(finding_id: str):
    item = get_finding(finding_id)
    if not item:
        raise HTTPException(status_code=404, detail='Finding not found')
    return item


@router.put('/compliance/findings/{finding_id}')
def update_compliance_finding(finding_id: str, payload: dict = Body(...)):
    item = update_finding(
        finding_id,
        status=payload.get('status'),
        owner=payload.get('owner'),
        note=payload.get('note'),
    )
    if not item:
        raise HTTPException(status_code=404, detail='Finding not found')
    return item


@router.post('/compliance/run')
def create_compliance_run(request: Request, payload: dict = Body(default={})):
    actor = payload.get('author') or payload.get('actor_username') or 'admin'
    actor_id = payload.get('actor_id')
    actor_role = payload.get('actor_role') or 'Administrator'
    device_ids = payload.get('device_ids') or None
    summary = run_compliance_audit(
        device_ids=device_ids,
        initiated_by=actor,
        actor_id=str(actor_id) if actor_id is not None else None,
        actor_role=actor_role,
        source_ip=request.client.host if request.client else None,
    )
    return summary
