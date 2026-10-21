from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.rbac import require_permission, require_role
from services import reconciliation_service


router = APIRouter()


class ActionRequest(BaseModel):
    action_type: str
    payload: dict = Field(default_factory=dict)


class ActionReview(BaseModel):
    reason: str = ''


@router.post('/ipam/reconciliation/runs', status_code=201)
def create_run(user=require_permission('ip_address', 'execute')):
    return reconciliation_service.materialize_current_ipam_findings(requested_by=user.get('username', 'system'))


@router.get('/ipam/reconciliation/runs')
def read_runs(status: str = '', page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), _user=require_permission('ip_address', 'read')):
    return reconciliation_service.list_runs(status=status, page=page, page_size=page_size)


@router.get('/ipam/reconciliation/findings')
def read_findings(run_id: str = '', status: str = '', risk_level: str = '', _user=require_permission('ip_address', 'read')):
    return reconciliation_service.list_findings(run_id=run_id, status=status, risk_level=risk_level)


@router.post('/ipam/reconciliation/findings/{finding_id}/actions', status_code=201)
def request_finding_action(finding_id: str, body: ActionRequest, user=require_permission('ip_address', 'update')):
    try:
        return reconciliation_service.request_action(
            finding_id, action_type=body.action_type,
            requested_by=user.get('username', 'system'), payload=body.payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/ipam/reconciliation/actions/{action_id}/approve')
def approve_finding_action(action_id: str, user=require_role('Administrator')):
    try:
        return reconciliation_service.approve_action(action_id, approved_by=user.get('username', 'system'))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post('/ipam/reconciliation/actions/{action_id}/reject')
def reject_finding_action(action_id: str, body: ActionReview, user=require_role('Administrator')):
    try:
        return reconciliation_service.reject_action(
            action_id, rejected_by=user.get('username', 'system'), reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
