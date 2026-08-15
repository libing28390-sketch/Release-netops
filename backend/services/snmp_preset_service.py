"""SNMP Preset Profiles and Built-in MIB Seeder.

Provides out-of-the-box model metric templates for major network vendors (Cisco,
Huawei, H3C, Arista, Ruijie, Juniper, Fortinet) and seeds standard RFC / vendor MIB definitions.
"""

from __future__ import annotations

import hashlib
import logging
from copy import deepcopy
from typing import Any

from database import get_db_connection
from services.snmp_mib_service import deduplicate_builtin_mibs, parse_and_store_mib

logger = logging.getLogger(__name__)

OFFICIAL_MODEL_PRESETS: list[dict[str, Any]] = [
    # ── Cisco IOS / IOS-XE (Catalyst 2960 / 3850 / 9300 / ISR 4000) ──
    {
        "vendor": "Cisco",
        "model": "Catalyst 9300",
        "category": "Campus Switch",
        "description": "Cisco Catalyst 9300 Series Enterprise Switch (IOS-XE)",
        "metric_definitions": {
            "cpu": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.9.9.109.1.1.1.1.8",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "memory": {
                "mode": "used_total_percent",
                "used_oid": "1.3.6.1.4.1.9.9.221.1.1.1.1.18",
                "total_oid": "1.3.6.1.4.1.9.9.221.1.1.1.1.17",
                "aggregation": "sum",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "temperature": {
                "mode": "direct_value",
                "oid": "1.3.6.1.4.1.9.9.13.1.3.1.3",
                "aggregation": "max",
                "unit": "°C",
                "scale": 1,
                "offset": 0,
            },
            "fan": {
                "mode": "status_code",
                "oid": "1.3.6.1.4.1.9.9.13.1.4.1.3",
                "status_ok_values": [1],
                "status_warning_values": [3],
                "status_fail_values": [2, 4],
                "aggregation": "first",
                "unit": "bool",
            },
            "power_supply": {
                "mode": "status_code",
                "oid": "1.3.6.1.4.1.9.9.13.1.5.1.3",
                "status_ok_values": [1],
                "status_warning_values": [],
                "status_fail_values": [2, 3, 4, 5],
                "aggregation": "first",
                "unit": "bool",
            },
        },
        "interface_config": {
            "enabled": True,
            "if_name_oid": "1.3.6.1.2.1.31.1.1.1.1",
            "if_descr_oid": "1.3.6.1.2.1.2.2.1.2",
            "if_alias_oid": "1.3.6.1.2.1.31.1.1.1.18",
            "if_oper_status_oid": "1.3.6.1.2.1.2.2.1.8",
            "if_high_speed_oid": "1.3.6.1.2.1.31.1.1.1.15",
            "if_speed_oid": "1.3.6.1.2.1.2.2.1.5",
            "if_last_change_oid": "1.3.6.1.2.1.2.2.1.9",
            "if_in_octets_oid": "1.3.6.1.2.1.2.2.1.10",
            "if_out_octets_oid": "1.3.6.1.2.1.2.2.1.16",
            "if_hc_in_octets_oid": "1.3.6.1.2.1.31.1.1.1.6",
            "if_hc_out_octets_oid": "1.3.6.1.2.1.31.1.1.1.10",
            "if_in_errors_oid": "1.3.6.1.2.1.2.2.1.14",
            "if_out_errors_oid": "1.3.6.1.2.1.2.2.1.20",
            "if_in_discards_oid": "1.3.6.1.2.1.2.2.1.13",
            "if_out_discards_oid": "1.3.6.1.2.1.2.2.1.19",
            "if_in_ucast_oid": "1.3.6.1.2.1.2.2.1.11",
            "if_out_ucast_oid": "1.3.6.1.2.1.2.2.1.17",
            "counter_mode": "auto",
        },
    },
    {
        "vendor": "Cisco",
        "model": "Catalyst 3850",
        "category": "Campus Switch",
        "description": "Cisco Catalyst 3850 Series Stackable Switch (IOS-XE)",
        "metric_definitions": {
            "cpu": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.9.9.109.1.1.1.1.8",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "memory": {
                "mode": "used_total_percent",
                "used_oid": "1.3.6.1.4.1.9.9.221.1.1.1.1.18",
                "total_oid": "1.3.6.1.4.1.9.9.221.1.1.1.1.17",
                "aggregation": "sum",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "temperature": {
                "mode": "direct_value",
                "oid": "1.3.6.1.4.1.9.9.13.1.3.1.3",
                "aggregation": "max",
                "unit": "°C",
                "scale": 1,
                "offset": 0,
            },
        },
        "interface_config": {
            "enabled": True,
            "if_name_oid": "1.3.6.1.2.1.31.1.1.1.1",
            "if_descr_oid": "1.3.6.1.2.1.2.2.1.2",
            "if_alias_oid": "1.3.6.1.2.1.31.1.1.1.18",
            "if_oper_status_oid": "1.3.6.1.2.1.2.2.1.8",
            "if_high_speed_oid": "1.3.6.1.2.1.31.1.1.1.15",
            "if_speed_oid": "1.3.6.1.2.1.2.2.1.5",
            "if_last_change_oid": "1.3.6.1.2.1.2.2.1.9",
            "if_in_octets_oid": "1.3.6.1.2.1.2.2.1.10",
            "if_out_octets_oid": "1.3.6.1.2.1.2.2.1.16",
            "if_hc_in_octets_oid": "1.3.6.1.2.1.31.1.1.1.6",
            "if_hc_out_octets_oid": "1.3.6.1.2.1.31.1.1.1.10",
            "if_in_errors_oid": "1.3.6.1.2.1.2.2.1.14",
            "if_out_errors_oid": "1.3.6.1.2.1.2.2.1.20",
            "if_in_discards_oid": "1.3.6.1.2.1.2.2.1.13",
            "if_out_discards_oid": "1.3.6.1.2.1.2.2.1.19",
            "if_in_ucast_oid": "1.3.6.1.2.1.2.2.1.11",
            "if_out_ucast_oid": "1.3.6.1.2.1.2.2.1.17",
            "counter_mode": "auto",
        },
    },
    {
        "vendor": "Cisco",
        "model": "Catalyst 2960",
        "category": "Campus Switch",
        "description": "Cisco Catalyst 2960 Series Layer 2 Switch (Classic IOS)",
        "metric_definitions": {
            "cpu": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.9.9.109.1.1.1.1.8",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "memory": {
                "mode": "used_free_percent",
                "used_oid": "1.3.6.1.4.1.9.9.48.1.1.1.5",
                "free_oid": "1.3.6.1.4.1.9.9.48.1.1.1.6",
                "aggregation": "sum",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "temperature": {
                "mode": "direct_value",
                "oid": "1.3.6.1.4.1.9.9.13.1.3.1.3",
                "aggregation": "max",
                "unit": "°C",
                "scale": 1,
                "offset": 0,
            },
        },
        "interface_config": {
            "enabled": True,
            "if_name_oid": "1.3.6.1.2.1.31.1.1.1.1",
            "if_descr_oid": "1.3.6.1.2.1.2.2.1.2",
            "if_alias_oid": "1.3.6.1.2.1.31.1.1.1.18",
            "if_oper_status_oid": "1.3.6.1.2.1.2.2.1.8",
            "if_high_speed_oid": "1.3.6.1.2.1.31.1.1.1.15",
            "if_speed_oid": "1.3.6.1.2.1.2.2.1.5",
            "if_last_change_oid": "1.3.6.1.2.1.2.2.1.9",
            "if_in_octets_oid": "1.3.6.1.2.1.2.2.1.10",
            "if_out_octets_oid": "1.3.6.1.2.1.2.2.1.16",
            "if_hc_in_octets_oid": "1.3.6.1.2.1.31.1.1.1.6",
            "if_hc_out_octets_oid": "1.3.6.1.2.1.31.1.1.1.10",
            "if_in_errors_oid": "1.3.6.1.2.1.2.2.1.14",
            "if_out_errors_oid": "1.3.6.1.2.1.2.2.1.20",
            "if_in_discards_oid": "1.3.6.1.2.1.2.2.1.13",
            "if_out_discards_oid": "1.3.6.1.2.1.2.2.1.19",
            "if_in_ucast_oid": "1.3.6.1.2.1.2.2.1.11",
            "if_out_ucast_oid": "1.3.6.1.2.1.2.2.1.17",
            "counter_mode": "auto",
        },
    },
    {
        "vendor": "Cisco",
        "model": "Nexus 9000",
        "category": "Data Center Switch",
        "description": "Cisco Nexus 9000 Series Data Center Switch (NX-OS)",
        "metric_definitions": {
            "cpu": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.9.9.109.1.1.1.1.8",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "memory": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.9.9.305.1.1.2.0",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "temperature": {
                "mode": "direct_value",
                "oid": "1.3.6.1.2.1.99.1.1.1.4",
                "aggregation": "max",
                "unit": "°C",
                "scale": 1,
                "offset": 0,
            },
        },
        "interface_config": {
            "enabled": True,
            "if_name_oid": "1.3.6.1.2.1.31.1.1.1.1",
            "if_descr_oid": "1.3.6.1.2.1.2.2.1.2",
            "if_alias_oid": "1.3.6.1.2.1.31.1.1.1.18",
            "if_oper_status_oid": "1.3.6.1.2.1.2.2.1.8",
            "if_high_speed_oid": "1.3.6.1.2.1.31.1.1.1.15",
            "if_speed_oid": "1.3.6.1.2.1.2.2.1.5",
            "if_last_change_oid": "1.3.6.1.2.1.2.2.1.9",
            "if_in_octets_oid": "1.3.6.1.2.1.2.2.1.10",
            "if_out_octets_oid": "1.3.6.1.2.1.2.2.1.16",
            "if_hc_in_octets_oid": "1.3.6.1.2.1.31.1.1.1.6",
            "if_hc_out_octets_oid": "1.3.6.1.2.1.31.1.1.1.10",
            "if_in_errors_oid": "1.3.6.1.2.1.2.2.1.14",
            "if_out_errors_oid": "1.3.6.1.2.1.2.2.1.20",
            "if_in_discards_oid": "1.3.6.1.2.1.2.2.1.13",
            "if_out_discards_oid": "1.3.6.1.2.1.2.2.1.19",
            "if_in_ucast_oid": "1.3.6.1.2.1.2.2.1.11",
            "if_out_ucast_oid": "1.3.6.1.2.1.2.2.1.17",
            "counter_mode": "64",
        },
    },

    # ── Huawei VRP (S5700 / S6700 / CE6800 / CE12800 / AR6100) ──
    {
        "vendor": "Huawei",
        "model": "S5700",
        "category": "Campus Switch",
        "description": "Huawei S5700 Series Gigabit Campus Switch (VRP)",
        "metric_definitions": {
            "cpu": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "memory": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "temperature": {
                "mode": "direct_value",
                "oid": "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.11",
                "aggregation": "max",
                "unit": "°C",
                "scale": 1,
                "offset": 0,
            },
            "fan": {
                "mode": "status_code",
                "oid": "1.3.6.1.4.1.2011.5.25.31.1.1.10.1.7",
                "status_ok_values": [1],
                "status_warning_values": [],
                "status_fail_values": [2],
                "aggregation": "first",
                "unit": "bool",
            },
        },
        "interface_config": {
            "enabled": True,
            "if_name_oid": "1.3.6.1.2.1.31.1.1.1.1",
            "if_descr_oid": "1.3.6.1.2.1.2.2.1.2",
            "if_alias_oid": "1.3.6.1.2.1.31.1.1.1.18",
            "if_oper_status_oid": "1.3.6.1.2.1.2.2.1.8",
            "if_high_speed_oid": "1.3.6.1.2.1.31.1.1.1.15",
            "if_speed_oid": "1.3.6.1.2.1.2.2.1.5",
            "if_last_change_oid": "1.3.6.1.2.1.2.2.1.9",
            "if_in_octets_oid": "1.3.6.1.2.1.2.2.1.10",
            "if_out_octets_oid": "1.3.6.1.2.1.2.2.1.16",
            "if_hc_in_octets_oid": "1.3.6.1.2.1.31.1.1.1.6",
            "if_hc_out_octets_oid": "1.3.6.1.2.1.31.1.1.1.10",
            "if_in_errors_oid": "1.3.6.1.2.1.2.2.1.14",
            "if_out_errors_oid": "1.3.6.1.2.1.2.2.1.20",
            "if_in_discards_oid": "1.3.6.1.2.1.2.2.1.13",
            "if_out_discards_oid": "1.3.6.1.2.1.2.2.1.19",
            "if_in_ucast_oid": "1.3.6.1.2.1.2.2.1.11",
            "if_out_ucast_oid": "1.3.6.1.2.1.2.2.1.17",
            "counter_mode": "auto",
        },
    },
    {
        "vendor": "Huawei",
        "model": "S6700",
        "category": "Campus Core Switch",
        "description": "Huawei S6700 10GE Core/Aggregation Campus Switch (VRP)",
        "metric_definitions": {
            "cpu": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "memory": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "temperature": {
                "mode": "direct_value",
                "oid": "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.11",
                "aggregation": "max",
                "unit": "°C",
                "scale": 1,
                "offset": 0,
            },
        },
        "interface_config": {
            "enabled": True,
            "if_name_oid": "1.3.6.1.2.1.31.1.1.1.1",
            "if_descr_oid": "1.3.6.1.2.1.2.2.1.2",
            "if_alias_oid": "1.3.6.1.2.1.31.1.1.1.18",
            "if_oper_status_oid": "1.3.6.1.2.1.2.2.1.8",
            "if_high_speed_oid": "1.3.6.1.2.1.31.1.1.1.15",
            "if_speed_oid": "1.3.6.1.2.1.2.2.1.5",
            "if_last_change_oid": "1.3.6.1.2.1.2.2.1.9",
            "if_in_octets_oid": "1.3.6.1.2.1.2.2.1.10",
            "if_out_octets_oid": "1.3.6.1.2.1.2.2.1.16",
            "if_hc_in_octets_oid": "1.3.6.1.2.1.31.1.1.1.6",
            "if_hc_out_octets_oid": "1.3.6.1.2.1.31.1.1.1.10",
            "if_in_errors_oid": "1.3.6.1.2.1.2.2.1.14",
            "if_out_errors_oid": "1.3.6.1.2.1.2.2.1.20",
            "if_in_discards_oid": "1.3.6.1.2.1.2.2.1.13",
            "if_out_discards_oid": "1.3.6.1.2.1.2.2.1.19",
            "if_in_ucast_oid": "1.3.6.1.2.1.2.2.1.11",
            "if_out_ucast_oid": "1.3.6.1.2.1.2.2.1.17",
            "counter_mode": "64",
        },
    },
    {
        "vendor": "Huawei",
        "model": "CE6800",
        "category": "Data Center Switch",
        "description": "Huawei CloudEngine 6800 Data Center Switch (VRP8)",
        "metric_definitions": {
            "cpu": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "memory": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "temperature": {
                "mode": "direct_value",
                "oid": "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.11",
                "aggregation": "max",
                "unit": "°C",
                "scale": 1,
                "offset": 0,
            },
        },
        "interface_config": {
            "enabled": True,
            "if_name_oid": "1.3.6.1.2.1.31.1.1.1.1",
            "if_descr_oid": "1.3.6.1.2.1.2.2.1.2",
            "if_alias_oid": "1.3.6.1.2.1.31.1.1.1.18",
            "if_oper_status_oid": "1.3.6.1.2.1.2.2.1.8",
            "if_high_speed_oid": "1.3.6.1.2.1.31.1.1.1.15",
            "if_speed_oid": "1.3.6.1.2.1.2.2.1.5",
            "if_last_change_oid": "1.3.6.1.2.1.2.2.1.9",
            "if_in_octets_oid": "1.3.6.1.2.1.2.2.1.10",
            "if_out_octets_oid": "1.3.6.1.2.1.2.2.1.16",
            "if_hc_in_octets_oid": "1.3.6.1.2.1.31.1.1.1.6",
            "if_hc_out_octets_oid": "1.3.6.1.2.1.31.1.1.1.10",
            "if_in_errors_oid": "1.3.6.1.2.1.2.2.1.14",
            "if_out_errors_oid": "1.3.6.1.2.1.2.2.1.20",
            "if_in_discards_oid": "1.3.6.1.2.1.2.2.1.13",
            "if_out_discards_oid": "1.3.6.1.2.1.2.2.1.19",
            "if_in_ucast_oid": "1.3.6.1.2.1.2.2.1.11",
            "if_out_ucast_oid": "1.3.6.1.2.1.2.2.1.17",
            "counter_mode": "64",
        },
    },

    # ── H3C Comware (S5500 / S6800 / S10500) ──
    {
        "vendor": "H3C",
        "model": "S5500",
        "category": "Campus Switch",
        "description": "H3C S5500 Series Gigabit Campus Switch (Comware V7)",
        "metric_definitions": {
            "cpu": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.25506.2.6.1.1.1.1.6",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "memory": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.25506.2.6.1.1.1.1.8",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "temperature": {
                "mode": "direct_value",
                "oid": "1.3.6.1.4.1.25506.2.6.1.1.1.1.12",
                "aggregation": "max",
                "unit": "°C",
                "scale": 1,
                "offset": 0,
            },
        },
        "interface_config": {
            "enabled": True,
            "if_name_oid": "1.3.6.1.2.1.31.1.1.1.1",
            "if_descr_oid": "1.3.6.1.2.1.2.2.1.2",
            "if_alias_oid": "1.3.6.1.2.1.31.1.1.1.18",
            "if_oper_status_oid": "1.3.6.1.2.1.2.2.1.8",
            "if_high_speed_oid": "1.3.6.1.2.1.31.1.1.1.15",
            "if_speed_oid": "1.3.6.1.2.1.2.2.1.5",
            "if_last_change_oid": "1.3.6.1.2.1.2.2.1.9",
            "if_in_octets_oid": "1.3.6.1.2.1.2.2.1.10",
            "if_out_octets_oid": "1.3.6.1.2.1.2.2.1.16",
            "if_hc_in_octets_oid": "1.3.6.1.2.1.31.1.1.1.6",
            "if_hc_out_octets_oid": "1.3.6.1.2.1.31.1.1.1.10",
            "if_in_errors_oid": "1.3.6.1.2.1.2.2.1.14",
            "if_out_errors_oid": "1.3.6.1.2.1.2.2.1.20",
            "if_in_discards_oid": "1.3.6.1.2.1.2.2.1.13",
            "if_out_discards_oid": "1.3.6.1.2.1.2.2.1.19",
            "if_in_ucast_oid": "1.3.6.1.2.1.2.2.1.11",
            "if_out_ucast_oid": "1.3.6.1.2.1.2.2.1.17",
            "counter_mode": "auto",
        },
    },
    {
        "vendor": "H3C",
        "model": "S6800",
        "category": "Data Center Switch",
        "description": "H3C S6800 10G/40G Data Center Switch (Comware V7)",
        "metric_definitions": {
            "cpu": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.25506.2.6.1.1.1.1.6",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "memory": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.25506.2.6.1.1.1.1.8",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "temperature": {
                "mode": "direct_value",
                "oid": "1.3.6.1.4.1.25506.2.6.1.1.1.1.12",
                "aggregation": "max",
                "unit": "°C",
                "scale": 1,
                "offset": 0,
            },
        },
        "interface_config": {
            "enabled": True,
            "if_name_oid": "1.3.6.1.2.1.31.1.1.1.1",
            "if_descr_oid": "1.3.6.1.2.1.2.2.1.2",
            "if_alias_oid": "1.3.6.1.2.1.31.1.1.1.18",
            "if_oper_status_oid": "1.3.6.1.2.1.2.2.1.8",
            "if_high_speed_oid": "1.3.6.1.2.1.31.1.1.1.15",
            "if_speed_oid": "1.3.6.1.2.1.2.2.1.5",
            "if_last_change_oid": "1.3.6.1.2.1.2.2.1.9",
            "if_in_octets_oid": "1.3.6.1.2.1.2.2.1.10",
            "if_out_octets_oid": "1.3.6.1.2.1.2.2.1.16",
            "if_hc_in_octets_oid": "1.3.6.1.2.1.31.1.1.1.6",
            "if_hc_out_octets_oid": "1.3.6.1.2.1.31.1.1.1.10",
            "if_in_errors_oid": "1.3.6.1.2.1.2.2.1.14",
            "if_out_errors_oid": "1.3.6.1.2.1.2.2.1.20",
            "if_in_discards_oid": "1.3.6.1.2.1.2.2.1.13",
            "if_out_discards_oid": "1.3.6.1.2.1.2.2.1.19",
            "if_in_ucast_oid": "1.3.6.1.2.1.2.2.1.11",
            "if_out_ucast_oid": "1.3.6.1.2.1.2.2.1.17",
            "counter_mode": "64",
        },
    },

    # ── Arista EOS ──
    {
        "vendor": "Arista",
        "model": "7050X",
        "category": "Data Center Switch",
        "description": "Arista 7050X Series 10G/40G Data Center Switch (EOS)",
        "metric_definitions": {
            "cpu": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.2.1.25.3.3.1.2",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "memory": {
                "mode": "used_total_percent",
                "used_oid": "1.3.6.1.2.1.25.2.3.1.6",
                "total_oid": "1.3.6.1.2.1.25.2.3.1.5",
                "aggregation": "sum",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "temperature": {
                "mode": "direct_value",
                "oid": "1.3.6.1.2.1.99.1.1.1.4",
                "aggregation": "max",
                "unit": "°C",
                "scale": 1,
                "offset": 0,
            },
        },
        "interface_config": {
            "enabled": True,
            "if_name_oid": "1.3.6.1.2.1.31.1.1.1.1",
            "if_descr_oid": "1.3.6.1.2.1.2.2.1.2",
            "if_alias_oid": "1.3.6.1.2.1.31.1.1.1.18",
            "if_oper_status_oid": "1.3.6.1.2.1.2.2.1.8",
            "if_high_speed_oid": "1.3.6.1.2.1.31.1.1.1.15",
            "if_speed_oid": "1.3.6.1.2.1.2.2.1.5",
            "if_last_change_oid": "1.3.6.1.2.1.2.2.1.9",
            "if_in_octets_oid": "1.3.6.1.2.1.2.2.1.10",
            "if_out_octets_oid": "1.3.6.1.2.1.2.2.1.16",
            "if_hc_in_octets_oid": "1.3.6.1.2.1.31.1.1.1.6",
            "if_hc_out_octets_oid": "1.3.6.1.2.1.31.1.1.1.10",
            "if_in_errors_oid": "1.3.6.1.2.1.2.2.1.14",
            "if_out_errors_oid": "1.3.6.1.2.1.2.2.1.20",
            "if_in_discards_oid": "1.3.6.1.2.1.2.2.1.13",
            "if_out_discards_oid": "1.3.6.1.2.1.2.2.1.19",
            "if_in_ucast_oid": "1.3.6.1.2.1.2.2.1.11",
            "if_out_ucast_oid": "1.3.6.1.2.1.2.2.1.17",
            "counter_mode": "64",
        },
    },

    # ── Ruijie (RG-S5750 / RG-S6220) ──
    {
        "vendor": "Ruijie",
        "model": "RG-S5750",
        "category": "Campus Switch",
        "description": "Ruijie RG-S5750 Series Gigabit Switch (RGOS)",
        "metric_definitions": {
            "cpu": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.4881.1.1.10.2.35.1.1.1.3",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "memory": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.4881.1.1.10.2.35.1.1.1.2",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "temperature": {
                "mode": "direct_value",
                "oid": "1.3.6.1.4.1.4881.1.1.10.2.35.1.1.1.4",
                "aggregation": "max",
                "unit": "°C",
                "scale": 1,
                "offset": 0,
            },
        },
        "interface_config": {
            "enabled": True,
            "if_name_oid": "1.3.6.1.2.1.31.1.1.1.1",
            "if_descr_oid": "1.3.6.1.2.1.2.2.1.2",
            "if_alias_oid": "1.3.6.1.2.1.31.1.1.1.18",
            "if_oper_status_oid": "1.3.6.1.2.1.2.2.1.8",
            "if_high_speed_oid": "1.3.6.1.2.1.31.1.1.1.15",
            "if_speed_oid": "1.3.6.1.2.1.2.2.1.5",
            "if_last_change_oid": "1.3.6.1.2.1.2.2.1.9",
            "if_in_octets_oid": "1.3.6.1.2.1.2.2.1.10",
            "if_out_octets_oid": "1.3.6.1.2.1.2.2.1.16",
            "if_hc_in_octets_oid": "1.3.6.1.2.1.31.1.1.1.6",
            "if_hc_out_octets_oid": "1.3.6.1.2.1.31.1.1.1.10",
            "if_in_errors_oid": "1.3.6.1.2.1.2.2.1.14",
            "if_out_errors_oid": "1.3.6.1.2.1.2.2.1.20",
            "if_in_discards_oid": "1.3.6.1.2.1.2.2.1.13",
            "if_out_discards_oid": "1.3.6.1.2.1.2.2.1.19",
            "if_in_ucast_oid": "1.3.6.1.2.1.2.2.1.11",
            "if_out_ucast_oid": "1.3.6.1.2.1.2.2.1.17",
            "counter_mode": "auto",
        },
    },

    # ── Juniper Junos (EX4300 / QFX5100 / MX240) ──
    {
        "vendor": "Juniper",
        "model": "EX4300",
        "category": "Campus Switch",
        "description": "Juniper EX4300 Series Campus Switch (Junos OS)",
        "metric_definitions": {
            "cpu": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.2636.3.1.13.1.8",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "memory": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.2636.3.1.13.1.11",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "temperature": {
                "mode": "direct_value",
                "oid": "1.3.6.1.4.1.2636.3.1.13.1.7",
                "aggregation": "max",
                "unit": "°C",
                "scale": 1,
                "offset": 0,
            },
        },
        "interface_config": {
            "enabled": True,
            "if_name_oid": "1.3.6.1.2.1.31.1.1.1.1",
            "if_descr_oid": "1.3.6.1.2.1.2.2.1.2",
            "if_alias_oid": "1.3.6.1.2.1.31.1.1.1.18",
            "if_oper_status_oid": "1.3.6.1.2.1.2.2.1.8",
            "if_high_speed_oid": "1.3.6.1.2.1.31.1.1.1.15",
            "if_speed_oid": "1.3.6.1.2.1.2.2.1.5",
            "if_last_change_oid": "1.3.6.1.2.1.2.2.1.9",
            "if_in_octets_oid": "1.3.6.1.2.1.2.2.1.10",
            "if_out_octets_oid": "1.3.6.1.2.1.2.2.1.16",
            "if_hc_in_octets_oid": "1.3.6.1.2.1.31.1.1.1.6",
            "if_hc_out_octets_oid": "1.3.6.1.2.1.31.1.1.1.10",
            "if_in_errors_oid": "1.3.6.1.2.1.2.2.1.14",
            "if_out_errors_oid": "1.3.6.1.2.1.2.2.1.20",
            "if_in_discards_oid": "1.3.6.1.2.1.2.2.1.13",
            "if_out_discards_oid": "1.3.6.1.2.1.2.2.1.19",
            "if_in_ucast_oid": "1.3.6.1.2.1.2.2.1.11",
            "if_out_ucast_oid": "1.3.6.1.2.1.2.2.1.17",
            "counter_mode": "auto",
        },
    },

    # ── Fortinet FortiGate ──
    {
        "vendor": "Fortinet",
        "model": "FortiGate-100F",
        "category": "Firewall / Gateway",
        "description": "Fortinet FortiGate 100F Next-Generation Firewall (FortiOS)",
        "metric_definitions": {
            "cpu": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.12356.101.4.1.3.0",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
            "memory": {
                "mode": "direct_percent",
                "oid": "1.3.6.1.4.1.12356.101.4.1.4.0",
                "aggregation": "average",
                "unit": "%",
                "scale": 1,
                "offset": 0,
            },
        },
        "interface_config": {
            "enabled": True,
            "if_name_oid": "1.3.6.1.2.1.31.1.1.1.1",
            "if_descr_oid": "1.3.6.1.2.1.2.2.1.2",
            "if_alias_oid": "1.3.6.1.2.1.31.1.1.1.18",
            "if_oper_status_oid": "1.3.6.1.2.1.2.2.1.8",
            "if_high_speed_oid": "1.3.6.1.2.1.31.1.1.1.15",
            "if_speed_oid": "1.3.6.1.2.1.2.2.1.5",
            "if_last_change_oid": "1.3.6.1.2.1.2.2.1.9",
            "if_in_octets_oid": "1.3.6.1.2.1.2.2.1.10",
            "if_out_octets_oid": "1.3.6.1.2.1.2.2.1.16",
            "if_hc_in_octets_oid": "1.3.6.1.2.1.31.1.1.1.6",
            "if_hc_out_octets_oid": "1.3.6.1.2.1.31.1.1.1.10",
            "if_in_errors_oid": "1.3.6.1.2.1.2.2.1.14",
            "if_out_errors_oid": "1.3.6.1.2.1.2.2.1.20",
            "if_in_discards_oid": "1.3.6.1.2.1.2.2.1.13",
            "if_out_discards_oid": "1.3.6.1.2.1.2.2.1.19",
            "if_in_ucast_oid": "1.3.6.1.2.1.2.2.1.11",
            "if_out_ucast_oid": "1.3.6.1.2.1.2.2.1.17",
            "counter_mode": "64",
        },
    },
]


def _derive_series_preset(
    *,
    base_vendor: str,
    base_model: str,
    model: str,
    category: str,
    description: str,
) -> dict[str, Any]:
    """Create a series-level preset while keeping metric definitions isolated.

    The domestic vendors expose the same core ENTITY/DEVICE MIB objects across
    many switch series.  Reusing a known-good vendor baseline keeps the catalog
    compact while ``deepcopy`` prevents later edits from mutating the source
    preset by reference.
    """
    base = next(
        item for item in OFFICIAL_MODEL_PRESETS
        if item["vendor"] == base_vendor and item["model"] == base_model
    )
    derived = deepcopy(base)
    derived.update({"model": model, "category": category, "description": description})
    return derived


# The catalog intentionally covers the common domestic switch series without
# turning every SKU into a separate template.  Exact device variants can still
# be refined from the MIB picker and SNMP WALK verification in the editor.
OFFICIAL_MODEL_PRESETS.extend([
    _derive_series_preset(
        base_vendor="Huawei",
        base_model="S5700",
        model="S5720",
        category="Campus Switch",
        description="Huawei S5720 Series Gigabit Campus Switch (VRP)",
    ),
    _derive_series_preset(
        base_vendor="Huawei",
        base_model="S5700",
        model="S5735",
        category="Campus Switch",
        description="Huawei S5735 Series Gigabit Campus Switch (VRP)",
    ),
    _derive_series_preset(
        base_vendor="H3C",
        base_model="S5500",
        model="S5130",
        category="Access Switch",
        description="H3C S5130 Series Gigabit Access Switch (Comware)",
    ),
    _derive_series_preset(
        base_vendor="H3C",
        base_model="S5500",
        model="S5560X",
        category="Aggregation Switch",
        description="H3C S5560X Series Aggregation Switch (Comware)",
    ),
    _derive_series_preset(
        base_vendor="H3C",
        base_model="S6800",
        model="S6520X",
        category="Aggregation/Core Switch",
        description="H3C S6520X Series 10GE Aggregation Switch (Comware)",
    ),
    _derive_series_preset(
        base_vendor="Ruijie",
        base_model="RG-S5750",
        model="RG-S2910",
        category="Access Switch",
        description="Ruijie RG-S2910 Series Access Switch (RGOS)",
    ),
    _derive_series_preset(
        base_vendor="Ruijie",
        base_model="RG-S5750",
        model="RG-S5300",
        category="Aggregation Switch",
        description="Ruijie RG-S5300 Series Aggregation Switch (RGOS)",
    ),
    _derive_series_preset(
        base_vendor="Ruijie",
        base_model="RG-S5750",
        model="RG-S6000",
        category="Aggregation/Core Switch",
        description="Ruijie RG-S6000 Series Aggregation Switch (RGOS)",
    ),
    _derive_series_preset(
        base_vendor="Ruijie",
        base_model="RG-S5750",
        model="RG-S6220",
        category="Data Center Switch",
        description="Ruijie RG-S6220 Series Data Center Switch (RGOS)",
    ),
])


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
    """Auto-match and assemble recommended SNMP metric definitions based on asset vendor and model."""
    v_clean = vendor.strip().lower()
    m_clean = model.strip().lower()

    if not v_clean and not m_clean:
        return None

    # 1. Exact model match from pre-built catalog
    for preset in OFFICIAL_MODEL_PRESETS:
        p_vendor = preset["vendor"].strip().lower()
        p_model = preset["model"].strip().lower()
        if (not v_clean or p_vendor == v_clean) and p_model == m_clean:
            return {
                "match_type": "exact",
                "confidence": 1.0,
                "preset": preset,
            }

    # 2. Heuristic series / prefix matching rules
    # Cisco rules
    if "cisco" in v_clean or any(kw in m_clean for kw in ["c9300", "c3850", "ws-c2960", "nexus"]):
        if any(x in m_clean for x in ["9300", "9200", "9400", "9500", "c93", "c92"]):
            target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "Catalyst 9300"), None)
            if target:
                return {"match_type": "series_inferred", "confidence": 0.95, "matched_series": "Catalyst 9000 (IOS-XE)", "preset": target}
        if any(x in m_clean for x in ["3850", "3650", "c38", "c36"]):
            target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "Catalyst 3850"), None)
            if target:
                return {"match_type": "series_inferred", "confidence": 0.95, "matched_series": "Catalyst 3850 (IOS-XE)", "preset": target}
        if any(x in m_clean for x in ["2960", "3750", "3560", "2950", "c29"]):
            target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "Catalyst 2960"), None)
            if target:
                return {"match_type": "series_inferred", "confidence": 0.90, "matched_series": "Catalyst 2960/3750 (Classic IOS)", "preset": target}
        if any(x in m_clean for x in ["nexus", "n9k", "n7k", "n5k", "n3k", "9000", "9300-gx"]):
            target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "Nexus 9000"), None)
            if target:
                return {"match_type": "series_inferred", "confidence": 0.95, "matched_series": "Nexus (NX-OS)", "preset": target}
        # Fallback Cisco default (IOS-XE Catalyst 9300 profile)
        fallback = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "Catalyst 9300"), None)
        if fallback:
            return {"match_type": "vendor_default", "confidence": 0.85, "matched_series": "Cisco Standard (IOS-XE)", "preset": fallback}

    # Huawei rules
    if "huawei" in v_clean or any(kw in m_clean for kw in ["s57", "s67", "ce68", "ce128"]):
        if any(x in m_clean for x in ["ce68", "ce128", "ce88", "ce58", "cloudengine"]):
            target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "CE6800"), None)
            if target:
                return {"match_type": "series_inferred", "confidence": 0.95, "matched_series": "Huawei CloudEngine Series", "preset": target}
        if "s5735" in m_clean:
            target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "S5735"), None)
            if target:
                return {"match_type": "series_inferred", "confidence": 0.95, "matched_series": "Huawei S5735 Campus Series", "preset": target}
        if "s5720" in m_clean:
            target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "S5720"), None)
            if target:
                return {"match_type": "series_inferred", "confidence": 0.95, "matched_series": "Huawei S5720 Campus Series", "preset": target}
        if any(x in m_clean for x in ["s67", "s127", "s77", "s97", "6700", "6720", "6730"]):
            target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "S6700"), None)
            if target:
                return {"match_type": "series_inferred", "confidence": 0.95, "matched_series": "Huawei S6700 Core Series", "preset": target}
        # Default Huawei S5700 series
        target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "S5700"), None)
        if target:
            return {"match_type": "vendor_default", "confidence": 0.90, "matched_series": "Huawei S5700/Campus Series", "preset": target}

    # H3C rules
    if "h3c" in v_clean or any(kw in m_clean for kw in ["s55", "s68", "s5130", "s5560", "s6520", "s10500"]):
        if any(x in m_clean for x in ["s68", "s105", "s125", "6800", "10500"]):
            target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "S6800"), None)
            if target:
                return {"match_type": "series_inferred", "confidence": 0.95, "matched_series": "H3C S6800 Data Center Series", "preset": target}
        if "s6520" in m_clean:
            target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "S6520X"), None)
            if target:
                return {"match_type": "series_inferred", "confidence": 0.95, "matched_series": "H3C S6520X Aggregation Series", "preset": target}
        if "s5560" in m_clean:
            target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "S5560X"), None)
            if target:
                return {"match_type": "series_inferred", "confidence": 0.95, "matched_series": "H3C S5560X Aggregation Series", "preset": target}
        if "s5130" in m_clean:
            target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "S5130"), None)
            if target:
                return {"match_type": "series_inferred", "confidence": 0.95, "matched_series": "H3C S5130 Access Series", "preset": target}
        target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "S5500"), None)
        if target:
            return {"match_type": "vendor_default", "confidence": 0.90, "matched_series": "H3C S5500/Campus Series", "preset": target}

    # Arista rules
    if "arista" in v_clean or any(kw in m_clean for kw in ["7050", "7280", "7060", "dcs-"]):
        target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "7050X"), None)
        if target:
            return {"match_type": "vendor_default", "confidence": 0.95, "matched_series": "Arista 7050X EOS Series", "preset": target}

    # Ruijie rules
    if "ruijie" in v_clean or any(kw in m_clean for kw in ["s5750", "s6220", "rg-s"]):
        for marker, target_model, series_name in (
            ("s2910", "RG-S2910", "Ruijie RG-S2910 Access Series"),
            ("s5300", "RG-S5300", "Ruijie RG-S5300 Aggregation Series"),
            ("s6000", "RG-S6000", "Ruijie RG-S6000 Aggregation Series"),
            ("s6220", "RG-S6220", "Ruijie RG-S6220 Data Center Series"),
            ("s5750", "RG-S5750", "Ruijie RG-S5750 Campus Series"),
        ):
            if marker in m_clean:
                target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == target_model), None)
                if target:
                    return {"match_type": "series_inferred", "confidence": 0.95, "matched_series": series_name, "preset": target}
        target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "RG-S5750"), None)
        if target:
            return {"match_type": "vendor_default", "confidence": 0.90, "matched_series": "Ruijie RGOS Series", "preset": target}

    # Juniper rules
    if "juniper" in v_clean or any(kw in m_clean for kw in ["ex43", "qfx", "mx240", "ex2"]):
        target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "EX4300"), None)
        if target:
            return {"match_type": "vendor_default", "confidence": 0.90, "matched_series": "Juniper Junos Series", "preset": target}

    # Fortinet rules
    if "fortinet" in v_clean or any(kw in m_clean for kw in ["fortigate", "fg-", "100f", "200f", "60f"]):
        target = next((p for p in OFFICIAL_MODEL_PRESETS if p["model"] == "FortiGate-100F"), None)
        if target:
            return {"match_type": "vendor_default", "confidence": 0.90, "matched_series": "Fortinet FortiOS Series", "preset": target}

    return None
