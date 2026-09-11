"""Four-stage, CLI-only IP path tracing engine.

The legacy locator predates shared cache/task coordination and is kept for
compatibility.  This module provides a small, deterministic engine for the
new flow:

    core -> target route/Direct -> ARP target IP -> MAC target -> topology
    recursion

It deliberately uses the existing vendor command catalog and parsers.  No
SNMP code is imported or used here.  The engine is synchronous so callers can
run it in the existing worker pool; the API layer is responsible for
offloading it from the event loop.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from database import get_db_connection
from services import ip_locator_service as legacy

logger = logging.getLogger(__name__)


DIRECT_PROTOCOLS = {"direct", "connected", "local", "receive", "directly connected"}
CORE_ROLES = {"core", "router", "gateway", "firewall", "distribution", "dist", "aggregation", "l3switch"}


@dataclass(frozen=True)
class TraceLimits:
    """Safety limits for one user initiated trace."""

    max_l3_hops: int = 16
    max_l2_hops: int = 16
    max_devices: int = 32
    max_candidates_per_hop: int = 4


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _cache_for_scope(scope: dict[str, Any]) -> tuple[Any, str] | tuple[None, str]:
    """Return the optional shared locator cache and a scope hash.

    The trace engine remains usable when Redis is not installed/configured;
    callers then fall through to PostgreSQL facts and CLI collection.
    """
    try:
        from services.ip_locator_cache_service import get_locator_cache

        cache = get_locator_cache()
        scope_hash = cache.scope_hash(scope)
        return cache, scope_hash
    except Exception as exc:  # pragma: no cover - optional dependency path
        logger.debug("[IPLocatorV2] shared cache unavailable: %s", type(exc).__name__)
        return None, ""


def _cache_key(cache: Any, kind: str, scope_hash: str, *parts: Any) -> str:
    if cache is None or not scope_hash:
        return ""
    try:
        return cache.build_key(kind, scope_hash, *parts)
    except Exception:
        return ""


def _normalise_vrf(value: Any) -> str:
    text = str(value or "").strip()
    return text or "default"


def _device_label(device: dict[str, Any]) -> str:
    return str(device.get("hostname") or device.get("ip_address") or device.get("id") or "unknown")


def _normalise_platform(device: dict[str, Any]) -> str:
    return str(device.get("platform") or "cisco_ios").strip().lower()


def _route_command(device: dict[str, Any], target_ip: str, vrf: str) -> str:
    """Build a read-only exact route lookup for the canonical platform."""
    platform = _normalise_platform(device)
    if vrf != "default":
        if "juniper" in platform or "junos" in platform:
            return f"show route table {vrf}.inet.0 {target_ip}"
        if any(token in platform for token in ("huawei", "vrp", "comware", "h3c", "hp")):
            return f"display ip routing-table vpn-instance {vrf} {target_ip}"
        return f"show ip route vrf {vrf} {target_ip}"
    if "juniper" in platform or "junos" in platform:
        return f"show route {target_ip}"
    if any(token in platform for token in ("huawei", "vrp", "comware", "h3c", "hp")):
        return f"display ip routing-table {target_ip}"
    return f"show ip route {target_ip}"


def _prefix_from_values(prefix: Any, mask: Any) -> str:
    raw_prefix = str(prefix or "").strip()
    raw_mask = str(mask or "").strip()
    if "/" in raw_prefix:
        return raw_prefix
    if raw_prefix and raw_mask:
        try:
            if raw_mask.isdigit():
                return f"{raw_prefix}/{raw_mask}"
            return str(ipaddress.ip_network(f"{raw_prefix}/{raw_mask}", strict=False))
        except ValueError:
            return ""
    return raw_prefix


def _route_row(raw: Any, *, device_id: str, vrf: str, target_ip: str = "") -> dict[str, Any] | None:
    def value(key: str, default: Any = "") -> Any:
        if isinstance(raw, dict):
            return raw.get(key, default)
        try:
            return raw[key]
        except (KeyError, IndexError, TypeError):
            return default

    prefix = _prefix_from_values(
        value("prefix") or value("destination"),
        value("mask") or value("prefix_length"),
    )
    if not prefix and target_ip:
        prefix = f"{target_ip}/32"
    if not prefix:
        return None
    try:
        network = ipaddress.ip_network(prefix, strict=False)
    except ValueError:
        return None
    return {
        "device_id": str(value("device_id") or device_id),
        "vrf_name": _normalise_vrf(value("vrf_name") or value("vrf") or vrf),
        "prefix": str(network.network_address),
        "mask": str(network.netmask),
        "destination": str(network),
        "next_hop": str(value("next_hop") or value("nexthop") or "").strip(),
        "protocol": str(value("protocol") or value("route_type") or "").strip().lower(),
        "interface": str(value("interface") or value("outgoing_interface") or "").strip(),
        "metric": value("metric") or 0,
        "preference": value("preference") or 0,
        "last_updated": value("last_updated") or value("last_update") or "",
        "source": value("source") or "cache",
    }


def _is_direct(row: dict[str, Any]) -> bool:
    protocol = str(row.get("protocol") or "").strip().lower()
    next_hop = str(row.get("next_hop") or "").strip().lower()
    return protocol in DIRECT_PROTOCOLS or next_hop in DIRECT_PROTOCOLS or next_hop in {"on-link", "onlink"}


def _route_age_seconds(value: Any) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()))
    except (TypeError, ValueError):
        return None


def _cached_route_rows(device_id: str, target_ip: str, vrf: str, fresh_seconds: int) -> list[dict[str, Any]]:
    """Read only fresh route facts from the existing PG projections."""
    rows: list[dict[str, Any]] = []
    try:
        conn = get_db_connection()
        try:
            for table, ts_column in (("route_cache", "last_update"), ("route_table", "last_updated")):
                try:
                    found = conn.execute(
                        f"SELECT * FROM {table} WHERE device_id = ? AND vrf_name = ?",
                        (device_id, vrf),
                    ).fetchall()
                except Exception:
                    continue
                for item in found:
                    normalised = _route_row(item, device_id=device_id, vrf=vrf, target_ip=target_ip)
                    if not normalised:
                        continue
                    normalised["source"] = table
                    normalised["last_updated"] = normalised.get("last_updated") or item[ts_column]
                    age = _route_age_seconds(normalised.get("last_updated"))
                    if age is None or age <= max(1, int(fresh_seconds)):
                        try:
                            if ipaddress.ip_address(target_ip) in ipaddress.ip_network(normalised["destination"], strict=False):
                                rows.append(normalised)
                        except ValueError:
                            continue
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("[IPLocatorV2] route cache read failed: %s", exc)
    # The two legacy projections may contain the same fact.
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["destination"], row["next_hop"], row["interface"], row["protocol"])
        unique.setdefault(key, row)
    return list(unique.values())


def _parse_target_route_output(output: str, device: dict[str, Any], target_ip: str, vrf: str) -> list[dict[str, Any]]:
    """Parse exact or small route command output using existing vendor parsers."""
    platform = _normalise_platform(device)
    parsed: list[dict[str, Any]] = []
    try:
        for raw in legacy.parse_routing_table(output or "", platform):
            row = _route_row(raw, device_id=str(device.get("id") or ""), vrf=vrf, target_ip=target_ip)
            if row:
                parsed.append(row)
    except Exception as exc:
        logger.debug("[IPLocatorV2] route parser failed for %s: %s", _device_label(device), exc)

    # Targeted command output is not uniform across vendors.  The diagnostic
    # parser can still recover next-hop/interface pairs when the full parser
    # did not recognise a line; the destination remains the requested IP and
    # is marked as CLI evidence rather than pretending to know a prefix.
    if not parsed:
        try:
            from services.diagnose_service import parse_route_output

            for next_hop, interface in parse_route_output(output or "", platform):
                row = _route_row(
                    {
                        "prefix": f"{target_ip}/32",
                        "next_hop": next_hop,
                        "interface": interface,
                        "protocol": "direct" if str(next_hop).lower() in DIRECT_PROTOCOLS else "cli",
                        "source": "cli",
                    },
                    device_id=str(device.get("id") or ""),
                    vrf=vrf,
                    target_ip=target_ip,
                )
                if row:
                    parsed.append(row)
        except Exception as exc:
            logger.debug("[IPLocatorV2] diagnostic route parser failed: %s", exc)
    # Some exact-output variants expose the destination on a heading while
    # the continuation line only carries next-hop/interface.  Recover that
    # prefix so longest-prefix selection does not degrade every result to a
    # synthetic /32.
    if parsed:
        headings = re.findall(r"(?<!\d)(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})(?!\d)", output or "")
        for heading in headings:
            try:
                network = ipaddress.ip_network(heading, strict=False)
            except ValueError:
                continue
            if ipaddress.ip_address(target_ip) not in network:
                continue
            for row in parsed:
                try:
                    row_network = ipaddress.ip_network(row.get("destination") or "", strict=False)
                except ValueError:
                    continue
                if row_network.prefixlen == 32 and row_network.network_address == ipaddress.ip_address(target_ip):
                    row.update({
                        "prefix": str(network.network_address),
                        "mask": str(network.netmask),
                        "destination": str(network),
                    })
            break
    return parsed


def _best_routes(rows: Iterable[dict[str, Any]], target_ip: str) -> list[dict[str, Any]]:
    target = ipaddress.ip_address(target_ip)
    matching: list[dict[str, Any]] = []
    for row in rows:
        try:
            network = ipaddress.ip_network(row.get("destination") or "", strict=False)
        except ValueError:
            continue
        if target.version == network.version and target in network:
            item = dict(row)
            item["prefix_length"] = network.prefixlen
            matching.append(item)
    if not matching:
        return []
    longest = max(int(row.get("prefix_length") or 0) for row in matching)
    selected = [row for row in matching if int(row.get("prefix_length") or 0) == longest]
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in selected:
        key = (
            str(row.get("destination") or ""),
            str(row.get("next_hop") or ""),
            str(row.get("interface") or ""),
            str(row.get("protocol") or ""),
        )
        unique.setdefault(key, row)
    selected = list(unique.values())
    selected.sort(key=lambda row: (
        0 if _is_direct(row) else 1,
        str(row.get("next_hop") or ""),
        str(row.get("interface") or ""),
    ))
    return selected


def _load_devices(*, start_device_id: str = "", site_id: str = "") -> list[dict[str, Any]]:
    try:
        devices = [dict(item) for item in legacy._load_eligible_devices()]
    except Exception as exc:
        logger.warning("[IPLocatorV2] eligible device load failed: %s", exc)
        return []
    if site_id:
        requested = str(site_id).strip().lower()
        scoped = [
            item for item in devices
            if str(item.get("site_id") or item.get("site") or "").strip().lower() == requested
        ]
        if scoped:
            devices = scoped
    # Return the complete in-scope inventory.  The trace selects its starting
    # frontier separately so an explicit core can still resolve downstream
    # next hops from the same managed-device map.
    selected_id = str(start_device_id or "")
    return sorted(
        devices,
        key=lambda item: (
            0 if selected_id and str(item.get("id") or "") == selected_id else 1,
            str(item.get("id") or item.get("ip_address") or ""),
        ),
    )


def _device_map(devices: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id") or ""): item for item in devices if item.get("id")}


def _run_cli_with_device_lease(
    device: dict[str, Any],
    operation: str,
    callback: Any,
    *,
    owner_id: str,
) -> Any:
    """Run one CLI operation under the durable per-device budget.

    The PostgreSQL lease is best effort for legacy installations that have
    not applied migration 219 yet; the existing process-level SSH limiter
    remains the final guard in that case.  Once the migration is present, a
    second worker cannot bypass the same canonical device slot.
    """
    device_id = str(device.get("id") or "")
    if not device_id:
        return callback()
    lease = None
    try:
        from services.ip_locator_task_service import acquire_device_access_lease

        lease = acquire_device_access_lease(
            device_id,
            owner_id=owner_id,
            task_id=f"{owner_id}:{operation}:{device_id}",
            capacity=1,
            purpose="ip_locator",
            lease_seconds=90,
        )
    except Exception as exc:
        # A pre-V2 database or an unavailable coordination service should not
        # silently make the old CLI path unusable.  The callback still uses
        # limited_connect_handler and therefore retains the local guard.
        logger.debug("[IPLocatorV2] durable device lease unavailable (%s)", type(exc).__name__)
        return callback()
    if lease is None:
        raise TimeoutError("device access budget unavailable")
    try:
        return callback()
    except TimeoutError:
        raise
    except Exception as exc:
        raise exc
    finally:
        if lease:
            try:
                from services.ip_locator_task_service import release_device_access_lease

                release_device_access_lease(
                    device_id,
                    owner_id=owner_id,
                    lease_token=str(lease.get("lease_token") or ""),
                    purpose="ip_locator",
                )
            except Exception as exc:
                logger.debug("[IPLocatorV2] device lease release failed (%s)", type(exc).__name__)


def _persist_observation(
    *,
    tenant_id: str,
    scope_hash: str,
    network_domain_id: str,
    site_id: str,
    vrf: str,
    device_id: str,
    kind: str,
    target_ip: str = "",
    target_mac: str = "",
    vlan_id: Any = None,
    records: Any = None,
    coverage: str = "targeted",
    collected_at: str | None = None,
) -> None:
    """Best-effort PG projection for a successful CLI observation."""
    try:
        from services.ip_locator_task_service import upsert_locator_observation
        from core.config import settings

        cache, _ = _cache_for_scope({"tenant_id": tenant_id})
        policy = cache.policy(kind) if cache is not None else None
        fresh_seconds = int(getattr(settings, f"IP_LOCATOR_{kind.upper()}_FRESH_SECONDS", 300))
        retain_seconds = int(getattr(settings, f"IP_LOCATOR_{kind.upper()}_RETAIN_SECONDS", fresh_seconds))
        observed_at = collected_at or _now_iso()
        upsert_locator_observation(
            tenant_id=tenant_id,
            scope_hash=scope_hash,
            network_domain_id=network_domain_id,
            site_id=site_id,
            vrf_name=vrf,
            device_id=str(device_id),
            observation_kind=kind,
            target_ip=target_ip,
            target_mac=target_mac,
            vlan_id=vlan_id,
            records=records if records is not None else {},
            coverage=coverage,
            source="ssh_cli",
            collected_at=observed_at,
            fresh_seconds=(policy.fresh_seconds if policy else fresh_seconds),
            retain_seconds=(policy.retain_seconds if policy else retain_seconds),
        )
    except Exception as exc:
        # Projection failure must not turn a successful device observation
        # into an API failure; the legacy facts and Redis result remain usable.
        logger.debug("[IPLocatorV2] observation projection skipped (%s)", type(exc).__name__)


def _find_next_hop_device(conn: Any, next_hop: str, current: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve a next hop only to a managed device in the current scope."""
    if not next_hop or str(next_hop).strip().lower() in DIRECT_PROTOCOLS:
        return None
    try:
        return legacy.lookup_neighbor_device(conn, "", str(next_hop).strip())
    except Exception:
        return None


def _topology_neighbors(conn: Any, device_id: str, port: str) -> list[dict[str, Any]]:
    """Return all active topology candidates for a canonical local port."""
    normalized = legacy.normalize_interface_name(port).lower()
    if not normalized:
        return []
    matches: list[dict[str, Any]] = []
    try:
        rows = conn.execute(
            """SELECT * FROM topology_links
               WHERE (source_device_id = ? OR target_device_id = ?)
                 AND COALESCE(status, 'up') NOT IN ('down', 'stale', 'inactive', 'deleted')""",
            (device_id, device_id),
        ).fetchall()
    except Exception:
        rows = []
    for raw in rows:
        row = dict(raw)
        for side, other in (("source", "target"), ("target", "source")):
            if str(row.get(f"{side}_device_id") or "") != str(device_id):
                continue
            candidates = {
                legacy.normalize_interface_name(str(row.get(f"{side}_port") or "")).lower(),
                str(row.get(f"{side}_port_normalized") or "").strip().lower(),
                legacy.normalize_interface_name(str(row.get(f"{side}_aggregation_name") or "")).lower(),
            }
            if normalized not in candidates:
                continue
            neighbor_id = str(row.get(f"{other}_device_id") or "")
            if not neighbor_id or neighbor_id == str(device_id):
                continue
            matches.append({
                "neighbor_id": neighbor_id,
                "neighbor_name": row.get(f"{other}_hostname") or neighbor_id,
                "neighbor_port": row.get(f"{other}_port") or row.get(f"{other}_port_normalized") or "",
                "evidence": row.get("discovery_source") or "topology",
                "confidence": float(row.get("confidence") or 0),
                "last_seen": row.get("last_seen") or row.get("updated_at") or "",
            })
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in matches:
        unique.setdefault((str(item["neighbor_id"]), str(item["neighbor_port"])), item)
    return sorted(unique.values(), key=lambda item: (-float(item.get("confidence") or 0), str(item["neighbor_id"])))


def _lldp_neighbors(device: dict[str, Any], port: str) -> list[dict[str, Any]]:
    """CLI-only fallback for a missing topology projection."""
    try:
        records = legacy._collect_lldp_from_device(device)
    except Exception as exc:
        logger.debug("[IPLocatorV2] LLDP CLI fallback failed for %s: %s", _device_label(device), exc)
        return []
    wanted = legacy.normalize_interface_name(port).lower()
    result = []
    for item in records or []:
        local = legacy.normalize_interface_name(item.get("local_interface") or "").lower()
        if local != wanted or not item.get("neighbor"):
            continue
        result.append({
            "neighbor_name": item.get("neighbor") or "",
            "neighbor_port": item.get("neighbor_port") or "",
            "evidence": "lldp_cli",
            "confidence": 0.6,
        })
    return result


def _terminal_evidence(conn: Any, device_id: str, port: str) -> dict[str, Any]:
    try:
        identity = legacy._load_trace_port_identity(conn, device_id, port)
    except Exception as exc:
        logger.debug("[IPLocatorV2] terminal identity failed: %s", exc)
        return {"is_terminal": False, "reason": "interface_evidence_unavailable"}
    try:
        confirmed = bool(legacy._trace_identity_confirms_access_terminal(identity))
    except Exception:
        confirmed = False
    return {
        "is_terminal": confirmed,
        "is_physical": bool(identity.get("is_physical")),
        "is_access": bool(identity.get("is_access")),
        "is_trunk": bool(identity.get("is_trunk")),
        "is_aggregation": bool(identity.get("is_aggregation")),
        "access_evidence": list(identity.get("access_evidence") or []),
        "reason": "access_evidence" if confirmed else "missing_access_evidence",
    }


def _initial_result(target_ip: str, vrf: str, scope: dict[str, Any], limits: TraceLimits) -> dict[str, Any]:
    return {
        "run_id": str(uuid.uuid4()),
        "target_ip": target_ip,
        "vrf": vrf,
        "scope": dict(scope),
        "status": "running",
        "conclusion": "not_found",
        "found": False,
        "source": "cli",
        "created_at": _now_iso(),
        "started_at": _now_iso(),
        "completed_at": None,
        "l3_paths": [],
        "gateway_candidates": [],
        "arp_evidence": [],
        "l2_paths": [],
        "terminal_candidates": [],
        "queried_devices": {"route": [], "arp": [], "mac": [], "lldp": []},
        "coverage_gaps": [],
        "freshness": {"route": None, "arp": None, "mac": None, "topology": None},
        "cache": {"route": "miss", "arp": "miss", "mac": "miss", "result": "miss"},
        "limits": {
            "max_l3_hops": limits.max_l3_hops,
            "max_l2_hops": limits.max_l2_hops,
            "max_devices": limits.max_devices,
            "max_candidates_per_hop": limits.max_candidates_per_hop,
        },
        "errors": [],
    }


def _trace_ip_uncached(
    target_ip: str,
    *,
    tenant_id: str = "tenant-default",
    start_device_id: str = "",
    vrf: str = "default",
    site_id: str = "",
    network_domain_id: str = "",
    force_refresh: bool = False,
    limits: TraceLimits | None = None,
    route_fresh_seconds: int = 300,
) -> dict[str, Any]:
    """Execute the four-stage CLI-only trace with bounded branching."""
    try:
        target_ip = str(ipaddress.ip_address(str(target_ip).strip()))
    except ValueError:
        return {
            "run_id": str(uuid.uuid4()),
            "target_ip": str(target_ip),
            "status": "failed",
            "conclusion": "invalid_ip",
            "found": False,
            "errors": ["目标 IP 地址无效"],
        }
    limits = limits or TraceLimits()
    vrf = _normalise_vrf(vrf)
    scope = {
        "tenant_id": str(tenant_id or "tenant-default"),
        "site_id": str(site_id or ""),
        "network_domain_id": str(network_domain_id or ""),
        "vrf": vrf,
    }
    result = _initial_result(target_ip, vrf, scope, limits)
    cache, scope_hash = _cache_for_scope(scope)
    result_key = _cache_key(
        cache,
        "result",
        scope_hash,
        target_ip,
        vrf,
        start_device_id or "auto",
    )
    if cache is not None and result_key and not force_refresh:
        cached_result = cache.get_json(result_key)
        if isinstance(cached_result, dict):
            collected_at = cached_result.get("completed_at") or cached_result.get("created_at")
            try:
                fresh = cache.is_fresh("result", collected_at)
            except Exception:
                fresh = False
            if fresh:
                cached = dict(cached_result)
                cached["run_id"] = result["run_id"]
                cached["cache"] = {**dict(cached.get("cache") or {}), "result": "hit"}
                cached["status"] = (
                    "completed"
                    if str(cached.get("conclusion") or "") == "managed_access_confirmed"
                    else str(cached.get("status") or "partial")
                )
                cached["cached_from_run_id"] = cached_result.get("run_id")
                return cached
    devices = _load_devices(start_device_id=start_device_id, site_id=site_id)
    by_id = _device_map(devices)
    if start_device_id:
        start_devices = [item for item in devices if str(item.get("id") or "") == str(start_device_id)]
    else:
        start_devices = [
            item for item in devices
            if str(item.get("role") or "").strip().lower() in CORE_ROLES
        ]
        if not start_devices:
            try:
                start_devices, _ = legacy._select_route_devices(devices)
            except Exception:
                start_devices = []
        if not start_devices:
            start_devices = devices
    if not devices or not start_devices:
        result["status"] = "failed"
        result["conclusion"] = "no_managed_start_device"
        result["coverage_gaps"].append("没有可用的纳管起始设备")
        result["completed_at"] = _now_iso()
        return result

    queried_device_ids: set[str] = set()
    route_branches: list[dict[str, Any]] = []
    frontier = [
        {
            "device": device,
            "vrf": vrf,
            "path": [],
            "visited": set(),
        }
        for device in start_devices
    ]
    direct_devices: list[tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]] ] = []
    route_fresh_seconds = max(1, int(route_fresh_seconds or 300))

    try:
        conn = get_db_connection()
    except Exception as exc:
        result["status"] = "failed"
        result["conclusion"] = "database_unavailable"
        result["errors"].append("无法读取拓扑与设备事实库")
        result["completed_at"] = _now_iso()
        logger.warning("[IPLocatorV2] database unavailable: %s", exc)
        return result

    try:
        while frontier and len(route_branches) < limits.max_devices:
            branch = frontier.pop(0)
            device = branch["device"]
            device_id = str(device.get("id") or "")
            if not device_id or device_id in branch["visited"]:
                continue
            if len(branch["path"]) >= limits.max_l3_hops:
                result["coverage_gaps"].append("L3 路径超过最大跳数")
                continue
            branch["visited"] = set(branch["visited"]) | {device_id}
            queried_device_ids.add(device_id)
            label = _device_label(device)
            if label not in result["queried_devices"]["route"]:
                result["queried_devices"]["route"].append(label)

            rows = [] if force_refresh else _cached_route_rows(device_id, target_ip, branch["vrf"], route_fresh_seconds)
            if rows:
                result["cache"]["route"] = "hit"
            else:
                command = _route_command(device, target_ip, branch["vrf"])
                try:
                    output = _run_cli_with_device_lease(
                        device,
                        "route",
                        lambda: legacy._send_command(device, command, force_refresh=True),
                        owner_id=f"{result['run_id']}:route",
                    )
                    rows = _parse_target_route_output(output, device, target_ip, branch["vrf"])
                    result["cache"]["route"] = "cli"
                    if rows:
                        _persist_observation(
                            tenant_id=tenant_id,
                            scope_hash=scope_hash,
                            network_domain_id=network_domain_id,
                            site_id=site_id,
                            vrf=branch["vrf"],
                            device_id=device_id,
                            kind="route",
                            target_ip=target_ip,
                            records=rows,
                            collected_at=_now_iso(),
                        )
                except Exception as exc:
                    result["errors"].append(f"{label} 路由查询失败")
                    result["coverage_gaps"].append(f"route_failed:{device_id}")
                    logger.debug("[IPLocatorV2] route query failed for %s: %s", label, exc)
                    continue
            best = _best_routes(rows, target_ip)
            if not best:
                result["coverage_gaps"].append(f"{label} 无目标路由")
                continue
            for row in best[: limits.max_candidates_per_hop]:
                hop = {
                    "device_id": device_id,
                    "device": label,
                    "vrf": branch["vrf"],
                    "prefix": row.get("destination") or "",
                    "protocol": row.get("protocol") or "",
                    "next_hop": row.get("next_hop") or "",
                    "interface": row.get("interface") or "",
                    "source": row.get("source") or "cache",
                    "age_seconds": _route_age_seconds(row.get("last_updated")),
                }
                next_path = branch["path"] + [hop]
                result["l3_paths"].append(hop)
                if hop["age_seconds"] is not None:
                    age = hop["age_seconds"]
                    result["freshness"]["route"] = max(int(result["freshness"]["route"] or 0), age)
                if _is_direct(row):
                    direct_devices.append((device, row, next_path))
                    result["gateway_candidates"].append({
                        "device_id": device_id,
                        "device": label,
                        "interface": row.get("interface") or "",
                        "prefix": row.get("destination") or "",
                        "vrf": branch["vrf"],
                    })
                    continue
                next_hop = str(row.get("next_hop") or "").strip()
                next_device = _find_next_hop_device(conn, next_hop, device)
                if not next_device:
                    result["coverage_gaps"].append(f"next_hop_unmanaged:{next_hop}")
                    continue
                next_id = str(next_device.get("id") or "")
                if next_id in branch["visited"]:
                    result["coverage_gaps"].append(f"route_loop:{next_id}")
                    continue
                if next_id not in by_id:
                    result["coverage_gaps"].append(f"next_hop_out_of_scope:{next_id}")
                    continue
                frontier.append({
                    "device": by_id[next_id],
                    "vrf": branch["vrf"],
                    "path": next_path,
                    "visited": branch["visited"],
                })
                route_branches.append({"device_id": next_id, "path": next_path})
    finally:
        conn.close()

    if not direct_devices:
        result["status"] = "partial" if result["l3_paths"] else "failed"
        result["conclusion"] = "no_direct_gateway" if result["l3_paths"] else "no_route"
        if not result["coverage_gaps"]:
            result["coverage_gaps"].append("未找到 Direct 三层终结设备")
        result["completed_at"] = _now_iso()
        return result

    # ARP is queried only on Direct gateway candidates.  A candidate may be
    # queried once even when ECMP branches converge on the same device.
    unique_gateways: dict[str, tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]] = {}
    for item in direct_devices:
        unique_gateways.setdefault(str(item[0].get("id") or ""), item)
    arp_hits: list[tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]] = []
    for device, route, l3_path in unique_gateways.values():
        label = _device_label(device)
        result["queried_devices"]["arp"].append(label)
        try:
            arp_key = _cache_key(cache, "arp", scope_hash, device.get("id") or "", vrf, target_ip)
            arp = None
            if cache is not None and arp_key and not force_refresh:
                cached_arp = cache.get_json(arp_key)
                if isinstance(cached_arp, dict) and cache.is_fresh("arp", cached_arp.get("collected_at")):
                    arp = cached_arp.get("record") or cached_arp
                    result["cache"]["arp"] = "hit"
            if arp is None:
                arp = _run_cli_with_device_lease(
                    device,
                    "arp",
                    lambda: legacy._targeted_arp_query(
                        device,
                        target_ip,
                        vrf if vrf != "default" else None,
                        force_refresh=force_refresh,
                    ),
                    owner_id=f"{result['run_id']}:arp",
                )
                if arp and cache is not None and arp_key:
                    cache.set_json(
                        arp_key,
                        {"record": dict(arp), "collected_at": _now_iso()},
                        kind="arp",
                        collected_at=_now_iso(),
                    )
                    result["cache"]["arp"] = "cli"
                if arp and result["cache"].get("arp") == "cli":
                    _persist_observation(
                        tenant_id=tenant_id,
                        scope_hash=scope_hash,
                        network_domain_id=network_domain_id,
                        site_id=site_id,
                        vrf=vrf,
                        device_id=str(arp.get("source_device_id") or device.get("id") or ""),
                        kind="arp",
                        target_ip=target_ip,
                        target_mac=str(arp.get("mac") or ""),
                        vlan_id=arp.get("vlan"),
                        records=dict(arp),
                        collected_at=_now_iso(),
                    )
        except Exception as exc:
            result["coverage_gaps"].append(f"arp_failed:{device.get('id')}")
            result["errors"].append(f"{label} ARP 查询失败")
            logger.debug("[IPLocatorV2] ARP query failed for %s: %s", label, exc)
            continue
        if not arp:
            result["coverage_gaps"].append(f"arp_not_found:{device.get('id')}")
            continue
        arp_item = dict(arp)
        arp_item.update({
            "device_id": str(arp_item.get("source_device_id") or device.get("id") or ""),
            "device": arp_item.get("source_device") or label,
            "collected_at": _now_iso(),
            "vrf": vrf,
            "route_prefix": route.get("destination") or "",
        })
        result["arp_evidence"].append(arp_item)
        arp_hits.append((device, arp_item, l3_path))

    if not arp_hits:
        result["status"] = "partial"
        result["conclusion"] = "arp_not_found"
        result["completed_at"] = _now_iso()
        return result

    # MAC recursion starts at each ARP hit, then follows only known topology
    # neighbours.  All SQL reads are finished before a CLI call is made.
    final_candidates: list[dict[str, Any]] = []
    visited_l2: set[tuple[str, str]] = set()
    try:
        conn = get_db_connection()
    except Exception:
        conn = None
    try:
        for gateway, arp, l3_path in arp_hits:
            mac = legacy._normalize_mac(str(arp.get("mac") or ""))
            if not mac:
                continue
            queue: list[tuple[dict[str, Any], list[dict[str, Any]], set[str]]] = [(gateway, [], set())]
            while queue and len(result["l2_paths"]) < limits.max_devices:
                current, path, visited = queue.pop(0)
                current_id = str(current.get("id") or "")
                if not current_id or current_id in visited or len(path) >= limits.max_l2_hops:
                    if len(path) >= limits.max_l2_hops:
                        result["coverage_gaps"].append("L2 路径超过最大跳数")
                    continue
                visited = set(visited) | {current_id}
                pair = (current_id, mac)
                if pair in visited_l2:
                    continue
                visited_l2.add(pair)
                label = _device_label(current)
                if label not in result["queried_devices"]["mac"]:
                    result["queried_devices"]["mac"].append(label)
                try:
                    vlan_hint = str(arp.get("vlan") or "")
                    mac_key = _cache_key(cache, "mac", scope_hash, current_id, vrf, mac, vlan_hint)
                    mac_result = None
                    records = []
                    status = {}
                    if cache is not None and mac_key and not force_refresh:
                        cached_mac = cache.get_json(mac_key)
                        if isinstance(cached_mac, dict) and cache.is_fresh("mac", cached_mac.get("collected_at")):
                            records = list(cached_mac.get("records") or [])
                            status = dict(cached_mac.get("status") or {})
                            result["cache"]["mac"] = "hit"
                    if not records and not (status and status.get("status") in {"unsupported", "query_failed"}):
                        mac_result = _run_cli_with_device_lease(
                            current,
                            "mac",
                            lambda: legacy._targeted_mac_query(current, mac, force_refresh=force_refresh),
                            owner_id=f"{result['run_id']}:mac",
                        )
                        records = list(mac_result or [])
                        status = getattr(mac_result, "status", {}) or {}
                        if records and cache is not None and mac_key:
                            cache.set_json(
                                mac_key,
                                {"records": records, "status": status, "collected_at": _now_iso()},
                                kind="mac",
                                collected_at=_now_iso(),
                            )
                            result["cache"]["mac"] = "cli"
                        if records and result["cache"].get("mac") == "cli":
                            _persist_observation(
                                tenant_id=tenant_id,
                                scope_hash=scope_hash,
                                network_domain_id=network_domain_id,
                                site_id=site_id,
                                vrf=vrf,
                                device_id=current_id,
                                kind="mac",
                                target_mac=mac,
                                vlan_id=vlan_hint,
                                records=records,
                                collected_at=_now_iso(),
                            )
                except Exception as exc:
                    records = []
                    status = {"status": "query_failed", "reason": str(exc)}
                    result["coverage_gaps"].append(f"mac_failed:{current_id}")
                if not records:
                    result["coverage_gaps"].append(f"mac_not_found:{current_id}")
                    if isinstance(status, dict) and status.get("status") in {"unsupported", "query_failed"}:
                        result["errors"].append(f"{label} MAC 查询{status.get('status')}")
                    continue
                for record in records[: limits.max_candidates_per_hop]:
                    port = str(record.get("port") or record.get("interface") or "").strip()
                    if not port:
                        result["coverage_gaps"].append(f"mac_port_missing:{current_id}")
                        continue
                    hop = {
                        "device_id": current_id,
                        "device": label,
                        "port": port,
                        "mac": mac,
                        "vlan": str(record.get("vlan") or arp.get("vlan") or ""),
                        "type": record.get("type") or "dynamic",
                        "source": "cli",
                        "collected_at": _now_iso(),
                    }
                    result["l2_paths"].append({"l3_path": l3_path, "hops": path + [hop]})
                    topology = []
                    if conn is not None:
                        topology = _topology_neighbors(conn, current_id, port)
                    if not topology:
                        topology = _run_cli_with_device_lease(
                            current,
                            "neighbor",
                            lambda: _lldp_neighbors(current, port),
                            owner_id=f"{result['run_id']}:neighbor",
                        )
                        if topology:
                            result["queried_devices"]["lldp"].append(label)
                            _persist_observation(
                                tenant_id=tenant_id,
                                scope_hash=scope_hash,
                                network_domain_id=network_domain_id,
                                site_id=site_id,
                                vrf=vrf,
                                device_id=current_id,
                                kind="neighbor",
                                records=topology,
                                collected_at=_now_iso(),
                            )
                    child_devices: list[dict[str, Any]] = []
                    for neighbor in topology[: limits.max_candidates_per_hop]:
                        neighbor_id = str(neighbor.get("neighbor_id") or "")
                        if neighbor_id and neighbor_id in by_id and neighbor_id not in visited:
                            child_devices.append(by_id[neighbor_id])
                        elif neighbor.get("neighbor_name"):
                            result["coverage_gaps"].append(f"neighbor_unmanaged:{neighbor.get('neighbor_name')}")
                    if child_devices:
                        hop["is_uplink"] = True
                        hop["neighbors"] = [
                            {"device_id": str(item.get("id") or ""), "device": _device_label(item)}
                            for item in child_devices
                        ]
                        for child in child_devices:
                            queue.append((child, path + [hop], visited))
                        continue

                    identity = _terminal_evidence(conn, current_id, port) if conn is not None else {"is_terminal": False}
                    hop["terminal_evidence"] = identity
                    if identity.get("is_terminal"):
                        final_candidates.append({
                            "device_id": current_id,
                            "device": label,
                            "port": port,
                            "vlan": hop["vlan"],
                            "mac": mac,
                            "l3_path": l3_path,
                            "l2_path": path + [hop],
                            "confidence": "high",
                        })
                    else:
                        result["coverage_gaps"].append(f"topology_incomplete:{current_id}:{port}")
    finally:
        if conn is not None:
            conn.close()

    result["terminal_candidates"] = final_candidates
    if final_candidates:
        result["found"] = True
        result["status"] = "completed"
        result["conclusion"] = "managed_access_confirmed"
        result["location"] = final_candidates[0]
        _persist_observation(
            tenant_id=tenant_id,
            scope_hash=scope_hash,
            network_domain_id=network_domain_id,
            site_id=site_id,
            vrf=vrf,
            device_id=str(final_candidates[0].get("device_id") or ""),
            kind="path",
            target_ip=target_ip,
            target_mac=str(final_candidates[0].get("mac") or ""),
            vlan_id=final_candidates[0].get("vlan"),
            records=final_candidates[0],
            coverage="targeted",
            collected_at=_now_iso(),
        )
    else:
        result["status"] = "partial"
        result["conclusion"] = "topology_incomplete" if result["l2_paths"] else "mac_not_found"
        if arp_hits and not result["l2_paths"]:
            result["conclusion"] = "arp_only"
            result["found"] = True
            result["location"] = {
                "device_id": arp_hits[0][1].get("device_id"),
                "device": arp_hits[0][1].get("device"),
                "port": arp_hits[0][1].get("interface") or "",
                "mac": arp_hits[0][1].get("mac") or "",
                "vlan": arp_hits[0][1].get("vlan") or "",
                "confidence": "arp_only",
            }
    result["freshness"]["arp"] = 0
    result["freshness"]["mac"] = 0 if result["l2_paths"] else None
    result["freshness"]["topology"] = 0 if result["l2_paths"] else None
    result["completed_at"] = _now_iso()
    if cache is not None and result_key and result.get("status") in {"completed", "partial"}:
        cache.set_json(
            result_key,
            result,
            kind="result",
            collected_at=result.get("completed_at"),
        )
    return result


def trace_ip(target_ip: str, **kwargs: Any) -> dict[str, Any]:
    """Run one trace with a Redis single-flight guard when available."""
    force_refresh = bool(kwargs.get("force_refresh", False))
    tenant_id = str(kwargs.get("tenant_id") or "tenant-default")
    site_id = str(kwargs.get("site_id") or "")
    network_domain_id = str(kwargs.get("network_domain_id") or "")
    vrf = _normalise_vrf(kwargs.get("vrf") or "default")
    start_device_id = str(kwargs.get("start_device_id") or "")
    scope = {
        "tenant_id": tenant_id,
        "site_id": site_id,
        "network_domain_id": network_domain_id,
        "vrf": vrf,
        "start_device_id": start_device_id,
    }
    cache, scope_hash = _cache_for_scope(scope)
    result_key = _cache_key(cache, "result", scope_hash, target_ip, vrf, start_device_id or "auto")
    lock_key = _cache_key(cache, "lock", scope_hash, target_ip, vrf, start_device_id or "auto")
    if cache is None or not lock_key or force_refresh:
        return _trace_ip_uncached(target_ip, **kwargs)

    # A completed result may have been written by another request before this
    # call acquired the lock.  The uncached function performs the authoritative
    # freshness check as well, so this is only a fast path.
    cached = cache.get_json(result_key)
    if isinstance(cached, dict) and cache.is_fresh("result", cached.get("completed_at") or cached.get("created_at")):
        cached = dict(cached)
        cached["cache"] = {**dict(cached.get("cache") or {}), "result": "hit"}
        return cached

    token = cache.acquire_lock(
        lock_key,
        ttl=max(30, int(kwargs.get("task_deadline_seconds") or 180)),
    )
    if token is None:
        # Let the first worker populate the shared result.  The bounded wait
        # prevents a request storm while still allowing progress when Redis is
        # unavailable or a previous worker died before its lock expired.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            time.sleep(0.2)
            cached = cache.get_json(result_key)
            if isinstance(cached, dict) and cache.is_fresh("result", cached.get("completed_at") or cached.get("created_at")):
                cached = dict(cached)
                cached["cache"] = {**dict(cached.get("cache") or {}), "result": "hit"}
                return cached
        return _trace_ip_uncached(target_ip, **kwargs)
    try:
        # The second freshness check is required after waiting to acquire the
        # lock; another worker may have completed just before us.
        return _trace_ip_uncached(target_ip, **kwargs)
    finally:
        cache.release_lock(lock_key, token)


async def trace_ip_async(target_ip: str, **kwargs: Any) -> dict[str, Any]:
    """Offload the blocking CLI trace from FastAPI's event loop."""
    return await asyncio.to_thread(trace_ip, target_ip, **kwargs)


def add_legacy_compatibility(result: dict[str, Any]) -> dict[str, Any]:
    """Expose the fields used by the existing IP locator page.

    The V2 response keeps its explicit evidence fields.  These aliases let
    the existing page roll out behind ``IP_LOCATOR_V2_ENABLED`` without a
    second interpretation of the terminal result.
    """
    enriched = dict(result)
    location = enriched.get("location")
    if isinstance(location, dict):
        enriched["locations"] = [{
            "switch_id": location.get("device_id") or "",
            "switch_name": location.get("device") or "",
            "port": location.get("port") or "",
            "vlan": location.get("vlan") or "",
            "type": "PATH_TRACED" if enriched.get("conclusion") == "managed_access_confirmed" else "ARP_DIRECT",
            "is_uplink": False,
            "note": "CLI 四阶段路径追踪结果",
        }]
        enriched["mac"] = location.get("mac") or enriched.get("mac")
        if enriched.get("mac"):
            enriched["mac_display"] = legacy._format_mac(str(enriched["mac"]))
    else:
        enriched.setdefault("locations", [])
    arp_evidence = enriched.get("arp_evidence") or []
    if arp_evidence and isinstance(arp_evidence[0], dict):
        arp = arp_evidence[0]
        enriched.setdefault("mac", arp.get("mac"))
        if enriched.get("mac"):
            enriched.setdefault("mac_display", legacy._format_mac(str(enriched["mac"])))
        enriched["arp_source"] = {
            "device_id": arp.get("device_id") or "",
            "device": arp.get("device") or "",
            "interface": arp.get("interface") or "",
            "vlan": arp.get("vlan") or "",
        }
    enriched["trace_status"] = {
        "managed_access_confirmed": "terminal",
        "arp_only": "arp_only",
        "topology_incomplete": "incomplete",
        "mac_not_found": "incomplete",
        "arp_not_found": "not_found",
        "no_route": "not_found",
        "no_direct_gateway": "incomplete",
    }.get(str(enriched.get("conclusion") or ""), str(enriched.get("status") or "unknown"))
    searched = enriched.get("queried_devices") or {}
    enriched["searched_devices"] = {
        "arp": list(searched.get("arp") or []),
        "mac": list(searched.get("mac") or []),
        "lldp": list(searched.get("lldp") or []),
    }
    cache = dict(enriched.get("cache") or {})
    cache.setdefault("enabled", True)
    cache.setdefault("arp_cache_hit", cache.get("arp") == "hit")
    cache.setdefault("ttl_seconds", 300)
    cache.setdefault("force_refresh", False)
    enriched["cache"] = cache
    return enriched
