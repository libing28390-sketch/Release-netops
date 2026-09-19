from fastapi import APIRouter, HTTPException, Query, Body, Depends
from typing import Optional, List
from repository.inventory_repository import InventoryRepository
from domain.models import Interface
from core.rbac import require_role
import logging

_logger = logging.getLogger(__name__)
router = APIRouter()

@router.get('/interfaces')
def api_list_interfaces(
    device_id: Optional[str] = Query(default=None),
    _user=require_role('Viewer')
):
    """List interfaces with optional device filter via Repository."""
    repo = InventoryRepository()
    try:
        interfaces = repo.list_interfaces(device_id)
        return [item.__dict__ for item in interfaces]
    except Exception as exc:
        _logger.error(f"Failed to list interfaces: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database lookup failed")

@router.get('/devices/{device_id}/interfaces')
def api_get_device_interfaces(
    device_id: str,
    _user=require_role('Viewer')
):
    """Get interfaces belonging to a specific device via Repository."""
    repo = InventoryRepository()
    try:
        interfaces = repo.list_interfaces(device_id)
        return [item.__dict__ for item in interfaces]
    except Exception as exc:
        _logger.error(f"Failed to get device {device_id} interfaces: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database lookup failed")

@router.get('/inventory/summary')
def api_get_inventory_summary(
    _user=require_role('Viewer')
):
    """Get global inventory summary counters (devices, interfaces, status, CRC errors)."""
    repo = InventoryRepository()
    try:
        return repo.get_inventory_summary()
    except Exception as exc:
        _logger.error(f"Failed to get inventory summary: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database lookup failed")

@router.post('/inventory/resync')
def api_trigger_inventory_resync(
    device_id: str = Body(..., embed=True),
    _user=require_role('Operator')
):
    """Trigger immediate baseline inventory synchronization for a target device (stub)."""
    # This is a stub for Phase 3/discovery driver sync integration
    _logger.info(f"Inventory resync triggered for device: {device_id} by {_user.get('username')}")
    return {
        "success": True,
        "message": f"Inventory baseline resync scheduled/started for device: {device_id}",
        "device_id": device_id
    }

@router.get('/interfaces/{interface_id:path}/timelines/status')
def api_interface_status_timeline(
    interface_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    _user=require_role('Viewer')
):
    """Get status timeline history for an interface via Repository."""
    repo = InventoryRepository()
    try:
        return repo.get_status_timeline(interface_id, limit)
    except Exception as exc:
        _logger.error(f"Failed to get status timeline for {interface_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database lookup failed")

@router.get('/interfaces/{interface_id:path}/timelines/statistics')
def api_interface_statistics_timeline(
    interface_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    _user=require_role('Viewer')
):
    """Get bandwidth and traffic statistics timeline history for an interface via Repository."""
    repo = InventoryRepository()
    try:
        return repo.get_statistics_timeline(interface_id, limit)
    except Exception as exc:
        _logger.error(f"Failed to get statistics timeline for {interface_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database lookup failed")

@router.get('/interfaces/{interface_id:path}/timelines/optical')
def api_interface_optical_timeline(
    interface_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    _user=require_role('Viewer')
):
    """Get transceiver optical metrics timeline history for an interface via Repository."""
    repo = InventoryRepository()
    try:
        return repo.get_optical_timeline(interface_id, limit)
    except Exception as exc:
        _logger.error(f"Failed to get optical timeline for {interface_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database lookup failed")

@router.get('/interfaces/{interface_id:path}')
def api_get_interface(
    interface_id: str,
    _user=require_role('Viewer')
):
    """Get details of a single interface via Repository."""
    repo = InventoryRepository()
    try:
        interface = repo.get_interface(interface_id)
        if not interface:
            raise HTTPException(status_code=404, detail="Interface not found")
        return interface.__dict__
    except HTTPException:
        raise
    except Exception as exc:
        _logger.error(f"Failed to get interface {interface_id}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database lookup failed")
