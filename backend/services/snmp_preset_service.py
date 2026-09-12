"""MD-backed SNMP preset profiles and built-in MIB seeder.

The official model template catalog is sourced from the vendor OID document
provided by the operator.  Standard/vendor MIB definitions are seeded
separately and are not model-template data.
"""

from __future__ import annotations

import hashlib
import logging
from copy import deepcopy
from typing import Any

from database import get_db_connection
from services.snmp_mib_service import deduplicate_builtin_mibs, parse_and_store_mib
from services.snmp_md_preset_catalog import get_md_official_model_presets

logger = logging.getLogger(__name__)

OFFICIAL_MODEL_PRESETS: list[dict[str, Any]] = get_md_official_model_presets()

# Built-in core standard MIB definitions (RFC1213, IF-MIB, HOST-RESOURCES, CISCO, HUAWEI, HH3C, ARISTA, JUNIPER, FORTINET, RUIJIE)
BUILTIN_MIB_SEEDS = [
    {
        "filename": "RFC1213-MIB.txt",
        "vendor": "Standard",
        "description": "Management Information Base for Network Management of TCP/IP-based internets: MIB-II",
        "content": """
RFC1213-MIB DEFINITIONS ::= BEGIN

IMPORTS
    mgmt, NetworkAddress, IpAddress, Counter, Gauge,
    TimeTicks FROM RFC1155-SMI
    OBJECT-TYPE FROM RFC-1212;

mib-2      OBJECT IDENTIFIER ::= { mgmt 1 }
system     OBJECT IDENTIFIER ::= { mib-2 1 }
interfaces OBJECT IDENTIFIER ::= { mib-2 2 }

sysDescr OBJECT-TYPE
    SYNTAX  DisplayString (SIZE (0..255))
    ACCESS  read-only
    STATUS  mandatory
    DESCRIPTION "A textual description of the entity."
    ::= { system 1 }

sysObjectID OBJECT-TYPE
    SYNTAX  OBJECT IDENTIFIER
    ACCESS  read-only
    STATUS  mandatory
    DESCRIPTION "The vendor's authoritative identification of the network management subsystem contained in the entity."
    ::= { system 2 }

sysUpTime OBJECT-TYPE
    SYNTAX  TimeTicks
    ACCESS  read-only
    STATUS  mandatory
    DESCRIPTION "The time (in hundredths of a second) since the network management portion of the system was last re-initialized."
    ::= { system 3 }

sysContact OBJECT-TYPE
    SYNTAX  DisplayString (SIZE (0..255))
    ACCESS  read-write
    STATUS  mandatory
    DESCRIPTION "The textual identification of the contact person for this managed node."
    ::= { system 4 }

sysName OBJECT-TYPE
    SYNTAX  DisplayString (SIZE (0..255))
    ACCESS  read-write
    STATUS  mandatory
    DESCRIPTION "An administratively-assigned name for this managed node."
    ::= { system 5 }

sysLocation OBJECT-TYPE
    SYNTAX  DisplayString (SIZE (0..255))
    ACCESS  read-write
    STATUS  mandatory
    DESCRIPTION "The physical location of this node."
    ::= { system 6 }

ifNumber OBJECT-TYPE
    SYNTAX  INTEGER
    ACCESS  read-only
    STATUS  mandatory
    DESCRIPTION "The number of network interfaces present on this system."
    ::= { interfaces 1 }

ifTable OBJECT-TYPE
    SYNTAX  SEQUENCE OF IfEntry
    ACCESS  not-accessible
    STATUS  mandatory
    DESCRIPTION "A list of interface entries."
    ::= { interfaces 2 }

ifEntry OBJECT-TYPE
    SYNTAX  IfEntry
    ACCESS  not-accessible
    STATUS  mandatory
    DESCRIPTION "An interface entry."
    ::= { ifTable 1 }

ifIndex OBJECT-TYPE
    SYNTAX  INTEGER
    ACCESS  read-only
    STATUS  mandatory
    DESCRIPTION "A unique value for each interface."
    ::= { ifEntry 1 }

ifDescr OBJECT-TYPE
    SYNTAX  DisplayString (SIZE (0..255))
    ACCESS  read-only
    STATUS  mandatory
    DESCRIPTION "A textual string containing information about the interface."
    ::= { ifEntry 2 }

ifSpeed OBJECT-TYPE
    SYNTAX  Gauge
    ACCESS  read-only
    STATUS  mandatory
    DESCRIPTION "An estimate of the interface's current bandwidth in bits per second."
    ::= { ifEntry 5 }

ifOperStatus OBJECT-TYPE
    SYNTAX  INTEGER { up(1), down(2), testing(3), unknown(4), dormant(5) }
    ACCESS  read-only
    STATUS  mandatory
    DESCRIPTION "The current operational state of the interface."
    ::= { ifEntry 8 }

ifInOctets OBJECT-TYPE
    SYNTAX  Counter
    ACCESS  read-only
    STATUS  mandatory
    DESCRIPTION "The total number of octets received on the interface."
    ::= { ifEntry 10 }

ifInErrors OBJECT-TYPE
    SYNTAX  Counter
    ACCESS  read-only
    STATUS  mandatory
    DESCRIPTION "The number of inbound packets that contained errors."
    ::= { ifEntry 14 }

ifOutOctets OBJECT-TYPE
    SYNTAX  Counter
    ACCESS  read-only
    STATUS  mandatory
    DESCRIPTION "The total number of octets transmitted out of the interface."
    ::= { ifEntry 16 }

ifOutErrors OBJECT-TYPE
    SYNTAX  Counter
    ACCESS  read-only
    STATUS  mandatory
    DESCRIPTION "The number of outbound packets that could not be transmitted."
    ::= { ifEntry 20 }

END
        """,
    },
    {
        "filename": "IF-MIB.txt",
        "vendor": "Standard",
        "description": "The MIB module to describe generic objects for network interface sub-layers (RFC 2863)",
        "content": """
IF-MIB DEFINITIONS ::= BEGIN

IMPORTS
    mib-2, Counter32, Counter64, Gauge32, Integer32, TimeTicks FROM SNMPv2-SMI
    OBJECT-TYPE FROM SNMPv2-SMI;

ifMIB OBJECT IDENTIFIER ::= { mib-2 31 }
ifMIBObjects OBJECT IDENTIFIER ::= { ifMIB 1 }
ifXTable OBJECT IDENTIFIER ::= { ifMIBObjects 1 }
ifXEntry OBJECT IDENTIFIER ::= { ifXTable 1 }

ifName OBJECT-TYPE
    SYNTAX      DisplayString
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The textual name of the interface."
    ::= { ifXEntry 1 }

ifHCInOctets OBJECT-TYPE
    SYNTAX      Counter64
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The total number of octets received on the interface. (64-bit high capacity counter)"
    ::= { ifXEntry 6 }

ifHCOutOctets OBJECT-TYPE
    SYNTAX      Counter64
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The total number of octets transmitted out of the interface. (64-bit high capacity counter)"
    ::= { ifXEntry 10 }

ifHighSpeed OBJECT-TYPE
    SYNTAX      Gauge32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "An estimate of the interface's current bandwidth in units of 1,000,000 bits per second (Mbps)."
    ::= { ifXEntry 15 }

ifAlias OBJECT-TYPE
    SYNTAX      DisplayString
    MAX-ACCESS  read-write
    STATUS      current
    DESCRIPTION "This object is an 'alias' name for the interface as specified by a network manager."
    ::= { ifXEntry 18 }

END
        """,
    },
    {
        "filename": "HOST-RESOURCES-MIB.txt",
        "vendor": "Standard",
        "description": "Host Resources MIB for Host and Processor Performance Monitoring (RFC 2790)",
        "content": """
HOST-RESOURCES-MIB DEFINITIONS ::= BEGIN

IMPORTS
    mib-2, Integer32, Gauge32 FROM SNMPv2-SMI
    OBJECT-TYPE FROM SNMPv2-SMI;

host OBJECT IDENTIFIER ::= { mib-2 25 }
hrStorage OBJECT IDENTIFIER ::= { host 2 }
hrDevice OBJECT IDENTIFIER ::= { host 3 }

hrProcessorTable OBJECT IDENTIFIER ::= { hrDevice 3 }
hrProcessorEntry OBJECT IDENTIFIER ::= { hrProcessorTable 1 }

hrProcessorLoad OBJECT-TYPE
    SYNTAX      Integer32 (0..100)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The average, over the last minute, of the percentage of time that this processor was not idle."
    ::= { hrProcessorEntry 2 }

hrStorageTable OBJECT IDENTIFIER ::= { hrStorage 3 }
hrStorageEntry OBJECT IDENTIFIER ::= { hrStorageTable 1 }

hrStorageIndex OBJECT-TYPE
    SYNTAX      Integer32 (1..2147483647)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "A unique value for each logical storage area."
    ::= { hrStorageEntry 1 }

hrStorageType OBJECT-TYPE
    SYNTAX      OBJECT IDENTIFIER
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The type of storage represented by this entry."
    ::= { hrStorageEntry 2 }

hrStorageDescr OBJECT-TYPE
    SYNTAX      DisplayString
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "A description of the storage area (e.g. Physical Memory, Flash, Storage)."
    ::= { hrStorageEntry 3 }

hrStorageAllocationUnits OBJECT-TYPE
    SYNTAX      Integer32 (1..2147483647)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The size, in bytes, of the data objects allocated to this storage area."
    ::= { hrStorageEntry 4 }

hrStorageSize OBJECT-TYPE
    SYNTAX      Integer32 (0..2147483647)
    MAX-ACCESS  read-write
    STATUS      current
    DESCRIPTION "The size of the storage represented by this entry, in units of hrStorageAllocationUnits."
    ::= { hrStorageEntry 5 }

hrStorageUsed OBJECT-TYPE
    SYNTAX      Integer32 (0..2147483647)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The amount of storage currently allocated, in units of hrStorageAllocationUnits."
    ::= { hrStorageEntry 6 }

END
        """,
    },
    {
        "filename": "CISCO-PROCESS-MIB.my",
        "vendor": "Cisco",
        "description": "Cisco Process and CPU Utilization MIB",
        "content": """
CISCO-PROCESS-MIB DEFINITIONS ::= BEGIN

IMPORTS
    ciscoMgmt, Gauge32 FROM SNMPv2-SMI
    OBJECT-TYPE FROM SNMPv2-SMI;

ciscoProcessMIB OBJECT IDENTIFIER ::= { ciscoMgmt 109 }
ciscoProcessMIBObjects OBJECT IDENTIFIER ::= { ciscoProcessMIB 1 }
cpmCPU OBJECT IDENTIFIER ::= { ciscoProcessMIBObjects 1 }
cpmCPUTotalTable OBJECT IDENTIFIER ::= { cpmCPU 1 }
cpmCPUTotalEntry OBJECT IDENTIFIER ::= { cpmCPUTotalTable 1 }

cpmCPUTotal5secRev OBJECT-TYPE
    SYNTAX      Gauge32 (0..100)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The overall CPU busy percentage in the last 5 second period."
    ::= { cpmCPUTotalEntry 6 }

cpmCPUTotal1minRev OBJECT-TYPE
    SYNTAX      Gauge32 (0..100)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The overall CPU busy percentage in the last 1 minute period."
    ::= { cpmCPUTotalEntry 7 }

cpmCPUTotal5minRev OBJECT-TYPE
    SYNTAX      Gauge32 (0..100)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The overall CPU busy percentage in the last 5 minute period."
    ::= { cpmCPUTotalEntry 8 }

END
        """,
    },
    {
        "filename": "CISCO-ENVMON-MIB.my",
        "vendor": "Cisco",
        "description": "Cisco Environmental Monitor MIB for Temperature, Fan, Power",
        "content": """
CISCO-ENVMON-MIB DEFINITIONS ::= BEGIN

IMPORTS
    ciscoMgmt, Integer32, Gauge32 FROM SNMPv2-SMI
    OBJECT-TYPE FROM SNMPv2-SMI;

ciscoEnvMonMIB OBJECT IDENTIFIER ::= { ciscoMgmt 13 }
ciscoEnvMonObjects OBJECT IDENTIFIER ::= { ciscoEnvMonMIB 1 }

ciscoEnvMonTemperatureStatusTable OBJECT IDENTIFIER ::= { ciscoEnvMonObjects 3 }
ciscoEnvMonTemperatureStatusEntry OBJECT IDENTIFIER ::= { ciscoEnvMonTemperatureStatusTable 1 }

ciscoEnvMonTemperatureStatusValue OBJECT-TYPE
    SYNTAX      Gauge32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The current temperature measured in degrees Celsius."
    ::= { ciscoEnvMonTemperatureStatusEntry 3 }

ciscoEnvMonFanStatusTable OBJECT IDENTIFIER ::= { ciscoEnvMonObjects 4 }
ciscoEnvMonFanStatusEntry OBJECT IDENTIFIER ::= { ciscoEnvMonFanStatusTable 1 }

ciscoEnvMonFanState OBJECT-TYPE
    SYNTAX      INTEGER { normal(1), warning(2), critical(3), shutdown(4), notPresent(5), notFunctioning(6) }
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The current state of the fan being instrumented."
    ::= { ciscoEnvMonFanStatusEntry 3 }

ciscoEnvMonSupplyStatusTable OBJECT IDENTIFIER ::= { ciscoEnvMonObjects 5 }
ciscoEnvMonSupplyStatusEntry OBJECT IDENTIFIER ::= { ciscoEnvMonSupplyStatusTable 1 }

ciscoEnvMonSupplyState OBJECT-TYPE
    SYNTAX      INTEGER { normal(1), warning(2), critical(3), shutdown(4), notPresent(5), notFunctioning(6) }
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The current state of the power supply being instrumented."
    ::= { ciscoEnvMonSupplyStatusEntry 3 }

END
        """,
    },
    {
        "filename": "HUAWEI-ENTITY-EXTENT-MIB.mib",
        "vendor": "Huawei",
        "description": "Huawei Entity Extent MIB for Hardware Performance Monitoring",
        "content": """
HUAWEI-ENTITY-EXTENT-MIB DEFINITIONS ::= BEGIN

IMPORTS
    huaweiMgmt, Integer32 FROM SNMPv2-SMI
    OBJECT-TYPE FROM SNMPv2-SMI;

hwEntityStateMIB OBJECT IDENTIFIER ::= { huaweiMgmt 25 }
hwEntityStateMIBObjects OBJECT IDENTIFIER ::= { hwEntityStateMIB 31 }
hwEntityStateTable OBJECT IDENTIFIER ::= { hwEntityStateMIBObjects 1 }
hwEntityStateEntry OBJECT IDENTIFIER ::= { hwEntityStateTable 1 }

hwEntityCpuUsage OBJECT-TYPE
    SYNTAX      Integer32 (0..100)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The CPU usage percentage of the entity."
    ::= { hwEntityStateEntry 5 }

hwEntityMemUsage OBJECT-TYPE
    SYNTAX      Integer32 (0..100)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The memory usage percentage of the entity."
    ::= { hwEntityStateEntry 7 }

hwEntityTemperature OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The temperature in degrees Celsius of the entity."
    ::= { hwEntityStateEntry 11 }

hwEntityFanState OBJECT-TYPE
    SYNTAX      INTEGER { normal(1), abnormal(2) }
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The state of the fan entity."
    ::= { hwEntityStateEntry 10 }

END
        """,
    },
    {
        "filename": "HH3C-ENTITY-EXT-MIB.mib",
        "vendor": "H3C",
        "description": "H3C Entity Extension MIB for Comware Devices",
        "content": """
HH3C-ENTITY-EXT-MIB DEFINITIONS ::= BEGIN

IMPORTS
    hh3cCommon, Integer32 FROM SNMPv2-SMI
    OBJECT-TYPE FROM SNMPv2-SMI;

hh3cEntityExtMIB OBJECT IDENTIFIER ::= { hh3cCommon 6 }
hh3cEntityExtObjects OBJECT IDENTIFIER ::= { hh3cEntityExtMIB 1 }
hh3cEntityExtStateTable OBJECT IDENTIFIER ::= { hh3cEntityExtObjects 1 }
hh3cEntityExtStateEntry OBJECT IDENTIFIER ::= { hh3cEntityExtStateTable 1 }

hh3cEntityExtCpuUsage OBJECT-TYPE
    SYNTAX      Integer32 (0..100)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The CPU utilization ratio of the entity."
    ::= { hh3cEntityExtStateEntry 6 }

hh3cEntityExtMemUsage OBJECT-TYPE
    SYNTAX      Integer32 (0..100)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The memory utilization ratio of the entity."
    ::= { hh3cEntityExtStateEntry 8 }

hh3cEntityExtTemperature OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The temperature in degrees Celsius of the entity."
    ::= { hh3cEntityExtStateEntry 12 }

END
        """,
    },
    {
        "filename": "JUNIPER-OPERATING-MIB.mib",
        "vendor": "Juniper",
        "description": "Juniper Networks Operating Performance and Hardware Sensor MIB",
        "content": """
JUNIPER-OPERATING-MIB DEFINITIONS ::= BEGIN

IMPORTS
    juniperMIB, Integer32, Gauge32 FROM SNMPv2-SMI
    OBJECT-TYPE FROM SNMPv2-SMI;

jnxMibs OBJECT IDENTIFIER ::= { juniperMIB 1 }
jnxOperatingTable OBJECT IDENTIFIER ::= { jnxMibs 13 }
jnxOperatingEntry OBJECT IDENTIFIER ::= { jnxOperatingTable 1 }

jnxOperatingTemp OBJECT-TYPE
    SYNTAX      Gauge32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The temperature in degrees Celsius of this operating component."
    ::= { jnxOperatingEntry 7 }

jnxOperatingCPU OBJECT-TYPE
    SYNTAX      Integer32 (0..100)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The CPU utilization in percent for this operating component."
    ::= { jnxOperatingEntry 8 }

jnxOperatingBuffer OBJECT-TYPE
    SYNTAX      Integer32 (0..100)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The buffer/memory pool utilization in percent for this component."
    ::= { jnxOperatingEntry 11 }

END
        """,
    },
    {
        "filename": "FORTINET-FORTIGATE-MIB.mib",
        "vendor": "Fortinet",
        "description": "Fortinet FortiGate System and Performance MIB",
        "content": """
FORTINET-FORTIGATE-MIB DEFINITIONS ::= BEGIN

IMPORTS
    enterprises, Gauge32, Integer32 FROM SNMPv2-SMI
    OBJECT-TYPE FROM SNMPv2-SMI;

fortinet OBJECT IDENTIFIER ::= { enterprises 12356 }
fnFortiGateMib OBJECT IDENTIFIER ::= { fortinet 101 }
fgSystem OBJECT IDENTIFIER ::= { fnFortiGateMib 4 }
fgSystemInfo OBJECT IDENTIFIER ::= { fgSystem 1 }

fgSysCpuUsage OBJECT-TYPE
    SYNTAX      Gauge32 (0..100)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Current CPU usage percentage of the FortiGate device."
    ::= { fgSystemInfo 3 }

fgSysMemUsage OBJECT-TYPE
    SYNTAX      Gauge32 (0..100)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Current memory usage percentage of the FortiGate device."
    ::= { fgSystemInfo 4 }

fgSysSesCount OBJECT-TYPE
    SYNTAX      Gauge32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Total active sessions currently open on the FortiGate unit."
    ::= { fgSystemInfo 8 }

END
        """,
    },
    {
        "filename": "RUIJIE-DEVICE-MIB.mib",
        "vendor": "Ruijie",
        "description": "Ruijie Networks System Device and Hardware Performance MIB",
        "content": """
RUIJIE-DEVICE-MIB DEFINITIONS ::= BEGIN

IMPORTS
    ruijie, Integer32 FROM SNMPv2-SMI
    OBJECT-TYPE FROM SNMPv2-SMI;

ruijieDeviceMIB OBJECT IDENTIFIER ::= { ruijie 10 }
ruijieDeviceObjects OBJECT IDENTIFIER ::= { ruijieDeviceMIB 2 }
ruijieSystemPerformance OBJECT IDENTIFIER ::= { ruijieDeviceObjects 35 }
ruijieCpuMemEntry OBJECT IDENTIFIER ::= { ruijieSystemPerformance 1 }

ruijieMemUsage OBJECT-TYPE
    SYNTAX      Integer32 (0..100)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Ruijie system memory utilization percentage."
    ::= { ruijieCpuMemEntry 2 }

ruijieCpuUsage OBJECT-TYPE
    SYNTAX      Integer32 (0..100)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Ruijie system 5-second CPU utilization percentage."
    ::= { ruijieCpuMemEntry 3 }

ruijieDeviceTemperature OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Ruijie device temperature in degrees Celsius."
    ::= { ruijieCpuMemEntry 4 }

END
        """,
    },
]


def list_preset_profiles() -> list[dict[str, Any]]:
    """Return all official pre-built model metric presets."""
    return list(OFFICIAL_MODEL_PRESETS)


def _builtin_mib_id(item: dict[str, Any]) -> str:
    """Return a stable identity for one built-in catalog definition."""
    identity = f"{str(item['vendor']).strip().lower()}\0{str(item['filename']).strip().lower()}"
    return f"builtin-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]}"


def seed_builtin_mibs() -> int:
    """Seed standard and vendor core MIBs into the database if not present."""
    conn = get_db_connection()
    count = 0
    try:
        for index, item in enumerate(BUILTIN_MIB_SEEDS):
            savepoint = f"snmp_builtin_seed_{index}"
            conn.execute(f"SAVEPOINT {savepoint}")
            try:
                parse_and_store_mib(
                    conn,
                    filename=item["filename"],
                    raw_text=item["content"].strip(),
                    vendor=item["vendor"],
                    source_type="builtin",
                    description=item["description"],
                    existing_id=_builtin_mib_id(item),
                )
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                count += 1
            except Exception as exc:
                try:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                except Exception:
                    conn.rollback()
                    raise
                logger.warning("Failed to seed builtin MIB %s: %s", item["filename"], str(exc)[:500])
        deduplicate_builtin_mibs(conn)
        conn.commit()
    finally:
        conn.close()
    return count


def reset_builtin_mibs() -> int:
    """Force re-parse and refresh all built-in core MIBs in the repository."""
    conn = get_db_connection()
    count = 0
    try:
        # Delete existing built-in MIBs to allow fresh seeding
        conn.execute("DELETE FROM snmp_mibs WHERE source_type = 'builtin'")
        for index, item in enumerate(BUILTIN_MIB_SEEDS):
            savepoint = f"snmp_builtin_reset_{index}"
            conn.execute(f"SAVEPOINT {savepoint}")
            try:
                parse_and_store_mib(
                    conn,
                    filename=item["filename"],
                    raw_text=item["content"].strip(),
                    vendor=item["vendor"],
                    source_type="builtin",
                    description=item["description"],
                    existing_id=_builtin_mib_id(item),
                )
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                count += 1
            except Exception as exc:
                try:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                except Exception:
                    conn.rollback()
                    raise
                logger.warning("Failed to reset builtin MIB %s: %s", item["filename"], str(exc)[:500])
        deduplicate_builtin_mibs(conn)
        conn.commit()
    finally:
        conn.close()
    return count


def match_profile_for_model(vendor: str, model: str) -> dict[str, Any] | None:
    """Match an asset to one of the MD-backed vendor/model templates.

    The matcher deliberately uses the same MD catalog that the preset API
    exposes.  It does not infer an unlisted vendor or manufacture a
    model-specific OID set.
    """

    v_clean = str(vendor or "").strip().lower()
    m_clean = str(model or "").strip().lower()
    if not v_clean and not m_clean:
        return None

    aliases = {
        "华三": "h3c",
        "新华三": "h3c",
        "华为": "huawei",
        "中兴": "zte",
        "思科": "cisco",
    }
    for alias, canonical in aliases.items():
        if alias in v_clean:
            v_clean = canonical
            break

    def preset_for(preset_id: str, model_hint: str = "") -> dict[str, Any] | None:
        candidates = [
            item
            for item in OFFICIAL_MODEL_PRESETS
            if item.get("id") == preset_id or item.get("family_id") == preset_id
        ]
        if not candidates:
            return None

        # Prefer an explicitly named model row when the asset model contains
        # the series marker.  Keep the V5 row separate from the V7 OIDs.
        hint = model_hint.casefold()
        if "v5" in hint:
            v5 = next((item for item in candidates if "v5" in str(item.get("model", "")).casefold()), None)
            if v5:
                return v5
        for item in candidates:
            candidate_model = str(item.get("model", "")).casefold()
            if candidate_model and candidate_model in hint and item.get("testable", True):
                return item
        return next((item for item in candidates if item.get("testable", True)), candidates[0])

    def result(
        preset_id: str,
        match_type: str,
        confidence: float,
        matched_series: str,
    ) -> dict[str, Any] | None:
        preset = preset_for(preset_id, m_clean)
        if not preset:
            return None
        return {
            "match_type": match_type,
            "confidence": confidence,
            "matched_series": matched_series,
            "preset": preset,
        }

    # Exact matches remain supported for the compact MD model labels.
    for preset in OFFICIAL_MODEL_PRESETS:
        p_vendor = str(preset.get("vendor", "")).strip().lower()
        p_model = str(preset.get("model", "")).strip().lower()
        if (not v_clean or p_vendor == v_clean) and p_model == m_clean:
            return {
                "match_type": "exact",
                "confidence": 1.0,
                "matched_series": preset["model"],
                "preset": preset,
            }

    h3c_markers = (
        "s5000", "s5110", "s5120", "s5130", "s5135", "s5170", "s5500",
        "s5800", "s6300", "s6500", "s6800", "s10500",
        "comware",
    )
    if v_clean == "h3c" or "h3c" in v_clean or any(marker in m_clean for marker in h3c_markers):
        confidence = 0.95 if any(marker in m_clean for marker in h3c_markers) else 0.88
        return result(
            "md-h3c-comware-v7",
            "series_inferred" if confidence > 0.9 else "vendor_default",
            confidence,
            "H3C Comware V7（MD 厂商模板）",
        )

    huawei_markers = (
        "s3700", "s5700", "s6700", "s7700", "s8700", "s9700", "s12700",
        "s16700", "vrp",
    )
    if v_clean == "huawei" or "huawei" in v_clean or any(marker in m_clean for marker in huawei_markers):
        confidence = 0.95 if any(marker in m_clean for marker in huawei_markers) else 0.88
        return result(
            "md-huawei-vrp-switch",
            "series_inferred" if confidence > 0.9 else "vendor_default",
            confidence,
            "Huawei VRP Switch（MD 厂商模板）",
        )

    if v_clean == "zte" or "zte" in v_clean or "zxr10" in m_clean:
        confidence = 0.95 if "zxr10" in m_clean else 0.88
        return result(
            "md-zte-zxr10-switch",
            "series_inferred" if confidence > 0.9 else "vendor_default",
            confidence,
            "ZTE ZXR10（MD 厂商模板）",
        )

    if "nexus" in m_clean:
        # Nexus is intentionally not part of the MD-backed official catalog:
        # the supplied MD does not provide a verified numeric OID set.  Do
        # not fall through to the generic Cisco Catalyst recommendation.
        return None

    if v_clean == "cisco" or "cisco" in v_clean or "catalyst" in m_clean:
        confidence = 0.95 if "catalyst" in m_clean else 0.88
        return result(
            "md-cisco-catalyst-categraf",
            "series_inferred" if confidence > 0.9 else "vendor_default",
            confidence,
            "Cisco Catalyst Categraf（MD 厂商模板）",
        )

    return None
