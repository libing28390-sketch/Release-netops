"""Multi-vendor L3 interface configuration block parser.

Parses lightweight ``interface`` configuration sections (typically 30-100 KB per
device) from Huawei VRP/CE, H3C Comware, Cisco IOS/IOS-XE/NX-OS, and Arista EOS
to capture facts routinely missed by ``brief`` commands and SNMP ``ipAddressTable``:
- Primary + ALL ``sub`` / ``secondary`` IPv4/IPv6 addresses with exact masks
- Explicit VRF / ``vpn-instance`` bindings
- VRRP / HSRP / VARP virtual gateway IPs (VIPs)
- Subinterface real 802.1Q encapsulation VLAN ID (``encap_vlan_id``)
- Administratively ``shutdown`` interface IPs (preserved for fault lookup)
- Dynamic (``dhcp`` / ``ppp-negotiate``) and ``ip unnumbered`` markers
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from core.interface_utils import normalize_interface_name

_IF_HEADER_RE = re.compile(r"^interface\s+(.+?)\s*$", re.IGNORECASE)
_VRF_RE = re.compile(
    r"^(?:ip\s+binding\s+vpn-instance|ip\s+vrf\s+forwarding|vrf\s+forwarding|vrf\s+member)\s+(\S+)",
    re.IGNORECASE,
)
_ENCAP_VLAN_RE = re.compile(
    r"^(?:dot1q\s+termination\s+vid|vlan-type\s+dot1q\s+vid|encapsulation\s+dot1q)\s+(\d+)",
    re.IGNORECASE,
)
_DESC_RE = re.compile(r"^description\s+(.+?)\s*$", re.IGNORECASE)
_IPV4_CIDR_OR_MASK_RE = re.compile(
    r"^ip\s+address\s+(\d{1,3}(?:\.\d{1,3}){3})(?:/(\d{1,2})|\s+(\d{1,3}(?:\.\d{1,3}){3}|\d{1,2}))(?:\s+(sub|secondary))?\b",
    re.IGNORECASE,
)
_IPV6_ADDR_RE = re.compile(
    r"^ipv6\s+address\s+([0-9a-fA-F:]+)(?:/(\d{1,3})|\s+(\d{1,3}))(?:\s+(sub|secondary))?\b",
    re.IGNORECASE,
)
_DYNAMIC_IP_RE = re.compile(
    r"^ip\s+address\s+(dhcp(?:-alloc)?|ppp-negotiate|negotiate)\b",
    re.IGNORECASE,
)
_UNNUMBERED_RE = re.compile(
    r"^ip\s+address\s+unnumbered\s+interface\s+(\S+)|^ip\s+unnumbered\s+(\S+)",
    re.IGNORECASE,
)
_HUAWEI_H3C_VRRP_RE = re.compile(
    r"^vrrp\s+vrid\s+(\d+)\s+virtual-ip\s+([0-9a-fA-F:.]+)",
    re.IGNORECASE,
)
_CISCO_HSRP_RE = re.compile(
    r"^standby\s+(\d+)\s+ip\s+([0-9a-fA-F:.]+)(?:\s+(secondary))?",
    re.IGNORECASE,
)
_CISCO_VRRP_RE = re.compile(
    r"^vrrp\s+(\d+)\s+ip\s+([0-9a-fA-F:.]+)(?:\s+(secondary))?",
    re.IGNORECASE,
)
_ANYCAST_VARP_RE = re.compile(
    r"^ip\s+virtual-router\s+address\s+([0-9a-fA-F:.]+)",
    re.IGNORECASE,
)
_SHUTDOWN_RE = re.compile(r"^shutdown\s*$", re.IGNORECASE)
_NO_SHUTDOWN_RE = re.compile(r"^(?:no|undo)\s+shutdown\s*$", re.IGNORECASE)


def _prefix_len_from_token(token: str, version: int) -> int | None:
    text = str(token or "").strip().lstrip("/")
    if not text:
        return None
    try:
        if "." in text and version == 4:
            return ipaddress.IPv4Network(f"0.0.0.0/{text}").prefixlen
        val = int(text)
    except ValueError:
        return None
    max_bits = 32 if version == 4 else 128
    return val if 0 <= val <= max_bits else None


def parse_interface_config_blocks(raw_config: str) -> dict[str, Any]:
    """Parse multi-vendor interface config blocks into structured interfaces, addresses, and VIPs."""
    interfaces: list[dict[str, Any]] = []
    all_addresses: list[dict[str, Any]] = []
    all_vips: list[dict[str, Any]] = []

    current: dict[str, Any] | None = None

    def _flush() -> None:
        nonlocal current
        if current is None:
            return
        vrf = current["vrf_name"]
        for addr in current["addresses"]:
            addr["vrf_name"] = vrf
            addr["context_type"] = "vrf" if vrf != "default" else "global"
            addr["local_context_key"] = vrf if vrf != "default" else "--"
            addr["is_admin_down"] = current["is_admin_down"]
            all_addresses.append(addr)
        for vip in current["vips"]:
            vip["vrf_name"] = vrf
            all_vips.append(vip)
        interfaces.append(current)
        current = None

    for raw_line in str(raw_config or "").splitlines():
        if not raw_line.strip():
            continue
        # Block delimiters (# or !) end the current interface section
        stripped = raw_line.strip()
        if stripped in {"#", "!"}:
            _flush()
            continue

        # Top-level interface header (unindented)
        if not raw_line[0].isspace():
            header_match = _IF_HEADER_RE.match(stripped)
            if header_match:
                _flush()
                if_name = header_match.group(1).strip()
                current = {
                    "interface_name": if_name,
                    "normalized_interface_name": normalize_interface_name(if_name).lower(),
                    "vrf_name": "default",
                    "encap_vlan_id": None,
                    "description": "",
                    "is_admin_down": False,
                    "dynamic_mode": "",
                    "unnumbered_ref": "",
                    "addresses": [],
                    "vips": [],
                }
            else:
                # Another top-level stanza started
                _flush()
            continue

        if current is None:
            continue

        # Inside an interface block
        if _SHUTDOWN_RE.match(stripped):
            current["is_admin_down"] = True
            continue
        if _NO_SHUTDOWN_RE.match(stripped):
            current["is_admin_down"] = False
            continue

        m = _DESC_RE.match(stripped)
        if m:
            current["description"] = m.group(1).strip()
            continue

        m = _VRF_RE.match(stripped)
        if m:
            current["vrf_name"] = m.group(1).strip()
            continue

        m = _ENCAP_VLAN_RE.match(stripped)
        if m:
            vid = int(m.group(1))
            if 1 <= vid <= 4094:
                current["encap_vlan_id"] = vid
            continue

        m = _IPV4_CIDR_OR_MASK_RE.match(stripped)
        if m:
            ip_raw = m.group(1)
            mask_token = m.group(2) or m.group(3) or ""
            is_sec = bool(m.group(4))
            try:
                norm_ip = str(ipaddress.IPv4Address(ip_raw))
            except ValueError:
                continue
            plen = _prefix_len_from_token(mask_token, 4)
            if plen is not None:
                current["addresses"].append({
                    "interface": current["interface_name"],
                    "ip_address": norm_ip,
                    "prefix_length": plen,
                    "ip_version": 4,
                    "is_secondary": is_sec,
                    "source": "config_block",
                })
            continue

        m = _IPV6_ADDR_RE.match(stripped)
        if m:
            ip_raw = m.group(1)
            mask_token = m.group(2) or m.group(3) or ""
            is_sec = bool(m.group(4))
            try:
                norm_ip = str(ipaddress.IPv6Address(ip_raw))
            except ValueError:
                continue
            plen = _prefix_len_from_token(mask_token, 6)
            if plen is not None:
                current["addresses"].append({
                    "interface": current["interface_name"],
                    "ip_address": norm_ip,
                    "prefix_length": plen,
                    "ip_version": 6,
                    "is_secondary": is_sec,
                    "source": "config_block",
                })
            continue

        m = _DYNAMIC_IP_RE.match(stripped)
        if m:
            current["dynamic_mode"] = m.group(1).lower()
            continue

        m = _UNNUMBERED_RE.match(stripped)
        if m:
            current["unnumbered_ref"] = (m.group(1) or m.group(2) or "").strip()
            continue

        for pattern, proto in (
            (_HUAWEI_H3C_VRRP_RE, "vrrp"),
            (_CISCO_HSRP_RE, "hsrp"),
            (_CISCO_VRRP_RE, "vrrp"),
        ):
            m = pattern.match(stripped)
            if m:
                try:
                    vip_ip = str(ipaddress.ip_address(m.group(2).strip()))
                except ValueError:
                    break
                current["vips"].append({
                    "protocol": proto,
                    "group_id": int(m.group(1)),
                    "virtual_ip": vip_ip,
                    "interface_name": current["interface_name"],
                })
                break
        else:
            m = _ANYCAST_VARP_RE.match(stripped)
            if m:
                try:
                    vip_ip = str(ipaddress.ip_address(m.group(1).strip()))
                except ValueError:
                    continue
                current["vips"].append({
                    "protocol": "anycast_varp",
                    "group_id": 0,
                    "virtual_ip": vip_ip,
                    "interface_name": current["interface_name"],
                })

    _flush()
    return {
        "interfaces": interfaces,
        "addresses": all_addresses,
        "vips": all_vips,
    }


def interface_config_command_for_platform(platform: str) -> str | None:
    """Return the read-only interface config-block CLI command for a normalized platform."""
    p = str(platform or "").strip().lower()
    if p.startswith(("huawei", "h3c", "hp_comware")):
        return "display current-configuration interface"
    if p in {"cisco_nxos", "nxos"}:
        return "show running-config interface"
    if p.startswith(("cisco_ios", "ios", "arista", "ruijie")):
        return "show running-config | section ^interface"
    return None
