from __future__ import annotations

import re

from core.interface_utils import normalize_interface_name
from domain.models import Device, Interface, Neighbor
from services.normalizers.base import BaseNormalizer
from services.normalizers.common import (
    clean_ip,
    first_match,
    interface_type,
    neighbor_from_record,
    parse_speed_bps,
    record_value,
    regex_lldp_neighbors,
    status_value,
    textfsm_records,
)


class RaisecomNormalizer(BaseNormalizer):
    """Normalize Raisecom ROS output without applying Cisco grammar."""

    _PLATFORMS = ("raisecom_ros", "raisecom")

    def parse_device_info(self, device_id: str, raw_version: str) -> Device:
        records = textfsm_records(self._PLATFORMS, "show version", raw_version)
        record = records[0] if records else {}
        hostname = record_value(record, "hostname") or first_match(
            raw_version, r"^([\w.-]+)#\s*(?:show|display)\s+version"
        )
        model = record_value(record, "model", "product_name") or first_match(
            raw_version, r"^Product\s+Name\s*:\s*([^\r\n]+)"
        )
        version = record_value(record, "version", "software_version") or first_match(
            raw_version,
            r"^Software\s+Version\s*:\s*([^\s(]+)",
            r"^ROS\s+Version\s*:\s*([^\r\n]+)",
        )
        serial = record_value(record, "serial", "serial_number") or first_match(
            raw_version, r"^Serial\s+number\s*:\s*([^\r\n]*\S[^\r\n]*)"
        )
        uptime = record_value(record, "uptime") or first_match(
            raw_version, r"^System\s+uptime\s*:\s*([^\r\n]+)"
        )
        return Device(
            id=device_id,
            hostname=hostname or device_id,
            ip_address="",
            vendor="Raisecom",
            platform="raisecom_ros",
            sn=serial,
            model=model.strip(),
            version=version.strip(),
            uptime=uptime,
        )

    def parse_interfaces(
        self, device_id: str, raw_interfaces: str, raw_ip_brief: str = ""
    ) -> list[Interface]:
        interfaces: dict[str, Interface] = {}

        # ROS variants use both whitespace-aligned and space-aligned tables.
        # Only accept rows with an explicit up/down token so headings and
        # counters cannot become phantom interfaces.
        for line in raw_ip_brief.splitlines():
            columns = [column.strip() for column in re.split(r"\s{2,}|\s+", line.strip()) if column.strip()]
            if len(columns) < 2 or columns[0].lower() in {
                "interface", "interface-name", "port", "name", "ip-address",
            }:
                continue
            states = [index for index, value in enumerate(columns) if value.lower() in {"up", "down"}]
            if not states:
                continue
            oper_index = states[-1]
            admin_index = states[-2] if len(states) > 1 else oper_index
            name = columns[0]
            ip_value = clean_ip(columns[1]) if len(columns) > 1 else None
            self._merge_detail(
                interfaces,
                device_id,
                name,
                {
                    "admin_status": columns[admin_index],
                    "oper_status": columns[oper_index],
                    "primary_ip": ip_value or "",
                },
            )

        for line in raw_interfaces.splitlines():
            header = re.match(
                r"^\s*(\S+)\s+is\s+(up|down)(?:,\s*line protocol is\s+(up|down))?",
                line,
                flags=re.IGNORECASE,
            )
            if header:
                self._merge_detail(
                    interfaces,
                    device_id,
                    header.group(1),
                    {"admin_status": header.group(2), "oper_status": header.group(3) or header.group(2)},
                )
                continue

            columns = [column.strip() for column in re.split(r"\s{2,}|\s+", line.strip()) if column.strip()]
            if len(columns) < 2 or columns[0].lower() in {"interface", "port", "name"}:
                continue
            state_index = next(
                (index for index, value in enumerate(columns[1:], start=1) if value.lower() in {"up", "down"}),
                None,
            )
            if state_index is None:
                continue
            speed = next((value for value in columns[state_index + 1:] if re.search(r"(?:[gmkt]?bps|[gmkt]$)", value, re.I)), "")
            self._merge_detail(
                interfaces,
                device_id,
                columns[0],
                {
                    "admin_status": columns[state_index],
                    "oper_status": columns[state_index],
                    "speed": speed,
                    "description": " ".join(columns[state_index + 1:]).strip(),
                },
            )

        return list(interfaces.values())

    def parse_neighbors(self, device_id: str, raw_lldp: str) -> list[Neighbor]:
        records = textfsm_records(self._PLATFORMS, "show lldp remote", raw_lldp)
        parsed = [neighbor for record in records if (neighbor := neighbor_from_record(device_id, record))]
        return parsed or regex_lldp_neighbors(device_id, raw_lldp)

    @staticmethod
    def _merge_detail(interfaces: dict[str, Interface], device_id: str, name: str, record: dict) -> None:
        key = normalize_interface_name(name)
        interface = interfaces.get(key)
        if interface is None:
            interface = Interface(
                device_id=device_id,
                name_raw=name,
                name_display=key,
                interface_type=interface_type(name),
            )
            interfaces[key] = interface

        admin = record_value(record, "admin_status", "link_status", "status")
        oper = record_value(record, "oper_status", "protocol_status", "protocol")
        if admin:
            interface.admin_status = status_value(admin)
        if oper:
            interface.oper_status = status_value(oper)
        primary_ip = record_value(record, "primary_ip", "ip_address")
        if primary_ip:
            interface.primary_ip = clean_ip(primary_ip)
            interface.is_l3 = True
        description = record_value(record, "description")
        if description:
            interface.description = description
        speed = parse_speed_bps(record_value(record, "speed", "bandwidth"))
        if speed:
            interface.speed = speed
        interface.is_l3 = interface.is_l3 or interface.interface_type in {"svi", "loopback"}
