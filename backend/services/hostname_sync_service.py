"""Canonical SNMP hostname normalization and device/asset synchronization."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


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


__all__ = ["clean_system_hostname", "sync_device_hostname_metadata"]
