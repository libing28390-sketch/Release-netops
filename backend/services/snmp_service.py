"""SNMP identity, IF-MIB interface monitoring, LLDP, and raw walk transport.

Hardware discovery and polling execute versioned LibreNMS rules locally.
This module owns their SNMP transport and interface operations.
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
IF_MTU         = '1.3.6.1.2.1.2.2.1.4'
IF_PHYS_ADDRESS = '1.3.6.1.2.1.2.2.1.6'
IF_ADMIN_STATUS = '1.3.6.1.2.1.2.2.1.7'
IF_OPER_STATUS = '1.3.6.1.2.1.2.2.1.8'
IF_SPEED       = '1.3.6.1.2.1.2.2.1.5'
IF_IN_OCTETS   = '1.3.6.1.2.1.2.2.1.10'
IF_OUT_OCTETS  = '1.3.6.1.2.1.2.2.1.16'
IF_HC_IN       = '1.3.6.1.2.1.31.1.1.1.6'
IF_HC_OUT      = '1.3.6.1.2.1.31.1.1.1.10'
IF_ALIAS       = '1.3.6.1.2.1.31.1.1.1.18'
IF_NAME        = '1.3.6.1.2.1.31.1.1.1.1'

# Standard IP-MIB address rows.  ``ipAddressIfIndex`` joins the address
# table to IF-MIB's ifIndex; ``ipAddressPrefix`` points at the corresponding
# row in ipAddressPrefixTable (whose index ends with the prefix length).
IP_ADDRESS_IF_INDEX = '1.3.6.1.2.1.4.34.1.3'
IP_ADDRESS_TYPE = '1.3.6.1.2.1.4.34.1.4'
IP_ADDRESS_PREFIX = '1.3.6.1.2.1.4.34.1.5'
IP_ADDRESS_STATUS = '1.3.6.1.2.1.4.34.1.7'
IP_ADDRESS_PREFIX_ENTRY = '1.3.6.1.2.1.4.32.1'

# Q-BRIDGE-MIB current membership is indexed by TimeMark and VLAN ID.  Its
# PortLists use dot1dBasePort numbers, which must be translated to ifIndex.
DOT1Q_VLAN_CURRENT_EGRESS_PORTS = '1.3.6.1.2.1.17.7.1.4.2.1.4'
DOT1Q_VLAN_CURRENT_UNTAGGED_PORTS = '1.3.6.1.2.1.17.7.1.4.2.1.5'
DOT1Q_VLAN_STATIC_NAME = '1.3.6.1.2.1.17.7.1.4.3.1.1'
DOT1Q_PORT_PVID = '1.3.6.1.2.1.17.7.1.4.5.1.1'

# IF-MIB high-speed (for >=10G interfaces)
IF_HIGH_SPEED     = '1.3.6.1.2.1.31.1.1.1.15'   # ifHighSpeed (Mbps)

# ifLastChange: sysUpTime when oper status last changed (hundredths of sec)
IF_LAST_CHANGE    = '1.3.6.1.2.1.2.2.1.9'        # ifLastChange (TimeTicks)

# Standard IP-MIB IPv4 address translation (ARP) table.
IP_NET_TO_MEDIA_PHYS_ADDRESS = '1.3.6.1.2.1.4.22.1.2'
IP_NET_TO_MEDIA_TYPE = '1.3.6.1.2.1.4.22.1.4'

# Standard Q-BRIDGE-MIB forwarding and VLAN-to-FDB tables.
DOT1Q_TP_FDB_PORT = '1.3.6.1.2.1.17.7.1.2.2.1.2'
DOT1Q_TP_FDB_STATUS = '1.3.6.1.2.1.17.7.1.2.2.1.3'
DOT1Q_VLAN_FDB_ID = '1.3.6.1.2.1.17.7.1.4.2.1.3'
DOT1D_BASE_PORT_IF_INDEX = '1.3.6.1.2.1.17.1.4.1.2'


# IP-FORWARD-MIB inetCidrRouteTable.  The index is shared by all columns;
# only columns with MAX-ACCESS other than not-accessible can be walked.
INET_CIDR_ROUTE_IF_INDEX = '1.3.6.1.2.1.4.24.7.1.7'
INET_CIDR_ROUTE_TYPE = '1.3.6.1.2.1.4.24.7.1.8'
INET_CIDR_ROUTE_PROTO = '1.3.6.1.2.1.4.24.7.1.9'
INET_CIDR_ROUTE_AGE = '1.3.6.1.2.1.4.24.7.1.10'
INET_CIDR_ROUTE_NEXT_HOP_AS = '1.3.6.1.2.1.4.24.7.1.11'
INET_CIDR_ROUTE_METRIC1 = '1.3.6.1.2.1.4.24.7.1.12'
INET_CIDR_ROUTE_METRIC2 = '1.3.6.1.2.1.4.24.7.1.13'
INET_CIDR_ROUTE_METRIC3 = '1.3.6.1.2.1.4.24.7.1.14'
INET_CIDR_ROUTE_METRIC4 = '1.3.6.1.2.1.4.24.7.1.15'
INET_CIDR_ROUTE_METRIC5 = '1.3.6.1.2.1.4.24.7.1.16'
INET_CIDR_ROUTE_STATUS = '1.3.6.1.2.1.4.24.7.1.17'

# Standard routing-protocol neighbor tables (RFC 4273, RFC 4750, RFC 5643,
# and RFC 4444 respectively).
BGP4_PEER_IDENTIFIER = '1.3.6.1.2.1.15.3.1.1'
BGP4_LOCAL_AS = '1.3.6.1.2.1.15.2.0'
BGP4_PEER_STATE = '1.3.6.1.2.1.15.3.1.2'
BGP4_PEER_ADMIN_STATUS = '1.3.6.1.2.1.15.3.1.3'
BGP4_PEER_LOCAL_ADDRESS = '1.3.6.1.2.1.15.3.1.5'
BGP4_PEER_REMOTE_ADDRESS = '1.3.6.1.2.1.15.3.1.7'
BGP4_PEER_REMOTE_AS = '1.3.6.1.2.1.15.3.1.9'
BGP4_PEER_FSM_ESTABLISHED_TIME = '1.3.6.1.2.1.15.3.1.16'
RIP2_PEER_ADDRESS = '1.3.6.1.2.1.23.4.1.1'
RIP2_PEER_DOMAIN = '1.3.6.1.2.1.23.4.1.2'
RIP2_PEER_LAST_UPDATE = '1.3.6.1.2.1.23.4.1.3'
RIP2_PEER_VERSION = '1.3.6.1.2.1.23.4.1.4'
RIP2_PEER_BAD_PACKETS = '1.3.6.1.2.1.23.4.1.5'
RIP2_PEER_BAD_ROUTES = '1.3.6.1.2.1.23.4.1.6'
EIGRP_PEER_ADDRESS_TYPE = '1.3.6.1.4.1.9.9.449.1.4.1.1.2'
EIGRP_PEER_ADDRESS = '1.3.6.1.4.1.9.9.449.1.4.1.1.3'
EIGRP_PEER_IF_INDEX = '1.3.6.1.4.1.9.9.449.1.4.1.1.4'
EIGRP_PEER_HOLD_TIME = '1.3.6.1.4.1.9.9.449.1.4.1.1.5'
OSPF_NBR_ROUTER_ID = '1.3.6.1.2.1.14.10.1.3'
OSPF_NBR_PRIORITY = '1.3.6.1.2.1.14.10.1.5'
OSPF_NBR_STATE = '1.3.6.1.2.1.14.10.1.6'
OSPF_NBR_EVENTS = '1.3.6.1.2.1.14.10.1.7'
OSPF_NBR_RETRANS_QUEUE = '1.3.6.1.2.1.14.10.1.8'
OSPFV3_NBR_ADDRESS_TYPE = '1.3.6.1.2.1.191.1.9.1.4'
OSPFV3_NBR_ADDRESS = '1.3.6.1.2.1.191.1.9.1.5'
OSPFV3_NBR_PRIORITY = '1.3.6.1.2.1.191.1.9.1.7'
OSPFV3_NBR_STATE = '1.3.6.1.2.1.191.1.9.1.8'
OSPFV3_NBR_EVENTS = '1.3.6.1.2.1.191.1.9.1.9'
ISIS_CIRC_IF_INDEX = '1.3.6.1.2.1.138.1.3.2.1.2'
ISIS_ADJ_STATE = '1.3.6.1.2.1.138.1.6.1.1.2'
ISIS_ADJ_THREE_WAY_STATE = '1.3.6.1.2.1.138.1.6.1.1.3'
ISIS_ADJ_SNPA_ADDRESS = '1.3.6.1.2.1.138.1.6.1.1.4'
ISIS_ADJ_NEIGHBOR_TYPE = '1.3.6.1.2.1.138.1.6.1.1.5'
ISIS_ADJ_NEIGHBOR_SYSTEM_ID = '1.3.6.1.2.1.138.1.6.1.1.6'
ISIS_ADJ_USAGE = '1.3.6.1.2.1.138.1.6.1.1.8'
ISIS_ADJ_HOLD_TIMER = '1.3.6.1.2.1.138.1.6.1.1.9'
ISIS_ADJ_NEIGHBOR_PRIORITY = '1.3.6.1.2.1.138.1.6.1.1.10'

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


def parse_snmp_uptime_seconds(value: Any) -> Optional[float]:
    """Normalize SNMP TimeTicks and common timedelta text into seconds."""
    if value is None or isinstance(value, bool):
        return None

    raw_value = str(value).strip()
    if not raw_value:
        return None

    tick_match = re.search(r'\(\s*(\d+)\s*(?:ticks?)?\s*\)', raw_value, re.IGNORECASE)
    if tick_match:
        return int(tick_match.group(1)) / 100.0

    duration_match = re.fullmatch(
        r'(?:(?P<days>\d+)\s+days?,?\s*)?(?P<hours>\d+):(?P<minutes>[0-5]\d):(?P<seconds>[0-5]\d(?:\.\d+)?)',
        raw_value,
        re.IGNORECASE,
    )
    if duration_match:
        days = int(duration_match.group('days') or 0)
        hours = int(duration_match.group('hours'))
        minutes = int(duration_match.group('minutes'))
        seconds = float(duration_match.group('seconds'))
        return float(days * 86400 + hours * 3600 + minutes * 60) + seconds

    if re.fullmatch(r'\d+(?:\.\d+)?', raw_value):
        return float(raw_value) / 100.0
    return None


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


def _snmpv3_credentials(profile: Mapping[str, Any]):
    """Create puresnmp USM credentials from a resolved, server-side profile."""
    from puresnmp import Auth, Priv, V3

    username = str(profile.get('username') or '').strip()
    level = str(profile.get('security_level') or 'authPriv').strip().casefold()
    if not username:
        raise ValueError('SNMPv3 username is missing')
    if level not in {'noauthnopriv', 'authnopriv', 'authpriv'}:
        raise ValueError('Unsupported SNMPv3 security level')

    auth = None
    privacy = None
    if level != 'noauthnopriv':
        auth_password = str(profile.get('auth_password') or '')
        auth_method = str(profile.get('auth_protocol') or 'SHA').strip().casefold()
        auth_methods = {
            'md5': 'md5',
            'sha': 'sha1', 'sha1': 'sha1', 'sha-1': 'sha1',
            'sha224': 'sha224', 'sha-224': 'sha224',
            'sha256': 'sha256', 'sha-256': 'sha256',
            'sha384': 'sha384', 'sha-384': 'sha384',
            'sha512': 'sha512', 'sha-512': 'sha512',
        }
        if not auth_password:
            raise ValueError('SNMPv3 authentication password is missing')
        if auth_method not in auth_methods:
            raise ValueError('Unsupported SNMPv3 authentication protocol')
        auth = Auth(auth_password.encode('utf-8'), auth_methods[auth_method])

    if level == 'authpriv':
        priv_password = str(profile.get('priv_password') or '')
        priv_method = str(profile.get('priv_protocol') or 'AES').strip().casefold()
        priv_methods = {'aes': 'aes', 'aes-128': 'aes', 'des': 'des'}
        if not priv_password:
            raise ValueError('SNMPv3 privacy password is missing')
        if priv_method not in priv_methods:
            raise ValueError('Unsupported SNMPv3 privacy protocol')
        privacy = Priv(priv_password.encode('utf-8'), priv_methods[priv_method])

    context_name = str(profile.get('context_name') or '').encode('utf-8')
    return V3(username, auth=auth, priv=privacy), context_name


def _build_versioned_snmp_client(
    ip: str,
    community_or_profile: str | Mapping[str, Any],
    port: int,
    version: str,
):
    """Build a bounded puresnmp client for v1/v2c or a resolved v3 profile."""
    from puresnmp import V1, V2C

    version_key = str(version or '2c').strip().casefold()
    if version_key in {'3', 'v3', 'snmpv3'}:
        if not isinstance(community_or_profile, Mapping):
            raise ValueError('SNMPv3 requires a bound credential profile')
        credentials, context_name = _snmpv3_credentials(community_or_profile)
        if context_name:
            return _build_snmp_client(ip, credentials, port, context_name=context_name)
        return _build_snmp_client(ip, credentials, port)
    community = str(community_or_profile or '')
    auth = V1(community) if version_key in {'v1', '1'} else V2C(community)
    return _build_snmp_client(ip, auth, port)


def _build_snmp_client(ip: str, auth, port: int, *, context_name: bytes = b''):
    """Build a client whose internal deadline fits the collector deadline."""
    from puresnmp import Client

    if context_name:
        client = Client(ip, auth, port=port, sender=_safe_send_udp, context_name=context_name)
    else:
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
    community: str | Mapping[str, Any],
    oid: str,
    port: int = 161,
    timeout: float = 3,
    version: str = '2c',
) -> Optional[str]:
    """GET one OID via puresnmp using v1, v2c, or a resolved v3 profile."""
    async with get_network_access_limiter().async_snmp():
      try:
        version_key = str(version or '2c').strip().lower()
        from puresnmp import PyWrapper

        client = PyWrapper(_build_versioned_snmp_client(ip, community, port, version_key))
        result = await asyncio.wait_for(client.get(oid), timeout=timeout)
        if result is None:
            return None
        v = _val_to_str(result)
        if v and 'noSuchObject' not in v and 'noSuchInstance' not in v:
            return v
      except Exception as e:
        if str(version or '').strip().casefold() in {'3', 'v3', 'snmpv3'}:
            logger.debug('SNMPv3 GET %s %s failed (%s)', ip, oid, type(e).__name__)
        else:
            logger.debug(f"SNMP GET {ip} {oid} failed: {e}")
      return None


async def _snmp_get_v3(
    ip: str,
    username: str,
    oid: str,
    port: int = 161,
    timeout: float = 3,
    auth_password: str = '',
    auth_protocol: str = '',
    priv_password: str = '',
    priv_protocol: str = '',
    context_name: str = '',
    security_level: str = '',
) -> Optional[str]:
    """GET one OID using an explicitly configured SNMPv3 security profile."""
    async with get_network_access_limiter().async_snmp():
      try:
        from puresnmp import PyWrapper

        profile = {
            'username': username,
            'security_level': security_level or ('authPriv' if priv_protocol else 'authNoPriv' if auth_protocol else 'noAuthNoPriv'),
            'auth_password': auth_password,
            'auth_protocol': auth_protocol or 'SHA',
            'priv_password': priv_password,
            'priv_protocol': priv_protocol or 'AES',
            'context_name': context_name,
        }
        client = PyWrapper(_build_versioned_snmp_client(ip, profile, port, '3'))
        result = await asyncio.wait_for(client.get(oid), timeout=timeout)
        if result is None:
            return None
        value = _val_to_str(result)
        if value and 'noSuchObject' not in value and 'noSuchInstance' not in value:
            return value
      except Exception as exc:
        # Never include SNMPv3 secrets or library exception text in logs.
        logger.debug('SNMPv3 GET %s %s failed (%s)', ip, oid, type(exc).__name__)
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
    community: str | Mapping[str, Any],
    oid: str,
    port: int = 161,
    timeout: float = 5,
    max_rows: Optional[int] = 200,
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
    elif version_key in {'3', 'v3', 'snmpv3'}:
        version_key = '3'
    else:
        raise ValueError('Unsupported SNMP version; use 1, 2c, or 3')

    async def _collect():
        from puresnmp import PyWrapper
        client = PyWrapper(_build_versioned_snmp_client(ip, community, port, version_key))
        async for varbind in client.walk(base_oid):
            oid_str = str(varbind.oid)
            suffix = oid_str[len(base_oid) + 1:] if oid_str.startswith(base_oid + '.') else oid_str
            v = _val_to_str(varbind.value)
            if 'endOfMibView' in v:
                return
            results.append((suffix, v))
            if preserve_octets and isinstance(varbind.value, (bytes, bytearray)):
                results.octet_values[suffix] = bytes(varbind.value)
            if max_rows is not None and len(results) >= max_rows:
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
        if version_key == '3':
            logger.debug('SNMPv3 WALK %s %s failed (%s)', ip, oid, type(exc).__name__)
        else:
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
    community: str | Mapping[str, Any],
    oid: str,
    port: int,
    version: str,
) -> Optional[str]:
    """Call the scalar helper without changing the v2c monkeypatch contract."""
    if str(version or '2c').strip().lower() in {'v2c', '2c', '2', ''}:
        return await _snmp_get(ip, community, oid, port)
    if str(version or '').strip().lower() in {'3', 'v3', 'snmpv3'}:
        if not isinstance(community, Mapping):
            return None
        return await _snmp_get_v3(
            ip,
            str(community.get('username') or ''),
            oid,
            port,
            auth_password=str(community.get('auth_password') or ''),
            auth_protocol=str(community.get('auth_protocol') or ''),
            priv_password=str(community.get('priv_password') or ''),
            priv_protocol=str(community.get('priv_protocol') or ''),
            context_name=str(community.get('context_name') or ''),
            security_level=str(community.get('security_level') or ''),
        )
    return await _snmp_get(ip, community, oid, port, version=version)


async def _snmp_get_many_versioned(
    ip: str,
    community: str | Mapping[str, Any],
    oids: list[str],
    port: int,
    version: str,
) -> dict[str, Optional[str]]:
    """Read known instances in bounded GET batches, without walking columns.

    SNMPv1 rejects an entire request containing one unavailable instance.
    Split only protocol size/missing-instance errors so healthy instances are
    retained, while timeouts and authentication failures never fan out into
    one request per sensor.
    """
    from puresnmp import PyWrapper
    from puresnmp.exc import NoSuchOID, TooBig

    requested = list(dict.fromkeys(str(oid).strip('.') for oid in oids))
    if any(not re.fullmatch(r'\d+(?:\.\d+)+', oid) for oid in requested):
        raise ValueError('SNMP GET instances must be numeric OIDs')
    results: dict[str, Optional[str]] = {oid: None for oid in requested}
    semaphore = asyncio.Semaphore(4)

    async def read_batch(batch: list[str]) -> None:
        split = False
        async with semaphore:
            async with get_network_access_limiter().async_snmp():
                try:
                    client = PyWrapper(_build_versioned_snmp_client(ip, community, port, version))
                    values = await asyncio.wait_for(client.multiget(batch), timeout=3)
                    if len(values) != len(batch):
                        raise ValueError('Unexpected SNMP GET response length')
                    for oid, value in zip(batch, values):
                        if value is None:
                            continue
                        text = _val_to_str(value)
                        if not any(token in text.casefold() for token in ('nosuchobject', 'nosuchinstance', 'endofmibview')):
                            results[oid] = text
                except (NoSuchOID, TooBig):
                    split = len(batch) > 1
                except Exception as exc:
                    logger.debug('SNMP batch GET %s failed (%s)', ip, type(exc).__name__)
        if split:
            middle = len(batch) // 2
            await read_batch(batch[:middle])
            await read_batch(batch[middle:])

    await asyncio.gather(*(read_batch(requested[start:start + 20]) for start in range(0, len(requested), 20)))
    return results


async def _snmp_walk_versioned(
    ip: str,
    community: str | Mapping[str, Any],
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
    community: str | Mapping[str, Any],
    oid: str,
    port: int = 161,
    timeout: float = 3,
    version: str = '2c',
) -> Optional[SnmpTypedValue]:
    """GET one OID while preserving its puresnmp ASN.1 type."""
    async with get_network_access_limiter().async_snmp():
        try:
            version_key = str(version or '2c').strip().lower()
            from puresnmp import ObjectIdentifier

            client = _build_versioned_snmp_client(ip, community, port, version_key)
            result = await asyncio.wait_for(
                client.get(ObjectIdentifier(oid)),
                timeout=timeout,
            )
            typed = _typed_value_from_raw(result)
            if typed.number is not None:
                return typed
        except Exception as exc:
            if str(version or '').strip().casefold() in {'3', 'v3', 'snmpv3'}:
                logger.debug('Typed SNMPv3 GET %s %s failed (%s)', ip, oid, type(exc).__name__)
            else:
                logger.debug("Typed SNMP GET %s %s failed: %s", ip, oid, exc)
        return None


async def _snmp_walk_typed(
    ip: str,
    community: str | Mapping[str, Any],
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
        version_key = str(version or '2c').strip().lower()
        from puresnmp import ObjectIdentifier

        client = _build_versioned_snmp_client(ip, community, port, version_key)
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
            if str(version or '').strip().casefold() in {'3', 'v3', 'snmpv3'}:
                logger.debug('Typed SNMPv3 WALK %s %s failed (%s)', ip, oid, type(exc).__name__)
            else:
                logger.debug("Typed SNMP WALK %s %s failed: %s", ip, oid, exc)
    return results


async def _snmp_bulk_walk_typed(
    ip: str,
    community: str | Mapping[str, Any],
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
        version_key = str(version or '2c').strip().lower()
        from puresnmp import ObjectIdentifier

        client = _build_versioned_snmp_client(ip, community, port, version_key)
        walker = (
            client.walk(ObjectIdentifier(base_oid))
            if version_key in {'v1', '1'}
            else client.bulkwalk([ObjectIdentifier(base_oid)], bulk_size=max_repetitions)
        )
        async for varbind in walker:
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
            if str(version or '').strip().casefold() in {'3', 'v3', 'snmpv3'}:
                logger.debug('Typed SNMPv3 BULK_WALK %s %s failed (%s)', ip, oid, type(exc).__name__)
            else:
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
    community: str | Mapping[str, Any],
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
        from puresnmp import PyWrapper
        version_key = str(version or '2c').strip().lower()
        client = PyWrapper(_build_versioned_snmp_client(ip, community, port, version_key))
        # GETBULK significantly reduces UDP round-trips. SNMPv1 only supports
        # GETNEXT, so use the library's regular walk implementation there.
        walker = (
            client.walk(base_oid)
            if version_key in {'v1', '1'}
            else client.bulkwalk([base_oid], bulk_size=max_repetitions)
        )
        async for varbind in walker:
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
        if str(version or '').strip().casefold() in {'3', 'v3', 'snmpv3'}:
            logger.debug('SNMPv3 BULK_WALK %s %s failed (%s)', ip, oid, type(e).__name__)
        else:
            logger.debug(f"SNMP BULK_WALK {ip} {oid} failed: {e}")
    if not results:
        logger.debug(f"SNMP BULK_WALK returned no results for {ip} {oid}. Falling back to standard WALK.")
        results = await _snmp_walk(ip, community, oid, port, timeout=timeout, version=version)
    return results


async def _snmp_bulk_walk_complete(
    ip: str,
    community_or_profile: str | Mapping[str, Any],
    oid: str,
    port: int = 161,
    *,
    timeout: float = 30,
    max_repetitions: int = 20,
    version: str = '2c',
) -> list[tuple[str, Any]]:
    """Walk an entire subtree and propagate failures instead of returning partial rows.

    Unlike the general telemetry walkers, this helper is for replacing current
    inventory snapshots. A timeout or protocol error must not look like a
    successful, shorter table to the caller.
    """
    base_oid = oid.strip('.')
    if not base_oid:
        raise ValueError('SNMP walk OID is required')
    results: list[tuple[str, Any]] = []

    async def _collect() -> None:
        from puresnmp import ObjectIdentifier

        client = _build_versioned_snmp_client(ip, community_or_profile, port, version)
        version_key = str(version or '2c').strip().casefold()
        # SNMPv1 has no GETBULK PDU. Keep the same uncapped/full-walk contract
        # by using GETNEXT for v1 and GETBULK for v2c/v3.
        walker = (
            client.walk(ObjectIdentifier(base_oid))
            if version_key in {'v1', '1'}
            else client.bulkwalk(
                [ObjectIdentifier(base_oid)],
                bulk_size=max(1, int(max_repetitions)),
            )
        )
        async for varbind in walker:
            oid_str = str(varbind.oid).strip('.')
            if oid_str == base_oid or not oid_str.startswith(base_oid + '.'):
                # The walk has reached the next MIB subtree; all rows below
                # the requested OID have already been returned.
                break
            raw_value = varbind.value
            if 'endofmibview' in type(raw_value).__name__.casefold():
                break
            results.append((oid_str[len(base_oid) + 1:], getattr(raw_value, 'value', raw_value)))

    try:
        async with get_network_access_limiter().async_snmp():
            await asyncio.wait_for(_collect(), timeout=max(1.0, float(timeout)))
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f'SNMP walk timed out for OID {base_oid}') from exc
    except Exception as exc:
        raise RuntimeError(f'SNMP walk failed for OID {base_oid} ({type(exc).__name__})') from exc
    return results


def _snmp_text_value(value: Any) -> str:
    """Decode SNMP text/octet values without exposing binary bytes as replacement text."""
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytearray):
        value = bytes(value)
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace').strip('\r\n \x00')
    return str(value or '').strip()


def _snmp_integer_value(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed


def _interface_status_from_if_mib(value: Any) -> str:
    status = _snmp_integer_value(value)
    if status == 1:
        return 'up'
    if status in {2, 7}:
        return 'down'
    return 'unknown'


async def collect_interface_status_data(
    ip: str,
    community: str | Mapping[str, Any] = 'public',
    port: int = 161,
    *,
    version: str = '2c',
    timeout: float = 30,
) -> list[dict[str, Any]]:
    """Read IF-MIB identity, status, speed, alias, physical address, and MTU.

    This intentionally avoids counters: telemetry sampling owns traffic and
    error counters, while this collector maintains the CMDB projection. Every
    required table walk is complete before any returned rows are used.
    """
    try:
        name_rows = await _snmp_bulk_walk_complete(
            ip, community, IF_NAME, port, timeout=timeout, version=version,
        )
    except Exception:
        name_rows = []
    if not name_rows:
        name_rows = await _snmp_bulk_walk_complete(
            ip, community, IF_DESCR, port, timeout=timeout, version=version,
        )
    if not name_rows:
        raise RuntimeError('IF-MIB returned no interface names')

    interface_names: dict[str, str] = {}
    for suffix, raw_name in name_rows:
        try:
            if_index = int(suffix)
        except (TypeError, ValueError, OverflowError):
            continue
        name = _snmp_text_value(raw_name)
        if if_index > 0 and name:
            interface_names[str(if_index)] = name
    if not interface_names:
        raise RuntimeError('IF-MIB returned no usable interface names')

    admin_rows, oper_rows = await asyncio.gather(
        _snmp_bulk_walk_complete(
            ip, community, IF_ADMIN_STATUS, port, timeout=timeout, version=version,
        ),
        _snmp_bulk_walk_complete(
            ip, community, IF_OPER_STATUS, port, timeout=timeout, version=version,
        ),
    )
    admin_by_index = {str(index): value for index, value in admin_rows}
    oper_by_index = {str(index): value for index, value in oper_rows}
    if not admin_by_index or not oper_by_index:
        raise RuntimeError('IF-MIB status tables returned no rows')
    if set(admin_by_index) != set(oper_by_index):
        raise RuntimeError('IF-MIB admin and operational status tables do not match')

    missing_names = set(admin_by_index) - set(interface_names)
    if missing_names:
        descr_rows = await _snmp_bulk_walk_complete(
            ip, community, IF_DESCR, port, timeout=timeout, version=version,
        )
        for suffix, raw_name in descr_rows:
            if str(suffix) in missing_names:
                name = _snmp_text_value(raw_name)
                if name:
                    interface_names[str(suffix)] = name
    if set(admin_by_index) - set(interface_names):
        raise RuntimeError('IF-MIB names did not cover the complete status table')

    missing_status = set(interface_names) - set(admin_by_index)
    if missing_status:
        raise RuntimeError('IF-MIB status tables did not cover the complete interface index')

    optional_results = await asyncio.gather(
        _snmp_bulk_walk_complete(
            ip, community, IF_HIGH_SPEED, port, timeout=timeout, version=version,
        ),
        _snmp_bulk_walk_complete(
            ip, community, IF_SPEED, port, timeout=timeout, version=version,
        ),
        _snmp_bulk_walk_complete(
            ip, community, IF_ALIAS, port, timeout=timeout, version=version,
        ),
        _snmp_bulk_walk_complete(
            ip, community, IF_PHYS_ADDRESS, port, timeout=timeout, version=version,
        ),
        _snmp_bulk_walk_complete(
            ip, community, IF_MTU, port, timeout=timeout, version=version,
        ),
        return_exceptions=True,
    )
    high_speed_rows, speed_rows, alias_rows, phys_address_rows, mtu_rows = [
        result if isinstance(result, list) else [] for result in optional_results
    ]
    high_speed_by_index = dict(high_speed_rows)
    speed_by_index = dict(speed_rows)
    alias_by_index = dict(alias_rows)
    phys_address_by_index = dict(phys_address_rows)
    mtu_by_index = dict(mtu_rows)
    interface_index_set = {int(index) for index in interface_names}
    alias_table_available = (
        isinstance(optional_results[2], list)
        and interface_index_set <= {int(index) for index in alias_by_index if str(index).isdigit()}
    )
    phys_address_complete = (
        isinstance(optional_results[3], list)
        and interface_index_set <= {int(index) for index in phys_address_by_index if str(index).isdigit()}
    )
    mtu_complete = (
        isinstance(optional_results[4], list)
        and interface_index_set <= {int(index) for index in mtu_by_index if str(index).isdigit()}
    )

    interfaces: list[dict[str, Any]] = []
    for if_index, name in interface_names.items():
        high_speed = _snmp_integer_value(high_speed_by_index.get(if_index))
        speed_bps = _snmp_integer_value(speed_by_index.get(if_index))
        speed_mbps = float(high_speed) if high_speed and high_speed > 0 else (
            float(speed_bps) / 1_000_000 if speed_bps and speed_bps > 0 else 0.0
        )
        raw_phys_address = phys_address_by_index.get(if_index)
        if isinstance(raw_phys_address, memoryview):
            raw_phys_address = raw_phys_address.tobytes()
        elif isinstance(raw_phys_address, bytearray):
            raw_phys_address = bytes(raw_phys_address)
        if isinstance(raw_phys_address, bytes):
            mac_address = ':'.join(f'{octet:02x}' for octet in raw_phys_address) if raw_phys_address else ''
        else:
            mac_address = _snmp_text_value(raw_phys_address)
        interfaces.append({
            'name': name,
            'if_index': int(if_index),
            'status': _interface_status_from_if_mib(oper_by_index[if_index]),
            'admin_status': _interface_status_from_if_mib(admin_by_index[if_index]),
            'speed_mbps': speed_mbps,
            'description': _snmp_text_value(alias_by_index.get(if_index)),
            'description_available': alias_table_available,
            'mac_address': mac_address,
            'mac_address_available': phys_address_complete,
            'mtu': _snmp_integer_value(mtu_by_index.get(if_index)),
            'mtu_available': mtu_complete,
        })
    return interfaces


def _parse_ip_mib_address_index(suffix: Any) -> tuple[int, str]:
    """Decode the RFC 4001 InetAddressType/length/octet table index."""
    import ipaddress

    try:
        parts = [int(part) for part in str(suffix).strip('.').split('.')]
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError('IP-MIB address table has a non-numeric index') from exc
    if len(parts) < 3:
        raise RuntimeError('IP-MIB address table index is incomplete')
    address_type, address_length = parts[:2]
    octets = parts[2:]
    if address_length != len(octets) or any(octet < 0 or octet > 255 for octet in octets):
        raise RuntimeError('IP-MIB address table index has an invalid InetAddress length')
    if address_type == 1 and address_length == 4:
        return address_type, str(ipaddress.IPv4Address(bytes(octets)))
    if address_type == 2 and address_length == 16:
        return address_type, str(ipaddress.IPv6Address(bytes(octets)))
    # The interface/IPAM schema has no IPv6 zone identifier.  Reject zoned
    # and non-IP InetAddress forms so they take the targeted CLI fallback
    # instead of being silently flattened or written under an ambiguous IP.
    raise RuntimeError('IP-MIB address uses an address form unsupported by the interface inventory')


def _ip_mib_prefix_length(
    raw_pointer: Any,
    if_index: int,
    address_type: int,
    address: str,
) -> int | None:
    """Resolve ipAddressPrefix's RowPointer to its indexed prefix length."""
    import ipaddress

    pointer = _snmp_text_value(raw_pointer).strip().strip('.')
    if pointer in {'', '0.0', '0.0.0.0'}:
        return None
    try:
        parts = [int(part) for part in pointer.split('.')]
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError('IP-MIB address has an invalid prefix RowPointer') from exc
    root = [int(part) for part in IP_ADDRESS_PREFIX_ENTRY.split('.')]
    if parts[:len(root)] != root:
        raise RuntimeError('IP-MIB address prefix pointer does not reference ipAddressPrefixTable')
    suffix = parts[len(root):]
    if len(suffix) < 7:
        raise RuntimeError('IP-MIB address prefix pointer has an incomplete row index')
    prefix_if_index, prefix_type, prefix_octet_count = suffix[:3]
    prefix_octets = suffix[3:-1]
    prefix_length = suffix[-1]
    expected_octet_count = 4 if address_type == 1 else 16
    if (
        prefix_if_index != if_index
        or prefix_type != address_type
        or prefix_octet_count != expected_octet_count
        or len(prefix_octets) != expected_octet_count
        or any(octet < 0 or octet > 255 for octet in prefix_octets)
        or not 0 <= prefix_length <= expected_octet_count * 8
    ):
        raise RuntimeError('IP-MIB address prefix pointer does not match its interface/address family')
    prefix_address = ipaddress.ip_address(bytes(prefix_octets))
    network = ipaddress.ip_network(f'{prefix_address}/{prefix_length}', strict=False)
    if ipaddress.ip_address(address) not in network:
        raise RuntimeError('IP-MIB address is outside the prefix referenced by its row')
    return prefix_length


async def collect_interface_ip_addresses(
    ip: str,
    community_or_profile: str | Mapping[str, Any],
    interface_names_by_index: Mapping[int, str] | None = None,
    port: int = 161,
    *,
    version: str = '2c',
    timeout: float = 30,
) -> list[dict[str, Any]]:
    """Collect IP-MIB IPv4/IPv6 assignments and join them through ifIndex.

    This collector intentionally treats an empty/unsupported table as an
    incomplete domain.  The caller can then run the existing interface IP
    CLI fallback without clearing the previous address snapshot.
    """
    columns = await _snmp_walk_columns_complete(
        ip,
        community_or_profile,
        {
            'if_index': IP_ADDRESS_IF_INDEX,
            'address_type': IP_ADDRESS_TYPE,
            'prefix': IP_ADDRESS_PREFIX,
            'status': IP_ADDRESS_STATUS,
        },
        port,
        version=version,
        timeout=timeout,
    )
    status_names = {1: 'preferred', 2: 'deprecated', 3: 'invalid', 4: 'inaccessible', 5: 'unknown', 6: 'tentative', 7: 'duplicate'}
    names_by_index = {int(index): str(name) for index, name in (interface_names_by_index or {}).items()}
    required_if_indexes = {
        parsed_if_index
        for suffix in columns['if_index']
        for parsed_if_index in [_snmp_integer_value(columns['if_index'][suffix])]
        if parsed_if_index is not None and parsed_if_index > 0
    }
    missing_if_indexes = required_if_indexes - set(names_by_index)
    if missing_if_indexes:
        names_by_index.update(await _snmp_map_if_indexes(
            ip, community_or_profile, missing_if_indexes, port,
            version=version, timeout=timeout,
        ))

    records: list[dict[str, Any]] = []
    for suffix in sorted(columns['if_index']):
        address_type, address = _parse_ip_mib_address_index(suffix)
        if_index = _snmp_integer_value(columns['if_index'][suffix])
        mib_address_type = _snmp_integer_value(columns['address_type'][suffix])
        status = _snmp_integer_value(columns['status'][suffix])
        if if_index is None or if_index <= 0 or mib_address_type not in {1, 2, 3}:
            raise RuntimeError('IP-MIB address row has an invalid interface or address type')
        if if_index not in names_by_index:
            raise RuntimeError('IP-MIB address row references an ifIndex absent from IF-MIB')
        if status not in status_names:
            raise RuntimeError('IP-MIB address row has an unknown address status')
        if status not in {1, 2, 5}:
            # Invalid, inaccessible, tentative, and duplicate addresses are
            # not current usable interface assignments.
            continue
        records.append({
            'if_index': if_index,
            'interface': names_by_index[if_index],
            'ip_address': address,
            'ip_version': address_type,
            'prefix_length': _ip_mib_prefix_length(
                columns['prefix'][suffix], if_index, address_type, address,
            ),
            'address_status': status_names[status],
            'address_type': mib_address_type,
        })
    if not records:
        raise RuntimeError('IP-MIB address table returned no usable IPv4/IPv6 assignments')
    records.sort(key=lambda item: (
        item['interface'].casefold(), item['ip_version'], item['ip_address'],
    ))
    return records


def _snmp_port_list(value: Any) -> set[int]:
    if isinstance(value, memoryview):
        value = value.tobytes()
    elif isinstance(value, bytearray):
        value = bytes(value)
    if isinstance(value, bytes):
        octets = value
    elif not _snmp_text_value(value):
        octets = b''
    else:
        octets = _snmp_octets_value(value, 'Q-BRIDGE port list')
    ports: set[int] = set()
    for byte_index, octet in enumerate(octets):
        for bit_index in range(8):
            if octet & (1 << (7 - bit_index)):
                ports.add(byte_index * 8 + bit_index + 1)
    return ports


async def collect_qbridge_interface_vlan_data(
    ip: str,
    community_or_profile: str | Mapping[str, Any],
    interface_names_by_index: Mapping[int, str] | None = None,
    port: int = 161,
    *,
    version: str = '2c',
    timeout: float = 30,
) -> dict[str, list[dict[str, Any]]]:
    """Collect complete Q-BRIDGE VLAN memberships, PVIDs, and port mappings.

    Egress/untagged PortLists are mapped through dot1dBasePortIfIndex, then
    joined to IF-MIB names. PVID is preserved as raw evidence; callers must
    combine it with complete membership before inferring access/trunk mode.
    """
    egress_rows, untagged_rows, pvid_rows, bridge_if_rows = await asyncio.gather(
        _snmp_bulk_walk_complete(
            ip, community_or_profile, DOT1Q_VLAN_CURRENT_EGRESS_PORTS, port,
            timeout=timeout, version=version,
        ),
        _snmp_bulk_walk_complete(
            ip, community_or_profile, DOT1Q_VLAN_CURRENT_UNTAGGED_PORTS, port,
            timeout=timeout, version=version,
        ),
        _snmp_bulk_walk_complete(
            ip, community_or_profile, DOT1Q_PORT_PVID, port,
            timeout=timeout, version=version,
        ),
        _snmp_bulk_walk_complete(
            ip, community_or_profile, DOT1D_BASE_PORT_IF_INDEX, port,
            timeout=timeout, version=version,
        ),
    )
    if not egress_rows or not untagged_rows or not pvid_rows or not bridge_if_rows:
        raise RuntimeError('Q-BRIDGE VLAN membership or port mapping table returned no rows')

    def _indexed_values(rows: list[tuple[str, Any]], label: str) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for suffix, value in rows:
            normalized = str(suffix).strip('.')
            if not normalized or normalized in values:
                raise RuntimeError(f'Q-BRIDGE {label} table has an invalid or duplicate row index')
            values[normalized] = value
        return values

    egress_by_suffix = _indexed_values(egress_rows, 'egress-port')
    untagged_by_suffix = _indexed_values(untagged_rows, 'untagged-port')
    if set(egress_by_suffix) != set(untagged_by_suffix):
        raise RuntimeError('Q-BRIDGE egress and untagged VLAN tables do not match')

    bridge_port_to_if_index: dict[int, int] = {}
    if_index_to_bridge_port: dict[int, int] = {}
    for suffix, raw_if_index in bridge_if_rows:
        try:
            bridge_port = int(str(suffix).strip('.'))
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError('Q-BRIDGE bridge-port mapping has an invalid port index') from exc
        if_index = _snmp_integer_value(raw_if_index)
        if bridge_port <= 0 or if_index is None or if_index <= 0:
            raise RuntimeError('Q-BRIDGE bridge-port mapping has an invalid ifIndex')
        if bridge_port in bridge_port_to_if_index or if_index in if_index_to_bridge_port:
            raise RuntimeError('Q-BRIDGE bridge-port mapping is not one-to-one')
        bridge_port_to_if_index[bridge_port] = if_index
        if_index_to_bridge_port[if_index] = bridge_port

    pvid_by_bridge_port: dict[int, int] = {}
    for suffix, raw_pvid in pvid_rows:
        try:
            bridge_port = int(str(suffix).strip('.'))
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError('Q-BRIDGE PVID table has an invalid bridge-port index') from exc
        pvid = _snmp_integer_value(raw_pvid)
        if bridge_port <= 0 or pvid is None or not 1 <= pvid <= 4094:
            raise RuntimeError('Q-BRIDGE PVID table has an invalid port or VLAN identifier')
        if bridge_port in pvid_by_bridge_port:
            raise RuntimeError('Q-BRIDGE PVID table contains a duplicate bridge port')
        pvid_by_bridge_port[bridge_port] = pvid
    if set(pvid_by_bridge_port) != set(bridge_port_to_if_index):
        raise RuntimeError('Q-BRIDGE PVID and bridge-port mapping tables do not match')

    required_if_indexes = set(bridge_port_to_if_index.values())
    names_by_index = dict(interface_names_by_index or {})
    missing_if_indexes = required_if_indexes - set(names_by_index)
    if missing_if_indexes:
        resolved_names = await _snmp_map_if_indexes(
            ip, community_or_profile, missing_if_indexes, port,
            version=version, timeout=timeout,
        )
        names_by_index.update(resolved_names)
    if required_if_indexes - set(names_by_index):
        raise RuntimeError('Q-BRIDGE bridge ports did not map to complete IF-MIB names')

    vlan_members: dict[int, dict[str, set[int]]] = {}
    for suffix, raw_egress in egress_by_suffix.items():
        parts = suffix.split('.')
        if len(parts) != 2:
            raise RuntimeError('Q-BRIDGE current VLAN index must contain TimeMark and VLAN ID')
        try:
            time_mark, vlan_id = (int(part) for part in parts)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError('Q-BRIDGE current VLAN index contains non-numeric values') from exc
        if time_mark < 0 or not 1 <= vlan_id <= 4094 or vlan_id in vlan_members:
            raise RuntimeError('Q-BRIDGE current VLAN index is invalid or duplicated')
        egress_ports = _snmp_port_list(raw_egress)
        untagged_ports = _snmp_port_list(untagged_by_suffix[suffix])
        if not untagged_ports <= egress_ports:
            raise RuntimeError('Q-BRIDGE untagged membership is not a subset of VLAN egress membership')
        if (egress_ports | untagged_ports) - set(bridge_port_to_if_index):
            raise RuntimeError('Q-BRIDGE VLAN PortList references an unmapped bridge port')
        vlan_members[vlan_id] = {
            'egress': egress_ports,
            'untagged': untagged_ports,
        }

    if not vlan_members:
        raise RuntimeError('Q-BRIDGE current VLAN table returned no VLANs')

    try:
        name_rows = await _snmp_bulk_walk_complete(
            ip, community_or_profile, DOT1Q_VLAN_STATIC_NAME, port,
            timeout=timeout, version=version,
        )
    except Exception:
        # VLAN names are descriptive. Complete membership/PVID facts remain
        # usable when a device omits the optional static-name table.
        name_rows = []
    names_by_vlan: dict[int, str] = {}
    for suffix, raw_name in name_rows:
        try:
            vlan_id = int(str(suffix).strip('.'))
        except (TypeError, ValueError, OverflowError):
            continue
        name = _snmp_text_value(raw_name)
        if 1 <= vlan_id <= 4094 and name:
            names_by_vlan[vlan_id] = name

    tagged_by_if_index: dict[int, set[int]] = {}
    untagged_by_if_index: dict[int, set[int]] = {}
    vlan_records: list[dict[str, Any]] = []
    for vlan_id, membership in sorted(vlan_members.items()):
        tagged_if_indexes = sorted(
            bridge_port_to_if_index[bridge_port]
            for bridge_port in membership['egress'] - membership['untagged']
        )
        untagged_if_indexes = sorted(
            bridge_port_to_if_index[bridge_port]
            for bridge_port in membership['untagged']
        )
        for if_index in tagged_if_indexes:
            tagged_by_if_index.setdefault(if_index, set()).add(vlan_id)
        for if_index in untagged_if_indexes:
            untagged_by_if_index.setdefault(if_index, set()).add(vlan_id)
        vlan_records.append({
            'vlan_id': vlan_id,
            'vlan_name': names_by_vlan.get(vlan_id) or f'VLAN {vlan_id}',
            'tagged_interfaces': [str(names_by_index[index]) for index in tagged_if_indexes],
            'untagged_interfaces': [str(names_by_index[index]) for index in untagged_if_indexes],
        })

    interface_records: list[dict[str, Any]] = []
    for bridge_port, if_index in sorted(bridge_port_to_if_index.items()):
        interface_records.append({
            'bridge_port': bridge_port,
            'if_index': if_index,
            'interface': str(names_by_index[if_index]),
            'pvid': pvid_by_bridge_port[bridge_port],
            'tagged_vlans': sorted(tagged_by_if_index.get(if_index, set())),
            'untagged_vlans': sorted(untagged_by_if_index.get(if_index, set())),
        })
    return {'vlans': vlan_records, 'interfaces': interface_records}


async def collect_arp_table(
    ip: str,
    community: str | Mapping[str, Any] = 'public',
    port: int = 161,
    *,
    version: str = '2c',
    timeout: float = 120,
) -> list[dict[str, Any]]:
    """Collect a complete IPv4 IP-MIB ARP table and map ifIndex to IF-MIB names."""
    phys_rows, type_rows = await asyncio.gather(
        _snmp_bulk_walk_complete(
            ip, community, IP_NET_TO_MEDIA_PHYS_ADDRESS, port,
            timeout=timeout, version=version,
        ),
        _snmp_bulk_walk_complete(
            ip, community, IP_NET_TO_MEDIA_TYPE, port,
            timeout=timeout, version=version,
        ),
    )
    if not phys_rows and not type_rows:
        raise RuntimeError('IP-MIB ARP table returned no rows')

    type_by_index: dict[str, int] = {}
    for suffix, raw_type in type_rows:
        parsed_type = _snmp_integer_value(raw_type)
        if parsed_type is not None:
            type_by_index[suffix] = parsed_type

    if_name_rows: list[tuple[str, Any]] = []
    try:
        if_name_rows = await _snmp_bulk_walk_complete(
            ip, community, IF_NAME, port, timeout=timeout, version=version,
        )
    except Exception:
        if_name_rows = []
    if not if_name_rows:
        try:
            if_name_rows = await _snmp_bulk_walk_complete(
                ip, community, IF_DESCR, port, timeout=timeout, version=version,
            )
        except Exception:
            if_name_rows = []
    interface_by_index = {
        str(suffix): _snmp_text_value(raw_name)
        for suffix, raw_name in if_name_rows
        if str(suffix).isdigit() and _snmp_text_value(raw_name)
    }

    entries: list[dict[str, Any]] = []
    phys_suffixes = {suffix for suffix, _ in phys_rows}
    if phys_suffixes - set(type_by_index):
        raise RuntimeError('IP-MIB ARP type table did not cover the complete MAC table')

    for suffix, raw_mac in phys_rows:
        parts = str(suffix).split('.')
        if len(parts) != 5:
            raise RuntimeError('IP-MIB ARP row has an invalid IPv4 index')
        if_index, *address_octets = parts
        if not if_index.isdigit() or any(not octet.isdigit() for octet in address_octets):
            raise RuntimeError('IP-MIB ARP row has an invalid interface/address index')
        try:
            import ipaddress
            ip_address = str(ipaddress.IPv4Address(bytes(int(octet) for octet in address_octets)))
        except ValueError as exc:
            raise RuntimeError('IP-MIB ARP row has an invalid IPv4 address') from exc

        entry_type = type_by_index.get(str(suffix))
        # RFC 1213 defines invalid(2); omit invalidated entries but retain
        # valid static and dynamic mappings (and implementation-specific other).
        if entry_type == 2:
            continue

        if isinstance(raw_mac, memoryview):
            raw_mac = raw_mac.tobytes()
        elif isinstance(raw_mac, bytearray):
            raw_mac = bytes(raw_mac)
        if isinstance(raw_mac, bytes):
            mac = ':'.join(f'{octet:02x}' for octet in raw_mac)
        else:
            mac = _snmp_text_value(raw_mac)
        if not mac:
            raise RuntimeError('IP-MIB ARP row has no physical address')

        interface_name = interface_by_index.get(if_index, '')
        if not interface_name:
            raise RuntimeError('IF-MIB did not map an ARP row to an interface name')

        type_label = {3: 'dynamic', 4: 'static', 1: 'other'}.get(entry_type, str(entry_type))
        entries.append({
            'ip_address': ip_address,
            'mac_address': mac,
            'interface': interface_name,
            'type': type_label,
        })
    if not entries:
        raise RuntimeError('IP-MIB ARP table had no usable IPv4 mappings')
    return entries


async def collect_bridge_mac_table(
    ip: str,
    community_or_profile: str | Mapping[str, Any],
    port: int = 161,
    *,
    version: str = '2c',
    timeout: float = 120,
) -> list[dict[str, Any]]:
    """Collect a complete Q-BRIDGE-MIB unicast FDB and resolve its VLANs/ports.

    All walks use the uncapped full-walk helper.  Any missing table, malformed
    index, stale-but-invalid entry, or unresolved bridge/IF-MIB mapping makes
    this snapshot unsuitable for replacement and is reported to the caller as
    an exception so it can use its configured fallback.
    """
    fdb_port_rows, fdb_status_rows, vlan_fdb_rows, bridge_if_rows = await asyncio.gather(
        _snmp_bulk_walk_complete(
            ip, community_or_profile, DOT1Q_TP_FDB_PORT, port,
            timeout=timeout, version=version,
        ),
        _snmp_bulk_walk_complete(
            ip, community_or_profile, DOT1Q_TP_FDB_STATUS, port,
            timeout=timeout, version=version,
        ),
        _snmp_bulk_walk_complete(
            ip, community_or_profile, DOT1Q_VLAN_FDB_ID, port,
            timeout=timeout, version=version,
        ),
        _snmp_bulk_walk_complete(
            ip, community_or_profile, DOT1D_BASE_PORT_IF_INDEX, port,
            timeout=timeout, version=version,
        ),
    )
    if not fdb_port_rows or not fdb_status_rows:
        raise RuntimeError('Q-BRIDGE-MIB FDB table returned no rows')
    if not vlan_fdb_rows:
        raise RuntimeError('Q-BRIDGE-MIB VLAN-to-FDB table returned no rows')
    if not bridge_if_rows:
        raise RuntimeError('BRIDGE-MIB bridge-port map returned no rows')

    vlan_ids_by_fdb: dict[int, set[int]] = {}
    fdb_by_vlan: dict[int, int] = {}
    for suffix, raw_fdb_id in vlan_fdb_rows:
        parts = str(suffix).strip('.').split('.')
        if len(parts) != 2:
            raise RuntimeError('Q-BRIDGE-MIB VLAN-to-FDB row has an invalid index')
        try:
            time_mark, vlan_id = (int(part) for part in parts)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError('Q-BRIDGE-MIB VLAN-to-FDB row has a non-numeric index') from exc
        fdb_id = _snmp_integer_value(raw_fdb_id)
        if time_mark < 0 or vlan_id <= 0 or vlan_id == 4095 or fdb_id is None or fdb_id < 0:
            raise RuntimeError('Q-BRIDGE-MIB VLAN-to-FDB row has an invalid VLAN/FDB identifier')
        existing_fdb_id = fdb_by_vlan.get(vlan_id)
        if existing_fdb_id is not None and existing_fdb_id != fdb_id:
            raise RuntimeError('Q-BRIDGE-MIB VLAN maps to conflicting FDB identifiers')
        fdb_by_vlan[vlan_id] = fdb_id
        vlan_ids_by_fdb.setdefault(fdb_id, set()).add(vlan_id)

    bridge_port_to_if_index: dict[int, int] = {}
    for suffix, raw_if_index in bridge_if_rows:
        try:
            bridge_port = int(str(suffix).strip('.'))
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError('BRIDGE-MIB bridge-port row has an invalid index') from exc
        if_index = _snmp_integer_value(raw_if_index)
        if bridge_port <= 0 or if_index is None or if_index <= 0:
            raise RuntimeError('BRIDGE-MIB bridge-port row has an invalid ifIndex mapping')
        previous_if_index = bridge_port_to_if_index.get(bridge_port)
        if previous_if_index is not None and previous_if_index != if_index:
            raise RuntimeError('BRIDGE-MIB bridge port maps to conflicting ifIndex values')
        bridge_port_to_if_index[bridge_port] = if_index

    required_if_indexes = set(bridge_port_to_if_index.values())
    if_name_rows: list[tuple[str, Any]] = []
    try:
        if_name_rows = await _snmp_bulk_walk_complete(
            ip, community_or_profile, IF_NAME, port,
            timeout=timeout, version=version,
        )
    except Exception:
        # IF-MIB::ifDescr is the standard fallback for agents without ifName.
        if_name_rows = []
    if_name_by_index: dict[int, str] = {}
    for suffix, raw_name in if_name_rows:
        try:
            if_index = int(str(suffix).strip('.'))
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError('IF-MIB ifName row has an invalid index') from exc
        name = _snmp_text_value(raw_name)
        if if_index <= 0:
            raise RuntimeError('IF-MIB ifName row has an invalid interface index')
        if name:
            if_name_by_index[if_index] = name

    missing_if_indexes = required_if_indexes - set(if_name_by_index)
    if missing_if_indexes:
        try:
            if_descr_rows = await _snmp_bulk_walk_complete(
                ip, community_or_profile, IF_DESCR, port,
                timeout=timeout, version=version,
            )
        except Exception as exc:
            raise RuntimeError('IF-MIB could not resolve every bridge port to an interface name') from exc
        for suffix, raw_name in if_descr_rows:
            try:
                if_index = int(str(suffix).strip('.'))
            except (TypeError, ValueError, OverflowError) as exc:
                raise RuntimeError('IF-MIB ifDescr row has an invalid index') from exc
            name = _snmp_text_value(raw_name)
            if if_index <= 0:
                raise RuntimeError('IF-MIB ifDescr row has an invalid interface index')
            if name:
                if_name_by_index.setdefault(if_index, name)
    if required_if_indexes - set(if_name_by_index):
        raise RuntimeError('IF-MIB did not map every bridge port to an interface name')

    fdb_port_by_suffix: dict[str, int] = {}
    fdb_status_by_suffix: dict[str, int] = {}
    for suffix, raw_value in fdb_port_rows:
        normalized_suffix = str(suffix).strip('.')
        if normalized_suffix in fdb_port_by_suffix:
            raise RuntimeError('Q-BRIDGE-MIB FDB port table contains a duplicate row')
        bridge_port = _snmp_integer_value(raw_value)
        if bridge_port is None or bridge_port < 0:
            raise RuntimeError('Q-BRIDGE-MIB FDB row has an invalid bridge-port value')
        fdb_port_by_suffix[normalized_suffix] = bridge_port

    status_codes = {'other': 1, 'invalid': 2, 'learned': 3, 'self': 4, 'mgmt': 5}
    for suffix, raw_value in fdb_status_rows:
        normalized_suffix = str(suffix).strip('.')
        if normalized_suffix in fdb_status_by_suffix:
            raise RuntimeError('Q-BRIDGE-MIB FDB status table contains a duplicate row')
        status_code = _snmp_integer_value(raw_value)
        if status_code is None:
            status_text = _snmp_text_value(raw_value).strip().casefold()
            status_code = status_codes.get(status_text)
            if status_code is None:
                match = re.search(r'\((\d+)\)\s*$', status_text)
                status_code = int(match.group(1)) if match else None
        if status_code not in status_codes.values():
            raise RuntimeError('Q-BRIDGE-MIB FDB row has an unknown status')
        fdb_status_by_suffix[normalized_suffix] = status_code

    if set(fdb_port_by_suffix) != set(fdb_status_by_suffix):
        raise RuntimeError('Q-BRIDGE-MIB FDB port and status tables do not match')

    status_to_type = {1: 'other', 3: 'dynamic', 4: 'self', 5: 'static'}
    records: list[dict[str, Any]] = []
    for suffix, bridge_port in fdb_port_by_suffix.items():
        status_code = fdb_status_by_suffix[suffix]
        # invalid(2) rows have already aged out and are not current FDB facts.
        if status_code == 2:
            continue

        parts = suffix.split('.')
        if len(parts) != 7:
            raise RuntimeError('Q-BRIDGE-MIB FDB row has an invalid FDB/MAC index')
        try:
            fdb_id = int(parts[0])
            mac_octets = [int(part) for part in parts[1:]]
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError('Q-BRIDGE-MIB FDB row has a non-numeric FDB/MAC index') from exc
        if fdb_id < 0 or any(octet < 0 or octet > 255 for octet in mac_octets):
            raise RuntimeError('Q-BRIDGE-MIB FDB row has an invalid FDB/MAC index')
        vlan_ids = vlan_ids_by_fdb.get(fdb_id)
        if not vlan_ids:
            raise RuntimeError('Q-BRIDGE-MIB FDB row has no matching VLAN-to-FDB mapping')
        if bridge_port <= 0:
            raise RuntimeError('Q-BRIDGE-MIB FDB row does not identify a bridge port')
        if_index = bridge_port_to_if_index.get(bridge_port)
        if if_index is None:
            raise RuntimeError('BRIDGE-MIB did not map an FDB bridge port to ifIndex')
        interface_name = if_name_by_index.get(if_index)
        if not interface_name:
            raise RuntimeError('IF-MIB did not map an FDB ifIndex to an interface name')

        mac = ':'.join(f'{octet:02x}' for octet in mac_octets)
        entry_type = status_to_type.get(status_code)
        if not entry_type:
            raise RuntimeError('Q-BRIDGE-MIB FDB row has an unsupported status')
        for vlan_id in sorted(vlan_ids):
            records.append({
                'mac': mac,
                'vlan': vlan_id,
                'port': interface_name,
                'if_index': if_index,
                'type': entry_type,
            })

    if not records:
        raise RuntimeError('Q-BRIDGE-MIB FDB table had no usable MAC mappings')
    records.sort(key=lambda item: (item['vlan'], item['mac'], item['if_index']))
    return records


async def collect_ip_forward_table(
    ip: str,
    community_or_profile: str | Mapping[str, Any],
    port: int = 161,
    *,
    version: str = '2c',
    timeout: float = 120,
) -> list[dict[str, Any]]:
    """Collect a complete IPv4/IPv6 IP-FORWARD-MIB inetCidrRouteTable.

    Each accessible column is walked in full and must contain exactly the same
    route indexes.  Index decoding follows the InetAddress/OBJECT IDENTIFIER
    length-prefixed SNMP index encoding.  Any unsupported or incomplete walk,
    malformed index/value, or unresolved non-zero ifIndex raises so callers
    can preserve their CLI fallback path.
    """
    import ipaddress

    metric_oids = {
        'metric1': INET_CIDR_ROUTE_METRIC1,
        'metric2': INET_CIDR_ROUTE_METRIC2,
        'metric3': INET_CIDR_ROUTE_METRIC3,
        'metric4': INET_CIDR_ROUTE_METRIC4,
        'metric5': INET_CIDR_ROUTE_METRIC5,
    }
    column_oids = {
        'if_index': INET_CIDR_ROUTE_IF_INDEX,
        'type': INET_CIDR_ROUTE_TYPE,
        'protocol': INET_CIDR_ROUTE_PROTO,
        'age': INET_CIDR_ROUTE_AGE,
        'next_hop_as': INET_CIDR_ROUTE_NEXT_HOP_AS,
        **metric_oids,
        'status': INET_CIDR_ROUTE_STATUS,
    }
    walked_columns = await asyncio.gather(*(
        _snmp_bulk_walk_complete(
            ip, community_or_profile, oid, port,
            timeout=timeout, version=version,
        )
        for oid in column_oids.values()
    ))

    values_by_column: dict[str, dict[str, Any]] = {}
    route_suffixes: set[str] | None = None
    for (column, _oid), rows in zip(column_oids.items(), walked_columns):
        if not rows:
            raise RuntimeError(f'IP-FORWARD-MIB {column} column returned no rows')
        value_by_suffix: dict[str, Any] = {}
        for suffix, value in rows:
            normalized_suffix = str(suffix).strip('.')
            if not normalized_suffix or normalized_suffix in value_by_suffix:
                raise RuntimeError(f'IP-FORWARD-MIB {column} column has an invalid or duplicate route index')
            value_by_suffix[normalized_suffix] = value
        suffixes = set(value_by_suffix)
        if route_suffixes is None:
            route_suffixes = suffixes
        elif suffixes != route_suffixes:
            raise RuntimeError('IP-FORWARD-MIB columns do not cover the same complete route set')
        values_by_column[column] = value_by_suffix

    if not route_suffixes:
        raise RuntimeError('IP-FORWARD-MIB route table returned no rows')

    address_type_names = {0: 'unknown', 1: 'ipv4', 2: 'ipv6', 3: 'ipv4z', 4: 'ipv6z'}

    def _read_index_integer(parts: list[str], offset: int, label: str) -> tuple[int, int]:
        if offset >= len(parts):
            raise RuntimeError(f'IP-FORWARD-MIB route index is missing {label}')
        try:
            value = int(parts[offset])
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError(f'IP-FORWARD-MIB route index has an invalid {label}') from exc
        return value, offset + 1

    def _read_inet_address(
        parts: list[str], offset: int, address_type: int, label: str,
    ) -> tuple[str, int | None, int]:
        length, offset = _read_index_integer(parts, offset, f'{label} length')
        if length < 0 or offset + length > len(parts):
            raise RuntimeError(f'IP-FORWARD-MIB route index has an invalid {label} length')
        try:
            octets = [int(part) for part in parts[offset:offset + length]]
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError(f'IP-FORWARD-MIB route index has non-numeric {label} octets') from exc
        if any(octet < 0 or octet > 255 for octet in octets):
            raise RuntimeError(f'IP-FORWARD-MIB route index has out-of-range {label} octets')
        offset += length

        if address_type == 0:
            if octets:
                raise RuntimeError(f'IP-FORWARD-MIB unknown {label} must have a zero-length address')
            return '', None, offset
        address_spec = {1: (4, 4), 2: (16, 16), 3: (4, 8), 4: (16, 20)}.get(address_type)
        if address_spec is None:
            raise RuntimeError(f'IP-FORWARD-MIB route uses unsupported {label} type {address_type}')
        address_length, encoded_length = address_spec
        if len(octets) != encoded_length:
            raise RuntimeError(f'IP-FORWARD-MIB route index has an invalid {label} address size')
        address = str(ipaddress.ip_address(bytes(octets[:address_length])))
        zone = int.from_bytes(bytes(octets[address_length:]), 'big') if encoded_length > address_length else None
        return address, zone, offset

    parsed_indexes: dict[str, dict[str, Any]] = {}
    for suffix in route_suffixes:
        parts = suffix.split('.')
        if any(not part for part in parts):
            raise RuntimeError('IP-FORWARD-MIB route index contains an empty subidentifier')
        offset = 0
        destination_type, offset = _read_index_integer(parts, offset, 'destination type')
        if destination_type not in {1, 2, 3, 4}:
            raise RuntimeError(f'IP-FORWARD-MIB route has unsupported destination type {destination_type}')
        destination, destination_zone, offset = _read_inet_address(
            parts, offset, destination_type, 'destination',
        )
        prefix_length, offset = _read_index_integer(parts, offset, 'prefix length')
        address_bits = 32 if destination_type in {1, 3} else 128
        if prefix_length < 0 or prefix_length > address_bits:
            raise RuntimeError('IP-FORWARD-MIB route has an out-of-range prefix length')

        policy_length, offset = _read_index_integer(parts, offset, 'policy OID length')
        if policy_length < 2 or offset + policy_length > len(parts):
            raise RuntimeError('IP-FORWARD-MIB route has an invalid policy OID index')
        try:
            policy_arcs = [int(part) for part in parts[offset:offset + policy_length]]
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError('IP-FORWARD-MIB route has a non-numeric policy OID index') from exc
        if (
            any(arc < 0 or arc > 0xFFFFFFFF for arc in policy_arcs)
            or policy_arcs[0] not in {0, 1, 2}
            or (policy_arcs[0] < 2 and policy_arcs[1] > 39)
        ):
            raise RuntimeError('IP-FORWARD-MIB route has an invalid policy OID subidentifier')
        offset += policy_length

        next_hop_type, offset = _read_index_integer(parts, offset, 'next-hop type')
        if next_hop_type not in address_type_names:
            raise RuntimeError(f'IP-FORWARD-MIB route has unsupported next-hop type {next_hop_type}')
        next_hop, next_hop_zone, offset = _read_inet_address(
            parts, offset, next_hop_type, 'next-hop',
        )
        if offset != len(parts):
            raise RuntimeError('IP-FORWARD-MIB route index has trailing subidentifiers')

        try:
            network = ipaddress.ip_network(f'{destination}/{prefix_length}', strict=True)
        except ValueError as exc:
            raise RuntimeError('IP-FORWARD-MIB route destination is inconsistent with its prefix length') from exc
        parsed_indexes[suffix] = {
            'prefix': str(network),
            'destination': str(network),
            'destination_type': address_type_names[destination_type],
            'destination_zone': destination_zone,
            'policy': '.'.join(str(arc) for arc in policy_arcs),
            'next_hop': next_hop,
            'next_hop_type': address_type_names[next_hop_type],
            'next_hop_zone': next_hop_zone,
        }

    numeric_columns: dict[str, dict[str, int]] = {}
    for column, values in values_by_column.items():
        parsed: dict[str, int] = {}
        for suffix, raw_value in values.items():
            value = _snmp_integer_value(raw_value)
            if value is None:
                text_value = _snmp_text_value(raw_value)
                match = re.search(r'\((-?\d+)\)\s*$', text_value)
                value = int(match.group(1)) if match else None
            if value is None:
                raise RuntimeError(f'IP-FORWARD-MIB {column} column contains a non-integer value')
            parsed[suffix] = value
        numeric_columns[column] = parsed

    route_type_names = {1: 'other', 2: 'reject', 3: 'local', 4: 'remote', 5: 'blackhole'}
    protocol_names = {
        1: 'other', 2: 'local', 3: 'netmgmt', 4: 'icmp', 5: 'egp', 6: 'ggp',
        7: 'hello', 8: 'rip', 9: 'isis', 10: 'esis', 11: 'igrp',
        12: 'bbn_spf_igp', 13: 'ospf', 14: 'bgp', 15: 'idpr', 16: 'eigrp',
        17: 'dvmrp', 18: 'rpl',
    }
    route_status_names = {
        1: 'active', 2: 'not_in_service', 3: 'not_ready',
        4: 'create_and_go', 5: 'create_and_wait', 6: 'destroy',
    }
    if_indexes: set[int] = set()
    for suffix in route_suffixes:
        if_index = numeric_columns['if_index'][suffix]
        route_type = numeric_columns['type'][suffix]
        status = numeric_columns['status'][suffix]
        if if_index < 0:
            raise RuntimeError('IP-FORWARD-MIB route has an invalid ifIndex')
        if route_type not in route_type_names:
            raise RuntimeError('IP-FORWARD-MIB route has an unknown route type')
        if status not in route_status_names:
            raise RuntimeError('IP-FORWARD-MIB route has an unknown row status')
        if_indexes.add(if_index)
        for metric_name in metric_oids:
            metric = numeric_columns[metric_name][suffix]
            if metric < -1:
                raise RuntimeError(f'IP-FORWARD-MIB route has an invalid {metric_name} value')
        if numeric_columns['age'][suffix] < 0 or numeric_columns['next_hop_as'][suffix] < 0:
            raise RuntimeError('IP-FORWARD-MIB route has an invalid age or next-hop AS number')

    if_name_by_index: dict[int, str] = {}
    try:
        if_name_rows = await _snmp_bulk_walk_complete(
            ip, community_or_profile, IF_NAME, port,
            timeout=timeout, version=version,
        )
    except Exception:
        if_name_rows = []
    for suffix, raw_name in if_name_rows:
        try:
            if_index = int(str(suffix).strip('.'))
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError('IF-MIB ifName row has an invalid index') from exc
        if if_index <= 0:
            raise RuntimeError('IF-MIB ifName row has an invalid interface index')
        name = _snmp_text_value(raw_name)
        if name:
            if if_index in if_name_by_index:
                raise RuntimeError('IF-MIB ifName table contains a duplicate interface index')
            if_name_by_index[if_index] = name

    missing_if_indexes = (if_indexes - {0}) - set(if_name_by_index)
    if missing_if_indexes:
        try:
            if_descr_rows = await _snmp_bulk_walk_complete(
                ip, community_or_profile, IF_DESCR, port,
                timeout=timeout, version=version,
            )
        except Exception as exc:
            raise RuntimeError('IF-MIB could not resolve every route ifIndex') from exc
        for suffix, raw_name in if_descr_rows:
            try:
                if_index = int(str(suffix).strip('.'))
            except (TypeError, ValueError, OverflowError) as exc:
                raise RuntimeError('IF-MIB ifDescr row has an invalid index') from exc
            if if_index <= 0:
                raise RuntimeError('IF-MIB ifDescr row has an invalid interface index')
            name = _snmp_text_value(raw_name)
            if name:
                if if_index in if_name_by_index and if_index not in missing_if_indexes:
                    continue
                if if_index in if_name_by_index and if_index in missing_if_indexes:
                    raise RuntimeError('IF-MIB ifDescr table contains a duplicate interface index')
                if_name_by_index.setdefault(if_index, name)
    if (if_indexes - {0}) - set(if_name_by_index):
        raise RuntimeError('IF-MIB did not map every route ifIndex to an interface name')

    records: list[dict[str, Any]] = []
    for suffix in sorted(route_suffixes):
        status = numeric_columns['status'][suffix]
        if status != 1:
            continue
        route_index = parsed_indexes[suffix]
        if_index = numeric_columns['if_index'][suffix]
        raw_metrics = {name: numeric_columns[name][suffix] for name in metric_oids}
        metrics = {name: (None if value == -1 else value) for name, value in raw_metrics.items()}
        metric = metrics['metric1']
        protocol_code = numeric_columns['protocol'][suffix]
        route_type_code = numeric_columns['type'][suffix]
        records.append({
            **route_index,
            'interface': if_name_by_index.get(if_index, '') if if_index else '',
            'if_index': if_index,
            'protocol': protocol_names.get(protocol_code, f'protocol_{protocol_code}'),
            'protocol_code': protocol_code,
            'type': route_type_names[route_type_code],
            'route_type': route_type_names[route_type_code],
            'route_type_code': route_type_code,
            'metric': metric,
            # IP-FORWARD-MIB exposes protocol-specific metrics, not a generic
            # administrative distance/preference value.
            'preference': None,
            'metrics': metrics,
            'age': numeric_columns['age'][suffix],
            'next_hop_as': numeric_columns['next_hop_as'][suffix],
            'status': route_status_names[status],
        })

    if not records:
        raise RuntimeError('IP-FORWARD-MIB route table had no active IPv4/IPv6 routes')
    records.sort(key=lambda item: (item['prefix'], item['next_hop'], item['if_index']))
    return records


async def _snmp_walk_columns_complete(
    ip: str,
    community_or_profile: str | Mapping[str, Any],
    columns: Mapping[str, str],
    port: int,
    *,
    version: str,
    timeout: float,
) -> dict[str, dict[str, Any]]:
    """Walk related table columns and require exact, non-empty row coverage."""
    names = list(columns)
    walked = await asyncio.gather(*(
        _snmp_bulk_walk_complete(
            ip, community_or_profile, columns[name], port,
            timeout=timeout, version=version,
        )
        for name in names
    ))
    expected_suffixes: set[str] | None = None
    values_by_column: dict[str, dict[str, Any]] = {}
    for name, rows in zip(names, walked):
        values: dict[str, Any] = {}
        for suffix, value in rows:
            normalized_suffix = str(suffix).strip('.')
            if not normalized_suffix or normalized_suffix in values:
                raise RuntimeError(f'SNMP {name} table column has an invalid or duplicate row index')
            values[normalized_suffix] = value
        suffixes = set(values)
        if expected_suffixes is None:
            expected_suffixes = suffixes
        elif suffixes != expected_suffixes:
            raise RuntimeError(f'SNMP {name} table column does not cover the same complete row set')
        values_by_column[name] = values
    if not expected_suffixes:
        raise RuntimeError('SNMP protocol neighbor table returned no rows')
    return values_by_column


def _snmp_octets_value(value: Any, label: str) -> bytes:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytearray):
        value = bytes(value)
    if isinstance(value, bytes):
        return value
    text_value = str(value or '').strip()
    if text_value:
        compact = re.sub(r'[. :\-_]', '', text_value)
        if len(compact) % 2 == 0 and re.fullmatch(r'[0-9a-fA-F]+', compact):
            return bytes.fromhex(compact)
    raise RuntimeError(f'SNMP {label} value is not an octet string')


def _snmp_ipv4_value(value: Any, label: str) -> str:
    import ipaddress

    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytearray):
        value = bytes(value)
    try:
        if isinstance(value, bytes):
            if len(value) != 4:
                raise ValueError('IPv4 octet string must contain four octets')
            return str(ipaddress.IPv4Address(value))
        return str(ipaddress.IPv4Address(str(value).strip()))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f'SNMP {label} value is not a valid IPv4 address') from exc


async def _snmp_map_if_indexes(
    ip: str,
    community_or_profile: str | Mapping[str, Any],
    if_indexes: set[int],
    port: int,
    *,
    version: str,
    timeout: float,
) -> dict[int, str]:
    required = {index for index in if_indexes if index > 0}
    if not required:
        return {}
    names: dict[int, str] = {}
    try:
        name_rows = await _snmp_bulk_walk_complete(
            ip, community_or_profile, IF_NAME, port,
            timeout=timeout, version=version,
        )
    except Exception:
        name_rows = []
    for suffix, raw_name in name_rows:
        try:
            if_index = int(str(suffix).strip('.'))
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError('IF-MIB ifName table has an invalid index') from exc
        name = _snmp_text_value(raw_name)
        if if_index <= 0:
            raise RuntimeError('IF-MIB ifName table has an invalid interface index')
        if name:
            if if_index in names:
                raise RuntimeError('IF-MIB ifName table contains a duplicate interface index')
            names[if_index] = name

    missing = required - set(names)
    if missing:
        try:
            descr_rows = await _snmp_bulk_walk_complete(
                ip, community_or_profile, IF_DESCR, port,
                timeout=timeout, version=version,
            )
        except Exception as exc:
            raise RuntimeError('IF-MIB could not resolve every protocol neighbor ifIndex') from exc
        descriptions: dict[int, str] = {}
        for suffix, raw_name in descr_rows:
            try:
                if_index = int(str(suffix).strip('.'))
            except (TypeError, ValueError, OverflowError) as exc:
                raise RuntimeError('IF-MIB ifDescr table has an invalid index') from exc
            name = _snmp_text_value(raw_name)
            if if_index <= 0:
                raise RuntimeError('IF-MIB ifDescr table has an invalid interface index')
            if name:
                if if_index in descriptions:
                    raise RuntimeError('IF-MIB ifDescr table contains a duplicate interface index')
                descriptions[if_index] = name
        for if_index in missing:
            if if_index in descriptions:
                names[if_index] = descriptions[if_index]
    if required - set(names):
        raise RuntimeError('IF-MIB did not map every protocol neighbor ifIndex to a name')
    return names


async def collect_snmp_routing_neighbors(
    ip: str,
    community_or_profile: str | Mapping[str, Any],
    protocol: str,
    port: int = 161,
    *,
    version: str = '2c',
    timeout: float = 120,
) -> list[dict[str, Any]]:
    """Collect one routing protocol's neighbors from its standard/vendor MIB.

    Supported protocols are BGP4-MIB (IPv4 peers), RIPv2-MIB, Cisco's
    CISCO-EIGRP-MIB, OSPF-MIB (OSPFv2), OSPFV3-MIB, and ISIS-MIB. All required
    columns are completely walked and cross-checked. Unsupported MIBs, empty
    tables, or incomplete mappings raise so the caller can run its CLI fallback.
    """
    import ipaddress

    protocol_key = re.sub(r'[-_\s]', '', str(protocol or '').casefold())
    aliases = {
        'bgp': 'bgp', 'bgp4': 'bgp', 'bgp4mib': 'bgp',
        'rip': 'rip', 'rip2': 'rip', 'ripv2': 'rip', 'ripv2mib': 'rip',
        'eigrp': 'eigrp', 'ciscoeigrp': 'eigrp', 'ciscoeigrpmib': 'eigrp',
        'ospf': 'ospf', 'ospfv2': 'ospf', 'ospfmib': 'ospf',
        'ospfv3': 'ospfv3', 'ospfv3mib': 'ospfv3',
        'isis': 'isis', 'isisv1': 'isis', 'isismib': 'isis',
    }
    normalized_protocol = aliases.get(protocol_key)
    if not normalized_protocol:
        raise ValueError(f'Unsupported standard SNMP routing protocol: {protocol}')

    if normalized_protocol == 'bgp':
        columns = await _snmp_walk_columns_complete(
            ip, community_or_profile,
            {
                'peer_identifier': BGP4_PEER_IDENTIFIER,
                'state': BGP4_PEER_STATE,
                'admin_status': BGP4_PEER_ADMIN_STATUS,
                'local_address': BGP4_PEER_LOCAL_ADDRESS,
                'remote_address': BGP4_PEER_REMOTE_ADDRESS,
                'remote_as': BGP4_PEER_REMOTE_AS,
            },
            port, version=version, timeout=timeout,
        )
        try:
            established_time_rows = await _snmp_bulk_walk_complete(
                ip, community_or_profile, BGP4_PEER_FSM_ESTABLISHED_TIME, port,
                timeout=timeout, version=version,
            )
        except Exception:
            established_time_rows = []
        established_time_by_suffix = {
            str(suffix).strip('.'): value for suffix, value in established_time_rows
        }
        state_names = {
            1: 'idle', 2: 'connect', 3: 'active',
            4: 'opensent', 5: 'openconfirm', 6: 'established',
        }
        admin_names = {1: 'stopped', 2: 'started'}
        local_as_raw = await _snmp_get(
            ip, community_or_profile, BGP4_LOCAL_AS, port,
            timeout=min(3.0, max(1.0, float(timeout))), version=version,
        )
        local_as = _snmp_integer_value(local_as_raw)
        if local_as is not None and local_as < 0:
            local_as = None
        records: list[dict[str, Any]] = []
        for suffix in sorted(columns['state']):
            parts = suffix.split('.')
            if len(parts) != 4:
                raise RuntimeError('BGP4-MIB peer index is not an IPv4 address')
            try:
                peer_ip = str(ipaddress.IPv4Address(bytes(int(part) for part in parts)))
            except (ValueError, OverflowError) as exc:
                raise RuntimeError('BGP4-MIB peer index contains invalid IPv4 octets') from exc
            state = _snmp_integer_value(columns['state'][suffix])
            admin_status = _snmp_integer_value(columns['admin_status'][suffix])
            remote_as = _snmp_integer_value(columns['remote_as'][suffix])
            if state not in state_names or admin_status not in admin_names:
                raise RuntimeError('BGP4-MIB peer has an unknown state or administrative status')
            if remote_as is None or remote_as < 0:
                raise RuntimeError('BGP4-MIB peer has an invalid remote AS number')
            indexed_peer_ip = _snmp_ipv4_value(columns['remote_address'][suffix], 'BGP peer remote address')
            if indexed_peer_ip != peer_ip:
                raise RuntimeError('BGP4-MIB remote-address column conflicts with its peer index')
            records.append({
                'protocol': 'bgp',
                'neighbor_ip': peer_ip,
                'peer_ip': peer_ip,
                'router_id': _snmp_ipv4_value(columns['peer_identifier'][suffix], 'BGP peer identifier'),
                'local_ip': _snmp_ipv4_value(columns['local_address'][suffix], 'BGP peer local address'),
                'local_as': local_as,
                'remote_as': remote_as,
                'uptime_seconds': _snmp_integer_value(established_time_by_suffix.get(suffix)),
                'state': state_names[state],
                'admin_status': admin_names[admin_status],
                'if_index': None,
                'interface': None,
            })
        return records

    if normalized_protocol == 'rip':
        columns = await _snmp_walk_columns_complete(
            ip, community_or_profile,
            {
                'peer_address': RIP2_PEER_ADDRESS,
                'peer_domain': RIP2_PEER_DOMAIN,
                'last_update': RIP2_PEER_LAST_UPDATE,
                'version': RIP2_PEER_VERSION,
                'bad_packets': RIP2_PEER_BAD_PACKETS,
                'bad_routes': RIP2_PEER_BAD_ROUTES,
            },
            port, version=version, timeout=timeout,
        )
        records = []
        for suffix in sorted(columns['peer_address']):
            parts = suffix.split('.')
            if len(parts) != 6:
                raise RuntimeError('RIPv2-MIB peer index is not an IPv4 address/domain pair')
            try:
                index_octets = [int(part) for part in parts]
                address_octets = index_octets[:4]
                domain_octets = index_octets[4:]
                if any(octet < 0 or octet > 255 for octet in index_octets):
                    raise ValueError('RIPv2 peer index is outside its valid range')
                peer_ip = str(ipaddress.IPv4Address(bytes(address_octets)))
                domain = int.from_bytes(bytes(domain_octets), 'big')
            except (TypeError, ValueError, OverflowError) as exc:
                raise RuntimeError('RIPv2-MIB peer index contains invalid values') from exc
            indexed_peer_ip = _snmp_ipv4_value(columns['peer_address'][suffix], 'RIP peer address')
            version_value = _snmp_integer_value(columns['version'][suffix])
            last_update = _snmp_integer_value(columns['last_update'][suffix])
            bad_packets = _snmp_integer_value(columns['bad_packets'][suffix])
            bad_routes = _snmp_integer_value(columns['bad_routes'][suffix])
            if indexed_peer_ip != peer_ip:
                raise RuntimeError('RIPv2-MIB peer-address column conflicts with its table index')
            if version_value not in {1, 2} or last_update is None or last_update < 0:
                raise RuntimeError('RIPv2-MIB peer has an invalid version or last-update time')
            if bad_packets is None or bad_packets < 0 or bad_routes is None or bad_routes < 0:
                raise RuntimeError('RIPv2-MIB peer has invalid error counters')
            domain_value = _snmp_octets_value(columns['peer_domain'][suffix], 'RIP peer domain')
            if len(domain_value) != 2:
                raise RuntimeError('RIPv2-MIB peer domain must contain two octets')
            indexed_domain = int.from_bytes(domain_value, 'big')
            if indexed_domain != domain:
                raise RuntimeError('RIPv2-MIB peer-domain column conflicts with its table index')
            records.append({
                'protocol': 'rip',
                'neighbor_id': peer_ip,
                'neighbor_ip': peer_ip,
                'state': 'active',
                'rip_domain': domain,
                'rip_version': version_value,
                'last_update_ticks': last_update,
                'bad_packets': bad_packets,
                'bad_routes': bad_routes,
                'interface': '',
            })
        return records

    if normalized_protocol == 'eigrp':
        columns = await _snmp_walk_columns_complete(
            ip, community_or_profile,
            {
                'address_type': EIGRP_PEER_ADDRESS_TYPE,
                'address': EIGRP_PEER_ADDRESS,
                'if_index': EIGRP_PEER_IF_INDEX,
                'hold_time': EIGRP_PEER_HOLD_TIME,
            },
            port, version=version, timeout=timeout,
        )
        parsed_rows: list[tuple[str, str, int, int]] = []
        interface_indexes: set[int] = set()
        for suffix in sorted(columns['address']):
            index_parts = suffix.split('.')
            if len(index_parts) != 3:
                raise RuntimeError('CISCO-EIGRP-MIB peer index is not a VPN/AS/handle tuple')
            try:
                vpn_id, autonomous_system, peer_handle = (int(part) for part in index_parts)
            except (TypeError, ValueError, OverflowError) as exc:
                raise RuntimeError('CISCO-EIGRP-MIB peer index contains non-numeric values') from exc
            if vpn_id < 0 or autonomous_system <= 0 or peer_handle <= 0:
                raise RuntimeError('CISCO-EIGRP-MIB peer index contains invalid values')
            address_type = _snmp_integer_value(columns['address_type'][suffix])
            raw_address = _snmp_octets_value(columns['address'][suffix], 'EIGRP peer address')
            if address_type == 1 and len(raw_address) == 4:
                peer_ip = str(ipaddress.IPv4Address(raw_address))
            elif address_type == 2 and len(raw_address) == 16:
                peer_ip = str(ipaddress.IPv6Address(raw_address))
            else:
                raise RuntimeError('CISCO-EIGRP-MIB peer address has an unsupported type or length')
            if_index = _snmp_integer_value(columns['if_index'][suffix])
            hold_time = _snmp_integer_value(columns['hold_time'][suffix])
            if if_index is None or if_index < 0 or hold_time is None or hold_time < 0:
                raise RuntimeError('CISCO-EIGRP-MIB peer has an invalid ifIndex or hold timer')
            if if_index:
                interface_indexes.add(if_index)
            parsed_rows.append((suffix, peer_ip, if_index, autonomous_system))

        interface_names = await _snmp_map_if_indexes(
            ip, community_or_profile, interface_indexes, port,
            version=version, timeout=timeout,
        )
        records = []
        for suffix, peer_ip, if_index, autonomous_system in parsed_rows:
            if if_index and if_index not in interface_names:
                raise RuntimeError('CISCO-EIGRP-MIB did not map every peer ifIndex')
            records.append({
                'protocol': 'eigrp',
                'neighbor_id': f'{peer_ip}/AS{autonomous_system}',
                'neighbor_ip': peer_ip,
                'state': 'up',
                'local_as': autonomous_system,
                'hold_time': _snmp_integer_value(columns['hold_time'][suffix]),
                'if_index': if_index or None,
                'interface': interface_names.get(if_index, ''),
                'vpn_id': int(suffix.split('.')[0]),
            })
        return records

    if normalized_protocol == 'ospf':
        columns = await _snmp_walk_columns_complete(
            ip, community_or_profile,
            {
                'router_id': OSPF_NBR_ROUTER_ID,
                'priority': OSPF_NBR_PRIORITY,
                'state': OSPF_NBR_STATE,
                'events': OSPF_NBR_EVENTS,
                'retransmit_queue': OSPF_NBR_RETRANS_QUEUE,
            },
            port, version=version, timeout=timeout,
        )
        state_names = {
            1: 'down', 2: 'attempt', 3: 'init', 4: 'two_way',
            5: 'exchange_start', 6: 'exchange', 7: 'loading', 8: 'full',
        }
        parsed_rows: list[tuple[str, str, int, int, int, int]] = []
        interface_indexes: set[int] = set()
        for suffix in sorted(columns['state']):
            parts = suffix.split('.')
            if len(parts) != 5:
                raise RuntimeError('OSPF-MIB neighbor index has an invalid IPv4/interface shape')
            try:
                address_octets = [int(part) for part in parts[:4]]
                if any(octet < 0 or octet > 255 for octet in address_octets):
                    raise ValueError('neighbor IPv4 octet out of range')
                neighbor_ip = str(ipaddress.IPv4Address(bytes(address_octets)))
                addressless_if_index = int(parts[4])
            except (TypeError, ValueError, OverflowError) as exc:
                raise RuntimeError('OSPF-MIB neighbor index contains invalid values') from exc
            router_id = _snmp_ipv4_value(columns['router_id'][suffix], 'OSPF neighbor router ID')
            priority = _snmp_integer_value(columns['priority'][suffix])
            state = _snmp_integer_value(columns['state'][suffix])
            events = _snmp_integer_value(columns['events'][suffix])
            retransmit_queue = _snmp_integer_value(columns['retransmit_queue'][suffix])
            if addressless_if_index < 0 or priority is None or not 0 <= priority <= 255:
                raise RuntimeError('OSPF-MIB neighbor has an invalid interface index or priority')
            if state not in state_names or events is None or events < 0 or retransmit_queue is None or retransmit_queue < 0:
                raise RuntimeError('OSPF-MIB neighbor has an invalid state or counter')
            interface_indexes.add(addressless_if_index)
            parsed_rows.append((suffix, neighbor_ip, addressless_if_index, router_id, priority, state))
        interface_names = await _snmp_map_if_indexes(
            ip, community_or_profile, interface_indexes, port,
            version=version, timeout=timeout,
        )
        return [{
            'protocol': 'ospf',
            'neighbor_ip': neighbor_ip,
            'peer_ip': neighbor_ip,
            'router_id': router_id,
            'state': state_names[state],
            'priority': priority,
            'events': _snmp_integer_value(columns['events'][suffix]),
            'retransmit_queue_length': _snmp_integer_value(columns['retransmit_queue'][suffix]),
            # OSPF-MIB's addressless index is zero on addressed interfaces;
            # in that case the standard table does not expose a local ifIndex.
            'if_index': addressless_if_index or None,
            'interface': interface_names.get(addressless_if_index),
        } for suffix, neighbor_ip, addressless_if_index, router_id, priority, state in parsed_rows]

    if normalized_protocol == 'ospfv3':
        columns = await _snmp_walk_columns_complete(
            ip, community_or_profile,
            {
                'address_type': OSPFV3_NBR_ADDRESS_TYPE,
                'address': OSPFV3_NBR_ADDRESS,
                'priority': OSPFV3_NBR_PRIORITY,
                'state': OSPFV3_NBR_STATE,
                'events': OSPFV3_NBR_EVENTS,
            },
            port, version=version, timeout=timeout,
        )
        state_names = {
            1: 'down', 2: 'attempt', 3: 'init', 4: 'two_way',
            5: 'exchange_start', 6: 'exchange', 7: 'loading', 8: 'full',
        }
        parsed_rows: list[tuple[str, str, int, int, int, int, int]] = []
        interface_indexes: set[int] = set()
        for suffix in sorted(columns['state']):
            parts = suffix.split('.')
            if len(parts) != 3:
                raise RuntimeError('OSPFV3-MIB neighbor index has an invalid shape')
            try:
                if_index, instance_id, router_id_value = (int(part) for part in parts)
                router_id = str(ipaddress.IPv4Address(router_id_value))
            except (TypeError, ValueError, OverflowError) as exc:
                raise RuntimeError('OSPFV3-MIB neighbor index contains invalid values') from exc
            address_type = _snmp_integer_value(columns['address_type'][suffix])
            address_bytes = _snmp_octets_value(columns['address'][suffix], 'OSPFv3 neighbor address')
            if if_index <= 0 or instance_id < 0 or instance_id > 255 or router_id_value <= 0:
                raise RuntimeError('OSPFV3-MIB neighbor index has an invalid interface, instance, or router ID')
            if address_type != 2 or len(address_bytes) != 16:
                raise RuntimeError('OSPFV3-MIB neighbor address is not an IPv6 address')
            neighbor_ip = str(ipaddress.IPv6Address(address_bytes))
            priority = _snmp_integer_value(columns['priority'][suffix])
            state = _snmp_integer_value(columns['state'][suffix])
            events = _snmp_integer_value(columns['events'][suffix])
            if priority is None or not 0 <= priority <= 255 or state not in state_names or events is None or events < 0:
                raise RuntimeError('OSPFV3-MIB neighbor has an invalid priority, state, or event counter')
            interface_indexes.add(if_index)
            parsed_rows.append((suffix, neighbor_ip, if_index, instance_id, router_id_value, priority, state))
        interface_names = await _snmp_map_if_indexes(
            ip, community_or_profile, interface_indexes, port,
            version=version, timeout=timeout,
        )
        return [{
            'protocol': 'ospfv3',
            'neighbor_ip': neighbor_ip,
            'peer_ip': neighbor_ip,
            'router_id': str(ipaddress.IPv4Address(router_id_value)),
            'state': state_names[state],
            'priority': priority,
            'events': _snmp_integer_value(columns['events'][suffix]),
            'instance_id': instance_id,
            'if_index': if_index,
            'interface': interface_names[if_index],
        } for suffix, neighbor_ip, if_index, instance_id, router_id_value, priority, state in parsed_rows]

    columns = await _snmp_walk_columns_complete(
        ip, community_or_profile,
        {
            'state': ISIS_ADJ_STATE,
            'three_way_state': ISIS_ADJ_THREE_WAY_STATE,
            'snpa_address': ISIS_ADJ_SNPA_ADDRESS,
            'neighbor_type': ISIS_ADJ_NEIGHBOR_TYPE,
            'neighbor_system_id': ISIS_ADJ_NEIGHBOR_SYSTEM_ID,
            'usage': ISIS_ADJ_USAGE,
            'hold_timer': ISIS_ADJ_HOLD_TIMER,
            'priority': ISIS_ADJ_NEIGHBOR_PRIORITY,
        },
        port, version=version, timeout=timeout,
    )
    circuit_rows = await _snmp_bulk_walk_complete(
        ip, community_or_profile, ISIS_CIRC_IF_INDEX, port,
        timeout=timeout, version=version,
    )
    if not circuit_rows:
        raise RuntimeError('ISIS-MIB circuit-to-ifIndex table returned no rows')
    circuit_if_indexes: dict[int, int] = {}
    for suffix, raw_if_index in circuit_rows:
        try:
            circuit_index = int(str(suffix).strip('.'))
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError('ISIS-MIB circuit table has an invalid circuit index') from exc
        if_index = _snmp_integer_value(raw_if_index)
        if circuit_index <= 0 or if_index is None or if_index <= 0:
            raise RuntimeError('ISIS-MIB circuit table has an invalid interface mapping')
        if circuit_index in circuit_if_indexes:
            raise RuntimeError('ISIS-MIB circuit table contains a duplicate circuit index')
        circuit_if_indexes[circuit_index] = if_index

    state_names = {1: 'down', 2: 'initializing', 3: 'up', 4: 'failed'}
    three_way_state_names = {0: 'up', 1: 'initializing', 2: 'down', 3: 'failed'}
    neighbor_type_names = {1: 'level1', 2: 'level2', 3: 'level1_and_level2', 4: 'unknown'}
    usage_names = {1: 'level1', 2: 'level2', 3: 'level1_and_level2'}
    parsed_rows: list[dict[str, Any]] = []
    interface_indexes: set[int] = set()
    for suffix in sorted(columns['state']):
        parts = suffix.split('.')
        if len(parts) != 2:
            raise RuntimeError('ISIS-MIB adjacency index has an invalid circuit/neighbor shape')
        try:
            circuit_index, adjacency_index = (int(part) for part in parts)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError('ISIS-MIB adjacency index contains non-numeric values') from exc
        if circuit_index <= 0 or adjacency_index <= 0:
            raise RuntimeError('ISIS-MIB adjacency index contains a non-positive value')
        if_index = circuit_if_indexes.get(circuit_index)
        if if_index is None:
            raise RuntimeError('ISIS-MIB did not map an adjacency circuit to ifIndex')
        state = _snmp_integer_value(columns['state'][suffix])
        three_way_state = _snmp_integer_value(columns['three_way_state'][suffix])
        neighbor_type = _snmp_integer_value(columns['neighbor_type'][suffix])
        usage = _snmp_integer_value(columns['usage'][suffix])
        hold_timer = _snmp_integer_value(columns['hold_timer'][suffix])
        priority = _snmp_integer_value(columns['priority'][suffix])
        if state not in state_names or three_way_state not in three_way_state_names:
            raise RuntimeError('ISIS-MIB adjacency has an unknown state')
        if neighbor_type not in neighbor_type_names or usage not in usage_names:
            raise RuntimeError('ISIS-MIB adjacency has an unknown level/type')
        if hold_timer is None or hold_timer < 0 or priority is None or not 0 <= priority <= 127:
            raise RuntimeError('ISIS-MIB adjacency has an invalid hold timer or priority')
        system_id_octets = _snmp_octets_value(columns['neighbor_system_id'][suffix], 'IS-IS neighbor system ID')
        if len(system_id_octets) != 6:
            raise RuntimeError('ISIS-MIB neighbor system ID must contain six octets')
        system_hex = system_id_octets.hex()
        system_id = '.'.join(system_hex[offset:offset + 4] for offset in range(0, 12, 4))
        snpa_octets = _snmp_octets_value(columns['snpa_address'][suffix], 'IS-IS neighbor SNPA')
        snpa = snpa_octets.hex(':') if snpa_octets else ''
        interface_indexes.add(if_index)
        parsed_rows.append({
            'protocol': 'isis',
            'neighbor_id': system_id,
            'neighbor_system_id': system_id,
            'neighbor_ip': None,
            'peer_ip': None,
            'state': state_names[state],
            'three_way_state': three_way_state_names[three_way_state],
            'neighbor_type': neighbor_type_names[neighbor_type],
            'level': usage_names[usage],
            'hold_time': hold_timer,
            'priority': priority,
            'snpa': snpa,
            'circuit_index': circuit_index,
            'adjacency_index': adjacency_index,
            'if_index': if_index,
        })
    interface_names = await _snmp_map_if_indexes(
        ip, community_or_profile, interface_indexes, port,
        version=version, timeout=timeout,
    )
    for record in parsed_rows:
        record['interface'] = interface_names[record['if_index']]
    return parsed_rows


async def collect_device_info(
    ip: str,
    community: str | Mapping[str, Any] = 'public',
    port: int = 161,
    version: str = '2c',
) -> dict:
    """
    Collect standard MIB-2 system information.
    Returns: { sys_name, sys_descr, sys_object_id, uptime, sys_location, sys_contact }
    """
    import asyncio as _aio
    result = {'sys_name': None, 'sys_descr': None, 'sys_object_id': None, 'uptime': None,
              'sys_location': None, 'sys_contact': None}
    try:
        vals = await _aio.gather(
            _snmp_get(ip, community, SYS_NAME, port, version=version),
            _snmp_get(ip, community, SYS_DESCR, port, version=version),
            _snmp_get(ip, community, SYS_OBJECT_ID, port, version=version),
            _snmp_get(ip, community, SYS_UPTIME, port, version=version),
            _snmp_get(ip, community, SYS_LOCATION, port, version=version),
            _snmp_get(ip, community, SYS_CONTACT, port, version=version),
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
    community: str | Mapping[str, Any],
    port: int = 161,
    version: str = '2c',
    timeout: float = 30.0,
    max_rows: Optional[int] = 10000,
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
    # configured fallback (for example, SSH) instead. SNMPv3 uses the resolved
    # profile mapping in the same transport helper as the other collectors.
    version_key = str(version or '2c').strip().casefold()
    if version_key in {'3', 'v3', 'snmpv3'}:
        if not isinstance(community, Mapping):
            raise ValueError('SNMPv3 profile is required for LLDP discovery')
        _snmpv3_credentials(community)
    elif not str(community or '').strip():
        raise ValueError('SNMP community is required for LLDP discovery')

    class _SnmpLLDPBatch(list[dict[str, Any]]):
        def __init__(
            self,
            records: list[dict[str, Any]],
            collection_status: str,
            *,
            truncated_oids: Optional[list[str]] = None,
            max_rows: Optional[int] = 10000,
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
    community: str | Mapping[str, Any] = 'public',
    port: int = 161,
    interface_config: Mapping[str, Any] | None = None,
    *,
    version: str = '2c',
) -> list[dict[str, Any]]:
    """Read only interface names and IF-MIB indexes for a device inventory refresh."""
    config = normalize_interface_config(interface_config) if interface_config else dict(DEFAULT_INTERFACE_CONFIG)
    if not config.get('enabled', True):
        config = dict(DEFAULT_INTERFACE_CONFIG)

    name_rows = await _snmp_bulk_walk(
        ip, community, config.get('if_name_oid') or '', port, version=version,
    ) if config.get('if_name_oid') else []
    if not name_rows and config.get('if_descr_oid'):
        name_rows = await _snmp_bulk_walk(
            ip, community, config['if_descr_oid'], port, version=version,
        )

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
    community: str | Mapping[str, Any] = 'public',
    port: int = 161,
    interface_config: Mapping[str, Any] | None = None,
    *,
    template_only: bool = False,
    version: str = '2c',
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
    community_token_source = (
        json.dumps(community, sort_keys=True, ensure_ascii=False, default=str)
        if isinstance(community, Mapping)
        else str(community or '')
    )
    community_token = hashlib.sha256(community_token_source.encode('utf-8')).hexdigest()[:12]
    config_token = hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    ).hexdigest()[:16]
    cache_key = f"intf-health:{ip}:{port}:{version}:{int(template_only)}:{community_token}:{config_token}"
    cached = _get_result_cache(cache_key)
    if cached is not None:
        return cached

    interfaces: dict[str, dict[str, Any]] = {}
    try:
        async def _walk(oid: str):
            if not oid:
                return []
            if str(version or '2c').strip().casefold() in {'2c', 'v2c', '2', ''}:
                return await _snmp_bulk_walk(ip, community, oid, port)
            return await _snmp_bulk_walk(ip, community, oid, port, version=version)

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
    community: str | Mapping[str, Any],
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
    elif version_key in {'3', 'v3', 'snmpv3'}:
        version_key = '3'
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
            # compatible. Other versions use the profile-aware transport.
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
