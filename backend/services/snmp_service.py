"""SNMP identity, IF-MIB interface monitoring, LLDP, and raw walk transport.

Hardware discovery and polling are owned by the bound LibreNMS runtime.
This module retains protocol and interface operations only.
"""

import asyncio
import hashlib
import inspect
import json
import math
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from services.network_access_limiter import get_network_access_limiter
import logging
import time as _time
from collections.abc import Mapping
from typing import Any, Optional

from services.snmp_counter_service import (
    calculate_counter_delta,
    load_counter_sample,
    save_counter_sample,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# SNMP 并发控制 — 限制全局同时进行的 SNMP 操作数
# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
# SNMP 采集结果短期缓存 — 避免同一设备短时间内重复采集
# ═══════════════════════════════════════════════════════════════
_SNMP_RESULT_CACHE_TTL = 20  # seconds
_snmp_result_cache: dict[str, tuple[float, object]] = {}


def _get_result_cache(key: str):
    entry = _snmp_result_cache.get(key)
    if entry and _time.monotonic() - entry[0] < _SNMP_RESULT_CACHE_TTL:
        return entry[1]
    return None


def _set_result_cache(key: str, value):
    _snmp_result_cache[key] = (_time.monotonic(), value)
    # Prune stale entries when cache grows large
    if len(_snmp_result_cache) > 500:
        cutoff = _time.monotonic() - _SNMP_RESULT_CACHE_TTL
        stale = [k for k, v in _snmp_result_cache.items() if v[0] < cutoff]
        for k in stale:
            del _snmp_result_cache[k]


# ═══════════════════════════════════════════════════════════════
# Standard interface, system, and topology OIDs
# ═══════════════════════════════════════════════════════════════

# Standard IF-MIB OIDs (all vendors)
IF_DESCR       = '1.3.6.1.2.1.2.2.1.2'
IF_ADMIN_STATUS = '1.3.6.1.2.1.2.2.1.7'
IF_OPER_STATUS = '1.3.6.1.2.1.2.2.1.8'
IF_SPEED       = '1.3.6.1.2.1.2.2.1.5'
IF_IN_OCTETS   = '1.3.6.1.2.1.2.2.1.10'
IF_OUT_OCTETS  = '1.3.6.1.2.1.2.2.1.16'
IF_HC_IN       = '1.3.6.1.2.1.31.1.1.1.6'
IF_HC_OUT      = '1.3.6.1.2.1.31.1.1.1.10'
IF_ALIAS       = '1.3.6.1.2.1.31.1.1.1.18'
IF_NAME        = '1.3.6.1.2.1.31.1.1.1.1'

# IF-MIB high-speed (for >=10G interfaces)
IF_HIGH_SPEED     = '1.3.6.1.2.1.31.1.1.1.15'   # ifHighSpeed (Mbps)

# ifLastChange: sysUpTime when oper status last changed (hundredths of sec)
IF_LAST_CHANGE    = '1.3.6.1.2.1.2.2.1.9'        # ifLastChange (TimeTicks)

# Interface error/discard/packet counters (RFC 1213)
IF_IN_ERRORS    = '1.3.6.1.2.1.2.2.1.14'
IF_OUT_ERRORS   = '1.3.6.1.2.1.2.2.1.20'
IF_IN_DISCARDS  = '1.3.6.1.2.1.2.2.1.13'
IF_OUT_DISCARDS = '1.3.6.1.2.1.2.2.1.19'
IF_IN_UCAST     = '1.3.6.1.2.1.2.2.1.11'
IF_OUT_UCAST    = '1.3.6.1.2.1.2.2.1.17'

# IF-MIB high-capacity packet counters.  These are Counter64 and are the
# correct denominator for error-rate calculations on high-speed H3C ports.
IF_HC_IN_UCAST       = '1.3.6.1.2.1.31.1.1.1.7'
IF_HC_IN_MULTICAST    = '1.3.6.1.2.1.31.1.1.1.8'
IF_HC_IN_BROADCAST    = '1.3.6.1.2.1.31.1.1.1.9'
IF_HC_OUT_UCAST      = '1.3.6.1.2.1.31.1.1.1.11'
IF_HC_OUT_MULTICAST  = '1.3.6.1.2.1.31.1.1.1.12'
IF_HC_OUT_BROADCAST  = '1.3.6.1.2.1.31.1.1.1.13'

# EtherLike-MIB error details.  FCS is the CRC-equivalent receive counter;
# the other counters explain the remaining hardware receive-error classes.
DOT3_HC_FCS_ERRORS          = '1.3.6.1.2.1.10.7.11.1.2'
DOT3_HC_FRAME_TOO_LONG      = '1.3.6.1.2.1.10.7.11.1.4'
DOT3_HC_INTERNAL_MAC_RX     = '1.3.6.1.2.1.10.7.11.1.5'
DOT3_HC_SYMBOL_ERRORS       = '1.3.6.1.2.1.10.7.11.1.6'
DOT3_FCS_ERRORS_32          = '1.3.6.1.2.1.10.7.2.1.3'

# The interface template deliberately mirrors the complete IF-MIB contract
# used by the collector.  Keeping the defaults in one place lets a model
# profile replace only the OIDs that differ on a vendor while preserving the
# standard fallback behaviour for every other field.
DEFAULT_INTERFACE_CONFIG = {
    'enabled': True,
    'if_name_oid': IF_NAME,
    'if_descr_oid': IF_DESCR,
    'if_alias_oid': IF_ALIAS,
    'if_admin_status_oid': IF_ADMIN_STATUS,
    'if_oper_status_oid': IF_OPER_STATUS,
    'if_high_speed_oid': IF_HIGH_SPEED,
    'if_speed_oid': IF_SPEED,
    'if_last_change_oid': IF_LAST_CHANGE,
    # sysUpTime is used only to interpret ifLastChange; the applied interface
    # template owns this OID just like the rest of the interface table.
    'sys_uptime_oid': '1.3.6.1.2.1.1.3.0',
    'if_in_octets_oid': IF_IN_OCTETS,
    'if_out_octets_oid': IF_OUT_OCTETS,
    'if_hc_in_octets_oid': IF_HC_IN,
    'if_hc_out_octets_oid': IF_HC_OUT,
    'if_in_errors_oid': IF_IN_ERRORS,
    'if_out_errors_oid': IF_OUT_ERRORS,
    'if_in_discards_oid': IF_IN_DISCARDS,
    'if_out_discards_oid': IF_OUT_DISCARDS,
    'if_in_ucast_oid': IF_IN_UCAST,
    'if_out_ucast_oid': IF_OUT_UCAST,
    'if_hc_in_ucast_pkts_oid': IF_HC_IN_UCAST,
    'if_hc_in_multicast_pkts_oid': IF_HC_IN_MULTICAST,
    'if_hc_in_broadcast_pkts_oid': IF_HC_IN_BROADCAST,
    'if_hc_out_ucast_pkts_oid': IF_HC_OUT_UCAST,
    'if_hc_out_multicast_pkts_oid': IF_HC_OUT_MULTICAST,
    'if_hc_out_broadcast_pkts_oid': IF_HC_OUT_BROADCAST,
    'dot3_hc_fcs_errors_oid': DOT3_HC_FCS_ERRORS,
    'dot3_hc_frame_too_long_oid': DOT3_HC_FRAME_TOO_LONG,
    'dot3_hc_internal_mac_rx_errors_oid': DOT3_HC_INTERNAL_MAC_RX,
    'dot3_hc_symbol_errors_oid': DOT3_HC_SYMBOL_ERRORS,
    'dot3_fcs_errors_oid': DOT3_FCS_ERRORS_32,
    'counter_mode': 'auto',
}

# A live template validation should fail fast for optional OIDs that are not
# exposed by the device's SNMP view.  The underlying bulk walker has its own
# retry/fallback path, so without an outer bound one missing OID can consume
# two full walk timeouts before the validation response is returned.
INTERFACE_PROBE_OID_TIMEOUT_SECONDS = 2.5

_INTERFACE_OID_FIELDS = tuple(
    key for key in DEFAULT_INTERFACE_CONFIG if key.endswith('_oid')
)
_INTERFACE_OID_ALIASES = {
    'if_name': 'if_name_oid',
    'if_descr': 'if_descr_oid',
    'if_alias': 'if_alias_oid',
    'if_admin_status': 'if_admin_status_oid',
    'admin_status_oid': 'if_admin_status_oid',
    'if_oper_status': 'if_oper_status_oid',
    'if_high_speed': 'if_high_speed_oid',
    'if_speed': 'if_speed_oid',
    'if_last_change': 'if_last_change_oid',
    'sys_uptime': 'sys_uptime_oid',
    'if_in_octets': 'if_in_octets_oid',
    'if_out_octets': 'if_out_octets_oid',
    'if_hc_in_oid': 'if_hc_in_octets_oid',
    'if_hc_out_oid': 'if_hc_out_octets_oid',
    'if_hc_in_octets': 'if_hc_in_octets_oid',
    'if_hc_out_octets': 'if_hc_out_octets_oid',
    'if_in_errors': 'if_in_errors_oid',
    'if_out_errors': 'if_out_errors_oid',
    'if_in_discards': 'if_in_discards_oid',
    'if_out_discards': 'if_out_discards_oid',
    'if_in_ucast': 'if_in_ucast_oid',
    'if_out_ucast': 'if_out_ucast_oid',
    'if_hc_in_ucast': 'if_hc_in_ucast_pkts_oid',
    'if_hc_in_ucast_pkts': 'if_hc_in_ucast_pkts_oid',
    'if_hc_in_multicast': 'if_hc_in_multicast_pkts_oid',
    'if_hc_in_multicast_pkts': 'if_hc_in_multicast_pkts_oid',
    'if_hc_in_broadcast': 'if_hc_in_broadcast_pkts_oid',
    'if_hc_in_broadcast_pkts': 'if_hc_in_broadcast_pkts_oid',
    'if_hc_out_ucast': 'if_hc_out_ucast_pkts_oid',
    'if_hc_out_ucast_pkts': 'if_hc_out_ucast_pkts_oid',
    'if_hc_out_multicast': 'if_hc_out_multicast_pkts_oid',
    'if_hc_out_multicast_pkts': 'if_hc_out_multicast_pkts_oid',
    'if_hc_out_broadcast': 'if_hc_out_broadcast_pkts_oid',
    'if_hc_out_broadcast_pkts': 'if_hc_out_broadcast_pkts_oid',
    'dot3_hc_fcs_errors': 'dot3_hc_fcs_errors_oid',
    'dot3_hc_frame_too_long': 'dot3_hc_frame_too_long_oid',
    'dot3_hc_internal_mac_rx_errors': 'dot3_hc_internal_mac_rx_errors_oid',
    'dot3_hc_symbol_errors': 'dot3_hc_symbol_errors_oid',
    'dot3_fcs_errors': 'dot3_fcs_errors_oid',
    'name_oid': 'if_name_oid',
    'descr_oid': 'if_descr_oid',
    'alias_oid': 'if_alias_oid',
    'oper_status_oid': 'if_oper_status_oid',
    'high_speed_oid': 'if_high_speed_oid',
    'speed_oid': 'if_speed_oid',
    'last_change_oid': 'if_last_change_oid',
    'in_octets_oid': 'if_in_octets_oid',
    'out_octets_oid': 'if_out_octets_oid',
    'hc_in_oid': 'if_hc_in_octets_oid',
    'hc_out_oid': 'if_hc_out_octets_oid',
}

# Standard MIB-2 system info OIDs
SYS_DESCR    = '1.3.6.1.2.1.1.1.0'
SYS_UPTIME   = '1.3.6.1.2.1.1.3.0'
SYS_CONTACT  = '1.3.6.1.2.1.1.4.0'
SYS_NAME     = '1.3.6.1.2.1.1.5.0'
SYS_LOCATION = '1.3.6.1.2.1.1.6.0'
SYS_OBJECT_ID = '1.3.6.1.2.1.1.2.0'

_METRIC_OID_PATTERN = re.compile(r'^\d+(?:\.\d+)+$')


def normalize_metric_oid(value: Any) -> str:
    """Normalize and validate one interface-profile OID.

    A leading dot is accepted because both ``.1.3...`` and ``1.3...`` are
    common representations in vendor documentation.  Interface profiles store
    the canonical dotted-decimal form without leading/trailing dots.
    """
    raw = str(value or '').strip().strip('.')
    if not raw:
        return ''
    if len(raw) > 128 or not _METRIC_OID_PATTERN.fullmatch(raw):
        raise ValueError('OID must be a dotted decimal SNMP OID, for example 1.3.6.1.2.1.1.3.0')
    return raw


def normalize_interface_config(value: Any = None) -> dict[str, Any]:
    """Normalize a model-scoped interface OID override.

    An empty value means that the built-in IF-MIB mapping should be used.  A
    non-empty mapping is expanded with the standard defaults so the collector
    never has to guess which OID a missing field represents.  ``counter_mode``
    is intentionally explicit: ``auto`` prefers a paired Counter64 result and
    falls back to a paired Counter32 result, while ``32``/``64`` force one
    width and never mix the two directions.
    """
    if isinstance(value, Mapping):
        raw = dict(value)
    elif isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        raw = dict(decoded) if isinstance(decoded, Mapping) else {}
    else:
        return {}
    if not raw:
        return {}

    normalized: dict[str, Any] = dict(DEFAULT_INTERFACE_CONFIG)
    enabled = raw.get('enabled', True)
    if isinstance(enabled, str):
        enabled = enabled.strip().casefold() not in {'', '0', 'false', 'no', 'off'}
    normalized['enabled'] = bool(enabled)
    mode = str(raw.get('counter_mode') or raw.get('counter_width') or raw.get('counter_bits') or 'auto').strip().casefold()
    if mode in {'32bit', 'counter32', 'counter_32'}:
        mode = '32'
    elif mode in {'64bit', 'counter64', 'counter_64'}:
        mode = '64'
    if mode not in {'auto', '32', '64'}:
        raise ValueError('counter_mode must be auto, 32, or 64')
    normalized['counter_mode'] = mode

    for submitted_key, canonical_key in _INTERFACE_OID_ALIASES.items():
        if canonical_key not in raw and submitted_key in raw:
            raw[canonical_key] = raw[submitted_key]
    for key in _INTERFACE_OID_FIELDS:
        submitted = raw.get(key, normalized[key])
        try:
            normalized[key] = normalize_metric_oid(submitted)
        except ValueError as exc:
            raise ValueError(f'{key} must be a dotted decimal SNMP OID') from exc

    # A table cannot be correlated without at least one identity OID.  The
    # standard collector uses ifName first and ifDescr as fallback; custom
    # profiles may replace either one, but not both with an empty value.
    if not normalized['if_name_oid'] and not normalized['if_descr_oid']:
        raise ValueError('interface profile requires if_name_oid or if_descr_oid')
    if mode == '64' and (not normalized['if_hc_in_octets_oid'] or not normalized['if_hc_out_octets_oid']):
        raise ValueError('counter_mode 64 requires both high-capacity octet OIDs')
    if mode == '32' and (not normalized['if_in_octets_oid'] or not normalized['if_out_octets_oid']):
        raise ValueError('counter_mode 32 requires both legacy octet OIDs')
    return normalized


def _parse_snmp_number(value: Any) -> float | None:
    """Extract a numeric SNMP value from puresnmp's string representation."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or 'nosuchobject' in text.lower() or 'nosuchinstance' in text.lower():
        return None
    match = re.search(r'(?<![A-Za-z])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?![A-Za-z])', text)
    if not match:
        return None
    try:
        number = float(match.group(0))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


@dataclass(frozen=True)
class SnmpTypedValue:
    """A numeric SNMP value with the ASN.1 semantics preserved."""

    number: float | None
    snmp_type: str
    counter_bits: int | None = None


def _typed_value_from_raw(raw: Any) -> SnmpTypedValue:
    """Convert a puresnmp raw value without throwing away its type.

    ``PyWrapper`` intentionally pythonizes values and therefore loses the
    distinction between Counter32, Counter64, Gauge32 and Integer32.  Metric
    profiles use the raw Client path so width validation is based on the
    received ASN.1 type rather than on the magnitude of the number.
    """
    type_name = type(raw).__name__.casefold()
    if "counter64" in type_name:
        snmp_type, counter_bits = "counter", 64
    elif "counter" in type_name:
        snmp_type, counter_bits = "counter", 32
    elif "gauge64" in type_name:
        snmp_type, counter_bits = "gauge", 64
    elif "gauge" in type_name:
        snmp_type, counter_bits = "gauge", 32
    elif "timetick" in type_name:
        snmp_type, counter_bits = "timeticks", 32
    elif any(token in type_name for token in ("integer", "unsigned")):
        snmp_type, counter_bits = "integer", 32
    elif isinstance(raw, (int, float)):
        # This branch is only a defensive fallback for test doubles or an
        # alternate SNMP library.  It is intentionally not accepted as a
        # counter unless the template separately declares the counter width.
        snmp_type, counter_bits = "python_number", None
    else:
        snmp_type, counter_bits = "other", None

    raw_number = getattr(raw, "value", raw)
    if isinstance(raw_number, bool):
        number = None
    else:
        try:
            number = float(raw_number)
        except (TypeError, ValueError):
            number = _parse_snmp_number(raw_number)
        if number is not None and not math.isfinite(number):
            number = None
    return SnmpTypedValue(number=number, snmp_type=snmp_type, counter_bits=counter_bits)


# ═══════════════════════════════════════════════════════════════
# puresnmp async helpers (replaces pysnmp — Python 3.13 compatible)
# ═══════════════════════════════════════════════════════════════

def _val_to_str(val) -> str:
    """Convert puresnmp value to a clean string."""
    if isinstance(val, bytes):
        return val.decode('utf-8', errors='replace').strip('\r\n \x00')
    return str(val).strip()


_SNMP_TRANSPORT_TIMEOUT_SECONDS = 1
_SNMP_TRANSPORT_RETRIES = 2


class _SafeSNMPClientProtocol(asyncio.DatagramProtocol):
    """Cancellation-safe UDP protocol for puresnmp requests.

    puresnmp 2.0.1 unconditionally calls ``Future.set_result`` when a
    datagram arrives.  A response can arrive after an outer timeout has
    cancelled that Future, especially on Windows' Proactor event loop.  The
    guards below make late packets and transport callbacks harmless while
    preserving the original cancellation/timeout semantics.
    """

    def __init__(self, packet: bytes) -> None:
        self.packet = packet
        self.transport = None
        self.future = asyncio.get_running_loop().create_future()

    def connection_made(self, transport) -> None:
        self.transport = transport
        transport.sendto(self.packet)

    def _close_transport(self) -> None:
        if self.transport is not None:
            self.transport.close()

    def connection_lost(self, exc) -> None:
        if exc is not None and not self.future.done():
            self.future.set_exception(exc)

    def datagram_received(self, data, addr) -> None:
        if self.future.done():
            self._close_transport()
            return
        self.future.set_result(data)
        self._close_transport()

    def error_received(self, exc) -> None:
        if not self.future.done():
            self.future.set_exception(exc)

    async def get_data(self, timeout):
        from puresnmp.exc import Timeout

        try:
            return await asyncio.wait_for(self.future, timeout)
        except (asyncio.TimeoutError, socket.timeout) as exc:
            if self.transport is not None:
                self.transport.abort()
            raise Timeout(
                f'{timeout} second timeout exceeded on UDP transport.'
            ) from exc
        except asyncio.CancelledError:
            if self.transport is not None:
                self.transport.abort()
            raise


def _build_snmp_client(ip: str, auth, port: int):
    """Build a client whose internal deadline fits the collector deadline."""
    from puresnmp import Client

    client = Client(ip, auth, port=port, sender=_safe_send_udp)
    # puresnmp defaults to 6 seconds and 10 retries.  The collectors wrap
    # requests in 3-5 second application deadlines, so those defaults cause
    # outer cancellation before the library cleans up its UDP Future.
    client.configure(
        timeout=_SNMP_TRANSPORT_TIMEOUT_SECONDS,
        retries=_SNMP_TRANSPORT_RETRIES,
    )
    return client


async def _safe_send_udp(
    endpoint,
    packet: bytes,
    timeout: int = _SNMP_TRANSPORT_TIMEOUT_SECONDS,
    loop=None,
    retries: int = _SNMP_TRANSPORT_RETRIES,
) -> bytes:
    """Send one SNMP datagram and always close its asyncio UDP transport.

    puresnmp's default sender leaves the transport open when the protocol
    reports an OS-level socket error. Automatic telemetry calls this sender
    frequently, so make cleanup unconditional for success, timeout, error,
    and task cancellation paths.
    """
    from puresnmp.exc import Timeout

    if loop is None:
        loop = asyncio.get_event_loop()
    remaining = max(1, int(retries))

    while remaining > 0:
        protocol = None
        datagram_transport = None
        try:
            datagram_transport, protocol = await loop.create_datagram_endpoint(
                lambda: _SafeSNMPClientProtocol(packet),
                remote_addr=(str(endpoint.ip), endpoint.port),
            )
            return await protocol.get_data(timeout)
        except Timeout:
            remaining -= 1
            if remaining <= 0:
                raise
        finally:
            active_transport = getattr(protocol, 'transport', None) or datagram_transport
            if active_transport is not None:
                try:
                    active_transport.close()
                except Exception:
                    logger.debug('Failed to close SNMP UDP transport', exc_info=True)

    raise Timeout(f'{timeout} second timeout exceeded on UDP transport.')


async def _snmp_get(
    ip: str,
    community: str,
    oid: str,
    port: int = 161,
    timeout: float = 3,
    version: str = '2c',
) -> Optional[str]:
    """GET a single OID value via puresnmp (SNMPv1/v2c)."""
    async with get_network_access_limiter().async_snmp():
      try:
        from puresnmp import V1, V2C, PyWrapper
        version_key = str(version or '2c').strip().lower()
        auth = V1(community) if version_key in {'v1', '1'} else V2C(community)
        client = PyWrapper(_build_snmp_client(ip, auth, port))
        result = await asyncio.wait_for(client.get(oid), timeout=timeout)
        if result is None:
            return None
        v = _val_to_str(result)
        if v and 'noSuchObject' not in v and 'noSuchInstance' not in v:
            return v
      except Exception as e:
        logger.debug(f"SNMP GET {ip} {oid} failed: {e}")
      return None


class SnmpWalkResult(list[tuple[str, str]]):
    """List-compatible SNMP walk result with an explicit row-limit marker."""

    def __init__(
        self,
        values: Optional[list[tuple[str, str]]] = None,
        *,
        truncated: bool = False,
        octet_values: Optional[Mapping[str, bytes]] = None,
    ) -> None:
        super().__init__(values or [])
        self.truncated = bool(truncated)
        self.octet_values: dict[str, bytes] = {
            str(suffix): bytes(value)
            for suffix, value in (octet_values or {}).items()
            if isinstance(value, (bytes, bytearray))
        }


class SnmpWalkTimeoutError(Exception):
    """A diagnostic SNMP walk timed out, optionally after collecting some values."""

    def __init__(self, partial_results: list[tuple[str, str]]):
        super().__init__('SNMP WALK timed out')
        self.partial_results = partial_results


async def _snmp_walk(
    ip: str,
    community: str,
    oid: str,
    port: int = 161,
    timeout: float = 5,
    max_rows: int = 200,
    version: str = '2c',
    raise_on_error: bool = False,
    preserve_octets: bool = False,
) -> SnmpWalkResult:
    """Walk an OID subtree via puresnmp, return list of (oid_suffix, value).

    The collector remains v2c by default.  The optional v1 path is used by
    the read-only template tester and keeps the same transport/error handling;
    existing collection callers do not need to change their arguments.
    ``raise_on_error`` is reserved for interactive diagnostics and
    completeness-sensitive collectors that must tell a timeout from a
    completed walk with no matching OID instances.  The returned list remains
    backward compatible while exposing ``truncated`` when the row budget was
    reached before the subtree walk completed.  ``preserve_octets`` keeps raw
    OCTET STRING bytes in ``octet_values`` for callers that need lossless
    binary handling without changing the normal string result.
    """
    results = SnmpWalkResult()
    base_oid = oid.rstrip('.')
    version_key = str(version or '2c').strip().lower()
    if version_key in {'v1', '1'}:
        version_key = '1'
    elif version_key in {'v2c', '2c', '2'}:
        version_key = '2c'
    else:
        raise ValueError('Unsupported SNMP version; use 1 or 2c')

    async def _collect():
        from puresnmp import PyWrapper, V1, V2C
        auth = V1(community) if version_key == '1' else V2C(community)
        client = PyWrapper(_build_snmp_client(ip, auth, port))
        async for varbind in client.walk(base_oid):
            oid_str = str(varbind.oid)
            suffix = oid_str[len(base_oid) + 1:] if oid_str.startswith(base_oid + '.') else oid_str
            v = _val_to_str(varbind.value)
            if 'endOfMibView' in v:
                return
            results.append((suffix, v))
            if preserve_octets and isinstance(varbind.value, (bytes, bytearray)):
                results.octet_values[suffix] = bytes(varbind.value)
            if len(results) >= max_rows:
                results.truncated = True
                return

    async with get_network_access_limiter().async_snmp():
      try:
        await asyncio.wait_for(_collect(), timeout=timeout)
      except asyncio.TimeoutError as exc:
        logger.debug(f"SNMP WALK {ip} {oid} timeout after {timeout}s ({len(results)} rows collected)")
        if raise_on_error:
            raise SnmpWalkTimeoutError(results) from exc
      except Exception as exc:
        logger.debug(f"SNMP WALK {ip} {oid} failed: {exc}")
        if raise_on_error:
            is_timeout = (
                isinstance(exc, (TimeoutError, socket.timeout, asyncio.TimeoutError))
                or type(exc).__name__.strip().lower() in {'timeout', 'requesttimeout'}
            )
            if is_timeout:
                raise SnmpWalkTimeoutError(results) from exc
            raise
    return results


async def _snmp_get_versioned(
    ip: str,
    community: str,
    oid: str,
    port: int,
    version: str,
) -> Optional[str]:
    """Call the scalar helper without changing the v2c monkeypatch contract."""
    if str(version or '2c').strip().lower() in {'v2c', '2c', '2', ''}:
        return await _snmp_get(ip, community, oid, port)
    return await _snmp_get(ip, community, oid, port, version=version)


async def _snmp_walk_versioned(
    ip: str,
    community: str,
    oid: str,
    port: int,
    version: str,
) -> list[tuple[str, str]]:
    """Call the walk helper while preserving legacy v2c test doubles."""
    if str(version or '2c').strip().lower() in {'v2c', '2c', '2', ''}:
        return await _snmp_walk(ip, community, oid, port)
    return await _snmp_walk(ip, community, oid, port, version=version)


async def _snmp_get_typed(
    ip: str,
    community: str,
    oid: str,
    port: int = 161,
    timeout: float = 3,
    version: str = '2c',
) -> Optional[SnmpTypedValue]:
    """GET one OID while preserving its puresnmp ASN.1 type."""
    async with get_network_access_limiter().async_snmp():
        try:
            from puresnmp import ObjectIdentifier, V1, V2C

            version_key = str(version or '2c').strip().lower()
            auth = V1(community) if version_key in {'v1', '1'} else V2C(community)
            client = _build_snmp_client(ip, auth, port)
            result = await asyncio.wait_for(
                client.get(ObjectIdentifier(oid)),
                timeout=timeout,
            )
            typed = _typed_value_from_raw(result)
            if typed.number is not None:
                return typed
        except Exception as exc:
            logger.debug("Typed SNMP GET %s %s failed: %s", ip, oid, exc)
        return None


async def _snmp_walk_typed(
    ip: str,
    community: str,
    oid: str,
    port: int = 161,
    timeout: float = 5,
    max_rows: int = 200,
    version: str = '2c',
) -> list[tuple[str, SnmpTypedValue]]:
    """WALK one OID subtree and preserve each row's ASN.1 type."""
    results: list[tuple[str, SnmpTypedValue]] = []
    base_oid = oid.rstrip(".")

    async def _collect():
        from puresnmp import ObjectIdentifier, V1, V2C

        version_key = str(version or '2c').strip().lower()
        auth = V1(community) if version_key in {'v1', '1'} else V2C(community)
        client = _build_snmp_client(ip, auth, port)
        async for varbind in client.walk(ObjectIdentifier(base_oid)):
            oid_str = str(varbind.oid)
            suffix = oid_str[len(base_oid) + 1:] if oid_str.startswith(base_oid + ".") else oid_str
            typed = _typed_value_from_raw(varbind.value)
            if typed.number is not None:
                results.append((suffix, typed))
            if len(results) >= max_rows:
                return

    async with get_network_access_limiter().async_snmp():
        try:
            await asyncio.wait_for(_collect(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.debug("Typed SNMP WALK %s %s timeout after %ss (%s rows)", ip, oid, timeout, len(results))
        except Exception as exc:
            logger.debug("Typed SNMP WALK %s %s failed: %s", ip, oid, exc)
    return results


async def _snmp_bulk_walk_typed(
    ip: str,
    community: str,
    oid: str,
    port: int = 161,
    timeout: float = 5,
    max_repetitions: int = 20,
    max_rows: int = 2000,
    version: str = '2c',
) -> list[tuple[str, SnmpTypedValue]]:
    """Typed GETBULK walk used for interface counters."""
    results: list[tuple[str, SnmpTypedValue]] = []
    base_oid = oid.rstrip(".")

    async def _collect():
        from puresnmp import ObjectIdentifier, V1, V2C

        version_key = str(version or '2c').strip().lower()
        auth = V1(community) if version_key in {'v1', '1'} else V2C(community)
        client = _build_snmp_client(ip, auth, port)
        async for varbind in client.bulkwalk([ObjectIdentifier(base_oid)], bulk_size=max_repetitions):
            oid_str = str(varbind.oid)
            suffix = oid_str[len(base_oid) + 1:] if oid_str.startswith(base_oid + ".") else oid_str
            typed = _typed_value_from_raw(varbind.value)
            if typed.number is not None:
                results.append((suffix, typed))
            if len(results) >= max_rows:
                return

    async with get_network_access_limiter().async_snmp():
        try:
            await asyncio.wait_for(_collect(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.debug("Typed SNMP BULK_WALK %s %s timeout after %ss (%s rows)", ip, oid, timeout, len(results))
        except Exception as exc:
            logger.debug("Typed SNMP BULK_WALK %s %s failed: %s", ip, oid, exc)
    if not results:
        return await _snmp_walk_typed(
            ip,
            community,
            oid,
            port,
            timeout=timeout,
            max_rows=max_rows,
            version=version,
        )
    return results


async def _snmp_bulk_walk(
    ip: str,
    community: str,
    oid: str,
    port: int = 161,
    timeout: float = 5,
    max_repetitions: int = 20,
    version: str = '2c',
) -> list[tuple[str, str]]:
    """Bulk Walk an OID subtree via puresnmp, using GETBULK for high performance."""
    results: list[tuple[str, str]] = []
    base_oid = oid.rstrip('.')

    async def _collect():
        from puresnmp import V1, V2C, PyWrapper
        version_key = str(version or '2c').strip().lower()
        auth = V1(community) if version_key in {'v1', '1'} else V2C(community)
        client = PyWrapper(_build_snmp_client(ip, auth, port))
        # bulkwalk significantly reduces UDP round-trips
        async for varbind in client.bulkwalk([base_oid], bulk_size=max_repetitions):
            oid_str = str(varbind.oid)
            suffix = oid_str[len(base_oid) + 1:] if oid_str.startswith(base_oid + '.') else oid_str
            v = _val_to_str(varbind.value)
            if 'endOfMibView' in v:
                return
            results.append((suffix, v))

    async with get_network_access_limiter().async_snmp():
      try:
        await asyncio.wait_for(_collect(), timeout=timeout)
      except asyncio.TimeoutError:
        logger.debug(f"SNMP BULK_WALK {ip} {oid} timeout after {timeout}s ({len(results)} rows collected)")
      except Exception as e:
        logger.debug(f"SNMP BULK_WALK {ip} {oid} failed: {e}")
    if not results:
        logger.debug(f"SNMP BULK_WALK returned no results for {ip} {oid}. Falling back to standard WALK.")
        results = await _snmp_walk(ip, community, oid, port, timeout=timeout, version=version)
    return results


async def collect_device_info(ip: str, community: str = 'public', port: int = 161) -> dict:
    """
    Collect standard MIB-2 system information.
    Returns: { sys_name, sys_descr, sys_object_id, uptime, sys_location, sys_contact }
    """
    import asyncio as _aio
    result = {'sys_name': None, 'sys_descr': None, 'sys_object_id': None, 'uptime': None,
              'sys_location': None, 'sys_contact': None}
    try:
        vals = await _aio.gather(
            _snmp_get(ip, community, SYS_NAME, port),
            _snmp_get(ip, community, SYS_DESCR, port),
            _snmp_get(ip, community, SYS_OBJECT_ID, port),
            _snmp_get(ip, community, SYS_UPTIME, port),
            _snmp_get(ip, community, SYS_LOCATION, port),
            _snmp_get(ip, community, SYS_CONTACT, port),
        )
        result['sys_name'] = vals[0]
        result['sys_descr'] = vals[1]
        result['sys_object_id'] = vals[2]
        # sysUpTime is in hundredths of a second → human readable
        if vals[3]:
            try:
                ticks = int(vals[3])
                secs = ticks // 100
                days, rem = divmod(secs, 86400)
                hours, rem = divmod(rem, 3600)
                mins, _ = divmod(rem, 60)
                result['uptime'] = f"{days}d {hours}h {mins}m"
            except (ValueError, TypeError):
                result['uptime'] = vals[3]
        result['sys_location'] = vals[4]
        result['sys_contact'] = vals[5]
    except Exception as e:
        logger.warning(f"SNMP device info collection failed for {ip}: {e}")
    return result


async def collect_snmp_lldp_neighbors(
    ip: str,
    community: str,
    port: int = 161,
    version: str = '2c',
    timeout: float = 30.0,
    max_rows: int = 10000,
) -> list[dict[str, Any]]:
    """Collect LLDP neighbor relationships via the standard IEEE 802.1AB LLDP-MIB.

    Uses lightweight, zero-SSH SNMP walks. A usable neighbor table survives
    failures in optional LLDP columns; the caller records it as partial and
    merges the evidence without expiring unseen links. If no usable neighbor
    can be formed, a failed walk remains an error so it cannot be mistaken for
    a complete empty topology snapshot.
    Returns a list of neighbor dicts with:
        local_interface, neighbor_name, neighbor_interface, mgmt_address,
        chassis_id, neighbor_platform, protocol ('lldp')
    """
    # LLDP discovery must use the credential resolved for the target asset.
    # Never silently probe with the well-known ``public`` community: callers
    # that do not have an SNMP secret should skip this path and use their
    # configured fallback (for example, SSH) instead.
    if not str(community or '').strip():
        raise ValueError('SNMP community is required for LLDP discovery')

    class _SnmpLLDPBatch(list[dict[str, Any]]):
        def __init__(
            self,
            records: list[dict[str, Any]],
            collection_status: str,
            *,
            truncated_oids: Optional[list[str]] = None,
            max_rows: int = 10000,
        ) -> None:
            super().__init__(records)
            self.collection_status = collection_status
            self.truncated_oids = list(truncated_oids or [])
            self.max_rows = max_rows

    neighbors: list[dict[str, Any]] = []

    def _clean_host(raw_name: str) -> str:
        if not raw_name:
            return ''
        s = str(raw_name).strip().split('\r')[0].split('\n')[0].strip()
        if '.' in s:
            candidate = s.split('.')[0].strip()
            if len(candidate) >= 2 and re.match(r'^[A-Za-z0-9_-]+$', candidate):
                return candidate
        return s

    def _parse_lldp_suffix(suffix: str) -> tuple[str, str]:
        # Suffix is timeMark.localPortNum.remIndex
        parts = suffix.strip('.').split('.')
        if len(parts) >= 3:
            return parts[1], parts[2]
        if len(parts) == 2:
            return parts[0], parts[1]
        return parts[0] if parts else '1', '1'

    # Read the related IEEE 802.1AB LLDP-MIB columns in parallel.
    lldp_chassis_id_oid = '1.0.8802.1.1.2.1.4.1.1.5'
    walk_errors: list[BaseException] = []
    truncated_oids: list[str] = []
    truncated_rows: dict[str, int] = {}
    walk_signature_target = getattr(_snmp_walk, 'side_effect', None)
    if not callable(walk_signature_target):
        walk_signature_target = _snmp_walk
    try:
        walk_parameters = tuple(inspect.signature(walk_signature_target).parameters.values())
        supports_error_flag = any(
            item.name == 'raise_on_error' or item.kind == inspect.Parameter.VAR_KEYWORD
            for item in walk_parameters
        )
        supports_max_rows = any(
            item.name == 'max_rows' or item.kind == inspect.Parameter.VAR_KEYWORD
            for item in walk_parameters
        )
        supports_octet_preservation = any(
            item.name == 'preserve_octets' or item.kind == inspect.Parameter.VAR_KEYWORD
            for item in walk_parameters
        )
    except (TypeError, ValueError):
        supports_error_flag = False
        supports_max_rows = False
        supports_octet_preservation = False

    async def _walk_lldp_column(oid: str) -> list[tuple[str, str]]:
        # The LLDP collector needs to distinguish an empty table from a failed
        # walk. Keep compatibility with older test doubles and plugins that
        # expose the historical _snmp_walk signature without the newer
        # raise_on_error/max_rows keyword arguments.
        kwargs: dict[str, Any] = {'timeout': timeout, 'version': version}
        if supports_error_flag:
            kwargs['raise_on_error'] = True
        if supports_max_rows:
            kwargs['max_rows'] = max_rows
        if supports_octet_preservation and oid == lldp_chassis_id_oid:
            kwargs['preserve_octets'] = True
        return await _snmp_walk(ip, community, oid, port, **kwargs)

    try:
        walk_specs = [
            ('1.0.8802.1.1.2.1.4.1.1.9', 'lldpRemSysName'),
            ('1.0.8802.1.1.2.1.4.1.1.7', 'lldpRemPortId'),
            ('1.0.8802.1.1.2.1.4.1.1.8', 'lldpRemPortDesc'),
            (lldp_chassis_id_oid, 'lldpRemChassisId'),
            ('1.0.8802.1.1.2.1.4.1.1.4', 'lldpRemChassisIdSubtype'),
            ('1.0.8802.1.1.2.1.4.1.1.10', 'lldpRemSysDesc'),
            ('1.0.8802.1.1.2.1.4.2.1', 'lldpRemManAddrTable'),
            ('1.0.8802.1.1.2.1.3.7.1.3', 'lldpLocPortId'),
            ('1.3.6.1.2.1.31.1.1.1.1', 'ifName'),
        ]
        lldp_tasks = [_walk_lldp_column(oid) for oid, _label in walk_specs]
        results = await asyncio.gather(*lldp_tasks, return_exceptions=True)
        if any(isinstance(result, asyncio.CancelledError) for result in results):
            raise asyncio.CancelledError
        walk_errors = [result for result in results if isinstance(result, Exception)]

        def _row_count(value: Any) -> int:
            if isinstance(value, (list, tuple)):
                return len(value)
            return 0

        for (oid, _label), result in zip(walk_specs, results):
            partial_rows = getattr(result, 'partial_results', None)
            result_truncated = bool(getattr(result, 'truncated', False))
            partial_truncated = bool(getattr(partial_rows, 'truncated', False))
            if result_truncated or partial_truncated:
                truncated_oids.append(oid)
                truncated_rows[oid] = _row_count(partial_rows if partial_rows is not None else result)

        if walk_errors:
            error_types = ','.join(sorted({type(error).__name__ for error in walk_errors}))
            failure_oids = [
                oid for (oid, _label), result in zip(walk_specs, results)
                if isinstance(result, Exception)
            ]
            logger.warning(
                'SNMP LLDP MIB walks had failures on %s (oids=%s, %s/%s, error_types=%s)',
                ip,
                ','.join(failure_oids),
                len(walk_errors),
                len(results),
                error_types,
            )
        if truncated_oids:
            logger.warning(
                'SNMP LLDP MIB walks reached row budget on %s (oids=%s, rows=%s, max_rows=%s)',
                ip,
                ','.join(truncated_oids),
                ','.join(f'{oid}={truncated_rows.get(oid, 0)}' for oid in truncated_oids),
                max_rows,
            )

        def _rows_at(index: int) -> list[tuple[str, str]]:
            result = results[index]
            if isinstance(result, list):
                return result
            partial_rows = getattr(result, 'partial_results', None)
            return partial_rows if isinstance(partial_rows, list) else []

        rem_sys_names = _rows_at(0)
        rem_port_ids = _rows_at(1)
        rem_port_descs = _rows_at(2)
        rem_chassis_ids = _rows_at(3)
        rem_chassis_subtypes = _rows_at(4)
        rem_sys_descs = _rows_at(5)
        rem_man_addrs = _rows_at(6)
        loc_port_ids = dict(_rows_at(7))
        if_names = dict(_rows_at(8))

        sys_name_map = { _parse_lldp_suffix(s): v for s, v in rem_sys_names }
        port_id_map = { _parse_lldp_suffix(s): v for s, v in rem_port_ids }
        port_desc_map = { _parse_lldp_suffix(s): v for s, v in rem_port_descs }
        chassis_id_map = { _parse_lldp_suffix(s): v for s, v in rem_chassis_ids }
        chassis_subtype_map = { _parse_lldp_suffix(s): v for s, v in rem_chassis_subtypes }
        sys_desc_map = { _parse_lldp_suffix(s): v for s, v in rem_sys_descs }

        def _octets_at(index: int) -> dict[str, bytes]:
            result = results[index]
            if not isinstance(result, list):
                result = getattr(result, 'partial_results', None)
            octets = getattr(result, 'octet_values', None)
            if not isinstance(octets, Mapping):
                return {}
            return {
                str(suffix): bytes(value)
                for suffix, value in octets.items()
                if isinstance(value, (bytes, bytearray))
            }

        chassis_octet_values = {
            _parse_lldp_suffix(suffix): value
            for suffix, value in _octets_at(3).items()
        }

        def _parse_chassis_subtype(value: Any) -> Optional[int]:
            try:
                return int(str(value).strip())
            except (TypeError, ValueError):
                return None

        def _format_chassis_id(key: tuple[str, str]) -> str:
            raw_value = chassis_octet_values.get(key)
            fallback = chassis_id_map.get(key) or ''
            if raw_value is None:
                return str(fallback).strip()
            if not raw_value:
                return ''
            subtype = _parse_chassis_subtype(chassis_subtype_map.get(key))
            if subtype == 4:
                return raw_value.hex(':')
            try:
                text_value = raw_value.decode('utf-8', errors='strict').strip('\r\n \x00')
            except UnicodeDecodeError:
                return raw_value.hex(':')
            return text_value if text_value and text_value.isprintable() else raw_value.hex(':')

        # Extract management IP addresses from lldpRemManAddrTable
        # IEEE 802.1AB Index: timeMark.localPortNum.remIndex.manAddrSubtype(1).manAddrLen(4).a.b.c.d
        man_addr_map: dict[Any, str] = {}
        for s, _ in rem_man_addrs:
            parts = s.strip('.').split('.')
            found = False
            for k in range(len(parts) - 5):
                if parts[k] == '1' and parts[k+1] == '4' and len(parts) - (k + 2) == 4:
                    ip_cand = '.'.join(parts[k+2:])
                    if k >= 2:
                        man_addr_map[(parts[k-2], parts[k-1])] = ip_cand
                        man_addr_map[parts[k-2]] = ip_cand
                    found = True
                    break
            if not found and len(parts) >= 4:
                last4 = parts[-4:]
                if all(x.isdigit() and 0 <= int(x) <= 255 for x in last4):
                    ip_cand = '.'.join(last4)
                    if len(parts) >= 6:
                        man_addr_map[(parts[-6], parts[-5])] = ip_cand
                        man_addr_map[parts[-6]] = ip_cand

        all_keys = set(sys_name_map.keys()) | set(port_id_map.keys()) | set(chassis_id_map.keys())
        chassis_value_map = {key: _format_chassis_id(key) for key in all_keys}
        for key in all_keys:
            loc_port_num, rem_idx = key
            loc_port = loc_port_ids.get(loc_port_num) or if_names.get(loc_port_num) or f"Port-{loc_port_num}"
            raw_peer_name = sys_name_map.get(key) or chassis_value_map.get(key) or ''
            peer_name = _clean_host(raw_peer_name)
            if not peer_name:
                continue

            r_desc = (port_desc_map.get(key) or '').strip()
            r_id = (port_id_map.get(key) or '').strip()

            def _is_mac_or_pure_number(val: str) -> bool:
                if not val:
                    return True
                cleaned = val.replace(':', '').replace('-', '').replace('.', '')
                if cleaned.isdigit():
                    return True
                if len(cleaned) == 12 and all(c in '0123456789abcdefABCDEF' for c in cleaned):
                    return True
                return False

            # Prefer the standard IEEE 802.1AB lldpRemPortId (r_id) whenever it is a valid port identifier.
            # Only fall back to lldpRemPortDesc (r_desc) if r_id is empty, pure numeric index, or MAC address,
            # and r_desc is not a user description prefix (e.g. "TO-", "uplink", etc.).
            if r_id and not _is_mac_or_pure_number(r_id):
                remote_port = r_id
            elif r_desc and not _is_mac_or_pure_number(r_desc) and not re.match(r'^(?:to[-_ ]|uplink|downlink|peer)', r_desc, re.I):
                remote_port = r_desc
            elif r_id:
                remote_port = r_id
            else:
                remote_port = r_desc or 'Unknown'

            sys_desc = sys_desc_map.get(key) or ''
            chassis_val = chassis_value_map.get(key) or ''
            mgmt_ip = man_addr_map.get(key) or man_addr_map.get(loc_port_num) or ''

            neighbors.append({
                'protocol': 'lldp',
                'local_interface': loc_port,
                'neighbor_name': peer_name,
                'neighbor_interface': remote_port,
                'mgmt_address': mgmt_ip,
                'chassis_id': chassis_val,
                'neighbor_platform': sys_desc,
                'system_description': sys_desc,
            })
    except Exception as exc:
        logger.debug("SNMP LLDP walk encounter error on %s: %s", ip, exc)

    if walk_errors or truncated_oids:
        error_types = ','.join(sorted({type(error).__name__ for error in walk_errors}))
        if not truncated_oids:
            # Keep the established machine-readable error suffix unchanged for
            # ordinary walk failures; row-limit details are additive only for
            # the new truncation condition.
            anomaly_detail = error_types or 'unknown'
        else:
            anomaly_parts: list[str] = []
            if error_types:
                anomaly_parts.append(f'error_types={error_types}')
            anomaly_parts.append('row_limit_exceeded:' + ','.join(truncated_oids))
            anomaly_detail = ':'.join(anomaly_parts)
        if neighbors:
            logger.warning(
                'Using %d SNMP LLDP neighbor(s) from partial MIB data on %s; '
                'the topology snapshot will be merged without aging old links (%s)',
                len(neighbors), ip, anomaly_detail,
            )
            return _SnmpLLDPBatch(
                neighbors,
                'partial',
                truncated_oids=truncated_oids,
                max_rows=max_rows,
            )
        failure_scope = (
            'all_mib_walks_failed'
            if walk_errors and len(walk_errors) == len(results)
            else 'partial_mib_walks_failed'
            if walk_errors
            else 'row_limit_exceeded'
        )
        raise RuntimeError(f'snmp_lldp_walk_failed:{failure_scope}:{anomaly_detail}')

    return _SnmpLLDPBatch(neighbors, 'success', max_rows=max_rows)


async def collect_interface_inventory(
    ip: str,
    community: str = 'public',
    port: int = 161,
    interface_config: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Read only interface names and IF-MIB indexes for a device inventory refresh."""
    config = normalize_interface_config(interface_config) if interface_config else dict(DEFAULT_INTERFACE_CONFIG)
    if not config.get('enabled', True):
        config = dict(DEFAULT_INTERFACE_CONFIG)

    name_rows = await _snmp_bulk_walk(ip, community, config.get('if_name_oid') or '', port) if config.get('if_name_oid') else []
    if not name_rows and config.get('if_descr_oid'):
        name_rows = await _snmp_bulk_walk(ip, community, config['if_descr_oid'], port)

    interfaces: list[dict[str, Any]] = []
    for raw_index, raw_name in name_rows:
        name = str(raw_name or '').strip()
        try:
            if_index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if name and if_index > 0:
            interfaces.append({
                'name': name,
                'if_index': if_index,
                'status': 'unknown',
                'admin_status': 'unknown',
                'description': '',
            })
    return interfaces


async def collect_interface_data(
    ip: str,
    community: str = 'public',
    port: int = 161,
    interface_config: Mapping[str, Any] | None = None,
    *,
    template_only: bool = False,
) -> list[dict]:
    """
    Collect interface table via standard IF-MIB (works for all vendors).
    Returns: [{ name, status, speed_mbps, in_octets, out_octets, description }, ...]

    Performance: after obtaining interface index (ifName), all remaining OID
    walks are issued in parallel via asyncio.gather to reduce per-device
    collection latency. Uses GetBulk to drastically reduce UDP packets.
    """
    if template_only and not interface_config:
        return []
    config = normalize_interface_config(interface_config) if interface_config else dict(DEFAULT_INTERFACE_CONFIG)
    if not config.get('enabled', True):
        if template_only:
            return []
        config = dict(DEFAULT_INTERFACE_CONFIG)
    community_token = hashlib.sha256(str(community or '').encode('utf-8')).hexdigest()[:12]
    config_token = hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    ).hexdigest()[:16]
    cache_key = f"intf:{ip}:{port}:{int(template_only)}:{community_token}:{config_token}"
    cached = _get_result_cache(cache_key)
    if cached is not None:
        return cached

    interfaces = {}
    try:
        async def _walk(oid: str):
            return await _snmp_bulk_walk(ip, community, oid, port) if oid else []

        async def _typed_walk(oid: str):
            return await _snmp_bulk_walk_typed(ip, community, oid, port) if oid else []

        # Step 1: ifName (preferred) or ifDescr — must be first to build index
        name_rows = await _walk(config['if_name_oid'])
        if not name_rows:
            name_rows = await _walk(config['if_descr_oid'])
        for idx, val in name_rows:
            interfaces[idx] = {'name': val, 'index': idx}

        # Step 2: Parallel fetch of all independent OIDs using GetBulk
        (status_rows, admin_status_rows, hspeed_rows, speed_rows,
         hc_in_rows, hc_out_rows, alias_rows,
         in_err_rows, out_err_rows, in_disc_rows, out_disc_rows,
         in_ucast_rows, out_ucast_rows,
         hc_in_ucast_rows, hc_in_multicast_rows, hc_in_broadcast_rows,
         hc_out_ucast_rows, hc_out_multicast_rows, hc_out_broadcast_rows,
         hc_fcs_rows, hc_frame_too_long_rows, hc_mac_rx_rows, hc_symbol_rows,
         fcs32_rows,
         sys_uptime_raw, lc_rows) = await asyncio.gather(
            _walk(config['if_oper_status_oid']),
            _walk(config.get('if_admin_status_oid') or IF_ADMIN_STATUS),
            _walk(config['if_high_speed_oid']),
            _walk(config['if_speed_oid']),
            _typed_walk(config['if_hc_in_octets_oid']) if config['counter_mode'] in {'auto', '64'} else asyncio.sleep(0, result=[]),
            _typed_walk(config['if_hc_out_octets_oid']) if config['counter_mode'] in {'auto', '64'} else asyncio.sleep(0, result=[]),
            _walk(config['if_alias_oid']),
            _walk(config['if_in_errors_oid']),
            _walk(config['if_out_errors_oid']),
            _walk(config['if_in_discards_oid']),
            _walk(config['if_out_discards_oid']),
            _walk(config['if_in_ucast_oid']),
            _walk(config['if_out_ucast_oid']),
            _typed_walk(config['if_hc_in_ucast_pkts_oid']),
            _typed_walk(config['if_hc_in_multicast_pkts_oid']),
            _typed_walk(config['if_hc_in_broadcast_pkts_oid']),
            _typed_walk(config['if_hc_out_ucast_pkts_oid']),
            _typed_walk(config['if_hc_out_multicast_pkts_oid']),
            _typed_walk(config['if_hc_out_broadcast_pkts_oid']),
            _walk(config['dot3_hc_fcs_errors_oid']),
            _walk(config['dot3_hc_frame_too_long_oid']),
            _walk(config['dot3_hc_internal_mac_rx_errors_oid']),
            _walk(config['dot3_hc_symbol_errors_oid']),
            _walk(config['dot3_fcs_errors_oid']),
            _snmp_get(ip, community, config.get('sys_uptime_oid', ''), port),
            _snmp_bulk_walk(ip, community, config['if_last_change_oid'], port),
        )

        # IF-HC-MIB is semantically Counter64 and IF-MIB is Counter32.  Do
        # not infer width from the magnitude of a value and do not mix one
        # direction's 64-bit counter with the other direction's 32-bit value.
        def _counter_rows(rows, expected_bits: int) -> list[tuple[str, str]]:
            return [
                (idx, str(int(value.number)))
                for idx, value in rows
                if value.snmp_type == 'counter'
                and value.counter_bits == expected_bits
                and value.number is not None
                and float(value.number).is_integer()
                and value.number >= 0
            ]

        hc_in_valid = _counter_rows(hc_in_rows, 64)
        hc_out_valid = _counter_rows(hc_out_rows, 64)
        hc_in_map = dict(hc_in_valid)
        hc_out_map = dict(hc_out_valid)
        hc_pair_indices = set(hc_in_map).intersection(hc_out_map)

        def _typed_counter_map(rows, expected_bits: int = 64) -> dict[str, int]:
            values: dict[str, int] = {}
            for idx, value in rows:
                if not isinstance(value, SnmpTypedValue):
                    continue
                if value.snmp_type != 'counter' or value.counter_bits != expected_bits or value.number is None:
                    continue
                try:
                    number = int(value.number)
                except (TypeError, ValueError, OverflowError):
                    continue
                if number >= 0:
                    values[str(idx)] = number
            return values

        def _numeric_counter_map(rows) -> dict[str, int]:
            values: dict[str, int] = {}
            for idx, raw in rows:
                number = _parse_snmp_number(raw)
                if number is None or number < 0 or not float(number).is_integer():
                    continue
                values[str(idx)] = int(number)
            return values

        # Prefer the documented Counter64 packet counters and retain the old
        # IF-MIB unicast counters only as a per-interface compatibility
        # fallback for agents that do not expose ifHC*Pkts.
        hc_in_ucast_map = _typed_counter_map(hc_in_ucast_rows)
        hc_in_multicast_map = _typed_counter_map(hc_in_multicast_rows)
        hc_in_broadcast_map = _typed_counter_map(hc_in_broadcast_rows)
        hc_out_ucast_map = _typed_counter_map(hc_out_ucast_rows)
        hc_out_multicast_map = _typed_counter_map(hc_out_multicast_rows)
        hc_out_broadcast_map = _typed_counter_map(hc_out_broadcast_rows)
        legacy_in_ucast_map = _numeric_counter_map(in_ucast_rows)
        legacy_out_ucast_map = _numeric_counter_map(out_ucast_rows)
        fcs_map = _numeric_counter_map(hc_fcs_rows)
        fcs32_map = _numeric_counter_map(fcs32_rows)
        frame_too_long_map = _numeric_counter_map(hc_frame_too_long_rows)
        mac_rx_map = _numeric_counter_map(hc_mac_rx_rows)
        symbol_map = _numeric_counter_map(hc_symbol_rows)

        legacy_in_valid: list[tuple[str, str]] = []
        legacy_out_valid: list[tuple[str, str]] = []
        if config['counter_mode'] in {'auto', '32'} and set(interfaces) - hc_pair_indices:
            fb_in, fb_out = await asyncio.gather(
                _typed_walk(config['if_in_octets_oid']),
                _typed_walk(config['if_out_octets_oid']),
            )
            legacy_in_valid = _counter_rows(fb_in, 32)
            legacy_out_valid = _counter_rows(fb_out, 32)
        legacy_in_map = dict(legacy_in_valid)
        legacy_out_map = dict(legacy_out_valid)

        # ── Apply collected data to interfaces dict ──

        # ifOperStatus
        for idx, val in status_rows:
            if idx in interfaces:
                s = int(val) if val.isdigit() else 2
                interfaces[idx]['status'] = 'up' if s == 1 else 'down' if s == 2 else 'testing'

        # ifAdminStatus
        for idx, val in admin_status_rows:
            if idx in interfaces:
                s = int(val) if val.isdigit() else 2
                interfaces[idx]['admin_status'] = 'up' if s == 1 else 'down' if s == 2 else 'testing'

        for idx, iface in interfaces.items():
            if 'admin_status' not in iface:
                iface['admin_status'] = 'up' if iface.get('status') == 'up' else 'down'

        # Speed
        speed_map = {idx: int(val) // 1_000_000 for idx, val in speed_rows if val.isdigit()}
        for idx, val in hspeed_rows:
            if idx in interfaces and val.isdigit():
                hs = int(val)
                interfaces[idx]['speed_mbps'] = hs if hs > 0 else speed_map.get(idx, 0)
        for idx, spd in speed_map.items():
            if idx in interfaces and 'speed_mbps' not in interfaces[idx]:
                interfaces[idx]['speed_mbps'] = spd

        # Octets: select one common width per interface.
        for idx in interfaces:
            if config['counter_mode'] in {'auto', '64'} and idx in hc_pair_indices:
                in_value = int(hc_in_map[idx])
                out_value = int(hc_out_map[idx])
                interfaces[idx]['in_octets_hc'] = in_value
                interfaces[idx]['out_octets_hc'] = out_value
                interfaces[idx]['in_octets'] = in_value
                interfaces[idx]['out_octets'] = out_value
                interfaces[idx]['counter_width'] = 64
            elif config['counter_mode'] in {'auto', '32'} and idx in legacy_in_map and idx in legacy_out_map:
                interfaces[idx]['in_octets'] = int(legacy_in_map[idx])
                interfaces[idx]['out_octets'] = int(legacy_out_map[idx])
                interfaces[idx]['counter_width'] = 32

        # Alias
        for idx, val in alias_rows:
            if idx in interfaces:
                interfaces[idx]['description'] = val

        # Error / discard / unicast counters
        for oid_name, rows in [
            ('in_errors', in_err_rows), ('out_errors', out_err_rows),
            ('in_discards', in_disc_rows), ('out_discards', out_disc_rows),
        ]:
            for idx, val in rows:
                number = _parse_snmp_number(val)
                if idx in interfaces and number is not None and number >= 0 and float(number).is_integer():
                    interfaces[idx][oid_name] = int(number)

        # Packet counters are kept as individual values for evidence and as a
        # direction total for rate/error-rate calculations.  The total uses
        # all available HC unicast/multicast/broadcast counters; if an agent
        # only exposes unicast, that value is retained without inventing the
        # missing traffic classes.
        for idx in interfaces:
            in_ucast = hc_in_ucast_map.get(idx, legacy_in_ucast_map.get(idx))
            out_ucast = hc_out_ucast_map.get(idx, legacy_out_ucast_map.get(idx))
            in_multicast = hc_in_multicast_map.get(idx)
            in_broadcast = hc_in_broadcast_map.get(idx)
            out_multicast = hc_out_multicast_map.get(idx)
            out_broadcast = hc_out_broadcast_map.get(idx)
            in_components = [value for value in (in_ucast, in_multicast, in_broadcast) if value is not None]
            out_components = [value for value in (out_ucast, out_multicast, out_broadcast) if value is not None]
            if in_ucast is not None:
                interfaces[idx]['in_ucast_pkts'] = in_ucast
            if out_ucast is not None:
                interfaces[idx]['out_ucast_pkts'] = out_ucast
            if in_multicast is not None:
                interfaces[idx]['in_multicast_pkts'] = in_multicast
            if in_broadcast is not None:
                interfaces[idx]['in_broadcast_pkts'] = in_broadcast
            if out_multicast is not None:
                interfaces[idx]['out_multicast_pkts'] = out_multicast
            if out_broadcast is not None:
                interfaces[idx]['out_broadcast_pkts'] = out_broadcast
            if in_components:
                interfaces[idx]['in_packets_total'] = sum(in_components)
            if out_components:
                interfaces[idx]['out_packets_total'] = sum(out_components)
            if in_ucast is not None or out_ucast is not None:
                interfaces[idx]['packet_counter_source'] = (
                    'ifHCIn/Out{Ucast,Multicast,Broadcast}Pkts'
                    if idx in hc_in_ucast_map or idx in hc_out_ucast_map
                    else 'ifInUcastPkts/ifOutUcastPkts'
                )

            if idx in fcs_map:
                interfaces[idx]['fcs_errors'] = fcs_map[idx]
                interfaces[idx]['fcs_source'] = 'dot3HCStatsFCSErrors'
            elif idx in fcs32_map:
                interfaces[idx]['fcs_errors'] = fcs32_map[idx]
                interfaces[idx]['fcs_source'] = 'dot3StatsFCSErrors'
            if idx in frame_too_long_map:
                interfaces[idx]['frame_too_long_errors'] = frame_too_long_map[idx]
            if idx in mac_rx_map:
                interfaces[idx]['mac_rx_errors'] = mac_rx_map[idx]
            if idx in symbol_map:
                interfaces[idx]['symbol_errors'] = symbol_map[idx]

        # Keep every numeric value returned by the device.  Some agents expose
        # vendor-specific or placeholder-looking values for physical
        # interfaces; the monitoring view must not replace those returned
        # values with zero or an "unavailable" marker.
        for data in interfaces.values():
            if data.get('counter_width') in (32, 64):
                data['counter_quality'] = (
                    'hc64_typed' if data.get('counter_width') == 64 else 'legacy32_typed'
                )

        # A valid ASN.1 Counter64 type does not guarantee valid telemetry.  A
        # few Comware SNMP agents/views return one identical non-zero pair for
        # every physical port while the aggregate row has a different value.
        # Preserve those raw counters, but tag them so health scoring does not
        # turn an agent/view defect into a false interface-error alarm.
        def _is_virtual_or_aggregate(name: object) -> bool:
            lowered = str(name or '').strip().casefold()
            return (
                not lowered
                or lowered.startswith(('lo', 'loopback', 'inloopback', 'vl', 'vlan', 'tu', 'tunnel'))
                or 'tunnel' in lowered
                or any(skip in lowered for skip in ('null', 'nu0', 'unrouted', 'stack', 'cpu', 'async', 'voip', 'vo0'))
                or any(token in lowered for token in ('bridge-aggregation', 'route-aggregation', 'eth-trunk', 'port-channel', 'portchannel', 'lag'))
            )

        physical_counter_rows = [
            data for data in interfaces.values()
            if data.get('counter_width') in (32, 64)
            and not _is_virtual_or_aggregate(data.get('name'))
            and data.get('in_octets') is not None
            and data.get('out_octets') is not None
        ]
        if len(physical_counter_rows) >= 3:
            in_values = {int(data['in_octets']) for data in physical_counter_rows}
            out_values = {int(data['out_octets']) for data in physical_counter_rows}
            if len(in_values) == 1 and len(out_values) == 1:
                in_value = next(iter(in_values))
                out_value = next(iter(out_values))
                if in_value > 0 and out_value > 0:
                    reason = (
                        'SNMP returned the same non-zero byte counter for '
                        f'{len(physical_counter_rows)} physical interfaces '
                        f'(IN={in_value}, OUT={out_value}); raw values are preserved '
                        'but should be checked against the device SNMP view.'
                    )
                    for data in physical_counter_rows:
                        data['counter_quality'] = 'suspicious_uniform'
                        data['counter_quality_reason'] = reason

        # ifLastChange
        sys_uptime_hs = int(sys_uptime_raw) if sys_uptime_raw and sys_uptime_raw.isdigit() else 0
        for idx, val in lc_rows:
            if idx in interfaces and val.isdigit():
                lc_hs = int(val)
                if sys_uptime_hs > 0 and lc_hs <= sys_uptime_hs:
                    secs_ago = (sys_uptime_hs - lc_hs) // 100
                    interfaces[idx]['last_change_secs'] = secs_ago
        if sys_uptime_hs > 0:
            for data in interfaces.values():
                data['device_uptime_cs'] = sys_uptime_hs

    except Exception as e:
        logger.warning(f"SNMP interface collection failed for {ip}: {e}")

    # Filter: skip virtual interfaces (loopback, vlan, tunnel, null, etc.) to only keep physical interfaces
    result = []
    for data in interfaces.values():
        name = data.get('name', '').lower()
        if (name.startswith('lo') or name.startswith('loopback') or
            name.startswith('inloopback') or
            name.startswith('vl') or name.startswith('vlan') or
            name.startswith('tu') or name.startswith('tunnel') or
            'tunnel' in name or
            any(skip in name for skip in ('null', 'nu0', 'unrouted', 'stack', 'cpu', 'async', 'voip', 'vo0'))):
            continue
        result.append({
            'name': data.get('name', 'Unknown'),
            'if_index': int(data.get('index') or 0) if str(data.get('index') or '').isdigit() else None,
            'status': data.get('status', 'unknown'),
            'speed_mbps': data.get('speed_mbps', 0),
            'in_octets': data.get('in_octets') if data.get('counter_width') in (32, 64) else None,
            'out_octets': data.get('out_octets') if data.get('counter_width') in (32, 64) else None,
            'in_octets_hc': data.get('in_octets_hc'),
            'out_octets_hc': data.get('out_octets_hc'),
            'in_octets_32': data.get('in_octets') if data.get('in_octets_hc') is None else None,
            'out_octets_32': data.get('out_octets') if data.get('out_octets_hc') is None else None,
            'counter_width': data.get('counter_width'),
            'counter_source': 'ifHCInOctets/ifHCOutOctets' if data.get('counter_width') == 64 else 'ifInOctets/ifOutOctets' if data.get('counter_width') == 32 else 'not_collected',
            'counter_quality': data.get('counter_quality') or (
                'hc64_typed' if data.get('counter_width') == 64 else
                'legacy32_typed' if data.get('counter_width') == 32 else
                'not_collected'
            ),
             'counter_quality_reason': data.get('counter_quality_reason'),
            'counter_mode': config['counter_mode'],
            'device_uptime_cs': data.get('device_uptime_cs'),
            'description': data.get('description', ''),
            'in_errors': data.get('in_errors', 0),
            'out_errors': data.get('out_errors', 0),
            'in_discards': data.get('in_discards', 0),
            'out_discards': data.get('out_discards', 0),
            'in_ucast_pkts': data.get('in_ucast_pkts', 0),
            'out_ucast_pkts': data.get('out_ucast_pkts', 0),
            'in_multicast_pkts': data.get('in_multicast_pkts', 0),
            'out_multicast_pkts': data.get('out_multicast_pkts', 0),
            'in_broadcast_pkts': data.get('in_broadcast_pkts', 0),
            'out_broadcast_pkts': data.get('out_broadcast_pkts', 0),
            'in_packets_total': data.get('in_packets_total', data.get('in_ucast_pkts', 0)),
            'out_packets_total': data.get('out_packets_total', data.get('out_ucast_pkts', 0)),
            'packet_counter_source': data.get('packet_counter_source', 'not_collected'),
            'fcs_errors': data.get('fcs_errors', 0),
            'fcs_source': data.get('fcs_source', 'not_collected'),
            'frame_too_long_errors': data.get('frame_too_long_errors', 0),
            'mac_rx_errors': data.get('mac_rx_errors', 0),
            'symbol_errors': data.get('symbol_errors', 0),
            'last_change_secs': data.get('last_change_secs'),
        })

    _set_result_cache(cache_key, result)
    return result


async def collect_interface_health(
    ip: str,
    community: str = 'public',
    port: int = 161,
    interface_config: Mapping[str, Any] | None = None,
    *,
    template_only: bool = False,
) -> list[dict]:
    """Collect only interface identity and oper state for device health.

    The regular interface collector is intentionally richer because topology,
    WAN, and inspection views need counters and utilization.  The periodic
    device-health path only needs to know which physical interfaces exist and
    whether they are up/down.  This function therefore performs at most three
    bulk walks (ifName, ifDescr fallback, and ifOperStatus) and returns the
    legacy row shape with counter fields left unset for safe consumers.
    """
    if template_only and not interface_config:
        return []
    config = normalize_interface_config(interface_config) if interface_config else dict(DEFAULT_INTERFACE_CONFIG)
    if not config.get('enabled', True):
        if template_only:
            return []
        config = dict(DEFAULT_INTERFACE_CONFIG)
    community_token = hashlib.sha256(str(community or '').encode('utf-8')).hexdigest()[:12]
    config_token = hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    ).hexdigest()[:16]
    cache_key = f"intf-health:{ip}:{port}:{int(template_only)}:{community_token}:{config_token}"
    cached = _get_result_cache(cache_key)
    if cached is not None:
        return cached

    interfaces: dict[str, dict[str, Any]] = {}
    try:
        async def _walk(oid: str):
            return await _snmp_bulk_walk(ip, community, oid, port) if oid else []

        name_rows = await _walk(config['if_name_oid'])
        if not name_rows:
            name_rows = await _walk(config['if_descr_oid'])
        for idx, value in name_rows:
            interfaces[str(idx)] = {'name': str(value or '').strip() or f'ifIndex {idx}', 'index': idx}

        status_rows = await _walk(config['if_oper_status_oid'])
        for idx, value in status_rows:
            key = str(idx)
            if key not in interfaces:
                continue
            raw_status = str(value or '').strip().split('(', 1)[0]
            try:
                status_code = int(raw_status)
            except (TypeError, ValueError):
                status_code = 0
            interfaces[key]['status'] = (
                'up' if status_code == 1
                else 'down' if status_code == 2
                else 'testing' if status_code in {3, 4, 5}
                else 'unknown'
            )
    except Exception as exc:
        logger.warning(f"SNMP interface health collection failed for {ip}: {exc}")

    result: list[dict[str, Any]] = []
    for data in interfaces.values():
        name = str(data.get('name') or '').strip()
        lowered = name.casefold()
        if (
            lowered.startswith(('lo', 'loopback', 'vl', 'vlan', 'tu', 'tunnel'))
            or any(skip in lowered for skip in ('null', 'nu0', 'unrouted', 'stack', 'cpu', 'async', 'voip', 'vo0'))
        ):
            continue
        index = data.get('index')
        result.append({
            'name': name or 'Unknown',
            'if_index': int(index) if str(index or '').isdigit() else None,
            'status': data.get('status', 'unknown'),
            'speed_mbps': 0,
            'in_octets': None,
            'out_octets': None,
            'in_octets_hc': None,
            'out_octets_hc': None,
            'in_octets_32': None,
            'out_octets_32': None,
            'counter_width': None,
            'counter_source': 'not_collected',
            'counter_quality': 'not_collected',
            'counter_mode': 'disabled',
            'device_uptime_cs': None,
            'description': '',
            'in_errors': 0,
            'out_errors': 0,
            'in_discards': 0,
            'out_discards': 0,
            'in_ucast_pkts': 0,
            'out_ucast_pkts': 0,
            'last_change_secs': None,
            'collection_mode': 'health_only',
        })

    _set_result_cache(cache_key, result)
    return result


async def probe_interface_definition(
    ip: str,
    community: str,
    config: Mapping[str, Any] | None = None,
    port: int = 161,
    version: str = '2c',
) -> dict[str, Any]:
    """Validate an interface template without changing throughput baselines.

    Identity and a paired counter width are the mandatory checks.  Status,
    speed, alias and error/packet columns are reported individually because
    restricted SNMP views commonly omit one of those optional columns while
    still exposing usable traffic counters.
    """
    try:
        normalized = normalize_interface_config(config)
    except ValueError as exc:
        return {
            'passed': False,
            'status': 'invalid_config',
            'message': str(exc),
            'checks': {},
            'counter_mode': None,
            'interfaces': 0,
            'counter_supported': 0,
        }
    if not normalized:
        normalized = dict(DEFAULT_INTERFACE_CONFIG)
    version_key = str(version or '2c').strip().lower()
    if version_key in {'v1', '1'}:
        version_key = '1'
    else:
        version_key = '2c'
    if not normalized.get('enabled', True):
        return {
            'passed': True,
            'status': 'disabled',
            'message': 'Interface profile is disabled; built-in IF-MIB mapping remains active',
            'checks': {},
            'interface_config': normalized,
            'counter_mode': normalized['counter_mode'],
            'interfaces': 0,
            'counter_supported': 0,
            'version': version_key,
        }

    async def _walk(oid: str):
        if not oid:
            return []
        try:
            # Keep the legacy four-argument call for the default v2c path so
            # existing collectors and tests that replace the walker remain
            # compatible.  SNMPv1 explicitly uses the version-aware path.
            if version_key == '2c':
                return await asyncio.wait_for(
                    _snmp_bulk_walk(ip, community, oid, port),
                    timeout=INTERFACE_PROBE_OID_TIMEOUT_SECONDS,
                )
            return await asyncio.wait_for(
                _snmp_bulk_walk(ip, community, oid, port, version=version_key),
                timeout=INTERFACE_PROBE_OID_TIMEOUT_SECONDS,
            )
        except Exception:
            return []

    async def _typed_walk(oid: str):
        if not oid:
            return []
        try:
            if version_key == '2c':
                return await asyncio.wait_for(
                    _snmp_bulk_walk_typed(ip, community, oid, port),
                    timeout=INTERFACE_PROBE_OID_TIMEOUT_SECONDS,
                )
            return await asyncio.wait_for(
                _snmp_bulk_walk_typed(ip, community, oid, port, version=version_key),
                timeout=INTERFACE_PROBE_OID_TIMEOUT_SECONDS,
            )
        except Exception:
            return []

    (
        identity_rows,
        descr_rows,
        status_rows,
        high_speed_rows,
        speed_rows,
        alias_rows,
        last_change_rows,
        in_error_rows,
        out_error_rows,
        in_discard_rows,
        out_discard_rows,
        in_ucast_rows,
        out_ucast_rows,
        hc_in_ucast_rows,
        hc_in_multicast_rows,
        hc_in_broadcast_rows,
        hc_out_ucast_rows,
        hc_out_multicast_rows,
        hc_out_broadcast_rows,
        hc_fcs_rows,
        hc_frame_too_long_rows,
        hc_mac_rx_rows,
        hc_symbol_rows,
        fcs32_rows,
        hc_in_rows,
        hc_out_rows,
        legacy_in_rows,
        legacy_out_rows,
    ) = await asyncio.gather(
        _walk(normalized['if_name_oid']),
        _walk(normalized['if_descr_oid']),
        _walk(normalized['if_oper_status_oid']),
        _walk(normalized['if_high_speed_oid']),
        _walk(normalized['if_speed_oid']),
        _walk(normalized['if_alias_oid']),
        _walk(normalized['if_last_change_oid']),
        _walk(normalized['if_in_errors_oid']),
        _walk(normalized['if_out_errors_oid']),
        _walk(normalized['if_in_discards_oid']),
        _walk(normalized['if_out_discards_oid']),
        _walk(normalized['if_in_ucast_oid']),
        _walk(normalized['if_out_ucast_oid']),
        _typed_walk(normalized['if_hc_in_ucast_pkts_oid']),
        _typed_walk(normalized['if_hc_in_multicast_pkts_oid']),
        _typed_walk(normalized['if_hc_in_broadcast_pkts_oid']),
        _typed_walk(normalized['if_hc_out_ucast_pkts_oid']),
        _typed_walk(normalized['if_hc_out_multicast_pkts_oid']),
        _typed_walk(normalized['if_hc_out_broadcast_pkts_oid']),
        _walk(normalized['dot3_hc_fcs_errors_oid']),
        _walk(normalized['dot3_hc_frame_too_long_oid']),
        _walk(normalized['dot3_hc_internal_mac_rx_errors_oid']),
        _walk(normalized['dot3_hc_symbol_errors_oid']),
        _walk(normalized['dot3_fcs_errors_oid']),
        _typed_walk(normalized['if_hc_in_octets_oid']) if normalized['counter_mode'] in {'auto', '64'} else asyncio.sleep(0, result=[]),
        _typed_walk(normalized['if_hc_out_octets_oid']) if normalized['counter_mode'] in {'auto', '64'} else asyncio.sleep(0, result=[]),
        _typed_walk(normalized['if_in_octets_oid']) if normalized['counter_mode'] in {'auto', '32'} else asyncio.sleep(0, result=[]),
        _typed_walk(normalized['if_out_octets_oid']) if normalized['counter_mode'] in {'auto', '32'} else asyncio.sleep(0, result=[]),
    )

    def _valid_counter_rows(rows: list[tuple[str, SnmpTypedValue]], bits: int) -> dict[str, int]:
        values: dict[str, int] = {}
        for index, value in rows:
            if value.snmp_type != 'counter' or value.counter_bits != bits or value.number is None:
                continue
            try:
                number = int(value.number)
            except (TypeError, ValueError, OverflowError):
                continue
            if number >= 0:
                values[str(index)] = number
        return values

    hc_in = _valid_counter_rows(hc_in_rows, 64)
    hc_out = _valid_counter_rows(hc_out_rows, 64)
    legacy_in = _valid_counter_rows(legacy_in_rows, 32)
    legacy_out = _valid_counter_rows(legacy_out_rows, 32)
    hc_pairs = set(hc_in).intersection(hc_out)
    legacy_pairs = set(legacy_in).intersection(legacy_out)

    # A structurally valid table can still be a bad telemetry source.  Some
    # Comware agents return the same non-zero placeholder for every physical
    # port while returning a changing value for an aggregation interface.  Do
    # not rewrite or discard those device values—the collector contract is to
    # expose exactly what SNMP returned—but surface the anomaly during OID
    # verification so a template is not mistaken for a trustworthy source.
    identity_by_index = {
        str(index): str(value or '').strip()
        for index, value in (identity_rows or descr_rows)
    }

    def _looks_virtual_or_aggregate(name: str) -> bool:
        normalized_name = str(name or '').strip().lower()
        return any(
            token in normalized_name
            for token in (
                'bridge-aggregation', 'route-aggregation', 'eth-trunk',
                'port-channel', 'portchannel', 'lag', 'loopback',
                'inloopback', 'vlan', 'tunnel', 'register-', 'null',
            )
        )

    physical_counter_indices = {
        index for index in hc_pairs
        if index in identity_by_index
        and not _looks_virtual_or_aggregate(identity_by_index[index])
    }
    verification_warnings: list[dict[str, Any]] = []
    if len(physical_counter_indices) >= 3:
        physical_in_values = {hc_in[index] for index in physical_counter_indices}
        physical_out_values = {hc_out[index] for index in physical_counter_indices}
        if (
            len(physical_in_values) == 1
            and len(physical_out_values) == 1
            and next(iter(physical_in_values), 0) > 0
            and next(iter(physical_out_values), 0) > 0
        ):
            verification_warnings.append({
                'code': 'uniform_nonzero_counter64',
                'severity': 'warning',
                'message': (
                    'Counter64 octet counters returned the same non-zero value '
                    f'for {len(physical_counter_indices)} physical interfaces; '
                    'verify the device SNMP Agent/view or vendor MIB.'
                ),
                'physical_interfaces': len(physical_counter_indices),
                'in_value': next(iter(physical_in_values)),
                'out_value': next(iter(physical_out_values)),
            })

    def _valid_optional_counter_rows(rows: list[tuple[str, SnmpTypedValue]]) -> dict[str, int]:
        return _valid_counter_rows(rows, 64)

    hc_packet_maps = {
        'in_ucast': _valid_optional_counter_rows(hc_in_ucast_rows),
        'in_multicast': _valid_optional_counter_rows(hc_in_multicast_rows),
        'in_broadcast': _valid_optional_counter_rows(hc_in_broadcast_rows),
        'out_ucast': _valid_optional_counter_rows(hc_out_ucast_rows),
        'out_multicast': _valid_optional_counter_rows(hc_out_multicast_rows),
        'out_broadcast': _valid_optional_counter_rows(hc_out_broadcast_rows),
    }
    mode = normalized['counter_mode']
    selected_width = 64 if mode == '64' and hc_pairs else 32 if mode == '32' and legacy_pairs else None
    if mode == 'auto':
        selected_width = 64 if hc_pairs else 32 if legacy_pairs else None
    selected_pairs = hc_pairs if selected_width == 64 else legacy_pairs if selected_width == 32 else set()

    def _sample_text_rows(rows: list[tuple[str, str]], limit: int = 3) -> list[dict[str, str]]:
        return [
            {'index': str(index), 'value': str(value)}
            for index, value in rows[:limit]
        ]

    def _sample_counter_rows(values: Mapping[str, int], limit: int = 3) -> list[dict[str, int | str]]:
        return [
            {'index': str(index), 'value': int(value)}
            for index, value in list(values.items())[:limit]
        ]

    checks = {
        'identity': {
            'oid': normalized['if_name_oid'] or normalized['if_descr_oid'],
            'passed': bool(identity_rows or descr_rows),
            'rows': len(identity_rows or descr_rows),
            'message': 'ifName/ifDescr table available' if (identity_rows or descr_rows) else 'No interface identity rows returned',
            'sample': _sample_text_rows(identity_rows or descr_rows),
        },
        'oper_status': {'oid': normalized['if_oper_status_oid'], 'passed': bool(status_rows), 'rows': len(status_rows), 'sample': _sample_text_rows(status_rows)},
        'high_speed': {'oid': normalized['if_high_speed_oid'], 'passed': bool(high_speed_rows), 'rows': len(high_speed_rows), 'sample': _sample_text_rows(high_speed_rows)},
        'speed': {'oid': normalized['if_speed_oid'], 'passed': bool(speed_rows), 'rows': len(speed_rows), 'sample': _sample_text_rows(speed_rows)},
        'alias': {'oid': normalized['if_alias_oid'], 'passed': bool(alias_rows), 'rows': len(alias_rows), 'sample': _sample_text_rows(alias_rows)},
        'last_change': {'oid': normalized['if_last_change_oid'], 'passed': bool(last_change_rows), 'rows': len(last_change_rows), 'sample': _sample_text_rows(last_change_rows)},
        'in_errors': {'oid': normalized['if_in_errors_oid'], 'passed': bool(in_error_rows), 'rows': len(in_error_rows), 'sample': _sample_text_rows(in_error_rows)},
        'out_errors': {'oid': normalized['if_out_errors_oid'], 'passed': bool(out_error_rows), 'rows': len(out_error_rows), 'sample': _sample_text_rows(out_error_rows)},
        'in_discards': {'oid': normalized['if_in_discards_oid'], 'passed': bool(in_discard_rows), 'rows': len(in_discard_rows), 'sample': _sample_text_rows(in_discard_rows)},
        'out_discards': {'oid': normalized['if_out_discards_oid'], 'passed': bool(out_discard_rows), 'rows': len(out_discard_rows), 'sample': _sample_text_rows(out_discard_rows)},
        'in_ucast': {'oid': normalized['if_in_ucast_oid'], 'passed': bool(in_ucast_rows), 'rows': len(in_ucast_rows), 'sample': _sample_text_rows(in_ucast_rows)},
        'out_ucast': {'oid': normalized['if_out_ucast_oid'], 'passed': bool(out_ucast_rows), 'rows': len(out_ucast_rows), 'sample': _sample_text_rows(out_ucast_rows)},
        'counter64_in_ucast': {'oid': normalized['if_hc_in_ucast_pkts_oid'], 'passed': bool(hc_packet_maps['in_ucast']), 'rows': len(hc_packet_maps['in_ucast']), 'counter_bits': 64, 'sample': _sample_counter_rows(hc_packet_maps['in_ucast'])},
        'counter64_in_multicast': {'oid': normalized['if_hc_in_multicast_pkts_oid'], 'passed': bool(hc_packet_maps['in_multicast']), 'rows': len(hc_packet_maps['in_multicast']), 'counter_bits': 64, 'sample': _sample_counter_rows(hc_packet_maps['in_multicast'])},
        'counter64_in_broadcast': {'oid': normalized['if_hc_in_broadcast_pkts_oid'], 'passed': bool(hc_packet_maps['in_broadcast']), 'rows': len(hc_packet_maps['in_broadcast']), 'counter_bits': 64, 'sample': _sample_counter_rows(hc_packet_maps['in_broadcast'])},
        'counter64_out_ucast': {'oid': normalized['if_hc_out_ucast_pkts_oid'], 'passed': bool(hc_packet_maps['out_ucast']), 'rows': len(hc_packet_maps['out_ucast']), 'counter_bits': 64, 'sample': _sample_counter_rows(hc_packet_maps['out_ucast'])},
        'counter64_out_multicast': {'oid': normalized['if_hc_out_multicast_pkts_oid'], 'passed': bool(hc_packet_maps['out_multicast']), 'rows': len(hc_packet_maps['out_multicast']), 'counter_bits': 64, 'sample': _sample_counter_rows(hc_packet_maps['out_multicast'])},
        'counter64_out_broadcast': {'oid': normalized['if_hc_out_broadcast_pkts_oid'], 'passed': bool(hc_packet_maps['out_broadcast']), 'rows': len(hc_packet_maps['out_broadcast']), 'counter_bits': 64, 'sample': _sample_counter_rows(hc_packet_maps['out_broadcast'])},
        'dot3_hc_fcs_errors': {'oid': normalized['dot3_hc_fcs_errors_oid'], 'passed': bool(hc_fcs_rows), 'rows': len(hc_fcs_rows), 'sample': _sample_text_rows(hc_fcs_rows)},
        'dot3_hc_frame_too_long': {'oid': normalized['dot3_hc_frame_too_long_oid'], 'passed': bool(hc_frame_too_long_rows), 'rows': len(hc_frame_too_long_rows), 'sample': _sample_text_rows(hc_frame_too_long_rows)},
        'dot3_hc_internal_mac_rx_errors': {'oid': normalized['dot3_hc_internal_mac_rx_errors_oid'], 'passed': bool(hc_mac_rx_rows), 'rows': len(hc_mac_rx_rows), 'sample': _sample_text_rows(hc_mac_rx_rows)},
        'dot3_hc_symbol_errors': {'oid': normalized['dot3_hc_symbol_errors_oid'], 'passed': bool(hc_symbol_rows), 'rows': len(hc_symbol_rows), 'sample': _sample_text_rows(hc_symbol_rows)},
        'dot3_fcs_errors_32_fallback': {'oid': normalized['dot3_fcs_errors_oid'], 'passed': bool(fcs32_rows), 'rows': len(fcs32_rows), 'sample': _sample_text_rows(fcs32_rows)},
        'counter64_in': {'oid': normalized['if_hc_in_octets_oid'], 'passed': bool(hc_in), 'rows': len(hc_in), 'counter_bits': 64, 'sample': _sample_counter_rows(hc_in)},
        'counter64_out': {'oid': normalized['if_hc_out_octets_oid'], 'passed': bool(hc_out), 'rows': len(hc_out), 'counter_bits': 64, 'sample': _sample_counter_rows(hc_out)},
        'counter32_in': {'oid': normalized['if_in_octets_oid'], 'passed': bool(legacy_in), 'rows': len(legacy_in), 'counter_bits': 32, 'sample': _sample_counter_rows(legacy_in)},
        'counter32_out': {'oid': normalized['if_out_octets_oid'], 'passed': bool(legacy_out), 'rows': len(legacy_out), 'counter_bits': 32, 'sample': _sample_counter_rows(legacy_out)},
    }
    passed = bool(identity_rows or descr_rows) and bool(selected_pairs)
    if passed:
        message = f'Interface table and paired Counter{selected_width} counters passed validation'
    elif not (identity_rows or descr_rows):
        message = 'Interface identity table validation failed'
    else:
        message = f'No paired Counter{mode if mode in {"32", "64"} else "32/64"} octet counters returned'
    if verification_warnings:
        message += ' Warning: ' + ' '.join(item['message'] for item in verification_warnings)
    return {
        'passed': passed,
        'status': 'ok' if passed else 'missing',
        'message': message,
        'checks': checks,
        'interface_config': normalized,
        'counter_mode': mode,
        'selected_counter_bits': selected_width,
        'interfaces': len(identity_rows or descr_rows),
        'counter_supported': len(selected_pairs),
        'version': version_key,
        'warnings': verification_warnings,
    }


async def collect_interface_data_detailed(
    ip: str,
    community: str = 'public',
    port: int = 161,
    interface_config: Mapping[str, Any] | None = None,
    *,
    template_only: bool = False,
) -> dict:
    """Return IF-MIB data with an explicit, secret-free collection outcome.

    The legacy collector intentionally returns a best-effort list for existing
    callers. WAN monitoring needs to distinguish a complete walk from a
    missing/partial walk so that a failed poll cannot be interpreted as an
    interface-down sample. This wrapper keeps the old API stable while adding
    the stricter contract for the WAN domain.
    """
    if template_only and not interface_config:
        return {
            'status': 'template_not_applied',
            'items': [],
            'error_code': 'snmp_template_not_applied',
            'error_message': 'No applied SNMP interface template is available for this device model',
        }
    try:
        result = await collect_interface_data(
            ip,
            community,
            port,
            interface_config,
            template_only=template_only,
        )
    except Exception as exc:  # pragma: no cover - defensive boundary
        message = str(exc).lower()
        status = 'auth_failed' if any(token in message for token in ('authentication', 'authorization', 'community')) else 'timeout' if 'timeout' in message else 'device_unreachable'
        return {'status': status, 'items': [], 'error_code': status, 'error_message': type(exc).__name__}
    if result:
        # A non-empty IF-MIB response is not automatically a complete poll:
        # restricted SNMP views often return identity rows while omitting
        # oper-status or one side of the octet counter pair.  Treat the walk
        # as partial unless every returned physical interface has the minimum
        # status + paired counter evidence required by WAN rate calculation.
        complete_items = [
            item for item in result
            if str(item.get('status') or '').lower() in {'up', 'down'}
            and item.get('counter_width') in {32, 64}
            and item.get('in_octets') is not None
            and item.get('out_octets') is not None
        ]
        if len(complete_items) != len(result):
            return {
                'status': 'partial',
                'items': result,
                'error_code': 'partial_data',
                'error_message': 'SNMP IF-MIB walk returned incomplete interface evidence',
                'complete_items': len(complete_items),
                'total_items': len(result),
            }
        return {'status': 'success', 'items': result, 'error_code': '', 'error_message': ''}
    # The underlying best-effort walker suppresses transport details. A
    # failed/empty walk is therefore recorded as timeout-like evidence rather
    # than as a successful empty inventory.
    return {
        'status': 'timeout',
        'items': [],
        'error_code': 'timeout',
        'error_message': 'SNMP IF-MIB walk returned no interfaces',
    }
