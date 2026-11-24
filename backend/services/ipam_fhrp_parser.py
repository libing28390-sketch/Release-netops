"""Read-only parsers for explicitly supported Cisco IOS and H3C Comware FHRP commands."""

from __future__ import annotations

import ipaddress
import re
from typing import Any


_IOS_PLATFORMS = frozenset(
    {
        "cisco_ios",
        "cisco_iosxe",
        "cisco_xe",
        "cisco_nxos",
        "nxos",
        "ios",
        "iosxe",
    }
)
_HUAWEI_PLATFORMS = frozenset({"huawei", "huawei_vrp", "vrp"})

_COMMANDS = {
    "show standby brief": "hsrp",
    "show hsrp brief": "hsrp",
    "show vrrp brief": "vrrp",
}
_H3C_VRRP_COMMANDS = {
    "display vrrp verbose": 4,
    "display vrrp ipv6 verbose": 6,
}

_HSRP_STATES = frozenset(
    {"active", "standby", "speak", "listen", "init", "initialize", "learn", "unknown"}
)
_VRRP_STATES = frozenset({"master", "backup", "init", "initialize", "inactive"})
_IP_UNAVAILABLE = frozenset({"-", "--", "*", "local", "unknown", "unassigned", "none", "n/a"})
_VRRP_FLAGS = frozenset({"y", "n", "yes", "no", "-"})
_CLI_ERROR = re.compile(
    r"(?:invalid input|unknown command|unrecognized command|incomplete command|"
    r"ambiguous command|command not found|unsupported command|not supported)",
    re.IGNORECASE,
)


def parse_cisco_fhrp_output(command: str, output: str, *, platform: str) -> dict[str, Any]:
    """Parse a supported Cisco IOS HSRP or VRRP brief table.

    Only the two allowlisted commands and known IOS platform keys are accepted.
    The brief output does not expose a virtual MAC, so that field is always
    ``None`` rather than inferred from a group number.
    """

    normalized_platform = str(platform or "").strip().casefold()
    normalized_command = str(command or "").strip().casefold()
    protocol = _COMMANDS.get(normalized_command)
    if normalized_platform not in _IOS_PLATFORMS or protocol is None:
        return {"status": "unsupported", "observations": []}

    text = str(output or "")
    if _CLI_ERROR.search(text):
        return {"status": "unsupported", "observations": []}

    lines = text.splitlines()
    header_index = _find_header(lines, protocol)
    if header_index is None:
        if _is_explicit_empty(text, protocol):
            return {"status": "complete", "observations": []}
        return {"status": "partial", "observations": []}

    observations: list[dict[str, Any]] = []
    partial = any(
        line.strip() and not _is_ignorable_line(line.strip(), normalized_command)
        for line in lines[:header_index]
    )
    for line in lines[header_index + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        if _is_page_marker(stripped):
            partial = True
            continue
        if _is_ignorable_line(stripped, normalized_command):
            continue
        if _is_header(stripped, protocol):
            continue

        observation = (
            _parse_hsrp_row(stripped)
            if protocol == "hsrp"
            else _parse_vrrp_row(stripped)
        )
        if observation is None:
            partial = True
            continue
        observations.append(observation)

    return {"status": "partial" if partial else "complete", "observations": observations}


def parse_h3c_vrrp_output(command: str, output: str, *, platform: str) -> dict[str, Any]:
    """Parse strict Comware 7 verbose IPv4/IPv6 VRRP output.

    A total-router count is required. A count of zero is the only empty-result
    proof; missing counts, truncated groups, or a count/row mismatch stay
    partial so they cannot erase a last-success snapshot.
    """

    normalized_platform = str(platform or "").strip().casefold()
    normalized_command = str(command or "").strip().casefold()
    address_family = _H3C_VRRP_COMMANDS.get(normalized_command)
    if normalized_platform != "h3c_comware" or address_family is None:
        return {"status": "unsupported", "observations": []}

    text = str(output or "")
    if _CLI_ERROR.search(text):
        return {"status": "unsupported", "observations": []}
    empty_message = "vrrp4 is not configured." if address_family == 4 else "vrrp6 is not configured."
    meaningful_lines = [
        line.strip() for line in text.splitlines()
        if line.strip() and not _is_ignorable_line(line.strip(), normalized_command)
    ]
    if meaningful_lines and all(line.casefold() == empty_message for line in meaningful_lines):
        return {"status": "complete", "observations": []}
    title = "ipv4 virtual router information" if address_family == 4 else "ipv6 virtual router information"
    lines = text.splitlines()
    title_index = next(
        (index for index, line in enumerate(lines) if line.strip().rstrip(":").casefold() == title),
        None,
    )
    if title_index is None:
        return {"status": "partial", "observations": []}

    total_count: int | None = None
    partial = any(
        line.strip() and not _is_ignorable_line(line.strip(), normalized_command)
        for line in lines[:title_index]
    ) or any(_is_page_marker(line.strip()) for line in lines)
    groups: list[dict[str, Any]] = []
    current_interface = ""
    interface_pending = False
    current_group: dict[str, Any] | None = None
    capture_virtual_ip_continuation = False

    def finish_group() -> None:
        nonlocal current_group, capture_virtual_ip_continuation
        if current_group is not None:
            groups.append(current_group)
        current_group = None
        capture_virtual_ip_continuation = False

    for line in lines[title_index + 1 :]:
        stripped = line.strip()
        if not stripped or _is_page_marker(stripped) or re.fullmatch(r"[-=+\s]+", stripped):
            continue

        total_match = re.match(r"^Total\s+number\s+of\s+virtual\s+routers\s*:\s*(\d+)\s*$", stripped, re.IGNORECASE)
        if total_match:
            parsed_total = int(total_match.group(1))
            if total_count is not None and total_count != parsed_total:
                partial = True
            total_count = parsed_total
            continue

        interface_match = re.match(r"^Interface\s*:?[ \t]+(.+?)\s*$", stripped, re.IGNORECASE)
        if interface_match:
            finish_group()
            if interface_pending:
                partial = True
            current_interface = interface_match.group(1).strip()
            interface_pending = bool(current_interface)
            if not current_interface:
                partial = True
            continue

        vrid_match = re.match(r"^VRID\s*:\s*(\d+)\b", stripped, re.IGNORECASE)
        if vrid_match:
            finish_group()
            current_group = {
                "group_id": int(vrid_match.group(1)),
                "interface_name": current_interface,
                "priority": None,
                "state": "",
                "master_address": None,
                "virtual_ips": [],
                "virtual_mac": None,
            }
            interface_pending = False
            if not current_interface:
                partial = True
            continue

        if current_group is None:
            continue

        virtual_match = re.search(r"\bVirtual\s+IP\s*:\s*([^ \t]+)?", stripped, re.IGNORECASE)
        if virtual_match:
            capture_virtual_ip_continuation = True
            value = str(virtual_match.group(1) or "").strip()
            if value:
                parsed_ip, parsed_family, valid = _parse_cli_ip(value)
                if not valid or (parsed_family is not None and parsed_family != address_family):
                    partial = True
                elif parsed_ip is not None:
                    current_group["virtual_ips"].append(parsed_ip)
            continue

        master_match = re.search(r"\bMaster\s+IP\s*:\s*([^ \t]+)?", stripped, re.IGNORECASE)
        if master_match:
            capture_virtual_ip_continuation = False
            value = str(master_match.group(1) or "").strip()
            parsed_ip, parsed_family, valid = _parse_cli_ip(value)
            if not valid or (parsed_family is not None and parsed_family != address_family):
                partial = True
            else:
                current_group["master_address"] = parsed_ip
            continue

        mac_match = re.search(r"\bVirtual\s+MAC\s*:\s*([^ \t]+)?", stripped, re.IGNORECASE)
        if mac_match:
            capture_virtual_ip_continuation = False
            current_group["virtual_mac"] = str(mac_match.group(1) or "").strip() or None
            continue

        running_priority_match = re.search(r"\bRunning\s+Pri\s*:\s*(\d+)\b", stripped, re.IGNORECASE)
        config_priority_match = re.search(r"\bConfig\s+Pri\s*:\s*(\d+)\b", stripped, re.IGNORECASE)
        priority_match = running_priority_match or config_priority_match
        if priority_match:
            capture_virtual_ip_continuation = False
            priority = _parse_bounded_int(priority_match.group(1), 0, 255)
            if priority is None:
                partial = True
            elif running_priority_match or current_group["priority"] is None:
                current_group["priority"] = priority
            continue

        state_match = re.search(r"\bState\s*:\s*([a-z-]+)\b", stripped, re.IGNORECASE)
        if state_match:
            capture_virtual_ip_continuation = False
            state = state_match.group(1).casefold()
            if state in _VRRP_STATES and not current_group["state"]:
                current_group["state"] = state
            elif state not in _VRRP_STATES and not current_group["state"]:
                partial = True
            continue

        # Comware prints additional virtual IPs on indented continuation lines.
        if capture_virtual_ip_continuation and re.fullmatch(r"[0-9A-Fa-f:.%]+", stripped):
            parsed_ip, parsed_family, valid = _parse_cli_ip(stripped)
            if not valid or parsed_family != address_family:
                partial = True
            elif parsed_ip is not None:
                current_group["virtual_ips"].append(parsed_ip)
            continue

        capture_virtual_ip_continuation = False

    finish_group()
    if interface_pending:
        partial = True
    if total_count is None or total_count != len(groups):
        partial = True

    observations: list[dict[str, Any]] = []
    for group in groups:
        if not group["interface_name"] or not group["state"]:
            partial = True
            continue
        virtual_ips = list(dict.fromkeys(group["virtual_ips"])) or [None]
        for virtual_ip in virtual_ips:
            observations.append({
                "protocol": "vrrp",
                "group_id": group["group_id"],
                "address_family": address_family,
                "interface_name": group["interface_name"],
                "priority": group["priority"],
                "state": group["state"],
                "master_address": group["master_address"],
                "virtual_ip": virtual_ip,
                "virtual_mac": group["virtual_mac"],
            })

    return {"status": "partial" if partial else "complete", "observations": observations}


def parse_huawei_vrrp_brief_output(command: str, output: str, *, platform: str) -> dict[str, Any]:
    """Parse Huawei VRP / CloudEngine ``display vrrp brief`` output."""
    normalized_platform = str(platform or "").strip().casefold()
    normalized_command = str(command or "").strip().casefold()
    if normalized_platform not in _HUAWEI_PLATFORMS or normalized_command != "display vrrp brief":
        return {"status": "unsupported", "observations": []}
    text = str(output or "")
    if _CLI_ERROR.search(text):
        return {"status": "unsupported", "observations": []}
    if re.search(r"total\s*:\s*0\b|no\s+vrrp", text, re.IGNORECASE):
        return {"status": "complete", "observations": []}

    observations: list[dict[str, Any]] = []
    # Typical Huawei display vrrp brief row:
    # Vlanif100      100   Master   10.10.10.254     Vlanif100  ...
    row_re = re.compile(
        r"^\s*(\S+)\s+(\d+)\s+(Master|Backup|Initialize|Init|Inactive)\s+([0-9a-fA-F:.]+)",
        re.IGNORECASE,
    )
    saw_header = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"\bVRID\b.*\bState\b", stripped, re.IGNORECASE):
            saw_header = True
            continue
        m = row_re.match(stripped)
        if m:
            if_name = m.group(1)
            vrid = int(m.group(2))
            state = m.group(3).lower()
            if state == "init":
                state = "initialize"
            vip_raw = m.group(4)
            try:
                parsed_ip = ipaddress.ip_address(vip_raw)
            except ValueError:
                continue
            observations.append({
                "protocol": "vrrp",
                "group_id": vrid,
                "address_family": parsed_ip.version,
                "interface_name": if_name,
                "priority": None,
                "state": state,
                "master_address": None,
                "virtual_ip": parsed_ip.compressed,
                "virtual_mac": None,
            })
    if not saw_header and not observations:
        return {"status": "partial", "observations": []}
    return {"status": "complete", "observations": observations}


def parse_fhrp_output(command: str, output: str, *, platform: str) -> dict[str, Any]:
    """Dispatch only explicitly supported read-only FHRP query commands."""

    normalized_platform = str(platform or "").strip().casefold()
    if normalized_platform in _IOS_PLATFORMS:
        return parse_cisco_fhrp_output(command, output, platform=normalized_platform)
    if normalized_platform in _HUAWEI_PLATFORMS:
        return parse_huawei_vrrp_brief_output(command, output, platform=normalized_platform)
    return parse_h3c_vrrp_output(command, output, platform=normalized_platform)


def _header_tokens(line: str) -> list[str]:
    return re.findall(r"[a-z0-9-]+", line.casefold())


def _is_header(line: str, protocol: str) -> bool:
    tokens = _header_tokens(line)
    if protocol == "hsrp":
        if len(tokens) in {9, 11} and tokens[3] == "p":
            tokens.pop(3)
        if len(tokens) not in {8, 10}:
            return False
        tokens[2] = "priority" if tokens[2] in {"pri", "prio", "priority"} else tokens[2]
        detailed_columns = tokens == [
            "interface",
            "grp",
            "priority",
            "state",
            "active",
            "addr",
            "standby",
            "addr",
            "group",
            "addr",
        ]
        documented_short_columns = tokens == [
            "interface",
            "grp",
            "priority",
            "state",
            "active",
            "standby",
            "virtual",
            "ip",
        ]
        return detailed_columns or documented_short_columns

    return tokens == [
        "interface",
        "grp",
        "a-f",
        "pri",
        "time",
        "own",
        "pre",
        "state",
        "master",
        "addr",
        "group",
        "addr",
    ]


def _find_header(lines: list[str], protocol: str) -> int | None:
    return next((index for index, line in enumerate(lines) if _is_header(line, protocol)), None)


def _parse_hsrp_row(line: str) -> dict[str, Any] | None:
    fields = line.split()
    if len(fields) not in {7, 8}:
        return None

    if fields[3].casefold() in _HSRP_STATES:
        state_index = 3
    elif (
        len(fields) == 8
        and fields[3].casefold() in {"p", "-"}
        and fields[4].casefold() in _HSRP_STATES
    ):
        state_index = 4
    else:
        return None

    if state_index == 3 and len(fields) != 7:
        return None
    if state_index == 4 and len(fields) != 8:
        return None

    group_id = _parse_nonnegative_int(fields[1])
    priority = _parse_bounded_int(fields[2], 0, 255)
    if group_id is None or priority is None:
        return None

    active, active_family, active_valid = _parse_cli_ip(fields[state_index + 1])
    standby, standby_family, standby_valid = _parse_cli_ip(fields[state_index + 2])
    virtual_ip, virtual_family, virtual_valid = _parse_cli_ip(fields[state_index + 3])
    if not (active_valid and standby_valid and virtual_valid):
        return None
    if virtual_family is not None and any(
        family is not None and family != virtual_family
        for family in (active_family, standby_family)
    ):
        return None

    return {
        "protocol": "hsrp",
        "group_id": group_id,
        "address_family": virtual_family,
        "interface_name": fields[0],
        "priority": priority,
        "state": fields[state_index].casefold(),
        "master_address": active,
        "virtual_ip": virtual_ip,
        "virtual_mac": None,
    }


def _parse_vrrp_row(line: str) -> dict[str, Any] | None:
    fields = line.split()
    if len(fields) != 10:
        return None

    family_token = fields[2].casefold()
    if family_token not in {"ipv4", "ipv6"}:
        return None
    address_family = 4 if family_token == "ipv4" else 6
    group_id = _parse_nonnegative_int(fields[1])
    priority = _parse_bounded_int(fields[3], 0, 255)
    if group_id is None or priority is None:
        return None
    if not re.fullmatch(r"\d+(?:\.\d+)?", fields[4]):
        return None
    if fields[5].casefold() not in _VRRP_FLAGS or fields[6].casefold() not in _VRRP_FLAGS:
        return None

    state = fields[7].casefold()
    if state not in _VRRP_STATES:
        return None
    master, master_family, master_valid = _parse_cli_ip(fields[8])
    virtual_ip, virtual_family, virtual_valid = _parse_cli_ip(fields[9])
    if not (master_valid and virtual_valid):
        return None
    if any(
        family is not None and family != address_family
        for family in (master_family, virtual_family)
    ):
        return None

    return {
        "protocol": "vrrp",
        "group_id": group_id,
        "address_family": address_family,
        "interface_name": fields[0],
        "priority": priority,
        "state": state,
        "master_address": master,
        "virtual_ip": virtual_ip,
        "virtual_mac": None,
    }


def _parse_cli_ip(value: str) -> tuple[str | None, int | None, bool]:
    if value.casefold() in _IP_UNAVAILABLE:
        return None, None, True
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        return None, None, False
    return parsed.compressed, parsed.version, True


def _parse_nonnegative_int(value: str) -> int | None:
    if not re.fullmatch(r"\d+", value):
        return None
    return int(value)


def _parse_bounded_int(value: str, minimum: int, maximum: int) -> int | None:
    parsed = _parse_nonnegative_int(value)
    if parsed is None or not minimum <= parsed <= maximum:
        return None
    return parsed


def _is_explicit_empty(output: str, protocol: str) -> bool:
    protocol_name = "hsrp" if protocol == "hsrp" else "vrrp"
    pattern = re.compile(
        rf"(?:no\s+(?:{protocol_name}|standby)\s+groups?(?:\s+configured|\s+found)?|"
        rf"no\s+entries\s+(?:found|displayed)|total\s+groups?\s*[:=]\s*0)",
        re.IGNORECASE,
    )
    return bool(pattern.search(output))


def _is_page_marker(line: str) -> bool:
    return line.casefold().startswith("--more--") or line.casefold().startswith("<--- more")


def _is_ignorable_line(line: str, command: str) -> bool:
    folded = line.casefold()
    if folded == command or folded.endswith(f"#{command}") or folded.endswith(f">{command}"):
        return True
    if re.fullmatch(rf"[\w./:-]+[>#]\s*(?:{re.escape(command)})?", folded):
        return True
    if re.fullmatch(r"[-=+\s]+", line):
        return True
    if re.match(r"^(?:total\s+(?:groups?|entries?)|number\s+of\s+groups)\b", folded):
        return True
    return False
