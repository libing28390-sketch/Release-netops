"""IPAM-owned, read-only projections of ARP/MAC source evidence.

This module never performs device I/O and never writes shared collector tables.
The only writes are to the IPAM discovery evidence tables and explicit IPAM
registration/calibration actions.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from core.tenant_policy import DEFAULT_TENANT_ID, TENANT_ISOLATION_ENABLED
from database import get_db_connection
from services.ipam_network_scope import is_business_utilization_network

logger = logging.getLogger(__name__)
_NAMESPACE = uuid.UUID("6b50f4d4-51f7-5a11-a49a-2779d3d96030")
_PROJECTION_LOCK_KEY = (806301, 1)
_VIRTUAL_GATEWAY_MAC_PREFIXES = (
    "00005e0001",  # VRRP IPv4
    "00005e0002",  # VRRP IPv6
    "00000c07ac",  # HSRP v1
    "00000c9f",    # HSRP v2
    "0007b4",      # GLBP
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _parse_time(value: Any) -> tuple[datetime | None, str]:
    text = str(value or "").strip()
    if not text:
        return None, "missing"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None, "invalid"
    if parsed.tzinfo is None:
        # Legacy collector timestamps are emitted in Asia/Shanghai without an
        # explicit offset. Preserve that source convention; never use now().
        from datetime import timedelta as _timedelta
        parsed = parsed.replace(tzinfo=timezone(_timedelta(hours=8)))
    parsed = parsed.astimezone(timezone.utc)
    if parsed > _utc_now():
        return parsed, "future"
    return parsed, "valid"


def _normalized_ip(value: Any) -> str:
    try:
        return str(ipaddress.ip_address(str(value or "").strip()))
    except (TypeError, ValueError):
        return ""


def _normalized_mac(value: Any) -> str:
    text = str(value or "").strip().lower()
    compact = text.replace(":", "").replace("-", "").replace(".", "")
    if len(compact) != 12 or any(char not in "0123456789abcdef" for char in compact):
        return ""
    return ":".join(compact[index:index + 2] for index in range(0, 12, 2))


def _is_virtual_gateway_mac(value: Any) -> bool:
    normalized = _normalized_mac(value)
    compact = normalized.replace(":", "")
    return any(compact.startswith(prefix) for prefix in _VIRTUAL_GATEWAY_MAC_PREFIXES)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _stable_id(namespace: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, namespace))


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _retention_days() -> int:
    try:
        return min(max(int(os.getenv("IPAM_DISCOVERY_RETENTION_DAYS", "90")), 1), 3650)
    except ValueError:
        return 90


def _recent_minutes() -> int:
    try:
        configured = os.getenv("IPAM_DISCOVERY_RECENT_MINUTES")
        if configured is not None and configured.strip():
            return min(max(int(configured), 1), 1440)
    except ValueError:
        pass
    try:
        arp_interval_seconds = max(300, int(os.getenv("ARP_SWEEP_INTERVAL_SECONDS", "3600")))
    except ValueError:
        arp_interval_seconds = 3600
    # Two collection intervals plus two minutes of scheduler/device jitter.
    return min(max((arp_interval_seconds * 2 + 120 + 59) // 60, 1), 1440)


def _mac_recent_minutes() -> int:
    try:
        configured = os.getenv("IPAM_DISCOVERY_MAC_RECENT_MINUTES")
        if configured is not None and configured.strip():
            return min(max(int(configured), 1), 10080)
    except ValueError:
        pass
    try:
        endpoint_interval_seconds = max(300, int(os.getenv("ENDPOINT_FACT_INTERVAL_SECONDS", "3600")))
    except ValueError:
        endpoint_interval_seconds = 3600
    # Match the paired ARP/FDB schedule: tolerate one missed cycle plus jitter.
    return min(max((endpoint_interval_seconds * 2 + 120 + 59) // 60, 1), 10080)


def _stale_days() -> int:
    try:
        return min(max(int(os.getenv("IPAM_DISCOVERY_STALE_DAYS", "7")), 1), 365)
    except ValueError:
        return 7


def _required_misses() -> int:
    try:
        return min(max(int(os.getenv("IPAM_DISCOVERY_REQUIRED_SNAPSHOTS", "3")), 1), 20)
    except ValueError:
        return 3


def _catalog_scope(conn) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    sites = {
        str(row["id"]): dict(row)
        for row in conn.execute("SELECT id, site_code, site_name, tenant_id FROM sites").fetchall()
    }
    vrfs = {
        str(row["id"]): dict(row)
        for row in conn.execute("SELECT id, vrf_name, tenant_id FROM vrfs").fetchall()
    }
    return sites, vrfs


def _resolve_device_scope(
    device: dict[str, Any],
    sites: dict[str, dict[str, Any]],
    vrfs: dict[str, dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_site_id = str(device.get("site_id") or "").strip()
    raw_asset_site_id = str(device.get("asset_site_id") or "").strip()
    raw_site = str(device.get("site") or "").strip()
    asset_site_id = raw_asset_site_id if raw_asset_site_id in sites else ""
    device_site_id = raw_site_id if raw_site_id in sites else ""
    # Canonical CMDB identity follows the linked physical asset first. If the
    # device row disagrees, retain the asset site as the projection but mark
    # the evidence conflicted so it cannot be registered or reconciled.
    site_id = asset_site_id or device_site_id
    site_ambiguous = False
    if not site_id and raw_site:
        matches = [
            key for key, site in sites.items()
            if raw_site in (str(site.get("site_code") or ""), str(site.get("site_name") or ""))
        ]
        if len(matches) == 1:
            site_id = matches[0]
        elif len(matches) > 1:
            site_ambiguous = True
    alias_site_id = ""
    if raw_site:
        alias_matches = [
            key for key, site in sites.items()
            if raw_site == key or raw_site in (str(site.get("site_code") or ""), str(site.get("site_name") or ""))
        ]
        if len(alias_matches) == 1:
            alias_site_id = alias_matches[0]
        elif len(alias_matches) > 1:
            site_ambiguous = True

    device_tenant = str(device.get("tenant_id") or "").strip()
    site_tenant = str(sites.get(site_id, {}).get("tenant_id") or "").strip() if site_id else ""
    tenant_conflict = bool(device_tenant and site_tenant and device_tenant != site_tenant)
    canonical_device_site = device_site_id or alias_site_id
    asset_device_site_conflict = bool(asset_site_id and canonical_device_site and asset_site_id != canonical_device_site)
    if TENANT_ISOLATION_ENABLED:
        tenant_id = device_tenant or site_tenant
    else:
        tenant_id = device_tenant or site_tenant or DEFAULT_TENANT_ID

    context_value: Any = (metadata or {}).get("vrf_context")
    context_record: dict[str, Any] = {}
    if context_value is None:
        context_value = (metadata or {}).get("source_context")
    if isinstance(context_value, dict):
        context_record = context_value
        context_value = context_value.get("vrf_context") or context_value.get("address_space")
    context = str(context_value or "").strip().lower().replace("-", "_")
    raw_vrf_id_value = (metadata or {}).get("vrf_id") or context_record.get("vrf_id")
    raw_vrf_id = str(raw_vrf_id_value or "").strip()
    vrf_id = raw_vrf_id if raw_vrf_id in vrfs else ""
    if raw_vrf_id and not vrf_id:
        vrf_context_status = "invalid_vrf"
    elif vrf_id:
        vrf_context_status = "explicit_vrf"
    elif context in {"global", "global_table", "default"}:
        vrf_context_status = "explicit_global"
    else:
        vrf_context_status = "unknown"
    vrf = vrfs.get(vrf_id) or {}
    vrf_tenant = str(vrf.get("tenant_id") or "").strip()
    vrf_conflict = bool(vrf_id and vrf_tenant and tenant_id and vrf_tenant != tenant_id)
    # An empty VRF is deliberately not interpreted as the default VRF. ARP
    # metadata currently carries no VRF context.
    resolved = bool(
        tenant_id and site_id
        and vrf_context_status in {"explicit_vrf", "explicit_global"}
        and not site_ambiguous and not tenant_conflict and not vrf_conflict and not asset_device_site_conflict
    )
    return {
        "tenant_id": tenant_id or None,
        "site_id": site_id or None,
        "vrf_id": vrf_id if vrf_context_status == "explicit_global" else vrf_id or None,
        "vrf_context_status": vrf_context_status,
        "scope_status": "conflict" if tenant_conflict or vrf_conflict or site_ambiguous or asset_device_site_conflict else "resolved" if resolved else "scope_pending",
        "site_ambiguous": site_ambiguous,
    }


def _device_catalog(conn) -> tuple[
    dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]
]:
    sites, vrfs = _catalog_scope(conn)
    devices = {
        str(row["id"]): dict(row)
        for row in conn.execute(
            """SELECT d.id, d.hostname, d.tenant_id, d.site_id, d.site, d.asset_id,
                      pa.site_id AS asset_site_id
                 FROM devices d
                 LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                ORDER BY d.id"""
        ).fetchall()
    }
    resolved = {
        device_id: {
            **device,
            **_resolve_device_scope(device, sites, vrfs),
            "device_name": str(device.get("hostname") or device_id),
        }
        for device_id, device in devices.items()
    }
    return resolved, sites, vrfs


def _timestamp_window(rows: list[dict[str, Any]]) -> tuple[list[str], list[datetime], bool]:
    statuses: list[str] = []
    valid_times: list[datetime] = []
    for row in rows:
        parsed, status = _parse_time(row.get("last_updated"))
        statuses.append(status)
        if parsed and status == "valid":
            valid_times.append(parsed)
    trusted = bool(rows) and len(valid_times) == len(rows)
    return statuses, valid_times, trusted


def _arp_coverage_proof(
    *,
    status: dict[str, Any] | None,
    sweep: dict[str, Any] | None,
    rows: list[dict[str, Any]],
    now: datetime,
) -> tuple[bool, str, str]:
    status = status or {}
    sweep = sweep or {}
    metadata = _json_object(status.get("metadata_json"))
    run_id = str(metadata.get("collection_run_id") or "").strip()
    if str(status.get("status") or "") != "success" or str(status.get("source") or "") != "arp_sweep":
        return False, "unavailable", "collector_not_successful"
    if int(status.get("coverage_supported") or 0) < 1:
        return False, "unavailable", "collector_did_not_confirm_coverage"
    if not run_id or run_id != str(sweep.get("last_run_id") or ""):
        return False, "unavailable", "collection_run_not_correlated"

    attempted, attempted_state = _parse_time(status.get("last_attempt_at"))
    succeeded, succeeded_state = _parse_time(status.get("last_success_at"))
    completed, completed_state = _parse_time(sweep.get("last_completed_at"))
    if any(state != "valid" for state in (attempted_state, succeeded_state, completed_state)):
        return False, "unavailable", "collection_timestamps_untrusted"
    if not attempted or not succeeded or not completed or succeeded != attempted or completed < attempted:
        return False, "unavailable", "collection_run_not_completed"

    try:
        expected_count = int(metadata.get("entry_count"))
        coverage_total = int(status.get("coverage_total") or 0)
    except (TypeError, ValueError):
        return False, "unavailable", "collector_count_missing"
    if expected_count < 0 or expected_count != coverage_total or expected_count != len(rows):
        return False, "unavailable", "entry_count_mismatch"

    timestamp_states, valid_times, trusted_timestamps = _timestamp_window(rows)
    if rows and not trusted_timestamps:
        return False, "unavailable", "source_timestamp_untrusted"
    if valid_times and (min(valid_times) < attempted or max(valid_times) > completed):
        return False, "unavailable", "source_time_outside_completed_run"
    if not rows and expected_count != 0:
        return False, "unavailable", "empty_source_count_mismatch"
    return True, "complete", ""


def _observation_identity(
    *, source_type: str, device_id: str, scope: dict[str, Any], ip: str, mac: str,
    interface_name: str, vlan: str,
) -> str:
    return _digest([
        source_type, device_id, scope.get("tenant_id"), scope.get("site_id"), scope.get("vrf_id"),
        scope.get("vrf_context_status"), scope.get("scope_status"), ip, mac, interface_name, vlan,
    ])


def _insert_snapshot(
    conn,
    *, collector: str, device_id: str, source_device_name: str, scope: dict[str, Any], source_run_id: str,
    source_version: str, source_status: str, coverage_status: str, coverage_complete: bool,
    coverage_reason: str, entry_count: int, observed_at: str | None, projected_at: str,
) -> str:
    snapshot_id = _stable_id(f"ipam-discovery-snapshot:{collector}:{device_id}:{source_version}")
    conn.execute(
        """INSERT INTO ipam_discovery_snapshots (
               id, collector, device_id, source_device_name, tenant_id, site_id, vrf_id,
               vrf_context_status, scope_status,
               source_run_id, source_version, source_status, coverage_status,
               coverage_complete, coverage_reason, entry_count, observed_at, projected_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (collector, device_id, source_version) DO NOTHING""",
        (
            snapshot_id, collector, device_id, source_device_name, scope.get("tenant_id"), scope.get("site_id"),
            scope.get("vrf_id"), scope.get("vrf_context_status") or "unknown",
            scope.get("scope_status") or "scope_pending", source_run_id,
            source_version, source_status, coverage_status, 1 if coverage_complete else 0,
            coverage_reason, max(0, int(entry_count)), observed_at, projected_at,
        ),
    )
    existing = conn.execute(
        "SELECT id FROM ipam_discovery_snapshots WHERE collector = ? AND device_id = ? AND source_version = ?",
        (collector, device_id, source_version),
    ).fetchone()
    return str(existing["id"] if existing else snapshot_id)


def _insert_observation(
    conn,
    *, snapshot_id: str, source_type: str, device_id: str, source_device_name: str, scope: dict[str, Any], ip: str | None,
    mac: str | None, interface_name: str, vlan: str, raw_timestamp: Any, projected_at: str,
) -> int:
    parsed, timestamp_status = _parse_time(raw_timestamp)
    observed_at = _iso(parsed) if parsed and timestamp_status == "valid" else None
    identity = _observation_identity(
        source_type=source_type, device_id=device_id, scope=scope,
        ip=ip or "", mac=mac or "", interface_name=interface_name, vlan=vlan,
    )
    observation_id = _stable_id(f"ipam-discovery-observation:{snapshot_id}:{identity}")
    cursor = conn.execute(
        """INSERT INTO ipam_discovery_observations (
               id, snapshot_id, source_type, source_device_id, source_device_name,
               tenant_id, site_id, vrf_id, vrf_context_status,
               scope_status, ip, mac, interface_name, vlan, source_identity_key,
               source_observed_at, timestamp_status, projected_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (snapshot_id, source_identity_key) DO NOTHING""",
        (
            observation_id, snapshot_id, source_type, device_id, source_device_name, scope.get("tenant_id"),
            scope.get("site_id"), scope.get("vrf_id"), scope.get("vrf_context_status") or "unknown",
            scope.get("scope_status") or "scope_pending",
            ip, mac, interface_name, vlan, identity, observed_at, timestamp_status, projected_at,
        ),
    )
    return max(0, int(getattr(cursor, "rowcount", 0) or 0))


def run_ipam_discovery_projection() -> dict[str, Any]:
    """Project current ARP/MAC source versions without performing device I/O."""
    now = _utc_now()
    projected_at = _iso(now) or now.isoformat()
    retention_cutoff = _iso(now - timedelta(days=_retention_days()))
    conn = get_db_connection()
    result = {
        "snapshots_created": 0,
        "observations_created": 0,
        "complete_arp_snapshots": 0,
        "unavailable_arp_snapshots": 0,
        "mac_positive_snapshots": 0,
        "retention_days": _retention_days(),
    }
    try:
        # All shared source reads below must use one MVCC view. Projection is
        # not allowed to observe status from one collector generation and rows
        # from another transactionally replaced source snapshot.
        conn.execute("SELECT pg_advisory_lock(?, ?)", _PROJECTION_LOCK_KEY)
        conn.commit()
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        devices, sites, vrfs = _device_catalog(conn)
        sweep_row = conn.execute(
            "SELECT * FROM collector_sweep_state WHERE collector = ?", ("arp",)
        ).fetchone()
        sweep = dict(sweep_row) if sweep_row else {}
        status_rows = conn.execute(
            "SELECT * FROM device_collection_status WHERE collector = ? ORDER BY device_id", ("arp",)
        ).fetchall()
        arp_rows = conn.execute(
            """SELECT id, device_id, ip_address, mac_address, interface_name, vlan_id, last_updated
                 FROM arp_table
                ORDER BY device_id, ip_address, id"""
        ).fetchall()
        mac_rows = conn.execute(
            """SELECT id, device_id, mac_address, interface_name, vlan_id, entry_type, last_updated
                 FROM mac_table
                ORDER BY device_id, mac_address, interface_name, id"""
        ).fetchall()

        statuses = {str(row["device_id"]): dict(row) for row in status_rows}
        arps_by_device: dict[str, list[dict[str, Any]]] = {}
        for row in arp_rows:
            item = dict(row)
            arps_by_device.setdefault(str(item.get("device_id") or ""), []).append(item)
        macs_by_device: dict[str, list[dict[str, Any]]] = {}
        for row in mac_rows:
            item = dict(row)
            macs_by_device.setdefault(str(item.get("device_id") or ""), []).append(item)

        for device_id in sorted(set(arps_by_device) | set(statuses)):
            status = statuses.get(device_id)
            rows = arps_by_device.get(device_id, [])
            metadata = _json_object(status.get("metadata_json")) if status else {}
            complete, coverage_status, coverage_reason = _arp_coverage_proof(
                status=status, sweep=sweep, rows=rows, now=now,
            )
            parsed_times = [_parse_time(row.get("last_updated")) for row in rows]
            valid_times = [parsed for parsed, state in parsed_times if parsed and state == "valid"]
            observed_at = _iso(max(valid_times)) if valid_times and len(valid_times) == len(rows) else None
            if not rows and complete and status:
                observed_at = _iso(_parse_time(status.get("last_success_at"))[0])

            run_id = str(metadata.get("collection_run_id") or "").strip()
            device = devices.get(device_id, {"id": device_id})
            scope = _resolve_device_scope(device, sites, vrfs, metadata if complete else {})
            scope_signature = _digest([
                scope, device.get("device_name"), device.get("asset_id"),
                device.get("site_id"), device.get("site"), device.get("asset_site_id"),
            ])
            source_rows_signature = _digest([
                [row.get("ip_address"), _normalized_mac(row.get("mac_address")), row.get("interface_name"),
                 str(row.get("vlan_id") or ""), row.get("last_updated")]
                for row in rows
            ])
            source_version = (
                f"run:{run_id}:scope:{scope_signature}"
                if complete and run_id
                else f"raw:{_digest([source_rows_signature, scope_signature])}"
            )
            # No-data failed devices do not create synthetic snapshots. A
            # proven successful empty result is retained to support absence.
            if not rows and not complete:
                continue
            created = conn.execute(
                "SELECT 1 FROM ipam_discovery_snapshots WHERE collector = ? AND device_id = ? AND source_version = ?",
                ("arp", device_id, source_version),
            ).fetchone() is None
            snapshot_id = _insert_snapshot(
                conn, collector="arp", device_id=device_id,
                source_device_name=str(device.get("device_name") or device_id), scope=scope,
                source_run_id=run_id, source_version=source_version,
                source_status=str(status.get("status") if status else "unknown"),
                coverage_status=coverage_status, coverage_complete=complete,
                coverage_reason=coverage_reason, entry_count=len(rows), observed_at=observed_at,
                projected_at=projected_at,
            )
            if created:
                result["snapshots_created"] += 1
            if complete:
                result["complete_arp_snapshots"] += int(created)
            else:
                result["unavailable_arp_snapshots"] += int(created)
            for row in rows:
                ip = _normalized_ip(row.get("ip_address"))
                mac = _normalized_mac(row.get("mac_address"))
                if not ip and not mac:
                    continue
                result["observations_created"] += _insert_observation(
                    conn, snapshot_id=snapshot_id, source_type="arp", device_id=device_id,
                    source_device_name=str(device.get("device_name") or device_id),
                    scope=scope, ip=ip or None, mac=mac or None,
                    interface_name=str(row.get("interface_name") or "").strip(),
                    vlan=str(row.get("vlan_id") or "").strip(), raw_timestamp=row.get("last_updated"),
                    projected_at=projected_at,
                )

        for device_id, rows in sorted(macs_by_device.items()):
            if not rows:
                continue
            normalized_rows = []
            for row in rows:
                mac = _normalized_mac(row.get("mac_address"))
                if not mac:
                    continue
                normalized_rows.append({
                    "mac": mac,
                    "interface_name": str(row.get("interface_name") or "").strip(),
                    "vlan": str(row.get("vlan_id") or "").strip(),
                    "entry_type": str(row.get("entry_type") or "").strip(),
                    "last_updated": str(row.get("last_updated") or ""),
                })
            if not normalized_rows:
                continue
            device = devices.get(device_id, {"id": device_id})
            scope = _resolve_device_scope(device, sites, vrfs, {})
            scope_signature = _digest([
                scope, device.get("device_name"), device.get("asset_id"),
                device.get("site_id"), device.get("site"), device.get("asset_site_id"),
            ])
            source_version = f"raw:{_digest([normalized_rows, scope_signature])}"
            created = conn.execute(
                "SELECT 1 FROM ipam_discovery_snapshots WHERE collector = ? AND device_id = ? AND source_version = ?",
                ("mac", device_id, source_version),
            ).fetchone() is None
            parsed_times = [_parse_time(row.get("last_updated")) for row in normalized_rows]
            valid_times = [parsed for parsed, state in parsed_times if parsed and state == "valid"]
            observed_at = _iso(max(valid_times)) if valid_times and len(valid_times) == len(normalized_rows) else None
            snapshot_id = _insert_snapshot(
                conn, collector="mac", device_id=device_id,
                source_device_name=str(device.get("device_name") or device_id), scope=scope,
                source_run_id="", source_version=source_version, source_status="observed",
                coverage_status="unavailable", coverage_complete=False,
                coverage_reason="mac_collector_generation_not_recorded",
                entry_count=len(normalized_rows), observed_at=observed_at, projected_at=projected_at,
            )
            if created:
                result["snapshots_created"] += 1
                result["mac_positive_snapshots"] += 1
            for row in normalized_rows:
                result["observations_created"] += _insert_observation(
                    conn, snapshot_id=snapshot_id, source_type="mac", device_id=device_id,
                    source_device_name=str(device.get("device_name") or device_id),
                    scope=scope, ip=None, mac=row["mac"], interface_name=row["interface_name"],
                    vlan=row["vlan"], raw_timestamp=row["last_updated"], projected_at=projected_at,
                )

        conn.execute(
            """DELETE FROM ipam_discovery_snapshots old
                 WHERE old.projected_at < ?
                   AND EXISTS (
                       SELECT 1 FROM ipam_discovery_snapshots newer
                        WHERE newer.collector = old.collector
                          AND newer.device_id = old.device_id
                          AND (newer.projected_at, newer.id) > (old.projected_at, old.id)
                   )""",
            (retention_cutoff,),
        )
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        logger.exception("IPAM discovery projection failed")
        raise
    finally:
        try:
            conn.execute("SELECT pg_advisory_unlock(?, ?)", _PROJECTION_LOCK_KEY)
            conn.commit()
        except Exception:
            pass
        conn.close()


def _load_projected_observations(
    conn, *, observation_id: str | None = None, ip: str | None = None,
    mac: str | None = None, history: bool = False,
) -> list[dict[str, Any]]:
    identity_filter = ""
    params: list[Any] = []
    if observation_id:
        row = conn.execute(
            "SELECT source_identity_key FROM ipam_discovery_observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
        if not row:
            return []
        identity_filter = "AND o.source_identity_key = ?"
        params.append(str(row["source_identity_key"]))
    if ip is not None:
        identity_filter += " AND o.ip = ?"
        params.append(_normalized_ip(ip))
    if mac is not None:
        identity_filter += " AND o.mac = ?"
        params.append(_normalized_mac(mac))
    rank_filter = "" if history or observation_id else "WHERE ranked.row_num = 1"
    rows = conn.execute(
        f"""WITH ranked AS (
                SELECT o.*, s.collector, s.source_run_id, s.source_version,
                       s.source_status, s.coverage_status, s.coverage_complete,
                       s.coverage_reason, s.observed_at AS snapshot_observed_at,
                       s.projected_at AS snapshot_projected_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY o.source_identity_key
                           ORDER BY o.projected_at DESC, s.projected_at DESC, o.id DESC
                       ) AS row_num
                  FROM ipam_discovery_observations o
                  JOIN ipam_discovery_snapshots s ON s.id = o.snapshot_id
                 WHERE 1=1 {identity_filter}
            )
            SELECT ranked.*,
                   a.id AS assertion_id, a.subnet_id AS asserted_subnet_id,
                   a.tenant_id AS asserted_tenant_id, a.site_id AS asserted_site_id,
                   a.vrf_id AS asserted_vrf_id, a.subnet_prefix AS asserted_subnet_prefix,
                   a.current_subnet_id, a.current_subnet_tenant_id,
                   a.current_subnet_site_id, a.current_subnet_vrf_id,
                   a.current_subnet_prefix, a.current_subnet_status,
                   a.current_subnet_is_active,
                   a.asserted_by, a.asserted_at
              FROM ranked
              LEFT JOIN LATERAL (
                    SELECT candidate.*, current_prefix.id AS current_subnet_id,
                           current_prefix.tenant_id AS current_subnet_tenant_id,
                           current_prefix.site_id AS current_subnet_site_id,
                           current_prefix.vrf_id AS current_subnet_vrf_id,
                           current_prefix.prefix AS current_subnet_prefix,
                           current_prefix.status AS current_subnet_status,
                           current_prefix.is_active AS current_subnet_is_active
                      FROM ipam_discovery_scope_assertions candidate
                      LEFT JOIN prefixes current_prefix ON current_prefix.id = candidate.subnet_id
                     WHERE candidate.source_identity_key = ranked.source_identity_key
                     ORDER BY candidate.asserted_at DESC, candidate.id DESC
                     LIMIT 1
              ) a ON TRUE
             {rank_filter}
             ORDER BY COALESCE(ranked.source_observed_at, ranked.projected_at) DESC,
                      ranked.id DESC""",
        tuple(params),
    ).fetchall()
    return [dict(row) for row in rows]


def _ipam_address_index(conn) -> tuple[dict[tuple[str, str, str, str], list[dict[str, Any]]], list[dict[str, Any]]]:
    rows = conn.execute(
        """SELECT ip.id, ip.address, ip.hostname, ip.mac_address, ip.subnet_id, ip.status,
                  ip.device_id, ip.interface_name, ip.tenant_id AS ip_tenant_id,
                  ip.vrf_id AS ip_vrf_id, ip.site_id AS ip_site_id,
                  ip.address_space_id AS ip_address_space_id, ip.source_ref,
                  ip.created_at, ip.purpose, ip.device_type, ip.interface_id,
                  p.prefix, p.name AS prefix_name, p.tenant_id AS prefix_tenant_id,
                  p.vrf_id AS prefix_vrf_id, p.site_id AS prefix_site_id,
                  p.address_space_id AS prefix_address_space_id,
                  p.status AS prefix_status, p.is_active AS prefix_is_active,
                  p.gateway_device_id AS prefix_gateway_device_id,
                  p.network_type, i.interface_type AS interface_type,
                  i.interface_role AS linked_interface_role
             FROM ip_addresses ip
             LEFT JOIN prefixes p ON p.id = ip.subnet_id
             LEFT JOIN interfaces i ON i.id = ip.interface_id
            ORDER BY ip.id"""
    ).fetchall()
    by_scope: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    records: list[dict[str, Any]] = []
    for raw in rows:
        item = dict(raw)
        address = _normalized_ip(item.get("address"))
        if not address:
            continue
        has_prefix = bool(item.get("prefix"))
        ip_tenant = str(item.get("ip_tenant_id") or "")
        prefix_tenant = str(item.get("prefix_tenant_id") or "")
        ip_site = str(item.get("ip_site_id") or "")
        prefix_site = str(item.get("prefix_site_id") or "")
        ip_vrf = str(item.get("ip_vrf_id") or "")
        prefix_vrf = str(item.get("prefix_vrf_id") or "")
        ip_address_space = str(item.get("ip_address_space_id") or "")
        prefix_address_space = str(item.get("prefix_address_space_id") or "")
        scope_conflicts = []
        if has_prefix:
            if ip_tenant and prefix_tenant and ip_tenant != prefix_tenant:
                scope_conflicts.append("tenant_mismatch")
            if ip_site and ip_site != prefix_site:
                scope_conflicts.append("site_mismatch")
            # The parent prefix owns an explicit empty/global VRF too. A
            # stale address-level VRF must not silently override it.
            if ip_vrf and ip_vrf != prefix_vrf:
                scope_conflicts.append("vrf_mismatch")
            if ip_address_space and prefix_address_space and ip_address_space != prefix_address_space:
                scope_conflicts.append("address_space_mismatch")
            tenant_id, site_id, vrf_id = prefix_tenant or DEFAULT_TENANT_ID, prefix_site, prefix_vrf
            address_space_id = prefix_address_space or ip_address_space
        else:
            scope_conflicts.append("parent_prefix_missing")
            tenant_id, site_id, vrf_id = ip_tenant or DEFAULT_TENANT_ID, ip_site, ip_vrf
            address_space_id = ip_address_space
        item.update({
            "_address": address, "_tenant_id": tenant_id, "_site_id": site_id,
            "_vrf_id": vrf_id, "_scope_conflict": bool(scope_conflicts),
            "_scope_conflict_reason": ",".join(scope_conflicts),
            "_address_space_id": address_space_id,
            "_expected_source_device_id": str(item.get("prefix_gateway_device_id") or ""),
        })
        by_scope.setdefault((tenant_id, site_id, vrf_id, address), []).append(item)
        records.append(item)
    return by_scope, records


def _effective_scope(row: dict[str, Any]) -> dict[str, Any]:
    assertion_present = bool(row.get("assertion_id"))
    assertion_valid = False
    assertion_reason = ""
    if assertion_present:
        try:
            current_network = ipaddress.ip_network(str(row.get("current_subnet_prefix") or ""), strict=False)
            asserted_network = ipaddress.ip_network(str(row.get("asserted_subnet_prefix") or ""), strict=False)
            observation_ip = ipaddress.ip_address(str(row.get("ip") or ""))
            assertion_valid = bool(
                row.get("current_subnet_id")
                and str(row.get("asserted_tenant_id") or "") == str(row.get("current_subnet_tenant_id") or "")
                and str(row.get("asserted_site_id") or "") == str(row.get("current_subnet_site_id") or "")
                and str(row.get("asserted_vrf_id") or "") == str(row.get("current_subnet_vrf_id") or "")
                and current_network == asserted_network
                and observation_ip.version == current_network.version
                and observation_ip in current_network
                and str(row.get("current_subnet_status") or "active") not in {"stale", "disabled"}
                and row.get("current_subnet_is_active") not in (False, 0)
            )
        except (TypeError, ValueError):
            assertion_valid = False
        if not assertion_valid:
            assertion_reason = "asserted_subnet_scope_or_prefix_changed"

    asserted = assertion_present and assertion_valid
    tenant_id = row.get("asserted_tenant_id") if asserted else row.get("tenant_id")
    site_id = row.get("asserted_site_id") if asserted else row.get("site_id")
    vrf_id = row.get("asserted_vrf_id") if asserted else row.get("vrf_id")
    raw_status = str(row.get("scope_status") or "scope_pending")
    status = "resolved" if asserted else "scope_pending" if assertion_present else raw_status
    return {
        "tenant_id": str(tenant_id or "") or None,
        "site_id": str(site_id or "") or None,
        "vrf_id": str(vrf_id or ""),
        "scope_status": status,
        "scope_resolution": "manual_assertion" if asserted else "source",
        "vrf_context_status": ("explicit_vrf" if vrf_id else "explicit_global") if asserted else str(row.get("vrf_context_status") or "unknown"),
        "scope_assertion_status": "valid" if asserted else "invalid" if assertion_present else "none",
        "scope_assertion_reason": assertion_reason,
        "subnet_id": row.get("asserted_subnet_id") if asserted else None,
        "subnet_prefix": row.get("asserted_subnet_prefix") if asserted else None,
    }


def _evidence_status(row: dict[str, Any], now: datetime) -> tuple[str, str, datetime | None]:
    timestamp_status = str(row.get("timestamp_status") or "unknown")
    observed_at, parsed_status = _parse_time(row.get("source_observed_at"))
    if timestamp_status != "valid" or parsed_status != "valid" or observed_at is None:
        return "unknown", timestamp_status if timestamp_status != "valid" else parsed_status, None
    if str(row.get("scope_status") or "") == "conflict":
        return "conflict", "valid", observed_at
    recent_minutes = _mac_recent_minutes() if str(row.get("source_type") or "") == "mac" else _recent_minutes()
    if now - observed_at <= timedelta(minutes=recent_minutes):
        return "recent", "valid", observed_at
    return "historical", "valid", observed_at


def _decorate_observations(
    rows: list[dict[str, Any]], conn, now: datetime,
    ipam_by_scope_override: dict[tuple[str, str, str, str], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    sites, vrfs = _catalog_scope(conn)
    if ipam_by_scope_override is None:
        ipam_by_scope, _ipam_records = _ipam_address_index(conn)
    else:
        ipam_by_scope = ipam_by_scope_override
    mac_rows = [row for row in rows if row.get("source_type") == "mac"]
    access_port_cache: dict[tuple[str, str], str] = {}
    vlan_vrf_cache: dict[tuple[str, str, str], tuple[str, str] | None] = {}
    local_mac_ports: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    access_vlan_cache: dict[tuple[str, str, str], set[str]] = {}
    port_generation_cache: dict[str, dict[str, Any]] = {}

    def matches_access_vlan(row: dict[str, Any], vlan: str) -> bool:
        from services.ip_locator_service import normalize_interface_name
        device_id = str(row.get('source_device_id') or '')
        name = normalize_interface_name(str(row.get('interface_name') or '')).lower()
        key = (device_id, name, str(row.get('source_observed_at') or ''))
        if key not in access_vlan_cache:
            if device_id not in port_generation_cache:
                generation = conn.execute(
                    "SELECT status, transport, last_success_at, metadata_json FROM device_collection_status WHERE device_id = ? AND collector = 'endpoint_port_attributes'",
                    (device_id,),
                ).fetchone()
                port_generation_cache[device_id] = dict(generation) if generation else {}
            generation = port_generation_cache[device_id]
            generation_ports = _json_object(generation.get('metadata_json')).get('interfaces') or []
            # A missing-PVID bridge port must not reuse a prior round's mode.
            if (generation.get('status') != 'success' or generation.get('transport') != 'snmp'
                    or name not in {normalize_interface_name(str(item)).lower() for item in generation_ports}):
                access_vlan_cache[key] = set()
                return False
            interface_rows = conn.execute(
                'SELECT interface_name, access_vlan, last_seen FROM interfaces WHERE device_id = ?', (device_id,),
            ).fetchall()
            access_vlan_cache[key] = set()
            mac_time, mac_time_status = _parse_time(row.get('source_observed_at'))
            generation_time, generation_state = _parse_time(generation.get('last_success_at'))
            if (not mac_time or mac_time_status != 'valid' or not generation_time or generation_state != 'valid'
                    or abs(generation_time - mac_time) > timedelta(minutes=5)):
                return False
            for item in interface_rows:
                if normalize_interface_name(str(item['interface_name'] or '')).lower() != name:
                    continue
                attribute_time, attribute_state = _parse_time(item['last_seen'])
                if (mac_time_status == 'valid' and mac_time and attribute_state == 'valid' and attribute_time
                        and abs(attribute_time - mac_time) <= timedelta(minutes=5)):
                    access_vlan_cache[key].add(_normalize_vlan_number(item['access_vlan']))
        return access_vlan_cache[key] == {vlan}

    def access_port_status(row: dict[str, Any]) -> str:
        from services.ip_locator_service import endpoint_access_port_evidence
        key = (str(row.get('source_device_id') or ''), str(row.get('interface_name') or ''))
        if key not in access_port_cache:
            access_port_cache[key] = endpoint_access_port_evidence(conn, *key)
        return access_port_cache[key]

    arp_rows = [row for row in rows if row.get("source_type") == "arp" and row.get("ip")]
    conflict_groups: dict[tuple[str, str, str, str], set[str]] = {}
    recent_arp_counts: dict[tuple[str, str, str, str], int] = {}
    for row in arp_rows:
        scope = _effective_scope(row)
        status, _time_status, observed_at = _evidence_status(row, now)
        if scope["scope_status"] != "resolved" or status != "recent" or observed_at is None:
            continue
        key = (str(scope["tenant_id"] or ""), str(scope["site_id"] or ""), str(scope["vrf_id"] or ""), str(row.get("ip") or ""))
        recent_arp_counts[key] = recent_arp_counts.get(key, 0) + 1
        if row.get("mac"):
            conflict_groups.setdefault(key, set()).add(_normalized_mac(row.get("mac")))
    conflict_keys = {key for key, macs in conflict_groups.items() if len(macs - {""}) > 1}

    current_mac_ports: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    for row in mac_rows:
        scope = _effective_scope(row)
        evidence_status, _timestamp_status, observed_at = _evidence_status(row, now)
        if (
            evidence_status != "recent" or not observed_at
            or scope.get("scope_status") not in {"resolved", "scope_pending"}
            or now - observed_at > timedelta(minutes=_recent_minutes())
            or not scope.get("tenant_id") or not scope.get("site_id")
        ):
            continue
        mac = _normalized_mac(row.get("mac"))
        vlan = _normalize_vlan_number(row.get('vlan'))
        if not mac or not vlan:
            continue
        if access_port_status(row) != 'access':
            continue
        if (scope.get('vrf_context_status') == 'unknown'
                and scope.get('scope_status') == 'scope_pending'
                and matches_access_vlan(row, vlan)):
            # Same-device L2 location evidence does not resolve the source's
            # L3 address space or authorize registration/reconciliation.
            local_key = (str(scope['tenant_id']), str(scope['site_id']), str(row.get('source_device_id') or ''), vlan, mac)
            local_mac_ports.setdefault(local_key, []).append(row)
        if scope.get('vrf_context_status') in {'explicit_vrf', 'explicit_global'} and scope.get('scope_status') == 'resolved':
            association_vrf = str(scope.get('vrf_id') or '')
        elif scope.get('vrf_context_status') == 'unknown':
            # A layer-2 forwarding table normally has no VRF field. Resolve
            # its bridge VLAN only through an unambiguous configured binding;
            # keep the original source scope unknown in the returned evidence.
            from services.ip_locator_service import endpoint_vlan_vrf_key
            vlan_scope = (str(scope['tenant_id']), str(scope['site_id']), vlan)
            if vlan_scope not in vlan_vrf_cache:
                vlan_vrf_cache[vlan_scope] = endpoint_vlan_vrf_key(conn, *vlan_scope)
            vlan_vrf_key = vlan_vrf_cache[vlan_scope]
            if vlan_vrf_key is None:
                continue
            association_vrf = vlan_vrf_key[1]
        else:
            continue
        key = (str(scope["tenant_id"]), str(scope["site_id"]), association_vrf, vlan, mac)
        current_mac_ports.setdefault(key, []).append(row)

    decorated: list[dict[str, Any]] = []
    for row in rows:
        scope = _effective_scope(row)
        evidence_status, timestamp_status, observed_at = _evidence_status(row, now)
        if scope["scope_status"] == "conflict":
            evidence_status = "conflict"
        ip = _normalized_ip(row.get("ip"))
        mac = _normalized_mac(row.get("mac"))
        tenant_id = str(scope.get("tenant_id") or "")
        site_id = str(scope.get("site_id") or "")
        vrf_id = str(scope.get("vrf_id") or "")
        conflict_key = (tenant_id, site_id, vrf_id, ip)
        if row.get("source_type") == "arp" and conflict_key in conflict_keys:
            evidence_status = "conflict"
            scope["scope_status"] = "conflict"

        site = sites.get(site_id, {})
        vrf = vrfs.get(vrf_id, {}) if vrf_id else {}
        all_matches = ipam_by_scope.get((tenant_id, site_id, vrf_id, ip), []) if ip else []
        ipam_scope_conflict = any(item.get("_scope_conflict") for item in all_matches)
        matches = [item for item in all_matches if not item.get("_scope_conflict")]
        selected_ipam = matches[0] if (
            len(matches) == 1 and not ipam_scope_conflict and scope['scope_status'] == 'resolved'
        ) else None
        if selected_ipam:
            registration_status = "registered"
        elif not ip or scope["scope_status"] != "resolved" or ipam_scope_conflict:
            registration_status = "scope_pending"
        else:
            registration_status = "unregistered"

        is_access_observation = row.get('source_type') == 'mac' and access_port_status(row) == 'access'
        switch_id = row.get("source_device_id") if is_access_observation else ""
        switch_name = row.get("source_device_name") if is_access_observation else ""
        switch_port = row.get("interface_name") if is_access_observation else ""
        mac_observed_at = row.get("source_observed_at") if row.get("source_type") == "mac" else ""
        location_basis = ''
        if (row.get("source_type") == "arp" and mac and row.get("vlan") and site_id and tenant_id
                and scope.get("scope_status") == "resolved"
                and scope.get("vrf_context_status") in {"explicit_vrf", "explicit_global"}):
            association_key = (tenant_id, site_id, vrf_id, _normalize_vlan_number(row.get('vlan')), mac)
            candidates = current_mac_ports.get(association_key, [])
            unique_ports = {
                (str(candidate.get("source_device_id") or ""), str(candidate.get("interface_name") or "")): candidate
                for candidate in candidates
            }
            if len(unique_ports) == 1:
                candidate = next(iter(unique_ports.values()))
                switch_id = candidate.get("source_device_id")
                switch_name = candidate.get("source_device_name")
                switch_port = candidate.get("interface_name")
                mac_observed_at = candidate.get("source_observed_at")
                location_basis = 'scoped_vlan_mac_access'

        if (not switch_port and row.get('source_type') == 'arp' and mac and row.get('vlan')
                and site_id and tenant_id and scope.get('scope_status') == 'scope_pending'
                and scope.get('vrf_context_status') == 'unknown' and evidence_status == 'recent'
                and observed_at):
            local_key = (tenant_id, site_id, str(row.get('source_device_id') or ''), _normalize_vlan_number(row.get('vlan')), mac)
            candidates = []
            for candidate in local_mac_ports.get(local_key, []):
                candidate_time, candidate_state = _parse_time(candidate.get('source_observed_at'))
                if candidate_state == 'valid' and candidate_time and abs(candidate_time - observed_at) <= timedelta(minutes=5):
                    candidates.append(candidate)
            unique_ports = {
                str(candidate.get('interface_name') or ''): candidate for candidate in candidates
            }
            if len(unique_ports) == 1:
                candidate = next(iter(unique_ports.values()))
                switch_id = candidate.get('source_device_id')
                switch_name = candidate.get('source_device_name')
                switch_port = candidate.get('interface_name')
                mac_observed_at = candidate.get('source_observed_at')
                location_basis = 'same_device_vlan_mac_access'

        decorated.append({
            "id": str(row.get("id") or ""),
            "observation_id": str(row.get("id") or ""),
            "ip": ip or None,
            "mac": mac or None,
            "tenant_id": tenant_id or None,
            "site_id": site_id or None,
            "site_name": str(site.get("site_name") or site.get("site_code") or ""),
            "site": str(site.get("site_name") or site.get("site_code") or ""),
            "vrf_id": vrf_id,
            "vrf_name": str(vrf.get("vrf_name") or ("全局/默认" if scope.get("vrf_context_status") == "explicit_global" else "")),
            "vrf_context_status": scope["vrf_context_status"],
            "source_vrf_context_status": str(row.get("vrf_context_status") or "unknown"),
            "scope_assertion_status": scope["scope_assertion_status"],
            "scope_status": scope["scope_status"],
            "scope_resolution": scope["scope_resolution"],
            "registration_status": registration_status,
            "ipam_scope_status": "conflict" if ipam_scope_conflict else "resolved" if selected_ipam else "unmatched",
            "ip_mac_conflict": row.get("source_type") == "arp" and conflict_key in conflict_keys,
            "subnet_id": (selected_ipam or {}).get("subnet_id") or scope.get("subnet_id"),
            "subnet_prefix": (selected_ipam or {}).get("prefix") or scope.get("subnet_prefix") or "",
            "source_type": str(row.get("source_type") or ""),
            "source_device_id": str(row.get("source_device_id") or ""),
            "source_device_name": str(row.get("source_device_name") or row.get("source_device_id") or ""),
            "source_interface_name": str(row.get('interface_name') or ''),
            "switch_id": str(switch_id or ""),
            "switch_name": str(switch_name or ""),
            "switch_port": str(switch_port or ""),
            "switch_location_status": "matched" if switch_id and switch_port else "pending",
            "switch_location_basis": location_basis,
            "vlan": str(row.get("vlan") or ""),
            "observed_at": str(row.get("source_observed_at") or ""),
            "mac_observed_at": str(mac_observed_at or ""),
            "projected_at": str(row.get("projected_at") or ""),
            "evidence_status": evidence_status,
            "timestamp_status": timestamp_status,
            "hostname": str((selected_ipam or {}).get("hostname") or ""),
            "hostname_source": "ipam" if (selected_ipam or {}).get("hostname") else "",
            "coverage_status": str(row.get("coverage_status") or "unavailable"),
            "coverage_complete": bool(row.get("coverage_complete")),
            "coverage_reason": str(row.get("coverage_reason") or ""),
            "source_run_id": str(row.get("source_run_id") or ""),
            "source_version": str(row.get("source_version") or ""),
            "source_identity_key": str(row.get("source_identity_key") or ""),
            "ipam_address_id": (selected_ipam or {}).get("id") or "",
            "ipam_mac": (selected_ipam or {}).get("mac_address") or "",
            "observed_mac": mac or "",
            "mac_mismatch": bool(
                selected_ipam and _normalized_mac(selected_ipam.get("mac_address"))
                and mac and _normalized_mac(selected_ipam.get("mac_address")) != mac
            ),
            "calibration_safe": bool(
                row.get("source_type") == "arp"
                and scope["scope_status"] == "resolved"
                and evidence_status == "recent"
                and timestamp_status == "valid"
                and recent_arp_counts.get(conflict_key) == 1
                and conflict_key not in conflict_keys
                and selected_ipam
                and not selected_ipam.get("_scope_conflict")
                and selected_ipam.get("status") not in {"available", "released"}
                and selected_ipam.get("mac_address")
                and mac
                and _normalized_mac(selected_ipam.get("mac_address")) != mac
            ),
        })
    return decorated


def _list_filter(item: dict[str, Any], *, site_id: str, vrf_id: str, device_id: str,
                 query: str, kind: str, evidence_status: str, registration_status: str) -> bool:
    if site_id and str(item.get("site_id") or "") != site_id:
        return False
    if vrf_id == "__unknown__":
        if item.get("vrf_context_status") != "unknown":
            return False
    elif vrf_id and str(item.get("vrf_id") or "") != vrf_id:
        return False
    if device_id and device_id not in {
        str(item.get("source_device_id") or ""), str(item.get("switch_id") or ""),
        *(str(value) for value in item.get("source_device_ids", [])),
    }:
        return False
    if kind == "ip" and not item.get("ip"):
        return False
    if kind == "mac" and (item.get("source_type") != "mac" or not item.get("mac")):
        return False
    if evidence_status == "scope_pending":
        if item.get("scope_status") == "resolved":
            return False
    elif evidence_status == "conflict":
        if not item.get("ip_mac_conflict"):
            return False
    elif evidence_status and item.get("evidence_status") != evidence_status:
        return False
    if registration_status and item.get("registration_status") != registration_status:
        return False
    if query:
        values = " ".join(str(value or "") for value in item.values()).lower()
        if query not in values:
            return False
    return True


def _supersede_older_endpoint_context_observations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For one tenant/site/IP/MAC/VLAN identity, keep the latest sample.

    Current endpoint rows are stored per routing context. If that context is
    later resolved or reclassified, an older successful snapshot can otherwise
    remain visible beside the newer one. Keep both only when the latest sample
    is tied across contexts; that case needs explicit scope review.
    """
    groups: dict[tuple[str, ...], list[tuple[int, datetime, tuple[str, ...]]]] = {}
    for index, item in enumerate(items):
        if str(item.get("source_type") or "") not in {"arp", "ndp"}:
            continue
        if not item.get("ip") or not item.get("mac") or not item.get("source_device_id"):
            continue
        observed_at, timestamp_status = _parse_time(item.get("observed_at"))
        if timestamp_status != "valid" or observed_at is None:
            continue
        identity = (
            str(item.get("source_type") or ""),
            str(item.get("tenant_id") or ""),
            str(item.get("site_id") or ""),
            str(item.get("ip") or ""),
            _normalized_mac(item.get("mac")),
            str(item.get("vlan") or ""),
        )
        context = (
            str(item.get("scope_status") or ""),
            str(item.get("address_space_id") or ""),
            str(item.get("vrf_id") or ""),
            str(item.get("source_device_id") or ""),
            str(item.get("context_source") or ""),
            str(item.get("context_type") or ""),
            str(item.get("local_context_key") or ""),
        )
        groups.setdefault(identity, []).append((index, observed_at, context))

    superseded_indices: set[int] = set()
    for group in groups.values():
        contexts = {context for _index, _observed_at, context in group}
        if len(contexts) < 2:
            continue
        latest_at = max(observed_at for _index, observed_at, _context in group)
        latest_contexts = {
            context for _index, observed_at, context in group if observed_at == latest_at
        }
        if len(latest_contexts) != 1:
            continue
        latest_context = next(iter(latest_contexts))
        superseded_indices.update(
            index for index, observed_at, context in group
            if observed_at < latest_at and context != latest_context
        )

    return [item for index, item in enumerate(items) if index not in superseded_indices]


def _terminal_identity_key(item: dict[str, Any]) -> tuple[Any, ...]:
    if (item.get("scope_status") == "resolved" or item.get('vrf_context_inferred')) and item.get("ip"):
        return (
            "ip", item.get("tenant_id"), item.get("site_id"), item.get("vrf_id"),
            item.get("ip"), _normalized_mac(item.get("mac")),
        )
    if (item.get("scope_status") == "resolved" and not item.get("ip") and item.get("mac")
            and item.get('switch_location_status') == 'matched'):
        return (
            "mac", item.get("tenant_id"), item.get("site_id"), item.get("vrf_id"),
            _normalized_mac(item.get("mac")), item.get("vlan"), item.get("switch_id"), item.get("switch_port"),
        )
    # Unknown scope is never collapsed globally by IP or MAC. Retain the
    # original source context so site reuse and unresolved VRFs remain visible.
    return (
        "source", item.get("source_type"), item.get("tenant_id"), item.get("site_id"),
        item.get("vrf_id"), item.get("source_device_id"), item.get("ip"),
        _normalized_mac(item.get("mac")), item.get("vlan"), item.get("switch_port"),
        item.get('source_interface_name'),
    )


def _collapse_terminal_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(_terminal_identity_key(item), []).append(item)
    collapsed = []
    for group in grouped.values():
        group.sort(key=lambda item: (item.get("observed_at") or item.get("projected_at") or "", item.get("id") or ""), reverse=True)
        item = dict(group[0])
        source_devices = {}
        for evidence in group:
            device_id = str(evidence.get("source_device_id") or "")
            if device_id:
                source_devices[device_id] = str(evidence.get("source_device_name") or device_id)
        item["source_device_ids"] = sorted(source_devices)
        item["source_device_names"] = [source_devices[key] for key in sorted(source_devices)]
        item["source_evidence_count"] = len(group)
        item["calibration_safe"] = bool(item.get("calibration_safe") and len(group) == 1)
        collapsed.append(item)
    return collapsed


def _normalize_vlan_number(value: Any) -> str:
    text = str(value or '').strip()
    if text.isdigit() and 1 <= int(text) <= 4094:
        return str(int(text))
    return ''


def _infrastructure_addresses(conn) -> set[tuple[str, str, str, str]]:
    """Exclude known device/gateway IPs only within their own address scope."""
    owned: set[tuple[str, str, str, str]] = set()
    rows = conn.execute(
        """SELECT tenant_id, site_id, vrf_id, gateway AS address FROM prefixes
           WHERE COALESCE(is_active, 1) = 1 AND COALESCE(gateway, '') <> ''
           UNION ALL
           SELECT p.tenant_id, p.site_id, p.vrf_id, a.address
           FROM ip_addresses a JOIN prefixes p ON p.id = a.subnet_id
           WHERE a.source_type = 'interface_collection'"""
    ).fetchall()
    for row in rows:
        address = _normalized_ip(row.get('address'))
        if address and row.get('site_id'):
            owned.add((str(row.get('tenant_id') or DEFAULT_TENANT_ID),
                       str(row['site_id']), str(row.get('vrf_id') or ''), address))
    # Current CMDB CLI snapshots use the project's global/default VRF policy.
    # Never use those rows to exclude an identically numbered host in another VRF.
    from services.ipam_service import _current_cmdb_interface_ip_observations
    devices, _sites, _vrfs = _device_catalog(conn)
    for row in conn.execute("SELECT id, ip_address FROM devices WHERE COALESCE(ip_address, '') <> ''").fetchall():
        scope = devices.get(str(row['id']), {})
        address = _normalized_ip(row.get('ip_address'))
        if address and scope.get('site_id') and scope.get('scope_status') != 'conflict':
            owned.add((str(scope.get('tenant_id') or DEFAULT_TENANT_ID),
                       str(scope['site_id']), '', address))
    for row in _current_cmdb_interface_ip_observations(conn):
        device = devices.get(str(row.get('device_id') or ''), {})
        scope = _resolve_device_scope(device, _sites, _vrfs)
        address = _normalized_ip(row.get('ip_address'))
        if address and scope.get('site_id') and scope.get('scope_status') != 'conflict':
            owned.add((str(scope.get('tenant_id') or DEFAULT_TENANT_ID),
                       str(scope['site_id']), '', address))
    return owned


def _load_active_prefix_scopes(conn) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    rows = conn.execute(
        """SELECT p.id, p.prefix, p.tenant_id, p.site_id, p.vrf_id,
                  p.network_type, p.status, p.is_active, p.vlan_id,
                  vl.vlan_id AS vlan_number, vl.status AS vlan_status,
                  vl.site_id AS vlan_site_id, vl.tenant_id AS vlan_tenant_id
             FROM prefixes p
             LEFT JOIN vlans vl ON vl.id = p.vlan_id
            WHERE COALESCE(p.is_active, 1) = 1"""
    ).fetchall()
    prefixes_by_scope: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for raw in rows:
        row = dict(raw)
        try:
            network = ipaddress.ip_network(str(row.get('prefix') or ''), strict=False)
        except ValueError:
            continue
        tenant_id = str(row.get('tenant_id') or DEFAULT_TENANT_ID)
        site_id = str(row.get('site_id') or '')
        vlan_id = str(row.get('vlan_id') or '')
        vlan_site_id = str(row.get('vlan_site_id') or '')
        vlan_tenant_id = str(row.get('vlan_tenant_id') or '')
        vlan_status = str(row.get('vlan_status') or '').strip().lower()
        vlan_number = _normalize_vlan_number(row.get('vlan_number'))
        vlan_scope_valid = bool(
            vlan_id and vlan_number and vlan_status == 'active'
            and (not vlan_site_id or vlan_site_id == site_id)
            and (not vlan_tenant_id or vlan_tenant_id == tenant_id)
        )
        status = str(row.get('status') or 'active').strip().lower()
        scope = (tenant_id, site_id, str(row.get('vrf_id') or ''))
        prefixes_by_scope.setdefault(scope, []).append({
            'id': str(row.get('id') or ''),
            'network': network,
            'vrf_id': scope[2],
            'network_type': str(row.get('network_type') or ''),
            'active': status == 'active',
            'vlan_id': vlan_id,
            'vlan_number': vlan_number,
            'vlan_scope_valid': vlan_scope_valid,
        })
    return prefixes_by_scope


def _match_business_vlan_scope(
    item: dict[str, Any],
    prefixes_by_scope: dict[tuple[str, str, str], list[dict[str, Any]]],
) -> dict[str, Any] | None:
    source_vrf_status = str(item.get('vrf_context_status') or 'unknown')
    inferred_global = source_vrf_status == 'unknown' and item.get('scope_status') == 'scope_pending'
    explicitly_scoped = (
        source_vrf_status in {'explicit_vrf', 'explicit_global'}
        and item.get('scope_status') in {'resolved', 'conflict'}
    )
    if not (inferred_global or explicitly_scoped):
        return None
    tenant_id = str(item.get('tenant_id') or '')
    site_id = str(item.get('site_id') or '')
    if not tenant_id or not site_id:
        return None
    scope = (tenant_id, site_id, str(item.get('vrf_id') or ''))
    if inferred_global:
        scoped_prefixes = [
            prefix
            for (prefix_tenant_id, prefix_site_id, _prefix_vrf_id), rows in prefixes_by_scope.items()
            if prefix_tenant_id == tenant_id and prefix_site_id == site_id
            for prefix in rows
        ]
    else:
        scoped_prefixes = prefixes_by_scope.get(scope, [])
    observed_vlan = _normalize_vlan_number(item.get('vlan'))

    if item.get('ip'):
        try:
            address = ipaddress.ip_address(str(item.get('ip')))
        except ValueError:
            return None
        candidates = [prefix for prefix in scoped_prefixes if address.version == prefix['network'].version and address in prefix['network']]
        if not candidates:
            return None
        most_specific_length = max(prefix['network'].prefixlen for prefix in candidates)
        most_specific = [prefix for prefix in candidates if prefix['network'].prefixlen == most_specific_length]
        if len(most_specific) != 1:
            return None
        prefix = most_specific[0]
        if inferred_global and prefix['vrf_id']:
            return None
        if not prefix['active'] or not is_business_utilization_network(prefix['network_type']):
            return None
        network = prefix['network']
        if network.num_addresses <= 2:
            return None
        if address.version == 4 and address in {network.network_address, network.broadcast_address}:
            return None
        # A source VLAN is direct evidence that the endpoint was observed in
        # a VLAN. When IPAM already links the prefix to a VLAN, require an
        # exact match; legacy prefixes without that link can still be scoped
        # by their business CIDR plus the source VLAN observation.
        if not observed_vlan:
            return None
        if prefix['vlan_id']:
            if not prefix['vlan_scope_valid'] or observed_vlan != prefix['vlan_number']:
                return None
        return {'inferred_global': inferred_global}

    if inferred_global or item.get('source_type') != 'mac' or not observed_vlan:
        return None
    vlan_prefixes = [
        prefix for prefix in scoped_prefixes
        if prefix['vlan_scope_valid'] and prefix['vlan_number'] == observed_vlan
    ]
    if not vlan_prefixes or not all(
        prefix['active'] and is_business_utilization_network(prefix['network_type'])
        for prefix in vlan_prefixes
    ):
        return None
    return {'inferred_global': False}


def list_discovered_endpoints(
    *, site_id: str = "", vrf_id: str = "", device_id: str = "", q: str = "",
    kind: str = "all", evidence_status: str = "", registration_status: str = "",
    network_scope: str = "all",
    page: int = 1, page_size: int = 20,
    visible_scopes: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    if network_scope not in {"all", "business_vlan"}:
        raise ValueError("Unsupported discovered endpoint network_scope")
    conn = get_db_connection()
    try:
        now = _utc_now()
        raw_rows = _load_projected_observations(conn)
        if visible_scopes is not None:
            raw_rows = [
                row for row in raw_rows
                if (str(row.get("tenant_id") or ""), str(row.get("site_id") or "")) in visible_scopes
            ]
        items = _decorate_observations(raw_rows, conn, now)
        if network_scope == "business_vlan":
            prefixes_by_scope = _load_active_prefix_scopes(conn)
            infrastructure_addresses = _infrastructure_addresses(conn)
            scoped_items = []
            for item in items:
                scope_match = _match_business_vlan_scope(item, prefixes_by_scope)
                if scope_match is None:
                    continue
                if _is_virtual_gateway_mac(item.get('mac')):
                    # Keep this observation in raw snapshots/all-scope views,
                    # but do not count a VRRP/HSRP/GLBP virtual MAC as a host.
                    continue
                address_key = (str(item.get('tenant_id') or ''), str(item.get('site_id') or ''),
                               str(item.get('vrf_id') or ''), str(item.get('ip') or ''))
                if item.get('ip') and address_key in infrastructure_addresses:
                    continue
                scoped_item = dict(item)
                if scope_match['inferred_global']:
                    scoped_item.update({
                        'vrf_id': '',
                        'vrf_name': '全局/默认',
                        'vrf_context_status': 'inferred_global',
                        'scope_resolution': 'business_prefix_unique_default_vrf',
                        'vrf_context_inferred': True,
                    })
                scoped_items.append(scoped_item)
            items = scoped_items
        visible_items = [
            item for item in items
            if visible_scopes is None
            or (str(item.get("tenant_id") or ""), str(item.get("site_id") or "")) in visible_scopes
        ]
        filtered_source_items = [
            item for item in items
            if _list_filter(
                item, site_id=site_id.strip(), vrf_id=vrf_id.strip(), device_id=device_id.strip(),
                query=q.strip().lower(), kind=kind, evidence_status=evidence_status,
                registration_status=registration_status,
            )
        ]
        filtered_source_items = [
            item for item in filtered_source_items
            if visible_scopes is None
            or (str(item.get("tenant_id") or ""), str(item.get("site_id") or "")) in visible_scopes
        ]
        filtered = _collapse_terminal_items(filtered_source_items)
        filtered.sort(key=lambda item: (item.get("observed_at") or item.get("projected_at") or "", item.get("id") or ""), reverse=True)
        safe_page = max(1, int(page or 1))
        safe_page_size = min(max(1, int(page_size or 20)), 100)
        start = (safe_page - 1) * safe_page_size
        site_catalog, vrf_catalog = _catalog_scope(conn)
        authorized_for_options = visible_items
        site_ids = sorted({str(item.get("site_id") or "") for item in authorized_for_options if item.get("site_id")})
        vrf_ids = sorted({str(item.get("vrf_id") or "") for item in authorized_for_options if item.get("vrf_context_status") != "unknown"})
        site_options = [
            {"id": value, "name": str(site_catalog.get(value, {}).get("site_name") or site_catalog.get(value, {}).get("site_code") or value)}
            for value in site_ids
        ]
        vrf_options = [
            {
                "id": value,
                "name": "全局/默认" if not value else str(vrf_catalog.get(value, {}).get("vrf_name") or value),
            }
            for value in vrf_ids
        ]
        if any(item.get("vrf_context_status") == "unknown" for item in authorized_for_options):
            vrf_options.append({"id": "__unknown__", "name": "范围待确认"})
        devices_by_id: dict[str, str] = {}
        for item in filtered_source_items:
            for key_id, key_name in ((item.get("source_device_id"), item.get("source_device_name")), (item.get("switch_id"), item.get("switch_name"))):
                if key_id:
                    devices_by_id[str(key_id)] = str(key_name or key_id)
        device_options = [{"id": key, "name": devices_by_id[key]} for key in sorted(devices_by_id)]
        evidence_device_ids = sorted({
            str(item.get("source_device_id") or "")
            for item in filtered_source_items if item.get("source_type") == "arp" and item.get("source_device_id")
        })
        latest_success_at = ""
        if evidence_device_ids:
            placeholders = ",".join("?" for _ in evidence_device_ids)
            status_rows = conn.execute(
                f"""SELECT device_id, last_success_at
                      FROM device_collection_status
                     WHERE collector = 'arp' AND status = 'success'
                       AND device_id IN ({placeholders})""",
                tuple(evidence_device_ids),
            ).fetchall()
            device_catalog, site_catalog, vrf_catalog = _device_catalog(conn)
            success_times = []
            for status in status_rows:
                device = device_catalog.get(str(status.get("device_id") or ""), {})
                scope = _resolve_device_scope(device, site_catalog, vrf_catalog)
                if visible_scopes is not None and (
                    str(scope.get("tenant_id") or ""), str(scope.get("site_id") or "")
                ) not in visible_scopes:
                    continue
                parsed, parsed_state = _parse_time(status.get("last_success_at"))
                if parsed and parsed_state == "valid":
                    success_times.append(parsed)
            latest_success_at = _iso(max(success_times)) if success_times else ""
        arp_items = [item for item in filtered if item.get("ip")]
        full_comparison_evidence = bool(arp_items) and all(
            item.get("scope_status") == "resolved" and item.get("coverage_complete")
            and item.get("source_vrf_context_status") in {"explicit_vrf", "explicit_global"}
            and item.get("evidence_status") == "recent" for item in arp_items
        )
        summary = {
            # This is the number of displayed IP observations, including
            # historical/unresolved records, not a PC census or recent-only count.
            "discovered_ip_count": len(arp_items),
            "recent_ip_count": sum(1 for item in arp_items if item.get("evidence_status") == "recent"),
            "mac_only_count": sum(1 for item in filtered if item.get("mac") and not item.get("ip")),
            "registered_count": sum(1 for item in filtered if item.get("registration_status") == "registered"),
            "unregistered_count": sum(1 for item in filtered if item.get("registration_status") == "unregistered"),
            "scope_pending_count": sum(1 for item in filtered if item.get("scope_status") != "resolved"),
            "conflict_count": sum(1 for item in filtered if item.get("evidence_status") == "conflict"),
            "coverage_status": "complete" if full_comparison_evidence else "partial" if filtered else "unavailable",
            "coverage_reason": "仅显示已投影的源记录；范围不明或无法证明完整代次的采集不会用于判断缺席。",
            "source_last_success_at": latest_success_at,
        }
        return {
            "items": filtered[start:start + safe_page_size],
            "total": len(filtered), "page": safe_page, "page_size": safe_page_size,
            "has_more": start + safe_page_size < len(filtered),
            "summary": summary, "sites": site_options, "vrfs": vrf_options, "devices": device_options,
            "network_scope": network_scope,
        }
    finally:
        conn.close()


def get_discovered_endpoint(observation_id: str) -> dict[str, Any] | None:
    conn = get_db_connection()
    try:
        now = _utc_now()
        latest_rows = _load_projected_observations(conn)
        latest_items = _decorate_observations(latest_rows, conn, now)
        latest = next((item for item in latest_items if item.get("id") == observation_id), None)
        if not latest:
            return None
        if latest.get("scope_status") == "resolved" and latest.get("ip"):
            raw_rows = _load_projected_observations(conn, ip=latest["ip"], mac=latest.get("mac"), history=True)
        elif latest.get("mac"):
            raw_rows = _load_projected_observations(conn, observation_id=observation_id, history=True)
        else:
            raw_rows = _load_projected_observations(conn, observation_id=observation_id, history=True)
        decorated_history = _decorate_observations(raw_rows, conn, now)
        evidence_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for item, row in zip(decorated_history, raw_rows):
            same_identity = _terminal_identity_key(item) == _terminal_identity_key(latest)
            scoped_mac_evidence = bool(
                latest.get("scope_status") == "resolved"
                and latest.get("vrf_context_status") in {"explicit_vrf", "explicit_global"}
                and item.get("source_type") == "mac"
                and item.get("scope_status") == "resolved"
                and item.get("vrf_context_status") in {"explicit_vrf", "explicit_global"}
                and item.get("mac") == latest.get("mac")
                and item.get("tenant_id") == latest.get("tenant_id")
                and item.get("site_id") == latest.get("site_id")
                and item.get("vrf_id") == latest.get("vrf_id")
                and item.get("vlan") == latest.get("vlan")
            )
            if same_identity or scoped_mac_evidence:
                evidence_rows.append((item, row))
        evidence = []
        for item, row in evidence_rows:
            evidence.append({
                "observation_id": item["id"], "source_type": item["source_type"],
                "source_device_id": item["source_device_id"],
                "source_device_name": item["source_device_name"],
                "interface_name": str(row.get("interface_name") or ""),
                "interface_id": None,
                "vlan": item["vlan"], "ip": item["ip"], "mac": item["mac"],
                "observed_at": item["observed_at"], "projected_at": item["projected_at"],
                "timestamp_status": item["timestamp_status"],
                "scope_status": item["scope_status"], "vrf_context_status": item["vrf_context_status"],
                "coverage_status": item["coverage_status"], "coverage_complete": item["coverage_complete"],
                "coverage_reason": item["coverage_reason"], "source_run_id": item["source_run_id"],
                "source_version": item["source_version"], "source_identity_key": item["source_identity_key"],
            })
        return {**latest, "source_evidence_count": len(evidence), "observations": evidence}
    finally:
        conn.close()


def _acquire_projection_lock(conn) -> None:
    # Match the projector's session lock so a source projection cannot advance
    # between version validation and the IPAM write.
    conn.execute("SELECT pg_advisory_lock(?, ?)", _PROJECTION_LOCK_KEY)
    conn.commit()


def _assert_latest_raw_arp_observation(conn, row: dict[str, Any]) -> None:
    if str(row.get("source_type") or "") != "arp" or not row.get("ip"):
        raise ValueError("registration_requires_ip_observation")
    latest = conn.execute(
        """SELECT o.id
             FROM ipam_discovery_observations o
             JOIN ipam_discovery_snapshots s ON s.id = o.snapshot_id
            WHERE o.source_identity_key = ?
            ORDER BY o.projected_at DESC, s.projected_at DESC, o.id DESC
            LIMIT 1""",
        (str(row.get("source_identity_key") or ""),),
    ).fetchone()
    if not latest or str(latest["id"]) != str(row.get("id") or ""):
        raise ValueError("observation_version_changed")

    newer_source = conn.execute(
        """SELECT id FROM ipam_discovery_observations
            WHERE source_type = 'arp'
              AND source_device_id = ?
              AND ip = ?
              AND projected_at > ?
              AND COALESCE(tenant_id, '') = COALESCE(?, '')
              AND COALESCE(site_id, '') = COALESCE(?, '')
              AND COALESCE(vrf_id, '') = COALESCE(?, '')
              AND vrf_context_status = ?
            LIMIT 1""",
        (
            row.get("source_device_id"), row.get("ip"), row.get("projected_at"),
            row.get("tenant_id"), row.get("site_id"), row.get("vrf_id"),
            row.get("vrf_context_status") or "unknown",
        ),
    ).fetchone()
    if newer_source:
        raise ValueError("observation_version_changed")

    raw_rows = conn.execute(
        """SELECT ip_address, mac_address, interface_name, vlan_id, last_updated
             FROM arp_table
            WHERE device_id = ? AND ip_address = ?
            ORDER BY id FOR SHARE""",
        (row.get("source_device_id"), row.get("ip")),
    ).fetchall()
    if len(raw_rows) != 1:
        raise ValueError("observation_no_longer_in_source_snapshot")
    raw = dict(raw_rows[0])
    source_time, source_time_status = _parse_time(raw.get("last_updated"))
    expected_time, expected_time_status = _parse_time(row.get("source_observed_at"))
    if (
        source_time_status != "valid" or expected_time_status != "valid"
        or source_time != expected_time
        or _normalized_mac(raw.get("mac_address")) != _normalized_mac(row.get("mac"))
        or str(raw.get("interface_name") or "").strip() != str(row.get("interface_name") or "").strip()
        or str(raw.get("vlan_id") or "").strip() != str(row.get("vlan") or "").strip()
    ):
        raise ValueError("observation_version_changed")


def register_discovered_observation(
    *, observation_id: str, subnet_id: str, expected_observed_at: str,
    confirmed_scope: bool, requested_by: str,
) -> dict[str, Any]:
    """Create an IPAM address and a durable manual scope assertion atomically."""
    if not confirmed_scope:
        raise ValueError("scope_confirmation_required")
    conn = get_db_connection()
    try:
        _acquire_projection_lock(conn)
        raw = conn.execute(
            """SELECT o.*, s.source_run_id, s.coverage_status, s.coverage_complete,
                      s.coverage_reason, s.source_status
                 FROM ipam_discovery_observations o
                 JOIN ipam_discovery_snapshots s ON s.id = o.snapshot_id
                WHERE o.id = ? FOR UPDATE OF o""",
            (observation_id,),
        ).fetchone()
        if not raw:
            raise LookupError("observation_not_found")
        row = dict(raw)
        _assert_latest_raw_arp_observation(conn, row)
        observed_at, time_state = _parse_time(row.get("source_observed_at"))
        expected_at, expected_state = _parse_time(expected_observed_at)
        if time_state != "valid" or expected_state != "valid" or observed_at != expected_at:
            raise ValueError("observation_version_changed")
        if _utc_now() - observed_at > timedelta(minutes=_recent_minutes()):
            raise ValueError("observation_not_current")
        if row.get("scope_status") == "conflict":
            raise ValueError("observation_scope_conflict")
        if not row.get("tenant_id") or not row.get("site_id"):
            raise ValueError("source_site_tenant_not_verified")

        prefix_row = conn.execute(
            "SELECT * FROM prefixes WHERE id = ? FOR UPDATE", (subnet_id,)
        ).fetchone()
        if not prefix_row:
            raise LookupError("subnet_not_found")
        prefix = dict(prefix_row)
        prefix_tenant = str(prefix.get("tenant_id") or DEFAULT_TENANT_ID)
        prefix_site = str(prefix.get("site_id") or "")
        prefix_vrf = str(prefix.get("vrf_id") or "")
        if prefix.get("status") == "stale" or prefix.get("is_active") in (False, 0):
            raise ValueError("subnet_not_active")
        if prefix_tenant != str(row.get("tenant_id") or "") or not prefix_site or prefix_site != str(row.get("site_id") or ""):
            raise ValueError("subnet_scope_does_not_match_source")
        raw_context = str(row.get("vrf_context_status") or "unknown")
        if raw_context == "invalid_vrf":
            raise ValueError("source_vrf_context_invalid")
        if raw_context == "explicit_vrf" and prefix_vrf != str(row.get("vrf_id") or ""):
            raise ValueError("subnet_vrf_does_not_match_source")
        if raw_context == "explicit_global" and prefix_vrf:
            raise ValueError("subnet_vrf_does_not_match_global_source")
        ip = _normalized_ip(row.get("ip"))
        try:
            network = ipaddress.ip_network(str(prefix.get("prefix") or ""), strict=False)
        except ValueError as exc:
            raise ValueError("subnet_prefix_invalid") from exc
        if not ip or ipaddress.ip_address(ip) not in network:
            raise ValueError("ip_not_in_subnet")

        from services.ipam_service import _create_address_with_conn
        source_note = "从发现证据人工登记"
        source_device_name = str(row.get("source_device_name") or row.get("source_device_id") or "")
        source_interface = str(row.get("interface_name") or "")
        if source_device_name or source_interface:
            source_note += f"；来源设备/接口：{source_device_name} {source_interface}".strip()
        address = _create_address_with_conn(
            conn, subnet_id, address=ip,
            # An ARP source device/interface identifies the router's neighbor
            # table observation, not ownership/NIC data for the endpoint IP.
            hostname="", device_id="", interface_name="",
            mac_address=_normalized_mac(row.get("mac")) or "",
            device_type="", description=source_note,
            status="active", lock_prefix=False, requested_by=requested_by,
            source_type="ipam_discovery", source_ref=observation_id,
        )
        asserted_at = _iso(_utc_now()) or _utc_now().isoformat()
        assertion_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO ipam_discovery_scope_assertions (
                   id, observation_id, source_identity_key, subnet_id, tenant_id, site_id, vrf_id,
                   subnet_prefix, prior_scope_status, prior_tenant_id, prior_site_id, prior_vrf_id,
                   asserted_by, asserted_at, confirmation
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                assertion_id, observation_id, row.get("source_identity_key") or "", subnet_id,
                prefix_tenant, prefix_site, prefix_vrf, prefix.get("prefix") or "",
                row.get("scope_status") or "scope_pending", row.get("tenant_id"), row.get("site_id"),
                row.get("vrf_id"), requested_by, asserted_at, "confirmed_scope",
            ),
        )
        conn.commit()
        return {
            "ok": True,
            "ipam_address_id": str(address.get("id") or ""),
            "observation_id": observation_id,
            "created": not bool(address.get("reused")),
            "assertion_id": assertion_id,
            "scope": {"tenant_id": prefix_tenant, "site_id": prefix_site, "vrf_id": prefix_vrf, "subnet_id": subnet_id},
            "source_scope": {"tenant_id": row.get("tenant_id"), "site_id": row.get("site_id"), "vrf_id": row.get("vrf_id")},
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def calibrate_ipam_mac(
    *, observation_id: str, ipam_address_id: str, expected_observed_at: str,
    expected_mac_address: str, confirmed: bool,
) -> dict[str, Any]:
    """Update only the IPAM MAC from one current, unique ARP observation."""
    if not confirmed:
        raise ValueError("mac_calibration_confirmation_required")
    conn = get_db_connection()
    try:
        current_rows = _load_projected_observations(conn)
        decorated = _decorate_observations(current_rows, conn, _utc_now())
        evidence = next((item for item in decorated if item.get("id") == observation_id), None)
        if not evidence:
            raise LookupError("observation_not_current")
        if evidence.get("source_type") != "arp" or not evidence.get("calibration_safe"):
            raise ValueError("observation_not_calibration_safe")
        if evidence.get("ipam_address_id") != ipam_address_id:
            raise ValueError("observation_ipam_binding_changed")
        observed_at, observed_state = _parse_time(evidence.get("observed_at"))
        expected_at, expected_state = _parse_time(expected_observed_at)
        if observed_state != "valid" or expected_state != "valid" or observed_at != expected_at:
            raise ValueError("observation_version_changed")
        if _utc_now() - observed_at > timedelta(minutes=_recent_minutes()):
            raise ValueError("observation_not_current")

        address_row = conn.execute(
            """SELECT ip.*, p.tenant_id AS prefix_tenant_id, p.site_id AS prefix_site_id,
                      p.vrf_id AS prefix_vrf_id, p.prefix AS subnet_prefix
                 FROM ip_addresses ip JOIN prefixes p ON p.id = ip.subnet_id
                WHERE ip.id = ? FOR UPDATE OF ip""",
            (ipam_address_id,),
        ).fetchone()
        if not address_row:
            raise LookupError("ipam_address_not_found")
        address = dict(address_row)
        current_mac = _normalized_mac(address.get("mac_address"))
        expected_mac = _normalized_mac(expected_mac_address)
        observed_mac = _normalized_mac(evidence.get("observed_mac"))
        if current_mac != expected_mac:
            raise ValueError("ipam_mac_version_changed")
        if not observed_mac or observed_mac == current_mac:
            raise ValueError("mac_calibration_not_required")
        ip = _normalized_ip(address.get("address"))
        tenant_id = str(address.get("prefix_tenant_id") or DEFAULT_TENANT_ID)
        site_id = str(address.get("prefix_site_id") or "")
        vrf_id = str(address.get("prefix_vrf_id") or "")
        if (
            ip != evidence.get("ip") or tenant_id != str(evidence.get("tenant_id") or "")
            or site_id != str(evidence.get("site_id") or "")
            or vrf_id != str(evidence.get("vrf_id") or "")
        ):
            raise ValueError("observation_scope_does_not_match_ipam")
        updated_at = _iso(_utc_now()) or _utc_now().isoformat()
        conn.execute(
            "UPDATE ip_addresses SET mac_address = ?, updated_at = ?, revision = revision + 1 WHERE id = ?",
            (observed_mac, updated_at, ipam_address_id),
        )
        conn.commit()
        return {
            "ok": True, "ipam_address_id": ipam_address_id,
            "observation_id": observation_id, "previous_mac": current_mac,
            "mac": observed_mac, "observed_at": evidence.get("observed_at"),
            "scope": {"tenant_id": tenant_id, "site_id": site_id, "vrf_id": vrf_id},
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _current_endpoint_observation_id(row: dict[str, Any]) -> str:
    """Build a stable ID for one replaceable ARP/ND row in a successful generation."""
    identity = {
        "source": str(row.get("observation_source") or "arp"),
        "device_id": str(row.get("source_device_id") or ""),
        "context_source": str(row.get("context_source") or ""),
        "context_type": str(row.get("context_type") or ""),
        "local_context_key": str(row.get("local_context_key") or ""),
        "ip": _normalized_ip(row.get("ip_address")),
        "mac": _normalized_mac(row.get("mac_address")),
        "interface": str(row.get("normalized_interface_name") or ""),
        "vlan": int(row.get("vlan_id") or 0),
        "generation": int(row.get("generation") or 0),
    }
    return _stable_id("ipam-current-endpoint:" + _canonical_json(identity))


def _current_endpoint_projection(
    conn, *, device_id: str = "", observation_source: str = "arp",
) -> list[dict[str, Any]]:
    """Decorate current ARP/ND rows, collection state, and explicit mappings."""
    from services.ipam_current_endpoint_observation_service import list_current_endpoint_observations

    normalized_source = str(observation_source or "arp").strip().lower()
    if normalized_source not in {"arp", "ndp"}:
        raise ValueError("unsupported_current_address_observation_source")
    source_rows = list_current_endpoint_observations(
        conn, device_id=device_id or None, observation_source=normalized_source,
    )
    if not source_rows:
        return []

    unmapped_global_tenants = {
        str(row.get("tenant_id") or DEFAULT_TENANT_ID)
        for row in source_rows
        if str(row.get("context_type") or "").strip().lower() == "global"
        and not str(row.get("address_space_id") or "").strip()
    }
    global_spaces_by_tenant: dict[str, list[dict[str, Any]]] = {}
    if unmapped_global_tenants:
        tenant_marks = ",".join("?" for _ in unmapped_global_tenants)
        global_rows = conn.execute(
            f"""SELECT id, security_tenant_id, name, kind, vrf_id, status
                  FROM ipam_address_spaces
                 WHERE kind = 'global' AND status = 'active'
                   AND COALESCE(NULLIF(btrim(security_tenant_id), ''), ?) IN ({tenant_marks})""",
            (DEFAULT_TENANT_ID, *sorted(unmapped_global_tenants)),
        ).fetchall()
        for raw in global_rows:
            space = dict(raw)
            global_spaces_by_tenant.setdefault(
                str(space.get("security_tenant_id") or DEFAULT_TENANT_ID).strip() or DEFAULT_TENANT_ID, [],
            ).append(space)
        # A device's collector explicitly reported the global table. If its
        # tenant has exactly one active Global domain, that is an unambiguous
        # address-space mapping even when no per-device context row was stored.
        for row in source_rows:
            if str(row.get("context_type") or "").strip().lower() != "global":
                continue
            tenant_id = str(row.get("tenant_id") or DEFAULT_TENANT_ID)
            candidates = global_spaces_by_tenant.get(tenant_id, [])
            if not str(row.get("address_space_id") or "").strip() and len(candidates) == 1:
                space = candidates[0]
                row["address_space_id"] = str(space.get("id") or "")
                row["resolved_context_type"] = "global"
                row["address_space_name"] = str(space.get("name") or "")
                row["mapped_vrf_id"] = ""

    from services.ipam_inventory_scope import load_inventory_catalog, match_inventory_prefix
    prefix_catalog, _prefix_sites, _prefix_vrfs = load_inventory_catalog(conn)
    active_prefix_ids = {
        str(row["id"])
        for row in conn.execute(
            """SELECT id FROM prefixes
                 WHERE COALESCE(is_active, 1) = 1
                   AND COALESCE(status, 'active') = 'active'
                   AND COALESCE(address_space_id, '') <> ''"""
        ).fetchall()
    }
    prefix_catalog = [item for item in prefix_catalog if str(item.get("id") or "") in active_prefix_ids]

    device_ids = sorted({str(row.get("source_device_id") or "") for row in source_rows if row.get("source_device_id")})
    device_marks = ",".join("?" for _ in device_ids)
    device_rows = conn.execute(
        f"""SELECT device.id, device.hostname,
                   COALESCE(NULLIF(btrim(device.tenant_id), ''), ?) AS tenant_id,
                   COALESCE(device.site_id, '') AS site_id,
                   COALESCE(site.site_name, site.site_code, '') AS site_name,
                   COALESCE(site.site_code, '') AS site_code
              FROM devices device
              LEFT JOIN sites site ON site.id = device.site_id
             WHERE device.id IN ({device_marks})""",
        (DEFAULT_TENANT_ID, *device_ids),
    ).fetchall()
    devices = {str(row["id"]): dict(row) for row in device_rows}

    address_space_ids = sorted({str(row.get("address_space_id") or "") for row in source_rows if row.get("address_space_id")})
    spaces: dict[str, dict[str, Any]] = {}
    if address_space_ids:
        space_marks = ",".join("?" for _ in address_space_ids)
        space_rows = conn.execute(
            f"""SELECT space.id, space.security_tenant_id, space.name,
                       space.kind, space.vrf_id, space.status,
                       COALESCE(vrf.vrf_name, '') AS vrf_name
                  FROM ipam_address_spaces space
                  LEFT JOIN vrfs vrf ON vrf.id = space.vrf_id
                 WHERE space.id IN ({space_marks})""",
            tuple(address_space_ids),
        ).fetchall()
        spaces = {str(row["id"]): dict(row) for row in space_rows}

    ips = sorted({
        _normalized_ip(row.get("ip_address"))
        for row in source_rows if row.get("address_space_id") and _normalized_ip(row.get("ip_address"))
    })
    formal_by_scope: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    if address_space_ids and ips:
        space_marks = ",".join("?" for _ in address_space_ids)
        ip_marks = ",".join("?" for _ in ips)
        formal_rows = conn.execute(
            f"""SELECT ip.id, COALESCE(host(ip.address_inet), ip.address) AS address,
                       ip.mac_address, ip.hostname, ip.status, ip.revision,
                       COALESCE(NULLIF(ip.address_space_id, ''), prefix.address_space_id, '') AS address_space_id,
                       COALESCE(NULLIF(prefix.tenant_id, ''), ?) AS tenant_id,
                       prefix.site_id, prefix.id AS subnet_id, prefix.prefix AS subnet_prefix,
                       prefix.status AS prefix_status, prefix.is_active AS prefix_is_active
                  FROM ip_addresses ip
                  JOIN prefixes prefix ON prefix.id = ip.subnet_id
                 WHERE COALESCE(NULLIF(ip.address_space_id, ''), prefix.address_space_id, '') IN ({space_marks})
                   AND COALESCE(host(ip.address_inet), ip.address) IN ({ip_marks})""",
            (DEFAULT_TENANT_ID, *address_space_ids, *ips),
        ).fetchall()
        for raw in formal_rows:
            item = dict(raw)
            address = _normalized_ip(item.get("address"))
            key = (
                str(item.get("tenant_id") or DEFAULT_TENANT_ID),
                str(item.get("address_space_id") or ""),
                address,
            )
            formal_by_scope.setdefault(key, []).append(item)

    current_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    staged: list[dict[str, Any]] = []
    for source in source_rows:
        row = dict(source)
        device = devices.get(str(row.get("source_device_id") or ""))
        if not device:
            # An orphan row cannot carry a trustworthy security scope.
            continue
        tenant_id = str(device.get("tenant_id") or DEFAULT_TENANT_ID)
        site_id = str(device.get("site_id") or "")
        address = _normalized_ip(row.get("ip_address"))
        if not address:
            continue

        generation = int(row.get("generation") or 0)
        last_success_generation = int(row.get("last_success_generation") or 0)
        if generation < 1 or generation != last_success_generation:
            # A row whose generation does not match the state fence is not current evidence.
            continue

        space_id = str(row.get("address_space_id") or "")
        space = spaces.get(space_id)
        resolved_type = str(row.get("resolved_context_type") or "")
        resolved = bool(
            space and space_id
            and str(space.get("status") or "") == "active"
            and str(space.get("security_tenant_id") or "") == tenant_id
            and (
                (resolved_type == "vrf" and str(space.get("kind") or "") == "vrf")
                or (resolved_type == "global" and str(space.get("kind") or "") == "global")
            )
        )
        if not resolved:
            space_id = ""
            space = None
            resolved_type = ""

        observed_at = str(row.get("observed_at") or "")
        observed_time, timestamp_status = _parse_time(observed_at)
        age = (_utc_now() - observed_time) if observed_time and timestamp_status == "valid" else None
        evidence_status = (
            "recent" if age is not None and age <= timedelta(minutes=_recent_minutes())
            else "stale" if age is not None
            else "unknown"
        )
        latest_status = str(row.get("latest_status") or "")
        latest_attempt_generation = int(row.get("latest_attempt_generation") or 0)
        latest_success_is_current_attempt = (
            generation == latest_attempt_generation
            and latest_status in {"complete", "scope_unknown"}
        )
        coverage_complete = latest_success_is_current_attempt
        context_status = (
            "explicit_vrf" if resolved_type == "vrf"
            else "explicit_global" if resolved_type == "global"
            else "explicit_global" if str(row.get("context_type") or "").strip().lower() == "global"
            else "unknown"
        )
        ipam_key = (tenant_id, space_id, address) if resolved else (tenant_id, "", address)
        candidates = formal_by_scope.get(ipam_key, []) if resolved else []
        active_candidates = [
            item for item in candidates
            if str(item.get("status") or "active") not in {"released", "available"}
            and str(item.get("prefix_status") or "active") != "stale"
            and item.get("prefix_is_active") not in (False, 0)
        ]
        ipam_conflict = len(active_candidates) > 1
        selected_ipam = active_candidates[0] if len(active_candidates) == 1 else None
        suggested_prefix = None
        if resolved and not selected_ipam:
            suggested_prefix = match_inventory_prefix(
                address,
                (tenant_id, f"space:{space_id}"),
                site_id,
                prefix_catalog,
            )
        registration_status = (
            "registered" if selected_ipam
            else "unregistered" if resolved and not ipam_conflict
            else "scope_pending"
        )
        mac = _normalized_mac(row.get("mac_address"))
        scope_key = (tenant_id, space_id, address) if resolved else (
            tenant_id,
            f"device:{device['id']}:{row.get('context_source')}:{row.get('context_type')}:{row.get('local_context_key')}",
            address,
        )
        item = {
            "id": _current_endpoint_observation_id(row),
            "observation_id": _current_endpoint_observation_id(row),
            "ip": address,
            "mac": mac or None,
            "tenant_id": tenant_id,
            "site_id": site_id,
            "site_name": str(device.get("site_name") or device.get("site_code") or ""),
            "site": str(device.get("site_name") or device.get("site_code") or ""),
            "vrf_id": str(space.get("vrf_id") or "") if space and resolved_type == "vrf" else "",
            "vrf_name": str(space.get("vrf_name") or ("全局/默认" if resolved_type == "global" else "")) if space else "",
            "vrf_context_status": context_status,
            "source_vrf_context_status": str(row.get("context_type") or "unknown"),
            "scope_assertion_status": "not_applicable",
            "scope_status": "resolved" if resolved else "scope_pending",
            "scope_resolution": "current_explicit_context_mapping" if resolved else "unresolved_current_context",
            "registration_status": registration_status,
            "ipam_scope_status": "conflict" if ipam_conflict else "resolved" if selected_ipam else "unmatched",
            "ip_mac_conflict": False,
            "subnet_id": str((selected_ipam or {}).get("subnet_id") or ""),
            "subnet_prefix": str((selected_ipam or {}).get("subnet_prefix") or ""),
            "suggested_subnet_id": str((suggested_prefix or {}).get("id") or ""),
            "suggested_subnet_prefix": str((suggested_prefix or {}).get("prefix") or ""),
            "source_type": normalized_source,
            "observation_source": normalized_source,
            "source_device_id": str(row.get("source_device_id") or ""),
            "source_device_name": str(device.get("hostname") or row.get("source_device_id") or ""),
            "source_interface_name": str(row.get("interface_name") or ""),
            "normalized_interface_name": str(row.get("normalized_interface_name") or ""),
            "switch_id": "",
            "switch_name": "",
            "switch_port": "",
            "switch_location_status": "pending",
            "switch_location_basis": "",
            "vlan": str(row.get("vlan_id") or ""),
            "observed_at": observed_at,
            "mac_observed_at": "",
            "projected_at": "",
            "evidence_status": evidence_status,
            "timestamp_status": timestamp_status,
            "hostname": str((selected_ipam or {}).get("hostname") or ""),
            "hostname_source": "ipam" if (selected_ipam or {}).get("hostname") else "",
            "coverage_status": "complete" if coverage_complete else latest_status or "unavailable",
            "coverage_complete": coverage_complete,
            "coverage_reason": (
                "latest_attempt_complete" if coverage_complete
                else "latest_attempt_not_successful; showing last successful current generation"
            ),
            "source_run_id": str(row.get("run_id") or ""),
            "source_version": str(generation),
            "source_identity_key": _digest({
                "device_id": str(row.get("source_device_id") or ""),
                "context_source": str(row.get("context_source") or ""),
                "context_type": str(row.get("context_type") or ""),
                "local_context_key": str(row.get("local_context_key") or ""),
                "ip": address,
                "mac": mac,
                "interface": str(row.get("normalized_interface_name") or ""),
                "vlan": int(row.get("vlan_id") or 0),
                "generation": generation,
            }),
            "ipam_address_id": str((selected_ipam or {}).get("id") or ""),
            "ipam_mac": str((selected_ipam or {}).get("mac_address") or ""),
            "observed_mac": mac,
            "mac_mismatch": bool(
                selected_ipam and _normalized_mac(selected_ipam.get("mac_address"))
                and mac and _normalized_mac(selected_ipam.get("mac_address")) != mac
            ),
            "calibration_safe": bool(
                resolved and evidence_status == "recent" and timestamp_status == "valid"
                and latest_success_is_current_attempt and not ipam_conflict
                and selected_ipam and str(selected_ipam.get("status") or "active") not in {"available", "released"}
                and _normalized_mac(selected_ipam.get("mac_address"))
                and mac and _normalized_mac(selected_ipam.get("mac_address")) != mac
            ),
            "address_space_id": space_id or None,
            "address_space_name": str(space.get("name") or "") if space else "",
            "address_space_kind": str(space.get("kind") or "") if space else "",
            "context_source": str(row.get("context_source") or ""),
            "context_type": str(row.get("context_type") or "unknown"),
            "local_context_key": str(row.get("local_context_key") or ""),
            "local_context_name": str(row.get("local_context_name") or ""),
            "collection_status": latest_status,
            "generation": generation,
            "latest_attempt_generation": latest_attempt_generation,
            "last_success_generation": last_success_generation,
            "last_attempt_at": str(row.get("last_attempt_at") or ""),
            "last_success_at": str(row.get("last_success_at") or ""),
            "_current_scope_key": scope_key,
            "_ipam_conflict": ipam_conflict,
        }
        staged.append(item)
        current_groups.setdefault(scope_key, []).append(item)

    for siblings in current_groups.values():
        observed_macs = {_normalized_mac(item.get("mac")) for item in siblings if _normalized_mac(item.get("mac"))}
        if len(observed_macs) > 1:
            for item in siblings:
                item["ip_mac_conflict"] = True
                item["evidence_status"] = "conflict"
                item["calibration_safe"] = False

    for item in staged:
        item.pop("_current_scope_key", None)
        item.pop("_ipam_conflict", None)
    ids: dict[str, int] = {}
    for item in staged:
        ids[str(item.get("id") or "")] = ids.get(str(item.get("id") or ""), 0) + 1
    # Stable IDs intentionally omit observed_at. If the current table contains
    # conflicting rows for one identity/generation, hide each collision.
    return [item for item in staged if ids.get(str(item.get("id") or "")) == 1]


def _current_fdb_observation_id(row: dict[str, Any]) -> str:
    return "fdb:" + _digest({
        "device_id": str(row.get("source_device_id") or ""),
        "context_source": str(row.get("context_source") or ""),
        "context_type": str(row.get("context_type") or ""),
        "local_context_key": str(row.get("local_context_key") or ""),
        "mac": _normalized_mac(row.get("mac_address")),
        "interface": str(row.get("normalized_interface_name") or ""),
        "vlan": int(row.get("vlan_id") or 0),
        "generation": int(row.get("generation") or 0),
    })


def _classify_current_fdb_path(
    interface_metadata: dict[str, Any] | None,
    aggregation: dict[str, Any] | None,
    topology_link_kind: str = '',
) -> tuple[str, str]:
    """Describe current port evidence without inventing a unique edge host."""
    if not interface_metadata:
        return 'unknown', 'interface_inventory_missing'
    if aggregation:
        return (
            'logical_aggregation' if aggregation.get('is_logical') else 'aggregation_member',
            'current_interface_aggregation_membership',
        )
    switchport_mode = str(interface_metadata.get('switchport_mode') or '').strip().lower()
    if switchport_mode in {'trunk', 'tagged', 'hybrid'}:
        return 'trunk_tagged_interface', 'current_interface_switchport_mode'
    if topology_link_kind:
        return str(topology_link_kind), 'current_topology_link'
    if switchport_mode in {'access', 'untagged'}:
        return 'access_edge', 'explicit_interface_access_mode'
    return 'unknown', 'insufficient_edge_or_uplink_evidence'


def _current_fdb_path_metadata(conn, source_rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Load current interface and topology hints for FDB path classification."""
    from core.interface_utils import normalize_interface_name
    from services.topology_service import _load_interface_aggregation_map

    device_ids = sorted({
        str(row.get('source_device_id') or '').strip()
        for row in source_rows if row.get('source_device_id')
    })
    if not device_ids:
        return {}
    marks = ', '.join('?' for _ in device_ids)
    interface_rows = [dict(row) for row in conn.execute(
        f'''SELECT id, device_id, interface_name, interface_type, switchport_mode
              FROM interfaces WHERE device_id IN ({marks})''',
        tuple(device_ids),
    ).fetchall()]
    interface_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in interface_rows:
        normalized = normalize_interface_name(str(row.get('interface_name') or '')).strip().lower()
        if normalized:
            interface_by_key.setdefault((str(row.get('device_id') or ''), normalized), []).append(row)

    aggregation_map = _load_interface_aggregation_map(conn)
    topology_kinds: dict[tuple[str, str], set[str]] = {}
    link_rows = conn.execute(
        f'''SELECT source_device_id, source_port, source_port_normalized,
                   target_device_id, target_port, target_port_normalized,
                   link_kind, status
              FROM topology_links
             WHERE source_device_id IN ({marks}) OR target_device_id IN ({marks})''',
        tuple(device_ids + device_ids),
    ).fetchall()
    for raw in link_rows:
        link = dict(raw)
        if str(link.get('status') or '').strip().lower() not in {'up', 'degraded'}:
            continue
        link_kind = str(link.get('link_kind') or 'physical').strip().lower()
        path_kind = 'topology_aggregation_link' if link_kind == 'aggregation' else 'topology_neighbor_link'
        for side in ('source', 'target'):
            endpoint_device = str(link.get(f'{side}_device_id') or '').strip()
            endpoint_name = str(link.get(f'{side}_port_normalized') or '').strip().lower()
            if not endpoint_name:
                endpoint_name = normalize_interface_name(
                    str(link.get(f'{side}_port') or '')
                ).strip().lower()
            if endpoint_device and endpoint_device in device_ids and endpoint_name:
                topology_kinds.setdefault((endpoint_device, endpoint_name), set()).add(path_kind)

    result: dict[tuple[str, str], dict[str, Any]] = {}
    for key, matches in interface_by_key.items():
        if len(matches) != 1:
            result[key] = {
                'path_classification': 'unknown',
                'path_evidence': 'interface_identity_ambiguous',
                'aggregation_name': '',
                'aggregation_protocol': '',
            }
            continue
        interface = matches[0]
        aggregation = aggregation_map.get(key)
        topology_options = sorted(topology_kinds.get(key, set()))
        topology_kind = topology_options[0] if len(topology_options) == 1 else (
            'topology_uplink' if topology_options else ''
        )
        if aggregation and not topology_kind:
            topology_kind = topology_kinds.get(
                (key[0], normalize_interface_name(str(aggregation.get('aggregation_name') or '')).strip().lower()),
                set(),
            )
            topology_kind = sorted(topology_kind)[0] if topology_kind else ''
        path_classification, path_evidence = _classify_current_fdb_path(
            interface, aggregation, topology_kind,
        )
        result[key] = {
            'path_classification': path_classification,
            'path_evidence': path_evidence,
            'aggregation_name': str((aggregation or {}).get('aggregation_name') or ''),
            'aggregation_protocol': str((aggregation or {}).get('aggregation_protocol') or ''),
            'topology_link_kind': str(topology_kind or ''),
        }
    return result


def _current_fdb_endpoint_projection(conn, *, device_id: str = "") -> list[dict[str, Any]]:
    """Project current FDB rows as MAC-only observations; never as IP ownership."""
    from services.ipam_current_fdb_observation_service import list_current_fdb_observations

    source_rows = list_current_fdb_observations(conn, device_id=device_id or None)
    path_metadata = _current_fdb_path_metadata(conn, [dict(row) for row in source_rows])
    staged: list[dict[str, Any]] = []
    path_groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for source in source_rows:
        row = dict(source)
        mac = _normalized_mac(row.get("mac_address"))
        if not mac:
            continue
        generation = int(row.get("generation") or 0)
        if generation < 1 or generation != int(row.get("last_success_generation") or 0):
            continue
        tenant_id = str(row.get("tenant_id") or DEFAULT_TENANT_ID)
        site_id = str(row.get("site_id") or "")
        address_space_id = str(row.get("address_space_id") or "")
        resolved_context_type = str(row.get("resolved_context_type") or "")
        resolved = bool(address_space_id and resolved_context_type in {"vrf", "global"})
        context_type = str(row.get("context_type") or "unknown")
        context_source = str(row.get("context_source") or "")
        local_context_key = str(row.get("local_context_key") or "")
        interface_name = str(row.get("interface_name") or "")
        normalized_interface = str(row.get("normalized_interface_name") or "")
        observed_at = str(row.get("observed_at") or "")
        observed_time, timestamp_status = _parse_time(observed_at)
        age = (_utc_now() - observed_time) if observed_time and timestamp_status == "valid" else None
        evidence_status = (
            "recent" if age is not None and age <= timedelta(minutes=_recent_minutes())
            else "stale" if age is not None
            else "unknown"
        )
        latest_status = str(row.get("latest_status") or "")
        latest_attempt_generation = int(row.get("latest_attempt_generation") or 0)
        coverage_complete = (
            generation == latest_attempt_generation
            and latest_status in {"complete", "scope_unknown"}
        )
        device_id_value = str(row.get("source_device_id") or "")
        interface_path = path_metadata.get(
            (device_id_value, normalized_interface.strip().lower()),
            {
                'path_classification': 'unknown',
                'path_evidence': 'interface_inventory_missing',
                'aggregation_name': '',
                'aggregation_protocol': '',
                'topology_link_kind': '',
            },
        )
        observation_id = _current_fdb_observation_id(row)
        item = {
            "id": observation_id,
            "observation_id": observation_id,
            "ip": None,
            "mac": mac,
            "tenant_id": tenant_id,
            "site_id": site_id,
            "site_name": str(row.get("site_name") or ""),
            "vrf_id": str(row.get("mapped_vrf_id") or "") if resolved_context_type == "vrf" else "",
            "vrf_name": str(row.get("address_space_name") or "") if resolved_context_type == "vrf" else "",
            "vrf_context_status": resolved_context_type if resolved else "unknown",
            "source_vrf_context_status": context_type,
            "scope_status": "resolved" if resolved else "scope_pending",
            "scope_resolution": "current_explicit_context_mapping" if resolved else "unresolved_current_context",
            "registration_status": "not_applicable",
            "subnet_id": None,
            "subnet_prefix": None,
            "source_type": "mac",
            "observation_source": "fdb",
            "source_device_id": device_id_value,
            "source_device_name": str(row.get("source_device_name") or device_id_value),
            "switch_id": device_id_value,
            "switch_name": str(row.get("source_device_name") or device_id_value),
            "switch_port": interface_name,
            "source_interface_name": interface_name,
            "normalized_interface_name": normalized_interface,
            "switch_location_status": "observed_interface",
            "switch_location_basis": "current_fdb_observation",
            "path_ambiguity": False,
            "path_ambiguity_reason": "",
            "path_classification": str(interface_path.get('path_classification') or 'unknown'),
            "path_evidence": str(interface_path.get('path_evidence') or ''),
            "aggregation_name": str(interface_path.get('aggregation_name') or ''),
            "aggregation_protocol": str(interface_path.get('aggregation_protocol') or ''),
            "topology_link_kind": str(interface_path.get('topology_link_kind') or ''),
            "virtual_gateway_mac": _is_virtual_gateway_mac(mac),
            "vlan": str(row.get("vlan_id") or ""),
            "entry_type": str(row.get("entry_type") or ""),
            "observed_at": observed_at,
            "mac_observed_at": observed_at,
            "projected_at": "",
            "evidence_status": evidence_status,
            "timestamp_status": timestamp_status,
            "hostname": "",
            "hostname_source": "",
            "coverage_status": "complete" if coverage_complete else latest_status or "unavailable",
            "coverage_complete": coverage_complete,
            "coverage_reason": (
                "latest_attempt_complete" if coverage_complete
                else "latest_attempt_not_successful; showing last successful current generation"
            ),
            "source_run_id": str(row.get("run_id") or ""),
            "source_version": str(generation),
            "source_identity_key": _digest({
                "device_id": device_id_value,
                "context_source": context_source,
                "context_type": context_type,
                "local_context_key": local_context_key,
                "mac": mac,
                "interface": normalized_interface,
                "vlan": int(row.get("vlan_id") or 0),
                "generation": generation,
            }),
            "ipam_address_id": None,
            "ipam_mac": None,
            "observed_mac": mac,
            "mac_mismatch": False,
            "calibration_safe": False,
            "address_space_id": address_space_id or None,
            "address_space_name": str(row.get("address_space_name") or "") if resolved else "",
            "address_space_kind": "vrf" if resolved_context_type == "vrf" else "global" if resolved else "",
            "context_source": context_source,
            "context_type": context_type,
            "local_context_key": local_context_key,
            "local_context_name": str(row.get("local_context_name") or ""),
            "collection_status": latest_status,
            "generation": generation,
            "latest_attempt_generation": latest_attempt_generation,
            "last_success_generation": int(row.get("last_success_generation") or 0),
            "last_attempt_at": str(row.get("last_attempt_at") or ""),
            "last_success_at": str(row.get("last_success_at") or ""),
            "source_evidence_count": 1,
            "observations": [{
                "observation_id": observation_id,
                "source_type": "fdb",
                "source_device_id": device_id_value,
                "source_device_name": str(row.get("source_device_name") or device_id_value),
                "interface_name": interface_name,
                "vlan": str(row.get("vlan_id") or ""),
                "ip": None,
                "mac": mac,
                "observed_at": observed_at,
                "source_version": str(generation),
                "coverage_status": latest_status,
                "timestamp_status": timestamp_status,
                "context_source": context_source,
                "context_type": context_type,
                "local_context_key": local_context_key,
                "path_classification": str(interface_path.get('path_classification') or 'unknown'),
                "aggregation_name": str(interface_path.get('aggregation_name') or ''),
                "topology_link_kind": str(interface_path.get('topology_link_kind') or ''),
                "virtual_gateway_mac": _is_virtual_gateway_mac(mac),
            }],
        }
        staged.append(item)
        if resolved:
            path_key = (tenant_id, address_space_id, mac, str(row.get("vlan_id") or ""))
        else:
            path_key = (
                tenant_id, site_id, f"device:{device_id_value}:{context_source}:{context_type}:{local_context_key}",
                mac, str(row.get("vlan_id") or ""),
            )
        path_groups.setdefault(path_key, []).append(item)

    for siblings in path_groups.values():
        locations = {
            (str(item.get("source_device_id") or ""), str(item.get("normalized_interface_name") or ""))
            for item in siblings
        }
        if len(locations) > 1:
            for item in siblings:
                item["path_ambiguity"] = True
                item["path_ambiguity_reason"] = "multiple_current_fdb_paths_for_mac_vlan_scope"
                item["switch_location_status"] = "ambiguous"

    ids: dict[str, int] = {}
    for item in staged:
        identity = str(item.get("id") or "")
        ids[identity] = ids.get(identity, 0) + 1
    return [item for item in staged if ids.get(str(item.get("id") or "")) == 1]


def _current_endpoint_is_current(conn, observation_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Lock and reload a current ARP/ND row/state pair after selection."""
    projection = [
        *_current_endpoint_projection(conn, observation_source="arp"),
        *_current_endpoint_projection(conn, observation_source="ndp"),
    ]
    matches = [item for item in projection if item.get("id") == observation_id]
    if not matches:
        raise LookupError("observation_not_current")
    if len(matches) != 1:
        raise ValueError("observation_version_ambiguous")
    displayed = matches[0]
    observation_source = str(displayed.get("observation_source") or displayed.get("source_type") or "arp")
    if observation_source not in {"arp", "ndp"}:
        raise ValueError("observation_source_not_supported_for_ip_action")
    context_source = str(displayed.get("context_source") or "")
    context_type = str(displayed.get("context_type") or "")
    local_key = str(displayed.get("local_context_key") or "")
    state = conn.execute(
        """SELECT * FROM ipam_endpoint_collection_states
             WHERE device_id = ? AND observation_source = ?
               AND context_source = ? AND context_type = ? AND local_context_key = ?
             FOR UPDATE""",
        (displayed["source_device_id"], observation_source, context_source, context_type, local_key),
    ).fetchone()
    if not state:
        raise LookupError("observation_not_current")
    current = conn.execute(
        """SELECT * FROM ipam_current_endpoint_observations
             WHERE source_device_id = ? AND observation_source = ?
               AND context_source = ? AND context_type = ? AND local_context_key = ?
               AND generation = ? AND ip_address = ?::inet AND mac_address = ?
               AND normalized_interface_name = ? AND vlan_key = ?
             FOR UPDATE""",
        (
            displayed["source_device_id"], observation_source, context_source, context_type, local_key,
            int(displayed["generation"]), displayed["ip"],
            _normalized_mac(displayed.get("mac")).replace(":", ""),
            str(displayed.get("normalized_interface_name") or ""), int(displayed.get("vlan") or 0),
        ),
    ).fetchone()
    if not current:
        raise ValueError("observation_version_changed")
    locked = dict(current)
    locked["vlan_id"] = locked.get("vlan_key")
    locked["observed_at"] = locked.get("observed_at")
    if _current_endpoint_observation_id(locked) != observation_id:
        raise ValueError("observation_version_changed")
    if int(state["last_success_generation"] or 0) != int(locked["generation"] or 0):
        raise ValueError("observation_version_changed")
    return displayed, {**locked, "_state": dict(state)}


def _current_infrastructure_ip_keys(
    conn, visible_scopes: set[tuple[str, str]] | None = None,
) -> tuple[
    set[tuple[str, str, str]], set[tuple[str, str, str]], set[tuple[str, str]],
]:
    """Read configured interface and managed-device addresses from current state."""
    from services.ipam_service import _current_cmdb_interface_ip_observations

    interface_keys: set[tuple[str, str, str]] = set()
    for row in _current_cmdb_interface_ip_observations(conn):
        sites = {str(row.get(key) or '') for key in ('asset_site_id', 'device_site_id') if row.get(key)}
        address = _normalized_ip(row.get('ip_address'))
        if len(sites) == 1 and address:
            tenant_id = str(row.get('tenant_id') or DEFAULT_TENANT_ID)
            site_id = next(iter(sites))
            if visible_scopes is None or (tenant_id, site_id) in visible_scopes:
                interface_keys.add((tenant_id, site_id, address))

    managed_keys: set[tuple[str, str, str]] = set()
    managed_addresses: set[tuple[str, str]] = set()
    for row in conn.execute(
        "SELECT tenant_id, site_id, ip_address FROM devices WHERE COALESCE(ip_address, '') <> ''"
    ).fetchall():
        address = _normalized_ip(row['ip_address'])
        if not address:
            continue
        tenant_id = str(row['tenant_id'] or DEFAULT_TENANT_ID)
        if visible_scopes is not None and (tenant_id, str(row['site_id'] or '')) not in visible_scopes:
            continue
        managed_addresses.add((tenant_id, address))
        if row['site_id']:
            managed_keys.add((tenant_id, str(row['site_id']), address))
    return interface_keys, managed_keys, managed_addresses


def _classify_current_endpoint_rows(
    items: list[dict[str, Any]], fdb_items: list[dict[str, Any]],
    interface_keys: set[tuple[str, str, str]], managed_keys: set[tuple[str, str, str]],
    managed_addresses: set[tuple[str, str]],
) -> None:
    """Annotate observations without promoting ARP or FDB to formal ownership."""
    fdb_by_identity: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for fdb in fdb_items:
        key = tuple(str(fdb.get(field) or '') for field in (
            'tenant_id', 'site_id', 'source_device_id', 'context_source',
            'context_type', 'local_context_key', 'mac', 'vlan',
        ))
        fdb_by_identity.setdefault(key, []).append(fdb)

    for item in items:
        ip = _normalized_ip(item.get('ip'))
        if not ip:
            item['endpoint_class'] = 'mac_only'
            item['endpoint_class_reason'] = 'fdb_without_ip'
            continue
        identity = (
            str(item.get('tenant_id') or DEFAULT_TENANT_ID),
            str(item.get('site_id') or ''), ip,
        )
        if identity in interface_keys:
            endpoint_class, reason = 'infrastructure', 'current_l3_interface_ip'
        elif identity in managed_keys:
            endpoint_class, reason = 'infrastructure', 'managed_device_ip'
        elif _is_virtual_gateway_mac(item.get('mac')):
            endpoint_class, reason = 'infrastructure', 'virtual_gateway_mac'
            item['virtual_gateway_mac'] = True
        elif (identity[0], ip) in managed_addresses:
            endpoint_class, reason = 'infrastructure', 'managed_device_site_mismatch'
        else:
            key = tuple(str(item.get(field) or '') for field in (
                'tenant_id', 'site_id', 'source_device_id', 'context_source',
                'context_type', 'local_context_key', 'mac', 'vlan',
            ))
            paths = fdb_by_identity.get(key, []) if item.get('mac') and item.get('vlan') else []
            access_paths = [fdb for fdb in paths if (
                fdb.get('path_classification') == 'access_edge'
                and not fdb.get('path_ambiguity')
                and fdb.get('evidence_status') == 'recent'
                and fdb.get('coverage_complete')
                and fdb.get('switch_port')
            )]
            if (
                item.get('evidence_status') == 'recent'
                and item.get('coverage_complete')
                and len(paths) == len(access_paths) == 1
            ):
                path = access_paths[0]
                endpoint_class, reason = 'access_host', 'same_device_vlan_fdb_access'
                item['switch_id'] = path.get('switch_id') or ''
                item['switch_name'] = path.get('switch_name') or ''
                item['switch_port'] = path.get('switch_port') or ''
                item['path_classification'] = 'access_edge'
                item['path_evidence'] = reason
            else:
                endpoint_class, reason = 'candidate', 'access_path_not_confirmed'
        item['endpoint_class'] = endpoint_class
        item['endpoint_class_reason'] = reason


def _current_endpoint_identity(item: dict[str, Any]) -> tuple[str, ...]:
    space = str(item.get('address_space_id') or '')
    context = space or ':'.join(str(item.get(key) or '') for key in (
        'context_source', 'context_type', 'local_context_key',
    ))
    return (
        str(item.get('tenant_id') or DEFAULT_TENANT_ID),
        str(item.get('site_id') or ''), context, str(item.get('ip') or ''),
    )


def list_current_discovered_endpoints(
    *, site_id: str = "", vrf_id: str = "", device_id: str = "", q: str = "",
    kind: str = "all", evidence_status: str = "", registration_status: str = "",
    network_scope: str = "all", endpoint_class: str = 'all',
    page: int = 1, page_size: int = 20,
    visible_scopes: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """List replaceable current ARP/FDB projections and explicit mappings only."""
    if network_scope not in {"all", "business_vlan"}:
        raise ValueError("Unsupported discovered endpoint network_scope")
    if endpoint_class not in {'all', 'terminal', 'infrastructure', 'access_host', 'candidate'}:
        raise ValueError('Unsupported endpoint_class')
    conn = get_db_connection()
    try:
        arp_projection = _current_endpoint_projection(
            conn, device_id=device_id.strip(), observation_source="arp",
        )
        ndp_projection = _current_endpoint_projection(
            conn, device_id=device_id.strip(), observation_source="ndp",
        )
        fdb_projection = _current_fdb_endpoint_projection(conn, device_id=device_id.strip())
        all_items = [*arp_projection, *ndp_projection, *fdb_projection]
        # The terminal inventory is sourced only from explicitly classified
        # access switches and APs. Keep other devices' observations in storage
        # for IP locator/reconciliation, but do not present them as endpoint
        # collection results here. Generic "switch" is not an access role.
        source_device_ids = sorted({
            str(item.get("source_device_id") or "") for item in all_items
            if item.get("source_device_id")
        })
        if source_device_ids:
            marks = ",".join("?" for _ in source_device_ids)
            role_rows = conn.execute(
                f"""SELECT d.id, COALESCE(NULLIF(pa.device_role, ''), d.role, '') AS role
                      FROM devices d
                      LEFT JOIN physical_assets pa ON pa.id = d.asset_id
                     WHERE d.id IN ({marks})""",
                tuple(source_device_ids),
            ).fetchall()
            from services.collection_plan_service import normalize_device_role
            terminal_role_ids = {
                str(row["id"]): normalize_device_role(row["role"])
                for row in role_rows
                if normalize_device_role(row["role"]) in {
                    "access", "access-layer-switch", "接入交换机", "ap",
                    "wireless-ap", "无线ap", "无线接入点",
                }
            }
            all_items = [
                item for item in all_items
                if str(item.get("source_device_id") or "") in terminal_role_ids
            ]
        if visible_scopes is not None:
            all_items = [
                item for item in all_items
                if (str(item.get("tenant_id") or ""), str(item.get("site_id") or "")) in visible_scopes
            ]
        all_items = _supersede_older_endpoint_context_observations(all_items)
        interface_keys, managed_keys, managed_addresses = _current_infrastructure_ip_keys(conn, visible_scopes)
        _classify_current_endpoint_rows(all_items, fdb_projection, interface_keys, managed_keys, managed_addresses)

        if network_scope == "business_vlan":
            address_space_ids = sorted({str(item.get("address_space_id") or "") for item in all_items if item.get("address_space_id")})
            business_prefixes: list[dict[str, Any]] = []
            if address_space_ids:
                marks = ",".join("?" for _ in address_space_ids)
                rows = conn.execute(
                    f"""SELECT id, prefix, tenant_id, site_id, address_space_id, network_type
                          FROM prefixes
                         WHERE address_space_id IN ({marks})
                           AND COALESCE(status, 'active') <> 'stale'
                           AND COALESCE(is_active, 1) = 1""",
                    tuple(address_space_ids),
                ).fetchall()
                from services.ipam_network_scope import is_business_utilization_network
                for raw in rows:
                    prefix = dict(raw)
                    if not is_business_utilization_network(prefix.get("network_type")):
                        continue
                    try:
                        prefix["_network"] = ipaddress.ip_network(str(prefix.get("prefix") or ""), strict=False)
                    except ValueError:
                        continue
                    business_prefixes.append(prefix)
            filtered_for_network = []
            for item in all_items:
                try:
                    address = ipaddress.ip_address(str(item.get("ip") or ""))
                except ValueError:
                    continue
                if any(
                    str(prefix.get("tenant_id") or DEFAULT_TENANT_ID) == str(item.get("tenant_id") or "")
                    and str(prefix.get("address_space_id") or "") == str(item.get("address_space_id") or "")
                    and (not prefix.get("site_id") or str(prefix.get("site_id")) == str(item.get("site_id") or ""))
                    and address.version == prefix["_network"].version and address in prefix["_network"]
                    for prefix in business_prefixes
                ) and not _is_virtual_gateway_mac(item.get("mac")):
                    filtered_for_network.append(item)
            all_items = filtered_for_network

        visible_items = list(all_items)
        query = q.strip().lower()
        scope_filtered_items = [
            item for item in all_items
            if _list_filter(
                item,
                site_id=site_id.strip(), vrf_id=vrf_id.strip(), device_id=device_id.strip(),
                query=query, kind=kind, evidence_status=evidence_status,
                registration_status=registration_status,
            )
        ]
        terminal_classes = {'access_host', 'candidate', 'mac_only'}
        filtered_source_items = [
            item for item in scope_filtered_items
            if endpoint_class == 'all'
            or (endpoint_class == 'terminal' and item.get('endpoint_class') in terminal_classes)
            or item.get('endpoint_class') == endpoint_class
        ]
        filtered_source_items.sort(
            key=lambda item: (item.get("observed_at") or "", item.get("id") or ""), reverse=True,
        )
        safe_page = max(1, int(page or 1))
        safe_page_size = min(max(1, int(page_size or 20)), 100)
        start = (safe_page - 1) * safe_page_size

        sites_by_id = {
            str(item.get("site_id") or ""): str(item.get("site_name") or item.get("site_id") or "")
            for item in visible_items if item.get("site_id")
        }
        site_options = [{"id": key, "name": sites_by_id[key]} for key in sorted(sites_by_id)]
        vrf_options_by_id: dict[str, str] = {}
        for item in visible_items:
            if item.get("vrf_context_status") == "unknown":
                vrf_options_by_id["__unknown__"] = "范围待确认"
            else:
                vrf_id_value = str(item.get("vrf_id") or "")
                vrf_options_by_id[vrf_id_value] = str(item.get("vrf_name") or ("全局/默认" if not vrf_id_value else vrf_id_value))
        vrf_options = [{"id": key, "name": vrf_options_by_id[key]} for key in sorted(vrf_options_by_id)]
        devices_by_id = {
            str(item.get("source_device_id") or ""): str(item.get("source_device_name") or item.get("source_device_id") or "")
            for item in scope_filtered_items if item.get("source_device_id")
        }
        device_options = [{"id": key, "name": devices_by_id[key]} for key in sorted(devices_by_id)]
        arp_items = [item for item in scope_filtered_items if item.get("ip")]
        mac_items = [item for item in scope_filtered_items if not item.get("ip") and item.get("mac")]
        distinct_ips: dict[tuple[str, ...], str] = {}
        class_rank = {'candidate': 0, 'access_host': 1, 'infrastructure': 2}
        for item in arp_items:
            key = _current_endpoint_identity(item)
            current = distinct_ips.get(key, 'candidate')
            proposed = str(item.get('endpoint_class') or 'candidate')
            if class_rank.get(proposed, 0) >= class_rank.get(current, 0):
                distinct_ips[key] = proposed
        complete = bool(scope_filtered_items) and all(
            item.get("coverage_complete") and item.get("scope_status") == "resolved"
            and item.get("evidence_status") == "recent" for item in scope_filtered_items
        )
        summary = {
            "discovered_ip_count": len(arp_items),
            "distinct_ip_count": len(distinct_ips),
            "infrastructure_ip_count": sum(value == 'infrastructure' for value in distinct_ips.values()),
            "access_host_ip_count": sum(value == 'access_host' for value in distinct_ips.values()),
            "candidate_ip_count": sum(value == 'candidate' for value in distinct_ips.values()),
            "recent_ip_count": sum(item.get("evidence_status") == "recent" for item in arp_items),
            "mac_only_count": len(mac_items),
            "registered_count": sum(item.get("registration_status") == "registered" for item in arp_items),
            "unregistered_count": sum(item.get("registration_status") == "unregistered" for item in arp_items),
            "scope_pending_count": sum(item.get("scope_status") != "resolved" for item in scope_filtered_items),
            "conflict_count": sum(bool(item.get("ip_mac_conflict")) for item in scope_filtered_items),
            "path_ambiguity_count": sum(bool(item.get("path_ambiguity")) for item in scope_filtered_items),
            "coverage_status": "complete" if complete else "partial" if scope_filtered_items else "unavailable",
            "coverage_reason": "仅使用最新成功的当前 ARP/FDB 上下文行；未成功的最新尝试可能保留上一成功代次。",
            "source_last_success_at": max((str(item.get("last_success_at") or "") for item in visible_items), default=""),
        }
        return {
            "items": filtered_source_items[start:start + safe_page_size],
            "total": len(filtered_source_items), "page": safe_page, "page_size": safe_page_size,
            "has_more": start + safe_page_size < len(filtered_source_items),
            "summary": summary, "sites": site_options, "vrfs": vrf_options,
            "devices": device_options, "network_scope": network_scope,
        }
    finally:
        conn.close()


def get_current_discovered_endpoint(
    observation_id: str, *, visible_scopes: set[tuple[str, str]] | None = None,
) -> dict[str, Any] | None:
    """Return one current ARP/FDB row and its current collection state only."""
    conn = get_db_connection()
    try:
        fdb_items = _current_fdb_endpoint_projection(conn)
        items = [
            *_current_endpoint_projection(conn, observation_source="arp"),
            *_current_endpoint_projection(conn, observation_source="ndp"),
            *fdb_items,
        ]
        if visible_scopes is not None:
            items = [item for item in items if (
                str(item.get('tenant_id') or ''), str(item.get('site_id') or '')
            ) in visible_scopes]
        items = _supersede_older_endpoint_context_observations(items)
        interface_keys, managed_keys, managed_addresses = _current_infrastructure_ip_keys(conn, visible_scopes)
        _classify_current_endpoint_rows(items, fdb_items, interface_keys, managed_keys, managed_addresses)
        matches = [item for item in items if item.get("id") == observation_id]
        if len(matches) != 1:
            return None
        latest = matches[0]
        if latest.get("source_type") == "mac":
            return latest
        observation = {
            "observation_id": latest["id"],
            "source_type": latest["source_type"],
            "observation_source": latest["observation_source"],
            "source_device_id": latest["source_device_id"],
            "source_device_name": latest["source_device_name"],
            "interface_name": latest["source_interface_name"],
            "interface_id": None,
            "vlan": latest["vlan"],
            "ip": latest["ip"],
            "mac": latest["mac"],
            "observed_at": latest["observed_at"],
            "projected_at": "",
            "timestamp_status": latest["timestamp_status"],
            "scope_status": latest["scope_status"],
            "vrf_context_status": latest["vrf_context_status"],
            "coverage_status": latest["coverage_status"],
            "coverage_complete": latest["coverage_complete"],
            "coverage_reason": latest["coverage_reason"],
            "source_run_id": latest["source_run_id"],
            "source_version": latest["source_version"],
            "source_identity_key": latest["source_identity_key"],
        }
        return {**latest, "source_evidence_count": 1, "observations": [observation]}
    finally:
        conn.close()


def register_current_endpoint_observation(
    *, observation_id: str, subnet_id: str, expected_observed_at: str,
    confirmed_scope: bool, requested_by: str, audit_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Register a current host observation against the operator-selected Prefix."""
    if not confirmed_scope:
        raise ValueError("scope_confirmation_required")
    conn = get_db_connection()
    try:
        # Read both scopes without locks first. All writers that can claim an
        # address identity then take the address-space advisory lock before
        # locking Prefix, address space, or address rows.
        current_observations = [
            item for item in [
                *_current_endpoint_projection(conn, observation_source="arp"),
                *_current_endpoint_projection(conn, observation_source="ndp"),
            ]
        ]
        observation_matches = [
            item for item in _supersede_older_endpoint_context_observations(current_observations)
            if item.get("id") == observation_id
        ]
        if not observation_matches:
            raise LookupError("observation_not_current")
        if len(observation_matches) != 1:
            raise ValueError("observation_version_ambiguous")
        pre_displayed = observation_matches[0]
        if pre_displayed.get("source_type") not in {"arp", "ndp"} or not pre_displayed.get("ip"):
            raise ValueError("registration_requires_ip_observation")
        interface_ip_keys, managed_device_ip_keys, managed_device_ips = _current_infrastructure_ip_keys(conn)
        observed_scope_ip = (
            str(pre_displayed.get("tenant_id") or DEFAULT_TENANT_ID),
            str(pre_displayed.get("site_id") or ""),
            str(pre_displayed.get("ip") or ""),
        )
        if (
            observed_scope_ip in interface_ip_keys
            or observed_scope_ip in managed_device_ip_keys
            or (observed_scope_ip[0], observed_scope_ip[2]) in managed_device_ips
            or _is_virtual_gateway_mac(pre_displayed.get("mac"))
        ):
            raise ValueError("infrastructure_address_not_terminal")
        pre_prefix_row = conn.execute(
            """SELECT id, prefix, tenant_id, site_id, vrf_id, address_space_id,
                      status, is_active
                 FROM prefixes WHERE id = ?""",
            (subnet_id,),
        ).fetchone()
        if not pre_prefix_row:
            raise LookupError("subnet_not_found")
        pre_prefix = dict(pre_prefix_row)
        prefix_tenant = str(pre_prefix.get("tenant_id") or DEFAULT_TENANT_ID)
        source_tenant = str(pre_displayed.get("tenant_id") or DEFAULT_TENANT_ID)
        if prefix_tenant != source_tenant:
            raise ValueError("subnet_tenant_does_not_match_source")
        address_space_id = str(pre_prefix.get("address_space_id") or "")
        if not address_space_id:
            raise ValueError("subnet_address_space_required")
        pre_space = conn.execute(
            """SELECT security_tenant_id, status, kind, vrf_id FROM ipam_address_spaces
                 WHERE id = ?""",
            (address_space_id,),
        ).fetchone()
        if not pre_space:
            raise ValueError("subnet_address_space_invalid")
        if (
            str(pre_space["security_tenant_id"] or "") != prefix_tenant
            or str(pre_space["status"] or "") != "active"
        ):
            raise ValueError("subnet_address_space_not_active")
        source_context_status = str(pre_displayed.get("vrf_context_status") or "unknown")
        if source_context_status == "explicit_global" and str(pre_space["kind"] or "") != "global":
            raise ValueError("observation_address_space_mismatch")
        if source_context_status == "explicit_vrf" and (
            str(pre_space["kind"] or "") != "vrf"
            or str(pre_prefix.get("vrf_id") or "") != str(pre_displayed.get("vrf_id") or "")
        ):
            raise ValueError("observation_address_space_mismatch")
        if (
            pre_displayed.get("scope_status") == "resolved"
            and str(pre_displayed.get("address_space_id") or "") != address_space_id
        ):
            raise ValueError("observation_address_space_mismatch")
        try:
            pre_network = ipaddress.ip_network(str(pre_prefix.get("prefix") or ""), strict=False)
            pre_address = ipaddress.ip_address(str(pre_displayed.get("ip") or ""))
        except ValueError as exc:
            raise ValueError("subnet_prefix_invalid") from exc
        if pre_network.version != pre_address.version or pre_address not in pre_network:
            raise ValueError("ip_not_in_subnet")

        from services.ipam_address_space_service import lock_ipam_scope
        lock_ipam_scope(
            conn,
            security_tenant_id=prefix_tenant,
            address_space_id=address_space_id,
            vrf_id=str(pre_prefix.get("vrf_id") or ""),
        )
        prefix_row = conn.execute(
            "SELECT * FROM prefixes WHERE id = ? FOR UPDATE",
            (subnet_id,),
        ).fetchone()
        if not prefix_row:
            raise LookupError("subnet_not_found")
        prefix = dict(prefix_row)
        locked_scope = (
            str(prefix.get("tenant_id") or DEFAULT_TENANT_ID),
            str(prefix.get("site_id") or ""),
            str(prefix.get("vrf_id") or ""),
            str(prefix.get("address_space_id") or ""),
        )
        pre_scope = (
            prefix_tenant,
            str(pre_prefix.get("site_id") or ""),
            str(pre_prefix.get("vrf_id") or ""),
            address_space_id,
        )
        if locked_scope != pre_scope:
            raise ValueError("subnet_scope_changed")
        if str(prefix.get("status") or "active") != "active" or prefix.get("is_active") in (False, 0):
            raise ValueError("subnet_not_active")
        space_row = conn.execute(
            """SELECT security_tenant_id, status FROM ipam_address_spaces
                 WHERE id = ? FOR SHARE""",
            (address_space_id,),
        ).fetchone()
        if (
            not space_row
            or str(space_row["security_tenant_id"] or "") != prefix_tenant
            or str(space_row["status"] or "") != "active"
        ):
            raise ValueError("subnet_address_space_not_active")

        displayed, current = _current_endpoint_is_current(conn, observation_id)
        latest_observations = _supersede_older_endpoint_context_observations([
            *_current_endpoint_projection(conn, observation_source="arp"),
            *_current_endpoint_projection(conn, observation_source="ndp"),
        ])
        if not any(item.get("id") == observation_id for item in latest_observations):
            raise ValueError("observation_not_current")
        if (
            displayed.get("scope_status") == "resolved"
            and str(displayed.get("address_space_id") or "") != address_space_id
        ):
            raise ValueError("observation_address_space_mismatch")
        if str(displayed.get("tenant_id") or DEFAULT_TENANT_ID) != prefix_tenant:
            raise ValueError("subnet_tenant_does_not_match_source")
        observed_at, observed_state = _parse_time(displayed.get("observed_at"))
        expected_at, expected_state = _parse_time(expected_observed_at)
        if observed_state != "valid" or expected_state != "valid" or observed_at != expected_at:
            raise ValueError("observation_version_changed")
        if _utc_now() - observed_at > timedelta(minutes=_recent_minutes()):
            raise ValueError("observation_not_current")
        device = conn.execute(
            """SELECT id, COALESCE(NULLIF(btrim(tenant_id), ''), ?) AS tenant_id,
                      COALESCE(site_id, '') AS site_id, hostname
                 FROM devices WHERE id = ? FOR SHARE""",
            (DEFAULT_TENANT_ID, displayed["source_device_id"]),
        ).fetchone()
        if not device:
            raise LookupError("source_device_not_found")
        if str(device["tenant_id"] or DEFAULT_TENANT_ID) != prefix_tenant:
            raise ValueError("subnet_tenant_does_not_match_source")
        device_tenant = str(device["tenant_id"] or DEFAULT_TENANT_ID)
        try:
            network = ipaddress.ip_network(str(prefix.get("prefix") or ""), strict=False)
            address = ipaddress.ip_address(str(displayed.get("ip") or ""))
        except ValueError as exc:
            raise ValueError("subnet_prefix_invalid") from exc
        if network.version != address.version or address not in network:
            raise ValueError("ip_not_in_subnet")

        from services.ipam_service import _create_address_with_conn
        source_note = "当前 ARP 观察经操作者确认登记；主机归属待核实。"
        source_device_name = str(device["hostname"] or device["id"] or "")
        source_interface = str(displayed.get("source_interface_name") or "")
        if source_device_name or source_interface:
            source_note += f" 来源设备/接口：{source_device_name} {source_interface}".strip()
        address_result = _create_address_with_conn(
            conn, subnet_id, address=str(address), hostname="", device_id="", interface_name="",
            mac_address=_normalized_mac(displayed.get("mac")) or "", device_type="",
            description=source_note, status="active", lock_prefix=False,
            requested_by=requested_by, source_type="ipam_current_endpoint",
            source_ref=observation_id,
        )
        audit_values = dict(audit_context or {})
        from services.audit_service import log_audit_event
        log_audit_event(
            event_type="ipam.discovery.register", category="ipam", severity="info", status="success",
            summary=f"Registered current endpoint {address} in explicit Prefix {subnet_id}",
            target_type="ip_address", target_id=address_result.get("id"), target_name=subnet_id,
            before={"registration_status": "unregistered"},
            after={"registration_status": "registered", "address": str(address), "subnet_id": subnet_id},
            details={
                "current_observation_id": observation_id,
                "generation": int(current["generation"]),
                "explicit_prefix_selection": True,
                "source_context_resolution": displayed.get("scope_status"),
            },
            conn=conn, **audit_values,
        )
        conn.commit()
        return {
            "ok": True,
            "ipam_address_id": str(address_result.get("id") or ""),
            "observation_id": observation_id,
            "created": not bool(address_result.get("reused")),
            "assertion_id": "",
            "scope": {
                "tenant_id": prefix_tenant, "site_id": str(prefix.get("site_id") or ""),
                "vrf_id": str(prefix.get("vrf_id") or ""), "subnet_id": subnet_id,
            },
            "source_scope": {
                "tenant_id": device_tenant, "site_id": str(device["site_id"] or ""),
                "vrf_id": str(displayed.get("vrf_id") or ""),
                "address_space_id": displayed.get("address_space_id"),
                "context_status": displayed.get("scope_status"),
            },
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def calibrate_current_endpoint_mac(
    *, observation_id: str, ipam_address_id: str, expected_observed_at: str,
    expected_mac_address: str, confirmed: bool, audit_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calibrate an IPAM MAC from one unique, resolved current ARP/ND row in the same space."""
    if not confirmed:
        raise ValueError("mac_calibration_confirmation_required")
    conn = get_db_connection()
    try:
        observation_matches = [
            item for item in [
                *_current_endpoint_projection(conn, observation_source="arp"),
                *_current_endpoint_projection(conn, observation_source="ndp"),
            ]
            if item.get("id") == observation_id
        ]
        if not observation_matches:
            raise LookupError("observation_not_current")
        if len(observation_matches) != 1:
            raise ValueError("observation_version_ambiguous")
        pre_displayed = observation_matches[0]
        if not pre_displayed.get("address_space_id") or pre_displayed.get("scope_status") != "resolved":
            raise ValueError("observation_not_calibration_safe")
        pre_address_row = conn.execute(
            """SELECT ip.id, ip.address, ip.address_inet, ip.address_space_id,
                      ip.status, prefix.id AS prefix_id,
                      prefix.tenant_id AS prefix_tenant_id,
                      prefix.site_id AS prefix_site_id, prefix.vrf_id AS prefix_vrf_id,
                      prefix.address_space_id AS prefix_address_space_id,
                      prefix.status AS prefix_status, prefix.is_active AS prefix_is_active
                 FROM ip_addresses ip
                 JOIN prefixes prefix ON prefix.id = ip.subnet_id
                WHERE ip.id = ?""",
            (ipam_address_id,),
        ).fetchone()
        if not pre_address_row:
            raise LookupError("ipam_address_not_found")
        pre_address = dict(pre_address_row)
        prefix_address_space_id = str(pre_address.get("prefix_address_space_id") or "")
        address_field_space_id = str(pre_address.get("address_space_id") or "")
        address_space_id = prefix_address_space_id
        tenant_id = str(pre_address.get("prefix_tenant_id") or DEFAULT_TENANT_ID)
        prefix_vrf_id = str(pre_address.get("prefix_vrf_id") or "")
        if (
            not address_space_id
            or (address_field_space_id and address_field_space_id != prefix_address_space_id)
            or address_space_id != str(pre_displayed.get("address_space_id") or "")
            or tenant_id != str(pre_displayed.get("tenant_id") or "")
            or _normalized_ip(pre_address.get("address_inet") or pre_address.get("address")) != str(pre_displayed.get("ip") or "")
        ):
            raise ValueError("observation_scope_does_not_match_ipam")
        pre_space = conn.execute(
            "SELECT security_tenant_id, status FROM ipam_address_spaces WHERE id = ?",
            (address_space_id,),
        ).fetchone()
        if (
            not address_space_id or not pre_space
            or str(pre_space["security_tenant_id"] or "") != tenant_id
            or str(pre_space["status"] or "") != "active"
        ):
            raise ValueError("observation_scope_does_not_match_ipam")
        if str(pre_address.get("prefix_status") or "active") != "active" or pre_address.get("prefix_is_active") in (False, 0):
            raise ValueError("ipam_address_not_active")

        from services.ipam_address_space_service import lock_ipam_scope
        lock_ipam_scope(
            conn,
            security_tenant_id=tenant_id,
            address_space_id=address_space_id,
            vrf_id=prefix_vrf_id,
        )
        prefix_row = conn.execute(
            "SELECT * FROM prefixes WHERE id = ? FOR UPDATE",
            (str(pre_address["prefix_id"]),),
        ).fetchone()
        if not prefix_row:
            raise LookupError("ipam_prefix_not_found")
        prefix = dict(prefix_row)
        locked_prefix_scope = (
            str(prefix.get("tenant_id") or DEFAULT_TENANT_ID),
            str(prefix.get("site_id") or ""),
            str(prefix.get("vrf_id") or ""),
            str(prefix.get("address_space_id") or ""),
        )
        pre_prefix_scope = (
            tenant_id,
            str(pre_address.get("prefix_site_id") or ""),
            prefix_vrf_id,
            str(pre_address.get("prefix_address_space_id") or ""),
        )
        if locked_prefix_scope != pre_prefix_scope or str(prefix.get("status") or "active") != "active" or prefix.get("is_active") in (False, 0):
            raise ValueError("ipam_scope_changed")
        space_row = conn.execute(
            """SELECT security_tenant_id, status FROM ipam_address_spaces
                 WHERE id = ? FOR SHARE""",
            (address_space_id,),
        ).fetchone()
        if (
            not space_row
            or str(space_row["security_tenant_id"] or "") != tenant_id
            or str(space_row["status"] or "") != "active"
        ):
            raise ValueError("observation_scope_does_not_match_ipam")
        address_row = conn.execute(
            "SELECT * FROM ip_addresses WHERE id = ? FOR UPDATE",
            (ipam_address_id,),
        ).fetchone()
        if not address_row:
            raise LookupError("ipam_address_not_found")
        address = dict(address_row)
        locked_address_space_id = str(address.get("address_space_id") or prefix.get("address_space_id") or "")
        if (
            locked_address_space_id != address_space_id
            or (address.get("address_space_id") and str(address.get("address_space_id")) != str(prefix.get("address_space_id") or ""))
            or (address.get("tenant_id") and str(address.get("tenant_id")) != tenant_id)
        ):
            raise ValueError("ipam_scope_changed")
        if str(address.get("status") or "active") in {"released", "available"}:
            raise ValueError("ipam_address_not_active")

        displayed, current = _current_endpoint_is_current(conn, observation_id)
        if (
            displayed.get("scope_status") != "resolved"
            or str(displayed.get("address_space_id") or "") != address_space_id
            or str(displayed.get("tenant_id") or "") != tenant_id
        ):
            raise ValueError("observation_scope_does_not_match_ipam")
        observed_at, observed_state = _parse_time(displayed.get("observed_at"))
        expected_at, expected_state = _parse_time(expected_observed_at)
        if observed_state != "valid" or expected_state != "valid" or observed_at != expected_at:
            raise ValueError("observation_version_changed")
        if _utc_now() - observed_at > timedelta(minutes=_recent_minutes()):
            raise ValueError("observation_not_current")

        current_rows = [
            *_current_endpoint_projection(conn, observation_source="arp"),
            *_current_endpoint_projection(conn, observation_source="ndp"),
        ]
        same_scope_ip = [
            item for item in current_rows
            if str(item.get("tenant_id") or "") == tenant_id
            and str(item.get("address_space_id") or "") == address_space_id
            and str(item.get("ip") or "") == str(displayed.get("ip") or "")
            and item.get("scope_status") == "resolved"
        ]
        if len(same_scope_ip) != 1 or same_scope_ip[0].get("id") != observation_id:
            raise ValueError("observation_not_unique_in_address_space")

        if _normalized_ip(address.get("address_inet") or address.get("address")) != str(displayed.get("ip") or ""):
            raise ValueError("observation_scope_does_not_match_ipam")
        current_mac = _normalized_mac(address.get("mac_address"))
        expected_mac = _normalized_mac(expected_mac_address)
        observed_mac = _normalized_mac(displayed.get("observed_mac"))
        if current_mac != expected_mac:
            raise ValueError("ipam_mac_version_changed")
        if not observed_mac or observed_mac == current_mac:
            raise ValueError("mac_calibration_not_required")
        updated_at = _iso(_utc_now()) or _utc_now().isoformat()
        conn.execute(
            "UPDATE ip_addresses SET mac_address = ?, updated_at = ?, revision = revision + 1 WHERE id = ?",
            (observed_mac, updated_at, ipam_address_id),
        )
        audit_values = dict(audit_context or {})
        from services.audit_service import log_audit_event
        log_audit_event(
            event_type="ipam.discovery.mac_calibrate", category="ipam", severity="warning", status="success",
            summary=f"Calibrated IPAM MAC for address {ipam_address_id}",
            target_type="ip_address", target_id=ipam_address_id,
            before={"mac_address": current_mac},
            after={"mac_address": observed_mac, "current_observation_id": observation_id},
            details={
                "confirmed": True, "observed_at": displayed.get("observed_at"),
                "address_space_id": address_space_id, "generation": int(current["generation"]),
            },
            conn=conn, **audit_values,
        )
        conn.commit()
        return {
            "ok": True, "ipam_address_id": ipam_address_id,
            "observation_id": observation_id, "previous_mac": current_mac,
            "mac": observed_mac, "observed_at": displayed.get("observed_at"),
            "scope": {
                "tenant_id": tenant_id,
                "site_id": str(prefix.get("site_id") or ""),
                "vrf_id": str(prefix.get("vrf_id") or ""),
                "address_space_id": address_space_id,
            },
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _current_routing_context_mappings(conn) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Load only explicit active device-local mappings for endpoint context keys."""
    rows = conn.execute(
        """SELECT context.device_id, context.context_source, context.context_type,
                  context.local_context_key, context.address_space_id,
                  COALESCE(NULLIF(btrim(device.tenant_id), ''), 'tenant-default') AS device_tenant_id,
                  space.security_tenant_id, space.kind AS address_space_kind,
                  space.vrf_id, space.status AS address_space_status
             FROM ipam_device_routing_contexts AS context
             JOIN devices AS device ON device.id = context.device_id
             JOIN ipam_address_spaces AS space ON space.id = context.address_space_id
            WHERE context.status = 'active' AND space.status = 'active'
            ORDER BY context.device_id, context.local_context_key, context.context_source"""
    ).fetchall()
    mappings: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        item = dict(row)
        if str(item.get('security_tenant_id') or '') != str(item.get('device_tenant_id') or ''):
            continue
        context_type = str(item.get('context_type') or '')
        expected_kind = 'vrf' if context_type == 'vrf' else 'global' if context_type == 'global' else ''
        if not expected_kind or str(item.get('address_space_kind') or '') != expected_kind:
            continue
        key = (str(item.get('device_id') or ''), str(item.get('local_context_key') or ''))
        mappings.setdefault(key, []).append(item)
    return mappings


def _current_arp_collection_state(
    conn,
    *,
    devices: dict[str, dict[str, Any]],
    scope_visible,
) -> dict[str, Any]:
    """Return only the latest sweep and each device's current result row."""
    status_rows = conn.execute(
        """SELECT status.device_id, status.status, status.source,
                  status.last_attempt_at, status.last_success_at,
                  status.coverage_total, status.coverage_supported, status.metadata_json
             FROM device_collection_status AS status
            WHERE status.collector = 'arp'
            ORDER BY status.device_id"""
    ).fetchall()
    status_by_device = {str(row['device_id']): dict(row) for row in status_rows}
    sweep_row = conn.execute(
        "SELECT * FROM collector_sweep_state WHERE collector = 'arp'"
    ).fetchone()
    sweep = dict(sweep_row) if sweep_row else {}
    run_id = str(sweep.get('last_run_id') or '').strip()
    current_by_device: dict[str, dict[str, Any]] = {}
    for device_id, status in status_by_device.items():
        metadata = _json_object(status.get('metadata_json'))
        if run_id and str(metadata.get('collection_run_id') or '').strip() == run_id:
            current_by_device[device_id] = {**status, '_metadata': metadata}

    try:
        eligible = int(sweep.get('last_eligible') or 0)
        selected = int(sweep.get('last_selected') or 0)
        successful = int(sweep.get('last_successful') or 0)
        failed = int(sweep.get('last_failed') or 0)
        collected = int(sweep.get('last_collected') or 0)
    except (TypeError, ValueError):
        eligible = selected = successful = failed = collected = 0
    started_at, started_state = _parse_time(sweep.get('last_started_at'))
    completed_at, completed_state = _parse_time(sweep.get('last_completed_at'))

    def result_is_complete(status: dict[str, Any]) -> bool:
        metadata = status.get('_metadata') or {}
        try:
            coverage_total = int(status.get('coverage_total') or 0)
            entry_count = int(metadata.get('entry_count'))
            coverage_supported = int(status.get('coverage_supported') or 0)
        except (TypeError, ValueError):
            return False
        attempted_at, attempted_state = _parse_time(status.get('last_attempt_at'))
        success_at, success_state = _parse_time(status.get('last_success_at'))
        return bool(
            status.get('status') == 'success'
            and str(status.get('source') or '') == 'arp_sweep'
            and coverage_supported > 0
            and entry_count == coverage_total
            and attempted_state == success_state == 'valid'
            and attempted_at and success_at and attempted_at == success_at
            and started_state == completed_state == 'valid'
            and started_at and completed_at
            and started_at <= attempted_at <= success_at <= completed_at
        )

    all_results_complete = bool(current_by_device) and all(
        result_is_complete(status) for status in current_by_device.values()
    )
    valid_current_by_device = {
        device_id: status
        for device_id, status in current_by_device.items()
        if result_is_complete(status)
    }
    expected_status_count = selected
    visible_status_set = all(
        scope_visible(
            devices.get(device_id, {}).get('tenant_id'),
            devices.get(device_id, {}).get('site_id'),
        )
        for device_id in current_by_device
    )
    complete = bool(
        run_id and eligible > 0 and selected == eligible
        and successful == selected and failed == 0
        and expected_status_count == len(current_by_device)
        and all_results_complete and visible_status_set
        and started_state == completed_state == 'valid'
        and started_at and completed_at and completed_at >= started_at
        and sum(int(status.get('coverage_total') or 0) for status in current_by_device.values()) == collected
    )
    return {
        'sweep': sweep,
        'run_id': run_id,
        'status_by_device': status_by_device,
        'current_by_device': current_by_device,
        'valid_current_by_device': valid_current_by_device,
        'complete': complete,
        'started_at': started_at,
        'completed_at': completed_at,
        'eligible': eligible,
        'selected': selected,
        'successful': successful,
        'failed': failed,
        'collected': collected,
    }


def _reconciliation_ipam_status(item: dict[str, Any]) -> str:
    return str(item.get("status") or "active").strip().lower()


def _reconciliation_address_is_stale_eligible(item: dict[str, Any]) -> bool:
    roles = (
        item.get("purpose"), item.get("device_type"), item.get("network_type"),
        item.get("interface_type"), item.get("linked_interface_role"),
    )
    if any(str(value or "").strip().lower() in {"loopback", "vip", "virtual", "virtual_ip", "virtual-ip", "virtual ip"} for value in roles):
        return False
    interface_name = str(item.get("interface_name") or "").strip().lower()
    return not interface_name.startswith("loopback") and not (interface_name.startswith("lo") and not interface_name.startswith("local"))


def build_ipam_reconciliation(
    conn, *, active_tab: str = "", q: str = "", page: int | None = None,
    page_size: int = 20, visible_scopes: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Build from current IPAM, endpoint, CMDB and collector state only.

    Discovery-ledger observations and snapshots remain available to the
    discovery endpoints, but this current-state page never reads them.
    """
    now = _utc_now()
    from services.ipam_inventory_scope import load_inventory_catalog, match_inventory_prefix
    from services.ipam_service import _current_cmdb_interface_ip_observations
    from services.ipam_current_endpoint_observation_service import (
        get_current_endpoint_collection_states,
        list_current_endpoint_observations,
    )
    from core.interface_utils import normalize_interface_name

    prefix_catalog, _prefix_sites, _prefix_vrfs = load_inventory_catalog(conn)
    _ipam_by_scope, ipam_records = _ipam_address_index(conn)
    devices, sites, vrfs = _device_catalog(conn)
    address_spaces = {
        str(row["id"]): dict(row)
        for row in conn.execute(
            """SELECT id, security_tenant_id, kind, vrf_id, status
                 FROM ipam_address_spaces"""
        ).fetchall()
    }

    def scope_visible(tenant_id: Any, site_id: Any) -> bool:
        if visible_scopes is None:
            return True
        return (str(tenant_id or ""), str(site_id or "")) in visible_scopes

    ipam_records = [
        item for item in ipam_records
        if scope_visible(item.get("_tenant_id"), item.get("_site_id"))
    ]
    allocated_records = [
        item for item in ipam_records
        if _reconciliation_ipam_status(item) not in {"available", "released"}
    ]
    ipam_by_space_ip: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    all_ipam_by_space_ip: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for item in ipam_records:
        space_id = str(item.get("_address_space_id") or "")
        if not space_id:
            continue
        key = (
            str(item.get("_tenant_id") or ""),
            space_id,
            str(item.get("_address") or ""),
        )
        all_ipam_by_space_ip.setdefault(key, []).append(item)
        if not item.get("_scope_conflict"):
            ipam_by_space_ip.setdefault(key, []).append(item)

    context_mappings = _current_routing_context_mappings(conn)
    collection_state = _current_arp_collection_state(
        conn, devices=devices, scope_visible=scope_visible,
    )
    source_set_known = bool(collection_state["complete"])
    current_run_id = str(collection_state["run_id"] or "")
    last_checked_at = _iso(collection_state["completed_at"]) if collection_state["completed_at"] else ""
    valid_current_by_device = collection_state["valid_current_by_device"]

    def scope_for_device(device_id: str, address_space_id: str = "") -> dict[str, Any]:
        device = devices.get(str(device_id or ""))
        if not device:
            return {
                "tenant_id": "", "site_id": "", "vrf_id": "",
                "scope_status": "scope_pending", "reason": "source_device_not_found",
            }
        resolved = _resolve_device_scope(device, sites, vrfs)
        tenant_id = str(resolved.get("tenant_id") or "")
        site_id = str(resolved.get("site_id") or "")
        if resolved.get("scope_status") == "conflict":
            return {**resolved, "reason": "source_device_scope_conflict"}
        if not tenant_id or not site_id:
            return {**resolved, "scope_status": "scope_pending", "reason": "source_device_scope_missing"}
        space = address_spaces.get(str(address_space_id or ""))
        if (
            not space
            or str(space.get("status") or "") != "active"
            or str(space.get("security_tenant_id") or "") != tenant_id
        ):
            return {**resolved, "scope_status": "scope_pending", "reason": "address_space_mapping_missing"}
        return {
            **resolved,
            "tenant_id": tenant_id,
            "site_id": site_id,
            "vrf_id": str(space.get("vrf_id") or ""),
            "address_space_id": str(address_space_id),
            "scope_status": "resolved",
            "reason": "",
        }

    def endpoint_scope(endpoint: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
        device_id = str(endpoint.get("switch_id") or "")
        device = devices.get(device_id)
        if not device:
            return scope_for_device(device_id), "", "source_device_not_found"
        base = _resolve_device_scope(device, sites, vrfs)
        if base.get("scope_status") == "conflict":
            return base, "", "source_device_scope_conflict"
        # network_endpoints stores a local VRF key only. Resolve it solely by
        # an exact active device-local mapping; never by VRF display names or aliases.
        local_key = str(endpoint.get("vrf") or "").strip()
        if not local_key:
            return {**base, "scope_status": "scope_pending"}, "", "routing_context_mapping_missing"
        candidates = context_mappings.get((device_id, local_key), [])
        identities = {
            (str(row.get("address_space_id") or ""), str(row.get("context_type") or ""))
            for row in candidates
        }
        if len(identities) != 1:
            reason = "routing_context_mapping_ambiguous" if identities else "routing_context_mapping_missing"
            return {**base, "scope_status": "scope_pending"}, "", reason
        address_space_id, context_type = next(iter(identities))
        resolved = scope_for_device(device_id, address_space_id)
        if resolved.get("scope_status") != "resolved":
            return resolved, "", str(resolved.get("reason") or "routing_context_mapping_invalid")
        return resolved, context_type, ""

    def endpoint_source_identity(source: dict[str, Any]) -> tuple[str, ...]:
        """Deduplicate only the same source position within one explicit scope."""
        normalized_interface = normalize_interface_name(str(source.get("interface_name") or ""))
        return (
            str(source.get("tenant_id") or ""),
            str(source.get("site_id") or ""),
            str(source.get("address_space_id") or ""),
            str(source.get("ip") or ""),
            _normalized_mac(source.get("mac")),
            str(source.get("vlan") or ""),
            str(source.get("source_device_id") or ""),
            normalized_interface.strip().lower(),
            str(source.get("local_context_key") or ""),
        )

    unscoped: dict[tuple[Any, ...], dict[str, Any]] = {}
    unresolved_by_tenant_ip: set[tuple[str, str]] = set()
    unresolved_by_tenant_site_ip: set[tuple[str, str, str]] = set()

    def add_unscoped(item: dict[str, Any], *, reason: str, source_kind: str) -> None:
        record = {
            **item,
            "kind": source_kind,
            "reason": reason,
            "scope_status": str(item.get("scope_status") or "scope_pending"),
            "address_space_id": str(item.get("address_space_id") or ""),
        }
        identity = (source_kind, record.get("id"), record.get("ip"), reason)
        unscoped[identity] = record
        tenant_id = str(record.get("tenant_id") or "")
        site_id = str(record.get("site_id") or "")
        ip = str(record.get("ip") or "")
        if tenant_id and ip:
            unresolved_by_tenant_ip.add((tenant_id, ip))
            if site_id:
                unresolved_by_tenant_site_ip.add((tenant_id, site_id, ip))

    active_endpoint_rows = conn.execute(
        """SELECT id, ip, mac, hostname, switch_id, switch_port, vlan, vrf, site,
                  source_type, first_seen, last_seen, is_active
             FROM network_endpoints
            WHERE is_active = 1
            ORDER BY ip, id"""
    ).fetchall()
    active_endpoint_count = 0
    endpoint_times: list[datetime] = []
    recent_endpoint_times: list[datetime] = []
    endpoint_count_identities: set[tuple[str, ...]] = set()
    current_endpoint_sources: list[dict[str, Any]] = []
    for raw in active_endpoint_rows:
        endpoint = dict(raw)
        if str(endpoint.get("source_type") or "arp").strip().lower() != "arp":
            continue
        ip = _normalized_ip(endpoint.get("ip"))
        if not ip:
            continue
        observed_at, time_state = _parse_time(endpoint.get("last_seen"))
        recent = bool(
            observed_at and time_state == "valid"
            and observed_at <= now and now - observed_at <= timedelta(minutes=_recent_minutes())
        )

        resolved, context_type, reason = endpoint_scope(endpoint)
        device_id = str(endpoint.get("switch_id") or "")
        device = devices.get(device_id) or {}
        source = {
            "id": str(endpoint.get("id") or ""),
            "ip": ip,
            "address": ip,
            "mac": _normalized_mac(endpoint.get("mac")),
            "mac_address": _normalized_mac(endpoint.get("mac")),
            "hostname": str(endpoint.get("hostname") or ""),
            "device_id": device_id,
            "source_device_id": device_id,
            "source_device_name": str(device.get("hostname") or device_id),
            "device_name": str(device.get("hostname") or endpoint.get("hostname") or device_id),
            "interface_name": str(endpoint.get("switch_port") or ""),
            "vlan": str(endpoint.get("vlan") or ""),
            "vrf": str(endpoint.get("vrf") or ""),
            "site_id": str(resolved.get("site_id") or ""),
            "site_name": str(sites.get(str(resolved.get("site_id") or ""), {}).get("site_name") or ""),
            "tenant_id": str(resolved.get("tenant_id") or ""),
            "vrf_id": str(resolved.get("vrf_id") or ""),
            "address_space_id": str(resolved.get("address_space_id") or ""),
            "scope_status": str(resolved.get("scope_status") or "scope_pending"),
            "observed_at": str(endpoint.get("last_seen") or ""),
            "evidence_status": "recent" if recent else "outside_current_window",
            "context_source": "arp",
            "context_type": context_type or "unknown",
            "local_context_key": str(endpoint.get("vrf") or ""),
            "source_kind": "network_endpoint",
        }
        if not scope_visible(source["tenant_id"], source["site_id"]):
            continue
        if observed_at and time_state == "valid":
            endpoint_times.append(observed_at)
        if recent:
            source_identity = endpoint_source_identity(source)
            if source_identity not in endpoint_count_identities:
                endpoint_count_identities.add(source_identity)
                active_endpoint_count += 1
                recent_endpoint_times.append(observed_at)
        if source["scope_status"] != "resolved":
            add_unscoped(source, reason=reason or "source_scope_unresolved", source_kind="network_endpoint")
            continue
        if recent:
            current_endpoint_sources.append(source)

    current_neighbor_rows = [
        *list_current_endpoint_observations(conn, observation_source="arp"),
        *list_current_endpoint_observations(conn, observation_source="ndp"),
    ]
    current_neighbor_sources: list[dict[str, Any]] = []
    current_neighbor_coverage_incomplete = False
    current_neighbor_visible_count = 0
    current_neighbor_last_success_times: list[datetime] = []
    for raw in current_neighbor_rows:
        observation = dict(raw)
        observation_source = str(observation.get("observation_source") or "arp")
        source_kind = f"current_{observation_source}"
        ip = _normalized_ip(observation.get("ip_address"))
        if not ip:
            continue
        device_id = str(observation.get("source_device_id") or "")
        device = devices.get(device_id) or {}
        base_scope = _resolve_device_scope(device, sites, vrfs) if device else {
            "tenant_id": "", "site_id": "", "scope_status": "scope_pending",
        }
        tenant_id = str(base_scope.get("tenant_id") or observation.get("tenant_id") or "")
        site_id = str(
            observation.get("asset_site_id") or observation.get("device_site_id")
            or base_scope.get("site_id") or ""
        )
        if not scope_visible(tenant_id, site_id):
            continue
        current_neighbor_visible_count += 1
        last_success_time, last_success_time_state = _parse_time(observation.get("last_success_at"))
        if last_success_time and last_success_time_state == "valid":
            current_neighbor_last_success_times.append(last_success_time)

        observed_at = observation.get("observed_at")
        observed_time, time_state = _parse_time(observed_at)
        if observed_time and time_state == "valid":
            endpoint_times.append(observed_time)
        recent = bool(
            observed_time and time_state == "valid" and observed_time <= now
            and now - observed_time <= timedelta(minutes=_recent_minutes())
        )

        address_space_id = str(observation.get("address_space_id") or "")
        resolved = scope_for_device(device_id, address_space_id) if address_space_id else {
            **base_scope, "scope_status": "scope_pending", "reason": "routing_context_mapping_missing",
        }
        context_type = str(observation.get("resolved_context_type") or "")
        if resolved.get("scope_status") != "resolved":
            unresolved = {
                "id": _current_endpoint_observation_id(observation),
                "ip": ip, "address": ip,
                "mac": _normalized_mac(observation.get("mac_address")),
                "mac_address": _normalized_mac(observation.get("mac_address")),
                "hostname": str(observation.get("source_device_name") or device.get("hostname") or ""),
                "device_id": device_id, "source_device_id": device_id,
                "source_device_name": str(observation.get("source_device_name") or device.get("hostname") or device_id),
                "device_name": str(observation.get("source_device_name") or device.get("hostname") or device_id),
                "interface_name": str(observation.get("interface_name") or ""),
                "vlan": str(observation.get("vlan_id") or ""),
                "vrf": str(observation.get("local_context_key") or ""),
                "site_id": site_id, "site_name": str(sites.get(site_id, {}).get("site_name") or ""),
                "tenant_id": tenant_id,
                "vrf_id": "", "address_space_id": "",
                "scope_status": "scope_pending",
                "observed_at": str(observed_at or ""),
                "evidence_status": f"current_successful_{observation_source}_observation",
                "context_source": str(observation.get("context_source") or ""),
                "context_type": str(observation.get("context_type") or "unknown"),
                "local_context_key": str(observation.get("local_context_key") or ""),
                "generation": int(observation.get("generation") or 0),
                "source_kind": source_kind,
            }
            reason = str(resolved.get("reason") or "routing_context_mapping_missing")
            if not address_space_id and device_id and unresolved["local_context_key"]:
                candidates = [
                    item for item in context_mappings.get((device_id, unresolved["local_context_key"]), [])
                    if str(item.get("context_source") or "") == unresolved["context_source"]
                ]
                identities = {
                    (str(item.get("address_space_id") or ""), str(item.get("context_type") or ""))
                    for item in candidates
                }
                if len(identities) > 1:
                    reason = "routing_context_mapping_ambiguous"
                elif identities:
                    reason = "routing_context_mapping_invalid"
            add_unscoped(unresolved, reason=reason, source_kind=source_kind)
            continue

        space_id = str(resolved.get("address_space_id") or "")
        current_status = str(observation.get("latest_status") or "")
        latest_success_is_current_attempt = (
            int(observation.get("latest_attempt_generation") or 0)
            == int(observation.get("last_success_generation") or 0)
            and current_status in {"complete", "scope_unknown"}
        )
        if not latest_success_is_current_attempt:
            current_neighbor_coverage_incomplete = True
        source = {
            "id": _current_endpoint_observation_id(observation),
            "ip": ip, "address": ip,
            "mac": _normalized_mac(observation.get("mac_address")),
            "mac_address": _normalized_mac(observation.get("mac_address")),
            "hostname": str(observation.get("source_device_name") or device.get("hostname") or ""),
            "device_id": device_id, "source_device_id": device_id,
            "source_device_name": str(observation.get("source_device_name") or device.get("hostname") or device_id),
            "device_name": str(observation.get("source_device_name") or device.get("hostname") or device_id),
            "interface_name": str(observation.get("interface_name") or ""),
            "vlan": str(observation.get("vlan_id") or ""),
            "vrf": str(observation.get("local_context_key") or ""),
            "site_id": site_id,
            "site_name": str(sites.get(site_id, {}).get("site_name") or ""),
            "tenant_id": tenant_id,
            "vrf_id": str(resolved.get("vrf_id") or ""),
            "address_space_id": space_id,
            "scope_status": "resolved",
            "observed_at": str(observed_at or ""),
            "evidence_status": "recent" if recent else "outside_recent_window",
            "context_source": str(observation.get("context_source") or ""),
            "context_type": context_type or "unknown",
            "local_context_key": str(observation.get("local_context_key") or ""),
            "generation": int(observation.get("generation") or 0),
            "last_success_at": str(observation.get("last_success_at") or ""),
            "collection_status": current_status,
            "coverage_complete": latest_success_is_current_attempt,
            "source_kind": source_kind,
        }
        identity = endpoint_source_identity(source)
        if recent and identity not in endpoint_count_identities:
            endpoint_count_identities.add(identity)
            active_endpoint_count += 1
            recent_endpoint_times.append(observed_time)
        current_neighbor_sources.append(source)

    current_neighbor_states = [
        *get_current_endpoint_collection_states(conn, observation_source="arp"),
        *get_current_endpoint_collection_states(conn, observation_source="ndp"),
    ]
    for state in current_neighbor_states:
        latest_status = str(state.get("latest_status") or "")
        latest_attempt_generation = int(state.get("latest_attempt_generation") or 0)
        last_success_generation = int(state.get("last_success_generation") or 0)
        if latest_status != "complete" or latest_attempt_generation != last_success_generation:
            current_neighbor_coverage_incomplete = True
        last_success_time, last_success_time_state = _parse_time(state.get("last_success_at"))
        if last_success_time and last_success_time_state == "valid":
            current_neighbor_last_success_times.append(last_success_time)

    current_neighbor_identities = {endpoint_source_identity(item) for item in current_neighbor_sources}
    current_endpoint_sources = [
        item for item in current_endpoint_sources
        if endpoint_source_identity(item) not in current_neighbor_identities
    ] + current_neighbor_sources

    current_interface_rows = _current_cmdb_interface_ip_observations(conn)
    interface_snapshot_ip_count = 0
    current_interface_sources: list[dict[str, Any]] = []
    for raw in current_interface_rows:
        interface = dict(raw)
        ip = _normalized_ip(interface.get("ip_address"))
        if not ip:
            continue
        device_id = str(interface.get("device_id") or "")
        device = devices.get(device_id) or {}
        base_scope = _resolve_device_scope(device, sites, vrfs) if device else {
            "tenant_id": "", "site_id": "", "scope_status": "scope_pending",
        }
        tenant_id = str(base_scope.get("tenant_id") or interface.get("tenant_id") or "")
        site_id = str(
            interface.get("asset_site_id") or interface.get("device_site_id")
            or base_scope.get("site_id") or ""
        )
        if not scope_visible(tenant_id, site_id):
            continue
        interface_snapshot_ip_count += 1
        address_space_id = str(interface.get("address_space_id") or "")
        space = address_spaces.get(address_space_id) if address_space_id else None
        if (
            base_scope.get("scope_status") == "conflict"
            or not tenant_id or not site_id
            or not space or str(space.get("status") or "") != "active"
            or str(space.get("security_tenant_id") or "") != tenant_id
        ):
            add_unscoped({
                "id": f"interface:{device_id}:{interface.get('normalized_interface_name') or ''}:{ip}",
                "ip": ip, "address": ip,
                "device_id": device_id, "source_device_id": device_id,
                "source_device_name": str(interface.get("device_hostname") or device_id),
                "device_name": str(interface.get("device_hostname") or device_id),
                "interface_name": str(interface.get("interface_name") or ""),
                "tenant_id": tenant_id, "site_id": site_id,
                "site_name": str(sites.get(site_id, {}).get("site_name") or ""),
                "address_space_id": "",
                "context_source": str(interface.get("context_source") or ""),
                "context_type": str(interface.get("context_type") or "unknown"),
                "local_context_key": str(interface.get("local_context_key") or ""),
                "scope_status": "scope_pending",
                "observed_at": str(interface.get("observed_at") or ""),
            }, reason="interface_routing_context_unmapped", source_kind="interface_snapshot")
            continue
        current_interface_sources.append({
            "id": f"interface:{device_id}:{interface.get('normalized_interface_name') or ''}:{ip}",
            "ip": ip, "address": ip, "mac": "", "mac_address": "",
            "hostname": str(interface.get("device_hostname") or ""),
            "device_id": device_id, "source_device_id": device_id,
            "source_device_name": str(interface.get("device_hostname") or device_id),
            "device_name": str(interface.get("device_hostname") or device_id),
            "interface_name": str(interface.get("interface_name") or ""),
            "site_id": site_id,
            "site_name": str(sites.get(site_id, {}).get("site_name") or ""),
            "tenant_id": tenant_id,
            "vrf_id": str(interface.get("mapped_vrf_id") or space.get("vrf_id") or ""),
            "address_space_id": address_space_id,
            "scope_status": "resolved",
            "observed_at": str(interface.get("observed_at") or ""),
            "context_source": str(interface.get("context_source") or ""),
            "context_type": str(interface.get("context_type") or "unknown"),
            "local_context_key": str(interface.get("local_context_key") or ""),
            "source_kind": "interface_snapshot",
            "evidence_status": "current_successful_interface_snapshot",
        })

    current_observed_by_space_ip = {
        (
            str(item.get("tenant_id") or ""),
            str(item.get("address_space_id") or ""),
            str(item.get("ip") or ""),
        )
        for item in [*current_endpoint_sources, *current_interface_sources]
    }
    undocumented: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    mismatched: dict[str, dict[str, Any]] = {}
    for source in [*current_endpoint_sources, *current_interface_sources]:
        tenant_id = str(source.get("tenant_id") or "")
        site_id = str(source.get("site_id") or "")
        space_id = str(source.get("address_space_id") or "")
        ip = str(source.get("ip") or "")
        key = (tenant_id, space_id, ip)
        all_candidates = all_ipam_by_space_ip.get(key, [])
        conflicts = [candidate for candidate in all_candidates if candidate.get("_scope_conflict")]
        candidates = [
            candidate for candidate in ipam_by_space_ip.get(key, [])
            if not candidate.get("_site_id") or str(candidate.get("_site_id") or "") == site_id
        ]
        if conflicts and not candidates:
            add_unscoped(
                {**source, "ipam_address_id": "", "scope_status": "conflict"},
                reason="ipam_scope_conflict", source_kind=str(source.get("source_kind") or "endpoint"),
            )
            continue
        if len(candidates) > 1:
            add_unscoped(
                {**source, "ipam_address_id": "", "scope_status": "conflict"},
                reason="duplicate_ipam_scope_records", source_kind=str(source.get("source_kind") or "endpoint"),
            )
            continue
        if not candidates:
            suggested = match_inventory_prefix(
                ip, (tenant_id, f"space:{space_id}", ip), site_id, prefix_catalog,
            )
            identity = (tenant_id, space_id, site_id, ip)
            evidence_device = {
                "id": source.get("source_device_id") or "",
                "name": source.get("source_device_name") or source.get("device_name") or "",
                "interface_name": source.get("interface_name") or "",
                "source_kind": source.get("source_kind") or "",
                "ip": source.get("ip") or "",
                "mac": source.get("mac") or "",
                "vlan": source.get("vlan") or "",
                "address_space_id": source.get("address_space_id") or "",
                "local_context_key": source.get("local_context_key") or "",
                "observation_id": source.get("id") or "",
            }
            if identity in undocumented:
                record = undocumented[identity]
                record["source_evidence_count"] = int(record.get("source_evidence_count") or 0) + 1
                record.setdefault("source_devices", []).append(evidence_device)
            else:
                undocumented[identity] = {
                    **source,
                    "ipam_address_id": "",
                    "subnet_id": (suggested or {}).get("id") or "",
                    "subnet_prefix": (suggested or {}).get("prefix") or "",
                    "subnet_name": (suggested or {}).get("name") or "",
                    "reason": "not_registered_in_current_ipam",
                    "source_evidence_count": 1,
                    "source_devices": [evidence_device],
                }
            continue
        ipam = candidates[0]
        ipam_status = _reconciliation_ipam_status(ipam)
        ipam_mac = _normalized_mac(ipam.get("mac_address"))
        observed_mac = _normalized_mac(source.get("mac"))
        mac_mismatch = bool(ipam_mac and observed_mac and ipam_mac != observed_mac)
        status_mismatch = ipam_status in {"available", "released"}
        if not mac_mismatch and not status_mismatch:
            continue
        ipam_id = str(ipam.get("id") or "")
        source_device = {
            "id": source.get("source_device_id") or "",
            "name": source.get("source_device_name") or source.get("device_name") or "",
            "interface_name": source.get("interface_name") or "",
            "source_kind": source.get("source_kind") or "",
            "ip": source.get("ip") or "",
            "mac": source.get("mac") or "",
            "vlan": source.get("vlan") or "",
            "address_space_id": source.get("address_space_id") or "",
            "local_context_key": source.get("local_context_key") or "",
            "observation_id": source.get("id") or "",
        }
        if ipam_id in mismatched:
            mismatch = mismatched[ipam_id]
            mismatch["mac_mismatch"] = bool(mismatch.get("mac_mismatch") or mac_mismatch)
            mismatch["status_mismatch"] = bool(mismatch.get("status_mismatch") or status_mismatch)
            mismatch["source_evidence_count"] = int(mismatch.get("source_evidence_count") or 0) + 1
            mismatch.setdefault("source_devices", []).append(source_device)
        else:
            mismatched[ipam_id] = {
                **source,
                "id": ipam_id,
                "ipam_address_id": ipam_id,
                "ipam_mac": str(ipam.get("mac_address") or ""),
                "observed_mac": str(source.get("mac") or ""),
                "mac_mismatch": mac_mismatch,
                "status_mismatch": status_mismatch,
                "ipam_status": ipam_status,
                "subnet_id": str(ipam.get("subnet_id") or ""),
                "subnet_prefix": str(ipam.get("prefix") or ""),
                "reason": "mac_mismatch" if mac_mismatch else "status_mismatch",
                "source_evidence_count": 1,
                "source_devices": [source_device],
            }

    def source_positions_are_ambiguous(record: dict[str, Any]) -> bool:
        sources = list(record.get("source_devices") or [])
        if len(sources) < 2:
            return False
        positions = {
            (
                str(item.get("id") or ""),
                normalize_interface_name(str(item.get("interface_name") or "")).strip().lower(),
                str(item.get("local_context_key") or ""),
            )
            for item in sources
        }
        macs = {str(item.get("mac") or "") for item in sources if item.get("mac")}
        vlans = {str(item.get("vlan") or "") for item in sources if item.get("vlan")}
        return len(positions) > 1 or len(macs) > 1 or len(vlans) > 1

    for record in undocumented.values():
        record["source_ambiguity"] = source_positions_are_ambiguous(record)
    for record in mismatched.values():
        record["source_ambiguity"] = source_positions_are_ambiguous(record)

    stale: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    unavailable_address_count = 0
    expected_source_ids: set[str] = set()
    proven_source_ids: set[str] = set()
    addresses_without_expected_source = 0

    def address_base(ipam: dict[str, Any]) -> dict[str, Any]:
        site_id = str(ipam.get("_site_id") or "")
        vrf_id = str(ipam.get("_vrf_id") or "")
        return {
            "id": str(ipam.get("id") or ""),
            "ipam_address_id": str(ipam.get("id") or ""),
            "ip": str(ipam.get("_address") or ""),
            "address": str(ipam.get("_address") or ""),
            "hostname": str(ipam.get("hostname") or ""),
            "mac_address": str(ipam.get("mac_address") or ""),
            "subnet_id": str(ipam.get("subnet_id") or ""),
            "subnet_prefix": str(ipam.get("prefix") or ""),
            "subnet_name": str(ipam.get("prefix_name") or ""),
            "site_id": site_id,
            "site_name": str(sites.get(site_id, {}).get("site_name") or ""),
            "vrf_id": vrf_id,
            "vrf_name": str(vrfs.get(vrf_id, {}).get("vrf_name") or ""),
            "tenant_id": str(ipam.get("_tenant_id") or DEFAULT_TENANT_ID),
            "address_space_id": str(ipam.get("_address_space_id") or ""),
            "status": str(ipam.get("status") or "active"),
        }

    for ipam in allocated_records:
        base = address_base(ipam)
        ip = str(ipam.get("_address") or "")
        tenant_id = str(ipam.get("_tenant_id") or "")
        site_id = str(ipam.get("_site_id") or "")
        space_id = str(ipam.get("_address_space_id") or "")
        if (tenant_id, space_id, ip) in current_observed_by_space_ip:
            continue
        if ipam.get("_scope_conflict") or not tenant_id or not site_id or not space_id:
            unavailable.append({
                **base,
                "kind": "ipam_address",
                "reason": ipam.get("_scope_conflict_reason") or "ipam_scope_or_address_space_unresolved",
                "miss_count": 0,
                "required_misses": 1,
                "coverage_status": "unavailable",
                "last_observed_at": "",
                "stale_reason": "scope_not_comparable",
            })
            unavailable_address_count += 1
            continue
        if (tenant_id, ip) in unresolved_by_tenant_ip or (tenant_id, site_id, ip) in unresolved_by_tenant_site_ip:
            unavailable.append({
                **base,
                "kind": "ipam_address",
                "reason": "same_ip_current_evidence_scope_unresolved",
                "miss_count": 0,
                "required_misses": 1,
                "coverage_status": "unavailable",
                "last_observed_at": "",
                "stale_reason": "current_evidence_scope_unresolved",
            })
            unavailable_address_count += 1
            continue
        if not _reconciliation_address_is_stale_eligible(ipam):
            continue
        expected_device_id = str(ipam.get("_expected_source_device_id") or "")
        if not expected_device_id:
            unavailable.append({
                **base,
                "kind": "ipam_address",
                "reason": "expected_source_not_established",
                "miss_count": 0,
                "required_misses": 1,
                "coverage_status": "unavailable",
                "last_observed_at": "",
                "stale_reason": "expected_source_not_established",
            })
            unavailable_address_count += 1
            addresses_without_expected_source += 1
            continue
        expected_source_ids.add(expected_device_id)
        current_source = valid_current_by_device.get(expected_device_id)
        if current_source:
            proven_source_ids.add(expected_device_id)
        if not source_set_known:
            unavailable.append({
                **base,
                "kind": "ipam_address",
                "reason": "no_complete_current_sweep",
                "miss_count": 0,
                "required_misses": 1,
                "coverage_status": "unavailable",
                "last_observed_at": "",
                "stale_reason": "current_sweep_incomplete",
            })
            unavailable_address_count += 1
            continue
        if not current_source:
            unavailable.append({
                **base,
                "kind": "ipam_address",
                "reason": "expected_source_not_complete_in_current_sweep",
                "miss_count": 0,
                "required_misses": 1,
                "coverage_status": "unavailable",
                "last_observed_at": "",
                "stale_reason": "expected_source_not_complete",
            })
            unavailable_address_count += 1
            continue
        stale.append({
            **base,
            "last_observed_at": "",
            "last_checked_at": last_checked_at,
            "miss_count": 1,
            "required_misses": 1,
            "coverage_status": "complete",
            "current_sweep_run_id": current_run_id,
            "evidence_status": "current_sweep_miss",
            "scope_status": "resolved",
            "stale_reason": "not_observed_in_latest_complete_sweep",
        })

    for device_id, status in collection_state["current_by_device"].items():
        if device_id in valid_current_by_device:
            continue
        device = devices.get(device_id, {})
        tenant_id = str(device.get("tenant_id") or "")
        site_id = str(device.get("site_id") or "")
        if not scope_visible(tenant_id, site_id):
            continue
        metadata = status.get("_metadata") or {}
        unavailable.append({
            "id": f"source:{device_id}",
            "kind": "source_coverage",
            "source_device_id": device_id,
            "source_device_name": str(device.get("hostname") or device_id),
            "tenant_id": tenant_id,
            "site_id": site_id,
            "scope_status": "resolved" if tenant_id and site_id else "scope_pending",
            "status": str(status.get("status") or "unknown"),
            "coverage_status": "unavailable",
            "coverage_reason": "current_device_result_incomplete",
            "reason": "current_device_result_incomplete",
            "source_run_id": str(metadata.get("collection_run_id") or ""),
            "last_attempt_at": str(status.get("last_attempt_at") or ""),
            "last_success_at": str(status.get("last_success_at") or ""),
        })
    if current_run_id and not source_set_known:
        unavailable.append({
            "id": f"source:sweep:{current_run_id}",
            "kind": "source_coverage",
            "source_device_id": "",
            "source_device_name": "ARP sweep",
            "status": "incomplete",
            "coverage_status": "unavailable",
            "coverage_reason": "current_sweep_incomplete",
            "reason": "current_sweep_incomplete",
            "source_run_id": current_run_id,
            "last_attempt_at": str(collection_state["sweep"].get("last_started_at") or ""),
            "last_success_at": str(collection_state["sweep"].get("last_completed_at") or ""),
            "expected_device_count": int(collection_state["eligible"] or 0),
            "selected_device_count": int(collection_state["selected"] or 0),
            "successful_device_count": int(collection_state["successful"] or 0),
            "failed_device_count": int(collection_state["failed"] or 0),
        })

    expected_source_count = len(expected_source_ids) + addresses_without_expected_source
    missing_source_count = max(0, expected_source_count - len(proven_source_ids))
    latest_success_times = [
        parsed
        for status in valid_current_by_device.values()
        if (parsed := _parse_time(status.get("last_success_at"))[0]) is not None
    ]
    latest_success_times.extend(current_neighbor_last_success_times)
    latest_endpoint_seen = _iso(max(endpoint_times)) if endpoint_times else ""
    latest_active_endpoint_seen = _iso(max(recent_endpoint_times)) if recent_endpoint_times else ""
    latest_source_success_at = _iso(max(latest_success_times)) if latest_success_times else ""
    has_inputs = bool(
        ipam_records or active_endpoint_rows or interface_snapshot_ip_count
        or current_neighbor_visible_count or current_neighbor_states
    )
    if not has_inputs:
        coverage_status = "no_inputs"
        coverage_reason = "当前没有已登记 IP、活动终端、最新成功接口地址、ARP 当前观察行或采集结果。"
    elif not source_set_known:
        coverage_status = "partial" if (
            active_endpoint_rows or interface_snapshot_ip_count
            or current_neighbor_visible_count or current_neighbor_states
        ) else "unavailable"
        coverage_reason = "当前全量 ARP sweep 尚未证明设备与覆盖完整；无法判断本次是否未观察到。"
    elif unavailable or unscoped or missing_source_count or current_neighbor_coverage_incomplete:
        coverage_status = "partial"
        coverage_reason = "结果仅比较当前数据；存在未映射范围、未完整证明的来源或未成功的最新上下文尝试。"
    else:
        coverage_status = "complete"
        coverage_reason = "结果仅依据当前 IPAM、ARP/ND 当前观察行、活动终端、最新成功接口地址和最近一次完整 ARP sweep；不回溯历史观察。"

    result: dict[str, Any] = {
        "undocumented_endpoints": list(undocumented.values()),
        "stale_ip_addresses": stale,
        "mismatched_endpoints": list(mismatched.values()),
        "never_observed": [],
        "unscoped": list(unscoped.values()),
        "unavailable": unavailable,
        "summary": {
            "ipam_address_record_count": len(ipam_records),
            "allocated_ipam_address_count": len(allocated_records),
            "active_endpoint_count": active_endpoint_count,
            "current_endpoint_count": active_endpoint_count,
            "interface_snapshot_ip_count": interface_snapshot_ip_count,
            "total_undocumented": len(undocumented),
            "total_stale": len(stale),
            "total_mismatched": len(mismatched),
            "total_never_observed": 0,
            "total_unscoped": len(unscoped),
            "total_unavailable": len(unavailable),
            "unavailable_address_count": unavailable_address_count,
            "unavailable_source_count": sum(1 for item in unavailable if item.get("kind") == "source_coverage"),
            "endpoint_cache_fresh": source_set_known,
            "latest_endpoint_seen": latest_endpoint_seen,
            "latest_active_endpoint_seen": latest_active_endpoint_seen,
            "latest_source_success_at": latest_source_success_at,
            "current_window_minutes": _recent_minutes(),
            "stale_after_days": 0,
            "required_misses": 1,
            "stale_basis": "latest_complete_current_sweep",
            "complete_source_run_count": 1 if source_set_known else 0,
            "coverage_source_set_known": source_set_known,
            "expected_source_count": expected_source_count,
            "proven_source_count": len(proven_source_ids),
            "missing_source_count": missing_source_count,
            "coverage_status": coverage_status,
            "coverage_reason": coverage_reason,
        },
    }
    if page is None:
        return result

    tab_map = {
        "undocumented": "undocumented_endpoints",
        "stale": "stale_ip_addresses",
        "mismatched": "mismatched_endpoints",
        "never_observed": "never_observed",
        "unscoped": "unscoped",
        "unavailable": "unavailable",
    }
    normalized_tab = tab_map.get(active_tab, "undocumented_endpoints")
    normalized_query = q.strip().lower()
    all_items = [
        item for item in result[normalized_tab]
        if not normalized_query
        or normalized_query in " ".join(str(value or "") for value in item.values()).lower()
    ]
    safe_page = max(1, int(page or 1))
    safe_page_size = min(max(1, int(page_size or 20)), 100)
    start = (safe_page - 1) * safe_page_size
    for key in tab_map.values():
        result[key] = all_items[start:start + safe_page_size] if key == normalized_tab else []
    result["result_total"] = len(all_items)
    result["page"] = safe_page
    result["page_size"] = safe_page_size
    result["has_more"] = start + safe_page_size < len(all_items)
    return result
