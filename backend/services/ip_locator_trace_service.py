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
import hashlib
import inspect
import ipaddress
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from database import get_db_connection
from services import ip_locator_service as legacy

logger = logging.getLogger(__name__)

# Freeze the validated transport registry at import time so parser/driver
# adapters may be replaced in tests without changing the accepted platform
# contract.
_PLATFORM_DEVICE_TYPE_MAP = dict(legacy.PLATFORM_DEVICE_TYPE_MAP)


DIRECT_PROTOCOLS = {"direct", "connected", "local", "receive", "directly connected"}
LOCAL_DEVICE_PROTOCOLS = {"local", "receive"}
DISCARD_PROTOCOLS = {"blackhole", "discard", "reject", "unreachable", "prohibit"}
CORE_ROLES = {"core"}
_ROUTE_UNSUPPORTED_MARKERS = (
    "unrecognized command", "unknown command", "command not found",
    "not supported", "unsupported", "invalid input", "invalid command",
    "incomplete command", "wrong parameter", "too many parameters",
    "% invalid", "% incomplete",
)
_ROUTE_NOT_FOUND_MARKERS = (
    "network not in table", "no route to host", "no matching route",
    "no route information", "route not found", "no route found",
    "not in routing table", "destination unreachable",
)
_INCOMPLETE_CLI_MARKERS = (
    "--more--", "--- more ---", "press any key", "output truncated",
    "command timed out", "timeout",
)
_VIRTUAL_GATEWAY_MAC_PREFIXES = (
    "00005e0001",  # VRRP IPv4
    "00005e0002",  # VRRP IPv6
    "00000c07ac",  # HSRP v1
    "00000c9f",    # HSRP v2
    "0007b4",      # GLBP
)


class UnsupportedLocatorPlatform(ValueError):
    """Raised instead of silently issuing Cisco commands for an unknown platform."""


class _LocatorNeighborRecords(list[dict[str, Any]]):
    def __init__(self, records: Iterable[dict[str, Any]] = (), status: dict[str, Any] | None = None):
        super().__init__(records)
        self.status = dict(status or {})


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


def _redis_write_configured(cache: Any, key: Any) -> bool:
    """Only label a Redis write attempt when this adapter targets Redis."""
    return bool(
        cache is not None
        and key
        and str(getattr(cache, "backend", "redis") or "redis").strip().lower() == "redis"
    )


def _set_cache_source(
    result: dict[str, Any],
    stage: str,
    device: Mapping[str, Any] | None,
    source: str,
    *,
    vrf: str = "",
    variant: str = "target",
    redis_write_attempted: bool = False,
    redis_write_ack: Any = None,
) -> dict[str, Any]:
    """Keep the legacy stage summary and append/update per-device provenance.

    ``result.cache[stage]`` is intentionally retained for API compatibility,
    but a trace can visit several devices and that scalar is last-writer-wins.
    The detailed list lets operators distinguish mixed Redis, PostgreSQL, and
    CLI evidence without inspecting internal cache keys.
    """
    stage_name = str(stage or "").strip().lower()
    device = device if isinstance(device, Mapping) else {}
    device_id = str(device.get("id") or device.get("device_id") or "").strip()
    device_name = str(device.get("hostname") or device.get("ip_address") or device_id or "unknown")
    normalized_vrf = _normalise_vrf(vrf) if vrf else ""
    variant_name = str(variant or "target").strip().lower()

    summary = result.setdefault("cache", {})
    if isinstance(summary, dict):
        summary[stage_name] = str(source or "unknown")

    entries = result.setdefault("cache_provenance", [])
    if not isinstance(entries, list):
        entries = []
        result["cache_provenance"] = entries
    entry = next((item for item in reversed(entries) if (
        isinstance(item, dict)
        and item.get("stage") == stage_name
        and item.get("device_id") == device_id
        and item.get("vrf") == normalized_vrf
        and item.get("variant") == variant_name
    )), None)
    if entry is None:
        entry = {
            "stage": stage_name,
            "device_id": device_id,
            "device": device_name,
            "vrf": normalized_vrf,
            "variant": variant_name,
        }
        entries.append(entry)
    entry["source"] = str(source or "unknown")
    if redis_write_attempted:
        entry["redis_write_attempted"] = True
        entry["redis_write_ack"] = redis_write_ack is True
    return entry


def _copy_cached_result_for_request(cached: Mapping[str, Any]) -> dict[str, Any]:
    """Copy mutable provenance containers before annotating a cache hit."""
    result = dict(cached)
    cache_summary = result.get("cache")
    result["cache"] = dict(cache_summary) if isinstance(cache_summary, Mapping) else {}
    provenance = result.get("cache_provenance")
    if isinstance(provenance, list):
        result["cache_provenance"] = [
            dict(entry) if isinstance(entry, Mapping) else entry
            for entry in provenance
        ]
    return result


_OBSERVATION_SCHEMA_FIELDS = {
    "route": ("device_id", "vrf_name", "prefix", "protocol", "next_hop", "out_interface", "last_updated"),
    "arp": ("ip", "mac", "interface", "vlan", "vrf_name", "status"),
    "mac": ("mac", "port", "interface", "vlan", "bridge_domain", "status"),
    "neighbor": ("local_port", "neighbor_id", "neighbor_name", "neighbor_ip", "remote_port", "protocol", "status"),
    "path": ("device_id", "port", "ip", "mac", "vlan", "confidence", "l3_path", "l2_path"),
}


def _callable_fingerprint(function: Any) -> str:
    if not callable(function):
        return "missing"
    try:
        material = inspect.getsource(function)
    except (OSError, TypeError):
        code = getattr(function, "__code__", None)
        material = repr((getattr(function, "__module__", ""), getattr(function, "__qualname__", ""), getattr(code, "co_code", b"").hex(), getattr(code, "co_consts", ())))
    return hashlib.sha256(str(material).encode("utf-8")).hexdigest()


def _schema_version(kind: str) -> str:
    fields = _OBSERVATION_SCHEMA_FIELDS.get(str(kind or "").lower(), ())
    material = json.dumps(
        {"kind": str(kind or "").lower(), "fields": fields, "coverage": ("targeted", "full", "partial", "failed")},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"locator-schema:{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


def _pipeline_versions(
    operation: str,
    device: Mapping[str, Any] | None = None,
    target: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Fingerprint the selected CLI action, parser implementation and fact schema."""

    operation = str(operation or "").strip().lower()
    device = device if isinstance(device, Mapping) else {}
    target = target if isinstance(target, Mapping) else {}
    platform = str(target.get("platform") or device.get("platform") or "").strip().lower()
    profile_fields = {
        key: str(device.get(key) or target.get(key) or "")
        for key in (
            "platform_profile_id", "platform_release_id", "release_checksum",
            "command_checksum", "parser_template_version_id",
        )
        if device.get(key) or target.get(key)
    }
    if operation == "route":
        action_functions = (legacy._send_command, _route_command)
        parser_functions = (legacy.parse_routing_table, _parse_target_route_output, _route_row, _best_routes)
        schema_kind = "route"
    elif operation == "arp":
        action_functions = tuple(
            function for function in (
                getattr(legacy, "_targeted_arp_query_status", None),
                getattr(legacy, "_targeted_arp_query", None),
                getattr(legacy, "_collect_arp_snapshot", None) if target.get("snapshot") == "full" else None,
            ) if callable(function)
        )
        parser_functions = tuple(
            function for function in (
                _arp_query_parts,
                getattr(legacy, "_parse_arp_output_fallback", None),
                getattr(legacy, "_targeted_arp_query_status", None),
            ) if callable(function)
        )
        schema_kind = "arp"
    elif operation == "mac":
        action_functions = tuple(
            function for function in (
                _targeted_mac_query_for_trace,
                getattr(legacy, "_targeted_mac_query", None),
                getattr(legacy, "_collect_mac_table_snapshot", None) if target.get("snapshot") == "full" else None,
            ) if callable(function)
        )
        parser_functions = tuple(
            function for function in (
                getattr(legacy, "_parse_mac_output", None),
                getattr(legacy, "_parse_mac_table_line", None),
                _targeted_mac_query_for_trace,
            ) if callable(function)
        )
        schema_kind = "mac"
    elif operation == "path":
        action_functions = (_trace_contract_version,)
        parser_functions = (_trace_contract_version,)
        schema_kind = "path"
    else:
        action_functions = tuple(
            function for function in (getattr(legacy, "_collect_lldp_from_device", None),) if callable(function)
        )
        parser_functions = tuple(
            function for function in (
                getattr(legacy, "_collect_lldp_from_device", None), _lldp_neighbors,
            ) if callable(function)
        )
        schema_kind = "neighbor"
    action_material = {
        "contract": "locator-cli-action-v2",
        "operation": operation,
        "platform": platform,
        "profile": profile_fields,
        "target_mode": str(target.get("snapshot") or "targeted"),
        # Keep command material out of task metadata; the digest still fences
        # changes to exact route commands and vendor command selection.
        "command_digest": hashlib.sha256(str(target.get("command") or "").encode("utf-8")).hexdigest(),
        "functions": [_callable_fingerprint(function) for function in action_functions],
    }
    parser_material = {
        "contract": "locator-cli-parser-v2",
        "operation": operation,
        "platform": platform,
        "functions": [_callable_fingerprint(function) for function in parser_functions],
        "schema_version": _schema_version(schema_kind),
    }
    encode = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "action_version": f"locator-action:{hashlib.sha256(encode(action_material).encode('utf-8')).hexdigest()}",
        "parser_version": f"locator-parser:{hashlib.sha256(encode(parser_material).encode('utf-8')).hexdigest()}",
        "schema_version": _schema_version(schema_kind),
    }


def _trace_contract_version() -> str:
    from services.topology_lldp_snapshot_service import lldp_snapshot_versions

    all_functions = (
        _route_command, legacy.parse_routing_table, _parse_target_route_output, _route_row, _best_routes,
        _arp_query_parts, getattr(legacy, "_targeted_arp_query_status", None),
        getattr(legacy, "_parse_arp_output_fallback", None), _targeted_mac_query_for_trace,
        getattr(legacy, "_parse_mac_output", None), getattr(legacy, "_parse_mac_table_line", None),
        getattr(legacy, "_collect_lldp_from_device", None), _lldp_neighbors,
        _load_lldp_snapshot, _record_topology_snapshot_dependency, lldp_snapshot_versions,
    )
    material = {
        "functions": [_callable_fingerprint(function) for function in all_functions],
        "schemas": {kind: _schema_version(kind) for kind in sorted(_OBSERVATION_SCHEMA_FIELDS)},
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _record_observation(result: dict[str, Any] | None, observation: Mapping[str, Any] | None) -> None:
    if not isinstance(result, dict) or not isinstance(observation, Mapping):
        return
    key = str(observation.get("observation_key") or "").strip()
    if not key:
        return
    manifest = result.get("dependency_manifest")
    if not isinstance(manifest, dict):
        return
    entries = manifest.setdefault("observations", [])
    if not isinstance(entries, list):
        entries = []
        manifest["observations"] = entries
    item = {
        "observation_key": key,
        "generation": int(observation.get("generation") or 0),
        "observation_kind": str(observation.get("observation_kind") or ""),
        "device_id": str(observation.get("device_id") or ""),
        "target_ip": str(observation.get("target_ip") or ""),
        "target_mac": str(observation.get("target_mac") or ""),
        "action_version": str(observation.get("action_version") or ""),
        "parser_version": str(observation.get("parser_version") or ""),
        "schema_version": str(observation.get("schema_version") or ""),
    }
    if item not in entries:
        entries.append(item)


def _manifest_is_current_for_code(manifest: Any) -> bool:
    if not isinstance(manifest, Mapping) or str(manifest.get("contract_version") or "") != _trace_contract_version():
        return False
    try:
        from services.ip_locator_task_service import locator_dependency_manifest_is_current

        return locator_dependency_manifest_is_current(manifest)
    except Exception:
        return False


def _cached_observation_is_current(
    cached: Any,
    *,
    expected_versions: Mapping[str, str],
    result: dict[str, Any],
    cache: Any,
    kind: str,
) -> dict[str, Any] | None:
    if not isinstance(cached, Mapping):
        return None
    metadata = cached.get("_locator_dependency")
    if not isinstance(metadata, Mapping):
        return None
    manifest = result.get("dependency_manifest")
    topology = manifest.get("topology") if isinstance(manifest, Mapping) else None
    if not isinstance(topology, Mapping):
        return None
    if (
        metadata.get("scope") != "global"
        or metadata.get("topology_generation") != topology.get("generation")
        or any(str(metadata.get(key) or "") != str(expected_versions.get(key) or "") for key in (
            "action_version", "parser_version", "schema_version",
        ))
    ):
        return None
    try:
        freshness_kind = "negative" if cached.get("negative") else str(kind or "")
        if not freshness_kind or not cache.is_fresh(
            freshness_kind,
            cached.get("collected_at"),
        ):
            return None
    except Exception:
        return None
    key = str(metadata.get("observation_key") or "").strip()
    if not key:
        return None
    try:
        from services.ip_locator_task_service import (
            get_locator_dependency_generation,
            get_locator_observation,
        )

        current_topology = get_locator_dependency_generation("topology:global")
        if not current_topology or int(current_topology.get("generation") or 0) != int(topology.get("generation") or 0):
            return None
        observation = get_locator_observation(key)
    except Exception:
        return None
    if not isinstance(observation, Mapping) or any(
        str(observation.get(name) or "") != str(metadata.get(name) or "")
        for name in ("observation_key", "action_version", "parser_version", "schema_version")
    ) or int(observation.get("generation") or 0) != int(metadata.get("generation") or 0):
        return None
    _record_observation(result, observation)
    return dict(cached)


def _fenced_observation_payload(
    result: Mapping[str, Any],
    payload: Mapping[str, Any],
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = result.get("dependency_manifest")
    topology = manifest.get("topology") if isinstance(manifest, Mapping) else {}
    return {
        **dict(payload),
        "_locator_dependency": {
            "scope": "global",
            "topology_generation": int((topology or {}).get("generation") or 0),
            "observation_key": str(observation.get("observation_key") or ""),
            "generation": int(observation.get("generation") or 0),
            "action_version": str(observation.get("action_version") or ""),
            "parser_version": str(observation.get("parser_version") or ""),
            "schema_version": str(observation.get("schema_version") or ""),
        },
    }


def _pending_fact_invalidation(scope_hash: str, target_ip: str) -> bool:
    try:
        from services.ip_locator_task_service import has_pending_locator_invalidation

        return has_pending_locator_invalidation(scope_hash=scope_hash, target_ip=target_ip)
    except Exception as exc:
        # Do not trust a complete Redis result if PG cannot confirm its
        # dependency-invalidation state.
        logger.debug("[IPLocatorV2] invalidation state unavailable (%s)", type(exc).__name__)
        return True


def _authorization_scope_hash(device_ids: Iterable[str] | None) -> str:
    if device_ids is None:
        return "unrestricted-internal"
    try:
        from services.ip_locator_cache_service import IPLocatorCacheService

        return IPLocatorCacheService.scope_hash({
            "authorized_device_ids": sorted({str(item) for item in device_ids if str(item)}),
        })
    except Exception:
        return "restricted"


def _normalise_vrf(value: Any) -> str:
    text = str(value or "").strip()
    return text or "default"


def _device_label(device: dict[str, Any]) -> str:
    return str(device.get("hostname") or device.get("ip_address") or device.get("id") or "unknown")


def _normalise_platform(device: dict[str, Any]) -> str:
    vendor = str(device.get("vendor") or "").strip()
    raw_platform = str(device.get("platform") or "").strip().lower()
    if not raw_platform and not vendor:
        raise UnsupportedLocatorPlatform("device vendor/platform is missing")
    try:
        resolved = legacy.resolve_device_platform_context(device)
        platform = str(resolved.get("catalog_platform") or resolved.get("public_platform") or "").strip().lower()
    except Exception:
        from core.platform_utils import normalize_device_platform

        platform = str(normalize_device_platform(vendor, raw_platform) or "").strip().lower()
    if not platform or platform not in _PLATFORM_DEVICE_TYPE_MAP:
        raise UnsupportedLocatorPlatform(f"no registered CLI driver for platform {platform or '<empty>'}")
    return platform


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
    if platform in {
        "cisco_ios", "cisco_nxos", "cisco_iosxr", "arista_eos", "ruijie_rgos",
        "dptech_ios", "zte_zxros", "raisecom_ros", "maipu",
    }:
        return f"show ip route {target_ip}"
    raise UnsupportedLocatorPlatform(f"no target-route command for platform {platform}")


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


def _is_newer_evidence(candidate_at: Any, current_at: Any) -> bool:
    candidate_age = _route_age_seconds(candidate_at)
    current_age = _route_age_seconds(current_at)
    return bool(candidate_age is not None and (current_age is None or candidate_age < current_age))


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
                    if age is not None and age <= max(1, int(fresh_seconds)):
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
    for raw_row in rows:
        row = dict(raw_row)
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


def _route_output_status(output: Any) -> str:
    """Classify an empty targeted route response without inventing negatives."""
    normalized = str(output or "").strip().lower()
    if not normalized:
        return "query_failed"
    if any(marker in normalized for marker in _ROUTE_UNSUPPORTED_MARKERS):
        return "unsupported"
    if any(marker in normalized for marker in _INCOMPLETE_CLI_MARKERS):
        return "incomplete"
    if any(marker in normalized for marker in _ROUTE_NOT_FOUND_MARKERS):
        return "not_found"
    return "parse_incomplete"


def _is_virtual_gateway_mac(value: Any) -> bool:
    try:
        normalized = legacy._normalize_mac(str(value or ""))
    except Exception:
        normalized = re.sub(r"[^0-9a-f]", "", str(value or "").lower())
    return any(normalized.startswith(prefix) for prefix in _VIRTUAL_GATEWAY_MAC_PREFIXES)


def _local_interface_for_mac(device_id: str, mac: str) -> str:
    """Match an ARP MAC against the source device's own interface inventory."""
    if not device_id or not mac:
        return ""
    try:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT interface_name, mac_address FROM interfaces WHERE device_id = ?",
                (device_id,),
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("[IPLocatorV2] local MAC inventory lookup failed (%s)", type(exc).__name__)
        return ""
    for row in rows:
        raw_mac = str(row.get("mac_address") or "")
        try:
            candidate = legacy._normalize_mac(raw_mac)
        except Exception:
            candidate = re.sub(r"[^0-9a-f]", "", raw_mac.lower())
        if candidate and candidate == mac:
            return str(row.get("interface_name") or "").strip()
    return ""


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


def _load_devices(
    *,
    tenant_id: str = "tenant-default",
    start_device_id: str = "",
    site_id: str = "",
    authorized_device_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    try:
        devices = [
            dict(item)
            for item in legacy._load_eligible_devices(
                tenant_id=str(tenant_id or "tenant-default"),
                site_id=str(site_id) if site_id else None,
                device_ids=authorized_device_ids,
            )
        ]
    except Exception as exc:
        logger.warning("[IPLocatorV2] eligible device load failed: %s", exc)
        return []
    expected_tenant = str(tenant_id or "tenant-default").strip()
    devices = [
        item for item in devices
        if str(item.get("tenant_id") or "tenant-default").strip() == expected_tenant
    ]
    if site_id:
        requested_site = str(site_id).strip().lower()
        devices = [
            item for item in devices
            if str(item.get("site_id") or item.get("site") or "").strip().lower() == requested_site
        ]
    if authorized_device_ids is not None:
        allowed_ids = {str(item) for item in authorized_device_ids if str(item)}
        devices = [item for item in devices if str(item.get("id") or "") in allowed_ids]
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
    task_context: dict[str, Any],
    wait_seconds: int = 30,
) -> Any:
    """Execute or join the scoped PostgreSQL task under a pooled SSH lease."""
    del owner_id  # Task and retained session owners have their own fencing IDs.
    from services.ip_locator_cli_service import run_locator_cli_query

    return run_locator_cli_query(
        device,
        operation,
        callback,
        task_context=task_context,
        wait_seconds=wait_seconds,
    )


def _cli_result_parts(value: Any) -> tuple[Any, str, str, dict[str, Any]]:
    """Unwrap a shared task without resetting its original observation age."""
    try:
        from services.ip_locator_cli_service import LocatorCLIResult

        if isinstance(value, LocatorCLIResult):
            return value.value, value.collected_at, value.task_id, value.status
    except Exception:
        pass
    status = getattr(value, "status", {}) or {}
    return value, _now_iso(), "", dict(status) if isinstance(status, dict) else {}


def _arp_query_parts(value: Any, metadata: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str]:
    """Unwrap a structured ARP query while keeping legacy test adapters usable."""
    statuses = {"found", "not_found", "unsupported", "query_failed", "parse_incomplete", "ambiguous"}
    if isinstance(value, dict) and value.get("status") in statuses and "record" in value:
        record = value.get("record")
        return (dict(record) if isinstance(record, dict) else None), str(value.get("status"))
    status = str((metadata or {}).get("status") or "").strip().lower()
    if status in statuses:
        return (dict(value) if isinstance(value, dict) else None), status
    if isinstance(value, dict) and value:
        return dict(value), "found"
    return None, "not_found"


def _targeted_mac_query_for_trace(device: dict[str, Any], target_mac: str) -> Any:
    """Disable legacy per-target full-table scans for the bounded V2 trace."""
    query = getattr(legacy, "_targeted_mac_query")
    try:
        return query(
            device,
            target_mac,
            force_refresh=True,
            allow_full_table_fallback=False,
        )
    except TypeError as exc:
        # Keep simple legacy test doubles compatible; production uses the
        # explicit bounded-fallback parameter above.
        if "allow_full_table_fallback" not in str(exc):
            raise
        return query(device, target_mac, force_refresh=True)


def _cli_task_context(
    *,
    scope: dict[str, Any],
    scope_hash: str,
    target_ip: str,
    operation: str,
    device: Mapping[str, Any] | None = None,
    force_refresh: bool,
    durable_run_id: str = "",
    run_owner_id: str = "",
    target_mac: str = "",
    vlan_id: Any = None,
    bridge_domain: str = "",
    target: dict[str, Any] | None = None,
    cancel_check: Any = None,
) -> dict[str, Any]:
    versions = _pipeline_versions(operation, device, target)
    return {
        "tenant_id": str(scope.get("tenant_id") or "tenant-default"),
        "scope_hash": str(scope_hash or ""),
        "network_domain_id": str(scope.get("network_domain_id") or ""),
        "site_id": str(scope.get("site_id") or ""),
        "vrf_name": str(scope.get("vrf") or "default"),
        "start_device_id": str(scope.get("start_device_id") or ""),
        "authorization_scope_hash": str(scope.get("authorization_scope_hash") or ""),
        "target_ip": str(target_ip or ""),
        "target_mac": str(target_mac or ""),
        "vlan_id": vlan_id,
        "bridge_domain": str(bridge_domain or ""),
        "target": dict(target or {}),
        "force_refresh": bool(force_refresh),
        "durable_run_id": str(durable_run_id or ""),
        "run_owner_id": str(run_owner_id or ""),
        "cancel_check": cancel_check,
        "action_version": versions["action_version"],
        "parser_version": versions["parser_version"],
        "schema_version": versions["schema_version"],
    }


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
    query_task_id: str = "",
    fresh_seconds: int | None = None,
    retain_seconds: int | None = None,
    result: dict[str, Any] | None = None,
    device: Mapping[str, Any] | None = None,
    target: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Persist a CLI observation in PostgreSQL before projecting it to Redis."""
    try:
        from services.ip_locator_task_service import upsert_locator_observation
        from core.config import settings

        cache, _ = _cache_for_scope({"tenant_id": tenant_id})
        policy = cache.policy(kind) if cache is not None else None
        default_fresh = int(getattr(settings, f"IP_LOCATOR_{kind.upper()}_FRESH_SECONDS", 300))
        default_retain = int(getattr(settings, f"IP_LOCATOR_{kind.upper()}_RETAIN_SECONDS", default_fresh))
        observed_at = collected_at or _now_iso()
        action_version = ""
        parser_version = ""
        if query_task_id:
            try:
                from services.ip_locator_task_service import get_locator_task

                task = get_locator_task(query_task_id) or {}
                action_version = str(task.get("action_version") or "")
                parser_version = str(task.get("parser_version") or "")
            except Exception:
                pass
        versions = _pipeline_versions(kind, device, target)
        persisted = upsert_locator_observation(
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
            action_version=action_version or versions["action_version"],
            parser_version=parser_version or versions["parser_version"],
            schema_version=versions["schema_version"],
            fresh_seconds=(fresh_seconds if fresh_seconds is not None else (policy.fresh_seconds if policy else default_fresh)),
            retain_seconds=(retain_seconds if retain_seconds is not None else (policy.retain_seconds if policy else default_retain)),
            query_task_id=query_task_id or None,
        )
        if bool((persisted or {}).get("stale_ignored")):
            return None
        _record_observation(result, persisted)
        return persisted
    except Exception as exc:
        # PostgreSQL is the source of truth. A successful device response is
        # not eligible for Redis projection if its durable fact could not be
        # committed.
        logger.warning("[IPLocatorV2] observation persistence failed (%s)", type(exc).__name__)
        return None


def _is_complete_full_snapshot(status: Any, records: Any) -> bool:
    """Require an explicit successful full-coverage marker before reconciling."""
    if not isinstance(status, dict):
        return False
    status_name = str(status.get("status") or "").strip().lower()
    coverage = str(status.get("coverage") or "").strip().lower()
    if status_name not in {"found", "not_found"} or coverage != "full":
        return False
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        return False
    return bool(records) if status_name == "found" else not records


def _configured_observation_retain_seconds(cache: Any, kind: str) -> int:
    try:
        policy = cache.policy(kind) if cache is not None else None
        if policy is not None:
            return max(15, int(policy.retain_seconds))
        from core.config import settings

        default_retain = 1800 if kind == "arp" else 900
        return max(15, int(getattr(settings, f"IP_LOCATOR_{kind.upper()}_RETAIN_SECONDS", default_retain)))
    except Exception:
        return 1800 if kind == "arp" else 900


def _snapshot_retain_seconds(cache: Any, kind: str, negative: bool) -> int:
    return 15 if negative else _configured_observation_retain_seconds(cache, kind)


def _snapshot_failure_reason(status: Any, records: Any) -> str:
    if not isinstance(status, dict):
        return "status_missing"
    status_name = str(status.get("status") or "").strip().lower()
    coverage = str(status.get("coverage") or "").strip().lower()
    if status_name in {"found", "not_found"}:
        if coverage != "full":
            return f"coverage_{coverage or 'unspecified'}"
        return "records_invalid"
    return status_name or "status_missing"


def _reconcile_full_snapshot_absences(
    *,
    tenant_id: str,
    scope_hash: str,
    network_domain_id: str,
    site_id: str,
    vrf: str,
    device_id: str,
    kind: str,
    records: list[dict[str, Any]],
    status: dict[str, Any],
    collected_at: str,
    query_task_id: str,
    retain_seconds: int,
    versions: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not _is_complete_full_snapshot(status, records):
        return {"applied": False, "reason": _snapshot_failure_reason(status, records)}
    try:
        from services.ip_locator_task_service import reconcile_locator_snapshot_absences

        return reconcile_locator_snapshot_absences(
            tenant_id=tenant_id,
            scope_hash=scope_hash,
            network_domain_id=network_domain_id,
            site_id=site_id,
            vrf_name=vrf,
            device_id=device_id,
            observation_kind=kind,
            records=records,
            snapshot_status=status,
            collected_at=collected_at,
            query_task_id=query_task_id or None,
            action_version=str((versions or {}).get("action_version") or ""),
            parser_version=str((versions or {}).get("parser_version") or ""),
            schema_version=str((versions or {}).get("schema_version") or ""),
            retain_seconds=retain_seconds,
        )
    except Exception as exc:
        logger.warning("[IPLocatorV2] full snapshot reconciliation failed (%s)", type(exc).__name__)
        return None


def _find_fresh_observation(
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
    versions: Mapping[str, str] | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        from services.ip_locator_task_service import find_locator_observation

        observation = find_locator_observation(
            tenant_id=tenant_id,
            scope_hash=scope_hash,
            network_domain_id=network_domain_id,
            site_id=site_id,
            vrf_name=vrf,
            device_id=device_id,
            observation_kind=kind,
            target_ip=target_ip,
            target_mac=target_mac,
            vlan_id=vlan_id,
            action_version=(versions or {}).get("action_version"),
            parser_version=(versions or {}).get("parser_version"),
            schema_version=(versions or {}).get("schema_version"),
        )
        _record_observation(result, observation)
        return observation
    except Exception as exc:
        logger.debug("[IPLocatorV2] PostgreSQL observation lookup skipped (%s)", type(exc).__name__)
        return None


def _include_evidence_timestamp(result: dict[str, Any], collected_at: Any) -> None:
    if not collected_at:
        return
    current = result.get("evidence_collected_at")
    if not current:
        result["evidence_collected_at"] = str(collected_at)
        return
    current_age = _route_age_seconds(current)
    new_age = _route_age_seconds(collected_at)
    if new_age is not None and (current_age is None or new_age > current_age):
        result["evidence_collected_at"] = str(collected_at)


def _find_next_hop_device_candidates(
    conn: Any,
    next_hop: str,
    eligible_devices: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve every in-scope device matching a next-hop IP.

    The legacy helper uses ``fetchone`` across three projections, which can
    silently select the first device when overlapping management/loopback IPs
    exist. Keep the locator boundary explicit and let the caller report
    ambiguity instead of guessing.
    """
    if not next_hop or str(next_hop).strip().lower() in DIRECT_PROTOCOLS:
        return []
    eligible_ids = {str(device_id) for device_id in eligible_devices if str(device_id)}
    if not eligible_ids:
        return []
    placeholders = ", ".join("?" for _ in eligible_ids)
    allowed_ids = sorted(eligible_ids)
    queries = (
        (
            "SELECT id, hostname, role, platform, ip_address FROM devices "
            f"WHERE TRIM(ip_address) = ? AND id IN ({placeholders})",
        ),
        (
            "SELECT d.id, d.hostname, d.role, d.platform, d.ip_address "
            "FROM ip_addresses ip JOIN devices d ON ip.device_id = d.id "
            f"WHERE TRIM(ip.address) = ? AND d.id IN ({placeholders})",
        ),
        (
            "SELECT d.id, d.hostname, d.role, d.platform, d.ip_address "
            "FROM ip_inventory inv JOIN devices d ON inv.device_id = d.id "
            f"WHERE TRIM(inv.ip) = ? AND d.id IN ({placeholders})",
        ),
    )
    matches: dict[str, dict[str, Any]] = {}
    for (query,) in queries:
        try:
            rows = conn.execute(query, [str(next_hop).strip(), *allowed_ids]).fetchall()
        except Exception:
            continue
        for raw in rows:
            item = dict(raw)
            device_id = str(item.get("id") or "")
            if device_id in eligible_ids and device_id in eligible_devices:
                # Prefer the authorized inventory record; database projections
                # only establish the address-to-ID relation.
                matches[device_id] = dict(eligible_devices[device_id])
    return [matches[device_id] for device_id in sorted(matches)]


def _topology_neighbors(conn: Any, device_id: str, port: str) -> list[dict[str, Any]]:
    """Return all active topology candidates for a canonical local port."""
    normalized = legacy.normalize_interface_name(port).lower()
    if not normalized:
        return []
    try:
        from core.config import settings

        topology_fresh_seconds = int(getattr(settings, "IP_LOCATOR_TOPOLOGY_FRESH_SECONDS", 172800))
    except Exception:
        topology_fresh_seconds = 172800
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
        observed_at = row.get("last_seen") or row.get("updated_at")
        observed_age = _route_age_seconds(observed_at)
        if observed_age is None or observed_age > topology_fresh_seconds:
            continue
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


def _lldp_neighbors(
    device: dict[str, Any],
    port: str,
    *,
    records: Any = None,
    source_status: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Normalize a full-device neighbor snapshot for one local port."""
    if records is None:
        try:
            records = legacy._collect_lldp_from_device(device)
        except Exception as exc:
            logger.debug("[IPLocatorV2] neighbor CLI fallback failed (%s)", type(exc).__name__)
            return _LocatorNeighborRecords([], {"status": "query_failed"})
    status = dict(
        source_status
        or getattr(records, "status", {})
        or {}
    )
    if str(status.get("status") or "").lower() in {
        "unsupported", "query_failed", "parse_incomplete", "parse_failed",
        "unsupported_command", "truncated", "lldp_disabled", "command_failed",
    }:
        return _LocatorNeighborRecords([], status)
    wanted = legacy.normalize_interface_name(port).lower()
    result = []
    for item in records or []:
        local = legacy.normalize_interface_name(item.get("local_interface") or "").lower()
        if local != wanted or not item.get("neighbor"):
            continue
        result.append({
            "neighbor_id": item.get("neighbor_id") or "",
            "neighbor_name": item.get("neighbor") or "",
            "neighbor_port": item.get("neighbor_port") or "",
            "neighbor_ip": item.get("neighbor_ip") or "",
            "evidence": item.get("evidence") or "lldp_cli",
            "confidence": 0.6,
            "protocol": item.get("protocol") or "",
        })
    return _LocatorNeighborRecords(
        result,
        {
            **status,
            "status": "found" if result else "not_found",
            "record_count": len(result),
        },
    )


def _snapshot_cache_is_after_latest_attempt(collected_at: Any, marker: Mapping[str, Any] | None) -> bool:
    if not isinstance(marker, Mapping):
        return True
    state = str(marker.get("state") or "")
    cutoff = (
        marker.get("completed_at")
        if state == "complete"
        else marker.get("started_at")
        if state in {"collecting", "failed"}
        else None
    )
    if not cutoff:
        return True
    collected_age = _route_age_seconds(collected_at)
    cutoff_age = _route_age_seconds(cutoff)
    return collected_age is not None and cutoff_age is not None and collected_age <= cutoff_age


def _snapshot_is_newer(candidate_at: Any, current_at: Any) -> bool:
    candidate_age = _route_age_seconds(candidate_at)
    current_age = _route_age_seconds(current_at)
    return candidate_age is not None and (current_age is None or candidate_age < current_age)


def _record_topology_snapshot_dependency(result: dict[str, Any], marker: Mapping[str, Any]) -> None:
    manifest = result.get("dependency_manifest")
    if not isinstance(manifest, dict):
        return
    try:
        from services.topology_lldp_snapshot_service import snapshot_dependency

        dependency = snapshot_dependency(marker)
    except Exception:
        return
    dependencies = manifest.setdefault("topology_snapshots", [])
    if not isinstance(dependencies, list):
        dependencies = []
        manifest["topology_snapshots"] = dependencies
    if dependency not in dependencies:
        dependencies.append(dependency)


def _load_lldp_snapshot(
    device: dict[str, Any],
    port: str,
    *,
    cache: Any,
    scope: dict[str, Any],
    scope_hash: str,
    tenant_id: str,
    target_ip: str,
    network_domain_id: str,
    site_id: str,
    vrf: str,
    force_refresh: bool,
    durable_run_id: str,
    run_owner_id: str,
    cancel_check: Any,
    result: dict[str, Any],
    wait_seconds: int,
) -> tuple[list[dict[str, Any]], str, str, dict[str, Any]]:
    """Reuse a complete topology snapshot before falling back to device CLI."""
    device_id = str(device.get("id") or "")
    key = _cache_key(cache, "topology", scope_hash, device_id, "full")
    neighbor_target = {
        "snapshot": "full",
        "platform": _normalise_platform(device),
        "profile_id": str(device.get("platform_profile_id") or ""),
    }
    neighbor_versions = _pipeline_versions("neighbor", device, neighbor_target)
    snapshot: list[dict[str, Any]] = []
    collected_at = ""
    task_id = ""
    snapshot_status: dict[str, Any] = {}
    loaded = False
    negative = False
    shared_marker: dict[str, Any] | None = None
    shared_dependency_marker: Mapping[str, Any] | None = None
    shared_selected = False
    pending_invalidation = _pending_fact_invalidation(scope_hash, target_ip)

    if not force_refresh:
        try:
            from services.topology_lldp_snapshot_service import (
                get_lldp_snapshot_marker,
                load_complete_lldp_snapshot,
            )

            shared_marker = get_lldp_snapshot_marker(device_id)
            if shared_marker and not pending_invalidation:
                shared = load_complete_lldp_snapshot(
                    device,
                    cache=cache,
                    marker=shared_marker,
                )
                if shared:
                    snapshot = list(shared.get("neighbors") or [])
                    collected_at = str(shared.get("collected_at") or "")
                    snapshot_status = {
                        "status": "found" if snapshot else "not_found",
                        "coverage": "full",
                        "source": "topology_collector",
                    }
                    loaded = True
                    shared_selected = True
                    shared_dependency_marker = shared.get("marker") or shared_marker
                    shared_source = str(shared.get("source") or "postgres")
                    _set_cache_source(
                        result,
                        "topology",
                        device,
                        shared_source,
                        vrf=vrf,
                        variant="shared_snapshot",
                        redis_write_attempted=shared.get("redis_write_attempted") is True,
                        redis_write_ack=shared.get("redis_written"),
                    )
        except Exception as exc:
            logger.debug("[IPLocatorV2] shared topology snapshot unavailable (%s)", type(exc).__name__)

    if (
        cache is not None
        and key
        and not force_refresh
        and not pending_invalidation
    ):
        candidate_result = dict(result)
        candidate_manifest = dict(result.get("dependency_manifest") or {})
        candidate_manifest["observations"] = list(candidate_manifest.get("observations") or [])
        candidate_result["dependency_manifest"] = candidate_manifest
        cached = cache.get_json(key)
        cached = _cached_observation_is_current(
            cached,
            expected_versions=neighbor_versions,
            result=candidate_result,
            cache=cache,
            kind="topology",
        )
        cached_at = str(cached.get("collected_at") or "") if isinstance(cached, dict) else ""
        cached_negative = bool(cached.get("negative")) if isinstance(cached, dict) else False
        if (
            isinstance(cached, dict)
            and cached_at
            and _snapshot_cache_is_after_latest_attempt(cached_at, shared_marker)
            and cache.is_fresh("negative" if cached_negative else "topology", cached_at)
            and (not loaded or _snapshot_is_newer(cached_at, collected_at))
        ):
            snapshot = list(cached.get("neighbors") or [])
            collected_at = cached_at
            negative = cached_negative
            snapshot_status = {"status": "not_found" if negative else "found"}
            loaded = True
            shared_selected = False
            for observation in candidate_manifest.get("observations") or []:
                _record_observation(result, observation)
            _set_cache_source(
                result,
                "topology",
                device,
                "negative_redis" if negative else "redis",
                vrf=vrf,
                variant="port_neighbor",
            )

    if not force_refresh and not pending_invalidation:
        observation = _find_fresh_observation(
            tenant_id=tenant_id,
            scope_hash=scope_hash,
            network_domain_id=network_domain_id,
            site_id=site_id,
            vrf=vrf,
            device_id=device_id,
            kind="neighbor",
            versions=neighbor_versions,
            result=None if loaded else result,
        )
        if observation:
            stored = observation.get("records") or []
            observation_at = str(observation.get("collected_at") or "")
            observation_negative = not stored or (isinstance(stored, dict) and bool(stored.get("not_found")))
            if (
                observation_at
                and _snapshot_cache_is_after_latest_attempt(observation_at, shared_marker)
                and (not loaded or _snapshot_is_newer(observation_at, collected_at))
            ):
                snapshot = list(stored) if isinstance(stored, list) else []
                collected_at = observation_at
                negative = observation_negative
                snapshot_status = {"status": "not_found" if negative else "found"}
                loaded = True
                if shared_selected:
                    shared_selected = False
                _record_observation(result, observation)
                redis_write_attempted = _redis_write_configured(cache, key)
                redis_write_ack = None
                if cache is not None and key:
                    redis_write_ack = cache.set_json(
                        key,
                        _fenced_observation_payload(
                            result,
                            {"negative": negative, "neighbors": snapshot, "collected_at": collected_at},
                            observation,
                        ),
                        kind="negative" if negative else "topology",
                        collected_at=collected_at,
                        retain_seconds=15 if negative else None,
                    ) is True
                _set_cache_source(
                    result,
                    "topology",
                    device,
                    "negative_postgres" if negative else "postgres",
                    vrf=vrf,
                    variant="port_neighbor",
                    redis_write_attempted=redis_write_attempted,
                    redis_write_ack=redis_write_ack,
                )

    if not loaded:
        collect_full_neighbors = getattr(legacy, "_collect_lldp_from_device", None)
        if not callable(collect_full_neighbors):
            return [], "", "", {"status": "unsupported", "error_code": "NEIGHBOR_ACTION_UNSUPPORTED"}
        query = _run_cli_with_device_lease(
            device,
            "neighbor",
            lambda: collect_full_neighbors(device),
            owner_id=f"{result.get('run_id')}:neighbor",
            task_context=_cli_task_context(
                device=device,
                scope=scope,
                scope_hash=scope_hash,
                target_ip="",
                operation="neighbor",
                force_refresh=force_refresh,
                durable_run_id=durable_run_id,
                run_owner_id=run_owner_id,
                target=neighbor_target,
                cancel_check=cancel_check,
            ),
            wait_seconds=max(1, min(30, int(wait_seconds))),
        )
        value, collected_at, task_id, snapshot_status = _cli_result_parts(query)
        snapshot = list(value or [])
        if not snapshot_status.get("status"):
            snapshot_status = {
                "status": "found" if snapshot else "not_found",
            }
        status_name = str(snapshot_status.get("status") or "").strip().lower()
        coverage = str(snapshot_status.get("coverage") or "").strip().lower()
        if status_name not in {"found", "not_found"} or (coverage and coverage != "full"):
            result["queried_devices"]["lldp"].append(_device_label(device))
            return [], collected_at, task_id, snapshot_status
        result["queried_devices"]["lldp"].append(_device_label(device))
        collected_at = collected_at or _now_iso()
        negative = status_name == "not_found" or not snapshot
        persisted = _persist_observation(
            tenant_id=tenant_id,
            scope_hash=scope_hash,
            network_domain_id=network_domain_id,
            site_id=site_id,
            vrf=vrf,
            device_id=device_id,
            kind="neighbor",
            records=snapshot,
            coverage="full",
            collected_at=collected_at,
            query_task_id=task_id,
            fresh_seconds=15 if negative else None,
            retain_seconds=15 if negative else None,
            result=result,
            device=device,
            target=neighbor_target,
        )
        if not persisted:
            result["coverage_gaps"].append(f"observation_persist_failed:{device_id}:neighbor")
            return [], collected_at, task_id, {"status": "query_failed", "error_code": "OBSERVATION_PERSIST_FAILED"}
        redis_write_attempted = _redis_write_configured(cache, key)
        redis_write_ack = None
        if cache is not None and key:
            redis_write_ack = cache.set_json(
                key,
                _fenced_observation_payload(
                    result,
                    {"negative": negative, "neighbors": snapshot, "collected_at": collected_at},
                    persisted,
                ),
                kind="negative" if negative else "topology",
                collected_at=collected_at,
                retain_seconds=15 if negative else None,
            ) is True
        _set_cache_source(
            result,
            "topology",
            device,
            "negative_cli" if negative else "cli",
            vrf=vrf,
            variant="full_snapshot",
            redis_write_attempted=redis_write_attempted,
            redis_write_ack=redis_write_ack,
        )

    if shared_selected and shared_dependency_marker:
        _record_topology_snapshot_dependency(result, shared_dependency_marker)

    selected = _lldp_neighbors(
        device,
        port,
        records=snapshot,
        source_status=snapshot_status,
    )
    if collected_at:
        _include_evidence_timestamp(result, collected_at)
        age = _route_age_seconds(collected_at)
        if age is not None:
            result["freshness"]["topology"] = max(
                int(result["freshness"].get("topology") or 0),
                age,
            )
    return list(selected), collected_at, task_id, dict(getattr(selected, "status", {}) or snapshot_status)


def _neighbor_device_candidates(
    conn: Any,
    neighbor: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    neighbor_id = str(neighbor.get("neighbor_id") or "")
    if neighbor_id:
        candidate = by_id.get(neighbor_id)
        return [candidate] if candidate else []

    ip_candidates = _find_next_hop_device_candidates(
        conn,
        str(neighbor.get("neighbor_ip") or ""),
        by_id,
    )
    ip_ids = {str(item.get("id") or "") for item in ip_candidates}

    neighbor_name = str(neighbor.get("neighbor_name") or "").strip().rstrip(".").lower()
    name_ids: set[str] = set()
    if neighbor_name:
        short_name = neighbor_name.split(".", 1)[0]
        for device_id, item in by_id.items():
            hostname = str(item.get("hostname") or "").strip().rstrip(".").lower()
            if hostname and (hostname == neighbor_name or hostname.split(".", 1)[0] == short_name):
                name_ids.add(str(device_id))

    # If both identity sources point somewhere, use their intersection when
    # possible. Conflicting or repeated identities stay ambiguous.
    if ip_ids and name_ids:
        selected_ids = ip_ids.intersection(name_ids) or ip_ids.union(name_ids)
    else:
        selected_ids = ip_ids or name_ids
    return [by_id[device_id] for device_id in sorted(selected_ids) if device_id in by_id]


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


def _initial_result(
    target_ip: str,
    vrf: str,
    scope: dict[str, Any],
    limits: TraceLimits,
    *,
    run_id: str = "",
) -> dict[str, Any]:
    return {
        "run_id": str(run_id or uuid.uuid4()),
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
        "dependency_manifest": {
            "version": 1,
            "contract_version": _trace_contract_version(),
            "topology": {"key": "topology:global", "scope": "global", "generation": 0},
            "observations": [],
            "topology_snapshots": [],
        },
        "freshness": {"route": None, "arp": None, "mac": None, "topology": None},
        "evidence_collected_at": None,
        "cache": {"route": "miss", "arp": "miss", "mac": "miss", "result": "miss"},
        "cache_provenance": [],
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
    durable_run_id: str = "",
    run_owner_id: str = "",
    cancel_check: Any = None,
    tenant_id: str = "tenant-default",
    start_device_id: str = "",
    vrf: str = "default",
    site_id: str = "",
    network_domain_id: str = "",
    authorized_device_ids: Iterable[str] | None = None,
    force_refresh: bool = False,
    limits: TraceLimits | None = None,
    route_fresh_seconds: int = 300,
    deadline_seconds: int = 180,
) -> dict[str, Any]:
    """Execute the four-stage CLI-only trace with bounded branching."""
    try:
        parsed_target_ip = ipaddress.ip_address(str(target_ip).strip())
        target_ip = str(parsed_target_ip)
    except ValueError:
        return {
            "run_id": str(durable_run_id or uuid.uuid4()),
            "target_ip": str(target_ip),
            "status": "failed",
            "conclusion": "invalid_ip",
            "found": False,
            "errors": ["目标 IP 地址无效"],
        }
    if parsed_target_ip.version != 4:
        return {
            "run_id": str(durable_run_id or uuid.uuid4()),
            "target_ip": target_ip,
            "status": "failed",
            "conclusion": "unsupported_address_family",
            "reason_code": "IPV6_NDP_UNSUPPORTED",
            "found": False,
            "errors": ["当前四阶段定位仅支持 IPv4；IPv6 需要 NDP 专项适配"],
        }
    limits = limits or TraceLimits()
    deadline = time.monotonic() + max(1, int(deadline_seconds or 180))
    deadline_exceeded = False
    cancelled = False
    storage_failed = False

    def operation_budget_available() -> bool:
        nonlocal deadline_exceeded, cancelled, storage_failed
        if storage_failed:
            return False
        if callable(cancel_check):
            try:
                cancelled = bool(cancel_check())
            except Exception:
                cancelled = True
            if cancelled:
                if "task_cancelled" not in result["coverage_gaps"]:
                    result["coverage_gaps"].append("task_cancelled")
                return False
        if time.monotonic() >= deadline:
            deadline_exceeded = True
            if "task_deadline_exceeded" not in result["coverage_gaps"]:
                result["coverage_gaps"].append("task_deadline_exceeded")
            return False
        return True

    vrf = _normalise_vrf(vrf)
    scope = {
        "tenant_id": str(tenant_id or "tenant-default"),
        "site_id": str(site_id or ""),
        "network_domain_id": str(network_domain_id or ""),
        "vrf": vrf,
        "start_device_id": str(start_device_id or ""),
        "authorization_scope_hash": _authorization_scope_hash(authorized_device_ids),
    }
    result = _initial_result(target_ip, vrf, scope, limits, run_id=durable_run_id)
    if network_domain_id:
        result["status"] = "needs_context"
        result["conclusion"] = "network_domain_scope_unavailable"
        result["coverage_gaps"].append("当前设备目录没有可核验的网络域绑定，拒绝跨域追踪")
        result["completed_at"] = _now_iso()
        return result
    try:
        from services.ip_locator_task_service import get_locator_dependency_generation

        topology_generation = get_locator_dependency_generation("topology:global")
    except Exception:
        topology_generation = None
    if not topology_generation:
        result["status"] = "partial"
        result["conclusion"] = "dependency_generation_unavailable"
        result["coverage_gaps"].append("dependency_generation_unavailable:topology:global")
        result["completed_at"] = _now_iso()
        return result
    result["dependency_manifest"]["topology"]["generation"] = int(topology_generation.get("generation") or 0)
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
            collected_at = (
                cached_result.get("evidence_collected_at")
                or cached_result.get("completed_at")
                or cached_result.get("created_at")
            )
            try:
                fresh = cache.is_fresh("result", collected_at)
            except Exception:
                fresh = False
            if fresh and _manifest_is_current_for_code(cached_result.get("dependency_manifest")) and not _pending_fact_invalidation(scope_hash, target_ip):
                cached = _copy_cached_result_for_request(cached_result)
                cached["run_id"] = result["run_id"]
                _set_cache_source(
                    cached,
                    "result",
                    {"hostname": "whole-result"},
                    "redis",
                    vrf=vrf,
                    variant="whole_result",
                )
                cached["cache"]["result"] = "hit"
                cached["status"] = (
                    "completed"
                    if str(cached.get("conclusion") or "") == "managed_access_confirmed"
                    else str(cached.get("status") or "partial")
                )
                cached["cached_from_run_id"] = cached_result.get("run_id")
                return cached
            if fresh:
                cache.delete(result_key)
        _set_cache_source(
            result,
            "result",
            {"hostname": "whole-result"},
            "miss",
            vrf=vrf,
            variant="whole_result",
        )
    devices = _load_devices(
        tenant_id=tenant_id,
        start_device_id=start_device_id,
        site_id=site_id,
        authorized_device_ids=authorized_device_ids,
    )
    by_id = _device_map(devices)
    if start_device_id:
        start_devices = [item for item in devices if str(item.get("id") or "") == str(start_device_id)]
    else:
        start_devices = [
            item for item in devices
            if str(item.get("role") or "").strip().lower() in CORE_ROLES
        ]
    if not devices or not start_devices:
        result["status"] = "failed"
        result["status"] = "needs_context"
        result["conclusion"] = "core_start_not_configured"
        result["coverage_gaps"].append("当前租户/站点没有可访问的纳管核心设备，请指定起始设备")
        result["completed_at"] = _now_iso()
        return result
    if len(start_devices) > limits.max_candidates_per_hop:
        result["coverage_gaps"].append("core_candidate_budget_exceeded")
        start_devices = start_devices[: limits.max_candidates_per_hop]

    queried_device_ids: set[str] = set()
    l3_visited: set[tuple[str, str]] = set()
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
        while frontier and len(queried_device_ids) < limits.max_devices:
            if not operation_budget_available():
                break
            branch = frontier.pop(0)
            device = branch["device"]
            device_id = str(device.get("id") or "")
            if not device_id or device_id in branch["visited"]:
                continue
            if len(branch["path"]) >= limits.max_l3_hops:
                result["coverage_gaps"].append("L3 路径超过最大跳数")
                continue
            branch["visited"] = set(branch["visited"]) | {device_id}
            branch_key = (device_id, str(branch["vrf"]))
            if branch_key in l3_visited:
                continue
            l3_visited.add(branch_key)
            queried_device_ids.add(device_id)
            label = _device_label(device)
            if label not in result["queried_devices"]["route"]:
                result["queried_devices"]["route"].append(label)

            route_key = _cache_key(cache, "route", scope_hash, device_id, branch["vrf"], target_ip)
            try:
                route_target = {"command": _route_command(device, target_ip, branch["vrf"]), "platform": _normalise_platform(device)}
            except UnsupportedLocatorPlatform:
                route_target = {"platform": str(device.get("platform") or "")}
            route_versions = _pipeline_versions("route", device, route_target)
            rows: list[dict[str, Any]] = []
            route_collected_at = ""
            route_task_id = ""
            if (
                not force_refresh
                and cache is not None
                and route_key
                and not _pending_fact_invalidation(scope_hash, target_ip)
            ):
                cached_route = cache.get_json(route_key)
                cached_route = _cached_observation_is_current(
                    cached_route,
                    expected_versions=route_versions,
                    result=result,
                    cache=cache,
                    kind="route",
                )
                if isinstance(cached_route, dict) and cache.is_fresh("route", cached_route.get("collected_at")):
                    if cached_route.get("negative"):
                        result["coverage_gaps"].append(f"{label} 无目标路由（负缓存）")
                        _set_cache_source(result, "route", device, "negative_redis", vrf=branch["vrf"])
                        continue
                    rows = list(cached_route.get("records") or [])
                    route_collected_at = str(cached_route.get("collected_at") or "")
                    _set_cache_source(result, "route", device, "redis", vrf=branch["vrf"])
            if not force_refresh and not rows and not route_collected_at:
                observation = _find_fresh_observation(
                    tenant_id=tenant_id,
                    scope_hash=scope_hash,
                    network_domain_id=network_domain_id,
                    site_id=site_id,
                    vrf=branch["vrf"],
                    device_id=device_id,
                    kind="route",
                    target_ip=target_ip,
                    versions=route_versions,
                    result=result,
                )
                if observation:
                    records = observation.get("records") or {}
                    rows = list(records if isinstance(records, list) else records.get("routes") or [])
                    route_collected_at = str(observation.get("collected_at") or "")
                    if rows:
                        for route_row in rows:
                            if isinstance(route_row, dict):
                                route_row.setdefault("last_updated", route_collected_at)
                                route_row.setdefault("source", "postgres_observation")
                        redis_write_attempted = _redis_write_configured(cache, route_key)
                        redis_write_ack = None
                        if cache is not None and route_key:
                            redis_write_ack = cache.set_json(route_key, _fenced_observation_payload(
                                result,
                                {"records": rows, "collected_at": route_collected_at},
                                observation,
                            ), kind="route", collected_at=route_collected_at) is True
                        _set_cache_source(
                            result,
                            "route",
                            device,
                            "postgres",
                            vrf=branch["vrf"],
                            redis_write_attempted=redis_write_attempted,
                            redis_write_ack=redis_write_ack,
                        )
                    elif isinstance(records, dict) and records.get("not_found"):
                        result["coverage_gaps"].append(f"{label} 无目标路由（负缓存）")
                        _set_cache_source(result, "route", device, "negative_postgres", vrf=branch["vrf"])
                        continue
            # The legacy route cache carries no observation generation or
            # parser/action fingerprint and is not safe to reuse in V2.
            if not rows:
                try:
                    command = str(route_target.get("command") or "")
                    if not command:
                        raise UnsupportedLocatorPlatform("route action is unavailable")
                except UnsupportedLocatorPlatform as exc:
                    result["errors"].append(f"{label} 平台暂不支持 IP 定位路由查询")
                    result["coverage_gaps"].append(f"unsupported_platform:{device_id}")
                    logger.info("[IPLocator] route command is unsupported for %s (%s)", label, type(exc).__name__)
                    continue
                try:
                    cli_result = _run_cli_with_device_lease(
                        device,
                        "route",
                        lambda: legacy._send_command(device, command, force_refresh=True),
                        owner_id=f"{result['run_id']}:route",
                        task_context=_cli_task_context(
                            device=device,
                            scope=scope,
                            scope_hash=scope_hash,
                            target_ip=target_ip,
                            operation="route",
                            force_refresh=force_refresh,
                            durable_run_id=durable_run_id,
                            run_owner_id=run_owner_id,
                            target=route_target,
                            cancel_check=cancel_check,
                        ),
                        wait_seconds=max(1, min(30, int(deadline - time.monotonic()))),
                    )
                    output, route_collected_at, route_task_id, _ = _cli_result_parts(cli_result)
                    rows = _parse_target_route_output(output, device, target_ip, branch["vrf"])
                    route_collected_at = route_collected_at or _now_iso()
                    for route_row in rows:
                        route_row["last_updated"] = route_collected_at
                        route_row["source"] = "ssh_cli"
                    if rows:
                        persisted = _persist_observation(
                            tenant_id=tenant_id,
                            scope_hash=scope_hash,
                            network_domain_id=network_domain_id,
                            site_id=site_id,
                            vrf=branch["vrf"],
                            device_id=device_id,
                            kind="route",
                            target_ip=target_ip,
                            records=rows,
                            collected_at=route_collected_at,
                            query_task_id=route_task_id,
                            result=result,
                            device=device,
                            target=route_target,
                        )
                        if persisted:
                            redis_write_attempted = _redis_write_configured(cache, route_key)
                            redis_write_ack = None
                            if cache is not None and route_key:
                                redis_write_ack = cache.set_json(
                                    route_key,
                                    _fenced_observation_payload(
                                        result,
                                        {"records": rows, "collected_at": route_collected_at},
                                        persisted,
                                    ),
                                    kind="route",
                                    collected_at=route_collected_at,
                                ) is True
                            _set_cache_source(
                                result,
                                "route",
                                device,
                                "cli",
                                vrf=branch["vrf"],
                                redis_write_attempted=redis_write_attempted,
                                redis_write_ack=redis_write_ack,
                            )
                        else:
                            storage_failed = True
                            result["coverage_gaps"].append(f"observation_persist_failed:{device_id}:route")
                    else:
                        output_status = _route_output_status(output)
                        if output_status != "not_found":
                            result["errors"].append(f"{label} 路由输出无法确认目标路由状态")
                            result["coverage_gaps"].append(f"route_{output_status}:{device_id}")
                            continue
                        negative_at = route_collected_at or _now_iso()
                        persisted = _persist_observation(
                            tenant_id=tenant_id,
                            scope_hash=scope_hash,
                            network_domain_id=network_domain_id,
                            site_id=site_id,
                            vrf=branch["vrf"],
                            device_id=device_id,
                            kind="route",
                            target_ip=target_ip,
                            records={"not_found": True},
                            fresh_seconds=15,
                            retain_seconds=15,
                            collected_at=negative_at,
                            query_task_id=route_task_id,
                            result=result,
                            device=device,
                            target=route_target,
                        )
                        if persisted:
                            redis_write_attempted = _redis_write_configured(cache, route_key)
                            redis_write_ack = None
                            if cache is not None and route_key:
                                redis_write_ack = cache.set_json(
                                    route_key,
                                    _fenced_observation_payload(
                                        result,
                                        {"negative": True, "records": [], "collected_at": negative_at},
                                        persisted,
                                    ),
                                    kind="negative",
                                    collected_at=negative_at,
                                    retain_seconds=15,
                                ) is True
                            _set_cache_source(
                                result,
                                "route",
                                device,
                                "negative_cli",
                                vrf=branch["vrf"],
                                redis_write_attempted=redis_write_attempted,
                                redis_write_ack=redis_write_ack,
                            )
                        else:
                            storage_failed = True
                            result["coverage_gaps"].append(f"observation_persist_failed:{device_id}:route")
                except Exception as exc:
                    result["errors"].append(f"{label} 路由查询失败")
                    result["coverage_gaps"].append(f"route_failed:{device_id}")
                    _set_cache_source(result, "route", device, "query_failed", vrf=branch["vrf"])
                    logger.debug("[IPLocatorV2] route query failed for %s: %s", label, exc)
                    continue
            best = _best_routes(rows, target_ip)
            if not best:
                result["coverage_gaps"].append(f"{label} 无目标路由")
                continue
            if len(best) > limits.max_candidates_per_hop:
                result["coverage_gaps"].append(f"route_candidate_budget_exceeded:{device_id}")
            _include_evidence_timestamp(result, route_collected_at)
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
                    "collected_at": row.get("last_updated") or route_collected_at,
                    "age_seconds": _route_age_seconds(row.get("last_updated")),
                }
                next_path = branch["path"] + [hop]
                result["l3_paths"].append(hop)
                if hop["age_seconds"] is not None:
                    age = hop["age_seconds"]
                    result["freshness"]["route"] = max(int(result["freshness"]["route"] or 0), age)
                protocol = str(row.get("protocol") or "").strip().lower()
                next_hop_normalized = str(row.get("next_hop") or "").strip().lower()
                if protocol in DISCARD_PROTOCOLS or next_hop_normalized in {"null0", "discard", "reject"}:
                    result["coverage_gaps"].append(f"route_discard:{device_id}:{row.get('destination') or ''}")
                    continue
                if protocol in LOCAL_DEVICE_PROTOCOLS:
                    local_location = {
                        "device_id": device_id,
                        "device": label,
                        "port": row.get("interface") or "",
                        "ip": target_ip,
                        "confidence": "device_interface",
                    }
                    result["status"] = "completed"
                    result["conclusion"] = "device_interface"
                    result["found"] = True
                    result["location"] = local_location
                    result["terminal_candidates"].append(local_location)
                    result["completed_at"] = _now_iso()
                    return add_legacy_compatibility(result)
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
                next_hop_candidates = _find_next_hop_device_candidates(conn, next_hop, by_id)
                next_device = next_hop_candidates[0] if len(next_hop_candidates) == 1 else None
                next_hop_ip_ambiguous = len(next_hop_candidates) > 1
                if not next_device:
                    route_port = str(row.get("interface") or "").strip()
                    discovered_neighbors = (
                        _topology_neighbors(conn, device_id, route_port)
                        if route_port else []
                    )
                    if not discovered_neighbors and route_port and operation_budget_available():
                        discovered_neighbors, _, _, neighbor_status = _load_lldp_snapshot(
                            device,
                            route_port,
                            cache=cache,
                            scope=scope,
                            scope_hash=scope_hash,
                            tenant_id=tenant_id,
                            target_ip=target_ip,
                            network_domain_id=network_domain_id,
                            site_id=site_id,
                            vrf=branch["vrf"],
                            force_refresh=force_refresh,
                            durable_run_id=durable_run_id,
                            run_owner_id=run_owner_id,
                            cancel_check=cancel_check,
                            result=result,
                            wait_seconds=max(1, min(30, int(deadline - time.monotonic()))),
                        )
                        if neighbor_status.get("status") in {"unsupported", "query_failed", "parse_incomplete"}:
                            result["coverage_gaps"].append(
                                f"next_hop_neighbor_{neighbor_status.get('status')}:{device_id}:{route_port}"
                            )
                    if len(discovered_neighbors) > limits.max_candidates_per_hop:
                        result["coverage_gaps"].append(f"next_hop_candidate_budget_exceeded:{device_id}")
                    resolved_neighbors = []
                    exact_next_hops = []
                    for neighbor in discovered_neighbors[: limits.max_candidates_per_hop]:
                        neighbor_candidates = _neighbor_device_candidates(conn, neighbor, by_id)
                        if len(neighbor_candidates) > 1:
                            gap_prefix = (
                                "next_hop_ambiguous"
                                if str(neighbor.get("neighbor_ip") or "").strip() == next_hop
                                else "neighbor_ambiguous"
                            )
                            result["coverage_gaps"].append(
                                f"{gap_prefix}:{neighbor.get('neighbor_ip') or neighbor.get('neighbor_name') or device_id}"
                            )
                            continue
                        candidate = neighbor_candidates[0] if neighbor_candidates else None
                        if candidate is None:
                            if neighbor.get("neighbor_id"):
                                result["coverage_gaps"].append(
                                    f"next_hop_out_of_scope:{neighbor.get('neighbor_id')}"
                                )
                            continue
                        resolved_neighbors.append(candidate)
                        if str(neighbor.get("neighbor_ip") or "").strip() == next_hop:
                            exact_next_hops.append(candidate)
                    unique_exact = {str(item.get("id") or ""): item for item in exact_next_hops}
                    unique_resolved = {str(item.get("id") or ""): item for item in resolved_neighbors}
                    if len(unique_exact) == 1:
                        next_device = next(iter(unique_exact.values()))
                    elif len(unique_exact) > 1 or (not unique_exact and len(unique_resolved) > 1):
                        result["coverage_gaps"].append(f"next_hop_ambiguous:{next_hop}")
                        continue
                    elif next_hop_ip_ambiguous and len(unique_resolved) != 1:
                        result["coverage_gaps"].append(f"next_hop_ambiguous:{next_hop}")
                        continue
                    elif len(unique_resolved) == 1 and len(discovered_neighbors) == 1:
                        # A single managed physical neighbor on the route's
                        # egress is stronger evidence than guessing a login
                        # target from an arbitrary next-hop IP.
                        next_device = next(iter(unique_resolved.values()))
                    else:
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
        if frontier and len(queried_device_ids) >= limits.max_devices:
            result["coverage_gaps"].append("device_budget_exceeded")
    finally:
        conn.close()

    if cancelled:
        result["status"] = "cancelled"
        result["conclusion"] = "cancelled"
        result["completed_at"] = _now_iso()
        return result

    if not direct_devices:
        unsupported_platform = any(
            str(gap).startswith("unsupported_platform:") for gap in result["coverage_gaps"]
        )
        result["status"] = "partial" if result["l3_paths"] or deadline_exceeded or unsupported_platform else "failed"
        result["conclusion"] = (
            "deadline_exceeded" if deadline_exceeded
            else "unsupported" if unsupported_platform
            else ("no_direct_gateway" if result["l3_paths"] else "no_route")
        )
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
        if not operation_budget_available():
            break
        label = _device_label(device)
        result["queried_devices"]["arp"].append(label)
        try:
            arp_key = _cache_key(cache, "arp", scope_hash, device.get("id") or "", vrf, target_ip)
            arp_snapshot_key = _cache_key(cache, "arp_snapshot", scope_hash, device.get("id") or "", vrf)
            arp_target = {"vrf": vrf, "platform": _normalise_platform(device)}
            arp_versions = _pipeline_versions("arp", device, arp_target)
            arp_snapshot_target = {"snapshot": "full", **arp_target}
            arp_snapshot_versions = _pipeline_versions("arp", device, arp_snapshot_target)
            arp = None
            arp_status = "unknown"
            arp_collected_at = ""
            arp_task_id = ""
            arp_negative = False
            arp_source = ""
            snapshot_source = ""
            redis_write_attempted = False
            redis_write_ack = None
            if cache is not None and arp_key and not force_refresh and not _pending_fact_invalidation(scope_hash, target_ip):
                cached_arp = cache.get_json(arp_key)
                cached_arp = _cached_observation_is_current(
                    cached_arp,
                    expected_versions=arp_versions,
                    result=result,
                    cache=cache,
                    kind="arp",
                )
                if isinstance(cached_arp, dict) and cache.is_fresh("arp", cached_arp.get("collected_at")):
                    arp_collected_at = str(cached_arp.get("collected_at") or "")
                    arp_negative = bool(cached_arp.get("negative"))
                    arp = cached_arp.get("record") or None
                    arp_status = "not_found" if arp_negative else ("found" if arp else "unknown")
                    arp_source = "negative_redis" if arp_negative else "redis"
                    _set_cache_source(
                        result,
                        "arp",
                        device,
                        "negative_redis" if arp_negative else "redis",
                        vrf=vrf,
                    )
            if arp is None and not arp_negative:
                observation = _find_fresh_observation(
                    tenant_id=tenant_id,
                    scope_hash=scope_hash,
                    network_domain_id=network_domain_id,
                    site_id=site_id,
                    vrf=vrf,
                    device_id=str(device.get("id") or ""),
                    kind="arp",
                    target_ip=target_ip,
                    versions=arp_versions,
                    result=result,
                )
                if observation:
                    records = observation.get("records") or {}
                    arp_collected_at = str(observation.get("collected_at") or "")
                    arp_negative = bool(records.get("not_found")) if isinstance(records, dict) else False
                    arp = None if arp_negative else (records if isinstance(records, dict) else None)
                    arp_status = "not_found" if arp_negative else ("found" if arp else "unknown")
                    arp_source = "negative_postgres" if arp_negative else "postgres"
                    redis_write_attempted = bool(arp and _redis_write_configured(cache, arp_key))
                    redis_write_ack = None
                    if arp and cache is not None and arp_key:
                        redis_write_ack = cache.set_json(
                            arp_key,
                            _fenced_observation_payload(
                                result,
                                {"record": arp, "collected_at": arp_collected_at},
                                observation,
                            ),
                            kind="arp",
                            collected_at=arp_collected_at,
                        ) is True
                    _set_cache_source(
                        result,
                        "arp",
                        device,
                        "negative_postgres" if arp_negative else "postgres",
                        vrf=vrf,
                        redis_write_attempted=redis_write_attempted,
                        redis_write_ack=redis_write_ack,
                    )
            full_snapshot = None
            full_snapshot_at = ""
            full_snapshot_task_id = ""
            if not force_refresh and not _pending_fact_invalidation(scope_hash, target_ip):
                if cache is not None and arp_snapshot_key:
                    cached_snapshot = cache.get_json(arp_snapshot_key)
                    cached_snapshot = _cached_observation_is_current(
                        cached_snapshot,
                        expected_versions=arp_snapshot_versions,
                        result=result,
                        cache=cache,
                        kind="arp",
                    )
                    if isinstance(cached_snapshot, dict):
                        candidate_at = str(cached_snapshot.get("collected_at") or "")
                        if candidate_at and cache.is_fresh(
                            "negative" if cached_snapshot.get("negative") else "arp",
                            candidate_at,
                        ):
                            full_snapshot = list(cached_snapshot.get("records") or [])
                            full_snapshot_at = candidate_at
                            snapshot_source = (
                                "snapshot_negative_redis"
                                if cached_snapshot.get("negative") else "snapshot_redis"
                            )
                            _set_cache_source(
                                result,
                                "arp",
                                device,
                                "snapshot_negative_redis" if cached_snapshot.get("negative") else "snapshot_redis",
                                vrf=vrf,
                                variant="full_snapshot",
                            )
                if full_snapshot is None:
                    snapshot_observation = _find_fresh_observation(
                        tenant_id=tenant_id,
                        scope_hash=scope_hash,
                        network_domain_id=network_domain_id,
                        site_id=site_id,
                        vrf=vrf,
                        device_id=str(device.get("id") or ""),
                        kind="arp",
                        versions=arp_snapshot_versions,
                        result=result,
                    )
                    if snapshot_observation and snapshot_observation.get("coverage") == "full":
                        snapshot_records = snapshot_observation.get("records") or []
                        if isinstance(snapshot_records, list):
                            full_snapshot = snapshot_records
                            full_snapshot_at = str(snapshot_observation.get("collected_at") or "")
                            full_snapshot_task_id = str(snapshot_observation.get("query_task_id") or "")
                            snapshot_negative = not full_snapshot
                            snapshot_source = "snapshot_postgres"
                            redis_write_attempted = bool(full_snapshot_at and _redis_write_configured(cache, arp_snapshot_key))
                            redis_write_ack = None
                            if cache is not None and arp_snapshot_key and full_snapshot_at:
                                redis_write_ack = cache.set_json(
                                    arp_snapshot_key,
                                    _fenced_observation_payload(result, {
                                        "negative": snapshot_negative,
                                        "records": full_snapshot,
                                        "collected_at": full_snapshot_at,
                                    }, snapshot_observation),
                                    kind="negative" if snapshot_negative else "arp",
                                    collected_at=full_snapshot_at,
                                    retain_seconds=15 if snapshot_negative else None,
                                ) is True
                            _set_cache_source(
                                result,
                                "arp",
                                device,
                                "snapshot_postgres",
                                vrf=vrf,
                                variant="full_snapshot",
                                redis_write_attempted=redis_write_attempted,
                                redis_write_ack=redis_write_ack,
                            )
            if full_snapshot is not None and _is_newer_evidence(full_snapshot_at, arp_collected_at):
                matches = [
                    dict(record)
                    for record in full_snapshot
                    if isinstance(record, dict) and str(record.get("ip") or "") == target_ip
                ]
                unique_matches = {
                    (
                        str(item.get("mac") or ""),
                        str(item.get("interface") or ""),
                        str(item.get("vlan") or ""),
                    ): item
                    for item in matches
                }
                full_snapshot_at = full_snapshot_at or _now_iso()
                full_snapshot_task_id = full_snapshot_task_id or ""
                arp_collected_at = full_snapshot_at
                arp_task_id = full_snapshot_task_id
                if len(unique_matches) > 1:
                    arp = None
                    arp_negative = False
                    arp_status = "ambiguous"
                elif unique_matches:
                    arp = next(iter(unique_matches.values()))
                    arp_negative = False
                    arp_status = "found"
                else:
                    arp = None
                    arp_negative = True
                    arp_status = "not_found"
                if arp_status in {"found", "not_found"}:
                    if snapshot_source == "snapshot_negative_redis":
                        arp_source = snapshot_source
                    elif snapshot_source == "snapshot_negative_cli":
                        arp_source = snapshot_source
                    elif snapshot_source.startswith("snapshot_"):
                        arp_source = snapshot_source if arp_status == "found" else f"snapshot_negative_{snapshot_source.removeprefix('snapshot_')}"
            if arp is None and not arp_negative and arp_status != "ambiguous":
                cli_result = _run_cli_with_device_lease(
                    device,
                    "arp",
                    lambda: (
                        legacy._targeted_arp_query_status(
                            device,
                            target_ip,
                            vrf if vrf != "default" else None,
                            force_refresh=True,
                        )
                        if callable(getattr(legacy, "_targeted_arp_query_status", None))
                        else legacy._targeted_arp_query(
                            device,
                            target_ip,
                            vrf if vrf != "default" else None,
                            force_refresh=True,
                        )
                    ),
                    owner_id=f"{result['run_id']}:arp",
                    task_context=_cli_task_context(
                        device=device,
                        scope=scope,
                        scope_hash=scope_hash,
                        target_ip=target_ip,
                        operation="arp",
                        force_refresh=force_refresh,
                        durable_run_id=durable_run_id,
                        run_owner_id=run_owner_id,
                        target=arp_target,
                        cancel_check=cancel_check,
                    ),
                    wait_seconds=max(1, min(30, int(deadline - time.monotonic()))),
                )
                arp_value, arp_collected_at, arp_task_id, arp_metadata = _cli_result_parts(cli_result)
                arp, arp_status = _arp_query_parts(arp_value, arp_metadata)
                if arp_status in {"found", "not_found"}:
                    arp_source = "cli" if arp_status == "found" else "negative_cli"
                arp_collected_at = arp_collected_at or _now_iso()
                if arp_status == "unsupported":
                    collect_snapshot = getattr(legacy, "_collect_arp_snapshot", None)
                    if callable(collect_snapshot) and operation_budget_available():
                        snapshot_result = _run_cli_with_device_lease(
                            device,
                            "arp",
                            lambda: collect_snapshot(
                                device,
                                vrf if vrf != "default" else None,
                            ),
                            owner_id=f"{result['run_id']}:arp-snapshot",
                            task_context=_cli_task_context(
                                device=device,
                                scope=scope,
                                scope_hash=scope_hash,
                                target_ip="",
                                operation="arp",
                                force_refresh=force_refresh,
                                durable_run_id=durable_run_id,
                                run_owner_id=run_owner_id,
                                target=arp_snapshot_target,
                                cancel_check=cancel_check,
                            ),
                            wait_seconds=max(1, min(30, int(deadline - time.monotonic()))),
                        )
                        snapshot_value, snapshot_at, snapshot_task_id, snapshot_status = _cli_result_parts(snapshot_result)
                        snapshot_records = list(snapshot_value or [])
                        snapshot_status_name = str(snapshot_status.get("status") or "").strip().lower()
                        if _is_complete_full_snapshot(snapshot_status, snapshot_records):
                            snapshot_at = snapshot_at or _now_iso()
                            snapshot_negative = snapshot_status_name == "not_found"
                            snapshot_retain_seconds = _snapshot_retain_seconds(
                                cache, "arp", snapshot_negative
                            )
                            persisted_snapshot = _persist_observation(
                                tenant_id=tenant_id,
                                scope_hash=scope_hash,
                                network_domain_id=network_domain_id,
                                site_id=site_id,
                                vrf=vrf,
                                device_id=str(device.get("id") or ""),
                                kind="arp",
                                records=snapshot_records,
                                coverage="full",
                                fresh_seconds=15 if snapshot_negative else None,
                                retain_seconds=snapshot_retain_seconds,
                                collected_at=snapshot_at,
                                query_task_id=snapshot_task_id,
                                result=result,
                                device=device,
                                target=arp_snapshot_target,
                            )
                            if persisted_snapshot:
                                reconciliation = _reconcile_full_snapshot_absences(
                                    tenant_id=tenant_id,
                                    scope_hash=scope_hash,
                                    network_domain_id=network_domain_id,
                                    site_id=site_id,
                                    vrf=vrf,
                                    device_id=str(device.get("id") or ""),
                                    kind="arp",
                                    records=snapshot_records,
                                    status=snapshot_status,
                                    collected_at=snapshot_at,
                                    query_task_id=snapshot_task_id,
                                    retain_seconds=_configured_observation_retain_seconds(cache, "arp"),
                                    versions=persisted_snapshot,
                                )
                                if reconciliation and reconciliation.get("applied"):
                                    redis_write_attempted = _redis_write_configured(cache, arp_snapshot_key)
                                    redis_write_ack = None
                                    snapshot_source = (
                                        "snapshot_negative_cli" if snapshot_negative else "snapshot_cli"
                                    )
                                    if cache is not None and arp_snapshot_key:
                                        redis_write_ack = cache.set_json(
                                            arp_snapshot_key,
                                            _fenced_observation_payload(result, {
                                                "negative": snapshot_negative,
                                                "records": snapshot_records,
                                                "collected_at": snapshot_at,
                                            }, persisted_snapshot),
                                            kind="negative" if snapshot_negative else "arp",
                                            collected_at=snapshot_at,
                                            retain_seconds=15 if snapshot_negative else None,
                                        ) is True
                                    matches = [
                                        dict(record)
                                        for record in snapshot_records
                                        if isinstance(record, dict) and str(record.get("ip") or "") == target_ip
                                    ]
                                    unique_matches = {
                                        (
                                            str(item.get("mac") or ""),
                                            str(item.get("interface") or ""),
                                            str(item.get("vlan") or ""),
                                        ): item
                                        for item in matches
                                    }
                                    arp_collected_at = snapshot_at
                                    arp_task_id = snapshot_task_id
                                    if len(unique_matches) > 1:
                                        arp = None
                                        arp_negative = False
                                        arp_status = "ambiguous"
                                    elif unique_matches:
                                        arp = next(iter(unique_matches.values()))
                                        arp_negative = False
                                        arp_status = "found"
                                    else:
                                        arp = None
                                        arp_negative = True
                                        arp_status = "not_found"
                                    _set_cache_source(
                                        result,
                                        "arp",
                                        device,
                                        "snapshot_negative_cli" if arp_status == "not_found" else "snapshot_cli",
                                        vrf=vrf,
                                        variant="full_snapshot",
                                        redis_write_attempted=redis_write_attempted,
                                        redis_write_ack=redis_write_ack,
                                    )
                                else:
                                    storage_failed = True
                                    arp_status = "query_failed"
                                    reconciliation_reason = (
                                        (reconciliation or {}).get("reason") or "persistence_failed"
                                    )
                                    result["coverage_gaps"].append(
                                        f"observation_reconcile_failed:{device.get('id')}:arp_snapshot:{reconciliation_reason}"
                                    )
                                    result["errors"].append(f"{label} ARP 快照失效协调失败")
                            else:
                                storage_failed = True
                                arp_status = "query_failed"
                                result["coverage_gaps"].append(
                                    f"observation_persist_failed:{device.get('id')}:arp_snapshot"
                                )
                        else:
                            snapshot_status_name = _snapshot_failure_reason(snapshot_status, snapshot_records)
                            arp_status = snapshot_status_name
                            result["errors"].append(f"{label} ARP 全表快照{arp_status}")
                            result["coverage_gaps"].append(f"arp_snapshot_{arp_status}:{device.get('id')}")
                if arp:
                    persisted = _persist_observation(
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
                        collected_at=arp_collected_at,
                        query_task_id=arp_task_id,
                        result=result,
                        device=device,
                        target=arp_snapshot_target if full_snapshot is not None else arp_target,
                    )
                    if persisted:
                        redis_write_attempted = _redis_write_configured(cache, arp_key)
                        redis_write_ack = None
                        if cache is not None and arp_key:
                            redis_write_ack = cache.set_json(
                                arp_key,
                                _fenced_observation_payload(
                                    result,
                                    {"record": dict(arp), "collected_at": arp_collected_at},
                                    persisted,
                                ),
                                kind="arp",
                                collected_at=arp_collected_at,
                            ) is True
                        _set_cache_source(
                            result,
                            "arp",
                            device,
                            arp_source or "cli",
                            vrf=vrf,
                            redis_write_attempted=redis_write_attempted,
                            redis_write_ack=redis_write_ack,
                        )
                    else:
                        storage_failed = True
                        result["coverage_gaps"].append(f"observation_persist_failed:{device.get('id')}:arp")
                elif arp_status == "not_found":
                    arp_negative = True
                    persisted = _persist_observation(
                        tenant_id=tenant_id,
                        scope_hash=scope_hash,
                        network_domain_id=network_domain_id,
                        site_id=site_id,
                        vrf=vrf,
                        device_id=str(device.get("id") or ""),
                        kind="arp",
                        target_ip=target_ip,
                        records={"not_found": True},
                        fresh_seconds=15,
                        retain_seconds=15,
                        collected_at=arp_collected_at,
                        query_task_id=arp_task_id,
                        result=result,
                        device=device,
                        target=arp_target,
                    )
                    if persisted:
                        redis_write_attempted = _redis_write_configured(cache, arp_key)
                        redis_write_ack = None
                        if cache is not None and arp_key:
                            redis_write_ack = cache.set_json(
                                arp_key,
                                _fenced_observation_payload(
                                    result,
                                    {"negative": True, "collected_at": arp_collected_at},
                                    persisted,
                                ),
                                kind="negative",
                                collected_at=arp_collected_at,
                                retain_seconds=15,
                            ) is True
                        _set_cache_source(
                            result,
                            "arp",
                            device,
                            arp_source or "negative_cli",
                            vrf=vrf,
                            redis_write_attempted=redis_write_attempted,
                            redis_write_ack=redis_write_ack,
                        )
                    else:
                        storage_failed = True
                        result["coverage_gaps"].append(f"observation_persist_failed:{device.get('id')}:arp")
                else:
                    result["errors"].append(f"{label} ARP 查询{arp_status}")
                    result["coverage_gaps"].append(f"arp_{arp_status}:{device.get('id')}")
        except Exception as exc:
            arp_status = "query_failed"
            result["coverage_gaps"].append(f"arp_failed:{device.get('id')}")
            result["errors"].append(f"{label} ARP 查询失败")
            _set_cache_source(result, "arp", device, "query_failed", vrf=vrf)
            logger.debug("[IPLocatorV2] ARP query failed for %s: %s", label, exc)
            continue
        if not arp and arp_status == "not_found":
            result["coverage_gaps"].append(f"arp_not_found:{device.get('id')}")
            continue
        if not arp and arp_status == "ambiguous":
            result["coverage_gaps"].append(f"arp_ambiguous:{device.get('id')}")
            result["errors"].append(f"{label} 存在多个冲突的 ARP 记录")
            continue
        if not arp:
            continue
        arp_item = dict(arp)
        arp_item.update({
            "device_id": str(arp_item.get("source_device_id") or device.get("id") or ""),
            "device": arp_item.get("source_device") or label,
            "collected_at": arp_collected_at or _now_iso(),
            "vrf": vrf,
            "route_prefix": route.get("destination") or "",
        })
        if arp_item.get("is_proxy") or _is_virtual_gateway_mac(arp_item.get("mac")):
            reason = "arp_proxy_or_virtual_gateway"
            result["coverage_gaps"].append(f"{reason}:{device.get('id')}")
            result["errors"].append(f"{label} 返回的是代理或虚拟网关 ARP，不能作为终端 MAC")
            result["arp_evidence"].append(arp_item)
            continue
        local_interface = (
            str(arp_item.get("interface") or "").strip()
            if arp_item.get("is_local")
            else _local_interface_for_mac(
                str(arp_item.get("device_id") or device.get("id") or ""),
                str(arp_item.get("mac") or ""),
            )
        )
        if local_interface:
            arp_item["is_local"] = True
            result["arp_evidence"].append(arp_item)
            _include_evidence_timestamp(result, arp_item["collected_at"])
            local_location = {
                "device_id": str(arp_item.get("device_id") or device.get("id") or ""),
                "device": arp_item.get("device") or label,
                "port": local_interface,
                "ip": target_ip,
                "mac": arp_item.get("mac") or "",
                "confidence": "device_interface",
            }
            result["status"] = "completed"
            result["conclusion"] = "device_interface"
            result["found"] = True
            result["location"] = local_location
            result["terminal_candidates"].append(local_location)
            result["completed_at"] = _now_iso()
            return add_legacy_compatibility(result)
        result["arp_evidence"].append(arp_item)
        _include_evidence_timestamp(result, arp_item["collected_at"])
        arp_age = _route_age_seconds(arp_item["collected_at"])
        if arp_age is not None:
            result["freshness"]["arp"] = max(int(result["freshness"]["arp"] or 0), arp_age)
        _include_evidence_timestamp(result, arp_item["collected_at"])
        arp_hits.append((device, arp_item, l3_path))

    if cancelled:
        result["status"] = "cancelled"
        result["conclusion"] = "cancelled"
        result["completed_at"] = _now_iso()
        return result
    if not arp_hits:
        result["status"] = "partial" if deadline_exceeded or result["coverage_gaps"] else "failed"
        has_unsupported_arp = any(str(gap).startswith("arp_unsupported:") for gap in result["coverage_gaps"])
        has_failed_arp = any(
            str(gap).startswith(("arp_query_failed:", "arp_parse_incomplete:", "arp_failed:"))
            for gap in result["coverage_gaps"]
        )
        has_special_arp = any(
            str(gap).startswith(("arp_proxy_or_virtual_gateway:", "arp_ambiguous:"))
            for gap in result["coverage_gaps"]
        )
        result["conclusion"] = (
            "deadline_exceeded" if deadline_exceeded
            else "unsupported" if has_unsupported_arp
            else "query_failed" if has_failed_arp
            else "ambiguous_arp_source" if has_special_arp
            else "arp_not_found"
        )
        result["completed_at"] = _now_iso()
        return result
    if deadline_exceeded:
        result["status"] = "partial"
        result["conclusion"] = "deadline_exceeded"
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
            while queue:
                if not operation_budget_available():
                    break
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
                if current_id not in queried_device_ids and len(queried_device_ids) >= limits.max_devices:
                    result["coverage_gaps"].append("device_budget_exceeded")
                    queue.insert(0, (current, path, visited))
                    break
                queried_device_ids.add(current_id)
                visited_l2.add(pair)
                label = _device_label(current)
                if label not in result["queried_devices"]["mac"]:
                    result["queried_devices"]["mac"].append(label)
                try:
                    vlan_hint = str(arp.get("vlan") or "")
                    mac_key = _cache_key(cache, "mac", scope_hash, current_id, vrf, mac, vlan_hint)
                    mac_snapshot_key = _cache_key(cache, "mac_snapshot", scope_hash, current_id, vrf)
                    mac_target = {"platform": _normalise_platform(current), "vlan": vlan_hint}
                    mac_versions = _pipeline_versions("mac", current, mac_target)
                    mac_snapshot_target = {
                        "snapshot": "full",
                        "platform": _normalise_platform(current),
                        "profile_id": str(current.get("platform_profile_id") or ""),
                    }
                    mac_snapshot_versions = _pipeline_versions("mac", current, mac_snapshot_target)
                    records = []
                    status = {}
                    mac_collected_at = ""
                    mac_task_id = ""
                    mac_negative = False
                    if cache is not None and mac_key and not force_refresh and not _pending_fact_invalidation(scope_hash, target_ip):
                        cached_mac = cache.get_json(mac_key)
                        cached_mac = _cached_observation_is_current(
                            cached_mac,
                            expected_versions=mac_versions,
                            result=result,
                            cache=cache,
                            kind="mac",
                        )
                        if isinstance(cached_mac, dict):
                            cached_kind = "negative" if cached_mac.get("negative") else "mac"
                            if cache.is_fresh(cached_kind, cached_mac.get("collected_at")):
                                mac_negative = bool(cached_mac.get("negative"))
                                records = list(cached_mac.get("records") or [])
                                status = dict(cached_mac.get("status") or {})
                                mac_collected_at = str(cached_mac.get("collected_at") or "")
                                _set_cache_source(
                                    result,
                                    "mac",
                                    current,
                                    "negative_redis" if mac_negative else "redis",
                                    vrf=vrf,
                                )
                    if not records and not mac_negative and not force_refresh:
                        observation = _find_fresh_observation(
                            tenant_id=tenant_id,
                            scope_hash=scope_hash,
                            network_domain_id=network_domain_id,
                            site_id=site_id,
                            vrf=vrf,
                            device_id=current_id,
                            kind="mac",
                            target_mac=mac,
                            vlan_id=vlan_hint,
                            versions=mac_versions,
                            result=result,
                        )
                        if observation:
                            stored_records = observation.get("records") or {}
                            mac_collected_at = str(observation.get("collected_at") or "")
                            mac_negative = bool(stored_records.get("not_found")) if isinstance(stored_records, dict) else False
                            records = list(stored_records) if isinstance(stored_records, list) else []
                            status = dict(stored_records.get("status") or {}) if isinstance(stored_records, dict) else {"status": "found"}
                            redis_write_attempted = bool((records or mac_negative) and _redis_write_configured(cache, mac_key))
                            redis_write_ack = None
                            if records and cache is not None and mac_key:
                                redis_write_ack = cache.set_json(
                                    mac_key,
                                    _fenced_observation_payload(
                                        result,
                                        {"records": records, "status": status, "collected_at": mac_collected_at},
                                        observation,
                                    ),
                                    kind="mac",
                                    collected_at=mac_collected_at,
                                ) is True
                            elif mac_negative and cache is not None and mac_key:
                                redis_write_ack = cache.set_json(
                                    mac_key,
                                    _fenced_observation_payload(
                                        result,
                                        {"negative": True, "records": [], "status": {"status": "not_found"}, "collected_at": mac_collected_at},
                                        observation,
                                    ),
                                    kind="negative",
                                    collected_at=mac_collected_at,
                                ) is True
                            _set_cache_source(
                                result,
                                "mac",
                                current,
                                "negative_postgres" if mac_negative else "postgres",
                                vrf=vrf,
                                redis_write_attempted=redis_write_attempted,
                                redis_write_ack=redis_write_ack,
                            )
                    full_snapshot_records = None
                    full_snapshot_at = ""
                    if not force_refresh and not _pending_fact_invalidation(scope_hash, target_ip):
                        if cache is not None and mac_snapshot_key:
                            cached_snapshot = cache.get_json(mac_snapshot_key)
                            cached_snapshot = _cached_observation_is_current(
                                cached_snapshot,
                                expected_versions=mac_snapshot_versions,
                                result=result,
                                cache=cache,
                                kind="mac",
                            )
                            if isinstance(cached_snapshot, dict):
                                candidate_at = str(cached_snapshot.get("collected_at") or "")
                                if candidate_at and cache.is_fresh(
                                    "negative" if cached_snapshot.get("negative") else "mac",
                                    candidate_at,
                                ):
                                    full_snapshot_records = list(cached_snapshot.get("records") or [])
                                    full_snapshot_at = candidate_at
                                    _set_cache_source(
                                        result,
                                        "mac",
                                        current,
                                        "snapshot_negative_redis" if cached_snapshot.get("negative") else "snapshot_redis",
                                        vrf=vrf,
                                        variant="full_snapshot",
                                    )
                        if full_snapshot_records is None:
                            snapshot_observation = _find_fresh_observation(
                                tenant_id=tenant_id,
                                scope_hash=scope_hash,
                                network_domain_id=network_domain_id,
                                site_id=site_id,
                                vrf=vrf,
                                device_id=current_id,
                                kind="mac",
                                versions=mac_snapshot_versions,
                                result=result,
                            )
                            if snapshot_observation and snapshot_observation.get("coverage") == "full":
                                stored_snapshot = snapshot_observation.get("records") or []
                                if isinstance(stored_snapshot, list):
                                    full_snapshot_records = stored_snapshot
                                    full_snapshot_at = str(snapshot_observation.get("collected_at") or "")
                                    snapshot_negative = not full_snapshot_records
                                    redis_write_attempted = bool(full_snapshot_at and _redis_write_configured(cache, mac_snapshot_key))
                                    redis_write_ack = None
                                    if cache is not None and mac_snapshot_key and full_snapshot_at:
                                        redis_write_ack = cache.set_json(
                                            mac_snapshot_key,
                                                _fenced_observation_payload(result, {
                                                    "negative": snapshot_negative,
                                                    "records": full_snapshot_records,
                                                    "collected_at": full_snapshot_at,
                                                }, snapshot_observation),
                                            kind="negative" if snapshot_negative else "mac",
                                            collected_at=full_snapshot_at,
                                            retain_seconds=15 if snapshot_negative else None,
                                        ) is True
                                    _set_cache_source(
                                        result,
                                        "mac",
                                        current,
                                        "snapshot_postgres",
                                        vrf=vrf,
                                        variant="full_snapshot",
                                        redis_write_attempted=redis_write_attempted,
                                        redis_write_ack=redis_write_ack,
                                    )
                    if (
                        full_snapshot_records is not None
                        and _is_newer_evidence(full_snapshot_at, mac_collected_at)
                    ):
                        records = [
                            dict(record)
                            for record in full_snapshot_records
                            if isinstance(record, dict)
                            and legacy._normalize_mac(str(record.get("mac") or "")) == mac
                        ]
                        mac_collected_at = full_snapshot_at
                        mac_negative = not records
                        status = {
                            "status": "found" if records else "not_found",
                            "source": "full_snapshot",
                        }
                    if not records and not mac_negative and not (status and status.get("status") in {"unsupported", "query_failed", "disabled"}):
                        mac_result = _run_cli_with_device_lease(
                            current,
                            "mac",
                            lambda: _targeted_mac_query_for_trace(current, mac),
                            owner_id=f"{result['run_id']}:mac",
                            task_context=_cli_task_context(
                                device=current,
                                scope=scope,
                                scope_hash=scope_hash,
                                target_ip=target_ip,
                                operation="mac",
                                target_mac=mac,
                                vlan_id=vlan_hint,
                                force_refresh=force_refresh,
                                durable_run_id=durable_run_id,
                                run_owner_id=run_owner_id,
                                target=mac_target,
                                cancel_check=cancel_check,
                            ),
                            wait_seconds=max(1, min(30, int(deadline - time.monotonic()))),
                        )
                        mac_result_value, mac_collected_at, mac_task_id, status = _cli_result_parts(mac_result)
                        records = list(mac_result_value or [])
                        mac_collected_at = mac_collected_at or _now_iso()
                        if isinstance(status, dict) and status.get("status") == "unsupported":
                            collect_snapshot = getattr(legacy, "_collect_mac_table_snapshot", None)
                            if callable(collect_snapshot) and operation_budget_available():
                                snapshot_result = _run_cli_with_device_lease(
                                    current,
                                    "mac",
                                    lambda: collect_snapshot(current),
                                    owner_id=f"{result['run_id']}:mac-snapshot",
                                    task_context=_cli_task_context(
                                        device=current,
                                        scope=scope,
                                        scope_hash=scope_hash,
                                        target_ip="",
                                        operation="mac",
                                        target_mac="",
                                        force_refresh=force_refresh,
                                        durable_run_id=durable_run_id,
                                        run_owner_id=run_owner_id,
                                        target=mac_snapshot_target,
                                        cancel_check=cancel_check,
                                    ),
                                    wait_seconds=max(1, min(30, int(deadline - time.monotonic()))),
                                )
                                snapshot_value, snapshot_at, snapshot_task_id, snapshot_status = _cli_result_parts(snapshot_result)
                                full_records = list(snapshot_value or [])
                                snapshot_status_name = str(snapshot_status.get("status") or "").strip().lower()
                                if _is_complete_full_snapshot(snapshot_status, full_records):
                                    snapshot_at = snapshot_at or _now_iso()
                                    snapshot_negative = snapshot_status_name == "not_found"
                                    snapshot_retain_seconds = _snapshot_retain_seconds(
                                        cache, "mac", snapshot_negative
                                    )
                                    persisted_snapshot = _persist_observation(
                                        tenant_id=tenant_id,
                                        scope_hash=scope_hash,
                                        network_domain_id=network_domain_id,
                                        site_id=site_id,
                                        vrf=vrf,
                                        device_id=current_id,
                                        kind="mac",
                                        records=full_records,
                                        coverage="full",
                                        fresh_seconds=15 if snapshot_negative else None,
                                        retain_seconds=snapshot_retain_seconds,
                                        collected_at=snapshot_at,
                                        query_task_id=snapshot_task_id,
                                        result=result,
                                        device=current,
                                        target=mac_snapshot_target,
                                    )
                                    if persisted_snapshot:
                                        reconciliation = _reconcile_full_snapshot_absences(
                                            tenant_id=tenant_id,
                                            scope_hash=scope_hash,
                                            network_domain_id=network_domain_id,
                                            site_id=site_id,
                                            vrf=vrf,
                                            device_id=current_id,
                                            kind="mac",
                                            records=full_records,
                                            status=snapshot_status,
                                            collected_at=snapshot_at,
                                            query_task_id=snapshot_task_id,
                                            retain_seconds=_configured_observation_retain_seconds(cache, "mac"),
                                            versions=persisted_snapshot,
                                        )
                                        if reconciliation and reconciliation.get("applied"):
                                            redis_write_attempted = _redis_write_configured(cache, mac_snapshot_key)
                                            redis_write_ack = None
                                            if cache is not None and mac_snapshot_key:
                                                redis_write_ack = cache.set_json(
                                                    mac_snapshot_key,
                                                    _fenced_observation_payload(result, {
                                                        "negative": snapshot_negative,
                                                        "records": full_records,
                                                        "collected_at": snapshot_at,
                                                    }, persisted_snapshot),
                                                    kind="negative" if snapshot_negative else "mac",
                                                    collected_at=snapshot_at,
                                                    retain_seconds=15 if snapshot_negative else None,
                                                ) is True
                                            records = [
                                                dict(record)
                                                for record in full_records
                                                if isinstance(record, dict)
                                                and legacy._normalize_mac(str(record.get("mac") or "")) == mac
                                            ]
                                            mac_collected_at = snapshot_at
                                            mac_task_id = snapshot_task_id
                                            mac_negative = not records
                                            status = {
                                                "status": "found" if records else "not_found",
                                                "source": "full_snapshot",
                                            }
                                            _set_cache_source(
                                                result,
                                                "mac",
                                                current,
                                                "snapshot_negative_cli" if mac_negative else "snapshot_cli",
                                                vrf=vrf,
                                                variant="full_snapshot",
                                                redis_write_attempted=redis_write_attempted,
                                                redis_write_ack=redis_write_ack,
                                            )
                                        else:
                                            storage_failed = True
                                            records = []
                                            status = {"status": "query_failed", "error_code": "OBSERVATION_RECONCILE_FAILED"}
                                            reconciliation_reason = (
                                                (reconciliation or {}).get("reason") or "persistence_failed"
                                            )
                                            result["coverage_gaps"].append(
                                                f"observation_reconcile_failed:{current_id}:mac_snapshot:{reconciliation_reason}"
                                            )
                                            result["errors"].append(f"{label} MAC 快照失效协调失败")
                                    else:
                                        storage_failed = True
                                        records = []
                                        status = {"status": "query_failed", "error_code": "OBSERVATION_PERSIST_FAILED"}
                                        result["coverage_gaps"].append(
                                            f"observation_persist_failed:{current_id}:mac_snapshot"
                                        )
                                else:
                                    records = []
                                    snapshot_status_name = _snapshot_failure_reason(snapshot_status, full_records)
                                    status = {"status": snapshot_status_name}
                                    result["errors"].append(
                                        f"{label} MAC 全表快照{snapshot_status_name}"
                                    )
                                    result["coverage_gaps"].append(
                                        f"mac_snapshot_{snapshot_status_name}:{current_id}"
                                    )
                        if records:
                            persisted = _persist_observation(
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
                                collected_at=mac_collected_at,
                                query_task_id=mac_task_id,
                                result=result,
                                device=current,
                                target=mac_snapshot_target if full_snapshot_records is not None else mac_target,
                            )
                            if persisted:
                                redis_write_attempted = _redis_write_configured(cache, mac_key)
                                redis_write_ack = None
                                if cache is not None and mac_key:
                                    redis_write_ack = cache.set_json(
                                        mac_key,
                                        _fenced_observation_payload(
                                            result,
                                            {"records": records, "status": status, "collected_at": mac_collected_at},
                                            persisted,
                                        ),
                                        kind="mac",
                                        collected_at=mac_collected_at,
                                    ) is True
                                _set_cache_source(
                                    result,
                                    "mac",
                                    current,
                                    "cli",
                                    vrf=vrf,
                                    redis_write_attempted=redis_write_attempted,
                                    redis_write_ack=redis_write_ack,
                                )
                            else:
                                storage_failed = True
                                result["coverage_gaps"].append(f"observation_persist_failed:{current_id}:mac")
                        elif isinstance(status, dict) and status.get("status") == "not_found":
                            mac_negative = True
                            persisted = _persist_observation(
                                tenant_id=tenant_id,
                                scope_hash=scope_hash,
                                network_domain_id=network_domain_id,
                                site_id=site_id,
                                vrf=vrf,
                                device_id=current_id,
                                kind="mac",
                                target_mac=mac,
                                vlan_id=vlan_hint,
                                records={"not_found": True, "status": status},
                                fresh_seconds=15,
                                retain_seconds=15,
                                collected_at=mac_collected_at,
                                query_task_id=mac_task_id,
                                result=result,
                                device=current,
                                target=mac_target,
                            )
                            if persisted:
                                redis_write_attempted = _redis_write_configured(cache, mac_key)
                                redis_write_ack = None
                                if cache is not None and mac_key:
                                    redis_write_ack = cache.set_json(
                                        mac_key,
                                        _fenced_observation_payload(
                                            result,
                                            {"negative": True, "records": [], "status": status, "collected_at": mac_collected_at},
                                            persisted,
                                        ),
                                        kind="negative",
                                        collected_at=mac_collected_at,
                                        retain_seconds=15,
                                    ) is True
                                _set_cache_source(
                                    result,
                                    "mac",
                                    current,
                                    "negative_cli",
                                    vrf=vrf,
                                    redis_write_attempted=redis_write_attempted,
                                    redis_write_ack=redis_write_ack,
                                )
                            else:
                                storage_failed = True
                                result["coverage_gaps"].append(f"observation_persist_failed:{current_id}:mac")
                    if records:
                        if len(records) > limits.max_candidates_per_hop:
                            result["coverage_gaps"].append(f"mac_candidate_budget_exceeded:{current_id}")
                        _include_evidence_timestamp(result, mac_collected_at)
                except Exception as exc:
                    records = []
                    status = {"status": "query_failed", "reason": str(exc)}
                    result["coverage_gaps"].append(f"mac_failed:{current_id}")
                    _set_cache_source(result, "mac", current, "query_failed", vrf=vrf)
                if records and vlan_hint:
                    vlan_records = [
                        record for record in records
                        if str(record.get("vlan") or "").strip() == vlan_hint
                    ]
                    unknown_vlan_records = [record for record in records if not str(record.get("vlan") or "").strip()]
                    if vlan_records:
                        records = vlan_records
                    elif unknown_vlan_records:
                        records = []
                        status = {"status": "vlan_unknown"}
                        result["coverage_gaps"].append(f"mac_vlan_evidence_missing:{current_id}")
                    else:
                        records = []
                        status = {"status": "not_found"}
                if not records:
                    if isinstance(status, dict) and status.get("status") == "vlan_unknown":
                        result["errors"].append(f"{label} 的 MAC 记录缺少 VLAN，不能确认二层域")
                        continue
                    mac_status = str(status.get("status") or "").strip().lower() if isinstance(status, dict) else ""
                    gateway_id = str(arp.get("device_id") or arp.get("source_device_id") or "")
                    if (
                        mac_status in {"unsupported", "disabled"}
                        and current_id == gateway_id
                    ):
                        lookup_ports = []
                        for candidate_port in (
                            arp.get("interface"),
                            (l3_path[-1].get("interface") if l3_path else ""),
                        ):
                            selected_port = str(candidate_port or "").strip()
                            normalized_port = legacy.normalize_interface_name(selected_port).lower()
                            if selected_port and all(
                                legacy.normalize_interface_name(existing).lower() != normalized_port
                                for existing in lookup_ports
                            ):
                                lookup_ports.append(selected_port)
                        downstream = []
                        discovered_port = ""
                        for candidate_port in lookup_ports:
                            downstream = _topology_neighbors(conn, current_id, candidate_port) if conn is not None else []
                            if not downstream:
                                downstream, _, _, neighbor_status = _load_lldp_snapshot(
                                    current,
                                    candidate_port,
                                    cache=cache,
                                    scope=scope,
                                    scope_hash=scope_hash,
                                    tenant_id=tenant_id,
                                    target_ip=target_ip,
                                    network_domain_id=network_domain_id,
                                    site_id=site_id,
                                    vrf=vrf,
                                    force_refresh=force_refresh,
                                    durable_run_id=durable_run_id,
                                    run_owner_id=run_owner_id,
                                    cancel_check=cancel_check,
                                    result=result,
                                    wait_seconds=max(1, min(30, int(deadline - time.monotonic()))),
                                )
                                if neighbor_status.get("status") in {"unsupported", "query_failed", "parse_incomplete"}:
                                    result["coverage_gaps"].append(
                                        f"neighbor_{neighbor_status.get('status')}:{current_id}"
                                    )
                            if downstream:
                                discovered_port = candidate_port
                                break
                        if len(downstream) > limits.max_candidates_per_hop:
                            result["coverage_gaps"].append(
                                f"neighbor_candidate_budget_exceeded:{current_id}:{discovered_port}"
                            )
                        child_devices = []
                        for neighbor in downstream[: limits.max_candidates_per_hop]:
                            neighbor_candidates = (
                                _neighbor_device_candidates(conn, neighbor, by_id)
                                if conn is not None else []
                            )
                            if len(neighbor_candidates) > 1:
                                result["coverage_gaps"].append(
                                    f"neighbor_ambiguous:{neighbor.get('neighbor_ip') or neighbor.get('neighbor_name') or current_id}"
                                )
                            neighbor_device = neighbor_candidates[0] if len(neighbor_candidates) == 1 else None
                            if neighbor_device and str(neighbor_device.get("id") or "") not in visited:
                                child_devices.append(neighbor_device)
                            elif neighbor.get("neighbor_name") or neighbor.get("neighbor_id"):
                                result["coverage_gaps"].append(
                                    f"neighbor_unmanaged:{neighbor.get('neighbor_name') or neighbor.get('neighbor_id')}"
                                )
                        if child_devices and discovered_port:
                            bridge_hop = {
                                "device_id": current_id,
                                "device": label,
                                "port": discovered_port,
                                "mac": mac,
                                "vlan": vlan_hint,
                                "type": "l3_egress",
                                "source": "arp_interface_topology",
                                "is_uplink": True,
                                "neighbors": [
                                    {"device_id": str(item.get("id") or ""), "device": _device_label(item)}
                                    for item in child_devices
                                ],
                            }
                            result["l2_paths"].append({
                                "l3_path": l3_path,
                                "hops": path + [bridge_hop],
                            })
                            for child in child_devices:
                                queue.append((child, path + [bridge_hop], visited))
                            continue
                        result["coverage_gaps"].append(
                            f"l2_entry_unknown:{current_id}:{discovered_port or (lookup_ports[0] if lookup_ports else 'unknown')}"
                        )
                        result["errors"].append(
                            f"{label} 无 MAC/FDB 能力，且 ARP 出接口无法映射到唯一的下游交换机"
                        )
                        continue
                    if mac_status in {"unsupported", "disabled"}:
                        result["coverage_gaps"].append(f"mac_unsupported:{current_id}")
                        result["coverage_gaps"].append(f"l2_entry_unknown:{current_id}:unknown")
                        result["errors"].append(f"{label} 不支持目标 MAC/FDB 查询")
                        continue
                    result["coverage_gaps"].append(f"mac_not_found:{current_id}")
                    if mac_status in {"query_failed", "parse_incomplete"}:
                        result["coverage_gaps"].append(f"mac_{mac_status}:{current_id}")
                        result["errors"].append(f"{label} MAC 查询{mac_status}")
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
                        "collected_at": mac_collected_at or _now_iso(),
                    }
                    result["l2_paths"].append({"l3_path": l3_path, "hops": path + [hop]})
                    hop_age = _route_age_seconds(mac_collected_at)
                    if hop_age is not None:
                        result["freshness"]["mac"] = max(int(result["freshness"]["mac"] or 0), hop_age)
                    _include_evidence_timestamp(result, mac_collected_at)
                    topology: list[dict[str, Any]] = []
                    topology_collected_at = ""
                    if conn is not None:
                        topology = _topology_neighbors(conn, current_id, port)
                    terminal_identity = (
                        _terminal_evidence(conn, current_id, port)
                        if conn is not None else {"is_terminal": False}
                    )
                    if topology:
                        topology_collected_at = min(
                            (str(item.get("last_seen") or "") for item in topology if item.get("last_seen")),
                            default="",
                        )
                        _set_cache_source(
                            result,
                            "topology",
                            current,
                            "postgres",
                            vrf=vrf,
                            variant="topology_links",
                        )
                    elif not terminal_identity.get("is_terminal") or force_refresh:
                        topology, topology_collected_at, _, topology_status = _load_lldp_snapshot(
                            current,
                            port,
                            cache=cache,
                            scope=scope,
                            scope_hash=scope_hash,
                            tenant_id=tenant_id,
                            target_ip=target_ip,
                            network_domain_id=network_domain_id,
                            site_id=site_id,
                            vrf=vrf,
                            force_refresh=force_refresh,
                            durable_run_id=durable_run_id,
                            run_owner_id=run_owner_id,
                            cancel_check=cancel_check,
                            result=result,
                            wait_seconds=max(1, min(30, int(deadline - time.monotonic()))),
                        )
                        if topology_status.get("status") in {"unsupported", "query_failed", "parse_incomplete"}:
                            status_name = str(topology_status.get("status") or "query_failed")
                            result["errors"].append(f"{label} 邻居查询{status_name}")
                            result["coverage_gaps"].append(f"neighbor_{status_name}:{current_id}")
                            # A failed/unsupported discovery is not evidence
                            # that an access port has no downstream switch.
                            continue
                    child_devices: list[dict[str, Any]] = []
                    if len(topology) > limits.max_candidates_per_hop:
                        result["coverage_gaps"].append(f"neighbor_candidate_budget_exceeded:{current_id}:{port}")
                    for neighbor in topology[: limits.max_candidates_per_hop]:
                        neighbor_candidates = (
                            _neighbor_device_candidates(conn, neighbor, by_id)
                            if conn is not None else []
                        )
                        if len(neighbor_candidates) > 1:
                            result["coverage_gaps"].append(
                                f"neighbor_ambiguous:{neighbor.get('neighbor_ip') or neighbor.get('neighbor_name') or current_id}"
                            )
                        neighbor_device = neighbor_candidates[0] if len(neighbor_candidates) == 1 else None
                        neighbor_id = str((neighbor_device or {}).get("id") or neighbor.get("neighbor_id") or "")
                        if neighbor_device and neighbor_id not in visited:
                            child_devices.append(neighbor_device)
                        elif neighbor.get("neighbor_name") or neighbor_id:
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

                    identity = terminal_identity
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
                if len(queried_device_ids) >= limits.max_devices and queue:
                    result["coverage_gaps"].append("device_budget_exceeded")
                    break
            if queue and deadline_exceeded and "task_deadline_exceeded" not in result["coverage_gaps"]:
                result["coverage_gaps"].append("task_deadline_exceeded")
    finally:
        if conn is not None:
            conn.close()

    if cancelled:
        result["status"] = "cancelled"
        result["conclusion"] = "cancelled"
        result["completed_at"] = _now_iso()
        return result

    unique_candidates: dict[tuple[str, str, str], dict[str, Any]] = {}
    for candidate in final_candidates:
        candidate_key = (
            str(candidate.get("device_id") or ""),
            str(candidate.get("port") or ""),
            str(candidate.get("vlan") or ""),
        )
        unique_candidates.setdefault(candidate_key, candidate)
    final_candidates = list(unique_candidates.values())
    result["terminal_candidates"] = final_candidates
    fatal_gap_prefixes = (
        "route_failed:",
        "route_candidate_budget_exceeded:",
        "unsupported_platform:",
        "observation_persist_failed:",
        "next_hop_unmanaged:",
        "next_hop_ambiguous:",
        "next_hop_candidate_budget_exceeded:",
        "neighbor_ambiguous:",
        "route_loop:",
        "next_hop_out_of_scope:",
        "device_budget_exceeded",
        "task_deadline_exceeded",
        "L2 路径超过",
        "L3 路径超过",
        "core_candidate_budget_exceeded",
        "mac_candidate_budget_exceeded:",
        "neighbor_candidate_budget_exceeded:",
        "l2_entry_unknown:",
        "topology_incomplete:",
        "neighbor_unmanaged:",
        "mac_failed:",
        "mac_unsupported:",
        "mac_query_failed:",
        "mac_parse_incomplete:",
        "mac_not_found:",
        "mac_vlan_evidence_missing:",
        "arp_failed:",
        "arp_query_failed:",
        "arp_unsupported:",
        "arp_parse_incomplete:",
        "arp_proxy_or_virtual_gateway:",
        "arp_ambiguous:",
    )
    has_unverified_branch = any(
        any(str(gap).startswith(prefix) for prefix in fatal_gap_prefixes)
        for gap in result["coverage_gaps"]
    )
    if len(final_candidates) == 1 and not has_unverified_branch and not deadline_exceeded:
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
            collected_at=str(result.get("evidence_collected_at") or _now_iso()),
            result=result,
        )
    elif len(final_candidates) > 1:
        result["found"] = False
        result["status"] = "partial"
        result["conclusion"] = "ambiguous_terminal_candidates"
    elif len(final_candidates) == 1:
        result["found"] = False
        result["status"] = "partial"
        result["conclusion"] = (
            "deadline_exceeded_with_candidate"
            if deadline_exceeded or "task_deadline_exceeded" in result["coverage_gaps"]
            else "path_has_unverified_branch"
        )
        result["location"] = final_candidates[0]
    else:
        result["status"] = "partial"
        result["conclusion"] = "topology_incomplete" if result["l2_paths"] else "mac_not_found"
        mac_errors = any(
            str(gap).startswith((
                "mac_failed:",
                "mac_unsupported:",
                "mac_query_failed:",
                "mac_parse_incomplete:",
                "mac_vlan_evidence_missing:",
                "l2_entry_unknown:",
            ))
            for gap in result["coverage_gaps"]
        )
        if any(str(gap).startswith("l2_entry_unknown:") for gap in result["coverage_gaps"]):
            result["conclusion"] = "l2_entry_unknown"
        elif arp_hits and not result["l2_paths"] and not mac_errors:
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
    result["completed_at"] = _now_iso()
    if (
        cache is not None
        and result_key
        and result.get("status") == "completed"
        and _manifest_is_current_for_code(result.get("dependency_manifest"))
        and not _pending_fact_invalidation(scope_hash, target_ip)
    ):
        redis_write_ack = cache.set_json(
            result_key,
            result,
            kind="result",
            collected_at=result.get("evidence_collected_at") or result.get("completed_at"),
        )
        _set_cache_source(
            result,
            "result",
            {"hostname": "whole-result"},
            "miss",
            vrf=vrf,
            variant="whole_result",
            redis_write_attempted=_redis_write_configured(cache, result_key),
            redis_write_ack=redis_write_ack,
        )
    return result


def trace_ip(target_ip: str, **kwargs: Any) -> dict[str, Any]:
    """Run one trace with a Redis single-flight guard when available."""
    durable_run_id = str(kwargs.get("durable_run_id") or "")
    force_refresh = bool(kwargs.get("force_refresh", False))
    tenant_id = str(kwargs.get("tenant_id") or "tenant-default")
    site_id = str(kwargs.get("site_id") or "")
    network_domain_id = str(kwargs.get("network_domain_id") or "")
    vrf = _normalise_vrf(kwargs.get("vrf") or "default")
    start_device_id = str(kwargs.get("start_device_id") or "")
    authorized_device_ids = kwargs.get("authorized_device_ids")
    scope = {
        "tenant_id": tenant_id,
        "site_id": site_id,
        "network_domain_id": network_domain_id,
        "vrf": vrf,
        "start_device_id": start_device_id,
        "authorization_scope_hash": _authorization_scope_hash(authorized_device_ids),
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
    if isinstance(cached, dict) and cache.is_fresh(
        "result",
        cached.get("evidence_collected_at") or cached.get("completed_at") or cached.get("created_at"),
    ) and _manifest_is_current_for_code(cached.get("dependency_manifest")) and not _pending_fact_invalidation(scope_hash, target_ip):
        cached = _copy_cached_result_for_request(cached)
        if durable_run_id:
            cached["run_id"] = durable_run_id
        _set_cache_source(
            cached,
            "result",
            {"hostname": "whole-result"},
            "redis",
            vrf=vrf,
            variant="whole_result",
        )
        cached["cache"] = {**dict(cached.get("cache") or {}), "result": "hit"}
        return cached

    task_deadline = max(1, int(kwargs.get("deadline_seconds") or 180))
    lock_ttl = max(30, task_deadline)
    token = cache.acquire_lock(lock_key, ttl=lock_ttl)
    if token is None and cache.ping() is not True:
        # Redis failure degrades to scoped PostgreSQL observations plus the
        # deployment-wide/device PostgreSQL leases. Never treat cache failure
        # as permission to open unbudgeted CLI sessions.
        return _trace_ip_uncached(target_ip, **kwargs)
    if token is None:
        # Another worker owns the single-flight query. Wait for its result or
        # for its bounded lease to expire, then compete for the lock again.
        # Do not start a duplicate path merely because the first CLI hop is slow.
        wait_until = time.monotonic() + task_deadline
        while time.monotonic() < wait_until:
            cached = cache.get_json(result_key)
            if isinstance(cached, dict) and cache.is_fresh(
                "result",
                cached.get("evidence_collected_at") or cached.get("completed_at") or cached.get("created_at"),
            ) and _manifest_is_current_for_code(cached.get("dependency_manifest")) and not _pending_fact_invalidation(scope_hash, target_ip):
                cached = _copy_cached_result_for_request(cached)
                if durable_run_id:
                    cached["run_id"] = durable_run_id
                _set_cache_source(
                    cached,
                    "result",
                    {"hostname": "whole-result"},
                    "redis",
                    vrf=vrf,
                    variant="whole_result",
                )
                cached["cache"] = {**dict(cached.get("cache") or {}), "result": "hit"}
                return cached
            token = cache.acquire_lock(lock_key, ttl=lock_ttl)
            if token is not None:
                break
            if cache.ping() is not True:
                return _trace_ip_uncached(target_ip, **kwargs)
            time.sleep(0.2)
        if token is None:
            return {
                "run_id": durable_run_id or str(uuid.uuid4()),
                "target_ip": target_ip,
                "status": "partial",
                "conclusion": "singleflight_timeout",
                "found": False,
                "cache": {"result": "waiting_on_shared_run"},
                "coverage_gaps": ["同一目标的共享定位任务仍在运行，请稍后查询"],
                "errors": [],
                "timestamp": _now_iso(),
            }
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

    The response keeps its explicit evidence fields while exposing aliases
    consumed by the existing IP locator page.
    """
    enriched = dict(result)
    location = enriched.get("location")
    if isinstance(location, dict):
        conclusion = str(enriched.get("conclusion") or "")
        location_type = (
            "PATH_TRACED"
            if conclusion == "managed_access_confirmed"
            else "DEVICE_INTERFACE"
            if conclusion == "device_interface"
            else "ARP_DIRECT"
            if conclusion == "arp_only"
            else "TRACE_INCOMPLETE"
        )
        enriched["locations"] = [{
            "switch_id": location.get("device_id") or "",
            "switch_name": location.get("device") or "",
            "port": location.get("port") or "",
            "vlan": location.get("vlan") or "",
            "type": location_type,
            "is_uplink": location_type == "TRACE_INCOMPLETE",
            "note": "CLI 四阶段路径追踪结果",
        }]
        enriched["mac"] = location.get("mac") or enriched.get("mac")
        if enriched.get("mac"):
            enriched["mac_display"] = legacy._format_mac(str(enriched["mac"]))
    else:
        candidates = enriched.get("terminal_candidates") or []
        enriched["locations"] = [
            {
                "switch_id": item.get("device_id") or "",
                "switch_name": item.get("device") or "",
                "port": item.get("port") or "",
                "vlan": item.get("vlan") or "",
                "type": "TRACE_INCOMPLETE",
                "is_uplink": True,
                "note": "存在多个或尚未确认的接入候选",
            }
            for item in candidates
        ]
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
        "device_interface": "device_interface",
        "arp_only": "arp_only",
        "topology_incomplete": "incomplete",
        "ambiguous_terminal_candidates": "incomplete",
        "path_has_unverified_branch": "incomplete",
        "deadline_exceeded": "incomplete",
        "deadline_exceeded_with_candidate": "incomplete",
        "mac_not_found": "incomplete",
        "arp_not_found": "not_found",
        "no_route": "not_found",
        "no_direct_gateway": "incomplete",
        "network_domain_scope_unavailable": "incomplete",
    }.get(str(enriched.get("conclusion") or ""), str(enriched.get("status") or "unknown"))
    enriched.setdefault("timestamp", enriched.get("completed_at") or enriched.get("created_at") or _now_iso())
    searched = enriched.get("queried_devices") or {}
    enriched["searched_devices"] = {
        "arp": list(searched.get("arp") or []),
        "mac": list(searched.get("mac") or []),
        "lldp": list(searched.get("lldp") or []),
    }
    if not isinstance(enriched.get("mac_lookup"), dict):
        coverage = [str(item) for item in enriched.get("coverage_gaps") or []]
        mac_status = (
            "found" if enriched.get("conclusion") == "managed_access_confirmed"
            else "query_failed" if any("mac_failed:" in item for item in coverage)
            else "unsupported" if any("unsupported" in item for item in coverage)
            else "not_found" if any("mac_not_found:" in item for item in coverage)
            else "not_attempted"
        )
        enriched["mac_lookup"] = {"status": mac_status}
    if enriched.get("coverage_gaps"):
        existing_errors = list(enriched.get("errors") or [])
        for gap in enriched["coverage_gaps"]:
            message = str(gap)
            if message not in existing_errors:
                existing_errors.append(message)
        enriched["errors"] = existing_errors
    cache = dict(enriched.get("cache") or {})
    cache.setdefault("enabled", True)
    cache.setdefault("arp_cache_hit", cache.get("arp") == "hit")
    cache.setdefault("ttl_seconds", 300)
    cache.setdefault("force_refresh", False)
    enriched["cache"] = cache
    if not isinstance(enriched.get("context"), dict):
        target_ip = str(enriched.get("target_ip") or "").strip()
        context_builder = getattr(legacy, "_get_ip_locator_context", None)
        if target_ip and callable(context_builder):
            try:
                context = context_builder(
                    target_ip,
                    enriched,
                    allow_live_interface_status=False,
                )
                if isinstance(context, dict):
                    enriched["context"] = context
            except Exception as exc:
                # Context is supplemental: a missing projection must never
                # turn a verified L2/L3 location into a failed run.
                logger.debug(
                    "[IPLocatorV2] locator context projection unavailable (%s)",
                    type(exc).__name__,
                )
    return enriched
