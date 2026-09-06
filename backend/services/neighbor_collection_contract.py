"""Shared LLDP-only contract for network-neighbor collection."""

from __future__ import annotations

import re
from typing import Any


LLDP_COLLECTION_STATUSES = frozenset({
    "success", "no_neighbors", "lldp_disabled", "command_failed",
    "parse_failed", "unsupported_platform", "timeout",
})
LLDP_SCENARIOS = frozenset({"neighbor_lldp", "topology_lldp", "lldp_neighbors"})

_PLATFORM_ALIASES = {
    "cisco": "cisco_ios", "ios": "cisco_ios", "iosxe": "cisco_ios",
    "cisco_xe": "cisco_ios", "cisco_iosxe": "cisco_ios",
    "nxos": "cisco_nxos", "nexus": "cisco_nxos",
    "junos": "juniper_junos", "juniper": "juniper_junos",
    "arista": "arista_eos", "eos": "arista_eos",
    "huawei": "huawei_vrp", "huawei_vrpv8": "huawei_vrp", "vrp": "huawei_vrp", "ce": "huawei_vrp",
    "h3c": "h3c_comware", "comware": "h3c_comware",
    "ruijie": "ruijie_rgos", "ruijie_os": "ruijie_rgos", "rgos": "ruijie_rgos",
    "zte": "zte_zxros", "zxros": "zte_zxros",
    "dptech": "dptech_ios", "dptech_ios": "dptech_ios", "dptech_conplat": "dptech_ios", "dptech_conplat_fw": "dptech_ios",
    "maipu": "maipu", "maipu_mypower": "maipu", "maipu_network": "maipu",
}

# Approved commands for the existing validated Automation Playbook/TextFSM
# scenarios. Additions require a matching vendor fixture/template.
LLDP_COMMAND_WHITELIST: dict[str, frozenset[str]] = {
    "cisco_ios": frozenset({"show lldp neighbors", "show lldp neighbors detail"}),
    "cisco_nxos": frozenset({"show lldp neighbors", "show lldp neighbors detail"}),
    "juniper_junos": frozenset({"show lldp neighbors", "show lldp neighbors detail"}),
    "arista_eos": frozenset({"show lldp neighbors", "show lldp neighbors detail"}),
    "huawei_vrp": frozenset({"display lldp neighbor", "display lldp neighbor brief", "display lldp neighbor verbose"}),
    "h3c_comware": frozenset({"display lldp neighbor", "display lldp neighbor-information list", "display lldp neighbor-information verbose"}),
    "ruijie_rgos": frozenset({"show lldp neighbors", "show lldp neighbors detail"}),
    "zte_zxros": frozenset({"show lldp neighbor", "show lldp neighbors", "show lldp neighbors detail"}),
    "dptech_ios": frozenset({"show lldp neighbors", "show lldp neighbors detail"}),
    "maipu": frozenset({"show lldp neighbors", "show lldp neighbors detail"}),
}


class NeighborCollectionContractError(ValueError):
    """Raised before a neighbor command is sent when policy is violated."""


def normalize_neighbor_platform(platform: str | None) -> str:
    raw = str(platform or "").strip().lower()
    return _PLATFORM_ALIASES.get(raw, raw)


def assert_lldp_command(platform: str | None, command: str, *, scenario_id: str | None = None) -> str:
    """Validate and return a normalized LLDP command before transport send."""
    normalized_platform = normalize_neighbor_platform(platform)
    normalized_command = re.sub(r"\s+", " ", str(command or "").strip().lower())
    if scenario_id and scenario_id not in LLDP_SCENARIOS:
        raise NeighborCollectionContractError(f"invalid_neighbor_scenario:{scenario_id}")
    if "cdp" in normalized_command:
        raise NeighborCollectionContractError("neighbor_protocol_forbidden:cdp")
    if normalized_platform not in LLDP_COMMAND_WHITELIST:
        raise NeighborCollectionContractError(f"unsupported_platform:{normalized_platform or 'missing'}")
    if normalized_command not in LLDP_COMMAND_WHITELIST[normalized_platform]:
        raise NeighborCollectionContractError(f"command_not_allowlisted:{normalized_platform}:{normalized_command}")
    return normalized_command


def classify_lldp_status(*, raw_output: str = "", parsed_count: int | None = None,
                         error: BaseException | None = None, supported: bool = True) -> str:
    """Map transport/parser evidence to a stable API/UI status."""
    if not supported:
        return "unsupported_platform"
    message = str(error or "").lower()
    if error:
        return "timeout" if "timeout" in message or "timed out" in message else "command_failed"
    lowered = str(raw_output or "").lower()
    if "lldp" in lowered and ("not enabled" in lowered or "disabled" in lowered):
        return "lldp_disabled"
    if parsed_count is not None and parsed_count > 0:
        return "success"
    return "parse_failed" if str(raw_output or "").strip() else "no_neighbors"


def normalize_neighbor_record(record: dict[str, Any], *, protocol: str = "lldp") -> dict[str, Any]:
    """Return the common Playbook/TextFSM neighbor object shape."""
    if str(protocol or "lldp").strip().lower() != "lldp":
        raise NeighborCollectionContractError(f"neighbor_protocol_forbidden:{protocol}")

    def first(*keys: str) -> str:
        folded = {str(key).lower(): value for key, value in record.items()}
        for key in keys:
            value = folded.get(key.lower())
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    capabilities = first("neighbor_capabilities", "capabilities", "capability")
    if isinstance(capabilities, str):
        capabilities = [item for item in re.split(r"[,;\s]+", capabilities) if item]
    if not isinstance(capabilities, list):
        capabilities = []
    return {
        "local_interface": first("local_interface", "local_port", "local_port_id", "interface", "src_port"),
        "neighbor_name": first("neighbor_name", "neighbor", "neighbor_id", "device_id", "remote_system_name", "system_name"),
        "neighbor_interface": first("neighbor_interface", "neighbor_port_id", "remote_port", "port_id", "remote_interface", "port"),
        "neighbor_management_ip": first("neighbor_management_ip", "mgmt_address", "management_address", "mgmt_ip", "neighbor_ip", "remote_management_address", "ip_address"),
        "neighbor_platform": first("neighbor_platform", "platform", "system_description", "description"),
        "neighbor_capabilities": capabilities,
        "protocol": "lldp",
    }
