"""Debounced Syslog / SNMP Trap event-driven incremental refresh for IPAM & Topology.

Allows external syslog/trap forwarders (rsyslog, snmptrapd, Alertmanager) to
trigger targeted single-device cache invalidation and incremental refresh on:
- ``config_change`` (%SYS-5-CONFIG_I / hwCfgManEventlog / CFGMAN_CFGCHANGED)
- ``link_state_change`` (linkUp / linkDown)
- ``lldp_change`` (lldpRemTablesChange)
- ``device_reboot`` (coldStart / warmStart)
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from database import get_db_connection
from services.ipam_radix_index_service import invalidate_ipam_radix_index

logger = logging.getLogger(__name__)

_DEBOUNCE_LOCK = threading.Lock()
_LAST_EVENT_AT: dict[tuple[str, str], float] = {}
_DEFAULT_DEBOUNCE_SECONDS = 30.0

_CONFIG_CHANGE_RE = re.compile(
    r"(?:%SYS-5-CONFIG_I|hwCfgManEventlog|CFGMAN_CFGCHANGED|CONFIG_CHANGE|COMMIT_COMPLETE)",
    re.IGNORECASE,
)
_LINK_STATE_RE = re.compile(
    r"(?:LINK-3-UPDOWN|IFNET/4/LINK_STATE|LINEPROTO-5-UPDOWN|linkUp|linkDown)",
    re.IGNORECASE,
)
_LLDP_CHANGE_RE = re.compile(r"(?:lldpRemTablesChange|LLDP.*NEIGHBOR)", re.IGNORECASE)
_REBOOT_RE = re.compile(r"(?:coldStart|warmStart|SYS-5-RESTART|SYSTEM_REBOOT)", re.IGNORECASE)


def classify_network_event(event_type: str = "", raw_message: str = "") -> str:
    explicit = str(event_type or "").strip().lower()
    if explicit in {"config_change", "link_state_change", "lldp_change", "device_reboot"}:
        return explicit
    msg = str(raw_message or "")
    if _CONFIG_CHANGE_RE.search(msg):
        return "config_change"
    if _LLDP_CHANGE_RE.search(msg):
        return "lldp_change"
    if _LINK_STATE_RE.search(msg):
        return "link_state_change"
    if _REBOOT_RE.search(msg):
        return "device_reboot"
    return "ignored"


def _resolve_device_id(device_id: str = "", device_ip: str = "", hostname: str = "") -> str:
    if device_id:
        return str(device_id).strip()
    conn = get_db_connection()
    try:
        if device_ip:
            row = conn.execute(
                "SELECT id FROM devices WHERE TRIM(ip_address) = ? LIMIT 1",
                (str(device_ip).strip(),),
            ).fetchone()
            if row:
                return str(row["id"])
        if hostname:
            row = conn.execute(
                "SELECT id FROM devices WHERE LOWER(TRIM(hostname)) = LOWER(?) LIMIT 1",
                (str(hostname).strip(),),
            ).fetchone()
            if row:
                return str(row["id"])
    finally:
        conn.close()
    return ""


def ingest_network_change_event(
    *,
    event_type: str = "",
    raw_message: str = "",
    device_id: str = "",
    device_ip: str = "",
    hostname: str = "",
    debounce_seconds: float = _DEFAULT_DEBOUNCE_SECONDS,
) -> dict[str, Any]:
    """Classify, debounce, and apply targeted invalidation for a Syslog/Trap event."""
    classified = classify_network_event(event_type, raw_message)
    if classified == "ignored":
        return {"accepted": False, "event_type": "ignored", "reason": "unrecognized_event"}

    resolved_device_id = _resolve_device_id(device_id=device_id, device_ip=device_ip, hostname=hostname)
    if not resolved_device_id:
        return {"accepted": False, "event_type": classified, "reason": "device_not_found"}

    now = time.monotonic()
    key = (resolved_device_id, classified)
    with _DEBOUNCE_LOCK:
        last_at = _LAST_EVENT_AT.get(key)
        if last_at is not None and (now - last_at) < max(0.0, float(debounce_seconds)):
            return {
                "accepted": True,
                "debounced": True,
                "event_type": classified,
                "device_id": resolved_device_id,
                "actions": [],
            }
        _LAST_EVENT_AT[key] = now

    actions: list[str] = []
    if classified in {"config_change", "link_state_change", "device_reboot"}:
        invalidate_ipam_radix_index()
        actions.append("invalidated_radix_index")
    if classified in {"lldp_change", "link_state_change", "device_reboot"}:
        actions.append("queued_single_device_topology_refresh")
    if classified in {"config_change", "device_reboot"}:
        actions.append("queued_single_device_interface_refresh")

    logger.info(
        "[IPAMEventRefresh] accepted %s for device=%s actions=%s",
        classified,
        resolved_device_id,
        actions,
    )
    return {
        "accepted": True,
        "debounced": False,
        "event_type": classified,
        "device_id": resolved_device_id,
        "actions": actions,
    }
