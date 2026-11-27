"""Bounded, positive-only live facts for the IP locator.

This adapter never runs a collector sweep, changes device configuration, or
replaces current ARP/FDB generations. The trace owns persistence and fallback.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from core.interface_utils import normalize_interface_name
from database import get_db_connection


@dataclass(frozen=True)
class LocatorFact:
    kind: str
    record: dict[str, Any]
    observed_at: str
    source: str = "snmp_targeted"
    coverage: str = "targeted"


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict").strip()
    return str(value or "").strip()


def _port_key(value: Any) -> str:
    return normalize_interface_name(_text(value)).strip().lower()


def _mac(value: Any) -> str:
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).hex()
    compact = re.sub(r"[:.\-]", "", str(value or "").strip().lower())
    if not re.fullmatch(r"[0-9a-f]{12}", compact):
        return ""
    if compact == "000000000000" or int(compact[:2], 16) & 1:
        return ""
    return compact


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("invalid integer")
    return int(value)


def _scope_profile(device: Mapping[str, Any], tenant_id: str, vrf: str):
    """Resolve exactly one explicitly mapped SNMP context for this request."""
    from services.snmp_collection_policy_service import is_snmp_collection_enabled
    from services.vault_service import resolve_collector_credentials

    device_id = str(device.get("id") or "")
    if not device_id or str(device.get("tenant_id") or "tenant-default") != tenant_id:
        return None
    if not is_snmp_collection_enabled(device):
        return None
    profile = dict(resolve_collector_credentials(dict(device)).get("snmp") or {})
    if not profile.get("configured"):
        return None
    version = str(profile.get("version") or "2c").lower().strip()
    if version not in {"1", "v1", "2", "2c", "v2c", "3", "v3", "snmpv3"}:
        return None
    is_v3 = version in {"3", "v3", "snmpv3"}
    with get_db_connection() as conn:
        rows = [dict(row) for row in conn.execute(
            """SELECT c.local_context_key, c.context_type, c.address_space_id,
                      s.kind, s.status AS space_status, s.security_tenant_id,
                      s.vrf_id, v.vrf_name
                 FROM ipam_device_routing_contexts c
                 LEFT JOIN ipam_address_spaces s ON s.id = c.address_space_id
                 LEFT JOIN vrfs v ON v.id = s.vrf_id
                WHERE c.device_id = ? AND c.context_source = 'snmp'
                  AND c.status = 'active'""", (device_id,),
        ).fetchall()]
    requested = str(vrf or "default").strip().lower()
    is_global = requested in {"", "default", "global"}
    matches = [
        row for row in rows
        if row.get("space_status") == "active"
        and str(row.get("security_tenant_id") or "tenant-default") == tenant_id
        and ((is_global and row.get("context_type") == row.get("kind") == "global")
             or (not is_global and row.get("context_type") == row.get("kind") == "vrf"
                 and requested in {str(row.get("vrf_id") or "").lower(),
                                   str(row.get("vrf_name") or "").lower()}))
    ]
    if len(matches) != 1:
        return None
    selected = matches[0]
    key = str(selected.get("local_context_key") or "")
    if sum(str(row.get("local_context_key") or "") == key for row in rows) != 1:
        return None
    if is_v3:
        profile["context_name"] = key
        auth: str | dict[str, Any] = profile
    else:
        # A community cannot select an arbitrary context. Only an explicitly
        # mapped, unambiguous default context is eligible for this adapter.
        if not is_global or len(rows) != 1 or key not in {"", "global"}:
            return None
        auth = str(profile.get("community") or "")
        if not auth:
            return None
    server = str(profile.get("server") or device.get("ip_address") or "").strip()
    port = int(profile.get("port") or 161)
    if not server or not 1 <= port <= 65535:
        return None
    return server, auth, port, version, str(selected["address_space_id"]), key


async def _get(client, oid: str) -> Any:
    from puresnmp import ObjectIdentifier
    raw = await client.get(ObjectIdentifier(oid))
    if raw is None or any(word in type(raw).__name__.lower()
                          for word in ("nosuch", "endofmib")):
        raise ValueError("missing SNMP instance")
    return getattr(raw, "value", raw)


async def _if_name(client, index: int) -> str:
    from services.snmp_service import IF_NAME, IF_DESCR
    try:
        name = _text(await _get(client, f"{IF_NAME}.{index}"))
    except Exception:
        name = ""
    return name or _text(await _get(client, f"{IF_DESCR}.{index}"))


async def _read_arp(client, target_ip: str, if_index: int, expected_port: str, vlan: int):
    from services.snmp_service import IP_NET_TO_MEDIA_PHYS_ADDRESS, IP_NET_TO_MEDIA_TYPE

    suffix = f"{if_index}.{ipaddress.IPv4Address(target_ip)}"
    name = await _if_name(client, if_index)
    if _port_key(name) != _port_key(expected_port):
        return None
    kind = _integer(await _get(client, f"{IP_NET_TO_MEDIA_TYPE}.{suffix}"))
    mac = _mac(await _get(client, f"{IP_NET_TO_MEDIA_PHYS_ADDRESS}.{suffix}"))
    if kind != 3 or not mac:
        return None
    return {"ip": target_ip, "mac": mac, "interface": name, "vlan": str(vlan),
            "type": "dynamic"}


async def _read_fdb(client, version: str, mac: str, vlan: int):
    from puresnmp import ObjectIdentifier
    from services.snmp_service import (
        DOT1Q_VLAN_FDB_ID, DOT1Q_TP_FDB_PORT, DOT1Q_TP_FDB_STATUS,
        DOT1D_BASE_PORT_IF_INDEX, IF_OPER_STATUS,
    )

    # The VLAN->FID mapping may use shared learning. Read only this small
    # mapping subtree, NOT the MAC table; reject shared or conflicting FIDs.
    root = DOT1Q_VLAN_FDB_ID
    walker = (client.walk(ObjectIdentifier(root)) if version in {"1", "v1"}
              else client.bulkwalk([ObjectIdentifier(root)], bulk_size=20))
    by_vlan: dict[int, set[int]] = {}
    count = 0
    async for binding in walker:
        oid = str(binding.oid).strip(".")
        if not oid.startswith(root + "."):
            break
        raw = binding.value
        if "endofmib" in type(raw).__name__.lower():
            break
        count += 1
        if count > 1024:
            return None
        parts = oid[len(root) + 1:].split(".")
        if len(parts) != 2:
            return None
        mark, observed_vlan = map(int, parts)
        fid = _integer(getattr(raw, "value", raw))
        if mark < 0 or not 1 <= observed_vlan <= 4094 or fid < 0:
            return None
        by_vlan.setdefault(observed_vlan, set()).add(fid)
    fids = by_vlan.get(vlan, set())
    if len(fids) != 1:
        return None
    fid = next(iter(fids))
    if any(other != vlan and fid in values for other, values in by_vlan.items()):
        return None
    suffix = ".".join([str(fid), *(str(value) for value in bytes.fromhex(mac))])
    bridge_port = _integer(await _get(client, f"{DOT1Q_TP_FDB_PORT}.{suffix}"))
    status = _integer(await _get(client, f"{DOT1Q_TP_FDB_STATUS}.{suffix}"))
    if bridge_port <= 0 or status != 3:
        return None
    index = _integer(await _get(client, f"{DOT1D_BASE_PORT_IF_INDEX}.{bridge_port}"))
    if index <= 0 or _integer(await _get(client, f"{IF_OPER_STATUS}.{index}")) != 1:
        return None
    port = await _if_name(client, index)
    if not port:
        return None
    # Do not accept a MAC that moved while bridge/ifIndex was being resolved.
    if (_integer(await _get(client, f"{DOT1Q_TP_FDB_PORT}.{suffix}")) != bridge_port
            or _integer(await _get(client, f"{DOT1Q_TP_FDB_STATUS}.{suffix}")) != 3):
        return None
    return {"mac": mac, "port": port, "vlan": str(vlan), "type": "dynamic",
            "if_index": index, "fdb_id": fid}


class TargetedFactReader:
    """One run's bounded SNMP adapter; all unsupported/missing facts fall back."""

    def __init__(self, *, tenant_id: str, vrf: str, allowed_ids: set[str],
                 deadline: float, enabled: bool = False, max_attempts: int = 4,
                 cancel_check=None):
        self.tenant_id = tenant_id
        self.vrf = vrf
        self.allowed_ids = frozenset(allowed_ids)
        self.deadline = deadline
        self.enabled = enabled
        self.remaining = max(0, min(4, int(max_attempts)))
        self.cancel_check = cancel_check

    def read(self, kind: str, device: dict[str, Any], *, target_ip: str = "",
             interface: str = "", mac: str = "", vlan: str = "") -> LocatorFact | None:
        if (not self.enabled or self.remaining <= 0
                or str(device.get("id") or "") not in self.allowed_ids
                or time.monotonic() >= self.deadline
                or kind not in {"arp", "mac"}):
            return None
        try:
            if callable(self.cancel_check) and self.cancel_check():
                return None
            profile = _scope_profile(device, self.tenant_id, self.vrf)
            if not profile:
                return None
            server, auth, port, version, space, context = profile
            if kind == "arp":
                from services.vlan_discovery_service import parse_vlan_id_from_interface
                address = str(ipaddress.IPv4Address(target_ip))
                # Restrict this first adapter to explicit SVI identities.
                # BVI/IRB/VE units need separate VLAN mapping and are excluded.
                if not re.fullmatch(r"vlan(?:if|[-_ ]?interface)?[-_ ]*\d+", interface.strip(), re.I):
                    return None
                target_vlan = parse_vlan_id_from_interface(interface)
                if not target_vlan:
                    return None
                with get_db_connection() as conn:
                    rows = [dict(row) for row in conn.execute(
                        "SELECT interface_name, if_index FROM interfaces WHERE device_id = ?",
                        (str(device["id"]),),
                    ).fetchall() if _port_key(row["interface_name"]) == _port_key(interface)]
                if len(rows) != 1 or int(rows[0].get("if_index") or 0) <= 0:
                    return None
                index = int(rows[0]["if_index"])
            else:
                compact = _mac(mac)
                target_vlan = int(vlan)
                if not compact or not 1 <= target_vlan <= 4094:
                    return None
            seconds = min(8.0, self.deadline - time.monotonic())
            if seconds <= 0:
                return None
            self.remaining -= 1

            async def collect():
                from services import snmp_service as snmp
                async with snmp.get_network_access_limiter().async_snmp():
                    client = snmp._build_versioned_snmp_client(server, auth, port, version)
                    if kind == "arp":
                        return await _read_arp(client, address, index, interface, target_vlan)
                    return await _read_fdb(client, version, compact, target_vlan)

            async def bounded():
                return await asyncio.wait_for(collect(), timeout=seconds)

            record = asyncio.run(bounded())
            if not record or time.monotonic() > self.deadline:
                return None
            if callable(self.cancel_check) and self.cancel_check():
                return None
            record.update({"address_space_id": space, "snmp_context_key": context,
                           "vrf": self.vrf})
            return LocatorFact(kind, record, datetime.now(timezone.utc).isoformat())
        except Exception:
            # NoSuchInstance, timeout, policy/context failure and malformed
            # replies are all inconclusive, never negative-cache evidence.
            return None
