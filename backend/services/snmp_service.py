"""
SNMP 采集服务 — 多厂商 CPU / 内存 / 温度 / 风扇 / 电源 / 接口监控
支持: Cisco IOS/NX-OS/IOS-XR, Huawei VRP, H3C Comware, Arista EOS, Juniper Junos

标准 MIB-2 OID 用于接口监控 (RFC 1213 / IF-MIB):
  ifDescr       .1.3.6.1.2.1.2.2.1.2
  ifOperStatus  .1.3.6.1.2.1.2.2.1.8
  ifSpeed       .1.3.6.1.2.1.2.2.1.5
  ifInOctets    .1.3.6.1.2.1.2.2.1.10
  ifOutOctets   .1.3.6.1.2.1.2.2.1.16
  ifHCInOctets  .1.3.6.1.2.1.31.1.1.1.6   (64-bit)
  ifHCOutOctets .1.3.6.1.2.1.31.1.1.1.10  (64-bit)
  ifAlias       .1.3.6.1.2.1.31.1.1.1.18

厂商 CPU / 内存 OID 参考:
  Cisco IOS:     cpmCPUTotal5minRev (.1.3.6.1.4.1.9.9.109.1.1.1.1.8)
                 ciscoMemoryPoolUsed (.1.3.6.1.4.1.9.9.48.1.1.1.5)
                 ciscoMemoryPoolFree (.1.3.6.1.4.1.9.9.48.1.1.1.6)
  Cisco NX-OS:   同 IOS OIDs (CISCO-PROCESS-MIB / CISCO-MEMORY-POOL-MIB)
  Huawei VRP:    hwEntityCpuUsage   (.1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5)
                 hwEntityMemUsage   (.1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7)
                 hwEntityTemperature(.1.3.6.1.4.1.2011.5.25.31.1.1.1.1.11)
                 hwEntityFanState   (.1.3.6.1.4.1.2011.5.25.31.1.1.10.1.7)
  H3C Comware:   hh3cEntityExtCpuUsage      (.1.3.6.1.4.1.25506.2.6.1.1.1.1.6)
                 hh3cEntityExtMemUsage      (.1.3.6.1.4.1.25506.2.6.1.1.1.1.8)
                 hh3cEntityExtTemperature   (.1.3.6.1.4.1.25506.2.6.1.1.1.1.12)
  Arista EOS:    使用 HOST-RESOURCES-MIB (hrProcessorLoad / hrStorageUsed)
                 hrProcessorLoad (.1.3.6.1.2.1.25.3.3.1.2)
                 hrStorageUsed   (.1.3.6.1.2.1.25.2.3.1.6)
                 hrStorageSize   (.1.3.6.1.2.1.25.2.3.1.5)
  Juniper Junos: jnxOperatingCPU     (.1.3.6.1.4.1.2636.3.1.13.1.8)
                 jnxOperatingBuffer  (.1.3.6.1.4.1.2636.3.1.13.1.11)
                 jnxOperatingTemp    (.1.3.6.1.4.1.2636.3.1.13.1.7)
"""

import asyncio
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from services.network_access_limiter import get_network_access_limiter
import logging
import sys
import time as _time
from collections.abc import Mapping
from typing import Any, Optional

from services.snmp_counter_service import (
    calculate_counter_delta,
    load_counter_sample,
    save_counter_sample,
)

logger = logging.getLogger(__name__)


def _install_snmp_error_filter() -> None:
    """Suppress puresnmp ProactorDatagramTransport errors on Windows.

    Windows ProactorEventLoop + puresnmp triggers harmless
    WinError 1234 / InvalidStateError in _loop_reading callbacks
    when SNMP targets are unreachable. These are not actionable and
    are purely noise in the logs.
    """
    if sys.platform != 'win32':
        return

    _original_handler = None

    def _filter_handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
        msg = context.get('message', '')
        # Suppress harmless puresnmp transport errors on Windows
        if '_loop_reading' in msg or '_SelectorDatagramTransport' in msg:
            return  # suppress
        
        # Also suppress InvalidStateError from puresnmp futures
        exception = context.get('exception')
        if exception and 'InvalidStateError' in str(type(exception)):
            return # suppress
        if _original_handler:
            _original_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    try:
        loop = asyncio.get_event_loop()
        _original_handler = getattr(loop, '_exception_handler', None)
        loop.set_exception_handler(_filter_handler)
    except RuntimeError:
        pass  # no event loop yet


_install_snmp_error_filter()

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
# OID Definitions per vendor
# ═══════════════════════════════════════════════════════════════

# Standard IF-MIB OIDs (all vendors)
IF_DESCR       = '1.3.6.1.2.1.2.2.1.2'
IF_OPER_STATUS = '1.3.6.1.2.1.2.2.1.8'
IF_SPEED       = '1.3.6.1.2.1.2.2.1.5'
IF_IN_OCTETS   = '1.3.6.1.2.1.2.2.1.10'
IF_OUT_OCTETS  = '1.3.6.1.2.1.2.2.1.16'
IF_HC_IN       = '1.3.6.1.2.1.31.1.1.1.6'
IF_HC_OUT      = '1.3.6.1.2.1.31.1.1.1.10'
IF_ALIAS       = '1.3.6.1.2.1.31.1.1.1.18'
IF_NAME        = '1.3.6.1.2.1.31.1.1.1.1'

# Standard HOST-RESOURCES-MIB (RFC 2790) – CPU / memory fallback
HR_PROCESSOR_LOAD = '1.3.6.1.2.1.25.3.3.1.2'   # hrProcessorLoad (%)
HR_STORAGE_DESCR  = '1.3.6.1.2.1.25.2.3.1.3'    # hrStorageDescr ("Physical Memory" etc.)
HR_STORAGE_UNITS  = '1.3.6.1.2.1.25.2.3.1.4'    # hrStorageAllocationUnits
HR_STORAGE_SIZE   = '1.3.6.1.2.1.25.2.3.1.5'    # hrStorageSize (allocation units)
HR_STORAGE_USED   = '1.3.6.1.2.1.25.2.3.1.6'    # hrStorageUsed (allocation units)

# ENTITY-SENSOR-MIB (RFC 3433) – standard temp/fan/psu for NX-OS, IOS-XR, Arista
ENT_SENSOR_VALUE  = '1.3.6.1.2.1.99.1.1.1.4'    # entPhySensorValue
ENT_SENSOR_TYPE   = '1.3.6.1.2.1.99.1.1.1.1'    # entPhySensorType (8=celsius, 10=rpm)

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

# The interface template deliberately mirrors the complete IF-MIB contract
# used by the collector.  Keeping the defaults in one place lets a model
# profile replace only the OIDs that differ on a vendor while preserving the
# standard fallback behaviour for every other field.
DEFAULT_INTERFACE_CONFIG = {
    'enabled': True,
    'if_name_oid': IF_NAME,
    'if_descr_oid': IF_DESCR,
    'if_alias_oid': IF_ALIAS,
    'if_oper_status_oid': IF_OPER_STATUS,
    'if_high_speed_oid': IF_HIGH_SPEED,
    'if_speed_oid': IF_SPEED,
    'if_last_change_oid': IF_LAST_CHANGE,
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
    'counter_mode': 'auto',
}

_INTERFACE_OID_FIELDS = tuple(
    key for key in DEFAULT_INTERFACE_CONFIG if key.endswith('_oid')
)
_INTERFACE_OID_ALIASES = {
    'if_name': 'if_name_oid',
    'if_descr': 'if_descr_oid',
    'if_alias': 'if_alias_oid',
    'if_oper_status': 'if_oper_status_oid',
    'if_high_speed': 'if_high_speed_oid',
    'if_speed': 'if_speed_oid',
    'if_last_change': 'if_last_change_oid',
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

VENDOR_OIDS = {
    # ── Cisco IOS / IOS-XE ──
    'cisco_ios': {
        'cpu': '1.3.6.1.4.1.9.9.109.1.1.1.1.8',       # cpmCPUTotal5minRev
        # Enhanced mempool (IOS-XE / Cat9K / ISR4K / ASR) — tried first
        'mem_used_enhanced': '1.3.6.1.4.1.9.9.221.1.1.1.1.18',  # cempMemPoolHCUsed (64-bit)
        'mem_free_enhanced': '1.3.6.1.4.1.9.9.221.1.1.1.1.20',  # cempMemPoolHCFree (64-bit)
        # Legacy mempool (classic IOS) — fallback
        'mem_used': '1.3.6.1.4.1.9.9.48.1.1.1.5',      # ciscoMemoryPoolUsed
        'mem_free': '1.3.6.1.4.1.9.9.48.1.1.1.6',      # ciscoMemoryPoolFree
        'temp': '1.3.6.1.4.1.9.9.13.1.3.1.3',           # ciscoEnvMonTemperatureValue
        'fan': '1.3.6.1.4.1.9.9.13.1.4.1.3',            # ciscoEnvMonFanState (1=normal)
        'psu': '1.3.6.1.4.1.9.9.13.1.5.1.3',            # ciscoEnvMonSupplyState (1=normal)
    },
    # ── Cisco NX-OS (Nexus series) ──
    'cisco_nxos': {
        'cpu': '1.3.6.1.4.1.9.9.109.1.1.1.1.8',         # cpmCPUTotal5minRev
        'mem_pct': '1.3.6.1.4.1.9.9.305.1.1.2.0',       # cseSysMemoryUtilization (percentage)
        # CISCO-ENTITY-SENSOR-MIB for temperature
        'temp_sensor_value': '1.3.6.1.4.1.9.9.91.1.1.1.1.4',  # entSensorValue
        'temp_sensor_type':  '1.3.6.1.4.1.9.9.91.1.1.1.1.1',  # entSensorType (8=celsius)
        # CISCO-ENTITY-FRU-CONTROL-MIB for fan/psu
        'fan': '1.3.6.1.4.1.9.9.117.1.4.1.1.1',         # cefcFanTrayOperStatus (1=unknown,2=up,3=down,4=warning)
        'psu': '1.3.6.1.4.1.9.9.117.1.1.2.1.2',         # cefcFRUPowerOperStatus (2=on,3=off,9=onButFanFail)
    },
    # ── Cisco IOS-XR (ASR9K / NCS / XRv) ──
    'cisco_iosxr': {
        'cpu': '1.3.6.1.4.1.9.9.109.1.1.1.1.8',         # cpmCPUTotal5minRev
        # CISCO-PROCESS-MIB memory (works on IOS-XR)
        'mem_used': '1.3.6.1.4.1.9.9.109.1.1.1.1.12',   # cpmCPUMemoryUsed
        'mem_free': '1.3.6.1.4.1.9.9.109.1.1.1.1.13',   # cpmCPUMemoryFree
        # CISCO-ENTITY-SENSOR-MIB + FRU-CONTROL (same as NX-OS)
        'temp_sensor_value': '1.3.6.1.4.1.9.9.91.1.1.1.1.4',
        'temp_sensor_type':  '1.3.6.1.4.1.9.9.91.1.1.1.1.1',
        'fan': '1.3.6.1.4.1.9.9.117.1.4.1.1.1',         # cefcFanTrayOperStatus
        'psu': '1.3.6.1.4.1.9.9.117.1.1.2.1.2',         # cefcFRUPowerOperStatus
    },
    # ── Huawei VRP (CE / S / AR / NE series) ──
    'huawei_vrp': {
        'cpu': '1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5',    # hwEntityCpuUsage
        'mem': '1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7',     # hwEntityMemUsage (percentage)
        'temp': '1.3.6.1.4.1.2011.5.25.31.1.1.1.1.11',   # hwEntityTemperature
        'fan': '1.3.6.1.4.1.2011.5.25.31.1.1.10.1.7',    # hwFanState (1=normal)
        'psu': '1.3.6.1.4.1.2011.5.25.31.1.1.13.1.2',    # hwPowerStatusTable
    },
    # ── H3C / New H3C Comware V7 ──
    'h3c_comware': {
        'cpu': '1.3.6.1.4.1.25506.2.6.1.1.1.1.6',        # hh3cEntityExtCpuUsage
        'mem': '1.3.6.1.4.1.25506.2.6.1.1.1.1.8',         # hh3cEntityExtMemUsage (percentage)
        'temp': '1.3.6.1.4.1.25506.2.6.1.1.1.1.12',       # hh3cEntityExtTemperature
        'fan': '1.3.6.1.4.1.25506.2.6.1.1.1.1.19',        # hh3cEntityExtFanStatus
        'psu': '1.3.6.1.4.1.25506.2.6.1.1.1.1.21',        # hh3cEntityExtPowerStatus
    },
    # ── Arista EOS ──
    'arista_eos': {
        'cpu': '1.3.6.1.2.1.25.3.3.1.2',                   # hrProcessorLoad (walk, average)
        'mem_descr': '1.3.6.1.2.1.25.2.3.1.3',             # hrStorageDescr (find "RAM")
        'mem_used': '1.3.6.1.2.1.25.2.3.1.6',              # hrStorageUsed
        'mem_size': '1.3.6.1.2.1.25.2.3.1.5',              # hrStorageSize
        'mem_units': '1.3.6.1.2.1.25.2.3.1.4',             # hrStorageAllocationUnits
        # ENTITY-SENSOR-MIB (RFC 3433) for temperature
        'temp_sensor_value': '1.3.6.1.2.1.99.1.1.1.4',     # entPhySensorValue
        'temp_sensor_type':  '1.3.6.1.2.1.99.1.1.1.1',     # entPhySensorType (8=celsius)
        # Arista fan/psu via ENTITY-SENSOR-MIB
        'fan': '1.3.6.1.2.1.99.1.1.1.4',                   # entPhySensorValue (filter type=10 rpm)
        'fan_type': '1.3.6.1.2.1.99.1.1.1.1',
        'psu': '1.3.6.1.2.1.99.1.1.1.4',                   # entPhySensorValue (filter type=3 volts)
        'psu_type': '1.3.6.1.2.1.99.1.1.1.1',
    },
    # ── Juniper Junos ──
    'juniper_junos': {
        'cpu': '1.3.6.1.4.1.2636.3.1.13.1.8',             # jnxOperatingCPU
        'mem': '1.3.6.1.4.1.2636.3.1.13.1.11',             # jnxOperatingBuffer (percentage)
        'temp': '1.3.6.1.4.1.2636.3.1.13.1.7',             # jnxOperatingTemp
        'fan': '1.3.6.1.4.1.2636.3.1.13.1.6',              # jnxOperatingState (2=running,5=runningAtFullSpeed)
        'fan_descr': '1.3.6.1.4.1.2636.3.1.13.1.5',        # jnxOperatingDescr (filter "Fan")
        'psu': '1.3.6.1.4.1.2636.3.1.13.1.6',              # jnxOperatingState for PSU entries
        'psu_descr': '1.3.6.1.4.1.2636.3.1.13.1.5',        # jnxOperatingDescr (filter "Power")
    },
    # ── Fortinet FortiOS (FortiGate) ──
    'fortinet_fortios': {
        'cpu': '1.3.6.1.4.1.12356.101.4.1.3.0',           # fgSysCpuUsage
        'mem': '1.3.6.1.4.1.12356.101.4.1.4.0',           # fgSysMemUsage
        'temp': '1.3.6.1.4.1.12356.101.4.3.2.1.3',        # fgHwSensorEntValue (temp sensors)
        'fan': '1.3.6.1.4.1.12356.101.4.3.2.1.3',         # fgHwSensorEntValue (fan sensors)
        'psu': '1.3.6.1.4.1.12356.101.4.3.2.1.3',         # fgHwSensorEntValue (psu sensors)
        'sensor_name': '1.3.6.1.4.1.12356.101.4.3.2.1.2', # fgHwSensorEntName
        'sensor_alarm': '1.3.6.1.4.1.12356.101.4.3.2.1.4',# fgHwSensorEntAlarmStatus
    },
}

# Map platform string -> vendor key
def _resolve_platform(platform: str) -> str:
    p = (platform or '').lower().replace('-', '_')
    if p in VENDOR_OIDS:
        return p
    if 'cisco' in p and 'nx' in p:
        return 'cisco_nxos'
    if 'cisco' in p and 'xr' in p:
        return 'cisco_iosxr'
    if 'cisco' in p:
        return 'cisco_ios'
    if 'huawei' in p:
        return 'huawei_vrp'
    if 'h3c' in p or 'comware' in p:
        return 'h3c_comware'
    if 'arista' in p:
        return 'arista_eos'
    if 'juniper' in p or 'junos' in p:
        return 'juniper_junos'
    if 'forti' in p:
        return 'fortinet_fortios'
    return 'cisco_ios'  # default


_METRIC_OID_PATTERN = re.compile(r'^\d+(?:\.\d+)+$')


def normalize_metric_oid(value: Any) -> str:
    """Normalize and validate a user-provided CPU/memory metric OID.

    A leading dot is accepted because both ``.1.3...`` and ``1.3...`` are
    common representations in vendor documentation.  The collector stores
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


def _safe_metric_oid(value: Any) -> str:
    """Ignore malformed legacy database values at collection time."""
    try:
        return normalize_metric_oid(value)
    except ValueError:
        return ''


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


def _as_percent(number: float | None) -> int | None:
    if number is None or number < 0 or number > 100:
        return None
    return int(round(number))


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


async def _collect_custom_percent_metric(
    ip: str,
    community: str,
    oid: str,
    port: int,
) -> int | None:
    """Read a user-supplied percentage OID as a scalar or a small table.

    Exact GET is preferred for scalar OIDs.  If the device exposes the OID as
    a table/root, WALK is used and the valid 0-100 values are averaged.  This
    keeps one device-level setting useful for both common SNMP layouts.
    """
    value = await _snmp_get(ip, community, oid, port)
    direct = _as_percent(_parse_snmp_number(value))
    if direct is not None:
        return direct

    rows = await _snmp_walk(ip, community, oid, port)
    values = [
        parsed
        for _, raw in rows
        if (parsed := _as_percent(_parse_snmp_number(raw))) is not None
    ]
    if not values:
        return None
    return int(round(sum(values) / len(values)))


async def _collect_default_cpu_metric(
    ip: str,
    community: str,
    vendor: str,
    oids: dict[str, str],
    port: int,
) -> int | None:
    if vendor == 'arista_eos':
        rows = await _snmp_walk(ip, community, oids['cpu'], port)
        values = [
            int(parsed)
            for _, raw in rows
            if (parsed := _parse_snmp_number(raw)) is not None
        ]
        return int(sum(values) / len(values)) if values else None

    rows = await _snmp_walk(ip, community, oids['cpu'], port)
    if not rows:
        return None
    if vendor in ('huawei_vrp', 'h3c_comware', 'juniper_junos'):
        for _, raw in rows:
            parsed = _parse_snmp_number(raw)
            if parsed is not None and parsed > 0:
                return int(parsed)
        return None

    for _, raw in rows:
        parsed = _parse_snmp_number(raw)
        if parsed is not None:
            return int(parsed)
    return None


async def _collect_default_memory_metric(
    ip: str,
    community: str,
    vendor: str,
    oids: dict[str, str],
    port: int,
) -> int | None:
    if vendor == 'cisco_nxos':
        mem_pct_oid = oids.get('mem_pct')
        if not mem_pct_oid:
            return None
        return _as_percent(_parse_snmp_number(await _snmp_get(ip, community, mem_pct_oid, port)))

    if vendor in ('huawei_vrp', 'h3c_comware', 'juniper_junos', 'fortinet_fortios'):
        mem_oid = oids.get('mem')
        if not mem_oid:
            return None
        rows = await _snmp_walk(ip, community, mem_oid, port)
        for _, raw in rows:
            parsed = _parse_snmp_number(raw)
            if parsed is not None and parsed > 0:
                return _as_percent(parsed)
        return None

    if vendor == 'arista_eos':
        descr_rows = await _snmp_walk(ip, community, oids['mem_descr'], port)
        used_rows = await _snmp_walk(ip, community, oids['mem_used'], port)
        size_rows = await _snmp_walk(ip, community, oids['mem_size'], port)
        used_map = {
            idx: int(parsed)
            for idx, raw in used_rows
            if (parsed := _parse_snmp_number(raw)) is not None
        }
        size_map = {
            idx: int(parsed)
            for idx, raw in size_rows
            if (parsed := _parse_snmp_number(raw)) is not None
        }
        ram_idx = None
        for idx, desc in descr_rows:
            desc_lower = desc.lower()
            if 'physical' in desc_lower or 'ram' in desc_lower or 'real' in desc_lower:
                ram_idx = idx
                break
        if ram_idx is None and size_map:
            ram_idx = max(size_map, key=lambda key: size_map[key])
        if ram_idx and ram_idx in used_map and ram_idx in size_map and size_map[ram_idx] > 0:
            return _as_percent((used_map[ram_idx] / size_map[ram_idx]) * 100)
        return None

    if vendor in ('cisco_ios', 'cisco_iosxr'):
        cemp_used = oids.get('mem_used_enhanced')
        cemp_free = oids.get('mem_free_enhanced')
        used_raw = await _snmp_walk(ip, community, cemp_used, port) if cemp_used else []
        free_raw = await _snmp_walk(ip, community, cemp_free, port) if cemp_free else []
        if not used_raw or not free_raw:
            used_raw = await _snmp_walk(ip, community, oids['mem_used'], port)
            free_raw = await _snmp_walk(ip, community, oids['mem_free'], port)
    else:
        used_oid = oids.get('mem_used')
        free_oid = oids.get('mem_free')
        if not used_oid or not free_oid:
            return None
        used_raw = await _snmp_walk(ip, community, used_oid, port)
        free_raw = await _snmp_walk(ip, community, free_oid, port)

    if not used_raw or not free_raw:
        return None
    used = _parse_snmp_number(used_raw[0][1]) or 0
    free = _parse_snmp_number(free_raw[0][1]) or 0
    total = used + free
    return _as_percent((used / total) * 100) if total > 0 else None


# ═══════════════════════════════════════════════════════════════
# puresnmp async helpers (replaces pysnmp — Python 3.13 compatible)
# ═══════════════════════════════════════════════════════════════

def _val_to_str(val) -> str:
    """Convert puresnmp value to a clean string."""
    if isinstance(val, bytes):
        return val.decode('utf-8', errors='replace').strip('\r\n \x00')
    return str(val).strip()


async def _safe_send_udp(endpoint, packet: bytes, timeout: int = 1, loop=None, retries: int = 10) -> bytes:
    """Send one SNMP datagram and always close its asyncio UDP transport.

    puresnmp's default sender leaves the transport open when the protocol
    reports an OS-level socket error. Automatic telemetry calls this sender
    frequently, so make cleanup unconditional for success, timeout, error,
    and task cancellation paths.
    """
    from puresnmp import transport
    from puresnmp.exc import Timeout

    if loop is None:
        loop = asyncio.get_event_loop()
    remaining = max(1, int(retries))

    while remaining > 0:
        protocol = None
        datagram_transport = None
        try:
            datagram_transport, protocol = await loop.create_datagram_endpoint(
                lambda: transport.SNMPClientProtocol(packet),
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


async def _snmp_get(ip: str, community: str, oid: str, port: int = 161, timeout: float = 3) -> Optional[str]:
    """GET a single OID value via puresnmp (SNMPv2c)."""
    async with get_network_access_limiter().async_snmp():
      try:
        from puresnmp import Client, V2C, PyWrapper
        client = PyWrapper(Client(ip, V2C(community), port=port, sender=_safe_send_udp))
        result = await asyncio.wait_for(client.get(oid), timeout=timeout)
        if result is None:
            return None
        v = _val_to_str(result)
        if v and 'noSuchObject' not in v and 'noSuchInstance' not in v:
            return v
      except Exception as e:
        logger.debug(f"SNMP GET {ip} {oid} failed: {e}")
      return None


async def _snmp_walk(
    ip: str,
    community: str,
    oid: str,
    port: int = 161,
    timeout: float = 5,
    max_rows: int = 200,
    version: str = '2c',
) -> list[tuple[str, str]]:
    """Walk an OID subtree via puresnmp, return list of (oid_suffix, value).

    The collector remains v2c by default.  The optional v1 path is used by
    the read-only template tester and keeps the same transport/error handling;
    existing collection callers do not need to change their arguments.
    """
    results: list[tuple[str, str]] = []
    base_oid = oid.rstrip('.')
    version_key = str(version or '2c').strip().lower()
    if version_key in {'v1', '1'}:
        version_key = '1'
    elif version_key in {'v2c', '2c', '2'}:
        version_key = '2c'
    else:
        raise ValueError('Unsupported SNMP version; use 1 or 2c')

    async def _collect():
        from puresnmp import Client, PyWrapper, V1, V2C
        auth = V1(community) if version_key == '1' else V2C(community)
        client = PyWrapper(Client(ip, auth, port=port, sender=_safe_send_udp))
        async for varbind in client.walk(base_oid):
            oid_str = str(varbind.oid)
            suffix = oid_str[len(base_oid) + 1:] if oid_str.startswith(base_oid + '.') else oid_str
            v = _val_to_str(varbind.value)
            if 'endOfMibView' in v:
                return
            results.append((suffix, v))
            if len(results) >= max_rows:
                return

    async with get_network_access_limiter().async_snmp():
      try:
        await asyncio.wait_for(_collect(), timeout=timeout)
      except asyncio.TimeoutError:
        logger.debug(f"SNMP WALK {ip} {oid} timeout after {timeout}s ({len(results)} rows collected)")
      except Exception as e:
        logger.debug(f"SNMP WALK {ip} {oid} failed: {e}")
    return results


async def _snmp_get_typed(
    ip: str,
    community: str,
    oid: str,
    port: int = 161,
    timeout: float = 3,
) -> Optional[SnmpTypedValue]:
    """GET one OID while preserving its puresnmp ASN.1 type."""
    async with get_network_access_limiter().async_snmp():
        try:
            from puresnmp import Client, ObjectIdentifier, V2C

            client = Client(ip, V2C(community), port=port, sender=_safe_send_udp)
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
) -> list[tuple[str, SnmpTypedValue]]:
    """WALK one OID subtree and preserve each row's ASN.1 type."""
    results: list[tuple[str, SnmpTypedValue]] = []
    base_oid = oid.rstrip(".")

    async def _collect():
        from puresnmp import Client, ObjectIdentifier, V2C

        client = Client(ip, V2C(community), port=port, sender=_safe_send_udp)
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
) -> list[tuple[str, SnmpTypedValue]]:
    """Typed GETBULK walk used for interface counters."""
    results: list[tuple[str, SnmpTypedValue]] = []
    base_oid = oid.rstrip(".")

    async def _collect():
        from puresnmp import Client, ObjectIdentifier, V2C

        client = Client(ip, V2C(community), port=port, sender=_safe_send_udp)
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
        return await _snmp_walk_typed(ip, community, oid, port, timeout=timeout, max_rows=max_rows)
    return results


async def _snmp_bulk_walk(ip: str, community: str, oid: str, port: int = 161, timeout: float = 5, max_repetitions: int = 20) -> list[tuple[str, str]]:
    """Bulk Walk an OID subtree via puresnmp, using GETBULK for high performance."""
    results: list[tuple[str, str]] = []
    base_oid = oid.rstrip('.')

    async def _collect():
        from puresnmp import Client, V2C, PyWrapper
        client = PyWrapper(Client(ip, V2C(community), port=port, sender=_safe_send_udp))
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
        results = await _snmp_walk(ip, community, oid, port, timeout=timeout)
    return results


def _runtime_metric_config(config: Mapping[str, Any] | None, legacy_oid: str = "") -> dict[str, Any]:
    """Normalize the already-validated profile payload at the collector edge."""
    raw = dict(config or {})
    mode = str(raw.get("mode") or "direct_percent").strip().casefold()
    aliases = {
        "gauge_percent": "direct_percent",
        "percent": "direct_percent",
        "value": "direct_value",
        "ratio": "used_total_percent",
        "counter_rate": "counter_rate_percent",
        "status": "status_code",
    }
    mode = aliases.get(mode, mode)
    default_unit = (
        "%"
        if mode in {"direct_percent", "used_total_percent", "used_free_percent", "counter_rate_percent"}
        else "bool"
        if mode == "status_code"
        else ""
    )
    return {
        "mode": mode,
        "oid": str(raw.get("oid") or legacy_oid or "").strip().strip("."),
        "used_oid": str(raw.get("used_oid") or raw.get("oid") or "").strip().strip("."),
        "total_oid": str(raw.get("total_oid") or "").strip().strip("."),
        "free_oid": str(raw.get("free_oid") or "").strip().strip("."),
        "capacity_oid": str(raw.get("capacity_oid") or "").strip().strip("."),
        "counter_bits": raw.get("counter_bits"),
        "counter_unit": str(raw.get("counter_unit") or "bits").strip().casefold(),
        "status_ok_values": _runtime_code_values(raw.get("status_ok_values", raw.get("normal_values"))),
        "status_warning_values": _runtime_code_values(raw.get("status_warning_values", raw.get("warning_values"))),
        "status_fail_values": _runtime_code_values(raw.get("status_fail_values", raw.get("failure_values"))),
        "unit": str(raw.get("unit") or default_unit).strip(),
        "aggregation": str(raw.get("aggregation") or "average").strip().casefold(),
        "selector": str(raw.get("selector") or "").strip().strip("."),
        "scale": raw.get("scale", 1),
        "offset": raw.get("offset", 0),
    }


def _runtime_code_values(value: Any) -> list[int]:
    values = value if isinstance(value, (list, tuple, set)) else str(value or "").replace("，", ",").split(",")
    result: list[int] = []
    for raw in values:
        try:
            if str(raw).strip() == "":
                continue
            code = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if code not in result:
            result.append(code)
    return result


async def _read_typed_points(
    ip: str,
    community: str,
    oid: str,
    port: int,
    selector: str = "",
) -> list[tuple[str, SnmpTypedValue]]:
    if not oid:
        return []
    if not selector:
        direct = await _snmp_get_typed(ip, community, oid, port)
        if direct is not None:
            return [("", direct)]
        return await _snmp_walk_typed(ip, community, oid, port)

    # A selector identifies a table instance, so a GET on the column root is
    # not enough.  The old implementation fetched the root, then discarded
    # the scalar result and filtered a walk; on devices/views that do not
    # expose GETNEXT this made a valid OID look missing.  Probe the exact
    # instance first, then fall back to a walk for agents that only support
    # GETBULK.  The returned empty suffix keeps downstream pairing stable.
    normalized_selector = str(selector).strip().strip('.')
    instance_oid = oid if oid.endswith(f'.{normalized_selector}') else f'{oid}.{normalized_selector}'
    instance = await _snmp_get_typed(ip, community, instance_oid, port)
    if instance is not None:
        return [(normalized_selector, instance)]
    points = await _snmp_walk_typed(ip, community, oid, port)
    return [
        (suffix, value)
        for suffix, value in points
        if str(suffix).strip().strip('.') == normalized_selector
        or str(suffix).strip().strip('.').endswith(f".{normalized_selector}")
    ]


def _numeric(raw: Any) -> float | None:
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _aggregate(values: list[float], aggregation: str) -> float | None:
    if not values:
        return None
    if aggregation == "first":
        return values[0]
    if aggregation == "max":
        return max(values)
    if aggregation == "min":
        return min(values)
    if aggregation == "sum":
        return sum(values)
    return sum(values) / len(values)


def _pair_points(
    left: list[tuple[str, SnmpTypedValue]],
    right: list[tuple[str, SnmpTypedValue]],
) -> list[tuple[str, SnmpTypedValue, SnmpTypedValue]]:
    """Pair scalar/table values by index, allowing one side to be scalar."""
    if not left or not right:
        return []
    left_map = dict(left)
    right_map = dict(right)
    common = set(left_map).intersection(right_map)
    if common:
        return [(key, left_map[key], right_map[key]) for key in sorted(common)]
    if len(left) == 1:
        return [(key, left[0][1], value) for key, value in right]
    if len(right) == 1:
        return [(key, value, right[0][1]) for key, value in left]
    return []


def _absolute_value_allowed(value: SnmpTypedValue) -> bool:
    # Counter values are never accepted as a current CPU/memory level.  A
    # vendor that exposes used/total as Counter32 is semantically wrong for a
    # ratio and must be corrected in the template rather than guessed here.
    return value.snmp_type in {"gauge", "integer", "python_number"}


def _scaled(raw: float, config: Mapping[str, Any]) -> float | None:
    scale = _numeric(config.get("scale", 1))
    offset = _numeric(config.get("offset", 0))
    if scale is None or offset is None or scale <= 0:
        return None
    value = raw * scale + offset
    return value if math.isfinite(value) else None


def _parse_sample_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _definition_result(
    config: Mapping[str, Any],
    *,
    value: Any,
    status: str,
    passed: bool,
    message: str = "",
    snmp_types: list[str] | None = None,
    counter_bits: int | None = None,
    quality: list[str] | None = None,
    rows: int = 0,
) -> dict[str, Any]:
    output = value
    if isinstance(output, (int, float)) and not isinstance(output, bool) and math.isfinite(output):
        output = round(float(output), 3)
    return {
        "value": output,
        "status": status,
        "passed": passed,
        "message": message,
        "mode": config.get("mode"),
        "oid": config.get("oid") or config.get("used_oid"),
        "snmp_types": sorted(set(snmp_types or [])),
        "counter_bits": counter_bits,
        "unit": config.get("unit") or "",
        "quality": quality or [],
        "rows": rows,
    }


async def _collect_metric_definition(
    ip: str,
    community: str,
    config: Mapping[str, Any],
    port: int,
    *,
    device_id: str = "",
    profile_id: str = "",
    metric_name: str = "",
    persist_counter: bool = True,
) -> dict[str, Any]:
    """Collect one typed metric definition without implicit reinterpretation."""
    normalized = _runtime_metric_config(config)
    mode = normalized["mode"]
    aggregation = normalized["aggregation"]

    if mode == "direct_percent":
        points = await _read_typed_points(ip, community, normalized["oid"], port, normalized["selector"])
        if not points:
            return _definition_result(normalized, value=None, status="missing", passed=False, message="OID returned no numeric value")
        types = [point.snmp_type for _, point in points]
        if not all(_absolute_value_allowed(point) for _, point in points):
            return _definition_result(
                normalized,
                value=None,
                status="type_mismatch",
                passed=False,
                message="A Counter32/Counter64 cannot be used as a direct percentage",
                snmp_types=types,
                counter_bits=next((point.counter_bits for _, point in points if point.counter_bits), None),
                rows=len(points),
            )
        values = [_scaled(float(point.number), normalized) for _, point in points if point.number is not None]
        if any(value is None or value < 0 or value > 100 for value in values) or not values:
            return _definition_result(
                normalized,
                value=None,
                status="out_of_range",
                passed=False,
                message="Direct percentage must be within 0..100 after scale/offset",
                snmp_types=types,
                rows=len(points),
            )
        return _definition_result(
            normalized,
            value=_aggregate([float(value) for value in values], aggregation),
            status="ok",
            passed=True,
            snmp_types=types,
            rows=len(points),
        )

    if mode == "direct_value":
        points = await _read_typed_points(ip, community, normalized["oid"], port, normalized["selector"])
        if not points:
            return _definition_result(normalized, value=None, status="missing", passed=False, message="OID returned no numeric value")
        types = [point.snmp_type for _, point in points]
        if not all(_absolute_value_allowed(point) for _, point in points):
            return _definition_result(
                normalized,
                value=None,
                status="type_mismatch",
                passed=False,
                message="A Counter32/Counter64 cannot be used as a direct hardware value",
                snmp_types=types,
                counter_bits=next((point.counter_bits for _, point in points if point.counter_bits), None),
                rows=len(points),
            )
        values = [_scaled(float(point.number), normalized) for _, point in points if point.number is not None]
        if any(value is None for value in values) or not values:
            return _definition_result(normalized, value=None, status="invalid_value", passed=False, message="Hardware value is not finite", snmp_types=types, rows=len(points))
        return _definition_result(
            normalized,
            value=_aggregate([float(value) for value in values], aggregation),
            status="ok",
            passed=True,
            snmp_types=types,
            rows=len(points),
        )

    if mode == "status_code":
        points = await _read_typed_points(ip, community, normalized["oid"], port, normalized["selector"])
        if not points:
            return _definition_result(normalized, value=None, status="missing", passed=False, message="Status OID returned no numeric value")
        types = [point.snmp_type for _, point in points]
        if not all(_absolute_value_allowed(point) for _, point in points):
            return _definition_result(normalized, value=None, status="type_mismatch", passed=False, message="Status OID must return Gauge/Integer values", snmp_types=types, rows=len(points))
        codes = [int(point.number) for _, point in points if point.number is not None and float(point.number).is_integer()]
        if len(codes) != len(points):
            return _definition_result(normalized, value=None, status="invalid_status_code", passed=False, message="Status OID must return integer codes", snmp_types=types, rows=len(points))
        ok_values = set(normalized.get("status_ok_values") or [])
        warning_values = set(normalized.get("status_warning_values") or [])
        fail_values = set(normalized.get("status_fail_values") or [])
        if any(code in fail_values for code in codes):
            status, boolean_value = "fail", False
        elif any(code in warning_values for code in codes):
            # The public contract is binary: true is normal and false is
            # abnormal. Keep warning as diagnostic status only.
            status, boolean_value = "warning", False
        elif all(code in ok_values for code in codes):
            status, boolean_value = "ok", True
        else:
            status, boolean_value = "unknown", None
        return _definition_result(
            normalized,
            value=boolean_value,
            status=status,
            passed=boolean_value is not None,
            message="" if boolean_value is not None else "Device returned an unmapped hardware status code",
            snmp_types=types,
            rows=len(points),
        )

    if mode in {"used_total_percent", "used_free_percent"}:
        used_points = await _read_typed_points(ip, community, normalized["used_oid"], port, normalized["selector"])
        denominator_oid = normalized["total_oid"] if mode == "used_total_percent" else normalized["free_oid"]
        denominator_points = await _read_typed_points(ip, community, denominator_oid, port, normalized["selector"])
        pairs = _pair_points(used_points, denominator_points)
        types = [point.snmp_type for _, used, total in pairs for point in (used, total)]
        if not pairs:
            return _definition_result(normalized, value=None, status="missing", passed=False, message="Used and denominator OIDs could not be paired", rows=0)
        if not all(_absolute_value_allowed(point) for _, used, denominator in pairs for point in (used, denominator)):
            return _definition_result(
                normalized,
                value=None,
                status="type_mismatch",
                passed=False,
                message="Ratio operands must be Gauge/Integer values, not SNMP counters",
                snmp_types=types,
                rows=len(pairs),
            )
        percentages: list[float] = []
        for _, used, denominator in pairs:
            used_value = _numeric(used.number)
            denominator_value = _numeric(denominator.number)
            if used_value is None or denominator_value is None or used_value < 0 or denominator_value <= 0:
                return _definition_result(normalized, value=None, status="invalid_denominator", passed=False, message="Ratio denominator must be greater than zero", snmp_types=types, rows=len(pairs))
            if mode == "used_free_percent":
                denominator_value += used_value
            ratio = used_value / denominator_value * 100
            scaled = _scaled(ratio, normalized)
            if scaled is None or scaled < 0 or scaled > 100:
                return _definition_result(normalized, value=None, status="out_of_range", passed=False, message="Calculated ratio must be within 0..100", snmp_types=types, rows=len(pairs))
            percentages.append(scaled)
        return _definition_result(normalized, value=_aggregate(percentages, aggregation), status="ok", passed=True, snmp_types=types, rows=len(pairs))

    if mode != "counter_rate_percent":
        return _definition_result(normalized, value=None, status="unsupported_mode", passed=False, message="Unsupported metric mode")

    points = await _read_typed_points(ip, community, normalized["oid"], port, normalized["selector"])
    capacity_points = await _read_typed_points(ip, community, normalized["capacity_oid"], port, normalized["selector"])
    pairs = _pair_points(points, capacity_points)
    configured_bits = normalized.get("counter_bits")
    try:
        configured_bits = int(configured_bits)
    except (TypeError, ValueError):
        configured_bits = None
    types = [point.snmp_type for _, point, _ in pairs]
    observed_bits = sorted({point.counter_bits for _, point, _ in pairs if point.counter_bits})
    if not pairs:
        return _definition_result(normalized, value=None, status="missing", passed=False, message="Counter or capacity OID returned no pair", rows=0)
    if any(point.snmp_type != "counter" for _, point, _ in pairs):
        return _definition_result(normalized, value=None, status="type_mismatch", passed=False, message="counter_rate_percent requires Counter32 or Counter64", snmp_types=types, rows=len(pairs))
    if configured_bits not in (32, 64) or observed_bits != [configured_bits]:
        return _definition_result(normalized, value=None, status="width_mismatch", passed=False, message=f"Template declares {configured_bits or 'unknown'}-bit but device returned {observed_bits or 'unknown'}-bit counter", snmp_types=types, counter_bits=observed_bits[0] if len(observed_bits) == 1 else None, rows=len(pairs))
    if any(not _absolute_value_allowed(capacity) for _, _, capacity in pairs):
        return _definition_result(normalized, value=None, status="capacity_type_mismatch", passed=False, message="Capacity OID must return Gauge/Integer, not a counter", snmp_types=types, counter_bits=configured_bits, rows=len(pairs))

    now = datetime.now(timezone.utc)
    sampled_at = now.isoformat()
    current_values: dict[str, int] = {}
    capacity_values: dict[str, float] = {}
    for suffix, point, capacity in pairs:
        if point.number is None or not float(point.number).is_integer() or point.number < 0:
            return _definition_result(normalized, value=None, status="invalid_counter", passed=False, message="Counter value must be a non-negative integer", snmp_types=types, counter_bits=configured_bits, rows=len(pairs))
        if capacity.number is None or capacity.number <= 0:
            return _definition_result(normalized, value=None, status="invalid_capacity", passed=False, message="Capacity must be greater than zero", snmp_types=types, counter_bits=configured_bits, rows=len(pairs))
        current_values[suffix] = int(point.number)
        capacity_values[suffix] = float(capacity.number)

    uptime_value = await _snmp_get_typed(ip, community, SYS_UPTIME, port, timeout=2)
    current_uptime_cs = int(uptime_value.number) if uptime_value and uptime_value.number is not None else None
    previous = load_counter_sample(device_id, profile_id, metric_name) if device_id and profile_id and metric_name else None
    config_hash = hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:32]
    previous_valid = bool(
        previous
        and str(previous.get("oid") or "") == normalized["oid"]
        and str(previous.get("config_hash") or "") == config_hash
        and int(previous.get("counter_bits") or 0) == configured_bits
    )
    previous_values = (previous or {}).get("values") if previous_valid else {}
    previous_time = _parse_sample_time((previous or {}).get("sampled_at")) if previous_valid else None
    elapsed = (now - previous_time).total_seconds() if previous_time else None
    previous_uptime_cs = (previous or {}).get("device_uptime_cs") if previous_valid else None

    unit_multiplier = 8.0 if normalized["counter_unit"] == "octets" else 1.0
    derived: list[float] = []
    qualities: list[str] = []
    for suffix, current_value in current_values.items():
        old_value = previous_values.get(suffix) if isinstance(previous_values, Mapping) else None
        if old_value is None or elapsed is None:
            qualities.append("baseline")
            continue
        capacity = capacity_values.get(suffix)
        max_counter_rate = capacity / unit_multiplier if capacity else None
        delta = calculate_counter_delta(
            current_value,
            old_value,
            elapsed,
            configured_bits,
            max_rate_per_sec=max_counter_rate,
            current_uptime_cs=current_uptime_cs,
            previous_uptime_cs=previous_uptime_cs,
        )
        quality = str(delta.get("status") or "invalid")
        qualities.append(quality)
        if delta.get("rate_per_sec") is None or not capacity:
            continue
        utilization = float(delta["rate_per_sec"]) * unit_multiplier / capacity * 100
        if not math.isfinite(utilization) or utilization < 0 or utilization > 100:
            qualities.append("utilization_out_of_range")
            continue
        derived.append(utilization)

    if persist_counter and device_id and profile_id and metric_name:
        save_counter_sample(
            device_id=device_id,
            profile_id=profile_id,
            metric_name=metric_name,
            oid=normalized["oid"],
            config_hash=config_hash,
            counter_bits=configured_bits,
            values=current_values,
            sampled_at=sampled_at,
            device_uptime_cs=current_uptime_cs,
        )

    if derived and len(derived) == len(current_values):
        status = next((quality for quality in qualities if quality in {"wrapped", "ok"}), "ok")
        return _definition_result(normalized, value=_aggregate(derived, aggregation), status=status, passed=True, snmp_types=types, counter_bits=configured_bits, quality=qualities, rows=len(pairs))
    if derived:
        return _definition_result(normalized, value=None, status="partial_sample", passed=False, message="Not every counter row produced a valid delta", snmp_types=types, counter_bits=configured_bits, quality=qualities, rows=len(pairs))
    status = "baseline" if "baseline" in qualities else (qualities[0] if qualities else "missing")
    return _definition_result(normalized, value=None, status=status, passed=status == "baseline", snmp_types=types, counter_bits=configured_bits, quality=qualities, rows=len(pairs))


async def probe_metric_definition(
    ip: str,
    community: str,
    config: Mapping[str, Any],
    port: int = 161,
) -> dict[str, Any]:
    """Read and validate a definition without changing a device baseline."""
    return await _collect_metric_definition(ip, community, config, port, persist_counter=False)

# ═══════════════════════════════════════════════════════════════
# High-level collection functions
# ═══════════════════════════════════════════════════════════════

async def collect_device_info(ip: str, community: str = 'public', port: int = 161) -> dict:
    """
    Collect standard MIB-2 system information.
    Returns: { sys_name, sys_descr, uptime, sys_location, sys_contact }
    """
    import asyncio as _aio
    result = {'sys_name': None, 'sys_descr': None, 'uptime': None,
              'sys_location': None, 'sys_contact': None}
    try:
        vals = await _aio.gather(
            _snmp_get(ip, community, SYS_NAME, port),
            _snmp_get(ip, community, SYS_DESCR, port),
            _snmp_get(ip, community, SYS_UPTIME, port),
            _snmp_get(ip, community, SYS_LOCATION, port),
            _snmp_get(ip, community, SYS_CONTACT, port),
        )
        result['sys_name'] = vals[0]
        result['sys_descr'] = vals[1]
        # sysUpTime is in hundredths of a second → human readable
        if vals[2]:
            try:
                ticks = int(vals[2])
                secs = ticks // 100
                days, rem = divmod(secs, 86400)
                hours, rem = divmod(rem, 3600)
                mins, _ = divmod(rem, 60)
                result['uptime'] = f"{days}d {hours}h {mins}m"
            except (ValueError, TypeError):
                result['uptime'] = vals[2]
        result['sys_location'] = vals[3]
        result['sys_contact'] = vals[4]
    except Exception as e:
        logger.warning(f"SNMP device info collection failed for {ip}: {e}")
    return result


async def collect_device_metrics(
    ip: str,
    platform: str,
    community: str = 'public',
    port: int = 161,
    custom_oids: dict[str, str] | None = None,
    *,
    custom_metrics: Mapping[str, Mapping[str, Any]] | None = None,
    device_id: str = '',
    metric_profile_id: str = '',
) -> dict:
    """
    Collect the standard hardware set (CPU, memory, temperature, fan, PSU,
    storage, voltage, and power) from a single device.
    Returns metric values plus typed quality details.  A configured metric is
    fail-closed: an invalid custom definition does not silently fall back to a
    different vendor OID and present a misleading value.
    """
    vendor = _resolve_platform(platform)
    custom_oids = custom_oids or {}
    custom_cpu_oid = _safe_metric_oid(custom_oids.get('cpu') or custom_oids.get('cpu_oid'))
    custom_memory_oid = _safe_metric_oid(
        custom_oids.get('memory')
        or custom_oids.get('mem')
        or custom_oids.get('memory_oid')
    )
    configured_metrics: dict[str, Mapping[str, Any]] = dict(custom_metrics or {})
    if custom_cpu_oid and 'cpu' not in configured_metrics:
        configured_metrics['cpu'] = {'mode': 'direct_percent', 'oid': custom_cpu_oid}
    if custom_memory_oid and 'memory' not in configured_metrics:
        configured_metrics['memory'] = {'mode': 'direct_percent', 'oid': custom_memory_oid}
    # The same target can be represented by multiple device records. Include
    # credentials and metric overrides in the in-process key so one device
    # cannot receive another device's cached result.
    community_token = hashlib.sha256(str(community or '').encode('utf-8')).hexdigest()[:12]
    metric_token = hashlib.sha256(
        json.dumps(
            {key: dict(value) for key, value in configured_metrics.items()},
            sort_keys=True,
            default=str,
        ).encode('utf-8')
    ).hexdigest()[:16]
    cache_key = (
        f"metrics:{ip}:{port}:{vendor}:{community_token}:"
        f"{metric_profile_id}:{device_id}:{metric_token}"
    )
    cached = _get_result_cache(cache_key)
    if cached is not None:
        return cached
    oids = VENDOR_OIDS.get(vendor, VENDOR_OIDS['cisco_ios'])
    result = {
        'cpu_usage': None,
        'memory_usage': None,
        'temp': None,
        'fan_status': None,
        'psu_status': None,
        'storage_usage': None,
        'voltage': None,
        'power_watts': None,
        'hardware_metrics': {},
        'metric_details': {},
    }

    try:
        for metric, result_key, default_collector in (
            ('cpu', 'cpu_usage', _collect_default_cpu_metric),
            ('memory', 'memory_usage', _collect_default_memory_metric),
        ):
            definition = configured_metrics.get(metric)
            if definition:
                detail = await _collect_metric_definition(
                    ip,
                    community,
                    definition,
                    port,
                    device_id=device_id,
                    profile_id=metric_profile_id,
                    metric_name=metric,
                )
                result['metric_details'][metric] = detail
                result['hardware_metrics'][metric] = detail.get('value')
                # Do not reinterpret an invalid configured OID with a built-in
                # OID. Missing data must remain visible to the operator.
                result[result_key] = detail.get('value')
            else:
                result[result_key] = await default_collector(ip, community, vendor, oids, port)
            result['hardware_metrics'][metric] = result[result_key]

        # ── Temperature, Fan, PSU ──
        if vendor == 'fortinet_fortios':
            try:
                names = await _snmp_walk(ip, community, oids['sensor_name'], port)
                values = await _snmp_walk(ip, community, oids['temp'], port) # temp/fan/psu point to the same OID
                alarms = await _snmp_walk(ip, community, oids['sensor_alarm'], port)
                
                name_map = {idx: v for idx, v in names}
                val_map = {idx: v for idx, v in values}
                alarm_map = {idx: v for idx, v in alarms}
                
                # Temp
                for idx, name in names:
                    name_lower = name.lower()
                    if 'temp' in name_lower and idx in val_map:
                        v = val_map[idx]
                        if v.isdigit():
                            val_int = int(v)
                            if val_int > 200:
                                val_int = val_int // 10
                            if 0 < val_int < 200:
                                result['temp'] = val_int
                                break
                
                # Fan
                fan_ok = True
                fan_found = False
                for idx, name in names:
                    name_lower = name.lower()
                    if 'fan' in name_lower:
                        fan_found = True
                        if idx in alarm_map:
                            if alarm_map[idx] != '0':
                                fan_ok = False
                        elif idx in val_map:
                            v = val_map[idx]
                            if v.isdigit() and int(v) == 0:
                                fan_ok = False
                if fan_found:
                    result['fan_status'] = 'ok' if fan_ok else 'fail'
                
                # PSU
                psu_ok_count = 0
                psu_fail_count = 0
                psu_found = False
                for idx, name in names:
                    name_lower = name.lower()
                    if 'psu' in name_lower or 'power supply' in name_lower or 'pwr' in name_lower:
                        psu_found = True
                        if idx in alarm_map:
                            if alarm_map[idx] == '0':
                                psu_ok_count += 1
                            else:
                                psu_fail_count += 1
                        elif idx in val_map:
                            v = val_map[idx]
                            if v.isdigit() and int(v) > 0:
                                psu_ok_count += 1
                            else:
                                psu_fail_count += 1
                if psu_found:
                    if psu_fail_count > 0:
                        result['psu_status'] = 'fail'
                    elif psu_ok_count >= 2:
                        result['psu_status'] = 'redundant'
                    elif psu_ok_count == 1:
                        result['psu_status'] = 'single'
                    else:
                        result['psu_status'] = 'fail'
            except Exception as e:
                logger.warning(f"Fortinet sensor collection failed for {ip}: {e}")
        else:
            # ── Temperature ──
            if vendor in ('cisco_nxos', 'cisco_iosxr', 'arista_eos'):
                # Use ENTITY-SENSOR-MIB / CISCO-ENTITY-SENSOR-MIB: match type=8 (celsius)
                type_oid = oids.get('temp_sensor_type')
                value_oid = oids.get('temp_sensor_value')
                if type_oid and value_oid:
                    type_rows = await _snmp_walk(ip, community, type_oid, port)
                    value_rows = await _snmp_walk(ip, community, value_oid, port)
                    value_map = {idx: v for idx, v in value_rows}
                    for idx, t in type_rows:
                        if t == '8' and idx in value_map:  # 8 = celsius
                            v = value_map[idx]
                            if v.isdigit() and 0 < int(v) < 200:
                                result['temp'] = int(v)
                                break
            else:
                temp_oid = oids.get('temp')
                if temp_oid:
                    rows = await _snmp_walk(ip, community, temp_oid, port)
                    if rows:
                        for _, v in rows:
                            if v.isdigit() and 0 < int(v) < 200:
                                result['temp'] = int(v)
                                break

            # ── Fan ──
            fan_oid = oids.get('fan')
            if fan_oid:
                if vendor == 'cisco_nxos' or vendor == 'cisco_iosxr':
                    # cefcFanTrayOperStatus: 2=up, 4=warning → ok; 3=down → fail
                    rows = await _snmp_walk(ip, community, fan_oid, port)
                    if rows:
                        all_ok = all(int(v) in (2, 4) for _, v in rows if v.isdigit())
                        result['fan_status'] = 'ok' if all_ok else 'fail'
                elif vendor == 'juniper_junos':
                    # jnxOperatingState: 2=running, 5=runningAtFullSpeed → normal
                    descr_rows = await _snmp_walk(ip, community, oids.get('fan_descr', ''), port)
                    state_rows = await _snmp_walk(ip, community, fan_oid, port)
                    state_map = {idx: int(v) for idx, v in state_rows if v.isdigit()}
                    fan_ok = True
                    for idx, desc in descr_rows:
                        desc_lower = desc.lower()
                        if 'fan' in desc_lower and idx in state_map:
                            if state_map[idx] not in (2, 3, 5):  # 2=running, 3=ready, 5=fullSpeed
                                fan_ok = False
                    if descr_rows:
                        result['fan_status'] = 'ok' if fan_ok else 'fail'
                elif vendor == 'arista_eos':
                    # ENTITY-SENSOR-MIB: filter type=10 (rpm), value > 0 means spinning
                    type_oid = oids.get('fan_type')
                    if type_oid:
                        type_rows = await _snmp_walk(ip, community, type_oid, port)
                        value_rows = await _snmp_walk(ip, community, fan_oid, port)
                        value_map = {idx: v for idx, v in value_rows}
                        fan_entries = [(idx, value_map.get(idx, '0')) for idx, t in type_rows if t == '10']
                        if fan_entries:
                            all_ok = all(v.isdigit() and int(v) > 0 for _, v in fan_entries)
                            result['fan_status'] = 'ok' if all_ok else 'fail'
                else:
                    # Cisco IOS/Huawei/H3C: 1 = normal
                    rows = await _snmp_walk(ip, community, fan_oid, port)
                    if rows:
                        all_ok = all(int(v) == 1 for _, v in rows if v.isdigit())
                        result['fan_status'] = 'ok' if all_ok else 'fail'

            # ── PSU ──
            psu_oid = oids.get('psu')
            if psu_oid:
                if vendor == 'cisco_nxos' or vendor == 'cisco_iosxr':
                    # cefcFRUPowerOperStatus: 2=on → normal; 3=offAdmin, etc → fail
                    rows = await _snmp_walk(ip, community, psu_oid, port)
                    if rows:
                        on_count = sum(1 for _, v in rows if v.isdigit() and int(v) == 2)
                        if on_count >= 2:
                            result['psu_status'] = 'redundant'
                        elif on_count == 1:
                            result['psu_status'] = 'single'
                        else:
                            result['psu_status'] = 'fail'
                elif vendor == 'juniper_junos':
                    # jnxOperatingState for Power Supply / PEM entries: 2=running, 5=fullSpeed
                    descr_rows = await _snmp_walk(ip, community, oids.get('psu_descr', ''), port)
                    state_rows = await _snmp_walk(ip, community, psu_oid, port)
                    state_map = {idx: int(v) for idx, v in state_rows if v.isdigit()}
                    psu_ok_count = 0
                    for idx, desc in descr_rows:
                        desc_lower = desc.lower()
                        if ('power' in desc_lower or 'pem' in desc_lower) and idx in state_map:
                            if state_map[idx] in (2, 3, 5):  # running/ready/fullSpeed
                                psu_ok_count += 1
                    if psu_ok_count >= 2:
                        result['psu_status'] = 'redundant'
                    elif psu_ok_count == 1:
                        result['psu_status'] = 'single'
                    elif descr_rows:
                        result['psu_status'] = 'fail'
                elif vendor == 'arista_eos':
                    # ENTITY-SENSOR-MIB type=3 (voltsAC/DC) — non-zero = PSU present and active
                    type_oid = oids.get('psu_type')
                    if type_oid:
                        type_rows = await _snmp_walk(ip, community, type_oid, port)
                        value_rows = await _snmp_walk(ip, community, psu_oid, port)
                        value_map = {idx: v for idx, v in value_rows}
                        psu_entries = [(idx, value_map.get(idx, '0')) for idx, t in type_rows if t == '3']
                        on_count = sum(1 for _, v in psu_entries if v.isdigit() and int(v) > 0)
                        if on_count >= 2:
                            result['psu_status'] = 'redundant'
                        elif on_count == 1:
                            result['psu_status'] = 'single'
                        elif psu_entries:
                            result['psu_status'] = 'fail'
                else:
                    # Cisco IOS / Huawei / H3C: 1 = normal
                    rows = await _snmp_walk(ip, community, psu_oid, port)
                    if rows:
                        normal_count = sum(1 for _, v in rows if v.isdigit() and int(v) == 1)
                        if normal_count >= 2:
                            result['psu_status'] = 'redundant'
                        elif normal_count == 1:
                            result['psu_status'] = 'single'
                        else:
                            result['psu_status'] = 'fail'
        # Model-scoped hardware definitions use the same typed collector as
        # CPU/memory. Built-in vendor logic above remains the fallback when
        # no model definition exists; a configured definition always wins,
        # including a deliberate None on a failed probe.
        for metric, result_key in (
            ('temperature', 'temp'),
            ('fan', 'fan_status'),
            ('power_supply', 'psu_status'),
            ('storage', 'storage_usage'),
            ('voltage', 'voltage'),
            ('power', 'power_watts'),
        ):
            definition = configured_metrics.get(metric)
            if not definition:
                continue
            detail = await _collect_metric_definition(
                ip,
                community,
                definition,
                port,
                device_id=device_id,
                profile_id=metric_profile_id,
                metric_name=metric,
            )
            result['metric_details'][metric] = detail
            result['hardware_metrics'][metric] = detail.get('value')
            result[result_key] = detail.get('value')
    except Exception as e:
        logger.warning(f"SNMP metrics collection failed for {ip}: {e}")

    def _status_to_bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        normalized = str(value or '').strip().casefold()
        if normalized in {'ok', 'normal', 'redundant', 'single', 'up', 'running', 'ready'}:
            return True
        if normalized in {'fail', 'failed', 'warning', 'down', 'offline', 'alarm'}:
            return False
        return None

    # Legacy built-in collectors historically returned labels such as
    # "redundant" and "fail". Normalize them at the boundary so every
    # status metric has the same true=normal / false=abnormal contract.
    result['fan_status'] = _status_to_bool(result.get('fan_status'))
    result['psu_status'] = _status_to_bool(result.get('psu_status'))

    # ── HR-MIB fallback (HOST-RESOURCES-MIB, RFC 2790) ──────────────────────
    # 当厂商私有 OID 无法访问时（SNMP view 限制等），用标准 MIB 兜底
    if result['cpu_usage'] is None and 'cpu' not in configured_metrics:
        try:
            rows = await _snmp_walk(ip, community, HR_PROCESSOR_LOAD, port)
            if rows:
                vals = [int(v) for _, v in rows if v.isdigit()]
                if vals:
                    result['cpu_usage'] = int(sum(vals) / len(vals))
        except Exception:
            pass

    if result['memory_usage'] is None and 'memory' not in configured_metrics:
        try:
            used_rows = await _snmp_walk(ip, community, HR_STORAGE_USED, port)
            size_rows = await _snmp_walk(ip, community, HR_STORAGE_SIZE, port)
            if used_rows and size_rows:
                size_map = {idx: int(v) for idx, v in size_rows if v.isdigit() and int(v) > 0}
                used_map = {idx: int(v) for idx, v in used_rows if v.isdigit()}
                # 选 size 最大的条目——路由器/交换机上通常就是物理内存
                best_idx = max(size_map, key=lambda k: size_map[k]) if size_map else None
                if best_idx and best_idx in used_map and size_map[best_idx] > 0:
                    result['memory_usage'] = int(used_map[best_idx] / size_map[best_idx] * 100)
        except Exception:
            pass

    for metric, result_key in (
        ('cpu', 'cpu_usage'),
        ('memory', 'memory_usage'),
        ('temperature', 'temp'),
        ('fan', 'fan_status'),
        ('power_supply', 'psu_status'),
        ('storage', 'storage_usage'),
        ('voltage', 'voltage'),
        ('power', 'power_watts'),
    ):
        result['hardware_metrics'].setdefault(metric, result.get(result_key))

    _set_result_cache(cache_key, result)
    return result


async def collect_interface_data(
    ip: str,
    community: str = 'public',
    port: int = 161,
    interface_config: Mapping[str, Any] | None = None,
) -> list[dict]:
    """
    Collect interface table via standard IF-MIB (works for all vendors).
    Returns: [{ name, status, speed_mbps, in_octets, out_octets, description }, ...]

    Performance: after obtaining interface index (ifName), all remaining OID
    walks are issued in parallel via asyncio.gather to reduce per-device
    collection latency. Uses GetBulk to drastically reduce UDP packets.
    """
    config = normalize_interface_config(interface_config) if interface_config else dict(DEFAULT_INTERFACE_CONFIG)
    if not config.get('enabled', True):
        config = dict(DEFAULT_INTERFACE_CONFIG)
    community_token = hashlib.sha256(str(community or '').encode('utf-8')).hexdigest()[:12]
    config_token = hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    ).hexdigest()[:16]
    cache_key = f"intf:{ip}:{port}:{community_token}:{config_token}"
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
        (status_rows, hspeed_rows, speed_rows,
         hc_in_rows, hc_out_rows, alias_rows,
         in_err_rows, out_err_rows, in_disc_rows, out_disc_rows,
         in_ucast_rows, out_ucast_rows,
         sys_uptime_raw, lc_rows) = await asyncio.gather(
            _walk(config['if_oper_status_oid']),
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
            _snmp_get(ip, community, SYS_UPTIME, port),
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
            ('in_ucast_pkts', in_ucast_rows), ('out_ucast_pkts', out_ucast_rows),
        ]:
            for idx, val in rows:
                if idx in interfaces and val.isdigit():
                    interfaces[idx][oid_name] = int(val)

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
            name.startswith('vl') or name.startswith('vlan') or
            name.startswith('tu') or name.startswith('tunnel') or
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
            'counter_source': 'ifHCInOctets/ifHCOutOctets' if data.get('counter_width') == 64 else 'ifInOctets/ifOutOctets' if data.get('counter_width') == 32 else 'unavailable',
            'counter_quality': 'hc64_typed' if data.get('counter_width') == 64 else 'legacy32_typed' if data.get('counter_width') == 32 else 'counter_unavailable',
            'counter_mode': config['counter_mode'],
            'device_uptime_cs': data.get('device_uptime_cs'),
            'description': data.get('description', ''),
            'in_errors': data.get('in_errors', 0),
            'out_errors': data.get('out_errors', 0),
            'in_discards': data.get('in_discards', 0),
            'out_discards': data.get('out_discards', 0),
            'in_ucast_pkts': data.get('in_ucast_pkts', 0),
            'out_ucast_pkts': data.get('out_ucast_pkts', 0),
            'last_change_secs': data.get('last_change_secs'),
        })

    _set_result_cache(cache_key, result)
    return result


async def probe_interface_definition(
    ip: str,
    community: str,
    config: Mapping[str, Any] | None = None,
    port: int = 161,
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
    if not normalized.get('enabled', True):
        return {
            'passed': True,
            'status': 'disabled',
            'message': 'Interface profile is disabled; built-in IF-MIB mapping remains active',
            'checks': {},
            'counter_mode': normalized['counter_mode'],
            'interfaces': 0,
            'counter_supported': 0,
        }

    async def _walk(oid: str):
        if not oid:
            return []
        try:
            return await _snmp_bulk_walk(ip, community, oid, port)
        except Exception:
            return []

    async def _typed_walk(oid: str):
        if not oid:
            return []
        try:
            return await _snmp_bulk_walk_typed(ip, community, oid, port)
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
    mode = normalized['counter_mode']
    selected_width = 64 if mode == '64' and hc_pairs else 32 if mode == '32' and legacy_pairs else None
    if mode == 'auto':
        selected_width = 64 if hc_pairs else 32 if legacy_pairs else None
    selected_pairs = hc_pairs if selected_width == 64 else legacy_pairs if selected_width == 32 else set()
    checks = {
        'identity': {
            'oid': normalized['if_name_oid'] or normalized['if_descr_oid'],
            'passed': bool(identity_rows or descr_rows),
            'rows': len(identity_rows or descr_rows),
            'message': 'ifName/ifDescr table available' if (identity_rows or descr_rows) else 'No interface identity rows returned',
        },
        'oper_status': {'oid': normalized['if_oper_status_oid'], 'passed': bool(status_rows), 'rows': len(status_rows)},
        'high_speed': {'oid': normalized['if_high_speed_oid'], 'passed': bool(high_speed_rows), 'rows': len(high_speed_rows)},
        'speed': {'oid': normalized['if_speed_oid'], 'passed': bool(speed_rows), 'rows': len(speed_rows)},
        'alias': {'oid': normalized['if_alias_oid'], 'passed': bool(alias_rows), 'rows': len(alias_rows)},
        'last_change': {'oid': normalized['if_last_change_oid'], 'passed': bool(last_change_rows), 'rows': len(last_change_rows)},
        'in_errors': {'oid': normalized['if_in_errors_oid'], 'passed': bool(in_error_rows), 'rows': len(in_error_rows)},
        'out_errors': {'oid': normalized['if_out_errors_oid'], 'passed': bool(out_error_rows), 'rows': len(out_error_rows)},
        'in_discards': {'oid': normalized['if_in_discards_oid'], 'passed': bool(in_discard_rows), 'rows': len(in_discard_rows)},
        'out_discards': {'oid': normalized['if_out_discards_oid'], 'passed': bool(out_discard_rows), 'rows': len(out_discard_rows)},
        'in_ucast': {'oid': normalized['if_in_ucast_oid'], 'passed': bool(in_ucast_rows), 'rows': len(in_ucast_rows)},
        'out_ucast': {'oid': normalized['if_out_ucast_oid'], 'passed': bool(out_ucast_rows), 'rows': len(out_ucast_rows)},
        'counter64_in': {'oid': normalized['if_hc_in_octets_oid'], 'passed': bool(hc_in), 'rows': len(hc_in), 'counter_bits': 64},
        'counter64_out': {'oid': normalized['if_hc_out_octets_oid'], 'passed': bool(hc_out), 'rows': len(hc_out), 'counter_bits': 64},
        'counter32_in': {'oid': normalized['if_in_octets_oid'], 'passed': bool(legacy_in), 'rows': len(legacy_in), 'counter_bits': 32},
        'counter32_out': {'oid': normalized['if_out_octets_oid'], 'passed': bool(legacy_out), 'rows': len(legacy_out), 'counter_bits': 32},
    }
    passed = bool(identity_rows or descr_rows) and bool(selected_pairs)
    if passed:
        message = f'Interface table and paired Counter{selected_width} counters passed validation'
    elif not (identity_rows or descr_rows):
        message = 'Interface identity table validation failed'
    else:
        message = f'No paired Counter{mode if mode in {"32", "64"} else "32/64"} octet counters returned'
    return {
        'passed': passed,
        'status': 'ok' if passed else 'missing',
        'message': message,
        'checks': checks,
        'counter_mode': mode,
        'selected_counter_bits': selected_width,
        'interfaces': len(identity_rows or descr_rows),
        'counter_supported': len(selected_pairs),
    }


async def collect_interface_data_detailed(
    ip: str,
    community: str = 'public',
    port: int = 161,
    interface_config: Mapping[str, Any] | None = None,
) -> dict:
    """Return IF-MIB data with an explicit, secret-free collection outcome.

    The legacy collector intentionally returns a best-effort list for existing
    callers. WAN monitoring needs to distinguish a complete walk from a
    missing/partial walk so that a failed poll cannot be interpreted as an
    interface-down sample. This wrapper keeps the old API stable while adding
    the stricter contract for the WAN domain.
    """
    try:
        result = await collect_interface_data(ip, community, port, interface_config)
    except Exception as exc:  # pragma: no cover - defensive boundary
        message = str(exc).lower()
        status = 'auth_failed' if any(token in message for token in ('authentication', 'authorization', 'community')) else 'timeout' if 'timeout' in message else 'device_unreachable'
        return {'status': status, 'items': [], 'error_code': status, 'error_message': type(exc).__name__}
    if result:
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
