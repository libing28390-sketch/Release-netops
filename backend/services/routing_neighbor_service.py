"""Credential-safe helpers for polling routing protocol neighbors over SNMP."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from services.vault_service import resolve_collector_credentials


ROUTING_NEIGHBOR_SNMP_TIMEOUT_SECONDS = 8.0


def _snmp_transport(device: Mapping[str, Any], credentials: Mapping[str, Any] | None = None) -> tuple[str, str | Mapping[str, Any], int, str]:
    from services.snmp_collection_policy_service import is_snmp_collection_enabled

    if not is_snmp_collection_enabled(device):
        raise RuntimeError("SNMP collection is disabled for this device")
    resolved = dict(credentials or resolve_collector_credentials(dict(device)).get("snmp") or {})
    version = str(resolved.get("version") or "2c").strip().casefold()
    is_v3 = version in {"3", "v3", "snmpv3"}
    host = str(resolved.get("server") or device.get("ip_address") or "").strip()
    community_or_profile: str | Mapping[str, Any] = dict(resolved) if is_v3 else str(resolved.get("community") or "")
    try:
        port = int(resolved.get("port") or 161)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("SNMP port is invalid") from exc

    if not resolved.get("configured"):
        raise RuntimeError("SNMP credentials are not configured")
    if not host:
        raise RuntimeError("SNMP target address is missing")
    if not 1 <= port <= 65535:
        raise ValueError("SNMP port is outside the valid range")
    if is_v3:
        if not str(resolved.get("username") or "").strip():
            raise RuntimeError("SNMPv3 username is missing")
    elif not str(community_or_profile).strip():
        raise RuntimeError("SNMP community is missing")

    return host, community_or_profile, port, "3" if is_v3 else version


def collect_device_routing_neighbors_snmp(
    device: Mapping[str, Any],
    protocol: str,
    *,
    snmp_credentials: Mapping[str, Any] | None = None,
    timeout: float = ROUTING_NEIGHBOR_SNMP_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Return one complete BGP/OSPF SNMP snapshot or raise without partial rows.

    Call from a synchronous worker thread. The underlying collector validates
    table-column completeness before returning; callers must not treat an
    exception or an empty table as evidence that previous neighbors went down.
    """
    normalized_protocol = str(protocol or "").strip().casefold()
    if normalized_protocol not in {"bgp", "ospf"}:
        raise ValueError("Only BGP and OSPF neighbor polling is supported here")

    host, community_or_profile, port, version = _snmp_transport(device, snmp_credentials)

    from services.snmp_service import collect_snmp_routing_neighbors

    records = asyncio.run(collect_snmp_routing_neighbors(
        host,
        community_or_profile,
        normalized_protocol,
        port,
        version=version,
        timeout=max(1.0, float(timeout)),
    ))
    if not isinstance(records, list):
        raise RuntimeError("SNMP routing-neighbor collector returned an invalid result")
    if not records:
        return {"protocol": normalized_protocol, "status": "no_neighbors", "records": []}
    if any(not isinstance(record, dict) for record in records):
        raise RuntimeError("SNMP routing-neighbor snapshot contains invalid rows")
    return {"protocol": normalized_protocol, "status": "success", "records": records}
