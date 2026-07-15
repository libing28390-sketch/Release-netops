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
import logging
import sys
import time as _time
from typing import Optional

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
_SNMP_CONCURRENCY = 30
_snmp_semaphore: asyncio.Semaphore | None = None
_snmp_semaphore_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_snmp_semaphore() -> asyncio.Semaphore:
    """Lazy-init semaphore bound to the current event loop."""
    global _snmp_semaphore, _snmp_semaphore_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.Semaphore(_SNMP_CONCURRENCY)
        
    if _snmp_semaphore is None or _snmp_semaphore_loop != current_loop:
        _snmp_semaphore = asyncio.Semaphore(_SNMP_CONCURRENCY)
        _snmp_semaphore_loop = current_loop
    return _snmp_semaphore


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


# ═══════════════════════════════════════════════════════════════
# puresnmp async helpers (replaces pysnmp — Python 3.13 compatible)
# ═══════════════════════════════════════════════════════════════

def _val_to_str(val) -> str:
    """Convert puresnmp value to a clean string."""
    if isinstance(val, bytes):
        return val.decode('utf-8', errors='replace').strip('\r\n \x00')
    return str(val).strip()


async def _snmp_get(ip: str, community: str, oid: str, port: int = 161, timeout: float = 3) -> Optional[str]:
    """GET a single OID value via puresnmp (SNMPv2c)."""
    sem = _get_snmp_semaphore()
    async with sem:
      try:
        from puresnmp import Client, V2C, PyWrapper
        client = PyWrapper(Client(ip, V2C(community), port=port))
        result = await asyncio.wait_for(client.get(oid), timeout=timeout)
        if result is None:
            return None
        v = _val_to_str(result)
        if v and 'noSuchObject' not in v and 'noSuchInstance' not in v:
            return v
      except Exception as e:
        logger.debug(f"SNMP GET {ip} {oid} failed: {e}")
      return None


async def _snmp_walk(ip: str, community: str, oid: str, port: int = 161, timeout: float = 5, max_rows: int = 200) -> list[tuple[str, str]]:
    """Walk an OID subtree via puresnmp, return list of (oid_suffix, value)."""
    results: list[tuple[str, str]] = []
    base_oid = oid.rstrip('.')
    sem = _get_snmp_semaphore()

    async def _collect():
        from puresnmp import Client, V2C, PyWrapper
        client = PyWrapper(Client(ip, V2C(community), port=port))
        async for varbind in client.walk(base_oid):
            oid_str = str(varbind.oid)
            suffix = oid_str[len(base_oid) + 1:] if oid_str.startswith(base_oid + '.') else oid_str
            v = _val_to_str(varbind.value)
            if 'endOfMibView' in v:
                return
            results.append((suffix, v))
            if len(results) >= max_rows:
                return

    async with sem:
      try:
        await asyncio.wait_for(_collect(), timeout=timeout)
      except asyncio.TimeoutError:
        logger.debug(f"SNMP WALK {ip} {oid} timeout after {timeout}s ({len(results)} rows collected)")
      except Exception as e:
        logger.debug(f"SNMP WALK {ip} {oid} failed: {e}")
    return results


async def _snmp_bulk_walk(ip: str, community: str, oid: str, port: int = 161, timeout: float = 5, max_repetitions: int = 20) -> list[tuple[str, str]]:
    """Bulk Walk an OID subtree via puresnmp, using GETBULK for high performance."""
    results: list[tuple[str, str]] = []
    base_oid = oid.rstrip('.')
    sem = _get_snmp_semaphore()

    async def _collect():
        from puresnmp import Client, V2C, PyWrapper
        client = PyWrapper(Client(ip, V2C(community), port=port))
        # bulkwalk significantly reduces UDP round-trips
        async for varbind in client.bulkwalk([base_oid], bulk_size=max_repetitions):
            oid_str = str(varbind.oid)
            suffix = oid_str[len(base_oid) + 1:] if oid_str.startswith(base_oid + '.') else oid_str
            v = _val_to_str(varbind.value)
            if 'endOfMibView' in v:
                return
            results.append((suffix, v))

    async with sem:
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


async def collect_device_metrics(ip: str, platform: str, community: str = 'public', port: int = 161) -> dict:
    """
    Collect CPU, memory, temp, fan, PSU from a single device.
    Returns dict with keys: cpu_usage, memory_usage, temp, fan_status, psu_status
    Falls back to None for any value that fails.
    """
    cache_key = f"metrics:{ip}:{port}"
    cached = _get_result_cache(cache_key)
    if cached is not None:
        return cached
    vendor = _resolve_platform(platform)
    oids = VENDOR_OIDS.get(vendor, VENDOR_OIDS['cisco_ios'])
    result = {'cpu_usage': None, 'memory_usage': None, 'temp': None, 'fan_status': None, 'psu_status': None}

    try:
        # ── CPU ──
        if vendor in ('arista_eos',):
            # Arista: walk hrProcessorLoad, average all cores
            rows = await _snmp_walk(ip, community, oids['cpu'], port)
            if rows:
                vals = [int(v) for _, v in rows if v.isdigit()]
                result['cpu_usage'] = int(sum(vals) / len(vals)) if vals else None
        elif vendor in ('huawei_vrp', 'h3c_comware', 'juniper_junos'):
            # Walk: first non-zero entry (usually the main board / RE)
            rows = await _snmp_walk(ip, community, oids['cpu'], port)
            if rows:
                for _, v in rows:
                    if v.isdigit() and int(v) > 0:
                        result['cpu_usage'] = int(v)
                        break
        else:
            # Cisco IOS/NX-OS/IOS-XR: GET first instance
            rows = await _snmp_walk(ip, community, oids['cpu'], port)
            if rows:
                for _, v in rows:
                    if v.isdigit():
                        result['cpu_usage'] = int(v)
                        break

        # ── Memory ──
        if vendor == 'cisco_nxos':
            # NX-OS: cseSysMemoryUtilization returns percentage directly
            mem_pct_oid = oids.get('mem_pct')
            if mem_pct_oid:
                val = await _snmp_get(ip, community, mem_pct_oid, port)
                if val and val.isdigit():
                    result['memory_usage'] = int(val)
        elif vendor in ('huawei_vrp', 'h3c_comware', 'juniper_junos', 'fortinet_fortios'):
            # Direct percentage OID
            mem_oid = oids.get('mem')
            if mem_oid:
                rows = await _snmp_walk(ip, community, mem_oid, port)
                if rows:
                    for _, v in rows:
                        if v.isdigit() and int(v) > 0:
                            result['memory_usage'] = int(v)
                            break
        elif vendor == 'arista_eos':
            # hrStorage: find "Physical Memory" / "RAM" entry by description
            descr_rows = await _snmp_walk(ip, community, oids['mem_descr'], port)
            used_rows = await _snmp_walk(ip, community, oids['mem_used'], port)
            size_rows = await _snmp_walk(ip, community, oids['mem_size'], port)
            used_map = {idx: int(v) for idx, v in used_rows if v.isdigit()}
            size_map = {idx: int(v) for idx, v in size_rows if v.isdigit()}
            ram_idx = None
            for idx, desc in descr_rows:
                desc_lower = desc.lower()
                if 'physical' in desc_lower or 'ram' in desc_lower or 'real' in desc_lower:
                    ram_idx = idx
                    break
            # Fallback: pick the largest storage entry
            if ram_idx is None and size_map:
                ram_idx = max(size_map, key=lambda k: size_map[k])
            if ram_idx and ram_idx in used_map and ram_idx in size_map and size_map[ram_idx] > 0:
                result['memory_usage'] = int((used_map[ram_idx] / size_map[ram_idx]) * 100)
        elif vendor in ('cisco_ios', 'cisco_iosxr'):
            # Cisco IOS/XE: try CEMP (enhanced) first, fallback to legacy CISCO-MEMORY-POOL-MIB
            used_raw = None
            free_raw = None
            cemp_used = oids.get('mem_used_enhanced')
            cemp_free = oids.get('mem_free_enhanced')
            if cemp_used and cemp_free:
                used_raw = await _snmp_walk(ip, community, cemp_used, port)
                free_raw = await _snmp_walk(ip, community, cemp_free, port)
            if not used_raw or not free_raw:
                # Fallback to legacy OIDs
                used_raw = await _snmp_walk(ip, community, oids['mem_used'], port)
                free_raw = await _snmp_walk(ip, community, oids['mem_free'], port)
            if used_raw and free_raw:
                used = int(used_raw[0][1]) if used_raw[0][1].isdigit() else 0
                free = int(free_raw[0][1]) if free_raw[0][1].isdigit() else 0
                total = used + free
                if total > 0:
                    result['memory_usage'] = int((used / total) * 100)
        else:
            # Generic Cisco fallback: used / (used + free)
            used_raw = await _snmp_walk(ip, community, oids.get('mem_used', ''), port)
            free_raw = await _snmp_walk(ip, community, oids.get('mem_free', ''), port)
            if used_raw and free_raw:
                used = int(used_raw[0][1]) if used_raw[0][1].isdigit() else 0
                free = int(free_raw[0][1]) if free_raw[0][1].isdigit() else 0
                total = used + free
                if total > 0:
                    result['memory_usage'] = int((used / total) * 100)

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
    except Exception as e:
        logger.warning(f"SNMP metrics collection failed for {ip}: {e}")

    # ── HR-MIB fallback (HOST-RESOURCES-MIB, RFC 2790) ──────────────────────
    # 当厂商私有 OID 无法访问时（SNMP view 限制等），用标准 MIB 兜底
    if result['cpu_usage'] is None:
        try:
            rows = await _snmp_walk(ip, community, HR_PROCESSOR_LOAD, port)
            if rows:
                vals = [int(v) for _, v in rows if v.isdigit()]
                if vals:
                    result['cpu_usage'] = int(sum(vals) / len(vals))
        except Exception:
            pass

    if result['memory_usage'] is None:
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

    _set_result_cache(cache_key, result)
    return result


async def collect_interface_data(ip: str, community: str = 'public', port: int = 161) -> list[dict]:
    """
    Collect interface table via standard IF-MIB (works for all vendors).
    Returns: [{ name, status, speed_mbps, in_octets, out_octets, description }, ...]

    Performance: after obtaining interface index (ifName), all remaining OID
    walks are issued in parallel via asyncio.gather to reduce per-device
    collection latency. Uses GetBulk to drastically reduce UDP packets.
    """
    cache_key = f"intf:{ip}:{port}"
    cached = _get_result_cache(cache_key)
    if cached is not None:
        return cached

    interfaces = {}
    try:
        # Step 1: ifName (preferred) or ifDescr — must be first to build index
        name_rows = await _snmp_bulk_walk(ip, community, IF_NAME, port)
        if not name_rows:
            name_rows = await _snmp_bulk_walk(ip, community, IF_DESCR, port)
        for idx, val in name_rows:
            interfaces[idx] = {'name': val, 'index': idx}

        # Step 2: Parallel fetch of all independent OIDs using GetBulk
        (status_rows, hspeed_rows, speed_rows,
         hc_in_rows, hc_out_rows, alias_rows,
         in_err_rows, out_err_rows, in_disc_rows, out_disc_rows,
         in_ucast_rows, out_ucast_rows,
         sys_uptime_raw, lc_rows) = await asyncio.gather(
            _snmp_bulk_walk(ip, community, IF_OPER_STATUS, port),
            _snmp_bulk_walk(ip, community, IF_HIGH_SPEED, port),
            _snmp_bulk_walk(ip, community, IF_SPEED, port),
            _snmp_bulk_walk(ip, community, IF_HC_IN, port),
            _snmp_bulk_walk(ip, community, IF_HC_OUT, port),
            _snmp_bulk_walk(ip, community, IF_ALIAS, port),
            _snmp_bulk_walk(ip, community, IF_IN_ERRORS, port),
            _snmp_bulk_walk(ip, community, IF_OUT_ERRORS, port),
            _snmp_bulk_walk(ip, community, IF_IN_DISCARDS, port),
            _snmp_bulk_walk(ip, community, IF_OUT_DISCARDS, port),
            _snmp_bulk_walk(ip, community, IF_IN_UCAST, port),
            _snmp_bulk_walk(ip, community, IF_OUT_UCAST, port),
            _snmp_get(ip, community, SYS_UPTIME, port),
            _snmp_bulk_walk(ip, community, IF_LAST_CHANGE, port),
        )

        # HC counter fallback: if 64-bit counters empty, try 32-bit
        in_rows = hc_in_rows
        out_rows = hc_out_rows
        if not in_rows or not out_rows:
            fb_in, fb_out = await asyncio.gather(
                _snmp_bulk_walk(ip, community, IF_IN_OCTETS, port) if not in_rows else asyncio.sleep(0, result=in_rows),
                _snmp_bulk_walk(ip, community, IF_OUT_OCTETS, port) if not out_rows else asyncio.sleep(0, result=out_rows),
            )
            if not in_rows:
                in_rows = fb_in
            if not out_rows:
                out_rows = fb_out

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

        # Octets
        for idx, val in in_rows:
            if idx in interfaces and val.isdigit():
                interfaces[idx]['in_octets'] = int(val)
        for idx, val in out_rows:
            if idx in interfaces and val.isdigit():
                interfaces[idx]['out_octets'] = int(val)

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
            'status': data.get('status', 'unknown'),
            'speed_mbps': data.get('speed_mbps', 0),
            'in_octets': data.get('in_octets', 0),
            'out_octets': data.get('out_octets', 0),
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
