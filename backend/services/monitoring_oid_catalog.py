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


OID_CATALOG_VERSION = "2026.09.26"


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
    lookups: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    scale: float | None = None,
    unit: str | None = None,
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
    if lookups:
        item["lookups"] = [dict(lk) for lk in lookups]
    if scale is not None:
        item["scale"] = scale
    if unit:
        item["unit"] = unit
    if enum_values:
        item["enum_values"] = enum_values
    return item


_IF_INDEX = ("ifIndex",)
_INTERFACE_LOOKUPS = (
    {"labels": ["ifIndex"], "labelname": "ifName", "oid": "1.3.6.1.2.1.31.1.1.1.1", "type": "DisplayString"},
    {"labels": ["ifIndex"], "labelname": "ifDescr", "oid": "1.3.6.1.2.1.2.2.1.2", "type": "DisplayString"},
)
_ENTITY_INDEX = ("entity_index",)
_FLASH_PARTITION_INDEX = ("flash_index", "partition_index")
_FAN_INDEX = ("fan_index",)
_POWER_INDEX = ("power_index",)

_ENTITY_LOOKUPS = (
    {"labels": ["entity_index"], "labelname": "entityName", "oid": "1.3.6.1.2.1.47.1.1.1.1.7", "type": "DisplayString"},
)

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
    _metric("ifMtu", "1.3.6.1.2.1.2.2.1.4", "gauge", "Maximum transmission unit of the interface.", source_name="ifMtu", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifSpeed", "1.3.6.1.2.1.2.2.1.5", "gauge", "Interface speed in bits per second (32-bit value).", source_name="ifSpeed", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifType", "1.3.6.1.2.1.2.2.1.3", "gauge", "Interface type enumeration.", source_name="ifType", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifAdminStatus", "1.3.6.1.2.1.2.2.1.7", "gauge", "Administrative state of the interface.", source_name="ifAdminStatus", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifOperStatus", "1.3.6.1.2.1.2.2.1.8", "gauge", "Operational state of the interface.", source_name="ifOperStatus", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifLastChange", "1.3.6.1.2.1.2.2.1.9", "gauge", "Value of sysUpTime when the interface entered its current operational state, in hundredths of a second.", source_name="ifLastChange", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifInDiscards", "1.3.6.1.2.1.2.2.1.13", "counter", "Inbound packets discarded.", source_name="ifInDiscards", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifInErrors", "1.3.6.1.2.1.2.2.1.14", "counter", "Inbound packets with errors.", source_name="ifInErrors", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifInOctets", "1.3.6.1.2.1.2.2.1.10", "counter", "Inbound octets using the 32-bit interface counter.", source_name="ifInOctets", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifOutDiscards", "1.3.6.1.2.1.2.2.1.19", "counter", "Outbound packets discarded.", source_name="ifOutDiscards", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifOutErrors", "1.3.6.1.2.1.2.2.1.20", "counter", "Outbound packets with errors.", source_name="ifOutErrors", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifOutOctets", "1.3.6.1.2.1.2.2.1.16", "counter", "Outbound octets using the 32-bit interface counter.", source_name="ifOutOctets", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifName", "1.3.6.1.2.1.31.1.1.1.1", "DisplayString", "Interface name.", source_name="ifName", indexes=_IF_INDEX),
    _metric("ifHighSpeed", "1.3.6.1.2.1.31.1.1.1.15", "gauge", "Interface speed in millions of bits per second.", source_name="ifHighSpeed", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifHCInOctets", "1.3.6.1.2.1.31.1.1.1.6", "counter", "Inbound octets using the high-capacity counter.", source_name="ifHCInOctets", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifHCInUcastPkts", "1.3.6.1.2.1.31.1.1.1.7", "counter", "Inbound unicast packets using the high-capacity counter.", source_name="ifHCInUcastPkts", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifHCInMulticastPkts", "1.3.6.1.2.1.31.1.1.1.8", "counter", "Inbound multicast packets using the high-capacity counter.", source_name="ifHCInMulticastPkts", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifHCInBroadcastPkts", "1.3.6.1.2.1.31.1.1.1.9", "counter", "Inbound broadcast packets using the high-capacity counter.", source_name="ifHCInBroadcastPkts", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifHCOutOctets", "1.3.6.1.2.1.31.1.1.1.10", "counter", "Outbound octets using the high-capacity counter.", source_name="ifHCOutOctets", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifHCOutUcastPkts", "1.3.6.1.2.1.31.1.1.1.11", "counter", "Outbound unicast packets using the high-capacity counter.", source_name="ifHCOutUcastPkts", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifHCOutMulticastPkts", "1.3.6.1.2.1.31.1.1.1.12", "counter", "Outbound multicast packets using the high-capacity counter.", source_name="ifHCOutMulticastPkts", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifHCOutBroadcastPkts", "1.3.6.1.2.1.31.1.1.1.13", "counter", "Outbound broadcast packets using the high-capacity counter.", source_name="ifHCOutBroadcastPkts", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
    _metric("ifPhysAddress", "1.3.6.1.2.1.2.2.1.6", "OctetString", "Interface physical address.", source_name="ifPhysAddress", indexes=_IF_INDEX),
    _metric("ifAlias", "1.3.6.1.2.1.31.1.1.1.18", "DisplayString", "Interface alias/description.", source_name="ifAlias", indexes=_IF_INDEX),
    _metric("dot3StatsFCSErrors", "1.3.6.1.2.1.10.7.2.1.3", "counter", "Ethernet frames received with FCS errors.", source_name="dot3StatsFCSErrors", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS),
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
        "https://github.com/librenms/librenms/blob/master/includes/discovery/sensors/dbm/comware.inc.php",
        "https://github.com/librenms/librenms/blob/master/mibs/comware/HH3C-TRANSCEIVER-INFO-MIB",
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
        "1.3.6.1.4.1.25506.2.70.1.1.1",
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
        _metric("hh3cTransceiverCurTXPowerDbm", "1.3.6.1.4.1.25506.2.70.1.1.1.9", "gauge", "Current H3C transceiver transmit optical power in dBm; raw values are hundredths of dBm and 2147483647 is unsupported.", source_name="hh3cTransceiverCurTXPower", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS, scale=0.01, unit="dBm"),
        _metric("hh3cTransceiverCurRXPowerDbm", "1.3.6.1.4.1.25506.2.70.1.1.1.12", "gauge", "Current H3C transceiver receive optical power in dBm; raw values are hundredths of dBm and 2147483647 is unsupported.", source_name="hh3cTransceiverCurRXPower", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS, scale=0.01, unit="dBm"),
        _metric("hh3cTransceiverTemperatureCelsius", "1.3.6.1.4.1.25506.2.70.1.1.1.15", "gauge", "H3C transceiver temperature in degrees Celsius; 2147483647 is unsupported.", source_name="hh3cTransceiverTemperature", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS, unit="celsius"),
        _metric("hh3cTransceiverVoltageVolts", "1.3.6.1.4.1.25506.2.70.1.1.1.16", "gauge", "H3C transceiver supply voltage in volts; raw values are hundredths of a volt and 2147483647 is unsupported.", source_name="hh3cTransceiverVoltage", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS, scale=0.01, unit="volts"),
        _metric("hh3cTransceiverBiasCurrentMilliAmps", "1.3.6.1.4.1.25506.2.70.1.1.1.17", "gauge", "H3C transceiver bias current in milliamps; raw values are hundredths of a milliamp and 2147483647 is unsupported.", source_name="hh3cTransceiverBiasCurrent", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS, scale=0.01, unit="milliamps"),
    ],
}


HUAWEI_ENTITY_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["HUAWEI-ENTITY-EXTENT-MIB", "HUAWEI-CPU-MIB", "HUAWEI-MEMORY-MIB", "ENTITY-MIB (RFC 4133)"],
    "source_urls": [
        "https://info.support.huawei.com/enterprise/en/doc/EDOC1100410594/e704d4b7/mib-example",
        "https://github.com/librenms/librenms/blob/master/resources/definitions/os_discovery/vrp.yaml",
        "https://github.com/librenms/librenms/blob/master/mibs/huawei/HUAWEI-ENTITY-EXTENT-MIB",
    ],
    "walk": [
        "1.3.6.1.4.1.2011.5.25.31.1.1.1",
        "1.3.6.1.4.1.2011.6.3.4",
        "1.3.6.1.4.1.2011.6.3.5",
        "1.3.6.1.4.1.2011.6.157.2.1.1",
        "1.3.6.1.2.1.47.1.1.1.1.7",
        "1.3.6.1.4.1.2011.5.25.31.1.1.3.1",
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
        _metric("hwEntityOpticalRxPowerRaw", "1.3.6.1.4.1.2011.5.25.31.1.1.3.1.8", "gauge", "Huawei VRP raw receive optical power; positive readings may be microwatts while negative readings are hundredths of dBm. Use the SNMP optical collector for normalized dBm.", source_name="hwEntityOpticalRxPower", indexes=_ENTITY_INDEX, lookups=_ENTITY_LOOKUPS, unit="mixed_raw"),
        _metric("hwEntityOpticalTxPowerRaw", "1.3.6.1.4.1.2011.5.25.31.1.1.3.1.9", "gauge", "Huawei VRP raw transmit optical power; positive readings may be microwatts while negative readings are hundredths of dBm. Use the SNMP optical collector for normalized dBm.", source_name="hwEntityOpticalTxPower", indexes=_ENTITY_INDEX, lookups=_ENTITY_LOOKUPS, unit="mixed_raw"),
        _metric("hwEntityOpticalTemperatureCelsius", "1.3.6.1.4.1.2011.5.25.31.1.1.3.1.5", "gauge", "Huawei VRP transceiver temperature in degrees Celsius; 2147483647 is invalid.", source_name="hwEntityOpticalTemperature", indexes=_ENTITY_INDEX, lookups=_ENTITY_LOOKUPS, unit="celsius"),
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


RUIJIE_ENTITY_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["RUIJIE-DEVICE-MIB", "RUIJIE-SYSTEM-MIB", "ENTITY-MIB (RFC 4133)"],
    "source_urls": [
        "https://www.ruijienetworks.com",
        "https://github.com/librenms/librenms/blob/master/resources/definitions/os_discovery/ruijie.yaml",
        "https://github.com/librenms/librenms/blob/master/mibs/ruijie/RUIJIE-FIBER-MIB",
    ],
    "walk": [
        "1.3.6.1.4.1.4881.1.1.10.2.35.1.1",
        "1.3.6.1.2.1.47.1.1.1.1.7",
        "1.3.6.1.4.1.4881.1.1.10.2.105.1.1.1",
    ],
    "metrics": [
        _metric("ruijieCpuCostRate", "1.3.6.1.4.1.4881.1.1.10.2.35.1.1.1.3", "gauge", "CPU utilization percentage for the Ruijie entity.", source_name="ruijieCpuCostRate", indexes=_ENTITY_INDEX),
        _metric("ruijieMemoryPoolCurrentUtilization", "1.3.6.1.4.1.4881.1.1.10.2.35.1.1.1.2", "gauge", "Memory utilization percentage for the Ruijie entity.", source_name="ruijieMemoryPoolCurrentUtilization", indexes=_ENTITY_INDEX),
        _metric("ruijieDeviceTemperature", "1.3.6.1.4.1.4881.1.1.10.2.35.1.1.1.4", "gauge", "Temperature for the Ruijie entity in degrees Celsius.", source_name="ruijieDeviceTemperature", indexes=_ENTITY_INDEX),
        _metric("ruijieDevicePowerStatus", "1.3.6.1.4.1.4881.1.1.10.2.35.1.1.1.5", "gauge", "Power supply status for the Ruijie entity.", source_name="ruijieDevicePowerStatus", indexes=_ENTITY_INDEX),
        _metric("ruijieDeviceFanStatus", "1.3.6.1.4.1.4881.1.1.10.2.35.1.1.1.6", "gauge", "Fan status for the Ruijie entity.", source_name="ruijieDeviceFanStatus", indexes=_ENTITY_INDEX),
        _metric("entPhysicalName", "1.3.6.1.2.1.47.1.1.1.1.7", "DisplayString", "Physical entity name used to identify Ruijie card and sensor rows.", source_name="entPhysicalName", indexes=_ENTITY_INDEX),
        _metric("ruijieFiberRXpowerDbm", "1.3.6.1.4.1.4881.1.1.10.2.105.1.1.1.76", "gauge", "Ruijie fiber transceiver receive optical power in dBm; raw values are hundredths of dBm, -10000 is invalid, and DDMSupport must indicate support.", source_name="ruijieFiberRXpower", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS, scale=0.01, unit="dBm"),
        _metric("ruijieFiberTXpowerDbm", "1.3.6.1.4.1.4881.1.1.10.2.105.1.1.1.81", "gauge", "Ruijie fiber transceiver transmit optical power in dBm; raw values are hundredths of dBm, -10000 is invalid, and DDMSupport must indicate support.", source_name="ruijieFiberTXpower", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS, scale=0.01, unit="dBm"),
        _metric("ruijieFiberTemperatureCelsius", "1.3.6.1.4.1.4881.1.1.10.2.105.1.1.1.17", "gauge", "Ruijie fiber module temperature in degrees Celsius; require DDMSupport=true.", source_name="ruijieFiberTemp", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS, unit="celsius"),
        _metric("ruijieFiberVoltageVolts", "1.3.6.1.4.1.4881.1.1.10.2.105.1.1.1.19", "gauge", "Ruijie fiber module voltage in volts; the raw value is millivolts and requires DDMSupport=true.", source_name="ruijieFiberVoltage", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS, scale=0.001, unit="volts"),
        _metric("ruijieFiberBiasCurrentMilliAmps", "1.3.6.1.4.1.4881.1.1.10.2.105.1.1.1.21", "gauge", "Ruijie fiber module bias current in milliamps; the raw value is microamps and requires DDMSupport=true.", source_name="ruijieFiberBias", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS, scale=0.001, unit="milliamps"),
    ],
}


JUNIPER_ENTITY_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["JUNIPER-MIB", "JUNIPER-SMI"],
    "source_urls": [
        "https://www.juniper.net/documentation/us/en/software/junos/chassis/topics/concept/digital-optical-monitoring.html",
        "https://github.com/librenms/librenms/blob/master/resources/definitions/os_discovery/junos.yaml",
        "https://github.com/librenms/librenms/blob/master/mibs/juniper/JUNIPER-DOM-MIB",
    ],
    "walk": [
        "1.3.6.1.4.1.2636.3.1.13.1",
        "1.3.6.1.4.1.2636.3.60.1.1.1.1",
    ],
    "metrics": [
        _metric("jnxOperatingCPU", "1.3.6.1.4.1.2636.3.1.13.1.8", "gauge", "Overall CPU busy percentage for the Juniper operating entity.", source_name="jnxOperatingCPU", indexes=("operating_index",)),
        _metric("jnxOperatingBuffer", "1.3.6.1.4.1.2636.3.1.13.1.11", "gauge", "Buffer/memory utilization percentage for the Juniper operating entity.", source_name="jnxOperatingBuffer", indexes=("operating_index",)),
        _metric("jnxOperatingTemp", "1.3.6.1.4.1.2636.3.1.13.1.7", "gauge", "Temperature of the Juniper operating entity in degrees Celsius.", source_name="jnxOperatingTemp", indexes=("operating_index",)),
        _metric("jnxOperatingDRAMSize", "1.3.6.1.4.1.2636.3.1.13.1.10", "gauge", "Total DRAM size of the Juniper operating entity in bytes.", source_name="jnxOperatingDRAMSize", indexes=("operating_index",)),
        _metric("jnxOperatingDescr", "1.3.6.1.4.1.2636.3.1.13.1.5", "DisplayString", "Textual description of the Juniper operating entity.", source_name="jnxOperatingDescr", indexes=("operating_index",)),
        _metric("jnxDomCurrentRxLaserPowerDbm", "1.3.6.1.4.1.2636.3.60.1.1.1.1.5", "gauge", "Juniper DOM receive laser power in dBm; raw values are hundredths of dBm and the table is indexed by ifIndex. A zero reading means unsupported.", source_name="jnxDomCurrentRxLaserPower", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS, scale=0.01, unit="dBm"),
        _metric("jnxDomCurrentTxLaserOutputPowerDbm", "1.3.6.1.4.1.2636.3.60.1.1.1.1.7", "gauge", "Juniper DOM transmit laser output power in dBm; raw values are hundredths of dBm and the table is indexed by ifIndex. A zero reading means unsupported.", source_name="jnxDomCurrentTxLaserOutputPower", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS, scale=0.01, unit="dBm"),
    ],
}


FORTINET_ENTITY_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["FORTINET-CORE-MIB", "FORTINET-FORTIGATE-MIB"],
    "source_urls": ["https://docs.fortinet.com"],
    "walk": [
        "1.3.6.1.4.1.12356.101.4.1",
    ],
    "metrics": [
        _metric("fnSysCpuUsage", "1.3.6.1.4.1.12356.101.4.1.3", "gauge", "Current CPU usage percentage of the FortiGate firewall.", source_name="fnSysCpuUsage"),
        _metric("fnSysMemUsage", "1.3.6.1.4.1.12356.101.4.1.4", "gauge", "Current memory usage percentage of the FortiGate firewall.", source_name="fnSysMemUsage"),
        _metric("fnSysSesCount", "1.3.6.1.4.1.12356.101.4.1.8", "gauge", "Number of active firewall sessions on the FortiGate.", source_name="fnSysSesCount"),
        _metric("fnSysDiskUsage", "1.3.6.1.4.1.12356.101.4.1.6", "gauge", "Current disk usage percentage of the FortiGate firewall.", source_name="fnSysDiskUsage"),
    ],
}


ZTE_ENTITY_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["ZTE-AN-SYS-MIB", "ZTE-EQUIPMENT-MIB", "ZTE-AN-OPTICAL-MODULE-MIB", "ZXR10-SMI"],
    "source_urls": [
        "https://support.zte.com.cn/support/docmap/00000455/en/",
        "https://github.com/librenms/librenms/blob/master/mibs/zte/ZTE-AN-OPTICAL-MODULE-MIB",
    ],
    "walk": [
        "1.3.6.1.4.1.3902.1082.500.1.2",
        "1.3.6.1.4.1.3902.1082.30.40.2.4.1",
    ],
    "metrics": [
        _metric("zteCpuRate", "1.3.6.1.4.1.3902.1082.500.1.2.1.1.1", "gauge", "CPU utilization percentage for ZTE network device.", source_name="zteCpuRate", indexes=_ENTITY_INDEX),
        _metric("zteMemRate", "1.3.6.1.4.1.3902.1082.500.1.2.2.1.1", "gauge", "Memory utilization percentage for ZTE network device.", source_name="zteMemRate", indexes=_ENTITY_INDEX),
        _metric("zteTemperature", "1.3.6.1.4.1.3902.1082.500.1.2.3.1.1", "gauge", "Board temperature in degrees Celsius for ZTE network device.", source_name="zteTemperature", indexes=_ENTITY_INDEX),
        _metric("zteAnOpticalIfRxPwrCurrDbm", "1.3.6.1.4.1.3902.1082.30.40.2.4.1.2", "gauge", "ZTE AN optical module receive power in dBm; raw values are thousandths of dBm and the table is indexed by ifIndex.", source_name="zxAnOpticalIfRxPwrCurrValue", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS, scale=0.001, unit="dBm"),
        _metric("zteAnOpticalIfTxPwrCurrDbm", "1.3.6.1.4.1.3902.1082.30.40.2.4.1.3", "gauge", "ZTE AN optical module transmit power in dBm; raw values are thousandths of dBm and the table is indexed by ifIndex.", source_name="zxAnOpticalIfTxPwrCurrValue", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS, scale=0.001, unit="dBm"),
        _metric("zteAnOpticalIfBiasCurrentMilliAmps", "1.3.6.1.4.1.3902.1082.30.40.2.4.1.5", "gauge", "ZTE AN optical module bias current in milliamps; raw values are thousandths of a milliamp.", source_name="zxAnOpticalBiasCurrent", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS, scale=0.001, unit="milliamps"),
        _metric("zteAnOpticalIfVoltageVolts", "1.3.6.1.4.1.3902.1082.30.40.2.4.1.6", "gauge", "ZTE AN optical module supply voltage in volts; raw values are thousandths of a volt.", source_name="zxAnOpticalSupplyVoltage", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS, scale=0.001, unit="volts"),
        _metric("zteAnOpticalIfTemperatureCelsius", "1.3.6.1.4.1.3902.1082.30.40.2.4.1.8", "gauge", "ZTE AN optical module temperature in degrees Celsius; raw values are thousandths of a degree.", source_name="zxAnOpticalTemperature", indexes=_IF_INDEX, lookups=_INTERFACE_LOOKUPS, scale=0.001, unit="celsius"),
    ],
}


MAIPU_ENTITY_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["MAIPU-SMI", "MP-SYSTEM-MIB"],
    "source_urls": ["https://www.maipu.com"],
    "walk": [
        "1.3.6.1.4.1.5651.1.2",
    ],
    "metrics": [
        _metric("mpCpuUtilization5Min", "1.3.6.1.4.1.5651.1.2.1.1.1", "gauge", "5-minute CPU utilization percentage for Maipu MyPower device.", source_name="mpCpuUtilization5Min", indexes=_ENTITY_INDEX),
        _metric("mpMemoryUtilization", "1.3.6.1.4.1.5651.1.2.1.1.2", "gauge", "Memory utilization percentage for Maipu MyPower device.", source_name="mpMemoryUtilization", indexes=_ENTITY_INDEX),
        _metric("mpTemperature", "1.3.6.1.4.1.5651.1.2.1.1.3", "gauge", "Temperature in degrees Celsius for Maipu MyPower device.", source_name="mpTemperature", indexes=_ENTITY_INDEX),
    ],
}


DPTECH_ENTITY_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["DPTECH-SYSTEM-MIB", "DPTECH-FRAMEWORK-MIB"],
    "source_urls": ["https://www.dptech.com"],
    "walk": [
        "1.3.6.1.4.1.31648.1.1",
    ],
    "metrics": [
        _metric("dptechCpuUsage", "1.3.6.1.4.1.31648.1.1.1.1", "gauge", "CPU usage percentage for DPtech switch/security device.", source_name="dptechCpuUsage", indexes=_ENTITY_INDEX),
        _metric("dptechMemUsage", "1.3.6.1.4.1.31648.1.1.1.2", "gauge", "Memory usage percentage for DPtech switch/security device.", source_name="dptechMemUsage", indexes=_ENTITY_INDEX),
        _metric("dptechTemperature", "1.3.6.1.4.1.31648.1.1.1.3", "gauge", "Temperature in degrees Celsius for DPtech device.", source_name="dptechTemperature", indexes=_ENTITY_INDEX),
        _metric("dptechSessions", "1.3.6.1.4.1.31648.1.1.1.4", "gauge", "Active session count for DPtech security gateway.", source_name="dptechSessions", indexes=_ENTITY_INDEX),
    ],
}


HILLSTONE_ENTITY_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["HILLSTONE-SYSTEM-MIB", "HILLSTONE-SMI"],
    "source_urls": ["https://www.hillstonenet.com.cn"],
    "walk": [
        "1.3.6.1.4.1.24681.1.1.1.1",
    ],
    "metrics": [
        _metric("hillstoneCPUUtilization", "1.3.6.1.4.1.24681.1.1.1.1.1.1", "gauge", "Current CPU utilization percentage for Hillstone StoneOS firewall.", source_name="hillstoneCPUUtilization", indexes=_ENTITY_INDEX),
        _metric("hillstoneMemoryUtilization", "1.3.6.1.4.1.24681.1.1.1.1.1.2", "gauge", "Current memory utilization percentage for Hillstone StoneOS firewall.", source_name="hillstoneMemoryUtilization", indexes=_ENTITY_INDEX),
        _metric("hillstoneActiveSessions", "1.3.6.1.4.1.24681.1.1.1.1.1.3", "gauge", "Active concurrent session count for Hillstone StoneOS firewall.", source_name="hillstoneActiveSessions", indexes=_ENTITY_INDEX),
    ],
}


SANGFOR_ENTITY_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["SANGFOR-SYSTEM-MIB", "SANGFOR-SMI"],
    "source_urls": ["https://www.sangfor.com.cn"],
    "get": [
        "1.3.6.1.4.1.35047.1.1.0",
        "1.3.6.1.4.1.35047.1.2.0",
        "1.3.6.1.4.1.35047.1.3.0",
    ],
    "metrics": [
        _metric("sangforCpuUsage", "1.3.6.1.4.1.35047.1.1", "gauge", "Current CPU usage percentage for Sangfor gateway device.", source_name="sangforCpuUsage"),
        _metric("sangforMemUsage", "1.3.6.1.4.1.35047.1.2", "gauge", "Current memory usage percentage for Sangfor gateway device.", source_name="sangforMemUsage"),
        _metric("sangforConcurrentConns", "1.3.6.1.4.1.35047.1.3", "gauge", "Active concurrent connections for Sangfor gateway device.", source_name="sangforConcurrentConns"),
    ],
}


DCN_ENTITY_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["DCN-SYSTEM-MIB", "DCN-SMI"],
    "source_urls": ["https://www.digitalchina.com"],
    "walk": [
        "1.3.6.1.4.1.6339.100.1.1",
    ],
    "metrics": [
        _metric("dcnCpuUsage", "1.3.6.1.4.1.6339.100.1.1.1.1", "gauge", "Current CPU usage percentage for DCN switch.", source_name="dcnCpuUsage", indexes=_ENTITY_INDEX),
        _metric("dcnMemUsage", "1.3.6.1.4.1.6339.100.1.1.1.2", "gauge", "Current memory usage percentage for DCN switch.", source_name="dcnMemUsage", indexes=_ENTITY_INDEX),
        _metric("dcnTemperature", "1.3.6.1.4.1.6339.100.1.1.1.3", "gauge", "Current temperature in degrees Celsius for DCN switch.", source_name="dcnTemperature", indexes=_ENTITY_INDEX),
    ],
}


HUAWEI_WIRELESS_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["HUAWEI-WLAN-MIB", "HUAWEI-WLAN-AP-MIB"],
    "source_urls": ["https://support.huawei.com"],
    "get": [
        "1.3.6.1.4.1.2011.6.139.13.1.2.1.0",
        "1.3.6.1.4.1.2011.6.139.13.1.2.2.0",
        "1.3.6.1.4.1.2011.6.139.13.1.2.3.0",
    ],
    "metrics": [
        _metric("hwWlanCurOnlineApNum", "1.3.6.1.4.1.2011.6.139.13.1.2.1", "gauge", "Current online AP count managed by Huawei WLAN AC.", source_name="hwWlanCurOnlineApNum"),
        _metric("hwWlanCurAssocUserNum", "1.3.6.1.4.1.2011.6.139.13.1.2.2", "gauge", "Current associated wireless clients count on Huawei WLAN AC.", source_name="hwWlanCurAssocUserNum"),
        _metric("hwWlanApTotalNum", "1.3.6.1.4.1.2011.6.139.13.1.2.3", "gauge", "Total configured AP count on Huawei WLAN AC.", source_name="hwWlanApTotalNum"),
    ],
}


H3C_WIRELESS_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["HH3C-DOT11-AC-MIB", "HH3C-DOT11-AP-MIB"],
    "source_urls": ["https://www.h3c.com"],
    "get": [
        "1.3.6.1.4.1.25506.2.75.1.1.1.0",
        "1.3.6.1.4.1.25506.2.75.1.1.2.0",
        "1.3.6.1.4.1.25506.2.75.1.1.3.0",
    ],
    "metrics": [
        _metric("hh3cDot11CurrOnlineAPNum", "1.3.6.1.4.1.25506.2.75.1.1.1", "gauge", "Current online AP count managed by H3C wireless controller.", source_name="hh3cDot11CurrOnlineAPNum"),
        _metric("hh3cDot11CurrAssocUserNum", "1.3.6.1.4.1.25506.2.75.1.1.2", "gauge", "Current associated wireless stations on H3C wireless controller.", source_name="hh3cDot11CurrAssocUserNum"),
        _metric("hh3cDot11TotalAPNum", "1.3.6.1.4.1.25506.2.75.1.1.3", "gauge", "Total AP count connected to H3C wireless controller.", source_name="hh3cDot11TotalAPNum"),
    ],
}


RUIJIE_WIRELESS_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["RUIJIE-WLAN-AC-MIB", "RUIJIE-AC-MGMT-MIB"],
    "source_urls": ["https://www.ruijienetworks.com"],
    "get": [
        "1.3.6.1.4.1.4881.1.1.10.2.75.1.1.1.0",
        "1.3.6.1.4.1.4881.1.1.10.2.75.1.1.2.0",
        "1.3.6.1.4.1.4881.1.1.10.2.75.1.1.3.0",
    ],
    "metrics": [
        _metric("ruijieApcTotalApNum", "1.3.6.1.4.1.4881.1.1.10.2.75.1.1.1", "gauge", "Total managed AP count for Ruijie AC.", source_name="ruijieApcTotalApNum"),
        _metric("ruijieApcOnlineApNum", "1.3.6.1.4.1.4881.1.1.10.2.75.1.1.2", "gauge", "Current online AP count for Ruijie AC.", source_name="ruijieApcOnlineApNum"),
        _metric("ruijieApcTotalStaNum", "1.3.6.1.4.1.4881.1.1.10.2.75.1.1.3", "gauge", "Total associated wireless stations on Ruijie AC.", source_name="ruijieApcTotalStaNum"),
    ],
}


CISCO_WIRELESS_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["CISCO-LWAPP-SYS-MIB", "CISCO-LWAPP-AP-MIB"],
    "source_urls": ["https://www.cisco.com"],
    "get": [
        "1.3.6.1.4.1.9.9.513.1.1.1.1.5.0",
        "1.3.6.1.4.1.9.9.618.1.1.1.0",
    ],
    "metrics": [
        _metric("cLApTotalUpAPs", "1.3.6.1.4.1.9.9.513.1.1.1.1.5", "gauge", "Total number of joined and up APs on Cisco WLC.", source_name="cLApTotalUpAPs"),
        _metric("cLSysTotalNumOfClients", "1.3.6.1.4.1.9.9.618.1.1.1", "gauge", "Total number of associated wireless clients on Cisco WLC.", source_name="cLSysTotalNumOfClients"),
    ],
}


ARUBA_WIRELESS_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["WLSX-SYSTEMEXT-MIB", "ARUBA-MIB"],
    "source_urls": ["https://www.arubanetworks.com"],
    "get": [
        "1.3.6.1.4.1.14823.2.2.1.1.3.1.0",
        "1.3.6.1.4.1.14823.2.2.1.1.3.2.0",
    ],
    "metrics": [
        _metric("wlsxSysExtAccessPointsNum", "1.3.6.1.4.1.14823.2.2.1.1.3.1", "gauge", "Total active Access Points managed by Aruba Mobility Controller.", source_name="wlsxSysExtAccessPointsNum"),
        _metric("wlsxSysExtStationsNum", "1.3.6.1.4.1.14823.2.2.1.1.3.2", "gauge", "Total connected wireless clients on Aruba Mobility Controller.", source_name="wlsxSysExtStationsNum"),
    ],
}


RUCKUS_WIRELESS_CONFIG = {
    "schema_version": "1",
    "mib_sources": ["RUCKUS-ZD-SYSTEM-MIB", "RUCKUS-ROOT-MIB"],
    "source_urls": ["https://www.commscope.com/ruckus/"],
    "get": [
        "1.3.6.1.4.1.25053.1.2.1.1.1.0",
        "1.3.6.1.4.1.25053.1.2.1.1.2.0",
    ],
    "metrics": [
        _metric("ruckusZDTotalNumAP", "1.3.6.1.4.1.25053.1.2.1.1.1", "gauge", "Total number of APs connected to Ruckus ZoneDirector/SmartZone controller.", source_name="ruckusZDTotalNumAP"),
        _metric("ruckusZDTotalNumSta", "1.3.6.1.4.1.25053.1.2.1.1.2", "gauge", "Total number of client stations connected to Ruckus controller.", source_name="ruckusZDTotalNumSta"),
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
    _module(
        "module-ruijie-common",
        "ruijie_common",
        "锐捷通用设备",
        "ruijie",
        "rgos",
        "hardware",
        "hardware",
        "ruijie-device-cpu-memory:1.3.6.1.4.1.4881",
        "锐捷 RGOS 常用实体 CPU、内存使用率与温度 OID。",
        _variant("variant-ruijie-common-std", "ruijie_common_std", "锐捷通用标准版本", RUIJIE_ENTITY_CONFIG, mib_bundle_id="ruijie-device-cpu-memory-2024", supported_platforms=["ruijie_rgos", "ruijie", "rgos"], supported_models=["RG-S", "RG-NBS", "RG-CS", "RG-IS"], supported_version_scope=["RGOS", "11.x", "12.x"]),
    ),
    _module(
        "module-juniper-common",
        "juniper_common",
        "瞻博通用设备",
        "juniper",
        "junos",
        "hardware",
        "hardware",
        "juniper-operating-table:1.3.6.1.4.1.2636",
        "瞻博 JUNOS 常用实体 CPU、内存缓冲与温度 OID。",
        _variant("variant-juniper-common-std", "juniper_common_std", "瞻博通用标准版本", JUNIPER_ENTITY_CONFIG, mib_bundle_id="juniper-operating-table-2024", supported_platforms=["juniper_junos", "juniper", "junos"], supported_models=["EX", "QFX", "MX", "SRX"], supported_version_scope=["JUNOS"]),
    ),
    _module(
        "module-fortinet-common",
        "fortinet_common",
        "飞塔防火墙设备",
        "fortinet",
        "fortios",
        "hardware",
        "hardware",
        "fortinet-sys-stats:1.3.6.1.4.1.12356",
        "飞塔 FortiOS 常用系统 CPU、内存使用率与会话数 OID。",
        _variant("variant-fortinet-common-std", "fortinet_common_std", "飞塔通用标准版本", FORTINET_ENTITY_CONFIG, mib_bundle_id="fortinet-sys-stats-2024", supported_platforms=["fortinet_fortios", "fortinet", "fortios"], supported_models=["FortiGate", "FG-"], supported_version_scope=["FortiOS"]),
    ),
    _module(
        "module-zte-common",
        "zte_common",
        "中兴通用设备",
        "zte",
        "zxros",
        "hardware",
        "hardware",
        "zte-sys-stats:1.3.6.1.4.1.3902",
        "中兴 ZXR10 常用系统 CPU、内存利用率与板卡温度 OID。",
        _variant("variant-zte-common-std", "zte_common_std", "中兴通用标准版本", ZTE_ENTITY_CONFIG, mib_bundle_id="zte-zxr10-2024", supported_platforms=["zte", "zte_zxros", "zxros"], supported_models=["ZXR10", "ZXCTN", "ZXHN"], supported_version_scope=["ZXROS"]),
    ),
    _module(
        "module-maipu-common",
        "maipu_common",
        "迈普通用设备",
        "maipu",
        "mypower",
        "hardware",
        "hardware",
        "maipu-sys-stats:1.3.6.1.4.1.5651",
        "迈普 MyPower 常用 CPU（5分钟均值）、内存与温度 OID。",
        _variant("variant-maipu-common-std", "maipu_common_std", "迈普通用标准版本", MAIPU_ENTITY_CONFIG, mib_bundle_id="maipu-mypower-2024", supported_platforms=["maipu", "maipu_mypower", "mypower"], supported_models=["NSS", "S3", "S4", "MP"], supported_version_scope=["MyPower"]),
    ),
    _module(
        "module-dptech-common",
        "dptech_common",
        "迪普通用设备",
        "dptech",
        "conplat",
        "hardware",
        "hardware",
        "dptech-sys-stats:1.3.6.1.4.1.31648",
        "迪普 Conplat 常用交换机与安全网关 CPU、内存、温度与会话 OID。",
        _variant("variant-dptech-common-std", "dptech_common_std", "迪普通用标准版本", DPTECH_ENTITY_CONFIG, mib_bundle_id="dptech-conplat-2024", supported_platforms=["dptech", "dptech_conplat", "conplat"], supported_models=["DPX", "FW", "IPS"], supported_version_scope=["Conplat"]),
    ),
    _module(
        "module-hillstone-common",
        "hillstone_common",
        "山石网科安全设备",
        "hillstone",
        "stoneos",
        "hardware",
        "hardware",
        "hillstone-sys-stats:1.3.6.1.4.1.24681",
        "山石网科 StoneOS 防火墙常用 CPU、内存使用率与并发会话数 OID。",
        _variant("variant-hillstone-common-std", "hillstone_common_std", "山石网科标准版本", HILLSTONE_ENTITY_CONFIG, mib_bundle_id="hillstone-stoneos-2024", supported_platforms=["hillstone", "hillstone_stoneos", "stoneos"], supported_models=["SG-", "K-", "A-", "E-"], supported_version_scope=["StoneOS"]),
    ),
    _module(
        "module-sangfor-common",
        "sangfor_common",
        "深信服网关设备",
        "sangfor",
        "sangforos",
        "hardware",
        "hardware",
        "sangfor-sys-stats:1.3.6.1.4.1.35047",
        "深信服安全与应用交付网关常用 CPU、内存与连接数 OID。",
        _variant("variant-sangfor-common-std", "sangfor_common_std", "深信服通用标准版本", SANGFOR_ENTITY_CONFIG, mib_bundle_id="sangfor-sangforos-2024", supported_platforms=["sangfor", "sangfor_sangforos", "sangforos"], supported_models=["NGAF", "AC", "AD", "AF"], supported_version_scope=["SangforOS"]),
    ),
    _module(
        "module-dcn-common",
        "dcn_common",
        "神州数码网络设备",
        "dcn",
        "dcos",
        "hardware",
        "hardware",
        "dcn-sys-stats:1.3.6.1.4.1.6339",
        "神州数码 DCN 交换机常用 CPU、内存使用率与温度 OID。",
        _variant("variant-dcn-common-std", "dcn_common_std", "神州数码通用标准版本", DCN_ENTITY_CONFIG, mib_bundle_id="dcn-dcos-2024", supported_platforms=["dcn", "dcn_dcos", "dcos"], supported_models=["CS", "S4", "S5", "DCRS"], supported_version_scope=["DCOS"]),
    ),
    _module(
        "module-huawei-wireless",
        "huawei_wireless",
        "华为无线控制器（WLAN AC）",
        "huawei",
        "vrp",
        "wireless",
        "wireless",
        "huawei-wlan:1.3.6.1.4.1.2011.6.139",
        "华为 WLAN AC 在线 AP 数、离线 AP 数与关联无线客户端用户数。",
        _variant("variant-huawei-wireless-std", "huawei_wireless_std", "华为无线标准版本", HUAWEI_WIRELESS_CONFIG, mib_bundle_id="huawei-wlan-2024", supported_platforms=["huawei_vrp", "huawei_wlan", "huawei"], supported_models=["AC6", "AC9", "AirEngine"], supported_version_scope=["VRP WLAN"]),
    ),
    _module(
        "module-h3c-wireless",
        "h3c_wireless",
        "华三无线控制器（Dot11 AC）",
        "h3c",
        "comware",
        "wireless",
        "wireless",
        "h3c-dot11:1.3.6.1.4.1.25506.2.75",
        "华三 Comware 无线 AC 在线 AP 总数与关联无线终端客户端数。",
        _variant("variant-h3c-wireless-std", "h3c_wireless_std", "华三无线标准版本", H3C_WIRELESS_CONFIG, mib_bundle_id="hh3c-dot11-2024", supported_platforms=["h3c_comware_v7", "h3c_comware_v5", "h3c_wlan", "h3c"], supported_models=["WX", "MSG", "WAP"], supported_version_scope=["Comware Dot11"]),
    ),
    _module(
        "module-ruijie-wireless",
        "ruijie_wireless",
        "锐捷无线控制器（RG-WS）",
        "ruijie",
        "rgos",
        "wireless",
        "wireless",
        "ruijie-wlan:1.3.6.1.4.1.4881.1.1.10.2.75",
        "锐捷无线控制器纳管 AP 总数、在线 AP 数与在线关联终端数。",
        _variant("variant-ruijie-wireless-std", "ruijie_wireless_std", "锐捷无线标准版本", RUIJIE_WIRELESS_CONFIG, mib_bundle_id="ruijie-wlan-2024", supported_platforms=["ruijie_rgos", "ruijie_wlan", "ruijie"], supported_models=["RG-WS", "WS6", "RG-M"], supported_version_scope=["RGOS WLAN"]),
    ),
    _module(
        "module-cisco-wireless",
        "cisco_wireless",
        "思科无线控制器（WLC / 9800）",
        "cisco",
        "iosxe",
        "wireless",
        "wireless",
        "cisco-lwapp:1.3.6.1.4.1.9.9.513",
        "思科 AireOS / Catalyst 9800 WLC 在线 AP 总数与无线客户端总数。",
        _variant("variant-cisco-wireless-std", "cisco_wireless_std", "思科无线标准版本", CISCO_WIRELESS_CONFIG, mib_bundle_id="cisco-lwapp-2024", supported_platforms=["cisco_iosxe", "cisco_aireos", "cisco_wlc", "cisco"], supported_models=["Catalyst 9800", "AIR-CT", "WLC"], supported_version_scope=["IOS-XE Wireless", "AireOS"]),
    ),
    _module(
        "module-aruba-wireless",
        "aruba_wireless",
        "Aruba 无线控制器（Mobility Controller）",
        "aruba",
        "arubaos",
        "wireless",
        "wireless",
        "aruba-wlsx:1.3.6.1.4.1.14823.2.2.1",
        "Aruba Mobility Controller 在线 AP 数与活跃无线客户端站点数。",
        _variant("variant-aruba-wireless-std", "aruba_wireless_std", "Aruba 无线标准版本", ARUBA_WIRELESS_CONFIG, mib_bundle_id="aruba-wlsx-2024", supported_platforms=["aruba_arubaos", "arubaos", "aruba"], supported_models=["Aruba 7", "Aruba 9", "Controller"], supported_version_scope=["ArubaOS"]),
    ),
    _module(
        "module-ruckus-wireless",
        "ruckus_wireless",
        "优科无线控制器（ZoneDirector / SmartZone）",
        "ruckus",
        "smartzone",
        "wireless",
        "wireless",
        "ruckus-zd:1.3.6.1.4.1.25053.1",
        "Ruckus 优科 ZoneDirector / SmartZone 控制器纳管 AP 总数与无线终端数。",
        _variant("variant-ruckus-wireless-std", "ruckus_wireless_std", "优科无线标准版本", RUCKUS_WIRELESS_CONFIG, mib_bundle_id="ruckus-zd-2024", supported_platforms=["ruckus_smartzone", "smartzone", "ruckus"], supported_models=["ZoneDirector", "SmartZone", "SZ-", "ZD-"], supported_version_scope=["SmartZone"]),
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
