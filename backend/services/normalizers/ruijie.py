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


class RuijieNormalizer(BaseNormalizer):
    _PLATFORMS = ("ruijie_rgos", "ruijie_os")

    def parse_device_info(self, device_id: str, raw_version: str) -> Device:
        records = textfsm_records(self._PLATFORMS, "show version", raw_version)
        record = records[0] if records else {}
        hostname = record_value(record, "hostname") or first_match(raw_version, r"^([\w.-]+)#\s*show version")
        model = record_value(record, "model", "hardware") or first_match(
            raw_version,
            r"System description\s*:\s*.*?\(([^()]+)\)\s+by\s+Ruijie",
            r"Product\s+(?:name|model)\s*:\s*(\S+)",
        )
        version = record_value(record, "version", "software_version") or first_match(
            raw_version, r"System software version\s*:\s*([^\r\n]+)"
        )
        serial = record_value(record, "serial", "serial_number") or first_match(
            raw_version, r"(?:System\s+)?Serial\s+(?:Number|number)\s*:\s*(\S+)"
        )
        uptime = record_value(record, "uptime") or first_match(raw_version, r"System uptime\s*:\s*([^\r\n]+)")
        return Device(
            id=device_id,
            hostname=hostname or device_id,
            ip_address="",
            vendor="Ruijie",
            platform="ruijie_rgos",
            sn=serial,
            model=model,
            version=version,
            uptime=uptime,
        )

    def parse_interfaces(self, device_id: str, raw_interfaces: str, raw_ip_brief: str = "") -> list[Interface]:
        interfaces: dict[str, Interface] = {}
        for line in raw_ip_brief.splitlines():
            columns = [column.strip() for column in re.split(r"\s{2,}", line.strip()) if column.strip()]
            if len(columns) < 4 or columns[0].lower() == "interface":
                continue
            if columns[-1].lower() not in {"up", "down"} or columns[-2].lower() not in {"up", "down"}:
                continue
            name, ip_value = columns[0], clean_ip(columns[1])
            key = normalize_interface_name(name)
            interfaces[key] = Interface(
                device_id=device_id,
                name_raw=name,
                name_display=key,
                interface_type=interface_type(name),
                admin_status=status_value(columns[-2]),
                oper_status=status_value(columns[-1]),
                primary_ip=ip_value,
                is_l3=ip_value is not None or interface_type(name) in {"svi", "loopback"},
            )

        records = textfsm_records(self._PLATFORMS, "show interfaces", raw_interfaces)
        for record in records:
            name = record_value(record, "interface", "port")
            if name:
                self._merge_detail(interfaces, device_id, name, record)

        header = re.compile(r"(?m)^(.+?)\s+is\s+(\S+),\s+line protocol is\s+(\S+)")
        matches = list(header.finditer(raw_interfaces))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_interfaces)
            block = raw_interfaces[match.end():end]
            record = {
                "admin_status": match.group(2),
                "oper_status": match.group(3),
                "description": first_match(block, r"^\s*Description:\s*([^\r\n]+)"),
                "mtu": first_match(block, r"\bMTU\s+(\d+)"),
                "mac_address": first_match(block, r"address is\s+([0-9a-f.:-]+)"),
                "speed": first_match(block, r"(?:Full|Half)-duplex,\s*([^,\r\n]+)"),
            }
            self._merge_detail(interfaces, device_id, match.group(1).strip(), record)
        return list(interfaces.values())

    def parse_neighbors(self, device_id: str, raw_lldp: str) -> list[Neighbor]:
        records = textfsm_records(self._PLATFORMS, "show lldp neighbors detail", raw_lldp)
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
        description = record_value(record, "description")
        if description:
            interface.description = description
        mtu = record_value(record, "mtu")
        if mtu and re.search(r"\d+", mtu):
            interface.mtu = int(re.search(r"\d+", mtu).group())
        mac = record_value(record, "mac_address", "hardware_address")
        if mac:
            interface.mac = mac
        speed = parse_speed_bps(record_value(record, "speed", "bandwidth"))
        if speed:
            interface.speed = speed
