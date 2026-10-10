from __future__ import annotations

import re
from importlib.util import find_spec
from collections.abc import Iterable
from typing import Any

from core.interface_utils import normalize_interface_name
from core.textfsm import parse_with_textfsm, resolve_textfsm_platform
from domain.models import Neighbor


_EMPTY_IP_VALUES = {"", "--", "-", "*", "unassigned", "unset", "unknown", "no", "no address"}


def textfsm_records(platforms: str | Iterable[str], command: str, output: str) -> list[dict[str, Any]]:
    if find_spec("textfsm") is None:
        return []
    candidates = (platforms,) if isinstance(platforms, str) else tuple(platforms)
    for platform in candidates:
        records = parse_with_textfsm(
            platform=resolve_textfsm_platform(platform) or platform,
            command=command,
            output=output,
        )
        if records:
            return [{str(key).lower(): value for key, value in record.items()} for record in records]
    return []


def record_value(record: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = record.get(key.lower())
        if isinstance(value, list):
            value = value[0] if value else ""
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def first_match(text: str, *patterns: str, flags: int = re.IGNORECASE | re.MULTILINE) -> str:
    for pattern in patterns:
        match = re.search(pattern, text or "", flags)
        if match:
            return next((group.strip() for group in match.groups() if group is not None), "")
    return ""


def status_value(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return "up" if normalized in {"up", "enabled", "connected", "ready", "up(s)"} else "down"


def clean_ip(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if normalized.lower() in _EMPTY_IP_VALUES or normalized.lower().startswith("no address"):
        return None
    return normalized.split("/")[0]


def parse_speed_bps(value: str | None) -> int | None:
    text = str(value or "").strip()
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([GMK]?)\s*(?:b(?:it)?/?s|bps)?", text, re.IGNORECASE)
    if not match:
        return None
    number = float(match.group(1))
    multiplier = {"g": 1_000_000_000, "m": 1_000_000, "k": 1_000}.get(match.group(2).lower(), 1)
    return int(number * multiplier)


def interface_type(name: str) -> str:
    normalized = str(name or "").strip().lower().replace(" ", "")
    if normalized.startswith(("loopback", "lo", "lo0")):
        return "loopback"
    if normalized.startswith(("vlanif", "vlan-interface", "vlan", "irb")):
        return "svi"
    if normalized.startswith(("tunnel", "gr-", "ip-")):
        return "tunnel"
    if normalized.startswith((
        "port-channel", "portchannel", "bridge-aggregation", "route-aggregation",
        "eth-trunk", "ae",
    )):
        return "port_channel"
    if "." in normalized:
        return "sub_interface"
    return "physical"


def neighbor_from_record(device_id: str, record: dict[str, Any]) -> Neighbor | None:
    local = record_value(record, "local_interface", "local_port", "local_intf", "interface")
    remote_port = record_value(
        record, "neighbor_interface", "neighbor_port_id", "remote_port", "port_id", "remote_interface"
    )
    remote_device = record_value(
        record, "neighbor_name", "neighbor_device", "system_name", "remote_system_name", "device_id", "chassis_id"
    )
    if not local or not remote_port or not remote_device:
        return None
    return Neighbor(
        device_id=device_id,
        local_interface=normalize_interface_name(local),
        remote_device=remote_device,
        remote_interface=normalize_interface_name(remote_port),
        platform=record_value(record, "platform", "system_description") or None,
        capabilities=record_value(record, "capabilities", "system_capabilities") or None,
    )


def regex_lldp_neighbors(device_id: str, output: str) -> list[Neighbor]:
    """Parse common detailed LLDP layouts without applying another vendor's rules."""
    blocks = re.split(
        r"(?=LLDP\s+Neighbor\s+Information)|(?=LLDP neighbor-information of port)|"
        r"(?=Local\s+Int(?:f|erface)\s*:)|(?=Interface\s+\S+\s+detected\s+\d+\s+LLDP)|-{20,}",
        output or "",
        flags=re.IGNORECASE,
    )
    neighbors: list[Neighbor] = []
    seen: set[tuple[str, str, str]] = set()
    for block in blocks:
        local = first_match(
            block,
            r"Local\s+Int(?:f|erface)\s*:\s*([^\r\n]+)",
            r"LLDP neighbor-information of port\s+(?:\d+\[)?([^\]:\r\n]+)",
            r"Interface\s+(\S+)\s+detected\s+\d+\s+LLDP",
        )
        remote_device = first_match(
            block,
            r"System\s+Name\s*:\s*([^\r\n]+)",
            r"System\s+name\s*:\s*([^\r\n]+)",
            r"Device\s+ID\s*:\s*([^\r\n]+)",
            r"Chassis\s+ID\s*:\s*([^\r\n]+)",
        )
        remote_port = first_match(
            block,
            r"Port\s+ID\s*:\s*([^\r\n]+)",
            r"Port\s+id\s*:\s*([^\r\n]+)",
            r"Port\s+Description\s*:\s*([^\r\n]+)",
        )
        capabilities = first_match(block, r"System\s+Capabilities[^:]*:\s*([^\r\n]+)")
        if not local or not remote_device or not remote_port:
            continue
        local = re.sub(r"^\d+\[|\]$", "", local).strip()
        remote_device = re.sub(r"\s*\([^)]*\)\s*$", "", remote_device).strip()
        remote_port = re.sub(r"\s*\([^)]*\)\s*$", "", remote_port).strip()
        key = (normalize_interface_name(local), remote_device.lower(), normalize_interface_name(remote_port))
        if key in seen:
            continue
        seen.add(key)
        neighbors.append(
            Neighbor(
                device_id=device_id,
                local_interface=key[0],
                remote_device=remote_device,
                remote_interface=key[2],
                capabilities=capabilities or None,
            )
        )
    return neighbors
