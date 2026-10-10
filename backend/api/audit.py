from fastapi import APIRouter, HTTPException, Query

from services.audit_service import get_audit_event, list_audit_events

router = APIRouter()


@router.get('/audit/events')
def read_audit_events(
    category: str = Query(default='all'),
    severity: str = Query(default='all'),
    status: str = Query(default='all'),
    time_range: str = Query(default='all'),
    search: str = Query(default=''),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    return list_audit_events(
        category=category,
        severity=severity,
        status=status,
        time_range=time_range,
        search=search,
        page=page,
        page_size=page_size,
    )


@router.get('/audit/events/{event_id}')
def read_audit_event(event_id: str):
    item = get_audit_event(event_id)
    if not item:
        raise HTTPException(status_code=404, detail='Audit event not found')
    return item
