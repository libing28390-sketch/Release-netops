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

logger = logging.getLogger(__name__)
_NAMESPACE = uuid.UUID("6b50f4d4-51f7-5a11-a49a-2779d3d96030")
_PROJECTION_LOCK_KEY = (806301, 1)


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
        arp_interval_seconds = max(300, int(os.getenv("ARP_SWEEP_INTERVAL_SECONDS", "600")))
    except ValueError:
        arp_interval_seconds = 600
    # Two collection intervals plus two minutes of scheduler/device jitter.
    return min(max((arp_interval_seconds * 2 + 120 + 59) // 60, 1), 1440)


def _mac_recent_minutes() -> int:
    try:
        configured = os.getenv("IPAM_DISCOVERY_MAC_RECENT_MINUTES")
        if configured is not None and configured.strip():
            return min(max(int(configured), 1), 10080)
    except ValueError:
        pass
    # The current MAC table is refreshed by the daily endpoint-location job;
    # this freshness window does not imply a real-time port signal.
    return 26 * 60


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
                  ip.vrf_id AS ip_vrf_id, ip.site_id AS ip_site_id, ip.source_ref,
                  ip.created_at, ip.purpose, ip.device_type, ip.interface_id,
                  p.prefix, p.name AS prefix_name, p.tenant_id AS prefix_tenant_id,
                  p.vrf_id AS prefix_vrf_id, p.site_id AS prefix_site_id,
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
            tenant_id, site_id, vrf_id = prefix_tenant or DEFAULT_TENANT_ID, prefix_site, prefix_vrf
        else:
            scope_conflicts.append("parent_prefix_missing")
            tenant_id, site_id, vrf_id = ip_tenant or DEFAULT_TENANT_ID, ip_site, ip_vrf
        item.update({
            "_address": address, "_tenant_id": tenant_id, "_site_id": site_id,
            "_vrf_id": vrf_id, "_scope_conflict": bool(scope_conflicts),
            "_scope_conflict_reason": ",".join(scope_conflicts),
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

    current_mac_ports: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for row in mac_rows:
        scope = _effective_scope(row)
        evidence_status, _timestamp_status, observed_at = _evidence_status(row, now)
        if (
            evidence_status != "recent" or not observed_at
            or scope.get("scope_status") != "resolved"
            or str(scope.get("vrf_context_status") or "unknown") not in {"explicit_vrf", "explicit_global"}
            or now - observed_at > timedelta(minutes=_recent_minutes())
            or not scope.get("tenant_id") or not scope.get("site_id")
        ):
            continue
        mac = _normalized_mac(row.get("mac"))
        vlan = str(row.get("vlan") or "").strip()
        if not mac or not vlan:
            continue
        key = (str(scope["tenant_id"]), str(scope["site_id"]), str(scope["vrf_id"] or ""), vlan, mac)
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
        selected_ipam = matches[0] if len(matches) == 1 and not ipam_scope_conflict else None
        if selected_ipam:
            registration_status = "registered"
        elif not ip or scope["scope_status"] != "resolved" or ipam_scope_conflict:
            registration_status = "scope_pending"
        else:
            registration_status = "unregistered"

        switch_id = row.get("source_device_id") if row.get("source_type") == "mac" else ""
        switch_name = row.get("source_device_name") if row.get("source_type") == "mac" else ""
        switch_port = row.get("interface_name") if row.get("source_type") == "mac" else ""
        mac_observed_at = row.get("source_observed_at") if row.get("source_type") == "mac" else ""
        if row.get("source_type") == "arp" and mac and row.get("vlan") and site_id and tenant_id:
            association_key = (tenant_id, site_id, vrf_id, str(row.get("vlan") or "").strip(), mac)
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
            "switch_id": str(switch_id or ""),
            "switch_name": str(switch_name or ""),
            "switch_port": str(switch_port or ""),
            "switch_location_status": "matched" if switch_id and switch_port else "pending",
            "vlan": str(row.get("vlan") or ""),
            "observed_at": str(row.get("source_observed_at") or ""),
            "mac_observed_at": str(mac_observed_at or ""),
            "projected_at": str(row.get("projected_at") or ""),
            "evidence_status": evidence_status,
            "timestamp_status": timestamp_status,
            "hostname": "",
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
    if evidence_status and item.get("evidence_status") != evidence_status:
        return False
    if registration_status and item.get("registration_status") != registration_status:
        return False
    if query:
        values = " ".join(str(value or "") for value in item.values()).lower()
        if query not in values:
            return False
    return True


def _terminal_identity_key(item: dict[str, Any]) -> tuple[Any, ...]:
    if item.get("scope_status") == "resolved" and item.get("ip"):
        return (
            "ip", item.get("tenant_id"), item.get("site_id"), item.get("vrf_id"),
            item.get("ip"), _normalized_mac(item.get("mac")),
        )
    if item.get("scope_status") == "resolved" and not item.get("ip") and item.get("mac"):
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


def list_discovered_endpoints(
    *, site_id: str = "", vrf_id: str = "", device_id: str = "", q: str = "",
    kind: str = "all", evidence_status: str = "", registration_status: str = "",
    page: int = 1, page_size: int = 20,
    visible_scopes: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
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
            "UPDATE ip_addresses SET mac_address = ?, updated_at = ? WHERE id = ?",
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


def _snapshot_scope_key(snapshot: dict[str, Any]) -> tuple[str, str, str] | None:
    if snapshot.get("scope_status") != "resolved":
        return None
    if str(snapshot.get("vrf_context_status") or "unknown") not in {"explicit_vrf", "explicit_global"}:
        return None
    if not snapshot.get("tenant_id") or not snapshot.get("site_id"):
        return None
    return (
        str(snapshot.get("tenant_id") or ""), str(snapshot.get("site_id") or ""),
        str(snapshot.get("vrf_id") or ""),
    )


def _source_snapshots(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, collector, device_id, source_device_name, tenant_id, site_id, vrf_id,
                  vrf_context_status, scope_status, source_run_id, source_version, source_status,
                  coverage_status, coverage_complete, coverage_reason, entry_count,
                  observed_at, projected_at
             FROM ipam_discovery_snapshots
            WHERE collector = 'arp'
            ORDER BY observed_at, projected_at"""
    ).fetchall()
    return [dict(row) for row in rows]


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


def _scoped_ipam_records(
    ipam_by_scope: dict[tuple[str, str, str, str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    records = []
    for values in ipam_by_scope.values():
        for item in values:
            marker = str(item.get("id") or "")
            if marker and marker not in seen:
                seen.add(marker)
                records.append(item)
    return records


def _known_scope_key(item: dict[str, Any]) -> tuple[str, str, str] | None:
    if item.get("_scope_conflict"):
        return None
    if not item.get("_tenant_id") or not item.get("_site_id"):
        return None
    return (str(item["_tenant_id"]), str(item["_site_id"]), str(item["_vrf_id"] or ""))


def build_ipam_reconciliation(
    conn, *, active_tab: str = "", q: str = "", page: int | None = None,
    page_size: int = 20, visible_scopes: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Build reconciliation findings solely from IPAM-owned source evidence."""
    now = _utc_now()
    from services.ipam_inventory_scope import load_inventory_catalog, match_inventory_prefix
    prefix_catalog, _prefix_sites, _prefix_vrfs = load_inventory_catalog(conn)
    ipam_by_scope, ipam_records = _ipam_address_index(conn)
    devices, sites, vrfs = _device_catalog(conn)

    def scope_visible(tenant_id: Any, site_id: Any) -> bool:
        if visible_scopes is None:
            return True
        return (str(tenant_id or ""), str(site_id or "")) in visible_scopes

    ipam_records = [
        item for item in ipam_records
        if scope_visible(item.get("_tenant_id"), item.get("_site_id"))
    ]
    ipam_by_scope = {}
    for item in ipam_records:
        ipam_by_scope.setdefault(
            (item["_tenant_id"], item["_site_id"], item["_vrf_id"], item["_address"]), []
        ).append(item)
    observations = _load_projected_observations(conn)
    observations = [
        row for row in observations
        if scope_visible(row.get("tenant_id"), row.get("site_id"))
    ]
    decorated = _decorate_observations(observations, conn, now, ipam_by_scope_override=ipam_by_scope)
    history_rows = _load_projected_observations(conn, history=True)
    history_rows = [
        row for row in history_rows
        if scope_visible(row.get("tenant_id"), row.get("site_id"))
    ]
    history_decorated = _decorate_observations(history_rows, conn, now, ipam_by_scope_override=ipam_by_scope)
    snapshots = [
        row for row in _source_snapshots(conn)
        if scope_visible(row.get("tenant_id"), row.get("site_id"))
    ]
    status_rows = conn.execute(
        """SELECT s.device_id, s.status, s.source, s.last_attempt_at, s.last_success_at,
                  s.coverage_total, s.coverage_supported, s.metadata_json,
                  d.hostname, d.site_id, d.site, d.tenant_id
             FROM device_collection_status s
             LEFT JOIN devices d ON d.id = s.device_id
            WHERE s.collector = 'arp'
            ORDER BY s.device_id"""
    ).fetchall()
    source_status_by_device = {str(row["device_id"]): dict(row) for row in status_rows}
    sweep_row = conn.execute(
        "SELECT * FROM collector_sweep_state WHERE collector = 'arp'"
    ).fetchone()
    sweep = dict(sweep_row) if sweep_row else {}
    current_sweep_run_id = str(sweep.get("last_run_id") or "")
    current_sweep_devices = [
        row for row in source_status_by_device.values()
        if str(_json_object(row.get("metadata_json")).get("collection_run_id") or "") == current_sweep_run_id
    ]
    try:
        last_eligible = int(sweep.get("last_eligible") or 0)
        last_selected = int(sweep.get("last_selected") or 0)
    except (TypeError, ValueError):
        last_eligible = last_selected = 0
    current_sweep_completed, current_sweep_completed_state = _parse_time(sweep.get("last_completed_at"))
    source_set_known = bool(
        current_sweep_run_id and last_eligible > 0 and last_selected == last_eligible
        and len(current_sweep_devices) == last_selected
        and current_sweep_completed_state == "valid" and current_sweep_completed
        and all(
            row.get("status") == "success"
            and str(row.get("source") or "") == "arp_sweep"
            and int(row.get("coverage_supported") or 0) > 0
            for row in current_sweep_devices
        )
    )
    if visible_scopes is not None:
        source_set_known = source_set_known and all(
            scope_visible(
                devices.get(str(row.get("device_id") or ""), {}).get("tenant_id"),
                devices.get(str(row.get("device_id") or ""), {}).get("site_id"),
            )
            for row in current_sweep_devices
        )

    all_observations_by_ip: dict[str, list[dict[str, Any]]] = {}
    exact_history: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    current_by_scope_ip: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    latest_endpoint_seen: datetime | None = None
    latest_active_endpoint_seen: datetime | None = None
    for item in history_decorated:
        if item.get("source_type") != "arp" or not item.get("ip"):
            continue
        ip = str(item.get("ip"))
        all_observations_by_ip.setdefault(ip, []).append(item)
        observed_at, timestamp_status = _parse_time(item.get("observed_at"))
        if observed_at and timestamp_status == "valid" and (latest_endpoint_seen is None or observed_at > latest_endpoint_seen):
            latest_endpoint_seen = observed_at
        if item.get("scope_status") == "resolved" and timestamp_status == "valid" and observed_at:
            key = (str(item.get("tenant_id") or ""), str(item.get("site_id") or ""), str(item.get("vrf_id") or ""), ip)
            exact_history.setdefault(key, []).append(item)

    for item in decorated:
        if item.get("source_type") != "arp" or not item.get("ip"):
            continue
        observed_at, timestamp_status = _parse_time(item.get("observed_at"))
        if (
            item.get("scope_status") == "resolved"
            and item.get("evidence_status") == "recent"
            and timestamp_status == "valid" and observed_at
        ):
            key = (str(item.get("tenant_id") or ""), str(item.get("site_id") or ""), str(item.get("vrf_id") or ""), str(item.get("ip") or ""))
            current_by_scope_ip.setdefault(key, []).append(item)
            if latest_active_endpoint_seen is None or observed_at > latest_active_endpoint_seen:
                latest_active_endpoint_seen = observed_at

    ipam_by_id = {str(item.get("id") or ""): item for item in ipam_records}
    allocated_records = [
        item for item in ipam_records
        if _reconciliation_ipam_status(item) not in {"available", "released"}
    ]
    allocated_count = len(allocated_records)
    interface_snapshot_ip_count = 0
    try:
        from services.ipam_service import _current_cmdb_interface_ip_observations
        interface_rows = _current_cmdb_interface_ip_observations(conn)
        interface_snapshot_ip_count = sum(
            1 for item in interface_rows
            if scope_visible(
                item.get("tenant_id") or devices.get(str(item.get("device_id") or ""), {}).get("tenant_id"),
                item.get("asset_site_id") or item.get("device_site_id") or devices.get(str(item.get("device_id") or ""), {}).get("site_id"),
            )
        )
    except Exception:
        # Interface snapshots are an explanatory source count only. Their
        # availability must never turn into a discovery/reconciliation input.
        interface_snapshot_ip_count = 0

    undocumented: dict[tuple[Any, ...], dict[str, Any]] = {}
    mismatched: dict[tuple[Any, ...], dict[str, Any]] = {}
    unscoped: dict[str, dict[str, Any]] = {}
    for item in decorated:
        if item.get("source_type") != "arp" or not item.get("ip"):
            continue
        finding_observed_at, finding_time_status = _parse_time(item.get("observed_at"))
        if finding_time_status != "valid" or not finding_observed_at or now - finding_observed_at > timedelta(minutes=_recent_minutes()):
            continue
        if item.get("evidence_status") != "recent" and item.get("evidence_status") != "conflict":
            continue
        if item.get("scope_status") != "resolved":
            unscoped[str(item.get("id") or "")] = {
                **item, "reason": "source_scope_conflict" if item.get("scope_status") == "conflict" else "source_scope_pending",
            }
            if item.get("ip_mac_conflict"):
                conflict_key = ("source-conflict", item.get("tenant_id"), item.get("site_id"), item.get("ip"), item.get("mac"))
                mismatched[conflict_key] = {
                    **item, "conflict": True, "mac_mismatch": False,
                    "reason": "multiple_macs_for_same_scope_ip", "ipam_address_id": "",
                }
            continue
        key = (str(item.get("tenant_id") or ""), str(item.get("site_id") or ""), str(item.get("vrf_id") or ""), str(item.get("ip") or ""))
        candidates = ipam_by_scope.get(key, [])
        conflicting_ipam = [candidate for candidate in candidates if candidate.get("_scope_conflict")]
        candidates = [candidate for candidate in candidates if not candidate.get("_scope_conflict")]
        if conflicting_ipam:
            unscoped[str(item.get("id") or "")] = {
                **item, "scope_status": "conflict", "reason": "ipam_scope_conflict",
            }
            continue
        if len(candidates) > 1:
            unscoped[str(item.get("id") or "")] = {
                **item, "scope_status": "conflict", "reason": "duplicate_ipam_scope_records",
            }
            continue
        if not candidates:
            suggested = match_inventory_prefix(str(item.get("ip") or ""), (key[0], key[2], key[3]), key[1], prefix_catalog)
            identity = (key, _normalized_mac(item.get("mac")))
            record = undocumented.get(identity)
            evidence = {
                **item,
                "subnet_id": (suggested or {}).get("id") or "",
                "subnet_prefix": (suggested or {}).get("prefix") or "",
                "subnet_name": (suggested or {}).get("name") or "",
                "source_evidence_count": 1,
            }
            if record:
                record["source_evidence_count"] += 1
                record.setdefault("source_devices", []).append({
                    "id": item.get("source_device_id"), "name": item.get("source_device_name"),
                    "observation_id": item.get("observation_id"),
                })
            else:
                evidence["source_devices"] = [{
                    "id": item.get("source_device_id"), "name": item.get("source_device_name"),
                    "observation_id": item.get("observation_id"),
                }]
                undocumented[identity] = evidence
            continue

        ipam = candidates[0]
        ipam_status = _reconciliation_ipam_status(ipam)
        ipam_mac = _normalized_mac(ipam.get("mac_address"))
        observed_mac = _normalized_mac(item.get("mac"))
        mac_mismatch = bool(ipam_mac and observed_mac and ipam_mac != observed_mac)
        status_mismatch = ipam_status in {"available", "released"}
        key_mismatch = (key, str(ipam.get("id") or ""))
        if mac_mismatch or status_mismatch or item.get("evidence_status") == "conflict":
            mismatched[key_mismatch] = {
                **item,
                "ipam_address_id": ipam.get("id") or "",
                "ipam_mac": ipam.get("mac_address") or "",
                "observed_mac": item.get("mac") or "",
                "mac_mismatch": mac_mismatch,
                "status_mismatch": status_mismatch,
                "ipam_status": ipam_status,
                "subnet_id": ipam.get("subnet_id") or "",
                "subnet_prefix": ipam.get("prefix") or "",
                "evidence_status": item.get("evidence_status"),
                "scope_status": item.get("scope_status"),
            }

    # Source conflicts are computed over current evidence even if there is no
    # IPAM row, because a duplicate address is still useful to investigate.
    conflict_groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for key, items in current_by_scope_ip.items():
        macs = {_normalized_mac(item.get("mac")) for item in items if item.get("mac")}
        if len(macs) <= 1:
            continue
        conflict_groups[key] = items
        ipam_candidates = [item for item in ipam_by_scope.get(key, []) if not item.get("_scope_conflict")]
        representative = items[0]
        if key not in {tuple(row.get("_key") or ()) for row in mismatched.values()}:
            mismatched[("source-conflict", *key)] = {
                **representative,
                "ipam_address_id": ipam_candidates[0].get("id") if len(ipam_candidates) == 1 else "",
                "ipam_mac": ipam_candidates[0].get("mac_address") if len(ipam_candidates) == 1 else "",
                "observed_mac": ", ".join(sorted(macs)),
                "observed_macs": sorted(macs),
                "mac_mismatch": False,
                "conflict": True,
                "reason": "multiple_macs_for_same_scope_ip",
                "scope_status": "conflict",
                "evidence_status": "conflict",
                "calibration_safe": False,
            }

    cutoff_recent = now - timedelta(minutes=_recent_minutes())
    cutoff_stale = now - timedelta(days=_stale_days())
    snapshot_misses_by_source_scope: dict[tuple[str, str, str, str], dict[str, datetime]] = {}
    for snapshot in snapshots:
        if not snapshot.get("coverage_complete") or str(snapshot.get("source_status") or "") != "success":
            continue
        scope_key = _snapshot_scope_key(snapshot)
        run_id = str(snapshot.get("source_run_id") or "").strip()
        observed_at, timestamp_status = _parse_time(snapshot.get("observed_at"))
        device_id = str(snapshot.get("device_id") or "")
        if not scope_key or not device_id or not run_id or timestamp_status != "valid" or observed_at is None:
            continue
        key = (device_id, *scope_key)
        scope_runs = snapshot_misses_by_source_scope.setdefault(key, {})
        previous = scope_runs.get(run_id)
        if previous is None or observed_at > previous:
            scope_runs[run_id] = observed_at

    positive_runs_by_scope_ip: dict[tuple[str, str, str, str], set[str]] = {}
    for item in history_decorated:
        if item.get("source_type") != "arp" or not item.get("ip") or item.get("scope_status") != "resolved":
            continue
        run_id = str(item.get("source_run_id") or "").strip()
        if not run_id:
            continue
        key = (
            str(item.get("tenant_id") or ""), str(item.get("site_id") or ""),
            str(item.get("vrf_id") or ""), str(item.get("ip") or ""),
        )
        positive_runs_by_scope_ip.setdefault(key, set()).add(run_id)

    never_observed: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    unavailable_address_count = 0
    expected_source_ids_all: set[str] = set()
    proven_source_ids_all: set[str] = set()
    addresses_without_expected_source = 0
    for ipam in allocated_records:
        ip = str(ipam.get("_address") or "")
        ipam_id = str(ipam.get("id") or "")
        scope_key = _known_scope_key(ipam)
        base = {
            "id": ipam_id, "ipam_address_id": ipam_id, "ip": ip,
            "address": ip, "hostname": ipam.get("hostname") or "",
            "mac_address": ipam.get("mac_address") or "",
            "subnet_id": ipam.get("subnet_id") or "",
            "subnet_prefix": ipam.get("prefix") or "",
            "site_id": ipam.get("_site_id") or "",
            "vrf_id": ipam.get("_vrf_id") or "",
            "tenant_id": ipam.get("_tenant_id") or DEFAULT_TENANT_ID,
            "status": ipam.get("status") or "active",
        }
        if ipam.get("_scope_conflict") or not scope_key:
            unavailable.append({**base, "reason": ipam.get("_scope_conflict_reason") or "ipam_scope_missing", "miss_count": 0, "required_misses": _required_misses()})
            continue
        key = (*scope_key, ip)
        created_at, created_status = _parse_time(ipam.get("created_at"))
        exact = [item for item in exact_history.get(key, []) if item.get("timestamp_status") == "valid"]
        source_ref = str(ipam.get("source_ref") or "")
        matching_since_registration = [
            item for item in exact
            if str(item.get("id") or "") == source_ref
            or not created_at
            or ((item_time := _parse_time(item.get("observed_at"))[0]) is not None and item_time >= created_at)
        ]
        recent_matches = [item for item in current_by_scope_ip.get(key, []) if item.get("evidence_status") == "recent"]
        if recent_matches:
            continue
        ambiguous_source = [
            item for item in all_observations_by_ip.get(ip, [])
            if item.get("scope_status") != "resolved"
            and str(item.get("tenant_id") or "") == scope_key[0]
            and str(item.get("site_id") or "") == scope_key[1]
        ]
        latest_exact = None
        if matching_since_registration:
            latest_exact = max(
                matching_since_registration,
                key=lambda item: (_parse_time(item.get("observed_at"))[0] or datetime.min.replace(tzinfo=timezone.utc), str(item.get("id") or "")),
            )
        latest_seen = _parse_time(latest_exact.get("observed_at"))[0] if latest_exact else None
        expected_source_ids = {
            str(item.get("source_device_id") or "")
            for item in exact if str(item.get("source_device_id") or "")
        }
        gateway_source_id = str(ipam.get("_expected_source_device_id") or "")
        if gateway_source_id:
            expected_source_ids.add(gateway_source_id)
        expected_source_ids_all.update(expected_source_ids)
        if not expected_source_ids:
            addresses_without_expected_source += 1

        runs_by_expected_source = {
            device_id: snapshot_misses_by_source_scope.get((device_id, *scope_key), {})
            for device_id in expected_source_ids
        }
        if expected_source_ids and len(runs_by_expected_source) == len(expected_source_ids):
            common_run_ids = set.intersection(*(set(values) for values in runs_by_expected_source.values())) if runs_by_expected_source else set()
        else:
            common_run_ids = set()
        positive_run_ids = positive_runs_by_scope_ip.get(key, set())
        eligible_runs: dict[str, datetime] = {}
        for run_id in common_run_ids - positive_run_ids:
            per_source_times = [runs_by_expected_source[device_id][run_id] for device_id in expected_source_ids]
            if not per_source_times:
                continue
            observation_time = min(per_source_times)
            if observation_time > now:
                continue
            if created_at and created_status == "valid" and observation_time < created_at:
                continue
            if latest_seen and observation_time <= latest_seen:
                continue
            eligible_runs[run_id] = observation_time
        miss_count = len(eligible_runs)

        current_source_proven = bool(expected_source_ids and current_sweep_run_id in common_run_ids)
        if current_source_proven:
            per_source_latest_times = []
            for source_device_id in expected_source_ids:
                status = source_status_by_device.get(source_device_id) or {}
                metadata = _json_object(status.get("metadata_json"))
                if (
                    status.get("status") != "success"
                    or str(status.get("source") or "") != "arp_sweep"
                    or str(metadata.get("collection_run_id") or "") != current_sweep_run_id
                    or int(status.get("coverage_supported") or 0) < 1
                ):
                    current_source_proven = False
                    break
                per_source_latest_times.append(
                    runs_by_expected_source[source_device_id].get(current_sweep_run_id)
                )
            if current_source_proven and (
                not per_source_latest_times or any(value is None or value < cutoff_recent for value in per_source_latest_times)
            ):
                current_source_proven = False
        if current_source_proven:
            proven_source_ids_all.update(expected_source_ids)

        if (
            matching_since_registration and latest_seen and latest_seen <= cutoff_stale
            and miss_count >= _required_misses() and current_source_proven
        ):
            stale.append({
                **base, "last_observed_at": _iso(latest_seen) or "",
                "last_seen": _iso(latest_seen) or "",
                "days_since_seen": round((now - latest_seen).total_seconds() / 86400, 1),
                "miss_count": miss_count, "required_misses": _required_misses(),
                "coverage_runs": sorted(eligible_runs), "evidence_status": "historical",
                "scope_status": "resolved",
            })
            continue
        if not matching_since_registration and not ambiguous_source:
            never_observed.append({
                **base, "last_observed_at": "", "evidence_status": "unknown",
                "reason": "no_matching_observation_since_registration",
            })
        if ambiguous_source:
            unavailable_reason = "same_ip_observation_scope_unresolved"
        elif not expected_source_ids:
            unavailable_reason = "expected_source_not_established"
        elif not snapshots:
            unavailable_reason = "no_collection_coverage_evidence"
        elif not current_source_proven:
            unavailable_reason = "expected_source_current_snapshot_unavailable"
        elif miss_count < _required_misses() and latest_seen and latest_seen <= cutoff_stale:
            unavailable_reason = "insufficient_complete_snapshots"
        elif matching_since_registration and latest_seen and latest_seen > cutoff_stale:
            unavailable_reason = "within_long_unseen_window"
        elif not matching_since_registration and miss_count < _required_misses():
            unavailable_reason = "no_proven_complete_scope_snapshot"
        else:
            unavailable_reason = "source_coverage_unavailable"
        unavailable.append({
            **base, "reason": unavailable_reason,
            "last_observed_at": _iso(latest_seen) if latest_seen else "",
            "miss_count": miss_count, "required_misses": _required_misses(),
            "coverage_status": "complete" if miss_count >= _required_misses() else "unavailable",
            "source_device_id": latest_exact.get("source_device_id") if latest_exact else "",
            "source_device_name": latest_exact.get("source_device_name") if latest_exact else "",
            "expected_source_device_ids": sorted(expected_source_ids),
        })
        unavailable_address_count += 1

    latest_snapshot_by_device: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        previous = latest_snapshot_by_device.get(str(snapshot.get("device_id") or ""))
        if previous is None or str(snapshot.get("projected_at") or "") > str(previous.get("projected_at") or ""):
            latest_snapshot_by_device[str(snapshot.get("device_id") or "")] = snapshot
    for status in source_status_by_device.values():
        device_id = str(status.get("device_id") or "")
        device_scope = devices.get(device_id, {})
        if not scope_visible(device_scope.get("tenant_id"), device_scope.get("site_id")):
            continue
        metadata = _json_object(status.get("metadata_json"))
        source_scope = _resolve_device_scope(device_scope, sites, vrfs, metadata)
        run_id = str(metadata.get("collection_run_id") or "")
        snapshot = latest_snapshot_by_device.get(device_id) or {}
        if (
            status.get("status") == "success"
            and run_id
            and snapshot.get("source_run_id") == run_id
            and snapshot.get("coverage_complete")
            and _snapshot_scope_key(snapshot) is not None
        ):
            completed_at, completed_state = _parse_time(snapshot.get("observed_at"))
            if completed_state == "valid" and completed_at and now - completed_at <= timedelta(minutes=_recent_minutes()):
                continue
        if status.get("status") == "success" and snapshot.get("coverage_complete") and _snapshot_scope_key(snapshot) is None:
            reason = "source_scope_unresolved"
            coverage_status = "scope_pending"
        elif status.get("status") != "success":
            reason = "collector_not_successful"
            coverage_status = "unavailable"
        elif not snapshot or not snapshot.get("coverage_complete"):
            reason = str(snapshot.get("coverage_reason") or "collection_run_not_correlated")
            coverage_status = "unavailable"
        else:
            reason = "source_snapshot_stale"
            coverage_status = "unavailable"
        unavailable.append({
            "id": f"source:{device_id}", "kind": "source_coverage",
            "source_device_id": device_id,
            "source_device_name": str(status.get("hostname") or snapshot.get("source_device_name") or device_id),
            "tenant_id": source_scope.get("tenant_id") or DEFAULT_TENANT_ID,
            "site_id": source_scope.get("site_id") or "",
            "scope_status": source_scope.get("scope_status") or "scope_pending",
            "status": str(status.get("status") or "unknown"),
            "coverage_status": coverage_status,
            "coverage_reason": reason,
            "last_attempt_at": str(status.get("last_attempt_at") or ""),
            "last_success_at": str(status.get("last_success_at") or ""),
            "source_run_id": run_id,
        })

    current_ip_identities = {
        (str(item.get("tenant_id") or ""), str(item.get("site_id") or ""), str(item.get("vrf_id") or ""), str(item.get("ip") or ""))
        for item in decorated
        if item.get("source_type") == "arp" and item.get("ip") and item.get("scope_status") == "resolved" and item.get("evidence_status") == "recent"
    }
    active_endpoint_count = len(current_ip_identities)
    complete_run_count = len({
        snapshot.get("source_run_id") for snapshot in snapshots
        if snapshot.get("coverage_complete") and snapshot.get("source_run_id")
        and _snapshot_scope_key(snapshot) is not None
    })
    visible_success_times: list[datetime] = []
    for device_id, status in source_status_by_device.items():
        snapshot = latest_snapshot_by_device.get(device_id, {})
        device_scope = devices.get(device_id, {})
        if not scope_visible(
            snapshot.get("tenant_id") or device_scope.get("tenant_id"),
            snapshot.get("site_id") or device_scope.get("site_id"),
        ):
            continue
        if status.get("status") == "success":
            parsed, parsed_state = _parse_time(status.get("last_success_at"))
            if parsed and parsed_state == "valid":
                visible_success_times.append(parsed)
    latest_success_at = _iso(max(visible_success_times)) if visible_success_times else ""
    missing_expected_sources = len(expected_source_ids_all - proven_source_ids_all) + addresses_without_expected_source
    if not allocated_count and not decorated:
        coverage_status = "no_inputs"
        coverage_reason = "当前没有已登记地址或可展示的发现证据。"
    elif unavailable or unscoped or not source_set_known or missing_expected_sources:
        coverage_status = "partial" if complete_run_count or active_endpoint_count or decorated else "unavailable"
        coverage_reason = "来源集合或地址范围尚未完整证明；结果仅反映当前可验证的正向观察。"
    elif complete_run_count or active_endpoint_count:
        coverage_status = "complete"
        coverage_reason = "当前比较输入具备可用范围；结果仍是供人工核查的证据。"
    else:
        coverage_status = "unavailable"
        coverage_reason = "已有台账，但没有可证明范围和时间的有效发现快照。"

    result: dict[str, Any] = {
        "undocumented_endpoints": list(undocumented.values()),
        "stale_ip_addresses": stale,
        "mismatched_endpoints": list(mismatched.values()),
        "never_observed": never_observed,
        "unscoped": list(unscoped.values()),
        "unavailable": unavailable,
        "summary": {
            "ipam_address_record_count": len(ipam_records),
            "allocated_ipam_address_count": allocated_count,
            "active_endpoint_count": active_endpoint_count,
            "current_endpoint_count": active_endpoint_count,
            "interface_snapshot_ip_count": interface_snapshot_ip_count,
            "total_undocumented": len(undocumented),
            "total_stale": len(stale),
            "total_mismatched": len(mismatched),
            "total_never_observed": len(never_observed),
            "total_unscoped": len(unscoped),
            "total_unavailable": len(unavailable),
            "unavailable_address_count": unavailable_address_count,
            "unavailable_source_count": len(unavailable) - unavailable_address_count,
            "endpoint_cache_fresh": bool(active_endpoint_count),
            "latest_endpoint_seen": _iso(latest_endpoint_seen) or "",
            "latest_active_endpoint_seen": _iso(latest_active_endpoint_seen) or "",
            "latest_source_success_at": latest_success_at,
            "current_window_minutes": _recent_minutes(),
            "stale_after_days": _stale_days(),
            "required_misses": _required_misses(),
            "complete_source_run_count": complete_run_count,
            "coverage_source_set_known": source_set_known,
            "expected_source_count": len(expected_source_ids_all) + addresses_without_expected_source,
            "proven_source_count": len(proven_source_ids_all),
            "missing_source_count": missing_expected_sources,
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
        if not normalized_query or normalized_query in " ".join(str(value or "") for value in item.values()).lower()
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
