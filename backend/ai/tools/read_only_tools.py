"""
READ_ONLY Tool Implementations for Agent Execution
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from database.core import get_db_connection
from ai.security.sanitizer import sanitize_data


def _freshness(value: Any) -> str:
    if not value:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - parsed).total_seconds()
        return "fresh" if age <= 300 else "stale" if age <= 3600 else "historical"
    except (TypeError, ValueError):
        return "unknown"


def tool_search_ip(ip: str, tenant_id: str = "tenant-default") -> Dict[str, Any]:
    """Search IP address in CMDB & ARP cache."""
    res = {"ip": ip, "device": None, "arp": None}
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT hostname, platform, vendor, status FROM devices WHERE ip_address = ? AND tenant_id = ?", (ip, tenant_id))
            row = cursor.fetchone()
            if row:
                res["device"] = {"hostname": row[0], "platform": row[1], "vendor": row[2], "status": row[3]}
    except Exception:
        pass
    res["evidence"] = [{"source_type": "cmdb", "source_id": "devices"}] if res["device"] else []
    res["freshness"] = "database_snapshot"
    return sanitize_data(res)


def tool_search_mac(mac: str, tenant_id: str = "tenant-default") -> Dict[str, Any]:
    """Search MAC address in ARP cache & MAC table."""
    result: Dict[str, Any] = {"mac": mac, "found": False, "vlan": None, "interface": None, "evidence": []}
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT vlan_id, interface_name FROM mac_table WHERE lower(mac_address) = lower(?) AND tenant_id = ? LIMIT 1",
                (mac, tenant_id),
            ).fetchone()
            if row:
                result.update({"found": True, "vlan": row[0], "interface": row[1], "evidence": [{"source_type": "mac_table"}]})
    except Exception:
        pass
    return sanitize_data(result)


def tool_get_device_neighbors(device_id: str, tenant_id: str = "tenant-default") -> Dict[str, Any]:
    """Get LLDP neighbors of device."""
    neighbors: list[dict[str, Any]] = []
    try:
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT l.source_device_id, l.target_device_id,
                       l.source_port, l.target_port
                FROM topology_links l
                JOIN devices sd ON sd.id = l.source_device_id
                JOIN devices td ON td.id = l.target_device_id
                WHERE (l.source_device_id = ? OR l.target_device_id = ?)
                  AND sd.tenant_id = ?
                  AND td.tenant_id = ?
                ORDER BY l.updated_at DESC LIMIT 100
                """,
                (device_id, device_id, tenant_id, tenant_id),
            ).fetchall()
            for row in rows:
                source = row[0]
                neighbors.append({"local_port": row[2], "remote_device": row[1] if source == device_id else source, "remote_port": row[3]})
    except Exception:
        pass
    return sanitize_data({"device_id": device_id, "neighbors": neighbors, "evidence": [{"source_type": "topology_links"}] if neighbors else []})


def tool_get_active_alarms(device_id: Optional[str] = None, tenant_id: str = "tenant-default") -> Dict[str, Any]:
    """Get active alarms from Nexora alarm center."""
    alarms: list[dict[str, Any]] = []
    try:
        with get_db_connection() as conn:
            if device_id:
                rows = conn.execute(
                    """
                    SELECT a.title, a.severity, a.device_id
                    FROM alert_events a JOIN devices d ON d.id = a.device_id
                    WHERE a.resolved_at IS NULL AND a.device_id = ?
                      AND d.tenant_id = ?
                    ORDER BY a.created_at DESC LIMIT 100
                    """,
                    (device_id, tenant_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT a.title, a.severity, a.device_id
                    FROM alert_events a JOIN devices d ON d.id = a.device_id
                    WHERE a.resolved_at IS NULL
                      AND d.tenant_id = ?
                    ORDER BY a.created_at DESC LIMIT 100
                    """,
                    (tenant_id,),
                ).fetchall()
            alarms = [{"title": row[0], "severity": row[1], "device": row[2]} for row in rows]
    except Exception:
        pass
    return sanitize_data({"alarms": alarms, "evidence": [{"source_type": "alert_events"}] if alarms else []})


def tool_get_config_diff(device_id: str, tenant_id: str = "tenant-default") -> Dict[str, Any]:
    """Get latest configuration diff for device from Nexora Diff Engine."""
    # The read-only tool returns a summary/diff view only.  Raw configurations
    # are intentionally not loaded into the agent context.
    return sanitize_data({"device_id": device_id, "changes": [], "evidence": [], "freshness": "not_available"})


def tool_get_asset(device_id: str, tenant_id: str = "tenant-default") -> Dict[str, Any]:
    """Return a tenant-scoped CMDB asset projection without credentials."""
    result: Dict[str, Any] = {"device_id": device_id, "asset": None, "evidence": []}
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                """
                SELECT d.id, d.hostname, d.ip_address, d.vendor, d.platform, d.status,
                       d.role, d.site, d.site_id, p.id, p.name, p.asset_tag
                FROM devices d
                LEFT JOIN physical_assets p ON p.id = d.asset_id
                WHERE d.id = ? AND d.tenant_id = ?
                """,
                (device_id, tenant_id),
            ).fetchone()
            if row:
                result["asset"] = {
                    "device_id": row[0], "hostname": row[1], "ip_address": row[2],
                    "vendor": row[3], "platform": row[4], "status": row[5],
                    "role": row[6], "site": row[7], "site_id": row[8],
                    "asset_id": row[9], "asset_name": row[10], "asset_tag": row[11],
                }
                result["evidence"] = [{"source_type": "cmdb", "source_id": str(row[0])}]
    except Exception:
        pass
    result["freshness"] = "database_snapshot"
    return sanitize_data(result)


def tool_get_device_status(device_id: str, tenant_id: str = "tenant-default") -> Dict[str, Any]:
    """Return health and collector status as a safe read-only projection."""
    result: Dict[str, Any] = {"device_id": device_id, "device": None, "collectors": [], "evidence": []}
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT id, hostname, status, last_seen, updated_at FROM devices WHERE id = ? AND tenant_id = ?",
                (device_id, tenant_id),
            ).fetchone()
            if row:
                result["device"] = {"id": row[0], "hostname": row[1], "status": row[2], "last_seen": row[3], "updated_at": row[4]}
                result["evidence"].append({"source_type": "cmdb", "source_id": str(device_id)})
            if result["device"]:
                rows = conn.execute(
                    """
                    SELECT collector, status, transport, last_attempt_at, last_success_at,
                           consecutive_failures, coverage_total, coverage_supported, error_code
                    FROM device_collection_status WHERE device_id = ? ORDER BY collector
                    """,
                    (device_id,),
                ).fetchall()
                for item in rows:
                    result["collectors"].append({
                        "collector": item[0], "status": item[1], "transport": item[2],
                        "last_attempt_at": item[3], "last_success_at": item[4],
                        "consecutive_failures": item[5], "coverage_total": item[6],
                        "coverage_supported": item[7], "error_code": item[8],
                        "freshness": _freshness(item[4]),
                    })
                    result["evidence"].append({"source_type": "collector_status", "source_id": str(item[0])})
    except Exception:
        pass
    return sanitize_data(result)


def tool_get_arp_entry(ip: str | None = None, device_id: str | None = None, tenant_id: str = "tenant-default") -> Dict[str, Any]:
    """Locate ARP evidence; never infer a physical edge from it."""
    entries: list[dict[str, Any]] = []
    try:
        with get_db_connection() as conn:
            where = ["d.tenant_id = ?"]
            params: list[Any] = [tenant_id]
            if ip:
                where.append("a.ip_address = ?")
                params.append(ip)
            if device_id:
                where.append("a.device_id = ?")
                params.append(device_id)
            rows = conn.execute(
                f"""
                SELECT a.device_id, d.hostname, a.ip_address, a.mac_address,
                       a.interface_name, a.vlan_id, a.last_updated
                FROM arp_table a JOIN devices d ON d.id = a.device_id
                WHERE {' AND '.join(where)} ORDER BY a.last_updated DESC LIMIT 100
                """,
                tuple(params),
            ).fetchall()
            entries = [{"device_id": r[0], "hostname": r[1], "ip": r[2], "mac": r[3], "interface": r[4], "vlan": r[5], "last_updated": r[6]} for r in rows]
    except Exception:
        pass
    return sanitize_data({"ip": ip, "device_id": device_id, "entries": entries, "evidence": [{"source_type": "arp", "source_id": str(item["device_id"])} for item in entries], "freshness": _freshness(entries[0].get("last_updated") if entries else None)})


def tool_get_mac_entry(mac: str, device_id: str | None = None, tenant_id: str = "tenant-default") -> Dict[str, Any]:
    """Locate MAC-table evidence; it is an endpoint hint, not a physical link."""
    entries: list[dict[str, Any]] = []
    try:
        with get_db_connection() as conn:
            where = ["lower(m.mac_address) = lower(?)", "d.tenant_id = ?"]
            params: list[Any] = [mac, tenant_id]
            if device_id:
                where.append("m.device_id = ?")
                params.append(device_id)
            rows = conn.execute(
                f"""
                SELECT m.device_id, d.hostname, m.mac_address, m.interface_name,
                       m.vlan_id, m.entry_type, m.last_updated
                FROM mac_table m JOIN devices d ON d.id = m.device_id
                WHERE {' AND '.join(where)} ORDER BY m.last_updated DESC LIMIT 100
                """,
                tuple(params),
            ).fetchall()
            entries = [{"device_id": r[0], "hostname": r[1], "mac": r[2], "interface": r[3], "vlan": r[4], "entry_type": r[5], "last_updated": r[6]} for r in rows]
    except Exception:
        pass
    return sanitize_data({"mac": mac, "entries": entries, "evidence": [{"source_type": "mac_table", "source_id": str(item["device_id"])} for item in entries], "freshness": _freshness(entries[0].get("last_updated") if entries else None)})


def tool_get_lldp_neighbors(device_id: str, tenant_id: str = "tenant-default") -> Dict[str, Any]:
    """Return LLDP/CDP physical observations only."""
    neighbors = tool_get_device_neighbors(device_id, tenant_id=tenant_id).get("neighbors", [])
    return sanitize_data({"device_id": device_id, "neighbors": neighbors, "relation_type": "PHYSICAL", "evidence": [{"source_type": "lldp", "source_id": device_id}] if neighbors else [], "freshness": "database_snapshot"})


def tool_find_ip_location(ip: str, tenant_id: str = "tenant-default") -> Dict[str, Any]:
    """Run the deterministic IP → ARP → MAC → topology lookup chain."""
    arp = tool_get_arp_entry(ip=ip, tenant_id=tenant_id)
    first = (arp.get("entries") or [None])[0]
    if not first:
        cmdb = tool_search_ip(ip, tenant_id=tenant_id)
        return sanitize_data({"ip": ip, "device": cmdb.get("device"), "confidence": 0.35 if cmdb.get("device") else 0.0, "evidence": cmdb.get("evidence") or [], "gaps": ["no_arp_evidence"]})
    mac = tool_get_mac_entry(str(first.get("mac") or ""), device_id=first.get("device_id"), tenant_id=tenant_id)
    neighbors = tool_get_lldp_neighbors(str(first.get("device_id") or ""), tenant_id=tenant_id)
    return sanitize_data({
        "ip": ip,
        "mac": first.get("mac"),
        "vlan": first.get("vlan"),
        "device": first.get("hostname"),
        "device_id": first.get("device_id"),
        "interface": first.get("interface"),
        "upstream": (neighbors.get("neighbors") or [None])[0],
        "confidence": 0.98 if mac.get("entries") else 0.85,
        "evidence": (arp.get("evidence") or []) + (mac.get("evidence") or []) + (neighbors.get("evidence") or []),
        "freshness": arp.get("freshness", "unknown"),
    })


def tool_get_running_config(device_id: str, tenant_id: str = "tenant-default") -> Dict[str, Any]:
    """Return config snapshot metadata, never the raw configuration body."""
    snapshots: list[dict[str, Any]] = []
    try:
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT s.id, s.device_id, s.timestamp, s.trigger, s.author, s.size,
                       s.raw_hash, s.normalized_hash, s.line_count, s.section_count,
                       s.integrity_status, s.config_type
                FROM config_snapshots s JOIN devices d ON d.id = s.device_id
                WHERE s.device_id = ? AND d.tenant_id = ?
                ORDER BY s.timestamp DESC LIMIT 20
                """,
                (device_id, tenant_id),
            ).fetchall()
            snapshots = [{"id": r[0], "device_id": r[1], "timestamp": r[2], "trigger": r[3], "author": r[4], "size": r[5], "raw_hash": r[6], "normalized_hash": r[7], "line_count": r[8], "section_count": r[9], "integrity_status": r[10], "config_type": r[11]} for r in rows]
    except Exception:
        pass
    return sanitize_data({"device_id": device_id, "snapshots": snapshots, "raw_available": False, "evidence": [{"source_type": "config_snapshot", "source_id": str(item["id"])} for item in snapshots], "freshness": _freshness(snapshots[0].get("timestamp") if snapshots else None)})


def tool_compare_config(device_id: str, before_snapshot_id: str | None = None, after_snapshot_id: str | None = None, tenant_id: str = "tenant-default") -> Dict[str, Any]:
    """Return a safe diff summary using hashes/line counts, not raw config text."""
    current = tool_get_running_config(device_id, tenant_id=tenant_id)
    snapshots = current.get("snapshots") or []
    if before_snapshot_id or after_snapshot_id:
        snapshots = [item for item in snapshots if item.get("id") in {before_snapshot_id, after_snapshot_id}]
    if len(snapshots) < 2:
        return sanitize_data({"device_id": device_id, "changes": [], "comparable": False, "raw_available": False, "evidence": current.get("evidence") or []})
    before, after = snapshots[-1], snapshots[0]
    return sanitize_data({
        "device_id": device_id,
        "comparable": True,
        "changed": before.get("normalized_hash") != after.get("normalized_hash"),
        "before": {"id": before.get("id"), "timestamp": before.get("timestamp"), "line_count": before.get("line_count")},
        "after": {"id": after.get("id"), "timestamp": after.get("timestamp"), "line_count": after.get("line_count")},
        "raw_available": False,
        "evidence": current.get("evidence") or [],
    })
