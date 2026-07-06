from fastapi import APIRouter, HTTPException, Body, BackgroundTasks
from typing import List, Optional
from services.discovery_service import DiscoveryService
from core.rbac import require_role
import logging

_logger = logging.getLogger(__name__)
router = APIRouter()

@router.post('/discovery/device/{device_id}')
def api_discover_device(
    device_id: str,
    _user=require_role('Operator')
):
    """Trigger synchronous active discovery on a single device ID."""
    svc = DiscoveryService()
    res = svc.discover_device(device_id)
    if not res.get("success", False):
        raise HTTPException(status_code=500, detail=res.get("error", "Discovery run failed"))
    return res

@router.post('/discovery/start')
def api_batch_discover(
    device_ids: List[str] = Body(..., embed=True),
    _user=require_role('Operator')
):
    """Trigger synchronous active discovery on a batch list of device IDs."""
    svc = DiscoveryService()
    results = []
    failed_cnt = 0
    for device_id in device_ids:
        res = svc.discover_device(device_id)
        results.append(res)
        if not res.get("success", False):
            failed_cnt += 1
            
    return {
        "total": len(device_ids),
        "successful": len(device_ids) - failed_cnt,
        "failed": failed_cnt,
        "results": results
    }
