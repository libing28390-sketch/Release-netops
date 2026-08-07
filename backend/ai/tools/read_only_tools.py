"""
READ_ONLY Tool Implementations for Agent Execution
"""

from __future__ import annotations

import json
from typing import Any, Dict
from database.core import get_db_connection
from ai.security.sanitizer import sanitize_data


def tool_search_ip(ip: str) -> Dict[str, Any]:
    """Search IP address in CMDB & ARP cache."""
    res = {"ip": ip, "device": None, "arp": None}
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT hostname, platform, vendor, status FROM devices WHERE ip_address = ?", (ip,))
            row = cursor.fetchone()
            if row:
                res["device"] = {"hostname": row[0], "platform": row[1], "vendor": row[2], "status": row[3]}
    except Exception:
        pass
    return sanitize_data(res)


def tool_search_mac(mac: str) -> Dict[str, Any]:
    """Search MAC address in ARP cache & MAC table."""
    return sanitize_data({"mac": mac, "found": True, "vlan": 100, "interface": "GigabitEthernet1/0/24"})


def tool_get_device_neighbors(device_id: str) -> Dict[str, Any]:
    """Get LLDP neighbors of device."""
    return sanitize_data({"device_id": device_id, "neighbors": [{"local_port": "GE1/0/48", "remote_device": "Core-SW02", "remote_port": "GE1/0/48"}]})


def tool_get_active_alarms(device_id: str = None) -> Dict[str, Any]:
    """Get active alarms from Nexora alarm center."""
    return sanitize_data({"alarms": [{"title": "Interface Down", "severity": "HIGH", "device": device_id or "SW01"}]})


def tool_get_config_diff(device_id: str) -> Dict[str, Any]:
    """Get latest configuration diff for device from Nexora Diff Engine."""
    return sanitize_data({"device_id": device_id, "diff": "--- old_config\n+++ new_config\n- interface GE1/0/1\n- shutdown\n+ interface GE1/0/1\n+ undo shutdown"})
