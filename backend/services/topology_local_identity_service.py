"""Collect the current device's own interface IP identities.

This collector is deliberately read-only and run-scoped.  It does not infer an
address from a neighbour name, and it does not consult persisted observations.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
from typing import Any, Iterable

logger = logging.getLogger(__name__)

IP_AD_ENT_ADDR_OID = "1.3.6.1.2.1.4.20.1.1"
IP_ADDRESS_IF_INDEX_OID = "1.3.6.1.2.1.4.34.1.3"
MAX_IP_ADDRESSES = 2048
SNMP_TIMEOUT_SECONDS = 3.0


def _snmp_walk(*args: Any, **kwargs: Any) -> Any:
    """Late-bind the existing SNMP helper so tests and callers can patch it."""
    from services.snmp_service import _snmp_walk as walk

    return walk(*args, **kwargs)


def execute_platform_action(*args: Any, **kwargs: Any) -> Any:
    """Late-bind the platform action boundary for patchable read-only calls."""
    from services.platform_registry_service import execute_platform_action as execute

    return execute(*args, **kwargs)


def collect_operational_data(*args: Any, **kwargs: Any) -> Any:
    """Late-bind the legacy multi-vendor operational collector."""
    from services.operational_data_service import collect_operational_data as collect

    return collect(*args, **kwargs)


def _protocol_status(protocol_results: Any, protocol: str) -> str:
    if not isinstance(protocol_results, dict):
        return ""
    result = protocol_results.get(protocol)
    if not isinstance(result, dict):
        return ""
    return str(result.get("status") or "").strip().lower()


def _credential_section(credentials: Any, name: str) -> dict[str, Any]:
    if not isinstance(credentials, dict):
        return {}
    section = credentials.get(name)
    return dict(section) if isinstance(section, dict) else {}


def _snmp_parameters(device: dict[str, Any], credentials: Any) -> tuple[str, str, int, str] | None:
    snmp = _credential_section(credentials, "snmp")
    community = str(
        snmp.get("community")
        or snmp.get("snmp_community")
        or (credentials.get("snmp_community") if isinstance(credentials, dict) else "")
        or ""
    ).strip()
    # An absent community is intentionally not replaced with a public/default
    # value.  This is also the gate that prevents an unauthenticated walk.
    if not community:
        return None

    server = str(snmp.get("server") or device.get("ip_address") or "").strip()
    if not server:
        return None
    raw_port = snmp.get("port", device.get("snmp_port", 161))
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        return None
    if not 1 <= port <= 65535:
        return None
    version = str(snmp.get("version") or "2c").strip().lower() or "2c"
    return server, community, port, version


def _normalise_snmp_suffix(raw_suffix: Any) -> list[int] | None:
    text = str(raw_suffix or "").strip().strip(".")
    if not text or not re.fullmatch(r"\d+(?:\.\d+)*", text):
        return None
    try:
        return [int(part) for part in text.split(".")]
    except ValueError:
        return None


def _ip_from_ip_address_if_index_suffix(raw_suffix: Any) -> str | None:
    """Decode the IP-MIB ``{addressType,address}`` index."""
    text = str(raw_suffix or "").strip()
    if ":" in text:
        # A few test doubles and SNMP wrappers expose the decoded address.
        return text.split("/", 1)[0]
    parts = _normalise_snmp_suffix(text)
    if not parts or len(parts) < 2:
        return None
    address_type, address_length = parts[0], parts[1]
    if address_type == 1 and address_length == 4 and len(parts) == 6:
        octets = parts[2:6]
        if all(0 <= value <= 255 for value in octets):
            return ".".join(str(value) for value in octets)
    if address_type == 2 and address_length == 16 and len(parts) == 18:
        octets = parts[2:18]
        if all(0 <= value <= 255 for value in octets):
            try:
                return str(ipaddress.IPv6Address(bytes(octets)))
            except ipaddress.AddressValueError:
                return None
    # Some SNMP agents/walk wrappers omit the variable-length OCTET STRING
    # length in an index.  Accept that wire representation as well while
    # retaining the address type as the discriminator.
    if address_type == 1 and len(parts) == 5:
        octets = parts[1:5]
        if all(0 <= value <= 255 for value in octets):
            return ".".join(str(value) for value in octets)
    if address_type == 2 and len(parts) == 17:
        octets = parts[1:17]
        if all(0 <= value <= 255 for value in octets):
            try:
                return str(ipaddress.IPv6Address(bytes(octets)))
            except ipaddress.AddressValueError:
                return None
    return None


def _canonical_ip(value: Any) -> str | None:
    text = str(value or "").strip().strip("[](),;")
    if not text:
        return None
    # Interface records normally contain one value.  Trim CIDR/prefix data
    # without retaining it in the identity key.
    text = text.split("/", 1)[0].strip()
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    if address.is_unspecified or address.is_loopback or address.is_multicast or address.is_link_local:
        return None
    return address.compressed


def _canonical_ips(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if isinstance(raw, (list, tuple, set)):
            nested = raw
        else:
            text = str(raw or "")
            nested = re.split(r"[\s,;]+", text)
        for value in nested:
            candidate = _canonical_ip(value)
            if candidate and candidate not in seen:
                seen.add(candidate)
                result.append(candidate)
    return result


def _ips_from_snmp_rows(rows: Any, *, ip_address_if_index: bool) -> list[str]:
    if not isinstance(rows, (list, tuple)):
        return []
    candidates: list[Any] = []
    for row in rows:
        if isinstance(row, dict):
            suffix = row.get("oid") or row.get("index") or row.get("suffix")
        elif isinstance(row, (list, tuple)) and row:
            suffix = row[0]
        else:
            suffix = row
        if ip_address_if_index:
            decoded = _ip_from_ip_address_if_index_suffix(suffix)
            if decoded:
                candidates.append(decoded)
        else:
            # ipAdEntAddr's index is the address itself.  Do not use the
            # varbind value as an alias or infer identity from other fields.
            candidates.append(str(suffix or ""))
    return _canonical_ips(candidates)


async def _collect_snmp_ips(device: dict[str, Any], collector_credentials: Any) -> list[str]:
    parameters = _snmp_parameters(device, collector_credentials)
    if parameters is None:
        return []
    server, community, port, version = parameters
    addresses: list[str] = []
    for oid, is_ip_address_if_index in (
        (IP_AD_ENT_ADDR_OID, False),
        (IP_ADDRESS_IF_INDEX_OID, True),
    ):
        try:
            rows = await _snmp_walk(
                server,
                community,
                oid,
                port=port,
                timeout=SNMP_TIMEOUT_SECONDS,
                max_rows=MAX_IP_ADDRESSES,
                version=version,
                raise_on_error=True,
            )
            # A row count at the collector limit is indistinguishable from a
            # truncated walk.  Do not turn a partial table into confirmed
            # local identity; another complete table or CLI may still succeed.
            if isinstance(rows, (list, tuple)) and len(rows) >= MAX_IP_ADDRESSES:
                logger.warning("Local identity SNMP walk discarded as truncated (error_type=TruncatedWalk)")
                continue
            for address in _ips_from_snmp_rows(rows, ip_address_if_index=is_ip_address_if_index):
                if address not in addresses:
                    addresses.append(address)
                    if len(addresses) >= MAX_IP_ADDRESSES:
                        return addresses
        except Exception as exc:  # noqa: BLE001
            logger.warning("Local identity SNMP walk failed (error_type=%s)", type(exc).__name__)
    return addresses[:MAX_IP_ADDRESSES]


_IP_FIELD_NAMES = {
    "ip",
    "ip_address",
    "ip_addresses",
    "ipaddress",
    "ipv4",
    "ipv6",
    "ipv4_address",
    "ipv6_address",
    "primary_ip",
    "secondary_ip",
    "main_ip",
    "ip_address_primary",
    "ip_address_secondary",
    "ip_address_pri",
    "ip_address_sec",
}


def _is_explicit_ip_field(name: Any) -> bool:
    key = str(name or "").strip().replace("-", "_").lower()
    return key in _IP_FIELD_NAMES


def _ips_from_cli_records(records: Any) -> list[str]:
    if not isinstance(records, (list, tuple)):
        return []
    values: list[Any] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        for key, value in record.items():
            if _is_explicit_ip_field(key):
                values.append(value)
    return _canonical_ips(values)[:MAX_IP_ADDRESSES]


def _ssh_is_available(device: dict[str, Any], collector_credentials: Any) -> bool:
    if device.get("platform_profile_id"):
        return True
    if not isinstance(collector_credentials, dict) or "ssh" not in collector_credentials:
        return True
    ssh = _credential_section(collector_credentials, "ssh")
    return bool(ssh.get("username") and ssh.get("password"))


async def _collect_ssh_ips(
    device: dict[str, Any],
    collector_credentials: Any,
    platform_action_session: Any = None,
) -> list[str]:
    if not _ssh_is_available(device, collector_credentials):
        return []
    try:
        if device.get("platform_profile_id"):
            user = {
                "id": f"topology-local-identity:{device.get('id') or 'unknown'}",
                "username": "topology-local-identity",
                "role": "Operator",
                "tenant_id": device.get("tenant_id") or "",
            }
            action_kwargs: dict[str, Any] = {"user": user}
            if platform_action_session is not None:
                action_kwargs["_session"] = platform_action_session
            result = await asyncio.to_thread(
                execute_platform_action,
                str(device.get("id") or ""),
                "get_ip_interfaces",
                **action_kwargs,
            )
            if not isinstance(result, dict) or not result.get("success"):
                return []
            return _ips_from_cli_records(result.get("records") or [])

        payload = await asyncio.to_thread(
            collect_operational_data,
            device,
            categories=["interfaces"],
            auth_role="normal",
            _platform_action_session=platform_action_session,
        )
        if not isinstance(payload, dict):
            return []
        for category in payload.get("categories") or []:
            if isinstance(category, dict) and category.get("key") == "interfaces":
                if category.get("success") is False:
                    return []
                return _ips_from_cli_records(category.get("records") or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Local identity SSH collection failed (error_type=%s)", type(exc).__name__)
    return []


async def collect_topology_local_identity(
    device: dict[str, Any],
    collector_credentials: Any,
    *,
    protocol_results: dict[str, Any] | None = None,
    platform_action_session: Any = None,
) -> dict[str, Any]:
    """Collect canonical IP addresses owned by one connected device this run."""
    snmp_status = _protocol_status(protocol_results, "snmp")
    ssh_status = _protocol_status(protocol_results, "ssh")

    snmp_ips: list[str] = []
    if snmp_status != "failed":
        snmp_ips = await _collect_snmp_ips(device, collector_credentials)
    if snmp_ips:
        return {
            "ip_addresses": snmp_ips[:MAX_IP_ADDRESSES],
            "collection_sources": ["snmp"],
            "status": "success",
        }

    ssh_ips: list[str] = []
    # Honor the main collector's SNMP-only choice. An optional identity read
    # must not open SSH after LLDP completed without a CLI fallback.
    if ssh_status not in {"failed", "not_attempted", "not_configured"}:
        ssh_ips = await _collect_ssh_ips(device, collector_credentials, platform_action_session)
    if ssh_ips:
        return {
            "ip_addresses": ssh_ips[:MAX_IP_ADDRESSES],
            "collection_sources": ["ssh"],
            "status": "success",
        }
    return {"ip_addresses": [], "collection_sources": [], "status": "unavailable"}
