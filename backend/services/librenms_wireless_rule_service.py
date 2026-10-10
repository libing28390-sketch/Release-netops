"""Python execution of narrowly pinned LibreNMS wireless MIB inputs.

LibreNMS bundles vendor MIBs, but not every controller has an upstream PHP OS
wireless collector. This module keeps MIB-derived adapters explicitly labeled
and never executes PHP source.
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Mapping

from database import get_db_connection
from services.librenms_source_policy import (
    PINNED_LIBRENMS_COMMIT,
    verify_librenms_mib_rule,
)


_H3C_RULE = {
    "source_type": "librenms_mib_rule",
    "rule_key": "wireless_h3c_comware",
    "source_path": "mibs/comware/HH3C-DOT11-APMT-MIB",
    "mib_source_files": [
        "mibs/comware/HH3C-DOT11-ACMT-MIB",
        "mibs/comware/HH3C-DOT11-APMT-MIB",
        "mibs/comware/HH3C-DOT11-STATION-MIB",
    ],
}
_HUAWEI_VRP_RULE = {
    "source_type": "librenms_mib_rule",
    "rule_key": "wireless_huawei_vrp",
    "source_path": "LibreNMS/OS/Vrp.php",
    "adapter_source_files": ["LibreNMS/Modules/Wireless.php", "LibreNMS/OS/Vrp.php"],
    "mib_source_files": [
        "mibs/huawei/HUAWEI-WLAN-GLOBAL-MIB",
        "mibs/huawei/HUAWEI-WLAN-AP-MIB",
        "mibs/huawei/HUAWEI-WLAN-AP-RADIO-MIB",
        "mibs/huawei/HUAWEI-WLAN-VAP-MIB",
    ],
}
_CISCO_IOS_RULE = {
    "source_type": "librenms_mib_rule",
    "rule_key": "wireless_cisco_ios",
    "source_path": "LibreNMS/OS/Ios.php",
    "adapter_source_files": [
        "LibreNMS/Modules/Wireless.php",
        "LibreNMS/OS/Ios.php",
        "LibreNMS/OS/Shared/Cisco.php",
        "LibreNMS/OS/Traits/CiscoCellular.php",
    ],
    "mib_source_files": [
        "mibs/cisco/CISCO-DOT11-ASSOCIATION-MIB",
        "mibs/cisco/CISCO-WAN-3G-MIB",
        "mibs/cisco/CISCO-WAN-CELL-EXT-MIB",
        "mibs/ENTITY-MIB",
    ],
}
_CISCO_IOSXE_CELLULAR_RULE = {
    "source_type": "librenms_mib_rule",
    "rule_key": "wireless_cisco_iosxe_cellular",
    "source_path": "LibreNMS/OS/Iosxe.php",
    "adapter_source_files": [
        "LibreNMS/Modules/Wireless.php",
        "LibreNMS/OS/Ciscowlc.php",
        "LibreNMS/OS/Iosxe.php",
        "LibreNMS/OS/Shared/Cisco.php",
        "LibreNMS/OS/Traits/CiscoCellular.php",
    ],
    "mib_source_files": [
        "mibs/cisco/CISCO-WAN-3G-MIB",
        "mibs/cisco/CISCO-WAN-CELL-EXT-MIB",
        "mibs/ENTITY-MIB",
    ],
}

_CISCO_CELLULAR_MIB_SOURCES = {
    "CISCO-WAN-3G-MIB": "mibs/cisco/CISCO-WAN-3G-MIB",
    "CISCO-WAN-CELL-EXT-MIB": "mibs/cisco/CISCO-WAN-CELL-EXT-MIB",
    "ENTITY-MIB": "mibs/ENTITY-MIB",
}
_CISCO_CELLULAR_SYMBOLS = {
    "rssi": ("CISCO-WAN-3G-MIB", "c3gCurrentGsmRssi"),
    "channel": ("CISCO-WAN-3G-MIB", "c3gGsmChannelNumber"),
    "cell": ("CISCO-WAN-3G-MIB", "c3gGsmCurrentCellId"),
    "rsrp": ("CISCO-WAN-CELL-EXT-MIB", "cwceLteCurrRsrp"),
    "rsrq": ("CISCO-WAN-CELL-EXT-MIB", "cwceLteCurrRsrq"),
    "snr": ("CISCO-WAN-CELL-EXT-MIB", "cwceLteCurrSnr"),
    "apn": ("CISCO-WAN-CELL-EXT-MIB", "cwceLteProfileApn"),
    "modem_name": ("ENTITY-MIB", "entPhysicalName"),
}

_STELLAR_OAW_MODULES = (
    "OAW-AP1101",
    "OAW-AP1201",
    "OAW-AP1201BG",
    "OAW-AP1201H",
    "OAW-AP1201HL",
    "OAW-AP1201L",
    "OAW-AP1221",
    "OAW-AP1222",
    "OAW-AP1231",
    "OAW-AP1232",
    "OAW-AP1251",
    "OAW-AP1251D",
    "OAW-AP1321",
    "OAW-AP1322",
    "OAW-AP1361",
    "OAW-AP1361D",
    "OAW-AP1362",
)
_STELLAR_MODEL_TO_MIB = {model.casefold(): model for model in _STELLAR_OAW_MODULES}
_STELLAR_MIB_SOURCE_FILES = tuple(
    f"mibs/nokia/stellar/{module}"
    for module in (
        "ALCATEL-NGOAW-BASE-MIB",
        "ALCATEL-NGOAW-DEVICES-MIB",
        *_STELLAR_OAW_MODULES,
    )
)
_STELLAR_WIRELESS_RULE = {
    "source_type": "librenms_mib_rule",
    "rule_key": "wireless_stellar",
    "source_path": "LibreNMS/OS/Stellar.php",
    "adapter_source_files": ["LibreNMS/Modules/Wireless.php", "LibreNMS/OS/Stellar.php"],
    "mib_source_files": list(_STELLAR_MIB_SOURCE_FILES),
}

# The upstream LibreNMS classes below expose wireless counts as pollable
# scalars or indexed MIB tables.  Keep each platform's exact upstream inputs
# separate so a controller rule cannot silently become a generic vendor OID.
_PROFILE_WIRELESS_RULES: dict[str, dict[str, Any]] = {
    "aruba-instant": {
        "source_rule": {
            "source_type": "librenms_mib_rule",
            "rule_key": "wireless_aruba_instant",
            "source_path": "LibreNMS/OS/ArubaInstant.php",
            "adapter_source_files": ["LibreNMS/Modules/Wireless.php", "LibreNMS/OS/ArubaInstant.php"],
            "mib_source_files": ["mibs/arubaos/AI-AP-MIB"],
        },
        "mib_sources": {"AI-AP-MIB": "mibs/arubaos/AI-AP-MIB"},
        "symbols": {
            "ap_serials": ("AI-AP-MIB", "aiAPSerialNum"),
            "client_macs": ("AI-AP-MIB", "aiClientMACAddress"),
            "ssid_clients": ("AI-AP-MIB", "aiSSIDClientNum"),
            "ssid_names": ("AI-AP-MIB", "aiSSID"),
        },
        "scalars": [],
        "tables": [
            {"symbol": "ssid_clients", "component_class": "wireless_ssid", "sensor_class": "clients", "unit": "count", "name": "SSID clients", "label_symbols": {"ssid": "ssid_names"}, "minimum_software_version": "8.4.0.0"},
        ],
        "aggregates": [
            {"symbol": "ap_serials", "kind": "table_count", "component_class": "wireless_controller", "sensor_class": "ap-count", "unit": "count", "name": "Total APs", "suffix": "total-aps", "labels": {"group": "access-points"}, "emit_on_empty": True},
            {"symbol": "ssid_clients", "kind": "table_sum", "component_class": "wireless_controller", "sensor_class": "clients", "unit": "count", "name": "Total Clients", "suffix": "total-clients", "labels": {"group": "clients"}, "minimum_software_version": "8.4.0.0", "emit_on_empty": True},
            {"symbol": "client_macs", "kind": "table_count", "component_class": "wireless_controller", "sensor_class": "clients", "unit": "count", "name": "Total Clients", "suffix": "total-clients", "labels": {"group": "clients"}, "maximum_software_version_exclusive": "8.4.0.0", "emit_on_empty": True},
        ],
    },
    "arubaos": {
        "source_rule": {
            "source_type": "librenms_mib_rule", "rule_key": "wireless_arubaos",
            "source_path": "LibreNMS/OS/Arubaos.php",
            "adapter_source_files": [
                "LibreNMS/Modules/Wireless.php",
                "LibreNMS/OS/Arubaos.php",
                "includes/polling/aruba-controller.inc.php",
            ],
            "mib_source_files": [
                "mibs/arubaos/WLSX-SWITCH-MIB",
                "mibs/arubaos/WLSX-WLAN-MIB",
                "mibs/arubaos/AI-AP-MIB",
            ],
        },
        "mib_sources": {
            "WLSX-SWITCH-MIB": "mibs/arubaos/WLSX-SWITCH-MIB",
            "WLSX-WLAN-MIB": "mibs/arubaos/WLSX-WLAN-MIB",
            "AI-AP-MIB": "mibs/arubaos/AI-AP-MIB",
        },
        "detail_symbols": {
            "ap_name": ("WLSX-WLAN-MIB", "wlanAPRadioAPName"),
            "radio_type": ("WLSX-WLAN-MIB", "wlanAPRadioType"),
            "channel": ("WLSX-WLAN-MIB", "wlanAPRadioChannel"),
            "tx_power_10x": ("WLSX-WLAN-MIB", "wlanAPRadioTransmitPower10x"),
            "tx_power": ("WLSX-WLAN-MIB", "wlanAPRadioTransmitPower"),
            "utilization": ("WLSX-WLAN-MIB", "wlanAPRadioUtilization"),
            "associated_clients": ("WLSX-WLAN-MIB", "wlanAPRadioNumAssociatedClients"),
            "monitored_clients": ("WLSX-WLAN-MIB", "wlanAPRadioNumMonitoredClients"),
            "active_bssids": ("WLSX-WLAN-MIB", "wlanAPRadioNumActiveBSSIDs"),
            "monitored_bssids": ("WLSX-WLAN-MIB", "wlanAPRadioNumMonitoredBSSIDs"),
            "interference": ("WLSX-WLAN-MIB", "wlanAPChInterferenceIndex"),
        },
        "scalars": [
            {"oid": "1.3.6.1.4.1.14823.2.2.1.1.3.1.0", "component_class": "wireless_controller", "sensor_class": "ap-count", "unit": "count", "name": "Connected APs", "group": "access-points"},
            {"oid": "1.3.6.1.4.1.14823.2.2.1.1.3.2.0", "component_class": "wireless_controller", "sensor_class": "clients", "unit": "count", "name": "Associated clients", "group": "clients"},
        ],
        "symbols": {
            "radio_channel": ("AI-AP-MIB", "aiRadioChannel"),
            "radio_noise_floor": ("AI-AP-MIB", "aiRadioNoiseFloor"),
            "radio_tx_power": ("AI-AP-MIB", "aiRadioTransmitPower"),
            "radio_utilization": ("AI-AP-MIB", "aiRadioUtilization64"),
        },
        "tables": [
            {"symbol": "radio_channel", "component_class": "wireless_radio", "sensor_class": "frequency", "unit": "MHz", "name": "Frequency", "value_transform": "channel_to_frequency"},
            {"symbol": "radio_noise_floor", "component_class": "wireless_radio", "sensor_class": "noise-floor", "unit": "dBm", "name": "Noise Floor", "allow_negative": True},
            {"symbol": "radio_tx_power", "component_class": "wireless_radio", "sensor_class": "power", "unit": "dBm", "name": "Tx Power", "allow_negative": True},
            {"symbol": "radio_utilization", "component_class": "wireless_radio", "sensor_class": "utilization", "unit": "percent", "name": "Utilization"},
        ],
    },
    "ciscowlc": {
        "source_rule": {
            "source_type": "librenms_mib_rule", "rule_key": "wireless_cisco_wlc",
            "source_path": "LibreNMS/OS/Ciscowlc.php",
            "adapter_source_files": ["LibreNMS/Modules/Wireless.php", "LibreNMS/OS/Ciscowlc.php", "LibreNMS/OS/Iosxe.php", "LibreNMS/OS/Shared/Cisco.php", "LibreNMS/OS/Traits/CiscoCellular.php"],
            "mib_source_files": [
                "mibs/cisco/AIRESPACE-SWITCHING-MIB", "mibs/cisco/AIRESPACE-WIRELESS-MIB",
                "mibs/cisco/CISCO-LWAPP-AP-MIB", "mibs/cisco/CISCO-LWAPP-SYS-MIB",
                "mibs/cisco/CISCO-LWAPP-WLAN-MIB",
                "mibs/cisco/CISCO-WAN-3G-MIB", "mibs/cisco/CISCO-WAN-CELL-EXT-MIB", "mibs/ENTITY-MIB",
            ],
        },
        "mib_sources": {
            "AIRESPACE-WIRELESS-MIB": "mibs/cisco/AIRESPACE-WIRELESS-MIB",
            "CISCO-LWAPP-WLAN-MIB": "mibs/cisco/CISCO-LWAPP-WLAN-MIB",
            **_CISCO_CELLULAR_MIB_SOURCES,
        },
        "symbols": {
            "ssid_clients": ("AIRESPACE-WIRELESS-MIB", "bsnDot11EssNumberOfMobileStations"),
            "ssid_names": ("AIRESPACE-WIRELESS-MIB", "bsnDot11EssSsid"),
            "lwapp_ssid_names": ("CISCO-LWAPP-WLAN-MIB", "cLWlanSsid"),
            **_CISCO_CELLULAR_SYMBOLS,
        },
        "detail_symbols": {
            "ap_name": ("AIRESPACE-WIRELESS-MIB", "bsnAPName"),
            "radio_type": ("AIRESPACE-WIRELESS-MIB", "bsnAPIfType"),
            "channel": ("AIRESPACE-WIRELESS-MIB", "bsnAPIfPhyChannelNumber"),
            "tx_power": ("AIRESPACE-WIRELESS-MIB", "bsnAPIfPhyTxPowerLevel"),
            "utilization": ("AIRESPACE-WIRELESS-MIB", "bsnAPIfLoadChannelUtilization"),
            "associated_clients": ("AIRESPACE-WIRELESS-MIB", "bsnApIfNoOfUsers"),
            "interference": ("AIRESPACE-WIRELESS-MIB", "bsnAPIfInterferencePower"),
        },
        "scalar_groups": [{
            "component_class": "wireless_controller", "sensor_class": "ap-count",
            "unit": "count", "name": "Connected APs", "group": "access-points",
            "oids": [
                "1.3.6.1.4.1.9.9.513.1.3.35.0",
                "1.3.6.1.4.1.9.9.618.1.8.4.0",
            ],
        }],
        "scalars": [],
        "tables": [{
            "symbol": "ssid_clients", "component_class": "wireless_ssid",
            "sensor_class": "clients", "unit": "count", "name": "SSID clients",
            "label_symbols": {"ssid": ["ssid_names", "lwapp_ssid_names"]},
        }],
        "aggregates": [{
            "symbol": "ssid_clients", "kind": "table_sum",
            "component_class": "wireless_controller", "sensor_class": "clients",
            "unit": "count", "name": "Clients: Total", "suffix": "total-clients",
            "labels": {"group": "clients"}, "minimum_rows": 1,
        }],
    },
    "iosxe": {"alias_of": "ciscowlc"},
    "ewc": {
        "source_rule": {
            "source_type": "librenms_mib_rule", "rule_key": "wireless_extreme_ewc",
            "source_path": "LibreNMS/OS/Ewc.php", "adapter_source_files": ["LibreNMS/Modules/Wireless.php", "LibreNMS/OS/Ewc.php"],
            "mib_source_files": [
                "mibs/ewc/HIPATH-WIRELESS-HWC-MIB",
                "mibs/ewc/HIPATH-WIRELESS-DOT11-EXTNS-MIB",
                "mibs/ewc/HIPATH-WIRELESS-SMI",
                "mibs/IEEE802dot11-MIB",
            ],
        },
        "mib_sources": {
            "HIPATH-WIRELESS-HWC-MIB": "mibs/ewc/HIPATH-WIRELESS-HWC-MIB",
            "HIPATH-WIRELESS-DOT11-EXTNS-MIB": "mibs/ewc/HIPATH-WIRELESS-DOT11-EXTNS-MIB",
        },
        "scalars": [
            {"oid": "1.3.6.1.4.1.4329.15.3.5.2.1.0", "component_class": "wireless_controller", "sensor_class": "ap-count", "unit": "count", "name": "Connected APs", "group": "access-points"},
            {"oid": "1.3.6.1.4.1.4329.15.3.5.1.1.0", "component_class": "wireless_controller", "sensor_class": "ap-count-configured", "unit": "count", "name": "Configured APs", "group": "access-points"},
            {"oid": "1.3.6.1.4.1.4329.15.3.6.1.0", "component_class": "wireless_controller", "sensor_class": "clients", "unit": "count", "name": "Connected clients", "group": "clients"},
        ],
        "tables": [{"symbol": "wlan_clients", "component_class": "wireless_ssid", "sensor_class": "clients", "unit": "count", "name": "SSID clients", "label_symbols": {"ssid": "wlan_names"}}],
        "symbols": {
            "wlan_clients": ("HIPATH-WIRELESS-HWC-MIB", "wlanStatsAssociatedClients"),
            "wlan_names": ("HIPATH-WIRELESS-HWC-MIB", "wlanName"),
        },
    },
    "ruckuswireless": {
        "source_rule": {
            "source_type": "librenms_mib_rule", "rule_key": "wireless_ruckus_zd",
            "source_path": "LibreNMS/OS/Ruckuswireless.php", "adapter_source_files": ["LibreNMS/Modules/Wireless.php", "LibreNMS/OS/Ruckuswireless.php"],
            "mib_source_files": ["mibs/ruckus/RUCKUS-ZD-SYSTEM-MIB", "mibs/ruckus/RUCKUS-ZD-WLAN-MIB"],
        },
        "mib_sources": {"RUCKUS-ZD-WLAN-MIB": "mibs/ruckus/RUCKUS-ZD-WLAN-MIB"},
        "symbols": {"ssid_clients": ("RUCKUS-ZD-WLAN-MIB", "ruckusZDWLANNumSta"), "ssid_names": ("RUCKUS-ZD-WLAN-MIB", "ruckusZDWLANSSID")},
        "scalars": [
            {"oid": "1.3.6.1.4.1.25053.1.2.1.1.1.15.1.0", "component_class": "wireless_controller", "sensor_class": "ap-count", "unit": "count", "name": "Connected APs", "group": "access-points", "identity_suffix": "1"},
            {"oid": "1.3.6.1.4.1.25053.1.2.1.1.1.15.15.0", "component_class": "wireless_controller", "sensor_class": "ap-count", "unit": "count", "name": "Total APs", "group": "access-points", "identity_suffix": "2"},
        ],
        "tables": [{
            "symbol": "ssid_clients", "component_class": "wireless_ssid", "sensor_class": "clients",
            "unit": "count", "name": "SSID clients", "label_symbols": {"ssid": "ssid_names"},
            "conditional_total": {
                "oid": "1.3.6.1.4.1.25053.1.2.1.1.1.15.2.0", "minimum_rows": 2,
                "component_class": "wireless_controller", "sensor_class": "clients", "unit": "count",
                "name": "System Total", "group": "clients", "identity_suffix": "1",
            },
        }],
    },
    "ruckuswireless-hotzone": {
        "source_rule": {
            "source_type": "librenms_mib_rule", "rule_key": "wireless_ruckus_hotzone",
            "source_path": "LibreNMS/OS/RuckuswirelessHotzone.php", "adapter_source_files": ["LibreNMS/Modules/Wireless.php", "LibreNMS/OS/RuckuswirelessHotzone.php"],
            "mib_source_files": ["mibs/ruckus/RUCKUS-ZD-SYSTEM-MIB"],
        },
        "mib_sources": {}, "symbols": {}, "tables": [],
        "scalars": [
            {"oid": "1.3.6.1.4.1.25053.1.1.12.1.1.1.3.1.2.1", "component_class": "wireless_controller", "sensor_class": "clients", "unit": "count", "name": "2.4 GHz clients", "group": "clients", "identity_suffix": "1"},
            {"oid": "1.3.6.1.4.1.25053.1.1.12.1.1.1.3.1.2.2", "component_class": "wireless_controller", "sensor_class": "clients", "unit": "count", "name": "5 GHz clients", "group": "clients", "identity_suffix": "2"},
            {"oid": "1.3.6.1.4.1.25053.1.1.12.1.1.1.3.1.50.1", "component_class": "wireless_radio", "sensor_class": "utilization-2g", "unit": "percent", "name": "2.4 GHz Utilization"},
            {"oid": "1.3.6.1.4.1.25053.1.1.12.1.1.1.3.1.50.2", "component_class": "wireless_radio", "sensor_class": "utilization-5g", "unit": "percent", "name": "5 GHz Utilization"},
            {"oid": "1.3.6.1.4.1.25053.1.1.12.1.1.1.2.1.8.1", "component_class": "wireless_radio", "sensor_class": "noise-floor-2g", "unit": "dBm", "name": "2.4 GHz Noise Floor", "allow_negative": True},
            {"oid": "1.3.6.1.4.1.25053.1.1.12.1.1.1.2.1.8.2", "component_class": "wireless_radio", "sensor_class": "noise-floor-5g", "unit": "dBm", "name": "5 GHz Noise Floor", "allow_negative": True},
            {"oid": "1.3.6.1.4.1.25053.1.1.12.1.1.1.3.1.21.1", "component_class": "wireless_radio", "sensor_class": "errors-2g", "unit": "count", "name": "2.4 GHz Received Errors"},
            {"oid": "1.3.6.1.4.1.25053.1.1.12.1.1.1.3.1.21.2", "component_class": "wireless_radio", "sensor_class": "errors-5g", "unit": "count", "name": "5 GHz Received Errors"},
        ],
    },
    "ruckuswireless-sz": {
        "source_rule": {
            "source_type": "librenms_mib_rule", "rule_key": "wireless_ruckus_sz",
            "source_path": "LibreNMS/OS/RuckuswirelessSz.php", "adapter_source_files": ["LibreNMS/Modules/Wireless.php", "LibreNMS/OS/RuckuswirelessSz.php"],
            "mib_source_files": ["mibs/ruckus/RUCKUS-CTRL-MIB", "mibs/ruckus/RUCKUS-SZ-SYSTEM-MIB", "mibs/ruckus/RUCKUS-SZ-WLAN-MIB"],
        },
        "mib_sources": {
            "RUCKUS-CTRL-MIB": "mibs/ruckus/RUCKUS-CTRL-MIB",
            "RUCKUS-SZ-WLAN-MIB": "mibs/ruckus/RUCKUS-SZ-WLAN-MIB",
        },
        "symbols": {
            "ssid_clients": ("RUCKUS-SZ-WLAN-MIB", "ruckusSZWLANNumSta"),
            "ssid_names": ("RUCKUS-SZ-WLAN-MIB", "ruckusSZWLANSSID"),
            "node_ap_counts": ("RUCKUS-CTRL-MIB", "ruckusCtrlSystemNodeNumApConnected"),
            "node_names": ("RUCKUS-CTRL-MIB", "ruckusCtrlSystemNodeName"),
        },
        "scalars": [{
            "oid": "1.3.6.1.4.1.25053.1.4.1.1.1.15.1.0", "component_class": "wireless_controller",
            "sensor_class": "ap-count", "unit": "count", "name": "Total APs", "group": "access-points",
            "identity_suffix": "1", "emit_if_value_gt": 1,
        }],
        "tables": [
            {
                "symbol": "ssid_clients", "component_class": "wireless_ssid", "sensor_class": "clients",
                "unit": "count", "name": "SSID clients", "label_symbols": {"ssid": "ssid_names"},
                "conditional_total": {
                    "oid": "1.3.6.1.4.1.25053.1.4.1.1.1.15.2.0", "minimum_rows": 2,
                    "component_class": "wireless_controller", "sensor_class": "clients", "unit": "count",
                    "name": "System Total", "group": "clients", "identity_suffix": "1",
                },
            },
            {
                "symbol": "node_ap_counts", "component_class": "wireless_controller", "sensor_class": "ap-count",
                "unit": "count", "name": "Connected APs", "label_symbols": {"node": "node_names"},
            },
        ],
    },
    "ruckuswireless-unleashed": {
        "source_rule": {
            "source_type": "librenms_mib_rule", "rule_key": "wireless_ruckus_unleashed",
            "source_path": "LibreNMS/OS/RuckuswirelessUnleashed.php", "adapter_source_files": ["LibreNMS/Modules/Wireless.php", "LibreNMS/OS/RuckuswirelessUnleashed.php"],
            "mib_source_files": ["mibs/ruckus/RUCKUS-UNLEASHED-SYSTEM-MIB"],
        },
        "mib_sources": {"RUCKUS-UNLEASHED-SYSTEM-MIB": "mibs/ruckus/RUCKUS-UNLEASHED-SYSTEM-MIB"},
        "symbols": {
            "ap_count": ("RUCKUS-UNLEASHED-SYSTEM-MIB", "ruckusUnleashedSystemStatsNumAP"),
            "clients": ("RUCKUS-UNLEASHED-SYSTEM-MIB", "ruckusUnleashedSystemStatsNumSta"),
        },
        "tables": [],
        "scalars": [
            {"symbol": "ap_count", "component_class": "wireless_controller", "sensor_class": "ap-count", "unit": "count", "name": "Connected APs", "group": "access-points", "identity_suffix": "1"},
            {"symbol": "clients", "component_class": "wireless_controller", "sensor_class": "clients", "unit": "count", "name": "Associated clients", "group": "clients", "identity_suffix": "1"},
        ],
    },
    "stellar": {
        "source_rule": _STELLAR_WIRELESS_RULE,
        "mib_sources": {},
        "symbols": {},
        "scalars": [],
        "tables": [],
    },
    "routeros": {
        "source_rule": {
            "source_type": "librenms_mib_rule", "rule_key": "wireless_mikrotik",
            "source_path": "LibreNMS/OS/Routeros.php", "adapter_source_files": ["LibreNMS/Modules/Wireless.php", "LibreNMS/OS/Routeros.php"],
            "mib_source_files": ["mibs/mikrotik/MIKROTIK-MIB"],
        },
        "mib_sources": {"MIKROTIK-MIB": "mibs/mikrotik/MIKROTIK-MIB"},
        "symbols": {
            "ap_clients": ("MIKROTIK-MIB", "mtxrWlApClientCount"),
            "ap_ssid": ("MIKROTIK-MIB", "mtxrWlApSsid"),
            "ap_frequency": ("MIKROTIK-MIB", "mtxrWlApFreq"),
            "ap_ccq": ("MIKROTIK-MIB", "mtxrWlApOverallTxCCQ"),
            "ap_noise": ("MIKROTIK-MIB", "mtxrWlApNoiseFloor"),
            "ap_tx_rate": ("MIKROTIK-MIB", "mtxrWlApTxRate"),
            "ap_rx_rate": ("MIKROTIK-MIB", "mtxrWlApRxRate"),
            "stat_ssid": ("MIKROTIK-MIB", "mtxrWlStatSsid"),
            "stat_frequency": ("MIKROTIK-MIB", "mtxrWlStatFreq"),
            "stat_tx_ccq": ("MIKROTIK-MIB", "mtxrWlStatTxCCQ"),
            "stat_rx_ccq": ("MIKROTIK-MIB", "mtxrWlStatRxCCQ"),
            "stat_tx_rate": ("MIKROTIK-MIB", "mtxrWlStatTxRate"),
            "stat_rx_rate": ("MIKROTIK-MIB", "mtxrWlStatRxRate"),
            "g60_ssid": ("MIKROTIK-MIB", "mtxrWl60GSsid"),
            "g60_frequency": ("MIKROTIK-MIB", "mtxrWl60GFreq"),
            "g60_rssi": ("MIKROTIK-MIB", "mtxrWl60GRssi"),
            "g60_quality": ("MIKROTIK-MIB", "mtxrWl60GSignal"),
            "g60_rate": ("MIKROTIK-MIB", "mtxrWl60GPhyRate"),
            "g60_distance": ("MIKROTIK-MIB", "mtxrWl60GStaDistance"),
            "g60_remote": ("MIKROTIK-MIB", "mtxrWl60GStaRemote"),
            "lte_rsrq": ("MIKROTIK-MIB", "mtxrLTEModemSignalRSRQ"),
            "lte_rsrp": ("MIKROTIK-MIB", "mtxrLTEModemSignalRSRP"),
            "lte_sinr": ("MIKROTIK-MIB", "mtxrLTEModemSignalSINR"),
            "interface_names": ("MIKROTIK-MIB", "mtxrInterfaceStatsName"),
        },
        "scalars": [],
        "tables": [
            {"symbol": "ap_clients", "component_class": "wireless_radio", "sensor_class": "clients", "unit": "count", "name": "Wireless Interface Clients", "label_symbols": {"ssid": "ap_ssid", "frequency": "ap_frequency"}},
            {"symbol": "ap_frequency", "component_class": "wireless_radio", "sensor_class": "frequency-ap", "unit": "MHz", "name": "Frequency", "label_symbols": {"ssid": "ap_ssid"}, "skip_value_strings": ["0"]},
            {"symbol": "stat_frequency", "component_class": "wireless_radio", "sensor_class": "frequency-station", "unit": "MHz", "name": "Frequency", "label_symbols": {"ssid": "stat_ssid"}, "skip_value_strings": ["0"]},
            {"symbol": "g60_frequency", "component_class": "wireless_radio", "sensor_class": "frequency-60g", "unit": "MHz", "name": "60 GHz Frequency", "label_symbols": {"ssid": "g60_ssid"}},
            {"symbol": "ap_ccq", "component_class": "wireless_radio", "sensor_class": "ccq-ap", "unit": "percent", "name": "Tx CCQ", "label_symbols": {"ssid": "ap_ssid", "frequency": "ap_frequency"}, "skip_zero_if_positive_symbol": "ap_clients"},
            {"symbol": "stat_tx_ccq", "component_class": "wireless_radio", "sensor_class": "ccq-tx", "unit": "percent", "name": "Tx CCQ", "label_symbols": {"ssid": "stat_ssid", "frequency": "stat_frequency"}, "skip_row_if_all_empty_or_zero_symbols": ["stat_tx_ccq", "stat_rx_ccq"]},
            {"symbol": "stat_rx_ccq", "component_class": "wireless_radio", "sensor_class": "ccq-rx", "unit": "percent", "name": "Rx CCQ", "label_symbols": {"ssid": "stat_ssid", "frequency": "stat_frequency"}, "skip_row_if_all_empty_or_zero_symbols": ["stat_tx_ccq", "stat_rx_ccq"]},
            {"symbol": "ap_noise", "component_class": "wireless_radio", "sensor_class": "noise-floor", "unit": "dBm", "name": "Noise Floor", "label_symbols": {"ssid": "ap_ssid", "frequency": "ap_frequency"}, "allow_negative": True},
            {"symbol": "ap_tx_rate", "component_class": "wireless_radio", "sensor_class": "rate-ap-tx", "unit": "rate", "name": "Tx Rate", "label_symbols": {"ssid": "ap_ssid", "frequency": "ap_frequency"}, "skip_row_if_all_zero_symbols": ["ap_tx_rate", "ap_rx_rate"]},
            {"symbol": "ap_rx_rate", "component_class": "wireless_radio", "sensor_class": "rate-ap-rx", "unit": "rate", "name": "Rx Rate", "label_symbols": {"ssid": "ap_ssid", "frequency": "ap_frequency"}, "skip_row_if_all_zero_symbols": ["ap_tx_rate", "ap_rx_rate"]},
            {"symbol": "stat_tx_rate", "component_class": "wireless_radio", "sensor_class": "rate-station-tx", "unit": "rate", "name": "Tx Rate", "label_symbols": {"ssid": "stat_ssid", "frequency": "stat_frequency"}, "skip_row_if_all_zero_symbols": ["stat_tx_rate", "stat_rx_rate"]},
            {"symbol": "stat_rx_rate", "component_class": "wireless_radio", "sensor_class": "rate-station-rx", "unit": "rate", "name": "Rx Rate", "label_symbols": {"ssid": "stat_ssid", "frequency": "stat_frequency"}, "skip_row_if_all_zero_symbols": ["stat_tx_rate", "stat_rx_rate"]},
            {"symbol": "g60_rate", "component_class": "wireless_radio", "sensor_class": "rate-60g", "unit": "bps", "name": "60 GHz Phy Rate", "value_multiplier": 1000000, "label_symbols": {"ssid": "g60_ssid"}},
            {"symbol": "g60_rssi", "component_class": "wireless_radio", "sensor_class": "rssi", "unit": "dBm", "name": "60 GHz RSSI", "allow_negative": True, "label_symbols": {"ssid": "g60_ssid"}},
            {"symbol": "g60_quality", "component_class": "wireless_radio", "sensor_class": "quality", "unit": "percent", "name": "60 GHz Signal Quality", "label_symbols": {"ssid": "g60_ssid"}},
            {"symbol": "g60_distance", "component_class": "wireless_radio", "sensor_class": "distance", "unit": "km", "name": "60 GHz Station Distance", "value_multiplier": 0.00001, "label_symbols": {"remote": "g60_remote"}},
            {"symbol": "lte_rsrq", "component_class": "wireless_radio", "sensor_class": "rsrq", "unit": "dB", "name": "LTE RSRQ", "allow_negative": True, "label_symbols": {"interface": "interface_names"}},
            {"symbol": "lte_rsrp", "component_class": "wireless_radio", "sensor_class": "rsrp", "unit": "dBm", "name": "LTE RSRP", "allow_negative": True, "label_symbols": {"interface": "interface_names"}},
            {"symbol": "lte_sinr", "component_class": "wireless_radio", "sensor_class": "sinr", "unit": "dB", "name": "LTE SINR", "allow_negative": True, "label_symbols": {"interface": "interface_names"}},
        ],
    },
    "airos": {
        "source_rule": {
            "source_type": "librenms_mib_rule", "rule_key": "wireless_ubiquiti_airos",
            "source_path": "LibreNMS/OS/Airos.php", "adapter_source_files": ["LibreNMS/Modules/Wireless.php", "LibreNMS/OS/Airos.php"],
            "mib_source_files": ["mibs/ubnt/UBNT-AirMAX-MIB"],
        },
        "mib_sources": {"UBNT-AirMAX-MIB": "mibs/ubnt/UBNT-AirMAX-MIB"},
        "symbols": {"rssi_chain": ("UBNT-AirMAX-MIB", "ubntRadioRssi")},
        "scalars": [
            {"oid": "1.3.6.1.4.1.41112.1.4.1.1.4.1", "component_class": "wireless_radio", "sensor_class": "frequency", "unit": "MHz", "name": "Radio Frequency"},
            {"oid": "1.3.6.1.4.1.41112.1.4.6.1.4.1", "component_class": "wireless_radio", "sensor_class": "capacity", "unit": "percent", "name": "airMAX Capacity"},
            {"oid": "1.3.6.1.4.1.41112.1.4.5.1.7.1", "component_class": "wireless_radio", "sensor_class": "ccq", "unit": "percent", "name": "CCQ"},
            {"oid": "1.3.6.1.4.1.41112.1.4.5.1.15.1", "component_class": "wireless_radio", "sensor_class": "clients", "unit": "count", "name": "Associated clients", "group": "clients"},
            {"oid": "1.3.6.1.4.1.41112.1.4.1.1.7.1", "component_class": "wireless_radio", "sensor_class": "distance", "unit": "km", "name": "Distance", "value_multiplier": 0.001},
            {"oid": "1.3.6.1.4.1.41112.1.4.5.1.8.1", "component_class": "wireless_radio", "sensor_class": "noise-floor", "unit": "dBm", "name": "Noise Floor", "allow_negative": True},
            {"oid": "1.3.6.1.4.1.41112.1.4.1.1.6.1", "component_class": "wireless_radio", "sensor_class": "tx-power", "unit": "dBm", "name": "Tx Power", "allow_negative": True},
            {"oid": "1.3.6.1.4.1.41112.1.4.5.1.5.1", "component_class": "wireless_radio", "sensor_class": "rx-power", "unit": "dBm", "name": "Signal Level", "allow_negative": True},
            {"oid": "1.3.6.1.4.1.41112.1.4.6.1.3.1", "component_class": "wireless_radio", "sensor_class": "quality", "unit": "percent", "name": "airMAX Quality"},
            {"oid": "1.3.6.1.4.1.41112.1.4.5.1.9.1", "component_class": "wireless_radio", "sensor_class": "tx-rate", "unit": "rate", "name": "Tx Rate"},
            {"oid": "1.3.6.1.4.1.41112.1.4.5.1.10.1", "component_class": "wireless_radio", "sensor_class": "rx-rate", "unit": "rate", "name": "Rx Rate"},
            {"oid": "1.3.6.1.4.1.41112.1.4.5.1.6.1", "component_class": "wireless_radio", "sensor_class": "rssi", "unit": "dBm", "name": "Overall RSSI", "allow_negative": True},
            {"oid": "1.3.6.1.4.1.41112.1.4.6.1.7.1", "component_class": "wireless_radio", "sensor_class": "utilization", "unit": "percent", "name": "Airtime", "value_multiplier": 0.1},
        ],
        "tables": [
            {"symbol": "rssi_chain", "component_class": "wireless_radio", "sensor_class": "rssi-chain", "unit": "dBm", "name": "RSSI Chain", "allow_negative": True},
        ],
    },
    "unifi": {
        "source_rule": {
            "source_type": "librenms_mib_rule", "rule_key": "wireless_ubiquiti_unifi",
            "source_path": "LibreNMS/OS/Unifi.php", "adapter_source_files": ["LibreNMS/Modules/Wireless.php", "LibreNMS/OS/Unifi.php"],
            "mib_source_files": ["mibs/ubnt/UBNT-UniFi-MIB"],
        },
        "mib_sources": {"UBNT-UniFi-MIB": "mibs/ubnt/UBNT-UniFi-MIB"},
        "symbols": {
            "vif_clients": ("UBNT-UniFi-MIB", "unifiVapNumStations"),
            "vif_ccq": ("UBNT-UniFi-MIB", "unifiVapCcq"),
            "vif_channel": ("UBNT-UniFi-MIB", "unifiVapChannel"),
            "vif_ssid": ("UBNT-UniFi-MIB", "unifiVapEssId"),
            "vif_radio": ("UBNT-UniFi-MIB", "unifiVapRadio"),
            "vif_tx_power": ("UBNT-UniFi-MIB", "unifiVapTxPower"),
            "radio_names": ("UBNT-UniFi-MIB", "unifiRadioRadio"),
            "radio_total_util": ("UBNT-UniFi-MIB", "unifiRadioCuTotal"),
            "radio_rx_util": ("UBNT-UniFi-MIB", "unifiRadioCuSelfRx"),
            "radio_tx_util": ("UBNT-UniFi-MIB", "unifiRadioCuSelfTx"),
            "radio_other_util": ("UBNT-UniFi-MIB", "unifiRadioOtherBss"),
        },
        "scalars": [],
        "tables": [
            {"symbol": "vif_ccq", "component_class": "wireless_ssid", "sensor_class": "ccq", "unit": "percent", "name": "CCQ", "value_multiplier": 0.1, "value_max": 100, "label_symbols": {"ssid": "vif_ssid", "radio": "vif_radio"}, "skip_empty_label": "ssid"},
            {"symbol": "vif_channel", "component_class": "wireless_radio", "sensor_class": "frequency", "unit": "MHz", "name": "Frequency", "value_transform": "channel_to_frequency", "label_symbols": {"radio": "vif_radio"}, "unique_by_labels": ["radio"]},
            {"symbol": "vif_tx_power", "component_class": "wireless_radio", "sensor_class": "power", "unit": "dBm", "name": "Tx Power", "allow_negative": True, "label_symbols": {"radio": "vif_radio"}, "unique_by_labels": ["radio"]},
            {"symbol": "radio_total_util", "component_class": "wireless_radio", "sensor_class": "utilization-total", "unit": "percent", "name": "Total Utilization", "label_symbols": {"radio": "radio_names"}},
            {"symbol": "radio_rx_util", "component_class": "wireless_radio", "sensor_class": "utilization-rx", "unit": "percent", "name": "Self Rx Utilization", "label_symbols": {"radio": "radio_names"}},
            {"symbol": "radio_tx_util", "component_class": "wireless_radio", "sensor_class": "utilization-tx", "unit": "percent", "name": "Self Tx Utilization", "label_symbols": {"radio": "radio_names"}},
            {"symbol": "radio_other_util", "component_class": "wireless_radio", "sensor_class": "utilization-other", "unit": "percent", "name": "Other BSS Utilization", "label_symbols": {"radio": "radio_names"}},
        ],
        "aggregates": [
            {"symbol": "vif_clients", "kind": "table_group_sum", "component_class": "wireless_radio", "sensor_class": "clients", "unit": "count", "name": "Clients", "aggregate_group_label": "radio", "group_label_symbols": {"radio": "vif_radio"}},
            {"symbol": "vif_clients", "kind": "table_group_sum", "component_class": "wireless_ssid", "sensor_class": "clients", "unit": "count", "name": "SSID Clients", "aggregate_group_label": "ssid", "group_label_symbols": {"ssid": "vif_ssid"}, "skip_empty_group": True},
        ],
    },
    "ciscosat": {
        "source_rule": {
            "source_type": "librenms_mib_rule", "rule_key": "wireless_cisco_satellite",
            "source_path": "LibreNMS/OS/Ciscosat.php",
            "adapter_source_files": ["LibreNMS/Modules/Wireless.php", "LibreNMS/OS/Ciscosat.php"],
            "mib_source_files": ["mibs/cisco/CISCO-DMN-DSG-TUNING-MIB"],
        },
        "mib_sources": {
            "CISCO-DMN-DSG-TUNING-MIB": "mibs/cisco/CISCO-DMN-DSG-TUNING-MIB",
        },
        "symbols": {
            "uncorrected_errors": ("CISCO-DMN-DSG-TUNING-MIB", "satSignalUncorErrCnt"),
            "rssi": ("CISCO-DMN-DSG-TUNING-MIB", "satSignalLevel"),
            "snr_margin": ("CISCO-DMN-DSG-TUNING-MIB", "satSignalCnMargin"),
            "snr_ratio": ("CISCO-DMN-DSG-TUNING-MIB", "satSignalCndisp"),
        },
        "scalars": [],
        "tables": [
            {"symbol": "uncorrected_errors", "component_class": "wireless_radio", "sensor_class": "errors", "unit": "count", "name": "Uncorrected Errors"},
            {"symbol": "rssi", "component_class": "wireless_radio", "sensor_class": "rssi", "unit": "dBm", "name": "Receive Signal Level", "allow_negative": True},
            {"symbol": "snr_margin", "component_class": "wireless_radio", "sensor_class": "snr-margin", "unit": "dB", "name": "C/N Link Margin", "allow_negative": True},
            {"symbol": "snr_ratio", "component_class": "wireless_radio", "sensor_class": "snr-ratio", "unit": "dB", "name": "C/N Ratio", "allow_negative": True},
        ],
    },
    "airos-af": {
        "source_rule": {
            "source_type": "librenms_mib_rule", "rule_key": "wireless_ubiquiti_airfiber",
            "source_path": "LibreNMS/OS/AirosAf.php",
            "adapter_source_files": ["LibreNMS/Modules/Wireless.php", "LibreNMS/OS/AirosAf.php"],
            "mib_source_files": ["mibs/ubnt/UBNT-AirFIBER-MIB"],
        },
        "mib_sources": {}, "symbols": {}, "tables": [],
        "scalars": [
            {"oid": "1.3.6.1.4.1.41112.1.3.1.1.5.1", "component_class": "wireless_radio", "sensor_class": "tx-frequency", "unit": "GHz", "name": "Tx Frequency"},
            {"oid": "1.3.6.1.4.1.41112.1.3.1.1.6.1", "component_class": "wireless_radio", "sensor_class": "rx-frequency", "unit": "GHz", "name": "Rx Frequency"},
            {"oid": "1.3.6.1.4.1.41112.1.3.2.1.4.1", "component_class": "wireless_radio", "sensor_class": "distance", "unit": "km", "name": "Distance", "value_multiplier": 0.001},
            {"oid": "1.3.6.1.4.1.41112.1.3.1.1.9.1", "component_class": "wireless_radio", "sensor_class": "tx-power", "unit": "dBm", "name": "Tx Power", "allow_negative": True},
            {"oid": "1.3.6.1.4.1.41112.1.3.2.1.11.1", "component_class": "wireless_radio", "sensor_class": "rx-power-chain-0", "unit": "dBm", "name": "Rx Chain 0 Power", "allow_negative": True},
            {"oid": "1.3.6.1.4.1.41112.1.3.2.1.14.1", "component_class": "wireless_radio", "sensor_class": "rx-power-chain-1", "unit": "dBm", "name": "Rx Chain 1 Power", "allow_negative": True},
            {"oid": "1.3.6.1.4.1.41112.1.3.2.1.6.1", "component_class": "wireless_radio", "sensor_class": "tx-rate", "unit": "Mbps", "name": "Tx Capacity"},
            {"oid": "1.3.6.1.4.1.41112.1.3.2.1.5.1", "component_class": "wireless_radio", "sensor_class": "rx-rate", "unit": "Mbps", "name": "Rx Capacity"},
        ],
    },
    "airos-af-ltu": {
        "source_rule": {
            "source_type": "librenms_mib_rule", "rule_key": "wireless_ubiquiti_airfiber_ltu",
            "source_path": "LibreNMS/OS/AirosAfLtu.php",
            "adapter_source_files": ["LibreNMS/Modules/Wireless.php", "LibreNMS/OS/AirosAfLtu.php"],
            "mib_source_files": ["mibs/ubnt/UBNT-AFLTU-MIB"],
        },
        "mib_sources": {"UBNT-AFLTU-MIB": "mibs/ubnt/UBNT-AFLTU-MIB"},
        "symbols": {
            "remote_distance": ("UBNT-AFLTU-MIB", "afLTUStaRemoteDistance"),
            "rx_power_0": ("UBNT-AFLTU-MIB", "afLTUStaRxPower0"),
            "rx_power_1": ("UBNT-AFLTU-MIB", "afLTUStaRxPower1"),
            "ideal_rx_power_0": ("UBNT-AFLTU-MIB", "afLTUStaIdealRxPower0"),
            "ideal_rx_power_1": ("UBNT-AFLTU-MIB", "afLTUStaIdealRxPower1"),
            "rx_quality_0": ("UBNT-AFLTU-MIB", "afLTUStaRxPowerLevel0"),
            "rx_quality_1": ("UBNT-AFLTU-MIB", "afLTUStaRxPowerLevel1"),
            "tx_capacity": ("UBNT-AFLTU-MIB", "afLTUStaTxCapacity"),
            "rx_capacity": ("UBNT-AFLTU-MIB", "afLTUStaRxCapacity"),
        },
        "scalars": [
            {"oid": "1.3.6.1.4.1.41112.1.10.1.2.2.0", "component_class": "wireless_radio", "sensor_class": "frequency", "unit": "Hz", "name": "Radio Frequency"},
            {"oid": "1.3.6.1.4.1.41112.1.10.1.2.6.0", "component_class": "wireless_radio", "sensor_class": "tx-eirp", "unit": "dBm", "name": "TX EIRP", "allow_negative": True},
        ],
        "tables": [
            {"symbol": "remote_distance", "component_class": "wireless_radio", "sensor_class": "distance", "unit": "km", "name": "Distance", "value_multiplier": 0.001, "first_row_only": True},
            {"symbol": "rx_power_0", "component_class": "wireless_radio", "sensor_class": "rx-power-chain-0", "unit": "dBm", "name": "RX Power Chain 0", "allow_negative": True, "first_row_only": True},
            {"symbol": "rx_power_1", "component_class": "wireless_radio", "sensor_class": "rx-power-chain-1", "unit": "dBm", "name": "RX Power Chain 1", "allow_negative": True, "first_row_only": True},
            {"symbol": "ideal_rx_power_0", "component_class": "wireless_radio", "sensor_class": "ideal-rx-power-chain-0", "unit": "dBm", "name": "RX Ideal Power Chain 0", "allow_negative": True, "first_row_only": True},
            {"symbol": "ideal_rx_power_1", "component_class": "wireless_radio", "sensor_class": "ideal-rx-power-chain-1", "unit": "dBm", "name": "RX Ideal Power Chain 1", "allow_negative": True, "first_row_only": True},
            {"symbol": "rx_quality_0", "component_class": "wireless_radio", "sensor_class": "quality-chain-0", "unit": "percent", "name": "Signal Level Chain 0", "first_row_only": True},
            {"symbol": "rx_quality_1", "component_class": "wireless_radio", "sensor_class": "quality-chain-1", "unit": "percent", "name": "Signal Level Chain 1", "first_row_only": True},
            {"symbol": "tx_capacity", "component_class": "wireless_radio", "sensor_class": "tx-rate", "unit": "bps", "name": "TX Rate", "value_multiplier": 1000, "first_row_only": True},
            {"symbol": "rx_capacity", "component_class": "wireless_radio", "sensor_class": "rx-rate", "unit": "bps", "name": "RX Rate", "value_multiplier": 1000, "first_row_only": True},
        ],
    },
    "airos-af60": {
        "source_rule": {
            "source_type": "librenms_mib_rule", "rule_key": "wireless_ubiquiti_airfiber_60",
            "source_path": "LibreNMS/OS/AirosAf60.php",
            "adapter_source_files": ["LibreNMS/Modules/Wireless.php", "LibreNMS/OS/AirosAf60.php"],
            "mib_source_files": ["mibs/ubnt/UI-AF60-MIB"],
        },
        "mib_sources": {"UI-AF60-MIB": "mibs/ubnt/UI-AF60-MIB"},
        "symbols": {
            "distance": ("UI-AF60-MIB", "af60StaRemoteDistance"),
            "tx_capacity": ("UI-AF60-MIB", "af60StaTxCapacity"),
            "rx_capacity": ("UI-AF60-MIB", "af60StaRxCapacity"),
            "local_rssi": ("UI-AF60-MIB", "af60StaRSSI"),
            "remote_rssi": ("UI-AF60-MIB", "af60StaRemoteRSSI"),
            "local_snr": ("UI-AF60-MIB", "af60StaSNR"),
            "remote_snr": ("UI-AF60-MIB", "af60StaRemoteSNR"),
        },
        "scalars": [{"oid": "1.3.6.1.4.1.41112.1.11.1.1.2.1", "component_class": "wireless_radio", "sensor_class": "frequency", "unit": "GHz", "name": "Radio Frequency"}],
        "tables": [
            {"symbol": "distance", "component_class": "wireless_radio", "sensor_class": "distance", "unit": "km", "name": "Distance", "value_multiplier": 0.001},
            {"symbol": "tx_capacity", "component_class": "wireless_radio", "sensor_class": "tx-rate", "unit": "bps", "name": "Tx Capacity", "value_multiplier": 1000},
            {"symbol": "rx_capacity", "component_class": "wireless_radio", "sensor_class": "rx-rate", "unit": "bps", "name": "Rx Capacity", "value_multiplier": 1000},
            {"symbol": "local_rssi", "component_class": "wireless_radio", "sensor_class": "rssi-local", "unit": "dBm", "name": "Local RSSI", "allow_negative": True},
            {"symbol": "remote_rssi", "component_class": "wireless_radio", "sensor_class": "rssi-remote", "unit": "dBm", "name": "Remote RSSI", "allow_negative": True},
            {"symbol": "local_snr", "component_class": "wireless_radio", "sensor_class": "snr-local", "unit": "dB", "name": "Local SNR", "allow_negative": True},
            {"symbol": "remote_snr", "component_class": "wireless_radio", "sensor_class": "snr-remote", "unit": "dB", "name": "Remote SNR", "allow_negative": True},
        ],
    },
    "timos": {
        "source_rule": {
            "source_type": "librenms_mib_rule", "rule_key": "wireless_nokia_timos",
            "source_path": "LibreNMS/OS/Timos.php",
            "adapter_source_files": ["LibreNMS/Modules/Wireless.php", "LibreNMS/OS/Timos.php"],
            "mib_source_files": ["mibs/nokia/TIMETRA-CELLULAR-MIB", "mibs/nokia/ALU-MICROWAVE-MIB", "mibs/IF-MIB"],
        },
        "mib_sources": {
            "TIMETRA-CELLULAR-MIB": "mibs/nokia/TIMETRA-CELLULAR-MIB",
            "ALU-MICROWAVE-MIB": "mibs/nokia/ALU-MICROWAVE-MIB",
            "IF-MIB": "mibs/IF-MIB",
        },
        "symbols": {
            "interface_names": ("IF-MIB", "ifName"),
            "radio_names": ("ALU-MICROWAVE-MIB", "aluMwRadioName"),
            "rx_power": ("ALU-MICROWAVE-MIB", "aluMwRadioLocalRxMainPower"),
            "tx_power": ("ALU-MICROWAVE-MIB", "aluMwRadioLocalTxPower"),
            "snr": ("TIMETRA-CELLULAR-MIB", "tmnxCellPortSinr"),
            "rsrq": ("TIMETRA-CELLULAR-MIB", "tmnxCellPortRsrq"),
            "rssi": ("TIMETRA-CELLULAR-MIB", "tmnxCellPortRssi"),
            "rsrp": ("TIMETRA-CELLULAR-MIB", "tmnxCellPortRsrp"),
            "channel": ("TIMETRA-CELLULAR-MIB", "tmnxCellPortChannelNumber"),
        },
        "scalars": [],
        "tables": [
            {"symbol": "rx_power", "component_class": "wireless_radio", "sensor_class": "power-rx", "unit": "dBm", "name": "Rx Power", "value_multiplier": 0.1, "allow_negative": True, "label_symbols": {"radio": "radio_names"}},
            {"symbol": "tx_power", "component_class": "wireless_radio", "sensor_class": "power-tx", "unit": "dBm", "name": "Tx Power", "value_multiplier": 0.1, "allow_negative": True, "label_symbols": {"radio": "radio_names"}},
            {"symbol": "snr", "component_class": "wireless_radio", "sensor_class": "snr", "unit": "dB", "name": "SNR", "value_multiplier": 0.1, "allow_negative": True, "label_symbols": {"interface": "interface_names"}},
            {"symbol": "rsrq", "component_class": "wireless_radio", "sensor_class": "rsrq", "unit": "dB", "name": "RSRQ", "allow_negative": True, "label_symbols": {"interface": "interface_names"}},
            {"symbol": "rssi", "component_class": "wireless_radio", "sensor_class": "rssi", "unit": "dBm", "name": "RSSI", "allow_negative": True, "label_symbols": {"interface": "interface_names"}},
            {"symbol": "rsrp", "component_class": "wireless_radio", "sensor_class": "rsrp", "unit": "dBm", "name": "RSRP", "allow_negative": True, "label_symbols": {"interface": "interface_names"}},
            {"symbol": "channel", "component_class": "wireless_radio", "sensor_class": "channel", "unit": "channel", "name": "Channel", "label_symbols": {"interface": "interface_names"}},
        ],
    },
}

_WIRELESS_RULELESS_UPSTREAM: dict[str, tuple[str, str]] = {
    "wavence": (
        "wireless_radio",
        "Pinned LibreNMS Wavence profile uses YAML radio-power discovery, not the Wireless module's AP/client inventory rules; the hardware YAML poller owns that source.",
    ),
}

WIRELESS_RULE_OS_KEYS = frozenset({
    "comware", "vrp", "ios",
    *_PROFILE_WIRELESS_RULES.keys(),
    *_WIRELESS_RULELESS_UPSTREAM.keys(),
})

_H3C_STATUS = {
    "1": ("join", 1),
    "join": ("join", 1),
    "join(1)": ("join", 1),
    "2": ("joinConfirm", 1),
    "joinconfirm": ("joinConfirm", 1),
    "joinconfirm(2)": ("joinConfirm", 1),
    "3": ("download", 1),
    "download": ("download", 1),
    "download(3)": ("download", 1),
    "4": ("config", 1),
    "config": ("config", 1),
    "config(4)": ("config", 1),
    "5": ("run", 0),
    "run": ("run", 0),
    "run(5)": ("run", 0),
}


def _row_map(result: Any) -> dict[str, str]:
    return {
        str(index).strip().strip("."): str(value)
        for index, value in (getattr(result, "rows", []) or [])
    }


def _decode_octet_string_index(suffix: Any) -> str | None:
    """Decode an SNMP OID index encoded as length + OCTET STRING bytes."""
    text = str(suffix or "").strip().strip(".")
    if not text:
        return None
    try:
        parts = [int(item) for item in text.split(".")]
    except ValueError:
        return None
    length = parts[0]
    if length < 0 or len(parts) != length + 1 or any(byte < 0 or byte > 255 for byte in parts[1:]):
        return None
    try:
        decoded = bytes(parts[1:]).decode("utf-8").strip("\x00")
    except UnicodeDecodeError:
        return None
    return decoded if decoded else None


def _indexed_octet_rows(rows: Mapping[str, str]) -> tuple[dict[str, str], int]:
    result: dict[str, str] = {}
    invalid = 0
    for suffix, value in rows.items():
        index = _decode_octet_string_index(suffix)
        if index is None:
            invalid += 1
        else:
            result[index] = value
    return result, invalid


def _format_mac_address(value: Any, octets: Any = None) -> str:
    """Render an SNMP MacAddress losslessly when its OCTET STRING is available."""
    if isinstance(octets, (bytes, bytearray)) and len(octets) == 6:
        return ":".join(f"{part:02x}" for part in octets)
    text = str(value or "").strip()
    compact = re.sub(r"[.:-]", "", text)
    if len(compact) == 12 and all(character in "0123456789abcdefABCDEF" for character in compact):
        return ":".join(compact[index:index + 2].lower() for index in range(0, 12, 2))
    return "" if "\ufffd" in text else text[:64]


def _oid_index_parts(suffix: Any) -> list[int] | None:
    text = str(suffix or "").strip().strip(".")
    if not text:
        return None
    try:
        parts = [int(item) for item in text.split(".")]
    except ValueError:
        return None
    return parts if all(item >= 0 for item in parts) else None


def _decode_mac_index(suffix: Any, *, trailing_parts: int = 0) -> tuple[str, tuple[int, ...]] | None:
    """Decode a fixed-size MacAddress index, optionally followed by numeric keys."""
    parts = _oid_index_parts(suffix)
    if parts is None:
        return None
    if len(parts) == 6 + trailing_parts:
        mac_parts = parts[:6]
        tail = parts[6:]
    elif len(parts) == 7 + trailing_parts and parts[0] == 6:
        # Some agents/tools render an OCTET STRING length arc even for SIZE(6).
        mac_parts = parts[1:7]
        tail = parts[7:]
    else:
        return None
    if any(item > 255 for item in mac_parts):
        return None
    mac = ":".join(f"{item:02x}" for item in mac_parts)
    return mac, tuple(tail)


def _numeric_enum(value: Any) -> float | None:
    number = _number(value)
    if number is not None:
        return number
    match = re.search(r"\((-?\d+(?:\.\d+)?)\)\s*$", str(value or "").strip())
    return _number(match.group(1)) if match else None


def _channel_to_frequency(value: Any) -> float | None:
    """Convert the channel numbers used by pinned Aruba/UniFi rules to MHz."""
    channel = _numeric_enum(value)
    if channel is None or channel <= 0 or not channel.is_integer():
        return None
    channel = int(channel) & 0xFF
    if channel == 14:
        return 2484.0
    if 1 <= channel <= 13:
        return float(2407 + 5 * channel)
    if 32 <= channel <= 196:
        return float(5000 + 5 * channel)
    return None


def _profile_detail_sensor(
    *,
    source_rule: Mapping[str, Any],
    os_key: str,
    source_id: str,
    component_class: str,
    sensor_class: str,
    oid: str,
    suffix: str,
    raw_value: Any,
    value: float,
    unit: str,
    name: str,
    labels: Mapping[str, Any],
    states: Mapping[str, Any] | None = None,
    poll_factor: float = 1.0,
    poll_offset: float = 0.0,
    poll_index: str | None = None,
    poll_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    planned_poll = dict(poll_plan or {
        "kind": "direct",
        "oid": oid,
        "index": poll_index or suffix,
        "factor": poll_factor,
        "offset": poll_offset,
    })
    return _sensor(
        source_id=source_id,
        component_class=component_class,
        measurement_type="component_state" if states is not None else "wireless_sensor_value",
        oid=oid,
        suffix=suffix,
        raw_value=raw_value,
        value=value,
        unit=unit,
        name=name,
        labels=labels,
        metadata={
            **dict(source_rule),
            "source_commit": PINNED_LIBRENMS_COMMIT,
            "collection_engine": "python",
            "rule_implementation": "Python equivalent of pinned LibreNMS AP/radio polling",
            "identity_os_key": os_key,
            "wireless_sensor_class": sensor_class,
        },
        states=states,
        poll_plan=planned_poll,
    )


def _number(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _category_result(
    component_class: str,
    *,
    status: str,
    complete: bool,
    reason_code: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "source_type": "librenms_mib_rule",
        "component_class": component_class,
        "status": status,
        "coverage_complete": bool(complete and status in {"success", "not_found"}),
        "reason_code": reason_code,
        "reason": reason,
    }


def _combine_wireless_results(
    *results: Mapping[str, Any],
    ignore_unsupported_reason_codes: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Combine same-class collectors into one persisted coverage result."""
    sensors = [
        sensor
        for result in results
        for sensor in (result.get("sensors") or [])
        if isinstance(sensor, Mapping)
    ]
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    order: list[str] = []
    for result in results:
        for item in result.get("category_results") or []:
            if not isinstance(item, Mapping):
                continue
            component_class = str(item.get("component_class") or "")
            if not component_class:
                continue
            if component_class not in grouped:
                grouped[component_class] = []
                order.append(component_class)
            grouped[component_class].append(item)

    category_results: list[dict[str, Any]] = []
    for component_class in order:
        entries = grouped[component_class]
        applicable = [
            item for item in entries
            if not (
                str(item.get("status") or "") == "unsupported"
                and str(item.get("reason_code") or "") in ignore_unsupported_reason_codes
            )
        ]
        class_sensors = [
            sensor for sensor in sensors
            if str(sensor.get("component_class") or "") == component_class
        ]
        if not applicable:
            status = "unsupported"
            complete = False
        else:
            complete = all(bool(item.get("coverage_complete")) for item in applicable)
            ignored_unsupported = any(
                str(item.get("status") or "") == "unsupported"
                and str(item.get("reason_code") or "") in ignore_unsupported_reason_codes
                for item in entries
            )
            status = (
                ("success" if class_sensors else "unsupported" if ignored_unsupported else "not_found")
                if complete else "partial" if class_sensors else "failed"
            )
            if ignored_unsupported and not class_sensors and complete:
                complete = False
        reasons = list(dict.fromkeys(
            str(item.get("reason") or "").strip()
            for item in entries
            if str(item.get("reason") or "").strip()
        ))
        category_results.append(_category_result(
            component_class,
            status=status,
            complete=complete,
            reason_code="combined_wireless_source_coverage",
            reason=" ".join(reasons),
        ))
    return {"sensors": sensors, "category_results": category_results}


def _sensor(
    *,
    source_id: str,
    component_class: str,
    measurement_type: str,
    oid: str,
    suffix: str,
    raw_value: Any,
    value: float,
    unit: str,
    name: str,
    labels: Mapping[str, Any],
    metadata: Mapping[str, Any],
    states: Mapping[str, Any] | None = None,
    poll_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    from services.snmp_hardware_probe_service import _sensor as make_hardware_sensor

    sensor = make_hardware_sensor(
        source_type="librenms_mib_rule",
        source_id=source_id,
        component_class=component_class,
        measurement_type=measurement_type,
        oid=oid,
        suffix=suffix,
        raw_value=raw_value,
        value=value,
        unit=unit,
        sensor_name=name,
        entity_name=str(labels.get("ap_name") or ""),
        group_name="wireless",
        quality="good",
        states=states,
        metadata=metadata,
        poll_plan=dict(poll_plan or {"kind": "direct", "oid": oid, "index": suffix}),
    )
    if sensor:
        sensor["index_labels"].update(dict(labels))
        series_parts = [str(metadata.get("wireless_sensor_class") or "").strip()]
        for label in ("radio_band", "group"):
            value = str(labels.get(label) or "").strip()
            if value:
                series_parts.append(f"{label}:{value}")
        series_variant = ":".join(part for part in series_parts if part)
        if series_variant:
            # Several wireless counters share the same table index and broad
            # measurement type. Keep their metric identity in the inventory
            # key so distinct AP/radio fields do not collide on persistence.
            sensor["series_variant"] = series_variant
    return sensor


def _resolve_pinned_symbols(
    requests: Mapping[str, tuple[str, str]],
    mib_sources: Mapping[str, str],
) -> tuple[dict[str, str], list[str]]:
    from services import snmp_hardware_probe_service as probe

    symbols: dict[str, str] = {}
    missing: list[str] = []
    conn = None
    try:
        conn = get_db_connection()
    except Exception:
        conn = None
    try:
        cache: dict[tuple[str, str], str] = {}
        for key, (module, symbol) in requests.items():
            mib_path = mib_sources[module]
            oid = probe._resolve_pinned_librenms_mib_symbol(
                conn, mib_path, symbol, cache=cache,
            )
            if oid:
                symbols[key] = oid
            else:
                missing.append(f"{mib_path}::{symbol}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return symbols, missing


async def _probe_h3c_wireless(
    ip: str,
    community: str | Mapping[str, Any],
    port: int,
    *,
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
) -> dict[str, Any]:
    from services import snmp_hardware_probe_service as probe

    mib_sources = {
        "HH3C-DOT11-ACMT-MIB": "mibs/comware/HH3C-DOT11-ACMT-MIB",
        "HH3C-DOT11-APMT-MIB": "mibs/comware/HH3C-DOT11-APMT-MIB",
        "HH3C-DOT11-STATION-MIB": "mibs/comware/HH3C-DOT11-STATION-MIB",
    }
    requests = {
        "ap_count": ("HH3C-DOT11-ACMT-MIB", "hh3cDot11TotalAPconnected"),
        "client_count": ("HH3C-DOT11-ACMT-MIB", "hh3cDot11StationCurAssocSum"),
        "ap_status": ("HH3C-DOT11-APMT-MIB", "hh3cDot11APOperationStatus"),
        "ap_name": ("HH3C-DOT11-APMT-MIB", "hh3cDot11CurrAPName"),
        "ap_model": ("HH3C-DOT11-APMT-MIB", "hh3cDot11CurrAPModelName"),
        "ap_ip": ("HH3C-DOT11-APMT-MIB", "hh3cDot11APIPAddress"),
        "ap_mac": ("HH3C-DOT11-APMT-MIB", "hh3cDot11APMacAddress"),
        "ap_clients": ("HH3C-DOT11-APMT-MIB", "hh3cDot11CurrAPStationAssocCount"),
        "ap_cpu": ("HH3C-DOT11-APMT-MIB", "hh3cDot11APCpuUsage"),
        "radio_admin_status": ("HH3C-DOT11-APMT-MIB", "hh3cDot11AdminStatus"),
        "radio_oper_status": ("HH3C-DOT11-APMT-MIB", "hh3cDot11OperStatus"),
        "radio_channel": ("HH3C-DOT11-APMT-MIB", "hh3cDot11Channel"),
        "radio_tx_power": ("HH3C-DOT11-APMT-MIB", "hh3cDot11TxPowerLevel"),
        "radio_ifindex": ("HH3C-DOT11-APMT-MIB", "hh3cDot11APRadioIfIndex"),
        "radio_resource_usage": ("HH3C-DOT11-APMT-MIB", "hh3cDot11ResourceUseRatio"),
        "radio_signal_strength": ("HH3C-DOT11-APMT-MIB", "hh3cDot11AvgRxSignalStrength"),
        "radio_utilization": ("HH3C-DOT11-APMT-MIB", "hh3cDot11AirPrimChnlBusy"),
        "radio_tx_busy": ("HH3C-DOT11-APMT-MIB", "hh3cDot11AirPrimChnlTxBusy"),
        "radio_rx_busy": ("HH3C-DOT11-APMT-MIB", "hh3cDot11AirPrimChnlRxBusy"),
        "radio_ext_busy": ("HH3C-DOT11-APMT-MIB", "hh3cDot11AirExtChnlBusy"),
    }
    symbols, missing = _resolve_pinned_symbols(requests, mib_sources)

    if not symbols:
        return {
            "sensors": [],
            "category_results": [
                _category_result(
                    "wireless_access_point", status="failed", complete=False,
                    reason_code="pinned_mib_symbols_unavailable",
                    reason="The exact pinned H3C wireless MIB symbols are not indexed in the active LibreNMS MIB database.",
                ),
            ],
        }

    reads = await probe._walk_many(
        ip, community, set(symbols.values()), port, version, walk_func=walk_func,
    )
    rows = {key: _row_map(reads.get(oid)) for key, oid in symbols.items()}
    complete = {
        key: bool(reads.get(oid) and reads[oid].complete and not reads[oid].reason)
        for key, oid in symbols.items()
    }
    sensors: list[dict[str, Any]] = []
    lineage = {
        **_H3C_RULE,
        "source_commit": PINNED_LIBRENMS_COMMIT,
        "collection_engine": "python",
        "rule_implementation": "Nexora Python MIB adapter",
        "identity_os_key": "comware",
    }

    def scalar_sensor(key: str, sensor_class: str, label: str) -> int:
        count = 0
        oid = symbols.get(key)
        for suffix, raw in sorted(rows.get(key, {}).items()):
            value = _number(raw)
            if not oid or value is None or suffix not in {"0", ""} or value < 0:
                continue
            sensor = _sensor(
                source_id=f"h3c:wireless:{sensor_class}:controller",
                component_class="wireless_controller",
                measurement_type="wireless_sensor_value",
                oid=oid,
                suffix=suffix or "0",
                raw_value=raw,
                value=value,
                unit="count",
                name=label,
                labels={},
                metadata={**lineage, "wireless_sensor_class": sensor_class},
            )
            if sensor:
                sensors.append(sensor)
                count += 1
        return count

    ap_count = scalar_sensor("ap_count", "ap-count", "Connected APs")
    client_count = scalar_sensor("client_count", "clients", "Associated clients")

    ap_status_rows = rows.get("ap_status", {})
    ap_rows: dict[str, str] = {}
    ap_status_suffixes: dict[str, str] = {}
    ap_invalid_index_count = 0
    for suffix, raw_status in ap_status_rows.items():
        ap_id = _decode_octet_string_index(suffix)
        if ap_id is None:
            ap_invalid_index_count += 1
            continue
        ap_rows[ap_id] = raw_status
        ap_status_suffixes[ap_id] = suffix
    ap_names, invalid_name_indexes = _indexed_octet_rows(rows.get("ap_name", {}))
    ap_models, invalid_model_indexes = _indexed_octet_rows(rows.get("ap_model", {}))
    ap_ips, invalid_ip_indexes = _indexed_octet_rows(rows.get("ap_ip", {}))
    ap_macs, invalid_mac_indexes = _indexed_octet_rows(rows.get("ap_mac", {}))
    ap_mac_octets = getattr(reads.get(symbols.get("ap_mac", "")), "octet_values", {}) or {}
    for suffix, octets in ap_mac_octets.items():
        ap_id = _decode_octet_string_index(suffix)
        if ap_id is not None:
            ap_macs[ap_id] = _format_mac_address(ap_macs.get(ap_id), octets)
    ap_macs = {
        ap_id: _format_mac_address(mac)
        for ap_id, mac in ap_macs.items()
    }
    ap_clients, invalid_client_indexes = _indexed_octet_rows(rows.get("ap_clients", {}))
    ap_cpus, invalid_cpu_indexes = _indexed_octet_rows(rows.get("ap_cpu", {}))
    ap_invalid_index_count += sum((
        invalid_name_indexes, invalid_model_indexes, invalid_ip_indexes,
        invalid_mac_indexes, invalid_client_indexes, invalid_cpu_indexes,
    ))
    unknown_ap_statuses = [
        raw_status for raw_status in ap_rows.values()
        if str(raw_status).strip().casefold() not in _H3C_STATUS
    ]
    for ap_id, raw_status in sorted(ap_rows.items()):
        state = _H3C_STATUS.get(str(raw_status).strip().casefold())
        if state is None:
            continue
        ap_name = str(ap_names.get(ap_id) or f"AP {ap_id}")[:120]
        ap_model = str(ap_models.get(ap_id) or "")[:120]
        ap_ip = str(ap_ips.get(ap_id) or "")[:64]
        ap_mac = str(ap_macs.get(ap_id) or "")[:64]
        labels = {
            "ap_id": ap_id,
            "ap_name": ap_name,
            "ap_model": ap_model,
            "ap_ip": ap_ip,
            "ap_mac": ap_mac,
        }
        sensor = _sensor(
            source_id=f"h3c:wireless:ap-state:{ap_id}",
            component_class="wireless_access_point",
            measurement_type="component_state",
            oid=symbols["ap_status"],
            suffix=ap_status_suffixes[ap_id],
            raw_value=raw_status,
            value=float(state[1]),
            unit="state",
            name=ap_name,
            labels=labels,
            metadata={**lineage, "wireless_sensor_class": "ap-state"},
            states={
                raw: {"generic": generic, "descr": description}
                for raw, (description, generic) in _H3C_STATUS.items()
            },
        )
        if sensor:
            sensors.append(sensor)

        for key, sensor_class, measurement, unit, values in (
            ("ap_clients", "clients", "wireless_sensor_value", "count", ap_clients),
            ("ap_cpu", "cpu", "wireless_sensor_value", "percent", ap_cpus),
        ):
            raw = values.get(ap_id)
            value = _number(raw)
            oid = symbols.get(key)
            if raw is None or value is None or value < 0 or not oid:
                continue
            metric_sensor = _sensor(
                source_id=f"h3c:wireless:ap:{sensor_class}:{ap_id}",
                component_class="wireless_access_point",
                measurement_type=measurement,
                oid=oid,
                suffix=next(
                    (index for index in rows.get(key, {}) if _decode_octet_string_index(index) == ap_id),
                    ap_status_suffixes[ap_id],
                ),
                raw_value=raw,
                value=value,
                unit=unit,
                name=f"{ap_name} {sensor_class}",
                labels=labels,
                metadata={**lineage, "wireless_sensor_class": sensor_class},
            )
            if metric_sensor:
                sensors.append(metric_sensor)

    ap_walk_keys = {
        "ap_status", "ap_name", "ap_model", "ap_ip", "ap_mac", "ap_clients", "ap_cpu",
    }
    ap_complete = (
        all(complete.get(key, False) for key in ap_walk_keys)
        and not unknown_ap_statuses
        and ap_invalid_index_count == 0
        and not any(
            item.split("::", 1)[-1] in {requests[key][1] for key in ap_walk_keys}
            for item in missing
        )
    )
    ap_sensor_count = sum(
        1 for sensor in sensors
        if sensor.get("component_class") == "wireless_access_point"
        and sensor.get("measurement_type") == "component_state"
    )
    ap_result = _category_result(
        "wireless_access_point",
        status="success" if ap_sensor_count and ap_complete else "partial" if ap_sensor_count else "not_found" if ap_complete else "failed",
        complete=ap_complete,
        reason_code="h3c_wireless_ap_table" if ap_sensor_count and ap_complete else "unrecognized_h3c_ap_status" if unknown_ap_statuses else "invalid_h3c_ap_index" if ap_invalid_index_count else "no_h3c_wireless_ap_rows" if ap_complete else "h3c_wireless_ap_walk_incomplete",
        reason=f"Pinned H3C wireless MIB walks returned {ap_sensor_count} AP row(s)." if ap_sensor_count and ap_complete else f"H3C AP status table included {len(unknown_ap_statuses)} unrecognized status value(s)." if unknown_ap_statuses else f"H3C AP tables included {ap_invalid_index_count} row(s) with an unrecognized index." if ap_invalid_index_count else "No H3C AP rows were returned by the pinned MIB table." if ap_complete else "One or more H3C AP table walks or symbol lookups did not complete.",
    )
    if missing:
        ap_result["reason"] += f" Missing MIB symbol(s): {len(missing)}."
        if any(item.split("::", 1)[-1] in {requests[key][1] for key in ap_walk_keys} for item in missing):
            ap_result["coverage_complete"] = False

    controller_complete = complete.get("ap_count", False) and complete.get("client_count", False)
    controller_sensors = [
        sensor for sensor in sensors
        if sensor.get("component_class") == "wireless_controller"
    ]
    controller_result = _category_result(
        "wireless_controller",
        status="success" if controller_sensors and controller_complete else "partial" if controller_sensors else "not_found" if controller_complete else "failed",
        complete=controller_complete,
        reason_code="h3c_wireless_controller_counts" if controller_sensors else "no_h3c_wireless_controller_counts" if controller_complete else "h3c_wireless_controller_walk_incomplete",
        reason=f"Pinned H3C wireless MIB scalars returned {len(controller_sensors)} aggregate sensor(s)." if controller_sensors else "No H3C wireless AP/client count was returned by the pinned MIB scalars." if controller_complete else "The H3C wireless AP/client count walks did not complete.",
    )

    # hh3cDot11APRadioTable is indexed by an OCTET STRING AP ID followed by
    # radio ID: length, each AP-ID byte, radio ID. Keep the original numeric
    # suffix for the polling plan and expose decoded identities as labels.
    def radio_index(suffix: str) -> tuple[str, str] | None:
        parts = suffix.split(".")
        if not parts or not all(part.isdigit() for part in parts):
            return None
        numbers = [int(part) for part in parts]
        length = numbers[0]
        if length < 0 or len(numbers) != length + 2 or any(byte > 255 for byte in numbers[1:-1]):
            return None
        try:
            ap_id = bytes(numbers[1:-1]).decode("utf-8").strip("\x00")
        except UnicodeDecodeError:
            return None
        radio_id = str(numbers[-1])
        if not ap_id or not radio_id:
            return None
        return ap_id[:120], radio_id

    ap_name_by_id = {str(ap_id): str(name) for ap_id, name in ap_names.items() if str(name).strip()}
    radio_status_rows = rows.get("radio_oper_status", {})
    radio_admin_rows = rows.get("radio_admin_status", {})
    parsed_radio_entries = [
        (suffix, radio_index(suffix))
        for suffix in sorted(radio_status_rows)
    ]
    invalid_radio_index_count = sum(1 for _suffix, parsed in parsed_radio_entries if parsed is None)
    radio_entries = [(suffix, parsed) for suffix, parsed in parsed_radio_entries if parsed is not None]
    radio_sensors_start = len(sensors)
    for suffix, parsed in radio_entries:
        assert parsed is not None
        ap_id, radio_id = parsed
        ap_name = ap_name_by_id.get(ap_id, f"AP {ap_id}")[:120]
        ap_model = str(ap_models.get(ap_id) or "")[:120]
        radio_labels = {
            "ap_id": ap_id,
            "ap_name": ap_name,
            "ap_model": ap_model,
            "radio_id": radio_id,
        }
        raw_status = radio_status_rows[suffix]
        oper_token = str(raw_status).strip().casefold()
        oper_up = oper_token in {"1", "true", "true(1)"}
        oper_down = oper_token in {"2", "false", "false(2)"}
        if oper_up or oper_down:
            radio_state = _sensor(
                source_id=f"h3c:wireless:radio-state:{ap_id}:{radio_id}",
                component_class="wireless_radio",
                measurement_type="component_state",
                oid=symbols["radio_oper_status"],
                suffix=suffix,
                raw_value=raw_status,
                value=0.0 if oper_up else 2.0,
                unit="state",
                name=f"{ap_name} Radio {radio_id}",
                labels=radio_labels,
                metadata={**lineage, "wireless_sensor_class": "radio-state"},
                states={
                    "1": {"generic": "ok", "descr": "up"},
                    "true(1)": {"generic": "ok", "descr": "up"},
                    "2": {"generic": "down", "descr": "down"},
                    "false(2)": {"generic": "down", "descr": "down"},
                },
            )
            if radio_state:
                sensors.append(radio_state)

        admin_raw = radio_admin_rows.get(suffix)
        if admin_raw is not None:
            admin_token = str(admin_raw).strip().casefold()
            admin_value = 1.0 if admin_token in {"1", "true", "true(1)"} else 0.0 if admin_token in {"2", "false", "false(2)"} else None
            if admin_value is not None:
                admin_sensor = _sensor(
                    source_id=f"h3c:wireless:radio-admin-status:{ap_id}:{radio_id}",
                    component_class="wireless_radio",
                    measurement_type="wireless_sensor_value",
                    oid=symbols["radio_admin_status"],
                    suffix=suffix,
                    raw_value=admin_raw,
                    value=admin_value,
                    unit="boolean",
                    name=f"{ap_name} Radio {radio_id} Admin Status",
                    labels=radio_labels,
                    metadata={**lineage, "wireless_sensor_class": "admin-status"},
                    poll_plan={
                        "kind": "direct",
                        "oid": symbols["radio_admin_status"],
                        "index": suffix,
                        "value_map": {
                            "1": 1,
                            "true": 1,
                            "true(1)": 1,
                            "2": 0,
                            "false": 0,
                            "false(2)": 0,
                        },
                    },
                )
                if admin_sensor:
                    sensors.append(admin_sensor)

        metric_specs = (
            ("radio_channel", "channel", "channel", "channel", False),
            ("radio_tx_power", "tx-power", "dbm", "dBm", False),
            ("radio_resource_usage", "radio-resource-usage", "percent", "percent", True),
            ("radio_signal_strength", "signal-strength", "dbm", "dBm", False),
            ("radio_utilization", "utilization", "percent", "percent", True),
            ("radio_tx_busy", "utilization-tx", "percent", "percent", True),
            ("radio_rx_busy", "utilization-rx", "percent", "percent", True),
            ("radio_ext_busy", "ext-channel-utilization", "percent", "percent", True),
        )
        for key, sensor_class, unit, label, percent in metric_specs:
            raw = rows.get(key, {}).get(suffix)
            value = _number(raw)
            oid = symbols.get(key)
            if raw is None or value is None or not oid:
                continue
            # H3C uses 255 to mean an unavailable channel-busy measurement.
            if percent and (value == 255 or value < 0 or value > 100):
                continue
            if key == "radio_channel" and value <= 0:
                continue
            radio_metric = _sensor(
                source_id=f"h3c:wireless:radio:{sensor_class}:{ap_id}:{radio_id}",
                component_class="wireless_radio",
                measurement_type="wireless_sensor_value",
                oid=oid,
                suffix=suffix,
                raw_value=raw,
                value=value,
                unit=unit,
                name=f"{ap_name} Radio {radio_id} {sensor_class}",
                labels=radio_labels,
                metadata={**lineage, "wireless_sensor_class": sensor_class},
            )
            if radio_metric:
                sensors.append(radio_metric)

        ifindex = _number(rows.get("radio_ifindex", {}).get(suffix))
        if ifindex is not None and ifindex >= 0:
            ifindex_sensor = _sensor(
                source_id=f"h3c:wireless:radio:interface-index:{ap_id}:{radio_id}",
                component_class="wireless_radio",
                measurement_type="wireless_sensor_value",
                oid=symbols["radio_ifindex"],
                suffix=suffix,
                raw_value=rows["radio_ifindex"][suffix],
                value=ifindex,
                unit="ifindex",
                name=f"{ap_name} Radio {radio_id} Interface Index",
                labels=radio_labels,
                metadata={**lineage, "wireless_sensor_class": "interface-index"},
            )
            if ifindex_sensor:
                sensors.append(ifindex_sensor)

    radio_walk_keys = {key for key in requests if key.startswith("radio_")}
    radio_complete = (
        all(complete.get(key, False) for key in radio_walk_keys)
        and invalid_radio_index_count == 0
        and not any(
            item.split("::", 1)[-1] in {requests[key][1] for key in radio_walk_keys}
            for item in missing
        )
    )
    radio_state_count = sum(
        1 for sensor in sensors[radio_sensors_start:]
        if sensor.get("measurement_type") == "component_state"
    )
    radio_result = _category_result(
        "wireless_radio",
        status="success" if radio_state_count and radio_complete else "partial" if radio_state_count else "not_found" if radio_complete else "failed",
        complete=radio_complete,
        reason_code="h3c_wireless_radio_table" if radio_state_count and radio_complete else "invalid_h3c_radio_index" if invalid_radio_index_count else "no_h3c_wireless_radio_rows" if radio_complete else "h3c_wireless_radio_walk_incomplete",
        reason=f"Pinned H3C wireless MIB walks returned {radio_state_count} radio state row(s)." if radio_state_count and radio_complete else f"H3C radio table included {invalid_radio_index_count} row(s) with an unrecognized index." if invalid_radio_index_count else "No H3C radio rows were returned by the pinned MIB table." if radio_complete else "One or more H3C radio table walks or symbol lookups did not complete.",
    )
    return {
        "sensors": sensors,
        "category_results": [controller_result, ap_result, radio_result],
    }


async def _probe_huawei_wireless(
    ip: str,
    community: str | Mapping[str, Any],
    port: int,
    *,
    rule: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
) -> dict[str, Any]:
    from services import snmp_hardware_probe_service as probe

    mib_sources = {
        "HUAWEI-WLAN-GLOBAL-MIB": "mibs/huawei/HUAWEI-WLAN-GLOBAL-MIB",
        "HUAWEI-WLAN-AP-MIB": "mibs/huawei/HUAWEI-WLAN-AP-MIB",
        "HUAWEI-WLAN-AP-RADIO-MIB": "mibs/huawei/HUAWEI-WLAN-AP-RADIO-MIB",
        "HUAWEI-WLAN-VAP-MIB": "mibs/huawei/HUAWEI-WLAN-VAP-MIB",
    }
    requests = {
        "ap_count": ("HUAWEI-WLAN-GLOBAL-MIB", "hwWlanCurJointApNum"),
        "ap_name": ("HUAWEI-WLAN-AP-MIB", "hwWlanApName"),
        "ap_serial": ("HUAWEI-WLAN-AP-MIB", "hwWlanApSn"),
        "ap_model": ("HUAWEI-WLAN-AP-MIB", "hwWlanApTypeInfo"),
        "radio_mac": ("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioMac"),
        "radio_utilization": ("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioChUtilizationRate"),
        "radio_interference": ("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioChInterferenceRate"),
        "radio_eirp": ("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioActualEIRP"),
        "radio_type": ("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioType"),
        "radio_channel": ("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioWorkingChannel"),
        "radio_clients": ("HUAWEI-WLAN-VAP-MIB", "hwWlanVapStaOnlineCnt"),
        "clients_2g": ("HUAWEI-WLAN-VAP-MIB", "hwWlanSsid2gStaCnt"),
        "clients_5g": ("HUAWEI-WLAN-VAP-MIB", "hwWlanSsid5gStaCnt"),
    }
    symbols, missing = _resolve_pinned_symbols(requests, mib_sources)
    if not symbols:
        return {
            "sensors": [],
            "category_results": [
                _category_result(
                    "wireless_controller", status="failed", complete=False,
                    reason_code="pinned_mib_symbols_unavailable",
                    reason="The exact pinned Huawei VRP wireless MIB symbols are not indexed in the active LibreNMS MIB database.",
                ),
            ],
        }

    reads = await probe._walk_many(
        ip, community, set(symbols.values()), port, version, walk_func=walk_func,
    )
    rows = {key: _row_map(reads.get(oid)) for key, oid in symbols.items()}
    complete = {
        key: bool(reads.get(oid) and reads[oid].complete and not reads[oid].reason)
        for key, oid in symbols.items()
    }
    lineage = {
        **_HUAWEI_VRP_RULE,
        "source_commit": PINNED_LIBRENMS_COMMIT,
        "collection_engine": "python",
        "rule_implementation": "Python equivalent of pinned LibreNMS VRP wireless discovery",
        "identity_os_key": str(rule.get("os_key") or "vrp"),
    }
    sensors: list[dict[str, Any]] = []
    ap_count = 0
    ap_count_oid = symbols.get("ap_count")
    for suffix, raw in sorted(rows.get("ap_count", {}).items()):
        value = _number(raw)
        if not ap_count_oid or suffix not in {"0", ""} or value is None or value < 0:
            continue
        sensor = _sensor(
            source_id="huawei:wireless:ap-count:controller",
            component_class="wireless_controller",
            measurement_type="wireless_sensor_value",
            oid=ap_count_oid,
            suffix=suffix or "0",
            raw_value=raw,
            value=value,
            unit="count",
            name="AP Count",
            labels={},
            metadata={**lineage, "wireless_sensor_class": "ap-count"},
        )
        if sensor:
            sensors.append(sensor)
            ap_count += 1

    band_rows: dict[str, dict[str, str]] = {}
    band_suffixes: dict[str, dict[str, str]] = {}
    invalid_ssid_indexes = 0
    invalid_client_values = 0
    for key, band in (("clients_2g", "2.4 GHz"), ("clients_5g", "5 GHz")):
        raw_rows = rows.get(key, {})
        band_rows[band], invalid = _indexed_octet_rows(raw_rows)
        invalid_ssid_indexes += invalid
        band_suffixes[band] = {
            ssid: suffix
            for suffix in raw_rows
            if (ssid := _decode_octet_string_index(suffix)) is not None
        }
    ssid_totals: dict[str, float] = {}
    ssid_suffixes: dict[str, str] = {}
    ssid_sensor_count = 0
    for band, ssids in band_rows.items():
        oid_key = "clients_2g" if band == "2.4 GHz" else "clients_5g"
        oid = symbols.get(oid_key)
        for ssid, raw in sorted(ssids.items()):
            value = _number(raw)
            if value is None or value < 0 or not oid:
                invalid_client_values += 1
                continue
            sensor = _sensor(
                source_id=f"huawei:wireless:ssid:{band}:{ssid}",
                component_class="wireless_ssid",
                measurement_type="wireless_sensor_value",
                oid=oid,
                suffix=band_suffixes.get(band, {}).get(ssid, "0"),
                raw_value=raw,
                value=value,
                unit="count",
                name=f"SSID: {ssid} ({band})",
                labels={"ssid": ssid, "radio_band": band},
                metadata={**lineage, "wireless_sensor_class": "clients"},
            )
            if sensor:
                sensors.append(sensor)
                ssid_sensor_count += 1
                ssid_totals[ssid] = ssid_totals.get(ssid, 0.0) + value
                ssid_suffixes.setdefault(ssid, band_suffixes.get(band, {}).get(ssid, ""))

    clients_complete = (
        complete.get("clients_2g", False)
        and complete.get("clients_5g", False)
        and invalid_ssid_indexes == 0
        and invalid_client_values == 0
    )
    if clients_complete and ssid_sensor_count:
        ssid_client_oids = [symbols["clients_2g"], symbols["clients_5g"]]
        for ssid, value in sorted(ssid_totals.items()):
            suffix = ssid_suffixes.get(ssid, "")
            sensor = _sensor(
                source_id=f"huawei:wireless:ssid:total:{ssid}",
                component_class="wireless_ssid",
                measurement_type="wireless_sensor_value",
                oid=symbols["clients_2g"],
                suffix=suffix,
                raw_value=value,
                value=value,
                unit="count",
                name=f"SSID: {ssid}",
                labels={"ssid": ssid, "radio_band": "all", "group": "clients"},
                metadata={**lineage, "wireless_sensor_class": "clients"},
                poll_plan={"kind": "table_multi_sum", "oids": ssid_client_oids, "index": suffix},
            )
            if sensor:
                sensors.append(sensor)

        total_clients = sum(ssid_totals.values())
        client_total = _sensor(
            source_id="huawei:wireless:clients:controller",
            component_class="wireless_controller",
            measurement_type="wireless_sensor_value",
            oid=symbols["clients_2g"],
            suffix="0",
            raw_value=total_clients,
            value=total_clients,
            unit="count",
            name="Total Clients",
            labels={},
            metadata={**lineage, "wireless_sensor_class": "clients"},
            poll_plan={"kind": "table_multi_sum", "oids": ssid_client_oids, "index": ""},
        )
        if client_total:
            sensors.append(client_total)

    # LibreNMS VRP pollOS() joins AP identity, per-AP radio configuration and
    # VAP client tables. Keep table presence separate from AP/radio state.
    ap_names: dict[str, str] = {}
    ap_labels_by_mac: dict[str, dict[str, Any]] = {}
    invalid_ap_indexes = 0
    invalid_ap_identity_rows = 0
    for suffix, raw_name in sorted(rows.get("ap_name", {}).items()):
        decoded = _decode_mac_index(suffix)
        if decoded is None:
            invalid_ap_indexes += 1
            continue
        mac = decoded[0]
        name = str(raw_name or "").strip()[:160]
        if not name:
            invalid_ap_identity_rows += 1
            name = f"AP {mac}"
        serial = str(rows.get("ap_serial", {}).get(suffix) or "").strip()[:120]
        model = str(rows.get("ap_model", {}).get(suffix) or "").strip()[:120]
        labels: dict[str, Any] = {"ap_mac": mac, "ap_name": name}
        if serial:
            labels["ap_serial"] = serial
        if model:
            labels["ap_model"] = model
        ap_names[mac] = name
        ap_labels_by_mac[mac] = labels
        ap_sensor = _sensor(
            source_id=f"huawei:wireless:ap:presence:{mac}",
            component_class="wireless_access_point",
            measurement_type="component_state",
            oid=symbols.get("ap_name", ""),
            suffix=suffix,
            raw_value="present",
            value=1,
            unit="state",
            name=f"{name} inventory presence",
            labels=labels,
            states={"1": "present"},
            metadata={
                **lineage,
                "wireless_sensor_class": "inventory-presence",
                "state_semantics": "AP row exists in the pinned LibreNMS VRP inventory; this is not an AP or radio operational state.",
            },
        )
        if ap_sensor:
            sensors.append(ap_sensor)

    radio_suffixes = set().union(*(
        set(rows.get(key, {}))
        for key in ("radio_mac", "radio_utilization", "radio_interference", "radio_eirp", "radio_type", "radio_channel")
    ))
    radio_client_counts: dict[tuple[str, int], float] = {}
    invalid_radio_indexes = 0
    for suffix, raw_clients in sorted(rows.get("radio_clients", {}).items()):
        decoded = _decode_mac_index(suffix, trailing_parts=2)
        value = _number(raw_clients)
        if decoded is None or value is None or value < 0:
            invalid_radio_indexes += 1
            continue
        mac, (radio_id, _wlan_id) = decoded
        key = (mac, radio_id)
        radio_client_counts[key] = radio_client_counts.get(key, 0.0) + value

    radio_emitted = 0
    for suffix in sorted(radio_suffixes):
        decoded = _decode_mac_index(suffix, trailing_parts=1)
        if decoded is None:
            invalid_radio_indexes += 1
            continue
        mac, (radio_id,) = decoded
        ap_name = ap_names.get(mac, f"AP {mac}")
        labels = dict(ap_labels_by_mac.get(mac, {"ap_mac": mac, "ap_name": ap_name}))
        labels["radio_id"] = radio_id
        raw_type = rows.get("radio_type", {}).get(suffix)
        radio_type = _numeric_enum(raw_type)
        if radio_type is not None:
            type_bits = ((1, "b"), (2, "a"), (4, "g"), (8, "n"), (16, "ac"), (32, "ax"))
            decoded_type = "dot11" + "".join(name for bit, name in type_bits if int(radio_type) & bit)
            labels["radio_type"] = decoded_type
        radio_mac = _format_mac_address(rows.get("radio_mac", {}).get(suffix))
        if radio_mac:
            labels["radio_mac"] = radio_mac
        radio_name = f"{ap_name} Radio {radio_id}"
        radio_suffix = f"{mac}.{radio_id}"
        raw_channel = rows.get("radio_channel", {}).get(suffix)
        channel = _numeric_enum(raw_channel)
        if channel is not None and channel >= 0:
            sensor = _sensor(
                source_id=f"huawei:wireless:radio:channel:{radio_suffix}",
                component_class="wireless_radio", measurement_type="wireless_sensor_value",
                oid=symbols.get("radio_channel", ""), suffix=suffix,
                raw_value=raw_channel, value=channel, unit="channel",
                name=f"{radio_name} Channel", labels=labels,
                metadata={**lineage, "wireless_sensor_class": "channel"},
            )
            if sensor:
                sensors.append(sensor)
                radio_emitted += 1

        raw_eirp = rows.get("radio_eirp", {}).get(suffix)
        eirp = _numeric_enum(raw_eirp)
        if eirp is not None and eirp >= 0:
            # Pinned LibreNMS maps values >127 (disabled/invalid) to zero.
            if eirp > 127:
                eirp = 0
            sensor = _sensor(
                source_id=f"huawei:wireless:radio:tx-power:{radio_suffix}",
                component_class="wireless_radio", measurement_type="wireless_sensor_value",
                oid=symbols.get("radio_eirp", ""), suffix=suffix,
                raw_value=raw_eirp, value=eirp, unit="dBm",
                name=f"{radio_name} EIRP", labels=labels,
                metadata={**lineage, "wireless_sensor_class": "tx-power"},
            )
            if sensor:
                sensors.append(sensor)

        for key, sensor_class, unit, name in (
            ("radio_utilization", "utilization", "percent", "Channel Utilization"),
            ("radio_interference", "interference", "percent", "Channel Interference"),
        ):
            raw = rows.get(key, {}).get(suffix)
            value = _numeric_enum(raw)
            if value is None or value < 0 or key == "radio_utilization" and value > 100:
                continue
            sensor = _sensor(
                source_id=f"huawei:wireless:radio:{sensor_class}:{radio_suffix}",
                component_class="wireless_radio", measurement_type="wireless_sensor_value",
                oid=symbols.get(key, ""), suffix=suffix,
                raw_value=raw, value=value, unit=unit,
                name=f"{radio_name} {name}", labels=labels,
                metadata={**lineage, "wireless_sensor_class": sensor_class},
            )
            if sensor:
                sensors.append(sensor)

        client_count = radio_client_counts.get((mac, radio_id), 0.0) if complete.get("radio_clients") else None
        if client_count is not None:
            sensor = _sensor(
                source_id=f"huawei:wireless:radio:clients:{radio_suffix}",
                component_class="wireless_radio", measurement_type="wireless_sensor_value",
                oid=symbols.get("radio_clients", ""), suffix=suffix,
                raw_value=client_count, value=client_count, unit="count",
                name=f"{radio_name} Associated Clients", labels=labels,
                metadata={**lineage, "wireless_sensor_class": "clients"},
            )
            if sensor:
                sensors.append(sensor)

    controller_complete = complete.get("ap_count", False) and not any(
        item.endswith("::hwWlanCurJointApNum") for item in missing
    )
    controller_sensors = [
        sensor for sensor in sensors
        if sensor.get("component_class") == "wireless_controller"
    ]
    controller_result = _category_result(
        "wireless_controller",
        status="success" if ap_count and controller_complete else "partial" if controller_sensors else "not_found" if controller_complete else "failed",
        complete=controller_complete,
        reason_code="huawei_vrp_wireless_ap_count" if ap_count and controller_complete else "no_huawei_vrp_ap_count" if controller_complete else "huawei_vrp_wireless_walk_incomplete",
        reason=f"Pinned LibreNMS VRP discovery returned AP count and {1 if clients_complete and ssid_sensor_count else 0} complete client total." if ap_count and controller_complete else "No Huawei VRP AP count was returned." if controller_complete else "The Huawei VRP AP-count walk or exact symbol lookup did not complete.",
    )
    ssid_complete = clients_complete and not any(
        item.endswith(("::hwWlanSsid2gStaCnt", "::hwWlanSsid5gStaCnt")) for item in missing
    )
    ssid_result = _category_result(
        "wireless_ssid",
        status="success" if ssid_sensor_count and ssid_complete else "partial" if ssid_sensor_count else "not_found" if ssid_complete else "failed",
        complete=ssid_complete,
        reason_code="huawei_vrp_ssid_client_counts" if ssid_sensor_count and ssid_complete else "invalid_huawei_ssid_index_or_value" if invalid_ssid_indexes or invalid_client_values else "no_huawei_vrp_ssid_rows" if ssid_complete else "huawei_vrp_ssid_walk_incomplete",
        reason=f"Pinned LibreNMS VRP discovery returned {ssid_sensor_count} SSID/band count row(s)." if ssid_sensor_count and ssid_complete else f"Huawei SSID tables included {invalid_ssid_indexes + invalid_client_values} invalid index/value row(s)." if invalid_ssid_indexes or invalid_client_values else "No Huawei VRP SSID client rows were returned." if ssid_complete else "One or more Huawei VRP SSID count walks or exact symbol lookups did not complete.",
    )
    ap_complete = (
        complete.get("ap_name", False)
        and complete.get("ap_serial", False)
        and complete.get("ap_model", False)
        and invalid_ap_indexes == 0
        and invalid_ap_identity_rows == 0
        and not any("::hwWlanAp" in item for item in missing)
    )
    ap_sensor_count = sum(
        1 for sensor in sensors
        if sensor.get("component_class") == "wireless_access_point"
    )
    ap_result = _category_result(
        "wireless_access_point",
        status="success" if ap_sensor_count and ap_complete else "partial" if ap_sensor_count else "not_found" if ap_complete else "failed",
        complete=ap_complete,
        reason_code="huawei_vrp_ap_inventory" if ap_sensor_count and ap_complete else "invalid_huawei_ap_index" if invalid_ap_indexes else "huawei_vrp_ap_name_missing" if invalid_ap_identity_rows else "no_huawei_vrp_ap_rows" if ap_complete else "huawei_vrp_ap_walk_incomplete",
        reason=f"Pinned LibreNMS VRP AP table returned {ap_sensor_count} inventory row(s); presence does not assert AP operational state." if ap_sensor_count and ap_complete else f"Huawei AP table contained {invalid_ap_indexes + invalid_ap_identity_rows} invalid identity row(s)." if invalid_ap_indexes or invalid_ap_identity_rows else "No Huawei VRP AP rows were returned." if ap_complete else "One or more pinned Huawei VRP AP identity walks or MIB symbols did not complete.",
    )
    required_radio_keys = ("radio_mac", "radio_utilization", "radio_interference", "radio_eirp", "radio_type", "radio_channel", "radio_clients")
    radio_complete = all(complete.get(key, False) for key in required_radio_keys) and invalid_radio_indexes == 0 and not missing
    radio_result = _category_result(
        "wireless_radio",
        status="success" if radio_emitted and radio_complete else "partial" if radio_emitted else "not_found" if radio_complete else "failed",
        complete=radio_complete,
        reason_code="huawei_vrp_ap_radio_rows" if radio_emitted and radio_complete else "invalid_huawei_radio_index_or_value" if invalid_radio_indexes else "no_huawei_vrp_radio_rows" if radio_complete else "huawei_vrp_radio_walk_incomplete",
        reason=f"Pinned LibreNMS VRP polling returned {radio_emitted} radio channel row(s), utilization, interference, EIRP, and per-radio client counts." if radio_emitted and radio_complete else f"Huawei radio/VAP tables contained {invalid_radio_indexes} invalid index/value row(s)." if invalid_radio_indexes else "No Huawei VRP radio rows were returned." if radio_complete else "One or more pinned Huawei VRP radio/VAP walks or MIB symbols did not complete.",
    )
    return {"sensors": sensors, "category_results": [controller_result, ssid_result, ap_result, radio_result]}


async def _probe_cisco_ios_wireless(
    ip: str,
    community: str | Mapping[str, Any],
    port: int,
    *,
    identity: Mapping[str, Any],
    rule: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
) -> dict[str, Any]:
    from services import snmp_hardware_probe_service as probe

    model = str(identity.get("model") or identity.get("hardware") or "").strip()
    model_token = model.casefold()
    if not (model_token.startswith("air-") or "ciscoair" in model_token):
        return {
            "sensors": [],
            "category_results": [
                _category_result(
                    "wireless_radio", status="unsupported", complete=False,
                    reason_code="librenms_ios_wireless_model_not_supported",
                    reason="Pinned LibreNMS IOS wireless-client discovery only supports AIR/ciscoAIR hardware models.",
                ),
            ],
        }

    mib_sources = {
        "CISCO-DOT11-ASSOCIATION-MIB": "mibs/cisco/CISCO-DOT11-ASSOCIATION-MIB",
        "ENTITY-MIB": "mibs/ENTITY-MIB",
    }
    requests = {
        "radio_clients": ("CISCO-DOT11-ASSOCIATION-MIB", "cDot11ActiveWirelessClients"),
        "entity_description": ("ENTITY-MIB", "entPhysicalDescr"),
    }
    symbols, missing = _resolve_pinned_symbols(requests, mib_sources)
    lineage = {
        **_CISCO_IOS_RULE,
        "source_commit": PINNED_LIBRENMS_COMMIT,
        "collection_engine": "python",
        "rule_implementation": "Python equivalent of pinned LibreNMS IOS AIR wireless-client discovery",
        "identity_os_key": str(rule.get("os_key") or "ios"),
    }
    if "radio_clients" not in symbols:
        return {
            "sensors": [],
            "category_results": [
                _category_result(
                    "wireless_radio", status="failed", complete=False,
                    reason_code="pinned_mib_symbols_unavailable",
                    reason="The exact pinned Cisco IOS wireless MIB symbol is not indexed in the active LibreNMS MIB database.",
                ),
            ],
        }
    reads = await probe._walk_many(
        ip, community, set(symbols.values()), port, version, walk_func=walk_func,
    )
    radio_rows = _row_map(reads.get(symbols["radio_clients"]))
    radio_read_complete = bool(
        reads.get(symbols["radio_clients"])
        and reads[symbols["radio_clients"]].complete
        and not reads[symbols["radio_clients"]].reason
    )
    entity_rows = _row_map(reads.get(symbols.get("entity_description", ""))) if symbols.get("entity_description") else {}
    def row_sort_key(item: tuple[str, Any]) -> tuple[int, int | str]:
        suffix = str(item[0])
        return (0, int(suffix)) if suffix.isdigit() else (1, suffix)

    entity_names = [
        value.strip() for _index, value in sorted(entity_rows.items(), key=row_sort_key)
        if value.strip().casefold().endswith("radio")
    ]
    sensors: list[dict[str, Any]] = []
    invalid_indexes = 0
    for position, (suffix, raw) in enumerate(sorted(radio_rows.items(), key=row_sort_key)):
        if not suffix.isdigit() or int(suffix) <= 0:
            invalid_indexes += 1
            continue
        value = _number(raw)
        if value is None or value < 0:
            invalid_indexes += 1
            continue
        radio_ifindex = int(suffix)
        radio_name = entity_names[position] if position < len(entity_names) else f"Radio {radio_ifindex}"
        sensor = _sensor(
            source_id=f"cisco:wireless:clients:{radio_ifindex}",
            component_class="wireless_radio",
            measurement_type="wireless_sensor_value",
            oid=symbols["radio_clients"],
            suffix=suffix,
            raw_value=raw,
            value=value,
            unit="count",
            name=f"{model} {radio_name} Clients",
            labels={"radio_ifindex": radio_ifindex},
            metadata={**lineage, "wireless_sensor_class": "clients"},
        )
        if sensor:
            sensors.append(sensor)
    radio_complete = radio_read_complete and invalid_indexes == 0 and not any(
        item.endswith("::cDot11ActiveWirelessClients") for item in missing
    )
    radio_result = _category_result(
        "wireless_radio",
        status="success" if sensors and radio_complete else "partial" if sensors else "not_found" if radio_complete else "failed",
        complete=radio_complete,
        reason_code="cisco_ios_wireless_client_rows" if sensors and radio_complete else "invalid_cisco_wireless_client_index" if invalid_indexes else "no_cisco_ios_wireless_client_rows" if radio_complete else "cisco_ios_wireless_client_walk_incomplete",
        reason=f"Pinned LibreNMS IOS AIR discovery returned {len(sensors)} radio/client row(s)." if sensors and radio_complete else f"Cisco wireless-client table included {invalid_indexes} invalid row(s)." if invalid_indexes else "No Cisco IOS wireless-client rows were returned." if radio_complete else "The Cisco IOS wireless-client walk or exact symbol lookup did not complete.",
    )
    return {"sensors": sensors, "category_results": [radio_result]}


def _profile_label(value: Any, suffix: str) -> str:
    text = str(value or "").strip()
    if text:
        return text[:160]
    return _decode_octet_string_index(suffix) or suffix


def _software_version_tuple(value: Any) -> tuple[int, ...] | None:
    match = re.search(r"\d+(?:\.\d+)+", str(value or ""))
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.group(0).split("."))
    except ValueError:
        return None


def _profile_version_enabled(item: Mapping[str, Any], software_version: str) -> bool | None:
    minimum = str(item.get("minimum_software_version") or "").strip()
    maximum = str(item.get("maximum_software_version_exclusive") or "").strip()
    if not minimum and not maximum:
        return True
    actual = _software_version_tuple(software_version)
    if actual is None:
        return None

    def padded(value: tuple[int, ...], width: int) -> tuple[int, ...]:
        return value + (0,) * (width - len(value))

    lower = _software_version_tuple(minimum) if minimum else None
    upper = _software_version_tuple(maximum) if maximum else None
    if minimum and lower is None or maximum and upper is None:
        return None
    if lower is not None and padded(actual, max(len(actual), len(lower))) < padded(lower, max(len(actual), len(lower))):
        return False
    if upper is not None and padded(actual, max(len(actual), len(upper))) >= padded(upper, max(len(actual), len(upper))):
        return False
    return True


async def _probe_controller_ap_radio_detail(
    ip: str,
    community: str | Mapping[str, Any],
    port: int,
    *,
    os_key: str,
    profile: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
) -> dict[str, Any]:
    """Port the pinned Cisco WLC and ArubaOS AccessPoint pollers to Python."""
    from services import snmp_hardware_probe_service as probe

    source_rule = profile["source_rule"]
    mib_sources = profile.get("mib_sources") or {}
    detail_specs = profile.get("detail_symbols") or {}
    symbols, missing = _resolve_pinned_symbols(detail_specs, mib_sources)
    reads = await probe._walk_many(
        ip, community, set(symbols.values()), port, version, walk_func=walk_func,
    )
    rows = {key: _row_map(reads.get(oid)) for key, oid in symbols.items()}
    complete = {
        key: bool(reads.get(oid) and reads[oid].complete and not reads[oid].reason)
        for key, oid in symbols.items()
    }
    lineage = {
        **dict(source_rule),
        "source_commit": PINNED_LIBRENMS_COMMIT,
        "collection_engine": "python",
        "rule_implementation": "Python equivalent of pinned LibreNMS AP/radio polling",
        "identity_os_key": os_key,
    }
    sensors: list[dict[str, Any]] = []
    invalid_ap_indexes = 0
    invalid_radio_indexes = 0
    missing_ap_names = 0
    ap_rows: dict[str, dict[str, Any]] = {}

    def emit(
        *,
        suffix: str,
        oid_key: str,
        component_class: str,
        sensor_class: str,
        raw: Any,
        value: float,
        unit: str,
        name: str,
        labels: Mapping[str, Any],
        source_suffix: str | None = None,
        poll_factor: float = 1.0,
        poll_offset: float = 0.0,
        poll_plan: Mapping[str, Any] | None = None,
    ) -> bool:
        oid = symbols.get(oid_key, "")
        if not oid:
            return False
        sensor = _profile_detail_sensor(
            source_rule=source_rule,
            os_key=os_key,
            source_id=f"{source_rule['rule_key']}:{component_class}:{sensor_class}:{suffix}",
            component_class=component_class,
            sensor_class=sensor_class,
            oid=oid,
            suffix=source_suffix or suffix,
            raw_value=raw,
            value=value,
            unit=unit,
            name=name,
            labels=labels,
            poll_factor=poll_factor,
            poll_offset=poll_offset,
            poll_index=source_suffix or suffix,
            poll_plan=poll_plan,
        )
        if not sensor:
            return False
        sensors.append(sensor)
        return True

    def emit_presence(*, mac: str, suffix: str, name: str, labels: Mapping[str, Any], oid_key: str = "ap_name") -> bool:
        oid = symbols.get(oid_key, "")
        if not oid:
            return False
        sensor = _profile_detail_sensor(
            source_rule=source_rule,
            os_key=os_key,
            source_id=f"{source_rule['rule_key']}:wireless_access_point:presence:{mac}",
            component_class="wireless_access_point",
            sensor_class="inventory-presence",
            oid=oid,
            suffix=suffix,
            raw_value="present",
            value=1,
            unit="state",
            name=f"{name} inventory presence",
            labels=labels,
            states={"1": "present"},
        )
        if not sensor:
            return False
        sensor["metadata"]["state_semantics"] = "AP row exists in the pinned LibreNMS controller inventory; this is not an AP or radio operational state."
        sensors.append(sensor)
        return True

    if os_key in {"ciscowlc", "iosxe"}:
        ap_names: dict[str, tuple[str, str]] = {}
        for suffix, raw_name in sorted(rows.get("ap_name", {}).items()):
            decoded = _decode_mac_index(suffix)
            if decoded is None:
                invalid_ap_indexes += 1
                continue
            mac = decoded[0]
            name = str(raw_name or "").strip()[:160]
            if not name:
                missing_ap_names += 1
                name = f"AP {mac}"
            ap_names[mac] = (name, suffix)
            labels = {"ap_mac": mac, "ap_name": name}
            emit_presence(mac=mac, suffix=suffix, name=name, labels=labels)

        radio_suffixes = set().union(*(
            set(rows.get(key, {}))
            for key in ("channel", "radio_type", "tx_power", "utilization", "associated_clients", "interference")
        ))
        radio_emitted = 0
        required_radio_walks = ("radio_type", "channel", "tx_power", "utilization", "associated_clients", "interference")
        for suffix in sorted(radio_suffixes):
            decoded = _decode_mac_index(suffix, trailing_parts=1)
            if decoded is None:
                invalid_radio_indexes += 1
                continue
            mac, (radio_id,) = decoded
            raw_channel = rows.get("channel", {}).get(suffix)
            channel_text = str(raw_channel or "").strip().casefold().replace("ch", "", 1).strip()
            channel = _number(channel_text)
            if channel is None:
                invalid_radio_indexes += 1
                continue
            ap_name = ap_names.get(mac, (f"AP {mac}", ""))[0]
            if mac not in ap_names:
                missing_ap_names += 1
            radio_type = str(rows.get("radio_type", {}).get(suffix) or "").strip()
            labels = {"ap_name": ap_name, "ap_mac": mac, "radio_id": radio_id}
            if radio_type:
                labels["radio_type"] = radio_type[:80]
            suffix_id = f"{mac}.{radio_id}"
            radio_name = f"{ap_name} Radio {radio_id}"
            if emit(suffix=suffix_id, source_suffix=suffix, oid_key="channel", component_class="wireless_radio", sensor_class="channel", raw=raw_channel, value=channel, unit="channel", name=f"{radio_name} Channel", labels=labels):
                radio_emitted += 1

            for key, sensor_class, unit, name in (
                ("tx_power", "tx-power-level", "level", "Tx Power Level"),
                ("utilization", "utilization", "percent", "Channel Utilization"),
                ("associated_clients", "clients", "count", "Associated Clients"),
            ):
                raw = rows.get(key, {}).get(suffix)
                value = _numeric_enum(raw)
                if value is not None and value >= 0:
                    emit(suffix=suffix_id, source_suffix=suffix, oid_key=key, component_class="wireless_radio", sensor_class=sensor_class, raw=raw, value=value, unit=unit, name=f"{radio_name} {name}", labels=labels)

            interference_rows = rows.get("interference", {})
            channel_index = str(int(channel))
            interference_raw = interference_rows.get(f"{suffix}.{channel_index}")
            if interference_raw is None and complete.get("interference"):
                # LibreNMS initializes absent channel interference rows to -128
                # before applying the same 128 offset.
                interference_raw = -128
            interference_value = _numeric_enum(interference_raw)
            if interference_value is not None:
                interference_index = f"{suffix}.{channel_index}"
                emit(
                    suffix=suffix_id, source_suffix=suffix, oid_key="interference",
                    component_class="wireless_radio", sensor_class="interference",
                    raw=interference_raw, value=128 + interference_value, unit="index",
                    name=f"{radio_name} Interference", labels=labels,
                    poll_plan={
                        "kind": "table_value", "oid": symbols["interference"],
                        "index": interference_index, "factor": 1.0,
                        "offset": 128.0, "fallback_value": -128.0,
                    },
                )

        ap_count = sum(1 for item in sensors if item.get("component_class") == "wireless_access_point")
        ap_complete = complete.get("ap_name", False) and invalid_ap_indexes == 0 and missing_ap_names == 0
        radio_complete = all(complete.get(key, False) for key in required_radio_walks) and invalid_radio_indexes == 0 and missing_ap_names == 0 and not missing
        ap_result = _category_result(
            "wireless_access_point",
            status="success" if ap_count and ap_complete else "partial" if ap_count else "not_found" if ap_complete else "failed",
            complete=ap_complete,
            reason_code="cisco_wlc_ap_inventory" if ap_count and ap_complete else "invalid_cisco_wlc_ap_index" if invalid_ap_indexes else "cisco_wlc_ap_name_missing" if missing_ap_names else "no_cisco_wlc_ap_rows" if ap_complete else "cisco_wlc_ap_walk_incomplete",
            reason=f"Pinned LibreNMS Cisco WLC AP table returned {ap_count} AP inventory row(s); presence does not assert operational state." if ap_count and ap_complete else "Cisco WLC AP inventory rows contained invalid indexes or missing names." if invalid_ap_indexes or missing_ap_names else "No Cisco WLC AP inventory rows were returned." if ap_complete else "The pinned Cisco WLC AP inventory walk or MIB symbol lookup did not complete.",
        )
        radio_result = _category_result(
            "wireless_radio",
            status="success" if radio_emitted and radio_complete else "partial" if radio_emitted else "not_found" if radio_complete else "failed",
            complete=radio_complete,
            reason_code="cisco_wlc_ap_radio_rows" if radio_emitted and radio_complete else "invalid_cisco_wlc_radio_index_or_channel" if invalid_radio_indexes else "no_cisco_wlc_radio_rows" if radio_complete else "cisco_wlc_radio_walk_incomplete",
            reason=f"Pinned LibreNMS Cisco WLC polling returned {radio_emitted} AP/radio channel row(s) and its radio metrics." if radio_emitted and radio_complete else f"Cisco WLC radio table contained {invalid_radio_indexes} invalid index/channel row(s)." if invalid_radio_indexes else "No Cisco WLC radio rows were returned." if radio_complete else "One or more pinned Cisco WLC radio walks or MIB symbols did not complete.",
        )
        return {"sensors": sensors, "category_results": [ap_result, radio_result]}

    # ArubaOS polls the WLSX AP radio table and persists one AP/Radio record per
    # {AP MAC, radio number} row. AP inventory presence is derived from those
    # rows and is deliberately kept separate from operational state.
    radio_suffixes = set().union(*(
        set(rows.get(key, {}))
        for key in ("ap_name", "radio_type", "channel", "tx_power_10x", "tx_power", "utilization", "associated_clients", "monitored_clients", "active_bssids", "monitored_bssids", "interference")
    ))
    ap_rows: dict[str, tuple[str, str, Mapping[str, Any]]] = {}
    invalid_radio_indexes = 0
    missing_ap_names = 0
    radio_emitted = 0
    required_radio_walks = ("ap_name", "radio_type", "channel", "tx_power_10x", "tx_power", "utilization", "associated_clients", "monitored_clients", "active_bssids", "monitored_bssids", "interference")
    for suffix in sorted(radio_suffixes):
        decoded = _decode_mac_index(suffix, trailing_parts=1)
        if decoded is None:
            invalid_radio_indexes += 1
            continue
        mac, (radio_id,) = decoded
        raw_channel = rows.get("channel", {}).get(suffix)
        channel = _numeric_enum(raw_channel)
        if channel is None:
            invalid_radio_indexes += 1
            continue
        ap_name = str(rows.get("ap_name", {}).get(suffix) or "").strip()[:160]
        if not ap_name:
            missing_ap_names += 1
            ap_name = f"AP {mac}"
        labels = {"ap_name": ap_name, "ap_mac": mac, "radio_id": radio_id}
        radio_type = str(rows.get("radio_type", {}).get(suffix) or "").strip()
        if radio_type:
            labels["radio_type"] = radio_type[:80]
        ap_rows.setdefault(mac, (ap_name, suffix, labels))
        suffix_id = f"{mac}.{radio_id}"
        radio_name = f"{ap_name} Radio {radio_id}"
        emitted_channel = emit(suffix=suffix_id, source_suffix=suffix, oid_key="channel", component_class="wireless_radio", sensor_class="channel", raw=raw_channel, value=channel, unit="channel", name=f"{radio_name} Channel", labels=labels)
        radio_emitted += int(emitted_channel)

        tx_power_raw = rows.get("tx_power_10x", {}).get(suffix)
        tx_power = _number(tx_power_raw)
        tx_power_key = "tx_power_10x"
        if tx_power is not None:
            tx_power /= 10
        else:
            tx_power_raw = rows.get("tx_power", {}).get(suffix)
            tx_power = _number(tx_power_raw)
            tx_power_key = "tx_power"
            if tx_power is not None:
                tx_power /= 2
        if tx_power is not None:
            emit(
                suffix=suffix_id, source_suffix=suffix, oid_key=tx_power_key,
                component_class="wireless_radio", sensor_class="tx-power",
                raw=tx_power_raw, value=tx_power, unit="dBm",
                name=f"{radio_name} Tx Power", labels=labels,
                poll_factor=0.1 if tx_power_key == "tx_power_10x" else 0.5,
            )

        for key, sensor_class, unit, name, multiplier in (
            ("utilization", "utilization", "percent", "Utilization", 1.0),
            ("associated_clients", "associated-clients", "count", "Associated Clients", 1.0),
            ("monitored_clients", "monitored-clients", "count", "Monitored Clients", 1.0),
            ("active_bssids", "active-bssids", "count", "Active BSSIDs", 1.0),
            ("monitored_bssids", "monitored-bssids", "count", "Monitored BSSIDs", 1.0),
            ("interference", "interference", "index", "Interference", 1 / 600),
        ):
            value_suffix = f"{suffix}.{int(channel)}" if key == "interference" else suffix
            raw = rows.get(key, {}).get(value_suffix)
            numeric = _numeric_enum(raw)
            if numeric is None and key == "interference" and complete.get(key):
                numeric = 0
                raw = 0
            if numeric is not None and numeric >= 0:
                poll_plan = None
                if key == "interference":
                    poll_plan = {
                        "kind": "table_value", "oid": symbols[key],
                        "index": value_suffix, "factor": multiplier,
                        "fallback_value": 0.0,
                    }
                emit(
                    suffix=suffix_id, source_suffix=suffix, oid_key=key,
                    component_class="wireless_radio", sensor_class=sensor_class,
                    raw=raw, value=numeric * multiplier, unit=unit,
                    name=f"{radio_name} {name}", labels=labels,
                    poll_factor=multiplier,
                    poll_plan=poll_plan,
                )

    # Emit AP presence after the radio join so the row is unique per AP.
    for mac, (ap_name, suffix, labels) in sorted(ap_rows.items()):
        # Remove the per-radio label: AP identity is keyed by the AP MAC.
        ap_labels = {key: value for key, value in labels.items() if key != "radio_id"}
        # The first radio row provides a valid indexed source OID for this
        # inventory-presence sample; it does not claim radio state.
        presence = next((item for item in sensors if item.get("source_id") == f"{source_rule['rule_key']}:wireless_access_point:presence:{mac}"), None)
        if presence:
            presence["index_labels"].update(ap_labels)
            continue
        emit_presence(mac=mac, suffix=suffix, name=ap_name, labels=ap_labels)

    ap_count = len(ap_rows)
    ap_complete = all(complete.get(key, False) for key in ("ap_name", "channel")) and invalid_radio_indexes == 0 and missing_ap_names == 0 and not missing
    radio_complete = all(complete.get(key, False) for key in required_radio_walks) and invalid_radio_indexes == 0 and missing_ap_names == 0 and not missing
    ap_result = _category_result(
        "wireless_access_point",
        status="success" if ap_count and ap_complete else "partial" if ap_count else "not_found" if ap_complete else "failed",
        complete=ap_complete,
        reason_code="arubaos_ap_inventory" if ap_count and ap_complete else "invalid_arubaos_radio_index" if invalid_radio_indexes else "arubaos_ap_name_missing" if missing_ap_names else "no_arubaos_ap_rows" if ap_complete else "arubaos_ap_radio_walk_incomplete",
        reason=f"Pinned LibreNMS ArubaOS radio table returned {ap_count} AP inventory row(s); presence does not assert operational state." if ap_count and ap_complete else f"ArubaOS radio table contained {invalid_radio_indexes} invalid index/channel row(s)." if invalid_radio_indexes else "No ArubaOS AP/radio rows were returned." if ap_complete else "The pinned ArubaOS AP/radio walks or MIB symbol lookup did not complete.",
    )
    radio_result = _category_result(
        "wireless_radio",
        status="success" if radio_emitted and radio_complete else "partial" if radio_emitted else "not_found" if radio_complete else "failed",
        complete=radio_complete,
        reason_code="arubaos_ap_radio_rows" if radio_emitted and radio_complete else "invalid_arubaos_radio_index_or_channel" if invalid_radio_indexes else "no_arubaos_radio_rows" if radio_complete else "arubaos_radio_walk_incomplete",
        reason=f"Pinned LibreNMS ArubaOS polling returned {radio_emitted} AP/radio row(s) and radio metrics." if radio_emitted and radio_complete else f"ArubaOS radio table contained {invalid_radio_indexes} invalid index/channel row(s)." if invalid_radio_indexes else "No ArubaOS radio rows were returned." if radio_complete else "One or more pinned ArubaOS radio walks or MIB symbols did not complete.",
    )
    return {"sensors": sensors, "category_results": [ap_result, radio_result]}


async def _probe_profile_wireless(
    ip: str,
    community: str | Mapping[str, Any],
    port: int,
    *,
    os_key: str,
    profile: Mapping[str, Any],
    version: str,
    software_version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
) -> dict[str, Any]:
    """Run reviewed scalar/table adapters for additional pinned LibreNMS OS classes."""
    from services import snmp_hardware_probe_service as probe

    source_rule = profile["source_rule"]
    mib_sources = profile.get("mib_sources") if isinstance(profile.get("mib_sources"), Mapping) else {}
    all_symbol_specs = profile.get("symbols") if isinstance(profile.get("symbols"), Mapping) else {}
    scalar_specs = [dict(item) for item in profile.get("scalars", []) if isinstance(item, Mapping)]
    scalar_groups = [dict(item) for item in profile.get("scalar_groups", []) if isinstance(item, Mapping)]
    version_unknown_classes: set[str] = set()

    def enabled_specs(name: str) -> list[dict[str, Any]]:
        enabled: list[dict[str, Any]] = []
        for raw_item in profile.get(name, []):
            if not isinstance(raw_item, Mapping):
                continue
            item = dict(raw_item)
            result = _profile_version_enabled(item, software_version)
            if result is True:
                enabled.append(item)
            elif result is None:
                component_class = str(item.get("component_class") or "wireless_controller")
                version_unknown_classes.add(component_class)
        return enabled

    table_specs = enabled_specs("tables")
    aggregate_specs = enabled_specs("aggregates")
    required_symbol_keys: set[str] = set()
    for item in scalar_specs + scalar_groups + table_specs + aggregate_specs:
        symbol_key = str(item.get("symbol") or "")
        if symbol_key:
            required_symbol_keys.add(symbol_key)
        for label_name in ("label_symbols", "group_label_symbols"):
            labels = item.get(label_name) if isinstance(item.get(label_name), Mapping) else {}
            for symbol_value in labels.values():
                candidates = symbol_value if isinstance(symbol_value, list) else [symbol_value]
                required_symbol_keys.update(str(candidate) for candidate in candidates if str(candidate))
        for condition_name in (
            "skip_zero_if_positive_symbol",
            "skip_row_if_all_zero_symbols",
            "skip_row_if_all_empty_or_zero_symbols",
        ):
            condition_value = item.get(condition_name)
            candidates = condition_value if isinstance(condition_value, list) else [condition_value]
            required_symbol_keys.update(str(candidate) for candidate in candidates if str(candidate))
    symbol_specs = {
        key: spec for key, spec in all_symbol_specs.items()
        if key in required_symbol_keys
    }
    symbols, missing = _resolve_pinned_symbols(symbol_specs, mib_sources)

    def scalar_oid(item: Mapping[str, Any]) -> str:
        symbol_key = str(item.get("symbol") or "")
        if symbol_key:
            base_oid = str(symbols.get(symbol_key) or "").strip().strip(".")
            instance = str(item.get("instance", "0") or "").strip().strip(".")
            return f"{base_oid}.{instance}" if base_oid and instance else base_oid
        return str(item.get("oid") or "").strip().strip(".")

    # Literal scalar OIDs are complete instances; symbol-backed scalars append
    # the MIB scalar's .0 instance to the verified object OID.
    get_oids = {
        scalar_oid(item)
        for item in scalar_specs
    }
    for group in scalar_groups:
        get_oids.update(
            str(oid or "").strip().strip(".")
            for oid in group.get("oids", [])
        )
    get_oids.discard("")
    scalar_values = await probe._get_many(ip, community, get_oids, port, version)

    needed_walks = {
        symbols[str(item.get("symbol") or "")]
        for item in table_specs + aggregate_specs
        if str(item.get("symbol") or "") in symbols
    }
    for item in table_specs:
        label_symbols = item.get("label_symbols") if isinstance(item.get("label_symbols"), Mapping) else {}
        for symbol_value in label_symbols.values():
            candidates = symbol_value if isinstance(symbol_value, list) else [symbol_value]
            needed_walks.update(symbols[str(candidate)] for candidate in candidates if str(candidate) in symbols)
    for item in aggregate_specs:
        label_symbols = item.get("group_label_symbols") if isinstance(item.get("group_label_symbols"), Mapping) else {}
        for symbol_value in label_symbols.values():
            candidates = symbol_value if isinstance(symbol_value, list) else [symbol_value]
            needed_walks.update(symbols[str(candidate)] for candidate in candidates if str(candidate) in symbols)
    reads = await probe._walk_many(
        ip, community, needed_walks, port, version, walk_func=walk_func,
    )
    rows_by_symbol = {
        key: _row_map(reads.get(oid))
        for key, oid in symbols.items()
    }
    walk_complete = {
        key: bool(reads.get(oid) and reads[oid].complete and not reads[oid].reason)
        for key, oid in symbols.items()
    }
    conditional_total_specs = [
        (str(item.get("symbol") or ""), item.get("conditional_total"))
        for item in table_specs
        if isinstance(item.get("conditional_total"), Mapping)
    ]
    conditional_total_specs = [
        (symbol_key, dict(spec))
        for symbol_key, spec in conditional_total_specs
        if symbol_key in symbols
        and len(rows_by_symbol.get(symbol_key, {})) >= max(1, int(spec.get("minimum_rows", 2)))
    ]
    conditional_total_oids = {
        str(spec.get("oid") or "").strip().strip(".")
        for _symbol_key, spec in conditional_total_specs
        if str(spec.get("oid") or "").strip().strip(".")
    }
    if conditional_total_oids:
        scalar_values.update(await probe._get_many(
            ip, community, conditional_total_oids, port, version,
        ))

    lineage = {
        **dict(source_rule),
        "source_commit": PINNED_LIBRENMS_COMMIT,
        "collection_engine": "python",
        "rule_implementation": "Nexora Python adapter for pinned LibreNMS wireless MIB definitions",
        "identity_os_key": os_key,
    }
    sensors: list[dict[str, Any]] = []
    class_state: dict[str, dict[str, Any]] = {}

    def track(component_class: str, *, complete: bool, sensor_count: int) -> None:
        state = class_state.setdefault(component_class, {"complete": True, "sensors": 0})
        state["complete"] = bool(state["complete"] and complete)
        state["sensors"] += sensor_count

    def emit(
        *,
        oid: str,
        suffix: str,
        raw: Any,
        component_class: str,
        sensor_class: str,
        unit: str,
        name: str,
        labels: Mapping[str, Any] | None = None,
        get_mode: bool = False,
        value_multiplier: float = 1.0,
        allow_negative: bool = False,
        value_transform: str = "",
        value_max: float | None = None,
        poll_plan: Mapping[str, Any] | None = None,
    ) -> bool:
        value = _channel_to_frequency(raw) if value_transform == "channel_to_frequency" else _number(raw)
        if value is None or (value < 0 and not allow_negative):
            return False
        value *= value_multiplier
        if value_max is not None:
            value = min(value, value_max)
        if _number(value) is None:
            return False
        sensor = _sensor(
            source_id=f"{source_rule['rule_key']}:{component_class}:{sensor_class}:{suffix or '0'}",
            component_class=component_class,
            measurement_type="wireless_sensor_value",
            oid=oid,
            suffix=suffix or "0",
            raw_value=raw,
            value=value,
            unit=unit,
            name=name,
            labels=labels or {},
            metadata={**lineage, "wireless_sensor_class": sensor_class},
        )
        if not sensor:
            return False
        if poll_plan is not None:
            sensor["metadata"]["poll_plan"] = dict(poll_plan)
        else:
            planned: dict[str, Any] = {
                "kind": "get" if get_mode else "direct",
                "oid": oid,
            }
            if value_multiplier != 1.0:
                planned["factor"] = value_multiplier
            if not get_mode:
                planned["index"] = suffix or "0"
            if value_transform:
                planned["value_transform"] = value_transform
            if value_max is not None:
                planned["value_max"] = value_max
            sensor["metadata"]["poll_plan"] = planned
        sensor["index_labels"].update(dict(labels or {}))
        sensors.append(sensor)
        return True

    for item in scalar_specs:
        oid = scalar_oid(item)
        raw = scalar_values.get(oid)
        component_class = str(item.get("component_class") or "wireless_controller")
        sensor_class = str(item.get("sensor_class") or "value")
        numeric_value = _number(raw)
        emit_if_value_gt = _number(item.get("emit_if_value_gt"))
        condition_met = emit_if_value_gt is None or (numeric_value is not None and numeric_value > emit_if_value_gt)
        emitted = bool(oid and raw is not None and condition_met and emit(
            oid=oid,
            suffix=str(item.get("identity_suffix") or "0"),
            raw=raw,
            component_class=component_class,
            sensor_class=sensor_class,
            unit=str(item.get("unit") or "count"),
            name=str(item.get("name") or "Wireless metric"),
            labels={"group": str(item.get("group") or "")},
            get_mode=True,
            value_multiplier=float(item.get("value_multiplier", 1.0)),
            allow_negative=bool(item.get("allow_negative", False)),
            value_max=_number(item.get("value_max")),
        ))
        track(
            component_class,
            complete=(
                raw is not None
                and numeric_value is not None
                and (numeric_value >= 0 or bool(item.get("allow_negative", False)))
            ),
            sensor_count=int(emitted),
        )

    for group in scalar_groups:
        component_class = str(group.get("component_class") or "wireless_controller")
        candidates = [str(item or "").strip().strip(".") for item in group.get("oids", [])]
        chosen_oid = next((oid for oid in candidates if scalar_values.get(oid) is not None), "")
        raw = scalar_values.get(chosen_oid) if chosen_oid else None
        emitted = bool(chosen_oid and emit(
            oid=chosen_oid,
            suffix="0",
            raw=raw,
            component_class=component_class,
            sensor_class=str(group.get("sensor_class") or "value"),
            unit=str(group.get("unit") or "count"),
            name=str(group.get("name") or "Wireless metric"),
            labels={"group": str(group.get("group") or "")},
            get_mode=True,
        ))
        track(component_class, complete=bool(chosen_oid and emitted), sensor_count=int(emitted))

    for item in table_specs:
        symbol_key = str(item.get("symbol") or "")
        oid = symbols.get(symbol_key, "")
        component_class = str(item.get("component_class") or "wireless_radio")
        table_rows = rows_by_symbol.get(symbol_key, {})
        label_symbols = item.get("label_symbols") if isinstance(item.get("label_symbols"), Mapping) else {}
        invalid_rows = 0
        emitted_count = 0
        required_complete = bool(oid and walk_complete.get(symbol_key, False))
        condition_symbol_keys = set(str(key) for key in item.get("skip_row_if_all_zero_symbols", []))
        condition_symbol_keys.update(str(key) for key in item.get("skip_row_if_all_empty_or_zero_symbols", []))
        if item.get("skip_zero_if_positive_symbol"):
            condition_symbol_keys.add(str(item["skip_zero_if_positive_symbol"]))
        if any(not walk_complete.get(key, False) for key in condition_symbol_keys):
            required_complete = False
        table_entries = list(table_rows.items())
        emitted_unique_labels: set[tuple[str, ...]] = set()
        if item.get("first_row_only"):
            table_entries = table_entries[:1]
        else:
            table_entries.sort(key=lambda entry: entry[0])
        for suffix, raw in table_entries:
            if not suffix or _decode_octet_string_index(suffix) is None and not suffix.replace(".", "").isdigit():
                invalid_rows += 1
                continue
            skip_value_strings = item.get("skip_value_strings")
            if isinstance(skip_value_strings, (list, tuple, set)) and str(raw).strip() in {str(value).strip() for value in skip_value_strings}:
                continue
            zero_symbols = item.get("skip_row_if_all_zero_symbols")
            if isinstance(zero_symbols, (list, tuple)) and zero_symbols:
                zero_values = [rows_by_symbol.get(str(key), {}).get(suffix) for key in zero_symbols]
                if all(value is not None and str(value).strip() == "0" for value in zero_values):
                    continue
            empty_or_zero_symbols = item.get("skip_row_if_all_empty_or_zero_symbols")
            if isinstance(empty_or_zero_symbols, (list, tuple)) and empty_or_zero_symbols:
                related_values = [rows_by_symbol.get(str(key), {}).get(suffix) for key in empty_or_zero_symbols]
                if all(value is None or not str(value).strip() or _number(value) == 0 for value in related_values):
                    continue
            skip_empty_label = str(item.get("skip_empty_label") or "")
            if skip_empty_label:
                candidates = label_symbols.get(skip_empty_label)
                candidates = candidates if isinstance(candidates, list) else [candidates]
                label_key = next((str(candidate) for candidate in candidates if str(candidate) in rows_by_symbol), "")
                label_raw = rows_by_symbol.get(label_key, {}).get(suffix) if label_key else None
                if label_raw is None or not str(label_raw).strip():
                    continue
            labels: dict[str, Any] = {}
            for label, symbol_value in label_symbols.items():
                candidates = symbol_value if isinstance(symbol_value, list) else [symbol_value]
                match = next((str(candidate) for candidate in candidates if str(candidate) in rows_by_symbol), "")
                label_raw = rows_by_symbol.get(match, {}).get(suffix) if match else None
                if label_raw is not None:
                    labels[str(label)] = _profile_label(label_raw, suffix)
                elif len(candidates) == 1:
                    required_complete = False
            unique_label_names = item.get("unique_by_labels")
            if isinstance(unique_label_names, (list, tuple)) and unique_label_names:
                unique_key = tuple(str(labels.get(str(label)) or "").strip() for label in unique_label_names)
                if all(unique_key) and unique_key in emitted_unique_labels:
                    continue
                if all(unique_key):
                    emitted_unique_labels.add(unique_key)
            if not labels.get("ssid") and component_class == "wireless_ssid":
                labels["ssid"] = _profile_label(None, suffix)
            skip_zero_if_symbol = str(item.get("skip_zero_if_positive_symbol") or "")
            current_number = _number(raw)
            if (
                skip_zero_if_symbol
                and current_number == 0
                and _number(rows_by_symbol.get(skip_zero_if_symbol, {}).get(suffix))
                and (_number(rows_by_symbol.get(skip_zero_if_symbol, {}).get(suffix)) or 0) > 0
            ):
                continue
            label = ", ".join(f"{key}: {value}" for key, value in labels.items() if value)
            sensor_name = f"{item.get('name') or 'Wireless metric'}{f' ({label})' if label else f' ({suffix})'}"
            emitted = emit(
                oid=oid,
                suffix=suffix,
                raw=raw,
                component_class=component_class,
                sensor_class=str(item.get("sensor_class") or "value"),
                unit=str(item.get("unit") or "count"),
                name=sensor_name,
                labels=labels,
                value_multiplier=float(item.get("value_multiplier", 1.0)),
                allow_negative=bool(item.get("allow_negative", False)),
                value_transform=str(item.get("value_transform") or ""),
                value_max=_number(item.get("value_max")),
            )
            emitted_count += int(emitted)
            if not emitted:
                invalid_rows += 1
        if invalid_rows:
            required_complete = False
        track(component_class, complete=required_complete, sensor_count=emitted_count)

        conditional_total = item.get("conditional_total")
        if isinstance(conditional_total, Mapping) and len(table_rows) >= max(1, int(conditional_total.get("minimum_rows", 2))):
            total_oid = str(conditional_total.get("oid") or "").strip().strip(".")
            total_raw = scalar_values.get(total_oid)
            total_component = str(conditional_total.get("component_class") or "wireless_controller")
            total_sensor_class = str(conditional_total.get("sensor_class") or "clients")
            total_emitted = bool(total_oid and total_raw is not None and emit(
                oid=total_oid,
                suffix=str(conditional_total.get("identity_suffix") or "1"),
                raw=total_raw,
                component_class=total_component,
                sensor_class=total_sensor_class,
                unit=str(conditional_total.get("unit") or "count"),
                name=str(conditional_total.get("name") or "System Total"),
                labels={"group": str(conditional_total.get("group") or "")},
                get_mode=True,
            ))
            total_number = _number(total_raw)
            track(
                total_component,
                complete=bool(
                    walk_complete.get(symbol_key, False)
                    and total_oid
                    and total_number is not None
                    and total_number >= 0
                ),
                sensor_count=int(total_emitted),
            )

    for item in aggregate_specs:
        symbol_key = str(item.get("symbol") or "")
        oid = symbols.get(symbol_key, "")
        component_class = str(item.get("component_class") or "wireless_controller")
        sensor_class = str(item.get("sensor_class") or "value")
        kind = str(item.get("kind") or "")
        rows = rows_by_symbol.get(symbol_key, {})
        minimum_rows = max(0, int(item.get("minimum_rows", 0)))
        complete = bool(oid and walk_complete.get(symbol_key, False))
        label_symbols = item.get("group_label_symbols") if isinstance(item.get("group_label_symbols"), Mapping) else {}
        label_keys: dict[str, str] = {}
        labels_complete = True
        for label_name, label_symbol in label_symbols.items():
            symbol_name = str(label_symbol or "")
            label_oid = symbols.get(symbol_name, "")
            if label_oid:
                label_keys[str(label_name)] = symbol_name
            else:
                labels_complete = False
        complete = complete and labels_complete
        emissions: list[tuple[str, float, dict[str, Any], dict[str, Any]]] = []

        if kind == "table_count":
            if len(rows) >= minimum_rows or (not rows and item.get("emit_on_empty") and complete):
                suffix = "1"
                emissions.append((suffix, float(len(rows)), dict(item.get("labels") or {}), {
                    "kind": "table_count", "oid": oid,
                }))
        elif kind == "table_sum":
            numbers = [_number(raw) for raw in rows.values()]
            if (len(rows) >= minimum_rows or (not rows and item.get("emit_on_empty") and complete)) and all(value is not None for value in numbers):
                total = sum(value for value in numbers if value is not None)
                suffix = "1"
                multiplier = float(item.get("value_multiplier", 1.0))
                emissions.append((suffix, total * multiplier, dict(item.get("labels") or {}), {
                    "kind": "table_sum", "oid": oid, "factor": multiplier,
                }))
            elif rows:
                complete = False
        elif kind == "table_group_sum":
            groups: dict[tuple[tuple[str, str], ...], tuple[dict[str, Any], float, int]] = {}
            if len(rows) < minimum_rows:
                complete = complete and not rows
            for row_suffix, raw in rows.items():
                number = _number(raw)
                if number is None:
                    complete = False
                    continue
                row_labels: dict[str, Any] = {}
                for label_name, symbol_name in label_keys.items():
                    label_raw = rows_by_symbol.get(symbol_name, {}).get(row_suffix)
                    row_labels[label_name] = str(label_raw).strip() if label_raw is not None else row_suffix
                selected_label = str(item.get("aggregate_group_label") or "")
                selected_value = str(row_labels.get(selected_label) or "").strip()
                if item.get("skip_empty_group") and not selected_value:
                    continue
                group_key = tuple(sorted((str(key), str(value)) for key, value in row_labels.items()))
                current = groups.get(group_key)
                groups[group_key] = (row_labels, number + (current[1] if current else 0.0), 1 + (current[2] if current else 0))
            for group_index, group_key in enumerate(sorted(groups), start=1):
                row_labels, total, matched_rows = groups[group_key]
                if matched_rows < minimum_rows:
                    continue
                multiplier = float(item.get("value_multiplier", 1.0))
                poll_plan = {
                    "kind": "table_group_sum",
                    "oid": oid,
                    "label_oids": {
                        label_name: symbols[symbol_name]
                        for label_name, symbol_name in label_keys.items()
                    },
                    "group_labels": row_labels,
                    "factor": multiplier,
                }
                emissions.append((str(group_index), total * multiplier, row_labels, poll_plan))
        else:
            complete = False

        if not complete:
            track(component_class, complete=False, sensor_count=0)
        elif not emissions and rows and kind == "table_group_sum" and minimum_rows:
            track(component_class, complete=True, sensor_count=0)
        elif not emissions and not rows and not item.get("emit_on_empty") and kind in {"table_count", "table_sum"}:
            track(component_class, complete=True, sensor_count=0)

        emitted_count = 0
        for suffix, value, labels, poll_plan in emissions:
            if value < 0 and not bool(item.get("allow_negative", False)):
                complete = False
                continue
            if item.get("value_max") is not None:
                value = min(value, float(item["value_max"]))
                poll_plan = {**poll_plan, "value_max": float(item["value_max"])}
            emitted = emit(
                oid=oid,
                suffix=suffix,
                raw=value,
                component_class=component_class,
                sensor_class=sensor_class,
                unit=str(item.get("unit") or "count"),
                name=str(item.get("name") or "Wireless metric"),
                labels=labels,
                value_multiplier=1.0,
                allow_negative=bool(item.get("allow_negative", False)),
                poll_plan=poll_plan,
            )
            emitted_count += int(emitted)
            if not emitted:
                complete = False
        track(component_class, complete=complete, sensor_count=emitted_count)

    # Preserve categories even when an upstream table is empty or a pinned
    # symbol was not resolved; empty output must not look like complete data.
    expected_classes = set(class_state)
    expected_classes.update(
        str(item.get("component_class") or "wireless_controller")
        for item in scalar_specs + scalar_groups + table_specs + aggregate_specs
    )
    expected_classes.update(version_unknown_classes)
    for component_class in version_unknown_classes:
        state = class_state.setdefault(component_class, {"complete": False, "sensors": 0})
        state["complete"] = False
    for component_class in sorted(expected_classes):
        state = class_state.get(component_class, {"complete": False, "sensors": 0})
        complete = bool(state["complete"])
        count = int(state["sensors"])
        if missing and any(
            str(item.get("symbol") or "") in symbol_specs
            and symbols.get(str(item.get("symbol") or "")) is None
            and str(item.get("component_class") or "wireless_controller") == component_class
            for item in table_specs + aggregate_specs
        ):
            complete = False
        status = "success" if count and complete else "partial" if count else "not_found" if complete else "failed"
        reason_code = f"{source_rule['rule_key']}_{component_class}_metrics"
        reason = f"Pinned LibreNMS wireless inputs returned {count} pollable {component_class} metric(s)." if count else f"No pollable {component_class} metrics were returned by this pinned LibreNMS profile." if complete else f"The pinned {component_class} source table or scalar did not resolve or complete."
        if missing:
            reason += f" Unresolved MIB symbol(s): {len(missing)}."
        class_state[component_class]["result"] = _category_result(
            component_class,
            status=status,
            complete=complete,
            reason_code=reason_code,
            reason=reason,
        )
    category_results = [class_state[key]["result"] for key in sorted(expected_classes)]
    return {"sensors": sensors, "category_results": category_results}


async def _probe_stellar_wireless(
    ip: str,
    community: str | Mapping[str, Any],
    port: int,
    *,
    identity: Mapping[str, Any],
    source_rule: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
) -> dict[str, Any]:
    """Collect Stellar SSID client counts using only the mapped OAW MIB."""
    from services import snmp_hardware_probe_service as probe

    raw_model = str(identity.get("model") or identity.get("hardware") or "").strip()
    module = _STELLAR_MODEL_TO_MIB.get(raw_model.casefold())
    if not module:
        return {
            "sensors": [],
            "category_results": [
                _category_result(
                    component_class,
                    status="unsupported",
                    complete=False,
                    reason_code="unsupported_stellar_hardware_mib",
                    reason="The Stellar hardware identity does not map to one of the pinned OAW model MIBs.",
                )
                for component_class in ("wireless_controller", "wireless_ssid")
            ],
        }

    mib_path = f"mibs/nokia/stellar/{module}"
    symbols, missing = _resolve_pinned_symbols(
        {
            "ssid_names": (module, "apWlanEssid"),
            "client_services": (module, "apClientWlanService"),
        },
        {module: mib_path},
    )
    if missing or not all(key in symbols for key in ("ssid_names", "client_services")):
        return {
            "sensors": [],
            "category_results": [
                _category_result(
                    component_class,
                    status="unsupported",
                    complete=False,
                    reason_code="pinned_stellar_mib_symbols_unavailable",
                    reason="The pinned OAW MIB does not provide both required Stellar wireless client tables.",
                )
                for component_class in ("wireless_controller", "wireless_ssid")
            ],
        }

    reads = await probe._walk_many(
        ip,
        community,
        {symbols["ssid_names"], symbols["client_services"]},
        port,
        version,
        walk_func=walk_func,
    )
    required_oids = (symbols["ssid_names"], symbols["client_services"])
    if any(
        not (reads.get(oid) and reads[oid].complete and not reads[oid].reason)
        for oid in required_oids
    ):
        return {
            "sensors": [],
            "category_results": [
                _category_result(
                    component_class,
                    status="failed",
                    complete=False,
                    reason_code="stellar_wireless_walk_incomplete",
                    reason="One or more pinned Stellar wireless client table walks did not complete.",
                )
                for component_class in ("wireless_controller", "wireless_ssid")
            ],
        }

    ssid_rows = _row_map(reads[symbols["ssid_names"]])
    client_rows = _row_map(reads[symbols["client_services"]])
    client_counts: dict[str, int] = {}
    for raw_ssid in client_rows.values():
        ssid = str(raw_ssid).strip()
        client_counts[ssid] = client_counts.get(ssid, 0) + 1

    lineage = {
        **dict(source_rule),
        "source_commit": PINNED_LIBRENMS_COMMIT,
        "collection_engine": "python",
        "rule_implementation": "Nexora Python adapter for pinned LibreNMS Stellar wireless client discovery and polling",
        "identity_os_key": "stellar",
        "identity_model": module,
        "resolved_mib_source_file": mib_path,
    }
    sensors: list[dict[str, Any]] = []
    seen_ssids: set[str] = set()
    invalid_ssid_indexes = 0
    for suffix, raw_ssid in ssid_rows.items():
        if not re.fullmatch(r"\d+(?:\.\d+)*", suffix):
            invalid_ssid_indexes += 1
            continue
        ssid = str(raw_ssid).strip()
        if ssid == "athmon2" or ssid in seen_ssids:
            continue
        seen_ssids.add(ssid)
        value = client_counts.get(ssid, 0)
        sensor = _sensor(
            source_id=f"wireless_stellar:wireless_ssid:clients:{suffix}",
            component_class="wireless_ssid",
            measurement_type="wireless_sensor_value",
            oid=symbols["client_services"],
            suffix=suffix,
            raw_value=value,
            value=float(value),
            unit="count",
            name=f"SSID {ssid} Clients",
            labels={"ssid": ssid, "group": "clients"},
            metadata={**lineage, "wireless_sensor_class": "clients"},
            poll_plan={
                "kind": "table_group_count",
                "oid": symbols["client_services"],
                "group_value": ssid,
            },
        )
        if sensor:
            sensors.append(sensor)

    total = len(client_rows)
    total_sensor = _sensor(
        source_id="wireless_stellar:wireless_controller:clients:0",
        component_class="wireless_controller",
        measurement_type="wireless_sensor_value",
        oid=symbols["client_services"],
        suffix="0",
        raw_value=total,
        value=float(total),
        unit="count",
        name="Total Clients",
        labels={"group": "clients"},
        metadata={**lineage, "wireless_sensor_class": "clients"},
        poll_plan={"kind": "table_count", "oid": symbols["client_services"]},
    )
    if total_sensor:
        sensors.append(total_sensor)

    ssid_complete = invalid_ssid_indexes == 0
    ssid_result = _category_result(
        "wireless_ssid",
        status=("success" if seen_ssids and ssid_complete else "partial" if seen_ssids else "not_found" if ssid_complete else "failed"),
        complete=ssid_complete,
        reason_code="stellar_ssid_client_counts" if seen_ssids and ssid_complete else "invalid_stellar_ssid_index" if invalid_ssid_indexes else "no_stellar_ssid_rows",
        reason=f"Pinned LibreNMS Stellar discovery returned client counts for {len(seen_ssids)} SSID(s)." if seen_ssids and ssid_complete else f"Stellar SSID table contained {invalid_ssid_indexes} row(s) with invalid indexes." if invalid_ssid_indexes else "No non-monitoring Stellar SSID rows were returned.",
    )
    controller_result = _category_result(
        "wireless_controller",
        status="success" if total_sensor else "failed",
        complete=bool(total_sensor),
        reason_code="stellar_total_client_count" if total_sensor else "stellar_total_client_sensor_unavailable",
        reason=f"Pinned LibreNMS Stellar discovery counted {total} client table row(s)." if total_sensor else "Could not create the Stellar total client sensor.",
    )
    return {"sensors": sensors, "category_results": [ssid_result, controller_result]}


async def _probe_cisco_cellular_wireless(
    ip: str,
    community: str | Mapping[str, Any],
    port: int,
    *,
    os_key: str,
    source_rule: Mapping[str, Any],
    version: str,
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None,
) -> dict[str, Any]:
    """Port the pinned CiscoCellular trait's LTE/radio sensor discovery."""
    from services import snmp_hardware_probe_service as probe

    symbols, missing = _resolve_pinned_symbols(_CISCO_CELLULAR_SYMBOLS, _CISCO_CELLULAR_MIB_SOURCES)
    reads = await probe._walk_many(
        ip, community, set(symbols.values()), port, version, walk_func=walk_func,
    )
    rows = {key: _row_map(reads.get(oid)) for key, oid in symbols.items()}
    required = ("rssi", "channel", "cell", "rsrp", "rsrq", "snr")
    metric_specs = (
        ("rssi", "rssi", "dBm", "RSSI", 1.0, True),
        ("channel", "channel", "channel", "Channel", 1.0, False),
        ("cell", "cell", "cell", "Cell ID", 1.0, False),
        ("rsrp", "rsrp", "dBm", "RSRP", 1.0, True),
        ("rsrq", "rsrq", "dB", "RSRQ", 0.1, True),
        ("snr", "snr", "dB", "SNR", 0.1, True),
    )
    lineage = {
        **dict(source_rule),
        "source_commit": PINNED_LIBRENMS_COMMIT,
        "collection_engine": "python",
        "rule_implementation": "Python equivalent of pinned LibreNMS CiscoCellular trait",
        "identity_os_key": os_key,
    }
    sensors: list[dict[str, Any]] = []
    invalid_values = 0
    indexes: set[str] = set()
    for key in required:
        indexes.update(rows.get(key, {}))

    for key, sensor_class, unit, title, multiplier, allow_negative in metric_specs:
        oid = symbols.get(key, "")
        if not oid:
            continue
        for suffix, raw in sorted(rows.get(key, {}).items()):
            number = _number(raw)
            if number is None or (number < 0 and not allow_negative):
                invalid_values += 1
                continue
            number *= multiplier
            apn = rows.get("apn", {}).get(f"{suffix}.1", "")
            modem_name = rows.get("modem_name", {}).get(suffix, "")
            label = str(apn or modem_name or f"Cellular {suffix}").strip()[:160]
            labels = {"modem_index": suffix, "modem_name": str(modem_name or "").strip()[:160], "apn": str(apn or "").strip()[:160]}
            sensor = _profile_detail_sensor(
                source_rule=source_rule,
                os_key=os_key,
                source_id=f"{source_rule['rule_key']}:wireless_radio:{sensor_class}:{suffix}",
                component_class="wireless_radio",
                sensor_class=sensor_class,
                oid=oid,
                suffix=suffix,
                raw_value=raw,
                value=number,
                unit=unit,
                name=f"{title}: {label}",
                labels=labels,
                poll_factor=multiplier,
            )
            if sensor:
                sensors.append(sensor)

    required_complete = all(
        key in symbols
        and key not in missing
        and bool(reads.get(symbols[key]) and reads[symbols[key]].complete and not reads[symbols[key]].reason)
        for key in required
    )
    required_complete = required_complete and invalid_values == 0
    sensor_count = len(sensors)
    status = "success" if sensor_count and required_complete else "partial" if sensor_count else "not_found" if required_complete else "failed"
    result = _category_result(
        "wireless_radio",
        status=status,
        complete=required_complete,
        reason_code="cisco_cellular_wireless_rows" if sensor_count and required_complete else "invalid_cisco_cellular_value" if invalid_values else "no_cisco_cellular_wireless_rows" if required_complete else "cisco_cellular_wireless_walk_incomplete",
        reason=f"Pinned LibreNMS CiscoCellular discovery returned {sensor_count} cellular radio metric row(s) across {len(indexes)} index(es)." if sensor_count and required_complete else f"Cisco cellular tables contained {invalid_values} invalid value(s)." if invalid_values else "No Cisco cellular wireless rows were returned." if required_complete else "One or more pinned Cisco cellular MIB symbols or walks did not complete.",
    )
    return {"sensors": sensors, "category_results": [result]}


async def probe_librenms_wireless_hardware(
    ip: str,
    community: str | Mapping[str, Any],
    port: int,
    *,
    rule: Mapping[str, Any],
    identity: Mapping[str, Any],
    version: str = "2c",
    walk_func: Callable[..., Awaitable[list[tuple[str, str]]]] | None = None,
) -> dict[str, Any]:
    """Collect wireless metrics in Python from exact pinned LibreNMS sources."""
    os_key = str(rule.get("os_key") or "").strip().casefold()
    profile = _PROFILE_WIRELESS_RULES.get(os_key)
    if profile and profile.get("alias_of"):
        profile = _PROFILE_WIRELESS_RULES.get(str(profile.get("alias_of") or ""))
    if profile:
        source_rule = profile.get("source_rule")
        if not isinstance(source_rule, Mapping) or not verify_librenms_mib_rule({
            **dict(source_rule),
            "source_type": "librenms_mib_rule",
            "source_commit": PINNED_LIBRENMS_COMMIT,
        }):
            expected_classes = sorted({
                str(item.get("component_class") or "wireless_controller")
                for item in [
                    *(profile.get("scalars") or []),
                    *(profile.get("scalar_groups") or []),
                    *(profile.get("tables") or []),
                ]
                if isinstance(item, Mapping)
            } | ({"wireless_access_point", "wireless_radio"} if profile.get("detail_symbols") or os_key in {"aruba-instant", "ewc"} else set()) | ({"wireless_controller", "wireless_ssid"} if os_key == "stellar" else set()) or {"wireless_controller"})
            return {
                "sensors": [],
                "category_results": [
                    _category_result(
                        component_class,
                        status="unsupported",
                        complete=False,
                        reason_code="unverified_librenms_mib_rule",
                        reason="The exact pinned LibreNMS wireless class and MIB source set do not match the local manifest.",
                    )
                    for component_class in expected_classes
                ],
            }
        if os_key == "stellar":
            return await _probe_stellar_wireless(
                ip, community, port, identity=identity, source_rule=source_rule,
                version=version, walk_func=walk_func,
            )
        base_result = await _probe_profile_wireless(
            ip, community, port, os_key=os_key, profile=profile,
            version=version,
            software_version=str(identity.get("software_version") or identity.get("version") or ""),
            walk_func=walk_func,
        )
        detail_result: dict[str, Any] = {"sensors": [], "category_results": []}
        if profile.get("detail_symbols"):
            detail_result = await _probe_controller_ap_radio_detail(
                ip, community, port, os_key=os_key, profile=profile,
                version=version, walk_func=walk_func,
            )
        elif os_key in {"aruba-instant", "ewc"}:
            from services.librenms_wireless_detail_adapters import probe_wireless_profile_details

            detail_result = await probe_wireless_profile_details(
                os_key, ip, community, port, source_rule=source_rule,
                version=version,
                software_version=str(identity.get("software_version") or identity.get("version") or ""),
                walk_func=walk_func,
            )
        extra_results: list[Mapping[str, Any]] = [base_result, detail_result]
        if os_key == "iosxe":
            if verify_librenms_mib_rule({
                **_CISCO_IOSXE_CELLULAR_RULE,
                "source_type": "librenms_mib_rule",
                "source_commit": PINNED_LIBRENMS_COMMIT,
            }):
                extra_results.append(await _probe_cisco_cellular_wireless(
                    ip, community, port, os_key=os_key,
                    source_rule=_CISCO_IOSXE_CELLULAR_RULE,
                    version=version, walk_func=walk_func,
                ))
            else:
                extra_results.append({
                    "sensors": [],
                    "category_results": [_category_result(
                        "wireless_radio", status="unsupported", complete=False,
                        reason_code="unverified_librenms_cisco_iosxe_cellular_rule",
                        reason="The pinned IOS-XE CiscoCellular trait and MIB sources do not match the local LibreNMS manifest.",
                    )],
                })
        return _combine_wireless_results(*extra_results)
    if os_key in _WIRELESS_RULELESS_UPSTREAM:
        component_class, reason = _WIRELESS_RULELESS_UPSTREAM[os_key]
        return {
            "sensors": [],
            "category_results": [
                _category_result(
                    component_class,
                    status="unsupported",
                    complete=False,
                    reason_code="upstream_wireless_rule_has_no_pollable_ap_inventory",
                    reason=reason,
                ),
            ],
        }
    rule_by_os = {
        "comware": _H3C_RULE,
        "vrp": _HUAWEI_VRP_RULE,
        "ios": _CISCO_IOS_RULE,
    }
    source_rule = rule_by_os.get(os_key)
    if source_rule is None:
        return {"sensors": [], "category_results": []}
    if not verify_librenms_mib_rule({
        **source_rule,
        "source_type": "librenms_mib_rule",
        "source_commit": PINNED_LIBRENMS_COMMIT,
    }):
        component_class = "wireless_access_point" if os_key == "comware" else "wireless_controller" if os_key == "vrp" else "wireless_radio"
        vendor_name = {"comware": "H3C", "vrp": "Huawei VRP", "ios": "Cisco IOS"}[os_key]
        return {
            "sensors": [],
            "category_results": [
                _category_result(
                    component_class, status="unsupported", complete=False,
                    reason_code="unverified_librenms_mib_rule",
                    reason=f"The pinned {vendor_name} wireless source set does not match the LibreNMS manifest.",
                ),
            ],
        }
    if os_key == "comware":
        return await _probe_h3c_wireless(
            ip, community, port, version=version, walk_func=walk_func,
        )
    if os_key == "vrp":
        return await _probe_huawei_wireless(
            ip, community, port, rule=rule, version=version, walk_func=walk_func,
        )
    cisco_result = await _probe_cisco_ios_wireless(
        ip, community, port, identity=identity, rule=rule,
        version=version, walk_func=walk_func,
    )
    cellular_result = await _probe_cisco_cellular_wireless(
        ip, community, port, os_key=os_key, source_rule=_CISCO_IOS_RULE,
        version=version, walk_func=walk_func,
    )
    return _combine_wireless_results(
        cisco_result,
        cellular_result,
        ignore_unsupported_reason_codes=frozenset({"librenms_ios_wireless_model_not_supported"}),
    )


__all__ = ["probe_librenms_wireless_hardware"]
