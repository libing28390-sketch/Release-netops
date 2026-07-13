from fastapi import APIRouter, HTTPException, Body
from typing import List, Optional
from services.discovery_service import DiscoveryService
from core.rbac import require_role
from services.job_service import create_job
import logging

_logger = logging.getLogger(__name__)
router = APIRouter()

@router.post('/discovery/device/{device_id}')
def api_discover_device(
    device_id: str,
    user=require_role('Operator')
):
    """Trigger synchronous active discovery on a single device ID."""
    svc = DiscoveryService()
    res = svc.discover_device(device_id, requested_by=user.get('username', 'system'))
    if not res.get("success", False):
        raise HTTPException(status_code=500, detail=res.get("error", "Discovery run failed"))
    return res

@router.post('/discovery/start')
def api_batch_discover(
    device_ids: List[str] = Body(..., embed=True),
    user=require_role('Operator')
):
    """Queue batch discovery in the unified job lifecycle."""
    if not device_ids:
        raise HTTPException(status_code=422, detail='device_ids must not be empty')
    return create_job(
        job_type='discovery', task_name='Network device discovery',
        created_by=user.get('username', 'system'),
        targets=[{'target_type': 'device', 'target_id': device_id} for device_id in device_ids],
        steps=['connect', 'collect', 'normalize', 'reconcile'],
        concurrency_limit=min(10, max(1, len(device_ids))), retry_limit=1,
        timeout_seconds=600, scope={'device_ids': device_ids},
    )
