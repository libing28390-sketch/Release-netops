"""Canonical SNMP hostname normalization and device/asset synchronization."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def clean_system_hostname(raw_sys_name: Any) -> str:
    """Normalize RFC1213 sysName for display and asset identity."""

    if not raw_sys_name:
        return ""
    cleaned = str(raw_sys_name).strip().split("\r")[0].split("\n")[0].strip()
    if not cleaned:
        return ""
    from services.topology_service import strip_domain_suffix

    return strip_domain_suffix(cleaned)


def sync_device_hostname_metadata(conn, device_id: str, raw_sys_name: Any) -> dict[str, str] | None:
    """Update device, linked physical asset, and topology source atomically.

    The caller owns the transaction.  This lets the SNMP discovery upsert and
    the inventory projection commit together when discovery is persisted.
    """

    clean_name = clean_system_hostname(raw_sys_name) or str(raw_sys_name or "").strip()
    if not clean_name:
        return None
    device = conn.execute(
        "SELECT id, hostname, asset_id FROM devices WHERE id = ?",
        (device_id,),
    ).fetchone()
    if not device:
        return None
    previous = str(device["hostname"] or "")
    asset_id = str(device["asset_id"] or "")
    now = datetime.now(timezone.utc).isoformat()
    # physical_assets is the inventory/source-of-truth projection.  Update it
    # first, then mirror the normalized identity to the operational device row
    # in the same transaction.
    if asset_id:
        conn.execute(
            "UPDATE physical_assets SET hostname = ?, updated_at = ? WHERE id = ?",
            (clean_name, now, asset_id),
        )
    conn.execute(
        "UPDATE devices SET hostname = ?, sys_name = ? WHERE id = ?",
        (clean_name, str(raw_sys_name or ""), device_id),
    )
    conn.execute(
        "UPDATE topology_observations SET source_hostname = ? WHERE source_device_id = ?",
        (clean_name, device_id),
    )
    return {
        "device_id": str(device_id),
        "asset_id": asset_id,
        "previous_hostname": previous,
        "hostname": clean_name,
        "raw_sys_name": str(raw_sys_name or ""),
    }


def schedule_monitoring_target_sync_if_hostname_changed(sync_result: dict[str, str] | None) -> bool:
    """Queue a debounced collector target rebuild after a committed hostname change."""

    if not sync_result:
        return False
    previous = str(sync_result.get("previous_hostname") or "").strip()
    current = str(sync_result.get("hostname") or sync_result.get("new_hostname") or "").strip()
    if not current or previous == current:
        return False

    try:
        from services.collector_sync_service import trigger_async_monitoring_sync

        trigger_async_monitoring_sync()
        return True
    except Exception as exc:
        logger.warning(
            "[HostnameSync] Failed to schedule collector target sync for device %s (%s)",
            sync_result.get("device_id") or "unknown",
            type(exc).__name__,
        )
        return False


__all__ = [
    "clean_system_hostname",
    "schedule_monitoring_target_sync_if_hostname_changed",
    "sync_device_hostname_metadata",
]
