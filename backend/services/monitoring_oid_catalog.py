"""Built-in SNMP OID catalog used by the Monitoring V1 control plane.

The catalog deliberately keeps the standard IF-MIB/System MIB collection in a
single baseline plan.  Vendor-specific OIDs are additional *module variants*
selected by the device vendor/platform; they are not additional collection
plans.  Numeric OIDs are used in the generated exporter config so deployment
does not depend on a particular MIB search path.  ``mib_sources`` and
``source_name`` remain in the persisted metadata for operators and audits.

The vendor entries are a conservative common denominator.  A device may not
implement every enterprise object, so the UI and docs describe them as
"常用/可选" and production validation must still be done against the device's
own MIB support.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


OID_CATALOG_VERSION = "2026.09.17"


def _indexes(*labels: str) -> list[dict[str, str]]:
    return [{"labelname": label, "type": "gauge"} for label in labels]


def _metric(
    name: str,
    oid: str,
    metric_type: str,
    help_text: str,
    *,
    source_name: str = "",
    indexes: tuple[str, ...] = (),
    scale: float | None = None,
    enum_values: dict[int, str] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": name,
        "oid": oid,
        "type": metric_type,
        "help": help_text,
    }
    if source_name:
        item["source_name"] = source_name
    if indexes:
        item["indexes"] = _indexes(*indexes)
    if scale is not None:
        item["scale"] = scale
    if enum_values:
        item["enum_values"] = enum_values
    return item


_IF_INDEX = ("ifIndex",)
_ENTITY_INDEX = ("entity_index",)
_FLASH_PARTITION_INDEX = ("flash_index", "partition_index")
_FAN_INDEX = ("fan_index",)
_POWER_INDEX = ("power_index",)

_H3C_STATUS_VALUES = {
    1: "active",
    2: "deactive",
    3: "not-install",
    4: "unsupport",
}

_H3C_ENTITY_OPER_STATUS_VALUES = {
    1: "notSupported",
    2: "disabled",
    3: "enabled",
    4: "dangerous",
}

_H3C_ENTITY_ERROR_STATUS_VALUES = {
    1: "notSupported",
    2: "normal",
    3: "postFailure",
    4: "entityAbsent",
    11: "poeError",
    21: "stackError",
    22: "stackPortBlocked",
    23: "stackPortFailed",
    31: "sfpRecvError",
    32: "sfpSendError",
    33: "sfpBothError",
    41: "fanError",
    51: "psuError",
    61: "rpsError",
    71: "moduleFaulty",
    81: "sensorError",
    91: "hardwareFaulty",
}

_H3C_FLASH_PART_STATUS_VALUES = {
    1: "readOnly",
    2: "runFromFlash",
    3: "readWrite",
}


STANDARD_INTERFACE_METRICS = [
    _metric("ifMtu", "1.3.6.1.2.1.2.2.1.4", "gauge", "Maximum transmission unit of the interface.", source_name="ifMtu", indexes=_IF_INDEX),
    _metric("ifSpeed", "1.3.6.1.2.1.2.2.1.5", "gauge", "Interface speed in bits per second (32-bit value).", source_name="ifSpeed", indexes=_IF_INDEX),
    _metric("ifType", "1.3.6.1.2.1.2.2.1.3", "gauge", "Interface type enumeration.", source_name="ifType", indexes=_IF_INDEX),
    _metric("ifAdminStatus", "1.3.6.1.2.1.2.2.1.7", "gauge", "Administrative state of the interface.", source_name="ifAdminStatus", indexes=_IF_INDEX),
    _metric("ifOperStatus", "1.3.6.1.2.1.2.2.1.8", "gauge", "Operational state of the interface.", source_name="ifOperStatus", indexes=_IF_INDEX),
    _metric("ifInDiscards", "1.3.6.1.2.1.2.2.1.13", "counter", "Inbound packets discarded.", source_name="ifInDiscards", indexes=_IF_INDEX),
    _metric("ifInErrors", "1.3.6.1.2.1.2.2.1.14", "counter", "Inbound packets with errors.", source_name="ifInErrors", indexes=_IF_INDEX),
    _metric("ifInOctets", "1.3.6.1.2.1.2.2.1.10", "counter", "Inbound octets using the 32-bit interface counter.", source_name="ifInOctets", indexes=_IF_INDEX),
    _metric("ifOutDiscards", "1.3.6.1.2.1.2.2.1.19", "counter", "Outbound packets discarded.", source_name="ifOutDiscards", indexes=_IF_INDEX),
    _metric("ifOutErrors", "1.3.6.1.2.1.2.2.1.20", "counter", "Outbound packets with errors.", source_name="ifOutErrors", indexes=_IF_INDEX),
    _metric("ifOutOctets", "1.3.6.1.2.1.2.2.1.16", "counter", "Outbound octets using the 32-bit interface counter.", source_name="ifOutOctets", indexes=_IF_INDEX),
    _metric("ifName", "1.3.6.1.2.1.31.1.1.1.1", "DisplayString", "Interface name.", source_name="ifName", indexes=_IF_INDEX),
    _metric("ifHighSpeed", "1.3.6.1.2.1.31.1.1.1.15", "gauge", "Interface speed in millions of bits per second.", source_name="ifHighSpeed", indexes=_IF_INDEX),
    _metric("ifHCInOctets", "1.3.6.1.2.1.31.1.1.1.6", "counter", "Inbound octets using the high-capacity counter.", source_name="ifHCInOctets", indexes=_IF_INDEX),
    _metric("ifHCInUcastPkts", "1.3.6.1.2.1.31.1.1.1.7", "counter", "Inbound unicast packets using the high-capacity counter.", source_name="ifHCInUcastPkts", indexes=_IF_INDEX),
    _metric("ifHCInMulticastPkts", "1.3.6.1.2.1.31.1.1.1.8", "counter", "Inbound multicast packets using the high-capacity counter.", source_name="ifHCInMulticastPkts", indexes=_IF_INDEX),
    _metric("ifHCInBroadcastPkts", "1.3.6.1.2.1.31.1.1.1.9", "counter", "Inbound broadcast packets using the high-capacity counter.", source_name="ifHCInBroadcastPkts", indexes=_IF_INDEX),
    _metric("ifHCOutOctets", "1.3.6.1.2.1.31.1.1.1.10", "counter", "Outbound octets using the high-capacity counter.", source_name="ifHCOutOctets", indexes=_IF_INDEX),
    _metric("ifHCOutUcastPkts", "1.3.6.1.2.1.31.1.1.1.11", "counter", "Outbound unicast packets using the high-capacity counter.", source_name="ifHCOutUcastPkts", indexes=_IF_INDEX),
    _metric("ifHCOutMulticastPkts", "1.3.6.1.2.1.31.1.1.1.12", "counter", "Outbound multicast packets using the high-capacity counter.", source_name="ifHCOutMulticastPkts", indexes=_IF_INDEX),
    _metric("ifHCOutBroadcastPkts", "1.3.6.1.2.1.31.1.1.1.13", "counter", "Outbound broadcast packets using the high-capacity counter.", source_name="ifHCOutBroadcastPkts", indexes=_IF_INDEX),
    _metric("ifPhysAddress", "1.3.6.1.2.1.2.2.1.6", "OctetString", "Interface physical address.", source_name="ifPhysAddress", indexes=_IF_INDEX),
    _metric("ifAlias", "1.3.6.1.2.1.31.1.1.1.18", "DisplayString", "Interface alias/description.", source_name="ifAlias", indexes=_IF_INDEX),
    _metric("dot3StatsFCSErrors", "1.3.6.1.2.1.10.7.2.1.3", "counter", "Ethernet frames received with FCS errors.", source_name="dot3StatsFCSErrors", indexes=_IF_INDEX),
]


STANDARD_INTERFACE_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["IF-MIB (RFC 2863)", "IF-MIB::interfaces", "IF-MIB::ifXTable"],
    "walk": ["1.3.6.1.2.1.2.2", "1.3.6.1.2.1.31.1.1", "1.3.6.1.2.1.10.7.2.1"],
    "get": ["1.3.6.1.2.1.1.3.0", "1.3.6.1.2.1.1.5.0"],
    "metrics": STANDARD_INTERFACE_METRICS,
}


STANDARD_SYSTEM_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["SNMPv2-MIB (RFC 3418)"],
    "walk": ["1.3.6.1.2.1.1"],
    "get": [
        "1.3.6.1.2.1.1.1.0",
        "1.3.6.1.2.1.1.3.0",
        "1.3.6.1.2.1.1.5.0",
        "1.3.6.1.2.1.1.6.0",
        "1.3.6.1.2.1.1.4.0",
        "1.3.6.1.2.1.1.2.0",
    ],
    "metrics": [
        _metric("sysUpTime", "1.3.6.1.2.1.1.3", "gauge", "Time since the network management portion of the system was last re-initialized.", source_name="sysUpTime"),
        _metric("sysDescr", "1.3.6.1.2.1.1.1", "DisplayString", "Textual description of the managed device.", source_name="sysDescr"),
        _metric("sysName", "1.3.6.1.2.1.1.5", "DisplayString", "Administratively assigned name of the managed device.", source_name="sysName"),
        _metric("sysLocation", "1.3.6.1.2.1.1.6", "DisplayString", "Physical location of the managed device.", source_name="sysLocation"),
        _metric("sysContact", "1.3.6.1.2.1.1.4", "DisplayString", "Contact person for the managed device.", source_name="sysContact"),
        _metric("sysObjectID", "1.3.6.1.2.1.1.2", "DisplayString", "Vendor authoritative identification of the network management subsystem.", source_name="sysObjectID"),
    ],
}


def _variant(
    variant_id: str,
    variant_key: str,
    display_name: str,
    oid_config: dict[str, Any],
    *,
    max_repetitions: int = 25,
    retries: int = 2,
    request_timeout_ms: int = 3000,
    scrape_timeout_ms: int = 20000,
    mib_bundle_id: str,
    supported_platforms: list[str] | None = None,
    supported_models: list[str] | None = None,
    supported_version_scope: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": variant_id,
        "variant_key": variant_key,
        "display_name": display_name,
        "max_repetitions": max_repetitions,
        "retries": retries,
        "request_timeout_ms": request_timeout_ms,
        "scrape_timeout_ms": scrape_timeout_ms,
        "supported_platforms": supported_platforms or [],
        "supported_models": supported_models or [],
        "supported_version_scope": supported_version_scope or [],
        "verified_models": [],
        "verified_versions": [],
        "mib_bundle_id": mib_bundle_id,
        "generator_version": f"snmp_exporter-config-v1/{OID_CATALOG_VERSION}",
        "status": "PUBLISHED",
        "enabled": True,
        "oid_config": oid_config,
    }


def _module(
    module_id: str,
    module_key: str,
    display_name: str,
    vendor: str,
    cli_platform: str,
    feature_domain: str,
    metric_group: str,
    walk_fingerprint: str,
    description: str,
    variant: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": module_id,
        "module_key": module_key,
        "display_name": display_name,
        "vendor": vendor,
        "cli_platform": cli_platform,
        "feature_domain": feature_domain,
        "metric_group": metric_group,
        "walk_fingerprint": walk_fingerprint,
        "description": description,
        "enabled": True,
        "built_in": True,
        "variant": variant,
    }


H3C_ENTITY_CONFIG = {
    "schema_version": "1",
    "mib_sources": [
        "HH3C-ENTITY-EXT-MIB",
        "HH3C-COMMON-SYSTEM-MIB",
        "HH3C-FLASH-MAN-MIB",
        "HH3C-LswDEVM-MIB",
        "HH3C-LswINF-MIB",
        "ENTITY-MIB (RFC 4133)",
    ],
    "source_urls": [
        "https://www.h3c.com/en/d_202307/1893238_294551_0.htm",
        "https://www.h3c.com/cn/d_202504/2413109_30005_0.htm",
        "https://www.h3c.com/en/d_202603/2774537_294551_0.htm",
        "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Reference_Guides/MIB_Companion/H3C_S6800_S6860_Switch_Series_MIB_Compan-9728/03/202303/1808889_294551_0.htm",
    ],
    "walk": [
        "1.3.6.1.4.1.25506.2.6.1.1.1.1",
        "1.3.6.1.4.1.25506.2.6.1.2.1.1",
        "1.3.6.1.4.1.25506.2.6.1.3.1.1",
        "1.3.6.1.4.1.25506.2.5.1.1.4.1.1",
        "1.3.6.1.4.1.25506.8.35.9.1.1.1",
        "1.3.6.1.4.1.25506.8.35.9.1.2.1",
        "1.3.6.1.2.1.47.1.1.1.1.7",
        "1.3.6.1.2.1.47.1.1.1.1.10",
        "1.3.6.1.2.1.47.1.1.1.1.11",
    ],
    "get": ["1.3.6.1.4.1.25506.8.35.5.1.12"],
    "metrics": [
        _metric("hh3cEntityExtCpuUsage", "1.3.6.1.4.1.25506.2.6.1.1.1.1.6", "gauge", "CPU usage for the H3C entity (5-second sample).", source_name="hh3cEntityExtCpuUsage", indexes=_ENTITY_INDEX),
        _metric("hh3cEntityExtCpuMaxUsage", "1.3.6.1.4.1.25506.2.6.1.1.1.1.20", "gauge", "Peak CPU usage during the most recent one-minute interval.", source_name="hh3cEntityExtCpuMaxUsage", indexes=_ENTITY_INDEX),
        _metric("hh3cEntityExtCpuAvgUsage", "1.3.6.1.4.1.25506.2.6.1.1.1.1.26", "gauge", "Average CPU usage for the H3C entity.", source_name="hh3cEntityExtCpuAvgUsage", indexes=_ENTITY_INDEX),
        _metric("hh3cEntityExtCpuUsageIn1Minute", "1.3.6.1.4.1.25506.2.6.1.1.1.1.33", "gauge", "Average CPU usage during the most recent one-minute interval.", source_name="hh3cEntityExtCpuUsageIn1Minute", indexes=_ENTITY_INDEX),
        _metric("hh3cEntityExtCpuUsageIn5Minutes", "1.3.6.1.4.1.25506.2.6.1.1.1.1.34", "gauge", "Average CPU usage during the most recent five-minute interval.", source_name="hh3cEntityExtCpuUsageIn5Minutes", indexes=_ENTITY_INDEX),
        _metric("hh3cEntityExtMemUsage", "1.3.6.1.4.1.25506.2.6.1.1.1.1.8", "gauge", "Memory usage for the H3C entity in percent.", source_name="hh3cEntityExtMemUsage", indexes=_ENTITY_INDEX),
        _metric("hh3cEntityExtMemAvgUsage", "1.3.6.1.4.1.25506.2.6.1.1.1.1.27", "gauge", "Average memory usage for the H3C entity.", source_name="hh3cEntityExtMemAvgUsage", indexes=_ENTITY_INDEX),
        _metric("hh3cEntityExtMemSize", "1.3.6.1.4.1.25506.2.6.1.1.1.1.10", "gauge", "Memory size for the H3C entity in bytes.", source_name="hh3cEntityExtMemSize", indexes=_ENTITY_INDEX),
        _metric("hh3cEntityExtMemSizeRev", "1.3.6.1.4.1.25506.2.6.1.1.1.1.32", "gauge", "64-bit memory size for the H3C entity in bytes.", source_name="hh3cEntityExtMemSizeRev", indexes=_ENTITY_INDEX),
        _metric("hh3cEntityExtTemperature", "1.3.6.1.4.1.25506.2.6.1.1.1.1.12", "gauge", "Temperature of the H3C entity.", source_name="hh3cEntityExtTemperature", indexes=_ENTITY_INDEX),
        _metric("hh3cEntityExtOperStatus", "1.3.6.1.4.1.25506.2.6.1.1.1.1.3", "EnumAsInfo", "Operational status of the H3C entity.", source_name="hh3cEntityExtOperStatus", indexes=_ENTITY_INDEX, enum_values=_H3C_ENTITY_OPER_STATUS_VALUES),
        _metric("hh3cEntityExtErrorStatus", "1.3.6.1.4.1.25506.2.6.1.1.1.1.19", "EnumAsInfo", "Error status of the H3C entity.", source_name="hh3cEntityExtErrorStatus", indexes=_ENTITY_INDEX, enum_values=_H3C_ENTITY_ERROR_STATUS_VALUES),
        _metric("entPhysicalName", "1.3.6.1.2.1.47.1.1.1.1.7", "DisplayString", "Physical entity name used to identify H3C CPU, module and sensor rows.", source_name="entPhysicalName", indexes=_ENTITY_INDEX),
        _metric("entPhysicalHardwareRev", "1.3.6.1.2.1.47.1.1.1.1.10", "DisplayString", "Hardware revision of the H3C physical entity.", source_name="entPhysicalHardwareRev", indexes=_ENTITY_INDEX),
        _metric("entPhysicalFirmwareRev", "1.3.6.1.2.1.47.1.1.1.1.11", "DisplayString", "Firmware revision of the H3C physical entity.", source_name="entPhysicalFirmwareRev", indexes=_ENTITY_INDEX),
        _metric("hh3cEntityExtUpTime", "1.3.6.1.4.1.25506.2.6.1.1.1.1.11", "gauge", "Power-on time of the H3C entity in seconds.", source_name="hh3cEntityExtUpTime", indexes=_ENTITY_INDEX),
        _metric("hh3cEntityExtMacAddressCount", "1.3.6.1.4.1.25506.2.6.1.2.1.1.5", "gauge", "MAC address count reported for the H3C entity.", source_name="hh3cEntityExtMacAddressCount", indexes=_ENTITY_INDEX),
        _metric("hh3cDevMFanStatus", "1.3.6.1.4.1.25506.8.35.9.1.1.1.2", "EnumAsInfo", "H3C fan status: active, deactive, not installed, or unsupported.", source_name="hh3cDevMFanStatus", indexes=_FAN_INDEX, enum_values=_H3C_STATUS_VALUES),
        _metric("hh3cDevMPowerStatus", "1.3.6.1.4.1.25506.8.35.9.1.2.1.2", "EnumAsInfo", "H3C power supply status: active, deactive, not installed, or unsupported.", source_name="hh3cDevMPowerStatus", indexes=_POWER_INDEX, enum_values=_H3C_STATUS_VALUES),
        _metric("hh3cFlhPartSpace", "1.3.6.1.4.1.25506.2.5.1.1.4.1.1.4", "gauge", "H3C Flash partition capacity in bytes.", source_name="hh3cFlhPartSpace", indexes=_FLASH_PARTITION_INDEX),
        _metric("hh3cFlhPartSpaceFree", "1.3.6.1.4.1.25506.2.5.1.1.4.1.1.5", "gauge", "H3C Flash partition free capacity in bytes.", source_name="hh3cFlhPartSpaceFree", indexes=_FLASH_PARTITION_INDEX),
        _metric("hh3cFlhPartStatus", "1.3.6.1.4.1.25506.2.5.1.1.4.1.1.8", "EnumAsInfo", "H3C Flash partition status.", source_name="hh3cFlhPartStatus", indexes=_FLASH_PARTITION_INDEX, enum_values=_H3C_FLASH_PART_STATUS_VALUES),
        _metric("hh3cFlhPartName", "1.3.6.1.4.1.25506.2.5.1.1.4.1.1.10", "DisplayString", "H3C Flash partition name.", source_name="hh3cFlhPartName", indexes=_FLASH_PARTITION_INDEX),
        _metric("hh3cMaxMacLearnRange", "1.3.6.1.4.1.25506.8.35.5.1.12", "gauge", "Maximum number of MAC addresses supported by an H3C interface.", source_name="hh3cMaxMacLearnRange"),
        _metric("hh3cEntityExtNominalPower", "1.3.6.1.4.1.25506.2.6.1.3.1.1.2", "gauge", "Rated power of an H3C power entity in milliwatts.", source_name="hh3cEntityExtNominalPower", indexes=("power_index",)),
        _metric("hh3cEntityExtCurrentPower", "1.3.6.1.4.1.25506.2.6.1.3.1.1.3", "gauge", "Current power of an H3C power entity in milliwatts.", source_name="hh3cEntityExtCurrentPower", indexes=("power_index",)),
        _metric("hh3cEntityExtAveragePower", "1.3.6.1.4.1.25506.2.6.1.3.1.1.4", "gauge", "Average power of an H3C power entity in milliwatts.", source_name="hh3cEntityExtAveragePower", indexes=("power_index",)),
    ],
}


HUAWEI_ENTITY_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["HUAWEI-ENTITY-EXTENT-MIB", "HUAWEI-CPU-MIB", "HUAWEI-MEMORY-MIB", "ENTITY-MIB (RFC 4133)"],
    "source_urls": ["https://info.support.huawei.com/enterprise/en/doc/EDOC1100410594/e704d4b7/mib-example"],
    "walk": [
        "1.3.6.1.4.1.2011.5.25.31.1.1.1",
        "1.3.6.1.4.1.2011.6.3.4",
        "1.3.6.1.4.1.2011.6.3.5",
        "1.3.6.1.4.1.2011.6.157.2.1.1",
        "1.3.6.1.2.1.47.1.1.1.1.7",
    ],
    "get": [
        "1.3.6.1.4.1.2011.6.157.1.1",
        "1.3.6.1.4.1.2011.6.157.1.3",
        "1.3.6.1.4.1.2011.6.157.1.4",
        "1.3.6.1.4.1.2011.6.157.1.6",
    ],
    "metrics": [
        _metric("hwEntityCpuUsage", "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5", "gauge", "CPU usage of the Huawei physical entity.", source_name="hwEntityCpuUsage", indexes=_ENTITY_INDEX),
        _metric("hwEntityMemUsage", "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7", "gauge", "Memory usage of the Huawei physical entity in percent.", source_name="hwEntityMemUsage", indexes=_ENTITY_INDEX),
        _metric("hwEntityMemSize", "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.9", "gauge", "Memory size of the Huawei physical entity in bytes.", source_name="hwEntityMemSize", indexes=_ENTITY_INDEX),
        _metric("hwEntityTemperature", "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.11", "gauge", "Highest temperature reported for the Huawei entity in degrees Celsius.", source_name="hwEntityTemperature", indexes=_ENTITY_INDEX),
        _metric("hwCpuDevDuty", "1.3.6.1.4.1.2011.6.3.4.1.2", "gauge", "Current CPU occupancy of a Huawei board or entity.", source_name="hwCpuDevDuty", indexes=("frame_index", "slot_index", "cpu_index")),
        _metric("hwAvgDuty1min", "1.3.6.1.4.1.2011.6.3.4.1.3", "gauge", "One-minute average CPU occupancy of a Huawei board or entity.", source_name="hwAvgDuty1min", indexes=("frame_index", "slot_index", "cpu_index")),
        _metric("hwAvgDuty5min", "1.3.6.1.4.1.2011.6.3.4.1.4", "gauge", "Five-minute average CPU occupancy of a Huawei board or entity.", source_name="hwAvgDuty5min", indexes=("frame_index", "slot_index", "cpu_index")),
        _metric("hwMemoryDevSize", "1.3.6.1.4.1.2011.6.3.5.1.1.2", "gauge", "Total memory size of a Huawei memory module in bytes.", source_name="hwMemoryDevSize", indexes=("frame_index", "slot_index", "memory_module_index")),
        _metric("hwMemoryDevFree", "1.3.6.1.4.1.2011.6.3.5.1.1.3", "gauge", "Free memory size of a Huawei memory module in bytes.", source_name="hwMemoryDevFree", indexes=("frame_index", "slot_index", "memory_module_index")),
        _metric("hwMemoryDevSize64", "1.3.6.1.4.1.2011.6.3.5.1.1.8", "gauge", "64-bit total memory size of a Huawei memory module in bytes.", source_name="hwMemoryDevSize64", indexes=("frame_index", "slot_index", "memory_module_index")),
        _metric("hwMemoryDevFree64", "1.3.6.1.4.1.2011.6.3.5.1.1.9", "gauge", "64-bit free memory size of a Huawei memory module in bytes.", source_name="hwMemoryDevFree64", indexes=("frame_index", "slot_index", "memory_module_index")),
        _metric("hwBoardRatedPower", "1.3.6.1.4.1.2011.6.157.2.1.1.5", "gauge", "Rated power of a Huawei board or power supply in milliwatts.", source_name="hwBoardRatedPower", indexes=("board_index",)),
        _metric("hwPowerConsumption", "1.3.6.1.4.1.2011.6.157.1.1", "gauge", "Historical Huawei device power consumption.", source_name="hwPowerConsumption"),
        _metric("hwAveragePower", "1.3.6.1.4.1.2011.6.157.1.3", "gauge", "Average Huawei device power in milliwatts.", source_name="hwAveragePower"),
        _metric("hwRatedPower", "1.3.6.1.4.1.2011.6.157.1.4", "gauge", "Rated Huawei device power in milliwatts.", source_name="hwRatedPower"),
        _metric("hwCurrentPower", "1.3.6.1.4.1.2011.6.157.1.6", "gauge", "Current Huawei device power in milliwatts.", source_name="hwCurrentPower"),
        _metric("entPhysicalName", "1.3.6.1.2.1.47.1.1.1.1.7", "DisplayString", "Physical entity name used to identify Huawei board and sensor rows.", source_name="entPhysicalName", indexes=_ENTITY_INDEX),
    ],
}


CISCO_ENTITY_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["CISCO-PROCESS-MIB", "CISCO-MEMORY-POOL-MIB", "CISCO-ENTITY-SENSOR-MIB", "ENTITY-MIB (RFC 4133)"],
    "source_urls": [
        "https://www.cisco.com/c/en/us/td/docs/security/asa/asa923/configuration/general/asa-923-general-config/snmp-mibs-oids.pdf",
        "https://raw.githubusercontent.com/prometheus/snmp_exporter/main/generator/generator.yml",
    ],
    "walk": [
        "1.3.6.1.4.1.9.9.109.1.1.1",
        "1.3.6.1.4.1.9.9.48.1.1.1",
        "1.3.6.1.4.1.9.9.91.1.1.1",
        "1.3.6.1.2.1.47.1.1.1.1.7",
    ],
    "metrics": [
        _metric("cpmCPUTotal1minRev", "1.3.6.1.4.1.9.9.109.1.1.1.1.7", "gauge", "Cisco overall CPU busy percentage during the last one-minute period.", source_name="cpmCPUTotal1minRev", indexes=("cpu_index",)),
        _metric("cpmCPUTotal5minRev", "1.3.6.1.4.1.9.9.109.1.1.1.1.8", "gauge", "Cisco overall CPU busy percentage during the last five-minute period.", source_name="cpmCPUTotal5minRev", indexes=("cpu_index",)),
        _metric("cpmCPUTotalMonIntervalValue", "1.3.6.1.4.1.9.9.109.1.1.1.1.10", "gauge", "Cisco CPU busy percentage during the configured monitoring interval.", source_name="cpmCPUTotalMonIntervalValue", indexes=("cpu_index",)),
        _metric("cpmCPUInterruptMonIntervalValue", "1.3.6.1.4.1.9.9.109.1.1.1.1.11", "gauge", "Cisco CPU interrupt utilization percentage.", source_name="cpmCPUInterruptMonIntervalValue", indexes=("cpu_index",)),
        _metric("cpmCPUMemoryHCUsed", "1.3.6.1.4.1.9.9.109.1.1.1.1.17", "gauge", "Cisco CPU-wide memory currently in use, in kilobytes.", source_name="cpmCPUMemoryHCUsed", indexes=("cpu_index",)),
        _metric("cpmCPUMemoryHCFree", "1.3.6.1.4.1.9.9.109.1.1.1.1.19", "gauge", "Cisco CPU-wide memory currently free, in kilobytes.", source_name="cpmCPUMemoryHCFree", indexes=("cpu_index",)),
        _metric("ciscoMemoryPoolUsed", "1.3.6.1.4.1.9.9.48.1.1.1.5", "gauge", "Cisco memory pool used bytes/kilobytes, depending on platform MIB implementation.", source_name="ciscoMemoryPoolUsed", indexes=("memory_pool_index",)),
        _metric("ciscoMemoryPoolFree", "1.3.6.1.4.1.9.9.48.1.1.1.6", "gauge", "Cisco memory pool free bytes/kilobytes, depending on platform MIB implementation.", source_name="ciscoMemoryPoolFree", indexes=("memory_pool_index",)),
        _metric("ciscoMemoryPoolName", "1.3.6.1.4.1.9.9.48.1.1.1.2", "DisplayString", "Cisco memory pool name.", source_name="ciscoMemoryPoolName", indexes=("memory_pool_index",)),
        _metric("entSensorValue", "1.3.6.1.4.1.9.9.91.1.1.1.4", "gauge", "Cisco entity sensor value.", source_name="entSensorValue", indexes=("sensor_index",)),
        _metric("entPhysicalName", "1.3.6.1.2.1.47.1.1.1.1.7", "DisplayString", "Physical entity name used to identify Cisco CPU, memory and sensor rows.", source_name="entPhysicalName", indexes=_ENTITY_INDEX),
    ],
}


BUILTIN_OID_CATALOG: tuple[dict[str, Any], ...] = (
    _module(
        "module-generic-if-mib",
        "generic_ifmib_interface",
        "通用接口（IF-MIB）",
        "generic",
        "generic",
        "interface",
        "interface",
        "if-mib:1.3.6.1.2.1.2|1.3.6.1.2.1.31",
        "RFC 2863 接口状态、速率和高容量计数器。",
        _variant("variant-generic-if-mib-std", "generic_ifmib_interface_std", "通用接口标准版本", STANDARD_INTERFACE_CONFIG, mib_bundle_id="if-mib-rfc2863"),
    ),
    _module(
        "module-generic-system",
        "generic_system",
        "通用系统（SNMPv2-MIB）",
        "generic",
        "generic",
        "system",
        "system",
        "system-mib:1.3.6.1.2.1.1",
        "RFC 3418 系统身份、位置和运行时间。",
        _variant("variant-generic-system-std", "generic_system_std", "通用系统标准版本", STANDARD_SYSTEM_CONFIG, max_repetitions=10, scrape_timeout_ms=30000, mib_bundle_id="snmpv2-mib-rfc3418"),
    ),
    _module(
        "module-h3c-common",
        "h3c_common",
        "华三通用设备",
        "h3c",
        "comware",
        "hardware",
        "hardware",
        "hh3c-entity-ext|hh3c-flash|hh3c-lswdevm|hh3c-lswinf",
        "华三 Comware 常用实体 CPU、内存、温度、风扇、电源、Flash 和 MAC 计数 OID。",
        _variant(
            "variant-h3c-common-std",
            "h3c_common_std",
            "华三通用标准版本",
            H3C_ENTITY_CONFIG,
            mib_bundle_id="hh3c-entity-ext-2023",
            retries=3,
            request_timeout_ms=5000,
            supported_models=["S5000", "S5110", "S5120", "S5130", "S5135", "S5170", "S5500", "S5800", "S6300", "S6500", "S6800", "S10500"],
            supported_platforms=["h3c_comware_v5", "h3c_comware_v7", "h3c_comware_v9"],
            supported_version_scope=["Comware 7", "Comware 9"],
        ),
    ),
    _module(
        "module-huawei-common",
        "huawei_common",
        "华为通用设备",
        "huawei",
        "vrp",
        "hardware",
        "hardware",
        "huawei-entity-cpu-memory:1.3.6.1.4.1.2011",
        "华为 VRP 常用实体 CPU、板卡 CPU 和内存 OID。",
        _variant("variant-huawei-common-std", "huawei_common_std", "华为通用标准版本", HUAWEI_ENTITY_CONFIG, mib_bundle_id="huawei-entity-cpu-memory-2019", supported_platforms=["huawei_vrp", "huawei_vrp5", "huawei_vrp8", "huawei_vrpv8"], supported_models=["S3700", "S5700", "S6700", "S7700", "S8700", "S9700", "S12700", "S16700"], supported_version_scope=["VRP V8", "VRP V9", "YunShan V200/V300"]),
    ),
    _module(
        "module-cisco-common",
        "cisco_common",
        "思科通用设备",
        "cisco",
        "ios",
        "hardware",
        "hardware",
        "cisco-process-memory-sensor:1.3.6.1.4.1.9.9",
        "思科 IOS/NX-OS 常用 CPU、内存池和实体传感器 OID。",
        _variant("variant-cisco-common-std", "cisco_common_std", "思科通用标准版本", CISCO_ENTITY_CONFIG, mib_bundle_id="cisco-process-memory-sensor-2026", supported_platforms=["cisco_ios", "cisco_iosxe", "cisco_nxos", "cisco_asa", "ios", "iosxe", "nxos", "asa"], supported_models=["Catalyst", "2960", "3850", "9300", "9500", "Nexus"], supported_version_scope=["IOS", "IOS-XE", "NX-OS", "ASA"]),
    ),
)


def iter_builtin_catalog() -> list[dict[str, Any]]:
    """Return a deep copy so migrations/API code cannot mutate the catalog."""

    return deepcopy(list(BUILTIN_OID_CATALOG))


def exporter_config_from_variant(module: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
    """Return the exporter-safe subset of a persisted OID configuration.

    Source metadata is intentionally not sent to snmp_exporter because its
    strict YAML parser rejects unknown module/metric fields.
    """

    raw = variant.get("oid_config")
    if not isinstance(raw, dict):
        raw = {}
    result: dict[str, Any] = {}
    for key in ("walk", "get", "metrics", "filters"):
        if key in raw:
            result[key] = deepcopy(raw[key])
    if not result.get("walk") and module.get("walk"):
        result["walk"] = deepcopy(module["walk"])
    for metric in result.get("metrics") or []:
        if isinstance(metric, dict):
            metric.pop("source_name", None)
            # ``unit`` is useful to Nexora's metric dictionary but is not a
            # field understood by snmp_exporter's strict runtime schema.
            metric.pop("unit", None)
    return result
