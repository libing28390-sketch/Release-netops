"""SNMP sysName verification and safe topology hostname synchronization."""

from __future__ import annotations

import asyncio
import ipaddress
from typing import Any

from core.read_cache import invalidate_read_cache
from database import get_db_connection
from services.hostname_sync_service import (
    clean_system_hostname,
    schedule_monitoring_target_sync_if_hostname_changed,
    sync_device_hostname_metadata,
)


SYS_NAME_OID = "1.3.6.1.2.1.1.5.0"
_VALID_PROTOCOL_STATUSES = {"success", "no_neighbors"}


def _result(
    status: str,
    *,
    hostname: str = "",
    sys_name: str = "",
    changed: bool = False,
    detail: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "hostname": hostname,
        "sys_name": sys_name,
        "changed": bool(changed),
    }
    if detail:
        result["detail"] = detail
    return result


def _is_ip_literal(value: Any) -> bool:
    text = str(value or "").strip().strip('"\'')
    if not text:
        return False
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def _same_name(left: Any, right: str) -> bool:
    return bool(str(left or "").strip()) and str(left).strip() == right


def _row_value(row: Any, key: str, index: int) -> Any:
    value = row[key] if hasattr(row, "keys") else row[index]
    return "" if value is None else value


def _is_allowed_existing_name(value: Any, *, clean_name: str, management_ips: set[str]) -> bool:
    current = str(value or "").strip()
    if not current:
        return True
    if _same_name(current, clean_name):
        return True
    return current in management_ips


def _validate_snapshot_generation(device_id: str, snapshot_generation: int) -> bool:
    """Reject missing/old snapshot markers before performing the SNMP GET."""
    if not device_id or int(snapshot_generation or 0) <= 0:
        return False
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT generation, state
              FROM topology_device_lldp_snapshots
             WHERE device_id = ?
            """,
            (device_id,),
        ).fetchone()
        if row is None:
            return False
        generation = int(_row_value(row, "generation", 0) or 0)
        state = str(_row_value(row, "state", 1) or "")
        return generation == int(snapshot_generation) and state == "collecting"
    finally:
        conn.close()


def _persist_hostname(
    device_id: str,
    run_id: str,
    snapshot_generation: int,
    raw_sys_name: str,
    clean_name: str,
    device_management_ip: str,
) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        marker = conn.execute(
            """
            SELECT generation, state
              FROM topology_device_lldp_snapshots
             WHERE device_id = ?
             FOR UPDATE
            """,
            (device_id,),
        ).fetchone()
        if marker is None:
            conn.rollback()
            return _result("superseded", hostname=clean_name, sys_name=raw_sys_name)
        marker_generation = int(_row_value(marker, "generation", 0) or 0)
        marker_state = str(_row_value(marker, "state", 1) or "")
        if marker_generation != int(snapshot_generation) or marker_state != "collecting":
            conn.rollback()
            return _result("superseded", hostname=clean_name, sys_name=raw_sys_name)

        # Read the relationship before locking.  The actual lock order is
        # physical asset first, device second, matching hostname import sync.
        device_ref = conn.execute(
            "SELECT id, asset_id, hostname, ip_address FROM devices WHERE id = ?",
            (device_id,),
        ).fetchone()
        if device_ref is None:
            conn.rollback()
            return _result("unavailable", hostname=clean_name, sys_name=raw_sys_name)
        asset_id = str(_row_value(device_ref, "asset_id", 1) or "")
        asset_ref = None
        if asset_id:
            asset_ref = conn.execute(
                "SELECT id, hostname, management_ip FROM physical_assets WHERE id = ? FOR UPDATE",
                (asset_id,),
            ).fetchone()
            if asset_ref is None:
                conn.rollback()
                return _result("unavailable", hostname=clean_name, sys_name=raw_sys_name)
        locked_device = conn.execute(
            "SELECT id, asset_id, hostname, ip_address FROM devices WHERE id = ? FOR UPDATE",
            (device_id,),
        ).fetchone()
        if locked_device is None:
            conn.rollback()
            return _result("unavailable", hostname=clean_name, sys_name=raw_sys_name)
        locked_asset_id = str(_row_value(locked_device, "asset_id", 1) or "")
        if locked_asset_id != asset_id:
            conn.rollback()
            return _result("superseded", hostname=clean_name, sys_name=raw_sys_name)

        current_device_name = _row_value(locked_device, "hostname", 2)
        current_device_ip = str(_row_value(locked_device, "ip_address", 3) or "").strip()
        if device_management_ip and current_device_ip != device_management_ip:
            conn.rollback()
            return _result("superseded", hostname=clean_name, sys_name=raw_sys_name)
        asset_name = ""
        asset_ip = ""
        if asset_ref is not None:
            asset_name = _row_value(asset_ref, "hostname", 1)
            asset_ip = str(_row_value(asset_ref, "management_ip", 2) or "").strip()
        management_ips = {
            value for value in {device_management_ip, asset_ip} if value
        }
        if not _is_allowed_existing_name(
            current_device_name,
            clean_name=clean_name,
            management_ips=management_ips,
        ) or not _is_allowed_existing_name(asset_name, clean_name=clean_name, management_ips=management_ips):
            conn.rollback()
            return _result(
                "conflict",
                hostname=str(current_device_name or ""),
                sys_name=raw_sys_name,
            )

        previous_name = str(current_device_name or "").strip()
        previous_asset_name = str(asset_name or "").strip()
        sync_result = sync_device_hostname_metadata(conn, device_id, raw_sys_name)
        if sync_result is None:
            conn.rollback()
            return _result("unavailable", hostname=clean_name, sys_name=raw_sys_name)
        conn.execute(
            """
            UPDATE topology_discovery_run_devices
               SET hostname = ?
             WHERE run_id = ? AND device_id = ?
            """,
            (clean_name, run_id, device_id),
        )
        changed = previous_name != clean_name or (
            bool(asset_id) and previous_asset_name != clean_name
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if changed:
        try:
            invalidate_read_cache()
        except Exception:
            pass
        try:
            schedule_monitoring_target_sync_if_hostname_changed(sync_result)
        except Exception:
            pass
    return _result(
        "synced" if changed else "verified",
        hostname=clean_name,
        sys_name=raw_sys_name,
        changed=changed,
    )


async def refresh_topology_hostname(
    device: dict[str, Any],
    collector_credentials: dict[str, Any],
    *,
    run_id: str,
    snapshot_generation: int,
    protocol_results: dict[str, Any],
) -> dict[str, Any]:
    """Read RFC1213 sysName and safely sync the current topology identity."""
    device_id = str(device.get("id") or "").strip()
    if not device_id or not str(run_id or "").strip() or int(snapshot_generation or 0) <= 0:
        return _result("not_attempted")
    snmp_result = protocol_results.get("snmp") if isinstance(protocol_results, dict) else None
    snmp_status = str((snmp_result or {}).get("status") or "").strip().lower()
    if snmp_status not in _VALID_PROTOCOL_STATUSES:
        return _result("not_attempted", detail="SNMP LLDP snapshot is not complete")
    if not await asyncio.to_thread(_validate_snapshot_generation, device_id, int(snapshot_generation)):
        return _result("superseded", detail="SNMP LLDP snapshot generation is not current")

    snmp = collector_credentials.get("snmp") if isinstance(collector_credentials, dict) else None
    snmp = snmp if isinstance(snmp, dict) else {}
    server = str(snmp.get("server") or "").strip()
    community = str(snmp.get("community") or "").strip()
    version = str(snmp.get("version") or "").strip()
    raw_port = snmp.get("port")
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        port = 0
    if not server or not community or not version or not 1 <= port <= 65535:
        return _result("unavailable", detail="Resolved SNMP credentials are incomplete")

    try:
        from services.snmp_service import _snmp_get

        raw_value = await _snmp_get(
            server,
            community,
            SYS_NAME_OID,
            port=port,
            timeout=3,
            version=version,
        )
    except Exception:
        return _result("unavailable")
    raw_sys_name = str(raw_value or "")
    raw_sys_name_text = raw_sys_name.strip()
    if not raw_sys_name_text or _is_ip_literal(raw_sys_name_text):
        return _result("unavailable", sys_name=raw_sys_name)
    clean_name = clean_system_hostname(raw_sys_name)
    management_ip = str(device.get("ip_address") or "").strip()
    if not clean_name or _is_ip_literal(clean_name) or clean_name == management_ip:
        return _result("unavailable", sys_name=raw_sys_name)

    try:
        return await asyncio.to_thread(
            _persist_hostname,
            device_id,
            str(run_id),
            int(snapshot_generation),
            raw_sys_name,
            clean_name,
            management_ip,
        )
    except Exception:
        return _result("unavailable", hostname=clean_name, sys_name=raw_sys_name)


__all__ = ["refresh_topology_hostname"]
